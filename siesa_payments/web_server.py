from __future__ import annotations

import argparse
import json
import mimetypes
import os
from dataclasses import asdict
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import MappingConfig, RuntimeConfig, load_env_file
from .flow import decide_flow
from .source import iter_payments
from .sync import PaymentSyncService, SendCooldownError
from .validation import PaymentValidator


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
REQUIRED_SEND_ENV = (
    "SIESA_F_CIA",
    "SIESA_ID_CO",
    "SIESA_ID_CAJA",
    "SIESA_ID_COBRADOR",
)
CROSS_FIELD_ENV = (
    ("cross_document_type", "SIESA_TIPO_DOCTO_CRUCE"),
    ("cross_document_number", "SIESA_CONSEC_DOCTO_CRUCE"),
    ("cross_installment", "SIESA_NRO_CUOTA_CRUCE"),
    ("cross_co", "SIESA_ID_CO_CRUCE"),
    ("cross_un", "SIESA_ID_UN_CRUCE"),
    ("cross_branch", "SIESA_SUCURSAL_DOCTO_CRUCE"),
    ("cross_auxiliary", "SIESA_AUXILIAR_DOCTO_CRUCE"),
)


def _runtime_for_request(dry_run: bool) -> RuntimeConfig:
    load_env_file(ROOT / ".env", override=True)
    runtime = RuntimeConfig.from_env()
    return RuntimeConfig(
        environment=runtime.environment,
        dry_run=dry_run,
        allow_send=runtime.allow_send,
        send_cooldown_minutes=runtime.send_cooldown_minutes,
        input_csv=runtime.input_csv,
        sheets_csv_url=runtime.sheets_csv_url,
        mapping_file=runtime.mapping_file,
        state_file=runtime.state_file,
        log_file=runtime.log_file,
        siesa_connector_url=runtime.siesa_connector_url,
        hub_base_url=runtime.hub_base_url,
        hub_connector_id=runtime.hub_connector_id,
        hub_operation=runtime.hub_operation,
        siesa_connikey=runtime.siesa_connikey,
        siesa_connitoken=runtime.siesa_connitoken,
        siesa_client_id=runtime.siesa_client_id,
        siesa_client_secret=runtime.siesa_client_secret,
        siesa_id_compania=runtime.siesa_id_compania,
        siesa_id_ecosistema=runtime.siesa_id_ecosistema,
        siesa_id_documento=runtime.siesa_id_documento,
        siesa_nombre_documento=runtime.siesa_nombre_documento,
        hub_execute_path=runtime.hub_execute_path,
    )


def _redacted_runtime(runtime: RuntimeConfig) -> dict[str, Any]:
    missing_send_env = [name for name in REQUIRED_SEND_ENV if not os.getenv(name)]
    application_mode = _receipt_application_mode()
    missing_cross_env = (
        []
        if _uses_other_income_mode()
        else [env_name for _field_name, env_name in CROSS_FIELD_ENV if not os.getenv(env_name)]
    )
    cooldown = PaymentSyncService(runtime, MappingConfig.load(runtime.mapping_file)).send_cooldown_status()
    return {
        "environment": runtime.environment,
        "application_mode": application_mode,
        "dry_run": runtime.dry_run,
        "allow_send": runtime.allow_send,
        "send_cooldown_minutes": runtime.send_cooldown_minutes,
        "source": "input_csv" if runtime.input_csv else "google_sheets_csv" if runtime.sheets_csv_url else "missing",
        "input_csv": runtime.input_csv,
        "sheets_csv_url_configured": bool(runtime.sheets_csv_url),
        "mapping_file": str(runtime.mapping_file),
        "hub_base_url": runtime.hub_base_url,
        "connector_url_configured": bool(runtime.siesa_connector_url),
        "connector_id": runtime.hub_connector_id,
        "operation": runtime.hub_operation,
        "id_compania_configured": bool(runtime.siesa_id_compania),
        "id_ecosistema_configured": bool(runtime.siesa_id_ecosistema),
        "connikey_configured": bool(runtime.siesa_connikey),
        "connitoken_configured": bool(runtime.siesa_connitoken),
        "client_id_configured": bool(runtime.siesa_client_id),
        "client_secret_configured": bool(runtime.siesa_client_secret),
        "missing_send_env": missing_send_env,
        "cross_fallback_configured": not missing_cross_env,
        "missing_cross_env": missing_cross_env,
        "ready_to_send": bool(
            runtime.siesa_connector_url
            and runtime.siesa_connikey
            and runtime.siesa_connitoken
            and runtime.siesa_id_compania
            and not missing_send_env
        ),
        "send_unlocked": bool(runtime.allow_send),
        "cooldown": cooldown,
        "can_send_now": bool(runtime.allow_send and not cooldown["cooldown_active"]),
    }


