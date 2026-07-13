import tempfile
import unittest

from engine.astra_multilane_activation_v2 import canonical_lane_activation_contract
from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1
from engine.learning_return_integrity_v1 import audit_learning_return_rows
from engine.paper_autopilot import _execution_trace_event, normalize_operational_candidate


class MultiLaneRuntimeWiringContractTests(unittest.TestCase):
    def test_blocked_candidate_trace_keeps_canonical_lineage(self):
        row = normalize_operational_candidate({
            "symbol": "NVDA", "asset_class": "equity", "paper_entry_horizon_style": "day_trade",
            "candidate_source": "cache", "generated_at": "2026-01-01T12:00:00Z",
        })
        trace = _execution_trace_event(row, eligible=False, selected=False, decision_reason="MARKET_CLOSED")
        self.assertEqual(trace["lane_id"], "DAY")
        self.assertTrue(trace["candidate_id"])
        self.assertTrue(trace["recommendation_id"])
        self.assertTrue(trace["canonical_symbol"])
        self.assertTrue(trace["source_record_id"])
        self.assertTrue(trace["ranking_version"])
        self.assertTrue(trace["generated_at"])
        self.assertTrue(trace["expires_at"])
        with tempfile.TemporaryDirectory() as directory:
            result = LaneExecutionTraceLedgerV1(directory).record([trace], cycle_id="cycle-1")
            self.assertEqual(result["appended"], 1)

    def test_session_contract_never_returns_null(self):
        contract = canonical_lane_activation_contract("DAY", env={"ASTRA_DAY_LANE_PILOT_ENABLED": "1", "ASTRA_DAY_LANE_CAPITAL_LIMIT": "100"})
        self.assertEqual(contract["session_state"], "CANDIDATE_DEPENDENT")
        self.assertIsInstance(contract["session_allowed"], bool)
        crypto = canonical_lane_activation_contract("CRYPTO", env={"ASTRA_ENABLE_ALPACA_CRYPTO_PAPER": "0"})
        self.assertEqual(crypto["session_state"], "CRYPTO_24_7_ALLOWED")

    def test_return_audit_separates_replay_and_quarantines_bad_broker_rows(self):
        report = audit_learning_return_rows([
            {"evidence_class": "BROKER_CONFIRMED_COMPLETE", "entry_price": 10, "exit_price": 11, "realized_return": 10},
            {"evidence_class": "REPLAY", "entry_price": 10, "exit_price": 50, "realized_return": 400},
            {"evidence_class": "BROKER_CONFIRMED_COMPLETE", "entry_price": 0, "exit_price": 11, "realized_return": 10},
            {"evidence_class": "BROKER_CONFIRMED_COMPLETE", "entry_price": 10, "exit_price": 11, "realized_return": 1000},
        ])
        self.assertEqual(report["broker_confirmed_eligible_count"], 1)
        self.assertEqual(report["replay_count"], 1)
        self.assertEqual(report["zero_basis_count"], 1)
        self.assertGreaterEqual(report["double_scale_suspect_count"], 1)
        self.assertTrue(report["official_metrics_guarded"])
        self.assertEqual(report["status"], "PASS_WITH_QUARANTINED_LEGACY_ROWS")


if __name__ == "__main__":
    unittest.main()
