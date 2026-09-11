from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from siesa_payments import web_server


class WebServerAuditTests(TestCase):
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
        self.assertEqual(events[0]["siesa_response"]["mensaje"], "Documento cruce no existe")
        self.assertNotIn("payload", events[0])
