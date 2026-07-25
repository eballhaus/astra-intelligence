"""Tests for shadow profit-giveback analysis module."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_shadow_profit_giveback_v1 import evaluate_profit_giveback


NOW = datetime(2026, 7, 24, 16, 0, 0, tzinfo=timezone.utc)


def _evaluation(
    signal_price: float = 100.0,
    quantity: float = 10.0,
    mfe_return: float = 0.10,
    actual_exit_price: float | None = None,
    levels: list[float] | None = None,
    **extra,
) -> dict[str, Any]:
    return {
        "shadow_evaluation_id": "eval-giveback",
        "position_identity": "shadow-pos:broker_position_id:abc123",
        "symbol": "CCC",
        "asset_class": "equity",
        "shadow_strategy": "PROTECT_PROFIT",
        "shadow_reference_price": signal_price,
        "hold_price_at_signal": signal_price,
        "quantity_at_evaluation": quantity,
        "maximum_favorable_excursion_after_signal": mfe_return,
        "actual_exit_price": actual_exit_price,
        "strategy_parameters": {"giveback_levels": levels} if levels else {},
        **extra,
    }


def _observation(price: float, timestamp: datetime, status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "shadow_observation_id": f"obs-{timestamp.isoformat()}",
        "shadow_evaluation_id": "eval-giveback",
        "position_identity": "shadow-pos:broker_position_id:abc123",
        "observation_window": "1h",
        "actual_observation_timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "market_price": price,
        "observation_status": status,
    }


class ProfitGivebackTests(unittest.TestCase):
    def test_giveback_calculated_relative_to_peak(self):
        """Profit given back is relative to peak profit, not signal return."""
        evaluation = _evaluation(signal_price=100.0, quantity=10.0, mfe_return=0.10)
        # Peak 110, current 105 -> gave back 5 of 10 profit = 50%.
        observations = [_observation(105.0, NOW + timedelta(minutes=30))]
        result = evaluate_profit_giveback(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertAlmostEqual(result["profit_given_back_pct"], 0.50, places=6)
        self.assertAlmostEqual(result["profit_given_back_dollars"], 50.0, places=6)

    def test_exit_at_10pct_giveback(self):
        """A 10% giveback of peak profit triggers exit at threshold."""
        evaluation = _evaluation(signal_price=100.0, quantity=10.0, mfe_return=0.10)
        # Peak 110. 10% giveback threshold price = 100 + 0.9*10 = 109.
        observations = [
            _observation(109.0, NOW + timedelta(minutes=10)),  # triggers exactly at 10%
            _observation(108.0, NOW + timedelta(minutes=20)),
            _observation(100.0, NOW + timedelta(minutes=30)),  # final
        ]
        result = evaluate_profit_giveback(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(any(c["level"] == 0.10 and c["triggered"] for c in result["giveback_levels_evaluated"]))
        self.assertEqual(result["best_observed_policy"], "EXIT_AT_10PCT_GIVEBACK")
        # Exiting at 109 vs holding to 100 preserves 9 * 10 = 90.
        self.assertEqual(result["profit_preserved"], 90.0)
        self.assertEqual(result["drawdown_avoided"], 90.0)
        self.assertEqual(result["additional_upside_missed"], 0.0)

    def test_continue_hold_when_price_keeps_rising(self):
        """When price continues to rise, continue hold is best."""
        evaluation = _evaluation(signal_price=100.0, quantity=10.0, mfe_return=0.10)
        observations = [
            _observation(108.0, NOW + timedelta(minutes=10)),
            _observation(112.0, NOW + timedelta(minutes=20)),  # new peak
        ]
        result = evaluate_profit_giveback(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["best_observed_policy"], "CONTINUE_HOLD")
        self.assertEqual(result["profit_preserved"], 0.0)

    def test_no_positive_peak_returns_insufficient(self):
        evaluation = _evaluation(signal_price=100.0, quantity=10.0, mfe_return=0.0)
        observations = [_observation(99.0, NOW + timedelta(minutes=10))]
        result = evaluate_profit_giveback(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE")
        self.assertIn("NO_POSITIVE_PEAK_PROFIT", result["blockers"])

    def test_zero_peak_profit_is_blocked(self):
        evaluation = _evaluation(signal_price=100.0, quantity=10.0, mfe_return=0.0)
        result = evaluate_profit_giveback(evaluation, [], now=NOW + timedelta(hours=1))
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE")
        self.assertIn("NO_POSITIVE_PEAK_PROFIT", result["blockers"])

    def test_confirmation_improves_outcome(self):
        """Confirmation requiring two consecutive breaches avoids noise."""
        evaluation = _evaluation(signal_price=100.0, quantity=10.0, mfe_return=0.10)
        # 10% threshold price = 109. Single spike to 108.5 then recovery should not trigger;
        # two consecutive below 109 confirms.
        observations = [
            _observation(109.5, NOW + timedelta(minutes=5)),
            _observation(108.5, NOW + timedelta(minutes=10)),
            _observation(109.5, NOW + timedelta(minutes=15)),  # recovery, no confirmation
            _observation(107.0, NOW + timedelta(minutes=20)),
            _observation(106.0, NOW + timedelta(minutes=25)),  # confirmed
            _observation(100.0, NOW + timedelta(minutes=30)),
        ]
        result = evaluate_profit_giveback(evaluation, observations, now=NOW + timedelta(hours=1))
        self.assertTrue(result["best_observed_policy"].startswith("EXIT_AT_10PCT_GIVEBACK") or result["best_observed_policy"].startswith("EXIT_AFTER_CONFIRMATION"))
        self.assertGreaterEqual(result["profit_preserved"], 0.0)

    def test_partial_evidence_pending(self):
        evaluation = _evaluation(signal_price=100.0, quantity=10.0, mfe_return=0.10)
        result = evaluate_profit_giveback(evaluation, [], now=NOW + timedelta(minutes=5))
        self.assertEqual(result["status"], "PENDING_OBSERVATION")

    def test_safety_flags_always_present(self):
        evaluation = _evaluation(signal_price=100.0, quantity=10.0, mfe_return=0.10)
        result = evaluate_profit_giveback(evaluation, [], now=NOW)
        self.assertTrue(result["shadow_only"])
        self.assertEqual(result["execution_authority"], "DISABLED")
        self.assertEqual(result["promotion_status"], "NOT_PROMOTED")


if __name__ == "__main__":
    unittest.main()
