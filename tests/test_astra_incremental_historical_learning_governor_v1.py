from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_incremental_historical_learning_governor_v1 import (
    CHECKPOINT_FILE,
    DELTA_INDEX_FILE,
    build_incremental_historical_learning_governor_v1,
    run_incremental_historical_learning_cycle_v1,
)


HEALTHY = {"worker_health": "HEALTHY", "resource_state": "RESOURCE_NORMAL"}


class IncrementalHistoricalLearningGovernorV1Tests(unittest.TestCase):
    def _root(self, sources: dict[str, list[dict]]) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "dashboard_cache").mkdir()
        (root / "storage_summary_indexes").mkdir()
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": []}))
        for name in ("realistic_shadow_evidence_learning_lab_v1.json", "shadow_vs_paper_performance_attribution_v1.json"):
            (root / "dashboard_cache" / name).write_text("{}")
        for name in ("symbol_behavior_profiles_v1.json", "astra_unified_position_advisory_v1.json"):
            (root / name).write_text("{}")
        for source, rows in sources.items():
            (root / source).write_text("".join(json.dumps(row) + "\n" for row in rows))
        return root

    @staticmethod
    def _row(tier: str = "shadow", symbol: str = "ABC") -> dict:
        row = {"symbol": symbol, "horizon": "DAY", "regime": "RISK_ON", "archetype": "BREAKOUT", "outcome": "WIN", "realized_return_pct": 1.25}
        if tier == "strict":
            row["truth_state"] = "STRICT_TRUTH"
        elif tier == "operational":
            row["validated"] = True
        else:
            row["shadow"] = True
        return row

    def test_partition_is_bounded_and_checkpoint_resumes_without_skipping_rows(self):
        root = self._root({"candidate_decision_ledger_v1.jsonl": [self._row(symbol=f"A{index}") for index in range(4)]})
        first = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY, max_rows=1, max_bytes=4096)
        second = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY, max_rows=1, max_bytes=4096)
        self.assertEqual(first["partitions_processed"][0]["rows_examined"], 1)
        self.assertEqual(second["partitions_processed"][0]["rows_examined"], 1)
        self.assertGreater(second["partitions_processed"][0]["cursor_start"], first["partitions_processed"][0]["cursor_start"])
        self.assertTrue((root / CHECKPOINT_FILE).exists())

    def test_completed_unchanged_partition_is_not_reprocessed(self):
        root = self._root({"candidate_decision_ledger_v1.jsonl": [self._row()]})
        run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY)
        repeated = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY)
        self.assertEqual(repeated["status"], "UNCHANGED")
        self.assertEqual(repeated["partitions_processed"], [])

    def test_append_resumes_at_checkpoint_but_rewrite_is_fail_closed(self):
        root = self._root({"candidate_decision_ledger_v1.jsonl": [self._row()]})
        first = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY)
        source = root / "candidate_decision_ledger_v1.jsonl"
        previous_size = source.stat().st_size
        source.write_text(source.read_text() + json.dumps(self._row(symbol="NEW")) + "\n")
        appended = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY)
        self.assertEqual(appended["partitions_processed"][0]["cursor_start"], previous_size)
        source.write_text(json.dumps(self._row(symbol="REWRITTEN")) + "\n")
        status = build_incremental_historical_learning_governor_v1(str(root), HEALTHY)
        self.assertIsNone(status["current_priority_partition"])
        self.assertEqual(status["current_status"], "ERROR")
        self.assertEqual(first["status"], "COMPLETE")

    def test_priority_prefers_candidate_decision_evidence(self):
        root = self._root({
            "trade_memory_similarity_v1.jsonl": [self._row()],
            "candidate_decision_ledger_v1.jsonl": [self._row()],
        })
        status = build_incremental_historical_learning_governor_v1(str(root), HEALTHY)
        self.assertEqual(status["current_priority_partition"]["source"], "candidate_decision_ledger_v1.jsonl")

    def test_unhealthy_worker_or_resource_pressure_defers_without_mining(self):
        root = self._root({"candidate_decision_ledger_v1.jsonl": [self._row()]})
        for facts in ({"worker_health": "STALE"}, {"worker_health": "HEALTHY", "resource_state": "RESOURCE_MEMORY_PAUSE"}):
            result = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=facts)
            self.assertEqual(result["status"], "DEFERRED_RESOURCE_PRESSURE")
            self.assertEqual(result["partitions_processed"], [])
        self.assertFalse((root / "storage_summary_indexes" / DELTA_INDEX_FILE).exists())

    def test_one_partition_writes_tier_separated_outcome_aggregates(self):
        root = self._root({"candidate_decision_ledger_v1.jsonl": [self._row("strict"), self._row("shadow")]})
        result = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY)
        index = json.loads((root / "storage_summary_indexes" / DELTA_INDEX_FILE).read_text())
        tiers = index["outcome_by_dimension"]["symbol"]["abc"]
        self.assertEqual(result["partitions_processed"][0]["outcome_linked_count"], 2)
        self.assertIn("BROKER_CONFIRMED_NATURAL_STRICT_TRUTH", tiers)
        self.assertIn("SHADOW_COUNTERFACTUAL", tiers)

    def test_broker_linked_canonical_lesson_reaches_existing_bounded_teacher_handoff(self):
        root = self._root({"canonical_lifecycle_lessons_v1.jsonl": [{
            "lesson_id": "lesson-rivn-1", "lifecycle_id": "life-rivn-1", "broker_truth_id": "strict:entry:exit",
            "symbol": "RIVN", "horizon_style": "day_trade", "outcome_label": "winner",
            "current_or_exit_profit_pct": 0.25, "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        }]})
        result = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY)
        processed = result["partitions_processed"][0]
        teacher = result["canonical_handoffs"]["teacher"]
        index = json.loads((root / "storage_summary_indexes" / DELTA_INDEX_FILE).read_text())

        self.assertEqual(processed["source"], "canonical_lifecycle_lessons_v1.jsonl")
        self.assertGreaterEqual(processed["outcome_linked_count"], 1)
        self.assertGreaterEqual(teacher["lessons_created"], 1)
        self.assertIn("BROKER_CONFIRMED_NATURAL_STRICT_TRUTH", index["evidence_tier_counts"])
        self.assertEqual(result["broker_actions_added"], 0)

    def test_missing_outcomes_remain_explicitly_unavailable(self):
        root = self._root({"candidate_decision_ledger_v1.jsonl": [{"symbol": "ABC", "horizon": "DAY"}]})
        result = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY, max_rows=10_000, max_bytes=10_000_000)
        self.assertEqual(result["status"], "NO_OUTCOME_DATA")
        self.assertLessEqual(result["partitions_processed"][0]["rows_examined"], 240)

    def test_v8_and_v9_consume_delta_summary_without_a_full_history_scan(self):
        root = self._root({"candidate_decision_ledger_v1.jsonl": [self._row() for _ in range(5)]})
        result = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY)
        self.assertGreaterEqual(result["v8_bounded_snapshot"]["patterns"], 1)
        self.assertIn("validation_priorities", result["v9_bounded_snapshot"])
        status = build_incremental_historical_learning_governor_v1(str(root), HEALTHY)
        self.assertEqual(status["full_history_scan_count"], 0)
        self.assertTrue(status["coverage_funnel"]["outcome_linked_observations"] >= 5)

    def test_v7_gate_and_execution_safety_are_preserved(self):
        root = self._root({"candidate_decision_ledger_v1.jsonl": [self._row() for _ in range(5)]})
        status = build_incremental_historical_learning_governor_v1(str(root), HEALTHY)
        self.assertTrue(status["explicit_cycle_required"])
        self.assertFalse(status["background_worker_integration"])
        self.assertFalse(status["execution_behavior_changed"])
        self.assertFalse(status["frozen_lifecycle_modified"])
        self.assertEqual(status["provider_calls_added"], 0)
        self.assertEqual(status["broker_calls_added"], 0)
        self.assertEqual(status["broker_actions_added"], 0)
        self.assertEqual(status["llm_calls_added"], 0)


if __name__ == "__main__":
    unittest.main()
