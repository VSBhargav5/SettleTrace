from pathlib import Path
import unittest

from settletrace.engine import reconcile
from settletrace.ingest import load_deposits, load_sales
from settletrace.stripe import parse_stripe


class StripeExampleTests(unittest.TestCase):
    def example(self, name, separator):
        directory = Path(__file__).resolve().parents[1] / "examples" / name
        entries = parse_stripe((directory / "processor.csv").read_bytes(), "processor.csv", decimal_separator=separator)
        result = reconcile(load_sales(directory / "sales.csv"), entries, load_deposits(directory / "bank.csv"))
        self.assertTrue(result["summary"]["reconciled"])
        self.assertEqual(result["summary"]["matched_sales"], 1)
        self.assertEqual(result["summary"]["matched_payouts"], 1)
        self.assertEqual(result["totals_by_currency"]["USD"],
                         {"gross_minor": 8000, "fee_minor": 350, "net_minor": 7650, "bank_minor": 7650})
        self.assertEqual(result["payouts"][0]["entry_count"], 2)
        self.assertEqual([entry.payment_ref for entry in entries], ["ch_demo", "ch_demo"])
        return result

    def test_documented_dot_and_comma_imports_have_identical_economic_results(self):
        self.assertEqual(self.example("stripe", "."), self.example("stripe-comma", ","))
