from __future__ import annotations

import tempfile
import json
from pathlib import Path
from unittest import TestCase

from siesa_payments.config import MappingConfig, RuntimeConfig
from siesa_payments.siesa_hub import SiesaHubClient
from siesa_payments.sync import PaymentSyncService


class FakeTransport:
    def __init__(self, status: int = 200, body: bytes = b'{"documento":"RC-1"}') -> None:
        self.status = status
        self.body = body
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: int):
        self.calls.append((method, url, headers, body))
        return self.status, {}, self.body


def runtime_for(tmp_path: Path, csv_path: Path, dry_run: bool) -> RuntimeConfig:
    return RuntimeConfig(
        environment="qa",
        dry_run=dry_run,
        allow_send=not dry_run,
        input_csv=str(csv_path),
        sheets_csv_url=None,
        mapping_file=Path("config/siesa_recibo_caja_mapping.json"),
        state_file=tmp_path / "state.json",
        log_file=tmp_path / "audit.jsonl",
        siesa_connector_url=None,
        hub_base_url="https://siesa.example",
        hub_connector_id="142888",
        hub_operation="API_v1_ReciboCaja",
        siesa_connikey="key",
        siesa_connitoken="token",
        siesa_client_id="client",
        siesa_client_secret="secret",
        siesa_id_compania="1",
        siesa_id_ecosistema="10",
        siesa_id_documento="142888",
        siesa_nombre_documento="API_v1_ReciboCaja",
        hub_execute_path="/hub/execute",
    )


class SyncTests(TestCase):
    def setUp(self) -> None:
        self.mapping = MappingConfig.load(Path("config/siesa_recibo_caja_mapping.json"))

    def test_dry_run_does_not_call_hub(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "payments.csv"
            csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")
            transport = FakeTransport()
            client = SiesaHubClient(
                "https://siesa.example",
                "key",
                "token",
                "1",
                "142888",
                "API_v1_ReciboCaja",
                transport=transport,
            )

            result = PaymentSyncService(runtime_for(tmp_path, csv_path, True), self.mapping, client).sync()

            self.assertEqual(result.dry_run, 1)
            self.assertEqual(transport.calls, [])
            event = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(event["flow"], "create_person_contact_receipt")
            self.assertIn("siesa_target", event)

    def test_send_posts_to_connector_and_stores_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "payments.csv"
            csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")
            transport = FakeTransport()
            client = SiesaHubClient(
                base_url="https://siesa.example",
                connikey="key",
                connitoken="token",
                client_id="client",
                client_secret="secret",
                id_compania="1",
                id_documento="142888",
                nombre_documento="API_v1_ReciboCaja",
                id_ecosistema="10",
                execute_path="/hub/execute",
                transport=transport,
            )

            result = PaymentSyncService(runtime_for(tmp_path, csv_path, False), self.mapping, client).sync()

            self.assertEqual(result.sent, 1)
            self.assertEqual(transport.calls[0][0], "POST")
            self.assertIn("/hub/execute", transport.calls[0][1])
            self.assertIn("idCompania=1", transport.calls[0][1])
            self.assertIn("idEcoSistema=10", transport.calls[0][1])
            self.assertEqual(transport.calls[0][2]["Connikey"], "key")
            self.assertEqual(transport.calls[0][2]["Connitoken"], "token")
            self.assertEqual(transport.calls[0][2]["client_id"], "client")
            self.assertEqual(transport.calls[0][2]["client_secret"], "secret")
            self.assertTrue((tmp_path / "state.json").exists())

    def test_send_requires_explicit_allow_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "payments.csv"
            csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")
            runtime = runtime_for(tmp_path, csv_path, False)
            runtime = RuntimeConfig(
                environment=runtime.environment,
                dry_run=runtime.dry_run,
                allow_send=False,
                input_csv=runtime.input_csv,
                sheets_csv_url=runtime.sheets_csv_url,
                mapping_file=runtime.mapping_file,
                state_file=runtime.state_file,
                log_file=runtime.log_file,
                siesa_connector_url=runtime.siesa_connector_url,
                hub_base_url=runtime.hub_base_url,
                hub_connector_id=runtime.hub_connector_id,
                hub_operation=runtime.hub_operation,
                siesa_connikey=runtime.siesa_connikey,
                siesa_connitoken=runtime.siesa_connitoken,
                siesa_client_id=runtime.siesa_client_id,
                siesa_client_secret=runtime.siesa_client_secret,
                siesa_id_compania=runtime.siesa_id_compania,
                siesa_id_ecosistema=runtime.siesa_id_ecosistema,
                siesa_id_documento=runtime.siesa_id_documento,
                siesa_nombre_documento=runtime.siesa_nombre_documento,
                hub_execute_path=runtime.hub_execute_path,
            )

            with self.assertRaises(PermissionError):
                PaymentSyncService(runtime, self.mapping).sync()
