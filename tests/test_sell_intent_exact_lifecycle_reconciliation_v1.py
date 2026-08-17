"""Regression coverage for exact-lifecycle paper sell-intent reconciliation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.paper_autopilot import PaperAutopilotEngine


class _FilledOrderBroker:
    def __init__(self, order: dict):
        self._order = dict(order)
        self.order_calls = 0
        self.submit_calls = 0

    def order(self, order_id: str) -> dict:
        self.order_calls += 1
        return {"ok": True, "order": {"id": order_id, **self._order}}

    def submit_paper_order(self, _order: dict) -> dict:
        self.submit_calls += 1
        raise AssertionError("sell-intent reconciliation must not submit an order")


class _ClientLookupBroker:
    def __init__(self, filled_order: dict):
        self._filled_order = dict(filled_order)
        self.order_calls = 0
        self.submit_calls = 0

    def orders(self, *, status: str, limit: int) -> dict:
        self.order_calls += 1
        return {"ok": True, "orders": [] if status == "open" else [self._filled_order]}

    def submit_paper_order(self, _order: dict) -> dict:
        self.submit_calls += 1
        raise AssertionError("sell-intent reconciliation must not submit an order")


class SellIntentExactLifecycleReconciliationTests(unittest.TestCase):
    def _engine(self) -> PaperAutopilotEngine:
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {"paper_sell_order_intents": {}, "learned_exit_pending_sells": {}}
        engine.alpaca_paper_broker = None
        engine.paper_mode = True
        engine._enabled = True
        engine._adaptive_learning_capacity_policy = {}
        return engine

    @staticmethod
    def _intent(
        *,
        symbol: str = "PTON",
        position_id: str = "old-position",
        status: str = "SUBMITTED",
        broker_order_id: str = "old-order",
    ) -> dict:
        return {
            "order_intent_id": "old-intent",
            "symbol": symbol,
            "position_id": position_id,
            "client_order_id": "old-intent",
            "broker_order_id": broker_order_id,
            "status": status,
            "order": {"symbol": symbol, "position_id": position_id, "side": "sell"},
        }

    def test_filled_order_terminalizes_intent_without_claiming_lifecycle_closure(self):
        engine = self._engine()
        engine.alpaca_paper_broker = _FilledOrderBroker(
            {
                "symbol": "PTON",
                "status": "filled",
                "filled_qty": "15.219178",
                "filled_avg_price": "6.75",
                "filled_at": "2026-08-17T19:55:00Z",
            },
        )
        engine._runtime_state["paper_sell_order_intents"] = {"old-intent": self._intent()}

        outcome = engine._refresh_unresolved_sell_intents()
        intent = engine._runtime_state["paper_sell_order_intents"]["old-intent"]

        self.assertEqual(outcome, {"checked": 1, "active": 0, "ambiguous": 0})
        self.assertEqual(intent["status"], "BROKER_FILLED_INTENT_RECONCILED")
        self.assertEqual(intent["reconciliation_status"], "ORIGINAL_ORDER_FILLED")
        self.assertEqual(intent["broker_order_status"], "FILLED")
        self.assertEqual(intent["filled_quantity"], 15.219178)
        self.assertTrue(intent["terminal"])
        self.assertEqual(intent["terminal_scope"], "SELL_INTENT_ONLY")
        self.assertTrue(intent["canonical_lifecycle_reconciliation_required"])
        self.assertNotIn(intent["status"], engine._UNRESOLVED_SELL_INTENT_STATES)
        self.assertNotIn("broker_zero_confirmed", intent)
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 0)

    def test_client_order_lookup_terminalizes_authoritatively_filled_original_order(self):
        engine = self._engine()
        engine.alpaca_paper_broker = _ClientLookupBroker(
            {
                "id": "broker-filled-order",
                "symbol": "PTON",
                "status": "filled",
                "client_order_id": "old-intent",
                "filled_qty": "15.219178",
            },
        )
        intent = self._intent(broker_order_id="")
        engine._runtime_state["paper_sell_order_intents"] = {"old-intent": intent}

        outcome = engine._refresh_unresolved_sell_intents()
        reconciled = engine._runtime_state["paper_sell_order_intents"]["old-intent"]

        self.assertEqual(outcome, {"checked": 1, "active": 0, "ambiguous": 0})
        self.assertEqual(reconciled["status"], "BROKER_FILLED_INTENT_RECONCILED")
        self.assertEqual(reconciled["broker_order_id"], "broker-filled-order")
        self.assertEqual(engine.alpaca_paper_broker.submit_calls, 0)

    def test_terminal_old_lifecycle_does_not_block_new_same_symbol_position(self):
        engine = self._engine()
        old = self._intent(status="BROKER_FILLED_INTENT_RECONCILED")
        old.update({"terminal": True, "reconciliation_status": "ORIGINAL_ORDER_FILLED"})
        engine._runtime_state["paper_sell_order_intents"] = {"old-intent": old}

        pending, reason = engine._position_pending_sell("PTON", "new-position")

        self.assertFalse(pending)
        self.assertEqual(reason, "")

    def test_same_position_unresolved_intent_still_blocks_duplicate_exit(self):
        engine = self._engine()
        engine._runtime_state["paper_sell_order_intents"] = {
            "current-intent": self._intent(position_id="current-position", status="SUBMITTED"),
        }

        pending, reason = engine._position_pending_sell("PTON", "current-position")

        self.assertTrue(pending)
        self.assertEqual(reason, "unresolved_sell_intent:current-intent:submitted")

    def test_unresolved_known_different_lifecycle_does_not_block_current_position(self):
        engine = self._engine()
        engine._runtime_state["paper_sell_order_intents"] = {
            "old-intent": self._intent(position_id="old-position", status="SUBMITTED"),
        }

        pending, reason = engine._position_pending_sell("PTON", "current-position")

        self.assertFalse(pending)
        self.assertEqual(reason, "")

    def test_identity_unavailable_same_symbol_intent_remains_explicitly_fail_closed(self):
        engine = self._engine()
        ambiguous = self._intent(position_id="", status="SUBMITTED")
        ambiguous["order"].pop("position_id")
        engine._runtime_state["paper_sell_order_intents"] = {"ambiguous-intent": ambiguous}

        pending, reason = engine._position_pending_sell("PTON", "current-position")

        self.assertTrue(pending)
        self.assertEqual(reason, "unresolved_sell_intent_identity_ambiguous:ambiguous-intent")

    def test_restart_preserves_terminal_old_intent_and_exact_same_lifecycle_guard(self):
        engine = self._engine()
        old = self._intent(status="BROKER_FILLED_INTENT_RECONCILED")
        old.update({"terminal": True, "reconciliation_status": "ORIGINAL_ORDER_FILLED"})
        engine._runtime_state["paper_sell_order_intents"] = {"old-intent": old}

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = str(Path(tmpdir) / "paper_autopilot_state.json")
            engine.state_path = state_path
            engine._save_state_file(worker_owned=True)
            restarted = self._engine()
            restarted.state_path = state_path
            restarted._load_state_file()

            self.assertEqual(
                restarted._runtime_state["paper_sell_order_intents"]["old-intent"]["status"],
                "BROKER_FILLED_INTENT_RECONCILED",
            )
            self.assertEqual(restarted._position_pending_sell("PTON", "new-position"), (False, ""))
            pending, reason = restarted._position_pending_sell("PTON", "old-position")
            self.assertTrue(pending)
            self.assertEqual(reason, "filled_sell_intent_awaiting_canonical_reconciliation:old-intent")

    def test_pton_and_rivn_equivalents_ignore_old_filled_lifecycle_intents(self):
        cases = (
            ("PTON", "ee9815f0-53a3-4206-b00c-4727899a87dd", "fc323f5f-474b-4590-907b-3deed8b30f8d"),
            ("RIVN", "62a16ff8-d983-4966-a53d-67530d73cc9b", "0275ee12-26f2-48f2-94e7-4fd920850a9a"),
        )
        for symbol, old_position, current_position in cases:
            with self.subTest(symbol=symbol):
                engine = self._engine()
                old = self._intent(symbol=symbol, position_id=old_position, status="BROKER_FILLED_INTENT_RECONCILED")
                old.update({"terminal": True, "reconciliation_status": "ORIGINAL_ORDER_FILLED"})
                engine._runtime_state["paper_sell_order_intents"] = {f"old-{symbol}": old}
                self.assertEqual(engine._position_pending_sell(symbol, current_position), (False, ""))

    def test_all_lane_exit_callers_keep_exact_same_position_duplicate_guard(self):
        for lane in ("DAY", "SWING", "SCALP", "CRYPTO"):
            with self.subTest(lane=lane):
                engine = self._engine()
                engine._runtime_state["paper_sell_order_intents"] = {
                    f"{lane}-intent": self._intent(position_id=f"{lane}-position", status="SUBMITTED"),
                }
                pending, reason = engine._position_pending_sell("PTON", f"{lane}-position")
                self.assertTrue(pending)
                self.assertIn(f"{lane}-intent", reason)


if __name__ == "__main__":
    unittest.main()
