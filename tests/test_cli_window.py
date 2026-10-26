from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from settletrace.cli import main
from settletrace.models import InputError
from settletrace.verify import verify_bundle
from settletrace.window import TIME_BASES


class WindowCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = Path(__file__).resolve().parents[1] / "examples/clean"
        self.window = self.root / "window.json"
        self.declaration = {"schema_version": "1", "account_scope": "demo<script>alert(1)</script>", "sources": {}}
        for source, basis in TIME_BASES.items():
            data = (self.inputs / (source + ".csv")).read_bytes()
            self.declaration["sources"][source] = {"time_basis": basis, "start_utc": "2026-10-01T00:00:00Z",
                "end_utc": "2026-11-01T00:00:00Z", "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        self.save()

    def save(self):
        self.window.write_text(json.dumps(self.declaration), encoding="utf-8")

    def sources(self):
        return [arg for source in TIME_BASES for arg in ("--" + source, str(self.inputs / (source + ".csv")))]

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def reconcile(self, name="pack", window=True):
        args = ["reconcile", *self.sources(), "--output", str(self.root / name)]
        return self.invoke(*args, *(["--window", str(self.window)] if window else []))

    def test_window_is_in_hashed_report_manifest_and_escaped_html(self):
        self.assertEqual(self.reconcile()[0], 0)
        checked = verify_bundle(self.root / "pack")
        self.assertEqual(checked["report"]["observation_window"]["completeness"], "not_established")
        self.assertTrue(checked["report"]["summary"]["reconciled"])
        self.assertEqual(set(checked["manifest"]["inputs"]), {"sales", "processor", "bank", "window"})
        html = (self.root / "pack/report.html").read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("No records were date-filtered", html)

    def test_declared_fingerprint_mismatch_is_rejected_before_output(self):
        self.declaration["sources"]["processor"]["sha256"] = "0" * 64
        self.save()
        code, _, err = self.reconcile()
        self.assertEqual(code, 2)
        self.assertIn("processor bytes", err)
        self.assertFalse((self.root / "pack").exists())

    def test_validation_discloses_declaration_without_creating_a_pack(self):
        code, out, _ = self.invoke("validate", *self.sources(), "--window", str(self.window))
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertFalse(result["observation_window"]["row_timestamps_checked"])
        self.assertTrue(result["valid"])

    def test_all_source_verification_requires_the_recorded_window_too(self):
        self.assertEqual(self.reconcile()[0], 0)
        args = ["verify", "--bundle", str(self.root / "pack"), *self.sources()]
        self.assertEqual(self.invoke(*args)[0], 2)
        self.assertEqual(self.invoke(*args, "--window", str(self.window))[0], 0)
        self.declaration["account_scope"] = "changed"
        self.save()
        self.assertEqual(self.invoke(*args, "--window", str(self.window))[0], 2)

    def test_old_bundle_still_verifies_and_rejects_an_unrecorded_window_source(self):
        self.assertEqual(self.reconcile(window=False)[0], 0)
        self.assertEqual(self.invoke("verify", "--bundle", str(self.root / "pack"), *self.sources())[0], 0)
        self.assertEqual(self.invoke("verify", "--bundle", str(self.root / "pack"), *self.sources(),
                                     "--window", str(self.window))[0], 2)

    def test_comparison_discloses_changed_window_with_identical_financial_findings(self):
        self.assertEqual(self.reconcile("before")[0], 0)
        self.declaration["sources"]["bank"]["end_utc"] = "2026-11-05T00:00:00Z"
        self.save()
        self.assertEqual(self.reconcile("after")[0], 0)
        code, out, _ = self.invoke("compare", "--baseline", str(self.root / "before"), "--current", str(self.root / "after"))
        result = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(result["input_changes"], ["window"])
        self.assertTrue(result["observation_window_changed"])
        self.assertEqual(result["added"], [])
        self.assertEqual(result["changed"], [])

    def test_comparison_discloses_added_window_in_old_and_new_bundle(self):
        self.assertEqual(self.reconcile("old", window=False)[0], 0)
        self.assertEqual(self.reconcile("new")[0], 0)
        code, out, _ = self.invoke("compare", "--baseline", str(self.root / "old"), "--current", str(self.root / "new"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["input_changes"], ["window"])

    def test_window_claims_cannot_be_changed_even_after_rehashing_the_report(self):
        self.assertEqual(self.reconcile()[0], 0)
        directory = self.root / "pack"
        report = json.loads((directory / "report.json").read_text())
        report["observation_window"]["completeness"] = "complete"
        data = json.dumps(report).encode()
        (directory / "report.json").write_bytes(data)
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest["outputs"]["report.json"]["sha256"] = hashlib.sha256(data).hexdigest()
        (directory / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(InputError, "assessment"):
            verify_bundle(directory)

    def test_window_does_not_suppress_an_absent_bank_finding(self):
        bank = self.root / "empty.csv"
        bank.write_bytes(b"bank_ref,payout_id,currency,amount_minor\n")
        data = bank.read_bytes()
        self.declaration["sources"]["bank"].update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                                                  end_utc="2026-12-01T00:00:00Z")
        self.save()
        args = self.sources()
        args[args.index("--bank") + 1] = str(bank)
        code, _, _ = self.invoke("reconcile", *args, "--window", str(self.window), "--output", str(self.root / "pack"))
        self.assertEqual(code, 1)
        checked = verify_bundle(self.root / "pack")
        self.assertEqual(checked["report"]["findings"][0]["code"], "BANK_DEPOSIT_NOT_OBSERVED")

    def test_rehashed_report_cannot_substitute_dates_for_original_window_bytes(self):
        self.assertEqual(self.reconcile()[0], 0)
        directory = self.root / "pack"
        report = json.loads((directory / "report.json").read_text())
        for source in report["observation_window"]["declaration"]["sources"].values():
            source["end_utc"] = "2026-12-01T00:00:00Z"
        data = json.dumps(report).encode()
        (directory / "report.json").write_bytes(data)
        manifest = json.loads((directory / "manifest.json").read_text())
        manifest["outputs"]["report.json"]["sha256"] = hashlib.sha256(data).hexdigest()
        (directory / "manifest.json").write_text(json.dumps(manifest))
        # Bundle consistency alone does not authenticate its declared sources.
        verify_bundle(directory)
        code, out, err = self.invoke("verify", "--bundle", str(directory), *self.sources(), "--window", str(self.window))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("declaration disagrees", err)
