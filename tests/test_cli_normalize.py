from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from settletrace.cli import main
from settletrace.ingest import parse_entries


class NormalizeCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "stripe.csv"
        self.source.write_text("balance_transaction_id,charge_id,automatic_payout_id,reporting_category,currency,gross,fee,net,description\n"
                               'txn1,ch1,po1,charge,usd,100.00,3.50,96.50,"first\nline"\n\n'
                               "txn2,ch1,po1,refund,usd,-20.00,0.00,-20.00,refund\n", encoding="utf-8")

    def invoke(self, output="normalized"):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(["normalize-stripe", "--input", str(self.source), "--output", str(self.root / output)])

    def test_export_round_trips_and_audit_retains_original_physical_lines(self):
        before = self.source.read_bytes()
        self.assertEqual(self.invoke(), 0)
        output = self.root / "normalized"
        self.assertEqual({p.name for p in output.iterdir()}, {"processor.csv", "audit.json"})
        data = (output / "processor.csv").read_bytes()
        entries = parse_entries(data, "normalized.csv")
        self.assertEqual(sum(entry.net_minor for entry in entries), 7650)
        self.assertEqual([entry.payment_ref for entry in entries], ["ch1", "ch1"])
        audit = json.loads((output / "audit.json").read_text())
        self.assertEqual(audit["rows"], [{"transaction_id": "txn1", "canonical_row": 2, "source_row": 3},
                                        {"transaction_id": "txn2", "canonical_row": 3, "source_row": 5}])
        self.assertEqual(audit["input"]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(audit["outputs"]["processor.csv"]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(self.source.read_bytes(), before)

    def test_existing_output_and_source_are_preserved(self):
        (self.root / "normalized").mkdir()
        self.assertEqual(self.invoke(), 2)
        before = self.source.read_bytes()
        self.assertEqual(self.invoke("stripe.csv"), 2)
        self.assertEqual(self.source.read_bytes(), before)

    def test_unsupported_activity_never_produces_a_partial_success(self):
        self.source.write_text(self.source.read_text().replace(",refund,", ",fee,"))
        self.assertEqual(self.invoke(), 2)
        self.assertFalse((self.root / "normalized").exists())
