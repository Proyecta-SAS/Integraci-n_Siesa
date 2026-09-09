from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
    ) -> tuple[int, dict[str, str], bytes]:
        ...


class UrlLibTransport:
    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
    ) -> tuple[int, dict[str, str], bytes]:
        request = urllib.request.Request(url=url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()


@dataclass(frozen=True)
class SiesaResponse:
    status_code: int
    ok: bool
    data: Any
    raw_body: str


class SiesaHubClient:
    def __init__(
        self,
        base_url: str | None,
        connikey: str,
        connitoken: str,
        id_compania: str,
        id_documento: str,
        nombre_documento: str,
        id_ecosistema: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        execute_path: str = "/apisestandar/v3/conectoresimportar",
        connector_url: str | None = None,
        transport: Transport | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.connikey = connikey
        self.connitoken = connitoken
        self.id_compania = id_compania
        self.id_ecosistema = id_ecosistema
        self.client_id = client_id
        self.client_secret = client_secret
        self.id_documento = id_documento
        self.nombre_documento = nombre_documento
        self.execute_path = execute_path
        self.connector_url = connector_url
        self.transport = transport or UrlLibTransport()
        self.timeout = timeout

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Connikey": self.connikey,
            "Connitoken": self.connitoken,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.client_id:
            headers["client_id"] = self.client_id
        if self.client_secret:
            headers["client_secret"] = self.client_secret
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _params(self) -> dict[str, str]:
        params = {
            "idCompania": self.id_compania,
            "idDocumento": self.id_documento,
            "nombreDocumento": self.nombre_documento,
        }
        if self.id_ecosistema:
            params["idEcoSistema"] = self.id_ecosistema
        return params

    def _url(self) -> str:
        if self.connector_url:
            return self.connector_url
        if not self.base_url:
            raise RuntimeError("configure SIESA_CONNECTOR_URL o SIESA_HUB_BASE_URL")
        path = self.execute_path
        if not path.startswith("/"):
            path = "/" + path
        base = self.base_url + path
        separator = "&" if "?" in base else "?"
        return base + separator + urlencode(self._params())

    def _decode(self, status: int, body: bytes) -> SiesaResponse:
        raw = body.decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw}
        return SiesaResponse(status_code=status, ok=200 <= status < 300, data=data, raw_body=raw)

    def connection_summary(self) -> dict[str, Any]:
        url = self._url()
        parsed = urlsplit(url)
        return {
            "method": "POST",
            "url": urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)),
            "headers": {
                "Connikey": "***",
                "Connitoken": "***",
                "client_id": "***" if self.client_id else None,
                "client_secret": "***" if self.client_secret else None,
            },
            "params": self._params(),
        }

    def register_cash_receipt(
        self, connector_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> SiesaResponse:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, _headers, response_body = self.transport.request(
            "POST",
            self._url(),
            self._headers(idempotency_key),
            body,
            self.timeout,
        )
        return self._decode(status, response_body)
