import tempfile
import unittest

from engine.astra_multilane_completion_matrix_v1 import AstraMultilaneCompletionMatrixV1, LANES, STAGES


class MultilaneCompletionMatrixTests(unittest.TestCase):
    def build(self, rows, crypto=None):
        with tempfile.TemporaryDirectory() as directory:
            matrix = AstraMultilaneCompletionMatrixV1(directory)
            payload = matrix.build(
                candidate_rows=rows,
                execution_trace={"per_candidate_decision_trace": []},
                crypto_readiness=crypto or {},
                shadow={"lifecycle_evidence_eligibility": {"eligible_by_lane": {}}},
                source_freshness="CURRENT",
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

    def test_matrix_snapshot_is_read_only_and_bounded(self):
        rows = [{"symbol": f"X{i}/USD", "asset_class": "crypto"} for i in range(400)]
        payload = self.build(rows, {"failed_gates": ["horizon_assignment"]})
        self.assertLessEqual(payload["resource_usage"]["rows_read"], 300)
        self.assertEqual(payload["provider_calls_from_get"], 0)
        self.assertEqual(payload["broker_actions_from_get"], 0)
        self.assertEqual(payload["state_mutations_from_get"], 0)


if __name__ == "__main__":
    unittest.main()
