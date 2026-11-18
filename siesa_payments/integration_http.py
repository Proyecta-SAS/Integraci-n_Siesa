"""HTTP boundary for Avanzar. Errors never expose provider payloads or secrets."""
import html
import json
import re
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .auth import SESSION_SECONDS
from .avanzar import IntegrationError
from .oidc import FLOW_COOKIE, FLOW_SECONDS


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Campo repetido')
        result[key] = value
    return result


class IntegrationHTTP:
    def _flow_cookie(self, token='', age=0):
        return f'{FLOW_COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={age}'

    def _browser_token(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get('Cookie', ''))
        value = cookie[FLOW_COOKIE].value if FLOW_COOKIE in cookie else ''
        return value if re.fullmatch(r'[a-zA-Z0-9_-]{43}', value) else ''

    def _integration_html(self, content, *, status=200, cookies=()):
        body = ('<!doctype html><html lang="es"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                '<title>Acceso Avanzar</title><link rel="stylesheet" href="/styles.css">'
                '<body><main class="portal-access">' + content + '</main></body></html>').encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for cookie in cookies:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _integration_redirect(self, target, cookies=()):
        self.send_response(303)
        self.send_header('Location', target)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        for cookie in cookies:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()

    def _limited_body(self, maximum):
        sizes = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(sizes) != 1 or not re.fullmatch(r'[0-9]+', sizes[0]):
            raise IntegrationError('Longitud de solicitud no valida', 422)
        size = int(sizes[0])
        if size > maximum:
            raise IntegrationError('Cuerpo demasiado grande', 413)
        self.connection.settimeout(5)
        data = self.rfile.read(size)
        if len(data) != size:
            raise IntegrationError('Cuerpo incompleto', 422)
        return data

    def _provision(self):
        service = self._app().provisioning
        request_id = self.headers.get('X-Request-Id', '')
        valid_request_id = bool(re.fullmatch(r'[a-zA-Z0-9._:-]{1,128}', request_id))
        if not valid_request_id:
            request_id = uuid4().hex
        status = 500
        try:
            if self.command != 'POST':
                raise IntegrationError('Metodo no permitido', 405)
            if not service.authorized(self.headers.get('Authorization', '')):
                raise IntegrationError('Credencial no valida', 401)
            if not valid_request_id:
                raise IntegrationError('X-Request-Id obligatorio: 1 a 128 caracteres alfanumericos, punto, guion, guion bajo o dos puntos', 422)
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                raise IntegrationError('Content-Type debe ser application/json', 415)
            try:
                data = json.loads(self._limited_body(16 * 1024), object_pairs_hook=unique_object)
            except (ValueError, UnicodeError):
                raise IntegrationError('JSON no valido', 422) from None
            status, body = service.create(data, request_id)
        except IntegrationError as exc:
            status, body = exc.status, {'ok': False, 'error': str(exc), 'request_id': request_id}
        except Exception:
            status, body = 500, {'ok': False, 'error': 'No se pudo completar la solicitud', 'request_id': request_id}
        if status not in {200, 201, 409}:
            try:
                service.audit(request_id, status)
            except Exception:
                # Logs contain identifiers/results only, including database outages.
                import logging
                logging.getLogger(__name__).error('provision request_id=%s result=%s audit_unavailable', request_id, status)
        headers = {'X-Request-Id': request_id}
        if status == 405:
            headers['Allow'] = 'POST'
        if status == 401:
            headers['WWW-Authenticate'] = 'Bearer'
        self.close_connection = True
        self._json(body, status=HTTPStatus(status), headers=headers)

    def _integration_request(self, parsed):
        if parsed.path == '/api/v1/crear-usuarios':
            self._provision()
            return True
        if parsed.path not in {'/portal/iniciar-sso', '/sso/iniciar', '/sso/callback', '/portal/volver'}:
            return False
        try:
            config = self._app().integration
            if parsed.path == '/portal/volver' and self.command == 'GET' and config.embed:
                if parsed.query:
                    raise IntegrationError('Retorno no permitido')
                self._integration_redirect(config.portal_origin + '/')
                return True
            if not config.sso:
                raise IntegrationError('Acceso corporativo aun no configurado', 503)
            expected_method = 'POST' if parsed.path == '/sso/iniciar' else 'GET'
            if self.command != expected_method:
                raise IntegrationError('Metodo no permitido', 405)
            if parsed.path != '/sso/callback' and parsed.query:
                raise IntegrationError('Parametros de retorno no permitidos')
            if parsed.path != '/sso/callback' and self.headers.get('Sec-Fetch-Dest') in {'iframe', 'frame'}:
                self._integration_html('<h1>Acceso corporativo</h1><a href="/portal/iniciar-sso" target="_top">Continuar en la ventana principal</a>')
                return True
            session = self._app().auth.session(self.headers.get('Cookie', ''))
            if parsed.path == '/portal/iniciar-sso':
                if session:
                    self._integration_redirect(config.return_url)
                else:
                    browser, csrf = self._app().oidc.prepare()
                    self._integration_html('<h1>Ingresar con Avanzar</h1><p>Continúa con tu identidad corporativa.</p>'
                        '<form method="post" action="/sso/iniciar" target="_top">'
                        f'<input type="hidden" name="csrf" value="{html.escape(csrf)}">'
                        '<button type="submit">Continuar con Avanzar</button></form>'
                        '<script src="/sso-start.js" defer></script>',
                        cookies=[self._flow_cookie(browser, FLOW_SECONDS)])
            elif parsed.path == '/sso/iniciar':
                if self.headers.get('Origin', '') != config.base_url:
                    raise IntegrationError('Origen no autorizado', 403)
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                    raise IntegrationError('Formulario no valido', 415)
                data = parse_qs(self._limited_body(2048).decode('utf-8'), keep_blank_values=True, max_num_fields=2)
                if set(data) != {'csrf'} or len(data['csrf']) != 1:
                    raise IntegrationError('Formulario no valido', 422)
                self._integration_redirect(self._app().oidc.begin(self._browser_token(), data['csrf'][0]))
            elif parsed.path == '/sso/callback':
                result = self._app().oidc.finish(self._browser_token(), parsed.query, session)
                self._integration_redirect(config.return_url,
                    [self._session_cookie(result['token'], SESSION_SECONDS), self._flow_cookie()])
            else:
                raise IntegrationError('Retorno no configurado', 503)
        except IntegrationError as exc:
            self._integration_html(f'<h1>No se pudo iniciar sesion</h1><p>{html.escape(str(exc))}</p>'
                '<a href="/portal/iniciar-sso" target="_top">Volver a intentar</a>', status=exc.status,
                cookies=[self._flow_cookie()])
        except Exception:
            self._integration_html('<h1>No se pudo completar el acceso corporativo</h1>'
                '<p>Vuelve a iniciar el acceso desde el portal.</p>', status=400, cookies=[self._flow_cookie()])
        return True

    def end_headers(self):
        config = getattr(self._app(), 'integration', None) if self._has_application() else None
        path = urlparse(self.path).path
        ancestors = config.portal_origin if config and config.embed and not path.startswith('/sso/') and path != '/portal/iniciar-sso' else "'none'"
        form_action = "'self'"
        if config and config.sso and path in {'/portal/iniciar-sso', '/sso/iniciar'}:
            issuer = urlparse(config.issuer)
            form_action += ' ' + issuer.scheme + '://' + issuer.netloc
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors " + ancestors + "; base-uri 'self'; form-action " + form_action)
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def _unsupported_integration_method(self):
        if not self._integration_request(urlparse(self.path)):
            self.send_error(405)

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _unsupported_integration_method
