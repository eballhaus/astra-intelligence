import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import engine.paper_autopilot as paper_autopilot_module
from engine.paper_autopilot import PaperAutopilotEngine, resolve_canonical_entry_price_lineage_v1
from engine.trade_lifecycle_excursion_v1 import TradeLifecycleExcursionV1


class _FilledOrderBroker:
    def __init__(self, order):
        self._order = dict(order)
        self.calls = 0

    def order(self, order_id):
        self.calls += 1
        return {"ok": True, "order": dict(self._order)}


def _open_position(engine, *, position_id="position-1", symbol="AMC", entry_price=426.0, order_id="entry-1", client_id="client-1"):
    with engine._connect() as conn:
        conn.execute(
            """
            INSERT INTO paper_positions(
                position_id, symbol, asset_type, status, quantity, entry_price,
                provisional_entry_price, source_broker_order_id, source_client_order_id,
                entry_order_id, entry_timestamp, row_json, lifecycle_notes, created_at, updated_at
            ) VALUES (?, ?, 'stock', 'OPEN', 1, ?, ?, ?, ?, ?, '2026-07-18T14:30:00Z', '{}', '{}', '2026-07-18T14:30:00Z', '2026-07-18T14:30:00Z')
            """,
            (position_id, symbol, entry_price, entry_price, order_id, client_id, order_id),
        )
        conn.commit()


