"""Contract tests for shadow-only performance aggregation."""
from __future__ import annotations

import json
import unittest

from engine.astra_shadow_exit_performance_v1 import aggregate_shadow_exit_performance


def _outcome(identifier, saved, *, lane="DAY", horizon="intraday", legacy="ASTRA_MANAGED", status="COMPLETED"):
    return {"shadow_evaluation_id": identifier, "position_identity": f"pos:{identifier}", "shadow_strategy": "EXIT_AFTER_CONFIRMATION",
            "exit_signal_type": "EXIT_REVIEW", "lane": lane, "horizon": horizon, "legacy_status": legacy, "status": status,
            "modules": {"confirmation": {"status": "COMPLETED", "net_capital_saved": saved},
                        "regret": {"status": "COMPLETED", "net_regret": -saved, "late_exit_regret": max(0, -saved), "early_exit_regret": max(0, saved)}}}


class ShadowPerformanceTests(unittest.TestCase):
    def test_insufficient_sample_does_not_publish_pf(self):
        result = aggregate_shadow_exit_performance([_outcome("a", 1.0)])
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE")
        self.assertIsNone(result["metrics"]["shadow_profit_factor"])
        self.assertEqual(result["metrics"]["shadow_profit_factor_status"], "INSUFFICIENT_SAMPLE")

    def test_profit_factor_and_win_rate_use_completed_comparable_rows_only(self):
        result = aggregate_shadow_exit_performance([_outcome("a", 5), _outcome("b", -2), _outcome("c", 1), _outcome("pending", 99, status="PENDING_OBSERVATION")])
        metrics = result["metrics"]
        self.assertEqual(metrics["sample_size"], 3)
        self.assertEqual(metrics["shadow_profit_factor"], 3.0)
        self.assertAlmostEqual(metrics["shadow_win_rate"], 2 / 3)
        self.assertEqual(metrics["evaluation_count"], 4)

    def test_completed_module_for_open_position_is_not_final_performance(self):
        open_outcome = _outcome("open", 8)
        open_outcome["evaluation_status"] = "PARTIALLY_OBSERVED"
        result = aggregate_shadow_exit_performance([_outcome("a", 1), _outcome("b", 1), open_outcome])
        self.assertEqual(result["metrics"]["sample_size"], 2)
        self.assertEqual(result["status"], "INSUFFICIENT_SAMPLE")

    def test_zero_gross_loss_is_truthful_not_infinite(self):
        result = aggregate_shadow_exit_performance([_outcome("a", 1), _outcome("b", 2), _outcome("c", 3)])
        self.assertIsNone(result["metrics"]["shadow_profit_factor"])
        self.assertEqual(result["metrics"]["shadow_profit_factor_status"], "ZERO_GROSS_LOSS")
        json.dumps(result, allow_nan=False)

    def test_legacy_rows_are_isolated_from_day_and_horizon_groups(self):
        result = aggregate_shadow_exit_performance([_outcome("a", 1), _outcome("b", 1), _outcome("c", 1), _outcome("legacy", -1, lane="DAY", horizon="swing", legacy="LEGACY")])
        lane_keys = {row["key"] for row in result["by_group"]["lane"]}
        horizon_keys = {row["key"] for row in result["by_group"]["horizon"]}
        self.assertIn("UNAVAILABLE", lane_keys)
        self.assertNotIn("LEGACY", lane_keys)
        self.assertIn("UNAVAILABLE", horizon_keys)

    def test_ordering_is_deterministic_and_safety_is_fixed(self):
        first = aggregate_shadow_exit_performance([_outcome("b", -1, lane="SWING"), _outcome("a", 2)])
        second = aggregate_shadow_exit_performance([_outcome("a", 2), _outcome("b", -1, lane="SWING")])
        self.assertEqual(first["by_group"], second["by_group"])
        self.assertTrue(first["shadow_only"])
        self.assertEqual(first["execution_authority"], "DISABLED")
        self.assertEqual(first["promotion_status"], "NOT_PROMOTED")


if __name__ == "__main__":
    unittest.main()
