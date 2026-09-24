import json
import unittest

from engine.astra_continuous_system_integrity_scanner_v1 import resource_efficiency_monitor_v1
from engine.paper_autopilot import (
    _compact_runtime_cycle_summary_v1,
    _compact_runtime_execution_trace_v1,
    _compact_runtime_large_payload_v1,
)


class RuntimePayloadMemoryV1Tests(unittest.TestCase):
    def _payloads(self):
        positions = [
            {
                "symbol": f"SYM{i}",
                "final_advisory": "WATCH" if i else "REVIEW",
                "priority": "HIGH" if i == 0 else "MEDIUM",
                "first_causal_blocker": "EVIDENCE_MISSING" if i < 2 else "",
            }
            for i in range(32)
        ]
        return {
            "position_evidence_completeness_v1": {
                "schema_version": "astra_position_evidence_completeness_v1",
                "broker_position_count": 32,
                "positions_represented": 32,
                "fresh_quote_count": 20,
                "fresh_completed_bar_count": 10,
                "first_missing_producer_count": 4,
                "positions": [{"symbol": f"SYM{i}", "first_missing_producer": "BAR_STALE"} for i in range(32)],
            },
            "unified_position_advisory_v1": {
                "schema_version": "astra_unified_position_advisory_v1",
                "broker_position_count": 32,
                "advisory_count": 32,
                "positions": positions,
            },
            "provider_consumption_telemetry_v1": {
                "schema_version": "astra_provider_consumption_telemetry_v1",
                "provider_calls_used": 10,
                "provider_count": 1,
                "endpoint_families": [{"endpoint_family": "quote", "attempted": 10, "successful": 8}],
            },
            "fmp_production_verification_v1": {
                "schema_version": "astra_fmp_production_verification_v1",
                "symbol": "AAPL",
                "attempted_count": 2,
                "successful_count": 1,
                "failed_count": 1,
                "endpoint_families": {"profile": {"status": "SUCCESS"}},
            },
        }

    def test_compact_projection_preserves_contract_without_nested_rows(self):
        payloads = self._payloads()
        for owner, payload in payloads.items():
            original = json.dumps(payload, sort_keys=True)
            summary = _compact_runtime_large_payload_v1(payload, owner)
            self.assertTrue(summary["full_payload_persisted"])
            self.assertNotIn("positions", summary)
            if owner in {"position_evidence_completeness_v1", "unified_position_advisory_v1"}:
                self.assertLess(len(json.dumps(summary)), len(original))
            self.assertEqual(json.dumps(payload, sort_keys=True), original)

    def test_runtime_trace_and_cycle_summary_are_bounded_and_idempotent(self):
        payloads = self._payloads()
        trace = {**payloads, "per_candidate_decision_trace": [{"symbol": "A", "decision": "HOLD"}]}
        compact_trace = _compact_runtime_execution_trace_v1(trace)
        compact_again = _compact_runtime_execution_trace_v1(compact_trace)
        self.assertNotIn("positions", compact_trace["unified_position_advisory_v1"])
        self.assertEqual(compact_trace, compact_again)

        summary = _compact_runtime_cycle_summary_v1({**payloads, "orders_submitted": 0})
        self.assertNotIn("positions", summary["position_evidence_completeness_v1"])
        self.assertEqual(summary, _compact_runtime_cycle_summary_v1(summary))

    def test_resource_monitor_exposes_payload_metrics_without_authority_change(self):
        result = resource_efficiency_monitor_v1(
            {
                "resource": {
                    "resource_state": "RESOURCE_NORMAL",
                    "worker_process": {"memory_mb": 512, "cpu_percent": 4},
                    "resource_memory_telemetry_v1": {
                        "top_memory_owners": [],
                        "large_payload_bytes_by_owner": {"unified_position_advisory_v1": 123},
                        "large_payload_builds_per_cycle": {"unified_position_advisory_v1": 1},
                        "large_payload_serializations_per_cycle": {"unified_position_advisory_v1": 1},
                        "runtime_state_large_payload_count": 4,
                        "worker_snapshot_bytes": 456,
                        "server_state_cache_bytes": 123,
                    },
                },
                "cycle_timing_v1": {"latest": {"total_seconds": 1.0}},
            }
        )
        current = result["samples"][0]
        self.assertEqual(current["runtime_state_large_payload_count"], 4)
        self.assertEqual(current["worker_snapshot_bytes"], 456)
        self.assertTrue(result["paper_only_preserved"])
        self.assertTrue(result["truth_lifecycle_reconciliation_changed"] is False)

if __name__ == "__main__":
    unittest.main()
