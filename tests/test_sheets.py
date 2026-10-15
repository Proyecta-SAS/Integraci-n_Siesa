from __future__ import annotations

import csv
import io
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from siesa_payments.config import MappingConfig, RuntimeConfig
from siesa_payments.sheets import (
    LOADED, NEEDS_CORRECTION, PENDING, SheetStatusWriter, SheetWriteError, writer_for_runtime,
)
from siesa_payments.siesa_hub import SiesaHubClient, SiesaResponse
from siesa_payments.sync import PaymentSyncService


class SheetTransportTests(TestCase):
    def test_sends_authenticated_row_snapshot_and_checks_application_error(self):
        transport = Mock()
        transport.request.return_value = (200, {}, b'{"ok":true}')
        writer = SheetStatusWriter("https://script.google.com/macros/s/example/exec", "secret", "book", 17, transport)
        writer.write(3, ("x",) * 11, NEEDS_CORRECTION, error="fecha invalida")
        method, url, headers, body, timeout = transport.request.call_args.args
        payload = json.loads(body)
        self.assertEqual((method, payload["spreadsheet_id"], payload["sheet_id"]), ("POST", "book", 17))
        self.assertEqual(payload["token"], "secret")
        self.assertEqual(payload["source_cells"], ["x"] * 11)
        self.assertEqual(payload["error"], "fecha invalida")
        transport.request.return_value = (200, {}, b'{"ok":false,"error":"La fila cambio"}')
        with self.assertRaisesRegex(SheetWriteError, "La fila cambio"):
            writer.write(3, ("x",) * 11, PENDING)
        transport.request.return_value = (200, {}, b'<html>Login</html>')
        with self.assertRaisesRegex(SheetWriteError, "no devolvio JSON"):
            writer.write(3, ("x",) * 11, PENDING)

    def test_destination_comes_from_each_activator_source(self):
        definitions = json.loads(Path("config/siesa_activators.json").read_text())["activators"]
        with patch.dict("os.environ", {
            "SIESA_SHEETS_WRITEBACK_ENABLED": "true",
            "SIESA_SHEETS_WEBHOOK_URL": "https://script.google.com/macros/s/example/exec",
            "SIESA_SHEETS_WEBHOOK_TOKEN": "secret",
        }, clear=True):
            runtime = RuntimeConfig.from_env()
        for definition in definitions.values():
            writer = writer_for_runtime(replace(runtime, sheets_csv_url=definition["csv_export_url"]))
            self.assertEqual(writer.spreadsheet_id, definition["spreadsheet_id"])
            self.assertEqual(writer.sheet_id, definition["sheet_id"])
        with self.assertRaisesRegex(ValueError, "CSV local"):
            writer_for_runtime(replace(runtime, input_csv="payments.csv"))
        self.assertIsNone(writer_for_runtime(replace(runtime, sheets_writeback_enabled=False)))

    def test_disallows_sending_secret_to_other_hosts(self):
        for url in ("https://example.com/exec", "http://script.google.com/macros/s/x/exec",
                    "https://script.google.com.evil.test/macros/s/x/exec"):
            with self.assertRaises(ValueError):
                SheetStatusWriter(url, "secret", "book", 0)

    def test_http_200_with_import_error_is_not_loaded(self):
        client = SiesaHubClient("https://example.com", "key", "token", "1", "142888", "Recibo")
        self.assertFalse(client._decode(200, b'{"codigo":1,"mensaje":"Rechazado"}').ok)
        self.assertTrue(client._decode(200, b'{"codigo":0,"mensaje":"Transaccion Exitosa"}').ok)


class SheetSyncTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.csv_path = root / "payments.csv"
        self.csv_path.write_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), encoding="utf-8")
        env = patch.dict("os.environ", {
            "SIESA_ID_MEDIO_PAGO_CONSIGNACION": "CONSIG_PRUEBA",
            "SIESA_ID_BANCO": "001", "SIESA_NRO_CUENTA": "123",
            "SIESA_DOCTO_BANCO_CG": "CG", "SIESA_ID_FE": "1103",
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.runtime = replace(RuntimeConfig.from_env(), input_csv=str(self.csv_path),
                               dry_run=False, allow_send=True, send_cooldown_minutes=0,
                               state_file=root / "state.json", log_file=root / "audit.jsonl")
        self.mapping = MappingConfig.load(self.runtime.mapping_file)
        self.hub = Mock()
        self.hub.register_cash_receipt.return_value = SiesaResponse(200, True, {"documento": "RC-17"}, "")
        self.writer = Mock(spec=SheetStatusWriter)

    def service(self):
        return PaymentSyncService(self.runtime, self.mapping, self.hub, self.writer)

    def rows(self):
        return list(csv.reader(io.StringIO(self.csv_path.read_text(encoding="utf-8"))))

    def save_rows(self, rows):
        output = io.StringIO()
        csv.writer(output, lineterminator="\n").writerows(rows)
        self.csv_path.write_text(output.getvalue(), encoding="utf-8")

    def statuses(self):
        return [call.args[2] for call in self.writer.write.call_args_list]

    def test_success_then_duplicate_repairs_status_without_resend(self):
        first = self.service().sync()
        self.assertEqual((first.sent, first.sheet_updates), (1, 2))
        self.assertEqual(self.statuses(), [PENDING, LOADED])
        self.writer.reset_mock()
        second = self.service().sync()
        self.assertEqual(second.skipped_duplicates, 1)
        self.assertEqual(self.hub.register_cash_receipt.call_count, 1)
        self.assertEqual(self.statuses(), [LOADED])
        self.assertEqual(self.writer.write.call_args.kwargs["receipt"], "RC-17")
        self.assertTrue(self.writer.write.call_args.kwargs["sent_at"])

    def test_failure_stays_pending_and_corrected_retry_can_send(self):
        self.hub.register_cash_receipt.return_value = SiesaResponse(400, False, {"mensaje": "Tercero no existe"}, "")
        result = self.service().sync()
        self.assertEqual(result.failed, 1)
        self.assertEqual(self.statuses(), [PENDING, NEEDS_CORRECTION])
        self.assertIn("Tercero no existe", self.writer.write.call_args.kwargs["error"])
        self.hub.register_cash_receipt.return_value = SiesaResponse(200, True, {"documento": "RC-18"}, "")
        self.assertEqual(self.service().sync().sent, 1)

    def test_missing_required_data_is_pending_without_calling_siesa(self):
        rows = self.rows()
        rows[1][6] = ""
        self.save_rows(rows)
        result = self.service().sync()
        self.assertEqual(result.invalid, 1)
        self.assertEqual(self.statuses(), [NEEDS_CORRECTION])
        self.hub.register_cash_receipt.assert_not_called()

    def test_invalid_date_does_not_block_later_receipt(self):
        rows = self.rows()
        invalid = rows[1].copy()
        invalid[1] = "fecha incorrecta"
        rows.insert(1, invalid)
        self.save_rows(rows)
        result = self.service().sync()
        self.assertEqual((result.processed, result.invalid, result.sent), (2, 1, 1))
        self.assertEqual(self.writer.write.call_args_list[0].args[0], 2)
        self.assertEqual(self.writer.write.call_args_list[-1].args[0], 3)

    def test_invalid_amount_and_unselected_errors_are_isolated(self):
        rows = self.rows()
        invalid = rows[1].copy()
        invalid[8] = "valor incorrecto"
        rows.append(invalid)
        self.save_rows(rows)
        result = self.service().sync(source_rows={3})
        self.assertEqual((result.processed, result.invalid, result.sent), (1, 1, 0))
        self.assertEqual(self.writer.write.call_args.args[0], 3)
        self.hub.register_cash_receipt.assert_not_called()

    def test_invalid_unselected_row_does_not_get_a_status(self):
        rows = self.rows()
        invalid = rows[1].copy()
        invalid[1] = "fecha incorrecta"
        rows.insert(1, invalid)
        self.save_rows(rows)
        result = self.service().sync(source_rows={3})
        self.assertEqual((result.processed, result.invalid, result.sent), (1, 0, 1))
        self.assertTrue(all(call.args[0] == 3 for call in self.writer.write.call_args_list))

    def test_missing_send_configuration_is_pending_for_correction(self):
        with patch.dict("os.environ", {"SIESA_ID_FE": ""}):
            result = self.service().sync()
        self.assertEqual(result.invalid, 1)
        self.assertEqual(self.statuses(), [NEEDS_CORRECTION])
        self.assertIn("SIESA_ID_FE", self.writer.write.call_args.kwargs["error"])
        self.hub.register_cash_receipt.assert_not_called()

    def test_invalid_connector_url_is_not_treated_as_an_uncertain_send(self):
        self.hub.connection_summary.side_effect = RuntimeError("configure SIESA_CONNECTOR_URL")
        result = self.service().sync()
        self.assertEqual((result.invalid, result.failed), (1, 0))
        self.assertEqual(self.statuses(), [NEEDS_CORRECTION])
        self.hub.register_cash_receipt.assert_not_called()

    def test_dry_run_never_writes_even_for_invalid_rows(self):
        rows = self.rows()
        invalid = rows[1].copy()
        invalid[1] = ""
        rows.append(invalid)
        self.save_rows(rows)
        result = self.service().sync(dry_run=True)
        self.assertEqual((result.dry_run, result.invalid), (1, 1))
        self.writer.write.assert_not_called()
        self.hub.register_cash_receipt.assert_not_called()

    def test_failed_pending_write_prevents_send(self):
        self.writer.write.side_effect = SheetWriteError("La fila cambio")
        result = self.service().sync()
        self.assertEqual((result.sent, result.failed, len(result.sheet_errors)), (0, 1, 1))
        self.hub.register_cash_receipt.assert_not_called()

    def test_failed_final_write_keeps_state_and_next_activation_repairs(self):
        def fail_final(*args, **kwargs):
            if args[2] == LOADED:
                raise SheetWriteError("sin conexion")
        self.writer.write.side_effect = fail_final
        first = self.service().sync()
        self.assertEqual((first.sent, len(first.sheet_errors)), (1, 1))
        state = json.loads(self.runtime.state_file.read_text())
        self.assertEqual(len(state["processed_keys"]), 1)
        self.writer.write.side_effect = None
        self.writer.reset_mock()
        second = self.service().sync()
        self.assertEqual(second.skipped_duplicates, 1)
        self.assertEqual(self.statuses(), [LOADED])
        self.assertEqual(self.hub.register_cash_receipt.call_count, 1)

    def test_unconfirmed_response_is_pending_and_not_resent(self):
        self.hub.register_cash_receipt.side_effect = TimeoutError("timed out")
        first = self.service().sync()
        self.assertEqual(first.failed, 1)
        self.assertEqual(self.statuses(), [PENDING, PENDING])
        self.assertIn("verificar en Siesa", self.writer.write.call_args.kwargs["error"])
        second = self.service().sync()
        self.assertEqual(second.failed, 1)
        self.assertEqual(self.hub.register_cash_receipt.call_count, 1)

    def test_without_webhook_configuration_preserves_existing_send_flow(self):
        result = PaymentSyncService(self.runtime, self.mapping, self.hub).sync()
        self.assertEqual((result.sent, result.sheet_updates, result.sheet_errors), (1, 0, ()))
