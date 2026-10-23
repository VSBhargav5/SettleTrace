import itertools
import json
import unittest

from settletrace.engine import reconcile
from settletrace.models import Deposit, Entry, InputError, Sale


class EngineTests(unittest.TestCase):
    def assert_codes(self, result, *expected):
        self.assertEqual([finding["code"] for finding in result["findings"]], sorted(expected))

    def test_empty_observation_window_is_not_a_successful_reconciliation(self):
        with self.assertRaisesRegex(InputError, "no observed records"):
            reconcile([], [], [])

    def test_individual_empty_datasets_remain_observation_reviews(self):
        cases = [
            ([Sale("s", "p", "USD", 100)], [], [], ["CHARGE_NOT_OBSERVED"]),
            ([], [Entry("e", "p", "po", "charge", "USD", 100, 0, 100)], [],
             ["BANK_DEPOSIT_NOT_OBSERVED", "SALE_NOT_OBSERVED"]),
            ([], [], [Deposit("b", "po", "USD", 100)], ["PROCESSOR_PAYOUT_NOT_OBSERVED"]),
        ]
        for sales, entries, deposits, codes in cases:
            with self.subTest(codes=codes):
                result = reconcile(sales, entries, deposits)
                self.assert_codes(result, *codes)
                self.assertFalse(result["summary"]["reconciled"])
                self.assertTrue(all(finding["severity"] == "review" for finding in result["findings"]))

    def test_charge_refund_fee_and_signed_deposit_balance_by_net(self):
        sales = [Sale("s1", "p1", "USD", 1000, 2)]
        entries = [
            Entry("c1", "p1", "po1", "charge", "USD", 1000, 30, 970, 2),
            Entry("r1", "p1", "po1", "refund", "USD", -200, -6, -194, 3),
            Entry("f1", "", "po1", "fee", "USD", 0, 10, -10, 4),
        ]
        result = reconcile(sales, entries, [Deposit("b1", "po1", "USD", 766, 2)])
        self.assert_codes(result)
        self.assertEqual(result["summary"]["matched_sales"], 1)
        self.assertEqual(result["summary"]["matched_payouts"], 1)
        self.assertTrue(result["summary"]["reconciled"])
        self.assertEqual(result["totals_by_currency"], {
            "USD": {"gross_minor": 800, "fee_minor": 34, "net_minor": 766, "bank_minor": 766},
        })

    def test_bank_matching_gross_instead_of_net_is_a_mismatch(self):
        result = reconcile([Sale("s", "p", "USD", 100)],
                           [Entry("e", "p", "po", "charge", "USD", 100, 3, 97)],
                           [Deposit("b", "po", "USD", 100)])
        self.assert_codes(result, "PAYOUT_AMOUNT_MISMATCH")
        self.assertEqual(result["summary"]["matched_payouts"], 0)
        self.assertEqual(result["findings"][0]["details"], {
            "currency": "USD", "expected_minor": 97, "observed_minor": 100, "delta_minor": 3,
        })

    def test_unobserved_sale_charge_and_prior_period_refund_are_reviews(self):
        result = reconcile([Sale("s", "missing", "USD", 100, 2)], [
            Entry("c", "outside", "po", "charge", "USD", 200, 0, 200, 2),
            Entry("r", "historical", "po", "refund", "USD", -100, 0, -100, 3),
            Entry("d", "historical-2", "po", "dispute", "USD", -50, 0, -50, 4),
        ], [Deposit("b", "po", "USD", 50, 2)])
        self.assert_codes(result, "CHARGE_NOT_OBSERVED", "SALE_NOT_OBSERVED",
                          "ORIGINAL_CHARGE_NOT_OBSERVED", "ORIGINAL_CHARGE_NOT_OBSERVED")
        self.assertTrue(all(item["severity"] == "review" for item in result["findings"]))
        self.assertTrue(all(item["evidence"] for item in result["findings"]))
        self.assertEqual(result["summary"]["matched_payouts"], 1)
        self.assertFalse(result["summary"]["reconciled"])

    def test_multiple_charges_are_not_arbitrarily_matched(self):
        result = reconcile([Sale("s", "p", "USD", 100, 2)], [
            Entry("c1", "p", "po", "charge", "USD", 100, 0, 100, 2),
            Entry("c2", "p", "po", "charge", "USD", 200, 0, 200, 3),
        ], [Deposit("b", "po", "USD", 300, 2)])
        self.assert_codes(result, "MULTIPLE_CHARGES")
        self.assertEqual(result["summary"]["matched_sales"], 0)
        self.assertEqual(result["findings"][0]["evidence"], [
            {"source": "processor", "row": 2, "id": "c1"},
            {"source": "processor", "row": 3, "id": "c2"},
            {"source": "sales", "row": 2, "id": "s"},
        ])

    def test_charge_gross_difference_reports_both_source_rows(self):
        result = reconcile([Sale("s", "p", "USD", 100, 8)],
                           [Entry("c", "p", "po", "charge", "USD", 101, 1, 100, 9)],
                           [Deposit("b", "po", "USD", 100, 3)])
        self.assert_codes(result, "CHARGE_AMOUNT_MISMATCH")
        self.assertEqual(result["findings"][0]["severity"], "error")
        self.assertEqual(result["findings"][0]["reference"], "p")
        self.assertEqual(result["findings"][0]["details"], {
            "currency": "USD", "expected_minor": 100, "observed_minor": 101, "delta_minor": 1,
        })
        self.assertEqual(result["findings"][0]["evidence"], [
            {"source": "processor", "row": 9, "id": "c"},
            {"source": "sales", "row": 8, "id": "s"},
        ])

    def test_currency_mismatch_does_not_join_by_amount_or_create_missing_record_findings(self):
        result = reconcile([Sale("s", "p", "USD", 100)],
                           [Entry("c", "p", "po", "charge", "EUR", 100, 0, 100)],
                           [Deposit("b", "po", "EUR", 100)])
        self.assert_codes(result, "CURRENCY_MISMATCH")
        self.assertEqual(result["summary"]["matched_sales"], 0)
        self.assertEqual(result["summary"]["matched_payouts"], 1)

    def test_refund_currency_must_match_observed_charge(self):
        result = reconcile([Sale("s", "p", "USD", 100)], [
            Entry("c", "p", "usd-po", "charge", "USD", 100, 0, 100),
            Entry("r", "p", "eur-po", "refund", "EUR", -10, 0, -10),
        ], [Deposit("b1", "usd-po", "USD", 100), Deposit("b2", "eur-po", "EUR", -10)])
        self.assert_codes(result, "CURRENCY_MISMATCH")

    def test_mixed_currency_payout_never_matches_even_when_integer_total_agrees(self):
        result = reconcile([], [
            Entry("a", "", "po", "adjustment", "USD", 100, 0, 100),
            Entry("b", "", "po", "adjustment", "EUR", 100, 0, 100),
        ], [Deposit("b", "po", "USD", 200)])
        self.assert_codes(result, "PAYOUT_CURRENCY_MISMATCH")
        self.assertEqual(result["summary"]["matched_payouts"], 0)
        self.assertEqual(result["totals_by_currency"], {
            "EUR": {"gross_minor": 100, "fee_minor": 0, "net_minor": 100, "bank_minor": 0},
            "USD": {"gross_minor": 100, "fee_minor": 0, "net_minor": 100, "bank_minor": 200},
        })

    def test_bank_currency_mismatch_blocks_amount_comparison(self):
        result = reconcile([], [Entry("a", "", "po", "adjustment", "USD", 100, 0, 100)],
                           [Deposit("b", "po", "EUR", 999)])
        self.assert_codes(result, "PAYOUT_CURRENCY_MISMATCH")
        self.assertEqual(result["summary"]["matched_payouts"], 0)

    def test_missing_payout_and_missing_bank_are_separate_review_findings(self):
        result = reconcile([], [
            Entry("a", "", "", "fee", "USD", 0, 5, -5, 2),
            Entry("b", "", "processor-only", "adjustment", "USD", 100, 0, 100, 3),
        ], [Deposit("bank-only", "other", "USD", 100, 2)])
        self.assert_codes(result, "PAYOUT_NOT_ATTRIBUTED", "BANK_DEPOSIT_NOT_OBSERVED",
                          "PROCESSOR_PAYOUT_NOT_OBSERVED")
        self.assertTrue(all(item["severity"] == "review" for item in result["findings"]))

    def test_duplicate_input_keys_fail_instead_of_double_counting(self):
        sale = Sale("s", "p", "USD", 100)
        entry = Entry("c", "p", "po", "charge", "USD", 100, 0, 100)
        deposit = Deposit("b", "po", "USD", 100)
        cases = [
            ([sale, Sale("s2", "p", "EUR", 100)], [entry], [deposit], "payment_ref"),
            ([sale, Sale("s", "p2", "USD", 100)], [entry], [deposit], "sale_id"),
            ([sale], [entry, entry], [deposit], "transaction_id"),
            ([sale], [entry], [deposit, Deposit("b", "po2", "USD", 1)], "bank_ref"),
            ([sale], [entry], [deposit, Deposit("b2", "po", "USD", 1)], "payout_id"),
        ]
        for sales, entries, deposits, field in cases:
            with self.subTest(field=field):
                with self.assertRaisesRegex(InputError, field):
                    reconcile(sales, entries, deposits)

    def test_balanced_payments_cannot_reuse_a_sale_evidence_identifier(self):
        sales = [Sale("same-sale", "p1", "USD", 100, 2), Sale("same-sale", "p2", "USD", 100, 3)]
        entries = [
            Entry("c1", "p1", "po", "charge", "USD", 100, 0, 100, 2),
            Entry("c2", "p2", "po", "charge", "USD", 100, 0, 100, 3),
        ]
        with self.assertRaisesRegex(InputError, "sale_id"):
            reconcile(sales, entries, [Deposit("b", "po", "USD", 200, 2)])

    def test_invalid_record_types_are_input_errors(self):
        for records in (([{}], [], []), ([], [{}], []), ([], [], [{}])):
            with self.assertRaises(InputError):
                reconcile(*records)

    def test_negative_payout_and_reversed_fee_keep_accounting_identity(self):
        result = reconcile([], [
            Entry("r", "prior", "po", "refund", "GBP", -1000, -30, -970),
            Entry("f", "", "po", "fee", "GBP", 0, 5, -5),
        ], [Deposit("b", "po", "GBP", -975)])
        self.assert_codes(result, "ORIGINAL_CHARGE_NOT_OBSERVED")
        self.assertEqual(result["summary"]["matched_payouts"], 1)
        self.assertEqual(result["totals_by_currency"]["GBP"], {
            "gross_minor": -1000, "fee_minor": -25, "net_minor": -975, "bank_minor": -975,
        })
        for totals in result["totals_by_currency"].values():
            self.assertEqual(totals["gross_minor"] - totals["fee_minor"], totals["net_minor"])

    def test_large_minor_unit_amounts_are_exact(self):
        amount = 10**30 + 7
        result = reconcile([Sale("s", "p", "INR", amount)],
                           [Entry("c", "p", "po", "charge", "INR", amount, 3, amount - 3)],
                           [Deposit("b", "po", "INR", amount - 3)])
        self.assert_codes(result)
        self.assertEqual(result["totals_by_currency"]["INR"]["net_minor"], amount - 3)
        json.dumps(result)

    def test_amount_mismatch_delta_is_observed_minus_expected_even_when_negative(self):
        result = reconcile([Sale("s", "p", "USD", 100)],
                           [Entry("c", "p", "po", "charge", "USD", 99, 0, 99)],
                           [Deposit("b", "po", "USD", 98)])
        self.assert_codes(result, "CHARGE_AMOUNT_MISMATCH", "PAYOUT_AMOUNT_MISMATCH")
        self.assertEqual(result["findings"][0]["details"], {
            "currency": "USD", "expected_minor": 100, "observed_minor": 99, "delta_minor": -1,
        })
        self.assertEqual(result["findings"][1]["details"], {
            "currency": "USD", "expected_minor": 99, "observed_minor": 98, "delta_minor": -1,
        })

    def test_permutations_produce_identical_json_and_do_not_mutate_inputs(self):
        sales = [Sale("s1", "p1", "USD", 100, 2), Sale("s2", "p2", "EUR", 200, 3)]
        entries = [
            Entry("c1", "p1", "po1", "charge", "USD", 99, 0, 99, 2),
            Entry("c2", "p1", "po1", "charge", "USD", 100, 0, 100, 3),
            Entry("r", "old", "po2", "refund", "EUR", -10, 0, -10, 4),
        ]
        deposits = [Deposit("b1", "po1", "USD", 199, 2), Deposit("b2", "po2", "EUR", -11, 3)]
        original = (sales.copy(), entries.copy(), deposits.copy())
        expected = json.dumps(reconcile(sales, entries, deposits))
        for sales_order, entry_order, deposit_order in itertools.product(
                itertools.permutations(sales), itertools.permutations(entries), itertools.permutations(deposits)):
            self.assertEqual(json.dumps(reconcile(list(sales_order), list(entry_order), list(deposit_order))), expected)
        self.assertEqual((sales, entries, deposits), original)


if __name__ == "__main__":
    unittest.main()
