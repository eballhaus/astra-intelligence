"""Regression coverage for broker-filled close reconciliation idempotency."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from engine.paper_autopilot import PaperAutopilotEngine


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _lyft_row() -> dict[str, object]:
    return {
        "position_id": "lyft-lifecycle-1",
        "symbol": "LYFT",
        "asset_type": "stock",
        "status": "OPEN",
        "quantity": 5.850789,
        "lane_id": "DAY",
        "position_owner": "DAY",
        "exit_policy_owner": "DAY",
        "entry_order_id": "lyft-entry-order",
        "entry_fill_id": "lyft-entry-fill",
        "entry_price": 17.09,
        "broker_filled_avg_price": 17.09,
        "entry_price_verified": True,
        "entry_timestamp": "2026-08-19T13:48:48Z",
        "source_bucket": "paper_autopilot_candidate",
        "entry_metadata_generation": "V1_MANDATORY",
        "order_intent_id": "lyft-order-intent-1",
        "entry_metadata_json": json.dumps({
            "metadata_generation": "V1_MANDATORY",
            "candidate_id": "lyft-candidate-1",
            "lifecycle_id": "lyft-lifecycle-1",
        }),
        "row_json": "{}",
        "lifecycle_notes": "{}",
    }


class _Broker:
    def order(self, order_id):
        return {
            "ok": True,
            "order": {
                "id": order_id,
                "symbol": "LYFT",
                "status": "filled",
                "filled_qty": "5.850789",
                "filled_avg_price": "17.26",
                "filled_at": "2026-08-19T15:27:45Z",
            },
        }

    def positions(self):
        # A successful complete list with no LYFT is authoritative broker zero.
        return {"ok": True, "positions": []}


class _TradeIntel:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record_trade(self, payload):
        self.records.append(dict(payload))
        return {"ok": True, "acknowledged": True}


class BrokerFillCloseIdempotencyTests(unittest.TestCase):
    def _engine(self, root: pathlib.Path, intel: _TradeIntel) -> PaperAutopilotEngine:
        (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
        engine = PaperAutopilotEngine(
            db_path=str(root / "paper.db"),
            state_path=str(root / "state.json"),
            alpaca_paper_broker=_Broker(),
            trade_intel=intel,
        )
        engine._position_tracker = None
        engine.trade_lifecycle_excursion_suite = None
        return engine

    @staticmethod
    def _insert(engine: PaperAutopilotEngine, row: dict[str, object]) -> None:
        with engine._connect() as conn:
            columns = ", ".join(row)
            placeholders = ", ".join("?" for _ in row)
            conn.execute(
                f"INSERT INTO paper_positions ({columns}, created_at, updated_at) VALUES ({placeholders}, ?, ?)",
                (*row.values(), _now(), _now()),
            )
            conn.commit()

    def test_exact_broker_fill_closes_one_lifecycle_and_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            intel = _TradeIntel()
            engine = self._engine(root, intel)
            row = _lyft_row()
            self._insert(engine, row)
            engine._runtime_state["authorized_lane_exit_pending"] = {
                "lyft-exit-order": {
                    "position_id": row["position_id"],
                    "symbol": "LYFT",
                    "lane_id": "DAY",
                    "order_id": "lyft-exit-order",
                    "client_order_id": "lyft-exit-client",
                    "exit_reason": "drawdown_from_peak",
                    "normalized_sell_qty": row["quantity"],
                }
            }

            first = engine._refresh_authorized_lane_exit_pending()
            self.assertEqual(first["filled"], 1)
            self.assertEqual(first["pending"], 0)
            with engine._connect() as conn:
                persisted = dict(conn.execute(
                    "SELECT status, exit_order_id, exit_fill_id FROM paper_positions WHERE position_id=?",
                    (row["position_id"],),
                ).fetchone())
            self.assertEqual(persisted["status"], "CLOSED")
            self.assertEqual(persisted["exit_order_id"], "lyft-exit-order")
            self.assertEqual(persisted["exit_fill_id"], "lyft-exit-order")
            self.assertEqual(len(intel.records), 1)
            truths = json.loads((root / "broker_truth_records_v1.json").read_text(encoding="utf-8"))["records"]
            self.assertEqual(len(truths), 1)

            replay = engine._close_position(
                dict(row),
                {"symbol": "LYFT", "price": 17.26, "source": "alpaca_paper_order_fill"},
                "drawdown_from_peak",
                broker_fill={
                    "position_id": row["position_id"],
                    "exit_order_id": "lyft-exit-order",
                    "exit_fill_id": "lyft-exit-order",
                },
            )
            self.assertTrue(replay["ok"])
            self.assertTrue(replay["idempotent_broker_fill_reconciliation"])
            self.assertEqual(len(intel.records), 1)

    def test_different_exit_fill_cannot_close_an_existing_closed_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            engine = self._engine(root, _TradeIntel())
            row = _lyft_row()
            self._insert(engine, row)
            with engine._connect() as conn:
                conn.execute(
                    "UPDATE paper_positions SET status='CLOSED', exit_order_id=?, exit_fill_id=? WHERE position_id=?",
                    ("exit-1", "fill-1", row["position_id"]),
                )
                conn.commit()
            result = engine._close_position(
                dict(row), {"symbol": "LYFT", "price": 17.26}, "fixture",
                broker_fill={"position_id": row["position_id"], "exit_order_id": "exit-1", "exit_fill_id": "different-fill"},
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "canonical_closed_exit_lineage_conflict")

    def test_existing_exact_entry_intent_never_reaches_a_second_broker_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            engine = self._engine(root, _TradeIntel())
            row = _lyft_row()
            self._insert(engine, row)
            engine.get_latest_row_fn = lambda *_args: {"symbol": "LYFT", "price": 17.09}
            engine._merge_latest_quote_for_submission = lambda candidate, *_args: dict(candidate)
            engine._submit_alpaca_paper_entry_order = lambda *_args, **_kwargs: self.fail(
                "an existing canonical entry intent must not submit another broker order"
            )
            with patch("engine.paper_autopilot._normalize_paper_entry_bridge", side_effect=lambda candidate: dict(candidate)):
                result = engine._open_position_from_row({
                    "symbol": "LYFT",
                    "asset_type": "stock",
                    "price": 17.09,
                    "entry_lane_horizon_contract_v1": {
                        "lifecycle_id": row["position_id"],
                        "order_intent_id": row["order_intent_id"],
                    },
                })
            self.assertTrue(result["ok"])
            self.assertTrue(result["idempotent_entry_reconciliation"])
            self.assertEqual(result["position_id"], row["position_id"])


if __name__ == "__main__":
    unittest.main()
