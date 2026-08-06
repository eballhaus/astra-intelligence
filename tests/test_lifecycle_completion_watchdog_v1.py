from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from engine.astra_continuous_governance_v1 import ContinuousGovernanceV1
from engine.paper_autopilot import PaperAutopilotEngine
from engine.trade_intelligence import TradeIntelligenceEngine


def _old_iso(seconds: int = 240) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _row() -> dict:
    return {
        "position_id": "lifecycle-1", "symbol": "PTON", "lane_id": "DAY",
        "quantity": 1.0, "entry_price": 10.0, "entry_timestamp": "2026-08-06T14:00:00Z",
        "entry_order_id": "entry-1", "entry_fill_id": "fill-1", "broker_filled_avg_price": 10.0,
        "entry_price_verified": True, "asset_type": "stock", "source_bucket": "paper_autopilot_candidate",
        "entry_metadata_json": json.dumps({"candidate_id": "cand-1", "lifecycle_id": "lifecycle-1"}),
        "row_json": "{}", "lifecycle_notes": "{}", "status": "OPEN",
        "position_owner": "DAY", "exit_policy_owner": "DAY",
    }


class _ZeroBroker:
    def positions(self):
        return {"ok": True, "positions": []}


class _FailsThenAcknowledges:
    def __init__(self) -> None:
        self.calls = 0

    def record_trade(self, payload):
        self.calls += 1
        if self.calls == 1:
            return {"ok": False, "reason": "fixture_consumer_unavailable"}
        return {"ok": True, "acknowledged": True}


