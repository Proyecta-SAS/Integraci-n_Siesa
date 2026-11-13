"""Application database. The original ERP send-state files remain authoritative."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS app_users (
        id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, created_at BIGINT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS app_sessions (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES app_users(id),
        csrf_token TEXT NOT NULL, expires_at BIGINT NOT NULL, created_at BIGINT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS login_failures (
        account_key TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_started BIGINT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ledger_events (
        event_id TEXT PRIMARY KEY, activator TEXT NOT NULL, payment_key TEXT NOT NULL,
        status TEXT NOT NULL, occurred_at TEXT NOT NULL, source_path TEXT NOT NULL,
        evidence TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ledger_receipts (
        id TEXT PRIMARY KEY, activator TEXT NOT NULL, payment_key TEXT NOT NULL,
        status TEXT NOT NULL, identity_number TEXT NOT NULL DEFAULT '',
        customer TEXT NOT NULL DEFAULT '', payment_date TEXT NOT NULL DEFAULT '',
        amount TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
        method TEXT NOT NULL DEFAULT '', receipt_number TEXT NOT NULL DEFAULT '',
        sent_at TEXT NOT NULL DEFAULT '', last_event_at TEXT NOT NULL DEFAULT '',
        possible_duplicate INTEGER NOT NULL DEFAULT 0, duplicate_of TEXT NOT NULL DEFAULT '',
        source_environment TEXT NOT NULL DEFAULT 'no_documentado',
        confirmation_source TEXT NOT NULL DEFAULT '',
        UNIQUE(activator, payment_key))""",
    """CREATE TABLE IF NOT EXISTS ledger_sources (
        source_path TEXT PRIMARY KEY, byte_offset BIGINT NOT NULL,
        prefix_hash TEXT NOT NULL, updated_at BIGINT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ledger_import_errors (
        id TEXT PRIMARY KEY, source_path TEXT NOT NULL, error TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS receipt_date_idx ON ledger_receipts(payment_date, id)",
    "CREATE INDEX IF NOT EXISTS receipt_key_idx ON ledger_events(activator, payment_key)",
    "CREATE INDEX IF NOT EXISTS receipt_match_idx ON ledger_receipts(identity_number, payment_date, amount)",
)


class DatabaseUnavailable(RuntimeError):
    pass


class Connection:
    def __init__(self, raw: Any, postgres: bool):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql: str, params=()):
        return self.raw.execute(sql.replace("?", "%s") if self.postgres else sql, params)


class Database:
    def __init__(self, url: str):
        if not url:
            raise ValueError("Configure SIESA_DATABASE_URL")
        self.url = url
        self.postgres = url.startswith(("postgres://", "postgresql://"))
        if not self.postgres and not url.startswith("sqlite:///"):
            raise ValueError("Base de datos no compatible")

    @classmethod
    def from_env(cls):
        url = os.getenv("SIESA_DATABASE_URL", "")
        if os.getenv("SIESA_ENV", "qa").lower() in {"prod", "production"} and url.startswith("sqlite:"):
            raise ValueError("Produccion requiere PostgreSQL")
        return cls(url)

    @contextmanager
    def transaction(self):
        try:
            if self.postgres:
                import psycopg
                from psycopg.rows import dict_row
                raw = psycopg.connect(self.url, connect_timeout=5, row_factory=dict_row)
            else:
                path = Path(self.url.removeprefix("sqlite:///"))
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = sqlite3.connect(path, timeout=15)
                raw.row_factory = sqlite3.Row
                raw.execute("PRAGMA foreign_keys=ON")
        except Exception as error:
            raise DatabaseUnavailable("La base de datos no esta disponible") from error
        try:
            yield Connection(raw, self.postgres)
            raw.commit()
        except Exception as error:
            raw.rollback()
            raise DatabaseUnavailable("No se pudo completar la operacion de base de datos") from error
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()

    def initialize(self):
        with self.transaction() as conn:
            for sql in SCHEMA:
                conn.execute(sql)

    def ping(self):
        with self.transaction() as conn:
            return conn.execute("SELECT 1").fetchone() is not None
