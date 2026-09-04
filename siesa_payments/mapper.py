from __future__ import annotations

import os
from typing import Any

from .config import MappingConfig
from .models import PAYMENT_FIELD_NAMES, PaymentRow


class MappingError(RuntimeError):
    pass


def _set_dotted(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    current = target
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        node = current.setdefault(part, {})
        if not isinstance(node, dict):
            raise MappingError(f"ruta de payload invalida: {dotted_path}")
        current = node
    current[parts[-1]] = value


def build_payload(payment: PaymentRow, mapping: MappingConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for target_path, rule in mapping.payload_template.items():
        source = rule.get("source")
        if source == "literal":
            value = rule.get("value")
        elif source == "connector_id":
            value = mapping.connector_id
        elif source == "operation":
            value = mapping.operation
        elif source == "idempotency_key":
            value = payment.idempotency_key()
        elif source == "env":
            env_name = str(rule.get("name", ""))
            if not env_name:
                raise MappingError(f"mapping env sin nombre para: {target_path}")
            value = os.getenv(env_name, rule.get("default"))
        elif source == "payment":
            field_name = str(rule.get("field", ""))
            if field_name not in PAYMENT_FIELD_NAMES:
                raise MappingError(f"campo de pago desconocido en mapping: {field_name}")
            value = payment.to_payload_value(field_name)
        else:
            raise MappingError(f"source de mapping no soportado: {source!r}")
        _set_dotted(payload, target_path, value)
    return payload