class LifecycleCompletionWatchdogTests(unittest.TestCase):
    def test_trade_intelligence_acknowledges_one_lifecycle_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = TradeIntelligenceEngine(str(pathlib.Path(directory) / "learning.db"))
            first = engine.record_trade({"trade_id": "life-1", "symbol": "PTON", "return_percent": -4.0})
            second = engine.record_trade({"trade_id": "life-1", "symbol": "PTON", "return_percent": -4.0})
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertTrue(second["deduplicated"])
            with engine._connect() as conn:
                row = conn.execute("SELECT symbol, return_percent FROM trade_journal WHERE trade_id='life-1'").fetchone()
            self.assertEqual(tuple(row), ("PTON", -4.0))

    def test_false_learning_acknowledgement_is_durable_and_retryable(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            consumer = _FailsThenAcknowledges()
            engine = PaperAutopilotEngine(
                db_path=str(root / "paper.db"), state_path=str(root / "state.json"),
                alpaca_paper_broker=_ZeroBroker(), trade_intel=consumer,
            )
            engine._position_tracker = None
            engine.trade_lifecycle_excursion_suite = None
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions (
                        position_id, symbol, asset_type, status, quantity, entry_price,
                        entry_timestamp, entry_order_id, entry_fill_id,
                        broker_filled_avg_price, entry_price_verified, source_bucket,
                        lifecycle_notes, row_json, entry_metadata_json, lane_id,
                        position_owner, exit_policy_owner, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        "lifecycle-1", "PTON", "stock", "OPEN", 1.0, 10.0,
                        "2026-08-06T14:00:00Z", "entry-1", "fill-1", 10.0, 1,
                        "paper_autopilot_candidate", "{}", "{}",
                        json.dumps({"candidate_id": "cand-1", "lifecycle_id": "lifecycle-1"}),
                        "DAY", "DAY", "DAY", "2026-08-06T14:00:00Z", "2026-08-06T14:00:00Z",
                    ),
                )
                conn.commit()
            closed = engine._close_position(
                _row(), {"symbol": "PTON", "price": 9.0, "source": "alpaca_paper_order_fill"}, "loss_boundary",
                broker_fill={"exit_order_id": "exit-1", "exit_fill_id": "exit-fill-1", "filled_at": "2026-08-06T15:00:00Z"},
            )
            self.assertTrue(closed["ok"])
            self.assertFalse(closed["learning_acknowledged"])
            with engine._connect() as conn:
                notes = json.loads(conn.execute("SELECT lifecycle_notes FROM paper_positions WHERE position_id='lifecycle-1'").fetchone()[0])
            self.assertTrue(notes["learning_acknowledgement_pending"])
            self.assertEqual(notes["learning_acknowledgement_result"]["reason"], "fixture_consumer_unavailable")
            retried = engine._retry_pending_learning_acknowledgements()
            self.assertEqual(retried["acknowledged"], 1)
            self.assertEqual(consumer.calls, 2)
            state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["lifecycle-1"]
            self.assertEqual(state["closure_state"], "LEARNING_ACKNOWLEDGED")

    def test_native_stage_metadata_preserves_identity_and_blocks_new_entries(self):
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {}
        first = engine._record_native_lane_exit_state(_row(), state="EXIT_READY", decision="EXIT_READY")
        second = engine._record_native_lane_exit_state(_row(), state="EXIT_READY", decision="EXIT_READY")
        self.assertEqual(first["position_id"], "lifecycle-1")
        self.assertEqual(first["lifecycle_id"], "lifecycle-1")
        self.assertEqual(first["stage_entered_at"], second["stage_entered_at"])
        self.assertEqual(second["expected_next_transition"], "SELL_SUBMITTED")
        self.assertFalse(second["new_entries_in_lane_safe"])

    def test_governance_escalates_stale_exit_ready_only_during_valid_session(self):
        runtime = {
            "native_lane_exit_lifecycle_v1": {
                "life-1": {
                    "position_id": "life-1", "lifecycle_id": "life-1", "symbol": "PTON", "lane_id": "DAY",
                    "closure_state": "EXIT_READY", "stage_entered_at": _old_iso(),
                    "session_status": {"paper_order_submission_allowed": True},
                    "expected_next_transition": "SELL_SUBMITTED",
                },
            },
        }
        healthy = {"CANONICAL_WORKER_ABSENT": {"state": "PASS", "observed_value": 1, "expected_value": "running"}}
        with tempfile.TemporaryDirectory() as directory, patch("engine.astra_continuous_governance_v1.canonical_runtime_invariants", return_value=healthy), patch("engine.astra_continuous_governance_v1.canonical_worker_state", return_value={}):
            result = ContinuousGovernanceV1(directory).run_worker_cycle(
                worker_state={}, runtime_state=runtime,
                safety={"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
            )
        invariant = next(item for item in result["invariants"] if item["invariant_id"] == "EXIT_READY_NOT_SUBMITTED")
        self.assertEqual(invariant["state"], "FAIL")
        self.assertEqual(result["lane_closure_decision"], "LANE_CLOSURE_CRITICAL")

    def test_after_hours_exit_ready_remains_a_wait_not_a_submission_timeout(self):
        runtime = {
            "native_lane_exit_lifecycle_v1": {
                "life-1": {
                    "position_id": "life-1", "lifecycle_id": "life-1", "symbol": "PTON", "lane_id": "DAY",
                    "closure_state": "EXIT_READY", "stage_entered_at": _old_iso(),
                    "session_status": {"paper_order_submission_allowed": False},
                    "exact_blocker": "REGULAR_SESSION_REQUIRED:after_hours",
                },
            },
        }
        healthy = {"CANONICAL_WORKER_ABSENT": {"state": "PASS", "observed_value": 1, "expected_value": "running"}}
        with tempfile.TemporaryDirectory() as directory, patch("engine.astra_continuous_governance_v1.canonical_runtime_invariants", return_value=healthy), patch("engine.astra_continuous_governance_v1.canonical_worker_state", return_value={}):
            result = ContinuousGovernanceV1(directory).run_worker_cycle(
                worker_state={}, runtime_state=runtime,
                safety={"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
            )
        self.assertFalse(any(item["invariant_id"] == "EXIT_READY_NOT_SUBMITTED" for item in result["invariants"]))

    def test_unmapped_broker_dust_is_critical_not_a_closed_lifecycle(self):
        runtime = {
            "native_lane_exit_lifecycle_v1": {
                "life-1": {
                    "position_id": "life-1", "lifecycle_id": "life-1", "symbol": "PH", "lane_id": "DAY",
                    "closure_state": "EXIT_BLOCKED_CRITICAL",
                    "exact_blocker": "BROKER_DUST_RESIDUAL_UNMAPPED_TO_CANONICAL_LIFECYCLE",
                    "local_quantity": 1.0, "broker_quantity": 0.000000926,
                },
            },
        }
        healthy = {"CANONICAL_WORKER_ABSENT": {"state": "PASS", "observed_value": 1, "expected_value": "running"}}
        with tempfile.TemporaryDirectory() as directory, patch("engine.astra_continuous_governance_v1.canonical_runtime_invariants", return_value=healthy), patch("engine.astra_continuous_governance_v1.canonical_worker_state", return_value={}):
            result = ContinuousGovernanceV1(directory).run_worker_cycle(
                worker_state={}, runtime_state=runtime,
                safety={"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
            )
        invariant = next(item for item in result["invariants"] if item["invariant_id"] == "BROKER_POSITION_QUANTITY_MISMATCH")
        self.assertEqual(invariant["state"], "FAIL")
        self.assertEqual(result["lane_closure_decision"], "LANE_CLOSURE_CRITICAL")


if __name__ == "__main__":
    unittest.main()
