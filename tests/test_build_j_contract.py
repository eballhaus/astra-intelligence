import tempfile
import unittest

from engine.astra_build_j_active_learning_v1 import (
    ActiveLearningEvidenceGapV1,
    BuildJFinalValidationV1,
    ShadowLifecycleCompressionRetentionV1,
    TeachingEffectivenessV1,
)


def _statuses():
    return {
        "broker_truth_accumulation_v2": {"total_complete_broker_confirmed_lifecycles": 4},
        "realistic_shadow_evidence_learning_lab_v1": {"completed_lifecycles": 16},
        "replay_counterfactual_learning_v2": {"tracked_lifecycles": 12, "counterfactuals_generated": 168, "most_common_missed_improvement": "exit_timing_profit_capture"},
        "shadow_vs_paper_performance_attribution_v1": {"shadow_completed_lifecycle_count": 14},
        "astra_knowledge_warehouse_v1": {"canonical_layer": True, "manifest_first": True},
        "astra_intelligence_effectiveness_learning_velocity_v1": {"evidence_available": 80, "evidence_indexed": 60, "evidence_retrieved": 20, "evidence_consumed": 5, "decision_fields_influenced": 2, "lesson_state_counts": {"lessons": 12, "contradicted": 1}, "evidence_chain": [{"consumed": 5}], "consumer_coverage": {"shadow": ["Copilot"]}},
        "astra_tier2a_librarian_executive_truth_layer_v1": {"lessons_organized": 12},
        "crypto_shadow_learning_v1": {"crypto_completed_lifecycles": 20},
    }


class BuildJContractTests(unittest.TestCase):
    def test_retention_policy_preserves_authoritative_truth(self):
        with tempfile.TemporaryDirectory() as state_dir:
            payload = ShadowLifecycleCompressionRetentionV1(state_dir=state_dir).status(statuses=_statuses(), force=True)
        authoritative = next(row for row in payload["retention_classes"] if row["retention_class"] == "PERMANENT_AUTHORITATIVE")
        self.assertFalse(authoritative["destructive_action_allowed"])
        self.assertTrue(payload["paper_shadow_twin"]["information_available_at_timestamp_only"])
        self.assertEqual(payload["provider_calls_used"], 0)

    def test_gap_and_teaching_contracts_do_not_claim_delivery_is_influence(self):
        statuses = _statuses()
        with tempfile.TemporaryDirectory() as state_dir:
            lifecycle = ShadowLifecycleCompressionRetentionV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["shadow_lifecycle_compression_retention_v1"] = lifecycle
            gaps = ActiveLearningEvidenceGapV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["active_learning_evidence_gap_v1"] = gaps
            teaching = TeachingEffectivenessV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertTrue(gaps["conflict_resolution_contract"]["same_calculation_may_not_self_approve"])
        self.assertTrue(teaching["teaching_proof"]["delivery_is_not_counted_as_influence"])
        self.assertEqual(teaching["outcome_effectiveness_status"], "INSUFFICIENT_BROKER_LINKAGE")

    def test_build_j_degrades_honestly_when_twin_evidence_is_small(self):
        statuses = _statuses()
        with tempfile.TemporaryDirectory() as state_dir:
            lifecycle = ShadowLifecycleCompressionRetentionV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["shadow_lifecycle_compression_retention_v1"] = lifecycle
            gaps = ActiveLearningEvidenceGapV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["active_learning_evidence_gap_v1"] = gaps
            teaching = TeachingEffectivenessV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["teaching_effectiveness_v1"] = teaching
            final = BuildJFinalValidationV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(final["status"], "BUILD_J_PASS_WITH_DEFERRED_EVIDENCE")
        self.assertIn("paper_shadow_twin_sample_below_25", final["deferred_evidence_limitations"])
        self.assertFalse(final["behavior_safe_to_apply"])
