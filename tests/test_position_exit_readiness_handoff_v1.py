"""Regression coverage for explicit same-session horizon handoffs."""
from __future__ import annotations

import unittest

from engine.astra_position_lane_horizon_recovery_v1 import build_position_lane_horizon_recovery_v1
from engine.astra_sentinel_causal_handoff_integrity_v1 import (
    causal_facts_from_position_horizon_handoffs_v1,
    classify_causal_handoff_facts_v1,
)
from engine.astra_unified_position_advisory_v1 import (
    build_position_exit_readiness_v1,
    build_unified_position_advisory_v1,
)


STAMP = "2026-09-16T15:31:41Z"


class PositionExitReadinessHandoffTests(unittest.TestCase):
    def test_explicit_day_window_reaches_readiness_without_causal_loss(self):
        broker = {"ORCL": {"symbol": "ORCL", "asset_class": "us_equity", "entry_fill_id": "fill-orcl", "entry_timestamp": STAMP}}
        evidence = [{
            "symbol": "ORCL", "asset_type": "stock", "position_id": "ORCL:2026-09-16T15:31:41",
            "entry_fill_id": "fill-orcl", "entry_timestamp": STAMP, "entry_filled_at": STAMP,
            "lane_id": "DAY", "canonical_horizon": "day_trade", "current_reconciled": True,
            "position_owner": "DAY", "exit_policy_owner": "DAY",
            "entry_metadata_json": {
                "lane_id": "DAY", "intended_horizon": "day_trade", "expected_max_hold": "2h-EOD",
                "same_session_exit_required": True, "overnight_allowed": False,
            },
        }]
        recovery = build_position_lane_horizon_recovery_v1(broker, evidence_rows=evidence)
        readiness = build_position_exit_readiness_v1(
            broker, evidence={"positions": [{"symbol": "ORCL"}]},
            triage={"positions": [{"symbol": "ORCL", "recommendation": "HOLD"}]},
            recovery=recovery,
        )
        row = readiness["positions"][0]
        self.assertEqual(row["horizon_exit_requirement"]["status"], "CANONICAL_SAME_SESSION_EXIT_REQUIRED")
        self.assertEqual(row["horizon_exit_requirement"]["expected_max_hold"], "2h-EOD")
        advisory = build_unified_position_advisory_v1(
            broker, evidence={"positions": [{"symbol": "ORCL"}]},
            triage={"positions": [{"symbol": "ORCL", "recommendation": "HOLD"}]},
            exit_readiness=readiness, recovery=recovery,
        )
        facts = causal_facts_from_position_horizon_handoffs_v1(recovery, readiness, advisory)
        horizon_facts = [fact for fact in facts if fact.get("kind") == "HORIZON_CONTRACT_LOSS"]
        self.assertTrue(horizon_facts)
        self.assertTrue(all(fact.get("consumer_value") is True for fact in horizon_facts))
        self.assertEqual(classify_causal_handoff_facts_v1(facts)["signals"], [])


if __name__ == "__main__":
    unittest.main()
