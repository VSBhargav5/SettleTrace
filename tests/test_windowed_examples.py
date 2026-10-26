import hashlib
from pathlib import Path
import unittest

from settletrace.bank import map_bank
from settletrace.bankpack import render_bank
from settletrace.engine import reconcile
from settletrace.ingest import parse_deposits, parse_sales
from settletrace.stripe import parse_stripe
from settletrace.window import assess_window, parse_window


class WindowedExampleTests(unittest.TestCase):
    def test_documented_fixture_maps_exactly_and_keeps_completeness_unproven(self):
        root = Path(__file__).resolve().parents[1] / "examples/windowed"
        deposits, audit = map_bank((root / "bank-extract.csv").read_bytes(), (root / "mapping.csv").read_bytes())
        canonical = render_bank(deposits).encode()
        snapshots = {"sales": (root / "sales.csv").read_bytes(), "processor": (root / "processor.csv").read_bytes(),
                     "bank": canonical}
        fingerprints = {source: {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
                        for source, data in snapshots.items()}
        window = assess_window(parse_window((root / "window.json").read_bytes()), fingerprints)
        result = reconcile(parse_sales(snapshots["sales"], "sales"), parse_stripe(snapshots["processor"], "stripe"),
                           parse_deposits(canonical, "mapped bank"))
        self.assertEqual(result["payouts"][0]["delta_minor"], 0)
        self.assertEqual(result["totals_by_currency"]["USD"]["bank_minor"], 7650)
        self.assertEqual(audit[0]["mapping_row"], 2)
        self.assertEqual(window["completeness"], "not_established")
        self.assertFalse(window["intervals_have_same_boundaries"])
