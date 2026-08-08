from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_trading_intelligence_improvement_v3 import build_trading_intelligence_improvement_suite_v3


def _truth(symbol: str, value: float, **context) -> dict:
    return {"stable_key": f"{symbol}-{value}", "truth_state": "STRICT_TRUTH", "symbol": symbol,
            "lane_id": "DAY", "realized_return": value, "hold_duration": 3600,
            "pretrade_context_v1": {"intended_horizon": "day_trade", "confidence": 80, **context}}


class TradingIntelligenceImprovementV3Tests(unittest.TestCase):
    def _state(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "dashboard_cache").mkdir(); (root / "storage_summary_indexes").mkdir()
        rows = [{**_truth("AAA", 1.0, market_regime="RISK_ON", archetype="momentum_breakout", catalyst="earnings"), "stable_key": f"AAA-{index}"} for index in range(5)]
        rows.append({"stable_key": "not-strict", "truth_quality": "broker_confirmed_complete", "symbol": "LEAK", "realized_return": 99})
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": rows}))
        (root / "symbol_behavior_profiles_v1.json").write_text(json.dumps({"profiles": {}}))
        (root / "astra_unified_position_advisory_v1.json").write_text(json.dumps({"positions": []}))
        (root / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json").write_text(json.dumps({
            "completed_shadow_lifecycles": 70,
            "candidate_lessons": [{"symbol": "SAFE", "subsequent_return": 12, "safety_blocker": True}, {"symbol": "MISS", "subsequent_return": 12}],
        }))
        (root / "dashboard_cache" / "shadow_vs_paper_performance_attribution_v1.json").write_text(json.dumps({}))
        for name, dims in {
            "market_context_learning_suite_v1.jsonl.summary_index.json": {},
            "opportunity_cost_learning_v1.jsonl.summary_index.json": {},
            "trade_archetype_regime_intelligence_v1.jsonl.summary_index.json": {"archetype": {"momentum_breakout": 12}},
            "candidate_decision_ledger_v1.jsonl.summary_index.json": {"symbol": {"safe": 1}, "regime": {"risk_on": 1}},
        }.items():
            (root / "storage_summary_indexes" / name).write_text(json.dumps({"dimension_counts": dims}))
        return root

    def test_cross_lane_context_is_strict_tier_and_non_authoritative(self):
        result = build_trading_intelligence_improvement_suite_v3(str(self._state()))
        self.assertEqual(result["strict_truth_sample_size"], 5)
        horizon = result["cross_lane_horizon_intelligence"]
        self.assertEqual(horizon["actual_strict_truth_comparisons"][0]["status"], "OBSERVATIONAL")
        self.assertFalse(horizon["automatic_horizon_authority"])
        self.assertEqual(result["trade_archetype_intelligence"]["profiles"][0]["status"], "OBSERVATIONAL")
        self.assertEqual(result["catalyst_intelligence"]["profiles"][0]["status"], "OBSERVATIONAL")
        self.assertFalse(result["behavior_safe_to_apply"])

    def test_calibration_and_rejections_are_gated_and_safety_preserving(self):
        result = build_trading_intelligence_improvement_suite_v3(str(self._state()))
        self.assertEqual(result["contextual_prediction_calibration"]["staged_aggregation"]["rich_context"][0]["status"], "OBSERVATIONAL")
        rejected = result["missed_opportunity_rejected_candidate_intelligence"]["classified_shadow_rejections"]
        self.assertEqual(rejected[0]["classification"], "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED")
        self.assertEqual(rejected[1]["classification"], "MISSED_OPPORTUNITY")
        self.assertFalse(result["v1_v2_continuity"]["knowledge_retrieval"]["full_history_scan_used"])
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)
        self.assertEqual(result["llm_calls_used"], 0)
