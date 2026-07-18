import unittest
from datetime import UTC, datetime, timedelta

from engine.astra_evidence_accumulation_capacity_v1 import (
    build_capacity_snapshot,
    candidate_capacity_decision,
)
from engine.astra_multilane_operational_completion_v1 import build_multilane_operational_status
from engine.astra_unified_position_lifecycle_v1 import (
    build_position_management_overlay_v1,
    build_position_resolution_inventory_v1,
)


class LegacyPositionResolutionTests(unittest.TestCase):
    def test_broker_only_position_is_proposed_legacy_without_slot_release(self):
        overlay = build_position_management_overlay_v1({"symbol": "AAPL", "qty": 2, "market_value": 100})
        self.assertEqual(overlay["classification"], "LEGACY_UNLINKED_POSITION")
        self.assertEqual(overlay["management_cohort"], "LEGACY_POSITION_RESOLUTION")
        self.assertTrue(overlay["full_risk_included"])
        self.assertFalse(overlay["active_slot_exclusion_approved"])
        self.assertTrue(overlay["no_new_legacy_entries"])

    def test_slot_exclusion_requires_explicit_governance_approval(self):
        base = {"symbol": "AAPL", "qty": 2, "market_value": 100}
        unapproved = build_position_management_overlay_v1(base)
        approved = build_position_management_overlay_v1({
            **base,
            "legacy_resolution_approved": True,
            "legacy_resolution_approval_id": "gov-approval-1",
            "legacy_slot_exclusion_approved": True,
        })
        self.assertFalse(unapproved["active_slot_exclusion_approved"])
        self.assertTrue(approved["active_slot_exclusion_approved"])

    def test_approved_legacy_slot_exclusion_keeps_full_broker_risk(self):
        legacy = build_position_management_overlay_v1({
            "symbol": "OLD", "qty": 1, "market_value": 100,
            "legacy_resolution_approved": True,
            "legacy_resolution_approval_id": "gov-approval-1",
            "legacy_slot_exclusion_approved": True,
        })
        current = {"symbol": "NEW", "lane_id": "SWING", "market_value": 100}
        snapshot = build_capacity_snapshot(
            broker_snapshot={"broker_reconciliation_active": True, "broker_positions_fetch_ok": True, "broker_state_age_seconds": 0},
            account_snapshot={"buying_power": 1000},
            open_positions=[{**legacy, "market_value": 100}, current],
            global_position_limit=2,
            env={},
        )
        self.assertEqual(snapshot["broker_total_exposure_position_count"], 2)
        self.assertEqual(snapshot["approved_legacy_slot_exclusion_count"], 1)
        self.assertEqual(snapshot["active_strategy_slot_capacity_remaining"], 1)
        self.assertTrue(snapshot["total_account_risk_capacity"]["approved_legacy_slot_exclusions_remain_risk_included"])
        decision = candidate_capacity_decision(snapshot, lane_id="SWING", symbol="NEXT")
        self.assertTrue(decision["allowed"])

    def test_overdue_day_position_is_not_silently_reclassified_as_swing(self):
        overlay = build_position_management_overlay_v1({
            "symbol": "SPY", "lane_id": "DAY", "original_lane": "DAY",
            "entry_timestamp": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        })
        self.assertEqual(overlay["classification"], "DAY_HORIZON_DRIFT_POSITION")
        self.assertEqual(overlay["original_lane"], "DAY")
        self.assertEqual(overlay["hold_exception_state"], "THESIS_REVALIDATION_REQUIRED")

    def test_inventory_has_one_existing_owner_and_no_automatic_migration(self):
        inventory = build_position_resolution_inventory_v1([
            {"symbol": "AAPL", "qty": 1, "market_value": 100},
            {"symbol": "MSFT", "qty": 1, "market_value": 100, "candidate_id": "c1", "contract_id": "contract-1"},
        ])
        self.assertEqual(inventory["owner"], "engine.astra_unified_position_lifecycle_v1")
        self.assertFalse(inventory["automatic_migration_enabled"])
        self.assertFalse(inventory["automatic_exit_authorized"])
        self.assertEqual(inventory["positions_processed"], 2)

    def test_multilane_treats_unapproved_legacy_as_waiting_not_silent_capacity_release(self):
        legacy = build_position_management_overlay_v1({"symbol": "AAPL", "qty": 1, "market_value": 100})
        payload = build_multilane_operational_status(
            candidates=[], open_positions=[legacy], broker_truth_records=[],
            source_metadata={"candidate_freshness_status": "CURRENT"},
            capacity_snapshot={"capacity_authority_state": "CURRENT", "approved_legacy_slot_exclusion_count": 0},
        )
        resolution = payload["legacy_position_resolution"]
        self.assertEqual(resolution["state"], "LEGACY_MIGRATION_AWAITING_GOVERNANCE")
        self.assertEqual(resolution["active_slot_exclusion_count"], 0)
        self.assertTrue(resolution["full_risk_inclusion_confirmed"])


if __name__ == "__main__":
    unittest.main()
