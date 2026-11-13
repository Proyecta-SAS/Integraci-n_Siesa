from __future__ import annotations
import hashlib
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from siesa_payments.database import Database, DatabaseUnavailable
from siesa_payments.ledger import Archive, Ledger


class LedgerTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database('sqlite:///' + str(self.root / 'app.sqlite3'))
        self.db.initialize()
        self.log = self.root / 'audit.jsonl'
        self.state = self.root / 'state.json'
        self.archive = Archive(self.db, [(self.log, 'alianza', 'audit'), (self.state, 'alianza', 'state')], self.root / 'backups')
        self.ledger = Ledger(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, key, status='sent', **kwargs):
        return {'idempotency_key': key, 'status': status, 'timestamp': '2026-11-12T16:00:00Z',
                'identity_number': '123', 'amount': '1000.00', 'payment_date': '2026-11-11',
                'note': 'Pago', **kwargs}

    def write(self, events):
        self.log.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')

    def test_recovery_is_repeatable_without_resending_or_modifying_sources(self):
        self.write([self.event('a'), self.event('a', 'duplicate'), self.event('b', 'unconfirmed')])
        self.state.write_text(json.dumps({'processed_keys': ['a', 'old-key'], 'uncertain_receipts': {'b': {'error': 'pending'}}}), encoding='utf-8')
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.log, self.state)}
        self.archive.refresh()
        first = self.ledger.query()
        self.assertEqual(first['total'], 3)
        self.assertEqual(first['summary']['confirmed'], 2)
        self.assertEqual(first['summary']['unconfirmed'], 1)
        self.assertEqual(first['avoided_resends'], 1)
        self.assertEqual(first['summary']['without_receipt_number'], 2)
        self.archive.refresh()
        self.assertEqual(self.ledger.query()['total'], 3)
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual(len(list((self.root / 'backups').iterdir())), 2)

    def test_possible_duplicates_are_candidates_and_stay_confirmed(self):
        self.write([self.event('a'), self.event('b', possible_duplicate=True, duplicate_of=2), self.event('c', note='Pago distinto')])
        self.archive.refresh()
        result = self.ledger.query(duplicate_only=True)
        self.assertEqual(result['total'], 2)
        self.assertTrue(all(r['status'] == 'confirmed' and r['possible_duplicate'] for r in result['rows']))
        self.assertEqual(self.ledger.query()['summary']['confirmed'], 3)
        self.assertEqual(self.ledger.query(search='Pago distinto')['total'], 1)
        self.assertEqual(self.ledger.query(search="' OR 1=1 --")['total'], 0)

    def test_audit_duplicates_and_overlapping_backups_are_not_new_receipts(self):
        event = self.event('a', siesa_response={'documento': 'RC-17'})
        self.write([event, event, self.event('a', 'duplicate')])
        other = self.root / 'copy.jsonl'
        other.write_bytes(self.log.read_bytes())
        self.archive.sources.append((other, 'alianza', 'audit'))
        self.archive.refresh()
        result = self.ledger.query()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['rows'][0]['receipt_number'], 'RC-17')
        self.assertEqual(result['avoided_resends'], 1)
        self.assertEqual(result['summary']['possible_duplicates'], 0)

    def test_partial_append_is_recovered_and_corrupt_lines_are_reported(self):
        complete = json.dumps(self.event('a')) + '\n'
        partial = json.dumps(self.event('b'))
        self.log.write_text(complete + partial[:30], encoding='utf-8')
        self.archive.refresh()
        self.assertEqual(self.ledger.query()['total'], 1)
        with self.log.open('a', encoding='utf-8') as output:
            output.write(partial[30:] + '\nnot-json\n' + json.dumps(self.event('c')))
        self.archive.refresh()
        result = self.ledger.query()
        self.assertEqual(result['total'], 3)
        self.assertEqual(result['import_issues'], 1)
        self.archive.refresh()
        self.assertEqual(self.ledger.query()['total'], 3)

    def test_simulations_are_retained_as_evidence_without_claiming_receipts(self):
        self.write([self.event('simulated', 'dry_run'), self.event('a', 'failed')])
        self.archive.refresh()
        result = self.ledger.query()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['summary']['rejected'], 1)
        with self.db.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM ledger_events').fetchone()['n'], 2)

    def test_import_rollback_can_resume_after_database_failure(self):
        self.write([self.event('a'), self.event('b')])
        original = self.archive.ledger.import_event
        calls = 0
        def fail(conn, *args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('simulated database failure')
            return original(conn, *args)
        with patch.object(self.archive.ledger, 'import_event', side_effect=fail):
            with self.assertRaises(DatabaseUnavailable):
                self.archive.refresh()
        self.assertEqual(self.ledger.query()['total'], 0)
        self.archive.refresh()
        self.assertEqual(self.ledger.query()['total'], 2)

    def test_confirmed_history_is_not_downgraded_by_later_failed_attempt(self):
        self.write([self.event('a'), self.event('a', 'failed', timestamp='2026-11-13T01:00:00Z')])
        self.archive.refresh()
        self.assertEqual(self.ledger.query()['rows'][0]['status'], 'confirmed')

    def test_postgres_is_required_in_production(self):
        with patch.dict('os.environ', {'SIESA_ENV': 'prod', 'SIESA_DATABASE_URL': 'sqlite:///local.db'}):
            with self.assertRaises(ValueError):
                Database.from_env()

    def test_recovers_notes_and_method_from_the_validated_legacy_payload(self):
        self.write([self.event('a', note='', payload={
            'RCyotrosingresos': [{'F350_NOTAS': 'Referencia original'}],
            'Caja': [{'F358_ID_MEDIOS_PAGO': 'CONSIG'}],
        })])
        self.archive.refresh()
        row = self.ledger.query()['rows'][0]
        self.assertEqual(row['note'], 'Referencia original')
        self.assertEqual(row['method'], 'CONSIG')

    def test_sources_are_recovered_separately_and_candidates_do_not_cross_companies(self):
        self.write([self.event('same-key')])
        other = self.root / 'other.jsonl'
        other.write_bytes(self.log.read_bytes())
        self.archive.sources.append((other, 'lidera', 'audit'))
        self.archive.refresh()
        self.assertEqual(self.ledger.query()['total'], 2)
        self.assertEqual(self.ledger.query()['summary']['possible_duplicates'], 0)
        self.assertEqual(self.ledger.query(activator='lidera')['total'], 1)
