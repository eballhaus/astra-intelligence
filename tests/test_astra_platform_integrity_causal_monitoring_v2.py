from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.astra_sentinel_causal_handoff_integrity_v1 import (
    classify_causal_handoff_facts_v1,
    collect_platform_integrity_monitors_v2,
)


def iso(offset_seconds: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


class PlatformIntegrityCausalMonitoringV2Tests(unittest.TestCase):
    def test_price_truth_only_flags_current_fresher_divergence(self) -> None:
        matching = collect_platform_integrity_monitors_v2({
            "price_truth_facts": [{"symbol": "GEHC", "producer": "quote", "consumer": "lifecycle", "producer_price": 10.0, "consumer_price": 10.0, "producer_timestamp": iso(), "consumer_timestamp": iso()}],
        })
        self.assertEqual(matching["price_data_truth"]["status"], "PASS")
        self.assertFalse(matching["facts"])

        divergent = collect_platform_integrity_monitors_v2({
            "price_truth_facts": [{"symbol": "GEHC", "producer": "canonical quote", "consumer": "lifecycle", "producer_price": 11.0, "consumer_price": 10.0, "producer_timestamp": iso(), "consumer_timestamp": iso(-120)}],
        })
        classified = classify_causal_handoff_facts_v1(divergent["facts"])
        self.assertEqual(classified["signals"][0]["category"], "CAUSAL_HANDOFF_LOSS")

        ambiguous = collect_platform_integrity_monitors_v2({
            "price_truth_facts": [{"symbol": "GEHC", "producer_price": 11.0, "consumer_price": 10.0}],
        })
        self.assertEqual(ambiguous["nondefects"][0]["category"], "INSUFFICIENT_RUNTIME_EVIDENCE")

        historical = collect_platform_integrity_monitors_v2({
            "price_truth_facts": [{"current": False, "symbol": "GEHC", "producer_price": 11.0, "consumer_price": 10.0, "producer_timestamp": iso(), "consumer_timestamp": iso(-120)}],
        })
        self.assertEqual(classify_causal_handoff_facts_v1(historical["facts"])["nondefects"][0]["category"], "STALE_OR_HISTORICAL_STATE_MISCLASSIFIED_CURRENT")

        deduplicated = collect_platform_integrity_monitors_v2({
            "price_truth_facts": [{"symbol": "GEHC", "producer_price": 11.0, "consumer_price": 10.0, "producer_timestamp": iso(), "consumer_timestamp": iso(-120)}] * 2,
        })
        self.assertEqual(len(deduplicated["facts"]), 1)

    def test_lifecycle_proof_and_horizon_deadline_are_observational(self) -> None:
        partial = collect_platform_integrity_monitors_v2({
            "current_candidate_traces": [{"lane_id": "SCALP", "candidate_id": "c1", "submitted": True, "generated_at": iso()}],
            "broker_positions": [{"symbol": "GEHC", "lane_id": "SCALP"}],
            "entry_lane_horizon_integrity": {"entries": ([{"symbol": "OLD", "lane": "DAY", "stage": "BLOCKED_PRE_SUBMISSION"}] * 25) + [{"symbol": "GEHC", "lane": "SCALP", "stage": "ENTRY_FILLED", "entry_fill_id": "fill-1", "updated_at": iso()}]},
        })
        scalp = partial["lifecycle_proof_deadline"]["lanes"]["SCALP"]
        self.assertEqual(scalp["status"], "PARTIALLY_PROVEN")
        self.assertNotEqual(scalp["highest_naturally_proven_stage"], "STRICT_BROKER_TRUTH")
        self.assertEqual(scalp["first_missing_stage"], "EXIT_DECISION")

        complete = collect_platform_integrity_monitors_v2({
            "broker_truth_records": [{"lane": "SCALP", "lifecycle_id": "life-1", "entry_fill_id": "entry", "exit_fill_id": "exit", "exit_order_id": "sell", "exit_timestamp": iso()}],
            "canonical_lifecycle_lessons": [{"lifecycle_id": "life-1"}],
        })
        self.assertEqual(complete["lifecycle_proof_deadline"]["lanes"]["SCALP"]["status"], "FULL_TRUTH_PROVEN")

        deadline = collect_platform_integrity_monitors_v2({
            "position_lane_horizon_recovery": {"positions": [{"symbol": "GEHC", "lane": "SCALP", "canonical_position_id": "p1", "same_session_exit_required": True, "exit_deadline_at": iso(-1)}]},
            "position_exit_readiness": {"positions": [{"symbol": "GEHC"}]},
        })
        self.assertEqual(classify_causal_handoff_facts_v1(deadline["facts"])["signals"][0]["category"], "HORIZON_DEADLINE_MISSED")

    def test_broker_position_truth_and_dust_are_fail_closed(self) -> None:
        matched = collect_platform_integrity_monitors_v2({
            "broker_position_truth_facts": [{"symbol": "BTC/USD", "field": "quantity", "broker_value": 1, "canonical_value": 1}],
        })
        self.assertEqual(matched["broker_position_execution_truth"]["status"], "PASS")

        mismatch = collect_platform_integrity_monitors_v2({
            "broker_position_truth_facts": [{"symbol": "BTC/USD", "field": "quantity", "broker_value": 1, "canonical_value": 2}],
            "broker_positions": [{"symbol": "BTC/USD", "dust": True, "meaningful_exposure": True}],
        })
        signals = classify_causal_handoff_facts_v1(mismatch["facts"])["signals"]
        self.assertEqual(len(signals), 2)
        self.assertTrue(all(row["category"] == "BROKER_POSITION_TRUTH_MISMATCH" for row in signals))

    def test_resource_provider_distinguishes_transport_from_usable_evidence(self) -> None:
        payload = collect_platform_integrity_monitors_v2({
            "worker_state": {"active_worker_present": True, "ownership_state": "SINGLE_WORKER_ACTIVE", "heartbeat_at": iso(), "resource": {"resource_state": "RESOURCE_NORMAL"}},
            "provider_consumption_telemetry": {"providers": [{"attempted_calls": 2, "successful_calls": 2, "stale_evidence_count": 2, "fresh_usable_evidence_count": 0}]},
        })
        monitor = payload["resource_provider_reliability"]
        self.assertEqual(monitor["transport_success_count"], 2.0)
        self.assertEqual(monitor["fresh_usable_evidence_count"], 0.0)
        self.assertEqual(payload["nondefects"][0]["category"], "LEGITIMATE_FAIL_CLOSED")
        self.assertEqual(payload["provider_calls_used"], 0)

        degraded = collect_platform_integrity_monitors_v2({"worker_state": {"active_worker_present": False, "ownership_state": "NO_WORKER_ACTIVE", "heartbeat_at": iso()}})
        self.assertEqual(classify_causal_handoff_facts_v1(degraded["facts"])["signals"][0]["category"], "RUNTIME_RESOURCE_INTEGRITY_DEGRADED")

    def test_scanner_publishes_compact_v2_section_without_external_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scanner = ContinuousSystemIntegrityScannerV1(Path(directory))
            result = scanner.run_if_due(
                worker_state={"process_role": "PAPER_AUTOPILOT_WORKER", "active_worker_present": True, "ownership_state": "SINGLE_WORKER_ACTIVE", "heartbeat_at": iso(), "worker_generation_id": "g1", "resource_state": "RESOURCE_NORMAL"},
                runtime_state={}, safety={},
                context={"targeted_reasons": ["test"], "price_truth_facts": [{"symbol": "GEHC", "producer_price": 10, "consumer_price": 10, "producer_timestamp": iso(), "consumer_timestamp": iso()}], "get_side_effects": 0},
            )
        monitors = result["platform_integrity_monitors_v2"]
        self.assertEqual(set(monitors).issuperset({"price_data_truth", "lifecycle_proof_deadline", "broker_position_execution_truth", "resource_provider_reliability"}), True)
        self.assertEqual(monitors["provider_calls_used"], 0)
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)


if __name__ == "__main__":
    unittest.main()
