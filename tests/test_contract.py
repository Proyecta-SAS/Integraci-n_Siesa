from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from siesa_payments.config import MappingConfig
from siesa_payments.contract import compare_contract_to_mapping, flatten_json_paths


class ContractTests(TestCase):
    def test_flattens_sectioned_body_paths(self) -> None:
        body = {"Inicial": [{"F_CIA": ""}], "ReciboCaja": [{"F_VALOR": 0}]}

        self.assertEqual(flatten_json_paths(body), ["Inicial.0.F_CIA", "ReciboCaja.0.F_VALOR"])

    def test_compares_connector_body_against_mapping(self) -> None:
        mapping = MappingConfig.load(Path("config/siesa_recibo_caja_mapping.json"))
        body = {
            "Inicial": [{"F_CIA": ""}],
            "ReciboCaja": [{"F_FECHA": "", "F_VALOR": "", "F_CAMPO_REAL_NUEVO": ""}],
            "Final": [{"F_CIA": ""}],
        }

        comparison = compare_contract_to_mapping(body, mapping)

        self.assertIn("ReciboCaja.0.F_CAMPO_REAL_NUEVO", comparison.missing_in_mapping)
        self.assertIn("Caja.0.F358_ID_MEDIOS_PAGO", comparison.not_in_contract)
