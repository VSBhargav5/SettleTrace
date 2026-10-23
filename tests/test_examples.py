"""Published examples retain their documented economic outcomes."""

from pathlib import Path
import unittest

from settletrace.engine import reconcile
from settletrace.ingest import load_deposits, load_entries, load_sales


class ExampleTests(unittest.TestCase):
    def run_example(self, name):
        directory = Path(__file__).resolve().parents[1] / "examples" / name
        return reconcile(load_sales(directory / "sales.csv"),
                         load_entries(directory / "processor.csv"),
                         load_deposits(directory / "bank.csv"))

    def test_clean_refund_and_fee_reach_bank(self):
        result = self.run_example("clean")
        self.assertTrue(result["summary"]["reconciled"])
        self.assertEqual(result["summary"]["matched_sales"], 1)
        self.assertEqual(result["summary"]["matched_payouts"], 1)
        self.assertEqual(result["totals_by_currency"]["USD"],
                         {"gross_minor": 8000, "fee_minor": 350,
                          "net_minor": 7650, "bank_minor": 7650})

    def test_exceptions_have_distinct_investigation_paths(self):
        result = self.run_example("exceptions")
        self.assertEqual([f["code"] for f in result["findings"]],
                         ["BANK_DEPOSIT_NOT_OBSERVED", "CHARGE_AMOUNT_MISMATCH",
                          "CHARGE_NOT_OBSERVED", "PAYOUT_AMOUNT_MISMATCH"])
        mismatches = {f["code"]: f["details"] for f in result["findings"] if "details" in f}
        self.assertEqual(mismatches["CHARGE_AMOUNT_MISMATCH"]["delta_minor"], -100)
        self.assertEqual(mismatches["PAYOUT_AMOUNT_MISMATCH"]["delta_minor"], -50)


if __name__ == "__main__":
    unittest.main()
