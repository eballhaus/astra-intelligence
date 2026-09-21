"""Regression coverage for native same-session lane closure plumbing."""
from __future__ import annotations

from datetime import datetime, timezone
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from engine.paper_autopilot import PaperAutopilotEngine


class _Broker:
    def __init__(self, *, status: str = "accepted") -> None:
        self.status = status
        self.submitted = []

    def submit_paper_order(self, order):
        self.submitted.append(dict(order))
        return {"ok": True, "order": {"id": "sell-1", "status": self.status, "client_order_id": order["client_order_id"]}}

    def order(self, _order_id):
        return {"ok": True, "order": {"id": "sell-1", "symbol": "DAY", "status": self.status, "filled_qty": "2"}}


class _NearZeroDinoBroker(_Broker):
    def __init__(self):
        super().__init__(status="filled")

    def order(self, _order_id):
        return {
            "ok": True,
            "order": {
                "id": "dino-exit-1",
                "client_order_id": "dino-exit",
                "symbol": "DINO",
                "status": "filled",
                "filled_qty": "0.867818",
                "filled_avg_price": "116.276",
                "filled_at": "2026-09-17T19:55:15.750279Z",
            },
        }

    def positions(self):
        return {"ok": True, "positions": [{
            "symbol": "DINO", "qty": "0.000000087", "qty_available": "0.000000087",
            "market_value": "0.00001", "asset_class": "us_equity",
        }]}

    def reconstruct_open_position_provenance(self, _positions, limit=500):
        return {
            "ok": True,
            "positions": [{
                "symbol": "DINO",
                "quantity_coverage_complete": True,
                "matching_entry_fills": [{
                    "entry_order_id": "entry-1",
                    "remaining_qty": 0.000000087,
                }],
            }],
            "broker_read_calls_used": 1,
        }


def _row():
    return {
        "symbol": "DAY", "position_id": "lifecycle-current", "quantity": 10.0,
        "lane_id": "DAY", "entry_order_id": "entry-1", "entry_fill_id": "fill-1",
        "same_session_exit_required": True, "overnight_allowed": False,
        "position_owner": "DAY", "exit_policy_owner": "DAY",
    }


def _scalp_row():
    return {
        **_row(),
        "symbol": "SCALP",
        "position_id": "scalp-current",
        "lane_id": "SCALP",
        "position_owner": "SCALP",
        "exit_policy_owner": "SCALP",
        "same_session_exit_required": True,
        "overnight_allowed": False,
    }


