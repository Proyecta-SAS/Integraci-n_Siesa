from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import MappingConfig, RuntimeConfig
from .flow import FlowDecision, decide_flow
from .mapper import build_payload
from .models import PaymentRow
from .siesa_hub import SiesaHubClient
from .source import iter_payments
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


class SendCooldownError(PermissionError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        minutes = max(1, (retry_after_seconds + 59) // 60)
        super().__init__(f"envio bloqueado por cooldown: espere {minutes} minutos")


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
    ) -> None:
        self.runtime = runtime
        self.mapping = mapping
        self.validator = PaymentValidator(mapping.required_transaction_type)
        self.state = SyncState(runtime.state_file)
        self.log = JsonlAuditLog(runtime.log_file)
        self.client = client

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

    def sync(self, dry_run: bool | None = None) -> SyncResult:
        is_dry_run = self.runtime.dry_run if dry_run is None else dry_run
        if not is_dry_run and not self.runtime.allow_send:
            raise PermissionError("envio bloqueado: configure SIESA_ALLOW_SEND=true para crear recibos")
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

        for payment in iter_payments(self.runtime.input_csv, self.runtime.sheets_csv_url, self.mapping):
            counters["processed"] += 1
            flow = decide_flow(payment)
            key = payment.idempotency_key()
            issues = self.validator.validate(payment)
            if issues:
                counters["invalid"] += 1
                self.log.write(_event("invalid", payment, flow=flow, issues=[issue.__dict__ for issue in issues]))
                continue
            if self.state.contains(key):
                counters["skipped_duplicates"] += 1
                self.log.write(_event("duplicate", payment, flow=flow))
                continue

            payload = build_payload(payment, self.mapping)
            if is_dry_run:
                counters["dry_run"] += 1
                self.log.write(_event("dry_run", payment, payload=payload, flow=flow))
                continue

            response = self._client().register_cash_receipt(self.mapping.connector_id, payload, key)
            if response.ok:
                counters["sent"] += 1
                self.state.add(key)
                self.log.write(_event("sent", payment, payload=payload, flow=flow, siesa_response=response.data))
            else:
                counters["failed"] += 1
                self.log.write(
                    _event(
                        "failed",
                        payment,
                        payload=payload,
                        flow=flow,
                        siesa_status_code=response.status_code,
                        siesa_response=response.data,
                    )
                )

        self.state.save()
        return SyncResult(**counters)


def format_issues(issues: list[ValidationIssue]) -> str:
    return "; ".join(f"fila {issue.row} {issue.field}: {issue.message}" for issue in issues)
