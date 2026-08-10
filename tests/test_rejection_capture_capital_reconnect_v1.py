from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_historical_evidence_mining_knowledge_distillation_v1 import LESSON_REGISTRY
from engine.astra_incremental_historical_learning_governor_v1 import run_incremental_historical_learning_cycle_v1
from engine.astra_knowledge_warehouse_v1 import AstraKnowledgeWarehouseV1
from engine.opportunity_cost_learning_v1 import OpportunityCostLearningV1
from engine.astra_portfolio_capacity_release_review_v1 import build_portfolio_release_review
from engine.astra_trading_intelligence_improvement_v3 import (
    _classify_rejection,
    _ledger_candidates,
    _missed_opportunity,
    _real_rejection_outcome,
)
from server_extend import _shadow_candidate_lesson_count


HEALTHY = {"worker_health": "HEALTHY", "resource_state": "RESOURCE_NORMAL"}


class RejectedCandidateOutcomeCaptureTests(unittest.TestCase):
    def test_real_later_return_requires_a_real_price_key(self):
        self.assertEqual(_real_rejection_outcome({"later_return_after_rejection": 4.2}), (4.2, "later_return_after_rejection"))
        self.assertEqual(_real_rejection_outcome({"subsequent_return": -1.1}), (-1.1, "subsequent_return"))
        # A quality-score proxy must never be treated as a real later price.
        self.assertEqual(_real_rejection_outcome({"rejected_return_pct": 1.5}), (None, ""))

    def test_rejection_classification_is_real_evidence_only_and_safety_preserving(self):
        self.assertEqual(_classify_rejection({"subsequent_return": 3}), "MISSED_OPPORTUNITY")
        self.assertEqual(_classify_rejection({"later_return_after_rejection": -2}), "CORRECT_REJECTION")
        self.assertEqual(_classify_rejection({"subsequent_return": 3, "safety_blocker": True}), "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED")
        self.assertEqual(_classify_rejection({"subsequent_return": 3, "liquidity_blocker": True}), "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED")
        self.assertEqual(_classify_rejection({"rejected_return_pct": 3}), "INSUFFICIENT_EVIDENCE")

    def test_ledger_candidates_only_carry_real_later_price_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate_decision_ledger_v1.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in [
                {"symbol": "MISS", "later_return_after_rejection": 4.2},
                {"symbol": "SAFE", "subsequent_return": 9.0, "blocked_reasons": ["safety_filter"]},
                {"symbol": "BLOAT", "rejected_return_pct": 1.5},
                {"symbol": "NOEVID", "confidence": 80},
            ]) + "\n")
            candidates = _ledger_candidates(path)
            symbols = {row["symbol"] for row in candidates}
            self.assertEqual(symbols, {"MISS", "SAFE"})
            self.assertEqual(candidates[0]["rejection_later_price_key"], "later_return_after_rejection")
            self.assertTrue(candidates[1]["safety_blocker"])

    def test_missed_opportunity_classifies_shadow_and_ledger_without_authority(self):
        result = _missed_opportunity(
            {},
            {"candidate_lessons": [{"symbol": "SHADOW", "subsequent_return": 2}]},
            [{"symbol": "LEDGER", "subsequent_return": 5, "rejection_later_price_key": "subsequent_return"}],
        )
        rows = {row["symbol"]: row for row in result["classified_shadow_rejections"]}
        self.assertEqual(rows["SHADOW"]["classification"], "MISSED_OPPORTUNITY")
        self.assertEqual(rows["SHADOW"]["evidence_tier"], "SHADOW_COUNTERFACTUAL")
        self.assertEqual(rows["LEDGER"]["classification"], "MISSED_OPPORTUNITY")
        self.assertEqual(rows["LEDGER"]["evidence_tier"], "REJECTION_LEDGER_LATER_PRICE")
        self.assertFalse(result["automatic_rejection_policy_authority"])
        self.assertTrue(result["safety_rejection_preserved_when_price_rises"])

    def test_candidate_lessons_shape_mismatch_is_detected_fail_closed(self):
        result = _missed_opportunity({}, {"candidate_lessons": 7}, [])
        self.assertTrue(result["candidate_lessons_shape_mismatch_detected"])
        self.assertEqual(result["status"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(result["automatic_rejection_policy_authority"])

    def test_opportunity_cost_prefers_real_evidence_and_persists_classification(self):
        self.assertEqual(
            OpportunityCostLearningV1._real_rejection_outcome({"rejected_return_pct": 5.0, "subsequent_return": 2.5}),
            (2.5, "subsequent_return"),
        )
        self.assertEqual(OpportunityCostLearningV1._classify_rejection({"subsequent_return": 3}, 3.0, "REAL_LATER_PRICE"), "MISSED_OPPORTUNITY")
        self.assertEqual(
            OpportunityCostLearningV1._classify_rejection({"safety_blocker": True, "subsequent_return": 3}, 3.0, "REAL_LATER_PRICE"),
            "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED",
        )
        self.assertEqual(OpportunityCostLearningV1._classify_rejection({}, 5.0, "QUALITY_PROXY"), "INSUFFICIENT_EVIDENCE")

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "trade_lifecycle_excursion_v2.jsonl").write_text(
                json.dumps({"symbol": "AAASEL", "current_or_exit_profit_pct": 0.5}) + "\n"
            )
            (Path(tmp) / "candidate_decision_ledger_v1.jsonl").write_text("\n".join(json.dumps(row) for row in [
                {"symbol": "REAL", "action": "buy", "final_action": "buy", "subsequent_return": 4.5},
                {"symbol": "PROXY", "action": "buy", "final_action": "buy", "rejected_return_pct": 1.0},
            ]) + "\n")
            (Path(tmp) / "execution_suppression_audit_v1.jsonl").write_text("")
            rows = OpportunityCostLearningV1(state_dir=tmp)._derive_rows()
            by_symbol = {row["rejected_symbol"]: row for row in rows}
            self.assertEqual(by_symbol["REAL"]["rejected_return_evidence_tier"], "REAL_LATER_PRICE")
            self.assertEqual(by_symbol["REAL"]["rejected_candidate_outcome_classification"], "MISSED_OPPORTUNITY")
            self.assertEqual(by_symbol["PROXY"]["rejected_return_evidence_tier"], "QUALITY_PROXY")
            self.assertEqual(by_symbol["PROXY"]["rejected_candidate_outcome_classification"], "INSUFFICIENT_EVIDENCE")

    def test_legacy_numeric_consumers_prefer_the_explicit_count(self):
        self.assertEqual(_shadow_candidate_lesson_count({"candidate_lesson_count": 7, "candidate_lessons": []}), 7)
        self.assertEqual(_shadow_candidate_lesson_count({"candidate_lessons": 5}), 5)
        self.assertEqual(_shadow_candidate_lesson_count({"candidate_lessons": []}), 0)
        self.assertEqual(_shadow_candidate_lesson_count(None), 0)


class V8PersistenceReuseTests(unittest.TestCase):
    def _governor_root(self) -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "dashboard_cache").mkdir()
        (root / "storage_summary_indexes").mkdir()
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": []}))
        for name in ("realistic_shadow_evidence_learning_lab_v1.json", "shadow_vs_paper_performance_attribution_v1.json"):
            (root / "dashboard_cache" / name).write_text("{}")
        for name in ("symbol_behavior_profiles_v1.json", "astra_unified_position_advisory_v1.json"):
            (root / name).write_text("{}")
        row = {"symbol": "ABC", "horizon": "DAY", "regime": "RISK_ON", "outcome": "WIN", "realized_return_pct": 1.25, "shadow": True}
        (root / "candidate_decision_ledger_v1.jsonl").write_text("".join(json.dumps(row) + "\n" for _ in range(5)))
        return root

    def test_governor_cycle_persists_v8_registry_at_the_prod_call_site(self):
        root = self._governor_root()
        result = run_incremental_historical_learning_cycle_v1(str(root), resource_facts=HEALTHY)
        self.assertEqual(result["status"], "COMPLETE")
        registry = root / LESSON_REGISTRY
        self.assertTrue(registry.exists())
        payload = json.loads(registry.read_text())
        self.assertIn("version", payload)
        self.assertIsInstance(payload.get("lessons"), list)

    def test_governor_status_path_stays_read_only(self):
        from engine.astra_incremental_historical_learning_governor_v1 import build_incremental_historical_learning_governor_v1
        root = self._governor_root()
        build_incremental_historical_learning_governor_v1(str(root), HEALTHY)
        self.assertFalse((root / LESSON_REGISTRY).exists())

    def test_warehouse_advisory_consumer_reads_persisted_registry_boundedly(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / LESSON_REGISTRY).write_text(json.dumps({
                "version": "1.0.0", "updated_at": "2026-08-09T00:00:00Z",
                "lessons": [{"lesson_id": "L1"}, {"lesson_id": "L2"}],
            }))
            advisory = AstraKnowledgeWarehouseV1(state_dir=tmp, ttl_seconds=0).status(force=True)["distilled_lesson_reuse"]
            self.assertGreaterEqual(advisory["lessons_available"], 2)
            self.assertTrue(advisory["advisory_only"])
            self.assertFalse(advisory["automatic_adaptation"])
            self.assertEqual(advisory["owner"], "historical_evidence_mining_knowledge_distillation_v1")
            references = AstraKnowledgeWarehouseV1(state_dir=tmp, ttl_seconds=0).source_references()
            self.assertNotIn("distilled_lessons", {row["source_identity"] for row in references})
            catalog = AstraKnowledgeWarehouseV1(state_dir=tmp, ttl_seconds=0).status(force=True)["source_catalog"]
            distilled = next(row for row in catalog if row.get("store") == "distilled_lessons")
            self.assertTrue(distilled["exists"])
            self.assertEqual(distilled["owner"], "historical_evidence_mining_knowledge_distillation_v1")


