"""Tests for off-hours completed-bar downside production."""
from __future__ import annotations

import unittest

from engine.astra_off_hours_completed_bar_v1 import (
    attach_completed_bar_downside_to_status,
    compute_completed_bar_downside_v1,
)


class CompletedBarDownsideTests(unittest.TestCase):
    def test_downside_from_close_and_low(self):
        bar = {"close": 100.0, "low": 98.0, "high": 101.0}
        result = compute_completed_bar_downside_v1(bar)
        self.assertEqual(result["downside_pct"], -2.0)
        self.assertEqual(result["downside_basis"], 100.0)
        self.assertEqual(result["source"], "close")

    def test_downside_from_previous_close(self):
        bar = {"previous_close": 100.0, "low": 97.0, "high": 101.0, "close": 99.0}
        result = compute_completed_bar_downside_v1(bar)
        self.assertEqual(result["downside_pct"], -3.0)
        self.assertEqual(result["downside_basis"], 100.0)
        self.assertEqual(result["source"], "previous_close")

    def test_true_range_downside(self):
        bar = {"previous_close": 100.0, "high": 103.0, "low": 98.0, "close": 99.0}
        result = compute_completed_bar_downside_v1(bar, use_true_range=True)
        # true_range = max(103-98, |103-100|, |98-100|) = 5
        self.assertEqual(result["downside_pct"], -5.0)

    def test_no_bar_returns_empty(self):
        result = compute_completed_bar_downside_v1(None)
        self.assertEqual(result["source"], "no_bar")
        self.assertIsNone(result["downside_pct"])

    def test_insufficient_price_returns_empty(self):
        result = compute_completed_bar_downside_v1({"low": 98.0})
        self.assertEqual(result["source"], "insufficient_price")
        self.assertIsNone(result["downside_pct"])

    def test_missing_low_returns_empty(self):
        result = compute_completed_bar_downside_v1({"close": 100.0})
        self.assertEqual(result["source"], "close")
        self.assertIsNone(result["downside_pct"])


class AttachDownsideToStatusTests(unittest.TestCase):
    def test_attaches_downside_flag(self):
        bar = {"close": 100.0, "low": 98.0, "high": 101.0}
        status = {"ok": False, "error": "session_order_submission_blocked"}
        result = attach_completed_bar_downside_to_status(status, bar)
        self.assertTrue(result["completed_bar_downside_included_before_early_return"])
        self.assertEqual(result["completed_bar_downside"]["downside_pct"], -2.0)
        self.assertEqual(result["error"], "session_order_submission_blocked")

    def test_attaches_empty_when_no_bar(self):
        status = {"ok": False, "error": "session_order_submission_blocked"}
        result = attach_completed_bar_downside_to_status(status, None)
        self.assertTrue(result["completed_bar_downside_included_before_early_return"])
        self.assertEqual(result["completed_bar_downside"]["source"], "no_bar")


if __name__ == "__main__":
    unittest.main()
