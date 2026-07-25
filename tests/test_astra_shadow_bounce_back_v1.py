"""Tests for shadow bounce-back analysis module."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_shadow_bounce_back_v1 import evaluate_bounce_back


NOW = datetime(2026, 7, 24, 16, 0, 0, tzinfo=timezone.utc)


def _evaluation(
    signal_price: float = 100.0,
    quantity: float = 10.0,
    windows: list[str] | None = None,
    rebound_pct: float = 0.02,
    max_drawdown_pct: float = 0.05,
    **extra,
) -> dict[str, Any]:
    return {
        "shadow_evaluation_id": "eval-bounce",
        "position_identity": "shadow-pos:broker_position_id:abc123",
        "symbol": "BBB",
        "asset_class": "equity",
        "shadow_strategy": "PROTECT_ON_BOUNCE",
        "shadow_reference_price": signal_price,
        "shadow_reference_timestamp": NOW.isoformat().replace("+00:00", "Z"),
        "hold_price_at_signal": signal_price,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "quantity_at_evaluation": quantity,
        "required_observation_windows": windows or ["1h"],
        "strategy_parameters": {
            "rebound_threshold_pct": rebound_pct,
            "max_additional_drawdown_pct": max_drawdown_pct,
        },
        **extra,
    }

def _observation(
    price: float,
    timestamp: datetime,
    window: str = "1h",
    status: str = "COMPLETED",
) -> dict[str, Any]:
    return {
        "shadow_observation_id": f"obs-{timestamp.isoformat()}",
        "shadow_evaluation_id": "eval-bounce",
        "position_identity": "shadow-pos:broker_position_id:abc123",
        "observation_window": window,
        "actual_observation_timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "market_price": price,
        "observation_status": status,
    }


class BounceBackTests(unittest.TestCase):
    def test_qualifying_rebound_makes_bounce_wait_better(self):
        """A 2% trough followed by a 2%+ rebound favors bounce wait."""
        evaluation = _evaluation(signal_price=100.0, rebound_pct=0.02, max_drawdown_pct=0.10)
        observations = [
            _observation(99.0, NOW + timedelta(minutes=15)),
            _observation(98.0, NOW + timedelta(minutes=30)),  # trough
            _observation(100.5, NOW + timedelta(minutes=45)),  # rebound peak
            _observation(99.0, NOW + timedelta(minutes=50)),   # lower final
        ]
        result = evaluate_bounce_back(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(result["rebound_occurred"])
        self.assertEqual(result["bounce_state"], "BOUNCE_WAIT_BETTER")
        self.assertAlmostEqual(result["rebound_percentage"], 100.5 / 98.0 - 1.0, places=6)
        self.assertGreater(result["capital_recovered"], 0)

    def test_no_rebound_makes_continue_hold_or_immediate_better(self):
        """A steady decline means bounce wait is not triggered."""
        evaluation = _evaluation(signal_price=100.0, rebound_pct=0.02, max_drawdown_pct=0.10)
        observations = [
            _observation(99.0, NOW + timedelta(minutes=20)),
            _observation(98.0, NOW + timedelta(minutes=40)),
            _observation(97.0, NOW + timedelta(minutes=55)),
        ]
        result = evaluate_bounce_back(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertFalse(result["rebound_occurred"])
        self.assertEqual(result["bounce_state"], "IMMEDIATE_EXIT_BETTER")
        self.assertEqual(result["continue_hold_result"], result["bounce_wait_result"])
        self.assertGreater(result["capital_lost_by_waiting"], 0)

    def test_rebound_after_excessive_drawdown_is_invalid(self):
        """A rebound after dropping beyond the max tolerated drawdown is rejected."""
        evaluation = _evaluation(signal_price=100.0, rebound_pct=0.02, max_drawdown_pct=0.03)
        observations = [
            _observation(97.0, NOW + timedelta(minutes=10)),  # exceeds 5% drawdown
            _observation(96.0, NOW + timedelta(minutes=20)),
            _observation(99.0, NOW + timedelta(minutes=30)),
        ]
        result = evaluate_bounce_back(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertFalse(result["rebound_occurred"])
        self.assertEqual(result["bounce_state"], "IMMEDIATE_EXIT_BETTER")

    def test_rebound_outside_window_is_ignored(self):
        """A rebound after the bounded wait window is not counted."""
        evaluation = _evaluation(signal_price=100.0, rebound_pct=0.02, max_drawdown_pct=0.10)
        observations = [
            _observation(98.0, NOW + timedelta(minutes=30)),
            _observation(100.5, NOW + timedelta(hours=2)),  # beyond 1h window
        ]
        result = evaluate_bounce_back(evaluation, observations, now=NOW + timedelta(hours=3))
        self.assertFalse(result["rebound_occurred"])
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["bounce_state"], "IMMEDIATE_EXIT_BETTER")

    def test_continued_rise_makes_hold_better(self):
        """If the price rises steadily, continue hold wins."""
        evaluation = _evaluation(signal_price=100.0, rebound_pct=0.02, max_drawdown_pct=0.10)
        observations = [
            _observation(101.0, NOW + timedelta(minutes=10)),
            _observation(102.0, NOW + timedelta(minutes=20)),
            _observation(103.0, NOW + timedelta(minutes=30)),
        ]
        result = evaluate_bounce_back(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["bounce_state"], "HOLD_BETTER")
        self.assertEqual(result["rebound_occurred"], False)

    def test_inconclusive_on_tie(self):
        """When all paths have the same return, report inconclusive."""
        evaluation = _evaluation(signal_price=100.0, rebound_pct=0.02, max_drawdown_pct=0.10)
        observations = [
            _observation(100.0, NOW + timedelta(minutes=30)),
        ]
        result = evaluate_bounce_back(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["bounce_state"], "INCONCLUSIVE")

    def test_legacy_position_is_unavailable(self):
        evaluation = _evaluation(legacy_status="LEGACY")
        result = evaluate_bounce_back(evaluation, [], now=NOW)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["bounce_state"], "LEGACY_POSITION")

    def test_no_observations_is_pending(self):
        evaluation = _evaluation()
        result = evaluate_bounce_back(evaluation, [], now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "PENDING_OBSERVATION")
        self.assertIn("NO_COMPLETED_OBSERVATIONS_IN_WINDOW", result["blockers"])

    def test_invalid_price_is_insufficient(self):
        evaluation = _evaluation()
        observations = [_observation(0.0, NOW + timedelta(minutes=30))]
        result = evaluate_bounce_back(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE")
        self.assertIn("INVALID_OBSERVATION_PRICE", result["blockers"])

    def test_safety_flags_always_present(self):
        evaluation = _evaluation()
        result = evaluate_bounce_back(evaluation, [], now=NOW)
        self.assertTrue(result["shadow_only"])
        self.assertEqual(result["execution_authority"], "DISABLED")
        self.assertEqual(result["promotion_status"], "NOT_PROMOTED")

    def test_identity_mismatch_is_not_usable_evidence(self):
        evaluation = _evaluation()
        observation = _observation(80.0, NOW + timedelta(minutes=30))
        observation["shadow_evaluation_id"] = "different-evaluation"
        result = evaluate_bounce_back(evaluation, [observation], now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "PENDING_OBSERVATION")
        self.assertIn("IDENTITY_MISMATCH_REJECTED", result["blockers"])

    def test_missing_signal_timestamp_fails_closed(self):
        evaluation = _evaluation()
        evaluation.pop("shadow_reference_timestamp")
        evaluation.pop("generated_at")
        result = evaluate_bounce_back(evaluation, [], now=NOW)
        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertIn("MISSING_SIGNAL_TIMESTAMP", result["blockers"])


if __name__ == "__main__":
    unittest.main()
