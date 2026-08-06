"""Fail-closed reconciliation of broker dust against current lifecycles."""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from engine.paper_autopilot import PaperAutopilotEngine


def _insert_open_row(engine: PaperAutopilotEngine, *, position_id: str = "life-1", symbol: str = "PH", quantity: float = 1.0) -> None:
    with engine._connect() as conn:
        conn.execute(
            """INSERT INTO paper_positions(
                position_id,symbol,asset_type,status,quantity,entry_price,entry_timestamp,
                entry_order_id,entry_fill_id,source_broker_order_id,entry_price_verified,
                lane_id,position_owner,exit_policy_owner,lifecycle_notes,row_json,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                position_id, symbol, "stock", "OPEN", quantity, 10.0, "2026-08-06T14:00:00Z",
                f"entry-{position_id}", f"fill-{position_id}", f"entry-{position_id}", 1,
                "DAY", "DAY", "DAY", "{}", "{}", "2026-08-06T14:00:00Z", "2026-08-06T14:00:00Z",
            ),
        )
        conn.commit()


def _dust_snapshot(symbol: str = "PH", quantity: str = "0.000000926") -> dict:
    return {
        "broker_reconciliation_active": True,
        "broker_positions_fetch_ok": True,
        "broker_position_by_symbol": {
            symbol: {"symbol": symbol, "qty": quantity, "market_value": "0.0009", "asset_class": "us_equity"},
        },
    }


class BrokerDustLifecycleReconciliationTests(unittest.TestCase):
    def _engine(self) -> tuple[PaperAutopilotEngine, tempfile.TemporaryDirectory]:
        directory = tempfile.TemporaryDirectory()
        root = pathlib.Path(directory.name)
        return PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json")), directory

    def test_unmapped_microscopic_broker_dust_is_quarantined_without_broker_write(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        _insert_open_row(engine)

        result = engine._reconcile_current_position_broker_dust_mismatches_v1(_dust_snapshot())

        self.assertEqual(result["critical"], 0)
        self.assertEqual(result["quarantined"], 1)
        with engine._connect() as conn:
            row = dict(conn.execute("SELECT status,quantity,lane_id,position_owner,exit_policy_owner,lifecycle_notes,reconciliation_reason,reconciliation_lineage_resolution FROM paper_positions WHERE position_id='life-1'").fetchone())
        self.assertEqual(row["status"], "BROKER_HELD_DUST")
        self.assertEqual(row["quantity"], 0.000000926)
        self.assertEqual(row["lane_id"], "")
        self.assertEqual(row["position_owner"], "HISTORICAL_DUST")
        self.assertEqual(row["exit_policy_owner"], "HISTORICAL_DUST")
        self.assertEqual(row["reconciliation_reason"], "IDENTITY_UNMAPPED_HISTORICAL_DUST_QUARANTINE")
        self.assertEqual(row["reconciliation_lineage_resolution"], "IDENTITY_UNMAPPED_FAIL_CLOSED")
        notes = __import__("json").loads(row["lifecycle_notes"])
        self.assertEqual(notes["historical_broker_dust_quarantine_v1"]["original_local_quantity"], 1.0)
        self.assertTrue(notes["historical_broker_dust_quarantine_v1"]["no_broker_zero_claimed"])
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["life-1"]
        self.assertEqual(state["closure_state"], "HISTORICAL_BROKER_DUST_QUARANTINED")
        self.assertEqual(state["exact_blocker"], "BROKER_DUST_RESIDUAL_UNMAPPED_TO_CANONICAL_LIFECYCLE")
        self.assertFalse(state["operational_lifecycle"])
        self.assertFalse(state["strict_truth_eligible"])
        self.assertEqual(result["broker_actions_used"], 0)

    def test_unverified_local_lineage_stays_fail_closed_without_exit_state(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        _insert_open_row(engine)
        with engine._connect() as conn:
            conn.execute("UPDATE paper_positions SET entry_fill_id='' WHERE position_id='life-1'")
            conn.commit()

        result = engine._reconcile_current_position_broker_dust_mismatches_v1(_dust_snapshot())

        record = result["records"]["life-1"]
        self.assertEqual(record["status"], "UNVERIFIED_LOCAL_LINEAGE")
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["life-1"]
        self.assertEqual(state["closure_state"], "EXIT_BLOCKED_IDENTITY")
        self.assertEqual(state["exact_blocker"], "BROKER_DUST_RESIDUAL_LOCAL_LIFECYCLE_UNLINKED")

    def test_same_symbol_multi_lifecycle_dust_is_ambiguous_and_does_not_select_owner(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        _insert_open_row(engine, position_id="life-1")
        _insert_open_row(engine, position_id="life-2")

        result = engine._reconcile_current_position_broker_dust_mismatches_v1(_dust_snapshot())

        self.assertEqual(result["critical"], 0)
        self.assertEqual(result["ambiguous"], 2)
        states = engine._runtime_state["native_lane_exit_lifecycle_v1"]
        self.assertEqual(set(states), {"life-1", "life-2"})
        self.assertTrue(all(item["closure_state"] == "EXIT_BLOCKED_IDENTITY" for item in states.values()))
        self.assertTrue(all(item["status"] == "AMBIGUOUS_FAIL_CLOSED" for item in result["records"].values()))

    def test_meaningful_broker_position_does_not_change_current_lifecycle(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        _insert_open_row(engine)
        snapshot = _dust_snapshot(quantity="1.0")
        snapshot["broker_position_by_symbol"]["PH"]["market_value"] = "10.0"

        result = engine._reconcile_current_position_broker_dust_mismatches_v1(snapshot)

        self.assertEqual(result["critical"], 0)
        self.assertFalse(result["records"])
        self.assertEqual(engine._runtime_state["native_lane_exit_lifecycle_v1"], {})

    def test_quarantined_dust_is_excluded_from_day_close_and_never_submits(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        _insert_open_row(engine)
        engine._reconcile_current_position_broker_dust_mismatches_v1(_dust_snapshot())
        engine._native_lane_exit_session_status = lambda: {"market_session_mode": "regular_market", "paper_order_submission_allowed": True}
        engine._lane_forced_exit_reason = lambda _row: "day_lane_overnight_breach"
        engine._submit_authorized_lane_exit = lambda *_args: self.fail("reconciliation-blocked lifecycle must not submit")

        result = engine._run_due_day_lane_close_stage(_dust_snapshot()["broker_position_by_symbol"])

        self.assertEqual(result["reviewed"], 0)
        self.assertEqual(result["blocked"], 0)
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["life-1"]
        self.assertEqual(state["closure_state"], "HISTORICAL_BROKER_DUST_QUARANTINED")

    def test_existing_sell_intent_keeps_unmapped_dust_fail_closed(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        _insert_open_row(engine)
        engine._runtime_state["paper_sell_order_intents"] = {
            "sell-life-1": {"symbol": "PH", "position_id": "life-1", "status": "SELL_SUBMITTED"},
        }

        result = engine._reconcile_current_position_broker_dust_mismatches_v1(_dust_snapshot())

        self.assertEqual(result["critical"], 1)
        with engine._connect() as conn:
            status = conn.execute("SELECT status FROM paper_positions WHERE position_id='life-1'").fetchone()[0]
        self.assertEqual(status, "OPEN")
        self.assertEqual(result["records"]["life-1"]["status"], "UNRESOLVED_CRITICAL")

    def test_quarantine_survives_restart_and_does_not_create_strict_truth(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        _insert_open_row(engine)
        engine._reconcile_current_position_broker_dust_mismatches_v1(_dust_snapshot())
        engine._save_state_file()

        restarted = PaperAutopilotEngine(db_path=engine.db_path, state_path=engine.state_path)
        self.assertEqual(restarted._fetch_open_positions(), [])
        self.assertIn("life-1", restarted._runtime_state["broker_dust_quarantine_v1"])
        with restarted._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM paper_positions WHERE status='CLOSED'").fetchone()[0], 0)

    def test_open_position_review_reuses_canonical_quote_evidence_before_provider_fallback(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        calls: list[tuple] = []
        engine.get_latest_row_fn = lambda *args: calls.append(args) or {"symbol": "PH", "price": 99.0}
        row = {"symbol": "PH", "asset_type": "stock"}
        cached = {
            "PH": {
                "symbol": "PH", "price": 10.0, "provider_used": "alpaca",
                "provider_quote_timestamp": "2026-08-06T14:00:00Z",
            }
        }

        quote = engine._open_position_review_quote_v1(row, {"current_price": 9.0}, cached)

        self.assertEqual(quote["price"], 10.0)
        self.assertEqual(quote["provider_quote_timestamp"], "2026-08-06T14:00:00Z")
        self.assertEqual(calls, [])

    def test_open_position_review_uses_existing_provider_fallback_when_evidence_missing(self):
        engine, directory = self._engine()
        self.addCleanup(directory.cleanup)
        calls: list[tuple] = []
        engine.get_latest_row_fn = lambda *args: calls.append(args) or {"symbol": "PH", "price": 11.0}

        quote = engine._open_position_review_quote_v1(
            {"symbol": "PH", "asset_type": "stock"},
            {"current_price": 9.0},
            {"PH": {"symbol": "PH", "price": 9.0, "retrieval_timestamp": "2026-08-06T14:00:00Z"}},
        )

        self.assertEqual(quote["price"], 11.0)
        self.assertEqual(calls, [("PH", "stock")])


if __name__ == "__main__":
    unittest.main()
