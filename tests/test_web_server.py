from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from siesa_payments import web_server
from siesa_payments.config import RuntimeConfig
from siesa_payments.source import read_csv_text


class WebServerAuditTests(TestCase):
    def test_preview_excludes_confirmed_payments_and_flags_matching_notes(self) -> None:
        csv_text = (
            "Cuenta bancaria,Fecha,Contacto,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,Nota\n"
            "BANCOLOMBIA,03/11/2026,Consumidor Final,Ingreso,Transferencia,28050505,1,1250872,Primer pago\n"
            "BANCOLOMBIA,03/11/2026,Consumidor Final,Ingreso,Transferencia,28050505,1,1250872,Primer pago\n"
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"SIESA_RECIBO_FLUJO": "otros_ingresos"}):
            root = Path(tmp)
            source = root / "source.csv"
            source.write_text(csv_text, encoding="utf-8")
            runtime = replace(RuntimeConfig.from_env(), input_csv=str(source), state_file=root / "state.json")
            mapping = web_server.MappingConfig.load(runtime.mapping_file)
            key = read_csv_text(csv_text, mapping)[0].idempotency_key()
            runtime.state_file.write_text(json.dumps({"processed_keys": [key]}), encoding="utf-8")
            with patch.object(web_server, "_runtime_for_request", return_value=runtime), patch.object(
                web_server, "_redacted_runtime", return_value={"ready_to_send": True, "send_unlocked": True}
            ):
                before = web_server.preflight()
                self.assertEqual(before["rows"][1]["duplicate_of"], 2)
                self.assertTrue(before["rows"][0]["already_sent"])
                self.assertEqual(before["preflight"]["ready_rows"], 0)
                self.assertEqual(before["preflight"]["duplicate_rows"], [3])
                self.assertEqual(before["preflight"]["invalid_rows"], [])
                # Change only the second note; the confirmed payment remains untouched.
                source.write_text(csv_text.rsplit("Primer pago", 1)[0] + "Segundo pago confirmado\n", encoding="utf-8")
                after = web_server.preflight()
            self.assertEqual(after["rows"][1]["note"], "Segundo pago confirmado")
            self.assertIsNone(after["rows"][1]["duplicate_of"])
            self.assertTrue(after["rows"][1]["ready"])
            self.assertFalse(after["rows"][0]["ready"])
            self.assertEqual(after["preflight"]["ready_rows"], 1)
            self.assertEqual(after["preflight"]["total_ready_amount"], "1250872")
            self.assertEqual(after["preflight"]["already_sent_rows"], [2])

    def test_reads_recent_failed_events_without_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_file = root / "siesa_payments.jsonl"
            log_file.write_text(
                "\n".join(
                    [
                        "not-json",
                        json.dumps({"status": "sent", "source_row": 1, "payload": {"secret": "x"}}),
                        json.dumps(
                            {
                                "status": "failed",
                                "timestamp": "2026-10-19T13:50:52+00:00",
                                "source_row": 2,
                                "identity_number": "1000033853",
                                "amount": "1000",
                                "payment_date": "2026-06-30",
                                "siesa_status_code": 400,
                                "siesa_response": {"mensaje": "Documento cruce no existe"},
                                "payload": {"F_SECRET": "no debe salir"},
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch.object(web_server, "ROOT", root),
                patch.dict("os.environ", {"SIESA_LOG_FILE": str(log_file)}, clear=True),
            ):
                events = web_server._audit_events(limit=10, event_type="failed")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_row"], 2)
        self.assertEqual(events[0]["siesa_status_code"], 400)
        self.assertEqual(events[0]["timestamp"], "2026-10-19T13:50:52+00:00")
        self.assertEqual(events[0]["siesa_response"]["mensaje"], "Documento cruce no existe")
        self.assertNotIn("payload", events[0])

    def test_health_reports_deployed_version(self) -> None:
        handler = Mock(path="/health")
        web_server.AppHandler.do_GET(handler)
        self.assertEqual(handler._json.call_args.args[0], {
            "ok": True, "service": "activadores-siesa", "version": web_server.__version__,
        })

    def test_other_income_mode_does_not_require_cxc_cross(self) -> None:
        class Payment:
            cross_document_type = ""
            cross_document_number = ""
            cross_installment = ""
            cross_co = ""
            cross_un = ""
            cross_branch = ""
            cross_auxiliary = ""
            cross_document = "FVE-00000006-00"

        with patch.dict("os.environ", {"SIESA_RECIBO_FLUJO": "otros_ingresos"}, clear=True):
            cross_ready, cross_source = web_server._cross_status(Payment())
            cross_document = web_server._siesa_cross_document(Payment())
            cross_auxiliary = web_server._siesa_cross_auxiliary(Payment())

        self.assertTrue(cross_ready)
        self.assertEqual(cross_source, "otros_ingresos")
        self.assertEqual(cross_document, "Otro ingreso 28050505")
        self.assertEqual(cross_auxiliary, "28050505")
