import tempfile
import unittest

from engine.astra_master_il_final_validation_v1 import AstraMasterILFinalValidationV1, WIRING_SPECS


def _statuses():
    statuses = {
        "astra_knowledge_warehouse_v1": {"canonical_layer": True},
        "ask_astra_reliability_grounding_v1": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "canonical_source_coverage_pct": 100.0, "source_lineage_coverage_pct": 100.0, "deterministic_answer_coverage_pct": 100.0, "llm_dependency_rate_pct": 0.0},
        "copilot_effectiveness_ranking_attribution_v2": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "canonical_engine": "_astra_copilot_suite_v1", "trade_linkage_coverage": 0, "sample_maturity": "UNLINKED", "exact_blockers": ["linkage_pending"]},
        "shadow_lifecycle_compression_retention_v1": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "paper_shadow_twin": {"linked_complete_twins": 0}, "retention_state": "DIAGNOSTIC_POLICY_ONLY"},
        "active_learning_evidence_gap_v1": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "active_learning_priority_queue": [{}]},
        "teaching_effectiveness_v1": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "teaching_proof": {"delivery_is_not_counted_as_influence": True}},
        "astra_autonomous_safe_repair_v1": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "repairs_attempted": 0, "trading_change_attempts_rejected": [{}]},
        "astra_governance_oversight_v2": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0},
        "momentum_exit_readiness_loss_acceptance_v1": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0},
        "horizon_capacity_turnover_research_v1": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0},
        "historical_replay_multi_horizon_validation_v1": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "evidence_hierarchy": "broker_truth_above_shadow_above_replay", "bias_protections": {"lookahead_rejected": True}},
        "crypto_intelligence_separate_evidence_v2": {"status": "ok", "generated_at": "2026-01-01T00:00:00Z", "behavior_safe_to_apply": False, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "asset_class_contamination_guard": "PASS"},
    }
    for name in ("build_i_final_validation_v1", "build_j_final_validation_v1", "build_k_final_validation_v1", "build_l_final_validation_v1"):
        statuses[name] = {"status": "BUILD_PASS_WITH_DEFERRED_EVIDENCE"}
    return statuses


class MasterILContractTests(unittest.TestCase):
    def test_master_wiring_matrix_has_no_orphans_or_silent_fallbacks(self):
        with tempfile.TemporaryDirectory() as state_dir:
            payload = AstraMasterILFinalValidationV1(state_dir=state_dir).status(statuses=_statuses(), force=True)
        self.assertEqual(payload["status"], "ASTRA_MASTER_IL_PASS_WITH_DEFERRED_EVIDENCE")
        self.assertEqual(payload["orphaned_new_components"], 0)
        self.assertEqual(payload["duplicate_authoritative_owners"], 0)
        self.assertEqual(payload["unwired_required_consumers"], 0)
        self.assertEqual(payload["silent_fallbacks"], 0)
        self.assertEqual(len(payload["wiring_matrix"]), len(WIRING_SPECS))

    def test_master_blocks_missing_component_instead_of_silent_success(self):
        statuses = _statuses()
        statuses.pop("teaching_effectiveness_v1")
        with tempfile.TemporaryDirectory() as state_dir:
            payload = AstraMasterILFinalValidationV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(payload["status"], "ASTRA_MASTER_IL_BLOCKED")
        self.assertIn("orphaned_new_components_zero", payload["checks_failed"])