class NativeLaneExitClosureTests(unittest.TestCase):
    def _engine(self, broker=None):
        engine = object.__new__(PaperAutopilotEngine)
        engine.alpaca_paper_broker = broker or _Broker()
        engine._runtime_state = {}
        engine.learned_exit_validation_kill_switch = False
        engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "broker_live_endpoint_allowed": False}
        engine._native_lane_exit_session_status = lambda: {"market_session_mode": "regular_market", "paper_order_submission_allowed": True}
        return engine

    def test_native_day_contract_submits_without_human_approval(self):
        engine = self._engine()
        with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "DAY", "native_natural_exit_authorized": True, "entry_order_id": "entry-1", "entry_fill_id": "fill-1"}):
            result = engine._submit_authorized_lane_exit(_row(), {"qty_available": 10}, "day_lane_session_close_required")
        self.assertTrue(result["submitted"])
        self.assertEqual(len(engine.alpaca_paper_broker.submitted), 1)
        self.assertEqual(engine.alpaca_paper_broker.submitted[0]["paper_sell_approval_intent_id"], engine.alpaca_paper_broker.submitted[0]["client_order_id"])
        self.assertEqual(engine._runtime_state["native_lane_exit_lifecycle_v1"]["lifecycle-current"]["closure_state"], "SELL_SUBMITTED")

    def test_native_day_contract_never_submits_after_hours(self):
        engine = self._engine()
        engine._native_lane_exit_session_status = lambda: {"market_session_mode": "after_hours", "paper_order_submission_allowed": False}
        with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "DAY", "native_natural_exit_authorized": True}):
            result = engine._submit_authorized_lane_exit(_row(), {"qty_available": 10}, "day_lane_session_close_required")
        self.assertFalse(result["submitted"])
        self.assertEqual(len(engine.alpaca_paper_broker.submitted), 0)
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["lifecycle-current"]
        self.assertEqual(state["closure_state"], "EXIT_BLOCKED_EXECUTION")
        self.assertIn("REGULAR_SESSION_REQUIRED", state["exact_blocker"])

    def test_non_native_writer_still_requires_human_approval(self):
        engine = self._engine()
        with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "DAY", "native_natural_exit_authorized": False}):
            result = engine._submit_authorized_lane_exit(_row(), {"qty_available": 10}, "fixture")
        self.assertFalse(result["submitted"])
        self.assertEqual(len(engine.alpaca_paper_broker.submitted), 0)
        self.assertIn("APPROVAL", result["reason"])

    def test_scalp_same_session_deadline_never_submits_with_stale_quote(self):
        engine = self._engine()
        stale = {"symbol": "SCALP", "price": 10.0, "timestamp": "2020-01-01T00:00:00Z"}
        with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "SCALP", "native_natural_exit_authorized": True, "entry_order_id": "entry-1", "entry_fill_id": "fill-1"}):
            result = engine._submit_authorized_lane_exit(
                _scalp_row(), {"qty_available": 10}, "scalp_lane_session_close_required", latest_quote=stale,
            )
        self.assertFalse(result["submitted"])
        self.assertEqual(result["blocker"], "executable_quote_freshness")
        self.assertEqual(len(engine.alpaca_paper_broker.submitted), 0)
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["scalp-current"]
        self.assertEqual(state["closure_state"], "EXIT_BLOCKED_EVIDENCE")
        self.assertEqual(state["deadline_requirement_status"], "SAME_SESSION_DEADLINE_PASSED")

    def test_scalp_same_session_deadline_can_use_existing_fresh_quote_path(self):
        engine = self._engine()
        fresh = {
            "symbol": "SCALP",
            "price": 10.0,
            "provider_quote_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "SCALP", "native_natural_exit_authorized": True, "entry_order_id": "entry-1", "entry_fill_id": "fill-1"}):
            result = engine._submit_authorized_lane_exit(
                _scalp_row(), {"qty_available": 10}, "scalp_lane_session_close_required", latest_quote=fresh,
            )
        self.assertTrue(result["submitted"])
        self.assertEqual(len(engine.alpaca_paper_broker.submitted), 1)

    def test_partial_fill_stays_on_the_same_lifecycle(self):
        engine = self._engine(_Broker(status="partially_filled"))
        engine._runtime_state["authorized_lane_exit_pending"] = {
            "sell-1": {"position_id": "lifecycle-current", "symbol": "DAY", "lane_id": "DAY", "order_id": "sell-1", "client_order_id": "native-day-exit", "exit_reason": "natural"},
        }
        engine._fetch_open_positions = lambda: [_row()]
        result = engine._refresh_authorized_lane_exit_pending()
        self.assertEqual(result["pending"], 1)
        self.assertEqual(engine._runtime_state["paper_sell_order_intents"]["native-day-exit"]["status"], "PARTIALLY_FILLED")
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["lifecycle-current"]
        self.assertEqual(state["closure_state"], "PARTIALLY_FILLED")

    def test_filled_exit_missing_canonical_row_preserves_exact_blocker(self):
        engine = self._engine(_Broker(status="filled"))
        engine._fetch_open_positions = lambda: []
        engine._runtime_state["authorized_lane_exit_pending"] = {
            "sell-1": {
                "position_id": "lifecycle-current",
                "symbol": "DAY",
                "lane_id": "DAY",
                "order_id": "sell-1",
                "client_order_id": "native-day-exit",
                "exit_reason": "natural",
                "normalized_sell_qty": 2,
            },
        }

        result = engine._refresh_authorized_lane_exit_pending()

        self.assertEqual(result["filled"], 0)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(len(engine.alpaca_paper_broker.submitted), 0)
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["lifecycle-current"]
        self.assertEqual(state["closure_state"], "CLOSURE_BLOCKED_CANONICAL_ROW_MISSING")
        self.assertEqual(state["decision"], "BROKER_FILLED")
        self.assertEqual(state["exit_fill_id"], "sell-1")
        self.assertEqual(state["exact_blocker"], "CANONICAL_POSITION_ROW_MISSING_FOR_FILLED_EXIT")
        intent = engine._runtime_state["paper_sell_order_intents"]["native-day-exit"]
        self.assertEqual(intent["reconciliation_status"], "CANONICAL_POSITION_ROW_MISSING")
        self.assertTrue(intent["canonical_lifecycle_reconciliation_required"])

    def test_filled_exit_waiting_for_broker_zero_preserves_fill_lineage(self):
        engine = self._engine(_Broker(status="filled"))
        engine._fetch_open_positions = lambda: [_row()]
        engine._close_position = lambda *args, **kwargs: {
            "ok": False,
            "error": "broker_residual_lookup_blocks_close:NONZERO_CONFIRMED",
        }
        engine._runtime_state["authorized_lane_exit_pending"] = {
            "sell-1": {
                "position_id": "lifecycle-current",
                "symbol": "DAY",
                "lane_id": "DAY",
                "order_id": "sell-1",
                "client_order_id": "native-day-exit",
                "exit_reason": "natural",
                "normalized_sell_qty": 2,
            },
        }

        result = engine._refresh_authorized_lane_exit_pending()

        self.assertEqual(result["pending"], 1)
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["lifecycle-current"]
        self.assertEqual(state["closure_state"], "AWAITING_BROKER_ZERO")
        self.assertEqual(state["exit_fill_id"], "sell-1")
        pending = engine._runtime_state["authorized_lane_exit_pending"]["sell-1"]
        self.assertEqual(pending["exit_fill_id"], "sell-1")

        downgraded = engine._record_native_lane_exit_state(
            _row(),
            state="EXIT_BLOCKED_EXECUTION",
            decision="EXIT_READY",
            reason="day_lane_overnight_breach",
            blocker="REGULAR_SESSION_REQUIRED:premarket",
        )

        self.assertEqual(downgraded["closure_state"], "AWAITING_BROKER_ZERO")
        self.assertEqual(downgraded["exit_fill_id"], "sell-1")
        self.assertTrue(downgraded["downgrade_suppressed"])

    def test_dino_near_zero_equity_residual_honors_broker_zero_tolerance(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            broker = _NearZeroDinoBroker()
            engine = PaperAutopilotEngine(
                db_path=str(root / "paper.db"),
                state_path=str(root / "state.json"),
                alpaca_paper_broker=broker,
            )
            engine._position_tracker = None
            engine.trade_lifecycle_excursion_suite = None
            row = {
                **_row(),
                "symbol": "DINO",
                "asset_type": "stock",
                "status": "OPEN",
                "position_id": "DINO:2026-09-17T15:37:59",
                "quantity": 0.867818087,
                "entry_timestamp": "2026-09-17T15:40:56.147925Z",
                "entry_price": 115.22,
                "source_bucket": "paper_autopilot_candidate",
                "entry_metadata_generation": "V1_MANDATORY",
                "row_json": "{}",
                "lifecycle_notes": "{}",
                "entry_order_id": "entry-1",
                "entry_fill_id": "entry-1",
            }
            with engine._connect() as conn:
                available = {item[1] for item in conn.execute("PRAGMA table_info(paper_positions)")}
                insert_row = {key: value for key, value in row.items() if key in available}
                columns = ", ".join(insert_row)
                placeholders = ", ".join("?" for _ in insert_row)
                conn.execute(
                    f"INSERT INTO paper_positions ({columns}, created_at, updated_at) VALUES ({placeholders}, ?, ?)",
                    (*insert_row.values(), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
                )
                conn.commit()
            engine._runtime_state["authorized_lane_exit_pending"] = {
                "dino-exit-1": {
                    "position_id": row["position_id"],
                    "symbol": "DINO",
                    "lane_id": "DAY",
                    "order_id": "dino-exit-1",
                    "client_order_id": "dino-exit",
                    "exit_reason": "day_lane_session_close_required",
                    "normalized_sell_qty": 0.867818,
                },
            }

            result = engine._refresh_authorized_lane_exit_pending()

            self.assertEqual(result["filled"], 1)
            self.assertEqual(result["pending"], 0)
            with engine._connect() as conn:
                status, exit_order_id, exit_fill_id = conn.execute(
                    "SELECT status, exit_order_id, exit_fill_id FROM paper_positions WHERE position_id=?",
                    (row["position_id"],),
                ).fetchone()
            self.assertEqual(status, "CLOSED")
            self.assertEqual(exit_order_id, "dino-exit-1")
            self.assertEqual(exit_fill_id, "dino-exit-1")

    def test_broker_filled_state_cannot_be_downgraded_to_premarket_blocker(self):
        engine = self._engine()
        engine._runtime_state["native_lane_exit_lifecycle_v1"] = {
            "lifecycle-current": {
                "position_id": "lifecycle-current",
                "lifecycle_id": "lifecycle-current",
                "symbol": "DAY",
                "lane_id": "DAY",
                "closure_state": "CLOSURE_BLOCKED_CANONICAL_ROW_MISSING",
                "decision": "BROKER_FILLED",
                "exact_blocker": "CANONICAL_POSITION_ROW_MISSING_FOR_FILLED_EXIT",
                "exit_fill_id": "sell-1",
            }
        }

        state = engine._record_native_lane_exit_state(
            _row(),
            state="EXIT_BLOCKED_EXECUTION",
            decision="EXIT_READY",
            reason="day_lane_overnight_breach",
            blocker="REGULAR_SESSION_REQUIRED:premarket",
        )

        self.assertEqual(state["closure_state"], "CLOSURE_BLOCKED_CANONICAL_ROW_MISSING")
        self.assertEqual(state["exact_blocker"], "CANONICAL_POSITION_ROW_MISSING_FOR_FILLED_EXIT")
        self.assertTrue(state["downgrade_suppressed"])
        self.assertEqual(state["downgrade_suppressed_blocker"], "REGULAR_SESSION_REQUIRED:premarket")


if __name__ == "__main__":
    unittest.main()
