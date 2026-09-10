from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


def normalize_header(value: str | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    return re.sub(r"\s+", " ", text)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_decimal(value: Any) -> Decimal:
    text = clean_text(value)
    if not text:
        return Decimal("0")
    text = text.replace("$", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "." in text:
        groups = text.split(".")
        if len(groups) > 1 and all(group.isdigit() for group in groups) and all(len(group) == 3 for group in groups[1:]):
            text = "".join(groups)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"valor decimal invalido: {value!r}") from exc


def format_decimal_signed(value: Decimal, integer_digits: int = 15, decimals: int = 4) -> str:
    quant = Decimal(1).scaleb(-decimals)
    rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else "+"
    absolute = abs(rounded)
    integer_text, _, decimal_text = format(absolute, f".{decimals}f").partition(".")
    return f"{sign}{integer_text.zfill(integer_digits)}.{decimal_text.ljust(decimals, '0')}"


def format_integer(value: Any, width: int) -> str:
    decimal_value = parse_decimal(value)
    return str(int(decimal_value)).zfill(width)


def parse_cross_document(value: Any) -> tuple[str, str, str]:
    text = clean_text(value).upper()
    match = re.match(r"^([A-Z0-9]+)-([0-9]+)(?:-([0-9]+))?$", text)
    if not match:
        return "", "", ""
    return match.group(1), match.group(2), match.group(3) or ""


def parse_date(value: Any) -> date:
    text = clean_text(value)
    if not text:
        raise ValueError("fecha vacia")
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"fecha invalida: {value!r}")


@dataclass(frozen=True)
class PaymentRow:
    bank_account: str
    payment_date: date
    contact: str
    transaction_type: str
    payment_method: str
    cost_center: str
    concept: str
    quantity: Decimal
    amount: Decimal
    note: str
    observations: str
    customer_action: str
    person_type: str
    identity_type: str
    identity_number: str
    first_name: str
    last_name: str
    tax_person_type: str
    tax_responsibility: str
    municipality_department: str
    address: str
    cross_document: str
    cross_document_type: str
    cross_document_number: str
    cross_installment: str
    cross_co: str
    cross_un: str
    cross_branch: str
    cross_auxiliary: str
    source_row: int

    @classmethod
    def from_raw(cls, data: dict[str, Any], source_row: int) -> "PaymentRow":
        parsed_cross_type, parsed_cross_number, parsed_cross_installment = parse_cross_document(
            data.get("cross_document")
        )
        return cls(
            bank_account=clean_text(data.get("bank_account")),
            payment_date=parse_date(data.get("payment_date")),
            contact=clean_text(data.get("contact")),
            transaction_type=clean_text(data.get("transaction_type")),
            payment_method=clean_text(data.get("payment_method")),
            cost_center=clean_text(data.get("cost_center")),
            concept=clean_text(data.get("concept")),
            quantity=parse_decimal(data.get("quantity") or "1"),
            amount=parse_decimal(data.get("amount")),
            note=clean_text(data.get("note")),
            observations=clean_text(data.get("observations")),
            customer_action=clean_text(data.get("customer_action")),
            person_type=clean_text(data.get("person_type")),
            identity_type=clean_text(data.get("identity_type")),
            identity_number=clean_text(data.get("identity_number")),
            first_name=clean_text(data.get("first_name")),
            last_name=clean_text(data.get("last_name")),
            tax_person_type=clean_text(data.get("tax_person_type")),
            tax_responsibility=clean_text(data.get("tax_responsibility")),
            municipality_department=clean_text(data.get("municipality_department")),
            address=clean_text(data.get("address")),
            cross_document=clean_text(data.get("cross_document")),
            cross_document_type=clean_text(data.get("cross_document_type")) or parsed_cross_type,
            cross_document_number=clean_text(data.get("cross_document_number")) or parsed_cross_number,
            cross_installment=clean_text(data.get("cross_installment")) or parsed_cross_installment,
            cross_co=clean_text(data.get("cross_co")),
            cross_un=clean_text(data.get("cross_un")),
            cross_branch=clean_text(data.get("cross_branch")),
            cross_auxiliary=clean_text(data.get("cross_auxiliary")),
            source_row=source_row,
        )

    def to_payload_value(self, field_name: str, value_format: str | None = None) -> Any:
        value = getattr(self, field_name)
        if isinstance(value, date):
            if value_format == "yyyymmdd":
                return value.strftime("%Y%m%d")
            return value.isoformat()
        if isinstance(value, Decimal):
            if value_format == "decimal_signed_21":
                return format_decimal_signed(value)
            if value_format and value_format.startswith("integer_"):
                return format_integer(value, int(value_format.removeprefix("integer_")))
            if value_format == "string":
                return format(value, "f")
            return float(value)
        return value

    def idempotency_key(self) -> str:
        parts = [
            self.payment_date.isoformat(),
            normalize_header(self.identity_number),
            str(self.amount),
            normalize_header(self.note),
            normalize_header(self.bank_account),
        ]
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        return digest[:32]


PAYMENT_FIELD_NAMES = {field.name for field in fields(PaymentRow)}
