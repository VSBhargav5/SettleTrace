import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from settletrace.cli import _bundle
from settletrace.engine import reconcile
from settletrace.models import Deposit, Entry, InputError, Sale
from settletrace.verify import verify_bundle


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        result = reconcile([Sale("s", "p", "USD", 100)],
                           [Entry("e", "p", "po", "charge", "USD", 100, 3, 97)],
                           [Deposit("b", "po", "USD", 96)])
        inputs = {key: {"name": key + ".csv", "size_bytes": 1, "sha256": "a" * 64}
                  for key in ("sales", "processor", "bank")}
        _bundle(result, inputs, self.bundle)

    def manifest(self, mutate):
        path = self.bundle / "manifest.json"
        value = json.loads(path.read_text())
        mutate(value)
        path.write_text(json.dumps(value))

    def report(self, text):
        data = text.encode("utf-8")
        (self.bundle / "report.json").write_bytes(data)
        self.manifest(lambda value: value["outputs"]["report.json"].update(sha256=hashlib.sha256(data).hexdigest()))

    def test_valid_bundle_returns_exact_verified_report_even_with_findings(self):
        checked = verify_bundle(self.bundle)
        self.assertEqual(checked["report"]["summary"]["findings"], 1)
        self.assertFalse(checked["report"]["summary"]["reconciled"])

    def test_tampering_any_output_fails(self):
        for name in ("report.html", "findings.csv", "report.json"):
            with self.subTest(name=name):
                path = self.bundle / name
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(InputError, "hash mismatch"):
                    verify_bundle(self.bundle)
                path.write_bytes(original)

    def test_missing_or_truncated_marker_fails(self):
        marker = self.bundle / "manifest.json"
        marker.write_text("{")
        with self.assertRaises(InputError):
            verify_bundle(self.bundle)
        marker.unlink()
        with self.assertRaises(InputError):
            verify_bundle(self.bundle)

    def test_deeply_nested_json_is_a_clean_input_error(self):
        (self.bundle / "manifest.json").write_bytes(b'{"nested":' + b"[" * 2000 + b"]" * 2000 + b"}")
        with self.assertRaisesRegex(InputError, "invalid JSON"):
            verify_bundle(self.bundle)

    def test_untrusted_output_paths_are_never_followed(self):
        self.manifest(lambda value: value["outputs"].update({"../outside.txt": {"sha256": "a" * 64}}))
        with self.assertRaisesRegex(InputError, "exactly"):
            verify_bundle(self.bundle)

    def test_bad_fingerprint_size_is_not_coerced_from_boolean(self):
        self.manifest(lambda value: value["inputs"]["sales"].update(size_bytes=True))
        with self.assertRaisesRegex(InputError, "size"):
            verify_bundle(self.bundle)

    def test_duplicate_keys_and_noninteger_numbers_are_rejected_even_with_matching_hash(self):
        for text in ('{"schema_version":"1","schema_version":"1"}', '{"value":NaN}', '{"value":1e400}'):
            with self.subTest(text=text), self.assertRaises(InputError):
                self.report(text)
                verify_bundle(self.bundle)

    def test_summary_cannot_claim_success_with_findings(self):
        value = json.loads((self.bundle / "report.json").read_text())
        value["summary"]["reconciled"] = True
        self.report(json.dumps(value))
        with self.assertRaisesRegex(InputError, "status"):
            verify_bundle(self.bundle)

    def test_malformed_finding_values_are_input_errors_not_type_crashes(self):
        value = json.loads((self.bundle / "report.json").read_text())
        value["findings"][0]["severity"] = []
        self.report(json.dumps(value))
        with self.assertRaisesRegex(InputError, "severity"):
            verify_bundle(self.bundle)

    def test_symlink_output_is_rejected(self):
        source = self.root / "outside"
        path = self.bundle / "report.html"
        source.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(source)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this host")
        with self.assertRaisesRegex(InputError, "non-symlink"):
            verify_bundle(self.bundle)
