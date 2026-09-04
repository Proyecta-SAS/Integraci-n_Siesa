from __future__ import annotations

import tempfile
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
        hub_base_url="https://siesa.example",
        hub_connector_id="142888",
        hub_operation="API_v1_ReciboCaja",
        hub_token="token",
        hub_auth_scheme="Bearer",
        hub_execute_path="/hub/{connector_id}/execute",
        hub_metadata_path="/hub/{connector_id}",
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
            client = SiesaHubClient("https://siesa.example", "token", transport=transport)

            result = PaymentSyncService(runtime_for(tmp_path, csv_path, True), self.mapping, client).sync()

            self.assertEqual(result.dry_run, 1)
            self.assertEqual(transport.calls, [])

    def test_send_posts_to_connector_and_stores_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "payments.csv"
            csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")
            transport = FakeTransport()
            client = SiesaHubClient(
                "https://siesa.example",
                "token",
                execute_path="/hub/{connector_id}/execute",
                transport=transport,
            )

            result = PaymentSyncService(runtime_for(tmp_path, csv_path, False), self.mapping, client).sync()

            self.assertEqual(result.sent, 1)
            self.assertEqual(transport.calls[0][0], "POST")
            self.assertIn("/hub/142888/execute", transport.calls[0][1])
            self.assertTrue((tmp_path / "state.json").exists())
