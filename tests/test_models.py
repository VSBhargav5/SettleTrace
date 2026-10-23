from dataclasses import FrozenInstanceError
import unittest

from settletrace.models import Deposit, Entry, InputError, Sale


class ModelTests(unittest.TestCase):
    def test_records_are_frozen(self):
        sale = Sale("sale-1", "pay-1", "USD", 100)
        with self.assertRaises(FrozenInstanceError):
            sale.gross_minor = 200

    def test_all_supported_currencies(self):
        for currency in ("USD", "EUR", "GBP", "INR"):
            with self.subTest(currency=currency):
                self.assertEqual(Sale("s", "p", currency, 1).currency, currency)

    def test_invalid_identifiers(self):
        constructors = [
            lambda: Sale("", "p", "USD", 1),
            lambda: Sale("s", "  ", "USD", 1),
            lambda: Sale(123, "p", "USD", 1),
            lambda: Entry("", "p", "po", "charge", "USD", 100, 3, 97),
            lambda: Entry("e", "", "po", "charge", "USD", 100, 3, 97),
            lambda: Entry("e", "", "po", "refund", "USD", -100, 0, -100),
            lambda: Entry("e", "", "po", "dispute", "USD", -100, 0, -100),
            lambda: Entry("e", "p", "  ", "charge", "USD", 100, 3, 97),
            lambda: Deposit("", "po", "USD", 97),
            lambda: Deposit("b", "", "USD", 97),
        ]
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises(InputError):
                    constructor()

    def test_optional_processor_references(self):
        self.assertEqual(Entry("e", "", "", "fee", "USD", 0, 3, -3).net_minor, -3)
        self.assertEqual(Entry("e", "", "", "adjustment", "USD", 5, 0, 5).gross_minor, 5)
        self.assertEqual(Entry("e", "p", "", "charge", "USD", 100, 3, 97).payout_id, "")

    def test_no_float_string_or_boolean_money(self):
        for value in (1.0, "1", True, False, None):
            for field in ("gross_minor", "fee_minor", "net_minor"):
                args = {"transaction_id": "e", "payment_ref": "p", "payout_id": "po", "kind": "charge",
                        "currency": "USD", "gross_minor": 100, "fee_minor": 3, "net_minor": 97}
                args[field] = value
                with self.subTest(value=value, field=field):
                    with self.assertRaises(InputError):
                        Entry(**args)
            with self.subTest(value=value, record="sale"):
                with self.assertRaises(InputError):
                    Sale("s", "p", "USD", value)
            with self.subTest(value=value, record="deposit"):
                with self.assertRaises(InputError):
                    Deposit("b", "po", "USD", value)

    def test_currency_is_explicit_and_uppercase(self):
        for value in ("usd", "JPY", "", " USD", None, ["USD"]):
            for constructor in (
                lambda: Sale("s", "p", value, 100),
                lambda: Entry("e", "p", "po", "charge", value, 100, 3, 97),
                lambda: Deposit("b", "po", value, 97),
            ):
                with self.subTest(value=value):
                    with self.assertRaises(InputError):
                        constructor()

    def test_rows_are_nonnegative_integers(self):
        for value in (-1, 2.0, True, "2", None):
            for constructor in (
                lambda: Sale("s", "p", "USD", 100, value),
                lambda: Entry("e", "p", "po", "charge", "USD", 100, 3, 97, value),
                lambda: Deposit("b", "po", "USD", 97, value),
            ):
                with self.subTest(value=value):
                    with self.assertRaises(InputError):
                        constructor()
        self.assertEqual(Sale("s", "p", "USD", 100).row, 0)
        self.assertEqual(Deposit("b", "po", "USD", 97, 2).row, 2)

    def test_amount_sign_rules(self):
        for value in (0, -100):
            with self.assertRaises(InputError):
                Sale("s", "p", "USD", value)
            with self.assertRaises(InputError):
                Entry("e", "p", "po", "charge", "USD", value, 0, value)
        for kind in ("refund", "dispute"):
            for value in (0, 100):
                with self.subTest(kind=kind, value=value):
                    with self.assertRaises(InputError):
                        Entry("e", "p", "po", kind, "USD", value, 0, value)
        self.assertEqual(Deposit("b", "po", "USD", -100).amount_minor, -100)
        self.assertEqual(Entry("e", "p", "po", "refund", "USD", -100, -3, -97).net_minor, -97)

    def test_unknown_kind_and_net_arithmetic_rejected(self):
        for kind in ("CHARGE", "payout", None, []):
            with self.subTest(kind=kind):
                with self.assertRaises(InputError):
                    Entry("e", "p", "po", kind, "USD", 100, 3, 97)
        with self.assertRaisesRegex(InputError, "net_minor"):
            Entry("e", "p", "po", "charge", "USD", 100, 3, 100)

    def test_fee_kind_has_zero_gross_and_signed_fee_cost_or_credit(self):
        for gross in (-5, 5):
            with self.subTest(gross=gross):
                with self.assertRaisesRegex(InputError, "fee gross_minor must be zero"):
                    Entry("e", "", "po", "fee", "USD", gross, 0, gross)
        self.assertEqual(Entry("cost", "", "po", "fee", "USD", 0, 5, -5).net_minor, -5)
        self.assertEqual(Entry("credit", "", "po", "fee", "USD", 0, -5, 5).net_minor, 5)


if __name__ == "__main__":
    unittest.main()
