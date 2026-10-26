from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from settletrace.cli import main
from settletrace.ingest import parse_deposits


class BankCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bank, self.mapping = self.root / "source.csv", self.root / "chosen.csv"
        self.bank.write_text('bank_ref,currency,amount_minor\n"bank\n1",USD,7650\n', encoding="utf-8", newline="")
        self.mapping.write_text('bank_ref,payout_id\n\n"bank\n1",po1\n', encoding="utf-8", newline="")
        self.output = self.root / "mapped"

    def invoke(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["map-bank", "--bank", str(self.bank), "--mapping", str(self.mapping),
                         "--output", str(self.output), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_export_preserves_rows_and_fingerprints_both_original_snapshots(self):
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual({p.name for p in self.output.iterdir()}, {"bank.csv", "audit.json"})
        canonical = (self.output / "bank.csv").read_bytes()
        deposits = parse_deposits(canonical, "bank.csv")
        self.assertEqual((deposits[0].payout_id, deposits[0].amount_minor, deposits[0].row), ("po1", 7650, 3))
        audit = json.loads((self.output / "audit.json").read_text())
        self.assertEqual(audit["rows"], [{"bank_ref": "bank\n1", "payout_id": "po1", "bank_row": 3,
                                        "mapping_row": 4, "canonical_row": 3}])
        for label, path in (("bank", self.bank), ("mapping", self.mapping)):
            self.assertEqual(audit["inputs"][label]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(audit["outputs"]["bank.csv"]["sha256"], hashlib.sha256(canonical).hexdigest())

    def test_ambiguous_mapping_and_capture_limit_produce_no_pack(self):
        self.assertEqual(self.invoke("--max-input-bytes", "5")[0], 2)
        self.assertFalse(self.output.exists())
        self.mapping.write_text(self.mapping.read_text() + '"bank\n1",po2\n')
        self.assertEqual(self.invoke()[0], 2)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_changed(self):
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_bytes(b"untouched")
        self.assertEqual(self.invoke()[0], 2)
        self.assertEqual(sentinel.read_bytes(), b"untouched")

    def test_failed_marker_publication_never_leaves_a_completed_audit(self):
        with patch("pathlib.Path.rename", side_effect=OSError("cannot publish")):
            self.assertEqual(self.invoke()[0], 2)
        self.assertFalse((self.output / "audit.json").exists())
        self.assertTrue((self.output / "bank.csv").exists())

    def verify(self, *extra):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(["verify-bank-map", "--bundle", str(self.output), "--bank", str(self.bank),
                         "--mapping", str(self.mapping), *extra])

    def test_operator_can_replay_the_complete_mapping_pack(self):
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(self.verify(), 0)
        self.assertEqual(self.verify("--max-input-bytes", "5"), 2)
        self.mapping.write_bytes(self.mapping.read_bytes().replace(b"po1", b"po2"))
        self.assertEqual(self.verify(), 2)

    def test_verification_refuses_missing_marker_and_tampered_output(self):
        self.assertEqual(self.invoke()[0], 0)
        canonical = self.output / "bank.csv"
        original = canonical.read_bytes()
        canonical.write_bytes(original + b"tampered")
        self.assertEqual(self.verify(), 2)
        canonical.write_bytes(original)
        (self.output / "audit.json").unlink()
        self.assertEqual(self.verify(), 2)
