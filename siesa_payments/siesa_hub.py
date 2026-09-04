from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


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
        base_url: str,
        token: str,
        auth_scheme: str = "Bearer",
        execute_path: str = "/api/v1/connectors/{connector_id}/execute",
        metadata_path: str = "/api/v1/connectors/{connector_id}",
        transport: Transport | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.auth_scheme = auth_scheme
        self.execute_path = execute_path
        self.metadata_path = metadata_path
        self.transport = transport or UrlLibTransport()
        self.timeout = timeout

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"{self.auth_scheme} {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _url(self, path_template: str, connector_id: str) -> str:
        path = path_template.format(connector_id=connector_id)
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def _decode(self, status: int, body: bytes) -> SiesaResponse:
        raw = body.decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw}
        return SiesaResponse(status_code=status, ok=200 <= status < 300, data=data, raw_body=raw)

    def validate_connector(self, connector_id: str) -> SiesaResponse:
        status, _headers, body = self.transport.request(
            "GET",
            self._url(self.metadata_path, connector_id),
            self._headers(),
            None,
            self.timeout,
        )
        return self._decode(status, body)

    def register_cash_receipt(
        self, connector_id: str, payload: dict[str, Any], idempotency_key: str
    ) -> SiesaResponse:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, _headers, response_body = self.transport.request(
            "POST",
            self._url(self.execute_path, connector_id),
            self._headers(idempotency_key),
            body,
            self.timeout,
        )
        return self._decode(status, response_body)
