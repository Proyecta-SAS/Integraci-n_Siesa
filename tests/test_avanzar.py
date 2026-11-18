from __future__ import annotations

import base64
import hashlib
import http.client
import json
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, Mock
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from joserfc import jwt
from joserfc.jwk import RSAKey, OctKey

from siesa_payments import web_server
from siesa_payments.application import Application
from siesa_payments.auth import Auth, COOKIE, digest_token, password_hash, verify_password
from siesa_payments.avanzar import IntegrationConfig, IntegrationError, Provisioning, resolve_identity
from siesa_payments.database import Database
from siesa_payments.oidc import OIDC, BoundedOAuthSession, FLOW_COOKIE, FLOW_SECONDS, MAX_PROVIDER_BYTES

EMAIL = 'persona@avanzarsoluciones.com'
CONFIG = IntegrationConfig(sso=True, embed=True, issuer='https://identity.example/realms/corporate',
    client_id='siesa-test', secret='test-only-oidc-secret', base_url='https://app.example',
    portal_origin='https://portal.example', return_url='https://portal.example/?abrir=SIESA_TEST',
    code='SIESA_TEST', domains=('avanzarsoluciones.com', 'avanzarsoluciones.co'),
    api_token='test-only-provisioning-credential-32-plus', profiles=('consulta', 'operador'))
DATA = {'correo': EMAIL, 'nombre': 'Persona de prueba', 'perfil_local': 'consulta', 'telefono': '3000000000'}


class IntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = RSAKey.generate_key(2048, parameters={'kid': 'test-key'})
        cls.jwks = {'keys': [cls.key.as_dict(private=False)]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database('sqlite:///' + str(Path(self.tmp.name) / 'test.db'))
        self.db.initialize()
        self.auth = Auth(self.db)
        self.provision = Provisioning(self.db, CONFIG)
        self.user_id = self.provision.create(DATA, 'setup')[1]['usuario']['id']
        self.oidc = OIDC(self.db, self.auth, CONFIG)
        self.claims = {'iss': CONFIG.issuer, 'aud': CONFIG.client_id, 'sub': 'Subject-A',
            'iat': int(time.time()), 'exp': int(time.time()) + 300,
            'nonce': 'nonce', 'email': EMAIL, 'email_verified': True}
        self.pending = {'nonce': 'nonce', 'created_at': int(time.time())}

    def tearDown(self):
        self.tmp.cleanup()

    def encode(self, claims=None, key=None, alg='RS256'):
        return jwt.encode({'alg': alg, 'kid': 'test-key'}, claims or self.claims, key or self.key)

    def test_config_is_disabled_by_default_and_rejects_arbitrary_returns(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(IntegrationConfig.from_env().sso)
        for changes in ({'return_url': 'https://evil.example'}, {'base_url': 'http://app.example'},
                        {'portal_origin': 'https://portal.example *'}, {'secret': ''},
                        {'api_token': CONFIG.secret}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(CONFIG, **changes).validate()

    def test_create_repeat_conflicts_and_no_local_password(self):
        status, body = self.provision.create({**DATA, 'correo': EMAIL.upper()}, 'retry')
        self.assertEqual(status, 200)
        self.assertEqual(body['usuario']['id'], self.user_id)
        self.assertFalse(body['usuario']['creado'])
        for changes in ({'nombre': 'Otra persona'}, {'perfil_local': 'operador'}, {'telefono': ''}):
            with self.subTest(changes=changes), self.assertRaises(IntegrationError) as caught:
                self.provision.create({**DATA, **changes}, 'conflict')
            self.assertEqual(caught.exception.status, 409)
        with self.db.transaction() as conn:
            row = conn.execute('SELECT * FROM app_users WHERE id=?', (self.user_id,)).fetchone()
            self.assertFalse(verify_password('test-only-password', row['password_hash']))
            conn.execute('UPDATE app_users SET active=0 WHERE id=?', (self.user_id,))
        with self.assertRaises(IntegrationError) as caught:
            self.provision.create(DATA, 'disabled')
        self.assertEqual(caught.exception.status, 409)

    def test_concurrent_creation_keeps_one_id(self):
        data = {**DATA, 'correo': 'concurrente@avanzarsoluciones.com'}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.provision.create(data, str(i)), range(4)))
        self.assertEqual(sorted(r[0] for r in results), [200, 200, 200, 201])
        self.assertEqual(len({r[1]['usuario']['id'] for r in results}), 1)

    def test_provisioning_rejects_extra_fields_forbidden_profiles_and_bad_data(self):
        for changes in ({'password': 'x'}, {'rol_id': 1}, {'email_verified': True}, {'token': 'x'},
                        {'permisos': []}, {'perfil_local': 'superadmin'}, {'nombre': 'x' * 121},
                        {'telefono': None}, {'correo': 'x@evil.example'}, {'correo': 'a..b@avanzarsoluciones.com'}):
            with self.subTest(changes=changes), self.assertRaises(IntegrationError) as caught:
                self.provision.create({**DATA, **changes}, 'invalid')
            self.assertEqual(caught.exception.status, 422)
        for profiles in ((), ('superadmin',)):
            with self.assertRaises(IntegrationError) as caught:
                Provisioning(self.db, replace(CONFIG, profiles=profiles)).create(DATA, 'unconfigured')
            self.assertEqual(caught.exception.status, 503)

    def test_claims_signature_algorithm_and_required_values(self):
        self.assertEqual(self.oidc.validate_token(self.encode(), self.jwks, self.pending), ('Subject-A', EMAIL))
        bad = [{'iss': 'https://evil.example'}, {'aud': 'other'}, {'aud': [CONFIG.client_id, 'other']},
               {'azp': 'other'}, {'exp': int(time.time()) - 1}, {'iat': int(time.time()) + 60},
               {'iat': int(time.time()) - 1000}, {'iat': True}, {'sub': ''}, {'sub': 17},
               {'nonce': 'wrong'}, {'email_verified': 'true'}, {'email_verified': False},
               {'email': ''}, {'email': 'x@evil.example'}, {'nbf': int(time.time()) + 120}]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(Exception):
                self.oidc.validate_token(self.encode({**self.claims, **change}), self.jwks, self.pending)
        for missing in ('iss', 'aud', 'sub', 'exp', 'iat', 'nonce', 'email', 'email_verified'):
            claims = {k: v for k, v in self.claims.items() if k != missing}
            with self.subTest(missing=missing), self.assertRaises(Exception):
                self.oidc.validate_token(self.encode(claims), self.jwks, self.pending)
        with self.assertRaises(Exception):
            self.oidc.validate_token(self.encode(key=RSAKey.generate_key(2048)), self.jwks, self.pending)
        with self.assertRaises(Exception):
            self.oidc.validate_token(self.encode(key=OctKey.generate_key(256), alg='HS256'), self.jwks, self.pending)
        claims = {**self.claims, 'aud': [CONFIG.client_id, 'other'], 'azp': CONFIG.client_id}
        self.oidc.validate_token(self.encode(claims), self.jwks, self.pending)

    def test_exact_identity_link_and_subsequent_email_change(self):
        with self.db.transaction(write=True) as conn:
            self.assertEqual(resolve_identity(conn, CONFIG.issuer, 'Subject-A', EMAIL)['id'], self.user_id)
            self.assertEqual(resolve_identity(conn, CONFIG.issuer, 'Subject-A', 'new@avanzarsoluciones.com')['id'], self.user_id)
            self.assertIsNone(resolve_identity(conn, CONFIG.issuer, 'subject-a', EMAIL))
            self.assertIsNone(resolve_identity(conn, CONFIG.issuer, 'Subject-B', EMAIL))
            self.assertIsNone(resolve_identity(conn, CONFIG.issuer, 'new', 'unknown@avanzarsoluciones.com'))
            conn.execute('UPDATE app_users SET active=0 WHERE id=?', (self.user_id,))
            self.assertIsNone(resolve_identity(conn, CONFIG.issuer, 'Subject-A', EMAIL))

    def provider(self, prepared, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.headers['Content-Type'] = 'application/json'
        if prepared.url.endswith('/.well-known/openid-configuration'):
            body = {'issuer': CONFIG.issuer, 'authorization_endpoint': CONFIG.issuer + '/auth',
                'token_endpoint': CONFIG.issuer + '/token', 'jwks_uri': CONFIG.issuer + '/jwks',
                'response_types_supported': ['code'], 'code_challenge_methods_supported': ['S256'],
                'id_token_signing_alg_values_supported': ['RS256'], 'token_endpoint_auth_methods_supported': ['client_secret_basic']}
        elif prepared.url.endswith('/token'):
            form = parse_qs(prepared.body)
            self.assertEqual(prepared.headers['Authorization'], 'Basic ' + base64.b64encode((CONFIG.client_id + ':' + CONFIG.secret).encode()).decode())
            self.assertEqual(form['redirect_uri'], [CONFIG.callback])
            self.assertEqual(form['grant_type'], ['authorization_code'])
            self.assertNotIn('client_secret', form)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
            if challenge != self.challenge:
                response.status_code = 400
                body = {'error': 'invalid_grant'}
            else:
                body = {'access_token': 'test-only-access', 'token_type': 'Bearer', 'id_token': self.encode()}
        elif prepared.url.endswith('/jwks'):
            body = self.jwks
        else:
            raise AssertionError('Unexpected provider URL')
        response._content = json.dumps(body).encode()
        response._content_consumed = True
        return response

    def start_flow(self):
        browser, csrf = self.oidc.prepare()
        url = self.oidc.begin(browser, csrf)
        params = parse_qs(urlparse(url).query)
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertEqual(params['scope'], ['openid email profile'])
        self.challenge = params['code_challenge'][0]
        self.claims['nonce'] = params['nonce'][0]
        return browser, urlencode({'code': 'test-code', 'state': params['state'][0]})

    def test_full_backend_flow_rotates_session_and_consumes_callback(self):
        with patch('requests.sessions.Session.send', side_effect=self.provider):
            browser, query = self.start_flow()
            result = OIDC(self.db, Auth(self.db), CONFIG).finish(browser, query)
            session = self.auth.session(COOKIE + '=' + result['token'])
            self.assertEqual(session['id'], self.user_id)
            self.assertEqual(session['profile'], 'consulta')
            with self.assertRaises(IntegrationError):
                self.oidc.finish(browser, query)
            browser, query = self.start_flow()
            result2 = self.oidc.finish(browser, query, session)
            self.assertNotEqual(result['csrf_token'], result2['csrf_token'])
            self.assertIsNone(self.auth.session(COOKIE + '=' + result['token']))
            with self.db.transaction() as conn:
                conn.execute('UPDATE app_users SET active=0 WHERE id=?', (self.user_id,))
            self.assertIsNone(self.auth.session(COOKIE + '=' + result2['token']))

    def test_csrf_state_browser_expiration_unexpected_callback_and_pkce_rejected(self):
        browser, csrf = self.oidc.prepare()
        with self.assertRaises(IntegrationError):
            self.oidc.begin(browser, 'wrong-csrf')
        with patch('requests.sessions.Session.send', side_effect=self.provider):
            for kind in ('state', 'browser', 'expired', 'duplicate', 'return', 'error', 'pkce'):
                with self.subTest(kind=kind):
                    browser, query = self.start_flow()
                    if kind == 'state': query = 'code=test-code&state=wrong'
                    if kind == 'browser': browser = 'another-browser'
                    if kind == 'expired':
                        with self.db.transaction() as conn:
                            conn.execute('UPDATE app_oidc_requests SET created_at=?', (int(time.time()) - FLOW_SECONDS,))
                    if kind == 'duplicate': query += '&code=another'
                    if kind == 'return': query += '&return=https://evil.example'
                    if kind == 'error': query += '&error=access_denied'
                    if kind == 'pkce': self.challenge = 'wrong-challenge'
                    with self.assertRaises(Exception):
                        self.oidc.finish(browser, query)

    def test_provider_responses_are_bounded_and_redirects_rejected(self):
        for status, content in ((302, b''), (200, b'x' * (MAX_PROVIDER_BYTES + 1))):
            response = requests.Response()
            response.status_code, response._content, response._content_consumed = status, content, True
            with patch('requests.sessions.Session.send', return_value=response), self.oidc.client() as client:
                with self.assertRaises(IntegrationError):
                    client.get(CONFIG.issuer, withhold_token=True)


class IntegrationHTTPTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = password_hash('test-only-password-2026')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'SIESA_ENV': 'qa', 'SIESA_BOOTSTRAP_ADMIN_EMAIL': EMAIL,
            'SIESA_BOOTSTRAP_ADMIN_PASSWORD_HASH': self.encoded, 'SIESA_STATE_FILE': str(Path(self.tmp.name) / 'state.json')})
        self.env.start()
        db = Database('sqlite:///' + str(Path(self.tmp.name) / 'app.db'))
        self.app = Application(web_server.ROOT, database=db, sources=[], background=False)
        self.app.integration = CONFIG
        self.app.provisioning = Provisioning(db, CONFIG)
        self.app.oidc = OIDC(db, self.app.auth, CONFIG)
        self.app_patch = patch.object(web_server, 'APPLICATION', self.app)
        self.app_patch.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), web_server.AppHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_api_contract_http_statuses_and_audit(self):
        path = '/api/v1/crear-usuarios'
        headers = {'Authorization': 'Bearer ' + CONFIG.api_token, 'Content-Type': 'application/json', 'X-Request-Id': 'test-001'}
        data = {**DATA, 'correo': 'new@avanzarsoluciones.com'}
        status, _, body = self.request('POST', path, json.dumps(data), headers)
        self.assertEqual(status, 201)
        user_id = json.loads(body)['usuario']['id']
        self.assertIsInstance(user_id, str)
        self.assertEqual(self.request('POST', path, json.dumps(data), headers)[0], 200)
        self.assertEqual(self.request('POST', path, json.dumps({**data, 'nombre': 'Cambio'}), headers)[0], 409)
        self.assertEqual(self.request('POST', path, '{}')[0], 401)
        self.assertEqual(self.request('POST', path, '{}', {**headers, 'Authorization': 'Bearer wrong'})[0], 401)
        self.assertEqual(self.request('POST', path, '{}', {**headers, 'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('POST', path, 'x' * (16384 + 1), headers)[0], 413)
        self.assertEqual(self.request('POST', path, '{', headers)[0], 422)
        self.assertEqual(self.request('POST', path, '{"correo":"a","correo":"b"}', headers)[0], 422)
        self.assertEqual(self.request('POST', path, json.dumps({**data, 'perfil_local': 'superadmin'}), headers)[0], 422)
        for method in ('GET', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'):
            self.assertEqual(self.request(method, path)[0], 405)
        self.app.provisioning.config = replace(CONFIG, profiles=())
        self.assertEqual(self.request('POST', path, json.dumps(data), headers)[0], 503)
        with patch.object(self.app.provisioning, 'create', side_effect=RuntimeError('secret SQL traceback')):
            status, _, body = self.request('POST', path, json.dumps(data), headers)
        self.assertEqual(status, 500)
        self.assertNotIn(b'SQL', body)
        with self.app.db.transaction() as conn:
            audits = [dict(row) for row in conn.execute('SELECT * FROM integration_audit').fetchall()]
        self.assertNotIn(CONFIG.api_token, json.dumps(audits))
        self.assertTrue(any(a['request_id'] == 'test-001' and a['user_id'] == user_id for a in audits))

    def test_embed_headers_direct_access_csrf_and_readonly_permissions(self):
        self.assertEqual(self.request('GET', '/resumen')[0], 303)
        status, headers, body = self.request('GET', '/resumen?portal_embed=1')
        self.assertEqual(status, 401)
        self.assertIn('frame-ancestors ' + CONFIG.portal_origin, headers['Content-Security-Policy'])
        self.assertNotIn('X-Frame-Options', headers)
        self.assertIn(b'target="_top"', body)
        with self.app.db.transaction() as conn:
            user = conn.execute('SELECT * FROM app_users WHERE email=?', (EMAIL,)).fetchone()
            conn.execute('INSERT INTO app_user_profiles(user_id,name,profile,phone) VALUES(?,?,?,?)',
                (user['id'], DATA['nombre'], 'consulta', ''))
            result = self.app.auth.create_session(conn, user)
        headers = {'Cookie': COOKIE + '=' + result['token'], 'Origin': CONFIG.base_url, 'X-CSRF-Token': result['csrf_token']}
        self.assertEqual(self.request('GET', '/resumen?portal_embed=1', headers=headers)[0], 200)
        for path in ('/api/sync/send', '/api/sync/dry-run', '/api/alegra/activate'):
            self.assertEqual(self.request('POST', path, headers=headers)[0], 403)
        self.assertEqual(self.request('POST', '/api/auth/logout', headers={**headers, 'X-CSRF-Token': 'bad'})[0], 403)
        self.assertEqual(self.request('POST', '/api/auth/logout', headers=headers)[0], 200)
        self.assertEqual(self.request('GET', '/api/auth/me', headers=headers)[0], 401)

    def test_start_is_csrf_protected_post_and_return_is_exact(self):
        status, headers, body = self.request('GET', '/portal/iniciar-sso')
        self.assertEqual(status, 200)
        self.assertIn('Secure', headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', headers['Set-Cookie'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertIn(b'method="post"', body)
        self.assertEqual(self.request('POST', '/sso/iniciar', 'csrf=bad', {'Origin': CONFIG.base_url, 'Content-Type': 'application/x-www-form-urlencoded'})[0], 403)
        self.assertEqual(self.request('GET', '/sso/iniciar')[0], 405)
        self.assertEqual(self.request('GET', '/portal/iniciar-sso?next=https://evil.example')[0], 400)
        self.assertEqual(self.request('GET', '/sso/callback?code=x&state=y')[0], 400)
        self.assertEqual(self.request('GET', '/portal/volver')[1]['Location'], CONFIG.portal_origin + '/')
        result = self.app.auth.login(EMAIL, 'test-only-password-2026')
        cookie = COOKIE + '=' + result['token']
        self.assertEqual(self.request('GET', '/portal/iniciar-sso', headers={'Cookie': cookie})[1]['Location'], CONFIG.return_url)
        status, headers, _ = self.request('POST', '/api/auth/login', json.dumps({'email': EMAIL, 'password': 'test-only-password-2026'}),
            {'Origin': CONFIG.base_url, 'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        for attribute in ('Secure', 'HttpOnly', 'SameSite=None'):
            self.assertIn(attribute, headers['Set-Cookie'])
