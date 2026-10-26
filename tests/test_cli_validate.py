from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from settletrace.cli import main


class ValidateCliTests(unittest.TestCase):
    def invoke(self, example="clean", *extra):
        directory = Path(__file__).resolve().parents[1] / "examples" / example
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["validate", "--sales", str(directory / "sales.csv"), "--processor",
                         str(directory / "processor.csv"), "--bank", str(directory / "bank.csv"), *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_validation_reports_contract_success_without_claiming_reconciled(self):
        code, stdout, _ = self.invoke("exceptions")
        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertTrue(result["valid"])
        self.assertEqual(result["observed_findings"], 4)
        self.assertNotIn("reconciled", result)

    def test_raw_validation_uses_explicit_format_and_writes_nothing(self):
        code, stdout, _ = self.invoke("clean")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["records"], {"sales": 1, "processor": 3, "bank": 1})

    def test_invalid_contract_returns_two_without_a_success_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / "bad.csv"
            invalid.write_text("sale_id,payment_ref,currency,gross_minor\ns,p,USD,1.001\n")
            code, stdout, stderr = self.invoke("clean", "--sales", str(invalid))
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("integer", stderr)
