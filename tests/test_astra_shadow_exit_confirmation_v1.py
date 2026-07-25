"""Contract tests for bounded shadow confirmation-path analysis."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_shadow_exit_confirmation_v1 import evaluate_confirmation_path


NOW = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)


def _evaluation(**extra):
    row = {"shadow_evaluation_id": "eval-confirm", "position_identity": "pos:one", "symbol": "AAA", "asset_class": "equity",
           "shadow_strategy": "EXIT_AFTER_CONFIRMATION", "lane": "DAY", "horizon": "intraday", "legacy_status": "ASTRA_MANAGED",
           "shadow_reference_price": 100.0, "quantity_at_evaluation": 2.5, "shadow_reference_timestamp": NOW.isoformat(),
           "strategy_parameters": {"confirmation_window_minutes": 60, "confirmation_threshold_pct": 0.01}}
    row.update(extra)
    return row


def _observation(price, minutes, **extra):
    row = {"shadow_observation_id": f"obs-{minutes}-{price}", "shadow_evaluation_id": "eval-confirm", "position_identity": "pos:one",
           "observation_status": "COMPLETED", "actual_observation_timestamp": (NOW + timedelta(minutes=minutes)).isoformat(), "market_price": price}
    row.update(extra)
    return row


class ConfirmationPathTests(unittest.TestCase):
    def test_confirmation_exit_is_better_after_bounded_drop(self):
        result = evaluate_confirmation_path(_evaluation(), [_observation(98.5, 15), _observation(95, 30)], now=NOW + timedelta(hours=2))
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(result["confirmation_signal_met"])
        self.assertEqual(result["confirmation_state"], "MET")
        self.assertEqual(result["best_observed_path"], "IMMEDIATE_EXIT_BETTER")
        self.assertLess(result["confirmation_exit_result"], 0)

    def test_hold_is_better_without_confirmation(self):
        result = evaluate_confirmation_path(_evaluation(), [_observation(101, 15), _observation(105, 60)], now=NOW + timedelta(hours=2))
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(result["confirmation_signal_failed"])
        self.assertEqual(result["best_observed_path"], "CONTINUE_HOLD_BETTER")

    def test_exact_deadline_is_included_but_later_price_is_excluded(self):
        result = evaluate_confirmation_path(_evaluation(), [_observation(99, 60), _observation(500, 61)], now=NOW + timedelta(hours=2))
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["continue_hold_result"], -0.01)
        self.assertIn("OUT_OF_WINDOW_OBSERVATION_REJECTED", result["blockers"])

    def test_pending_before_deadline_is_not_a_confirmation_failure(self):
        result = evaluate_confirmation_path(_evaluation(), [], now=NOW + timedelta(minutes=10))
        self.assertEqual(result["status"], "PENDING_OBSERVATION")
        self.assertFalse(result["confirmation_signal_failed"])

    def test_identity_mismatch_is_rejected(self):
        result = evaluate_confirmation_path(_evaluation(), [_observation(90, 10, position_identity="pos:other")], now=NOW + timedelta(hours=2))
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE")
        self.assertIn("IDENTITY_MISMATCH_REJECTED", result["blockers"])

    def test_future_observation_is_rejected_even_inside_confirmation_window(self):
        result = evaluate_confirmation_path(
            _evaluation(strategy_parameters={"confirmation_window_minutes": 180, "confirmation_threshold_pct": 0.01}),
            [_observation(90, 120)], now=NOW + timedelta(minutes=30),
        )
        self.assertEqual(result["status"], "PENDING_OBSERVATION")
        self.assertIn("FUTURE_OBSERVATION_REJECTED", result["blockers"])

    def test_fractional_crypto_quantity_and_json_safety(self):
        evaluation = _evaluation(asset_class="crypto", quantity_at_evaluation=0.00000031)
        result = evaluate_confirmation_path(evaluation, [_observation(98, 10)], now=NOW + timedelta(hours=2))
        self.assertEqual(result["execution_authority"], "DISABLED")
        self.assertTrue(result["shadow_only"])
        json.dumps(result, allow_nan=False)

    def test_invalid_inputs_fail_closed(self):
        result = evaluate_confirmation_path(_evaluation(shadow_reference_price=0), [], now=NOW)
        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertIn("MISSING_REFERENCE_PRICE", result["blockers"])


if __name__ == "__main__":
    unittest.main()
