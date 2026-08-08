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

    def test_error_without_owner_detail_remains_truthful(self):
        payload = build_astra_whole_platform_observability_efficiency_v1({"astra_incremental_historical_learning_governor_v1": {"current_status": "ERROR"}})
        row = next(item for item in payload["domains"] if item["domain"] == "v10_runner")
        self.assertEqual(row["first_causal_blocker"], "STATUS_REPORTED_WITHOUT_DETAILED_BLOCKER:ERROR")

    def test_publishes_existing_critical_fact_fields_without_new_owner(self):
        statuses = self._statuses()
        statuses.update({
            "canonical_worker_state": {"worker_health": "HEALTHY", "heartbeat_at": "2026-08-08T15:00:00Z", "process_id": 7, "generation": 2, "cycle_count": 12},
            "paper_autopilot_last_trace_v1": {"candidates_seen": 9, "eligible_candidates": 3, "selected_candidates": 1, "final_blocker_reason": "CAPACITY_RESERVED"},
            "alpaca_paper_status_v1": {"safety_status": "PASS", "paper_mode_verified": True, "broker_execution_ready": True, "live_endpoint_rejected": True, "open_positions_count": 2, "open_orders_count": 1},
            "astra_trade_state_reconciliation_v1": {"status": "PASS", "mirror_gap_remaining": 0},
            "cortex_lifecycle_evidence_master_truth_v1": {"status": "PASS", "strict_truth_count": 3, "latest_truth_at": "2026-08-08T14:00:00Z"},
        })
        payload = build_astra_whole_platform_observability_efficiency_v1(statuses)
        rows = {row["domain"]: row for row in payload["domains"]}
        self.assertEqual(rows["paper_autopilot_worker"]["fact_summary"]["process_id"], 7)
        self.assertEqual(rows["candidate_trading_pipeline"]["fact_summary"]["eligible_count"], 3)
        self.assertTrue(rows["broker"]["fact_summary"]["paper_mode_verified"])
        self.assertEqual(rows["broker"]["health"], "HEALTHY")
        self.assertTrue(rows["broker"]["fact_summary"]["live_endpoint_rejected"])
        self.assertEqual(rows["reconciliation"]["fact_summary"]["mirror_gap_remaining"], 0)
        self.assertEqual(rows["strict_truth"]["fact_summary"]["strict_truth_count"], 3)

    def test_v10_discrepancy_is_reported_without_repair(self):
        payload = build_astra_whole_platform_observability_efficiency_v1({"astra_incremental_historical_learning_governor_v1": {"current_status": "ERROR", "resource_decision": {"decision": "RUN"}, "last_checkpoint": {"status": "READY"}}})
        self.assertEqual(payload["v10_status_source_discrepancy"]["status"], "V10_STATUS_SOURCE_DISCREPANCY")
        self.assertFalse(payload["v10_status_source_discrepancy"]["automatic_repair_attempted"])


    def test_reconciliation_reuses_already_loaded_trace_payload_fresh(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        statuses = {
            "paper_autopilot_last_trace_v1": {
                "paper_worker_running": True,
                "candidates_seen": 4,
                "evidence_accumulation_capacity_v1": {
                    "generated_at": now,
                    "broker_reconciliation_status": "FRESH",
                    "capacity_authority_owner": "PaperAutopilot._evidence_capacity_snapshot_v1",
                },
            }
        }
        payload = build_astra_whole_platform_observability_efficiency_v1(statuses)
        row = next(item for item in payload["domains"] if item["domain"] == "reconciliation")
        self.assertEqual(row["monitored"], "YES")
        self.assertEqual(row["evidence_source"], "paper_autopilot_last_trace_v1")
        self.assertEqual(row["fact_summary"]["reconciliation_status"], "FRESH")
        self.assertEqual(row["health"], "HEALTHY")
        self.assertEqual(row["freshness"], "CURRENT")
        self.assertEqual(payload["provider_calls_added"], 0)
        self.assertEqual(payload["broker_calls_added"], 0)
        self.assertEqual(payload["broker_actions_added"], 0)
        self.assertEqual(payload["llm_calls_added"], 0)
        self.assertFalse(payload["execution_behavior_changed"])
        self.assertFalse(payload["frozen_lifecycle_modified"])

    def test_reconciliation_reuses_already_loaded_trace_payload_stale(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        statuses = {
            "paper_autopilot_last_trace_v1": {
                "evidence_accumulation_capacity_v1": {
                    "generated_at": now,
                    "broker_reconciliation_status": "STALE_OR_UNAVAILABLE",
                },
            }
        }
        payload = build_astra_whole_platform_observability_efficiency_v1(statuses)
        row = next(item for item in payload["domains"] if item["domain"] == "reconciliation")
        self.assertEqual(row["monitored"], "YES")
        self.assertEqual(row["fact_summary"]["reconciliation_status"], "STALE_OR_UNAVAILABLE")
        self.assertEqual(row["health"], "FAIL")
        self.assertEqual(payload["provider_calls_added"], 0)
        self.assertEqual(payload["broker_actions_added"], 0)

    def test_reconciliation_without_loaded_trace_stays_explicit_gap(self):
        payload = build_astra_whole_platform_observability_efficiency_v1(self._statuses())
        row = next(item for item in payload["domains"] if item["domain"] == "reconciliation")
        self.assertEqual(row["monitored"], "NO")
        self.assertEqual(row["evidence_source"], None)
        self.assertIn("reconciliation", payload["monitoring_gaps"])

    def test_dedicated_reconciliation_source_still_wins_over_trace(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        statuses = {
            "astra_trade_state_reconciliation_v1": {"status": "PASS", "mirror_gap_remaining": 0, "generated_at": now},
            "paper_autopilot_last_trace_v1": {"evidence_accumulation_capacity_v1": {"generated_at": now, "broker_reconciliation_status": "STALE_OR_UNAVAILABLE"}},
        }
        payload = build_astra_whole_platform_observability_efficiency_v1(statuses)
        row = next(item for item in payload["domains"] if item["domain"] == "reconciliation")
        self.assertEqual(row["evidence_source"], "astra_trade_state_reconciliation_v1")
        self.assertEqual(row["fact_summary"]["mirror_gap_remaining"], 0)
        self.assertEqual(row["health"], "HEALTHY")


if __name__ == "__main__":
    unittest.main()
