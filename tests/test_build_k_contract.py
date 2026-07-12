import tempfile
import unittest

from engine.astra_build_k_safe_repair_governance_v1 import (
    AstraAutonomousSafeRepairV1,
    AstraGovernanceOversightV2,
    BuildKFinalValidationV1,
)


def _statuses():
    return {
        "unified_learning_diagnostics_v1": {"failed_sources_count": 0, "behavior_safe_to_apply": False},
        "astra_governance_oversight_v1": {"stale_cache_summary": {"stale_decision_critical_cache_count": 0}},
        "astra_knowledge_warehouse_v1": {"canonical_layer": True, "manifest_first": True},
        "astra_recovery_center_v1": {"recovery_health_score": 90.0},
        "alpaca_paper_broker": {"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
    }


class BuildKContractTests(unittest.TestCase):
    def test_safe_repair_never_attempts_behavior_mutation_during_status(self):
        with tempfile.TemporaryDirectory() as state_dir:
            repair = AstraAutonomousSafeRepairV1(state_dir=state_dir).status(statuses=_statuses(), force=True)
        self.assertEqual(repair["repairs_attempted"], 0)
        self.assertTrue(repair["rollback_contract"]["snapshot_required"])
        names = {row["attempted_change"] for row in repair["trading_change_attempts_rejected"]}
        self.assertIn("ranking", names)
        self.assertIn("exit", names)
        self.assertIn("live_trading", names)

    def test_governance_reports_exact_causes_and_v1_compatibility(self):
        statuses = _statuses()
        with tempfile.TemporaryDirectory() as state_dir:
            repair = AstraAutonomousSafeRepairV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["astra_autonomous_safe_repair_v1"] = repair
            governance = AstraGovernanceOversightV2(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(governance["compatible_v1_source"], "/api/astra_governance_oversight_v1")
        self.assertTrue(governance["exact_top_concern_cause"])
        self.assertEqual(governance["provider_calls_used"], 0)

    def test_build_k_rejects_trading_changes_and_passes_safely(self):
        statuses = _statuses()
        with tempfile.TemporaryDirectory() as state_dir:
            repair = AstraAutonomousSafeRepairV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["astra_autonomous_safe_repair_v1"] = repair
            governance = AstraGovernanceOversightV2(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["astra_governance_oversight_v2"] = governance
            final = BuildKFinalValidationV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(final["status"], "BUILD_K_PASS_WITH_DEFERRED_EVIDENCE")
        self.assertEqual(final["checks_failed"], [])
        self.assertFalse(final["behavior_safe_to_apply"])
