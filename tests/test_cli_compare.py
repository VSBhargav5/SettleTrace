from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from settletrace.cli import main


class CompareCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        inputs = Path(__file__).resolve().parents[1] / "examples/clean"
        bank = self.root / "bank.csv"
        for name, amount, expected in (("baseline", 7651, 1), ("current", 7650, 0)):
            bank.write_text(f"bank_ref,payout_id,currency,amount_minor\nb,payout_001,USD,{amount}\n")
            with redirect_stdout(io.StringIO()):
                code = main(["reconcile", "--sales", str(inputs / "sales.csv"), "--processor",
                             str(inputs / "processor.csv"), "--bank", str(bank), "--output", str(self.root / name)])
            self.assertEqual(code, expected)

    def invoke(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["compare", "--baseline", str(self.root / "baseline"), "--current", str(self.root / "current")])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_comparison_discloses_changed_inputs_without_claiming_resolution(self):
        code, stdout, _ = self.invoke()
        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["no_longer_observed"][0]["code"], "PAYOUT_AMOUNT_MISMATCH")
        self.assertEqual(result["input_changes"], ["bank"])
        self.assertIn("does not prove resolution", result["note"])

    def test_comparison_refuses_a_tampered_baseline(self):
        (self.root / "baseline/report.html").write_text("changed")
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("hash mismatch", stderr)
