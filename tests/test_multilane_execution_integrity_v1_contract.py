import json
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

    def test_ledger_records_terminal_order_rejection_for_selected_candidate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                "lane_id": "DAY", "candidate_id": "candidate-rejected", "recommendation_id": "recommendation-rejected",
                "symbol": "NVDA", "candidate_generated_at": "2026-08-11T00:00:00Z",
                "eligible": True, "selected": True, "order_ready": True,
                "order_result": "rejected", "order_rejection_reason": "BROKER_BUYING_POWER_INSUFFICIENT",
                "order_readiness_reason": "ready_for_existing_paper_order_boundary", "decision_reason": "eligible",
            }
            self.assertEqual(ledger.record([row], cycle_id="cycle-rejected")["appended"], 1)
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["exact_blocker"], "BROKER_BUYING_POWER_INSUFFICIENT")

    def test_ledger_preserves_early_pipeline_blocker_without_order_rejection(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                "lane_id": "DAY", "candidate_id": "candidate-stale", "recommendation_id": "recommendation-stale",
                "symbol": "RIVN", "candidate_generated_at": "2026-08-11T00:00:00Z",
                "eligible": False, "selected": False, "order_ready": False,
                "order_readiness_reason": "STALE_PROVIDER_NATIVE_TIMESTAMP",
                "decision_reason": "candidate_stale",
            }
            ledger.record([row], cycle_id="cycle-stale")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["exact_blocker"], "STALE_PROVIDER_NATIVE_TIMESTAMP")

    def test_ledger_terminal_rejection_beats_generic_eligible_values(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                "lane_id": "DAY", "candidate_id": "candidate-generic", "recommendation_id": "recommendation-generic",
                "symbol": "COST", "candidate_generated_at": "2026-08-11T00:00:00Z",
                "eligible": True, "selected": True, "order_ready": True,
                "order_rejection_reason": "BROKER_ORDER_REJECTED:duplicate_client_order_id",
                "order_readiness_reason": "eligible", "decision_reason": "eligible", "final_blocker_reason": "eligible",
            }
            ledger.record([row], cycle_id="cycle-generic")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["exact_blocker"], "BROKER_ORDER_REJECTED:duplicate_client_order_id")

    def test_reconciled_entry_fill_updates_only_fill_transition_counters(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                "lane_id": "CRYPTO", "position_id": "crypto-position-1", "lifecycle_id": "crypto-position-1",
                "candidate_id": "candidate-1", "recommendation_id": "recommendation-1", "symbol": "ETH/USD",
                "asset_type": "crypto", "entry_order_id": "entry-order-1", "entry_fill_id": "entry-fill-1",
                "entry_filled_at": "2026-08-26T20:20:29Z", "entry_price_verified": True,
                "entry_price_evidence_class": "BROKER_CONFIRMED_FILL", "prior_status": "PENDING_ENTRY",
            }
            self.assertEqual(ledger.record_reconciled_entry_fill(row)["appended"], 1)
            self.assertEqual(ledger.record_reconciled_entry_fill(row)["suppressed"], 1)
            summary = ledger.summary()
            counters = summary["lanes"]["CRYPTO"]
            self.assertEqual(counters["candidates_seen"], 0)
            self.assertEqual(counters["filled_entries"], 1)
            self.assertEqual(counters["open_lane_positions"], 1)
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["event_type"], "BROKER_ENTRY_FILL_RECONCILED")
            self.assertEqual(record["entry_fill_id"], "entry-fill-1")


if __name__ == "__main__":
    unittest.main()
