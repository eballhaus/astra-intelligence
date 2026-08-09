from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_profitability_activation_intelligence_utilization_v1 import (
    AstraProfitabilityActivationIntelligenceUtilizationV1,
)
from engine.confidence_calibration_performance_attribution_v1 import (
    ConfidenceCalibrationPerformanceAttributionV1,
)


def _strict_truth(**extra):
    return {
        "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        "truth_quality": "BROKER_CONFIRMED_COMPLETE",
        "source": "paper_autopilot_authorized_lane_exit",
        "stable_key": "strict:entry-1:exit-1",
        "lifecycle_id": "life-1",
        "entry_fill_id": "entry-1",
        "exit_fill_id": "exit-1",
        "symbol": "AAPL",
        "lane_id": "DAY",
        "realized_return": 2.5,
        "exit_time": "2026-08-09T12:00:00Z",
        "pretrade_context_v1": {
            "candidate_id": "candidate-1",
            "confidence": 92.0,
            "observation_timestamp": "2026-08-09T10:00:00Z",
        },
        **extra,
    }


class ConfidenceCalibrationClosedOutcomeLinkageTests(unittest.TestCase):
    def test_calibration_uses_only_linked_strict_broker_truth(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "broker_truth_records_v1.json").write_text(
                json.dumps({"records": [_strict_truth()]}), encoding="utf-8"
            )
            payload = ConfidenceCalibrationPerformanceAttributionV1(state_dir=root).status(force=True)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["calibration_evidence_source"], "broker_truth_records_v1.strict_broker_confirmed_complete")
            self.assertEqual(payload["closed_outcome_linkage_status"], "LINKED")
            self.assertEqual(payload["strict_truth_records_linked"], 1)
            self.assertEqual(payload["evidence_count"], 1)
            self.assertEqual(payload["confidence_bucket_stats"]["90_to_94"]["trade_count"], 1)
            self.assertFalse(payload["behavior_safe_to_apply"])
            self.assertEqual(payload["provider_calls_used"], 0)

    def test_legacy_or_missing_pretrade_context_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            legacy = _strict_truth(source="legacy_reconstructed_replay")
            missing = _strict_truth(stable_key="strict:entry-2:exit-2", lifecycle_id="life-2", pretrade_context_v1={})
            Path(root, "broker_truth_records_v1.json").write_text(
                json.dumps({"records": [legacy, missing]}), encoding="utf-8"
            )
            payload = ConfidenceCalibrationPerformanceAttributionV1(state_dir=root).status(force=True)
            self.assertEqual(payload["status"], "insufficient_evidence")
            self.assertEqual(payload["evidence_count"], 0)
            self.assertEqual(payload["closed_outcome_linkage_status"], "PARTIAL")
            self.assertEqual(payload["strict_truth_records_missing_pre_outcome_prediction"], 1)

    def test_major_consumer_coverage_exposes_bounded_lesson_provenance(self):
        module = AstraProfitabilityActivationIntelligenceUtilizationV1(state_dir="/not-used")
        lessons = [{"lesson_id": "lesson-a", "symbol": "AAPL", "capture_ratio": 70.0}]
        table, _, _ = module._consumer_table(
            {"cortex_lifecycle_evidence_master_truth_v1": {"status": "ok"}}, lessons
        )
        cortex = next(row for row in table if row["system"] == "Cortex")
        self.assertEqual(cortex["canonical_lesson_ids_used"], ["lesson-a"])
        self.assertEqual(cortex["before_after_impact"]["impact"], "EXPLICIT_CANONICAL_PROVENANCE")
        self.assertEqual(cortex["canonical_lesson_provenance"], "canonical_lifecycle_lessons_v1.jsonl")


if __name__ == "__main__":
    unittest.main()
