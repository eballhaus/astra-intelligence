"""Tests for canonical market timestamp helper."""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone

from engine.astra_canonical_market_timestamp_v1 import (
    ALPACA_EQUITY_FUTURE_TIMESTAMP_TOLERANCE_SECONDS,
    canonical_market_timestamp_iso_v1,
    canonical_market_timestamp_v1,
    provider_future_timestamp_tolerance_seconds_v1,
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

    def test_future_provider_timestamp_fails_closed_by_default(self):
        now = datetime(2025, 12, 18, 20, 0, 0, tzinfo=timezone.utc)
        result = canonical_market_timestamp_v1(
            {"provider_native_timestamp": "2025-12-18T20:00:00.001Z"},
            now=now,
            source_type="QUOTE",
        )
        self.assertEqual(result["freshness_status"], "INVALID")
        self.assertEqual(result["first_causal_blocker"], "FUTURE_PROVIDER_NATIVE_TIMESTAMP")
        self.assertAlmostEqual(result["future_offset_seconds"], 0.001, places=6)

    def test_measured_alpaca_equity_jitter_is_bounded_and_observable(self):
        now = datetime(2025, 12, 18, 20, 0, 0, tzinfo=timezone.utc)
        quote = {
            "asset_type": "stock",
            "provider_used": "alpaca",
            "provider_native_timestamp": "2025-12-18T20:00:00.100Z",
        }
        tolerance = provider_future_timestamp_tolerance_seconds_v1(quote, source_type="QUOTE")
        self.assertEqual(tolerance, ALPACA_EQUITY_FUTURE_TIMESTAMP_TOLERANCE_SECONDS)
        result = canonical_market_timestamp_v1(
            quote,
            now=now,
            source_type="QUOTE",
            future_tolerance_seconds=tolerance,
        )
        self.assertEqual(result["freshness_status"], "FRESH")
        self.assertTrue(result["executable_freshness"])
        self.assertTrue(result["future_timestamp_tolerated"])

    def test_future_timestamp_beyond_provider_jitter_still_fails_closed(self):
        now = datetime(2025, 12, 18, 20, 0, 0, tzinfo=timezone.utc)
        quote = {
            "asset_type": "stock",
            "provider_used": "alpaca",
            "provider_native_timestamp": "2025-12-18T20:00:00.251Z",
        }
        result = canonical_market_timestamp_v1(
            quote,
            now=now,
            source_type="QUOTE",
            future_tolerance_seconds=provider_future_timestamp_tolerance_seconds_v1(quote, source_type="QUOTE"),
        )
        self.assertEqual(result["freshness_status"], "INVALID")
        self.assertFalse(result["executable_freshness"])

    def test_crypto_keeps_zero_future_tolerance(self):
        quote = {"asset_type": "crypto", "provider_used": "alpaca"}
        self.assertEqual(provider_future_timestamp_tolerance_seconds_v1(quote, source_type="QUOTE"), 0.0)

    def test_timezone_and_precision_normalize_without_future_false_positive(self):
        now = datetime(2025, 12, 18, 20, 0, 1, tzinfo=timezone.utc)
        result = canonical_market_timestamp_v1(
            {"provider_native_timestamp": "2025-12-18T15:00:00.123456-05:00"},
            now=now,
            source_type="QUOTE",
        )
        self.assertEqual(result["freshness_status"], "FRESH")
        normalized = datetime.fromisoformat(result["canonical_timestamp"].replace("Z", "+00:00")).astimezone(timezone.utc)
        self.assertEqual(normalized.isoformat().replace("+00:00", "Z"), "2025-12-18T20:00:00.123456Z")
        self.assertAlmostEqual(result["age_seconds"], 0.876544, places=5)


if __name__ == "__main__":
    unittest.main()
