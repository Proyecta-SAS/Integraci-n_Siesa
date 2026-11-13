"""Activadores Alegra: transporte separado del ERP y bloqueo compartido por cuenta."""
from __future__ import annotations

import json
import os
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

ACCOUNTS = {
    "alegra_antiguo": ("Alegra Antiguo", "ALEGRA_WEBHOOK_ANTIGUO"),
    "alegra_lidera": ("Alegra Lidera", "ALEGRA_WEBHOOK_LIDERA"),
    "alegra_alianza": ("Alegra Alianza", "ALEGRA_WEBHOOK_ALIANZA"),
    "alegra_prosperar": ("Alegra Prosperar", "ALEGRA_WEBHOOK_PROSPERAR"),
}
COOLDOWN_SECONDS = 15 * 60


class AlegraError(Exception):
    def __init__(self, message, status=400, *, remaining=0):
        super().__init__(message)
        self.status, self.remaining = status, remaining


def send_webhook(url, payload):
    request = Request(url, data=json.dumps(payload).encode(), method="POST",
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError("El activador no confirmó la solicitud")


class AlegraActivators:
    def __init__(self, database, *, sender=send_webhook, endpoints=None, clock=time.time, preview=False):
        self.db, self.sender, self.clock = database, sender, clock
        self.endpoints, self.preview = endpoints, preview

    def _endpoint(self, key):
        value = (self.endpoints.get(key, "") if self.endpoints is not None else os.getenv(ACCOUNTS[key][1], "")).strip()
        parsed = urlsplit(value)
        return value if parsed.scheme == "https" and parsed.netloc else ""

    def status(self):
        with self.db.transaction() as connection:
            locks = {row["activator"]: row["locked_until"] for row in connection.execute("SELECT activator,locked_until FROM alegra_activations").fetchall()}
        now = int(self.clock())
        return {"ok": True, "preview": self.preview, "cooldown_seconds": COOLDOWN_SECONDS,
                "accounts": [{"id": key, "label": label, "configured": bool(self._endpoint(key)),
                              "retry_after_seconds": max(0, locks.get(key, 0) - now)}
                             for key, (label, _) in ACCOUNTS.items()]}

    def activate(self, payload):
        if not isinstance(payload, dict):
            raise AlegraError("Solicitud no válida")
        key = payload.get("tipo")
        if not isinstance(key, str) or key not in ACCOUNTS or payload.get("activador") != "ON":
            raise AlegraError("Selecciona un activador Alegra válido")
        endpoint = self._endpoint(key)
        if not endpoint:
            raise AlegraError("Esta cuenta Alegra aún no tiene su conexión configurada", 503)
        now, token = int(self.clock()), uuid4().hex
        remaining = 0
        with self.db.transaction() as connection:
            connection.execute("INSERT INTO alegra_activations(activator,locked_until,attempt_token) VALUES(?,0,'') ON CONFLICT(activator) DO NOTHING", (key,))
            claimed = connection.execute("UPDATE alegra_activations SET locked_until=?,attempt_token=? WHERE activator=? AND locked_until<=?", (now + COOLDOWN_SECONDS, token, key, now))
            if claimed.rowcount != 1:
                row = connection.execute("SELECT locked_until FROM alegra_activations WHERE activator=?", (key,)).fetchone()
                remaining = max(1, row["locked_until"] - now)
        if remaining:
            raise AlegraError("Esta cuenta está en espera antes de su próxima activación", 429, remaining=remaining)
        try:
            self.sender(endpoint, {"activador": "ON"})
        except Exception:
            # Una respuesta perdida puede corresponder a una orden ya recibida.
            # Conservamos la espera para impedir un reenvío inmediato accidental.
            raise AlegraError("No se pudo confirmar la activación. Revisa su resultado antes de reintentar", 502,
                             remaining=max(1, now + COOLDOWN_SECONDS - int(self.clock()))) from None
        with self.db.transaction() as connection:
            connection.execute("UPDATE alegra_activations SET locked_until=? WHERE activator=? AND attempt_token=?", (int(self.clock()) + COOLDOWN_SECONDS, key, token))
        return {"ok": True, "status": "ok", "preview": self.preview, "activator": key,
                "retry_after_seconds": COOLDOWN_SECONDS}
