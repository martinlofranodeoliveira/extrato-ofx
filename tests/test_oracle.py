"""Expectativas manuais e comparação opcional com parser independente."""
from importlib.util import find_spec
from importlib.metadata import version
from pathlib import Path
import unittest

from extrato_ofx import parse_ofx
from scripts.check_oracles import (
    CARD_EXPECTED, ORACLE_VERSION, common_cases,
    fractional_case, known_divergences, oracle_projection, report_projection, utc,
)


PROJECT = Path(__file__).resolve().parents[1]


class SyntheticExamplesTest(unittest.TestCase):
    def test_many_variants_against_handwritten_expected_fields(self):
        for case in common_cases():
            with self.subTest(case=case.name):
                report = parse_ofx(case.raw)
                self.assertEqual(report_projection(report), case.expected)
                self.assertEqual(report["status"], "ok")
                self.assertEqual(report["coverage"]["status"], "complete")

    def test_fixture_encodings_accents_and_exact_sums(self):
        bank_bytes = (PROJECT / "examples" / "banco.ofx").read_bytes()
        card_bytes = (PROJECT / "examples" / "cartao.ofx").read_bytes()
        self.assertIn("Depósito fictício".encode("cp1252"), bank_bytes)
        self.assertIn("Livraria fictícia".encode("utf-8"), card_bytes)
        bank = parse_ofx(bank_bytes)["statements"][0]
        card = parse_ofx(card_bytes)["statements"][0]
        self.assertEqual(bank["totals"]["reportedAmountSum"], "1474.5")
        self.assertEqual(card["totals"]["reportedAmountSum"], "-79.8")
        self.assertEqual(bank["transactions"][1]["amount"], {"raw": "-25,75", "value": "-25.75"})
        self.assertTrue(bank["range"]["endExclusive"])
        self.assertEqual(bank["ledgerBalance"]["amount"]["value"], "2474.5")

    def test_fractional_hour_semantics_are_handwritten(self):
        for token in ("5.5", "5.50"):
            with self.subTest(offset=token):
                stmt = report_projection(parse_ofx(fractional_case(token)))["statements"][0]
                self.assertEqual(stmt["rows"][0]["posted"], utc("2026-11-04T00:30:00.250Z"))

    def test_version_221_supported_by_local_profile(self):
        raw = (PROJECT / "examples" / "cartao.ofx").read_bytes().replace(b'VERSION="220"', b'VERSION="221"')
        report = parse_ofx(raw)
        self.assertEqual(report["format"]["version"], "221")
        self.assertEqual(report_projection(report), CARD_EXPECTED)


@unittest.skipUnless(find_spec("ofxtools") is not None, "extra dev ofxtools opcional ausente")
class IndependentOracleTest(unittest.TestCase):
    def test_pinned_oracle_matches_both_expected_data_and_reader(self):
        self.assertEqual(version("ofxtools"), ORACLE_VERSION)
        cases = common_cases()
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            with self.subTest(case=case.name):
                oracle = oracle_projection(case.raw)
                self.assertEqual(oracle, case.expected)
                self.assertEqual(oracle, report_projection(parse_ofx(case.raw)))

    def test_known_divergences_are_explicit_and_not_matches(self):
        divergences = known_divergences(parse_ofx)
        self.assertEqual([(item["case"], item["result"]) for item in divergences], [
            ("offset-5.5", "oracle_rejected"),
            ("offset-5.50", "different_utc"),
            ("version-221", "oracle_rejected"),
        ])
        self.assertTrue(all(item["countedAsMatch"] is False for item in divergences))


if __name__ == "__main__":
    unittest.main()
