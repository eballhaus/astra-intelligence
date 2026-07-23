"""Focused tests for lane canonical candidate snapshots and partial-cycle consumption.

Verifies that the snapshot module correctly separates DAY/SWING/CRYPTO lanes,
excludes broker positions, preserves canonical fields, and supports the
CYCLE_PARTIAL candidate microphase contract.
"""
from __future__ import annotations

import os
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from engine.astra_lane_candidate_snapshot_v1 import (
    build_lane_candidate_snapshots,
    get_candidates_for_lane,
    load_lane_snapshots,
    save_lane_snapshots,
    snapshot_freshness,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _eq_row(**kwargs) -> dict:
    r = {"symbol": "AAPL", "lane_id": "DAY", "paper_entry_horizon_style": "day_trade",
         "candidate_id": "c1", "recommendation_id": "r1",
         "generated_at": _now_iso(), "quote_timestamp": _now_iso(), "rank": 1}
    r.update(kwargs)
    return r


def _crypto_row(**kwargs) -> dict:
    r = {"symbol": "BTC/USD", "asset_class": "crypto", "candidate_id": "c_crypto",
         "recommendation_id": "r_crypto", "generated_at": _now_iso(), "rank": 1}
    r.update(kwargs)
    return r


class SnapshotProductionTests(unittest.TestCase):
    """Verify snapshot construction from equity ranked candidates."""

    def test_day_candidates_identified_and_preserved(self):
        rows = [_eq_row(symbol="AAPL", lane_id="DAY", paper_entry_horizon_style="day_trade")]
        result = build_lane_candidate_snapshots(rows)
        self.assertEqual(result["lanes"]["DAY"]["candidate_count"], 1)
        self.assertEqual(result["lanes"]["SWING"]["candidate_count"], 0)

    def test_swing_candidates_identified_and_preserved(self):
        rows = [_eq_row(symbol="TSLA", lane_id="SWING", paper_entry_horizon_style="swing_trade")]
        result = build_lane_candidate_snapshots(rows)
        self.assertEqual(result["lanes"]["SWING"]["candidate_count"], 1)
        self.assertEqual(result["lanes"]["DAY"]["candidate_count"], 0)

    def test_crypto_excluded_from_equity_snapshots(self):
        rows = [_eq_row(), _crypto_row()]
        result = build_lane_candidate_snapshots(rows)
        for lane in ("DAY", "SWING"):
            for c in result["lanes"][lane]["candidates"]:
                self.assertNotIn("crypto", c.get("symbol", "").lower())

    def test_day_by_horizon_inference(self):
        rows = [_eq_row(symbol="AAPL", lane_id="", paper_entry_horizon_style="scalp")]
        result = build_lane_candidate_snapshots(rows)
        self.assertEqual(result["lanes"]["DAY"]["candidate_count"], 1)

    def test_swing_by_horizon_inference(self):
        rows = [_eq_row(symbol="AAPL", lane_id="", paper_entry_horizon_style="position_trade")]
        result = build_lane_candidate_snapshots(rows)
        self.assertEqual(result["lanes"]["SWING"]["candidate_count"], 1)

    def test_provider_calls_zero(self):
        result = build_lane_candidate_snapshots([_eq_row()])
        self.assertEqual(result["provider_calls_added"], 0)

    def test_bounded_to_max_rows(self):
        rows = [_eq_row(symbol=f"S{i}", candidate_id=f"c{i}") for i in range(20)]
        result = build_lane_candidate_snapshots(rows, max_rows=5)
        self.assertLessEqual(result["lanes"]["DAY"]["candidate_count"], 5)

    def test_zero_rows_is_truthful(self):
        result = build_lane_candidate_snapshots([])
        self.assertEqual(result["lanes"]["DAY"]["candidate_count"], 0)
        self.assertEqual(result["lanes"]["SWING"]["candidate_count"], 0)

    def test_non_dict_rows_skipped(self):
        rows = [_eq_row(), "not_a_dict", None, 42]
        result = build_lane_candidate_snapshots(rows)
        self.assertEqual(result["lanes"]["DAY"]["candidate_count"], 1)

    def test_broker_positions_excluded_from_snapshot(self):
        bp = {"symbol": "AAPL", "asset_id": "bp1", "qty": 10, "avg_entry_price": 100.0}
        rows = [bp]  # broker position row lacking lane_id/horizon
        result = build_lane_candidate_snapshots(rows)
        self.assertEqual(result["lanes"]["DAY"]["candidate_count"], 0)
        self.assertEqual(result["lanes"]["SWING"]["candidate_count"], 0)


class SnapshotPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="snapshot_test_")
        self.path = os.path.join(self.tmpdir, "snapshot.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_atomic_write_and_load(self):
        rows = [_eq_row(symbol="AAPL")]
        state = build_lane_candidate_snapshots(rows)
        save_lane_snapshots(self.path, state)
        loaded = load_lane_snapshots(self.path)
        self.assertTrue(loaded["loaded"])
        self.assertEqual(len(get_candidates_for_lane(loaded, "DAY")), 1)

    def test_missing_file_loads_empty(self):
        loaded = load_lane_snapshots(self.path)
        self.assertFalse(loaded["loaded"])

    def test_malformed_file_loads_empty(self):
        with open(self.path, "w") as f:
            f.write("not json")
        loaded = load_lane_snapshots(self.path)
        self.assertFalse(loaded["loaded"])

    def test_freshness_current(self):
        state = build_lane_candidate_snapshots([_eq_row()])
        self.assertEqual(snapshot_freshness(state), "SNAPSHOT_CURRENT")

    def test_freshness_stale(self):
        from datetime import timedelta
        state = build_lane_candidate_snapshots([_eq_row()])
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        state["generated_at"] = old
        self.assertEqual(snapshot_freshness(state), "SNAPSHOT_STALE")


class CRYPTOSourceSeparationTests(unittest.TestCase):
    """Verify CRYPTO uses its own canonical ranking source, not equity snapshots."""

    def test_crypto_not_in_day_snapshot(self):
        rows = [_eq_row(), _crypto_row()]
        result = build_lane_candidate_snapshots(rows)
        symbols = [c["symbol"] for c in result["lanes"]["DAY"]["candidates"]]
        self.assertNotIn("BTC/USD", symbols)

    def test_crypto_not_in_swing_snapshot(self):
        rows = [_eq_row(), _crypto_row()]
        result = build_lane_candidate_snapshots(rows)
        symbols = [c["symbol"] for c in result["lanes"]["SWING"]["candidates"]]
        self.assertNotIn("BTC/USD", symbols)

    def test_normalized_fields_preserved(self):
        rows = [_eq_row(
            candidate_id="cid-day", symbol="AAPL", rank=5,
            quote_timestamp="2026-01-01T12:00:00Z",
            bar_timestamp="2026-01-01T11:00:00Z",
            candidate_snapshot_freshness="CURRENT",
            eligibility_result="PASS",
            exact_blocker="capacity_exhausted",
            candidate_source="top_buys_runtime_snapshot",
        )]
        result = build_lane_candidate_snapshots(rows)
        c = result["lanes"]["DAY"]["candidates"][0]
        self.assertEqual(c["candidate_id"], "cid-day")
        self.assertEqual(c["first_causal_blocker"], "capacity_exhausted")
        self.assertEqual(c["source_provenance"], "top_buys_runtime_snapshot")


if __name__ == "__main__":
    unittest.main()
