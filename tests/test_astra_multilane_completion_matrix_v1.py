import tempfile
import unittest

from engine.astra_multilane_completion_matrix_v1 import AstraMultilaneCompletionMatrixV1, LANES, STAGES
from engine.paper_autopilot_worker import PaperAutopilotWorker


class MultilaneCompletionMatrixTests(unittest.TestCase):
    def build(self, rows, crypto=None, observations=None, active=None, managed=None, legacy=None):
        with tempfile.TemporaryDirectory() as directory:
            matrix = AstraMultilaneCompletionMatrixV1(directory)
            payload = matrix.build(
                candidate_rows=rows,
                execution_trace={"per_candidate_decision_trace": []},
                crypto_readiness=crypto or {},
                shadow={"lifecycle_evidence_eligibility": {"eligible_by_lane": {}}},
                source_freshness="CURRENT",
                lane_observations=observations or {},
                active_positions_by_lane=active or {},
                managed_capacity_positions_by_lane=managed or {},
                legacy_excluded_positions_by_lane=legacy or {},
            )
            matrix.write(payload)
            return matrix.snapshot()

    def test_all_lanes_and_stages_are_explicit(self):
        payload = self.build([])
        self.assertEqual(set(payload["lanes"]), set(LANES))
        for lane in payload["lanes"].values():
            self.assertEqual(set(lane["stages"]), set(STAGES))
            self.assertEqual(lane["stages"]["candidate_discovery"]["status"], "LEGITIMATE_WAITING")

    def test_crypto_horizon_is_not_forced(self):
        payload = self.build(
            [{"symbol": "GRT/USD", "asset_class": "crypto", "lane_id": "CRYPTO"}],
            {"failed_gates": ["horizon_assignment"]},
        )
        crypto = payload["lanes"]["CRYPTO"]
        self.assertEqual(crypto["first_blocker"], "horizon_assignment")
        self.assertEqual(crypto["horizon_assigned_count"], 0)
        self.assertEqual(crypto["stages"]["horizon_assignment"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(crypto["stages"]["order_ready"]["status"], "BLOCKED_BY_UPSTREAM")

    def test_worker_readiness_blocker_alias_is_consumed(self):
        payload = self.build(
            [{"symbol": "LINK/USD", "asset_class": "crypto"}],
            {"candidate_execution_blockers": ["horizon_assignment"]},
        )
        self.assertEqual(payload["lanes"]["CRYPTO"]["first_blocker"], "horizon_assignment")

    def test_crypto_market_evidence_precedes_downstream_horizon_symptom(self):
        payload = self.build(
            [{
                "symbol": "LINK/USD", "asset_class": "crypto", "lane_id": "CRYPTO",
                "assigned_horizon": "unknown",
                "first_causal_blocker": {"gate": "timestamp_freshness", "status": "REJECTED_STALE_QUOTE"},
            }],
        )
        crypto = payload["lanes"]["CRYPTO"]
        self.assertEqual(crypto["first_blocker"], "timestamp_freshness")
        self.assertEqual(crypto["stages"]["market_data"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(crypto["stages"]["horizon_assignment"]["status"], "BLOCKED_BY_UPSTREAM")
        self.assertNotIn("CRYPTO_HORIZON_EVIDENCE_MISSING", [row["root_cause_id"] for row in payload["repair_manifest"]])

    def test_day_contract_failure_blocks_downstream_without_claiming_runtime_proof(self):
        payload = self.build([{
            "symbol": "AAPL", "asset_class": "equity", "lane_id": "DAY",
            "first_failing_gate": "CONTRACT_INCOMPLETE", "order_blocker": "market is closed",
        }])
        day = payload["lanes"]["DAY"]
        self.assertEqual(day["first_blocker"], "CONTRACT_INCOMPLETE")
        self.assertEqual(day["stages"]["horizon_assignment"]["status"], "BLOCKED_BY_UPSTREAM")
        self.assertEqual(day["stages"]["paper_order"]["status"], "RUNTIME_NOT_EXERCISED")

    def test_partial_lane_observation_is_not_misreported_as_no_opportunity(self):
        payload = self.build([], observations={
            "DAY": {
                "observation_state": "CURRENT_PARTIAL_EVALUATION",
                "observation_scope": "bounded_candidate_integrity_only",
                "candidate_count": 3,
                "fresh_candidate_count": 2,
                "preliminary_eligible_candidate_count": 2,
                "first_causal_blocker": "CONTRACT_INCOMPLETE",
                "exact_blocker_reason": "missing lifecycle contract fields",
            },
            "SWING": {"observation_state": "NOT_EVALUATED_THIS_PARTIAL_CYCLE"},
        })
        day = payload["lanes"]["DAY"]
        self.assertEqual(day["candidate_count"], 3)
        self.assertEqual(day["eligible_candidate_count"], 0)
        self.assertEqual(day["preliminary_eligible_candidate_count"], 2)
        self.assertEqual(day["first_blocker"], "CONTRACT_INCOMPLETE")
        self.assertEqual(day["candidate_observation_scope"], "bounded_candidate_integrity_only")
        self.assertEqual(payload["lanes"]["SWING"]["first_blocker"], "CANDIDATE_OBSERVATION_PENDING")

    def test_evaluated_gate_attribution_precedes_legacy_crypto_alias(self):
        payload = self.build([{
            "symbol": "UNI/USD", "asset_class": "crypto", "lane_id": "CRYPTO",
            "first_causal_blocker": {"gate": "lane_activation", "status": "PENDING_LANE_ACTIVATION"},
            "eligibility_gate_attribution_v1": {
                "first_failing_gate": {
                    "code": "CONFIDENCE_BELOW_THRESHOLD",
                    "input_value": "entry_commitment_below_threshold",
                    "validity": "VALID_STRATEGY_REJECTION",
                },
            },
        }])
        crypto = payload["lanes"]["CRYPTO"]
        self.assertEqual(crypto["first_blocker"], "CONFIDENCE_BELOW_THRESHOLD")
        self.assertEqual(crypto["stages"]["eligibility"]["status"], "VALID_STRATEGY_REJECTION")
        self.assertEqual(crypto["first_blocker_validity"], "VALID_STRATEGY_REJECTION")

    def test_worker_projection_preserves_preexecution_guard_but_uses_final_candidate_gate(self):
        class FakeAutopilot:
            def _current_execution_capacities(self):
                return {"stock_capacity": 1, "crypto_capacity": 1, "total_capacity": 1}

            def _candidate_trace_row(self, row, **_kwargs):
                return ({
                    "eligibility_gate_attribution_v1": {
                        "first_failing_gate": {
                            "code": "CONFIDENCE_BELOW_THRESHOLD",
                            "validity": "VALID_STRATEGY_REJECTION",
                        },
                    },
                }, False, "entry_commitment_below_threshold", {})

        worker = object.__new__(PaperAutopilotWorker)
        worker.autopilot = FakeAutopilot()
        projected = worker._canonical_crypto_matrix_candidates(
            candidate_rows=[{
                "symbol": "UNI/USD", "asset_class": "crypto", "entry_commitment": 90,
                "candidate_generated_at": "2026-07-25T00:00:00Z",
            }],
            evaluated_rows=[{
                "symbol": "UNI/USD", "first_causal_blocker": {
                    "gate": "lane_activation", "status": "PENDING_LANE_ACTIVATION",
                },
            }],
            capacity_snapshot={"broker_positions_fetch_ok": True},
            open_symbols=set(),
        )
        self.assertEqual(projected[0]["pre_execution_integrity_blocker"]["gate"], "lane_activation")
        self.assertEqual(
            projected[0]["eligibility_gate_attribution_v1"]["first_failing_gate"]["code"],
            "CONFIDENCE_BELOW_THRESHOLD",
        )

    def test_worker_preserves_preexecution_crypto_blocker_without_final_contract_inputs(self):
        class FakeAutopilot:
            def _current_execution_capacities(self):
                return {"stock_capacity": 1, "crypto_capacity": 1, "total_capacity": 1}

            def _candidate_trace_row(self, *_args, **_kwargs):
                raise AssertionError("pre-execution evidence must not enter final qualification")

        worker = object.__new__(PaperAutopilotWorker)
        worker.autopilot = FakeAutopilot()
        projected = worker._canonical_crypto_matrix_candidates(
            candidate_rows=[{"symbol": "DOGE/USD", "asset_class": "crypto"}],
            evaluated_rows=[{
                "symbol": "DOGE/USD", "first_causal_blocker": {
                    "gate": "timestamp_freshness", "status": "REJECTED_STALE_QUOTE",
                },
            }],
            capacity_snapshot={"broker_positions_fetch_ok": True},
            open_symbols=set(),
        )
        self.assertEqual(projected[0]["canonical_execution_projection_owner"], "PRE_EXECUTION_INTEGRITY_ONLY")
        self.assertEqual(projected[0]["pre_execution_integrity_blocker"]["gate"], "timestamp_freshness")

    def test_broker_active_positions_are_not_hidden_by_legacy_capacity_exclusion(self):
        payload = self.build(
            [],
            active={"SWING": 39},
            managed={"SWING": 2},
            legacy={"SWING": 37},
        )
        swing = payload["lanes"]["SWING"]
        self.assertEqual(swing["active_positions"], 39)
        self.assertEqual(swing["managed_capacity_positions"], 2)
        self.assertEqual(swing["legacy_unlinked_positions_excluded_from_learning_capacity"], 37)

    def test_matrix_snapshot_is_read_only_and_bounded(self):
        rows = [{"symbol": f"X{i}/USD", "asset_class": "crypto"} for i in range(400)]
        payload = self.build(rows, {"failed_gates": ["horizon_assignment"]})
        self.assertLessEqual(payload["resource_usage"]["rows_read"], 300)
        self.assertEqual(payload["provider_calls_from_get"], 0)
        self.assertEqual(payload["broker_actions_from_get"], 0)
        self.assertEqual(payload["state_mutations_from_get"], 0)


if __name__ == "__main__":
    unittest.main()
