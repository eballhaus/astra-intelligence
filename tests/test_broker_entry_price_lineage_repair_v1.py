import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import engine.paper_autopilot as paper_autopilot_module
from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.paper_autopilot import PaperAutopilotEngine, resolve_canonical_entry_price_lineage_v1
from engine.trade_lifecycle_excursion_v1 import TradeLifecycleExcursionV1
from engine.astra_broker_open_db_closed_reconciliation_v1 import migrate_broker_open_db_closed


class _FilledOrderBroker:
    def __init__(self, order):
        self._order = dict(order)
        self.calls = 0
        self.order_ids = []

    def order(self, order_id):
        self.calls += 1
        self.order_ids.append(str(order_id))
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
                    "status": "filled", "filled_qty": "1", "filled_avg_price": "1.60", "filled_at": "2026-07-18T14:30:01Z",
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
        self.assertEqual(lineage["entry_fill_id"], "entry-1")
        self.assertEqual(lineage["entry_fill_identifier_type"], "BROKER_ORDER_ID_FILLED_EVIDENCE")
        self.assertTrue(lineage["entry_price_mismatch_over_50pct"])

    def test_partial_fill_uses_exact_broker_order_id_without_synthetic_lineage(self):
        lineage = resolve_canonical_entry_price_lineage_v1(
            symbol="AMC",
            provisional_entry_price=2.0,
            broker_order_result={
                "order": {
                    "id": "entry-partial-1", "symbol": "AMC", "status": "partially_filled",
                    "filled_qty": "0.25", "filled_avg_price": "1.60",
                    "filled_at": "2026-07-18T14:30:01Z", "paper_mode_verified": True,
                }
            },
            expected_broker_order_id="entry-partial-1",
        )
        self.assertTrue(lineage["entry_price_verified"])
        self.assertEqual(lineage["entry_filled_quantity"], 0.25)
        self.assertEqual(lineage["entry_fill_id"], "entry-partial-1")
        self.assertEqual(lineage["entry_fill_identifier_type"], "BROKER_ORDER_ID_FILLED_EVIDENCE")
        self.assertEqual(lineage["entry_price_lineage_status"], "BROKER_PARTIAL_FILL")

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
                    "id": "entry-1", "client_order_id": "client-1", "symbol": "AMC", "status": "filled", "filled_qty": "1",
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

    def test_acknowledged_but_unfilled_entry_is_pending_and_cannot_consume_open_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            engine._position_tracker = None
            engine._submit_alpaca_paper_entry_order = lambda *args, **kwargs: {
                "ok": True,
                "order": {
                    "id": "entry-accepted", "client_order_id": "client-accepted", "symbol": "AMC",
                    "status": "accepted", "qty": "1", "paper_mode_verified": True,
                },
            }
            with patch.object(paper_autopilot_module, "create_lifecycle_record", None):
                result = engine._open_position_from_row({"symbol": "AMC", "price": 10.0, "asset_type": "stock"})
            self.assertTrue(result["ok"])
            self.assertEqual(result["entry_position_status"], "PENDING_ENTRY")
            with engine._connect() as conn:
                row = dict(conn.execute("SELECT status, quantity FROM paper_positions WHERE position_id=?", (result["position_id"],)).fetchone())
                open_count = int(conn.execute("SELECT COUNT(*) FROM paper_positions WHERE status='OPEN'").fetchone()[0])
            self.assertEqual(row["status"], "PENDING_ENTRY")
            self.assertEqual(row["quantity"], 0.0)
            self.assertEqual(open_count, 0)

    def test_reconciliation_updates_once_with_exact_order_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            broker = _FilledOrderBroker({
                "id": "entry-1", "client_order_id": "client-1", "symbol": "AMC", "status": "filled", "filled_qty": "1",
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

    def test_pending_entry_activates_only_after_id_linked_broker_fill(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(paper_autopilot_module, "create_lifecycle_record", None):
            root = pathlib.Path(tmp)
            broker = _FilledOrderBroker({
                "id": "entry-1", "client_order_id": "client-1", "symbol": "AMC", "status": "filled",
                "filled_qty": "0.25", "filled_avg_price": "1.60", "filled_at": "2026-07-18T14:30:01Z", "paper_mode_verified": True,
            })
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"), alpaca_paper_broker=broker)
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price,
                    provisional_entry_price, source_broker_order_id, source_client_order_id, entry_order_id,
                    entry_timestamp, row_json, lifecycle_notes, created_at, updated_at)
                    VALUES ('pending-1', 'AMC', 'stock', 'PENDING_ENTRY', 0, 2, 2, 'entry-1', 'client-1', 'entry-1',
                    '2026-07-18T14:30:00Z', '{}', '{}', '2026-07-18T14:30:00Z', '2026-07-18T14:30:00Z')"""
                )
                conn.commit()
            report = engine._reconcile_entry_price_lineage_v1({"broker_reconciliation_active": True, "broker_position_by_symbol": {}})
            with engine._connect() as conn:
                row = dict(conn.execute("SELECT status, quantity, entry_fill_id FROM paper_positions WHERE position_id='pending-1'").fetchone())
            self.assertEqual(report["repaired"], 1)
            self.assertEqual(row["status"], "OPEN")
            self.assertEqual(row["quantity"], 0.25)
            self.assertTrue(row["entry_fill_id"])

    def test_new_pending_entry_is_not_starved_by_old_unverified_rows(self):
        """Bounded reconciliation prioritizes a current broker-filled entry."""
        with tempfile.TemporaryDirectory() as tmp, patch.object(paper_autopilot_module, "create_lifecycle_record", None):
            root = pathlib.Path(tmp)
            broker = _FilledOrderBroker({
                "id": "entry-current", "client_order_id": "client-current", "symbol": "SG", "status": "filled",
                "filled_qty": "16.805042016", "filled_avg_price": "5.95", "filled_at": "2026-08-04T13:44:29Z",
                "paper_mode_verified": True,
            })
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"), alpaca_paper_broker=broker)
            with engine._connect() as conn:
                for index in range(12):
                    conn.execute(
                        """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price,
                        provisional_entry_price, source_broker_order_id, source_client_order_id, entry_order_id,
                        entry_timestamp, row_json, lifecycle_notes, created_at, updated_at)
                        VALUES (?, ?, 'stock', 'OPEN', 1, 2, 2, ?, ?, ?, '2026-07-01T14:30:00Z', '{}', '{}',
                        '2026-07-01T14:30:00Z', '2026-07-01T14:30:00Z')""",
                        (f"old-{index}", f"OLD{index}", f"old-order-{index}", f"old-client-{index}", f"old-order-{index}"),
                    )
                conn.execute(
                    """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price,
                    provisional_entry_price, source_broker_order_id, source_client_order_id, entry_order_id,
                    entry_timestamp, row_json, lifecycle_notes, created_at, updated_at)
                    VALUES ('pending-current', 'SG', 'stock', 'PENDING_ENTRY', 0, 5.945, 5.945, 'entry-current',
                    'client-current', 'entry-current', '2026-08-04T13:44:26Z', '{}', '{}',
                    '2026-08-04T13:44:26Z', '2026-08-04T13:44:26Z')"""
                )
                conn.commit()
            report = engine._reconcile_entry_price_lineage_v1({"broker_reconciliation_active": True, "broker_position_by_symbol": {}})
            with engine._connect() as conn:
                row = dict(conn.execute("SELECT status, quantity, entry_fill_id FROM paper_positions WHERE position_id='pending-current'").fetchone())
            self.assertEqual(report["repaired"], 1)
            self.assertEqual(broker.order_ids[0], "entry-current")
            self.assertEqual(row["status"], "OPEN")
            self.assertAlmostEqual(row["quantity"], 16.805042016)
            self.assertEqual(row["entry_fill_id"], "entry-current")

    def test_historical_dust_row_cannot_override_new_same_symbol_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            with engine._connect() as conn:
                conn.execute("""INSERT INTO paper_positions(position_id,symbol,asset_type,status,quantity,entry_price,entry_price_verified,entry_fill_id,entry_timestamp,lane_id,position_owner,exit_policy_owner,reconciliation_reason,lifecycle_notes,created_at,updated_at) VALUES ('legacy-sg','SG','stock','OPEN',22.4614,8.9,0,'','2026-07-07T14:49:19Z','','LEGACY','LEGACY','PARTIAL_EXIT_RESIDUAL','{}','2026-07-31T20:00:00Z','2026-07-31T20:00:00Z')""")
                conn.execute("""INSERT INTO paper_positions(position_id,symbol,asset_type,status,quantity,entry_price,entry_price_verified,entry_fill_id,entry_timestamp,lane_id,position_owner,exit_policy_owner,lifecycle_notes,created_at,updated_at) VALUES ('day-sg','SG','stock','OPEN',16.805042016,5.95,1,'entry-sg','2026-08-04T13:44:29Z','DAY','DAY','DAY','{}','2026-08-04T13:44:29Z','2026-08-04T13:44:29Z')""")
                conn.commit()
            engine._runtime_state["paper_sell_order_intents"] = {"legacy-retire:SG": {"legacy_imported_retirement": True, "position_id": "legacy-sg", "order_intent_id": "legacy-retire:SG", "status": "BROKER_HELD_DUST", "broker_residual_lookup": {"broker_residual_quantity": 0.00000027}}}
            report = engine._archive_historical_reconciliation_collisions_v1()
            with engine._connect() as conn:
                old = dict(conn.execute("SELECT status,quantity FROM paper_positions WHERE position_id='legacy-sg'").fetchone())
                current = dict(conn.execute("SELECT status,lane_id,position_owner,exit_policy_owner FROM paper_positions WHERE position_id='day-sg'").fetchone())
            self.assertEqual(report["archived_count"], 1)
            self.assertEqual(old["status"], "BROKER_HELD_DUST")
            self.assertAlmostEqual(old["quantity"], 0.00000027)
            self.assertEqual(current, {"status": "OPEN", "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY"})

    def test_historical_reconciliation_maps_to_distinct_retirement_parent_by_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            with engine._connect() as conn:
                conn.execute("""INSERT INTO paper_positions(position_id,symbol,asset_type,status,quantity,entry_price,entry_price_verified,entry_fill_id,entry_timestamp,lane_id,position_owner,exit_policy_owner,reconciled_at,reconciliation_reason,reconciliation_evidence_source,prior_status,lifecycle_notes,created_at,updated_at) VALUES ('recon-legacy','SG','stock','OPEN',22.4614,8.9,0,'','2026-07-27T22:23:01Z','','LEGACY','LEGACY','2026-07-27T22:23:01Z','PARTIAL_EXIT_RESIDUAL','broker_position_truth','CLOSED','{}','2026-07-27T22:23:01Z','2026-07-27T22:23:01Z')""")
                conn.execute("""INSERT INTO paper_positions(position_id,symbol,asset_type,status,quantity,entry_price,entry_price_verified,entry_fill_id,entry_timestamp,lane_id,position_owner,exit_policy_owner,lifecycle_notes,created_at,updated_at) VALUES ('new-day','SG','stock','OPEN',16.805042016,5.95,1,'new-entry-fill','2026-08-04T13:44:29Z','DAY','DAY','DAY','{}','2026-08-04T13:44:29Z','2026-08-04T13:44:29Z')""")
                conn.commit()
            engine._runtime_state["paper_sell_order_intents"] = {
                "legacy-retire:SG": {
                    "legacy_imported_retirement": True, "position_id": "original-legacy-position",
                    "order_intent_id": "legacy-retire:SG", "symbol": "SG", "status": "BROKER_HELD_DUST",
                    "submission_timestamp": "2026-07-31T19:55:00Z", "submitted_quantity": 22.4614,
                    "cumulative_filled_quantity": 22.4614, "broker_order_id": "retirement-filled-order",
                    "broker_order_status": "FILLED", "order": {"side": "sell"},
                    "broker_residual_lookup": {"broker_residual_quantity": 0.00000027},
                    "dust_residual": {"is_dust": True},
                }
            }
            report = engine._archive_historical_reconciliation_collisions_v1()
            with engine._connect() as conn:
                old = dict(conn.execute("SELECT status,quantity,reconciliation_parent_position_id,reconciliation_parent_retirement_intent_id,reconciliation_lineage_resolution FROM paper_positions WHERE position_id='recon-legacy'").fetchone())
                current = dict(conn.execute("SELECT status,quantity,lane_id,position_owner,exit_policy_owner FROM paper_positions WHERE position_id='new-day'").fetchone())
            self.assertEqual(report["archived_count"], 1)
            self.assertEqual(old["status"], "BROKER_HELD_DUST")
            self.assertAlmostEqual(old["quantity"], 0.00000027)
            self.assertEqual(old["reconciliation_parent_position_id"], "original-legacy-position")
            self.assertEqual(old["reconciliation_parent_retirement_intent_id"], "legacy-retire:SG")
            self.assertEqual(old["reconciliation_lineage_resolution"], "VERIFIED_RETIREMENT_ARITHMETIC_PROVENANCE")
            self.assertEqual(current, {"status": "OPEN", "quantity": 16.805042016, "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY"})

    def test_symbol_only_or_ambiguous_retirement_lineage_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            with engine._connect() as conn:
                conn.execute("""INSERT INTO paper_positions(position_id,symbol,asset_type,status,quantity,entry_price,entry_price_verified,entry_fill_id,entry_timestamp,lane_id,position_owner,exit_policy_owner,reconciled_at,reconciliation_reason,reconciliation_evidence_source,prior_status,lifecycle_notes,created_at,updated_at) VALUES ('recon-legacy','SG','stock','OPEN',22.4614,8.9,0,'','2026-07-27T22:23:01Z','DAY','LEGACY','LEGACY','2026-07-27T22:23:01Z','PARTIAL_EXIT_RESIDUAL','broker_position_truth','CLOSED','{}','2026-07-27T22:23:01Z','2026-07-27T22:23:01Z')""")
                conn.execute("""INSERT INTO paper_positions(position_id,symbol,asset_type,status,quantity,entry_price,entry_price_verified,entry_fill_id,entry_timestamp,lane_id,position_owner,exit_policy_owner,lifecycle_notes,created_at,updated_at) VALUES ('new-day','SG','stock','OPEN',16.8,5.95,1,'new-entry-fill','2026-08-04T13:44:29Z','DAY','DAY','DAY','{}','2026-08-04T13:44:29Z','2026-08-04T13:44:29Z')""")
                conn.commit()
            base = {"legacy_imported_retirement": True, "symbol": "SG", "status": "BROKER_HELD_DUST", "submission_timestamp": "2026-07-31T19:55:00Z", "submitted_quantity": 22.4614, "cumulative_filled_quantity": 22.4614, "broker_order_id": "order", "broker_order_status": "FILLED", "order": {"side": "sell"}, "broker_residual_lookup": {"broker_residual_quantity": 0.00000027}, "dust_residual": {"is_dust": True}}
            engine._runtime_state["paper_sell_order_intents"] = {"one": {**base, "position_id": "original-a", "order_intent_id": "one"}, "two": {**base, "position_id": "original-b", "order_intent_id": "two"}}
            report = engine._archive_historical_reconciliation_collisions_v1()
            with engine._connect() as conn:
                old = dict(conn.execute("SELECT status FROM paper_positions WHERE position_id='recon-legacy'").fetchone())
            self.assertEqual(report["archived_count"], 0)
            self.assertEqual(old["status"], "OPEN")

    def test_broker_open_reconciliation_persists_immutable_parent_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            state_dir = root / "state"
            state_dir.mkdir()
            engine = PaperAutopilotEngine(db_path=str(state_dir / "ai_trading_memory.db"), state_path=str(root / "engine_state.json"))
            with engine._connect() as conn:
                conn.execute("""INSERT INTO paper_positions(position_id,symbol,asset_type,status,quantity,entry_price,entry_price_verified,entry_price_source,entry_timestamp,entry_order_id,entry_fill_id,source_lifecycle_id,lane_id,position_owner,lifecycle_notes,created_at,updated_at) VALUES ('legacy-parent','AMC','stock','CLOSED',1,10,0,'legacy','2026-07-01T00:00:00Z','','','legacy-life','','LEGACY','{}','2026-07-01T00:00:00Z','2026-07-01T00:00:00Z')""")
                conn.commit()
            (state_dir / "paper_autopilot_state.json").write_text(json.dumps({"last_evidence_capacity_snapshot": {"position_rows_for_read_only_consumers": [{"symbol": "AMC", "qty": 1.0, "avg_entry_price": 10.0, "current_price": 11.0, "market_value": 11.0, "asset_class": "us_equity"}]}}))
            original_cwd = os.getcwd()
            try:
                os.chdir(root)
                result = migrate_broker_open_db_closed(apply=True)
            finally:
                os.chdir(original_cwd)
            self.assertEqual(result["created"], 1)
            with engine._connect() as conn:
                row = dict(conn.execute("SELECT reconciliation_parent_position_id,reconciliation_parent_lifecycle_id FROM paper_positions WHERE position_id LIKE 'recon:AMC:%'").fetchone())
            self.assertEqual(row, {"reconciliation_parent_position_id": "legacy-parent", "reconciliation_parent_lifecycle_id": "legacy-life"})

    def test_partial_entry_reconciles_cumulative_broker_fill_on_later_cycle(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(paper_autopilot_module, "create_lifecycle_record", None):
            root = pathlib.Path(tmp)
            broker = _FilledOrderBroker({
                "id": "entry-partial", "client_order_id": "client-partial", "symbol": "AMC", "status": "partially_filled",
                "filled_qty": "0.25", "filled_avg_price": "1.60", "filled_at": "2026-07-18T14:30:01Z", "paper_mode_verified": True,
            })
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"), alpaca_paper_broker=broker)
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price,
                    provisional_entry_price, source_broker_order_id, source_client_order_id, entry_order_id,
                    entry_timestamp, row_json, lifecycle_notes, created_at, updated_at)
                    VALUES ('partial-1', 'AMC', 'stock', 'PENDING_ENTRY', 0, 2, 2, 'entry-partial', 'client-partial', 'entry-partial',
                    '2026-07-18T14:30:00Z', '{}', '{}', '2026-07-18T14:30:00Z', '2026-07-18T14:30:00Z')"""
                )
                conn.commit()
            snapshot = {"broker_reconciliation_active": True, "broker_position_by_symbol": {}}
            engine._reconcile_entry_price_lineage_v1(snapshot)
            broker._order.update({"status": "filled", "filled_qty": "1", "filled_at": "2026-07-18T14:31:00Z"})
            report = engine._reconcile_entry_price_lineage_v1(snapshot)
            with engine._connect() as conn:
                row = dict(conn.execute("SELECT status, quantity, entry_price_lineage_status FROM paper_positions WHERE position_id='partial-1'").fetchone())
            self.assertEqual(report["repaired"], 1)
            self.assertEqual(row["status"], "OPEN")
            self.assertEqual(row["quantity"], 1.0)
            self.assertEqual(row["entry_price_lineage_status"], "BROKER_CONFIRMED_FILL")

    def test_symbol_only_position_match_never_repairs_entry_price(self):
        lineage = resolve_canonical_entry_price_lineage_v1(
            symbol="AMC", provisional_entry_price=426.0, expected_broker_order_id="entry-1",
            broker_position={"symbol": "AMC", "avg_entry_price": "1.60", "paper_mode_verified": True},
        )
        self.assertFalse(lineage["entry_price_verified"])
        self.assertEqual(lineage["canonical_entry_price"], 426.0)

    def test_trade_state_reconciliation_excludes_unlinked_crypto_open_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price,
                    entry_timestamp, lane_id, position_owner, source_bucket, row_json, lifecycle_notes, created_at, updated_at)
                    VALUES ('unlinked-crypto', 'BTC/USD', 'crypto', 'OPEN', 1, 100, '2026-07-18T14:30:00Z',
                    'CRYPTO', 'CRYPTO', 'paper_autopilot', '{}', '{}', '2026-07-18T14:30:00Z', '2026-07-18T14:30:00Z')"""
                )
                conn.commit()
            report = engine.trade_state_reconciliation(
                apply=False,
                broker_snapshot={
                    "broker_reconciliation_active": True,
                    "broker_positions_fetch_ok": True,
                    "broker_open_symbols": set(),
                },
            )
            self.assertEqual(report["paper_positions_open_count"], 0)
            self.assertEqual(report["false_crypto_open_rows_excluded"], 1)

    def test_broker_truth_uses_broker_order_id_when_execution_id_is_unavailable(self):
        broker = AlpacaPaperBroker()
        broker.orders = lambda **_kwargs: {
            "ok": True,
            "orders": [
                {"id": "buy-order-1", "symbol": "AMC", "side": "buy", "status": "filled", "filled_qty": "1", "filled_avg_price": "10", "filled_at": "2026-07-18T14:30:00Z"},
                {"id": "sell-order-1", "symbol": "AMC", "side": "sell", "status": "filled", "filled_qty": "1", "filled_avg_price": "11", "filled_at": "2026-07-18T15:30:00Z"},
                {"symbol": "AMC", "side": "sell", "status": "filled", "filled_qty": "1", "filled_avg_price": "12", "filled_at": "2026-07-18T16:00:00Z"},
            ],
        }
        report = broker.broker_truth_metrics()
        self.assertEqual(report["filled_orders_reviewed"], 2)
        self.assertEqual(len(report["closed_trade_rows"]), 1)
        closed = report["closed_trade_rows"][0]
        self.assertEqual(closed["entry_order_ids"], ["buy-order-1"])
        self.assertEqual(closed["order_id"], "sell-order-1")

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
                {"exit_order_id": "exit-1", "exit_fill_id": "exit-fill", "filled_at": "2026-07-18T15:00:00Z", "broker_residual_zero_confirmed": True},
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
