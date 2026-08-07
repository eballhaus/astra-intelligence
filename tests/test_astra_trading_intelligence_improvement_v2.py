from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_trading_intelligence_improvement_v2 import (
    build_trading_intelligence_improvement_suite_v2,
)


def _strict(symbol: str, result: float, regime: str = "RISK_ON") -> dict:
    return {
        "stable_key": f"strict-{symbol}-{result}", "truth_state": "BROKER_TRUTH_CONFIRMED",
        "truth_quality": "BROKER_CONFIRMED_COMPLETE", "symbol": symbol, "asset_class": "equity",
        "lane_id": "DAY", "realized_return": result, "hold_duration": 3600,
        "pretrade_context_v1": {"intended_horizon": "day_trade", "market_regime": regime},
    }


class TradingIntelligenceImprovementV2Tests(unittest.TestCase):
    def _state(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "dashboard_cache").mkdir()
        (root / "storage_summary_indexes").mkdir()
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": [
            _strict("AAA", 3.0), _strict("AAA", -1.0),
            {"stable_key": "reconstructed", "truth_quality": "broker_confirmed_complete", "symbol": "LEAK", "realized_return": 99.0},
        ]}))
        (root / "symbol_behavior_profiles_v1.json").write_text(json.dumps({"profiles": {
            "AAA": {"sample_size": 40, "best_horizon": "day_trade", "best_exit_style": "time_exit"},
        }}))
        (root / "astra_unified_position_advisory_v1.json").write_text(json.dumps({"positions": [{
            "symbol": "AAA", "final_advisory": "WATCH", "opportunity_cost_state": "OPPORTUNITY_COST_RISING",
        }]}))
        (root / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json").write_text(json.dumps({
            "completed_shadow_lifecycles": 80, "shadow_profit_factor": 9.0,
            "evidence_quality_score": 80, "consensus_confidence_score": 80,
        }))
        (root / "dashboard_cache" / "shadow_vs_paper_performance_attribution_v1.json").write_text(json.dumps({"canonical_profit_factor": 1.2}))
        for name in ("market_context_learning_suite_v1.jsonl.summary_index.json", "opportunity_cost_learning_v1.jsonl.summary_index.json"):
            (root / "storage_summary_indexes" / name).write_text(json.dumps({"dimension_counts": {"regime": {"RISK_ON": 7}}}))
        return root

    def test_strict_and_shadow_evidence_are_never_mixed(self):
        result = build_trading_intelligence_improvement_suite_v2(str(self._state()))
        self.assertEqual(result["canonical_input"]["strict_truth_count"], 2)
        profile = result["symbol_intelligence"]["profiles"][0]
        self.assertEqual(profile["symbol"], "AAA")
        self.assertEqual(profile["strict_truth_sample_size"], 2)
        self.assertEqual(profile["shadow_sample_size_separate"], 80)
        self.assertEqual(profile["profile_status"], "EARLY_PROFILE")
        self.assertIsNone(profile["profit_factor"])
        self.assertFalse(profile["automatic_weighting_eligible"])
        self.assertFalse(result["shadow_validation_and_evidence_promotion"]["shadow_may_count_as_strict_truth"])
        self.assertTrue(result["shadow_validation_and_evidence_promotion"]["promotion_gate"]["passed"])

        shadow_path = self._state() / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json"
        shadow_path.write_text(json.dumps({"completed_shadow_lifecycles": 49, "shadow_profit_factor": 9.0, "evidence_quality_score": 80, "consensus_confidence_score": 80}))
        gated = build_trading_intelligence_improvement_suite_v2(str(shadow_path.parent.parent))
        self.assertEqual(gated["shadow_validation_and_evidence_promotion"]["promotion_status"], "COLLECT_MORE_SHADOW_EVIDENCE")

    def test_regime_opportunity_and_retrieval_are_observational(self):
        result = build_trading_intelligence_improvement_suite_v2(str(self._state()), {"symbol": "AAA", "regime": "RISK_ON"})
        self.assertEqual(result["market_regime_intelligence"]["profiles"][0]["regime"], "RISK_ON")
        opportunity = result["opportunity_cost_intelligence"]
        self.assertEqual(opportunity["positions"][0]["state"], "OPPORTUNITY_COST_RISING")
        self.assertFalse(opportunity["automatic_replacement_authority"])
        retrieval = result["knowledge_retrieval"]
        self.assertGreaterEqual(retrieval["result_count"], 2)
        self.assertFalse(retrieval["full_history_scan_used"])
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)
        self.assertFalse(result["behavior_safe_to_apply"])
