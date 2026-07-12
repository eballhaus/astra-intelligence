import tempfile
import unittest

from engine.astra_build_i_decision_intelligence_v1 import (
    AskAstraReliabilityGroundingV1,
    BuildIFinalValidationV1,
    CopilotEffectivenessRankingAttributionV2,
    resolve_question_route,
)


def _statuses():
    return {
        "astra_copilot_suite_v1": {
            "recommendations": [
                {
                    "recommendation_id": "rec-nvda-1",
                    "symbol": "NVDA",
                    "action": "HOLD",
                    "canonical_lifecycle_state": "HOLD",
                    "confidence": 82.0,
                    "preferred_horizon": "day_trade",
                    "trade_style": "momentum",
                    "paper_autopilot_eligible": False,
                }
            ]
        },
        "broker_truth_accumulation_v2": {
            "broker_truth_authoritative": True,
            "total_complete_broker_confirmed_lifecycles": 1,
            "official_metric_status": "INSUFFICIENT_BROKER_TRUTH_EVIDENCE",
        },
        "astra_knowledge_warehouse_v1": {"canonical_layer": True, "source_lineage_supported": True},
        "astra_shadow_experiment_governance_v1": {"current_readiness": "REPEATABILITY_PENDING"},
        "replay_counterfactual_learning_v2": {"status": "ok"},
        "crypto_shadow_learning_v1": {"status": "ok"},
        "market_breadth_index_intelligence_v1": {"status": "ok"},
        "etf_sector_rotation_intelligence_v1": {"status": "ok"},
        "unified_learning_diagnostics_v1": {"status": "ok"},
        "build_i_broker_records": [{"recommendation_id": "rec-nvda-1", "truth_quality": "broker_confirmed_complete"}],
    }


class BuildIContractTests(unittest.TestCase):
    def test_canonical_route_uses_selected_symbol_and_discloses_source(self):
        route = resolve_question_route("Why is it a hold?", selected_symbol="NVDA", statuses=_statuses())
        self.assertEqual(route["intent"], "copilot_recommendation")
        self.assertEqual(route["entities"]["symbol"], "NVDA")
        self.assertEqual(route["answer_state"], "ANSWERED_FROM_CANONICAL_CURRENT_DATA")
        self.assertIn("_astra_copilot_suite_v1", route["canonical_sources"])
        self.assertFalse(route["llm_required"])
        self.assertEqual(route["provider_calls_used"], 0)

    def test_crypto_pair_resolution_is_separate_from_equity(self):
        route = resolve_question_route("Explain BTC/USD crypto readiness", statuses=_statuses())
        self.assertEqual(route["entities"]["symbol"], "BTC")
        self.assertEqual(route["entities"]["asset_class"], "crypto")
        self.assertEqual(route["answer_state"], "ANSWERED_FROM_SHADOW_EVIDENCE")

    def test_build_i_contracts_are_grounded_and_guarded(self):
        statuses = _statuses()
        with tempfile.TemporaryDirectory() as state_dir:
            grounding = AskAstraReliabilityGroundingV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["ask_astra_reliability_grounding_v1"] = grounding
            attribution = CopilotEffectivenessRankingAttributionV2(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["copilot_effectiveness_ranking_attribution_v2"] = attribution
            final = BuildIFinalValidationV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(grounding["deterministic_answer_coverage_pct"], 100.0)
        self.assertEqual(attribution["canonical_engine"], "_astra_copilot_suite_v1")
        self.assertEqual(attribution["trade_linkage_coverage"], 1)
        self.assertEqual(final["status"], "BUILD_I_PASS_WITH_DEFERRED_EVIDENCE")
        for payload in (grounding, attribution, final):
            self.assertFalse(payload["behavior_safe_to_apply"])
            self.assertEqual(payload["provider_calls_used"], 0)
            self.assertEqual(payload["llm_calls_used"], 0)
