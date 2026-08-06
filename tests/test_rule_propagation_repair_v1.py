"""Regression coverage for execution-critical rule propagation.

All fixtures are in-memory and no test constructs a broker adapter call.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from engine.astra_canonical_position_snapshot_v1 import (
    build_canonical_position_snapshot,
    snapshot_to_loss_containment_rows,
)
from engine.astra_continuous_governance_v1 import ContinuousGovernanceV1
from engine.astra_loss_containment_engine_v1 import evaluate_position_loss_containment_v1
from engine.astra_runtime_governance_v1 import RuntimeLimits, worker_liveness
from engine.paper_autopilot import PaperAutopilotEngine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _loss_position(**overrides):
    row = {
        "position_id": "position-pt", "symbol": "PTON", "lane_id": "DAY",
        "entry_price": 6.57, "qty": 15.219178313,
        "quote_timestamp": _now(),
    }
    row.update(overrides)
    return row


class LossNormalizationTests(unittest.TestCase):
    def test_alpaca_fraction_becomes_percentage_points_once(self):
        decision = evaluate_position_loss_containment_v1(
            _loss_position(),
            broker_position={"symbol": "PTON", "qty": "15.219178313", "avg_entry_price": "6.57", "current_price": "5.475", "unrealized_plpc": "-0.16667"},
        )
        self.assertAlmostEqual(decision["current_return_pct"], -16.667, places=3)
        self.assertEqual(decision["threshold_state"], "HARD_BOUNDARY_BREACH")
        self.assertEqual(decision["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")

    def test_fraction_minus_point_zero_one_six_is_minus_one_point_six_percent(self):
        decision = evaluate_position_loss_containment_v1(
            _loss_position(), broker_position={"symbol": "PTON", "qty": "1", "avg_entry_price": "100", "current_price": "98.4", "unrealized_plpc": "-0.016"},
        )
        self.assertAlmostEqual(decision["current_return_pct"], -1.6, places=6)
        self.assertEqual(decision["threshold_state"], "HEALTHY")

    def test_canonical_percentage_outranks_legacy_fraction_without_double_conversion(self):
        decision = evaluate_position_loss_containment_v1(
            _loss_position(unrealized_pl_pct=-16.0, unrealized_plpc=-0.16),
            broker_position={"symbol": "PTON", "qty": "1", "avg_entry_price": "100", "current_price": "84", "unrealized_plpc": "-0.16"},
        )
        self.assertEqual(decision["current_return_pct"], -16.0)

    def test_snapshot_exposes_raw_fraction_separately_from_percentage_points(self):
        snapshot = build_canonical_position_snapshot({
            "PTON": {"symbol": "PTON", "qty": "1", "avg_entry_price": "6.57", "current_price": "5.475", "market_value": "5.475", "cost_basis": "6.57", "unrealized_plpc": "-0.16667"}
        })
        row = snapshot_to_loss_containment_rows(snapshot)[0]
        self.assertAlmostEqual(row["unrealized_pl_pct"], -16.666667, places=4)
        self.assertAlmostEqual(row["broker_unrealized_plpc_fraction"], -0.16666667, places=5)


class QuoteEvidenceTests(unittest.TestCase):
    def _engine(self, quote):
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {}
        engine.get_latest_row_fn = lambda _symbol, _asset: quote
        return engine

    def test_provider_native_quote_is_passed_to_loss_review(self):
        engine = self._engine({
            "symbol": "PTON", "price": 5.475, "bid": 5.47, "ask": 5.48,
            "provider_quote_timestamp": _now(), "provider_used": "alpaca_paper_market_data",
        })
        rows = engine._loss_containment_quote_evidence({"PTON": {"symbol": "PTON", "current_price": "5.475"}})
        self.assertEqual(rows["PTON"]["provider_quote_timestamp"], rows["PTON"]["provider_quote_timestamp"])
        decision = evaluate_position_loss_containment_v1(_loss_position(quote_timestamp=""), latest_price=rows["PTON"])
        self.assertNotIn("MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE", decision["exact_blockers"])

    def test_retrieval_time_only_remains_fail_closed(self):
        engine = self._engine({"symbol": "PTON", "price": 5.475, "retrieval_timestamp": _now()})
        rows = engine._loss_containment_quote_evidence({"PTON": {"symbol": "PTON", "current_price": "5.475"}})
        decision = evaluate_position_loss_containment_v1(_loss_position(quote_timestamp=""), latest_price=rows["PTON"])
        self.assertIn("MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE", decision["exact_blockers"])

    def test_one_bad_quote_does_not_block_other_positions(self):
        def quote(symbol, _asset):
            if symbol == "BAD":
                raise RuntimeError("provider unavailable")
            return {"symbol": symbol, "price": 10, "provider_quote_timestamp": _now(), "provider_used": "alpaca"}
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {}
        engine.get_latest_row_fn = quote
        rows = engine._loss_containment_quote_evidence({"BAD": {"current_price": "8"}, "GOOD": {"current_price": "10"}})
        self.assertIn("GOOD", rows)
        self.assertEqual(engine._runtime_state["loss_containment_quote_evidence_v1"]["BAD"]["status"], "QUOTE_LOOKUP_FAILED")


class DayContractMaterializationTests(unittest.TestCase):
    def test_immutable_day_contract_is_available_to_native_exit_owner(self):
        row = PaperAutopilotEngine._materialize_open_position_entry_contract({
            "position_id": "day-life", "lane_id": "DAY",
            "entry_metadata_json": '{"same_session_exit_required":true,"overnight_allowed":false,"paper_entry_horizon_style":"day_trade","entry_contract_id":"contract-1"}',
        })
        self.assertIs(row["same_session_exit_required"], True)
        self.assertIs(row["overnight_allowed"], False)
        self.assertEqual(row["paper_entry_horizon_style"], "day_trade")
        self.assertEqual(row["entry_contract_id"], "contract-1")

    def test_stored_column_cannot_be_overwritten_by_json(self):
        row = PaperAutopilotEngine._materialize_open_position_entry_contract({
            "same_session_exit_required": True, "overnight_allowed": False,
            "entry_metadata_json": '{"same_session_exit_required":false,"overnight_allowed":true}',
        })
        self.assertIs(row["same_session_exit_required"], True)
        self.assertIs(row["overnight_allowed"], False)


class WorkerAndOversightTests(unittest.TestCase):
    def test_dead_pid_and_stale_heartbeat_are_red_liveness(self):
        state = {
            "process_id": 777, "ownership_state": "SINGLE_WORKER_ACTIVE",
            "heartbeat_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "limits": RuntimeLimits().__dict__,
        }
        result = worker_liveness(state, process={"pid": 777, "running": False, "command": ""})
        self.assertEqual(result["liveness_state"], "PROCESS_MISSING")
        self.assertEqual(result["terminal_cause"], "CANONICAL_WORKER_ABSENT")
        self.assertEqual(result["incident_severity"], "RED")

    def test_governance_never_reports_pass_for_hard_loss_without_exit_state(self):
        runtime_state = {
            "loss_containment_review_v1": {"state": {"decisions": {"pt": {
                "position_id": "pt", "symbol": "PTON", "lane": "DAY", "threshold_state": "HARD_BOUNDARY_BREACH",
            }}}},
            "native_lane_exit_lifecycle_v1": {},
        }
        fake_runtime = {"CANONICAL_WORKER_ABSENT": {"state": "FAIL", "observed_value": 777, "expected_value": "running", "exact_blocker": "CANONICAL_WORKER_ABSENT"}}
        with tempfile.TemporaryDirectory() as directory, patch("engine.astra_continuous_governance_v1.canonical_runtime_invariants", return_value=fake_runtime), patch("engine.astra_continuous_governance_v1.canonical_worker_state", return_value={}):
            result = ContinuousGovernanceV1(directory).run_worker_cycle(
                worker_state={}, runtime_state=runtime_state,
                safety={"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
            )
        self.assertEqual(result["status"], "NO_GO_RUNTIME_INVARIANTS_FAILED")
        self.assertEqual(result["lane_closure_decision"], "LANE_CLOSURE_CRITICAL")
        self.assertEqual(result["cortex_operational_diagnosis"]["root_cause"], "CANONICAL_WORKER_ABSENT")

    def test_day_overnight_breach_blocked_after_hours_is_not_go(self):
        """A legitimate closed-session block is still a critical DAY closure wait."""
        runtime_state = {
            "native_lane_exit_lifecycle_v1": {
                "day-life": {
                    "position_id": "day-life", "lifecycle_id": "day-life", "symbol": "PTON",
                    "lane_id": "DAY", "reason": "day_lane_overnight_breach",
                    "decision": "EXIT_READY", "closure_state": "EXIT_BLOCKED_EXECUTION",
                    "exact_blocker": "REGULAR_SESSION_REQUIRED:after_hours",
                }
            },
        }
        healthy_runtime = {"CANONICAL_WORKER_ABSENT": {
            "state": "PASS", "observed_value": 1, "expected_value": "running",
        }}
        with tempfile.TemporaryDirectory() as directory, patch("engine.astra_continuous_governance_v1.canonical_runtime_invariants", return_value=healthy_runtime), patch("engine.astra_continuous_governance_v1.canonical_worker_state", return_value={}):
            result = ContinuousGovernanceV1(directory).run_worker_cycle(
                worker_state={}, runtime_state=runtime_state,
                safety={"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
            )
        self.assertEqual(result["status"], "NO_GO_RUNTIME_INVARIANTS_FAILED")
        self.assertEqual(result["lane_closure_decision"], "LANE_CLOSURE_CRITICAL")
        invariant = next(row for row in result["invariants"] if row["invariant_id"] == "DAY_POSITION_HORIZON_BREACH")
        self.assertEqual(invariant["exact_blocker"], "OVERNIGHT_HOLD_NOT_AUTHORIZED")

    def test_terminal_day_closure_clears_overnight_breach_invariant(self):
        runtime_state = {
            "native_lane_exit_lifecycle_v1": {
                "day-life": {
                    "position_id": "day-life", "symbol": "PTON", "lane_id": "DAY",
                    "reason": "day_lane_overnight_breach", "closure_state": "BROKER_ZERO_CONFIRMED",
                }
            },
        }
        healthy_runtime = {"CANONICAL_WORKER_ABSENT": {
            "state": "PASS", "observed_value": 1, "expected_value": "running",
        }}
        with tempfile.TemporaryDirectory() as directory, patch("engine.astra_continuous_governance_v1.canonical_runtime_invariants", return_value=healthy_runtime), patch("engine.astra_continuous_governance_v1.canonical_worker_state", return_value={}):
            result = ContinuousGovernanceV1(directory).run_worker_cycle(
                worker_state={}, runtime_state=runtime_state,
                safety={"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
            )
        invariant = next(row for row in result["invariants"] if row["invariant_id"] == "DAY_POSITION_HORIZON_BREACH")
        self.assertEqual(invariant["state"], "PASS")
        self.assertEqual(result["lane_closure_decision"], "LANE_CLOSURE_GO")


if __name__ == "__main__":
    unittest.main()
