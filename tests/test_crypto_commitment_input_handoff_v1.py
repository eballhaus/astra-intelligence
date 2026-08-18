"""Regression coverage for CRYPTO commitment-input provenance handoffs."""
from __future__ import annotations

import os
import tempfile
import unittest

from engine.paper_autopilot import PaperAutopilotEngine, _normalize_paper_entry_bridge


def _crypto_candidate(**extra) -> dict:
    return {
        "symbol": "BTC/USD",
        "asset_type": "crypto",
        "asset_class": "crypto",
        "lane_id": "CRYPTO",
        "paper_entry_horizon_style": "day_trade",
        "action": "Buy",
        "buy_quality_score": 70.0,
        "confidence": 75.0,
        "ranking_feedback_profile": {"entry_edge_score": 0.5},
        "persona_grades": {},
        "persona_best_fit": "Unknown",
        "persona_consensus_summary": {
            "consensus_strength": 0.0,
            "disagreement_index": 100.0,
            "persona_best_fit": "Unknown",
        },
        "persona_disagreement_index": 100.0,
        **extra,
    }


class CryptoCommitmentInputHandoffTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="astra_crypto_commitment_handoff_")
        self.addCleanup(self.directory.cleanup)
        self.engine = PaperAutopilotEngine(
            db_path=os.path.join(self.directory.name, "paper.db"),
            state_path=os.path.join(self.directory.name, "state.json"),
            enabled=False,
        )

    def test_profile_entry_edge_reaches_existing_commitment_input(self):
        bridged = _normalize_paper_entry_bridge(_crypto_candidate())
        self.assertEqual(bridged["entry_edge_score"], 0.5)
        self.assertEqual(
            bridged["entry_edge_score_provenance_v1"],
            "ranking_feedback_profile.entry_edge_score",
        )

    def test_candidate_local_entry_edge_keeps_precedence(self):
        bridged = _normalize_paper_entry_bridge(_crypto_candidate(entry_edge_score=-0.25))
        self.assertEqual(bridged["entry_edge_score"], -0.25)
        self.assertNotIn("entry_edge_score_provenance_v1", bridged)

    def test_measured_persona_disagreement_is_not_rewritten(self):
        bridged = _normalize_paper_entry_bridge(_crypto_candidate(
            persona_grades={"Trend": {"persona_grade_percent": 80.0}},
            persona_best_fit="Trend",
            persona_consensus_summary={
                "consensus_strength": 72.0,
                "disagreement_index": 100.0,
                "persona_best_fit": "Trend",
            },
        ))
        self.assertEqual(bridged["persona_disagreement_index"], 100.0)
        self.assertNotIn("persona_disagreement_input_state_v1", bridged)

    def test_missing_persona_placeholder_uses_existing_gate_default(self):
        allowed, reason, meta = self.engine._entry_commitment_gate_v1(
            _crypto_candidate(), require_trusted_quote=False,
        )
        self.assertTrue(allowed, reason)
        self.assertEqual(reason, "eligible")
        self.assertEqual(meta["commitment_score"], 58.7)

        bridged = _normalize_paper_entry_bridge(_crypto_candidate())
        self.assertNotIn("persona_disagreement_index", bridged)
        self.assertEqual(bridged["persona_disagreement_input_state_v1"], "DEFAULT_UNAVAILABLE")

    def test_commitment_trace_marks_placeholder_as_default_without_formula_change(self):
        rejected = _crypto_candidate(
            buy_quality_score=60.0,
            confidence=70.0,
            ranking_feedback_profile={"entry_edge_score": 0.0},
        )
        allowed, reason, meta = self.engine._entry_commitment_gate_v1(
            rejected, require_trusted_quote=False,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "entry_commitment_below_threshold")
        trace = meta["entry_commitment_trace_v1"]
        self.assertEqual(trace["applied_minimum"], 58.0)
        self.assertEqual(trace["entry_edge_score"], 0.0)
        self.assertEqual(trace["persona_disagreement_index"], 50.0)
        self.assertEqual(trace["persona_disagreement_input_state"], "DEFAULT_UNAVAILABLE")
        self.assertIn("persona_disagreement_index", trace["defaulted_inputs"])


if __name__ == "__main__":
    unittest.main()
