from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import MappingConfig


@dataclass(frozen=True)
class ContractComparison:
    contract_fields: list[str]
    mapped_fields: list[str]
    missing_in_mapping: list[str]
    not_in_contract: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing_in_mapping and not self.not_in_contract


def load_contract_body(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("el contrato Siesa debe ser un objeto JSON en la raiz")
    return data


def flatten_json_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(flatten_json_paths(child, child_prefix))
        return paths

    if isinstance(value, list):
        if not value:
            return [prefix] if prefix else []
        paths = []
        for index, child in enumerate(value):
            child_prefix = f"{prefix}.{index}" if prefix else str(index)
            paths.extend(flatten_json_paths(child, child_prefix))
        return paths

    return [prefix] if prefix else []


def compare_contract_to_mapping(contract_body: dict[str, Any], mapping: MappingConfig) -> ContractComparison:
    contract_fields = sorted(flatten_json_paths(contract_body))
    mapped_fields = sorted(mapping.payload_template)
    contract_set = set(contract_fields)
    mapped_set = set(mapped_fields)
    return ContractComparison(
        contract_fields=contract_fields,
        mapped_fields=mapped_fields,
        missing_in_mapping=sorted(contract_set - mapped_set),
        not_in_contract=sorted(mapped_set - contract_set),
    )
