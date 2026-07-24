from __future__ import annotations

import tempfile
import unittest

from engine.astra_legacy_position_risk_triage_v1 import (
    build_legacy_position_risk_triage_v1,
    load_legacy_position_risk_triage_v1,
    save_legacy_position_risk_triage_v1,
    triage_legacy_position_v1,
)


def _recovery(symbol: str = "AAA", lane: str = "UNAVAILABLE", horizon: str = "UNAVAILABLE"):
    return {"positions": [{"symbol": symbol, "lane_status": "RESOLVED" if lane != "UNAVAILABLE" else "UNAVAILABLE",
                              "horizon_status": "RESOLVED" if horizon != "UNAVAILABLE" else "UNAVAILABLE",
                              "metadata_generation": None}]}


class LegacyPositionRiskTriageTests(unittest.TestCase):
    def test_loss_alone_does_not_create_exit_review(self):
        decision = triage_legacy_position_v1({"symbol": "AAA", "unrealized_plpc": -0.09})
        self.assertEqual(decision["recommendation"], "WATCH")
        self.assertEqual(decision["execution_authority"], "DISABLED")

    def test_thesis_and_replacement_recommendations_are_explainable(self):
        broken = triage_legacy_position_v1({"symbol": "AAA", "thesis_state": "BROKEN", "momentum_state": "WEAK"})
        replacement = triage_legacy_position_v1({"symbol": "AAA", "unrealized_plpc": -0.02, "momentum_state": "WEAK"}, replacement={"state": "SUPERIOR"})
        self.assertEqual(broken["recommendation"], "THESIS_BROKEN")
        self.assertEqual(replacement["recommendation"], "REPLACE_CANDIDATE")
        self.assertTrue(broken["advisory_only"])

    def test_legacy_only_and_fmp_context_are_counted(self):
        triage = build_legacy_position_risk_triage_v1(
            {"AAA": {"symbol": "AAA", "unrealized_plpc": -0.01, "momentum_state": "HEALTHY"},
             "PH": {"symbol": "PH", "unrealized_plpc": 0.01}},
            {"positions": _recovery()["positions"] + _recovery("PH", "DAY", "scalp")["positions"]},
            fmp_evidence={"a": {"symbol": "AAA", "response_state": "SUCCESS", "normalized_fields": {"sector": "Tech"}}},
        )
        self.assertEqual(triage["legacy_position_count"], 1)
        self.assertEqual(triage["triaged_count"], 1)
        self.assertEqual(triage["FMP_evidence_used_count"], 1)
        self.assertEqual(triage["execution_authority"], "DISABLED")

    def test_state_round_trip_is_bounded(self):
        triage = build_legacy_position_risk_triage_v1({"AAA": {"symbol": "AAA"}}, _recovery())
        with tempfile.TemporaryDirectory() as directory:
            save_legacy_position_risk_triage_v1(triage, directory)
            loaded = load_legacy_position_risk_triage_v1(directory)
        self.assertEqual(loaded["triaged_count"], 1)
        self.assertEqual(loaded["positions"][0]["symbol"], "AAA")


if __name__ == "__main__":
    unittest.main()