class BrokerEntryPriceLineageRepairTests(unittest.TestCase):
    def test_filled_order_uses_broker_fill_and_records_mismatch(self):
        lineage = resolve_canonical_entry_price_lineage_v1(
            symbol="AMC",
            provisional_entry_price=426.0,
            broker_order_result={
                "order": {
                    "id": "entry-1", "client_order_id": "client-1", "symbol": "AMC",
                    "status": "filled", "filled_avg_price": "1.60", "filled_at": "2026-07-18T14:30:01Z",
                    "paper_mode_verified": True,
                }
            },
            expected_broker_order_id="entry-1",
            expected_client_order_id="client-1",
        )
        self.assertEqual(lineage["canonical_entry_price"], 1.6)
        self.assertEqual(lineage["provisional_entry_price"], 426.0)
        self.assertTrue(lineage["entry_price_verified"])
        self.assertEqual(lineage["entry_price_evidence_class"], "BROKER_CONFIRMED_FILL")
        self.assertTrue(lineage["entry_price_mismatch_over_50pct"])

    def test_unfilled_order_remains_explicitly_provisional(self):
        lineage = resolve_canonical_entry_price_lineage_v1(
            symbol="AAL", provisional_entry_price=423.0,
            broker_order_result={"order": {"id": "entry-2", "symbol": "AAL", "status": "accepted", "paper_mode_verified": True}},
            expected_broker_order_id="entry-2",
        )
        self.assertEqual(lineage["canonical_entry_price"], 423.0)
        self.assertTrue(lineage["entry_price_provisional"])
        self.assertFalse(lineage["entry_price_verified"])
        self.assertEqual(lineage["entry_price_evidence_class"], "PROVISIONAL_RUNTIME_QUOTE")

    def test_open_position_persists_canonical_fill_separately_from_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            engine._position_tracker = None
            engine._submit_alpaca_paper_entry_order = lambda *args, **kwargs: {
                "ok": True,
                "order": {
                    "id": "entry-1", "client_order_id": "client-1", "symbol": "AMC", "status": "filled",
                    "filled_avg_price": "1.60", "filled_at": "2026-07-18T14:30:01Z", "paper_mode_verified": True,
                },
            }
            with patch.object(paper_autopilot_module, "create_lifecycle_record", None):
                result = engine._open_position_from_row({"symbol": "AMC", "price": 426.0, "asset_type": "stock"})
            self.assertTrue(result["ok"])
            self.assertEqual(result["entry_price"], 1.6)
            self.assertEqual(result["provisional_entry_price"], 426.0)
            with engine._connect() as conn:
                row = dict(conn.execute("SELECT * FROM paper_positions WHERE position_id=?", (result["position_id"],)).fetchone())
            self.assertEqual(row["entry_price"], 1.6)
            self.assertEqual(row["provisional_entry_price"], 426.0)
            self.assertEqual(row["broker_filled_avg_price"], 1.6)
            self.assertEqual(row["entry_price_verified"], 1)

    def test_reconciliation_updates_once_with_exact_order_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            broker = _FilledOrderBroker({
                "id": "entry-1", "client_order_id": "client-1", "symbol": "AMC", "status": "filled",
                "filled_avg_price": "1.60", "filled_at": "2026-07-18T14:30:01Z", "paper_mode_verified": True,
            })
            engine = PaperAutopilotEngine(
                db_path=str(root / "paper.db"), state_path=str(root / "state.json"), alpaca_paper_broker=broker,
            )
            _open_position(engine)
            snapshot = {"broker_reconciliation_active": True, "broker_position_by_symbol": {}}
            first = engine._reconcile_entry_price_lineage_v1(snapshot)
            second = engine._reconcile_entry_price_lineage_v1(snapshot)
            with engine._connect() as conn:
                row = dict(conn.execute("SELECT * FROM paper_positions WHERE position_id='position-1'").fetchone())
            self.assertEqual(first["repaired"], 1)
            self.assertEqual(second["repaired"], 0)
            self.assertEqual(row["entry_price"], 1.6)
            self.assertEqual(row["provisional_entry_price"], 426.0)
            self.assertEqual(row["broker_filled_avg_price"], 1.6)
            self.assertEqual(row["entry_price_verified"], 1)
            self.assertEqual(row["entry_price_evidence_class"], "BROKER_CONFIRMED_FILL")

    def test_symbol_only_position_match_never_repairs_entry_price(self):
        lineage = resolve_canonical_entry_price_lineage_v1(
            symbol="AMC", provisional_entry_price=426.0, expected_broker_order_id="entry-1",
            broker_position={"symbol": "AMC", "avg_entry_price": "1.60", "paper_mode_verified": True},
        )
        self.assertFalse(lineage["entry_price_verified"])
        self.assertEqual(lineage["canonical_entry_price"], 426.0)

    def test_lifecycle_marks_unverified_entries_diagnostic_only(self):
        lifecycle = TradeLifecycleExcursionV1(state_path="/tmp/astra-entry-price-lineage-test.jsonl")
        provisional = lifecycle._build_record({
            "position_id": "provisional", "symbol": "AMC", "entry_timestamp": "2026-07-18T14:30:00Z",
            "entry_price": 426.0, "provisional_entry_price": 426.0,
            "entry_price_evidence_class": "PROVISIONAL_RUNTIME_QUOTE", "entry_price_verified": False,
        }, {"price": 1.6, "timestamp": "2026-07-18T14:31:00Z"})
        verified = lifecycle._build_record({
            "position_id": "verified", "symbol": "AMC", "entry_timestamp": "2026-07-18T14:30:00Z",
            "entry_price": 1.6, "provisional_entry_price": 426.0, "broker_filled_avg_price": 1.6,
            "entry_price_evidence_class": "BROKER_CONFIRMED_FILL", "entry_price_verified": True,
        }, {"price": 1.7, "timestamp": "2026-07-18T14:31:00Z"})
        self.assertTrue(provisional["diagnostic_only"])
        self.assertFalse(provisional["official_metric_eligible"])
        self.assertFalse(provisional["loss_calibration_eligible"])
        self.assertTrue(verified["official_metric_eligible"])
        self.assertTrue(verified["lifecycle_learning_eligible"])

    def test_strict_truth_rejects_provisional_entry_and_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": []}), encoding="utf-8")
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            rejected = engine._persist_strict_lane_truth(
                {"lane_id": "DAY", "symbol": "AMC", "position_id": "p", "entry_order_id": "entry-1", "entry_fill_id": "", "quantity": 1},
                {"exit_order_id": "exit-1", "exit_fill_id": "exit-fill", "filled_at": "2026-07-18T15:00:00Z"},
                exit_price=1.7, return_percent=1.0, hold_seconds=60, exit_reason="fixture",
            )
            _open_position(engine)
            report = engine.entry_price_lineage_dry_run_audit_v1()
            self.assertEqual(rejected["reason"], "broker_confirmed_entry_price_required")
            self.assertFalse(report["historical_state_modified"])
            self.assertFalse(report["apply_mode_available"])
            self.assertEqual(report["broker_actions_used"], 0)
            self.assertFalse(report["behavior_safe_to_apply"])


if __name__ == "__main__":
    unittest.main()
