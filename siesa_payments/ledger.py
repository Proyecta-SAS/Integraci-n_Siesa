"""Recover and index retained evidence, without calling Siesa or altering send state."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .database import Database
from .sheets import receipt_number


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def text(value):
    return "" if value is None else str(value)


def money(value):
    try:
        result = Decimal(str(value))
        return format(result.normalize(), "f") if result.is_finite() else ""
    except (InvalidOperation, ValueError):
        return ""


class Ledger:
    def __init__(self, db: Database):
        self.db = db

    def import_event(self, conn, event, activator, source):
        status = text(event.get("status"))
        event_id = fingerprint(activator + ":" + canonical(event))
        key = text(event.get("idempotency_key")) or "sin-llave:" + event_id
        inserted = conn.execute("""INSERT INTO ledger_events(event_id,activator,payment_key,status,occurred_at,source_path,evidence)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING""",
            (event_id, activator, key, status, text(event.get("timestamp")), source, canonical(event))).rowcount
        if not inserted or status not in {"sent", "failed", "unconfirmed", "duplicate", "possible_duplicate", "state_confirmed", "state_unconfirmed"}:
            return
        payload = event.get("payload") or {}
        section = payload.get("RCyotrosingresos") if isinstance(payload, dict) else None
        receipt = section[0] if isinstance(section, list) and section and isinstance(section[0], dict) else {}
        box_section = payload.get("Caja") if isinstance(payload, dict) else None
        box = box_section[0] if isinstance(box_section, list) and box_section and isinstance(box_section[0], dict) else {}
        note = event.get("note") or receipt.get("F350_NOTAS") or box.get("F358_NOTAS") or ""
        response = event.get("siesa_response") or {}
        number = event.get("receipt") or receipt_number(response)
        mapped = {"sent": "confirmed", "duplicate": "confirmed", "state_confirmed": "confirmed",
                  "failed": "rejected", "unconfirmed": "unconfirmed", "state_unconfirmed": "unconfirmed",
                  "possible_duplicate": "review"}[status]
        values = {
            "id": fingerprint(activator + ":" + key), "activator": activator, "payment_key": key,
            "status": mapped, "identity_number": text(event.get("identity_number") or receipt.get("F350_ID_TERCERO") or box.get("F358_ID_TERCERO")),
            "customer": text(event.get("customer") or event.get("contact")),
            "payment_date": text(event.get("payment_date")), "amount": money(event.get("amount")),
            "note": text(note), "method": text(event.get("method") or box.get("F358_ID_MEDIOS_PAGO")), "receipt_number": text(number),
            "sent_at": text(event.get("sent_at") or event.get("timestamp")) if mapped == "confirmed" else "",
            "last_event_at": text(event.get("timestamp")),
            "possible_duplicate": int(event.get("possible_duplicate") is True or status == "possible_duplicate"),
            "duplicate_of": text(event.get("duplicate_of")),
            "source_environment": text(event.get("environment") or "no_documentado"),
            "confirmation_source": status,
        }
        old = conn.execute("SELECT * FROM ledger_receipts WHERE activator=? AND payment_key=?", (activator, key)).fetchone()
        if old:
            old = dict(old)
            if old["status"] == "confirmed" or (status not in {"state_confirmed", "state_unconfirmed"} and values["last_event_at"] < old["last_event_at"]):
                values["status"] = old["status"]
            for name in ("identity_number", "customer", "payment_date", "amount", "note", "method", "receipt_number", "sent_at", "duplicate_of"):
                values[name] = values[name] or old[name]
            values["possible_duplicate"] = max(values["possible_duplicate"], old["possible_duplicate"])
            values["last_event_at"] = max(values["last_event_at"], old["last_event_at"])
            if values["source_environment"] == "no_documentado":
                values["source_environment"] = old["source_environment"]
            fields = [name for name in values if name not in {"id", "activator", "payment_key"}]
            conn.execute("UPDATE ledger_receipts SET " + ",".join(name + "=?" for name in fields) + " WHERE id=?",
                         tuple(values[name] for name in fields) + (old["id"],))
        else:
            fields = list(values)
            conn.execute("INSERT INTO ledger_receipts(" + ",".join(fields) + ") VALUES(" + ",".join("?" for _ in fields) + ")", tuple(values.values()))

    def query(self, *, activator=None, page=1, search="", status="", duplicate_only=False):
        page = max(1, min(int(page), 100000))
        if status not in {"", "confirmed", "unconfirmed", "rejected", "review"}:
            raise ValueError("Estado no valido")
        # Repeated audit events share a payment key and become one record. A
        # coincidence between DIFFERENT keys is only a candidate, never proof.
        duplicate = """(r.possible_duplicate=1 OR (r.identity_number<>'' AND r.payment_date<>'' AND r.amount<>'' AND EXISTS (
            SELECT 1 FROM ledger_receipts o WHERE o.activator=r.activator AND o.id<>r.id
            AND o.identity_number=r.identity_number AND o.payment_date=r.payment_date
            AND o.amount=r.amount AND o.note=r.note AND (o.method=r.method OR o.method='' OR r.method=''))))"""
        clauses, params = ["1=1"], []
        if activator:
            clauses.append("r.activator=?")
            params.append(activator)
        if search:
            clauses.append("(LOWER(r.identity_number) LIKE ? OR LOWER(r.customer) LIKE ? OR LOWER(r.note) LIKE ? OR LOWER(r.receipt_number) LIKE ?)")
            params += ["%" + search.lower()[:200] + "%"] * 4
        if status:
            clauses.append("r.status=?")
            params.append(status)
        if duplicate_only:
            clauses.append(duplicate)
        where = " AND ".join(clauses)
        scope, scope_args = (" WHERE activator=?", (activator,)) if activator else ("", ())
        duplicate_scope = "r.activator=? AND " if activator else ""
        number_scope = "activator=? AND " if activator else ""
        with self.db.transaction() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM ledger_receipts r WHERE " + where, params).fetchone()["n"]
            rows = conn.execute("SELECT r.*, CASE WHEN " + duplicate + " THEN 1 ELSE 0 END AS duplicate_candidate FROM ledger_receipts r WHERE " + where +
                                " ORDER BY r.payment_date DESC,r.last_event_at DESC,r.id LIMIT ? OFFSET ?", tuple(params) + (50, (page - 1) * 50)).fetchall()
            summary = {row["status"]: row["n"] for row in conn.execute("SELECT status,COUNT(*) AS n FROM ledger_receipts" + scope + " GROUP BY status", scope_args).fetchall()}
            summary["possible_duplicates"] = conn.execute("SELECT COUNT(*) AS n FROM ledger_receipts r WHERE " + duplicate_scope + duplicate, scope_args).fetchone()["n"]
            summary["without_receipt_number"] = conn.execute("SELECT COUNT(*) AS n FROM ledger_receipts WHERE " + number_scope + "status='confirmed' AND receipt_number=''", scope_args).fetchone()["n"]
            issues = conn.execute("SELECT COUNT(*) AS n FROM ledger_import_errors").fetchone()["n"]
            avoided = conn.execute("SELECT COUNT(*) AS n FROM ledger_events WHERE " + number_scope + "status='duplicate'", scope_args).fetchone()["n"]
            sources = [row["activator"] for row in conn.execute("SELECT DISTINCT activator FROM ledger_receipts ORDER BY activator").fetchall()]
        public = []
        for item in rows:
            row = dict(item)
            row.pop("payment_key")
            row["possible_duplicate"] = bool(row.pop("duplicate_candidate"))
            row["duplicate_reason"] = "Advertencia registrada por la integración" if item["possible_duplicate"] else (
                "Coinciden tercero, fecha, valor y nota en registros distintos; requiere verificación" if row["possible_duplicate"] else "")
            public.append(row)
        return {"rows": public, "total": total, "page": page, "page_size": 50, "summary": summary,
                "import_issues": issues, "avoided_resends": avoided, "sources": sources}


class Archive:
    def __init__(self, db: Database, sources, backup_dir: Path):
        self.db, self.sources, self.backup_dir = db, sources, backup_dir
        self.ledger = Ledger(db)
        self.lock = threading.Lock()
        self.last_success = None
        self.error = False
        self.backed_up = set()
        self.stop_event = threading.Event()

    def backup(self, path):
        data = path.read_bytes()
        target = self.backup_dir / (fingerprint(str(path.resolve()) + hashlib.sha256(data).hexdigest()) + path.suffix)
        if not target.exists():
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            # Keep a content-addressed immutable copy before importing it.
            with target.open("xb") as output:
                output.write(data)
        return data

    def refresh(self):
        with self.lock:
            for path, activator, kind in self.sources:
                if not path.is_file():
                    continue
                if kind == "state":
                    if path not in self.backed_up:
                        raw = self.backup(path)
                        self.backed_up.add(path)
                    else:
                        raw = path.read_bytes()
                    state = json.loads(raw.decode("utf-8-sig"))
                    confirmed = set(state.get("processed_keys", [])) | set(state.get("receipts", {}))
                    uncertain = state.get("uncertain_receipts", {})
                    with self.db.transaction() as conn:
                        for key in confirmed | set(uncertain):
                            saved = state.get("receipts", {}).get(key, {}) if key in confirmed else uncertain[key]
                            event = {"status": "state_confirmed" if key in confirmed else "state_unconfirmed",
                                     "idempotency_key": key, "timestamp": saved.get("sent_at") or saved.get("timestamp") or "",
                                     "receipt": saved.get("receipt", ""), "sent_at": saved.get("sent_at", ""),
                                     "siesa_response": saved.get("response", {}), "source_row": saved.get("source_row")}
                            self.ledger.import_event(conn, event, activator, str(path.resolve()))
                    continue
                source = str(path.resolve())
                with self.db.transaction() as conn:
                    previous = conn.execute("SELECT * FROM ledger_sources WHERE source_path=?", (source,)).fetchone()
                    size = path.stat().st_size
                    with path.open("rb") as file:
                        prefix = hashlib.sha256(file.read(256)).hexdigest()
                    offset = previous["byte_offset"] if previous and previous["byte_offset"] <= size and previous["prefix_hash"] == prefix else 0
                    if offset == size:
                        continue
                    if not previous:
                        self.backup(path)
                    with path.open("rb") as file:
                        file.seek(offset)
                        while line := file.readline():
                            if not line.strip():
                                offset = file.tell()
                                continue
                            try:
                                event = json.loads(line.decode("utf-8-sig"))
                                if not isinstance(event, dict):
                                    raise ValueError("registro no es un objeto")
                            except (ValueError, UnicodeError):
                                if not line.endswith(b"\n"):
                                    break  # An in-flight append is read on the next pass.
                                offset = file.tell()
                                conn.execute("INSERT INTO ledger_import_errors(id,source_path,error) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING",
                                             (fingerprint(source + line.hex()), source, "Registro histórico no interpretable; copia original conservada"))
                                continue
                            self.ledger.import_event(conn, event, activator, source)
                            offset = file.tell()
                    conn.execute("INSERT INTO ledger_sources(source_path,byte_offset,prefix_hash,updated_at) VALUES(?,?,?,?) ON CONFLICT(source_path) DO UPDATE SET byte_offset=excluded.byte_offset,prefix_hash=excluded.prefix_hash,updated_at=excluded.updated_at",
                                 (source, offset, prefix, int(time.time())))
            self.last_success = datetime.now(timezone.utc).isoformat()
            self.error = False

    def start(self):
        def run():
            while not self.stop_event.is_set():
                try:
                    self.refresh()
                except Exception:
                    self.error = True  # Original spool files are left untouched for recovery.
                self.stop_event.wait(30)
        threading.Thread(target=run, name="siesa-history-index", daemon=True).start()
