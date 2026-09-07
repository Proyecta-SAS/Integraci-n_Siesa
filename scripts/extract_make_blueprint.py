from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SHEET_INDEX = {
    "0": "bank_account",
    "1": "payment_date",
    "2": "contact",
    "3": "transaction_type",
    "4": "payment_method",
    "5": "cost_center",
    "6": "concept",
    "7": "quantity",
    "8": "amount",
    "9": "note",
    "10": "observations",
    "12": "customer_action",
    "13": "person_type",
    "14": "identity_type",
    "15": "identity_number",
    "16": "first_name",
    "17": "last_name",
    "18": "tax_person_type",
    "19": "tax_responsibility",
    "20": "municipality_department",
    "21": "address",
}


def walk_modules(flow: list[dict[str, Any]], path: str = "root") -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for module in flow:
        modules.append(
            {
                "path": path,
                "id": module.get("id"),
                "module": module.get("module"),
                "name": module.get("metadata", {}).get("designer", {}).get("name", ""),
            }
        )
        for route_index, route in enumerate(module.get("routes") or []):
            modules.extend(walk_modules(route.get("flow") or [], f"{path}/{module.get('id')}:route_{route_index}"))
    return modules


def find_module(flow: list[dict[str, Any]], module_id: int) -> dict[str, Any] | None:
    for module in flow:
        if module.get("id") == module_id:
            return module
        for route in module.get("routes") or []:
            found = find_module(route.get("flow") or [], module_id)
            if found:
                return found
    return None


def variables(module: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in module.get("mapper", {}).get("variables") or []:
        values[str(item.get("name", "")).strip()] = str(item.get("value", ""))
    return values


def parse_if_mapping(expression: str, column_index: str) -> list[dict[str, str | int]]:
    pattern = re.compile(
        r'if\(\s*14\.`'
        + re.escape(column_index)
        + r'`\s*=\s*"(?P<label>(?:[^"\\]|\\.)*)"\s*;\s*(?P<value>"(?:[^"\\]|\\.)*"|-?\d+|[A-Za-z0-9_,.-]+)'
    )
    result: list[dict[str, str | int]] = []
    for match in pattern.finditer(expression):
        label = match.group("label")
        raw_value = match.group("value").strip()
        if raw_value.startswith('"') and raw_value.endswith('"'):
            value: str | int = raw_value[1:-1]
        elif re.fullmatch(r"-?\d+", raw_value):
            value = int(raw_value)
        else:
            value = raw_value
        result.append({"label": label, "value": value})
    return result


def module_summary(module: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": module.get("id"),
        "module": module.get("module"),
        "name": module.get("metadata", {}).get("designer", {}).get("name", ""),
    }


def build_outputs(blueprint: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    flow = blueprint.get("flow") or []
    modules = walk_modules(flow)
    existing_vars = variables(find_module(flow, 10) or {})
    create_vars = variables(find_module(flow, 20) or {})

    bank_accounts = parse_if_mapping(existing_vars.get("Cuenta Bancaria", ""), "0")
    contact_ids = parse_if_mapping(existing_vars.get("Contacto", ""), "2")
    concepts = parse_if_mapping(existing_vars.get("Concepto", ""), "6")
    payment_methods = parse_if_mapping(existing_vars.get("Metodo de pago", ""), "4")
    transaction_types = parse_if_mapping(existing_vars.get("Tipo de transaccion", ""), "3")
    person_roles = parse_if_mapping(create_vars.get("Tipo", "") or create_vars.get("Tipo ", ""), "13")
    tax_responsibilities = parse_if_mapping(
        create_vars.get("Responsabilidad tributaria (solo para NIT)", "")
        or create_vars.get("Responsabilidad tributaria (solo para NIT) ", ""),
        "19",
    )

    flow_rules = {
        "source_blueprint": "references/make/alianza_juridica_avanzar.blueprint.json",
        "scenario_name": blueprint.get("name", ""),
        "reference_google_sheet": {
            "spreadsheet_id": "1TuXSZESNm1xJGJvXLMKTq2bAY1ZvmCl6n8Aez1FRVp8",
            "sheet_name": "Ingreso / Egreso",
            "header_range": "A1:CZ1",
            "sort": "__ROW_NUMBER__ desc",
        },
        "entry_condition": {
            "source": "webhook",
            "field": "activador",
            "operator": "equals",
            "value": "ON",
        },
        "routes": [
            {
                "key": "existing_contact_receipt",
                "make_nodes": [10, 3, 15],
                "condition": "upper(sheet.customer_action) does not contain CREAR",
                "required_after_mapping": ["contact_id != 0"],
                "siesa_target": "Financiero > Cuentas x cobrar > Recibos de caja > Clientes",
            },
            {
                "key": "create_person_contact_receipt",
                "make_nodes": [20, 21, 25, 24],
                "condition": "upper(sheet.customer_action) contains CREAR and identity_type is CC/persona natural",
                "siesa_target": "Crear/validar tercero persona natural y luego ReciboCaja",
            },
            {
                "key": "create_legal_contact_receipt",
                "make_nodes": [20, 23, 26, 27],
                "condition": "upper(sheet.customer_action) contains CREAR and identity_type is NIT/persona juridica",
                "siesa_target": "Crear/validar tercero juridico y luego ReciboCaja",
            },
            {
                "key": "create_client_provider_receipt",
                "make_nodes": [20, 36, 35, 37, 42, 38, 44, 40],
                "condition": "upper(sheet.customer_action) contains CREAR and role is Cliente / Proveedor",
                "siesa_target": "Crear/validar tercero con doble rol y luego ReciboCaja",
            },
        ],
        "sheet_index_map": SHEET_INDEX,
        "small_mappings": {
            "bank_accounts": bank_accounts,
            "payment_methods": payment_methods,
            "transaction_types": transaction_types,
            "person_roles": person_roles,
            "tax_responsibilities": tax_responsibilities,
        },
        "large_catalogs": {
            "contact_ids": {
                "count": len(contact_ids),
                "file": "config/alegra_catalogs_from_make.json",
                "json_path": "contact_ids",
            },
            "concept_ids": {
                "count": len(concepts),
                "file": "config/alegra_catalogs_from_make.json",
                "json_path": "concept_ids",
            },
        },
    }

    catalogs = {
        "source_blueprint": flow_rules["source_blueprint"],
        "contact_ids": contact_ids,
        "concept_ids": concepts,
    }

    inventory = {
        "source_blueprint": flow_rules["source_blueprint"],
        "modules": modules,
    }

    return flow_rules, catalogs, inventory


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Make/Alegra routing rules from a scenario blueprint.")
    parser.add_argument("blueprint", type=Path)
    parser.add_argument("--flow-rules", type=Path, default=Path("config/alegra_flow_rules.json"))
    parser.add_argument("--catalogs", type=Path, default=Path("config/alegra_catalogs_from_make.json"))
    parser.add_argument("--inventory", type=Path, default=Path("docs/make_blueprint_inventory.json"))
    args = parser.parse_args()

    blueprint = json.loads(args.blueprint.read_text(encoding="utf-8-sig"))
    flow_rules, catalogs, inventory = build_outputs(blueprint)

    for path, data in ((args.flow_rules, flow_rules), (args.catalogs, catalogs), (args.inventory, inventory)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
