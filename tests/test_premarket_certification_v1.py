from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_premarket_certification_v1 import (
    build_lane_certification,
    build_pretrade_decision_contract,
    deterministic_failure_injection_summary,
)
from engine.paper_autopilot import normalize_operational_candidate


def qualifying_candidate(**overrides):
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    candidate = {
        "candidate_id": "cand-test", "recommendation_id": "rec-test", "symbol": "TEST",
        "lane_id": "SWING", "strategy_archetype": "momentum_breakout", "trade_style": "swing_trade",
        "score": 82.0, "ranking_factors": ["momentum"], "thesis": "Momentum remains supported.",
        "thesis_supporting_conditions": ["trend"], "thesis_invalidation_conditions": ["trend_break"],
        "intended_horizon": "swing_trade", "expected_hold_window": "1d-5d",
        "expected_return_range": {"low": 1.0, "high": 3.0}, "expected_downside_range": {"low": -2.0, "high": -1.0},
        "expected_drawdown": -2.0, "expected_return_per_day_range": {"low": 0.2, "high": 0.6},
        "entry_conditions": ["session_confirmed"], "hold_conditions": ["thesis_intact"],
        "profit_protection_conditions": ["giveback"], "exit_review_conditions": ["horizon_expired"],
        "controlled_loss_conditions": ["thesis_broken"], "replacement_review_conditions": ["better_eligible_candidate"],
        "monitoring_priorities": ["thesis_and_horizon"],
        "confidence": 82.0, "evidence_classes": ["REPLAY_SUPPORTED"],
        "certification_snapshot_id": "premarket-test", "expires_at": future,
    }
    candidate.update(overrides)
    return candidate


class PreMarketCertificationContractTests(unittest.TestCase):
    def test_complete_contract_is_order_ready_eligible(self):
        contract = build_pretrade_decision_contract(qualifying_candidate())
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertTrue(contract["order_ready_allowed"])

    def test_existing_ranking_evidence_is_normalized_into_a_complete_forward_plan(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        normalized = normalize_operational_candidate({
            "symbol": "PLAN", "asset_class": "equity", "action": "buy", "confidence": 82.0,
            "astra_composite_score": 73.0, "paper_entry_horizon_style": "day_trade",
            "summary": "PLAN is ranked from the existing candidate snapshot.",
            "ranked_reason": "Existing probability-adjusted ranking evidence.",
            "expected_return_low_pct": 2.0, "expected_return_high_pct": 6.0,
            "expected_return_pct": 4.0, "price": 100.0, "stop_loss": 96.0,
            "expected_target_low": 102.0, "expected_target_high": 106.0,
            "drawdown_risk_score": 25.0, "recommended_entry_mode": "wait_for_confirmation",
            "sell_reason": "no_confirmed_exit_signal", "candidate_generated_at": future,
            "expires_at": future, "certification_snapshot_id": "premarket-test",
        })
        contract = build_pretrade_decision_contract(normalized)
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertTrue(contract["candidate_id"])
        self.assertTrue(contract["expected_return_range"])
        self.assertTrue(contract["hold_conditions"])
        self.assertEqual(contract["evidence_classes"], ["PROVISIONAL"])

    def test_missing_thesis_fails_closed(self):
        contract = build_pretrade_decision_contract(qualifying_candidate(thesis=""))
        self.assertEqual(contract["contract_status"], "INVALID")
        self.assertIn("thesis", contract["missing_required_fields"])
        self.assertFalse(contract["order_ready_allowed"])

    def test_missing_horizon_fails_closed(self):
        contract = build_pretrade_decision_contract(qualifying_candidate(intended_horizon="", paper_entry_horizon_style=""))
        self.assertIn("intended_horizon", contract["missing_required_fields"])

    def test_expired_contract_fails_closed(self):
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        contract = build_pretrade_decision_contract(qualifying_candidate(expires_at=expired))
        self.assertIn("expired_contract", contract["conflicting_fields"])

    def test_empty_lane_reports_ready_no_trade_without_fixture_truth(self):
        result = build_lane_certification(
            "DAY", activation={"exact_blockers": ["LANE_NOT_ENABLED"]}, dry_run={}, contracts=[],
            production_commit="test", snapshot_id="snapshot",
        )
        self.assertEqual(result["status"], "READY_NO_TRADE")
        self.assertEqual(result["exact_blocker"], "NO_CURRENT_ELIGIBLE_DAY_CANDIDATE")
        self.assertEqual(result["fixture_truths_created"], 0)
        self.assertEqual(result["residual_fixture_orders"], 0)

    def test_lane_certification_attributes_missing_contract_evidence(self):
        contract = build_pretrade_decision_contract({"symbol": "NVDA", "lane": "DAY"})
        result = build_lane_certification(
            "DAY", activation={}, dry_run={"per_candidate_decision_trace": []}, contracts=[contract],
            production_commit="test", snapshot_id="snapshot",
        )
        self.assertEqual(result["status"], "CONTRACT_INCOMPLETE")
        self.assertGreater(result["missing_contract_field_counts"].get("thesis", 0), 0)
        self.assertEqual(result["contract_evidence_samples"][0]["symbol"], "NVDA")

    def test_failure_injection_coverage_is_complete_and_non_mutating(self):
        coverage = deterministic_failure_injection_summary()
        self.assertEqual(coverage["total_cases"], 32)
        self.assertTrue(all(row["broker_actions_used"] == 0 for row in coverage["cases"]))


if __name__ == "__main__":
    unittest.main()
