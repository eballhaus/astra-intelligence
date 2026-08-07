"""Native SWING/CRYPTO closure contracts stay on the shared sell lifecycle."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.paper_autopilot import PaperAutopilotEngine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _row(lane: str) -> dict:
    crypto = lane == "CRYPTO"
    position_id = f"{lane.lower()}-lifecycle-1"
    entry_order_id = f"{lane.lower()}-entry-order"
    entry_fill_id = f"{lane.lower()}-entry-fill"
    return {
        "position_id": position_id,
        "symbol": "BTC/USD" if crypto else "SWING",
        "asset_type": "crypto" if crypto else "stock",
        "status": "OPEN",
        "quantity": 1.234567 if crypto else 2.0,
        "lane_id": lane,
        "position_owner": lane,
        "exit_policy_owner": lane,
        "entry_order_id": entry_order_id,
        "entry_fill_id": entry_fill_id,
        "entry_price": 100.0,
        "broker_filled_avg_price": 100.0,
        "entry_price_verified": True,
        "entry_timestamp": "2026-08-01T14:00:00Z",
        "source_bucket": "paper_autopilot_candidate",
        "entry_metadata_generation": "V1_MANDATORY",
        "entry_metadata_json": json.dumps({
            "metadata_generation": "V1_MANDATORY",
            "candidate_id": f"{lane.lower()}-candidate-1",
            "lifecycle_id": position_id,
            "lane": lane,
            "broker_order_id": entry_order_id,
            "entry_fill_id": entry_fill_id,
            "exact_blockers": [],
        }),
        "row_json": "{}",
        "lifecycle_notes": "{}",
    }


class _Broker:
    def __init__(self, *, order_status: str = "accepted", symbol: str = "BTC/USD") -> None:
        self.order_status = order_status
        self.symbol = symbol
        self.submitted: list[dict] = []

    def submit_paper_order(self, order):
        self.submitted.append(dict(order))
        return {"ok": True, "order": {"id": "exit-1", "status": self.order_status, "client_order_id": order["client_order_id"]}}

    def crypto_capability_status(self, _probe=False):
        return {
            "crypto_trading_supported": True,
            "supported_pairs": ["BTC/USD"],
            "tradable_pairs": ["BTC/USD"],
            "paper_mode_verified": True,
        }

    def order(self, order_id):
        return {
            "ok": True,
            "order": {
                "id": order_id,
                "symbol": self.symbol,
                "status": self.order_status,
                "filled_qty": "1.234567",
                "filled_avg_price": "101.0",
                "filled_at": "2026-08-05T12:00:00Z",
            },
        }

    def positions(self):
        return {"ok": True, "positions": []}


class _ResidualBroker(_Broker):
    def __init__(self, *, quantity: str, market_value: str) -> None:
        super().__init__(order_status="filled", symbol="SWING")
        self.quantity = quantity
        self.market_value = market_value

    def positions(self):
        return {"ok": True, "positions": [{
            "symbol": "SWING", "qty": self.quantity, "qty_available": self.quantity,
            "market_value": self.market_value, "asset_class": "us_equity",
        }]}

    def order(self, order_id):
        payload = super().order(order_id)
        payload["order"]["client_order_id"] = "swing-exit"
        return payload


class _TradeIntel:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record_trade(self, row: dict) -> None:
        self.records.append(dict(row))


class NativeSwingCryptoExitClosureTests(unittest.TestCase):
    def _engine(self, root: pathlib.Path | None = None, broker=None, trade_intel=None) -> PaperAutopilotEngine:
        if root is None:
            engine = object.__new__(PaperAutopilotEngine)
            engine._runtime_state = {}
        else:
            engine = PaperAutopilotEngine(
                db_path=str(root / "paper.db"),
                state_path=str(root / "state.json"),
                alpaca_paper_broker=broker or _Broker(),
                trade_intel=trade_intel,
            )
            engine._position_tracker = None
            engine.trade_lifecycle_excursion_suite = None
        engine.alpaca_paper_broker = broker or getattr(engine, "alpaca_paper_broker", None) or _Broker()
        engine.learned_exit_validation_kill_switch = False
        engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "broker_live_endpoint_allowed": False}
        engine._native_lane_exit_session_status = lambda: {"market_session_mode": "regular_market", "paper_order_submission_allowed": True}
        return engine

    @staticmethod
    def _capital(_lane):
        return {"capital_configured": True, "capital_configuration_status": "CONFIGURED"}

    def test_verified_native_swing_authorizes_without_day_timing(self):
        engine = self._engine(broker=_Broker())
        row = _row("SWING")
        with patch("engine.paper_autopilot.lane_capital_status", self._capital):
            contract = engine._authorized_lane_exit_contract(row)
        self.assertTrue(contract["authorized"], contract)
        self.assertTrue(contract["native_natural_exit_authorized"])
        self.assertEqual(engine._lane_forced_exit_reason(row), "")

    def test_native_swing_submits_through_shared_writer_without_human_approval(self):
        broker = _Broker()
        engine = self._engine(broker=broker)
        with patch("engine.paper_autopilot.lane_capital_status", self._capital):
            result = engine._submit_authorized_lane_exit(_row("SWING"), {"qty_available": 2.0}, "holding_window_expired")
        self.assertTrue(result["submitted"], result)
        self.assertEqual(len(broker.submitted), 1)
        self.assertTrue(broker.submitted[0]["native_lane_exit"])
        self.assertEqual(broker.submitted[0]["side"], "sell")

    def test_non_native_swing_classifications_remain_fail_closed(self):
        engine = self._engine(broker=_Broker())
        for field, value in (("legacy_imported", True), ("manual_exit", True), ("learned_exit_execution", True), ("reconstructed", True)):
            row = _row("SWING")
            row[field] = value
            with patch("engine.paper_autopilot.lane_capital_status", self._capital):
                contract = engine._authorized_lane_exit_contract(row)
            self.assertFalse(contract["authorized"], (field, contract))
            self.assertEqual(contract["reason"], "NON_NATIVE_EXIT_CLASSIFICATION")

    def test_non_native_source_bucket_cannot_gain_exit_authority(self):
        engine = self._engine(broker=_Broker())
        for source_bucket in ("manual_position", "learned_exit_experiment", "canary_import", "reconstructed_lifecycle", "ambiguous_row"):
            row = _row("SWING")
            row["source_bucket"] = source_bucket
            with patch("engine.paper_autopilot.lane_capital_status", self._capital):
                contract = engine._authorized_lane_exit_contract(row)
            self.assertFalse(contract["authorized"], (source_bucket, contract))
            self.assertEqual(contract["reason"], "NON_NATIVE_SOURCE_BUCKET")

    def test_native_crypto_is_24x7_and_requires_a_fresh_quote(self):
        broker = _Broker()
        engine = self._engine(broker=broker)
        engine._native_lane_exit_session_status = lambda: {"market_session_mode": "after_hours", "paper_order_submission_allowed": False}
        quote = {"timestamp": _now(), "price": 101.0, "bid": 100.9, "ask": 101.1}
        with patch("engine.paper_autopilot.lane_capital_status", self._capital):
            result = engine._submit_authorized_lane_exit(_row("CRYPTO"), {"qty_available": 1.234567}, "profit_protection", latest_quote=quote)
        self.assertTrue(result["submitted"], result)
        self.assertEqual(broker.submitted[0]["time_in_force"], "gtc")
        self.assertEqual(broker.submitted[0]["asset_class"], "crypto")
        self.assertNotIn("REGULAR_SESSION_REQUIRED", str(result))

        stale = dict(quote)
        stale["timestamp"] = "2020-01-01T00:00:00Z"
        fresh_engine = self._engine(broker=_Broker())
        with patch("engine.paper_autopilot.lane_capital_status", self._capital):
            rejected = fresh_engine._submit_authorized_lane_exit(_row("CRYPTO"), {"qty_available": 1.234567}, "profit_protection", latest_quote=stale)
        self.assertFalse(rejected["submitted"])
        self.assertEqual(rejected["reason"], "REJECTED_STALE_EXECUTABLE_CRYPTO_QUOTE")

    def test_crypto_capability_and_non_native_rows_fail_closed(self):
        class UnsupportedBroker(_Broker):
            def crypto_capability_status(self, _probe=False):
                return {"crypto_trading_supported": False, "exact_blocker": "crypto_trading_not_supported"}

        engine = self._engine(broker=UnsupportedBroker())
        with patch("engine.paper_autopilot.lane_capital_status", self._capital):
            blocked = engine._authorized_lane_exit_contract(_row("CRYPTO"))
        self.assertFalse(blocked["authorized"])
        self.assertEqual(blocked["reason"], "crypto_trading_not_supported")

        manual = _row("CRYPTO")
        manual["manual_exit"] = True
        manual_engine = self._engine(broker=_Broker())
        with patch("engine.paper_autopilot.lane_capital_status", self._capital):
            contract = manual_engine._authorized_lane_exit_contract(manual)
        self.assertFalse(contract["authorized"])
        self.assertEqual(contract["reason"], "NON_NATIVE_EXIT_CLASSIFICATION")

    def test_crypto_partial_fill_then_broker_zero_creates_one_truth_and_learning_ack(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            broker = _Broker(order_status="partially_filled")
            intel = _TradeIntel()
            engine = self._engine(root, broker, intel)
            row = _row("CRYPTO")
            with engine._connect() as conn:
                columns = ", ".join(row)
                placeholders = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO paper_positions ({columns}, created_at, updated_at) VALUES ({placeholders}, ?, ?)", (*row.values(), _now(), _now()))
                conn.commit()
            engine._runtime_state["authorized_lane_exit_pending"] = {
                "exit-1": {"position_id": row["position_id"], "symbol": row["symbol"], "lane_id": "CRYPTO", "order_id": "exit-1", "client_order_id": "crypto-exit", "exit_reason": "profit_protection"}
            }
            partial = engine._refresh_authorized_lane_exit_pending()
            self.assertEqual(partial["pending"], 1)
            self.assertEqual(engine._runtime_state["native_lane_exit_lifecycle_v1"][row["position_id"]]["closure_state"], "PARTIALLY_FILLED")

            broker.order_status = "filled"
            closed = engine._refresh_authorized_lane_exit_pending()
            self.assertEqual(closed["filled"], 1)
            self.assertEqual(engine._runtime_state["native_lane_exit_lifecycle_v1"][row["position_id"]]["closure_state"], "LEARNING_ACKNOWLEDGED")
            self.assertEqual(len(intel.records), 1)
            records = json.loads((root / "broker_truth_records_v1.json").read_text(encoding="utf-8"))["records"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["lane_id"], "CRYPTO")

            repeated = engine._refresh_authorized_lane_exit_pending()
            self.assertEqual(repeated["filled"], 0)
            self.assertEqual(len(intel.records), 1)

    def test_swing_partial_fill_then_broker_zero_creates_one_truth_and_learning_ack(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            broker = _Broker(order_status="partially_filled", symbol="SWING")
            intel = _TradeIntel()
            engine = self._engine(root, broker, intel)
            row = _row("SWING")
            with engine._connect() as conn:
                columns = ", ".join(row)
                placeholders = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO paper_positions ({columns}, created_at, updated_at) VALUES ({placeholders}, ?, ?)", (*row.values(), _now(), _now()))
                conn.commit()
            engine._runtime_state["authorized_lane_exit_pending"] = {
                "exit-1": {"position_id": row["position_id"], "symbol": row["symbol"], "lane_id": "SWING", "order_id": "exit-1", "client_order_id": "swing-exit", "exit_reason": "holding_window_expired"}
            }
            self.assertEqual(engine._refresh_authorized_lane_exit_pending()["pending"], 1)
            broker.order_status = "filled"
            self.assertEqual(engine._refresh_authorized_lane_exit_pending()["filled"], 1)
            self.assertEqual(engine._runtime_state["native_lane_exit_lifecycle_v1"][row["position_id"]]["closure_state"], "LEARNING_ACKNOWLEDGED")
            self.assertEqual(len(intel.records), 1)

    def test_identity_linked_full_fill_with_broker_dust_closes_once_and_learns(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            broker = _ResidualBroker(quantity="0.0000003", market_value="0.00001")
            intel = _TradeIntel()
            engine = self._engine(root, broker, intel)
            row = _row("SWING")
            row["quantity"] = 1.2345673
            with engine._connect() as conn:
                columns = ", ".join(row)
                placeholders = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO paper_positions ({columns}, created_at, updated_at) VALUES ({placeholders}, ?, ?)", (*row.values(), _now(), _now()))
                conn.commit()
            engine._runtime_state["authorized_lane_exit_pending"] = {
                "exit-1": {"position_id": row["position_id"], "symbol": row["symbol"], "lane_id": "SWING", "order_id": "exit-1", "client_order_id": "swing-exit", "exit_reason": "holding_window_expired", "normalized_sell_qty": 1.234567}
            }

            result = engine._refresh_authorized_lane_exit_pending()

            self.assertEqual(result["filled"], 1)
            self.assertFalse(engine._runtime_state["authorized_lane_exit_pending"])
            self.assertEqual(engine._runtime_state["paper_sell_order_intents"]["swing-exit"]["status"], "CLOSED_DUST_SAFE_RECONCILED")
            state = engine._runtime_state["native_lane_exit_lifecycle_v1"][row["position_id"]]
            self.assertEqual(state["closure_state"], "LEARNING_ACKNOWLEDGED")
            records = json.loads((root / "broker_truth_records_v1.json").read_text(encoding="utf-8"))["records"]
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["broker_residual_zero_confirmed"])
            self.assertEqual(records[0]["canonical_dust_safe_closure"]["status"], "VERIFIED_CANONICAL_DUST_SAFE_CLOSURE")
            self.assertEqual(len(intel.records), 1)

    def test_meaningful_residual_cannot_use_dust_safe_closure(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            broker = _ResidualBroker(quantity="0.01", market_value="0.1")
            engine = self._engine(root, broker, _TradeIntel())
            row = _row("SWING")
            row["quantity"] = 1.234567
            with engine._connect() as conn:
                columns = ", ".join(row)
                placeholders = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO paper_positions ({columns}, created_at, updated_at) VALUES ({placeholders}, ?, ?)", (*row.values(), _now(), _now()))
                conn.commit()
            engine._runtime_state["authorized_lane_exit_pending"] = {
                "exit-1": {"position_id": row["position_id"], "symbol": row["symbol"], "lane_id": "SWING", "order_id": "exit-1", "client_order_id": "swing-exit", "exit_reason": "holding_window_expired", "normalized_sell_qty": 1.234567}
            }

            result = engine._refresh_authorized_lane_exit_pending()

            self.assertEqual(result["filled"], 0)
            self.assertEqual(result["pending"], 1)
            self.assertFalse((root / "broker_truth_records_v1.json").exists())
            state = engine._runtime_state["native_lane_exit_lifecycle_v1"][row["position_id"]]
            self.assertEqual(state["closure_state"], "AWAITING_BROKER_ZERO")

    def test_mismatched_broker_order_cannot_close_same_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            broker = _Broker(order_status="filled", symbol="OTHER")
            engine = self._engine(root, broker, _TradeIntel())
            row = _row("SWING")
            with engine._connect() as conn:
                columns = ", ".join(row)
                placeholders = ", ".join("?" for _ in row)
                conn.execute(f"INSERT INTO paper_positions ({columns}, created_at, updated_at) VALUES ({placeholders}, ?, ?)", (*row.values(), _now(), _now()))
                conn.commit()
            engine._runtime_state["authorized_lane_exit_pending"] = {
                "exit-1": {"position_id": row["position_id"], "symbol": row["symbol"], "lane_id": "SWING", "order_id": "exit-1", "client_order_id": "swing-exit", "exit_reason": "fixture"}
            }
            result = engine._refresh_authorized_lane_exit_pending()
            self.assertEqual(result["pending"], 1)
            state = engine._runtime_state["native_lane_exit_lifecycle_v1"][row["position_id"]]
            self.assertEqual(state["closure_state"], "EXIT_BLOCKED_IDENTITY")
            self.assertEqual(state["exact_blocker"], "BROKER_ORDER_SYMBOL_MISMATCH")

    def test_native_exit_ledger_survives_worker_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            engine = self._engine(root, _Broker())
            engine._record_native_lane_exit_state(_row("SWING"), state="SELL_SUBMITTED", decision="EXIT_READY")
            engine._save_state_file(worker_owned=True)
            restored = self._engine(root, _Broker())
            self.assertEqual(restored._runtime_state["native_lane_exit_lifecycle_v1"]["swing-lifecycle-1"]["closure_state"], "SELL_SUBMITTED")

    def test_final_broker_adapter_accepts_a_valid_native_crypto_exit(self):
        broker = AlpacaPaperBroker()
        broker.safety_status = lambda: {"broker_execution_enabled": True, "paper_mode_verified": True, "live_endpoint_detected": False}
        broker.account = lambda: {"ok": True}
        broker.crypto_capability_status = lambda _probe=False: {"crypto_trading_supported": True, "supported_pairs": ["BTC/USD"], "tradable_pairs": ["BTC/USD"]}
        submitted: list[dict] = []
        broker._request = lambda method, _path, payload=None: (submitted.append(dict(payload or {})) or True, {"id": "exit-1", "status": "accepted"}, "")
        result = broker.submit_paper_order({
            "symbol": "BTC/USD", "asset_class": "crypto", "side": "sell", "type": "market", "time_in_force": "gtc", "qty": 1.234567,
            "paper_only": True, "native_lane_exit": True, "native_exit_contract_verified": True,
            "existing_exit_signal_verified": True, "paper_sell_approval_intent_id": "native-crypto-exit",
            "crypto_paper_activation_passed": True, "crypto_execution_integrity_passed": True,
            "broker_reconciliation_ok": True, "timestamp": _now(), "price": 101.0, "bid": 100.9, "ask": 101.1,
        })
        self.assertTrue(result["ok"], result)
        self.assertEqual(submitted[0]["symbol"], "BTC/USD")


if __name__ == "__main__":
    unittest.main()
