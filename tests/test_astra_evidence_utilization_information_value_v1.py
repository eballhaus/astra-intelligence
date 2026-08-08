from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_evidence_utilization_information_value_v1 import (
    build_evidence_utilization_information_value_v1,
)


class EvidenceUtilizationInformationValueV1Tests(unittest.TestCase):
    def _root(self, *, linked: bool = True, strict_count: int = 3) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "dashboard_cache").mkdir()
        (root / "storage_summary_indexes").mkdir()
        truths = [{
            "stable_key": f"truth-{index}", "truth_state": "STRICT_TRUTH", "symbol": "ABC",
            "lane_id": "DAY", "realized_return_pct": 1.0,
            "entry_fill_id": f"entry-{index}", "exit_fill_id": f"exit-{index}",
            "pretrade_context_v1": {"market_regime": "RISK_ON", "strategy_archetype": "BREAKOUT", "momentum_state": "STRONG"},
        } for index in range(strict_count)]
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": truths}))
        for name in ("realistic_shadow_evidence_learning_lab_v1.json", "shadow_vs_paper_performance_attribution_v1.json"):
            (root / "dashboard_cache" / name).write_text("{}")
        for name in ("symbol_behavior_profiles_v1.json", "astra_unified_position_advisory_v1.json"):
            (root / name).write_text("{}")
        payload = {
            "records_indexed": 1000, "outcome_linkable_observations": 20 if linked else 0,
            "outcome_linked_observations": 20 if linked else 0,
            "aggregate_count": 1 if linked else 0,
            "dimensions_linked": ["regime"] if linked else [],
            "dimensions_without_outcomes": [] if linked else ["regime"],
            "outcome_by_dimension": {"regime": {"RISK_ON": {
                "SHADOW_COUNTERFACTUAL": {"sample_size": 20, "average_return_pct": 1.0, "wins": 15, "losses": 5},
            }}} if linked else {},
        }
        (root / "storage_summary_indexes" / "candidate_decision_ledger_v1.jsonl.summary_index.json").write_text(json.dumps(payload))
        return root

    def test_status_consumes_bounded_snapshots_without_refresh_or_raw_scan(self):
        root = self._root()
        (root / "candidate_decision_ledger_v1.jsonl").write_text("must-not-be-read")
        result = build_evidence_utilization_information_value_v1(str(root))
        self.assertEqual(result["producer_refreshes_triggered"], 0)
        self.assertEqual(result["full_history_scan_count"], 0)
        self.assertEqual(result["v8_1_linkage_refresh"]["outcome_linked_observations"], 20)

    def test_overlapping_indexes_are_not_reported_as_unique_events(self):
        result = build_evidence_utilization_information_value_v1(str(self._root()))
        coverage = result["evidence_utilization_coverage"]
        self.assertEqual(coverage["unique_market_event_count"], "UNAVAILABLE_OVERLAPPING_SUMMARY_INDEXES")
        self.assertIn("overlapping", coverage["denominator_note"].lower())

    def test_indexed_but_unlinked_evidence_is_not_given_a_value_score(self):
        result = build_evidence_utilization_information_value_v1(str(self._root(linked=False)))
        regime = next(item for item in result["information_value"]["findings"] if item["dimension"] == "regime")
        self.assertEqual(regime["utilization_state"], "INDEXED_NOT_OUTCOME_LINKED")
        self.assertEqual(regime["information_value_state"], "UNPROVEN")

    def test_shadow_outcomes_are_not_enough_for_unused_high_value_handoff(self):
        result = build_evidence_utilization_information_value_v1(str(self._root()))
        regime = next(item for item in result["information_value"]["findings"] if item["dimension"] == "regime")
        self.assertEqual(regime["information_value_state"], "POSSIBLE_VALUE")
        self.assertEqual(regime["v4_reliability"]["association"], "UNAVAILABLE")
        self.assertEqual(result["unused_high_value_evidence"]["candidates"], [])
        self.assertEqual(result["v7_cortex_handoff"]["candidates"], [])

    def test_priority_is_deterministic_and_v7_gate_is_preserved(self):
        root = self._root()
        first = build_evidence_utilization_information_value_v1(str(root))
        second = build_evidence_utilization_information_value_v1(str(root))
        self.assertEqual(first["learning_teaching_priority"], second["learning_teaching_priority"])
        self.assertTrue(first["v7_cortex_handoff"]["v7_required_for_adaptation"])
        self.assertFalse(first["automatic_adaptation_authority"])

    def test_execution_and_external_call_contracts_remain_frozen(self):
        result = build_evidence_utilization_information_value_v1(str(self._root()))
        self.assertFalse(result["execution_behavior_changed"])
        self.assertFalse(result["frozen_lifecycle_modified"])
        self.assertEqual(result["provider_calls_added"], 0)
        self.assertEqual(result["broker_calls_added"], 0)
        self.assertEqual(result["broker_actions_added"], 0)
        self.assertEqual(result["llm_calls_added"], 0)


if __name__ == "__main__":
    unittest.main()
