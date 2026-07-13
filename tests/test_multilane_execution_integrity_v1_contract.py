import unittest

from engine.astra_multilane_activation_v2 import canonical_lane_activation_contract
from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1


class MultilaneExecutionIntegrityV1ContractTests(unittest.TestCase):
    def test_day_uses_pilot_switch_and_rejects_legacy_disagreement(self):
        env = {
            "ASTRA_DAY_LANE_PILOT_ENABLED": "1",
            "ASTRA_DAY_LEARNING_LANE_ENABLED": "0",
            "ASTRA_DAY_LANE_CAPITAL_LIMIT": "15000",
        }
        contract = canonical_lane_activation_contract("DAY", env)
        self.assertFalse(contract["lane_enabled"])
        self.assertFalse(contract["execution_enabled"])
        self.assertIn("LEGACY_DAY_SWITCH_CONFLICT", contract["exact_blockers"])

    def test_day_can_enable_without_legacy_switch_when_all_safety_inputs_pass(self):
        env = {"ASTRA_DAY_LANE_PILOT_ENABLED": "1", "ASTRA_DAY_LANE_CAPITAL_LIMIT": "15000"}
        safety = {
            "paper_mode_verified": True,
            "broker_execution_enabled": True,
            "paper_endpoint_verified": True,
            "live_endpoint_rejected": True,
        }
        contract = canonical_lane_activation_contract("DAY", env, broker_safety=safety)
        self.assertTrue(contract["lane_enabled"])
        self.assertTrue(contract["execution_enabled"])
        self.assertEqual(contract["legacy_switch_status"], "LEGACY_UNSET_COMPATIBLE")

    def test_broker_live_endpoint_allowed_false_is_a_valid_rejection_alias(self):
        env = {"ASTRA_DAY_LANE_PILOT_ENABLED": "1", "ASTRA_DAY_LANE_CAPITAL_LIMIT": "15000"}
        contract = canonical_lane_activation_contract(
            "DAY",
            env,
            broker_safety={
                "paper_mode_verified": True,
                "broker_execution_enabled": True,
                "paper_endpoint_verified": True,
                "broker_live_endpoint_allowed": False,
            },
        )
        self.assertTrue(contract["live_endpoint_rejected"])
        self.assertTrue(contract["execution_enabled"])

    def test_compact_ledger_deduplicates_without_scanning_candidate_ledger(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                "lane_id": "DAY", "candidate_id": "candidate-1", "recommendation_id": "recommendation-1",
                "symbol": "NVDA", "candidate_generated_at": "2026-07-13T00:00:00Z", "eligible": True,
                "selected": True, "order_ready": True,
            }
            self.assertEqual(ledger.record([row], cycle_id="cycle-1")["appended"], 1)
            self.assertEqual(ledger.record([row], cycle_id="cycle-1")["suppressed"], 1)
            summary = ledger.summary()
            self.assertTrue(summary["bounded_summary_read"])
            self.assertEqual(summary["lanes"]["DAY"]["order_ready"], 1)


if __name__ == "__main__":
    unittest.main()
