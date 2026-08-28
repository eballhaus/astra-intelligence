"""Focused advisory-only contracts for lane-specific exit readiness."""
from __future__ import annotations

import unittest

from engine.astra_unified_position_advisory_v1 import build_position_exit_readiness_v1


def _build(
    *, lane="DAY", momentum="STABLE", recommendation="HOLD", profit="HOLD",
    opportunity="NO_ELIGIBLE_REPLACEMENT", replacement="NO_ELIGIBLE_REPLACEMENT", position_id="life-1",
    previous=None,
):
    return build_position_exit_readiness_v1(
        {"AAA": {"symbol": "AAA"}},
        evidence={"positions": [{
            "symbol": "AAA", "canonical_lane_status": "RESOLVED", "first_causal_blocker": "EVIDENCE_CURRENT",
            "momentum_status": momentum, "opportunity_cost_status": opportunity,
            "replacement_candidate_status": replacement,
        }]},
        triage={"positions": [{
            "symbol": "AAA", "recommendation": recommendation, "first_causal_blocker": "EVIDENCE_CURRENT", "lane_id": lane,
        }]},
        profit_protection={"decisions": {position_id: {
            "position_id": position_id, "symbol": "AAA", "profit_state": profit,
        }}},
        recovery={"positions": [{
            "symbol": "AAA", "lane": lane, "canonical_position_id": position_id, "canonical_identity_status": "RESOLVED",
        }]},
        previous_exit_readiness=previous,
        include_lane_exit_funnel=True,
    )


class LaneExitReadinessFunnelTests(unittest.TestCase):
    def test_missing_optional_evidence_is_neutral_and_cannot_authorize_execution(self):
        payload = _build(momentum="MISSING")
        row = payload["positions"][0]
        self.assertEqual(row["lane_exit_readiness_state"], "HOLD")
        self.assertEqual(row["execution_authority"], "DISABLED")
        self.assertTrue(row["exit_advisory_only"])
        self.assertEqual(payload["lane_exit_readiness_funnel_v1"]["execution_authority"], "DISABLED")

    def test_one_weak_cycle_is_watch_but_persistent_deterioration_is_recorded(self):
        first = _build(momentum="DETERIORATING")
        self.assertEqual(first["positions"][0]["lane_exit_readiness_state"], "WATCH")
        second = _build(momentum="DETERIORATING", previous=first)
        row = second["positions"][0]
        self.assertEqual(row["exit_persistence_state"], "PERSISTENT_DETERIORATION")
        self.assertEqual(row["lane_exit_readiness_state"], "WATCH")

    def test_existing_thesis_break_remains_immediate_and_has_no_new_authority(self):
        payload = _build(profit="THESIS_BROKEN")
        row = payload["positions"][0]
        self.assertEqual(row["lane_exit_readiness_state"], "THESIS_BROKEN")
        self.assertEqual(row["execution_authority"], "DISABLED")

    def test_profit_giveback_plus_persistent_decay_escalates_advisory_only(self):
        first = _build(momentum="DETERIORATING", profit="PROTECT_PROFIT")
        second = _build(momentum="DETERIORATING", profit="PROTECT_PROFIT", previous=first)
        row = second["positions"][0]
        self.assertEqual(row["lane_exit_readiness_state"], "EXIT_REVIEW")
        self.assertEqual(row["recommendation"], "HOLD")
        self.assertEqual(row["exit_execution_authority"], "DISABLED")

    def test_replacement_pressure_alone_cannot_force_exit(self):
        payload = _build(opportunity="HIGH_OPPORTUNITY_COST", replacement="REPLACEMENT_AVAILABLE")
        row = payload["positions"][0]
        self.assertEqual(row["lane_exit_readiness_state"], "HOLD")
        self.assertEqual(row["opportunity_cost_pressure"], "OBSERVED")

    def test_lane_windows_are_isolated_and_crypto_remains_unchanged(self):
        scalp = _build(lane="SCALP", momentum="DETERIORATING", position_id="scalp-life")
        swing = _build(lane="SWING", momentum="DETERIORATING", position_id="swing-life")
        self.assertEqual(scalp["lane_exit_readiness_funnel_v1"]["history_windows"]["SCALP"], 3)
        self.assertEqual(swing["lane_exit_readiness_funnel_v1"]["history_windows"]["SWING"], 8)
        crypto = _build(lane="CRYPTO", position_id="crypto-life")
        self.assertNotIn("lane_exit_readiness_state", crypto["positions"][0])

    def test_history_is_bounded_and_cohort_is_write_once(self):
        payload = _build(lane="SCALP", momentum="DETERIORATING")
        activated_at = payload["lane_exit_readiness_funnel_v1"]["prospective_cohort"]["activated_at"]
        for _ in range(5):
            payload = _build(lane="SCALP", momentum="DETERIORATING", previous=payload)
        funnel = payload["lane_exit_readiness_funnel_v1"]
        self.assertEqual(funnel["prospective_cohort"]["activated_at"], activated_at)
        self.assertLessEqual(len(funnel["position_history"]["life-1"]["history"]), 3)


if __name__ == "__main__":
    unittest.main()
