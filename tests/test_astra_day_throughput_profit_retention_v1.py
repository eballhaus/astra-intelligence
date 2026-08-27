"""Focused regression coverage for passive DAY cohort and retention evidence."""
from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from engine.adaptive_profit_capture_intelligence_v1 import build_profit_capture_trade_effectiveness_v2
from engine.astra_daily_intelligence_summary_v1 import build_astra_daily_intelligence_summary_v1
from engine.astra_truth_learning_enrichment_v1 import (
    build_pretrade_truth_context_v1,
    build_truth_learning_enrichment_v1,
)
from engine.paper_autopilot import PaperAutopilotEngine


def _truth(*, lifecycle_id: str = "day-1", entry_state: str = "QUALIFIED", result: float = 1.0) -> dict:
    return {
        "stable_key": f"strict:{lifecycle_id}", "lifecycle_id": lifecycle_id,
        "symbol": "DAY", "lane_id": "DAY", "truth_quality": "BROKER_CONFIRMED_COMPLETE",
        "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        "entry_order_id": "entry", "entry_fill_id": "entry-fill", "exit_order_id": "exit", "exit_fill_id": "exit-fill",
        "broker_residual_zero_confirmed": True, "entry_time": "2026-08-20T13:00:00Z",
        "exit_time": "2026-08-20T14:00:00Z", "realized_return": result,
        "entry_price": 100.0, "exit_price": 100.0 * (1.0 + result / 100.0),
        "mfe": 2.0, "mae": -0.5, "profit_giveback": 1.0,
        "pretrade_context_v1": {"entry_quality_state": entry_state, "maximum_hold_minutes": 90},
    }


