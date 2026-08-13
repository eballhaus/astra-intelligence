from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_trade_learning_evidence_lane_monitor_v1 import (
    build_trade_learning_evidence_lane_monitor_v1,
)
from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1


def strict_truth(lifecycle_id: str = "life-1", lane: str = "DAY", **extra):
    row = {
        "stable_key": f"truth:{lifecycle_id}", "truth_id": f"truth:{lifecycle_id}", "truth_state": "STRICT_TRUTH",
        "strict_broker_truth": True, "lifecycle_id": lifecycle_id, "candidate_id": f"candidate:{lifecycle_id}",
        "symbol": "ABC", "lane_id": lane, "horizon": "DAY", "entry_fill_id": "entry-1", "exit_fill_id": "exit-1",
        "realized_return_pct": 1.5, "hold_duration": 5400, "mfe": 5.0, "mae": -3.0, "profit_giveback": 1.0,
        "exit_reason": "NORMAL_EXIT", "evidence_class": "BROKER_CONFIRMED_COMPLETE", "learning_acknowledged": True,
        "pretrade_context_v1": {
            "candidate_id": f"candidate:{lifecycle_id}", "contract_id": "contract-1", "thesis": "breakout continuation",
            "predicted_direction": "UP", "expected_return_pct": 4.0, "expected_downside": 2.0,
            "expected_hold_seconds": 3600, "confidence": 82, "lane": lane, "intended_horizon": "DAY",
            "market_regime": "RISK_ON", "strategy_archetype": "BREAKOUT", "catalyst": "EARNINGS",
            "ranking_factors": {"momentum": 0.8}, "risk_envelope": {"max_loss": 2.0},
        },
    }
    row.update(extra)
    return row


class TradeLearningEvidenceLaneMonitorV1Tests(unittest.TestCase):
    def _root(self, truths: list[dict]) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": truths}), encoding="utf-8")
        ledger = LaneExecutionTraceLedgerV1(str(root))
        summary = ledger._empty_summary()
        summary["lanes"]["DAY"].update({"candidates_seen": 5, "fresh_candidates": 5, "eligible": 2, "selected": 1, "order_ready": 1, "submitted": 1, "filled_entries": 1, "filled_exits": 1, "strict_broker_truths": 1})
        summary["daily_buckets"] = {"2026-08-12": {"lanes": {lane: ledger._empty_lane() for lane in ("DAY", "SCALP", "SWING", "CRYPTO")}, "cohorts": {}}}
        summary["daily_buckets"]["2026-08-12"]["lanes"]["DAY"].update({"filled_entries": 1, "strict_broker_truths": 1})
        ledger._write_summary(summary)
        return root

    def test_complete_evidence_reuses_strict_truth_without_mutating_it(self):
        truth = strict_truth()
        root = self._root([truth])
        result = build_trade_learning_evidence_lane_monitor_v1(str(root))
        evidence = result["complete_trade_evidence"]["records"][0]
        self.assertEqual(evidence["lifecycle_id"], "life-1")
        self.assertEqual(evidence["entry"]["entry_thesis"], "breakout continuation")
        self.assertEqual(evidence["exit"]["realized_return_pct"], 1.5)
        self.assertEqual(truth["pretrade_context_v1"]["expected_return_pct"], 4.0)
        self.assertTrue(result["complete_trade_evidence"]["immutable_source_records"])
        self.assertEqual(result["proving_phase_coverage"]["records_checked"], 1)
        self.assertEqual(result["proving_phase_coverage"]["normal_consumer"], "compressed/indexed canonical lessons; raw evidence remains drill-down only")

    def test_missing_evidence_remains_unavailable_not_fabricated(self):
        truth = strict_truth(pretrade_context_v1={"candidate_id": "candidate:life-1"}, mfe=None, mae=None)
        root = self._root([truth])
        evidence = build_trade_learning_evidence_lane_monitor_v1(str(root))["complete_trade_evidence"]["records"][0]
        self.assertEqual(evidence["entry"]["entry_thesis"], "UNAVAILABLE")
        self.assertEqual(evidence["prediction_vs_reality"]["return_error_pct"], "UNAVAILABLE")
        self.assertEqual(evidence["hold"]["mfe"], "UNAVAILABLE")

    def test_prediction_calibration_uses_original_values(self):
        root = self._root([strict_truth()])
        calibration = build_trade_learning_evidence_lane_monitor_v1(str(root))["prediction_vs_reality"]["records"][0]["calibration"]
        self.assertEqual(calibration["return_error_pct"], -2.5)
        self.assertEqual(calibration["hold_error_seconds"], 1800.0)
        self.assertEqual(calibration["downside_error_pct"], 1.0)

    def test_all_lanes_are_monitored_and_monitor_cannot_force_trades(self):
        root = self._root([strict_truth()])
        lanes = build_trade_learning_evidence_lane_monitor_v1(str(root))["lane_evidence_participation_monitor"]["lanes"]
        self.assertEqual(set(lanes), {"DAY", "SCALP", "SWING", "CRYPTO"})
        self.assertEqual(lanes["DAY"]["participation_state"], "EXECUTION_READY")
        self.assertTrue(all(not row["can_force_trade"] and not row["can_change_thresholds"] for row in lanes.values()))

    def test_current_operating_health_blocker_outranks_historical_ledger_blocker(self):
        root = self._root([strict_truth()])
        (root / "astra_operating_health_contract_v1.json").write_text(json.dumps({
            "lanes": {"DAY": {"first_causal_blocker": "CURRENT_RISK_BLOCK", "blocker_validity": "VALID_SAFETY_WAIT"}},
        }))
        lane = build_trade_learning_evidence_lane_monitor_v1(str(root))["lane_evidence_participation_monitor"]["lanes"]["DAY"]
        self.assertEqual(lane["first_or_current_blocker"], "CURRENT_RISK_BLOCK")
        self.assertEqual(lane["participation_state"], "SAFETY_BLOCKED")
        self.assertEqual(lane["historical_top_blocker"], "UNAVAILABLE")

    def test_similar_trade_comparison_is_bounded_and_cannot_promote(self):
        truths = [strict_truth(f"life-{index}") for index in range(30)]
        root = self._root(truths)
        result = build_trade_learning_evidence_lane_monitor_v1(str(root))
        comparison = result["similar_trade_learning"]["comparisons"][0]["similar_trade_comparison"]
        self.assertLessEqual(comparison["comparable_historical_outcomes"], 24)
        self.assertEqual(result["similar_trade_learning"]["maximum_comparisons"], 24)
        self.assertFalse(result["automatic_promotion_authority"])
        self.assertEqual(result["full_history_scan_count"], 0)

    def test_similar_trade_never_compares_a_truth_to_itself(self):
        root = self._root([strict_truth()])
        comparison = build_trade_learning_evidence_lane_monitor_v1(str(root))["similar_trade_learning"]["comparisons"][0]["similar_trade_comparison"]
        self.assertEqual(comparison["comparable_historical_outcomes"], 0)

    def test_paper_safety_and_existing_day_truth_remain_valid(self):
        root = self._root([strict_truth()])
        result = build_trade_learning_evidence_lane_monitor_v1(str(root))
        self.assertEqual(result["strict_truth_count"], 1)
        self.assertEqual(result["provider_calls_added"], 0)
        self.assertEqual(result["broker_calls_added"], 0)
        self.assertEqual(result["broker_actions_added"], 0)
        self.assertFalse(result["execution_behavior_changed"])
        self.assertFalse(result["frozen_lifecycle_modified"])


if __name__ == "__main__":
    unittest.main()
