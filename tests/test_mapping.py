from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

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
        self.assertEqual(payload["Final"][0]["F_CIA"], "")
        self.assertEqual(payload["Caja"][0]["F350_ID_TIPO_DOCTO"], "RC")
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_ID_TIPO_DOCTO"], "RC")
        self.assertEqual(payload["Caja"][0]["F358_VALOR"], "+000000000480000.0000")
        self.assertEqual(payload["Caja"][0]["F358_ID_MEDIOS_PAGO"], "EFE")
        self.assertEqual(payload["Caja"][0]["F358_FECHA_CONSIGNACION"], "20260213")
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_FECHA"], "20260213")
        self.assertEqual(payload["RCyotrosingresos"][0]["F357_VALOR_INGRESO"], "+000000000480000.0000")
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_ID_TERCERO"], "52833138")
        self.assertTrue(payload["RCyotrosingresos"][0]["F357_REFERENCIA"])
        self.assertEqual(payload["CxC"][0]["F354_VALOR_CR"], "+000000000480000.0000")
        self.assertEqual(payload["CxC"][0]["F353_NRO_CUOTA_CRUCE"], "000")

    def test_reads_cross_document_from_single_sheet_column(self) -> None:
        csv_text = (
            "Cuenta bancaria,Fecha,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,"
            "Tipo de identificacion, Numero de identificacion *,Nombre *,Documento cruce\n"
            "CAJA GENERAL,30/06/2026,Ingreso,Transferencia,130505 CLIENTES,1,1000,"
            "CC - Cedula de ciudadania,1000033853,Juan,FVE-00000006-00\n"
        )

        payment = read_csv_text(csv_text, self.mapping)[0]
        payload = build_payload(payment, self.mapping)

        self.assertEqual(payload["CxC"][0]["F350_ID_TIPO_DOCTO"], "RC")
        self.assertEqual(payload["CxC"][0]["F353_ID_TIPO_DOCTO_CRUCE"], "FVE")
        self.assertEqual(payload["CxC"][0]["F353_CONSEC_DOCTO_CRUCE"], "00000006")
        self.assertEqual(payload["CxC"][0]["F353_NRO_CUOTA_CRUCE"], "000")
        self.assertEqual(payload["CxC"][0]["F353_ID_AUXILIAR_DOCTO_CRUCE"], "")

    def test_operational_cross_values_come_from_sheet_before_env(self) -> None:
        csv_text = (
            "Cuenta bancaria,Fecha,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,"
            "Tipo de identificacion, Numero de identificacion *,Nombre *,Tipo docto cruce,"
            "Consecutivo cruce,Cuota cruce,C.O. cruce,U.N. cruce,Sucursal cruce,Auxiliar cruce\n"
            "CAJA GENERAL,30/06/2026,Ingreso,Transferencia,130505 CLIENTES,1,1000,"
            "CC - Cedula de ciudadania,1000033853,Juan,FVE,6,00,001,03,001,13050501\n"
        )
        env = {
            "SIESA_TIPO_DOCTO_CRUCE": "ENV",
            "SIESA_CONSEC_DOCTO_CRUCE": "999",
            "SIESA_NRO_CUOTA_CRUCE": "9",
            "SIESA_ID_CO_CRUCE": "999",
            "SIESA_ID_UN_CRUCE": "99",
            "SIESA_SUCURSAL_DOCTO_CRUCE": "999",
            "SIESA_AUXILIAR_DOCTO_CRUCE": "99999999",
        }

        payment = read_csv_text(csv_text, self.mapping)[0]
        with patch.dict("os.environ", env, clear=False):
            payload = build_payload(payment, self.mapping)

        self.assertEqual(payload["CxC"][0]["F353_ID_TIPO_DOCTO_CRUCE"], "FVE")
        self.assertEqual(payload["CxC"][0]["F353_CONSEC_DOCTO_CRUCE"], "00000006")
        self.assertEqual(payload["CxC"][0]["F353_NRO_CUOTA_CRUCE"], "000")
        self.assertEqual(payload["CxC"][0]["F353_ID_CO_DOCTO_CRUCE"], "001")
        self.assertEqual(payload["CxC"][0]["F353_ID_UN_DOCTO_CRUCE"], "03")
        self.assertEqual(payload["CxC"][0]["F353_ID_SUCURSAL_DOCTO_CRUCE"], "001")
        self.assertEqual(payload["CxC"][0]["F353_ID_AUXILIAR_DOCTO_CRUCE"], "13050501")

    def test_other_income_mode_uses_28050505_without_cxc_application(self) -> None:
        csv_text = (
            "Cuenta bancaria,Fecha,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,"
            "Tipo de identificacion, Numero de identificacion *,Nombre *\n"
            "CAJA GENERAL,30/06/2026,Ingreso,Transferencia,130505 CLIENTES,1,1000,"
            "CC - Cedula de ciudadania,1000033853,Juan\n"
        )
        env = {
            "SIESA_RECIBO_FLUJO": "otros_ingresos",
            "SIESA_ID_CO": "001",
            "SIESA_ID_UN": "99",
        }

        payment = read_csv_text(csv_text, self.mapping)[0]
        with patch.dict("os.environ", env, clear=False):
            payload = build_payload(payment, self.mapping)

        self.assertNotIn("CxC", payload)
        receipt = payload["RCyotrosingresos"][0]
        self.assertEqual(receipt["F350_ID_TIPO_DOCTO"], "RC")
        self.assertEqual(receipt["F351_ID_AUXILIAR_OTRO_ING"], "28050505")
        self.assertEqual(receipt["F351_ID_TERCERO_OTRO_ING"], "1000033853")
        self.assertEqual(receipt["F351_ID_CO_OTRO_ING"], "001")
        self.assertEqual(receipt["F351_ID_UN_OTRO_ING"], "99")
