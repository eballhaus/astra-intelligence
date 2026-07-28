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
from engine.astra_portfolio_capacity_release_review_v1 import build_portfolio_release_review, classify_position
from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1
from engine.paper_autopilot import PaperAutopilotEngine
from engine.paper_autopilot import _execution_trace_event


BASE_ENV = {
    "ASTRA_DAY_EVIDENCE_RESERVE_ENABLED": "1",
    "ASTRA_DAY_EVIDENCE_CAPITAL_LIMIT": "15000",
    "ASTRA_DAY_EVIDENCE_POSITION_LIMIT": "1",
    "ASTRA_CRYPTO_EVIDENCE_RESERVE_ENABLED": "1",
    "ASTRA_CRYPTO_EVIDENCE_CAPITAL_LIMIT": "10000",
    "ASTRA_CRYPTO_EVIDENCE_POSITION_LIMIT": "1",
    "ASTRA_DAY_LANE_PILOT_ENABLED": "1",
    "ASTRA_DAY_LANE_CAPITAL_LIMIT": "15000",
    "ASTRA_ENABLE_ALPACA_CRYPTO_PAPER": "1",
    "ASTRA_CRYPTO_PAPER_CAPITAL_LIMIT": "10000",
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


def contract_fields(symbol: str, lane: str, horizon: str) -> dict:
    expires_at = (datetime.now(UTC) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    return {
        "candidate_id": f"candidate-{symbol}", "recommendation_id": f"recommendation-{symbol}",
        "lane_id": lane, "strategy_archetype": "test_momentum", "trade_style": horizon,
        "score": 90.0, "ranking_factors": ["test_signal"], "thesis": "Test thesis is intact.",
        "thesis_supporting_conditions": ["trend"], "thesis_invalidation_conditions": ["trend_break"],
        "intended_horizon": horizon, "expected_hold_window": "1d", "entry_conditions": ["confirmed"],
        "expected_return_range": {"low": 1.0, "high": 3.0}, "expected_downside_range": {"low": -2.0, "high": -1.0},
        "expected_drawdown": -2.0, "expected_return_per_day_range": {"low": 0.2, "high": 0.6},
        "hold_conditions": ["thesis_intact"], "profit_protection_conditions": ["giveback"],
        "exit_review_conditions": ["horizon_review"], "controlled_loss_conditions": ["thesis_broken"],
        "replacement_review_conditions": ["better_candidate"], "monitoring_priorities": ["thesis_and_horizon"], "confidence": 90.0,
        "evidence_classes": ["REPLAY_SUPPORTED"], "certification_snapshot_id": "test-snapshot",
        "expires_at": expires_at,
    }


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
            self.assertFalse(summary["lanes"]["CRYPTO"]["reserve_commitments_pending_is_current_occupancy"])
            self.assertEqual(
                summary["lanes"]["CRYPTO"]["reserve_commitments_converted_to_pending_order_lifetime"],
                summary["lanes"]["CRYPTO"]["reserve_commitments_pending"],
            )
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

    def test_day_second_slot_remains_available_beneath_unchanged_capital_ceiling(self):
        env = {**BASE_ENV, "ASTRA_DAY_EVIDENCE_POSITION_LIMIT": "2"}
        capacity = build_capacity_snapshot(
            broker_snapshot={"broker_reconciliation_active": True, "broker_positions_fetch_ok": True, "broker_state_age_seconds": 0},
            account_snapshot={"buying_power": 50000},
            open_positions=[{"symbol": "DAY1", "lane_id": "DAY", "market_value": 100}],
            env=env, global_position_limit=10,
        )
        result = candidate_capacity_decision(capacity, lane_id="DAY", symbol="DAY2", open_symbols=[])
        self.assertTrue(result["allowed"])
        self.assertEqual(capacity["lanes"]["day"]["configured_capital_limit"], 15000.0)
        self.assertEqual(capacity["lanes"]["day"]["positions_remaining"], 1)

    def test_swing_uses_approved_active_slot_capacity_without_separate_concurrency_cap(self):
        capacity = build_capacity_snapshot(
            broker_snapshot={"broker_reconciliation_active": True, "broker_positions_fetch_ok": True, "broker_state_age_seconds": 0},
            account_snapshot={"buying_power": 50000},
            open_positions=[
                {"symbol": "S1", "lane_id": "SWING", "market_value": 100},
                {"symbol": "S2", "lane_id": "SWING", "market_value": 100},
            ], env=BASE_ENV, global_position_limit=10,
        )
        result = candidate_capacity_decision(capacity, lane_id="SWING", symbol="S3", open_symbols=[])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["capacity_decision"], "AVAILABLE")
        self.assertEqual(capacity["active_strategy_slot_capacity_remaining"], 8)
        self.assertEqual(capacity["swing_capacity_authority"], "ACTIVE_STRATEGY_SLOT_CAPACITY")

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

    def test_capacity_authority_is_explicit_and_fail_closed_when_stale(self):
        current = snapshot()
        self.assertEqual(current["capacity_authority_state"], "CURRENT")
        self.assertEqual(current["lanes"]["day"]["capacity_authority_state"], "CURRENT")
        stale = snapshot(fresh=False)
        self.assertEqual(stale["capacity_authority_state"], "BROKER_UNREACHABLE")
        self.assertEqual(stale["lanes"]["crypto"]["capacity_authority_state"], "BROKER_UNREACHABLE")

    def test_early_trace_records_exact_first_failing_gate(self):
        trace = _execution_trace_event(
            {"symbol": "BTC/USD", "asset_class": "crypto", "candidate_id": "btc-stale"},
            eligible=False,
            decision_reason="candidate_freshness_not_ready",
        )
        attribution = trace["eligibility_gate_attribution_v1"]
        self.assertEqual(attribution["first_failing_gate"]["code"], "CANDIDATE_STALE")
        self.assertEqual(attribution["first_failing_gate"]["validity"], "MISSING_INPUT_DEFECT")

    def test_missing_contract_and_crypto_source_are_not_generic_rejections(self):
        contract_trace = _execution_trace_event(
            {"symbol": "DAY", "candidate_id": "day-contract"},
            eligible=False,
            decision_reason="PRETRADE_DECISION_CONTRACT_MISSING_FIELDS",
        )
        crypto_trace = _execution_trace_event(
            {"symbol": "BTC/USD", "asset_class": "crypto", "candidate_id": "btc-source"},
            eligible=False,
            decision_reason="CANDIDATE_SOURCE_NOT_READY",
        )
        self.assertEqual(contract_trace["eligibility_gate_attribution_v1"]["first_failing_gate"]["code"], "CONTRACT_INCOMPLETE")
        self.assertEqual(crypto_trace["eligibility_gate_attribution_v1"]["first_failing_gate"]["code"], "CANDIDATE_STALE")

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

    def test_capacity_snapshot_never_advertises_duplicate_exposure_as_allowed(self):
        result = snapshot()
        self.assertFalse(result["lanes"]["day"]["duplicate_exposure_allowed"])
        self.assertFalse(result["lanes"]["crypto"]["duplicate_exposure_allowed"])

    def test_worker_capacity_snapshot_persists_secret_free_position_projection(self):
        class _Broker:
            def account(self):
                return {"buying_power": 1000}

        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperAutopilotEngine(
                db_path=str(pathlib.Path(tmp) / "paper.db"),
                state_path=str(pathlib.Path(tmp) / "state.json"),
                alpaca_paper_broker=_Broker(),
            )
            result = engine._evidence_capacity_snapshot_v1(
                {
                    "broker_reconciliation_active": True,
                    "broker_positions_fetch_ok": True,
                    "broker_position_by_symbol": {
                        "DAYTEST": {
                            "symbol": "DAYTEST", "qty": "2", "market_value": "100",
                            "lane_id": "DAY", "asset_id": "must_not_persist",
                        },
                    },
                },
                [],
                {"broker_execution_enabled": True},
            )
        self.assertTrue(result["position_rows_secret_free"])
        self.assertEqual(result["position_rows_for_read_only_consumers"][0]["symbol"], "DAYTEST")
        self.assertNotIn("asset_id", result["position_rows_for_read_only_consumers"][0])

    def test_worker_capacity_snapshot_does_not_count_lane_unavailable_legacy_as_day(self):
        """The worker must not let a stale local DAY label consume DAY reserve."""
        class _Broker:
            def account(self):
                return {"buying_power": 100000}

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            **BASE_ENV,
            "ASTRA_DAY_EVIDENCE_POSITION_LIMIT": "2",
        }, clear=False):
            engine = PaperAutopilotEngine(
                db_path=str(pathlib.Path(tmp) / "paper.db"),
                state_path=str(pathlib.Path(tmp) / "state.json"),
                alpaca_paper_broker=_Broker(),
            )
            engine._runtime_state["position_lane_horizon_recovery_v1"] = {
                "positions": [
                    {
                        "symbol": "LEGACY", "lane": "UNAVAILABLE", "horizon": "UNAVAILABLE",
                        "lane_status": "UNAVAILABLE", "horizon_status": "UNAVAILABLE",
                    },
                    {
                        "symbol": "VALIDDAY", "lane": "DAY", "horizon": "day_trade",
                        "lane_status": "RESOLVED", "horizon_status": "RESOLVED",
                    },
                    {
                        "symbol": "DUSTDAY", "lane": "DAY", "horizon": "day_trade",
                        "lane_status": "RESOLVED", "horizon_status": "RESOLVED",
                    },
                ],
            }
            result = engine._evidence_capacity_snapshot_v1(
                {
                    "broker_reconciliation_active": True,
                    "broker_positions_fetch_ok": True,
                    "broker_position_by_symbol": {
                        "LEGACY": {"symbol": "LEGACY", "qty": "1", "market_value": "100", "lane_id": "DAY"},
                        "VALIDDAY": {"symbol": "VALIDDAY", "qty": "1", "market_value": "100", "lane_id": "DAY"},
                        "DUSTDAY": {"symbol": "DUSTDAY", "qty": "0.000001", "market_value": "0.0001", "lane_id": "DAY"},
                    },
                },
                [],
                {"broker_execution_enabled": True},
            )

        self.assertEqual(result["lanes"]["day"]["open_position_count"], 1)
        self.assertEqual(result["lanes"]["day"]["positions_remaining"], 1)
        self.assertEqual(result["lanes"]["day"]["dust_strategy_slot_exclusion_count"], 1)
        self.assertEqual(result["broker_total_exposure_position_count"], 3)
        legacy = next(row for row in result["position_rows_for_read_only_consumers"] if row["symbol"] == "LEGACY")
        self.assertEqual(legacy["recovered_lane"], "UNAVAILABLE")

    def test_horizon_capacity_uses_canonical_strategy_slots_not_legacy_or_dust(self):
        """Legacy and dust exposure cannot re-saturate the worker horizon gate."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperAutopilotEngine(
                db_path=str(pathlib.Path(tmp) / "paper.db"),
                state_path=str(pathlib.Path(tmp) / "state.json"),
            )
            engine.horizon_total_capacity = 2
            engine._runtime_state["last_evidence_capacity_snapshot"] = {
                "capacity_authority_state": "CURRENT",
                "position_rows_for_read_only_consumers": [
                    {"symbol": "MANAGED"}, {"symbol": "LEGACY"}, {"symbol": "DUST"},
                ],
                "approved_legacy_slot_exclusion_symbols": ["LEGACY"],
                "dust_positions": [{"symbol": "DUST", "dust_state": "BROKER_DUST_MONITORED"}],
            }
            result = engine._horizon_capacity_snapshot(
                open_rows=[{"symbol": "MANAGED", "paper_entry_horizon_style": "swing_trade"}],
                broker_open_syms={"MANAGED", "LEGACY", "DUST"},
                broker_reconciliation_active=True,
                broker_positions_fetch_ok=True,
                adaptive_total_capacity=2,
            )

        self.assertEqual(result["total_used"], 1)
        self.assertEqual(result["total_available"], 1)
        self.assertEqual(result["strategy_capacity_excluded_legacy_count"], 1)
        self.assertEqual(result["strategy_capacity_excluded_dust_count"], 1)

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

    def test_loss_without_linked_forward_evidence_stays_watch_not_controlled_loss(self):
        result = classify_position({
            "symbol": "LOSS", "avg_entry_price": 10, "current_price": 8,
            "unrealized_plpc": -0.2,
        })
        self.assertEqual(result["primary_state"], "WATCH")
        self.assertNotIn("CONTROLLED_LOSS_ACCEPTABLE", result["secondary_labels"])
        self.assertIn("LOSS_REQUIRES_LINKED_FORWARD_EVIDENCE", result["reason_codes"])
        self.assertTrue(result["automatic_action_authorized"] is False)

    def test_linked_loss_evidence_can_only_request_human_exit_review(self):
        result = classify_position({
            "symbol": "REVIEW", "avg_entry_price": 10, "current_price": 8,
            "unrealized_plpc": -0.2, "horizon_expired": True,
            "controlled_loss_supported": True,
            "forward_value_status": "unfavorable",
        })
        self.assertEqual(result["primary_state"], "EXIT_REVIEW")
        self.assertIn("CONTROLLED_LOSS_ACCEPTABLE", result["secondary_labels"])
        self.assertTrue(result["human_review_required"])
        self.assertFalse(result["automatic_action_authorized"])

    def test_missing_lifecycle_evidence_is_not_a_blanket_behavioral_classification(self):
        result = build_portfolio_release_review([
            {"symbol": "A", "avg_entry_price": 10, "current_price": 9, "missing_evidence": ["mfe_mae"]},
            {"symbol": "B", "avg_entry_price": 10, "current_price": 11, "missing_evidence": ["mfe_mae"]},
        ])
        audit = result["differentiation_audit"]
        self.assertEqual(audit["evidence_gap_counts"]["MISSING_LIFECYCLE_DATA"], 2)
        self.assertFalse(audit["blanket_fallback_detected"])

    def test_paper_autopilot_gate_consumes_reserve_decision(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, BASE_ENV, clear=False):
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
                {"symbol": "DAYTEST", "asset_class": "equity", "paper_entry_horizon_style": "day_trade", **contract_fields("DAYTEST", "DAY", "day_trade")},
                open_syms=set(), stock_capacity=0, crypto_capacity=0, total_capacity=0,
                internal_open_syms=set(), broker_open_syms=set(), broker_reconciliation_active=True,
                capacity_decision=decision,
            )
            self.assertTrue(allowed, reason)
            self.assertEqual(trace["capacity_decision"], "AVAILABLE_FROM_LANE_RESERVE")
            self.assertEqual(
                trace["contract_failure_attribution_v1"]["producer"],
                "engine.astra_premarket_certification_v1.build_pretrade_decision_contract",
            )
            self.assertEqual(trace["contract_failure_attribution_v1"]["consumer"], "PaperAutopilot._candidate_trace_row")

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
                [{"symbol": "DAYFIXTURE", "asset_type": "stock", "paper_entry_horizon_style": "day_trade", **contract_fields("DAYFIXTURE", "DAY", "day_trade")}],
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
            contract = result["per_candidate_decision_trace"][0]["pretrade_decision_contract"]
            self.assertEqual(contract["contract_state"], "CONTRACT_COMPLETE")
            self.assertEqual(contract["consumer_acknowledgements"]["order_ready_status"], "CONSUMED_ORDER_READY")
            self.assertEqual(contract["candidate_terminal_state"], "ORDER_READY")
            self.assertEqual(engine._lane_reserve_commitment_snapshot()["active_commitments"], 0)

    def test_valid_swing_contract_reaches_order_ready_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, BASE_ENV, clear=False):
            engine = PaperAutopilotEngine(
                db_path=str(pathlib.Path(tmp) / "paper.db"),
                state_path=str(pathlib.Path(tmp) / "state.json"),
            )
            engine._current_execution_capacities = lambda: {
                "open_symbols": set(), "stock_capacity": 1, "crypto_capacity": 0, "total_capacity": 1,
            }
            engine._alpaca_safety_snapshot = lambda: {
                "paper_mode_verified": True, "paper_endpoint_verified": True,
                "broker_execution_enabled": True, "live_endpoint_rejected": True,
            }
            engine._is_candidate_paper_eligible = lambda row: (True, "eligible", {"commitment_score": 90})

            class _OpenSession:
                def confirmation_for_candidate(self, *_args, **_kwargs):
                    return {"market_is_open": True, "market_is_tradable": True, "paper_order_submission_allowed": True,
                            "execution_confirmation_required": False, "requires_open_confirmation": False}

            engine.market_session_timing_suite = _OpenSession()
            result = engine.operational_dry_run([{
                "symbol": "SWINGFIXTURE", "asset_type": "stock", "paper_entry_horizon_style": "swing_trade",
                **contract_fields("SWINGFIXTURE", "SWING", "swing_trade"),
            }])
            self.assertEqual(result["order_ready_candidates"], 1)
            self.assertEqual(result["per_candidate_decision_trace"][0]["pretrade_decision_contract_state"], "CONTRACT_COMPLETE")

    def test_lane_ledger_detects_false_reserve_exhaustion(self):
        with tempfile.TemporaryDirectory() as state_dir:
            ledger = LaneExecutionTraceLedgerV1(state_dir=state_dir)
            ledger.record([{
                "lane_id": "DAY", "candidate_id": "c1", "recommendation_id": "r1", "symbol": "DAY",
                "capacity_decision": "LANE_RESERVE_EXHAUSTED", "lane_reserve_enabled": True,
                "lane_capital_remaining": 100, "lane_positions_remaining": 1,
                "lane_open_position_count": 0, "lane_pending_order_count": 0, "lane_active_commitment_count": 0,
                "commitment_id": "held-then-released", "commitment_state": "RELEASED",
            }], cycle_id="fixture")
            summary = ledger.summary()["lanes"]["DAY"]
            self.assertEqual(summary["false_reserve_exhaustion_contradictions"], 1)
            self.assertEqual(summary["reserve_commitments_requested"], 1)
            self.assertEqual(summary["reserve_commitments_released"], 1)

    def test_operational_dry_run_reaches_order_ready_from_crypto_reserve(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, BASE_ENV, clear=False):
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
