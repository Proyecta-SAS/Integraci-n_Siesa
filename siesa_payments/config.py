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
    return value.strip().lower() in {"1", "true", "yes", "y", "si", "s"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value.strip())


def load_env_file(path: Path, override: bool = False) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator:
            continue
        name = name.strip()
        if not name or (not override and name in os.environ):
            continue
        os.environ[name] = value.strip().strip('"').strip("'")


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str
    dry_run: bool
    allow_send: bool
    send_cooldown_minutes: int
    input_csv: str | None
    sheets_csv_url: str | None
    mapping_file: Path
    state_file: Path
    log_file: Path
    siesa_connector_url: str | None
    hub_base_url: str | None
    hub_connector_id: str
    hub_operation: str
    siesa_connikey: str | None
    siesa_connitoken: str | None
    siesa_client_id: str | None
    siesa_client_secret: str | None
    siesa_id_compania: str | None
    siesa_id_ecosistema: str | None
    siesa_id_documento: str
    siesa_nombre_documento: str
    hub_execute_path: str

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            environment=os.getenv("SIESA_ENV", "qa").strip().lower(),
            dry_run=_env_bool("SIESA_DRY_RUN", True),
            allow_send=_env_bool("SIESA_ALLOW_SEND", False),
            send_cooldown_minutes=_env_int("SIESA_SEND_COOLDOWN_MINUTES", 15),
            input_csv=os.getenv("SIESA_INPUT_CSV") or None,
            sheets_csv_url=os.getenv("SIESA_SHEETS_CSV_URL") or None,
            mapping_file=Path(os.getenv("SIESA_CONFIG_FILE", "config/siesa_recibo_caja_mapping.json")),
            state_file=Path(os.getenv("SIESA_STATE_FILE", ".state/siesa_payments_state.json")),
            log_file=Path(os.getenv("SIESA_LOG_FILE", "logs/siesa_payments.jsonl")),
            siesa_connector_url=os.getenv("SIESA_CONNECTOR_URL") or None,
            hub_base_url=os.getenv("SIESA_HUB_BASE_URL") or os.getenv("SIESA_BASE_URL") or None,
            hub_connector_id=os.getenv("SIESA_HUB_CONNECTOR_ID", "142888"),
            hub_operation=os.getenv("SIESA_HUB_OPERATION", "API_v1_ReciboCaja"),
            siesa_connikey=os.getenv("SIESA_CONN_KEY") or os.getenv("SIESA_CONNIKEY") or None,
            siesa_connitoken=os.getenv("SIESA_CONN_TOKEN") or os.getenv("SIESA_CONNITOKEN") or None,
            siesa_client_id=os.getenv("SIESA_CLIENT_ID") or os.getenv("SIESA_APIGEE_CLIENT_ID") or None,
            siesa_client_secret=os.getenv("SIESA_CLIENT_SECRET") or os.getenv("SIESA_APIGEE_CLIENT_SECRET") or None,
            siesa_id_compania=os.getenv("SIESA_ID_COMPANIA") or None,
            siesa_id_ecosistema=os.getenv("SIESA_ID_ECOSISTEMA") or None,
            siesa_id_documento=os.getenv("SIESA_ID_DOCUMENTO", "142888"),
            siesa_nombre_documento=os.getenv("SIESA_NOMBRE_DOCUMENTO", "API_v1_ReciboCaja"),
            hub_execute_path=os.getenv("SIESA_HUB_EXECUTE_PATH", "/apisestandar/v3/conectoresimportar"),
        )


@dataclass(frozen=True)
class MappingConfig:
    connector_id: str
    operation: str
    required_transaction_type: str | None
    sheet_columns: dict[str, list[str]]
    value_maps: dict[str, dict[str, str]]
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
            value_maps={
                str(map_name): {str(source): str(target) for source, target in values.items()}
                for map_name, values in data.get("value_maps", {}).items()
            },
            payload_template=data.get("payload_template", {}),
        )
