"""Focused tests for the pure whole-platform fact adapter."""
from datetime import datetime, timedelta, timezone
import unittest

from engine.astra_whole_platform_observability_efficiency_v1 import (
    build_astra_whole_platform_observability_efficiency_v1,
)


class WholePlatformObservabilityTests(unittest.TestCase):
    def _statuses(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {
            "astra_sentinel_integrity_v1": {"status": "PASS", "generated_at": now, "first_causal_blocker": "NONE_OBSERVED"},
            "astra_continuous_governance_v1": {"status": "PASS", "generated_at": now},
            "cortex_lifecycle_evidence_master_truth_v1": {"status": "PASS", "generated_at": now},
            "astra_autonomous_learning_safe_adaptation_v1": {"status": "SHADOW_PRACTICE", "behavior_safe_to_apply": False, "generated_at": now},
            "astra_trading_intelligence_improvement_suite_v6": {"status": "OBSERVATIONAL_READY", "generated_at": now},
            "astra_historical_evidence_mining_knowledge_distillation_v1": {"status": "OBSERVATIONAL_READY", "generated_at": now},
            "astra_evidence_utilization_information_value_v1": {"status": "OBSERVATIONAL_READY", "generated_at": now},
            "astra_incremental_historical_learning_governor_v1": {"current_status": "READY", "generated_at": now},
            "astra_knowledge_warehouse_v1": {"status": "PASS", "generated_at": now},
            "knowledge_retrieval_indexing_v1": {"status": "PASS", "generated_at": now},
            "astra_evidence_consumption_teacher_shadow_v1": {"status": "PASS", "generated_at": now},
            "astra_runtime_resource_governance_v1": {"status": "PASS", "generated_at": now},
        }

    def test_reuses_sources_and_stays_read_only(self):
        payload = build_astra_whole_platform_observability_efficiency_v1(self._statuses())
        self.assertEqual(payload["control_plane_health"]["sentinel"]["evidence_source"], "astra_sentinel_integrity_v1")
        self.assertEqual(payload["provider_calls_added"], 0)
        self.assertEqual(payload["broker_actions_added"], 0)
        self.assertFalse(payload["execution_behavior_changed"])
        self.assertFalse(payload["frozen_lifecycle_modified"])
        self.assertLessEqual(len(payload["top_priorities"]), 5)

    def test_missing_sources_are_explicit_gaps(self):
        payload = build_astra_whole_platform_observability_efficiency_v1({})
        backend = next(row for row in payload["domains"] if row["domain"] == "backend")
        self.assertEqual(backend["monitored"], "NO")
        self.assertEqual(backend["health"], "UNKNOWN")
        self.assertIn("backend", payload["monitoring_gaps"])

    def test_stale_governance_pass_is_not_current_pass(self):
        stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        payload = build_astra_whole_platform_observability_efficiency_v1({"astra_continuous_governance_v1": {"status": "PASS", "generated_at": stale}})
        self.assertEqual(payload["control_plane_health"]["governance"]["health"], "STALE_PASS_NOT_CURRENT")

    def test_current_governance_pass_variant_is_healthy(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload = build_astra_whole_platform_observability_efficiency_v1({"astra_continuous_governance_v1": {"status": "PASS_AUTONOMOUS_REMEDIATION_WITH_BOUNDED_BACKLOG", "generated_at": now}})
        self.assertEqual(payload["control_plane_health"]["governance"]["health"], "HEALTHY")

    def test_learning_bottleneck_is_evidence_backed_and_bounded(self):
        statuses = self._statuses()
        statuses["astra_evidence_utilization_information_value_v1"] = {"status": "DEGRADED", "first_causal_blocker": "OUTCOME_LINKAGE_SPARSE"}
        payload = build_astra_whole_platform_observability_efficiency_v1(statuses)
        self.assertEqual(payload["learning_funnel"]["first_measurable_bottleneck"]["blocker"], "OUTCOME_LINKAGE_SPARSE")
        self.assertEqual(payload["autonomy_funnel"]["stages"][0]["evidence_source"], "astra_trading_intelligence_improvement_suite_v6")


if __name__ == "__main__":
    unittest.main()
