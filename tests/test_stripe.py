"""The supported report subset must preserve identity, money and evidence."""

import unittest

from settletrace.engine import reconcile
from settletrace.models import Deposit, InputError, Sale
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
        for category in ("fee", "adjustment", "dispute_reversal", "refund_failure", "partial_capture_reversal", "unknown", ""):
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

    def test_wrong_decimal_separator_does_not_autodetect_dot_amounts(self):
        with self.assertRaises(InputError):
            parse_stripe((HEADER + CHARGE).encode("utf-8"), "stripe.csv", decimal_separator=",")

    def test_explicit_quoted_comma_decimals_preserve_charge_and_debit_refund(self):
        text = HEADER + 'txn_1,ch_1,po_1,charge,eur,"100,00","3,50","96,50"\n'
        text += 'txn_refund,ch_1,po_1,refund,eur,"-20,00","-0,50","-19,50"\n'
        entries = parse_stripe(text.encode("utf-8"), "stripe.csv", decimal_separator=",")
        self.assertEqual([(entry.gross_minor, entry.fee_minor, entry.net_minor) for entry in entries],
                         [(10000, 350, 9650), (-2000, -50, -1950)])
        report = reconcile([Sale("sale_1", "ch_1", "EUR", 10000)], entries,
                           [Deposit("bank_1", "po_1", "EUR", 7700)])
        self.assertEqual(report["findings"], [])
        with self.assertRaises(InputError):
            parse_stripe(text.encode("utf-8"), "stripe.csv")

    def test_comma_mode_does_not_change_csv_delimiter_or_allow_mixed_amounts(self):
        text = HEADER + 'txn_1,ch_1,po_1,charge,eur,"100,00",3.50,"96,50"\n'
        with self.assertRaises(InputError):
            parse_stripe(text.encode("utf-8"), "stripe.csv", decimal_separator=",")
        with self.assertRaises(InputError):
            parse_stripe((HEADER + CHARGE).replace(",", ";").encode("utf-8"), "stripe.csv", decimal_separator=",")

    def test_unsupported_decimal_separator_reports_source_location(self):
        with self.assertRaises(InputError) as caught:
            parse_stripe((HEADER + CHARGE).encode("utf-8"), "stripe.csv", decimal_separator="auto")
        self.assertIn("stripe.csv:1:", str(caught.exception))

    def test_refund_and_debit_dispute_preserve_signed_fees_and_original_charge(self):
        rows = (
            ("txn_refund,ch_original,po_1,refund,usd,-5.00,-0.15,-4.85\n", "refund", -500, -15, -485),
            ("txn_dispute,ch_original,po_1,dispute,usd,-2.00,0.15,-2.15\n", "dispute", -200, 15, -215),
        )
        for text, kind, gross, fee, net in rows:
            with self.subTest(kind=kind):
                entry = self.parse(HEADER + text)[0]
                self.assertEqual((entry.kind, entry.payment_ref), (kind, "ch_original"))
                self.assertEqual((entry.gross_minor, entry.fee_minor, entry.net_minor), (gross, fee, net))

    def test_charge_refund_and_dispute_share_charge_identity_without_duplicate_activity(self):
        entries = self.parse(
            HEADER + CHARGE
            + "txn_refund,ch_1,po_1,refund,usd,-5.00,-0.15,-4.85\n"
            + "txn_dispute,ch_1,po_1,dispute,usd,-2.00,0.15,-2.15\n"
        )
        report = reconcile([Sale("sale_1", "ch_1", "USD", 1999)], entries,
                           [Deposit("bank_1", "po_1", "USD", 1240)])
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["summary"]["matched_sales"], 1)
        self.assertEqual(report["summary"]["matched_payouts"], 1)

    def test_historical_refund_or_dispute_requires_no_invented_original_charge(self):
        for kind in ("refund", "dispute"):
            with self.subTest(kind=kind):
                entries = self.parse(HEADER + f"txn_historical,ch_prior,po_1,{kind},usd,-100.00,0.00,-100.00\n")
                report = reconcile([], entries, [Deposit("bank_1", "po_1", "USD", -10000)])
                self.assertEqual([finding["code"] for finding in report["findings"]], ["ORIGINAL_CHARGE_NOT_OBSERVED"])
                self.assertEqual(report["findings"][0]["reference"], "ch_prior")
                self.assertEqual(report["summary"]["matched_payouts"], 1)

    def test_refund_and_dispute_require_negative_gross_and_exact_net(self):
        for kind in ("refund", "dispute"):
            for gross, net, message in (("1.00", "1.00", "gross_minor must be negative"),
                                        ("0.00", "0.00", "gross_minor must be negative"),
                                        ("-1.00", "-0.99", "net_minor must equal")):
                with self.subTest(kind=kind, gross=gross, net=net):
                    self.assert_invalid(HEADER + f"txn_2,ch_1,po_1,{kind},usd,{gross},0.00,{net}\n", message)

    def test_refund_and_dispute_never_fall_back_to_source_or_payment_intent(self):
        for kind in ("refund", "dispute"):
            with self.subTest(kind=kind):
                text = HEADER.rstrip() + ",source_id,payment_intent_id\n"
                text += f"txn_2,,po_1,{kind},usd,-1.00,0.00,-1.00,re_or_dp_1,pi_1\n"
                self.assert_invalid(text, "charge_id must be nonblank")


if __name__ == "__main__":
    unittest.main()
