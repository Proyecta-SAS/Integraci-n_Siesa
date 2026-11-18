"""Backend Authorization Code + PKCE. Pending flows and sessions live in SQL."""
from __future__ import annotations

import hmac
import secrets
import time
import json
from urllib.parse import parse_qs, urlparse

from authlib.integrations.requests_client import OAuth2Session
from joserfc import jwt
from joserfc.jwk import KeySet

from .auth import digest_token
from .avanzar import IntegrationError, corporate_email, https_url, resolve_identity

FLOW_SECONDS = 600
FLOW_COOKIE = '__Host-avanzar_oidc'
MAX_PROVIDER_BYTES = 256 * 1024


class BoundedOAuthSession(OAuth2Session):
    def request(self, method, url, **kwargs):
        kwargs.update(timeout=(3, 5), allow_redirects=False, stream=True)
        started = time.monotonic()
        response = super().request(method, url, **kwargs)
        try:
            if response.status_code != 200:
                raise IntegrationError('El proveedor no pudo completar la autenticacion', 502)
            content = bytearray()
            # Single-byte reads check the wall-clock deadline even on slow trickles.
            # One blocked read may exceed the deadline by at most the read timeout.
            for chunk in response.iter_content(chunk_size=1):
                content.extend(chunk)
                if len(content) > MAX_PROVIDER_BYTES or time.monotonic() - started > 15:
                    raise IntegrationError('Respuesta del proveedor fuera de limites', 502)
            response._content = bytes(content)
            response._content_consumed = True
            return response
        finally:
            response.close()


