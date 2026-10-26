import unittest

from settletrace.models import InputError
from settletrace.money import to_minor


class MoneyTests(unittest.TestCase):
    def test_amounts_that_could_overflow_json_digit_conversion_are_rejected(self):
        with self.assertRaises(InputError):
            to_minor("9" * 4300, "USD")
        with self.assertRaisesRegex(InputError, "128-digit"):
            to_minor("9" * 127 + ".99", "USD")

    def test_decimal_units_are_exact_for_all_supported_currencies(self):
        for currency in ("USD", "EUR", "GBP", "INR"):
            for text, expected in (("19.99", 1999), ("0.01", 1), ("10", 1000),
                                   ("10.1", 1010), ("+0.05", 5), ("-0.01", -1),
                                   ("-10.50", -1050), ("-0.00", 0)):
                with self.subTest(currency=currency, text=text):
                    self.assertEqual(to_minor(text, currency), expected)

    def test_large_values_do_not_depend_on_decimal_context_or_float_precision(self):
        self.assertEqual(to_minor("9" * 100 + ".07", "USD"), int("9" * 100) * 100 + 7)

    def test_unsupported_or_ambiguous_amounts_never_round_or_coerce(self):
        for value in ("1.001", "1.000", "1e2", "NaN", "Infinity", " 1.00", "1.00 ",
                      "1,000.00", "1,00", ".50", "1.", "", "--1", "١.٠٠", "１.００", 1.5, 1, True, None):
            with self.subTest(value=value), self.assertRaises(InputError):
                to_minor(value, "USD")

    def test_unsupported_currency_never_guesses_decimal_places(self):
        for currency in ("JPY", "KWD", "usd", "USD ", "", None, []):
            with self.subTest(currency=currency), self.assertRaises(InputError):
                to_minor("1.00", currency)

    def test_explicit_comma_decimal_keeps_exact_signed_minor_units(self):
        for value, expected in (("19,99", 1999), ("19,9", 1990), ("19", 1900),
                                ("-0,01", -1), ("+0,05", 5), ("-0,00", 0)):
            with self.subTest(value=value):
                self.assertEqual(to_minor(value, "EUR", decimal_separator=","), expected)
        whole = "9" * 100
        self.assertEqual(to_minor(whole + ",07", "INR", decimal_separator=","), int(whole) * 100 + 7)

    def test_wrong_or_mixed_separator_grouping_and_excess_precision_are_rejected(self):
        for separator, values in ((".", ("1,00", "1,000.00", "1.000,00")),
                                  (",", ("1.00", "1.000,00", "1,000.00", "1,001", "1,000", " 1,00", "1,00 ", ",50", "1,"))):
            for value in values:
                with self.subTest(separator=separator, value=value), self.assertRaises(InputError):
                    to_minor(value, "EUR", decimal_separator=separator)

    def test_unsupported_decimal_separator_is_not_inferred(self):
        for separator in (";", "", "auto", None, []):
            with self.subTest(separator=separator), self.assertRaises(InputError):
                to_minor("1.00", "USD", decimal_separator=separator)
