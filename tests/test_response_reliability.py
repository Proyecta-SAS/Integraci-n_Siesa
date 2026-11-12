from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from http.client import IncompleteRead
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.error import URLError

from siesa_payments.config import MappingConfig, RuntimeConfig
from siesa_payments.mapper import build_payload
from siesa_payments.source import read_csv_file
from siesa_payments.state import write_json_atomic
from siesa_payments.sync import PaymentSyncService


class SimulatedResponse:
    def __init__(self, delay_seconds=45, error=None):
        self.delay_seconds = delay_seconds
        self.error = error
        self.calls = []

    def request(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "headers": headers, "body": body, "timeout": timeout})
        if self.error:
            raise self.error
        if timeout < self.delay_seconds:
            raise TimeoutError("simulated slow response")
        return 200, {}, b'{"codigo":0,"documento":"RC-SLOW"}'


class ResponseReliabilityTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict("os.environ", {
            "SIESA_ID_MEDIO_PAGO_CONSIGNACION": "CONSIG_PRUEBA",
            "SIESA_ID_BANCO": "001", "SIESA_NRO_CUENTA": "30000003697",
            "SIESA_DOCTO_BANCO_CG": "CG", "SIESA_ID_FE": "1103",
        })
        self.env.start()
        with patch.dict("os.environ", {}, clear=True):
            base = RuntimeConfig.from_env()
        self.runtime = replace(
            base, allow_send=True, dry_run=False, send_cooldown_minutes=0,
            input_csv="samples/alegra_payments.csv", sheets_csv_url=None,
            state_file=self.root / "state.json", log_file=self.root / "audit.jsonl",
            siesa_connector_url="https://siesa.example/import", siesa_connikey="test-key",
            siesa_connitoken="test-token", siesa_id_compania="1",
        )
        self.mapping = MappingConfig.load(self.runtime.mapping_file)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def service(self, transport, runtime=None):
        service = PaymentSyncService(runtime or self.runtime, self.mapping)
        # Use the real configured client; replace only its network transport.
        service.client = service._client()
        service.client.transport = transport
        return service

    def test_timeout_defaults_to_120_and_can_be_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(RuntimeConfig.from_env().siesa_request_timeout_seconds, 120)
        with patch.dict("os.environ", {"SIESA_REQUEST_TIMEOUT_SECONDS": "180"}, clear=True):
            self.assertEqual(RuntimeConfig.from_env().siesa_request_timeout_seconds, 180)
        for invalid in ("0", "-1", "invalid"):
            with self.subTest(value=invalid), patch.dict("os.environ", {"SIESA_REQUEST_TIMEOUT_SECONDS": invalid}):
                with self.assertRaises(ValueError):
                    RuntimeConfig.from_env()

    def test_slow_response_can_finish_once_without_changing_payload_or_key(self):
        transport = SimulatedResponse(delay_seconds=45)
        result = self.service(transport).sync()
        self.assertEqual((result.sent, result.failed), (1, 0))
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0]["timeout"], 120)
        payment = read_csv_file(Path(self.runtime.input_csv), self.mapping)[0]
        self.assertEqual(json.loads(transport.calls[0]["body"]), build_payload(payment, self.mapping))
        self.assertEqual(transport.calls[0]["headers"]["Idempotency-Key"], payment.idempotency_key())
        saved = json.loads(self.runtime.state_file.read_text(encoding="utf-8"))
        self.assertFalse(saved["uncertain_receipts"])
        repeated = self.service(transport).sync()
        self.assertEqual(repeated.skipped_duplicates, 1)
        self.assertEqual(len(transport.calls), 1)

    def test_a_custom_short_timeout_preserves_the_uncertain_guard_without_retry(self):
        transport = SimulatedResponse(delay_seconds=45)
        runtime = replace(self.runtime, siesa_request_timeout_seconds=30)
        with patch("siesa_payments.sync.monotonic", side_effect=[100.0, 130.05]):
            first = self.service(transport, runtime).sync()
        self.assertEqual((first.sent, first.failed), (0, 1))
        diagnostic = first.failures[0]["siesa_response"]
        self.assertEqual(diagnostic["failure_kind"], "timeout")
        self.assertEqual(diagnostic["request_timeout_seconds"], 30)
        self.assertEqual(diagnostic["elapsed_seconds"], 30.05)
        second = self.service(transport, runtime).sync()
        self.assertEqual(second.failed, 1)
        self.assertEqual(len(transport.calls), 1)

    def test_failure_diagnostics_survive_restart_and_do_not_leak_exception_contents(self):
        cases = (
            (TimeoutError("private-token"), "timeout"),
            (URLError(TimeoutError("private-token")), "timeout"),
            (ConnectionResetError("https://secret.example/?token=private-token"), "connection_error"),
            (IncompleteRead(b"private-token", 50), "incomplete_response"),
            (RuntimeError("private-token"), "transport_error"),
        )
        for index, (error, kind) in enumerate(cases):
            with self.subTest(kind=kind, error_type=type(error).__name__):
                runtime = replace(self.runtime, state_file=self.root / f"state-{index}.json",
                                  log_file=self.root / f"audit-{index}.jsonl")
                transport = SimulatedResponse(error=error)
                with patch("siesa_payments.sync.monotonic", side_effect=[10.0, 130.0]):
                    result = self.service(transport, runtime).sync()
                diagnostic = result.failures[0]["siesa_response"]
                self.assertEqual(diagnostic["failure_kind"], kind)
                self.assertEqual(diagnostic["exception_type"], type(error).__name__)
                self.assertEqual(diagnostic["elapsed_seconds"], 120)
                saved = json.loads(runtime.state_file.read_text(encoding="utf-8"))
                stored = next(iter(saved["uncertain_receipts"].values()))
                self.assertEqual(stored["failure_kind"], kind)
                event = json.loads(runtime.log_file.read_text(encoding="utf-8").splitlines()[-1])
                self.assertEqual(event["siesa_response"], diagnostic)
                self.assertNotIn("private-token", runtime.state_file.read_text(encoding="utf-8"))
                self.assertNotIn("private-token", runtime.log_file.read_text(encoding="utf-8"))
                self.assertFalse(saved["processed_keys"])
                repeated = self.service(transport, runtime).sync()
                self.assertEqual(repeated.failed, 1)
                self.assertEqual(repeated.failures[0]["siesa_response"]["failure_kind"], kind)
                self.assertEqual(len(transport.calls), 1)

    def test_preexisting_unconfirmed_payments_are_not_unlocked_or_resent(self):
        payment = read_csv_file(Path(self.runtime.input_csv), self.mapping)[0]
        original = {"error": "Respuesta no confirmada; verificar en Siesa antes de reintentar.",
                    "timestamp": "2026-11-12T16:09:39+00:00", "source_row": payment.source_row}
        write_json_atomic(self.runtime.state_file, {"processed_keys": [],
                          "uncertain_receipts": {payment.idempotency_key(): original}})
        transport = SimulatedResponse()
        result = self.service(transport).sync()
        self.assertEqual((result.sent, result.failed), (0, 1))
        self.assertEqual(transport.calls, [])
        saved = json.loads(self.runtime.state_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["uncertain_receipts"][payment.idempotency_key()], original)
