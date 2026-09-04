from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .config import MappingConfig, RuntimeConfig
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
        hub_base_url=args.hub_base_url or runtime.hub_base_url,
        hub_connector_id=args.connector_id or runtime.hub_connector_id,
        hub_operation=args.operation or runtime.hub_operation,
        hub_token=args.hub_token or runtime.hub_token,
        hub_auth_scheme=args.auth_scheme or runtime.hub_auth_scheme,
        hub_execute_path=args.execute_path or runtime.hub_execute_path,
        hub_metadata_path=args.metadata_path or runtime.hub_metadata_path,
    )


def _load_mapping(runtime: RuntimeConfig) -> MappingConfig:
    mapping = MappingConfig.load(runtime.mapping_file)
    if runtime.hub_connector_id != mapping.connector_id or runtime.hub_operation != mapping.operation:
        return MappingConfig(
            connector_id=runtime.hub_connector_id,
            operation=runtime.hub_operation,
            required_transaction_type=mapping.required_transaction_type,
            sheet_columns=mapping.sheet_columns,
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
    if not runtime.hub_base_url or not runtime.hub_token:
        print("Configure SIESA_HUB_BASE_URL y SIESA_HUB_TOKEN.", file=sys.stderr)
        return 2
    client = SiesaHubClient(
        base_url=runtime.hub_base_url,
        token=runtime.hub_token,
        auth_scheme=runtime.hub_auth_scheme,
        execute_path=runtime.hub_execute_path,
        metadata_path=runtime.hub_metadata_path,
    )
    response = client.validate_connector(mapping.connector_id)
    print(json.dumps({"ok": response.ok, "status_code": response.status_code, "data": response.data}, indent=2, ensure_ascii=False))
    return 0 if response.ok else 2


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
    common.add_argument("--hub-base-url", help="Base URL de Siesa HUB.")
    common.add_argument("--hub-token", help="Token de Siesa HUB.")
    common.add_argument("--auth-scheme", help="Esquema Authorization, por defecto Bearer.")
    common.add_argument("--connector-id", help="ID de conector Siesa HUB.")
    common.add_argument("--operation", help="Operacion del conector.")
    common.add_argument("--execute-path", help="Path parametrizado de ejecucion del conector.")
    common.add_argument("--metadata-path", help="Path parametrizado de metadata del conector.")

    subparsers = parser.add_subparsers(dest="command")
    sync_parser = subparsers.add_parser("sync", parents=[common], help="Valida y sincroniza pagos.")
    dry_group = sync_parser.add_mutually_exclusive_group()
    dry_group.add_argument("--dry-run", dest="dry_run", action="store_true", help="No envia a Siesa.")
    dry_group.add_argument("--send", dest="dry_run", action="store_false", help="Envia a Siesa.")
    sync_parser.set_defaults(func=cmd_sync, dry_run=None)

    validate_parser = subparsers.add_parser("validate-connector", parents=[common], help="Consulta metadata del conector.")
    validate_parser.set_defaults(func=cmd_validate_connector, dry_run=None)
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
