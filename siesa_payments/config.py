from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "si", "sí"}


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    dry_run: bool
    input_csv: str | None
    sheets_csv_url: str | None
    mapping_file: Path
    state_file: Path
    log_file: Path
    hub_base_url: str | None
    hub_connector_id: str
    hub_operation: str
    hub_token: str | None
    hub_auth_scheme: str
    hub_execute_path: str
    hub_metadata_path: str

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            environment=os.getenv("SIESA_ENV", "qa").strip().lower(),
            dry_run=_env_bool("SIESA_DRY_RUN", True),
            input_csv=os.getenv("SIESA_INPUT_CSV") or None,
            sheets_csv_url=os.getenv("SIESA_SHEETS_CSV_URL") or None,
            mapping_file=Path(os.getenv("SIESA_CONFIG_FILE", "config/siesa_recibo_caja_mapping.json")),
            state_file=Path(os.getenv("SIESA_STATE_FILE", ".state/siesa_payments_state.json")),
            log_file=Path(os.getenv("SIESA_LOG_FILE", "logs/siesa_payments.jsonl")),
            hub_base_url=os.getenv("SIESA_HUB_BASE_URL") or None,
            hub_connector_id=os.getenv("SIESA_HUB_CONNECTOR_ID", "142888"),
            hub_operation=os.getenv("SIESA_HUB_OPERATION", "API_v1_ReciboCaja"),
            hub_token=os.getenv("SIESA_HUB_TOKEN") or None,
            hub_auth_scheme=os.getenv("SIESA_HUB_AUTH_SCHEME", "Bearer"),
            hub_execute_path=os.getenv("SIESA_HUB_EXECUTE_PATH", "/api/v1/connectors/{connector_id}/execute"),
            hub_metadata_path=os.getenv("SIESA_HUB_METADATA_PATH", "/api/v1/connectors/{connector_id}"),
        )


@dataclass(frozen=True)
class MappingConfig:
    connector_id: str
    operation: str
    required_transaction_type: str | None
    sheet_columns: dict[str, list[str]]
    payload_template: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> "MappingConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            connector_id=str(data.get("connector_id", "142888")),
            operation=str(data.get("operation", "API_v1_ReciboCaja")),
            required_transaction_type=data.get("required_transaction_type"),
            sheet_columns={
                key: [str(alias) for alias in aliases]
                for key, aliases in data.get("sheet_columns", {}).items()
            },
            payload_template=data.get("payload_template", {}),
        )
