from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from siesa_payments.jobs import SendJobs
from siesa_payments import web_server
from siesa_payments.state import write_json_atomic


class SendJobTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        self.jobs = SendJobs()
        self.release = threading.Event()
        self.entered = threading.Event()
        self.threads = []
        real_thread = threading.Thread

        def thread(*args, **kwargs):
            worker = real_thread(*args, **kwargs)
            self.threads.append(worker)
            return worker

        self.patch = patch("siesa_payments.jobs.threading.Thread", side_effect=thread)
        self.patch.start()

    def tearDown(self):
        self.release.set()
        for thread in self.threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.patch.stop()
        self.tmp.cleanup()

    def runner(self, progress):
        progress({"total": 109, "completed": 1, "sent": 1, "current_source_row": 4})
        self.entered.set()
        if not self.release.wait(timeout=3):
            raise TimeoutError("test worker not released")
        return {"mode": "send", "result": {"processed": 109, "sent": 109}}

    def finish(self):
        self.release.set()
        for worker in self.threads:
            worker.join(timeout=3)
        return self.jobs.status(self.state)

    def test_post_returns_202_before_siesa_finishes_and_repeated_click_reuses_job(self):
        handler = Mock(path="/api/sync/send?activator=alianza")
        with patch.object(web_server, "start_send", side_effect=lambda **kwargs:
                          self.jobs.start(self.state, "alianza", self.runner)):
            web_server.AppHandler.do_POST(handler)
        response = handler._json.call_args
        self.assertEqual(response.kwargs["status"].value, 202)
        self.assertTrue(self.entered.wait(timeout=2))
        job_id = response.args[0]["job"]["id"]
        # A different manager represents another request/process using the
        # same volume, rather than only a button disabled in this browser.
        other = SendJobs()
        ignored_runner = Mock()
        repeated = other.start(self.state, "alianza", ignored_runner)
        self.assertEqual(repeated["id"], job_id)
        ignored_runner.assert_not_called()
        self.assertEqual(other.status(self.state)["progress"]["sent"], 1)
        result = self.finish()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["outcome"]["result"]["sent"], 109)
        # The outcome survives a new manager/page, without another send.
        self.assertEqual(SendJobs().status(self.state), result)

    def test_abandoned_job_is_interrupted_and_is_never_automatically_replayed(self):
        write_json_atomic(self.jobs._path(self.state), {
            "id": "old", "status": "running", "progress": {"sent": 12},
        })
        recovered = SendJobs().status(self.state)
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["progress"]["sent"], 12)
        self.assertIn("Siesa antes de reintentar", recovered["error"])
        self.assertEqual(self.threads, [])

    def test_failure_releases_source_lock_and_retains_last_progress(self):
        def fail(progress):
            progress({"total": 2, "completed": 1, "sent": 1})
            raise RuntimeError("source unavailable")
        self.jobs.start(self.state, "alianza", fail)
        failed = self.finish()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["progress"]["sent"], 1)
        self.assertEqual(failed["error"], "source unavailable")
        following = self.jobs.start(self.state, "alianza", lambda p: {"result": {"sent": 0}})
        self.assertNotEqual(following["id"], failed["id"])
        self.assertEqual(self.finish()["status"], "completed")

    def test_sources_have_separate_workers_and_get_only_reads_status(self):
        self.jobs.start(self.state, "alianza", self.runner)
        other_state = self.state.with_name("lidera.json")
        other = self.jobs.start(other_state, "lidera", lambda p: {"result": {"sent": 0}})
        self.assertEqual(other["activator"], "lidera")
        self.assertTrue(self.entered.wait(timeout=2))
        runtime = Mock(state_file=self.state)
        handler = Mock(path="/api/sync/job?activator=alianza")
        with patch.object(web_server, "SEND_JOBS", self.jobs), patch.object(
                web_server, "_runtime_for_request", return_value=runtime):
            web_server.AppHandler.do_GET(handler)
        self.assertEqual(handler._json.call_args.args[0]["job"]["status"], "running")
        self.assertEqual(len(self.threads), 2)

    def test_failed_atomic_replace_preserves_previous_state(self):
        write_json_atomic(self.state, {"processed_keys": ["confirmed"]})
        with patch("siesa_payments.state.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                write_json_atomic(self.state, {"processed_keys": []})
        self.assertEqual(json.loads(self.state.read_text()), {"processed_keys": ["confirmed"]})
        self.assertEqual(list(self.state.parent.iterdir()), [self.state])
