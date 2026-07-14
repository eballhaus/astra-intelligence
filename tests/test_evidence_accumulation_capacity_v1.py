import unittest
import tempfile
import json
import os
import pathlib
import tempfile
from unittest.mock import patch

from engine.astra_evidence_accumulation_capacity_v1 import (
    build_capacity_snapshot,
    candidate_capacity_decision,
)
from engine.astra_portfolio_capacity_release_review_v1 import build_portfolio_release_review
from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1
from engine.paper_autopilot import PaperAutopilotEngine


BASE_ENV = {
    "ASTRA_DAY_EVIDENCE_RESERVE_ENABLED": "1",
    "ASTRA_DAY_EVIDENCE_CAPITAL_LIMIT": "15000",
    "ASTRA_DAY_EVIDENCE_POSITION_LIMIT": "1",
    "ASTRA_CRYPTO_EVIDENCE_RESERVE_ENABLED": "1",
    "ASTRA_CRYPTO_EVIDENCE_CAPITAL_LIMIT": "10000",
    "ASTRA_CRYPTO_EVIDENCE_POSITION_LIMIT": "1",
    "ASTRA_DAY_LANE_PILOT_ENABLED": "1",
    "ASTRA_ENABLE_ALPACA_CRYPTO_PAPER": "1",
}


def snapshot(*, positions=None, fresh=True, risk=True):
    return build_capacity_snapshot(
        broker_snapshot={
            "broker_reconciliation_active": True,
            "broker_positions_fetch_ok": fresh,
            "broker_state_age_seconds": 0 if fresh else 300,
        },
        account_snapshot={"buying_power": 50000, "equity": 50000, "cash": 50000},
        open_positions=positions or [],
        env=BASE_ENV,
        global_position_limit=10,
        global_risk_allowed=risk,
    )


