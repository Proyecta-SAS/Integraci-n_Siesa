"""Write receipt outcomes through the bundled Google Apps Script webhook."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import RuntimeConfig
from .siesa_hub import Transport, UrlLibTransport


PENDING = "Pendiente"
NEEDS_CORRECTION = "Pendiente por corregir"
LOADED = "Cargado"


class SheetWriteError(RuntimeError):
    pass


def receipt_number(response: Any) -> str:
    """Use only an explicit receipt/document field, never the connector ID."""
    if isinstance(response, dict):
        for name in ("documento", "recibo", "numero_recibo", "numeroDocumento"):
            value = response.get(name)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value)
        for name in ("data", "resultado", "result"):
            found = receipt_number(response.get(name))
            if found:
                return found
    elif isinstance(response, list):
        for item in response:
            found = receipt_number(item)
            if found:
                return found
    return ""


class SheetStatusWriter:
    def __init__(
        self, url: str, token: str, spreadsheet_id: str, sheet_id: int,
        transport: Transport | None = None,
    ) -> None:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.netloc != "script.google.com"
                or not re.fullmatch(r"/macros/s/[A-Za-z0-9_-]+/exec", parsed.path)
                or parsed.query or parsed.fragment):
            raise ValueError("SIESA_SHEETS_WEBHOOK_URL debe ser una URL /exec de Google Apps Script")
        if not token:
            raise ValueError("configure SIESA_SHEETS_WEBHOOK_TOKEN")
        self.url = url
        self.token = token
        self.spreadsheet_id = spreadsheet_id
        self.sheet_id = sheet_id
        self.transport = transport or UrlLibTransport()

    def write(
        self, source_row: int, source_cells: tuple[str, ...], status: str, *,
        receipt: str = "", sent_at: str = "", response: Any = None, error: str = "",
    ) -> None:
        if source_row < 2 or len(source_cells) != 11 or status not in {PENDING, NEEDS_CORRECTION, LOADED}:
            raise SheetWriteError("fila o estado de Sheets invalido")
        body = json.dumps({
            "token": self.token,
            "spreadsheet_id": self.spreadsheet_id,
            "sheet_id": self.sheet_id,
            "source_row": source_row,
            "source_cells": source_cells,
            "status": status,
            "receipt": receipt,
            "sent_at": sent_at,
            "response": response,
            "error": error,
        }, ensure_ascii=False).encode("utf-8")
        try:
            code, _, raw = self.transport.request(
                "POST", self.url, {"Content-Type": "application/json"}, body, 30,
            )
        except Exception as exc:
            # Never include request/URL details that might contain credentials.
            raise SheetWriteError("no se pudo conectar con el webhook de Sheets") from exc
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise SheetWriteError("el webhook no devolvio JSON; revise el despliegue y su acceso") from exc
        if not 200 <= code < 300 or not isinstance(result, dict) or result.get("ok") is not True:
            detail = result.get("error", "respuesta rechazada") if isinstance(result, dict) else "respuesta invalida"
            raise SheetWriteError(f"Sheets: {str(detail)[:500]}")


def writer_for_runtime(runtime: RuntimeConfig) -> SheetStatusWriter | None:
    if not runtime.sheets_writeback_enabled:
        return None
    if runtime.input_csv or not runtime.sheets_csv_url:
        raise ValueError("la escritura en Sheets requiere fuente Google Sheets, no un CSV local")
    parsed = urlparse(runtime.sheets_csv_url)
    match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]+)/export", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "docs.google.com" or not match:
        raise ValueError("no se pudo identificar la hoja de origen para escribir resultados")
    sheet_id = int(parse_qs(parsed.query).get("gid", ["0"])[0])
    if sheet_id < 0:
        raise ValueError("gid de Sheets invalido")
    return SheetStatusWriter(
        runtime.sheets_webhook_url or "", runtime.sheets_webhook_token or "",
        match.group(1), sheet_id,
    )
