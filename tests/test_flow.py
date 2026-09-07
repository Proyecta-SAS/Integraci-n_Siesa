from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from siesa_payments.config import MappingConfig
from siesa_payments.flow import (
    CREATE_CLIENT_PROVIDER_RECEIPT,
    CREATE_LEGAL_CONTACT_RECEIPT,
    CREATE_PERSON_CONTACT_RECEIPT,
    EXISTING_CONTACT_RECEIPT,
    decide_flow,
)
from siesa_payments.source import read_csv_text


class FlowTests(TestCase):
    def setUp(self) -> None:
        mapping = MappingConfig.load(Path("config/siesa_recibo_caja_mapping.json"))
        self.payment = read_csv_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), mapping)[0]

    def test_classifies_create_person_receipt_route(self) -> None:
        self.assertEqual(decide_flow(self.payment).key, CREATE_PERSON_CONTACT_RECEIPT)

    def test_classifies_existing_contact_receipt_route(self) -> None:
        payment = replace(self.payment, customer_action="", contact="AIDA RODRIGUEZ")

        self.assertEqual(decide_flow(payment).key, EXISTING_CONTACT_RECEIPT)

    def test_classifies_create_legal_receipt_route(self) -> None:
        payment = replace(
            self.payment,
            customer_action="CREAR",
            identity_type="NIT - Numero de identificacion tributaria",
            tax_person_type="Persona juridica",
        )

        self.assertEqual(decide_flow(payment).key, CREATE_LEGAL_CONTACT_RECEIPT)

    def test_classifies_client_provider_route_first(self) -> None:
        payment = replace(
            self.payment,
            customer_action="CREAR",
            person_type="Cliente / Proveedor",
            identity_type="NIT - Numero de identificacion tributaria",
        )

        self.assertEqual(decide_flow(payment).key, CREATE_CLIENT_PROVIDER_RECEIPT)
