from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .config import MappingConfig, RuntimeConfig
from .contract import compare_contract_to_mapping, load_contract_body
from .siesa_hub import SiesaHubClient
from .sync import PaymentSyncService


def _load_runtime(args: argparse.Namespace) -> RuntimeConfig:
    runtime = RuntimeConfig.from_env()
    return RuntimeConfig(
        environment=args.env or runtime.environment,
        dry_run=runtime.dry_run if args.dry_run is None else args.dry_run,
        input_csv=args.input_csv or runtime.input_csv,
        sheets_csv_url=args.sheets_csv_url or runtime.sheets_csv_url,
        mapping_file=Path(args.config_file) if args.config_file else runtime.mapping_file,
        state_file=Path(args.state_file) if args.state_file else runtime.state_file,
        log_file=Path(args.log_file) if args.log_file else runtime.log_file,
        siesa_connector_url=args.connector_url or runtime.siesa_connector_url,
        hub_base_url=args.hub_base_url or runtime.hub_base_url,
        hub_connector_id=args.connector_id or runtime.hub_connector_id,
        hub_operation=args.operation or runtime.hub_operation,
        siesa_connikey=args.connikey or runtime.siesa_connikey,
        siesa_connitoken=args.connitoken or runtime.siesa_connitoken,
        siesa_client_id=args.client_id or runtime.siesa_client_id,
        siesa_client_secret=args.client_secret or runtime.siesa_client_secret,
        siesa_id_compania=args.id_compania or runtime.siesa_id_compania,
        siesa_id_ecosistema=args.id_ecosistema or runtime.siesa_id_ecosistema,
        siesa_id_documento=args.id_documento or runtime.siesa_id_documento,
        siesa_nombre_documento=args.nombre_documento or runtime.siesa_nombre_documento,
        hub_execute_path=args.execute_path or runtime.hub_execute_path,
    )


def _load_mapping(runtime: RuntimeConfig) -> MappingConfig:
    mapping = MappingConfig.load(runtime.mapping_file)
    if runtime.hub_connector_id != mapping.connector_id or runtime.hub_operation != mapping.operation:
        return MappingConfig(
            connector_id=runtime.hub_connector_id,
            operation=runtime.hub_operation,
            required_transaction_type=mapping.required_transaction_type,
            sheet_columns=mapping.sheet_columns,
            value_maps=mapping.value_maps,
            payload_template=mapping.payload_template,
        )
    return mapping


def cmd_sync(args: argparse.Namespace) -> int:
    runtime = _load_runtime(args)
    mapping = _load_mapping(runtime)
    result = PaymentSyncService(runtime, mapping).sync()
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return 0 if result.failed == 0 and result.invalid == 0 else 2


def cmd_validate_connector(args: argparse.Namespace) -> int:
    runtime = _load_runtime(args)
    mapping = _load_mapping(runtime)
    if not runtime.siesa_connikey or not runtime.siesa_connitoken or not runtime.siesa_id_compania:
        print("Configure SIESA_CONN_KEY, SIESA_CONN_TOKEN y SIESA_ID_COMPANIA.", file=sys.stderr)
        return 2
    client = SiesaHubClient(
        base_url=runtime.hub_base_url,
        connector_url=runtime.siesa_connector_url,
        connikey=runtime.siesa_connikey,
        connitoken=runtime.siesa_connitoken,
        client_id=runtime.siesa_client_id,
        client_secret=runtime.siesa_client_secret,
        id_compania=runtime.siesa_id_compania,
        id_documento=runtime.siesa_id_documento,
        id_ecosistema=runtime.siesa_id_ecosistema,
        nombre_documento=runtime.siesa_nombre_documento,
        execute_path=runtime.hub_execute_path,
    )
    print(json.dumps({"ok": True, "connector": mapping.connector_id, "request": client.connection_summary()}, indent=2, ensure_ascii=False))
    return 0


def cmd_inspect_contract(args: argparse.Namespace) -> int:
    runtime = _load_runtime(args)
    mapping = _load_mapping(runtime)
    contract_body = load_contract_body(Path(args.contract_file))
    comparison = compare_contract_to_mapping(contract_body, mapping)
    print(json.dumps(asdict(comparison), indent=2, ensure_ascii=False))
    return 0 if comparison.ok else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sincroniza pagos de Google Sheets/Alegra a Siesa HUB.")
    parser.set_defaults(func=None)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env", choices=["qa", "prod", "production"], help="Ambiente destino.")
    common.add_argument("--config-file", help="Archivo JSON de mapeo.")
    common.add_argument("--input-csv", help="CSV local exportado desde Google Sheets.")
    common.add_argument("--sheets-csv-url", help="URL export CSV de Google Sheets.")
    common.add_argument("--state-file", help="Archivo de estado para deduplicacion.")
    common.add_argument("--log-file", help="Archivo JSONL de auditoria.")
    common.add_argument("--connector-url", help="URL completa copiada desde la guia del conector.")
    common.add_argument("--hub-base-url", help="Base URL de Siesa HUB.")
    common.add_argument("--connikey", help="Header Connikey copiado desde el Documentador.")
    common.add_argument("--connitoken", help="Header Connitoken copiado desde el Documentador.")
    common.add_argument("--client-id", help="Header client_id de Apigee QA.")
    common.add_argument("--client-secret", help="Header client_secret de Apigee QA.")
    common.add_argument("--id-compania", help="Parametro idCompania del conector.")
    common.add_argument("--id-ecosistema", help="Parametro idEcoSistema del conector.")
    common.add_argument("--id-documento", help="Parametro idDocumento del conector.")
    common.add_argument("--nombre-documento", help="Parametro nombreDocumento del conector.")
    common.add_argument("--connector-id", help="ID de conector Siesa HUB.")
    common.add_argument("--operation", help="Operacion del conector.")
    common.add_argument("--execute-path", help="Path parametrizado de ejecucion del conector.")

    subparsers = parser.add_subparsers(dest="command")
    sync_parser = subparsers.add_parser("sync", parents=[common], help="Valida y sincroniza pagos.")
    dry_group = sync_parser.add_mutually_exclusive_group()
    dry_group.add_argument("--dry-run", dest="dry_run", action="store_true", help="No envia a Siesa.")
    dry_group.add_argument("--send", dest="dry_run", action="store_false", help="Envia a Siesa.")
    sync_parser.set_defaults(func=cmd_sync, dry_run=None)

    validate_parser = subparsers.add_parser("validate-connector", parents=[common], help="Consulta metadata del conector.")
    validate_parser.set_defaults(func=cmd_validate_connector, dry_run=None)

    inspect_parser = subparsers.add_parser("inspect-contract", parents=[common], help="Compara el Body Siesa contra el mapeo local.")
    inspect_parser.add_argument("--contract-file", required=True, help="JSON del Body copiado desde el Documentador Siesa.")
    inspect_parser.set_defaults(func=cmd_inspect_contract, dry_run=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.func is None:
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
