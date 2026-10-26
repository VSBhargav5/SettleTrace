"""The supported report subset must preserve identity, money and evidence."""

import unittest

from settletrace.models import InputError
from settletrace.stripe import parse_stripe


HEADER = "balance_transaction_id,charge_id,automatic_payout_id,reporting_category,currency,gross,fee,net\n"
CHARGE = "txn_1,ch_1,po_1,charge,usd,19.99,0.59,19.40\n"


class StripeTests(unittest.TestCase):
    def parse(self, text):
        return parse_stripe(text.encode("utf-8"), "stripe.csv")

    def assert_invalid(self, text, message, line=2):
        with self.assertRaises(InputError) as caught:
            self.parse(text)
        self.assertIn(f"stripe.csv:{line}:", str(caught.exception))
        self.assertIn(message, str(caught.exception))

    def test_charge_preserves_original_charge_payout_and_exact_minor_units(self):
        entry = self.parse(HEADER + CHARGE)[0]
        self.assertEqual((entry.transaction_id, entry.payment_ref, entry.payout_id, entry.kind),
                         ("txn_1", "ch_1", "po_1", "charge"))
        self.assertEqual((entry.currency, entry.gross_minor, entry.fee_minor, entry.net_minor, entry.row),
                         ("USD", 1999, 59, 1940, 2))

    def test_extra_columns_are_allowed_and_source_id_never_replaces_charge_id(self):
        text = HEADER.rstrip() + ",source_id,description\n" + CHARGE.rstrip() + ',other_id,"one, item"\n'
        self.assertEqual(self.parse(text)[0].payment_ref, "ch_1")
        self.assert_invalid(text.replace("txn_1,ch_1,", "txn_1,,"), "charge_id must be nonblank")

    def test_identity_and_automatic_payout_are_required_without_trimming(self):
        for field, value in ((0, ""), (1, ""), (2, ""), (1, " ch_1"), (2, "po_1 ")):
            row = CHARGE.strip().split(",")
            row[field] = value
            with self.subTest(field=field, value=value):
                self.assert_invalid(HEADER + ",".join(row) + "\n", "nonblank" if not value else "whitespace")

    def test_duplicate_transaction_ids_abort_instead_of_double_counting(self):
        self.assert_invalid(HEADER + CHARGE + CHARGE, "duplicate balance_transaction_id", line=3)

    def test_every_unsupported_category_aborts_entire_import(self):
        for category in ("refund", "dispute", "fee", "adjustment", "unknown", ""):
            with self.subTest(category=category):
                self.assert_invalid(HEADER + CHARGE + CHARGE.replace("txn_1", "txn_2").replace("charge,", category + ","),
                                    "unsupported reporting_category", line=3)

    def test_invalid_arithmetic_and_money_syntax_are_rejected(self):
        for row, message in ((CHARGE.replace("19.40", "19.41"), "net_minor"),
                             (CHARGE.replace("19.99", "19.999"), "Amount"),
                             (CHARGE.replace("usd", "JPY"), "currency")):
            with self.subTest(row=row):
                self.assert_invalid(HEADER + row, message)

    def test_schema_and_row_width_errors_are_located(self):
        self.assert_invalid(HEADER.replace("charge_id,", ""), "missing columns", line=1)
        self.assert_invalid(HEADER.rstrip() + ",charge_id\n", "duplicate column", line=1)
        self.assert_invalid(HEADER + CHARGE.rstrip() + ",extra\n", "cell count")
        self.assert_invalid(HEADER + ",".join(CHARGE.strip().split(",")[:-1]) + "\n", "cell count")

    def test_utf8_bom_quoted_multiline_and_physical_evidence(self):
        text = "\ufeff" + HEADER.rstrip() + ",description\n\n" + CHARGE.rstrip() + ',"first\nsecond"\n'
        self.assertEqual(self.parse(text)[0].row, 4)
        with self.assertRaises(InputError) as caught:
            parse_stripe(HEADER.encode("utf-8") + CHARGE.encode("utf-8") + b"\xff", "stripe.csv")
        self.assertIn("stripe.csv:3:", str(caught.exception))
        self.assert_invalid(HEADER + '"unterminated\n', "invalid CSV")

    def test_empty_data_rejected_but_header_only_is_explicit_empty_dataset(self):
        self.assertEqual(self.parse(HEADER), [])
        self.assert_invalid("", "empty file", line=1)

    def test_decimal_separator_must_be_explicitly_supported(self):
        with self.assertRaises(InputError):
            parse_stripe((HEADER + CHARGE).encode("utf-8"), "stripe.csv", decimal_separator=",")


if __name__ == "__main__":
    unittest.main()
