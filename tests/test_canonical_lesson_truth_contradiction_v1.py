from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.cortex_lifecycle_evidence_master_truth_v1 import (
    CortexLifecycleEvidenceMasterTruthV1,
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
        **extra,
    }


class CanonicalLessonTruthContradictionTests(unittest.TestCase):
    def test_strict_truth_is_a_bounded_lesson_base_when_edge_sampling_misses_it(self):
        with tempfile.TemporaryDirectory() as root:
            truth = _strict_truth(
                symbol="RIVN",
                asset_class="equity",
                entry_time="2026-08-12T15:39:44Z",
                exit_time="2026-08-12T19:55:12Z",
                entry_price=15.96,
                exit_price=15.97,
                realized_return=0.062657,
                mfe=0.469925,
                mae=-0.344612,
                profit_giveback=0.75188,
                hold_duration=15328.407,
                exit_reason="day_lane_session_close_required",
                lane_id="DAY",
                pretrade_context_v1={"paper_entry_horizon_style": "day_trade"},
            )
            Path(root, "broker_truth_records_v1.json").write_text(
                json.dumps({"records": [truth]}), encoding="utf-8"
            )
            builder = CortexLifecycleEvidenceMasterTruthV1(state_dir=root)
            payload = builder.status(force=True)
            rows = [json.loads(line) for line in Path(root, "canonical_lifecycle_lessons_v1.jsonl").read_text().splitlines()]

        self.assertEqual(payload["canonical_lifecycle_lesson_store_v1"]["canonical_lesson_count"], 1)
        self.assertEqual(len(rows), 1)
        lesson = rows[0]
        self.assertEqual(lesson["lifecycle_id"], "life-1")
        self.assertEqual(lesson["broker_truth_id"], "strict:entry-1:exit-1")
        self.assertEqual(lesson["evidence_class"], "BROKER_CONFIRMED_COMPLETE")
        self.assertEqual(lesson["horizon_style"], "day_trade")
        self.assertEqual(lesson["lane_id"], "DAY")
        self.assertEqual(lesson["source_lane_ids"], ["DAY"])
        self.assertEqual(lesson["outcome_label"], "winner")
        self.assertEqual(lesson["mfe_pct"], 0.469925)
        self.assertEqual(lesson["mae_pct"], -0.344612)
        self.assertEqual(lesson["source_files_used"], ["broker_truth_records_v1.json"])

    def test_strict_truth_stays_in_the_recent_tail_for_bounded_retrieval(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "broker_truth_records_v1.json").write_text(
                json.dumps({"records": [_strict_truth()]}), encoding="utf-8"
            )
            Path(root, "trade_lifecycle_excursion_v2.jsonl").write_text(
                json.dumps({"lifecycle_id": "historical-life", "symbol": "OLD", "closed": True, "exit_timestamp": "2026-08-01T00:00:00Z"}) + "\n",
                encoding="utf-8",
            )
            builder = CortexLifecycleEvidenceMasterTruthV1(state_dir=root)
            builder.status(force=True)
            rows = [json.loads(line) for line in Path(root, "canonical_lifecycle_lessons_v1.jsonl").read_text().splitlines()]

        self.assertEqual(rows[-1]["lifecycle_id"], "life-1")
        self.assertEqual(rows[-1]["broker_truth_linkage_status"], "PROVEN_STRICT_BROKER_TRUTH")

    def test_exact_strict_truth_link_is_tagged_without_changing_eligibility(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "broker_truth_records_v1.json").write_text(
                json.dumps({"records": [_strict_truth()]}), encoding="utf-8"
            )
            builder = CortexLifecycleEvidenceMasterTruthV1(state_dir=root)
            strict = builder._strict_truth_index()["life-1"]
            lesson = builder._merged_lesson(
                {"lifecycle_id": "life-1", "symbol": "AAPL", "exit_timestamp": "2026-08-09T12:00:00Z"},
                {}, {"trade_lifecycle_excursion_v2.jsonl": "base-ref"}, strict,
            )
            self.assertEqual(lesson["broker_truth_id"], "strict:entry-1:exit-1")
            self.assertEqual(lesson["broker_truth_linkage_status"], "PROVEN_STRICT_BROKER_TRUTH")
            self.assertEqual(lesson["evidence_class"], "BROKER_CONFIRMED_COMPLETE")
            self.assertEqual(lesson["source_record_refs"]["broker_truth_records_v1.json"], "strict:entry-1:exit-1")

    def test_non_strict_or_unmatched_truth_cannot_be_mislabeled(self):
        builder = CortexLifecycleEvidenceMasterTruthV1(state_dir="/not-used")
        base = {"lifecycle_id": "life-1", "symbol": "AAPL", "evidence_class": "REPLAY_SUPPORTED"}
        non_strict = _strict_truth(lifecycle_id="life-2", source="legacy_reconstructed_replay")
        lesson = builder._merged_lesson(base, {}, {"trade_lifecycle_excursion_v2.jsonl": "base-ref"}, non_strict)
        self.assertIsNone(lesson["broker_truth_id"])
        self.assertEqual(lesson["broker_truth_linkage_status"], "UNLINKED_OR_NON_STRICT")
        self.assertEqual(lesson["evidence_class"], "REPLAY_SUPPORTED")
        self.assertNotIn("broker_truth_records_v1.json", lesson["source_record_refs"])

    def test_conflicting_source_values_are_preserved_with_provenance(self):
        builder = CortexLifecycleEvidenceMasterTruthV1(state_dir="/not-used")
        base = {"lifecycle_id": "life-1", "symbol": "AAPL", "capture_ratio": 55.0}
        matched = {"exit_learning_expansion_suite_v1.jsonl": {"lifecycle_id": "life-1", "capture_ratio": 80.0, "evidence_class": "SHADOW_COUNTERFACTUAL"}}
        lesson = builder._merged_lesson(
            base, matched,
            {"trade_lifecycle_excursion_v2.jsonl": "base-ref", "exit_learning_expansion_suite_v1.jsonl": "exit-ref"},
        )
        self.assertEqual(lesson["capture_ratio"], 55.0)
        self.assertEqual(lesson["contradiction_preservation_status"], "PRESERVED")
        contradiction = next(item for item in lesson["contradictory_evidence"] if item["field"] == "capture_ratio")
        self.assertEqual(contradiction["selected_source"], "trade_lifecycle_excursion_v2.jsonl")
        self.assertEqual(contradiction["minority_evidence"][0]["source_record_ref"], "exit-ref")
        self.assertEqual(contradiction["minority_evidence"][0]["evidence_class"], "SHADOW_COUNTERFACTUAL")


if __name__ == "__main__":
    unittest.main()