class ReleasableCapitalMeasurementTests(unittest.TestCase):
    def test_releasable_capital_sums_real_broker_market_values(self):
        result = build_portfolio_release_review([
            {"symbol": "KEEP", "entry_price": 10, "current_price": 10.1, "market_value": 100},
            {"symbol": "BROKEN", "entry_price": 10, "current_price": 8, "thesis_state": "broken", "market_value": 500},
            {"symbol": "REP", "entry_price": 10, "current_price": 9, "duplicate_exposure": True, "market_value": 300},
        ])
        self.assertEqual(result["primary_state_counts"]["THESIS_BROKEN"], 1)
        self.assertEqual(result["primary_state_counts"]["REPLACE_CANDIDATE"], 1)
        self.assertEqual(result["estimated_releasable_capital"], 800.0)
        self.assertEqual(result["releasable_capital_status"], "OBSERVATIONAL_BROKER_DERIVED")
        self.assertEqual(len(result["releasable_capital_components"]), 2)

    def test_releasable_capital_is_unknown_without_release_candidates(self):
        result = build_portfolio_release_review([
            {"symbol": "KEEP", "entry_price": 10, "current_price": 10.1, "market_value": 100},
        ])
        self.assertIsNone(result["estimated_releasable_capital"])
        self.assertEqual(result["releasable_capital_status"], "UNKNOWN_NO_RELEASE_CANDIDATES")

    def test_releasable_capital_is_unknown_when_market_value_is_missing(self):
        result = build_portfolio_release_review([
            {"symbol": "BROKEN", "entry_price": 10, "current_price": 8, "thesis_state": "broken"},
        ])
        self.assertIsNone(result["estimated_releasable_capital"])
        self.assertEqual(result["releasable_capital_status"], "UNKNOWN_MARKET_VALUE_MISSING")

    def test_release_review_remains_advisory_without_broker_actions(self):
        result = build_portfolio_release_review([
            {"symbol": "BROKEN", "entry_price": 10, "current_price": 8, "thesis_state": "broken", "market_value": 500},
        ])
        self.assertFalse(result["automatic_action_authorized"])
        self.assertTrue(result["no_exit_orders_submitted"])
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)


if __name__ == "__main__":
    unittest.main()