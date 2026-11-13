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
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    load_env_file(root / ".env", override=True)
    if args.command in {"hash-password", "create-user"}:
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
