from __future__ import annotations

import tempfile
import unittest

from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.astra_sentinel_causal_handoff_integrity_v1 import (
    classify_causal_handoff_facts_v1,
    collect_platform_integrity_monitors_v2,
)


class SentinelCausalHandoffIntegrityTests(unittest.TestCase):
    def _classify(self, *facts):
        return classify_causal_handoff_facts_v1(list(facts))

    def test_produced_entry_edge_dropped_is_causal_handoff_loss(self):
        result = self._classify({
            "producer": "ranking_feedback_profile", "consumer": "entry_commitment_gate",
            "field": "entry_edge_score", "producer_value_available": True,
            "consumer_value": None, "current": True,
        })
        self.assertEqual(result["signals"][0]["category"], "CAUSAL_HANDOFF_LOSS")

    def test_persona_placeholder_used_as_measured_is_shadowing(self):
        result = self._classify({
            "kind": "PLACEHOLDER_SHADOWING", "producer": "persona normalization",
            "consumer": "entry_commitment_gate", "field": "persona_disagreement_index",
            "placeholder_used_as_measured": True,
        })
        self.assertEqual(result["signals"][0]["category"], "PLACEHOLDER_OR_DEFAULT_SHADOWING")

    def test_accepted_refresh_replaced_by_original_row_is_causal_handoff_loss(self):
        result = self._classify({
            "kind": "POST_REFRESH_ROW_REPLACED", "producer": "final quote refresh",
            "consumer": "_open_position_from_row", "field": "provider_native_timestamp",
            "refreshed_evidence_replaced": True,
        })
        self.assertEqual(result["signals"][0]["category"], "CAUSAL_HANDOFF_LOSS")

    def test_missing_downside_is_producer_evidence_missing_not_handoff_loss(self):
        result = self._classify({
            "kind": "PRODUCER_MISSING", "producer": "risk envelope producer",
            "consumer": "pretrade contract", "field": "expected_downside_range",
        })
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["nondefects"][0]["category"], "PRODUCER_EVIDENCE_MISSING")

    def test_nonpositive_completed_bar_forecast_is_legitimate_fail_closed(self):
        result = self._classify({"kind": "FORECAST_NOT_POSITIVE", "field": "expected_return_range"})
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["nondefects"][0]["category"], "LEGITIMATE_FAIL_CLOSED")

    def test_stale_native_quote_is_legitimate_fail_closed(self):
        result = self._classify({"kind": "STALE_NATIVE_QUOTE", "field": "provider_native_timestamp"})
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["nondefects"][0]["category"], "LEGITIMATE_FAIL_CLOSED")

    def test_historical_record_cannot_be_reported_as_current_defect(self):
        result = self._classify({"kind": "HISTORICAL", "current": False, "field": "entry_edge_score"})
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["nondefects"][0]["category"], "STALE_OR_HISTORICAL_STATE_MISCLASSIFIED_CURRENT")

    def test_dead_worker_lease_is_a_causal_runtime_defect(self):
        result = self._classify({
            "kind": "WORKER_LEASE", "lease_state": "STALE_DEAD_LEASE",
            "producer": "PaperAutopilotWorker.run", "consumer": "WorkerLease.acquire",
        })
        self.assertEqual(result["signals"][0]["kind"], "WORKER_LEASE_PROCESS_OWNERSHIP_CONTRADICTION")

    def test_live_matching_worker_lease_is_not_a_defect(self):
        result = self._classify({"kind": "WORKER_LEASE", "lease_state": "ACTIVE_MATCHING_LEASE"})
        self.assertEqual(result["signals"], [])

    def test_worker_cached_broker_fill_pending_close_is_a_causal_handoff_loss(self):
        monitors = collect_platform_integrity_monitors_v2({
            "native_lane_exit_lifecycle": {
                "life-1": {
                    "lifecycle_id": "life-1", "symbol": "LYFT", "lane_id": "DAY",
                    "closure_state": "AWAITING_BROKER_ZERO",
                },
            },
            "authorized_lane_exit_pending": {
                "exit-1": {"position_id": "life-1", "last_order_status": "filled_awaiting_broker_zero"},
            },
        })
        fact = next(row for row in monitors["facts"] if row["kind"] == "BROKER_FILLED_CLOSURE_PENDING")
        result = self._classify(fact)
        self.assertEqual(result["signals"][0]["category"], "CAUSAL_HANDOFF_LOSS")

    def test_worker_cached_scalp_deadline_quote_blocker_surfaces_without_submission(self):
        monitors = collect_platform_integrity_monitors_v2({
            "native_lane_exit_lifecycle": {
                "life-2": {
                    "lifecycle_id": "life-2", "symbol": "GEHC", "lane_id": "SCALP",
                    "closure_state": "EXIT_BLOCKED_EVIDENCE",
                    "exact_blocker": "STALE_PROVIDER_NATIVE_TIMESTAMP",
                    "deadline_requirement_status": "SAME_SESSION_DEADLINE_PASSED",
                },
            },
        })
        fact = next(row for row in monitors["facts"] if row["kind"] == "HORIZON_DEADLINE_MISSED")
        self.assertEqual(fact["consumer_state"], "STALE_PROVIDER_NATIVE_TIMESTAMP")

    def test_scanner_publishes_bounded_causal_root_to_existing_sentinel_path(self):
        with tempfile.TemporaryDirectory() as directory:
            scanner = ContinuousSystemIntegrityScannerV1(directory)
            payload = scanner.run_if_due(
                worker_state={"active_worker_present": True, "process_role": "PAPER_AUTOPILOT_WORKER"},
                runtime_state={}, safety={},
                context={"causal_handoff_facts": [{
                    "producer": "ranking_feedback_profile", "consumer": "entry_commitment_gate",
                    "field": "entry_edge_score", "producer_value_available": True,
                    "consumer_value": None, "current": True,
                }]},
            )
            root = next(row for row in payload["active_root_causes"] if row["category"] == "CAUSAL_HANDOFF_LOSS")
            self.assertEqual(root["causal_handoff_integrity_v1"]["field"], "entry_edge_score")
            self.assertEqual(payload["causal_handoff_integrity_v1"]["provider_calls_used"], 0)


if __name__ == "__main__":
    unittest.main()
