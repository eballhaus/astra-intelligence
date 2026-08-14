"""Tests for canonical paper sell approval contract."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_paper_exit_approval_contract_v1 import (
    build_paper_sell_approval_v1,
    validate_paper_sell_approval_v1,
    consume_paper_sell_approval_v1,
)
from engine.paper_autopilot import PaperAutopilotEngine


def _now():
    return datetime.now(timezone.utc)


class PaperSellApprovalContractTests(unittest.TestCase):
    def test_build_approval_requires_human_identity(self):
        with self.assertRaises(ValueError):
            build_paper_sell_approval_v1(approved_by="", approved_symbol="AAPL", approved_quantity=10)

    def test_build_approval_requires_symbol(self):
        with self.assertRaises(ValueError):
            build_paper_sell_approval_v1(approved_by="human", approved_symbol="", approved_quantity=10)

    def test_build_approval_requires_positive_quantity(self):
        with self.assertRaises(ValueError):
            build_paper_sell_approval_v1(approved_by="human", approved_symbol="AAPL", approved_quantity=0)

    def test_build_approval_sets_all_fields(self):
        apr = build_paper_sell_approval_v1(
            approved_by="trader1", approved_symbol="AAPL", approved_quantity=50.0,
            approved_account="paper1", approved_decision_id="pos-123",
            expires_in_minutes=60,
        )
        self.assertEqual(apr["approval_status"], "APPROVED")
        self.assertEqual(apr["approved_by"], "trader1")
        self.assertEqual(apr["approved_symbol"], "AAPL")
        self.assertEqual(apr["approved_side"], "SELL")
        self.assertEqual(apr["approved_quantity"], 50.0)
        self.assertEqual(apr["approved_max_quantity"], 50.0)
        self.assertTrue(apr["approval_id"].startswith("apr:"))
        self.assertTrue(bool(apr["approval_expires_at"]))
        self.assertTrue(bool(apr["approved_at"]))

    # --- Validation: missing / bad approval ---
    def test_missing_approval_blocks(self):
        result = validate_paper_sell_approval_v1(None, symbol="AAPL", quantity=10)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "approval_missing")

    def test_empty_approval_blocks(self):
        result = validate_paper_sell_approval_v1({}, symbol="AAPL", quantity=10)
        self.assertFalse(result["valid"])

    def test_non_approved_status_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        apr["approval_status"] = "PENDING"
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10)
        self.assertFalse(result["valid"])
        self.assertIn("APPROVAL_NOT_ACTIVE", result["reason"])

    def test_expired_approval_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10, expires_in_minutes=-1)
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "expired")

    def test_consumed_approval_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        apr["consumed_at"] = "2026-01-01T00:00:00Z"
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "already_consumed")

    def test_revoked_approval_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        apr["revoked_at"] = "2026-01-01T00:00:00Z"
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "revoked")

    # --- Validation: mismatch ---
    def test_symbol_mismatch_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        result = validate_paper_sell_approval_v1(apr, symbol="MSFT", quantity=10)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "symbol_mismatch")

    def test_side_mismatch_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10, side="BUY")
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "side_mismatch")

    def test_quantity_exceeded_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=15)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "quantity_exceeded")

    def test_account_mismatch_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10, approved_account="A1")
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10, account="A2")
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "account_mismatch")

    def test_decision_mismatch_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10, approved_decision_id="D1")
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10, decision_id="D2")
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "decision_mismatch")

    def test_missing_approved_by_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        apr["approved_by"] = ""
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "approved_by")

    # --- Safety gates ---
    def test_kill_switch_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10, kill_switch_active=True)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "kill_switch")

    def test_live_endpoint_blocks(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=10, live_endpoint_detected=True)
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocker"], "live_endpoint")

    # --- Valid approval ---
    def test_valid_approval_passes(self):
        apr = build_paper_sell_approval_v1(approved_by="trader1", approved_symbol="AAPL", approved_quantity=50)
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=30)
        self.assertTrue(result["valid"])
        self.assertEqual(result["approval_id"], apr["approval_id"])

    def test_valid_approval_at_max_quantity(self):
        apr = build_paper_sell_approval_v1(approved_by="trader1", approved_symbol="AAPL", approved_quantity=50)
        result = validate_paper_sell_approval_v1(apr, symbol="AAPL", quantity=50)
        self.assertTrue(result["valid"])

    # --- Consumption ---
    def test_consume_sets_status_and_intent(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        consumed = consume_paper_sell_approval_v1(apr, order_intent_id="intent-1")
        self.assertEqual(consumed["approval_status"], "CONSUMED")
        self.assertEqual(consumed["consumed_by_order_intent_id"], "intent-1")
        self.assertTrue(bool(consumed["consumed_at"]))

    def test_consumed_cannot_be_validated(self):
        apr = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        consumed = consume_paper_sell_approval_v1(apr, order_intent_id="intent-1")
        result = validate_paper_sell_approval_v1(consumed, symbol="AAPL", quantity=10)
        self.assertFalse(result["valid"])
        self.assertIn("NOT_ACTIVE", result["reason"])

    # --- Idempotency ---
    def test_approvals_are_unique(self):
        a1 = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        a2 = build_paper_sell_approval_v1(approved_by="h", approved_symbol="AAPL", approved_quantity=10)
        self.assertNotEqual(a1["approval_id"], a2["approval_id"])


class _FakeBroker:
    def __init__(self, *, submit_result=None, submit_exception=None, open_orders=None, closed_orders=None):
        self.submit_calls = 0
        self.submit_result = submit_result
        self.submit_exception = submit_exception
        self.submitted_orders = []
        self.order_lookup_calls = 0
        self.open_orders = list(open_orders or [])
        self.closed_orders = list(closed_orders or [])

    def submit_paper_order(self, order):
        self.submit_calls += 1
        self.submitted_orders.append(dict(order))
        if self.submit_exception is not None:
            raise self.submit_exception
        if self.submit_result is not None:
            return dict(self.submit_result)
        return {"ok": True, "order": {"id": "order-1", "status": "submitted", "client_order_id": order.get("client_order_id")}}

    def orders(self, *, status="open", limit=50):
        self.order_lookup_calls += 1
        return {"ok": True, "orders": self.open_orders if status == "open" else self.closed_orders}


class ProductionApprovalEnforcementTests(unittest.TestCase):
    def _engine(self):
        engine = object.__new__(PaperAutopilotEngine)
        engine.alpaca_paper_broker = _FakeBroker()
        engine._runtime_state = {}
        engine.learned_exit_validation_kill_switch = False
        engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "live_endpoint_detected": False}
        return engine

    def test_no_production_bypass_exists(self):
        """Approval enforcement cannot be disabled through a runtime attribute."""
        engine = self._engine()
        engine._runtime_state["paper_sell_approvals"] = {}
        result = engine._validate_sell_approval({"symbol": "AAPL", "quantity": 10})
        self.assertFalse(result["valid"])
        # Setting the old bypass attribute must not change the result.
        engine.approval_enforcement = False
        result2 = engine._validate_sell_approval({"symbol": "AAPL", "quantity": 10})
        self.assertFalse(result2["valid"])
        self.assertNotEqual(result2.get("reason", ""), "APPROVAL_ENFORCEMENT_BYPASSED_TEST_ONLY")

    def test_missing_approval_blocks_authorized_lane_exit(self):
        engine = self._engine()
        result = engine._submit_authorized_lane_exit(
            {"symbol": "AAPL", "position_id": "p1", "quantity": 10, "lane_id": "DAY", "client_order_id": "c1"},
            {"qty_available": 10, "qty": 10},
            "fixture",
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result.get("submitted", True))
        self.assertIn("APPROVAL", result["reason"])
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 0)

    def test_missing_approval_blocks_guarded_learned_exit(self):
        engine = self._engine()
        result = engine._submit_guarded_learned_exit_sell(
            {"symbol": "AAPL", "position_id": "p1", "quantity": 10, "lane_id": "DAY", "client_order_id": "c1"},
            {"symbol": "AAPL", "price": 10.0},
            {"qty_available": 10, "qty": 10},
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result.get("submitted", True))
        self.assertIn("APPROVAL", result["reason"])
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 0)

    def test_valid_approval_allows_authorized_lane_exit(self):
        engine = self._engine()
        engine._runtime_state["paper_sell_approvals"] = {
            "AAPL": build_paper_sell_approval_v1(
                approved_by="human", approved_symbol="AAPL", approved_quantity=10, approved_decision_id="p1",
            ),
        }
        from unittest.mock import patch
        with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "DAY"}):
            result = engine._submit_authorized_lane_exit(
                {"symbol": "AAPL", "position_id": "p1", "quantity": 10, "lane_id": "DAY", "client_order_id": "c1"},
                {"qty_available": 10, "qty": 10},
                "fixture",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["submitted"])
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 1)

    def test_consumed_approval_cannot_be_reused(self):
        engine = self._engine()
        engine._runtime_state["paper_sell_approvals"] = {
            "AAPL": build_paper_sell_approval_v1(
                approved_by="human", approved_symbol="AAPL", approved_quantity=10, approved_decision_id="p1",
            ),
        }
        from unittest.mock import patch
        with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "DAY"}):
            result1 = engine._submit_authorized_lane_exit(
                {"symbol": "AAPL", "position_id": "p1", "quantity": 10, "lane_id": "DAY", "client_order_id": "c1"},
                {"qty_available": 10, "qty": 10},
                "fixture",
            )
            self.assertTrue(result1["ok"])
            result2 = engine._submit_authorized_lane_exit(
                {"symbol": "AAPL", "position_id": "p1", "quantity": 10, "lane_id": "DAY", "client_order_id": "c2"},
                {"qty_available": 10, "qty": 10},
                "fixture",
            )
        self.assertFalse(result2["ok"])
        self.assertFalse(result2.get("submitted", True))
        self.assertTrue(result2["reason"].startswith("unresolved_sell_intent:"))
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 1)

    def test_ambiguous_lane_submission_blocks_second_sell_across_restart(self):
        engine = self._engine()
        engine.alpaca_paper_broker = _FakeBroker(submit_exception=TimeoutError("response lost after submit"))
        engine._runtime_state["paper_sell_approvals"] = {
            "AAPL": build_paper_sell_approval_v1(
                approved_by="human", approved_symbol="AAPL", approved_quantity=10, approved_decision_id="p1",
            ),
        }
        from unittest.mock import patch
        row = {"symbol": "AAPL", "position_id": "p1", "quantity": 10, "lane_id": "DAY", "client_order_id": "day-exit-1"}
        with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "DAY"}):
            first = engine._submit_authorized_lane_exit(row, {"qty_available": 10, "qty": 10}, "fixture")
            second = engine._submit_authorized_lane_exit(row, {"qty_available": 10, "qty": 10}, "fixture")
        self.assertFalse(first["submitted"])
        self.assertEqual(first["reason"].split(":", 1)[0], "lane_exit_submit_exception")
        self.assertFalse(second["submitted"])
        self.assertIn("unresolved_sell_intent", second["reason"])
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 1)
        issued_client_order_id = engine.alpaca_paper_broker.submitted_orders[0]["client_order_id"]
        intent = engine._runtime_state["paper_sell_order_intents"][issued_client_order_id]
        self.assertEqual(intent["status"], "AMBIGUOUS_SUBMISSION")
        self.assertEqual(intent["client_order_id"], issued_client_order_id)

        # Restoring worker state preserves the original intent and cannot
        # create a new approval or a second client order id.
        restarted = self._engine()
        restarted.alpaca_paper_broker = engine.alpaca_paper_broker
        restarted._runtime_state = dict(engine._runtime_state)
        with patch.object(restarted, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": "DAY"}):
            after_restart = restarted._submit_authorized_lane_exit(row, {"qty_available": 10, "qty": 10}, "fixture")
        self.assertFalse(after_restart["submitted"])
        self.assertIn("unresolved_sell_intent", after_restart["reason"])
        self.assertEqual(restarted.alpaca_paper_broker.submit_calls, 1)
        self.assertEqual(
            restarted._runtime_state["paper_sell_order_intents"][issued_client_order_id]["client_order_id"],
            issued_client_order_id,
        )

    def test_day_swing_and_crypto_writers_share_ambiguity_duplicate_guard(self):
        from unittest.mock import patch
        for lane in ("DAY", "SWING", "CRYPTO"):
            with self.subTest(lane=lane):
                engine = self._engine()
                engine.alpaca_paper_broker = _FakeBroker(submit_exception=TimeoutError("ambiguous"))
                engine._runtime_state["paper_sell_approvals"] = {
                    "AAPL": build_paper_sell_approval_v1(
                        approved_by="human", approved_symbol="AAPL", approved_quantity=10, approved_decision_id=f"{lane}-p",
                    ),
                }
                row = {"symbol": "AAPL", "position_id": f"{lane}-p", "quantity": 10, "lane_id": lane, "client_order_id": f"{lane}-intent"}
                with patch.object(engine, "_authorized_lane_exit_contract", return_value={"authorized": True, "lane_id": lane}):
                    engine._submit_authorized_lane_exit(row, {"qty_available": 10, "qty": 10}, "fixture")
                    blocked = engine._submit_authorized_lane_exit(row, {"qty_available": 10, "qty": 10}, "fixture")
                self.assertFalse(blocked["submitted"])
                self.assertIn("unresolved_sell_intent", blocked["reason"])
                self.assertEqual(engine.alpaca_paper_broker.submit_calls, 1)

    def test_learned_insufficient_quantity_never_directly_retries_adapter(self):
        engine = self._engine()
        engine.alpaca_paper_broker = _FakeBroker(submit_result={"ok": False, "error": "insufficient qty available: 5"})
        engine.learned_exit_validation_bucket_configured = True
        engine.learned_exit_validation_max_exits_per_day = 1
        engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "live_endpoint_detected": False, "broker_execution_enabled": True}
        engine._runtime_state["paper_sell_approvals"] = {
            "AAPL": build_paper_sell_approval_v1(
                approved_by="human", approved_symbol="AAPL", approved_quantity=10, approved_decision_id="p1",
            ),
        }
        engine._learned_exit_candidate = lambda *_args: {
            "eligible": True, "symbol": "AAPL", "position_id": "p1", "normalized_sell_qty": 10.0,
            "qty": 10.0, "policy": "fixture", "horizon": "day_trade",
        }
        engine._broker_pending_sell_exists = lambda _symbol: (False, "")
        engine._append_learned_exit_event = lambda _event: None
        result = engine._submit_guarded_learned_exit_sell(
            {"symbol": "AAPL", "position_id": "p1", "quantity": 10},
            {"symbol": "AAPL", "price": 10.0},
            {"qty_available": 10, "qty": 10},
        )
        self.assertFalse(result["submitted"])
        self.assertEqual(result["reason"], "broker_reconciliation_required_before_retry")
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 1)
        intent = next(iter(engine._runtime_state["paper_sell_order_intents"].values()))
        self.assertEqual(intent["status"], "BROKER_RECONCILIATION_REQUIRED")
        self.assertFalse(intent["retry_eligible"])

    def test_ambiguous_intent_queries_original_client_order_without_resubmission(self):
        engine = self._engine()
        engine.alpaca_paper_broker = _FakeBroker(
            open_orders=[{"id": "broker-order-1", "symbol": "AAPL", "side": "sell", "status": "accepted", "client_order_id": "intent-1"}],
        )
        engine._runtime_state["paper_sell_order_intents"] = {
            "intent-1": {
                "order_intent_id": "intent-1", "symbol": "AAPL", "position_id": "p1",
                "client_order_id": "intent-1", "status": "AMBIGUOUS_SUBMISSION",
                "order": {"symbol": "AAPL", "side": "sell", "client_order_id": "intent-1"},
            },
        }
        outcome = engine._refresh_unresolved_sell_intents()
        intent = engine._runtime_state["paper_sell_order_intents"]["intent-1"]
        self.assertEqual(outcome["checked"], 1)
        self.assertEqual(engine.alpaca_paper_broker.order_lookup_calls, 2)
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 0)
        self.assertEqual(intent["status"], "SUBMITTED")
        self.assertEqual(intent["reconciliation_status"], "ORIGINAL_ORDER_FOUND")


if __name__ == "__main__":
    unittest.main()
