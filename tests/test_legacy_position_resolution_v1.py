import unittest
from datetime import UTC, datetime, timedelta

from engine.astra_evidence_accumulation_capacity_v1 import (
    build_capacity_snapshot,
    candidate_capacity_decision,
)
from engine.astra_multilane_operational_completion_v1 import build_multilane_operational_status
from engine.paper_autopilot import PaperAutopilotEngine
from engine.astra_unified_position_lifecycle_v1 import (
    build_legacy_migration_approval_v1,
    build_legacy_migration_manifest_v1,
    build_position_management_overlay_v1,
    build_position_resolution_inventory_v1,
    legacy_migration_position_identifier_v1,
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
        self.assertEqual(snapshot["lanes"]["swing"]["positions_used"], 1)
        self.assertEqual(snapshot["lanes"]["swing"]["legacy_excluded_position_count"], 1)
        self.assertEqual(snapshot["lanes"]["swing"]["capacity_decision"], "AVAILABLE")
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
        self.assertEqual(overlay["day_horizon_drift_decision"], "INSUFFICIENT_EVIDENCE_WITH_HARD_DEADLINE")
        self.assertEqual(overlay["day_close_root_cause"], "CONTRACT_INCOMPLETE")
        self.assertTrue(overlay["day_hard_deadline_at"])

    def test_non_day_position_has_no_day_close_root_cause(self):
        overlay = build_position_management_overlay_v1({"symbol": "AAPL", "qty": 1, "market_value": 100})
        self.assertIsNone(overlay["day_close_root_cause"])

    def test_deprecated_day_fail_closed_label_is_migrated_to_bounded_deadline(self):
        overlay = build_position_management_overlay_v1({
            "symbol": "SPY", "lane_id": "DAY", "original_lane": "DAY",
            "entry_timestamp": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        }, prior_review={"day_horizon_drift_decision": "INSUFFICIENT_EVIDENCE_FAIL_CLOSED"})
        self.assertEqual(overlay["day_horizon_drift_decision"], "INSUFFICIENT_EVIDENCE_WITH_HARD_DEADLINE")

    def test_one_time_manifest_is_stable_and_excludes_later_positions(self):
        rows = [
            build_position_management_overlay_v1({"asset_id": "asset-a", "symbol": "AAPL", "qty": 2, "avg_entry_price": 100, "market_value": 200}),
            build_position_management_overlay_v1({"asset_id": "asset-b", "symbol": "MSFT", "qty": 1, "avg_entry_price": 300, "market_value": 300}),
        ]
        manifest = build_legacy_migration_manifest_v1(rows, source_commit="source-commit")
        second = build_legacy_migration_manifest_v1(list(reversed(rows)), source_commit="source-commit")
        self.assertEqual(manifest["position_count"], 2)
        self.assertEqual(manifest["manifest_hash"], second["manifest_hash"])
        self.assertNotIn("NVDA", {row["symbol"] for row in manifest["position_identifiers"]})
        self.assertEqual(
            legacy_migration_position_identifier_v1({"asset_id": "asset-a", "symbol": "AAPL", "qty": 2, "avg_entry_price": 100})["position_id"],
            "asset-a",
        )

    def test_one_time_approval_is_bound_to_manifest_and_non_reusable(self):
        row = build_position_management_overlay_v1({"asset_id": "asset-a", "symbol": "AAPL", "qty": 1, "avg_entry_price": 100, "market_value": 100})
        manifest = build_legacy_migration_manifest_v1([row], source_commit="source-commit")
        approval = build_legacy_migration_approval_v1(manifest, approved_by="human")
        self.assertEqual(approval["migration_manifest_id"], manifest["migration_manifest_id"])
        self.assertFalse(approval["consumed_once"])
        self.assertFalse(approval["new_entries_allowed"])
        self.assertTrue(approval["expires_after_application"])

    def test_migration_field_aliases_release_only_active_slot_usage(self):
        legacy = build_position_management_overlay_v1({
            "asset_id": "asset-old", "symbol": "OLD", "qty": 1, "market_value": 100,
            "legacy_migration_approved": True,
            "legacy_migration_approval_id": "approval-1",
            "legacy_migration_manifest_id": "manifest-1",
            "active_slot_exclusion": True,
        })
        snapshot = build_capacity_snapshot(
            broker_snapshot={"broker_reconciliation_active": True, "broker_positions_fetch_ok": True, "broker_state_age_seconds": 0},
            account_snapshot={"buying_power": 1000}, open_positions=[legacy], global_position_limit=1, env={},
        )
        self.assertEqual(snapshot["broker_total_exposure_position_count"], 1)
        self.assertEqual(snapshot["approved_legacy_slot_exclusion_count"], 1)
        self.assertEqual(snapshot["active_strategy_slot_capacity_remaining"], 1)

    def test_closed_approval_recovers_using_canonical_uppercase_review_keys(self):
        engine = PaperAutopilotEngine.__new__(PaperAutopilotEngine)
        engine._runtime_state = {
            "legacy_migration_manifest_v1": {},
            "legacy_migration_approval_v1": {},
            "legacy_migration_application_v1": {},
        }
        base_rows = [
            build_position_management_overlay_v1({
                "asset_id": f"asset-{index}", "symbol": f"S{index:02d}",
                "qty": 1, "avg_entry_price": 10, "market_value": 10,
            })
            for index in range(37)
        ]
        refreshed = {row["position_id"].upper(): dict(row) for row in base_rows}
        applied, persisted = engine._apply_approved_legacy_migration_v1(base_rows, refreshed)
        self.assertEqual(len(applied), 37)
        self.assertTrue(all(row["active_slot_exclusion_approved"] for row in applied))
        self.assertEqual(engine._runtime_state["legacy_migration_approval_v1"]["approval_status"], "APPLIED_AND_CLOSED")

        next_cycle = [
            build_position_management_overlay_v1({
                "asset_id": f"asset-{index}", "symbol": f"S{index:02d}",
                "qty": 1, "avg_entry_price": 10, "market_value": 10,
            }, prior_review=persisted[f"ASSET-{index}".upper()])
            for index in range(37)
        ]
        recovered, _ = engine._apply_approved_legacy_migration_v1(next_cycle, persisted)
        self.assertTrue(all(row["active_slot_exclusion_approved"] for row in recovered))
        self.assertEqual(
            engine._runtime_state["legacy_migration_application_v1"]["recovery_state"],
            "EXISTING_MANIFEST_OVERLAY_RESTORED",
        )

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
