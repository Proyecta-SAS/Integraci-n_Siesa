from __future__ import annotations

import os
from typing import Any

from .config import MappingConfig
from .models import (
    PAYMENT_FIELD_NAMES,
    PaymentRow,
    clean_text,
    format_decimal_signed,
    format_integer,
    normalize_header,
    parse_decimal,
)


class MappingError(RuntimeError):
    pass


def _new_container(next_part: str) -> dict[str, Any] | list[Any]:
    return [] if next_part.isdigit() else {}


def _ensure_list_index(items: list[Any], index: int, next_part: str | None) -> None:
    while len(items) <= index:
        items.append(_new_container(next_part or ""))


def _set_dotted(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    current: dict[str, Any] | list[Any] = target
    parts = dotted_path.split(".")
    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        next_part = None if is_last else parts[index + 1]

        if part.isdigit():
            if not isinstance(current, list):
                raise MappingError(f"ruta de payload invalida: {dotted_path}")
            item_index = int(part)
            _ensure_list_index(current, item_index, next_part)
            if is_last:
                current[item_index] = value
            else:
                current = current[item_index]
            continue

        if not isinstance(current, dict):
            raise MappingError(f"ruta de payload invalida: {dotted_path}")
        if is_last:
            current[part] = value
            continue
        node = current.get(part)
        if not isinstance(node, (dict, list)):
            node = _new_container(next_part or "")
            current[part] = node
        current = node


def _apply_value_map(value: Any, rule: dict[str, Any], mapping: MappingConfig) -> Any:
    map_name = rule.get("map")
    if not map_name:
        return value
    value_map = mapping.value_maps.get(str(map_name), {})
    return value_map.get(normalize_header(str(value)), value)


def _apply_format(value: Any, rule: dict[str, Any]) -> Any:
    value_format = rule.get("format")
    if value_format == "decimal_signed_21":
        return format_decimal_signed(parse_decimal(value))
    if isinstance(value_format, str) and value_format.startswith("integer_"):
        return format_integer(value, int(value_format.removeprefix("integer_")))
    if isinstance(value_format, str) and value_format.startswith("max_"):
        return str(value)[: int(value_format.removeprefix("max_"))]
    return value


def _receipt_application_mode() -> str:
    value = os.getenv("SIESA_RECIBO_FLUJO") or os.getenv("SIESA_RECEIPT_MODE") or "cartera"
    return normalize_header(value).replace(" ", "_")


def _apply_other_income_mode(payload: dict[str, Any], payment: PaymentRow) -> None:
    if _receipt_application_mode() not in {"otros_ingresos", "otro_ingreso", "anticipo", "anticipo_por_identificar"}:
        return

    payload.pop("CxC", None)
    receipt_lines = payload.get("RCyotrosingresos") or []
    if not receipt_lines:
        return

    receipt = receipt_lines[0]
    receipt["F351_ID_AUXILIAR_OTRO_ING"] = os.getenv("SIESA_AUXILIAR_OTRO_ING", "28050505")
    receipt["F351_ID_TERCERO_OTRO_ING"] = payment.identity_number
    receipt["F351_ID_SUCURSAL_OTRO_ING"] = os.getenv("SIESA_SUCURSAL_OTRO_ING", "001")
    receipt["F351_ID_CO_OTRO_ING"] = os.getenv("SIESA_ID_CO_OTRO_ING") or os.getenv("SIESA_ID_CO", "")
    receipt["F351_ID_UN_OTRO_ING"] = os.getenv("SIESA_ID_UN_OTRO_ING") or os.getenv("SIESA_ID_UN", "")
    receipt["F351_ID_CCOSTO_OTRO_ING"] = payment.cost_center or os.getenv("SIESA_CCOSTO_OTRO_ING", "")


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
        elif source == "payment_or_env":
            field_name = str(rule.get("field", ""))
            env_name = str(rule.get("name", ""))
            if field_name not in PAYMENT_FIELD_NAMES:
                raise MappingError(f"campo de pago desconocido en mapping: {field_name}")
            if not env_name:
                raise MappingError(f"mapping env sin nombre para: {target_path}")
            value = payment.to_payload_value(field_name, rule.get("format"))
            if not clean_text(value):
                value = os.getenv(env_name, rule.get("default"))
        elif source == "payment":
            field_name = str(rule.get("field", ""))
            if field_name not in PAYMENT_FIELD_NAMES:
                raise MappingError(f"campo de pago desconocido en mapping: {field_name}")
            value = payment.to_payload_value(field_name, rule.get("format"))
        else:
            raise MappingError(f"source de mapping no soportado: {source!r}")
        value = _apply_format(value, rule)
        _set_dotted(payload, target_path, _apply_value_map(value, rule, mapping))
    _apply_other_income_mode(payload, payment)
    return payload
