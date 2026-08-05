"""Regression coverage for native same-session lane closure plumbing."""
from __future__ import annotations

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


def _row():
    return {
        "symbol": "DAY", "position_id": "lifecycle-current", "quantity": 10.0,
        "lane_id": "DAY", "entry_order_id": "entry-1", "entry_fill_id": "fill-1",
        "same_session_exit_required": True, "overnight_allowed": False,
        "position_owner": "DAY", "exit_policy_owner": "DAY",
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


if __name__ == "__main__":
    unittest.main()
