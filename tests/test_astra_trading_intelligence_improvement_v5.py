from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_truth_learning_enrichment_v1 import build_pretrade_truth_context_v1, merge_passive_excursion_evidence_v1
from engine.astra_trading_intelligence_improvement_v5 import build_trading_intelligence_improvement_suite_v5


class TradingIntelligenceImprovementV5Tests(unittest.TestCase):
    def test_context_is_immutable_copy_and_excursion_is_monotonic(self):
        source = {"candidate_id": "c1", "strategy_archetype": "momentum", "momentum_state": "strong", "factor_contributions": {"momentum": 0.8}}
        context = build_pretrade_truth_context_v1(source, {"contract_id": "k1"})
        source["momentum_state"] = "changed"
        source["factor_contributions"]["momentum"] = 0.1
        self.assertEqual(context["momentum_state"], "strong")
        self.assertEqual(context["factor_contributions"]["momentum"], 0.8)
        first = merge_passive_excursion_evidence_v1({}, current_return_pct=3, current_price=13, observed_at="t1", hold_seconds=10)
        second = merge_passive_excursion_evidence_v1(first, current_return_pct=-2, current_price=8, observed_at="t2", hold_seconds=20)
        self.assertEqual(second["max_favorable_excursion_pct"], 3)
        self.assertEqual(second["max_adverse_excursion_pct"], -2)
        self.assertEqual(second["peak_price"], 13)
        self.assertEqual(second["trough_price"], 8)
        self.assertEqual(second["time_to_peak"], 10)
        self.assertEqual(second["time_to_trough"], 20)
        self.assertEqual(second["excursion_observation_count"], 2)

    def test_historical_truth_is_not_reconstructed(self):
        root = Path(tempfile.mkdtemp()); (root / "dashboard_cache").mkdir(); (root / "storage_summary_indexes").mkdir()
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": [{"stable_key": "x", "truth_state": "STRICT_TRUTH", "symbol": "SG", "entry_fill_id": "e", "exit_fill_id": "x", "pretrade_context_v1": {"candidate_id": "legacy"}}]}))
        for name in ("symbol_behavior_profiles_v1.json", "astra_unified_position_advisory_v1.json"):
            (root / name).write_text(json.dumps({"profiles": {}} if "symbol" in name else {"positions": []}))
        (root / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json").write_text(json.dumps({}))
        (root / "dashboard_cache" / "shadow_vs_paper_performance_attribution_v1.json").write_text(json.dumps({}))
        for name in ("market_context_learning_suite_v1.jsonl.summary_index.json", "opportunity_cost_learning_v1.jsonl.summary_index.json", "trade_archetype_regime_intelligence_v1.jsonl.summary_index.json", "candidate_decision_ledger_v1.jsonl.summary_index.json"):
            (root / "storage_summary_indexes" / name).write_text(json.dumps({"dimension_counts": {}}))
        result = build_trading_intelligence_improvement_suite_v5(str(root))
        self.assertEqual(result["thesis_prediction_provenance"]["original_capture_verified"], 0)
        self.assertEqual(result["thesis_prediction_provenance"]["lifecycles"][0]["state"], "UNAVAILABLE")
        self.assertEqual(result["lifecycle_evidence_completeness"]["lifecycles"][0]["evidence_state"], "EVIDENCE_PARTIAL")
        self.assertFalse(result["historical_truths_modified"])
        self.assertFalse(result["execution_behavior_changed"])
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)
        self.assertEqual(result["llm_calls_used"], 0)
