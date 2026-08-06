from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from engine.astra_truth_learning_enrichment_v1 import (
    build_pretrade_truth_context_v1,
    build_truth_learning_enrichment_v1,
)
from engine.paper_autopilot import PaperAutopilotEngine


def _truth() -> dict:
    return {
        "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        "truth_quality": "BROKER_CONFIRMED_COMPLETE",
        "lifecycle_id": "life-current",
        "entry_order_id": "entry-order",
        "entry_fill_id": "entry-fill",
        "exit_order_id": "exit-order",
        "exit_fill_id": "exit-fill",
        "entry_time": "2026-08-06T14:00:00Z",
        "exit_time": "2026-08-06T16:00:00Z",
        "broker_residual_zero_confirmed": True,
        "realized_return": 2.0,
        "hold_duration": 7200.0,
        "exit_reason": "target_reached",
        "source": "paper_autopilot_authorized_lane_exit",
    }


class TruthLearningEnrichmentV1Tests(unittest.TestCase):
    def test_prediction_accuracy_uses_existing_context_without_posthoc_inference(self):
        context = build_pretrade_truth_context_v1(
            {
                "predicted_direction": "long",
                "expected_return_low_pct": 1.0,
                "expected_return_high_pct": 3.0,
                "confidence": 0.81,
                "thesis": "breakout",
                "maximum_hold_minutes": 180,
            },
            {"paper_entry_horizon_style": "day_trade"},
        )
        enriched = build_truth_learning_enrichment_v1(_truth(), pretrade_context=context)
        prediction = enriched["prediction_accuracy_v1"]
        self.assertEqual(prediction["predicted_direction"], "UP")
        self.assertTrue(prediction["direction_prediction_correct"])
        self.assertTrue(prediction["within_expected_return_range"])
        self.assertEqual(prediction["horizon_assessment"], "WITHIN_MAX_HOLD")
        self.assertEqual(prediction["thesis_outcome"], "UNAVAILABLE")

    def test_missing_prediction_context_remains_explicitly_unavailable(self):
        enriched = build_truth_learning_enrichment_v1(_truth())
        prediction = enriched["prediction_accuracy_v1"]
        self.assertEqual(prediction["predicted_direction"], "UNAVAILABLE")
        self.assertEqual(prediction["forecast_error_pct_points"], "UNAVAILABLE")
        self.assertEqual(prediction["direction_prediction_correct"], "UNAVAILABLE")
        self.assertFalse(enriched["truth_quality_score_v1"]["components"]["pretrade_context"])

    def test_historical_or_reconstructed_provenance_cannot_receive_high_quality(self):
        truth = _truth()
        truth["source"] = "legacy_reconstructed_replay"
        enriched = build_truth_learning_enrichment_v1(truth, pretrade_context={"thesis": "old"})
        quality = enriched["truth_quality_score_v1"]
        self.assertFalse(quality["components"]["no_reconstruction_ambiguity"])
        self.assertLessEqual(quality["score"], 25)

    def test_acknowledgement_updates_quality_without_rewriting_eligibility(self):
        before = build_truth_learning_enrichment_v1(_truth(), pretrade_context={"thesis": "x"}, learning_acknowledged=False)
        after = build_truth_learning_enrichment_v1(_truth(), pretrade_context={"thesis": "x"}, learning_acknowledged=True)
        self.assertFalse(before["truth_quality_score_v1"]["components"]["learning_acknowledged"])
        self.assertTrue(after["truth_quality_score_v1"]["components"]["learning_acknowledged"])
        self.assertEqual(after["truth_quality_score_v1"]["score"], before["truth_quality_score_v1"]["score"] + 2)

    def test_registry_ack_update_requires_exact_stable_key_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = root / "broker_truth_records_v1.json"
            row = {**_truth(), "stable_key": "strict:entry-fill:exit-fill", "pretrade_context_v1": {"thesis": "x"}}
            path.write_text(json.dumps({"records": [row]}), encoding="utf-8")
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            mismatch = engine._annotate_strict_truth_learning_acknowledgement(
                stable_key="strict:entry-fill:exit-fill", lifecycle_id="different-life", learning_acknowledged=True,
            )
            self.assertEqual(mismatch["reason"], "strict_truth_lifecycle_mismatch")
            result = engine._annotate_strict_truth_learning_acknowledgement(
                stable_key="strict:entry-fill:exit-fill", lifecycle_id="life-current", learning_acknowledged=True,
            )
            self.assertTrue(result["updated"])
            updated = json.loads(path.read_text())["records"][0]
            self.assertTrue(updated["learning_acknowledged"])
            self.assertTrue(updated["observational_learning_v1"]["truth_quality_score_v1"]["components"]["learning_acknowledged"])

    def test_enrichment_failure_never_blocks_strict_truth_or_learning_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            row = {
                "position_id": "life-1", "symbol": "AAPL", "asset_type": "stock", "lane_id": "DAY",
                "quantity": 1.0, "entry_order_id": "entry", "entry_fill_id": "entry-fill",
                "entry_timestamp": "2026-08-06T14:00:00Z", "broker_filled_avg_price": 100.0,
                "entry_price_verified": True, "entry_price_source": "alpaca",
                "entry_price_evidence_class": "BROKER_CONFIRMED_FILL", "row_json": "{}",
                "entry_metadata_json": "{}", "lifecycle_notes": "{}",
            }
            fill = {
                "exit_order_id": "exit", "exit_fill_id": "exit-fill",
                "filled_at": "2026-08-06T15:00:00Z", "broker_residual_zero_confirmed": True,
            }
            with patch("engine.paper_autopilot.build_truth_learning_enrichment_v1", side_effect=RuntimeError("fixture")):
                result = engine._persist_strict_lane_truth(
                    row, fill, exit_price=101.0, return_percent=1.0, hold_seconds=3600.0, exit_reason="fixture",
                )
            self.assertTrue(result["persisted"])
            self.assertEqual(result["observational_learning_v1"]["status"], "UNAVAILABLE_ENRICHMENT_FAILED")
            record = json.loads((root / "broker_truth_records_v1.json").read_text(encoding="utf-8"))["records"][0]
            self.assertEqual(record["observational_learning_v1"]["error_type"], "RuntimeError")

    def test_enrichment_failure_does_not_block_core_learning_acknowledgement(self):
        class Broker:
            def positions(self):
                return {"ok": True, "positions": []}

        class Learning:
            def __init__(self):
                self.rows: list[dict] = []

            def record_trade(self, row):
                self.rows.append(dict(row))
                return {"ok": True}

        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.close_lifecycle_record", None):
            root = pathlib.Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            learning = Learning()
            engine = PaperAutopilotEngine(
                db_path=str(root / "paper.db"), state_path=str(root / "state.json"),
                alpaca_paper_broker=Broker(), trade_intel=learning,
            )
            row = {
                "position_id": "life-ack", "symbol": "AAPL", "asset_type": "stock", "lane_id": "DAY",
                "quantity": 1.0, "entry_price": 100.0, "entry_order_id": "entry", "entry_fill_id": "entry-fill",
                "entry_timestamp": "2026-08-06T14:00:00Z", "broker_filled_avg_price": 100.0,
                "entry_price_verified": True, "entry_price_source": "alpaca",
                "entry_price_evidence_class": "BROKER_CONFIRMED_FILL", "row_json": "{}",
                "entry_metadata_json": "{}", "lifecycle_notes": "{}", "source_bucket": "paper_autopilot_candidate",
            }
            fill = {
                "exit_order_id": "exit", "exit_fill_id": "exit-fill", "filled_at": "2026-08-06T15:00:00Z", "filled_qty": 1.0,
            }
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions(position_id, symbol, asset_type, status, quantity, entry_price,
                    entry_timestamp, lane_id, entry_order_id, entry_fill_id, broker_filled_avg_price,
                    entry_price_verified, entry_price_source, entry_price_evidence_class, source_bucket,
                    row_json, entry_metadata_json, lifecycle_notes, created_at, updated_at)
                    VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["position_id"], row["symbol"], row["asset_type"], row["quantity"], row["entry_price"],
                        row["entry_timestamp"], row["lane_id"], row["entry_order_id"], row["entry_fill_id"],
                        row["broker_filled_avg_price"], row["entry_price_source"], row["entry_price_evidence_class"],
                        row["source_bucket"], row["row_json"], row["entry_metadata_json"], row["lifecycle_notes"],
                        row["entry_timestamp"], row["entry_timestamp"],
                    ),
                )
                conn.commit()
            with patch("engine.paper_autopilot.build_truth_learning_enrichment_v1", side_effect=RuntimeError("fixture")):
                result = engine._close_position(row, {"symbol": "AAPL", "price": 101.0}, "fixture", broker_fill=fill)
            self.assertTrue(result["ok"])
            self.assertTrue(result["strict_broker_truth_persistence"]["persisted"])
            self.assertTrue(result["learning_acknowledged"])
            self.assertEqual(len(learning.rows), 1)
            self.assertEqual(learning.rows[0]["observational_learning_v1"]["status"], "UNAVAILABLE_ENRICHMENT_FAILED")


if __name__ == "__main__":
    unittest.main()
