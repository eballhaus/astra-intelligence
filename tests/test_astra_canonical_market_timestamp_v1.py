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

    def test_falls_back_to_now_when_no_native_timestamp(self):
        result = canonical_market_timestamp_v1({})
        self.assertEqual(result["provenance"], "python_fallback")
        self.assertIsNone(result["provider_native_timestamp"])
        self.assertEqual(result["fallback_reason"], "no_provider_native_timestamp_field_available")
        self.assertRegex(result["canonical_timestamp"], r"^\d{4}-\d{2}-\d{2}T")

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

    def test_custom_now_override(self):
        custom = datetime(2025, 12, 18, 20, 5, 0, tzinfo=timezone.utc)
        result = canonical_market_timestamp_v1({}, now=custom)
        self.assertEqual(result["canonical_timestamp"], "2025-12-18T20:05:00Z")


if __name__ == "__main__":
    unittest.main()
