"""Vista local aislada: sesión real, datos Siesa de ejemplo y envíos simulados.

python scripts/preview_portal.py --port 5052
Abrir http://127.0.0.1:5052/demo para entrar a la demostración.
"""
import argparse
import os
import sys
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from siesa_payments import web_server as server
from siesa_payments.application import Application
from siesa_payments.auth import password_hash, SESSION_SECONDS
from siesa_payments.database import Database
from siesa_payments.alegra import AlegraActivators, ACCOUNTS

DEMO_EMAIL = 'operador@demo.local'
DEMO_PASSWORD = 'Vista-local-Siesa-Alegra-2026'


def runtime():
    return {'environment': 'qa', 'application_mode': 'otros_ingresos', 'activator': {'key': 'alianza', 'label': 'Siesa Alianza', 'sheet_name': 'Hoja de demostración'},
            'source': 'google_sheets_csv', 'dry_run': True, 'allow_send': False, 'ready_to_send': True,
            'send_unlocked': False, 'can_send_now': False, 'send_cooldown_minutes': 15,
            'connector_url_configured': True, 'missing_send_env': [], 'cross_fallback_configured': True,
            'cooldown': {'cooldown_active': False, 'retry_after_seconds': 0},
            'hub_connector_id': '261128', 'connector_id': '261128', 'operation': 'API_v2_ReciboCaja'}


def rows(**_):
    return {'runtime': runtime(), 'count': 2, 'rows': [dict(source_row=index, flow='otros_ingresos_28050505', identity_number='222222222222', customer='Cliente de demostración', payment_date='2026-11-13', method='Transferencia', amount=str(amount), note='Pago de ejemplo', duplicate_of=None, possible_duplicate=False, already_sent=False, unconfirmed=False, valid=True, ready=True, issues=[], cross_ready=True, cross_source='no_aplica', cross_document='', sheet_cross_document='', cross_auxiliary='28050505') for index, amount in [(2, 150000), (3, 275000)]]}


def preflight(**_):
    return {**rows(), 'preflight': {'ready': True, 'ready_rows': 2, 'rows_checked': 2, 'total_ready_amount': '425000', 'duplicate_rows': [], 'invalid_rows': [], 'already_sent_rows': [], 'missing_cross_rows': []}}


class PreviewHandler(server.AppHandler):
    def do_GET(self):
        if urlparse(self.path).path == '/demo':
            result = self._app().auth.login(DEMO_EMAIL, DEMO_PASSWORD)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header('Set-Cookie', self._session_cookie(result['token'], SESSION_SECONDS))
            self.send_header('Location', '/alegra')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == '/api/sync/send':
            if self._require_user(urlparse(self.path), write=True):
                self._json({'ok': False, 'error': 'La demostración no envía recibos reales.'}, status=HTTPStatus.FORBIDDEN)
            return
        super().do_POST()

    def _json(self, data, status=HTTPStatus.OK, headers=None):
        if urlparse(self.path).path == '/api/auth/me' and data.get('ok'):
            data = {**data, 'preview': True}
        super()._json(data, status=status, headers=headers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=5052)
    args = parser.parse_args()
    state = ROOT / '.state' / 'portal-preview'
    state.mkdir(parents=True, exist_ok=True)
    os.environ['SIESA_ENV'] = 'qa'
    os.environ['SIESA_STATE_FILE'] = str(state / 'send-state.json')
    os.environ['SIESA_BOOTSTRAP_ADMIN_EMAIL'] = DEMO_EMAIL
    os.environ['SIESA_BOOTSTRAP_ADMIN_PASSWORD_HASH'] = password_hash(DEMO_PASSWORD)
    app = Application(ROOT, database=Database('sqlite:///' + str(state / 'portal.sqlite3')), sources=[], background=False)
    app.alegra = AlegraActivators(app.db, sender=lambda *_: None, endpoints={key: 'https://demo.invalid/' + key for key in ACCOUNTS}, preview=True)
    server.APPLICATION = app
    server.inspect_rows = rows
    server.preflight = preflight
    server._redacted_runtime = lambda *_: runtime()
    server.SEND_JOBS.status = lambda *_: None
    # Job status normally needs the runtime state path; provide a local one.
    from types import SimpleNamespace
    server._runtime_for_request = lambda **_: SimpleNamespace(state_file=state / 'send-state.json')
    server.run_sync = lambda **_: {'runtime': runtime(), 'result': {'processed': 2, 'dry_run': 2, 'sent': 0, 'failed': 0, 'invalid': 0, 'skipped': 0, 'duplicate_warnings': [], 'sheets_writeback_errors': []}}
    server._audit_events = lambda **_: []
    print(f'Portal de demostración: http://127.0.0.1:{args.port}/demo', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), PreviewHandler).serve_forever()


if __name__ == '__main__':
    main()