class OIDC:
    def __init__(self, db, auth, config):
        self.db, self.auth, self.config = db, auth, config

    def client(self, state=None):
        client = BoundedOAuthSession(self.config.client_id, self.config.secret,
            token_endpoint_auth_method='client_secret_basic', scope='openid email profile',
            redirect_uri=self.config.callback, code_challenge_method='S256', state=state)
        client.trust_env = False
        return client

    def discovery(self, client):
        data = client.get(self.config.issuer + '/.well-known/openid-configuration', withhold_token=True).json()
        if data.get('issuer') != self.config.issuer:
            raise IntegrationError('Emisor del proveedor no valido')
        for name in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'):
            endpoint = https_url(data[name])
            if endpoint.netloc != urlparse(self.config.issuer).netloc or endpoint.fragment:
                raise IntegrationError('Endpoint del proveedor no permitido')
        for name, expected in (('response_types_supported', 'code'),
                               ('code_challenge_methods_supported', 'S256'),
                               ('id_token_signing_alg_values_supported', 'RS256'),
                               ('token_endpoint_auth_methods_supported', 'client_secret_basic')):
            if expected not in data.get(name, []):
                raise IntegrationError('Proveedor incompatible con el contrato OIDC', 503)
        return data

    def prepare(self):
        browser, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(time.time())
        with self.db.transaction() as conn:
            conn.execute('DELETE FROM app_oidc_requests WHERE created_at<=?', (now - FLOW_SECONDS,))
            conn.execute('INSERT INTO app_oidc_requests(browser_hash,csrf_hash,created_at,config_hash) VALUES(?,?,?,?)',
                         (digest_token(browser), digest_token(csrf), now, self.context_hash()))
        return browser, csrf

    def context_hash(self):
        # A flow cannot survive a switch of client, realm, redirect or policy.
        return digest_token(json.dumps([self.config.issuer, self.config.client_id, self.config.callback,
            self.config.return_url, self.config.domains], separators=(',', ':')))

    def begin(self, browser, csrf):
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        with self.db.transaction() as conn:
            row = conn.execute('''UPDATE app_oidc_requests SET state=?,nonce=?,verifier=?
                WHERE browser_hash=? AND csrf_hash=? AND state IS NULL AND created_at>? AND config_hash=? RETURNING created_at''',
                (state, nonce, verifier, digest_token(browser), digest_token(csrf), int(time.time()) - FLOW_SECONDS, self.context_hash())).fetchone()
        if not row:
            raise IntegrationError('Inicio vencido o no autorizado', 403)
        with self.client(state) as client:
            metadata = self.discovery(client)
            url, _ = client.create_authorization_url(metadata['authorization_endpoint'], state=state,
                nonce=nonce, code_verifier=verifier, response_type='code', response_mode='query')
        return url

    def validate_token(self, encoded, jwks, pending):
        token = jwt.decode(encoded, KeySet.import_key_set(jwks), algorithms=['RS256'])
        claims = token.claims
        jwt.JWTClaimsRegistry(leeway=30, iss={'essential': True, 'value': self.config.issuer},
            aud={'essential': True, 'value': self.config.client_id}, exp={'essential': True},
            iat={'essential': True}, sub={'essential': True}, nonce={'essential': True}).validate(claims)
        now = time.time()
        for name in ('exp', 'iat'):
            if type(claims[name]) not in (int, float):
                raise IntegrationError('Tiempo del ID token no valido')
        if not pending['created_at'] - 30 <= claims['iat'] <= now + 30 or claims['exp'] <= now or claims['exp'] <= claims['iat']:
            raise IntegrationError('ID token vencido o emitido fuera de la solicitud')
        audience = claims['aud']
        if not isinstance(audience, (str, list)) or (isinstance(audience, list) and (not audience or not all(isinstance(x, str) for x in audience))):
            raise IntegrationError('Audiencia no valida')
        if ('azp' in claims or isinstance(audience, list) and len(audience) > 1) and claims.get('azp') != self.config.client_id:
            raise IntegrationError('Parte autorizada no valida')
        if not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'].encode(), pending['nonce'].encode()):
            raise IntegrationError('Nonce no valido')
        if not isinstance(claims['sub'], str) or not claims['sub'].strip() or len(claims['sub']) > 255:
            raise IntegrationError('Sujeto no valido')
        if claims.get('email_verified') is not True:
            raise IntegrationError('Correo corporativo no verificado', 403)
        email = corporate_email(claims.get('email'), self.config.domains)
        return claims['sub'], email

    def finish(self, browser, query, previous=None):
        # Consume before parsing or contacting the provider, including error responses.
        with self.db.transaction() as conn:
            row = conn.execute('DELETE FROM app_oidc_requests WHERE browser_hash=? RETURNING *',
                               (digest_token(browser),)).fetchone()
        if not row or not row['state'] or int(time.time()) - row['created_at'] >= FLOW_SECONDS or row['config_hash'] != self.context_hash():
            raise IntegrationError('Solicitud vencida, repetida o sin sesion de inicio')
        pending = dict(row)
        params = parse_qs(query, keep_blank_values=True, max_num_fields=10)
        if (set(params) - {'code', 'state', 'iss', 'session_state'} or
                any(len(v) != 1 or not v[0] for v in params.values()) or
                not {'code', 'state'} <= params.keys() or
                not hmac.compare_digest(params['state'][0].encode(), pending['state'].encode()) or
                'iss' in params and params['iss'][0] != self.config.issuer):
            raise IntegrationError('Callback no valido')
        with self.client(pending['state']) as client:
            metadata = self.discovery(client)
            token = client.fetch_token(metadata['token_endpoint'], grant_type='authorization_code',
                authorization_response=self.config.callback + '?' + query, code_verifier=pending['verifier'])
            if not isinstance(token.get('id_token'), str):
                raise IntegrationError('El proveedor no entrego ID token')
            jwks = client.get(metadata['jwks_uri'], withhold_token=True).json()
            subject, email = self.validate_token(token['id_token'], jwks, pending)
        with self.db.transaction(write=True) as conn:
            user = resolve_identity(conn, self.config.issuer, subject, email)
            result = self.auth.create_session(conn, user, previous) if user else None
        if not result:
            raise IntegrationError('Cuenta inexistente, inactiva o con conflicto de identidad', 403)
        return result
