from __future__ import annotations

import tempfile
import unittest

from engine.astra_legacy_portfolio_resolution_v1 import (
    build_legacy_portfolio_resolution_v1,
    load_legacy_portfolio_resolution_v1,
    save_legacy_portfolio_resolution_v1,
)
from engine.astra_unified_position_advisory_v1 import (
    build_position_exit_readiness_v1,
    build_unified_position_advisory_v1,
)


class LegacyPortfolioResolutionTests(unittest.TestCase):
    def setUp(self):
        self.positions = {
            "LEG": {"symbol": "LEG", "market_value": 100.0, "cost_basis": 125.0, "unrealized_pl": -25.0, "unrealized_plpc": -0.2},
            "OWN": {"symbol": "OWN", "market_value": 80.0, "cost_basis": 75.0, "unrealized_pl": 5.0, "unrealized_plpc": 0.066},
        }
        self.recovery = {"positions": [
            {"symbol": "LEG", "lane_status": "UNAVAILABLE", "horizon_status": "UNAVAILABLE", "metadata_generation": "LEGACY"},
            {"symbol": "OWN", "lane_status": "RESOLVED", "horizon_status": "RESOLVED", "metadata_generation": "V1_MANDATORY"},
        ]}
        self.evidence = {"positions": [
            {"symbol": "LEG", "opportunity_cost_status": "NO_ELIGIBLE_REPLACEMENT", "replacement_candidate_status": "NO_ELIGIBLE_REPLACEMENT", "first_causal_blocker": "COMPLETED_BAR_PRODUCER_UNAVAILABLE"},
            {"symbol": "OWN", "opportunity_cost_status": "NO_ELIGIBLE_REPLACEMENT", "replacement_candidate_status": "NO_ELIGIBLE_REPLACEMENT", "first_causal_blocker": "EVIDENCE_CURRENT"},
        ]}

    def test_segmentation_keeps_legacy_out_of_managed_metrics(self):
        triage = {"positions": [{"symbol": "LEG", "recommendation": "EXIT_REVIEW", "confidence": "MODERATE", "first_causal_blocker": "MATERIAL_LOSS_WITH_MOMENTUM_DETERIORATION", "evidence_used": {"momentum_state": "DETERIORATING"}, "evidence_missing": []}]}
        result = build_legacy_portfolio_resolution_v1(self.positions, self.recovery, triage=triage, evidence=self.evidence)
        self.assertEqual(result["total_broker_portfolio"]["position_count"], 2)
        self.assertEqual(result["legacy_portfolio"]["position_count"], 1)
        self.assertEqual(result["astra_managed_portfolio"]["position_count"], 1)
        self.assertTrue(result["performance_population_contract"]["legacy_excluded_from_astra_managed_metrics"])
        row = result["positions"][0]
        self.assertEqual(row["resolution_plan"], "FULL_EXIT_REVIEW")
        self.assertEqual(row["estimated_capacity_releasable"], 100.0)
        self.assertEqual(row["execution_authority"], "DISABLED")

    def test_missing_evidence_waits_without_fabricating_metadata(self):
        triage = {"positions": [{"symbol": "LEG", "recommendation": "WATCH", "confidence": "LOW", "first_causal_blocker": "MOMENTUM_EVIDENCE_UNAVAILABLE", "evidence_used": {}, "evidence_missing": ["MOMENTUM_EVIDENCE_UNAVAILABLE"]}]}
        result = build_legacy_portfolio_resolution_v1(self.positions, self.recovery, triage=triage, evidence=self.evidence)
        row = result["positions"][0]
        self.assertEqual(row["resolution_plan"], "WAIT_FOR_EVIDENCE")
        self.assertNotIn("lane", row)
        self.assertNotIn("horizon", row)

    def test_resolution_reaches_exit_and_unified_advisory_without_execution(self):
        triage = {"positions": [{"symbol": "LEG", "recommendation": "PROTECT_CAPITAL", "confidence": "LOW", "first_causal_blocker": "LOSS_RISK_REQUIRES_MANUAL_REVIEW", "plain_english_reason": "manual review", "evidence_used": {}, "evidence_missing": []}]}
        resolution = build_legacy_portfolio_resolution_v1(self.positions, self.recovery, triage=triage, evidence=self.evidence)
        readiness = build_position_exit_readiness_v1(self.positions, evidence=self.evidence, triage=triage, resolution=resolution)
        advisory = build_unified_position_advisory_v1(self.positions, evidence=self.evidence, triage=triage, exit_readiness=readiness, resolution=resolution)
        row = next(item for item in advisory["positions"] if item["symbol"] == "LEG")
        self.assertEqual(row["resolution_plan"], "REDUCE_REVIEW")
        self.assertEqual(row["execution_authority"], "DISABLED")
        self.assertIn("legacy_position_resolution_v1", row["source_components"])

    def test_resolution_persistence_is_bounded_and_atomic(self):
        result = build_legacy_portfolio_resolution_v1(self.positions, self.recovery, triage={}, evidence=self.evidence)
        with tempfile.TemporaryDirectory() as directory:
            save_legacy_portfolio_resolution_v1(result, directory)
            loaded = load_legacy_portfolio_resolution_v1(directory)
            self.assertEqual(loaded["legacy_position_count"], 1)
            self.assertTrue((__import__("pathlib").Path(directory) / "astra_legacy_capacity_recovery_v1.json").exists())


if __name__ == "__main__":
    unittest.main()