def _receipt_application_mode() -> str:
    value = os.getenv("SIESA_RECIBO_FLUJO") or os.getenv("SIESA_RECEIPT_MODE") or "cartera"
    return value.strip().lower().replace(" ", "_")


def _uses_other_income_mode() -> bool:
    return _receipt_application_mode() in {
        "otros_ingresos",
        "otro_ingreso",
        "anticipo",
        "anticipo_por_identificar",
    }


def _cross_status(payment: Any) -> tuple[bool, str]:
    if _uses_other_income_mode():
        return True, "otros_ingresos"

    sheet_count = 0
    env_count = 0
    for field_name, env_name in CROSS_FIELD_ENV:
        if getattr(payment, field_name):
            sheet_count += 1
        elif os.getenv(env_name):
            env_count += 1
        else:
            return False, "missing"
    if sheet_count == len(CROSS_FIELD_ENV):
        return True, "sheet"
    if env_count == len(CROSS_FIELD_ENV):
        return True, "env"
    return True, "mixed"


def _siesa_cross_document(payment: Any) -> str:
    if _uses_other_income_mode():
        auxiliary = os.getenv("SIESA_AUXILIAR_OTRO_ING", "28050505")
        return f"Otro ingreso {auxiliary}"

    document_type = payment.cross_document_type
    number = payment.cross_document_number
    installment = payment.cross_installment
    if not number:
        return payment.cross_document
    return "-".join(part for part in [document_type, number, installment] if part)


def _siesa_cross_auxiliary(payment: Any) -> str:
    if _uses_other_income_mode():
        return os.getenv("SIESA_AUXILIAR_OTRO_ING", "28050505")

    return payment.cross_auxiliary or os.getenv("SIESA_AUXILIAR_DOCTO_CRUCE", "")


def inspect_rows(limit: int = 25) -> dict[str, Any]:
    runtime = _runtime_for_request(dry_run=True)
    mapping = MappingConfig.load(runtime.mapping_file)
    validator = PaymentValidator(mapping.required_transaction_type)
    rows = []
    for payment in iter_payments(runtime.input_csv, runtime.sheets_csv_url, mapping):
        issues = validator.validate(payment)
        flow = decide_flow(payment)
        flow_key = "otros_ingresos_28050505" if _uses_other_income_mode() else flow.key
        cross_ready, cross_source = _cross_status(payment)
        row_issues = [asdict(issue) for issue in issues]
        if not cross_ready:
            row_issues.append(
                {
                    "row": payment.source_row,
                    "field": "cross_document",
                    "message": "faltan datos del documento aplicado",
                }
            )
        rows.append(
            {
                "source_row": payment.source_row,
                "flow": flow_key,
                "identity_number": payment.identity_number,
                "cross_document": _siesa_cross_document(payment),
                "sheet_cross_document": payment.cross_document,
                "cross_auxiliary": _siesa_cross_auxiliary(payment),
                "cross_ready": cross_ready,
                "cross_source": cross_source,
                "customer": " ".join(part for part in [payment.first_name, payment.last_name] if part).strip()
                or payment.contact,
                "payment_date": payment.payment_date.isoformat(),
                "method": payment.payment_method,
                "amount": str(payment.amount),
                "valid": not issues,
                "ready": not issues and cross_ready,
                "issues": row_issues,
            }
        )
        if len(rows) >= limit:
            break
    return {"runtime": _redacted_runtime(runtime), "count": len(rows), "rows": rows}


