import tempfile
import unittest
from pathlib import Path

from engine.astra_continuous_governance_v1 import ContinuousGovernanceV1, dependency_graph, remediation_registry


def worker_state():
    return {
        "active_worker_present": True,
        "process_id": 1,
        "worker_instance_id": "worker-test",
        "worker_generation_id": "generation-test",
        "process_role": "PAPER_AUTOPILOT_WORKER",
        "heartbeat_at": "2026-07-17T00:00:00Z",
        "resource_state": "RESOURCE_NORMAL",
        "resource": {"logical_cpu_count": 6, "normalized_load_1m": 0.3},
        "resource_policy": {"resource_state": "RESOURCE_NORMAL"},
        "limits": {},
    }


def runtime(*, review=True, scheduled=False, momentum=False):
    activation_id = "activation-nvda"
    daily = {
        "record_id": "daily-nvda", "symbol": "NVDA", "asset_class": "equity",
        "lane": "LEGACY_SWING", "strategy": "legacy_swing", "horizon": "swing",
        "quality_state": "CURRENT_SUFFICIENT", "records_valid": 20, "required_completed_bars": 15,
    }
    reviews = {}
    if review:
        reviews[activation_id] = {
            "symbol": "NVDA", "asset_class": "equity", "lane": "LEGACY_SWING",
            "strategy": "legacy_swing", "horizon": "swing", "eligibility": True,
            "required_evidence": {"MOMENTUM": {"status": "CURRENT" if momentum else "MISSING"}},
        }
    return {
        "legacy_forward_activations": {activation_id: {"symbol": "NVDA", "lane": "LEGACY_SWING", "strategy": "legacy_swing", "horizon": "swing"}},
        "legacy_swing_canary": {"market_records": {activation_id: {"HISTORICAL_BARS_DAILY": daily}}, "reviews": reviews},
        "legacy_swing_market_activity": {"scheduler": {"per_symbol": {activation_id: {"scheduled": True}} if scheduled else {}}},
    }


SAFETY = {"paper_mode_verified": True, "broker_live_endpoint_allowed": False}


class ContinuousGovernanceTests(unittest.TestCase):
    def test_dependency_graph_and_registry_are_explicit_and_safe(self):
        edges = dependency_graph()
        self.assertGreaterEqual(len(edges), 14)
        self.assertTrue(all(edge["canonical_identity_key"] for edge in edges))
        registry = remediation_registry()
        self.assertIn("REQUEUE_ELIGIBLE_LIFECYCLE_REVIEW", registry)
        self.assertTrue(all(row["trading_policy_change"] is False for row in registry.values()))

    def test_proof_case_stops_at_legitimate_waiting_without_fabrication(self):
        with tempfile.TemporaryDirectory() as directory:
            governance = ContinuousGovernanceV1(directory)
            result = governance.run_worker_cycle(worker_state=worker_state(), runtime_state=runtime(review=False), safety=SAFETY)
        campaign = result["current_campaign"]
        self.assertEqual(campaign["first_causal_blocker"], "NO_CURRENT_ELIGIBLE_BROKER_LIFECYCLE_REVIEW")
        self.assertEqual(campaign["final_state"], "LEGITIMATE_WAITING_STATE")
        self.assertEqual(result["repairs_executed"], 0)
        self.assertEqual(result["proof_rows"][0]["momentum_state"], "NOT_CURRENT")

    def test_unambiguous_eligible_review_is_requeued_once_with_existing_budget(self):
        runtime_state = runtime(review=True, scheduled=False, momentum=False)
        with tempfile.TemporaryDirectory() as directory:
            governance = ContinuousGovernanceV1(directory)
            result = governance.run_worker_cycle(worker_state=worker_state(), runtime_state=runtime_state, safety=SAFETY)
            snapshot = governance.snapshot()
        campaign = result["current_campaign"]
        activation = runtime_state["legacy_forward_activations"]["activation-nvda"]
        self.assertEqual(campaign["selected_remediation"], "REQUEUE_ELIGIBLE_LIFECYCLE_REVIEW")
        self.assertEqual(campaign["final_state"], "SAFE_BOUNDED_BACKLOG")
        self.assertEqual(result["repairs_executed"], 1)
        self.assertGreaterEqual(activation["refresh_priority"], 100)
        self.assertIn("REQUEUE_ELIGIBLE_LIFECYCLE_REVIEW", activation["governance_tasks"])
        self.assertEqual(snapshot["campaign_count"], 1)

    def test_ambiguous_or_unsafe_repair_fails_closed(self):
        runtime_state = runtime(review=True, scheduled=False)
        runtime_state["legacy_swing_canary"]["reviews"]["activation-nvda"]["lane"] = "DAY"
        with tempfile.TemporaryDirectory() as directory:
            result = ContinuousGovernanceV1(directory).run_worker_cycle(worker_state=worker_state(), runtime_state=runtime_state, safety=SAFETY)
        self.assertEqual(result["current_campaign"]["final_state"], "UNSAFE_OR_AMBIGUOUS_FAIL_CLOSED")
        self.assertEqual(result["repairs_executed"], 0)

    def test_read_snapshot_is_pure_and_campaign_store_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            governance = ContinuousGovernanceV1(directory)
            before = list(Path(directory).iterdir())
            snapshot = governance.snapshot()
            after = list(Path(directory).iterdir())
            self.assertEqual(before, after)
            self.assertEqual(snapshot["status"], "AWAITING_WORKER_SCAN")
            governance.run_worker_cycle(worker_state=worker_state(), runtime_state=runtime(review=False), safety=SAFETY)
            self.assertTrue(governance.campaign_path.exists())
            self.assertTrue(governance.summary_path.exists())


if __name__ == "__main__":
    unittest.main()
