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
            "Tipo de identificacion, Numero de identificacion *,Nombre *\n"
            "CAJA GENERAL,13/02/2026,Ingreso,Transferencia,130505 CLIENTES,1,\"480.000\","
            "CC - Cedula de ciudadania,52833138,Aida\n"
        )

        payments = read_csv_text(csv_text, self.mapping)

        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0].identity_number, "52833138")
        self.assertEqual(str(payments[0].amount), "480000")

    def test_builds_sectioned_payload_for_connector_142888(self) -> None:
        payment = read_csv_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), self.mapping)[0]

        payload = build_payload(payment, self.mapping)

        self.assertEqual(payload["Inicial"][0]["F_CIA"], "")
        self.assertEqual(payload["Caja"][0]["F358_VALOR"], "480000")
        self.assertEqual(payload["Caja"][0]["F358_ID_MEDIOS_PAGO"], "Transferencia")
        self.assertEqual(payload["Caja"][0]["F358_FECHA_CONSIGNACION"], "20260213")
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_FECHA"], "20260213")
        self.assertEqual(payload["RCyotrosingresos"][0]["F357_VALOR_INGRESO"], "480000")
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_ID_TERCERO"], "52833138")
        self.assertTrue(payload["RCyotrosingresos"][0]["F357_REFERENCIA"])
        self.assertEqual(payload["CxC"][0]["F354_VALOR_CR"], "480000")
        self.assertEqual(payload["CxC"][0]["F353_NRO_CUOTA_CRUCE"], "0")
