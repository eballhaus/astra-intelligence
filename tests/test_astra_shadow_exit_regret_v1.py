"""Tests for shadow exit regret analysis module."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_shadow_exit_regret_v1 import calculate_exit_regret


NOW = datetime(2026, 7, 24, 16, 0, 0, tzinfo=timezone.utc)


def _evaluation(
    strategy: str = "CONTINUE_HOLD",
    signal_price: float = 100.0,
    quantity: float = 10.0,
    actual_exit_price: float | None = None,
    **extra,
) -> dict[str, Any]:
    return {
        "shadow_evaluation_id": "eval-1",
        "position_identity": "shadow-pos:broker_position_id:abc123",
        "symbol": "AAA",
        "asset_class": "equity",
        "shadow_strategy": strategy,
        "shadow_reference_price": signal_price,
        "shadow_reference_timestamp": NOW.isoformat().replace("+00:00", "Z"),
        "hold_price_at_signal": signal_price,
        "quantity_at_evaluation": quantity,
        "actual_exit_price": actual_exit_price,
        **extra,
    }


def _observation(
    price: float,
    timestamp: datetime = NOW,
    window: str = "1h",
    status: str = "COMPLETED",
    **extra,
) -> dict[str, Any]:
    return {
        "shadow_observation_id": f"obs-{timestamp.isoformat()}",
        "shadow_evaluation_id": "eval-1",
        "position_identity": "shadow-pos:broker_position_id:abc123",
        "observation_window": window,
        "actual_observation_timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "market_price": price,
        "observation_status": status,
        **extra,
    }


class ExitRegretTests(unittest.TestCase):
    def test_late_exit_regret_for_hold_strategy(self):
        """Holding through a drop produces late-exit regret."""
        evaluation = _evaluation("CONTINUE_HOLD", signal_price=100.0, quantity=10.0)
        observations = [
            _observation(98.0, NOW + timedelta(minutes=30)),
            _observation(95.0, NOW + timedelta(hours=1)),
        ]
        result = calculate_exit_regret(evaluation, observations, now=NOW + timedelta(hours=2))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["late_exit_regret"], 50.0)
        self.assertEqual(result["net_exit_regret"], 50.0)
        self.assertEqual(result["capital_missed"], 50.0)
        self.assertEqual(result["additional_loss_pct"], 0.05)
        self.assertIsNone(result["early_exit_regret"])
        self.assertEqual(result["sample_size"], 2)

    def test_early_exit_regret_for_exit_now_strategy(self):
        """Exiting early when the price rises produces early-exit regret."""
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=10.0)
        observations = [
            _observation(102.0, NOW + timedelta(minutes=30)),
            _observation(105.0, NOW + timedelta(hours=1)),
        ]
        result = calculate_exit_regret(evaluation, observations, now=NOW + timedelta(hours=2))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["early_exit_regret"], 50.0)
        self.assertEqual(result["net_exit_regret"], 50.0)
        self.assertEqual(result["capital_missed"], 50.0)
        self.assertEqual(result["profit_missed_pct"], 0.05)
        self.assertIsNone(result["late_exit_regret"])

    def test_exit_now_avoids_loss_and_is_beneficial(self):
        """Exiting before a drop is beneficial, producing negative net regret."""
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=10.0)
        observations = [
            _observation(98.0, NOW + timedelta(minutes=30)),
            _observation(95.0, NOW + timedelta(hours=1)),
        ]
        result = calculate_exit_regret(evaluation, observations, now=NOW + timedelta(hours=2))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["capital_preserved"], 50.0)
        self.assertEqual(result["additional_loss_pct"], 0.05)
        self.assertEqual(result["net_exit_regret"], -50.0)
        self.assertIsNone(result["early_exit_regret"])
        self.assertIsNone(result["capital_missed"])

    def test_completed_with_actual_exit_price(self):
        """An actual realized exit price produces COMPLETED status."""
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=10.0, actual_exit_price=94.0)
        observations = [_observation(95.0, NOW + timedelta(hours=1))]
        result = calculate_exit_regret(evaluation, observations, now=NOW + timedelta(hours=2))
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["outcome_price"], 94.0)
        self.assertEqual(result["capital_preserved"], 60.0)
        self.assertEqual(result["net_exit_regret"], -60.0)

    def test_no_observations_and_no_actual_exit_is_pending(self):
        """Missing both observations and closure means pending."""
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=10.0)
        result = calculate_exit_regret(evaluation, [], now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "PENDING_OBSERVATION")
        self.assertEqual(result["sample_size"], 0)
        self.assertIn("NO_COMPLETED_OBSERVATIONS", result["blockers"])

    def test_future_observation_is_excluded(self):
        """Observations with timestamps beyond `now` are not leaked."""
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=10.0)
        observations = [
            _observation(95.0, NOW + timedelta(minutes=30)),
            _observation(200.0, NOW + timedelta(days=1)),  # Future extreme price
        ]
        result = calculate_exit_regret(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["outcome_price"], 95.0)
        self.assertEqual(result["net_exit_regret"], -50.0)

    def test_mismatched_or_pre_signal_observations_are_rejected(self):
        evaluation = _evaluation("EXIT_NOW")
        observations = [
            _observation(20.0, NOW - timedelta(minutes=1)),
            _observation(20.0, NOW + timedelta(minutes=30), position_identity="other-position"),
        ]
        result = calculate_exit_regret(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "PENDING_OBSERVATION")
        self.assertIn("IDENTITY_MISMATCH_REJECTED", result["blockers"])

    def test_invalid_signal_price_returns_invalid_input(self):
        evaluation = _evaluation("EXIT_NOW", signal_price=0.0, quantity=10.0)
        result = calculate_exit_regret(evaluation, [], now=NOW)
        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertIn("MISSING_REFERENCE_PRICE", result["blockers"])

    def test_invalid_quantity_returns_invalid_input(self):
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=0.0)
        result = calculate_exit_regret(evaluation, [_observation(95.0)], now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertIn("MISSING_OR_INVALID_QUANTITY", result["blockers"])

    def test_missing_identity_returns_invalid_input(self):
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=10.0)
        del evaluation["position_identity"]
        result = calculate_exit_regret(evaluation, [], now=NOW)
        self.assertEqual(result["status"], "INVALID_INPUT")
        self.assertIn("MISSING_EVALUATION_IDENTITY", result["blockers"])

    def test_tiny_fractional_quantity(self):
        """Micro-fractional quantities are preserved without dropping."""
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=0.000000321)
        observations = [_observation(95.0, NOW + timedelta(minutes=30))]
        result = calculate_exit_regret(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "PARTIAL")
        expected = (100.0 - 95.0) * 0.000000321
        self.assertAlmostEqual(result["capital_preserved"], expected, places=12)
        self.assertEqual(result["execution_authority"], "DISABLED")
        self.assertEqual(result["promotion_status"], "NOT_PROMOTED")

    def test_safety_flags_always_present(self):
        evaluation = _evaluation("EXIT_NOW", signal_price=100.0, quantity=10.0)
        result = calculate_exit_regret(evaluation, [], now=NOW)
        self.assertTrue(result["shadow_only"])
        self.assertEqual(result["execution_authority"], "DISABLED")
        self.assertEqual(result["promotion_status"], "NOT_PROMOTED")


if __name__ == "__main__":
    unittest.main()