class EvidenceAccumulationCapacityContractTests(unittest.TestCase):

    def test_legacy_trace_summary_gets_new_capacity_counters(self):
        with tempfile.TemporaryDirectory() as state_dir:
            ledger = LaneExecutionTraceLedgerV1(state_dir=state_dir)
            legacy = ledger._empty_summary()
            for lane in legacy["lanes"].values():
                lane.pop("allowed_by_lane_reserve", None)
                lane.pop("reserve_order_ready_count", None)
            with open(ledger.summary_path, "w", encoding="utf-8") as handle:
                json.dump(legacy, handle)
            summary = ledger._read_summary()
            self.assertEqual(summary["lanes"]["DAY"]["allowed_by_lane_reserve"], 0)
            self.assertEqual(summary["lanes"]["CRYPTO"]["reserve_order_ready_count"], 0)
    def test_day_reserve_allows_full_global_account(self):
        positions = [{"symbol": f"S{i}", "lane_id": "SWING", "market_value": 100} for i in range(10)]
        result = candidate_capacity_decision(snapshot(positions=positions), lane_id="DAY", symbol="NEW", open_symbols=[])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["capacity_decision"], "AVAILABLE_FROM_LANE_RESERVE")

    def test_crypto_reserve_allows_full_global_account(self):
        positions = [{"symbol": f"S{i}", "lane_id": "SWING", "market_value": 100} for i in range(10)]
        result = candidate_capacity_decision(snapshot(positions=positions), lane_id="CRYPTO", symbol="BTC/USD", open_symbols=[])
        self.assertTrue(result["allowed"])

    def test_reserve_position_limit_fails_closed(self):
        result = candidate_capacity_decision(
            snapshot(positions=[{"symbol": "DAY1", "lane_id": "DAY", "market_value": 100}]),
            lane_id="DAY",
            symbol="DAY2",
            open_symbols=[],
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["capacity_decision"], "LANE_RESERVE_EXHAUSTED")
        self.assertIn("LANE_POSITION_LIMIT_REACHED", result["exact_blockers"])

    def test_global_risk_overrides_reserve(self):
        result = candidate_capacity_decision(
            snapshot(risk=False), lane_id="DAY", symbol="NEW", open_symbols=[]
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["capacity_decision"], "GLOBAL_RISK_BLOCKED")

    def test_stale_broker_state_does_not_authorize_capacity(self):
        result = candidate_capacity_decision(
            snapshot(fresh=False), lane_id="DAY", symbol="NEW", open_symbols=[]
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["capacity_decision"], "BROKER_STATE_STALE")

    def test_reserve_entry_limit_is_a_capacity_blocker(self):
        # The fixture's environment allows two DAY reserve entries; both are
        # consumed here to prove the canonical counter is not metadata only.
        exhausted = build_capacity_snapshot(
            broker_snapshot={
                "broker_reconciliation_active": True,
                "broker_positions_fetch_ok": True,
                "broker_state_age_seconds": 1,
                "broker_open_positions_count": 10,
                "position_details_available": True,
            },
            account_snapshot={"buying_power": 50000},
            open_positions=[{"symbol": f"S{i}", "lane_id": "SWING", "market_value": 100} for i in range(10)],
            env=BASE_ENV,
            global_position_limit=10,
            lane_entry_counts={"DAY": 2},
        )
        exhausted_result = candidate_capacity_decision(exhausted, lane_id="DAY", symbol="NEW", open_symbols=[])
        self.assertFalse(exhausted_result["allowed"])
        self.assertEqual(exhausted_result["capacity_decision"], "LANE_RESERVE_EXHAUSTED")
        self.assertIn("LANE_ENTRY_LIMIT_REACHED", exhausted_result["exact_blockers"])

    def test_duplicate_exposure_is_explicit(self):
        result = candidate_capacity_decision(
            snapshot(), lane_id="DAY", symbol="SAME", open_symbols=["SAME"]
        )
        self.assertFalse(result["allowed"])
        self.assertEqual(result["capacity_decision"], "DUPLICATE_EXPOSURE_BLOCKED")

    def test_portfolio_review_is_advisory_and_complete(self):
        result = build_portfolio_release_review([
            {"symbol": "KEEP", "entry_price": 10, "current_price": 10.1},
            {"symbol": "BROKEN", "entry_price": 10, "current_price": 8, "thesis_state": "broken"},
            {"symbol": "UNKNOWN"},
        ])
        self.assertEqual(result["total_positions"], 3)
        self.assertEqual(sum(result["positions_by_state"].values()), 3)
        self.assertTrue(result["no_exit_orders_submitted"])
        self.assertEqual(result["positions_by_state"]["THESIS_BROKEN"], 1)
        self.assertEqual(result["positions_by_state"]["DATA_INSUFFICIENT"], 1)

    def test_paper_autopilot_gate_consumes_reserve_decision(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(BASE_ENV, {"ASTRA_DAY_LANE_PILOT_ENABLED": "1"}, clear=False):
            engine = PaperAutopilotEngine(
                db_path=str(pathlib.Path(tmp) / "paper.db"),
                state_path=str(pathlib.Path(tmp) / "state.json"),
            )
            engine._alpaca_safety_snapshot = lambda: {
                "paper_mode_verified": True,
                "paper_endpoint_verified": True,
                "broker_execution_enabled": True,
                "live_endpoint_rejected": True,
            }
            engine._is_candidate_paper_eligible = lambda row: (True, "eligible", {"commitment_score": 90})
            engine.market_session_timing_suite = None
            positions = [{"symbol": f"S{i}", "lane_id": "SWING", "market_value": 100} for i in range(10)]
            capacity = snapshot(positions=positions)
            decision = candidate_capacity_decision(capacity, lane_id="DAY", symbol="DAYTEST", open_symbols=[])
            trace, allowed, reason, _ = engine._candidate_trace_row(
                {"symbol": "DAYTEST", "asset_class": "equity", "paper_entry_horizon_style": "day_trade", "confidence": 90},
                open_syms=set(), stock_capacity=0, crypto_capacity=0, total_capacity=0,
                internal_open_syms=set(), broker_open_syms=set(), broker_reconciliation_active=True,
                capacity_decision=decision,
            )
            self.assertTrue(allowed, reason)
            self.assertEqual(trace["capacity_decision"], "AVAILABLE_FROM_LANE_RESERVE")


if __name__ == "__main__":
    unittest.main()
