import unittest
import tempfile
import json
import pathlib
import os
from datetime import UTC, datetime, timedelta
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

    def test_historical_entry_counts_are_advisory_not_reserve_occupancy(self):
        # Historical DAY attempts are learning telemetry. They cannot consume
        # a live reserve slot once no broker position/order/commitment exists.
        available = build_capacity_snapshot(
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
        available_result = candidate_capacity_decision(available, lane_id="DAY", symbol="NEW", open_symbols=[])
        self.assertTrue(available_result["allowed"])
        self.assertTrue(available["historical_entry_counts_advisory_only"])
        self.assertEqual(available["lanes"]["day"]["historical_entries_used"], 2)

    def test_pending_order_and_active_commitment_consume_reserve(self):
        pending = build_capacity_snapshot(
            broker_snapshot={"broker_reconciliation_active": True, "broker_positions_fetch_ok": True, "broker_state_age_seconds": 0},
            account_snapshot={"buying_power": 50000},
            pending_orders=[{"symbol": "DAYP", "lane_id": "DAY", "status": "accepted", "notional": 100}],
            env=BASE_ENV,
            global_position_limit=10,
        )
        decision = candidate_capacity_decision(pending, lane_id="DAY", symbol="DAY2", open_symbols=[])
        self.assertFalse(decision["allowed"])
        self.assertEqual(pending["lanes"]["day"]["pending_order_count"], 1)

    def test_valid_commitment_consumes_and_expired_commitment_releases(self):
        active = build_capacity_snapshot(
            broker_snapshot={"broker_reconciliation_active": True, "broker_positions_fetch_ok": True, "broker_state_age_seconds": 0},
            account_snapshot={"buying_power": 50000},
            active_commitments=[{"lane_id": "DAY", "symbol": "DAYH", "state": "HELD", "expires_at": (datetime.now(UTC) + timedelta(seconds=60)).isoformat()}],
            env=BASE_ENV,
            global_position_limit=10,
        )
        self.assertFalse(candidate_capacity_decision(active, lane_id="DAY", symbol="DAY2", open_symbols=[])["allowed"])
        expired = build_capacity_snapshot(
            broker_snapshot={"broker_reconciliation_active": True, "broker_positions_fetch_ok": True, "broker_state_age_seconds": 0},
            account_snapshot={"buying_power": 50000},
            active_commitments=[{"lane_id": "DAY", "symbol": "DAYH", "state": "HELD", "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}],
            env=BASE_ENV,
            global_position_limit=10,
        )
        self.assertTrue(candidate_capacity_decision(expired, lane_id="DAY", symbol="DAY2", open_symbols=[])["allowed"])

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
            class _OpenSession:
                def confirmation_for_candidate(self, *_args, **_kwargs):
                    return {
                        "market_session_mode": "regular_market",
                        "market_is_open": True,
                        "market_is_tradable": True,
                        "paper_order_submission_allowed": True,
                        "execution_confirmation_required": False,
                        "requires_open_confirmation": False,
                    }
            engine.market_session_timing_suite = _OpenSession()
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

    def test_operational_dry_run_reaches_order_ready_from_day_reserve(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, BASE_ENV, clear=False):
            engine = PaperAutopilotEngine(
                db_path=str(pathlib.Path(tmp) / "paper.db"),
                state_path=str(pathlib.Path(tmp) / "state.json"),
            )
            engine._current_execution_capacities = lambda: {
                "open_symbols": set(), "stock_capacity": 0,
                "crypto_capacity": 0, "total_capacity": 0,
            }
            engine._alpaca_safety_snapshot = lambda: {
                "paper_mode_verified": True, "paper_endpoint_verified": True,
                "broker_execution_enabled": True, "live_endpoint_rejected": True,
            }
            engine._is_candidate_paper_eligible = lambda row: (True, "eligible", {"commitment_score": 90})
            class _OpenSession:
                def confirmation_for_candidate(self, *_args, **_kwargs):
                    return {
                        "market_session_mode": "regular_market",
                        "market_is_open": True,
                        "market_is_tradable": True,
                        "paper_order_submission_allowed": True,
                        "execution_confirmation_required": False,
                        "requires_open_confirmation": False,
                    }
            engine.market_session_timing_suite = _OpenSession()
            result = engine.operational_dry_run(
                [{"symbol": "DAYFIXTURE", "asset_type": "stock", "lane_id": "DAY", "paper_entry_horizon_style": "day_trade", "confidence": 90}],
                capacity_snapshot=snapshot(
                    positions=[{"symbol": f"S{i}", "lane_id": "SWING", "market_value": 100} for i in range(10)]
                ),
            )
            self.assertEqual(result["selected_candidates"], 1)
            self.assertEqual(result["order_ready_candidates"], 1)
            self.assertEqual(result["per_candidate_decision_trace"][0]["capacity_decision"], "AVAILABLE_FROM_LANE_RESERVE")
            self.assertTrue(result["per_candidate_decision_trace"][0]["lane_reserve_enabled"])
            self.assertTrue(result["per_candidate_decision_trace"][0]["lane_reserve_available"])
            self.assertEqual(result["per_candidate_decision_trace"][0]["commitment_final_state"], "RELEASED")
            self.assertEqual(engine._lane_reserve_commitment_snapshot()["active_commitments"], 0)

    def test_lane_ledger_detects_false_reserve_exhaustion(self):
        with tempfile.TemporaryDirectory() as state_dir:
            ledger = LaneExecutionTraceLedgerV1(state_dir=state_dir)
            ledger.record([{
                "lane_id": "DAY", "candidate_id": "c1", "recommendation_id": "r1", "symbol": "DAY",
                "capacity_decision": "LANE_RESERVE_EXHAUSTED", "lane_reserve_enabled": True,
                "lane_capital_remaining": 100, "lane_positions_remaining": 1,
                "lane_open_position_count": 0, "lane_pending_order_count": 0, "lane_active_commitment_count": 0,
            }], cycle_id="fixture")
            self.assertEqual(ledger.summary()["lanes"]["DAY"]["false_reserve_exhaustion_contradictions"], 1)

    def test_operational_dry_run_reaches_order_ready_from_crypto_reserve(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(BASE_ENV, clear=False):
            engine = PaperAutopilotEngine(
                db_path=str(pathlib.Path(tmp) / "paper.db"),
                state_path=str(pathlib.Path(tmp) / "state.json"),
            )
            engine._current_execution_capacities = lambda: {
                "open_symbols": set(), "stock_capacity": 0,
                "crypto_capacity": 0, "total_capacity": 0,
            }

            def reserve_trace(_row, **kwargs):
                decision = kwargs["capacity_decision"]
                self.assertTrue(decision["allowed"])
                return ({
                    "symbol": "BTC/USD",
                    "capacity_decision": decision["capacity_decision"],
                    "paper_order_submission_allowed": True,
                    "requires_open_confirmation": False,
                }, True, "", {})

            with patch.object(engine, "_candidate_trace_row", side_effect=reserve_trace):
                result = engine.operational_dry_run(
                    [{"symbol": "BTC/USD", "asset_type": "crypto", "lane_id": "CRYPTO"}],
                    capacity_snapshot=snapshot(
                        positions=[{"symbol": f"S{i}", "lane_id": "SWING", "market_value": 100} for i in range(10)]
                    ),
                )
            self.assertEqual(result["selected_candidates"], 1)
            self.assertEqual(result["order_ready_candidates"], 1)
            self.assertEqual(result["per_candidate_decision_trace"][0]["capacity_decision"], "AVAILABLE_FROM_LANE_RESERVE")


if __name__ == "__main__":
    unittest.main()
