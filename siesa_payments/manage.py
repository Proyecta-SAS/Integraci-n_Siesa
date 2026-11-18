"""Local/SSH administration; passwords are prompted, never passed as arguments."""
from __future__ import annotations
import argparse
import getpass
import json
from pathlib import Path

from .application import Application
from .auth import Auth, password_hash
from .config import load_env_file
from .database import Database


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    user = sub.add_parser("create-user")
    user.add_argument("--email", required=True)
    sub.add_parser("hash-password")
    sub.add_parser("recover")
    for command in ('deactivate-user', 'revoke-sessions'):
        operation = sub.add_parser(command)
        operation.add_argument('--email', required=True)
    sub.add_parser('check-integration')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    load_env_file(root / ".env", override=True)
    if args.command == 'check-integration':
        from .avanzar import IntegrationConfig, PROFILES
        config = IntegrationConfig.from_env()
        print(json.dumps({'sso_enabled': config.sso, 'embed_enabled': config.embed,
            'issuer': config.issuer, 'client_id': config.client_id, 'callback': config.callback if config.base_url else '',
            'return_url': config.return_url, 'oidc_secret_configured': bool(config.secret),
            'provisioning_credential_configured': bool(config.api_token), 'profiles': config.profiles,
            'profiles_valid': bool(config.profiles) and set(config.profiles) <= PROFILES,
            'domains': config.domains}, ensure_ascii=False, indent=2))
    elif args.command in {'deactivate-user', 'revoke-sessions'}:
        from .auth import normalize_email
        db = Database.from_env()
        with db.transaction(write=True) as conn:
            email = normalize_email(args.email)
            user = conn.execute('SELECT id FROM app_users WHERE email=?', (email,)).fetchone()
            if user:
                if args.command == 'deactivate-user':
                    conn.execute('UPDATE app_users SET active=0 WHERE id=?', (user['id'],))
                conn.execute('DELETE FROM app_sessions WHERE user_id=?', (user['id'],))
        if not user:
            raise SystemExit('Cuenta no encontrada; no se modifico ningun usuario')
        print('Cuenta desactivada y sesiones revocadas' if args.command == 'deactivate-user' else 'Sesiones revocadas')
    elif args.command in {"hash-password", "create-user"}:
        password = getpass.getpass("Contraseña (minimo 12 caracteres): ")
        if password != getpass.getpass("Repetir contraseña: "):
            raise SystemExit("Las contraseñas no coinciden")
        if args.command == "hash-password":
            print(password_hash(password))
        else:
            db = Database.from_env()
            db.initialize()
            Auth(db).create_user(args.email, password)
            print("Cuenta creada")
    else:
        app = Application(root, background=False)
        result = app.ledger.query()
        print(json.dumps({"summary": result["summary"], "total": result["total"], "import_issues": result["import_issues"]}))


if __name__ == "__main__":
    main()