class DayThroughputProfitRetentionTests(unittest.TestCase):
    def test_approved_cap_creates_immutable_prospective_boundary_without_changing_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = PaperAutopilotEngine(
                db_path=str(Path(directory) / "paper.db"), state_path=str(Path(directory) / "state.json"),
                max_new_positions_per_cycle=3, enabled=False,
            )
            first = engine._ensure_day_throughput_cohort_v1()
            second = engine._ensure_day_throughput_cohort_v1()
        self.assertEqual(first["previous_max_new_positions_per_cycle"], 2)
        self.assertEqual(first["current_max_new_positions_per_cycle"], 3)
        self.assertEqual(first["approximate_throughput_increase_percent"], 50.0)
        self.assertEqual(first["measurement_boundary_at"], second["measurement_boundary_at"])
        self.assertTrue(first["observational_only"])
        self.assertEqual(first["execution_authority"], "UNCHANGED")

    def test_pretrade_quality_is_lookahead_safe_and_management_uses_post_entry_evidence(self) -> None:
        truth = _truth(result=0.2)
        enriched = build_truth_learning_enrichment_v1(truth, pretrade_context=truth["pretrade_context_v1"])
        self.assertEqual(enriched["pretrade_entry_quality_v1"]["classification"], "GOOD_ENTRY")
        self.assertTrue(enriched["pretrade_entry_quality_v1"]["lookahead_safe"])
        result = build_profit_capture_trade_effectiveness_v2([truth])
        row = result["trade_rows"][0]
        self.assertEqual(row["trade_quality_attribution_v1"]["entry_quality"]["classification"], "GOOD_ENTRY")
        self.assertEqual(row["trade_quality_attribution_v1"]["classification"], "GOOD_ENTRY_POOR_MANAGEMENT")

    def test_explicit_entry_quality_is_preserved_in_the_frozen_pretrade_context(self) -> None:
        context = build_pretrade_truth_context_v1(
            {"symbol": "DAY", "entry_quality_state": "QUALIFIED", "selection_quality_state": "GOOD"},
            {"qualification_state": "APPROVED", "pretrade_decision_contract_state": "VALID"},
        )
        self.assertEqual(context["entry_quality_state"], "QUALIFIED")
        self.assertEqual(context["selection_quality_state"], "GOOD")
        self.assertEqual(context["qualification_state"], "APPROVED")
        self.assertEqual(context["pretrade_decision_contract_state"], "VALID")

    def test_future_day_strict_truth_receives_cohort_without_rewriting_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            engine = PaperAutopilotEngine(
                db_path=str(root / "paper.db"), state_path=str(root / "state.json"),
                max_new_positions_per_cycle=3, enabled=False,
            )
            row = {
                "position_id": "day-life", "symbol": "DAY", "lane_id": "DAY", "asset_type": "stock",
                "entry_order_id": "entry", "entry_fill_id": "entry-fill", "entry_price_verified": True,
                "broker_filled_avg_price": 100.0, "quantity": 1.0, "entry_timestamp": "2026-08-20T13:00:00Z",
                "source_bucket": "paper_autopilot_candidate", "row_json": json.dumps({"entry_quality_state": "QUALIFIED"}),
                "entry_metadata_json": "{}", "lifecycle_notes": "{}",
            }
            result = engine._persist_strict_lane_truth(
                row, {"exit_order_id": "exit", "exit_fill_id": "exit-fill", "filled_at": "2026-08-20T14:00:00Z", "filled_qty": 1.0, "broker_residual_zero_confirmed": True},
                exit_price=101.0, return_percent=1.0, hold_seconds=3600.0, exit_reason="natural_exit",
            )
            persisted = json.loads((root / "broker_truth_records_v1.json").read_text(encoding="utf-8"))["records"][0]
        self.assertTrue(result["persisted"])
        self.assertEqual(persisted["day_throughput_cohort_v1"]["current_max_new_positions_per_cycle"], 3)
        self.assertTrue(persisted["day_throughput_cohort_v1"]["immutable_for_future_day_strict_truths"])

    def test_missing_pretrade_quality_fails_closed_without_using_realized_result(self) -> None:
        truth = _truth(entry_state="", result=2.0)
        result = build_profit_capture_trade_effectiveness_v2([truth])
        quality = result["trade_rows"][0]["trade_quality_attribution_v1"]
        self.assertEqual(quality["classification"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(quality["entry_evidence_lookahead_safe"])

    def test_exit_advisory_is_observational_and_never_broker_truth(self) -> None:
        truth = _truth(result=0.4)
        truth["exit_decision_evidence_v1"] = [{
            "observed_at": "2026-08-20T13:30:00Z", "current_return_percent": 1.2,
            "exit_owner_decision": {"decision_reason": "advisory"},
        }]
        enriched = build_truth_learning_enrichment_v1(truth, pretrade_context=truth["pretrade_context_v1"])
        advisory = enriched["exit_advisory_effectiveness_v1"]
        self.assertFalse(advisory["counterfactual_is_official_broker_truth"])
        self.assertEqual(advisory["counterfactual_evidence_class"], "OBSERVATIONAL_COUNTERFACTUAL_NOT_BROKER_TRUTH")

    def test_zero_truth_lanes_remain_no_evidence_and_cohort_is_prospective(self) -> None:
        truth = _truth()
        truth["day_throughput_cohort_v1"] = {
            "status": "PROSPECTIVE_MEASUREMENT_BOUNDARY", "measurement_boundary_at": "2026-08-20T12:00:00Z",
            "previous_max_new_positions_per_cycle": 2, "current_max_new_positions_per_cycle": 3,
        }
        summary = build_astra_daily_intelligence_summary_v1(
            canonical_truths=[truth], bundle1={},
            bundle2={"horizon_lane_breakdown": {"DAY": {"average_profit_capture_pct": 20.0}}},
            operating_health={}, worker_state={"day_throughput_cohort_v1": truth["day_throughput_cohort_v1"]},
        )
        self.assertEqual(summary["profitability_by_lane"]["CRYPTO"]["status"], "NO_EVIDENCE")
        self.assertEqual(summary["day_throughput_profit_retention_v1"]["prospective_truth_count"], 1)
        self.assertEqual(summary["day_throughput_profit_retention_v1"]["checkpoints"]["10"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(summary["day_throughput_profit_retention_v1"]["no_retrospective_causality_claim"])


if __name__ == "__main__":
    unittest.main()
