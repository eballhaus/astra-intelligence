from __future__ import annotations

import json
import inspect
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from engine.paper_autopilot import PaperAutopilotEngine


class _Broker:
    def positions(self):
        return {"ok": True, "positions": []}


class _FilledExitBroker(_Broker):
    def order(self, order_id):
        return {
            "ok": True,
            "order": {
                "id": order_id, "symbol": "AAPL", "status": "filled",
                "filled_qty": "1", "filled_avg_price": "101",
                "filled_at": "2026-07-31T15:00:00Z",
            },
        }


class _TradeIntel:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record_trade(self, row: dict) -> None:
        self.records.append(dict(row))


class StrictTruthPromotionRecoveryTests(unittest.TestCase):
    def _engine(self, root: pathlib.Path, trade_intel: _TradeIntel) -> PaperAutopilotEngine:
        engine = PaperAutopilotEngine(
            db_path=str(root / "paper.db"),
            state_path=str(root / "state.json"),
            alpaca_paper_broker=_Broker(),
            trade_intel=trade_intel,
        )
        engine._position_tracker = None
        engine.trade_lifecycle_excursion_suite = None
        return engine

    @staticmethod
    def _open_row(lane: str = "SCALP") -> dict:
        return {
            "position_id": "position-1",
            "symbol": "BTC/USD" if lane == "CRYPTO" else "AAPL",
            "asset_type": "crypto" if lane == "CRYPTO" else "stock",
            "lane_id": lane,
            "quantity": 1.0,
            "entry_price": 100.0,
            "entry_timestamp": "2026-07-31T14:00:00Z",
            "entry_order_id": "entry-order-1",
            "entry_fill_id": "entry-fill-1",
            "broker_filled_avg_price": 100.0,
            "entry_price_verified": True,
            "entry_price_source": "alpaca_paper_order.filled_avg_price",
            "entry_price_evidence_class": "BROKER_CONFIRMED_FILL",
            "source_bucket": "paper_autopilot_candidate",
            "row_json": "{}",
            "lifecycle_notes": "{}",
        }

    def test_scalp_broker_zero_closure_promotes_one_strict_truth_and_learning_record(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            intel = _TradeIntel()
            engine = self._engine(root, intel)
            result = engine._close_position(
                self._open_row(),
                {"symbol": "AAPL", "price": 101.0, "source": "alpaca_paper_order_fill"},
                "holding_window_expired",
                broker_fill={
                    "exit_order_id": "exit-order-1",
                    "exit_fill_id": "exit-fill-1",
                    "filled_at": "2026-07-31T15:00:00Z",
                    "filled_qty": 1.0,
                },
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["strict_broker_truth_persistence"]["persisted"])
            self.assertEqual(len(intel.records), 1)
            records = json.loads((root / "broker_truth_records_v1.json").read_text())["records"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["lane_id"], "SCALP")
            self.assertTrue(records[0]["broker_residual_zero_confirmed"])
            self.assertTrue(records[0]["current_logic_performance_eligible"])

    def test_incomplete_exit_lineage_never_promotes_closed_position_to_learning(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            intel = _TradeIntel()
            engine = self._engine(root, intel)
            result = engine._close_position(
                self._open_row("SWING"),
                {"symbol": "AAPL", "price": 99.0, "source": "alpaca_paper_order_fill"},
                "loss_review",
                broker_fill={"exit_order_id": "exit-order-1", "filled_at": "2026-07-31T15:00:00Z", "filled_qty": 1.0},
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "broker_exit_fill_required_before_lifecycle_close")
            self.assertEqual(intel.records, [])

    def test_filled_learned_exit_reconciles_broker_zero_before_strict_truth(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            intel = _TradeIntel()
            engine = self._engine(root, intel)
            engine.alpaca_paper_broker = _FilledExitBroker()
            row = self._open_row("SCALP")
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price,
                    entry_timestamp, lane_id, entry_order_id, entry_fill_id, broker_filled_avg_price,
                    entry_price_verified, entry_price_source, entry_price_evidence_class, source_bucket,
                    row_json, lifecycle_notes, created_at, updated_at)
                    VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, '{}', '{}', ?, ?)""",
                    (
                        row["position_id"], row["symbol"], row["asset_type"], row["quantity"], row["entry_price"],
                        row["entry_timestamp"], row["lane_id"], row["entry_order_id"], row["entry_fill_id"],
                        row["broker_filled_avg_price"], row["entry_price_source"], row["entry_price_evidence_class"],
                        row["source_bucket"], row["entry_timestamp"], row["entry_timestamp"],
                    ),
                )
                conn.commit()
            engine._runtime_state["learned_exit_pending_sells"] = {
                "exit-order-1": {"order_id": "exit-order-1", "position_id": row["position_id"], "symbol": "AAPL", "policy": "fixture", "horizon": "scalp"},
            }
            result = engine._refresh_learned_exit_pending_sells()
            self.assertEqual(result["filled"], 1)
            self.assertEqual(result["active"], 0)
            self.assertEqual(engine._runtime_state["learned_exit_pending_sells"], {})
            records = json.loads((root / "broker_truth_records_v1.json").read_text())["records"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["exit_fill_id"], "exit-order-1")

    def test_filled_learned_exit_stays_pending_when_broker_zero_is_not_confirmed(self):
        class _NonzeroBroker(_FilledExitBroker):
            def positions(self):
                return {"ok": True, "positions": [{"symbol": "AAPL", "qty": "0.5"}]}

        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            engine = self._engine(root, _TradeIntel())
            engine.alpaca_paper_broker = _NonzeroBroker()
            row = self._open_row("DAY")
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price,
                    entry_timestamp, lane_id, entry_order_id, entry_fill_id, broker_filled_avg_price,
                    entry_price_verified, entry_price_source, entry_price_evidence_class, source_bucket,
                    row_json, lifecycle_notes, created_at, updated_at)
                    VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, '{}', '{}', ?, ?)""",
                    (
                        row["position_id"], row["symbol"], row["asset_type"], row["quantity"], row["entry_price"],
                        row["entry_timestamp"], row["lane_id"], row["entry_order_id"], row["entry_fill_id"],
                        row["broker_filled_avg_price"], row["entry_price_source"], row["entry_price_evidence_class"],
                        row["source_bucket"], row["entry_timestamp"], row["entry_timestamp"],
                    ),
                )
                conn.commit()
            engine._runtime_state["learned_exit_pending_sells"] = {
                "exit-order-2": {"order_id": "exit-order-2", "position_id": row["position_id"], "symbol": "AAPL", "policy": "fixture", "horizon": "day_trade"},
            }
            result = engine._refresh_learned_exit_pending_sells()
            self.assertEqual(result["filled"], 0)
            self.assertEqual(result["active"], 1)
            pending = engine._runtime_state["learned_exit_pending_sells"]["exit-order-2"]
            self.assertEqual(pending["last_order_status"], "filled_reconciliation_pending")

    def test_closed_broker_zero_lifecycle_retries_registry_promotion_without_broker_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            engine = self._engine(root, _TradeIntel())
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price, exit_price,
                    return_percent, hold_seconds, entry_timestamp, exit_timestamp, lane_id, entry_order_id, entry_fill_id,
                    exit_order_id, exit_fill_id, broker_filled_avg_price, entry_price_verified, entry_price_source,
                    entry_price_evidence_class, source_bucket, row_json, lifecycle_notes, created_at, updated_at)
                    VALUES ('retry-1', 'AAPL', 'stock', 'CLOSED', 1, 100, 101, 1, 60,
                    '2026-07-31T14:00:00Z', '2026-07-31T15:00:00Z', 'SWING', 'entry-order', 'entry-fill',
                    'exit-order', 'exit-fill', 100, 1, 'alpaca_paper_order.filled_avg_price', 'BROKER_CONFIRMED_FILL',
                    'paper_autopilot_candidate', '{}', ?, '2026-07-31T14:00:00Z', '2026-07-31T15:00:00Z')""",
                    (json.dumps({
                        "strict_truth_promotion_pending": True,
                        "exit_reason": "profit_protection",
                        "exit_filled_at": "2026-07-31T15:00:00Z",
                        "broker_residual_zero_confirmed": True,
                        "broker_residual_lookup_status": "AUTHORITATIVE_NOT_FOUND",
                    }),),
                )
                conn.commit()
            result = engine._retry_pending_strict_truth_promotions()
            self.assertEqual(result["reviewed"], 1)
            self.assertEqual(result["persisted"], 1)
            with engine._connect() as conn:
                notes = json.loads(conn.execute("SELECT lifecycle_notes FROM paper_positions WHERE position_id='retry-1'").fetchone()[0])
            self.assertFalse(notes["strict_truth_promotion_pending"])
            records = json.loads((root / "broker_truth_records_v1.json").read_text())["records"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["lane_id"], "SWING")

    def test_execution_reconciliation_isolated_and_persisted_before_advisory_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            engine = self._engine(root, _TradeIntel())
            calls: list[str] = []

            def failing_pending() -> dict:
                calls.append("pending")
                raise RuntimeError("broker read unavailable")

            def learned() -> dict:
                calls.append("learned")
                return {"filled": 1}

            def authorized() -> dict:
                calls.append("authorized")
                return {"filled": 1}

            def strict_retry() -> dict:
                calls.append("strict")
                return {"persisted": 1}

            def learning_retry() -> dict:
                calls.append("learning")
                return {"acknowledged": 1}

            engine._refresh_unresolved_sell_intents = failing_pending
            engine._refresh_learned_exit_pending_sells = learned
            engine._refresh_authorized_lane_exit_pending = authorized
            engine._retry_pending_strict_truth_promotions = strict_retry
            engine._retry_pending_learning_acknowledgements = learning_retry

            result = engine._execution_critical_reconciliation_phase()

            self.assertEqual(calls, ["pending", "learned", "authorized", "strict", "learning"])
            self.assertEqual(result["sell_intent_reconciliation"]["observation_state"], "FAILED")
            self.assertEqual(result["strict_truth_promotion_retry"]["persisted"], 1)
            persisted = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["worker_cycle_phase"], "learning_acknowledgement_retry")
            self.assertEqual(
                engine._runtime_state["worker_last_suppressed_exception_v1"]["phase"],
                "pending_exit_reconciliation",
            )

            source = inspect.getsource(PaperAutopilotEngine.run_cycle)
            self.assertLess(
                source.index("_execution_critical_reconciliation_phase()"),
                source.index("_position_evidence_and_advisory_phase("),
            )


if __name__ == "__main__":
    unittest.main()
