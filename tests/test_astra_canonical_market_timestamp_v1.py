"""Tests for canonical market timestamp helper."""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone

from engine.astra_canonical_market_timestamp_v1 import (
    canonical_market_timestamp_iso_v1,
    canonical_market_timestamp_v1,
)


class CanonicalMarketTimestampTests(unittest.TestCase):
    def test_prefers_observation_timestamp(self):
        record = {
            "observation_timestamp": "2025-12-18T20:00:00Z",
            "market_timestamp": "2025-12-18T20:01:00Z",
            "timestamp": "2025-12-18T20:02:00Z",
        }
        result = canonical_market_timestamp_v1(record)
        self.assertEqual(result["provenance"], "provider_native")
        self.assertEqual(result["source_field"], "observation_timestamp")
        self.assertEqual(result["provider_native_timestamp"], "2025-12-18T20:00:00Z")
        self.assertEqual(result["canonical_timestamp"], "2025-12-18T20:00:00Z")

    def test_prefers_market_timestamp_when_observation_missing(self):
        record = {
            "market_timestamp": "2025-12-18T20:01:00Z",
            "timestamp": "2025-12-18T20:02:00Z",
        }
        result = canonical_market_timestamp_v1(record)
        self.assertEqual(result["source_field"], "market_timestamp")
        self.assertEqual(result["canonical_timestamp"], "2025-12-18T20:01:00Z")

    def test_missing_native_timestamp_fails_closed_without_now_fallback(self):
        result = canonical_market_timestamp_v1({})
        self.assertEqual(result["provenance"], "unavailable")
        self.assertIsNone(result["provider_native_timestamp"])
        self.assertEqual(result["freshness_status"], "UNAVAILABLE")
        self.assertIsNone(result["canonical_timestamp"])

    def test_iso_wrapper_returns_string(self):
        record = {"quote_timestamp": "2025-12-18T20:03:00Z"}
        ts = canonical_market_timestamp_iso_v1(record)
        self.assertEqual(ts, "2025-12-18T20:03:00Z")

    def test_empty_strings_treated_as_missing(self):
        record = {
            "observation_timestamp": "",
            "market_timestamp": None,
            "quote_timestamp": "2025-12-18T20:04:00Z",
        }
        result = canonical_market_timestamp_v1(record)
        self.assertEqual(result["source_field"], "quote_timestamp")

    def test_custom_now_override_never_becomes_market_time(self):
        custom = datetime(2025, 12, 18, 20, 5, 0, tzinfo=timezone.utc)
        result = canonical_market_timestamp_v1({}, now=custom)
        self.assertIsNone(result["canonical_timestamp"])
        self.assertEqual(result["retrieval_timestamp"], "2025-12-18T20:05:00Z")

    def test_generic_record_timestamps_are_rejected(self):
        result = canonical_market_timestamp_v1({"timestamp": "2025-12-18T20:00:00Z", "updated_at": "2025-12-18T20:00:00Z", "created_at": "2025-12-18T20:00:00Z"})
        self.assertTrue(result["market_observation_unavailable"])

    def test_completed_bar_is_not_executable_quote_freshness(self):
        result = canonical_market_timestamp_v1({"bar_timestamp": "2025-12-18T20:00:00Z"}, source_type="COMPLETED_BAR", now=datetime(2025, 12, 18, 20, 1, tzinfo=timezone.utc))
        self.assertEqual(result["freshness_status"], "FRESH")
        self.assertFalse(result["executable_freshness"])


if __name__ == "__main__":
    unittest.main()
