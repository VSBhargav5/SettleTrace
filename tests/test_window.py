import copy
import json
import unittest

from settletrace.models import InputError
from settletrace.window import MAX_WINDOW_BYTES, TIME_BASES, assess_window, parse_window


def declaration():
    return {"schema_version": "1", "account_scope": "synthetic-single-account",
            "sources": {source: {"start_utc": "2026-10-01T00:00:00Z", "end_utc": "2026-11-01T00:00:00Z",
                                 "time_basis": basis, "sha256": "a" * 64, "size_bytes": 10}
                        for source, basis in TIME_BASES.items()}}


class WindowTests(unittest.TestCase):
    def parse(self, value):
        return parse_window(json.dumps(value).encode())

    def test_exact_declaration_is_preserved_and_does_not_claim_completeness(self):
        value = declaration()
        self.assertEqual(self.parse(value), value)
        result = assess_window(value, value["sources"])
        self.assertEqual(result["completeness"], "not_established")
        self.assertFalse(result["row_timestamps_checked"])
        self.assertTrue(result["source_bytes_match"])
        self.assertTrue(result["intervals_have_same_boundaries"])
        self.assertEqual(result["interval_convention"], "start_inclusive_end_exclusive")

    def test_bank_can_have_a_later_window_without_being_declared_complete(self):
        value = declaration()
        value["sources"]["bank"]["end_utc"] = "2026-11-05T00:00:00Z"
        self.assertFalse(assess_window(value, value["sources"])["intervals_have_same_boundaries"])

    def test_hash_or_size_mismatch_fails_instead_of_rebinding_the_declaration(self):
        value = declaration()
        for key, changed in (("sha256", "b" * 64), ("size_bytes", 9)):
            with self.subTest(key=key):
                actual = copy.deepcopy(value["sources"])
                actual["bank"][key] = changed
                with self.assertRaisesRegex(InputError, "bank bytes"):
                    assess_window(value, actual)
        with self.assertRaises(InputError):
            assess_window(value, {})

    def test_naive_offsets_partial_seconds_invalid_dates_and_empty_intervals_rejected(self):
        for stamp in ("2026-10-01", "2026-10-01T00:00:00", "2026-10-01T05:30:00+05:30",
                      "2026-10-01T00:00:00.0Z", "2026-02-30T00:00:00Z", "2026-10-01T24:00:00Z",
                      "2026-10-01T00:00:60Z", "2026-11-01T00:00:00Z", "2027-01-01T00:00:00Z", None):
            with self.subTest(stamp=stamp):
                value = declaration()
                value["sources"]["sales"]["start_utc"] = stamp
                with self.assertRaises(InputError):
                    self.parse(value)

    def test_unknown_scope_version_fields_and_wrong_event_basis_rejected(self):
        mutations = [lambda v: v.update(schema_version="2"), lambda v: v.update(account_scope=" "),
                     lambda v: v.update(account_scope=" padded "), lambda v: v.update(complete=True),
                     lambda v: v["sources"].pop("bank"),
                     lambda v: v["sources"]["processor"].update(time_basis="charge_created_utc"),
                     lambda v: v["sources"]["bank"].update(size_bytes=True),
                     lambda v: v["sources"]["bank"].update(sha256="A" * 64),
                     lambda v: v["sources"]["bank"].update(extra="ignored")]
        for mutate in mutations:
            value = declaration()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(InputError):
                self.parse(value)

    def test_duplicate_keys_numbers_nested_or_malformed_json_rejected_cleanly(self):
        for data in (b'{"schema_version":"1","schema_version":"1"}', b'{"size":NaN}',
                     b'{"size":1.0}', b'{"nested":' + b'[' * 2000 + b']' * 2000 + b'}', b'\xff', b'[]'):
            with self.subTest(data=data[:50]), self.assertRaises(InputError):
                parse_window(data)

    def test_utf8_bom_accepted_and_text_is_not_implicitly_encoded(self):
        data = json.dumps(declaration()).encode()
        self.assertEqual(parse_window(b'\xef\xbb\xbf' + data), declaration())
        with self.assertRaises(TypeError):
            parse_window(data.decode())

    def test_lone_surrogate_and_oversized_declaration_are_clean_input_errors(self):
        value = declaration()
        value["account_scope"] = "\ud800"
        with self.assertRaisesRegex(InputError, "UTF-8"):
            self.parse(value)
        with self.assertRaisesRegex(InputError, "1 MiB"):
            parse_window(b" " * (MAX_WINDOW_BYTES + 1))
