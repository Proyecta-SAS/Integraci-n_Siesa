from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from siesa_payments.alegra import ACCOUNTS, AlegraActivators, AlegraError
from siesa_payments.database import Database


class AlegraTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Database('sqlite:///' + str(Path(self.temp.name) / 'db.sqlite'))
        self.db.initialize()
        self.now = 10000
        self.sender = Mock()
        self.endpoints = {key: 'https://example.test/' + key for key in ACCOUNTS}
        self.service = AlegraActivators(self.db, sender=self.sender, endpoints=self.endpoints, clock=lambda: self.now)

    def activate(self, key='alegra_antiguo'):
        return self.service.activate({'tipo': key, 'activador': 'ON'})

    def test_accounts_keep_original_payload_and_separate_webhooks(self):
        for key in ACCOUNTS:
            self.assertTrue(self.activate(key)['ok'])
            self.sender.assert_called_with(self.endpoints[key], {'activador': 'ON'})
        self.assertEqual(self.sender.call_count, 4)

    def test_cooldown_is_per_account_and_survives_a_new_service(self):
        self.activate()
        self.service = AlegraActivators(self.db, sender=self.sender, endpoints=self.endpoints, clock=lambda: self.now)
        with self.assertRaises(AlegraError) as caught:
            self.activate()
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.remaining, 900)
        self.activate('alegra_lidera')
        self.now += 900
        self.activate()
        self.assertEqual(self.sender.call_count, 3)

    def test_concurrent_requests_only_send_once(self):
        def attempt(_):
            try:
                return self.activate()['ok']
            except AlegraError as error:
                self.assertEqual(error.status, 429)
                return False
        with ThreadPoolExecutor(max_workers=5) as pool:
            self.assertEqual(sum(pool.map(attempt, range(5))), 1)
        self.sender.assert_called_once()

    def test_invalid_or_unconfigured_accounts_never_send(self):
        for payload in [None, [], {'tipo': []}, {'tipo': 'siesa', 'activador': 'ON'}, {'tipo': 'alegra_antiguo', 'activador': 'OFF'}]:
            with self.assertRaises(AlegraError):
                self.service.activate(payload)
        self.service.endpoints = {}
        with self.assertRaises(AlegraError) as caught:
            self.activate()
        self.assertEqual(caught.exception.status, 503)
        self.sender.assert_not_called()

    def test_uncertain_transport_does_not_report_success_or_allow_immediate_resend(self):
        self.sender.side_effect = TimeoutError('endpoint must not leak')
        with self.assertRaises(AlegraError) as caught:
            self.activate()
        self.assertEqual(caught.exception.status, 502)
        self.assertNotIn('endpoint must not leak', str(caught.exception))
        with self.assertRaises(AlegraError) as caught:
            self.activate()
        self.assertEqual(caught.exception.status, 429)
        self.sender.assert_called_once()

    def test_status_exposes_only_account_configuration_and_remaining_time(self):
        self.activate()
        data = self.service.status()
        self.assertEqual(len(data['accounts']), 4)
        self.assertEqual(data['accounts'][0]['retry_after_seconds'], 900)
        self.assertNotIn('example.test', str(data))
