import tempfile
import unittest
from pathlib import Path

from engine.astra_governance_coverage_consolidation_v1 import (
    COMPONENT_ID,
    CRYPTO_COMPONENT_ID,
    REQUIRED_CONTRACT_FIELDS,
    AstraGovernanceCoverageConsolidationV1,
    component_registry,
    continuous_governance_contract,
    crypto_lane_contract,
)


def continuous_snapshot():
    return {
        "status": "PASS_AUTONOMOUS_REMEDIATION_WITH_BOUNDED_BACKLOG",
        "scan_time": "2026-07-17T12:00:00Z",
        "authorization": "AUTO_REMEDIATION_AUTHORIZED",
        "invariants_passed": 3,
        "invariants_warned": 1,
        "invariants_failed": 0,
        "active_campaigns": 0,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
        "dependency_graph": [{"edge_id": "evidence.review"}],
        "invariants": [{
            "invariant_id": "OPEN_POSITION_HAS_ONE_CANONICAL_LIFECYCLE",
            "owner": "PaperAutopilot",
            "state": "LEGITIMATE_WAITING_STATE",
            "repairability": "LEGITIMATE_WAITING",
            "exact_blocker": "no_current_eligible_broker_lifecycle_review",
        }],
        "current_campaign": {"campaign_id": "campaign-1", "first_causal_blocker": "NO_CURRENT_ELIGIBLE_BROKER_LIFECYCLE_REVIEW"},
        "repairs_verified": 0,
    }


class GovernanceCoverageConsolidationTests(unittest.TestCase):
    def test_registry_covers_every_required_domain_once(self):
        domains = [item["domain"] for item in component_registry()]
        required = {"RUNTIME", "PROCESSES", "RESOURCES", "PROVIDERS", "STORAGE", "INDEXES", "EVIDENCE", "RETRIEVAL", "LANES", "THROUGHPUT", "HORIZONS", "LIFECYCLES", "CORTEX", "COPILOT", "BROKER", "RECONCILIATION", "TRUTH", "LEARNING", "REMEDIATION", "SYSTEM_INTEGRITY", "SECURITY_AND_SAFETY", "UPGRADE_GOVERNANCE"}
        self.assertEqual(set(domains), required)
        self.assertEqual(len(domains), len(set(domains)))

    def test_complete_contract_is_admitted_and_certified_without_shortcut(self):
        with tempfile.TemporaryDirectory() as directory:
            governance = AstraGovernanceCoverageConsolidationV1(directory)
            result = governance.run_worker_cycle(continuous=continuous_snapshot(), runtime={"resource_state": "RESOURCE_NORMAL"}, preflight={"paper_mode_verified": True, "broker_live_endpoint_allowed": False})
            contract = result["upgrade_contracts"][0]
            self.assertEqual(contract["component_id"], COMPONENT_ID)
            self.assertEqual(contract["admission"]["admission_state"], "ADMISSION_APPROVED_FOR_SHADOW")
            self.assertEqual(contract["certification"]["certification_state"], "CERTIFIED_WITH_BOUNDED_WARNINGS")
            transitions = contract["lifecycle_transitions"]
            self.assertEqual(transitions[0]["from"], "DISCOVER")
            self.assertEqual(transitions[0]["to"], "BASELINE")
            self.assertTrue(any(row["to"] == "SHADOW_VALIDATION" for row in transitions))
            self.assertEqual(contract["lifecycle_state"], "ACTIVE_WITH_HEIGHTENED_OVERSIGHT")

    def test_missing_contract_field_blocks_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            governance = AstraGovernanceCoverageConsolidationV1(directory)
            contract = continuous_governance_contract()
            contract["rollback_procedure"] = ""
            admission = governance._admission(contract, {"governance_status": "healthy", "invariants_failed": 0, "paper_mode_verified": True, "broker_live_endpoint_allowed": False})
            self.assertEqual(admission["admission_state"], "ADMISSION_BLOCKED_MISSING_CONTRACT")
            self.assertIn("rollback_procedure", admission["missing_contract_fields"])

    def test_warning_waiting_is_classified_and_does_not_block_certification(self):
        with tempfile.TemporaryDirectory() as directory:
            result = AstraGovernanceCoverageConsolidationV1(directory).run_worker_cycle(continuous=continuous_snapshot(), runtime={}, preflight={"paper_mode_verified": True, "broker_live_endpoint_allowed": False})
            warning = result["warning_classification"][0]
            self.assertIn(warning["classification"], {"EXPECTED_WAITING", "MARKET_CLOSED_WAITING"})
            self.assertIn("escalate", warning["escalation_rule"])
            self.assertNotEqual(result["status"], "FAIL_WITH_EXACT_BLOCKER")

    def test_snapshot_is_read_only_and_isolation_is_component_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            governance = AstraGovernanceCoverageConsolidationV1(directory)
            governance.run_worker_cycle(continuous=continuous_snapshot(), runtime={}, preflight={"paper_mode_verified": True, "broker_live_endpoint_allowed": False})
            path = Path(directory) / "astra_governance_coverage_consolidation_v1.json"
            before = path.read_bytes()
            snapshot = governance.snapshot()
            self.assertTrue(snapshot["get_route_read_only"])
            self.assertEqual(before, path.read_bytes())
            isolated = governance.isolate_component(COMPONENT_ID, reason="deterministic test regression", deterministic_attribution=True)
            self.assertEqual(isolated["state"], "AUTO_ISOLATION_COMPLETE")
            self.assertFalse(governance.component_enabled(COMPONENT_ID))
            self.assertTrue(isolated["canonical_evidence_preserved"])

    def test_contract_schema_is_complete(self):
        contract = continuous_governance_contract()
        self.assertEqual([key for key in REQUIRED_CONTRACT_FIELDS if key not in contract or contract.get(key) in (None, "")], [])

    def test_existing_crypto_lane_is_admitted_for_shadow_without_forcing_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            result = AstraGovernanceCoverageConsolidationV1(directory).run_worker_cycle(
                continuous=continuous_snapshot(), runtime={},
                preflight={"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
                crypto={"activation": {"capital_configured": True, "capability": {"paper_mode_verified": True, "live_endpoint_detected": False, "crypto_trading_supported": True, "tradable_pairs": ["BTC/USD"]}},
                        "natural_candidate_count": 0, "cached_candidate_count": 1, "lineage_isolated": True},
            )
            contract = next(row for row in result["upgrade_contracts"] if row["component_id"] == CRYPTO_COMPONENT_ID)
            self.assertEqual(contract["admission"]["admission_state"], "ADMISSION_APPROVED_FOR_SHADOW")
            self.assertEqual(contract["certification"]["shadow_validation_state"], "SHADOW_PASS_NO_NATURAL_CANDIDATE")
            self.assertEqual(contract["lifecycle_state"], "SHADOW_VALIDATION")
            self.assertEqual(contract["certification"]["broker_orders"], 0)

    def test_crypto_contract_blocks_missing_separate_capital(self):
        contract = crypto_lane_contract()
        with tempfile.TemporaryDirectory() as directory:
            governance = AstraGovernanceCoverageConsolidationV1(directory)
            admission, certification, _state = governance._crypto_admission_and_certification(
                contract, {}, {"activation": {"capital_configured": False, "capability": {}}, "natural_candidate_count": 0, "lineage_isolated": True}
            )
        self.assertEqual(admission["admission_state"], "ADMISSION_BLOCKED_CAPITAL")
        self.assertEqual(certification["certification_state"], "CERTIFICATION_BLOCKED")


if __name__ == "__main__":
    unittest.main()
