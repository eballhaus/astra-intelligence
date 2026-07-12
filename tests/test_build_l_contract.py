import tempfile
import unittest

from engine.astra_build_l_research_maturation_v1 import (
    BuildLFinalValidationV1,
    CryptoIntelligenceSeparateEvidenceV2,
    HistoricalReplayMultiHorizonValidationV1,
    HorizonCapacityTurnoverResearchV1,
    MomentumExitReadinessLossAcceptanceV1,
)


def _statuses():
    return {
        "trade_lifecycle_audit_truth_horizon_integrity_suite_v1": {"broker_confirmed_count": 3},
        "profit_capture_peak_decay_exit_validation_suite_v1": {"profit_protection_opportunity_count": 1},
        "adaptive_execution_exit_intelligence_v3": {"exit_review_candidate_count": 1},
        "astra_trading_brain_completion_v1": {"exit_decision_intelligence_v1": {"exit_review_candidate_count": 1, "profit_protection_candidate_count": 1, "loss_containment_candidate_count": 1}},
        "alpaca_paper_broker": {"open_position_count": 3},
        "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1": {"horizon_capacity_manager_v1": {"total_capacity": 20, "total_used": 8, "day_used": 3, "swing_used": 5, "scalp_used": 0}},
        "multi_horizon_paper_capacity_exit_validation_v1": {"total_capacity": 20, "total_used": 8},
        "replay_counterfactual_learning_v2": {"tracked_lifecycles": 10, "replay_learning_score": 62.0},
        "realistic_shadow_evidence_learning_lab_v1": {"completed_lifecycles": 15, "regime_diversity_score": 40.0},
        "shadow_vs_paper_performance_attribution_v1": {"shadow_completed_lifecycle_count": 14},
        "crypto_shadow_learning_v1": {"crypto_completed_lifecycles": 12, "crypto_profit_factor_status": "INSUFFICIENT_EVIDENCE", "crypto_horizons": ["scalp", "intraday"]},
        "crypto_paper_execution_readiness_v1": {"readiness_state": "CRYPTO_PAPER_READY_NO_ELIGIBLE_TRADE", "verified_pairs": ["BTC/USD"]},
    }


class BuildLContractTests(unittest.TestCase):
    def test_momentum_and_capacity_outputs_are_advisory_only(self):
        statuses = _statuses()
        with tempfile.TemporaryDirectory() as state_dir:
            momentum = MomentumExitReadinessLossAcceptanceV1(state_dir=state_dir).status(statuses=statuses, force=True)
            horizon = HorizonCapacityTurnoverResearchV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(momentum["execution_state"], "ADVISORY_ONLY_NO_EXIT_ACTIVATION")
        self.assertFalse(momentum["forced_exits_enabled"])
        self.assertFalse(horizon["capacity_changed"])
        self.assertFalse(horizon["allocation_changed"])

    def test_replay_and_crypto_are_separate_and_bias_guarded(self):
        statuses = _statuses()
        with tempfile.TemporaryDirectory() as state_dir:
            replay = HistoricalReplayMultiHorizonValidationV1(state_dir=state_dir).status(statuses=statuses, force=True)
            crypto = CryptoIntelligenceSeparateEvidenceV2(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertTrue(replay["bias_protections"]["lookahead_rejected"])
        self.assertEqual(replay["evidence_hierarchy"], "broker_truth_above_shadow_above_replay")
        self.assertEqual(crypto["asset_class_contamination_guard"], "PASS")
        self.assertFalse(crypto["crypto_paper_trading_enabled"])

    def test_build_l_passes_with_deferred_evidence(self):
        statuses = _statuses()
        with tempfile.TemporaryDirectory() as state_dir:
            statuses["momentum_exit_readiness_loss_acceptance_v1"] = MomentumExitReadinessLossAcceptanceV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["horizon_capacity_turnover_research_v1"] = HorizonCapacityTurnoverResearchV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["historical_replay_multi_horizon_validation_v1"] = HistoricalReplayMultiHorizonValidationV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["crypto_intelligence_separate_evidence_v2"] = CryptoIntelligenceSeparateEvidenceV2(state_dir=state_dir).status(statuses=statuses, force=True)
            final = BuildLFinalValidationV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(final["status"], "BUILD_L_PASS_WITH_DEFERRED_EVIDENCE")
        self.assertEqual(final["checks_failed"], [])
        self.assertFalse(final["behavior_safe_to_apply"])
