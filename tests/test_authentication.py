from __future__ import annotations
import http.client
import json
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from siesa_payments import web_server
from siesa_payments.application import Application
from siesa_payments.auth import Auth, COOKIE, SESSION_SECONDS, password_hash, verify_password
from siesa_payments.database import Database

PASSWORD = 'Test-only-Long-Password-2026'
EMAIL = 'admin@example.test'


class AuthenticationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = password_hash(PASSWORD)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database('sqlite:///' + str(self.root / 'app.sqlite3'))
        self.db.initialize()
        self.auth = Auth(self.db)
        self.auth.bootstrap(EMAIL, self.encoded)

    def tearDown(self):
        self.tmp.cleanup()

    def test_password_hash_and_bootstrap_do_not_expose_or_reset_credentials(self):
        self.assertNotIn(PASSWORD, self.encoded)
        self.assertTrue(verify_password(PASSWORD, self.encoded))
        self.assertFalse(verify_password('wrong', self.encoded))
        self.assertFalse(self.auth.bootstrap('another@example.test', password_hash('Other-Long-Password-2026')))
        self.assertIsNotNone(self.auth.login(EMAIL.upper(), PASSWORD))

    def test_sessions_are_hashed_expire_and_are_revoked_on_logout(self):
        result = self.auth.login(EMAIL, PASSWORD)
        cookie = COOKIE + '=' + result['token']
        session = Auth(self.db).session(cookie)
        self.assertEqual(session['email'], EMAIL)
        with self.db.transaction() as conn:
            self.assertNotEqual(conn.execute('SELECT token_hash FROM app_sessions').fetchone()['token_hash'], result['token'])
        self.assertTrue(self.auth.valid_csrf(session, result['csrf_token']))
        self.assertFalse(self.auth.valid_csrf(session, 'wrong'))
        with patch('siesa_payments.auth.time.time', return_value=time.time() + SESSION_SECONDS + 1):
            self.assertIsNone(self.auth.session(cookie))
        self.auth.logout(session)
        self.assertIsNone(self.auth.session(cookie))

    def test_login_failures_are_limited_and_account_recovers_after_window(self):
        for _ in range(5):
            self.assertIsNone(self.auth.login(EMAIL, 'wrong'))
        self.assertIsNone(self.auth.login(EMAIL, PASSWORD))
        with patch('siesa_payments.auth.time.time', return_value=time.time() + 901):
            self.assertIsNotNone(self.auth.login(EMAIL, PASSWORD))


class AuthenticationHTTPTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = password_hash(PASSWORD)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict('os.environ', {'SIESA_ENV': 'qa', 'SIESA_STATE_FILE': str(self.root / 'state.json'),
            'SIESA_BOOTSTRAP_ADMIN_EMAIL': EMAIL, 'SIESA_BOOTSTRAP_ADMIN_PASSWORD_HASH': self.encoded})
        self.env.start()
        db = Database('sqlite:///' + str(self.root / 'app.sqlite3'))
        app = Application(web_server.ROOT, database=db, sources=[], background=False)
        self.app_patch = patch.object(web_server, 'APPLICATION', app)
        self.app_patch.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), web_server.AppHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, method, path, data=None, cookie='', csrf='', origin=None):
        headers = {'Cookie': cookie}
        if origin is not None:
            headers['Origin'] = origin
        if csrf:
            headers['X-CSRF-Token'] = csrf
        body = None
        if data is not None:
            body = json.dumps(data)
            headers['Content-Type'] = 'application/json'
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        conn.close()
        return result

    def login(self):
        status, headers, raw = self.request('POST', '/api/auth/login', {'email': EMAIL, 'password': PASSWORD}, origin=self.origin)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        return headers['Set-Cookie'].split(';')[0], data['csrf_token']

    def test_all_operational_and_history_pages_require_login(self):
        for path in ('/resumen', '/resultados', '/pagos', '/integracion', '/historico', '/app.js', '/history.js'):
            status, headers, _ = self.request('GET', path)
            self.assertEqual(status, 303, path)
            self.assertTrue(headers['Location'].startswith('/login?'))
        for path in ('/api/status', '/api/payments', '/api/preflight', '/api/audit', '/api/history', '/api/sync/job'):
            self.assertEqual(self.request('GET', path)[0], 401, path)
        self.assertEqual(self.request('GET', '/login')[0], 200)
        self.assertEqual(self.request('GET', '/health')[0], 200)

    def test_csrf_and_origin_are_checked_before_any_send(self):
        cookie, csrf = self.login()
        with patch.object(web_server, 'start_send', return_value={'id': 'test-job', 'status': 'queued'}) as send:
            self.assertEqual(self.request('POST', '/api/sync/send')[0], 401)
            self.assertEqual(self.request('POST', '/api/sync/send', cookie=cookie, origin=self.origin)[0], 403)
            self.assertEqual(self.request('POST', '/api/sync/send', cookie=cookie, csrf=csrf, origin='https://evil.example')[0], 403)
            send.assert_not_called()
            self.assertEqual(self.request('POST', '/api/sync/send', cookie=cookie, csrf=csrf, origin=self.origin)[0], 202)
            send.assert_called_once()
        self.assertEqual(self.request('POST', '/api/auth/logout', cookie=cookie, csrf=csrf, origin=self.origin)[0], 200)
        self.assertEqual(self.request('GET', '/api/history', cookie=cookie)[0], 401)

    def test_login_cookie_routes_and_history_are_private(self):
        with patch.dict('os.environ', {'SIESA_ENV': 'prod'}):
            status, headers, _ = self.request('POST', '/api/auth/login', {'email': EMAIL, 'password': PASSWORD}, origin=self.origin)
            self.assertEqual(status, 200)
            for attribute in ('HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/'):
                self.assertIn(attribute, headers['Set-Cookie'])
        cookie, _ = self.login()
        for path in ('/resumen', '/resultados', '/pagos', '/integracion', '/historico'):
            status, headers, _ = self.request('GET', path, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Cache-Control'], 'no-store')
        status, _, raw = self.request('GET', '/api/history?duplicates=1', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['total'], 0)
        self.assertEqual(self.request('GET', '/pagina-inexistente', cookie=cookie)[0], 404)

    def test_login_rejects_cross_origin_and_sql_injection(self):
        credentials = {'email': EMAIL, 'password': PASSWORD}
        self.assertEqual(self.request('POST', '/api/auth/login', credentials, origin='https://evil.example')[0], 403)
        self.assertEqual(self.request('POST', '/api/auth/login', {'email': "' OR 1=1 --", 'password': PASSWORD}, origin=self.origin)[0], 401)
