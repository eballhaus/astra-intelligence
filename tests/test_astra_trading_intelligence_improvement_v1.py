from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_trading_intelligence_improvement_v1 import build_trading_intelligence_improvement_suite_v1


class TradingIntelligenceImprovementTests(unittest.TestCase):
    def _write(self, root: Path, name: str, value: dict) -> None:
        (root / name).write_text(json.dumps(value), encoding="utf-8")

    def test_grades_only_original_prediction_evidence_and_preserves_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "broker_truth_records_v1.json", {"records": [
                {"truth_state": "STRICT_TRUTH", "symbol": "GOOD", "lifecycle_id": "a", "realized_return": 4,
                 "pretrade_context_v1": {"thesis": "breakout", "expected_direction": "UP", "expected_return_pct": 3, "confidence": 82}},
                {"truth_state": "STRICT_TRUTH", "symbol": "MISSING", "lifecycle_id": "b", "realized_return": 5,
                 "pretrade_context_v1": {"confidence": 90}},
            ]})
            self._write(root, "astra_unified_position_advisory_v1.json", {"positions": []})
            self._write(root, "astra_position_exit_readiness_v1.json", {"positions": []})
            self._write(root, "paper_autopilot_state.json", {})
            out = build_trading_intelligence_improvement_suite_v1(str(root))
        self.assertEqual(out["post_market"]["prediction_grading"]["graded_prediction_count"], 1)
        self.assertEqual(out["post_market"]["prediction_grading"]["unavailable_prediction_count"], 1)
        self.assertFalse(out["behavior_safe_to_apply"])
        self.assertFalse(out["automatic_promotions_enabled"])

    def test_hold_monitoring_reuses_existing_advisory_without_exit_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "broker_truth_records_v1.json", {"records": []})
            self._write(root, "astra_unified_position_advisory_v1.json", {"positions": [{"symbol": "ABC", "final_advisory": "WATCH", "evidence_used": {"thesis_state": "THESIS_INTACT", "momentum_state": "IMPROVING"}}]})
            self._write(root, "astra_position_exit_readiness_v1.json", {"positions": [{"symbol": "ABC", "recommendation": "PROTECT_PROFIT", "first_causal_blocker": "GIVEBACK"}]})
            self._write(root, "paper_autopilot_state.json", {})
            out = build_trading_intelligence_improvement_suite_v1(str(root))
        self.assertEqual(out["hold_monitoring"]["states"][0]["hold_state"], "PROTECT_PROFIT")
        self.assertFalse(out["hold_monitoring"]["automatic_exit_authority"])


if __name__ == "__main__":
    unittest.main()
