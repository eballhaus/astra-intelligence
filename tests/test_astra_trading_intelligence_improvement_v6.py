from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_trading_intelligence_improvement_v6 import build_trading_intelligence_improvement_suite_v6


class TradingIntelligenceImprovementV6Tests(unittest.TestCase):
    def _root(self, records, shadow=None):
        root = Path(tempfile.mkdtemp()); (root / "dashboard_cache").mkdir(); (root / "storage_summary_indexes").mkdir()
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": records}))
        (root / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json").write_text(json.dumps(shadow or {}))
        (root / "dashboard_cache" / "shadow_vs_paper_performance_attribution_v1.json").write_text(json.dumps({}))
        for name in ("symbol_behavior_profiles_v1.json", "astra_unified_position_advisory_v1.json"):
            (root / name).write_text(json.dumps({}))
        for name in ("market_context_learning_suite_v1.jsonl.summary_index.json", "opportunity_cost_learning_v1.jsonl.summary_index.json", "trade_archetype_regime_intelligence_v1.jsonl.summary_index.json", "candidate_decision_ledger_v1.jsonl.summary_index.json"):
            (root / "storage_summary_indexes" / name).write_text(json.dumps({"dimension_counts": {}}))
        return root

    def test_similarity_is_bounded_and_shadow_cannot_promote(self):
        records = [{"stable_key": str(i), "truth_state": "STRICT_TRUTH", "symbol": "ABC", "lane_id": "DAY", "realized_return": 1, "pretrade_context_v1": {"candidate_id": str(i), "market_regime": "BULL"}} for i in range(5)]
        result = build_trading_intelligence_improvement_suite_v6(str(self._root(records, {"completed_shadow_lifecycles": 100})), {"symbol": "ABC", "lane": "DAY", "regime": "BULL"})
        similarity = result["trade_pattern_similarity"]
        self.assertEqual(similarity["status"], "HIGH_SIMILARITY")
        self.assertEqual(len(similarity["strict_truth_matches"]), 5)
        self.assertEqual(similarity["shadow_matches"], [])
        self.assertEqual(result["learning_promotion_readiness"]["status"], "COLLECT_MORE_EVIDENCE")
        self.assertFalse(result["learning_promotion_readiness"]["human_review_eligible"])

    def test_missing_prediction_stays_unavailable_and_realization_is_deterministic(self):
        legacy = {"stable_key": "legacy", "truth_state": "STRICT_TRUTH", "symbol": "SG", "realized_return": 2}
        rich = {"stable_key": "rich", "truth_state": "STRICT_TRUTH", "symbol": "ABC", "realized_return": -3, "mfe": 1, "mae": -4, "hold_duration": 400, "time_to_peak": 50, "profit_giveback": 2, "pretrade_context_v1": {"predicted_direction": "UP", "expected_return_pct": 4, "expected_downside": 2, "confidence": 90, "expected_hold_seconds": 100}}
        result = build_trading_intelligence_improvement_suite_v6(str(self._root([legacy, rich])))
        errors = result["prediction_error_decomposition"]["errors"]
        self.assertEqual(errors[0]["status"], "UNAVAILABLE")
        self.assertIn("DIRECTION_ERROR", errors[1]["errors"])
        self.assertEqual(result["risk_reward_realization"]["observations"][1]["status"], "DOWNSIDE_UNDERESTIMATED")
        self.assertEqual(result["hold_duration_optimization"]["observations"][1]["status"], "HELD_TOO_LONG")
        self.assertFalse(result["execution_behavior_changed"])
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_calls_used"], 0)
        self.assertEqual(result["llm_calls_used"], 0)
