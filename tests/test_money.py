import unittest

from settletrace.models import InputError
from settletrace.money import to_minor


class MoneyTests(unittest.TestCase):
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
