from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from siesa_payments.config import MappingConfig
from siesa_payments.mapper import build_payload
from siesa_payments.source import read_csv_text


class MappingTests(TestCase):
    def setUp(self) -> None:
        self.mapping = MappingConfig.load(Path("config/siesa_recibo_caja_mapping.json"))

    def test_reads_alegra_headers_with_spaces_and_accents(self) -> None:
        csv_text = (
            "Cuenta bancaria,Fecha,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,"
            "Tipo de identificación, Número de identificación *,Nombre *\n"
            "CAJA GENERAL,13/02/2026,Ingreso,Transferencia,130505 CLIENTES,1,\"480.000\","
            "CC - Cédula de ciudadanía,52833138,Aida\n"
        )

        payments = read_csv_text(csv_text, self.mapping)

        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0].identity_number, "52833138")
        self.assertEqual(str(payments[0].amount), "480000")

    def test_builds_default_payload_for_connector_142888(self) -> None:
        payment = read_csv_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), self.mapping)[0]

        payload = build_payload(payment, self.mapping)

        self.assertEqual(payload["connectorId"], "142888")
        self.assertEqual(payload["operation"], "API_v1_ReciboCaja")
        self.assertEqual(payload["reciboCaja"]["fecha"], "2026-02-13")
        self.assertEqual(payload["reciboCaja"]["valor"], 480000.0)
        self.assertEqual(payload["tercero"]["numeroIdentificacion"], "52833138")
        self.assertTrue(payload["externalReference"])
