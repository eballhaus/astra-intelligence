from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.blind_spot_detection_v1 import BlindSpotDetectionV1
from engine.opportunity_cost_learning_v1 import OpportunityCostLearningV1


class CandidateQualityEvidenceTieringTests(unittest.TestCase):
    def test_shadow_counterfactual_return_is_not_real_later_price_evidence(self):
        self.assertEqual(
            OpportunityCostLearningV1._real_rejection_outcome({"hypothetical_return": 4.0}),
            (None, ""),
        )

    def test_quality_proxy_cannot_become_a_missed_or_correct_selection_signal(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            (state / "trade_lifecycle_excursion_v2.jsonl").write_text(
                json.dumps({"symbol": "SELECTED", "current_or_exit_profit_pct": 0.5}) + "\n"
            )
            (state / "candidate_decision_ledger_v1.jsonl").write_text("\n".join(json.dumps(row) for row in [
                {"symbol": "REAL", "action": "buy", "final_action": "buy", "subsequent_return": 4.5},
                {"symbol": "PROXY", "action": "buy", "final_action": "buy", "confidence": 98.0},
            ]) + "\n")
            (state / "execution_suppression_audit_v1.jsonl").write_text("")
            rows = OpportunityCostLearningV1(state_dir=str(state))._derive_rows()
            by_symbol = {row["rejected_symbol"]: row for row in rows}
            self.assertTrue(by_symbol["REAL"]["missed_better_candidate_flag"])
            self.assertEqual(by_symbol["REAL"]["comparison_evidence_status"], "REAL_LATER_PRICE")
            self.assertFalse(by_symbol["PROXY"]["missed_better_candidate_flag"])
            self.assertFalse(by_symbol["PROXY"]["correct_selection_flag"])
            self.assertEqual(by_symbol["PROXY"]["comparison_evidence_status"], "INSUFFICIENT_LATER_OUTCOME")

    def test_proxy_or_legacy_miss_flags_do_not_reach_blind_spot_counts(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            (state / "opportunity_cost_learning_v1.jsonl").write_text("\n".join(json.dumps(row) for row in [
                {
                    "symbol": "PROXY", "rejected_symbol": "PROXY",
                    "missed_better_candidate_flag": True,
                    "rejected_candidate_outcome_classification": "INSUFFICIENT_EVIDENCE",
                    "rejected_return_evidence_tier": "QUALITY_PROXY",
                    "opportunity_cost_pct": 9.0,
                },
                {
                    "symbol": "REAL", "rejected_symbol": "REAL",
                    "missed_better_candidate_flag": True,
                    "rejected_candidate_outcome_classification": "MISSED_OPPORTUNITY",
                    "rejected_return_evidence_tier": "REAL_LATER_PRICE",
                    "opportunity_cost_pct": 2.0,
                },
            ]) + "\n")
            payload = BlindSpotDetectionV1(state_dir=str(state)).status(force=True)
            self.assertEqual(payload["missed_opportunity_count"], 1)
            self.assertEqual(payload["top_missed_symbols"], ["REAL"])


if __name__ == "__main__":
    unittest.main()
