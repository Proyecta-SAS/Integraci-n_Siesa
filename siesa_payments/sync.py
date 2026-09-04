from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import MappingConfig, RuntimeConfig
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(status: str, payment: PaymentRow, payload: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    event = {
        "timestamp": _now(),
        "status": status,
        "source_row": payment.source_row,
        "idempotency_key": payment.idempotency_key(),
        "identity_number": payment.identity_number,
        "amount": str(payment.amount),
        "payment_date": payment.payment_date.isoformat(),
    }
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
        if not self.runtime.hub_base_url or not self.runtime.hub_token:
            raise RuntimeError("configure SIESA_HUB_BASE_URL y SIESA_HUB_TOKEN para enviar a Siesa")
        return SiesaHubClient(
            base_url=self.runtime.hub_base_url,
            token=self.runtime.hub_token,
            auth_scheme=self.runtime.hub_auth_scheme,
            execute_path=self.runtime.hub_execute_path,
            metadata_path=self.runtime.hub_metadata_path,
        )

    def sync(self, dry_run: bool | None = None) -> SyncResult:
        is_dry_run = self.runtime.dry_run if dry_run is None else dry_run
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
            key = payment.idempotency_key()
            issues = self.validator.validate(payment)
            if issues:
                counters["invalid"] += 1
                self.log.write(_event("invalid", payment, issues=[issue.__dict__ for issue in issues]))
                continue
            if self.state.contains(key):
                counters["skipped_duplicates"] += 1
                self.log.write(_event("duplicate", payment))
                continue

            payload = build_payload(payment, self.mapping)
            if is_dry_run:
                counters["dry_run"] += 1
                self.log.write(_event("dry_run", payment, payload=payload))
                continue

            response = self._client().register_cash_receipt(self.mapping.connector_id, payload, key)
            if response.ok:
                counters["sent"] += 1
                self.state.add(key)
                self.log.write(_event("sent", payment, payload=payload, siesa_response=response.data))
            else:
                counters["failed"] += 1
                self.log.write(
                    _event(
                        "failed",
                        payment,
                        payload=payload,
                        siesa_status_code=response.status_code,
                        siesa_response=response.data,
                    )
                )

        self.state.save()
        return SyncResult(**counters)


def format_issues(issues: list[ValidationIssue]) -> str:
    return "; ".join(f"fila {issue.row} {issue.field}: {issue.message}" for issue in issues)
