from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from settletrace.cli import main


class FormatCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sales = self.root / "sales.csv"
        self.processor = self.root / "stripe.csv"
        self.bank = self.root / "bank.csv"
        self.sales.write_text("sale_id,payment_ref,currency,gross_minor\ns1,ch1,USD,10000\n")
        self.processor.write_text("balance_transaction_id,charge_id,automatic_payout_id,reporting_category,currency,gross,fee,net\n"
                                  "txn1,ch1,po1,charge,usd,100.00,3.00,97.00\n")
        self.bank.write_text("bank_ref,payout_id,currency,amount_minor\nb1,po1,USD,9700\n")

    def invoke(self, *extra):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(["reconcile", "--sales", str(self.sales), "--processor", str(self.processor),
                         "--bank", str(self.bank), "--output", str(self.root / "report"), *extra])

    def test_raw_mode_preserves_source_hash_and_conversion_configuration(self):
        self.assertEqual(self.invoke("--processor-format", "stripe-payout-itemized-7"), 0)
        manifest = json.loads((self.root / "report/manifest.json").read_text())
        self.assertEqual(manifest["configuration"], {"processor_format": "stripe-payout-itemized-7", "decimal_separator": "."})
        self.assertEqual(manifest["inputs"]["processor"]["sha256"], hashlib.sha256(self.processor.read_bytes()).hexdigest())
        result = json.loads((self.root / "report/report.json").read_text())
        self.assertEqual(result["totals_by_currency"]["USD"]["net_minor"], 9700)
        html = (self.root / "report/report.html").read_text(encoding="utf-8")
        self.assertIn("stripe-payout-itemized-7", html)

    def test_default_format_does_not_guess_from_header_or_values(self):
        self.assertEqual(self.invoke(), 2)
        self.assertFalse((self.root / "report").exists())

    def test_canonical_mode_does_not_reinterpret_values_as_localized_major_units(self):
        self.assertEqual(self.invoke("--decimal-separator", ","), 2)
        self.assertFalse((self.root / "report").exists())
