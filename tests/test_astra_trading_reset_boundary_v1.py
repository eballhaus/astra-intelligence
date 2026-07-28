"""Deterministic tests for Astra trading reset boundary and legacy separation."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from engine.astra_trading_reset_boundary_v1 import (
    DUST,
    LEGACY_PRE_RESET_POSITION,
    LEGACY_RETIREMENT,
    MIXED_BOUNDARY_LIFECYCLE,
    POST_RESET_CURRENT,
    PRE_RESET_LEGACY,
    RESET_BOUNDARY_REVIEW_REQUIRED,
    build_lane_strict_truth_counts_v1,
    build_legacy_shadow_analysis_v1,
    build_post_reset_strict_truth_v1,
    classify_learning_eligibility_v1,
    classify_lifecycle_reset_scope_v1,
    classify_position_reset_scope_v1,
    classify_record_reset_scope_v1,
    compute_reset_aware_metrics_v1,
    detect_reset_scope_leakage_v1,
    determine_reset_boundary_v1,
    is_strict_truth_eligible_v1,
    load_reset_boundary_v1,
    save_reset_boundary_v1,
)
from engine.astra_legacy_retirement_workflow_v1 import (
    LEGACY_DUST_RECONCILIATION,
    LEGACY_EXIT_BLOCKED,
    LEGACY_EXIT_READY_FOR_HUMAN_APPROVAL,
    LEGACY_EXIT_REVIEW,
    build_legacy_retirement_review_queue_v1,
    classify_retirement_state_v1,
    load_legacy_retirement_queue_v1,
    save_legacy_retirement_queue_v1,
)
from engine.astra_reset_boundary_dashboard_payload_v1 import (
    build_dashboard_payload_v1,
)
from engine.astra_reset_boundary_migration_v1 import (
    migrate_records_to_reset_scope_v1,
)
from engine.astra_reset_boundary_sentinel_governance_v1 import (
    build_governance_reset_boundary_report_v1,
    build_sentinel_reset_boundary_report_v1,
)
import engine.astra_trading_reset_boundary_v1 as astra_trading_reset_boundary_v1
import engine.astra_legacy_retirement_workflow_v1 as astra_legacy_retirement_workflow_v1
import engine.astra_reset_boundary_dashboard_payload_v1 as astra_reset_boundary_dashboard_payload_v1
import engine.astra_reset_boundary_migration_v1 as astra_reset_boundary_migration_v1
import engine.astra_reset_boundary_sentinel_governance_v1 as astra_reset_boundary_sentinel_governance_v1


PRE_RESET_TS = "2026-07-27T12:00:00Z"
POST_RESET_TS = "2026-07-28T18:00:00Z"
LATER_POST_RESET_TS = "2026-07-29T10:00:00Z"


def _lifecycle(
    *,
    entry: str = PRE_RESET_TS,
    exit_: str = POST_RESET_TS,
    lane: str = "DAY",
    horizon: str = "day_trade",
    candidate_id: str = "c1",
    lifecycle_id: str = "l1",
    symbol: str = "AAPL",
    entry_fill_id: str = "ef1",
    exit_fill_id: str = "xf1",
    entry_order_id: str = "eo1",
    exit_order_id: str = "xo1",
    realized_return_pct: float = 1.5,
    realized_pnl: float = 15.0,
    hold_minutes: float = 30.0,
    current_ownership: str = "MANAGED",
    human_approval: bool = True,
    broker_zero: bool = True,
    closed: bool = True,
    truth_provenance: bool = True,
    trusted_quote: bool = True,
    paper_submitted: bool = True,
    entry_decision_after_reset: bool | None = None,
    exit_decision_after_reset: bool | None = None,
):
    return {
        "lifecycle_id": lifecycle_id,
        "candidate_id": candidate_id,
        "symbol": symbol,
        "lane_id": lane,
        "trade_horizon_style": horizon,
        "entry_timestamp": entry,
        "exit_timestamp": exit_,
        "entry_fill_id": entry_fill_id,
        "exit_fill_id": exit_fill_id,
        "entry_order_id": entry_order_id,
        "exit_order_id": exit_order_id,
        "realized_return_pct": realized_return_pct,
        "realized_pnl": realized_pnl,
        "hold_duration_minutes": hold_minutes,
        "current_astra_ownership": current_ownership,
        "human_approval_satisfied": human_approval,
        "broker_residual_zero_confirmed": broker_zero,
        "lifecycle_closed_once": closed,
        "truth_provenance_complete": truth_provenance,
        "trusted_quote_provenance": trusted_quote,
        "paper_order_submitted_after_reset": paper_submitted,
        "broker_entry_fill_confirmed": bool(entry_fill_id),
        "broker_exit_fill_confirmed": bool(exit_fill_id),
        "entry_decision_after_reset": entry_decision_after_reset if entry_decision_after_reset is not None else (_parse_dt(entry) >= _parse_dt(POST_RESET_TS)),
        "exit_decision_after_reset": exit_decision_after_reset if exit_decision_after_reset is not None else (_parse_dt(exit_) >= _parse_dt(POST_RESET_TS)),
    }


def _position(
    *,
    symbol: str = "AAPL",
    timestamp: str = PRE_RESET_TS,
    qty: float = 10.0,
    lane: str | None = None,
    candidate_id: str | None = None,
    lifecycle_id: str | None = None,
    contract_id: str | None = None,
    status: str = "OPEN",
    unrealized_plpc: float = 0.0,
    thesis: str | None = None,
):
    pos: dict[str, object] = {
        "position_id": f"pos-{symbol}",
        "symbol": symbol,
        "opened_at": timestamp,
        "quantity": qty,
        "status": status,
        "unrealized_plpc": unrealized_plpc,
    }
    if lane is not None:
        pos["lane_id"] = lane
    if candidate_id is not None:
        pos["candidate_id"] = candidate_id
    if lifecycle_id is not None:
        pos["lifecycle_id"] = lifecycle_id
    if contract_id is not None:
        pos["contract_id"] = contract_id
    if thesis is not None:
        pos["original_thesis"] = thesis
    return pos


def _parse_dt(ts: str):
    from datetime import datetime, timezone
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


class ResetBoundaryTests(unittest.TestCase):
    def test_default_boundary_values(self):
        boundary = determine_reset_boundary_v1()
        self.assertEqual(boundary["reset_id"], "ASTRA_CORRECTED_TRADING_RESET_2026_07_28")
        self.assertEqual(boundary["reset_date"], "2026-07-28")
        self.assertEqual(boundary["reset_timestamp_utc"], "2026-07-28T17:20:15Z")
        self.assertEqual(boundary["production_commit"], "ada1c8d201adc1137a2316d5e57ede174d41d253")
        self.assertEqual(boundary["status"], "ACTIVE")

    def test_boundary_override_from_config(self):
        boundary = determine_reset_boundary_v1({"reset_timestamp_utc": "2026-08-01T00:00:00Z"})
        self.assertEqual(boundary["reset_timestamp_utc"], "2026-08-01T00:00:00Z")

    def test_boundary_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            boundary = determine_reset_boundary_v1()
            save_reset_boundary_v1(boundary, tmp)
            loaded = load_reset_boundary_v1(tmp)
            self.assertEqual(loaded["reset_id"], boundary["reset_id"])
            self.assertEqual(loaded["reset_timestamp_utc"], boundary["reset_timestamp_utc"])

    def test_uncertain_same_day_record_fails_closed(self):
        record = {"symbol": "AAPL", "timestamp": "2026-07-28"}
        result = classify_record_reset_scope_v1(record)
        self.assertEqual(result["reset_scope"], RESET_BOUNDARY_REVIEW_REQUIRED)


class PositionClassificationTests(unittest.TestCase):
    def test_position_open_before_reset_is_legacy(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=10.0)
        result = classify_position_reset_scope_v1(pos)
        self.assertEqual(result["reset_scope"], LEGACY_PRE_RESET_POSITION)

    def test_legacy_position_does_not_consume_day_slot(self):
        pos = _position(timestamp=PRE_RESET_TS, lane="DAY", qty=10.0)
        result = classify_position_reset_scope_v1(pos)
        self.assertEqual(result["reset_scope"], LEGACY_PRE_RESET_POSITION)
        self.assertNotEqual(result.get("is_post_reset_candidate"), True)

    def test_legacy_position_does_not_consume_swing_slot(self):
        pos = _position(timestamp=PRE_RESET_TS, lane="SWING", qty=10.0)
        result = classify_position_reset_scope_v1(pos)
        self.assertEqual(result["reset_scope"], LEGACY_PRE_RESET_POSITION)

    def test_legacy_position_does_not_consume_crypto_slot(self):
        pos = _position(timestamp=PRE_RESET_TS, lane="CRYPTO", qty=0.1)
        result = classify_position_reset_scope_v1(pos)
        self.assertEqual(result["reset_scope"], LEGACY_PRE_RESET_POSITION)

    def test_dust_excluded_from_normal_slots(self):
        pos = _position(timestamp=POST_RESET_TS, qty=0.0005)
        result = classify_position_reset_scope_v1(pos)
        self.assertEqual(result["reset_scope"], DUST)
        self.assertFalse(result["is_post_reset_candidate"])

    def test_dust_visible_to_reconciliation(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=0.0005)
        result = classify_position_reset_scope_v1(pos)
        self.assertEqual(result["reset_scope"], DUST)
        self.assertTrue(result["dust_classification"]["counts_toward_reconciliation"])

    def test_post_reset_position_requires_current_ownership(self):
        pos = _position(timestamp=POST_RESET_TS, qty=10.0)
        result = classify_position_reset_scope_v1(pos)
        self.assertEqual(result["reset_scope"], RESET_BOUNDARY_REVIEW_REQUIRED)

    def test_post_reset_position_with_current_ownership_is_current(self):
        pos = _position(
            timestamp=POST_RESET_TS,
            qty=10.0,
            lane="DAY",
            candidate_id="c1",
            contract_id="c1",
            lifecycle_id="l1",
        )
        result = classify_position_reset_scope_v1(pos)
        self.assertEqual(result["reset_scope"], POST_RESET_CURRENT)


class LifecycleClassificationTests(unittest.TestCase):
    def test_completed_trade_before_reset_is_pre_reset_legacy(self):
        lc = _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS)
        result = classify_lifecycle_reset_scope_v1(lc)
        self.assertEqual(result["reset_scope"], PRE_RESET_LEGACY)

    def test_pre_reset_trade_preserved(self):
        lc = _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS)
        result = classify_lifecycle_reset_scope_v1(lc)
        self.assertIn("entry_timestamp_utc", result)
        self.assertIn("exit_timestamp_utc", result)

    def test_position_opened_before_reset_and_sold_after_is_retirement(self):
        lc = _lifecycle(entry=PRE_RESET_TS, exit_=POST_RESET_TS)
        result = classify_lifecycle_reset_scope_v1(lc)
        self.assertEqual(result["reset_scope"], LEGACY_RETIREMENT)

    def test_retirement_not_current_strict_truth(self):
        lc = _lifecycle(entry=PRE_RESET_TS, exit_=POST_RESET_TS)
        result = build_post_reset_strict_truth_v1(lc)
        self.assertIn("error", result)

    def test_post_reset_complete_lifecycle_is_current_strict_truth(self):
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS)
        result = build_post_reset_strict_truth_v1(lc)
        self.assertEqual(result["truth_scope"], POST_RESET_CURRENT)
        self.assertTrue(result["post_reset_day_strict_truth"])

    def test_post_reset_incomplete_lifecycle_is_not_strict_truth(self):
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, exit_fill_id="")
        result = build_post_reset_strict_truth_v1(lc)
        self.assertIn("error", result)

    def test_mixed_boundary_lifecycle_rejected_from_current_truth(self):
        lc = _lifecycle(entry=PRE_RESET_TS, exit_=POST_RESET_TS)
        result = classify_lifecycle_reset_scope_v1(lc)
        self.assertEqual(result["reset_scope"], LEGACY_RETIREMENT)
        eligible = is_strict_truth_eligible_v1(lc)
        self.assertFalse(eligible["eligible"])

    def test_unknown_provenance_fails_closed(self):
        lc = {"lifecycle_id": "l-unknown"}
        result = classify_lifecycle_reset_scope_v1(lc)
        self.assertEqual(result["reset_scope"], RESET_BOUNDARY_REVIEW_REQUIRED)


class StrictTruthEligibilityTests(unittest.TestCase):
    def test_required_fields_checked(self):
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS)
        result = is_strict_truth_eligible_v1(lc)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["blockers"], [])

    def test_missing_exit_fill_blocks_eligibility(self):
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, exit_fill_id="")
        result = is_strict_truth_eligible_v1(lc)
        self.assertFalse(result["eligible"])
        self.assertIn("BROKER_EXIT_FILL_NOT_CONFIRMED", result["blockers"])

    def test_broker_zero_confirmed_required(self):
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, broker_zero=False)
        result = is_strict_truth_eligible_v1(lc)
        self.assertFalse(result["eligible"])
        self.assertIn("BROKER_RESIDUAL_ZERO_NOT_CONFIRMED", result["blockers"])


class LaneStrictTruthCountTests(unittest.TestCase):
    def test_day_truth_increments_only_for_day(self):
        lifecycles = [
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, lane="DAY"),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, lane="SWING"),
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS, lane="DAY"),
        ]
        counts = build_lane_strict_truth_counts_v1(lifecycles)
        self.assertEqual(counts["POST_RESET_DAY_STRICT_TRUTH"], 1)
        self.assertEqual(counts["POST_RESET_SWING_STRICT_TRUTH"], 1)
        self.assertEqual(counts["POST_RESET_CRYPTO_STRICT_TRUTH"], 0)

    def test_swing_truth_increments_only_for_swing(self):
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, lane="SWING", horizon="swing_trade")
        counts = build_lane_strict_truth_counts_v1([lc])
        self.assertEqual(counts["POST_RESET_SWING_STRICT_TRUTH"], 1)
        self.assertEqual(counts["POST_RESET_DAY_STRICT_TRUTH"], 0)

    def test_crypto_truth_increments_only_for_crypto(self):
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, lane="CRYPTO", horizon="swing_trade")
        counts = build_lane_strict_truth_counts_v1([lc])
        self.assertEqual(counts["POST_RESET_CRYPTO_STRICT_TRUTH"], 1)
        self.assertEqual(counts["POST_RESET_DAY_STRICT_TRUTH"], 0)


class MetricsTests(unittest.TestCase):
    def test_current_metrics_insufficient_evidence_at_zero_samples(self):
        result = compute_reset_aware_metrics_v1([])
        self.assertEqual(result["evidence_status"], "insufficient_evidence")
        self.assertIsNone(result["win_rate"])
        self.assertIsNone(result["profit_factor"])
        self.assertEqual(result["eligible_sample_count"], 0)

    def test_current_metrics_count_only_post_reset_eligible_truths(self):
        lifecycles = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS, realized_return_pct=-2.0),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, realized_return_pct=3.0),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, realized_return_pct=2.0),
        ]
        result = compute_reset_aware_metrics_v1(lifecycles, scope="CURRENT_POST_RESET")
        self.assertEqual(result["eligible_sample_count"], 2)
        self.assertEqual(result["excluded_sample_count"], 1)
        self.assertEqual(result["completed_trades"], 2)

    def test_pre_reset_trade_excluded_from_current_win_rate(self):
        lifecycles = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS, realized_return_pct=50.0),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, realized_return_pct=-1.0),
        ]
        result = compute_reset_aware_metrics_v1(lifecycles, scope="CURRENT_POST_RESET")
        self.assertEqual(result["eligible_sample_count"], 1)
        self.assertEqual(result["win_rate"], 0.0)

    def test_pre_reset_trade_excluded_from_current_profit_factor(self):
        lifecycles = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS, realized_return_pct=100.0),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, realized_return_pct=-2.0),
        ]
        result = compute_reset_aware_metrics_v1(lifecycles, scope="CURRENT_POST_RESET")
        self.assertIsNotNone(result["profit_factor"])
        self.assertNotEqual(result["profit_factor"], 100.0)

    def test_legacy_metrics_separately_available(self):
        lifecycles = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS, realized_return_pct=5.0),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, realized_return_pct=3.0),
        ]
        result = compute_reset_aware_metrics_v1(lifecycles, scope="LEGACY_PRE_RESET")
        self.assertEqual(result["eligible_sample_count"], 1)
        self.assertEqual(result["completed_trades"], 1)

    def test_lifetime_metrics_available(self):
        lifecycles = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS),
        ]
        result = compute_reset_aware_metrics_v1(lifecycles, scope="LIFETIME_ALL_BROKER_FACTS")
        self.assertEqual(result["eligible_sample_count"], 2)


class LearningEligibilityTests(unittest.TestCase):
    def test_pre_reset_trade_excluded_from_current_learning(self):
        lc = _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS)
        result = classify_learning_eligibility_v1(lc)
        self.assertFalse(result["learning_eligible"])
        self.assertIn("scope_is_", result["learning_exclusion_reason"])

    def test_learning_consumes_only_current_eligible_truths(self):
        current = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS)
        legacy = _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS)
        self.assertTrue(classify_learning_eligibility_v1(current)["learning_eligible"])
        self.assertFalse(classify_learning_eligibility_v1(legacy)["learning_eligible"])

    def test_broker_zero_closure_mandatory_for_learning(self):
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS, broker_zero=False)
        result = classify_learning_eligibility_v1(lc)
        self.assertFalse(result["learning_eligible"])
        self.assertFalse(result["broker_zero_confirmed"])


class ShadowLegacyAnalysisTests(unittest.TestCase):
    def test_legacy_evidence_cannot_authorize_trade(self):
        legacy = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS, realized_return_pct=-10.0, hold_minutes=3000),
        ]
        result = build_legacy_shadow_analysis_v1(legacy)
        self.assertTrue(result["cannot_authorize_trade"])
        self.assertEqual(result["execution_authority"], "DISABLED")
        self.assertTrue(result["advisory_only"])

    def test_legacy_evidence_cannot_promote_policy(self):
        legacy = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS),
        ]
        result = build_legacy_shadow_analysis_v1(legacy)
        self.assertTrue(result["cannot_promote_policy"])
        self.assertTrue(result["cannot_alter_loss_thresholds"])

    def test_pre_reset_trade_available_for_shadow_analysis(self):
        legacy = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS, realized_return_pct=-10.0, hold_minutes=3000),
        ]
        result = build_legacy_shadow_analysis_v1(legacy)
        self.assertGreaterEqual(result["sample_size"], 1)
        self.assertIn("LEGACY_OVERHOLD_PATTERN", result["patterns"])


class LeakageDetectionTests(unittest.TestCase):
    def test_sentinel_detects_metric_leakage(self):
        payload = {
            "lifecycles": [_lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS)],
            "metrics": compute_reset_aware_metrics_v1([], scope="CURRENT_POST_RESET"),
            "learning_reports": [],
        }
        result = detect_reset_scope_leakage_v1(payload)
        self.assertTrue(result["leakage_detected"])
        self.assertTrue(any("legacy" in reason for reason in result["leakage_reasons"]))

    def test_governance_detects_learning_scope_leakage(self):
        classifications = []
        metrics = compute_reset_aware_metrics_v1([], scope="CURRENT_POST_RESET")
        learning_reports = [
            {
                "lifecycle_id": "l-legacy",
                "learning_eligible": True,
                "truth_scope": PRE_RESET_LEGACY,
            }
        ]
        result = build_governance_reset_boundary_report_v1(
            classifications, metrics, learning_reports
        )
        self.assertEqual(result["integrity"]["learning_scope_integrity"], "FAIL")
        self.assertEqual(result["overall_integrity"], "FAIL")


class RetirementWorkflowTests(unittest.TestCase):
    def test_legacy_position_added_to_review_queue(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=10.0)
        queue = build_legacy_retirement_review_queue_v1([pos], [pos])
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["retirement_state"], LEGACY_EXIT_REVIEW)

    def test_dust_added_to_reconciliation(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=0.0005)
        queue = build_legacy_retirement_review_queue_v1([pos], [pos])
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["retirement_state"], LEGACY_DUST_RECONCILIATION)

    def test_severe_loss_visible_for_human_review(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=10.0, unrealized_plpc=-0.20)
        queue = build_legacy_retirement_review_queue_v1([pos], [pos])
        self.assertTrue(queue[0]["human_approval_required"])
        self.assertLess(queue[0]["current_unrealized_pct_pl"], 0)

    def test_no_retirement_order_submitted(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=10.0)
        state = classify_retirement_state_v1(pos)
        self.assertIn(state, {
            LEGACY_EXIT_REVIEW,
            LEGACY_EXIT_READY_FOR_HUMAN_APPROVAL,
            LEGACY_EXIT_BLOCKED,
            LEGACY_DUST_RECONCILIATION,
        })

    def test_sell_approval_protections_untouched(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=10.0)
        queue = build_legacy_retirement_review_queue_v1([pos], [pos])
        self.assertTrue(queue[0]["human_approval_required"])

    def test_broker_zero_confirmation_required_for_retirement_completion(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=10.0)
        queue = build_legacy_retirement_review_queue_v1([pos], [pos])
        self.assertFalse(queue[0]["broker_zero_confirmation_required"])
        complete_pos = {**pos, "status": "CLOSED", "broker_residual_zero_confirmed": True}
        state = classify_retirement_state_v1(complete_pos)
        self.assertEqual(state, "LEGACY_RETIREMENT_COMPLETE")

    def test_retirement_queue_persists_and_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            pos = _position(timestamp=PRE_RESET_TS, qty=10.0)
            queue = build_legacy_retirement_review_queue_v1([pos], [pos])
            save_legacy_retirement_queue_v1(queue, tmp)
            loaded = load_legacy_retirement_queue_v1(tmp)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["symbol"], "AAPL")


class MigrationTests(unittest.TestCase):
    def test_migration_counts_positions_and_lifecycles(self):
        records = [
            _position(timestamp=PRE_RESET_TS, qty=10.0),
            _position(timestamp=POST_RESET_TS, qty=10.0, lane="DAY", candidate_id="c1", contract_id="c1", lifecycle_id="l1"),
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS),
        ]
        result = migrate_records_to_reset_scope_v1(records)
        totals = result["totals"]
        self.assertEqual(totals["positions_scanned"], 2)
        self.assertEqual(totals["legacy_positions"], 1)
        self.assertEqual(totals["current_positions"], 1)
        self.assertEqual(totals["completed_lifecycles_scanned"], 2)
        self.assertEqual(totals["pre_reset_completed_lifecycles"], 1)
        self.assertEqual(totals["post_reset_eligible_lifecycles"], 1)

    def test_migration_excludes_legacy_from_current_learning(self):
        records = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS),
        ]
        result = migrate_records_to_reset_scope_v1(records)
        self.assertEqual(result["totals"]["records_excluded_from_current_learning"], 1)

    def test_migration_idempotent(self):
        records = [
            _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS),
            _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS),
        ]
        r1 = migrate_records_to_reset_scope_v1(records)
        r2 = migrate_records_to_reset_scope_v1(records)
        self.assertEqual(r1["totals"], r2["totals"])

    def test_migration_does_not_mutate_broker_facts(self):
        pos = _position(timestamp=PRE_RESET_TS, qty=10.0)
        original_qty = pos["quantity"]
        migrate_records_to_reset_scope_v1([pos])
        self.assertEqual(pos["quantity"], original_qty)

    def test_duplicate_classification_does_not_create_duplicates(self):
        records = [
            _position(timestamp=PRE_RESET_TS, qty=10.0),
            _position(timestamp=PRE_RESET_TS, qty=10.0),
        ]
        result = migrate_records_to_reset_scope_v1(records)
        self.assertEqual(len(result["classifications"]), 2)
        self.assertEqual(result["totals"]["legacy_positions"], 2)


class DashboardPayloadTests(unittest.TestCase):
    def test_dashboard_states_metric_scope_and_reset_id(self):
        pos = _position(timestamp=POST_RESET_TS, qty=10.0, lane="DAY", candidate_id="c1", contract_id="c1", lifecycle_id="l1")
        lc = _lifecycle(entry=POST_RESET_TS, exit_=LATER_POST_RESET_TS)
        current_metrics = compute_reset_aware_metrics_v1([lc], scope="CURRENT_POST_RESET")
        shadow = build_legacy_shadow_analysis_v1([])
        sentinel = build_sentinel_reset_boundary_report_v1([], current_metrics, [])
        governance = build_governance_reset_boundary_report_v1([], current_metrics, [])
        payload = build_dashboard_payload_v1(
            [pos], [lc], current_metrics, shadow, sentinel, governance
        )
        self.assertEqual(payload["current_astra_performance_since_reset"]["metric_scope"], "CURRENT_POST_RESET")
        self.assertEqual(payload["current_astra_performance_since_reset"]["reset_id"], payload["reset_id"])
        self.assertIn("eligible_sample_count", payload["current_astra_performance_since_reset"])
        self.assertIn("exclusion_reasons", payload["legacy_portfolio"])

    def test_dashboard_legacy_section_isolated(self):
        legacy_pos = _position(timestamp=PRE_RESET_TS, qty=10.0)
        legacy_lc = _lifecycle(entry=PRE_RESET_TS, exit_=PRE_RESET_TS)
        current_metrics = compute_reset_aware_metrics_v1([], scope="CURRENT_POST_RESET")
        shadow = build_legacy_shadow_analysis_v1([legacy_lc])
        sentinel = build_sentinel_reset_boundary_report_v1([], current_metrics, [])
        governance = build_governance_reset_boundary_report_v1([], current_metrics, [])
        payload = build_dashboard_payload_v1(
            [legacy_pos], [legacy_lc], current_metrics, shadow, sentinel, governance
        )
        self.assertEqual(payload["legacy_portfolio"]["legacy_positions_count"], 1)
        self.assertTrue(payload["legacy_shadow_lessons"]["shadow_analysis"]["cannot_authorize_trade"])


class VersioningTests(unittest.TestCase):
    def test_modules_expose_schema_version(self):
        from engine import astra_legacy_retirement_workflow_v1
        from engine import astra_reset_boundary_dashboard_payload_v1
        from engine import astra_reset_boundary_migration_v1
        from engine import astra_reset_boundary_sentinel_governance_v1

        self.assertIsNotNone(astra_trading_reset_boundary_v1.SCHEMA_VERSION)
        self.assertIsNotNone(astra_legacy_retirement_workflow_v1.SCHEMA_VERSION)
        self.assertIsNotNone(astra_reset_boundary_sentinel_governance_v1.SCHEMA_VERSION)
        self.assertIsNotNone(astra_reset_boundary_migration_v1.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
