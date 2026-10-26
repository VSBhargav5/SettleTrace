import copy
import unittest

from settletrace.compare import compare_findings
from settletrace.models import InputError


def finding(reference="po1", identifier="txn1", row=2, delta=-1):
    return {"code": "PAYOUT_AMOUNT_MISMATCH", "severity": "error", "reference": reference,
            "message": "Observed differs", "details": {"currency": "USD", "expected_minor": 100,
                                                       "observed_minor": 100 + delta, "delta_minor": delta},
            "evidence": [{"source": "processor", "id": identifier, "row": row}]}


class CompareTests(unittest.TestCase):
    def test_separates_added_removed_and_changed_without_claiming_resolution(self):
        result = compare_findings({"findings": [finding(), finding("gone")]},
                                  {"findings": [finding(delta=-2), finding("new")]})
        self.assertEqual(result["added"][0]["reference"], "new")
        self.assertEqual(result["no_longer_observed"][0]["reference"], "gone")
        self.assertEqual(result["changed"][0]["after"]["details"]["delta_minor"], -2)
        self.assertIn("does not prove resolution", result["note"])
        self.assertEqual(result["unchanged_count"], 0)

    def test_moved_rows_do_not_turn_unchanged_findings_into_new_exceptions(self):
        before = {"findings": [finding(row=2)]}
        saved = copy.deepcopy(before)
        result = compare_findings(before, {"findings": [finding(row=42)]})
        self.assertEqual(result["unchanged_count"], 1)
        self.assertEqual(result["changed"], [])
        self.assertEqual(before, saved)

    def test_same_reference_with_distinct_records_is_not_collapsed(self):
        result = compare_findings({"findings": []}, {"findings": [finding(identifier="b"), finding(identifier="a")]})
        self.assertEqual([f["evidence"][0]["id"] for f in result["added"]], ["a", "b"])

    def test_ambiguous_duplicate_identity_fails_instead_of_overwriting(self):
        with self.assertRaisesRegex(InputError, "duplicate"):
            compare_findings({"findings": [finding(), finding(row=5)]}, {"findings": []})

    def test_empty_observations_are_a_valid_comparison(self):
        result = compare_findings({"findings": []}, {"findings": []})
        self.assertEqual(result["unchanged_count"], 0)
        self.assertEqual(result["added"], [])
