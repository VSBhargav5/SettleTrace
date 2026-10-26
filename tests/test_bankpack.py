"""Replay verifies a mapping pack without trusting its descriptive source names."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from settletrace.bank import map_bank
from settletrace.bankpack import render_bank, verify_bank_map
from settletrace.ingest import parse_deposits
from settletrace.models import InputError


class BankPackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "pack"
        self.bundle.mkdir()
        self.bank = b'bank_ref,currency,amount_minor\n"bank\n1",USD,7650\n\nb2,EUR,-1\n'
        self.mapping = b'bank_ref,payout_id\nb2,p2\n"bank\n1","po\n1"\n'
        deposits, rows = map_bank(self.bank, self.mapping)
        canonical = render_bank(deposits).encode()
        normalized = parse_deposits(canonical, "bank.csv")
        self.audit = {"schema_version": "1", "tool_version": "0.3.0",
                      "inputs": {label: {"name": label + "-original.csv", "size_bytes": len(data),
                                          "sha256": hashlib.sha256(data).hexdigest()}
                                 for label, data in (("bank", self.bank), ("mapping", self.mapping))},
                      "outputs": {"bank.csv": {"sha256": hashlib.sha256(canonical).hexdigest()}},
                      "rows": [{**row, "canonical_row": entry.row} for row, entry in zip(rows, normalized)]}
        (self.bundle / "bank.csv").write_bytes(canonical)
        self.save()

    def save(self):
        (self.bundle / "audit.json").write_text(json.dumps(self.audit), encoding="utf-8")

    def check(self):
        return verify_bank_map(self.bundle, self.bank, self.mapping)

    def test_exact_sources_replay_multiline_canonical_and_source_rows(self):
        checked = self.check()
        self.assertEqual(checked, self.audit)
        self.assertEqual(checked["rows"], [dict(bank_ref="bank\n1", payout_id="po\n1", bank_row=3,
                                               mapping_row=5, canonical_row=4),
                                          dict(bank_ref="b2", payout_id="p2", bank_row=5,
                                               mapping_row=2, canonical_row=5)])
        deposits = parse_deposits((self.bundle / "bank.csv").read_bytes(), "bank.csv")
        self.assertEqual([d.amount_minor for d in deposits], [7650, -1])

    def test_descriptive_source_basenames_need_not_exist_or_match_original_filenames(self):
        self.audit["inputs"]["bank"]["name"] = "renamed-bank.csv"
        self.audit["inputs"]["mapping"]["name"] = "copied-mapping.csv"
        self.save()
        reads = []
        original = Path.read_bytes

        def recorded_read(path):
            reads.append(path)
            return original(path)

        with patch.object(Path, "read_bytes", recorded_read):
            self.check()
        self.assertEqual(set(reads), {self.bundle / "audit.json", self.bundle / "bank.csv"})

    def test_changed_mapping_is_detected_even_when_same_size(self):
        changed = self.mapping.replace(b"p2", b"p3")
        with self.assertRaisesRegex(InputError, "Input hash mismatch: mapping"):
            verify_bank_map(self.bundle, self.bank, changed)

    def test_shorter_bank_source_is_not_accepted(self):
        with self.assertRaisesRegex(InputError, "Input size mismatch: bank"):
            verify_bank_map(self.bundle, self.bank[:-1], self.mapping)

    def test_missing_or_unfinished_completion_marker_is_not_verified(self):
        marker = self.bundle / "audit.json"
        marker.unlink()
        with self.assertRaises(InputError):
            self.check()
        marker.write_text("{")
        with self.assertRaises(InputError):
            self.check()

    def test_changed_output_fails_hash_check(self):
        path = self.bundle / "bank.csv"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(InputError, "Output hash mismatch"):
            self.check()

    def test_recomputed_output_hash_cannot_hide_disagreement_with_source_mapping(self):
        path = self.bundle / "bank.csv"
        data = path.read_bytes().replace(b"7650", b"7651")
        path.write_bytes(data)
        self.audit["outputs"]["bank.csv"]["sha256"] = hashlib.sha256(data).hexdigest()
        self.save()
        with self.assertRaisesRegex(InputError, "replayed explicit mapping"):
            self.check()

    def test_modified_source_fingerprints_still_require_replay_consistency(self):
        self.mapping = self.mapping.replace(b"p2", b"p3")
        self.audit["inputs"]["mapping"]["sha256"] = hashlib.sha256(self.mapping).hexdigest()
        self.save()
        with self.assertRaisesRegex(InputError, "replayed explicit mapping"):
            self.check()

    def test_false_physical_rows_and_missing_or_reordered_audits_are_rejected(self):
        original = json.dumps(self.audit)
        mutations = [lambda rows: rows[0].update(bank_row=2), lambda rows: rows[0].update(canonical_row=3),
                     lambda rows: rows.pop(), lambda rows: rows.reverse()]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.audit = json.loads(original)
                mutation(self.audit["rows"])
                self.save()
                with self.assertRaisesRegex(InputError, "Audit rows disagree"):
                    self.check()

    def test_boolean_and_malformed_row_values_are_not_coerced(self):
        original = json.dumps(self.audit)
        for key, value in (("bank_row", True), ("mapping_row", "5"), ("canonical_row", 0),
                           ("bank_ref", []), ("payout_id", "")):
            with self.subTest(key=key, value=value):
                self.audit = json.loads(original)
                self.audit["rows"][0][key] = value
                self.save()
                with self.assertRaisesRegex(InputError, "Malformed bank mapping audit row"):
                    self.check()

    def test_fingerprints_reject_paths_bool_sizes_and_unknown_output_filenames(self):
        original = json.dumps(self.audit)
        mutations = [lambda a: a["inputs"]["bank"].update(name="../outside.csv"),
                     lambda a: a["inputs"]["mapping"].update(size_bytes=True),
                     lambda a: a["outputs"].update({"../outside.csv": {"sha256": "a" * 64}}),
                     lambda a: a["outputs"].pop("bank.csv")]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.audit = json.loads(original)
                mutation(self.audit)
                self.save()
                with self.assertRaises(InputError):
                    self.check()

    def test_duplicate_json_keys_noninteger_numbers_and_nonobject_roots_fail(self):
        for text in ('{"schema_version":"1","schema_version":"1"}', '{"value":NaN}',
                     '{"value":1.0}', "[]", "{" + '"nested":' + "[" * 2000 + "]" * 2000 + "}"):
            with self.subTest(text=text[:60]):
                (self.bundle / "audit.json").write_text(text)
                with self.assertRaises(InputError):
                    self.check()

    def test_symlink_output_is_rejected(self):
        path = self.bundle / "bank.csv"
        outside = self.root / "outside.csv"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this host")
        with self.assertRaisesRegex(InputError, "non-symlink"):
            self.check()

    def test_symlink_bundle_root_is_rejected(self):
        link = self.root / "linked-pack"
        try:
            link.symlink_to(self.bundle, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this host")
        with self.assertRaisesRegex(InputError, "non-symlink"):
            verify_bank_map(link, self.bank, self.mapping)
