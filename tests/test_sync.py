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
        siesa_id_compania="1",
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
                id_compania="1",
                id_documento="142888",
                nombre_documento="API_v1_ReciboCaja",
                execute_path="/hub/execute",
                transport=transport,
            )

            result = PaymentSyncService(runtime_for(tmp_path, csv_path, False), self.mapping, client).sync()

            self.assertEqual(result.sent, 1)
            self.assertEqual(transport.calls[0][0], "POST")
            self.assertIn("/hub/execute", transport.calls[0][1])
            self.assertIn("idCompania=1", transport.calls[0][1])
            self.assertEqual(transport.calls[0][2]["Connikey"], "key")
            self.assertEqual(transport.calls[0][2]["Connitoken"], "token")
            self.assertTrue((tmp_path / "state.json").exists())
