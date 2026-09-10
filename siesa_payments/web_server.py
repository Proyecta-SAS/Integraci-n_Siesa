from __future__ import annotations

import argparse
import json
import mimetypes
import os
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import MappingConfig, RuntimeConfig, load_env_file
from .flow import decide_flow
from .source import iter_payments
from .sync import PaymentSyncService
from .validation import PaymentValidator


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
REQUIRED_SEND_ENV = (
    "SIESA_F_CIA",
    "SIESA_ID_CO",
    "SIESA_ID_CAJA",
    "SIESA_TIPO_DOCTO_CRUCE",
    "SIESA_CONSEC_DOCTO_CRUCE",
)


def _runtime_for_request(dry_run: bool) -> RuntimeConfig:
    load_env_file(ROOT / ".env", override=True)
    runtime = RuntimeConfig.from_env()
    return RuntimeConfig(
        environment=runtime.environment,
        dry_run=dry_run,
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
    return {
        "environment": runtime.environment,
        "dry_run": runtime.dry_run,
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
        "ready_to_send": bool(
            runtime.siesa_connector_url
            and runtime.siesa_connikey
            and runtime.siesa_connitoken
            and runtime.siesa_id_compania
            and not missing_send_env
        ),
    }


def inspect_rows(limit: int = 25) -> dict[str, Any]:
    runtime = _runtime_for_request(dry_run=True)
    mapping = MappingConfig.load(runtime.mapping_file)
    validator = PaymentValidator(mapping.required_transaction_type)
    rows = []
    for payment in iter_payments(runtime.input_csv, runtime.sheets_csv_url, mapping):
        issues = validator.validate(payment)
        flow = decide_flow(payment)
        rows.append(
            {
                "source_row": payment.source_row,
                "flow": flow.key,
                "identity_number": payment.identity_number,
                "customer": " ".join(part for part in [payment.first_name, payment.last_name] if part).strip()
                or payment.contact,
                "payment_date": payment.payment_date.isoformat(),
                "method": payment.payment_method,
                "amount": str(payment.amount),
                "valid": not issues,
                "issues": [asdict(issue) for issue in issues],
            }
        )
        if len(rows) >= limit:
            break
    return {"runtime": _redacted_runtime(runtime), "count": len(rows), "rows": rows}


def run_sync(send: bool) -> dict[str, Any]:
    runtime = _runtime_for_request(dry_run=not send)
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
            if parsed.path == "/api/status":
                self._json({"ok": True, "runtime": _redacted_runtime(_runtime_for_request(dry_run=True))})
                return
            if parsed.path == "/api/payments":
                params = parse_qs(parsed.query)
                limit = int(params.get("limit", ["25"])[0])
                self._json({"ok": True, **inspect_rows(limit=limit)})
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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4182)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    print(f"Activadores Siesa: http://{args.host}:{args.port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
