from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_trading_intelligence_improvement_v4 import build_trading_intelligence_improvement_suite_v4


class TradingIntelligenceImprovementV4Tests(unittest.TestCase):
    def _state(self, *, factors=True, excursions=True) -> Path:
        root = Path(tempfile.mkdtemp()); (root / "dashboard_cache").mkdir(); (root / "storage_summary_indexes").mkdir()
        rows = []
        for index in range(5):
            context = {"intended_horizon": "day_trade", "market_regime": "risk_on"}
            if factors: context["factor_contributions"] = {"momentum": 0.8}
            row = {"stable_key": f"strict-{index}", "truth_state": "STRICT_TRUTH", "symbol": "AAA", "lane_id": "DAY", "realized_return": 1.0,
                   "entry_price": 10, "exit_price": 11, "entry_time": "t0", "exit_time": "t1", "pretrade_context_v1": context}
            if excursions: row.update({"mfe": 2.0, "mae": -0.5})
            rows.append(row)
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": rows}))
        (root / "symbol_behavior_profiles_v1.json").write_text(json.dumps({"profiles": {}}))
        (root / "astra_unified_position_advisory_v1.json").write_text(json.dumps({"positions": []}))
        (root / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json").write_text(json.dumps({"completed_shadow_lifecycles": 10, "best_exit_style": "time_exit"}))
        (root / "dashboard_cache" / "shadow_vs_paper_performance_attribution_v1.json").write_text(json.dumps({}))
        for name in ("market_context_learning_suite_v1.jsonl.summary_index.json", "opportunity_cost_learning_v1.jsonl.summary_index.json", "trade_archetype_regime_intelligence_v1.jsonl.summary_index.json", "candidate_decision_ledger_v1.jsonl.summary_index.json"):
            (root / "storage_summary_indexes" / name).write_text(json.dumps({"dimension_counts": {}}))
        return root

    def test_persisted_pretrade_and_excursion_evidence_is_observational_only(self):
        result = build_trading_intelligence_improvement_suite_v4(str(self._state()))
        self.assertEqual(result["confidence_attribution"]["factors"][0]["association"], "POSITIVE_ASSOCIATION")
        self.assertEqual(result["entry_quality"]["status"], "OBSERVATIONAL")
        self.assertEqual(result["exit_effectiveness"]["actual_exit_status"], "OBSERVATIONAL")
        self.assertEqual(result["exit_effectiveness"]["counterfactual_exit_evidence_tier"], "SHADOW_COUNTERFACTUAL")
        self.assertFalse(result["automatic_reweighting_authority"])
        self.assertFalse(result["behavior_safe_to_apply"])

    def test_missing_original_evidence_is_not_reconstructed_and_drift_is_gated(self):
        result = build_trading_intelligence_improvement_suite_v4(str(self._state(factors=False, excursions=False)))
        self.assertEqual(result["confidence_attribution"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["entry_quality"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["exit_effectiveness"]["actual_exit_status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["learning_consistency_and_drift"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)
        self.assertEqual(result["llm_calls_used"], 0)
