"""Password authentication, opaque server-side sessions and CSRF validation."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from http.cookies import SimpleCookie
from uuid import uuid4

from .database import Database

COOKIE = "siesa_session"
SESSION_SECONDS = 8 * 60 * 60
ITERATIONS = 600_000


def password_hash(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("La contraseña debe tener entre 12 y 256 caracteres")
    salt = secrets.token_bytes(24)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) != ITERATIONS or len(password) > 256:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError, AttributeError):
        return False


def normalize_email(email: str) -> str:
    value = str(email).strip().lower()
    if len(value) > 254 or not (re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) or re.fullmatch(r"[a-z0-9._-]{3,64}", value)):
        raise ValueError("Usuario o correo no valido")
    return value


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self, database: Database):
        self.db = database
        # Unknown accounts perform the same password work as existing accounts.
        self.dummy = password_hash(secrets.token_urlsafe(32))

    def bootstrap(self, email: str, encoded: str) -> bool:
        if not email or not encoded:
            return False
        email = normalize_email(email)
        if not re.fullmatch(r"pbkdf2_sha256\$600000\$[a-f0-9]{48}\$[a-f0-9]{64}", encoded):
            raise ValueError("Hash inicial no valido")
        with self.db.transaction() as conn:
            # Bootstrap is deliberately one-time: restarting never resets users.
            if conn.execute("SELECT id FROM app_users LIMIT 1").fetchone():
                return False
            conn.execute("INSERT INTO app_users(id,email,password_hash,created_at) VALUES(?,?,?,?) ON CONFLICT(email) DO NOTHING",
                         (uuid4().hex, email, encoded, int(time.time())))
            return True

    def create_user(self, email, password):
        email = normalize_email(email)
        encoded = password_hash(password)
        with self.db.transaction() as conn:
            if conn.execute("SELECT id FROM app_users WHERE email=?", (email,)).fetchone():
                raise ValueError("El usuario ya existe")
            conn.execute("INSERT INTO app_users(id,email,password_hash,created_at) VALUES(?,?,?,?)",
                         (uuid4().hex, email, encoded, int(time.time())))

    def has_users(self):
        with self.db.transaction() as conn:
            return bool(conn.execute("SELECT id FROM app_users WHERE active=1 LIMIT 1").fetchone())

    def login(self, email: str, password: str):
        now = int(time.time())
        email = str(email).strip().lower()[:254]
        account_key = digest_token(email)
        with self.db.transaction() as conn:
            failed = conn.execute("SELECT * FROM login_failures WHERE account_key=?", (account_key,)).fetchone()
            if failed and failed["failures"] >= 5 and now - failed["window_started"] < 900:
                return None
            user = conn.execute("SELECT * FROM app_users WHERE email=?", (email,)).fetchone()
            valid = verify_password(password, user["password_hash"] if user else self.dummy)
            if not user or not user["active"] or not valid:
                conn.execute("""INSERT INTO login_failures(account_key,failures,window_started) VALUES(?,1,?)
                    ON CONFLICT(account_key) DO UPDATE SET
                    failures=CASE WHEN excluded.window_started-login_failures.window_started<900 THEN login_failures.failures+1 ELSE 1 END,
                    window_started=CASE WHEN excluded.window_started-login_failures.window_started<900 THEN login_failures.window_started ELSE excluded.window_started END""",
                    (account_key, now))
                return None
            conn.execute("DELETE FROM login_failures WHERE account_key=?", (account_key,))
            conn.execute("DELETE FROM app_sessions WHERE expires_at<=?", (now,))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            conn.execute("INSERT INTO app_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                         (digest_token(token), user["id"], csrf, now + SESSION_SECONDS, now))
            return {"token": token, "csrf_token": csrf, "user": {"id": user["id"], "email": user["email"]}}

    def session(self, cookie_header: str):
        try:
            cookie = SimpleCookie()
            cookie.load(cookie_header or "")
            token = cookie[COOKIE].value if COOKIE in cookie else ""
            if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
                return None
        except Exception:
            return None
        with self.db.transaction() as conn:
            row = conn.execute("""SELECT s.token_hash,s.csrf_token,u.id,u.email FROM app_sessions s
                JOIN app_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
                (digest_token(token), int(time.time()))).fetchone()
            return dict(row) if row else None

    def logout(self, session):
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM app_sessions WHERE token_hash=?", (session["token_hash"],))

    @staticmethod
    def valid_csrf(session, token):
        return bool(session and isinstance(token, str) and hmac.compare_digest(session["csrf_token"], token))
