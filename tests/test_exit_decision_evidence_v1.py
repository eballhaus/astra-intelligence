"""Focused regression coverage for bounded exit decision evidence."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.paper_autopilot import PaperAutopilotEngine


def _iso(minutes_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


class ExitDecisionEvidenceTests(unittest.TestCase):
    def _engine_and_row(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
        engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
        engine._runtime_state = {
            "loss_containment_state_v1": {
                "decisions": {
                    "life-1": {
                        "position_id": "life-1", "symbol": "AAA", "threshold_state": "WATCH",
                    },
                },
            },
            "profit_protection_state_v1": {
                "decisions": {
                    "life-1": {
                        "position_id": "life-1", "symbol": "AAA", "profit_state": "PROTECT_PROFIT",
                    },
                    "old-life": {
                        "position_id": "old-life", "symbol": "AAA", "profit_state": "EXIT_REVIEW",
                    },
                },
            },
            "position_exit_readiness_v1": {
                "positions": [{
                    "symbol": "AAA", "canonical_position_id": "life-1", "recommendation": "PROTECT_PROFIT",
                    "opportunity_cost_state": "HIGH_OPPORTUNITY_COST", "replacement_state": "REPLACEMENT_AVAILABLE",
                }],
            },
            "unified_position_advisory_v1": {
                "positions": [{
                    "symbol": "AAA", "canonical_position_id": "life-1", "final_advisory": "EXIT_REVIEW",
                }],
            },
        }
        notes = {
            "existing_lifecycle_evidence": "preserve-me",
            "peak_unrealized_pnl_percent": 5.0,
            "max_favorable_excursion": 5.0,
            "max_adverse_excursion": -1.0,
            "hold_seconds": 3600.0,
        }
        row = {
            "position_id": "life-1", "lifecycle_id": "life-1", "canonical_position_id": "life-1",
            "symbol": "AAA", "asset_type": "stock", "lane_id": "DAY", "canonical_horizon": "day_trade",
            "quantity": 1.0, "entry_price": 100.0, "entry_timestamp": _iso(60),
            "entry_order_id": "entry-order", "entry_fill_id": "entry-fill", "broker_filled_avg_price": 100.0,
            "entry_price_verified": True, "entry_price_source": "alpaca",
            "entry_price_evidence_class": "BROKER_CONFIRMED_FILL", "source_bucket": "paper_autopilot_candidate",
            "row_json": "{}", "entry_metadata_json": "{}", "lifecycle_notes": json.dumps(notes),
        }
        with engine._connect() as conn:
            conn.execute(
                """INSERT INTO paper_positions(
                    position_id, symbol, asset_type, status, quantity, entry_price, entry_timestamp,
                    lane_id, entry_order_id, entry_fill_id, broker_filled_avg_price, entry_price_verified,
                    entry_price_source, entry_price_evidence_class, source_bucket, row_json,
                    entry_metadata_json, lifecycle_notes, created_at, updated_at
                ) VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["position_id"], row["symbol"], row["asset_type"], row["quantity"], row["entry_price"],
                    row["entry_timestamp"], row["lane_id"], row["entry_order_id"], row["entry_fill_id"],
                    row["broker_filled_avg_price"], row["entry_price_source"], row["entry_price_evidence_class"],
                    row["source_bucket"], row["row_json"], row["entry_metadata_json"], row["lifecycle_notes"], _iso(), _iso(),
                ),
            )
            conn.commit()
        return directory, root, engine, row

    def test_material_snapshot_is_exact_identity_bounded_and_advisory_safe(self):
        directory, _root, engine, row = self._engine_and_row()
        self.addCleanup(directory.cleanup)
        latest = {"symbol": "AAA", "price": 102.0, "momentum_state": "DETERIORATING"}
        evidence = engine._record_exit_decision_evidence_v1(row, latest, should_close=False, reason="hold")
        self.assertTrue(evidence["materially_relevant"])
        self.assertEqual(evidence["lifecycle_id"], "life-1")
        self.assertEqual(evidence["analytics_consumption"]["profit_protection"]["status"], "ADVISORY_ONLY_BY_DESIGN")
        self.assertFalse(evidence["analytics_consumption"]["profit_protection"]["received_by_exit_owner"])
        self.assertEqual(evidence["analytics_consumption"]["exit_readiness"]["recommended_action"], "PROTECT_PROFIT")
        self.assertEqual(evidence["analytics_consumption"]["loss_containment"]["state"], "WATCH")

        # Re-evaluating the same lifecycle state cannot append another row.
        engine._record_exit_decision_evidence_v1(row, latest, should_close=False, reason="hold")
        with engine._connect() as conn:
            notes = json.loads(conn.execute("SELECT lifecycle_notes FROM paper_positions WHERE position_id='life-1'").fetchone()[0])
        self.assertEqual(notes["existing_lifecycle_evidence"], "preserve-me")
        self.assertEqual(len(notes["exit_decision_evidence_v1"]), 1)
        self.assertEqual(notes["exit_decision_evidence_v1"][0]["outcome_status"], "PENDING_NATURAL_CLOSURE")

    def test_monitoring_and_truth_preserve_pre_action_event_without_hindsight(self):
        directory, root, engine, row = self._engine_and_row()
        self.addCleanup(directory.cleanup)
        latest = {"symbol": "AAA", "price": 98.0, "provider_quote_timestamp": _iso()}
        event = engine._record_exit_decision_evidence_v1(row, latest, should_close=True, reason="stop_loss_breach")
        engine._update_open_row_snapshot(row, latest)
        with engine._connect() as conn:
            notes = json.loads(conn.execute("SELECT lifecycle_notes FROM paper_positions WHERE position_id='life-1'").fetchone()[0])
        self.assertEqual(notes["existing_lifecycle_evidence"], "preserve-me")
        self.assertEqual(notes["exit_decision_evidence_v1"][0]["decision_evidence_id"], event["decision_evidence_id"])

        truth_row = {**row, "lifecycle_notes": json.dumps(notes)}
        result = engine._persist_strict_lane_truth(
            truth_row,
            {
                "exit_order_id": "exit-order", "exit_fill_id": "exit-fill", "filled_at": _iso(),
                "filled_qty": 1.0, "broker_residual_zero_confirmed": True,
            },
            exit_price=98.0, return_percent=-2.0, hold_seconds=3600.0, exit_reason="stop_loss_breach",
        )
        self.assertTrue(result["persisted"])
        truth = json.loads((root / "broker_truth_records_v1.json").read_text(encoding="utf-8"))["records"][0]
        self.assertEqual(truth["exit_decision_evidence_status"], "CAPTURED_PRE_ACTION")
        self.assertEqual(truth["exit_decision_evidence_v1"][0]["outcome_status"], "PENDING_NATURAL_CLOSURE")
        hold_quality = truth["observational_learning_v1"]["hold_quality_exit_timing_v1"]
        self.assertEqual(hold_quality["exit_decision_consumption_status"], "CAPTURED_PRE_ACTION")
        self.assertEqual(hold_quality["last_exit_owner_decision"]["decision_reason"], "stop_loss_breach")

    def test_same_symbol_prior_lifecycle_cannot_supply_current_advisory(self):
        directory, _root, engine, row = self._engine_and_row()
        self.addCleanup(directory.cleanup)
        engine._runtime_state["profit_protection_state_v1"]["decisions"].pop("life-1")
        engine._runtime_state["position_exit_readiness_v1"]["positions"][0]["canonical_position_id"] = "old-life"
        evidence = engine._build_exit_decision_evidence_v1(
            row,
            {"symbol": "AAA", "price": 102.0},
            should_close=False,
            reason="hold",
        )
        self.assertEqual(evidence["analytics_consumption"]["profit_protection"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(evidence["analytics_consumption"]["exit_readiness"]["status"], "INSUFFICIENT_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
