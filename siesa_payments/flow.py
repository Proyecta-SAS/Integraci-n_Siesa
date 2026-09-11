from __future__ import annotations

from dataclasses import dataclass

from .models import PaymentRow, normalize_header


EXISTING_CONTACT_RECEIPT = "existing_contact_receipt"
CREATE_PERSON_CONTACT_RECEIPT = "create_person_contact_receipt"
CREATE_LEGAL_CONTACT_RECEIPT = "create_legal_contact_receipt"
CREATE_CLIENT_PROVIDER_RECEIPT = "create_client_provider_receipt"


@dataclass(frozen=True)
class FlowDecision:
    key: str
    creates_customer: bool
    siesa_target: str


def wants_customer_creation(payment: PaymentRow) -> bool:
    return "crear" in normalize_header(payment.customer_action)


def _is_client_provider(payment: PaymentRow) -> bool:
    role = normalize_header(payment.person_type).replace(" ", "")
    return role in {"cliente/proveedor", "clienteproveedor", "client,provider", "clientprovider"}


def _is_legal_entity(payment: PaymentRow) -> bool:
    identity_type = normalize_header(payment.identity_type)
    tax_person_type = normalize_header(payment.tax_person_type)
    return "nit" in identity_type or "juridica" in tax_person_type


def decide_flow(payment: PaymentRow) -> FlowDecision:
    if not wants_customer_creation(payment):
        return FlowDecision(
            key=EXISTING_CONTACT_RECEIPT,
            creates_customer=False,
            siesa_target="Financiero > Cuentas x cobrar > Recibos de caja > Otros ingresos",
        )

    if _is_client_provider(payment):
        return FlowDecision(
            key=CREATE_CLIENT_PROVIDER_RECEIPT,
            creates_customer=True,
            siesa_target="Crear/validar tercero cliente-proveedor y luego ReciboCaja",
        )

    if _is_legal_entity(payment):
        return FlowDecision(
            key=CREATE_LEGAL_CONTACT_RECEIPT,
            creates_customer=True,
            siesa_target="Crear/validar tercero juridico y luego ReciboCaja",
        )

    return FlowDecision(
        key=CREATE_PERSON_CONTACT_RECEIPT,
        creates_customer=True,
        siesa_target="Crear/validar tercero persona natural y luego ReciboCaja",
    )
