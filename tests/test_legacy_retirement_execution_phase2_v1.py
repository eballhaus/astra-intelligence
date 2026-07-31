"""Phase 2 coverage for imported-legacy paper sell lifecycle reconciliation."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
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

    def latest_quote(self, _symbol):
        return {"ok": True, "quote": {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "bid_price": 10, "ask_price": 10.1}}


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

    def test_filled_order_with_dust_residual_is_never_labelled_broker_zero(self):
        self.engine._process_legacy_retirement_sell_intents()
        self.broker.order_row.update({"status": "filled", "filled_qty": "2"})
        self.broker.position_rows = [{"symbol": "AAL", "asset_id": "asset-1", "qty": "0.000001", "qty_available": "0.000001"}]
        self.engine._refresh_authorized_lane_exit_pending()
        intent = self.engine._paper_sell_order_intents()[self.intent_id]
        self.assertEqual(intent["status"], "BROKER_HELD_DUST")
        self.assertFalse(intent["broker_zero_confirmed"])
        self.assertEqual(intent["first_causal_blocker"], "BROKER_HELD_DUST_RESIDUAL")
        self.assertNotIn(self.intent_id, self.engine._runtime_state.get("legacy_retirement_archive_v1") or {})

    def test_terminal_dust_mislabel_is_repaired_from_verified_broker_snapshot(self):
        self.engine._persist_sell_intent(
            self.intent_id,
            status="BROKER_ZERO_CONFIRMED",
            broker_order_id="sell-1",
            reconciliation_status="ORIGINAL_ORDER_FILLED",
        )
        repaired = self.engine._reconcile_legacy_retirement_terminal_states(
            {"AAL": {"symbol": "AAL", "qty": "0.000001", "qty_available": "0.000001"}},
            broker_positions_verified=True,
        )
        intent = self.engine._paper_sell_order_intents()[self.intent_id]
        self.assertEqual(repaired["corrected_to_dust"], 1)
        self.assertEqual(intent["status"], "BROKER_HELD_DUST")
        self.assertFalse(intent["broker_zero_confirmed"])

    def test_terminal_rejection_is_bounded_retry(self):
        self.engine._process_legacy_retirement_sell_intents()
        self.broker.order_row.update({"status": "rejected", "reject_reason": "broker rejected"})
        self.engine._refresh_authorized_lane_exit_pending()
        intent = self.engine._paper_sell_order_intents()[self.intent_id]
        self.assertEqual(intent["status"], "RETRY_PENDING")
        self.assertEqual(intent["retry_count"], 1)

    def test_quote_refresh_produces_provider_native_evidence_before_submission(self):
        self.engine._legacy_regular_session_open = lambda: False
        refreshed = self.engine._refresh_legacy_retirement_quote_evidence()
        self.assertEqual(refreshed["reason"], "MARKET_CLOSED_OR_QUOTE_ADAPTER_UNAVAILABLE")
        self.engine._legacy_regular_session_open = lambda: True
        refreshed = self.engine._refresh_legacy_retirement_quote_evidence()
        self.assertEqual(refreshed["refreshed"], 1)
        self.assertIn("AAL", self.engine._runtime_state["legacy_retirement_quote_evidence_v1"])

    def test_quote_evidence_survives_restart_and_advances_the_same_intent(self):
        self.engine._runtime_state["legacy_retirement_quote_evidence_v1"] = {}
        self.engine._legacy_regular_session_open = lambda: True
        refreshed = self.engine._refresh_legacy_retirement_quote_evidence()
        self.assertEqual(refreshed["refreshed"], 1)
        self.engine._save_state_file()

        restarted = PaperAutopilotEngine(
            db_path=str(Path(self.tmp.name) / "memory.sqlite"),
            state_path=str(Path(self.tmp.name) / "state.json"),
            alpaca_paper_broker=self.broker,
        )
        restarted._alpaca_safety_snapshot = self.engine._alpaca_safety_snapshot
        restarted._legacy_regular_session_open = lambda: True
        restarted._runtime_state["market_session_open"] = True
        self.assertIn("AAL", restarted._runtime_state["legacy_retirement_quote_evidence_v1"])

        result = restarted._process_legacy_retirement_sell_intents()
        self.assertEqual(result["submitted"], 1)
        self.assertEqual(self.broker.submit_calls, 1)
        self.assertEqual(restarted._paper_sell_order_intents()[self.intent_id]["status"], "BROKER_ACKNOWLEDGED")

    def test_quote_provider_exception_is_visible_and_does_not_stop_other_intents(self):
        self.engine._persist_sell_intent(
            "legacy-phase2-bad", symbol="BAD", position_id="asset-bad", legacy_imported=True,
            legacy_imported_retirement=True, legacy_lifecycle_id="legacy-lifecycle-bad",
            client_order_id="legacy-phase2-bad", status="WAITING_FOR_FRESH_EVIDENCE",
            order={"symbol": "BAD", "side": "sell", "qty": 1, "paper_only": True},
        )
        self.engine._legacy_regular_session_open = lambda: True

        def latest_quote(symbol):
            if symbol == "BAD":
                raise RuntimeError("malformed quote response")
            return {"ok": True, "quote": {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "bid_price": 10, "ask_price": 10.1}}

        self.broker.latest_quote = latest_quote
        refreshed = self.engine._refresh_legacy_retirement_quote_evidence()
        self.assertEqual(refreshed["symbol_results"]["AAL"]["status"], "ACCEPTED_PROVIDER_NATIVE_QUOTE")
        self.assertEqual(refreshed["symbol_results"]["BAD"]["first_causal_blocker"], "LEGACY_RETIREMENT_QUOTE_PROVIDER_EXCEPTION")
        self.assertIn("AAL", self.engine._runtime_state["legacy_retirement_quote_evidence_v1"])

    def test_one_intent_processing_failure_does_not_stop_the_remaining_batch(self):
        self.engine._persist_sell_intent(
            "legacy-phase2-bad", symbol="BAD", position_id="asset-bad", legacy_imported=True,
            legacy_imported_retirement=True, legacy_lifecycle_id="legacy-lifecycle-bad",
            client_order_id="legacy-phase2-bad", status="WAITING_FOR_FRESH_EVIDENCE",
            order={"symbol": "BAD", "side": "sell", "qty": 1, "paper_only": True},
        )
        original = self.engine._submit_imported_legacy_retirement_intent

        def submit(intent_id, intent):
            if intent_id == "legacy-phase2-bad":
                raise ValueError("malformed intent")
            return original(intent_id, intent)

        self.engine._submit_imported_legacy_retirement_intent = submit
        result = self.engine._process_legacy_retirement_sell_intents()
        self.assertEqual(result["submitted"], 1)
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(self.broker.submit_calls, 1)
        bad = self.engine._paper_sell_order_intents()["legacy-phase2-bad"]
        self.assertEqual(bad["first_causal_blocker"], "LEGACY_RETIREMENT_INTENT_PROCESSING_EXCEPTION")

    def test_external_worker_progress_and_quote_state_are_durable(self):
        self.engine._runtime_state["legacy_retirement_quote_refresh_v1"] = {"refreshed": 1}
        self.engine.record_external_worker_progress(
            worker_generation_id="generation-test",
            process_id=123,
            parent_process_id=45,
            cycle_count=9,
            phase="legacy_retirement_quote_refresh",
            cycle_started_at="2026-07-31T19:40:00Z",
            cycle_completed_at="2026-07-31T19:40:02Z",
            persist=True,
        )
        restarted = PaperAutopilotEngine(
            db_path=str(Path(self.tmp.name) / "memory.sqlite"),
            state_path=str(Path(self.tmp.name) / "state.json"),
            alpaca_paper_broker=self.broker,
        )
        self.assertEqual(restarted._runtime_state["worker_generation_id"], "generation-test")
        self.assertEqual(restarted._runtime_state["worker_cycle_phase"], "legacy_retirement_quote_refresh")
        self.assertEqual(restarted._runtime_state["legacy_retirement_quote_refresh_v1"]["refreshed"], 1)

    def test_api_control_write_preserves_worker_owned_quote_evidence(self):
        self.engine._runtime_state["legacy_retirement_quote_evidence_v1"] = {"AAL": {"provider_quote_timestamp": "2026-07-31T19:40:00Z"}}
        self.engine._save_state_file()
        api_engine = PaperAutopilotEngine(
            db_path=str(Path(self.tmp.name) / "memory.sqlite"),
            state_path=str(Path(self.tmp.name) / "state.json"),
            alpaca_paper_broker=self.broker,
        )
        api_engine._runtime_state["legacy_retirement_quote_evidence_v1"] = {}
        with patch.dict("os.environ", {"ASTRA_PROCESS_ROLE": "api"}):
            api_engine.toggle(False)
        reloaded = PaperAutopilotEngine(
            db_path=str(Path(self.tmp.name) / "memory.sqlite"),
            state_path=str(Path(self.tmp.name) / "state.json"),
            alpaca_paper_broker=self.broker,
        )
        self.assertIn("AAL", reloaded._runtime_state["legacy_retirement_quote_evidence_v1"])


if __name__ == "__main__":
    unittest.main()
