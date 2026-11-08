import decimal
from fractions import Fraction
import unittest
from extrato_ofx import Limits, OfxError
from extrato_ofx.scalars import parse_amount, parse_date, sum_amounts


class AmountTests(unittest.TestCase):
    def test_canonical_and_source(self):
        for raw, value in ((" +0001,2300 ", "1.23"), ("-.500", "-0.5"), ("1.", "1"),
                           ("+0", "0"), ("-0,000", "0"), ("1,234", "1.234")):
            with self.subTest(raw=raw):
                self.assertEqual(parse_amount(raw), {"raw": raw.strip(), "value": value})

    def test_no_grouping_exponent_float_or_unicode_digits(self):
        for value in ("1,234.56", "1.234,56", "NaN", "Infinity", "1e3", "1 000", "", ".", "-", "١٢", 0.5, None):
            with self.subTest(value=value), self.assertRaises(OfxError):
                parse_amount(value)

    def test_token_limit_and_expanded_leading_zero(self):
        amount = parse_amount("." + "0" * 30 + "1")
        self.assertEqual(sum_amounts([amount]), "0." + "0" * 30 + "1")
        with self.assertRaises(OfxError):
            parse_amount("1" * 33)

    def test_sum_large_values_and_cancellation(self):
        self.assertEqual(sum_amounts(map(parse_amount, ["99999999999999999999999999999.99", ".01"])), "100000000000000000000000000000")
        self.assertEqual(sum_amounts(map(parse_amount, ["123.450", "-123,45"])), "0")
        self.assertEqual(sum_amounts([]), "0")

    def test_sum_independent_fraction_oracle(self):
        tokens = [str(coefficient) for coefficient in range(-20, 21)]
        tokens += [f"{sign}{integer}.{fraction:03d}" for sign in ("", "-") for integer in range(7) for fraction in (0, 1, 17, 999)]
        parsed = list(map(parse_amount, tokens))
        expected = sum((Fraction(token) for token in tokens), Fraction())
        self.assertEqual(Fraction(sum_amounts(parsed)), expected)
        for start in range(0, len(tokens), 11):
            self.assertEqual(Fraction(sum_amounts(parsed[start:start + 11])), sum(map(Fraction, tokens[start:start + 11]), Fraction()))

    def test_decimal_context_has_no_influence(self):
        with decimal.localcontext() as context:
            context.prec = 1
            context.traps[decimal.Inexact] = True
            self.assertEqual(sum_amounts(map(parse_amount, ["123456789.123456789", ".000000001"])), "123456789.12345679")
            self.assertEqual(context.prec, 1)
            self.assertTrue(context.traps[decimal.Inexact])


class DateTests(unittest.TestCase):
    def test_date_default_gmt(self):
        result = parse_date(" 20240229 ")
        self.assertEqual(result["precision"], "date")
        self.assertEqual(result["utc"], "2024-02-29T00:00:00Z")
        self.assertEqual(result["offsetHours"], "0")
        self.assertIsNone(result["zoneLabel"])

    def test_right_omission_and_fraction(self):
        self.assertEqual(parse_date("2024010203")["iso"], "2024-01-02T03:00:00+00:00")
        self.assertEqual(parse_date("202401020304")["precision"], "minute")
        self.assertEqual(parse_date("20240102030405.007")["utc"], "2024-01-02T03:04:05.007Z")

    def test_fractional_hour_is_not_minutes(self):
        self.assertEqual(parse_date("20240101000000[5.5:ANY]")["utc"], "2023-12-31T18:30:00Z")
        result = parse_date("20240101000000[-0.01:TEST]")
        self.assertEqual(result["utc"], "2024-01-01T00:00:36Z")
        self.assertEqual(result["iso"], "2024-01-01T00:00:00-00:00:36")
        self.assertEqual(result["zoneLabel"], "TEST")

    def test_offsets_bounds_and_rollovers(self):
        self.assertEqual(parse_date("20250101010000[12]")["utc"], "2024-12-31T13:00:00Z")
        self.assertEqual(parse_date("20241231230000[-12]")["utc"], "2025-01-01T11:00:00Z")
        for value in ("20240101[12.01]", "20240101[-13]", "00010101[12]", "99991231235959[-12]"):
            with self.subTest(value=value), self.assertRaises(OfxError):
                parse_date(value)

    def test_invalid_dates_and_precisions(self):
        for token in ("2024", "202401", "20230229", "00000101", "20241301", "2024010124", "20240101000000.1", "202401010000.001", "20240101[1.001]", "20240101[3:America/Sao_Paulo bad]", "20240101000000Z"):
            with self.subTest(token=token), self.assertRaises(OfxError):
                parse_date(token)
        with self.assertRaises(OfxError) as raised:
            parse_date("20161231235960")
        self.assertEqual(raised.exception.code, "unsupported_leap_second")

    def test_token_preserved_year_one_and_label_informational(self):
        self.assertEqual(parse_date("00010101000000[0:NOT-A-ZONE]")["utc"], "0001-01-01T00:00:00Z")
        self.assertEqual(parse_date("20240101[-3:BRT]")["utc"], parse_date("20240101[-3:FOO]")["utc"])


class LimitsTests(unittest.TestCase):
    def test_strict_positive_and_caps(self):
        for values in ({"max_nodes": True}, {"max_depth": 129}, {"max_transactions": 0}, {"max_input_bytes": -1}, {"max_text_chars": 1.2}):
            with self.subTest(values=values), self.assertRaises(OfxError):
                Limits(**values)
