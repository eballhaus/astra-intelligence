from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_autonomous_learning_safe_adaptation_v1 import build_autonomous_learning_safe_adaptation_v1


class AutonomousLearningSafeAdaptationV1Tests(unittest.TestCase):
    def _root(self, strict_count=3, shadow=None):
        root = Path(tempfile.mkdtemp()); (root / "dashboard_cache").mkdir(); (root / "storage_summary_indexes").mkdir()
        records = [{
            "stable_key": str(i), "truth_state": "STRICT_TRUTH", "symbol": "ABC", "lane_id": "DAY",
            "realized_return": 1, "mfe": 2, "mae": -1, "entry_fill_id": f"entry-{i}",
            "exit_fill_id": f"exit-{i}", "exit_reason": "natural", "broker_residual_zero_confirmed": True,
            "learning_acknowledged": True,
            "pretrade_context_v1": {"candidate_id": str(i), "thesis": "momentum", "confidence": 80,
                                    "lane": "DAY", "market_regime": "BULL" if i % 2 else "NEUTRAL"},
        } for i in range(strict_count)]
        (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": records}))
        (root / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json").write_text(json.dumps(shadow or {}))
        (root / "dashboard_cache" / "shadow_vs_paper_performance_attribution_v1.json").write_text(json.dumps({}))
        for name in ("symbol_behavior_profiles_v1.json", "astra_unified_position_advisory_v1.json"):
            (root / name).write_text(json.dumps({}))
        for name in ("market_context_learning_suite_v1.jsonl.summary_index.json", "opportunity_cost_learning_v1.jsonl.summary_index.json", "trade_archetype_regime_intelligence_v1.jsonl.summary_index.json", "candidate_decision_ledger_v1.jsonl.summary_index.json"):
            (root / "storage_summary_indexes" / name).write_text(json.dumps({"dimension_counts": {}}))
        return root

    def test_insufficient_strict_truth_cannot_self_promote(self):
        result = build_autonomous_learning_safe_adaptation_v1(str(self._root()), {})
        self.assertEqual(result["adaptation_candidate_generator"]["state"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["cortex_adaptation_decision"]["decision"], "COLLECT_MORE_EVIDENCE")
        self.assertFalse(result["bounded_canary_controller"]["automatic_paper_activation"])
        self.assertEqual(result["active_adaptation_count"], 0)

    def test_domain_governance_and_owner_notice_contracts(self):
        blocked = build_autonomous_learning_safe_adaptation_v1(str(self._root()), {"domain": "broker_authority"})
        self.assertEqual(blocked["adaptation_candidate_generator"]["state"], "NOT_ALLOWED")
        self.assertEqual(blocked["cortex_adaptation_decision"]["decision"], "REJECT_CHANGE")
        shadow = {"ab_validation": {"timestamp_valid_evidence_only": True, "baseline": {"sample_size": 20, "expectancy": 1, "drawdown": 2}, "candidate": {"sample_size": 20, "expectancy": 2, "drawdown": 1}}}
        result = build_autonomous_learning_safe_adaptation_v1(str(self._root(20, shadow)), {"domain": "research_prioritization"}, governance_override={"passed": True})
        self.assertEqual(result["shadow_ab_validation"]["status"], "CANDIDATE_BETTER")
        self.assertEqual(result["cortex_adaptation_decision"]["decision"], "CANARY_ELIGIBLE")
        self.assertEqual(result["owner_notification"]["status"], "NOTIFICATION_PREPARED")
        self.assertTrue(result["rollback"]["baseline_preserved"])
        self.assertEqual(result["broker_actions_used"], 0)
        denied = build_autonomous_learning_safe_adaptation_v1(
            str(self._root(20, shadow)), {"domain": "research_prioritization"}, governance_override={"passed": False}
        )
        self.assertEqual(denied["cortex_adaptation_decision"]["decision"], "REJECT_CHANGE")
