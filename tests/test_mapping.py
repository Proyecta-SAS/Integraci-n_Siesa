from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from siesa_payments.config import MappingConfig
from siesa_payments.mapper import build_payload
from siesa_payments.source import read_csv_text
from siesa_payments.validation import PaymentValidator


class MappingTests(TestCase):
    def setUp(self) -> None:
        self.mapping = MappingConfig.load(Path("config/siesa_recibo_caja_mapping.json"))
        self.env = patch.dict('os.environ', {'SIESA_ID_MEDIO_PAGO_CONSIGNACION': 'CONSIG_PRUEBA'})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

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

    def test_ignores_residual_cross_only_rows_before_valid_payment(self) -> None:
        csv_text = (
            "Fecha,Contacto,Valor,Documento cruce,C.O. cruce\n"
            ",,,FVE-00000006-0,001\n"
            ",,,FVE-00000006-0,001\n"
            "13/09/2026,Consumidor Final,4100,,\n"
        )

        payments = read_csv_text(csv_text, self.mapping)

        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0].source_row, 4)
        self.assertEqual(payments[0].payment_date.isoformat(), "2026-09-13")
        self.assertEqual(str(payments[0].amount), "4100")

    def test_consumidor_final_uses_siesa_third_party_from_green_columns(self) -> None:
        csv_text = (
            "Cuenta bancaria,Fecha,Contacto,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,Nota,Observaciones\n"
            "BANCOLOMBIA,03/09/2026,Consumidor Final,Ingreso,Consignacion,28050505 ANTICIPO POR IDENTIFICAR,1,2000,Prueba,Prueba\n"
        )

        payment = read_csv_text(csv_text, self.mapping)[0]
        payload = build_payload(payment, self.mapping)

        self.assertEqual(payment.identity_number, "222222222222")
        self.assertEqual(PaymentValidator(self.mapping.required_transaction_type).validate(payment), [])
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_ID_TERCERO"], "222222222222")

    def test_builds_sectioned_payload_for_connector_142888(self) -> None:
        payment = read_csv_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), self.mapping)[0]

        payload = build_payload(payment, self.mapping)

        self.assertEqual(payload["Inicial"][0]["F_CIA"], "")
        self.assertEqual(payload["Final"][0]["F_CIA"], "")
        self.assertEqual(payload["Caja"][0]["F350_ID_TIPO_DOCTO"], "RC")
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_ID_TIPO_DOCTO"], "RC")
        self.assertEqual(payload["Caja"][0]["F358_VALOR"], "480000")
        self.assertEqual(payload["Caja"][0]["F358_ID_MEDIOS_PAGO"], "CONSIG_PRUEBA")
        self.assertEqual(payload["Caja"][0]["F358_FECHA_CONSIGNACION"], "20260213")
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_FECHA"], "20260213")
        self.assertEqual(payload["RCyotrosingresos"][0]["F357_VALOR_INGRESO"], "480000")
        self.assertEqual(payload["RCyotrosingresos"][0]["F350_ID_TERCERO"], "52833138")
        self.assertTrue(payload["RCyotrosingresos"][0]["F357_REFERENCIA"])
        self.assertEqual(payload["CxC"][0]["F354_VALOR_CR"], "480000")
        self.assertEqual(payload["CxC"][0]["F353_NRO_CUOTA_CRUCE"], "000")

    def test_rejected_keys_are_kept_out_of_both_connector_references(self) -> None:
        payment = read_csv_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), self.mapping)[0]
        rejected_keys = (
            "8d43f7bdcf3106bf06fd64df32ffd909",
            "3121e4877f7ed6fc489bd6c55070bff2",
            "1d92a23fe75825a3b83655282afd594c",
            "670e629ffcdb4079a9411886a1be1e6d",
            "e917bebb8222b29a29eb49e3990e1fc0",
            "d66289c54ff9796c2f81005f7d2250f7",
            "289415e83975544933504c092323c662",
            "44d27bc5346ba52ca5397f5847661b85",
            "44023e215d931d4ebd4aba3ac9bacd72",
            "934e27c8b6264293272e5a158b09ec5d",
        )
        for key in rejected_keys:
            with self.subTest(key=key), patch.object(type(payment), "idempotency_key", return_value=key):
                payload = build_payload(payment, self.mapping)
                self.assertEqual(payload["RCyotrosingresos"][0]["F357_REFERENCIA"], "20260213")
                self.assertEqual(payload["Caja"][0]["F358_REFERENCIA_OTROS"], "20260213")
                self.assertEqual(payment.idempotency_key(), key)

    def test_decimal_amounts_preserve_precision_without_sign_or_padding(self) -> None:
        payment = read_csv_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), self.mapping)[0]
        for amount in ("35000", "35000.50", "123456789012345.6789"):
            with self.subTest(amount=amount), patch.dict("os.environ", {"SIESA_RECIBO_FLUJO": "cartera"}):
                payload = build_payload(replace(payment, amount=Decimal(amount)), self.mapping)
                self.assertEqual(payload["Caja"][0]["F358_VALOR"], amount)
                self.assertEqual(payload["RCyotrosingresos"][0]["F357_VALOR_INGRESO"], amount)
                self.assertEqual(payload["RCyotrosingresos"][0]["F357_VALOR_APLICAR_REAL"], amount)
                self.assertEqual(payload["CxC"][0]["F354_VALOR_CR"], amount)

    def test_same_day_references_do_not_merge_distinct_payment_keys(self) -> None:
        payment = read_csv_text(Path("samples/alegra_payments.csv").read_text(encoding="utf-8"), self.mapping)[0]
        other = replace(payment, note="Otro pago el mismo dia")
        self.assertNotEqual(payment.idempotency_key(), other.idempotency_key())
        for item in (payment, other):
            payload = build_payload(item, self.mapping)
            self.assertEqual(payload["Caja"][0]["F358_REFERENCIA_OTROS"], "20260213")
            self.assertEqual(payload["RCyotrosingresos"][0]["F357_REFERENCIA"], "20260213")

    def test_matches_successful_support_example_from_october_29(self) -> None:
        expected = json.loads(Path("samples/siesa_support_20261029.json").read_text(encoding="utf-8"))
        payment = read_csv_text(
            "Cuenta bancaria,Fecha,Contacto,Tipo de Transaccion,Metodo de pago,Concepto,Cantidad,Valor,Nota\n"
            "BANCOLOMBIA,17/10/2026,Consumidor Final,Ingreso,Consignacion,28050505 ANTICIPO POR IDENTIFICAR,1,35000,PAGO QR MARCELA DEL C\n",
            self.mapping,
        )[0]
        env = {
            "SIESA_RECIBO_FLUJO": "otros_ingresos",
            "SIESA_F_CIA": "001",
            "SIESA_ID_CO": "001",
            "SIESA_TIPO_DOCUMENTO": "RC",
            "SIESA_CONSEC_DOCTO": "1",
            "SIESA_CONSEC_AUTO_REG": "1",
            "SIESA_ID_MEDIO_PAGO_CONSIGNACION": "CG1",
            "SIESA_ID_BANCO": "07",
            "SIESA_NRO_CUENTA": "30000003697",
            "SIESA_DOCTO_BANCO_CG": "CG",
            "SIESA_ID_CAJA": "01",
            "SIESA_ID_UN": "99",
            "SIESA_ID_COBRADOR": "9999",
            "SIESA_ID_FE": "1103",
        }
        with patch.dict("os.environ", env, clear=True):
            payload = build_payload(payment, self.mapping)
        # Consecutivo and document class retain the existing integer padding.
        # Support changed the references and amounts, not these numeric fields.
        for section in ("Caja", "RCyotrosingresos"):
            expected[section][0]["F350_CONSEC_DOCTO"] = "00000001"
        expected["RCyotrosingresos"][0]["F350_ID_CLASE_DOCTO"] = "00013"
        self.assertEqual(payload, expected)

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
