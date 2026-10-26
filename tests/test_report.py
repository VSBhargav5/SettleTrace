import csv
import io
import unittest

from settletrace.report import findings_csv, format_minor, render_html


def report(reference="ref"):
    return {
        "summary": {"sales": 1, "processor_entries": 1, "matched_payouts": 0, "findings": 1, "reconciled": False},
        "totals_by_currency": {"USD": {"gross_minor": 1000, "fee_minor": 30, "net_minor": 970, "bank_minor": 960}},
        "findings": [{"code": "PAYOUT_AMOUNT_MISMATCH", "severity": "error", "reference": reference,
                      "message": "Expected & observed differ", "evidence": [{"source": "bank", "row": 2, "id": reference}],
                      "details": {"currency": "USD", "expected_minor": 970, "observed_minor": 960, "delta_minor": -10}}],
    }


class ReportTests(unittest.TestCase):
    def test_minor_display_never_rounds_large_integers(self):
        self.assertEqual(format_minor(10**20 + 7, "USD"), "USD 1,000,000,000,000,000,000.07")
        self.assertEqual(format_minor(-1, "INR"), "INR -0.01")

    def test_html_escapes_source_and_record_content(self):
        attack = '<script>alert("x")</script>'
        manifest = {"inputs": {"bank": {"name": attack, "sha256": "abc"}}}
        content = render_html(report(attack), manifest)
        self.assertNotIn("<script>", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertIn("USD -0.10", content)
        self.assertIn("Content-Security-Policy", content)
        self.assertIn("line 2", content)

    def test_csv_neutralizes_spreadsheet_formulas_without_changing_json(self):
        for reference in ("=HYPERLINK(1)", "+SUM(1)", "-SUM(1)", "@SUM(1)", "\t=1", "  =1"):
            with self.subTest(reference=reference):
                result = report(reference)
                row = next(csv.DictReader(io.StringIO(findings_csv(result))))
                self.assertEqual(row["reference"], "'" + reference)
                self.assertEqual(result["findings"][0]["reference"], reference)

    def test_same_named_exports_retain_source_identity(self):
        result = report()
        result["findings"][0]["evidence"] = [
            {"source": source, "row": 2, "id": "same_id"}
            for source in ("sales", "processor", "bank")
        ]
        manifest = {"inputs": {source: {"name": "export.csv", "sha256": "abc"}
                               for source in ("sales", "processor", "bank")}}
        content = render_html(result, manifest)
        for source in ("sales", "processor", "bank"):
            self.assertIn(f"<li>{source}: export.csv · line 2", content)

    def test_empty_findings_export_still_has_the_schema(self):
        result = report()
        result["findings"] = []
        self.assertEqual(list(csv.DictReader(io.StringIO(findings_csv(result)))), [])

    def test_payout_ledger_shows_matching_and_missing_evidence(self):
        from settletrace.engine import reconcile
        from settletrace.models import Deposit, Entry
        result = reconcile([], [Entry("txn<script>", "", "po&1", "adjustment", "USD", 970, 0, 970, 2)],
                           [Deposit("b1", "po&1", "USD", 970, 2), Deposit("b2", "po2", "EUR", 100, 3)])
        manifest = {"inputs": {source: {"name": "export.csv", "sha256": "abc"}
                               for source in ("sales", "processor", "bank")}}
        content = render_html(result, manifest)
        self.assertIn("Payout ledger", content)
        self.assertIn("processor not observed", content)
        self.assertIn("USD 0.00", content)
        self.assertIn("Not compared", content)
        self.assertIn("po&amp;1", content)
        self.assertIn("txn&lt;script&gt;", content)
        self.assertIn("bank: export.csv · line 3", content)
