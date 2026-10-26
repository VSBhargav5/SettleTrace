from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from settletrace.cli import main


class VerifyCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = Path(__file__).resolve().parents[1] / "examples/clean"
        self.bundle = self.root / "bundle"
        with redirect_stdout(io.StringIO()):
            code = main(["reconcile", "--sales", str(self.inputs / "sales.csv"), "--processor",
                         str(self.inputs / "processor.csv"), "--bank", str(self.inputs / "bank.csv"),
                         "--output", str(self.bundle)])
        self.assertEqual(code, 0)

    def invoke(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["verify", "--bundle", str(self.bundle), *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_verifies_a_complete_bundle(self):
        code, stdout, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertIn("bundle hashes verified", stdout)

    def test_tampered_report_is_not_verified(self):
        report = self.bundle / "report.html"
        report.write_bytes(report.read_bytes() + b"tampered")
        code, _, stderr = self.invoke()
        self.assertEqual(code, 2)
        self.assertTrue(stderr)

    def test_missing_completion_marker_is_not_verified(self):
        (self.bundle / "manifest.json").unlink()
        code, _, _ = self.invoke()
        self.assertEqual(code, 2)

    def source_args(self, sales=None):
        return ["--sales", str(sales or self.inputs / "sales.csv"),
                "--processor", str(self.inputs / "processor.csv"), "--bank", str(self.inputs / "bank.csv")]

    def test_supplied_sources_can_be_copied_and_renamed_without_changing_content(self):
        renamed = self.root / "renamed.csv"
        renamed.write_bytes((self.inputs / "sales.csv").read_bytes())
        code, stdout, _ = self.invoke(*self.source_args(renamed))
        self.assertEqual(code, 0)
        self.assertIn("all three supplied source files", stdout)

    def test_same_sized_changed_source_does_not_pass_hash_verification(self):
        changed = self.root / "changed.csv"
        changed.write_bytes((self.inputs / "sales.csv").read_bytes().replace(b"10000", b"10001"))
        code, _, stderr = self.invoke(*self.source_args(changed))
        self.assertEqual(code, 2)
        self.assertIn("Input hash mismatch: sales", stderr)

    def test_partial_source_selection_does_not_claim_all_inputs_verified(self):
        code, stdout, stderr = self.invoke("--sales", str(self.inputs / "sales.csv"))
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("all three source paths", stderr)

    def test_truncated_source_does_not_pass_size_verification(self):
        changed = self.root / "short.csv"
        changed.write_bytes(b"short")
        code, _, stderr = self.invoke(*self.source_args(changed))
        self.assertEqual(code, 2)
        self.assertIn("Input size mismatch: sales", stderr)
