"""Focused coverage for append-only lifecycle tracker cache reuse."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import engine.trade_lifecycle_tracker as tracker


class TradeLifecycleTrackerPerformanceTests(unittest.TestCase):
    def setUp(self):
        self._path = tracker.TRADE_LIFECYCLE_PATH
        self._cache = tracker._LATEST_RECORD_CACHE.copy()
        self._signatures = tracker._LATEST_RECORD_CACHE_SIGNATURES.copy()
        self._offsets = tracker._LATEST_RECORD_CACHE_OFFSETS.copy()

    def tearDown(self):
        tracker.TRADE_LIFECYCLE_PATH = self._path
        tracker._LATEST_RECORD_CACHE.clear()
        tracker._LATEST_RECORD_CACHE.update(self._cache)
        tracker._LATEST_RECORD_CACHE_SIGNATURES.clear()
        tracker._LATEST_RECORD_CACHE_SIGNATURES.update(self._signatures)
        tracker._LATEST_RECORD_CACHE_OFFSETS.clear()
        tracker._LATEST_RECORD_CACHE_OFFSETS.update(self._offsets)

    def test_repeated_progress_updates_reuse_latest_map(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker.TRADE_LIFECYCLE_PATH = str(Path(directory) / "trade_lifecycle_v1.jsonl")
            tracker._LATEST_RECORD_CACHE.clear()
            tracker._LATEST_RECORD_CACHE_SIGNATURES.clear()
            tracker.create_lifecycle_record({
                "lifecycle_id": "life-1",
                "symbol": "AAPL",
                "entry_timestamp": "2026-09-02T12:00:00Z",
                "entry_price": 100.0,
                "source_endpoint": "test",
            })
            with patch.object(tracker, "_scan_latest_record_map", wraps=tracker._scan_latest_record_map) as scan:
                first = tracker.update_lifecycle_progress("life-1", {"current_price": 101.0})
                second = tracker.update_lifecycle_progress("life-1", {"current_price": 102.0})

            self.assertEqual(scan.call_count, 0)
            self.assertEqual(first["current_price"], 101.0)
            self.assertEqual(second["current_price"], 102.0)

    def test_external_append_invalidates_cached_latest_map(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker.TRADE_LIFECYCLE_PATH = str(Path(directory) / "trade_lifecycle_v1.jsonl")
            tracker._LATEST_RECORD_CACHE.clear()
            tracker._LATEST_RECORD_CACHE_SIGNATURES.clear()
            tracker.create_lifecycle_record({
                "lifecycle_id": "life-1",
                "symbol": "AAPL",
                "entry_timestamp": "2026-09-02T12:00:00Z",
                "entry_price": 100.0,
                "source_endpoint": "test",
            })
            with patch.object(tracker, "_scan_latest_record_map", wraps=tracker._scan_latest_record_map) as scan:
                tracker.update_lifecycle_progress("life-1", {"current_price": 101.0})
                with open(tracker.TRADE_LIFECYCLE_PATH, "a", encoding="utf-8") as handle:
                    handle.write("{\"lifecycle_id\":\"external\",\"symbol\":\"MSFT\"}\n")
                tracker.update_lifecycle_progress("life-1", {"current_price": 102.0})

            self.assertEqual(scan.call_count, 0)
            self.assertEqual(tracker._LATEST_RECORD_CACHE[str(Path(directory) / "trade_lifecycle_v1.jsonl")]["external"]["symbol"], "MSFT")

    def test_lifecycle_hot_cache_is_bounded_and_old_identity_is_resolved_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker.TRADE_LIFECYCLE_PATH = str(Path(directory) / "trade_lifecycle_v1.jsonl")
            tracker._LATEST_RECORD_CACHE.clear()
            tracker._LATEST_RECORD_CACHE_SIGNATURES.clear()
            tracker._LATEST_RECORD_CACHE_OFFSETS.clear()
            for index in range(tracker.LATEST_RECORD_CACHE_MAX_ITEMS + 64):
                tracker.create_lifecycle_record({
                    "lifecycle_id": f"life-{index}",
                    "symbol": "AAPL",
                    "entry_timestamp": f"2026-09-02T12:{index % 60:02d}:00Z",
                    "entry_price": 100.0,
                    "source_endpoint": "test",
                })

            recent = tracker.load_recent_lifecycle_records(limit=10)
            cache = tracker._LATEST_RECORD_CACHE[str(Path(directory) / "trade_lifecycle_v1.jsonl")]
            self.assertEqual(len(recent), 10)
            self.assertLessEqual(len(cache), tracker.LATEST_RECORD_CACHE_MAX_ITEMS)
            updated = tracker.update_lifecycle_progress("life-0", {"current_price": 101.0})

            self.assertEqual(updated["lifecycle_id"], "life-0")
            self.assertEqual(updated["symbol"], "AAPL")
            self.assertEqual(updated["current_price"], 101.0)
            self.assertLessEqual(len(cache), tracker.LATEST_RECORD_CACHE_MAX_ITEMS)


if __name__ == "__main__":
    unittest.main()
