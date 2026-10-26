from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from settletrace.cli import main


class ExitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = Path(__file__).resolve().parents[1] / "examples/clean"

    def invoke(self, bank, output, *extra):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(["reconcile", "--sales", str(self.inputs / "sales.csv"), "--processor",
                         str(self.inputs / "processor.csv"), "--bank", str(bank),
                         "--output", str(self.root / output), *extra])

    def test_error_only_policy_preserves_reviews_and_does_not_mark_them_reconciled(self):
        bank = self.root / "bank.csv"
        bank.write_text("bank_ref,payout_id,currency,amount_minor\n")
        self.assertEqual(self.invoke(bank, "strict"), 1)
        self.assertEqual(self.invoke(bank, "review", "--fail-on", "error"), 0)
        report = json.loads((self.root / "review/report.json").read_text())
        self.assertFalse(report["summary"]["reconciled"])
        self.assertEqual(report["findings"][0]["severity"], "review")
        manifest = json.loads((self.root / "review/manifest.json").read_text())
        self.assertEqual(manifest["configuration"]["fail_on"], "error")

    def test_errors_and_invalid_input_still_fail(self):
        bank = self.root / "bank.csv"
        bank.write_text("bank_ref,payout_id,currency,amount_minor\nb,po,USD,9999\n")
        # An explicitly mapped wrong amount is an error.
        bank.write_text(bank.read_text().replace(",po,", ",payout_001,"))
        self.assertEqual(self.invoke(bank, "mismatch", "--fail-on", "error"), 1)
        bank.write_text("invalid\n")
        self.assertEqual(self.invoke(bank, "invalid", "--fail-on", "error"), 2)
        self.assertFalse((self.root / "invalid").exists())
