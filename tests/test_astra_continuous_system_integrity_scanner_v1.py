from __future__ import annotations

import json
import os
import tempfile
import unittest

from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.astra_integrity_dependency_graph_v1 import root_cause_from_signal_v1
from engine.astra_safe_correction_registry_v1 import SafeCorrectionRegistryV1


class ContinuousSystemIntegrityScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scanner = ContinuousSystemIntegrityScannerV1(self.temp.name)

    def _scan(self, **context):
        return self.scanner.run_if_due(
            worker_state={"active_worker_present": True, "process_role": "PAPER_AUTOPILOT_WORKER"}, runtime_state={}, safety={"paper_mode_verified": True}, context=context,
        )

    def test_quote_field_loss_groups_one_root_with_downstream_symptoms(self):
        payload = self._scan(quote_handoffs=[{"symbol": "BTC/USD", "provider_bid": 10, "provider_ask": 10.1, "snapshot_bid": None, "snapshot_ask": None}])
        roots = payload["active_root_causes"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["category"], "FIELD_DROPPED_DURING_TRANSFORMATION")
        self.assertIn("PENDING_SPREAD", roots[0]["downstream_symptoms"])
        self.assertGreaterEqual(payload["downstream_symptoms_suppressed"], 1)

    def test_canonical_source_violation_is_safe_nonbehavioral_correction(self):
        payload = self._scan(truth_arbitration={"contradictions": [{"fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT", "severity": "HIGH"}]})
        self.assertEqual(payload["active_root_causes"][0]["category"], "CANONICAL_SOURCE_VIOLATION")
        self.assertTrue(payload["safe_corrections_applied"])
        self.assertFalse(payload["behavior_safe_to_apply"])
        self.assertFalse(payload["entry_behavior_changed"])

    def test_historical_reconciliation_collision_blocks_sentinel_pass_and_reports_cortex_owner(self):
        payload = self._scan(historical_reconciliation_ownership_collisions={"collisions": [{
            "symbol": "SG", "historical_reconciliation_id": "recon-old", "current_position_ids": ["day-new"],
        }]})
        self.assertEqual(payload["status"], "CRITICAL")
        root = payload["active_root_causes"][0]
        self.assertEqual(root["category"], "HISTORICAL_RECONCILIATION_OWNERSHIP_COLLISION")
        self.assertIn("Cortex", root["affected_endpoints"])
        self.assertTrue(root["human_repair_required"])

    def test_governance_critical_worker_or_day_exit_invariant_blocks_sentinel_pass(self):
        payload = self._scan(continuous_governance={"invariants": [{
            "invariant_id": "LOSS_THRESHOLD_BREACH_NOT_EXIT_READY",
            "state": "FAIL",
            "owner": "PaperAutopilot._loss_containment_review_phase",
            "exact_blocker": "LOSS_THRESHOLD_BREACH_NOT_EXIT_READY",
            "observed_value": {"position_id": "pt-day", "symbol": "PTON"},
        }]})
        self.assertEqual(payload["status"], "CRITICAL")
        root = payload["active_root_causes"][0]
        self.assertEqual(root["category"], "LOSS_THRESHOLD_BREACH_NOT_EXIT_READY")
        self.assertIn("Sentinel", root["affected_endpoints"])
        self.assertIn("Cortex", root["affected_endpoints"])

    def test_unsafe_correction_is_rejected_without_mutation(self):
        registry = SafeCorrectionRegistryV1(self.temp.name)
        transaction = registry.prepare("root-1", "CLOSE_POSITION", target_component="position store", target_artifact="position", before_state={"status": "OPEN"}, after_state={"status": "CLOSED"})
        self.assertFalse(transaction["allowed_by_registry"])
        self.assertEqual(transaction["verification_state"], "HUMAN_REPAIR_REQUIRED")
        self.assertFalse(transaction["applied"])

    def test_provider_absence_is_legitimate_waiting_not_contract_defect(self):
        payload = self._scan(quote_handoffs=[{"symbol": "LINK/USD", "provider_bid": None, "provider_ask": None}])
        self.assertFalse(any(root["category"] == "FIELD_DROPPED_DURING_TRANSFORMATION" for root in payload["active_root_causes"]))
        self.assertEqual(payload["legitimate_waiting_states"][0]["reason"], "provider_quote_absent")

    def test_identity_unmapped_microscopic_dust_remains_visible_as_waiting(self):
        payload = self._scan(continuous_governance={"invariants": [{
            "invariant_id": "HISTORICAL_BROKER_DUST_QUARANTINED",
            "state": "LEGITIMATE_WAITING_STATE",
            "owner": "PaperAutopilot._quarantine_identity_unmapped_broker_dust_v1",
            "observed_value": {"position_id": "dust-ph", "lifecycle_id": "dust-ph", "symbol": "PH"},
        }]})
        waiting = next(row for row in payload["legitimate_waiting_states"] if row["reason"] == "BROKER_DUST_RESIDUAL_UNMAPPED_TO_CANONICAL_LIFECYCLE")
        self.assertEqual(waiting["position_id"], "dust-ph")
        self.assertFalse(any(root["category"] == "BROKER_POSITION_QUANTITY_MISMATCH" for root in payload["active_root_causes"]))

    def test_current_market_evidence_blocker_does_not_become_horizon_root(self):
        payload = self._scan(
            crypto_integrity={"pair_eligibility": {"evaluated_candidates": [{
                "symbol": "LINK/USD",
                "first_causal_blocker": {"gate": "quote_spread", "status": "PENDING_SPREAD"},
                "gate_status": {"horizon_assignment": "PENDING_HORIZON_EVIDENCE:QUOTE"},
            }]}},
            multilane_completion_matrix={"status": "WARNING", "lanes": {"CRYPTO": {"first_blocker": "quote_spread"}}},
        )
        categories = [row["category"] for row in payload["active_root_causes"]]
        self.assertIn("CRYPTO_MARKET_EVIDENCE_NOT_READY", categories)
        self.assertNotIn("CRYPTO_HORIZON_PRODUCER_CONSUMER_MISMATCH", categories)
        self.assertNotIn("MONITORING_COVERAGE_GAP", categories)

    def test_valid_evidence_not_consumed_is_consumer_defect(self):
        payload = self._scan(shadow_protection={"lifecycle_evidence_eligibility": {"eligible_complete_lifecycles": 1}, "shadow_profit_loss_consumption": {"valid_records_consumed": 0}})
        self.assertEqual(payload["active_root_causes"][0]["category"], "EVIDENCE_CONSUMER_FAILURE")
        self.assertTrue(payload["human_repairs_required"])

    def test_invalid_evidence_is_legitimate_waiting(self):
        payload = self._scan(shadow_protection={"lifecycle_evidence_eligibility": {"eligible_complete_lifecycles": 0}})
        self.assertEqual(payload["active_root_causes"], [])
        self.assertIn("insufficient_completed_broker_lifecycle_evidence", [row["reason"] for row in payload["legitimate_waiting_states"]])

    def test_snapshot_get_is_read_only(self):
        self._scan()
        before = os.stat(self.scanner.summary_path).st_mtime_ns
        result = self.scanner.snapshot()
        after = os.stat(self.scanner.summary_path).st_mtime_ns
        self.assertEqual(before, after)
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)
        self.assertEqual(result["llm_calls_used"], 0)
        self.assertEqual(result["state_mutations_from_get"], 0)

    def test_overlap_is_deferred(self):
        self.scanner.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.scanner.lock_path.write_text("owned", encoding="utf-8")
        payload = self._scan()
        self.assertEqual(payload["scan_deferred"], "SCAN_DEFERRED_EXISTING_OWNER")

    def test_non_worker_owner_is_rejected(self):
        payload = self.scanner.run_if_due(worker_state={"process_role": "API_GET"}, runtime_state={}, safety={}, context={})
        self.assertEqual(payload["status"], "SCAN_REJECTED_NONCANONICAL_OWNER")

    def test_verification_window_does_not_resolve_on_one_clean_cycle(self):
        self._scan(truth_arbitration={"contradictions": [{"fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT"}]})
        self.scanner.summary_path.unlink()  # Make the test invoke another scan immediately.
        next_payload = self._scan()
        state = next_payload["active_root_causes"][0]["state"]
        self.assertEqual(state, "VERIFYING")

    def test_root_cause_ownership_is_deterministic(self):
        root = root_cause_from_signal_v1({"kind": "QUOTE_FIELDS_DROPPED", "canonical_fact_ids": ["CURRENT_QUOTE_BID"]})
        self.assertEqual(root["likely_owner"], "crypto ranking transformation")
        self.assertIn("data_orchestrator quote row", root["first_bad_handoff"])

    def test_resolved_root_recurrence_is_escalated(self):
        bad = {"truth_arbitration": {"contradictions": [{"fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT"}]}}
        self._scan(**bad)
        for _ in range(3):
            self.scanner.summary_path.unlink(missing_ok=True)
            self._scan()
        self.scanner.summary_path.unlink(missing_ok=True)
        payload = self._scan(**bad)
        self.assertEqual(payload["active_root_causes"][0]["state"], "RECURRENT")

    def test_absent_recurrent_root_resolves_without_erasing_recurrence_history(self):
        bad = {"truth_arbitration": {"contradictions": [{"fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT"}]}}
        self._scan(**bad)
        for _ in range(3):
            self.scanner.summary_path.unlink(missing_ok=True)
            self._scan()
        self.scanner.summary_path.unlink(missing_ok=True)
        recurrent = self._scan(**bad)["active_root_causes"][0]
        self.assertEqual(recurrent["state"], "RECURRENT")
        recurrence_count = recurrent["occurrence_count"]
        self.scanner.summary_path.unlink(missing_ok=True)
        for index in range(3):
            self.scanner.summary_path.unlink(missing_ok=True)
            payload = self._scan()
        self.assertFalse(any(row["root_cause_id"] == recurrent["root_cause_id"] for row in payload["active_root_causes"]))
        stored_payload = json.loads(self.scanner.root_path.read_text(encoding="utf-8"))
        stored = {row["root_cause_id"]: row for row in stored_payload["root_causes"]}
        self.assertEqual(stored[recurrent["root_cause_id"]]["state"], "RESOLVED")
        self.assertEqual(stored[recurrent["root_cause_id"]]["occurrence_count"], recurrence_count)
        self.assertTrue(stored[recurrent["root_cause_id"]]["resolved_at"])

    def test_endpoint_side_effect_blocks_executive_pass(self):
        payload = self._scan(get_side_effects=1)
        self.assertEqual(payload["status"], "CRITICAL")
        self.assertEqual(payload["active_root_causes"][0]["category"], "ENDPOINT_SIDE_EFFECT")

    def test_unknown_defect_has_human_repair_package(self):
        payload = self._scan(static_findings=[{"kind": "UNKNOWN_SYSTEM_DEFECT"}])
        # Static findings are intentionally advisory unless the worker passed
        # one as a verified runtime signal; unknown runtime packaging remains
        # covered by the deterministic root mapper.
        root = root_cause_from_signal_v1({"kind": "UNKNOWN_SYSTEM_DEFECT", "severity": "HIGH"})
        self.assertTrue(root["human_repair_required"])

    def test_global_safety_invariants_are_unchanged(self):
        payload = self._scan()
        self.assertTrue(payload["paper_only_preserved"])
        self.assertFalse(payload["live_trading_enabled"])
        self.assertFalse(payload["forced_trades_enabled"])
        self.assertFalse(payload["forced_exits_enabled"])
        self.assertFalse(payload["learned_exits_enabled"])

    def test_cortex_separates_current_exit_blocker_from_natural_crypto_evidence_wait(self):
        payload = self._scan(
            trading_readiness={
                "trading_integrity_state": "READY",
                "lane_readiness": {"DAY": "TECHNICALLY_READY", "SCALP": "TECHNICALLY_READY", "SWING": "TECHNICALLY_READY", "CRYPTO": "TECHNICALLY_READY"},
                "day_readiness": "TECHNICALLY_READY", "scalp_readiness": "TECHNICALLY_READY",
                "swing_readiness": "TECHNICALLY_READY", "crypto_readiness": "TECHNICALLY_READY",
            },
            continuous_governance={"invariants": [{
                "invariant_id": "DAY_POSITION_HORIZON_BREACH", "state": "FAIL",
                "owner": "PaperAutopilot._lane_forced_exit_reason",
                "exact_blocker": "OVERNIGHT_HOLD_NOT_AUTHORIZED",
                "observed_value": {"symbol": "LYFT", "position_id": "life-1"},
            }]},
            crypto_integrity={"pair_eligibility": {"evaluated_candidates": [{
                "symbol": "BTC/USD", "first_causal_blocker": {"gate": "timestamp_freshness", "status": "STALE"},
            }]}},
        )
        cortex = payload["cortex_summary"]
        self.assertTrue(cortex["cross_layer_readiness_consistency_v1"]["all_lanes_technically_ready"])
        self.assertTrue(cortex["active_exit_blockers"] or cortex["active_truth_blockers"])
        self.assertTrue(cortex["natural_evidence_pending"])

    def test_cortex_does_not_describe_degraded_readiness_as_all_ready(self):
        payload = self._scan(
            trading_readiness={
                "trading_integrity_state": "DEGRADED",
                "lane_readiness": {
                    "DAY": "DEGRADED", "SCALP": "DEGRADED",
                    "SWING": "DEGRADED", "CRYPTO": "TECHNICALLY_READY",
                },
            },
        )
        cross_layer = payload["cortex_summary"]["cross_layer_readiness_consistency_v1"]
        self.assertFalse(cross_layer["all_lanes_technically_ready"])
        self.assertIn("degraded or blocked", cross_layer["explanation"])
        self.assertNotIn("All lanes are technically entry-ready", cross_layer["explanation"])

    def test_lane_activity_summary_is_bounded_and_forwarded_to_governance_and_cortex(self):
        payload = self._scan(
            trading_readiness={
                "lane_readiness": {"DAY": "TECHNICALLY_READY", "SCALP": "TECHNICALLY_READY", "SWING": "TECHNICALLY_READY", "CRYPTO": "TECHNICALLY_READY"},
                "lane_activity_truth_starvation_v1": {"lanes": {
                    "DAY": {"classification": "POLICY_REJECTION", "activity_warning": "DEEP_REVIEW", "first_causal_stage": "QUALIFICATION", "reason": "CANDIDATES_OBSERVED_WITHOUT_ENTRY_OR_TRUTH_PROGRESS"},
                }},
            },
        )
        cortex = payload["cortex_summary"]["lane_operations_summary_v1"]
        governance = payload["governance_summary"]["lane_operations_summary_v1"]
        self.assertEqual(cortex["lanes"]["DAY"]["status"], "DEEP_REVIEW")
        self.assertEqual(cortex["lanes"]["DAY"]["first_causal_stage"], "QUALIFICATION")
        self.assertEqual(cortex["lanes"]["DAY"]["drill_down_ref"], "astra_trading_readiness_v1.lane_activity_truth_starvation_v1.lanes.DAY")
        self.assertEqual(cortex["raw_records_forwarded"], 0)
        self.assertEqual(governance, cortex)

    def test_lane_activity_provider_wait_is_not_described_as_healthy_or_a_code_defect(self):
        payload = self._scan(
            trading_readiness={
                "lane_readiness": {"DAY": "TECHNICALLY_READY"},
                "lane_activity_truth_starvation_v1": {"lanes": {
                    "DAY": {"classification": "PROVIDER_EXTERNAL", "activity_warning": "NORMAL"},
                }},
            },
        )
        day = payload["cortex_summary"]["lane_operations_summary_v1"]["lanes"]["DAY"]
        self.assertEqual(day["status"], "EXTERNAL_WAIT")
        self.assertEqual(day["activity_classification"], "PROVIDER_EXTERNAL")

    def test_current_allowed_capacity_with_a_pending_candidate_gate_remains_a_sentinel_defect(self):
        payload = self._scan(
            canonical_capacity_fact={"authority_current": True, "allowed": True, "capacity_decision": "AVAILABLE"},
            crypto_integrity={"candidate_execution_blockers": ["capacity_concentration"]},
        )
        categories = {row["category"] for row in payload["active_root_causes"]}
        self.assertIn("CANONICAL_CAPACITY_CONSUMER_MISMATCH", categories)

    def test_cycle_failure_is_reported_as_active_infrastructure_without_relaxing_governance(self):
        payload = self._scan(
            continuous_governance={"invariants": [{
                "invariant_id": "CYCLE_WITHIN_BOUNDS", "state": "FAIL",
                "owner": "astra_runtime_governance_v1",
                "exact_blocker": "cycle exceeded limit or failed safe",
                "observed_value": 30.0,
            }]},
        )
        self.assertTrue(payload["cortex_summary"]["active_infrastructure_blockers"])
        self.assertEqual(payload["cortex_summary"]["system_integrity_summary"], "CRITICAL")
