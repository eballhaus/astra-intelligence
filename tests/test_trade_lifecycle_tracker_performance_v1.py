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

    def tearDown(self):
        tracker.TRADE_LIFECYCLE_PATH = self._path
        tracker._LATEST_RECORD_CACHE.clear()
        tracker._LATEST_RECORD_CACHE.update(self._cache)
        tracker._LATEST_RECORD_CACHE_SIGNATURES.clear()
        tracker._LATEST_RECORD_CACHE_SIGNATURES.update(self._signatures)

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

            self.assertEqual(scan.call_count, 1)
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

            self.assertEqual(scan.call_count, 2)


if __name__ == "__main__":
    unittest.main()
