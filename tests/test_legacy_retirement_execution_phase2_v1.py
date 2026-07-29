"""Phase 2 coverage for imported-legacy paper sell lifecycle reconciliation."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engine.astra_legacy_retirement_workflow_v1 import build_legacy_retirement_owner_approval_v1
from engine.paper_autopilot import PaperAutopilotEngine


class _Broker:
    def __init__(self):
        self.position_rows = [{"symbol": "AAL", "asset_id": "asset-1", "qty": "2", "qty_available": "2", "tradable": True}]
        self.order_row = {"id": "sell-1", "symbol": "AAL", "side": "sell", "status": "accepted", "client_order_id": ""}
        self.submit_calls = 0
        self.open_orders = []

    def account(self):
        return {"ok": True, "account_id": "paper-1"}

    def positions(self):
        return {"ok": True, "positions": list(self.position_rows)}

    def orders(self, status="open", limit=100):
        return {"ok": True, "orders": list(self.open_orders if status == "open" else [])}

    def submit_paper_order(self, order):
        self.submit_calls += 1
        self.order_row.update({"client_order_id": order["client_order_id"], "qty": order["qty"]})
        return {"ok": True, "order": dict(self.order_row)}

    def order(self, _order_id):
        return {"ok": True, "order": dict(self.order_row)}


class LegacyRetirementExecutionPhase2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="astra_legacy_phase2_")
        self.broker = _Broker()
        self.engine = PaperAutopilotEngine(
            db_path=str(Path(self.tmp.name) / "memory.sqlite"),
            state_path=str(Path(self.tmp.name) / "state.json"),
            alpaca_paper_broker=self.broker,
        )
        self.engine._alpaca_safety_snapshot = lambda: {
            "paper_mode_verified": True, "live_endpoint_detected": False,
            "broker_live_endpoint_allowed": False, "broker_execution_enabled": True,
        }
        approval = build_legacy_retirement_owner_approval_v1(
            owner="operator", symbols=["AAL"], approved_at="2026-07-29T12:00:00Z", paper_account="paper-1"
        )
        self.engine._runtime_state["legacy_retirement_execution_v1"] = {"owner_approval": approval, "intents": {}}
        self.engine._runtime_state["legacy_retirement_quote_evidence_v1"] = {
            "AAL": {"provider_quote_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        }
        self.engine._runtime_state["market_session_open"] = True
        self.intent_id = "legacy-phase2-aal"
        self.lifecycle_id = "legacy-lifecycle-aal"
        self.engine._persist_legacy_retirement_transition(self.lifecycle_id, status="LEGACY_EXIT_APPROVED", symbol="AAL")
        self.engine._persist_sell_intent(
            self.intent_id, symbol="AAL", position_id="asset-1", legacy_imported=True,
            legacy_imported_retirement=True, legacy_lifecycle_id=self.lifecycle_id,
            client_order_id="legacy-phase2-aal", status="WAITING_FOR_REGULAR_SESSION",
            order={"symbol": "AAL", "side": "sell", "qty": 2, "paper_only": True},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_submission_is_durable_and_idempotent(self):
        first = self.engine._process_legacy_retirement_sell_intents()
        second = self.engine._process_legacy_retirement_sell_intents()
        intent = self.engine._paper_sell_order_intents()[self.intent_id]
        self.assertEqual(first["submitted"], 1)
        self.assertEqual(second["submitted"], 0)
        self.assertEqual(self.broker.submit_calls, 1)
        self.assertEqual(intent["status"], "BROKER_ACKNOWLEDGED")
        self.assertEqual(intent["broker_order_id"], "sell-1")

    def test_account_mismatch_blocks_before_submit(self):
        self.broker.account = lambda: {"ok": True, "account_id": "wrong"}
        result = self.engine._process_legacy_retirement_sell_intents()
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(self.broker.submit_calls, 0)
        self.assertEqual(self.engine._paper_sell_order_intents()[self.intent_id]["first_causal_blocker"], "PAPER_ACCOUNT_MISMATCH")

    def test_closed_market_stays_waiting(self):
        self.engine._runtime_state["market_session_open"] = False
        self.engine._legacy_regular_session_open = lambda: False
        result = self.engine._process_legacy_retirement_sell_intents()
        self.assertEqual(result["waiting"], 1)
        self.assertEqual(self.broker.submit_calls, 0)
        self.assertEqual(self.engine._paper_sell_order_intents()[self.intent_id]["status"], "WAITING_FOR_REGULAR_SESSION")

    def test_existing_open_sell_blocks_duplicate_submission(self):
        self.broker.open_orders = [{"id": "other-sell", "symbol": "AAL", "side": "sell", "client_order_id": "other"}]
        result = self.engine._process_legacy_retirement_sell_intents()
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(self.broker.submit_calls, 0)
        self.assertEqual(self.engine._paper_sell_order_intents()[self.intent_id]["first_causal_blocker"], "EXISTING_SELL_ORDER")

    def test_submit_exception_is_ambiguous_and_never_resubmits(self):
        def raise_submit(_order):
            self.broker.submit_calls += 1
            raise TimeoutError("ambiguous")
        self.broker.submit_paper_order = raise_submit
        self.engine._process_legacy_retirement_sell_intents()
        self.engine._process_legacy_retirement_sell_intents()
        self.assertEqual(self.broker.submit_calls, 1)
        self.assertEqual(self.engine._paper_sell_order_intents()[self.intent_id]["status"], "AMBIGUOUS_SUBMISSION")

    def test_partial_then_broker_zero_closes_without_managed_close(self):
        self.engine._process_legacy_retirement_sell_intents()
        self.broker.order_row.update({"status": "partially_filled", "filled_qty": "1"})
        partial = self.engine._refresh_authorized_lane_exit_pending()
        intent = self.engine._paper_sell_order_intents()[self.intent_id]
        self.assertEqual(partial["pending"], 1)
        self.assertEqual(intent["status"], "PARTIALLY_FILLED")
        self.assertAlmostEqual(intent["remaining_quantity"], 1.0, places=5)
        self.broker.order_row.update({"status": "filled", "filled_qty": "2"})
        self.broker.position_rows = []
        closed = self.engine._refresh_authorized_lane_exit_pending()
        self.assertEqual(closed["filled"], 1)
        self.assertEqual(self.engine._paper_sell_order_intents()[self.intent_id]["status"], "CLOSED_LEGACY_RETIREMENT")
        self.assertTrue(self.engine._runtime_state["legacy_retirement_archive_v1"][self.intent_id]["current_logic_performance_excluded"])

    def test_terminal_rejection_is_bounded_retry(self):
        self.engine._process_legacy_retirement_sell_intents()
        self.broker.order_row.update({"status": "rejected", "reject_reason": "broker rejected"})
        self.engine._refresh_authorized_lane_exit_pending()
        intent = self.engine._paper_sell_order_intents()[self.intent_id]
        self.assertEqual(intent["status"], "RETRY_PENDING")
        self.assertEqual(intent["retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
