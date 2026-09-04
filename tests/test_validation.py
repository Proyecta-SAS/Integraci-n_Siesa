from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from siesa_payments.config import MappingConfig
from siesa_payments.source import read_csv_text
from siesa_payments.validation import PaymentValidator


class ValidationTests(TestCase):
    def setUp(self) -> None:
        self.mapping = MappingConfig.load(Path("config/siesa_recibo_caja_mapping.json"))

    def test_rejects_egreso_for_client_payment_flow(self) -> None:
        csv_text = (
            "Cuenta bancaria,Fecha,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,"
            "Tipo de identificación, Número de identificación *,Nombre *\n"
            "CAJA GENERAL,13/02/2026,Egreso,Transferencia,130505 CLIENTES,1,480000,"
            "CC - Cédula de ciudadanía,52833138,Aida\n"
        )
        payment = read_csv_text(csv_text, self.mapping)[0]

        issues = PaymentValidator("Ingreso").validate(payment)

        self.assertTrue(any(issue.field == "transaction_type" for issue in issues))

    def test_rejects_zero_amount(self) -> None:
        csv_text = (
            "Cuenta bancaria,Fecha,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,"
            "Tipo de identificación, Número de identificación *,Nombre *\n"
            "CAJA GENERAL,13/02/2026,Ingreso,Transferencia,130505 CLIENTES,1,0,"
            "CC - Cédula de ciudadanía,52833138,Aida\n"
        )
        payment = read_csv_text(csv_text, self.mapping)[0]

        issues = PaymentValidator("Ingreso").validate(payment)

        self.assertTrue(any(issue.field == "amount" for issue in issues))
