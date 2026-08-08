from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_historical_evidence_mining_knowledge_distillation_v1 import (
    LESSON_REGISTRY,
    build_historical_evidence_mining_knowledge_distillation_v1,
)
from engine.astra_storage_cache_attribution_learning_efficiency_v1 import AstraStorageCacheAttributionLearningEfficiencyV1


class HistoricalEvidenceMiningKnowledgeDistillationV1Tests(unittest.TestCase):
    def _root(self, strict_count: int = 3, indexes: dict | None = None) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "dashboard_cache").mkdir()
        (root / "storage_summary_indexes").mkdir()
        records = []
        for index in range(strict_count):
            records.append({
                "stable_key": f"truth-{index}", "truth_state": "STRICT_TRUTH", "symbol": "ABC",
                "lane_id": "DAY", "realized_return": 1.0 if index % 2 else -0.5,
                "entry_fill_id": f"entry-{index}", "exit_fill_id": f"exit-{index}",
                "pretrade_context_v1": {"market_regime": "BULL", "strategy_archetype": "BREAKOUT", "momentum_state": "STRONG"},
            })
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": records}))
        (root / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json").write_text("{}")
        (root / "dashboard_cache" / "shadow_vs_paper_performance_attribution_v1.json").write_text("{}")
        for name in ("symbol_behavior_profiles_v1.json", "astra_unified_position_advisory_v1.json"):
            (root / name).write_text("{}")
        required = (
            "market_context_learning_suite_v1.jsonl.summary_index.json",
            "opportunity_cost_learning_v1.jsonl.summary_index.json",
            "trade_archetype_regime_intelligence_v1.jsonl.summary_index.json",
            "candidate_decision_ledger_v1.jsonl.summary_index.json",
        )
        for name in required:
            payload = (indexes or {}).get(name, {"dimension_counts": {}})
            (root / "storage_summary_indexes" / name).write_text(json.dumps(payload))
        return root

    @staticmethod
    def _index(sample=20, average=1.25, dimension="regime", bucket="BULL"):
        return {
            "records_indexed": 1000,
            "generated_at": "2026-08-07T00:00:00Z",
            "dimension_counts": {dimension: {bucket: sample}},
            "outcome_by_dimension": {dimension: {bucket: {"sample_size": sample, "average_return_pct": average, "wins": sample - 2, "losses": 2}}},
        }

    def test_mines_only_summary_indexes_and_never_raw_history(self):
        root = self._root(indexes={"candidate_decision_ledger_v1.jsonl.summary_index.json": self._index()})
        # A malformed raw store would fail if V8 attempted a full-history read.
        (root / "candidate_decision_ledger_v1.jsonl").write_text("not-jsonl-and-not-read")
        result = build_historical_evidence_mining_knowledge_distillation_v1(str(root))
        self.assertEqual(result["full_history_scan_count"], 0)
        self.assertEqual(result["historical_pattern_mining"]["raw_records_read"], 0)
        self.assertEqual(result["learning_coverage"]["indexed_historical_observations_available"], 1000)
        self.assertTrue(result["historical_pattern_mining"]["patterns"])

    def test_strict_and_shadow_tiers_remain_separate(self):
        root = self._root(indexes={"replay_counterfactual_learning_v2.jsonl.summary_index.json": self._index()})
        (root / "storage_summary_indexes" / "replay_counterfactual_learning_v2.jsonl.summary_index.json").write_text(json.dumps(self._index()))
        result = build_historical_evidence_mining_knowledge_distillation_v1(str(root))
        tiers = {row["evidence_tier"] for row in result["historical_pattern_mining"]["patterns"]}
        self.assertIn("SHADOW_COUNTERFACTUAL", tiers)
        self.assertIn("BROKER_CONFIRMED_NATURAL_STRICT_TRUTH", tiers)
        self.assertFalse(result["automatic_adaptation_authority"])

    def test_tiny_strict_samples_never_become_repeatable(self):
        result = build_historical_evidence_mining_knowledge_distillation_v1(str(self._root(strict_count=3)))
        strict = [row for row in result["historical_pattern_mining"]["patterns"] if row["evidence_tier"] == "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH"]
        self.assertTrue(strict)
        self.assertNotIn("REPEATABLE_PATTERN", {row["confidence_state"] for row in strict})
        self.assertEqual(result["knowledge_validation_drift_cortex_handoff"]["cortex_ready_lessons"], [])

    def test_interactions_are_bounded_and_require_incremental_value(self):
        result = build_historical_evidence_mining_knowledge_distillation_v1(str(self._root(strict_count=12)))
        interactions = result["multi_factor_interaction_discovery"]
        self.assertLessEqual(len(interactions["interactions"]), interactions["max_interactions"])
        self.assertEqual(interactions["max_dimensions"], 3)
        self.assertTrue(interactions["combinatorial_search_prevented"])
        self.assertTrue(all(row["interaction_state"] in {"NO_INCREMENTAL_VALUE", "POSSIBLE_INTERACTION", "REPEATABLE_INTERACTION"} for row in interactions["interactions"]))

    def test_redundancy_is_observational_and_never_removed(self):
        indexes = {
            "candidate_decision_ledger_v1.jsonl.summary_index.json": self._index(sample=20),
            "outcome_labels_v1.jsonl.summary_index.json": self._index(sample=20),
        }
        root = self._root(indexes=indexes)
        (root / "storage_summary_indexes" / "outcome_labels_v1.jsonl.summary_index.json").write_text(json.dumps(indexes["outcome_labels_v1.jsonl.summary_index.json"]))
        result = build_historical_evidence_mining_knowledge_distillation_v1(str(root))
        redundancy = result["evidence_redundancy_low_value_detection"]
        self.assertFalse(redundancy["automatic_evidence_removal"])
        self.assertTrue(all(not row["automatic_removal"] for row in redundancy["findings"]))

    def test_lessons_deduplicate_and_preserve_provenance(self):
        indexes = {
            "candidate_decision_ledger_v1.jsonl.summary_index.json": self._index(sample=20),
            "outcome_labels_v1.jsonl.summary_index.json": self._index(sample=20),
        }
        root = self._root(indexes=indexes)
        (root / "storage_summary_indexes" / "outcome_labels_v1.jsonl.summary_index.json").write_text(json.dumps(indexes["outcome_labels_v1.jsonl.summary_index.json"]))
        lessons = build_historical_evidence_mining_knowledge_distillation_v1(str(root))["knowledge_distillation_lesson_registry"]["lessons"]
        regime = [row for row in lessons if row["applicable_context"] == {"regime": "BULL"}]
        self.assertEqual(len(regime), 1)
        self.assertGreaterEqual(len(regime[0]["source_pattern_ids"]), 2)

    def test_drift_downgrades_lessons_without_deleting_provenance(self):
        root = self._root(indexes={"candidate_decision_ledger_v1.jsonl.summary_index.json": self._index(sample=20)})
        result = build_historical_evidence_mining_knowledge_distillation_v1(str(root), drift_override={"status": "HIGH_DRIFT"})
        lessons = result["knowledge_distillation_lesson_registry"]["lessons"]
        self.assertTrue(lessons)
        self.assertTrue(all(row["state"] == "DRIFTING" and row["source_pattern_ids"] for row in lessons))

    def test_registry_persistence_is_explicit_and_status_is_read_only(self):
        root = self._root(indexes={"candidate_decision_ledger_v1.jsonl.summary_index.json": self._index()})
        preview = build_historical_evidence_mining_knowledge_distillation_v1(str(root))
        self.assertFalse(preview["knowledge_distillation_lesson_registry"]["persisted"])
        self.assertFalse((root / LESSON_REGISTRY).exists())
        persisted = build_historical_evidence_mining_knowledge_distillation_v1(str(root), persist_lessons=True)
        self.assertTrue(persisted["knowledge_distillation_lesson_registry"]["persisted"])
        self.assertTrue((root / LESSON_REGISTRY).exists())

    def test_v7_remains_required_and_execution_contract_is_unchanged(self):
        result = build_historical_evidence_mining_knowledge_distillation_v1(str(self._root(strict_count=20)))
        self.assertTrue(result["knowledge_validation_drift_cortex_handoff"]["v7_required_for_adaptation"])
        self.assertFalse(result["execution_behavior_changed"])
        self.assertEqual(result["provider_calls_added"], 0)
        self.assertEqual(result["broker_calls_added"], 0)
        self.assertEqual(result["broker_actions_added"], 0)
        self.assertEqual(result["llm_calls_added"], 0)

    def _producer_index(self, rows):
        root = self._root()
        source = root / "candidate_decision_ledger_v1.jsonl"
        source.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        producer = AstraStorageCacheAttributionLearningEfficiencyV1(state_dir=str(root))
        producer._build_summary_indexes()
        return root, json.loads((root / "storage_summary_indexes" / "candidate_decision_ledger_v1.jsonl.summary_index.json").read_text())

    def test_bounded_producer_links_dimensions_to_tier_separated_outcomes(self):
        rows = [
            {"symbol": "ABC", "horizon": "DAY", "regime": "RISK_ON", "outcome": "WIN", "realized_return_pct": 1.2, "truth_state": "STRICT_TRUTH"},
            {"symbol": "ABC", "horizon": "DAY", "regime": "RISK_ON", "outcome": "LOSS", "realized_return_pct": -0.4, "shadow": True},
            {"symbol": "ABC", "horizon": "DAY", "regime": "RISK_ON", "outcome": "WIN", "realized_return_pct": 0.5, "validated": True},
        ]
        _, index = self._producer_index(rows)
        bucket = index["outcome_by_dimension"]["symbol"]["abc"]
        self.assertEqual(index["outcome_linked_observations"], 3)
        self.assertIn("BROKER_CONFIRMED_NATURAL_STRICT_TRUTH", bucket)
        self.assertIn("SHADOW_COUNTERFACTUAL", bucket)
        self.assertIn("VALIDATED_OPERATIONAL_EVIDENCE", bucket)
        self.assertEqual(bucket["BROKER_CONFIRMED_NATURAL_STRICT_TRUTH"]["average_return_pct"], 1.2)

    def test_missing_or_unit_ambiguous_outcome_is_not_converted_into_profitability_evidence(self):
        _, index = self._producer_index([{"symbol": "ABC", "horizon": "DAY", "regime": "RISK_ON", "realized_return": 1.5}])
        self.assertEqual(index["outcome_linkable_observations"], 0)
        self.assertEqual(index["outcome_linked_observations"], 0)
        self.assertEqual(index["outcome_by_dimension"], {})

    def test_v8_consumes_bounded_outcome_aggregate_with_provenance(self):
        rows = [
            {"symbol": "ABC", "horizon": "DAY", "regime": "RISK_ON", "outcome": "WIN", "realized_return_pct": 1.0, "validated": True}
            for _ in range(5)
        ]
        root, _ = self._producer_index(rows)
        result = build_historical_evidence_mining_knowledge_distillation_v1(str(root))
        coverage = result["learning_coverage"]
        patterns = result["historical_pattern_mining"]["patterns"]
        self.assertEqual(coverage["outcome_linked_observations"], 5)
        self.assertGreater(coverage["outcome_linkage_coverage_pct"], 0)
        self.assertTrue(any(row["source"] == "candidate_decision_ledger_v1.jsonl.summary_index.json" for row in patterns))
        self.assertTrue(any(row["evidence_tier"] == "VALIDATED_OPERATIONAL_EVIDENCE" for row in patterns))
        self.assertEqual(result["full_history_scan_count"], 0)


if __name__ == "__main__":
    unittest.main()