def preflight(limit: int = 100) -> dict[str, Any]:
    inspected = inspect_rows(limit=limit)
    rows = inspected["rows"]
    total_amount = Decimal("0")
    ready_rows = []
    invalid_rows = []
    missing_cross_rows = []
    for row in rows:
        if row["ready"]:
            ready_rows.append(row["source_row"])
            total_amount += Decimal(row["amount"])
        else:
            invalid_rows.append(row["source_row"])
        if not row["cross_ready"]:
            missing_cross_rows.append(row["source_row"])

    runtime = inspected["runtime"]
    return {
        **inspected,
        "preflight": {
            "ready": bool(runtime["ready_to_send"] and rows and not invalid_rows),
            "send_unlocked": runtime["send_unlocked"],
            "rows_checked": len(rows),
            "ready_rows": len(ready_rows),
            "invalid_rows": invalid_rows,
            "missing_cross_rows": missing_cross_rows,
            "total_ready_amount": str(total_amount),
            "next_step": (
                "activar SIESA_ALLOW_SEND=true solo durante la ventana controlada"
                if runtime["ready_to_send"] and rows and not invalid_rows and not runtime["send_unlocked"]
                else "corregir configuracion o filas antes de enviar"
            ),
        },
    }


def _audit_events(limit: int = 25, event_type: str | None = None) -> list[dict[str, Any]]:
    runtime = _runtime_for_request(dry_run=True)
    path = runtime.log_file
    if not path.exists():
        return []

    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = event.get("status")
        if event_type and status != event_type:
            continue
        events.append(
            {
                "status": status,
                "source_row": event.get("source_row"),
                "identity_number": event.get("identity_number"),
                "amount": event.get("amount"),
                "payment_date": event.get("payment_date"),
                "siesa_status_code": event.get("siesa_status_code"),
                "siesa_response": event.get("siesa_response"),
            }
        )
    return events[-limit:]


def run_sync(send: bool) -> dict[str, Any]:
    runtime = _runtime_for_request(dry_run=not send)
    if send and not runtime.allow_send:
        raise PermissionError("envio bloqueado: configure SIESA_ALLOW_SEND=true para crear recibos")
    mapping = MappingConfig.load(runtime.mapping_file)
    result = PaymentSyncService(runtime, mapping).sync(dry_run=not send)
    return {
        "runtime": _redacted_runtime(runtime),
        "mode": "send" if send else "dry_run",
        "result": asdict(result),
    }


class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                self._json({"ok": True, "service": "activadores-siesa"})
                return
            if parsed.path == "/api/status":
                self._json({"ok": True, "runtime": _redacted_runtime(_runtime_for_request(dry_run=True))})
                return
            if parsed.path == "/api/payments":
                params = parse_qs(parsed.query)
                limit = int(params.get("limit", ["25"])[0])
                self._json({"ok": True, **inspect_rows(limit=limit)})
                return
            if parsed.path == "/api/preflight":
                params = parse_qs(parsed.query)
                limit = int(params.get("limit", ["100"])[0])
                self._json({"ok": True, **preflight(limit=limit)})
                return
            if parsed.path == "/api/audit":
                params = parse_qs(parsed.query)
                limit = int(params.get("limit", ["25"])[0])
                event_type = params.get("event", [None])[0]
                self._json({"ok": True, "events": _audit_events(limit=limit, event_type=event_type)})
                return
            self._static(parsed.path)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/sync/dry-run":
                self._json({"ok": True, **run_sync(send=False)})
                return
            if parsed.path == "/api/sync/send":
                self._json({"ok": True, **run_sync(send=True)})
                return
            self._json({"ok": False, "error": "endpoint no encontrado"}, status=HTTPStatus.NOT_FOUND)
        except SendCooldownError as exc:
            self._json(
                {
                    "ok": False,
                    "error": str(exc),
                    "retry_after_seconds": exc.retry_after_seconds,
                },
                status=HTTPStatus.TOO_MANY_REQUESTS,
            )
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT not in target.parents and target != WEB_ROOT:
            self.send_error(HTTPStatus.FORBIDDEN.value)
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Servidor local para la visual de Activadores Siesa.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "4182")))
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Activadores Siesa: http://{args.host}:{args.port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
