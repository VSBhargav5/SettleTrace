from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from settletrace.cli import main


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sales = self.root / "sales.csv"
        self.processor = self.root / "processor.csv"
        self.bank = self.root / "bank.csv"
        self.sales.write_text("sale_id,payment_ref,currency,gross_minor\ns1,ch1,USD,10000\n", encoding="utf-8")
        self.processor.write_text("transaction_id,payment_ref,payout_id,kind,currency,gross_minor,fee_minor,net_minor\n"
                                  "tx1,ch1,po1,charge,USD,10000,300,9700\n", encoding="utf-8")
        self.bank.write_text("bank_ref,payout_id,currency,amount_minor\nb1,po1,USD,9700\n", encoding="utf-8")

    def invoke(self, output="result"):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(["reconcile", "--sales", str(self.sales), "--processor", str(self.processor),
                         "--bank", str(self.bank), "--output", str(self.root / output)])

    def test_clean_run_writes_a_complete_fingerprinted_bundle(self):
        self.assertEqual(self.invoke(), 0)
        output = self.root / "result"
        self.assertEqual({path.name for path in output.iterdir()}, {"report.json", "report.html", "findings.csv", "manifest.json"})
        result = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertTrue(result["summary"]["reconciled"])
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["inputs"]["sales"]["sha256"], hashlib.sha256(self.sales.read_bytes()).hexdigest())
        for name, fingerprint in manifest["outputs"].items():
            self.assertEqual(fingerprint["sha256"], hashlib.sha256((output / name).read_bytes()).hexdigest())

    def test_mismatch_is_nonzero_and_preserves_expected_observed_delta(self):
        self.bank.write_text("bank_ref,payout_id,currency,amount_minor\nb1,po1,USD,9800\n", encoding="utf-8")
        self.assertEqual(self.invoke(), 1)
        result = json.loads((self.root / "result/report.json").read_text())
        self.assertEqual(result["findings"][0]["details"], {
            "currency": "USD", "expected_minor": 9700, "observed_minor": 9800, "delta_minor": 100,
        })

    def test_review_findings_also_return_one(self):
        self.bank.write_text("bank_ref,payout_id,currency,amount_minor\n", encoding="utf-8")
        self.assertEqual(self.invoke(), 1)

    def test_bad_input_writes_no_bundle(self):
        self.sales.write_text("sale_id,payment_ref,currency,gross_minor\ns1,ch1,USD,100.00\n", encoding="utf-8")
        self.assertEqual(self.invoke(), 2)
        self.assertFalse((self.root / "result").exists())

    def test_no_data_cannot_be_green(self):
        for path in (self.sales, self.processor, self.bank):
            path.write_text(path.read_text().splitlines()[0] + "\n", encoding="utf-8")
        self.assertEqual(self.invoke(), 2)
        self.assertFalse((self.root / "result").exists())

    def test_existing_output_and_input_files_are_not_overwritten(self):
        output = self.root / "result"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("unchanged")
        self.assertEqual(self.invoke(), 2)
        self.assertEqual(sentinel.read_text(), "unchanged")
        original = self.sales.read_bytes()
        self.assertEqual(self.invoke("sales.csv"), 2)
        self.assertEqual(self.sales.read_bytes(), original)

    def test_identical_inputs_produce_identical_output_bytes(self):
        self.assertEqual(self.invoke("one"), 0)
        self.assertEqual(self.invoke("two"), 0)
        for path in (self.root / "one").iterdir():
            self.assertEqual(path.read_bytes(), (self.root / "two" / path.name).read_bytes())

    def test_manifest_write_failure_does_not_publish_completion_marker(self):
        write_text = Path.write_text

        def interrupted(path, content, *args, **kwargs):
            if path.name == ".manifest.json.tmp":
                write_text(path, "{", *args, **kwargs)
                raise OSError("simulated interrupted write")
            return write_text(path, content, *args, **kwargs)

        with patch.object(Path, "write_text", interrupted):
            self.assertEqual(self.invoke(), 2)
        self.assertFalse((self.root / "result/manifest.json").exists())
        self.assertEqual((self.root / "result/.manifest.json.tmp").read_text(), "{")

    def test_report_and_hash_use_same_snapshot_when_source_changes(self):
        from settletrace.ingest import parse_sales
        original = self.sales.read_bytes()

        def changed(data, source):
            # Changes after capture cannot alter what is parsed or fingerprinted.
            self.sales.write_bytes(original.replace(b"10000", b"9999"))
            return parse_sales(data, source)

        with patch("settletrace.cli.parse_sales", side_effect=changed):
            self.assertEqual(self.invoke(), 0)
        manifest = json.loads((self.root / "result/manifest.json").read_text())
        self.assertEqual(manifest["inputs"]["sales"]["sha256"], hashlib.sha256(original).hexdigest())
        self.assertNotEqual(manifest["inputs"]["sales"]["sha256"], hashlib.sha256(self.sales.read_bytes()).hexdigest())
