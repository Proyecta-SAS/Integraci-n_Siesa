from __future__ import annotations

import tempfile
import json
import csv
import io
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from siesa_payments.config import MappingConfig, RuntimeConfig
from siesa_payments.siesa_hub import SiesaHubClient
from siesa_payments.source import read_csv_file
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
        send_cooldown_minutes=15,
        input_csv=str(csv_path),
        sheets_csv_url=None,
        mapping_file=Path("config/siesa_recibo_caja_mapping.json"),
        state_file=tmp_path / "state.json",
        log_file=tmp_path / "audit.jsonl",
        siesa_connector_url=None,
        hub_base_url="https://siesa.example",
        hub_connector_id="261128",
        hub_operation="API_v2_ReciboCaja",
        siesa_connikey="key",
        siesa_connitoken="token",
        siesa_client_id="client",
        siesa_client_secret="secret",
        siesa_id_compania="1",
        siesa_id_ecosistema="10",
        siesa_id_documento="261128",
        siesa_nombre_documento="API_v2_ReciboCaja",
        hub_execute_path="/hub/execute",
    )


class SyncTests(TestCase):
    def setUp(self) -> None:
        self.mapping = MappingConfig.load(Path("config/siesa_recibo_caja_mapping.json"))
        self.env = patch.dict(
            'os.environ',
            {
                'SIESA_ID_MEDIO_PAGO_CONSIGNACION': 'CONSIG_PRUEBA',
                'SIESA_ID_BANCO': '001',
                'SIESA_NRO_CUENTA': '30000003697',
                'SIESA_DOCTO_BANCO_CG': 'CG',
                'SIESA_ID_FE': '1103',
            },
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_v2_defaults_and_mapping_target_the_new_connector(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            runtime = RuntimeConfig.from_env()
        self.assertEqual(runtime.hub_connector_id, self.mapping.connector_id)
        self.assertEqual(runtime.hub_operation, self.mapping.operation)
        self.assertEqual(runtime.siesa_id_documento, "261128")
        self.assertEqual(runtime.siesa_nombre_documento, "API_v2_ReciboCaja")
        client = SiesaHubClient("https://example.com", "key", "token", "1",
                               runtime.siesa_id_documento, runtime.siesa_nombre_documento)
        params = parse_qs(urlsplit(client.connection_summary()["url"]).query)
        self.assertEqual(params["idDocumento"], ["261128"])
        self.assertEqual(params["nombreDocumento"], ["API_v2_ReciboCaja"])

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
                "261128",
                "API_v2_ReciboCaja",
                transport=transport,
            )

            result = PaymentSyncService(runtime_for(tmp_path, csv_path, True), self.mapping, client).sync()

            self.assertEqual(result.dry_run, 1)
            self.assertEqual(transport.calls, [])
            event = json.loads((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(event["flow"], "create_person_contact_receipt")
            self.assertIn("siesa_target", event)

    def test_sync_can_limit_to_one_source_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "payments.csv"
            csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")

            result = PaymentSyncService(runtime_for(tmp_path, csv_path, True), self.mapping).sync(source_rows={2})

            self.assertEqual(result.processed, 1)
            self.assertEqual(result.dry_run, 1)

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
                id_documento="261128",
                nombre_documento="API_v2_ReciboCaja",
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

    def test_reference_fix_reuses_previously_confirmed_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "payments.csv"
            csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")
            runtime = runtime_for(root, csv_path, False)
            key = read_csv_file(csv_path, self.mapping)[0].idempotency_key()
            runtime.state_file.write_text(json.dumps({"processed_keys": [key]}), encoding="utf-8")
            transport = FakeTransport()
            client = SiesaHubClient("https://siesa.example", "key", "token", "1", "261128", "Recibo", transport=transport)

            result = PaymentSyncService(runtime, self.mapping, client).sync()

            self.assertEqual(result.skipped_duplicates, 1)
            self.assertEqual(result.sent, 0)
            self.assertEqual(transport.calls, [])
            self.assertEqual(json.loads(runtime.state_file.read_text())["processed_keys"], [key])

    def test_new_reference_keeps_full_request_key_and_deduplicates_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "payments.csv"
            csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")
            runtime = replace(runtime_for(root, csv_path, False), send_cooldown_minutes=0)
            key = read_csv_file(csv_path, self.mapping)[0].idempotency_key()
            transport = FakeTransport()
            client = SiesaHubClient("https://siesa.example", "key", "token", "1", "261128", "Recibo", transport=transport)

            first = PaymentSyncService(runtime, self.mapping, client).sync()
            second = PaymentSyncService(runtime, self.mapping, client).sync()

            self.assertEqual((first.sent, second.skipped_duplicates, len(transport.calls)), (1, 1, 1))
            self.assertEqual(transport.calls[0][2]["Idempotency-Key"], key)
            self.assertEqual(len(key), 32)
            payload = json.loads(transport.calls[0][3])
            self.assertEqual(payload["RCyotrosingresos"][0]["F357_REFERENCIA"], "20260213")
            self.assertEqual(payload["Caja"][0]["F358_REFERENCIA_OTROS"], "20260213")

    def test_distinct_notes_send_both_payments_and_retries_skip_both(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "payments.csv"
            rows = list(csv.reader(io.StringIO(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"))))
            second = list(rows[1])
            second[9] = "Transferencia 67890"
            rows[1][9] = "Transferencia 12345"
            rows.append(second)
            with csv_path.open("w", encoding="utf-8", newline="") as file:
                csv.writer(file).writerows(rows)
            runtime = replace(runtime_for(root, csv_path, False), send_cooldown_minutes=0)
            transport = FakeTransport()
            client = SiesaHubClient("https://siesa.example", "key", "token", "1", "261128", "Recibo", transport=transport)
            first = PaymentSyncService(runtime, self.mapping, client).sync()
            # Moving a payment to another row must not make it a new payment.
            rows[1:] = reversed(rows[1:])
            with csv_path.open("w", encoding="utf-8", newline="") as file:
                csv.writer(file).writerows(rows)
            retry = PaymentSyncService(runtime, self.mapping, client).sync()
            self.assertEqual((first.sent, retry.sent, retry.skipped_duplicates), (2, 0, 2))
            self.assertEqual(len(transport.calls), 2)
            self.assertNotEqual(transport.calls[0][2]["Idempotency-Key"], transport.calls[1][2]["Idempotency-Key"])

    def test_different_note_recovers_only_second_legitimate_payment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "payments.csv"
            rows = list(csv.reader(io.StringIO(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"))))
            rows.append(list(rows[1]))
            def save_rows():
                with csv_path.open("w", encoding="utf-8", newline="") as file:
                    csv.writer(file).writerows(rows)
            save_rows()
            runtime = replace(runtime_for(root, csv_path, False), send_cooldown_minutes=0)
            transport = FakeTransport()
            client = SiesaHubClient("https://siesa.example", "key", "token", "1", "261128", "Recibo", transport=transport)
            initial = PaymentSyncService(runtime, self.mapping, client).sync()
            self.assertEqual((initial.sent, initial.skipped_duplicates), (1, 1))
            original_key = read_csv_file(csv_path, self.mapping)[0].idempotency_key()
            rows[2][9] += " - Segundo pago confirmado"
            save_rows()
            corrected = PaymentSyncService(runtime, self.mapping, client).sync()
            retry = PaymentSyncService(runtime, self.mapping, client).sync()
            self.assertEqual((corrected.sent, corrected.skipped_duplicates), (1, 1))
            self.assertEqual((retry.sent, retry.skipped_duplicates, len(transport.calls)), (0, 2, 2))
            state = json.loads(runtime.state_file.read_text())
            self.assertIn(original_key, state["processed_keys"])
            self.assertEqual(len(state["processed_keys"]), 2)

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
                send_cooldown_minutes=runtime.send_cooldown_minutes,
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

    def test_send_cooldown_blocks_second_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "payments.csv"
            csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")
            first_transport = FakeTransport(body=b'{"documento":"RC-1"}')
            first_client = SiesaHubClient(
                base_url="https://siesa.example",
                connikey="key",
                connitoken="token",
                client_id="client",
                client_secret="secret",
                id_compania="1",
                id_documento="261128",
                nombre_documento="API_v2_ReciboCaja",
                id_ecosistema="10",
                execute_path="/hub/execute",
                transport=first_transport,
            )
            runtime = runtime_for(tmp_path, csv_path, False)

            first_result = PaymentSyncService(runtime, self.mapping, first_client).sync()

            self.assertEqual(first_result.sent, 1)
            second_transport = FakeTransport(body=b'{"documento":"RC-2"}')
            second_client = SiesaHubClient(
                base_url="https://siesa.example",
                connikey="key",
                connitoken="token",
                client_id="client",
                client_secret="secret",
                id_compania="1",
                id_documento="261128",
                nombre_documento="API_v2_ReciboCaja",
                id_ecosistema="10",
                execute_path="/hub/execute",
                transport=second_transport,
            )

            with self.assertRaises(PermissionError):
                PaymentSyncService(runtime, self.mapping, second_client).sync()
            self.assertEqual(second_transport.calls, [])

    def test_runtime_accepts_siesa_base_url_alias(self) -> None:
        env = {
            "SIESA_BASE_URL": "https://produccion.siesa.example",
            "SIESA_ID_ECOSISTEMA": "99",
        }

        with patch.dict("os.environ", env, clear=True):
            runtime = RuntimeConfig.from_env()

        self.assertEqual(runtime.hub_base_url, "https://produccion.siesa.example")
        self.assertEqual(runtime.siesa_id_ecosistema, "99")

    def test_connector_url_rejects_unresolved_placeholders(self) -> None:
        client = SiesaHubClient(
            base_url=None,
            connector_url=(
                "https://{baseUrl}/apisestandar/v3/conectoresimportar"
                "?idCompania=9534&idEcoSistema={idEcoSistema}&idDocumento=261128"
            ),
            connikey="key",
            connitoken="token",
            id_compania="9534",
            id_documento="261128",
            nombre_documento="API_v2_ReciboCaja",
        )

        with self.assertRaisesRegex(RuntimeError, "placeholders"):
            client.connection_summary()
