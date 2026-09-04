from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import PaymentRow, normalize_header


@dataclass(frozen=True)
class ValidationIssue:
    row: int
    field: str
    message: str


class PaymentValidator:
    def __init__(self, required_transaction_type: str | None = "Ingreso") -> None:
        self.required_transaction_type = normalize_header(required_transaction_type)

    def validate(self, payment: PaymentRow) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        required_fields = {
            "bank_account": payment.bank_account,
            "payment_method": payment.payment_method,
            "concept": payment.concept,
            "identity_type": payment.identity_type,
            "identity_number": payment.identity_number,
            "first_name": payment.first_name,
        }
        for field_name, value in required_fields.items():
            if not str(value).strip():
                issues.append(ValidationIssue(payment.source_row, field_name, "campo requerido"))

        if self.required_transaction_type:
            current = normalize_header(payment.transaction_type)
            if current != self.required_transaction_type:
                issues.append(
                    ValidationIssue(
                        payment.source_row,
                        "transaction_type",
                        f"debe ser {self.required_transaction_type!r}",
                    )
                )

        if payment.amount <= Decimal("0"):
            issues.append(ValidationIssue(payment.source_row, "amount", "debe ser mayor que cero"))

        if payment.quantity <= Decimal("0"):
            issues.append(ValidationIssue(payment.source_row, "quantity", "debe ser mayor que cero"))

        return issues
