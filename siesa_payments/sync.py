from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import MappingConfig, RuntimeConfig
from .flow import FlowDecision, decide_flow
from .mapper import build_payload
from .models import PaymentRow
from .siesa_hub import SiesaHubClient
from .source import iter_payments
from .sheets import LOADED, NEEDS_CORRECTION, PENDING, SheetStatusWriter, receipt_number, writer_for_runtime
from .state import JsonlAuditLog, SyncState
from .validation import PaymentValidator, ValidationIssue


@dataclass(frozen=True)
class SyncResult:
    processed: int = 0
    sent: int = 0
    dry_run: int = 0
    skipped_duplicates: int = 0
    invalid: int = 0
    failed: int = 0
    failures: tuple[dict[str, Any], ...] = ()
    sheet_updates: int = 0
    sheet_errors: tuple[dict[str, Any], ...] = ()


class SendCooldownError(PermissionError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        minutes = max(1, (retry_after_seconds + 59) // 60)
        super().__init__(f"envio bloqueado por cooldown: espere {minutes} minutos")


def _validate_send_payload(payload: dict[str, Any]) -> None:
    """Prevent a live request when accounting payment settings are incomplete."""
    caja = (payload.get("Caja") or [{}])[0]
    receipt = (payload.get("RCyotrosingresos") or [{}])[0]
    missing: list[str] = []
    if not str(caja.get("F358_ID_MEDIOS_PAGO") or "").strip():
        missing.append("SIESA_ID_MEDIO_PAGO_CONSIGNACION")
    if not str(caja.get("F358_ID_BANCO") or "").strip():
        missing.append("SIESA_ID_BANCO")
    if not str(caja.get("F358_NRO_CUENTA") or "").strip():
        missing.append("SIESA_NRO_CUENTA")
    if not str(caja.get("f358_docto_banco_cg") or "").strip():
        missing.append("SIESA_DOCTO_BANCO_CG")
    if not str(receipt.get("F357_ID_FE") or "").strip():
        missing.append("SIESA_ID_FE")
    if missing:
        raise PermissionError("envio bloqueado: falta parametrizar " + ", ".join(missing))

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(
    status: str,
    payment: PaymentRow,
    payload: dict[str, Any] | None = None,
    flow: FlowDecision | None = None,
    **extra: Any,
) -> dict[str, Any]:
    event = {
        "timestamp": _now(),
        "status": status,
        "source_row": payment.source_row,
        "idempotency_key": payment.idempotency_key(),
        "identity_number": payment.identity_number,
        "amount": str(payment.amount),
        "payment_date": payment.payment_date.isoformat(),
    }
    if flow is not None:
        event["flow"] = flow.key
        event["siesa_target"] = flow.siesa_target
    if payload is not None:
        event["payload"] = payload
    event.update(extra)
    return event


class PaymentSyncService:
    def __init__(
        self,
        runtime: RuntimeConfig,
        mapping: MappingConfig,
        client: SiesaHubClient | None = None,
        sheet_writer: SheetStatusWriter | None = None,
    ) -> None:
        self.runtime = runtime
        self.mapping = mapping
        self.validator = PaymentValidator(mapping.required_transaction_type)
        self.state = SyncState(runtime.state_file)
        self.log = JsonlAuditLog(runtime.log_file)
        self.client = client
        self.sheet_writer = sheet_writer

    def _client(self) -> SiesaHubClient:
        if self.client is not None:
            return self.client
        if not self.runtime.siesa_connikey or not self.runtime.siesa_connitoken or not self.runtime.siesa_id_compania:
            raise RuntimeError("configure SIESA_CONN_KEY, SIESA_CONN_TOKEN y SIESA_ID_COMPANIA para enviar a Siesa")
        return SiesaHubClient(
            base_url=self.runtime.hub_base_url,
            connector_url=self.runtime.siesa_connector_url,
            connikey=self.runtime.siesa_connikey,
            connitoken=self.runtime.siesa_connitoken,
            client_id=self.runtime.siesa_client_id,
            client_secret=self.runtime.siesa_client_secret,
            id_compania=self.runtime.siesa_id_compania,
            id_documento=self.runtime.siesa_id_documento,
            id_ecosistema=self.runtime.siesa_id_ecosistema,
            nombre_documento=self.runtime.siesa_nombre_documento,
            execute_path=self.runtime.hub_execute_path,
        )

    def _last_activation_at(self) -> datetime | None:
        value = self.state.get("last_activation_at")
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def send_cooldown_status(self) -> dict[str, Any]:
        last_activation_at = self._last_activation_at()
        cooldown = timedelta(minutes=max(0, self.runtime.send_cooldown_minutes))
        if last_activation_at is None or cooldown.total_seconds() <= 0:
            return {
                "cooldown_minutes": self.runtime.send_cooldown_minutes,
                "last_activation_at": None,
                "next_activation_at": None,
                "cooldown_active": False,
                "retry_after_seconds": 0,
            }

        next_activation_at = last_activation_at + cooldown
        now = datetime.now(timezone.utc)
        retry_after_seconds = max(0, int((next_activation_at - now).total_seconds()))
        return {
            "cooldown_minutes": self.runtime.send_cooldown_minutes,
            "last_activation_at": last_activation_at.isoformat(),
            "next_activation_at": next_activation_at.isoformat(),
            "cooldown_active": retry_after_seconds > 0,
            "retry_after_seconds": retry_after_seconds,
        }

    def _reserve_send_window(self) -> None:
        status = self.send_cooldown_status()
        if status["cooldown_active"]:
            raise SendCooldownError(int(status["retry_after_seconds"]))
        self.state.set("last_activation_at", _now())
        self.state.save()

    def sync(self, dry_run: bool | None = None, source_rows: set[int] | None = None) -> SyncResult:
        is_dry_run = self.runtime.dry_run if dry_run is None else dry_run
        if not is_dry_run and not self.runtime.allow_send:
            raise PermissionError("envio bloqueado: configure SIESA_ALLOW_SEND=true para crear recibos")
        writer = None if is_dry_run else self.sheet_writer or writer_for_runtime(self.runtime)
        if not is_dry_run:
            self._reserve_send_window()
        counters = {
            "processed": 0,
            "sent": 0,
            "dry_run": 0,
            "skipped_duplicates": 0,
            "invalid": 0,
            "failed": 0,
        }
        failures: list[dict[str, Any]] = []
        sheet_errors: list[dict[str, Any]] = []
        sheet_updates = 0

        def write_status(row: int, cells: tuple[str, ...], status: str, **details: Any) -> bool:
            nonlocal sheet_updates
            if writer is None:
                return True
            try:
                writer.write(row, cells, status, **details)
                sheet_updates += 1
                return True
            except Exception as exc:
                error = {"source_row": row, "status": status, "error": str(exc)}
                sheet_errors.append(error)
                self.log.write({**error, "timestamp": _now(), "status": "sheet_write_failed",
                                "intended_status": status})
                return False

        def invalid_source(row: int, cells: tuple[str, ...], error: str) -> None:
            if source_rows is not None and row not in source_rows:
                return
            counters["processed"] += 1
            counters["invalid"] += 1
            self.log.write({"timestamp": _now(), "status": "invalid", "source_row": row, "error": error})
            write_status(row, cells, NEEDS_CORRECTION, error=error)

        for payment in iter_payments(
            self.runtime.input_csv, self.runtime.sheets_csv_url, self.mapping, on_error=invalid_source,
        ):
            if source_rows is not None and payment.source_row not in source_rows:
                continue
            counters["processed"] += 1
            flow = decide_flow(payment)
            key = payment.idempotency_key()
            # A successful receipt stays successful even if its source cells
            # later fail validation. Repair a missing Sheets result without sending.
            if self.state.contains(key):
                counters["skipped_duplicates"] += 1
                self.log.write(_event("duplicate", payment, flow=flow))
                saved = self.state.get("receipts", {}).get(key, {})
                write_status(payment.source_row, payment.source_cells, LOADED, **saved)
                continue

            uncertain = self.state.get("uncertain_receipts", {}).get(key)
            if uncertain:
                counters["failed"] += 1
                failures.append({"source_row": payment.source_row, "amount": str(payment.amount),
                                 "siesa_status_code": None, "siesa_response": uncertain})
                write_status(payment.source_row, payment.source_cells, PENDING, error=uncertain["error"])
                continue

            issues = self.validator.validate(payment)
            if issues:
                counters["invalid"] += 1
                self.log.write(_event("invalid", payment, flow=flow, issues=[issue.__dict__ for issue in issues]))
                write_status(payment.source_row, payment.source_cells, NEEDS_CORRECTION, error=format_issues(issues))
                continue

            try:
                payload = build_payload(payment, self.mapping)
                if not is_dry_run:
                    _validate_send_payload(payload)
            except (ValueError, RuntimeError, PermissionError) as exc:
                counters["invalid"] += 1
                self.log.write(_event("invalid", payment, flow=flow, error=str(exc)))
                write_status(payment.source_row, payment.source_cells, NEEDS_CORRECTION, error=str(exc))
                continue

            if is_dry_run:
                counters["dry_run"] += 1
                self.log.write(_event("dry_run", payment, payload=payload, flow=flow))
                continue

            try:
                client = self._client()
                client.connection_summary()
            except RuntimeError as exc:
                counters["invalid"] += 1
                self.log.write(_event("invalid", payment, flow=flow, error=str(exc)))
                write_status(payment.source_row, payment.source_cells, NEEDS_CORRECTION, error=str(exc))
                continue

            # Verify that the source row has not moved/changed before sending.
            if not write_status(payment.source_row, payment.source_cells, PENDING):
                counters["failed"] += 1
                failures.append({"source_row": payment.source_row, "amount": str(payment.amount),
                                 "siesa_status_code": None,
                                 "siesa_response": {"error": "no se envio: no se pudo marcar Pendiente en Sheets"}})
                continue

            try:
                response = client.register_cash_receipt(self.mapping.connector_id, payload, key)
            except Exception:
                # A timeout can happen after the ERP commits. Require checking
                # Siesa before another attempt instead of risking a second receipt.
                error = "Respuesta no confirmada; verificar en Siesa antes de reintentar."
                uncertain_receipts = dict(self.state.get("uncertain_receipts", {}))
                uncertain_receipts[key] = {"error": error, "timestamp": _now(), "source_row": payment.source_row}
                self.state.set("uncertain_receipts", uncertain_receipts)
                self.state.save()
                counters["failed"] += 1
                failures.append({"source_row": payment.source_row, "amount": str(payment.amount),
                                 "siesa_status_code": None, "siesa_response": {"error": error}})
                self.log.write(_event("unconfirmed", payment, flow=flow, error=error))
                write_status(payment.source_row, payment.source_cells, PENDING, error=error)
                continue

            if response.ok:
                counters["sent"] += 1
                self.state.add(key)
                details = {"receipt": receipt_number(response.data), "sent_at": _now(), "response": response.data}
                receipts = dict(self.state.get("receipts", {}))
                receipts[key] = details
                self.state.set("receipts", receipts)
                # Persist BEFORE touching Sheets so an unavailable webhook cannot
                # cause a successful receipt to be resent in the next activation.
                self.state.save()
                self.log.write(_event("sent", payment, payload=payload, flow=flow, siesa_response=response.data))
                write_status(payment.source_row, payment.source_cells, LOADED, **details)
            else:
                counters["failed"] += 1
                event = _event(
                    "failed",
                    payment,
                    payload=payload,
                    flow=flow,
                    siesa_status_code=response.status_code,
                    siesa_response=response.data,
                )
                self.log.write(event)
                write_status(
                    payment.source_row, payment.source_cells, NEEDS_CORRECTION,
                    response=response.data,
                    error=f"Siesa HTTP {response.status_code}: " + json.dumps(response.data, ensure_ascii=False),
                )
                failures.append(
                    {
                        "source_row": payment.source_row,
                        "amount": str(payment.amount),
                        "siesa_status_code": response.status_code,
                        "siesa_response": response.data,
                    }
                )

        self.state.save()
        return SyncResult(**counters, failures=tuple(failures), sheet_updates=sheet_updates,
                          sheet_errors=tuple(sheet_errors))


def format_issues(issues: list[ValidationIssue]) -> str:
    return "; ".join(f"fila {issue.row} {issue.field}: {issue.message}" for issue in issues)
