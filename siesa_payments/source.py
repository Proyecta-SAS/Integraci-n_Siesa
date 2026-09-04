from __future__ import annotations

import csv
import io
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import MappingConfig
from .models import PaymentRow, normalize_header


class PaymentSourceError(RuntimeError):
    pass


def _build_header_index(headers: list[str]) -> dict[str, int]:
    index: dict[str, int] = {}
    for position, header in enumerate(headers):
        normalized = normalize_header(header)
        if normalized and normalized not in index:
            index[normalized] = position
    return index


def _row_to_canonical(
    headers: list[str], row: list[str], mapping: MappingConfig, source_row: int
) -> PaymentRow:
    header_index = _build_header_index(headers)
    canonical: dict[str, Any] = {}
    for field_name, aliases in mapping.sheet_columns.items():
        value = ""
        for alias in aliases:
            position = header_index.get(normalize_header(alias))
            if position is not None and position < len(row):
                value = row[position]
                break
        canonical[field_name] = value
    return PaymentRow.from_raw(canonical, source_row=source_row)


def read_csv_text(csv_text: str, mapping: MappingConfig) -> list[PaymentRow]:
    reader = csv.reader(io.StringIO(csv_text))
    try:
        headers = next(reader)
    except StopIteration:
        return []

    payments: list[PaymentRow] = []
    for row_number, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        payments.append(_row_to_canonical(headers, row, mapping, row_number))
    return payments


def read_csv_file(path: Path, mapping: MappingConfig) -> list[PaymentRow]:
    if not path.exists():
        raise PaymentSourceError(f"archivo CSV no existe: {path}")
    return read_csv_text(path.read_text(encoding="utf-8-sig"), mapping)


def read_google_sheet_csv(url: str, mapping: MappingConfig, timeout: int = 30) -> list[PaymentRow]:
    request = urllib.request.Request(url, headers={"User-Agent": "siesa-payments/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        csv_text = response.read().decode(charset)
    return read_csv_text(csv_text, mapping)


def iter_payments(input_csv: str | None, sheets_csv_url: str | None, mapping: MappingConfig) -> Iterable[PaymentRow]:
    if input_csv:
        yield from read_csv_file(Path(input_csv), mapping)
        return
    if sheets_csv_url:
        yield from read_google_sheet_csv(sheets_csv_url, mapping)
        return
    raise PaymentSourceError("configure SIESA_INPUT_CSV o SIESA_SHEETS_CSV_URL")
