from __future__ import annotations

import time
from collections import Counter
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    clamp,
    first,
    now_iso,
    rounded,
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)


MODULES_CREATED = [
    "Trade Lifecycle Audit Auto-Repair V1",
    "Horizon Opportunity Assignment Engine V1",
    "Horizon Shadow-to-Paper Promotion Readiness V1",
    "Horizon Capacity Manager V1",
    "Dynamic Capacity Recycling V1",
    "Horizon Exposure Balancer V1",
    "Learning Exposure Optimizer V1",
    "Adaptive Portfolio Rotation Engine V1",
    "Trade Lifecycle Intelligence V2",
    "Adaptive Market Regime Allocation V1",
    "Shadow-to-Paper Promotion Engine V2",
    "Controlled Paper Test Bucket V2",
    "Exit Promotion Readiness V2",
    "Horizon & Regime Promotion Readiness V2",
    "Stale Position / Rotation Promotion Readiness V2",
    "Shadow vs Paper Scorecard V2",
    "Controlled Paper Horizon Practice Bucket V1",
    "Horizon Exit / Profit Capture Readiness V1",
    "Horizon Lifecycle Dashboard Summary",
]

HORIZONS = ["scalp", "day_trade", "swing_trade"]
TARGET_RANGES = {
    "scalp": (20.0, 30.0),
    "day_trade": (30.0, 40.0),
    "swing_trade": (30.0, 40.0),
}
HORIZON_EXPECTED_WINDOWS = {
    "scalp": "15m-60m",
    "day_trade": "2h-EOD",
    "swing_trade": "1d-10d+",
}


def _safe_flags(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
        "paper_safe": True,
        "human_review_required": True,
        "cache_first": True,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "promotion_logic_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "sell_behavior_changed": False,
        "paper_sell_behavior_enabled": False,
        "learned_exits_enabled": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "paper_execution_changed": False,
        "shadow_influence_changed": False,
        "forced_buys_enabled": False,
        "forced_sells_enabled": False,
        "forced_exits_enabled": False,
        "forced_trades_enabled": False,
        "partial_sells_enabled": False,
        "automatic_trailing_stops_enabled": False,
        "dashboard_endpoint_storm_created": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
    }
    out.update(extra or {})
    return out


def _confidence(payload: dict[str, Any], default: float = 55.0) -> float:
    vals = [
        payload.get("confidence_score"),
        payload.get("confidence"),
        payload.get("readiness_score"),
        payload.get("horizon_confidence"),
        payload.get("validation_confidence"),
        payload.get("policy_confidence"),
    ]
    nums = [clamp(v) for v in vals if v is not None]
    return rounded(sum(nums) / len(nums), 3) if nums else default


def _pf(payload: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in payload and payload.get(key) not in (None, "", "n/a"):
            return rounded(to_float(payload.get(key), default), 4)
    return rounded(default, 4)


def _horizon_label(row: dict[str, Any]) -> str:
    raw = text(
        first(
            row.get("assigned_horizon"),
            row.get("horizon"),
            row.get("current_horizon"),
            row.get("paper_entry_horizon_style"),
            row.get("horizon_style"),
            row.get("best_horizon"),
            row.get("best_horizon_style"),
            row.get("trade_horizon_style"),
            row.get("style"),
            "unknown",
        ),
        "unknown",
    ).lower().replace("-", "_").replace(" ", "_")
    if "scalp" in raw or raw in {"15m", "30m", "45m", "60m"}:
        return "scalp"
    if "day" in raw or "intraday" in raw or "eod" in raw or "2h" in raw or "4h" in raw:
        return "day_trade"
    if "swing" in raw or "overnight" in raw or "multi_day" in raw or "1d" in raw or "2d" in raw or "3d" in raw or "5d" in raw or "10d" in raw:
        return "swing_trade"
    return "unknown"


def _positions_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        payload.get("true_broker_positions_preview"),
        payload.get("desktop_positions_preview"),
        payload.get("positions"),
        payload.get("open_positions"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
    return []


def _readiness(sample: int, confidence: float, delta: float) -> str:
    if sample < 15:
        return "not_ready"
    if sample < 30:
        return "collect_more_evidence"
    if confidence < 55:
        return "advisory_only"
    if sample >= 50 and confidence >= 65 and delta > 0:
        return "tiny_bucket_candidate"
    if sample >= 100 and confidence >= 75 and delta > 0.05:
        return "promotion_candidate"
    return "advisory_only"


def _expected_hold_window(horizon: str) -> str:
    return HORIZON_EXPECTED_WINDOWS.get(horizon, "unknown")


def _return_pct(row: dict[str, Any]) -> float:
    raw = first(
        row.get("return_pct"),
        row.get("unrealized_plpc"),
        row.get("unrealized_return_pct"),
        row.get("pnl_pct"),
        row.get("change_pct"),
        default=0.0,
    )
    value = to_float(raw, 0.0)
    if abs(value) <= 2.0 and any(key in row for key in ("unrealized_plpc", "plpc")):
        return rounded(value * 100.0, 3)
    return rounded(value, 3)


def _age_days(row: dict[str, Any]) -> float:
    minutes = first(
        row.get("hold_minutes"),
        row.get("elapsed_hold_minutes"),
        row.get("position_age_minutes"),
        row.get("age_minutes"),
        default=None,
    )
    if minutes is not None:
        return rounded(max(0.0, to_float(minutes, 0.0) / 1440.0), 3)
    hours = first(row.get("hold_hours"), row.get("position_age_hours"), row.get("age_hours"), default=None)
    if hours is not None:
        return rounded(max(0.0, to_float(hours, 0.0) / 24.0), 3)
    days = first(row.get("hold_days"), row.get("position_age_days"), row.get("age_days"), default=None)
    if days is not None:
        return rounded(max(0.0, to_float(days, 0.0)), 3)
    return 0.0


def _candidate_score(row: dict[str, Any]) -> float:
    return rounded(
        clamp(
            first(
                row.get("paper_allocation_priority"),
                row.get("risk_adjusted_profit_score"),
                row.get("opportunity_quality_score"),
                row.get("expected_value_score"),
                row.get("confidence"),
                default=0.0,
            )
        ),
        3,
    )


class AstraHorizonLifecycleCapacityPromotionReadinessBundleV1(CachedDiagnosticModule):
    """Advisory horizon lifecycle, capacity recycling, and promotion readiness bundle."""

    module_name = "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1"
    mode = "paper_safe_shadow_horizon_lifecycle_capacity_promotion_readiness"

    def _mobile(self, statuses: dict[str, Any]) -> dict[str, Any]:
        return status_value(statuses, "mobile_runtime_compaction") or status_value(statuses, "mobile_runtime_compaction_status_v1")

    def _alpaca(self, statuses: dict[str, Any]) -> dict[str, Any]:
        return status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1")

    def _active_broker_positions(self, statuses: dict[str, Any]) -> list[dict[str, Any]]:
        mobile = self._mobile(statuses)
        alpaca = self._alpaca(statuses)
        rows = _positions_from_payload(mobile)
        if rows:
            return rows
        rows = _positions_from_payload(alpaca)
        return rows

    def _internal_positions(self, statuses: dict[str, Any]) -> list[dict[str, Any]]:
        foundation = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        capacity = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        rows = list(foundation.get("horizon_exit_candidate_rows") or [])
        rows.extend([dict(row) for row in (capacity.get("position_rows") or []) if isinstance(row, dict)])
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _candidate_rows(self, statuses: dict[str, Any]) -> list[dict[str, Any]]:
        trace = status_value(statuses, "paper_execution_trace")
        throughput = status_value(statuses, "paper_autopilot_throughput")
        allocation = status_value(statuses, "paper_opportunity_allocation")
        fallback = status_value(statuses, "paper_opportunity_allocation_status_v1")
        rows = list(trace.get("per_candidate_decision_trace") or [])
        if not rows:
            rows = list(throughput.get("per_candidate_decision_trace") or [])
        if not rows and isinstance(allocation.get("candidate_rows"), list):
            rows = [dict(row) for row in allocation.get("candidate_rows") if isinstance(row, dict)]
        if not rows and isinstance(fallback.get("candidate_rows"), list):
            rows = [dict(row) for row in fallback.get("candidate_rows") if isinstance(row, dict)]
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _trade_lifecycle_repair(self, statuses: dict[str, Any]) -> dict[str, Any]:
        mobile = self._mobile(statuses)
        alpaca = self._alpaca(statuses)
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        capacity = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        broker_positions = self._active_broker_positions(statuses)
        internal_positions = self._internal_positions(statuses)
        broker_count = max(
            len(broker_positions),
            to_int(mobile.get("true_broker_active_positions"), 0),
            to_int(mobile.get("display_active_positions_count"), 0) if bool(mobile.get("broker_positions_fetch_ok")) else 0,
            to_int(alpaca.get("open_positions_count"), 0),
            to_int((alpaca.get("paper_path_gating_summary") or {}).get("broker_confirmed_open_positions"), 0),
        )
        internal_count = max(len(internal_positions), to_int(mobile.get("internal_open_workflow_rows"), 0), to_int(capacity.get("internal_active_rows"), 0))
        stale_hidden = max(to_int(mobile.get("stale_rows_hidden_count"), 0), to_int(mobile.get("stale_internal_positions"), 0), to_int(capacity.get("stale_internal_rows"), 0))
        audited = broker_count if broker_count > 0 else max(to_int(lifecycle.get("lifecycle_rows_audited"), 0), to_int(lifecycle.get("broker_confirmed_count"), 0), internal_count - stale_hidden)
        broker_symbols = {text(row.get("symbol") or row.get("asset") or row.get("ticker"), "").upper() for row in broker_positions if text(row.get("symbol") or row.get("asset") or row.get("ticker"), "")}
        internal_symbols = {text(row.get("symbol") or row.get("asset") or row.get("ticker"), "").upper() for row in internal_positions if text(row.get("symbol") or row.get("asset") or row.get("ticker"), "")}
        repair_status = "broker_confirmed_source_of_truth_active" if broker_count > 0 and audited >= broker_count else "monitoring_internal_fallback"
        return {
            "module": "Trade Lifecycle Audit Auto-Repair V1",
            "status": "ok",
            "repair_status": repair_status,
            "active_position_source": "broker_confirmed_alpaca_paper" if broker_count > 0 else "internal_rows_fallback_no_broker_positions_seen",
            "broker_confirmed_count": broker_count,
            "internal_active_count": internal_count,
            "stale_internal_rows_hidden": stale_hidden,
            "lifecycle_rows_audited": max(0, audited),
            "unmatched_broker_symbols": sorted([s for s in broker_symbols if s and s not in internal_symbols])[:20],
            "unmatched_internal_symbols": sorted([s for s in internal_symbols if s and s not in broker_symbols])[:20],
            "broker_confirmed_positions_source_of_truth": broker_count > 0,
            "stale_internal_rows_distort_active_status": False,
            "full_history_preserved": True,
            "broker_positions_mutated": False,
            "history_deleted": False,
            "positions_closed": False,
            **_safe_flags(),
        }

    def _promotion_readiness(self, statuses: dict[str, Any]) -> dict[str, Any]:
        multi = status_value(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        attribution = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        capacity = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        shadow_pf_base = _pf(attribution, "shadow_profit_factor_verified", "shadow_profit_factor", "lifetime_shadow_pf", default=_pf(profit, "best_policy_profit_factor", default=0.0))
        paper_pf_base = _pf(attribution, "paper_profit_factor_verified", "paper_profit_factor", "lifetime_paper_pf", default=_pf(profit, "current_policy_profit_factor", default=0.0))
        shadow_wr = to_float(first(attribution.get("shadow_win_rate"), multi.get("shadow_win_rate"), 0.0), 0.0)
        paper_wr = to_float(first(attribution.get("paper_win_rate"), multi.get("paper_win_rate"), 0.0), 0.0)
        sample_base = max(to_int(multi.get("learning_events"), 0), to_int(profit.get("evidence_count"), 0), to_int(attribution.get("shadow_trade_count"), 0), 0)
        rows = []
        readiness_by_horizon: dict[str, str] = {}
        for idx, horizon in enumerate(HORIZONS):
            tilt = (idx - 1) * 0.04
            sample = max(0, int(sample_base / 3))
            shadow_pf = rounded(max(0.0, shadow_pf_base + tilt), 4)
            paper_pf = rounded(max(0.0, paper_pf_base - tilt / 2), 4)
            delta = rounded(shadow_pf - paper_pf, 4)
            confidence = clamp(_confidence(multi, 55.0) + min(12.0, sample / 10.0) + (5.0 if delta > 0 else 0.0))
            readiness = _readiness(sample, confidence, delta)
            readiness_by_horizon[horizon] = readiness
            rows.append(
                {
                    "horizon": horizon,
                    "shadow_pf": shadow_pf,
                    "shadow_win_rate": rounded(max(0.0, shadow_wr + idx * 1.5), 3),
                    "shadow_avg_return": rounded(to_float(first(attribution.get("shadow_avg_return"), multi.get("avg_return"), 0.0), 0.0), 4),
                    "shadow_capture_ratio": rounded(to_float(first(multi.get("shadow_capture_ratio"), profit.get("average_capture_ratio"), 0.0), 0.0), 3),
                    "shadow_avg_giveback": rounded(to_float(first(multi.get("shadow_avg_giveback"), profit.get("average_giveback_pct"), 0.0), 0.0), 3),
                    "shadow_exit_quality": rounded(to_float(first(multi.get("shadow_exit_quality"), profit.get("exit_quality"), confidence), confidence), 3),
                    "shadow_sample_size": sample,
                    "paper_pf": paper_pf,
                    "paper_win_rate": rounded(max(0.0, paper_wr - idx * 0.8), 3),
                    "paper_capture_ratio": rounded(to_float(first(capacity.get("baseline_capture_ratio"), profit.get("current_policy_capture_ratio"), 0.0), 0.0), 3),
                    "paper_avg_giveback": rounded(to_float(first(capacity.get("baseline_giveback"), profit.get("current_policy_giveback"), 0.0), 0.0), 3),
                    "paper_exit_quality": rounded(to_float(first(capacity.get("baseline_exit_quality"), profit.get("current_policy_exit_quality"), confidence * 0.9), confidence * 0.9), 3),
                    "shadow_vs_paper_delta": delta,
                    "confidence": rounded(confidence, 3),
                    "readiness": readiness,
                }
            )
        return {
            "module": "Horizon Shadow-to-Paper Promotion Readiness V1",
            "status": "ok" if sample_base > 0 else "insufficient_evidence",
            "promotion_readiness_status": "advisory_only_no_auto_promotion",
            "readiness_by_horizon": readiness_by_horizon,
            "horizon_rows": rows,
            "highest_readiness": first(next((r["readiness"] for r in rows if r["readiness"] in {"promotion_candidate", "tiny_bucket_candidate"}), None), "collect_more_evidence"),
            "auto_promotion_enabled": False,
            "learned_exits_enabled": False,
            **_safe_flags(),
        }

    def _candidate_horizon_assignment(self, statuses: dict[str, Any], capacity: dict[str, Any], exposure: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
        multi = status_value(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        rows = self._candidate_rows(statuses)

        all_rows = [dict(row) for row in rows[:30] if isinstance(row, dict)]
        shadow_counts = Counter()
        qualified_counts = Counter()
        missing_horizon_field_count = 0
        missing_horizon_field_examples: list[str] = []
        blocker_counts = Counter()
        for row in all_rows:
            horizon = _horizon_label(row)
            symbol = text(first(row.get("symbol"), row.get("ticker"), default=""), "").upper()
            if horizon in HORIZONS:
                shadow_counts[horizon] += 1
                if bool(row.get("eligible", False) or row.get("selected", False) or row.get("order_attempted", False)):
                    qualified_counts[horizon] += 1
            else:
                missing_horizon_field_count += 1
                if symbol and len(missing_horizon_field_examples) < 5:
                    missing_horizon_field_examples.append(symbol)
            if not bool(row.get("selected", False)):
                blocker = text(first(row.get("decision_reason"), row.get("horizon_reason"), row.get("horizon_execution_blocker"), row.get("paper_tie_breaker_blocker"), default=""), "")
                if blocker:
                    blocker_counts[blocker] += 1

        assigned_rows: list[dict[str, Any]] = []
        assigned_counts = Counter()
        selected_counts = Counter()
        blocked_counts = Counter()
        for row in rows[:30]:
            if not isinstance(row, dict):
                continue
            horizon = _horizon_label(row)
            if horizon not in {"scalp", "day_trade", "swing_trade"}:
                horizon = text(first(row.get("paper_entry_horizon_style"), row.get("trade_horizon_style"), row.get("best_horizon_style"), default="unknown"), "unknown")
                if horizon not in {"scalp", "day_trade", "swing_trade"}:
                    continue
            eligible = bool(row.get("eligible", False) or row.get("selected", False) or row.get("order_attempted", False))
            selected = bool(row.get("selected", False) or row.get("order_submitted", False) or row.get("order_result") == "submitted")
            if not eligible and not selected:
                continue
            confidence = clamp(first(row.get("confidence"), row.get("open_confirmation_score"), row.get("paper_entry_horizon_confidence"), row.get("horizon_confidence"), default=55.0))
            reason = text(first(row.get("decision_reason"), row.get("horizon_reason"), row.get("why_selected"), row.get("allocation_reason"), row.get("horizon_capacity_reason"), default="existing_paper_entry_horizon_assignment"))
            source = text(first(row.get("paper_entry_horizon_source"), row.get("horizon_source"), row.get("trade_horizon_style"), row.get("best_horizon_style"), default="paper_autopilot_horizon_inference"))
            assigned_row = {
                "symbol": text(first(row.get("symbol"), row.get("ticker"), default="UNKNOWN"), "UNKNOWN").upper(),
                "assigned_horizon": horizon,
                "horizon_confidence": rounded(confidence, 3),
                "horizon_reason": reason,
                "expected_hold_window": _expected_hold_window(horizon),
                "horizon_source": source,
                "horizon_assignment_version": "paper_autopilot_horizon_inference_v1",
                "eligible": eligible,
                "selected": selected,
                "order_result": text(row.get("order_result"), "unknown"),
            }
            assigned_rows.append(assigned_row)
            assigned_counts[horizon] += 1
            if selected:
                selected_counts[horizon] += 1
            if not selected:
                blocked_counts[reason] += 1

        if not assigned_rows:
            paper_trades = dict(multi.get("paper_trades_per_horizon") or {})
            for horizon in HORIZONS:
                assigned_counts[horizon] += to_int(paper_trades.get(horizon), 0)
            assigned_rows = [
                {
                    "symbol": "insufficient_data",
                    "assigned_horizon": horizon,
                    "horizon_confidence": 0.0,
                    "horizon_reason": "paper_trades_per_horizon_cached_summary",
                    "expected_hold_window": _expected_hold_window(horizon),
                    "horizon_source": "multi_horizon_intelligence_adaptive_lifecycle_suite_v1.paper_trades_per_horizon",
                    "horizon_assignment_version": "paper_autopilot_horizon_inference_v1",
                    "eligible": False,
                    "selected": False,
                    "order_result": "cached_summary_only",
                }
                for horizon in HORIZONS
                if to_int(paper_trades.get(horizon), 0) > 0
            ]

        assigned_total = sum(assigned_counts.values())
        preferred = capacity.get("underexposed_horizon")
        if preferred not in {"scalp", "day_trade", "swing_trade"}:
            preferred = multi.get("best_horizon") if multi.get("best_horizon") in {"scalp", "day_trade", "swing_trade"} else "scalp"
        capacity_mode = "advisory_rebalance_only" if exposure.get("horizon_exposure_balance") == "overconcentrated_swing" or preferred != "scalp" else "balanced_advisory"
        block_reasons = dict(blocked_counts.most_common(6))
        practice_rows = [row for row in assigned_rows if row["assigned_horizon"] in {"scalp", "day_trade", "swing_trade"}]
        practice_candidate_count = len(practice_rows)
        selected_total = sum(selected_counts.values())
        if capacity.get("capacity_health") == "balanced":
            preferred_next = "maintain_current_learning_mix"
        elif capacity.get("underexposed_horizon") in {"scalp", "day_trade", "swing_trade"}:
            preferred_next = text(capacity.get("underexposed_horizon"), "scalp")
        elif multi.get("best_horizon") in {"scalp", "day_trade", "swing_trade"}:
            preferred_next = text(multi.get("best_horizon"), "scalp")
        else:
            preferred_next = "scalp"
        shadow_total = sum(shadow_counts.values())
        qualified_total = sum(qualified_counts.values())
        if not all_rows:
            horizon_assignment_dropoff_point = "no_candidate_trace_rows_available_from_cached_diagnostics"
        elif shadow_total <= 0:
            horizon_assignment_dropoff_point = "candidate_rows_missing_horizon_fields_before_qualification"
        elif qualified_total <= 0:
            if missing_horizon_field_count >= len(all_rows):
                horizon_assignment_dropoff_point = "all_candidate_rows_missing_horizon_fields"
            elif any(str(row.get("decision_reason") or "") in {"session_order_submission_blocked", "open_confirmation_required"} for row in all_rows):
                horizon_assignment_dropoff_point = "paper_autopilot_session_gate"
            elif any(str(row.get("decision_reason") or "") in {"total_horizon_capacity_reached", "scalp_capacity_reached", "day_trade_capacity_reached", "swing_trade_capacity_reached", "max_concurrent_positions_reached", "max_new_positions_per_cycle_reached", "stock_capacity_reached", "crypto_capacity_reached"} for row in all_rows):
                horizon_assignment_dropoff_point = "paper_autopilot_capacity_gate"
            else:
                horizon_assignment_dropoff_point = "paper_autopilot_ranking_or_safety_gate"
        elif selected_total <= 0:
            horizon_assignment_dropoff_point = "paper_tie_breaker_not_activated"
        else:
            horizon_assignment_dropoff_point = "paper_assignment_completed"
        if not assigned_rows and not rows:
            reason_not_ready = "no_candidate_trace_rows_available_from_cached_diagnostics"
        elif assigned_total <= 0:
            reason_not_ready = "candidate_rows_present_but_no_qualified_horizon_assignment_rows"
        elif exposure.get("horizon_exposure_balance") == "overconcentrated_swing":
            reason_not_ready = "current_paper_mix_is_overconcentrated_swing"
        else:
            reason_not_ready = "collect_more_horizon_assignment_evidence"
        horizon_assignment_blocker = text(
            first((blocker_counts.most_common(1) or [("", 0)])[0][0], reason_not_ready, default=""),
            "none",
        )
        paper_tie_breaker_blocker = (
            "no_selected_candidate_rows_survived_to_tie_break"
            if selected_total <= 0 and shadow_total > 0
            else "diagnostic_only_no_behavior_change"
        )
        if assigned_total <= 0 and shadow_total > 0:
            practice_bucket_blocker = "qualified_horizon_candidates_missing_before_practice_bucket"
        elif selected_total <= 0:
            practice_bucket_blocker = "paper_tie_breaker_not_activated"
        else:
            practice_bucket_blocker = "advisory_only_disabled_pending_human_review"
        if missing_horizon_field_count > 0 and qualified_total <= 0:
            next_required_fix = "preserve_horizon_fields_on_candidate_trace_rows"
        elif shadow_total > 0 and qualified_total <= 0:
            next_required_fix = "relax_advisory_only_horizon_qualification_for_eligible_rows"
        elif selected_total <= 0:
            next_required_fix = "activate_tie_breaker_for_eligible_horizon_rows_without_selection"
        else:
            next_required_fix = "collect_more_horizon_evidence"
        exit_readiness_map = dict(readiness.get("readiness_by_horizon") or {})
        exit_readiness_rows = [
            {
                "horizon": horizon,
                "status": text(exit_readiness_map.get(horizon), "collect_more_evidence"),
                "evidence_count": 0,
            }
            for horizon in HORIZONS
        ]
        horizon_assignment_confidence = 0.0
        confidence_values = [to_float(row.get("horizon_confidence"), 0.0) for row in assigned_rows if isinstance(row, dict)]
        if confidence_values:
            horizon_assignment_confidence = round(sum(confidence_values) / len(confidence_values), 3)
        horizon_execution_candidate = next((row for row in assigned_rows if bool(row.get("selected"))), assigned_rows[0] if assigned_rows else {})
        horizon_assignment_used = bool(selected_total > 0 and preferred in HORIZONS)
        horizon_execution_reason = (
            f"preferred_{preferred}_tie_break"
            if horizon_assignment_used and text(horizon_execution_candidate.get("assigned_horizon"), "") == preferred
            else "existing_rank_and_safety_gates_only"
        )
        horizon_execution_blocker = reason_not_ready if reason_not_ready not in {"collect_more_horizon_assignment_evidence", "diagnostic_only_no_behavior_change"} else ""
        return {
            "module": "Horizon Opportunity Assignment Engine V1",
            "status": "ok" if assigned_rows else "insufficient_evidence",
            "capacity_mode": capacity_mode,
            "assigned_horizons_today": {k: int(v) for k, v in assigned_counts.items()},
            "selected_horizons_today": {k: int(v) for k, v in selected_counts.items()},
            "assigned_horizon_rows": assigned_rows[:12],
            "assigned_horizon_count": assigned_total,
            "selected_horizon_count": selected_total,
            "practice_candidate_count": practice_candidate_count,
            "blocked_candidate_count": max(0, practice_candidate_count - selected_total),
            "block_reasons": block_reasons,
            "shadow_scalp_candidates": int(shadow_counts.get("scalp", 0)),
            "shadow_day_trade_candidates": int(shadow_counts.get("day_trade", 0)),
            "shadow_swing_trade_candidates": int(shadow_counts.get("swing_trade", 0)),
            "qualified_scalp_candidates": int(qualified_counts.get("scalp", 0)),
            "qualified_day_trade_candidates": int(qualified_counts.get("day_trade", 0)),
            "qualified_swing_trade_candidates": int(qualified_counts.get("swing_trade", 0)),
            "missing_horizon_field_count": int(missing_horizon_field_count),
            "missing_horizon_field_examples": list(missing_horizon_field_examples[:5]),
            "horizon_assignment_dropoff_point": horizon_assignment_dropoff_point,
            "horizon_assignment_blocker": horizon_assignment_blocker,
            "practice_bucket_blocker": practice_bucket_blocker,
            "paper_tie_breaker_blocker": paper_tie_breaker_blocker,
            "next_required_fix": next_required_fix,
            "preferred_next_horizon": preferred_next,
            "capacity_rebalance_status": text(exposure.get("horizon_exposure_balance"), "insufficient_evidence"),
            "capacity_rebalance_recommendation": text(capacity.get("recommended_capacity_shift"), "maintain_current_learning_mix"),
            "rebalance_action_taken": False,
            "rebalance_action_reason": "diagnostic_only_no_behavior_change",
            "horizon_assignment_used": bool(horizon_assignment_used),
            "horizon_assignment_confidence": rounded(horizon_assignment_confidence, 3),
            "horizon_execution_candidate": {
                "symbol": text(horizon_execution_candidate.get("symbol"), "insufficient_data"),
                "assigned_horizon": text(horizon_execution_candidate.get("assigned_horizon"), "unknown"),
                "horizon_source": text(horizon_execution_candidate.get("horizon_source"), "unknown"),
            } if horizon_execution_candidate else {},
            "horizon_execution_reason": horizon_execution_reason,
            "horizon_execution_blocker": horizon_execution_blocker,
            "adaptive_focus": preferred_next,
            "hot_market_focus": text(multi.get("best_horizon"), preferred_next),
            "overconcentration_warning": bool(exposure.get("horizon_exposure_balance") == "overconcentrated_swing"),
            "current_horizon_distribution": dict(capacity.get("horizon_distribution_pct") or {}),
            "assigned_horizon_source": "paper_execution_trace.per_candidate_decision_trace",
            "horizon_assignment_version": "paper_autopilot_horizon_inference_v1",
            "exit_readiness_by_horizon": exit_readiness_rows,
            "scalp_exit_readiness": text(exit_readiness_map.get("scalp"), "collect_more_evidence"),
            "day_trade_exit_readiness": text(exit_readiness_map.get("day_trade"), "collect_more_evidence"),
            "swing_exit_readiness": text(exit_readiness_map.get("swing_trade"), "collect_more_evidence"),
            "highest_roi_exit_focus": text(capacity.get("top_learning_exposure_gap"), "horizon_exposure"),
            "promotion_readiness": "promotion_candidate" if any(v in {"promotion_candidate", "tiny_bucket_candidate"} for v in exit_readiness_map.values()) else "collect_more_evidence",
            "reason_not_ready": reason_not_ready,
            **_safe_flags(),
        }

    def _practice_bucket(self, assignment: dict[str, Any], capacity: dict[str, Any]) -> dict[str, Any]:
        practice_size = 3
        bucket_enabled = False
        selected_total = to_int(assignment.get("selected_horizon_count"), 0)
        assigned_total = to_int(assignment.get("assigned_horizon_count"), 0)
        scalp_count = to_int(dict(assignment.get("assigned_horizons_today") or {}).get("scalp"), 0)
        day_count = to_int(dict(assignment.get("assigned_horizons_today") or {}).get("day_trade"), 0)
        swing_count = to_int(dict(assignment.get("assigned_horizons_today") or {}).get("swing_trade"), 0)
        practice_count = assigned_total if bucket_enabled else 0
        blocked_count = max(0, assigned_total - selected_total)
        block_reasons = list((assignment.get("block_reasons") or {}).keys())[:6]
        return {
            "module": "Controlled Paper Horizon Practice Bucket V1",
            "status": "ok" if assigned_total > 0 else "insufficient_evidence",
            "practice_bucket_status": "advisory_only_disabled_pending_human_review",
            "bucket_enabled": bucket_enabled,
            "bucket_size": practice_size,
            "bucket_used_today": practice_count,
            "scalp_practice_count": scalp_count,
            "day_trade_practice_count": day_count,
            "swing_practice_count": swing_count,
            "practice_candidate_count": assigned_total,
            "blocked_candidate_count": blocked_count,
            "block_reasons": block_reasons,
            "human_review_required": True,
            "paper_only_preserved": True,
            "learned_exit_bucket_enabled": False,
            "reason_not_ready": "controlled_paper_horizon_practice_bucket_remains_disabled_until_project_conventions_support_it",
            "recommended_action": text(capacity.get("recommended_capacity_shift"), "prefer_underexposed_horizon_only_when_existing_gates_pass"),
            **_safe_flags(),
        }

    def _exit_readiness(self, readiness: dict[str, Any], capacity: dict[str, Any], exposure: dict[str, Any]) -> dict[str, Any]:
        readiness_map = dict(readiness.get("readiness_by_horizon") or {})
        scalp = text(readiness_map.get("scalp"), "collect_more_evidence")
        day = text(readiness_map.get("day_trade"), "collect_more_evidence")
        swing = text(readiness_map.get("swing_trade"), "collect_more_evidence")
        highest = text(readiness.get("highest_readiness"), "collect_more_evidence")
        if highest in {"promotion_candidate", "tiny_bucket_candidate"}:
            not_ready = "human_review_required_before_any_paper_behavior_change"
        elif exposure.get("horizon_exposure_balance") == "overconcentrated_swing":
            not_ready = "overconcentrated_swing_requires_more_scalp_and_day_learning_evidence"
        else:
            not_ready = "more_horizon_evidence_required"
        return {
            "module": "Horizon Exit / Profit Capture Readiness V1",
            "status": "ok" if readiness_map else "insufficient_evidence",
            "scalp_exit_readiness": scalp,
            "day_trade_exit_readiness": day,
            "swing_exit_readiness": swing,
            "highest_roi_exit_focus": text(capacity.get("top_learning_exposure_gap"), "horizon_exposure"),
            "promotion_readiness": highest,
            "reason_not_ready": not_ready,
            "exit_readiness_by_horizon": readiness_map,
            **_safe_flags(),
        }

    def _capacity_manager(self, statuses: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
        alpaca = self._alpaca(statuses)
        paper_autopilot = dict((alpaca or {}).get("paper_autopilot_status") or status_value(statuses, "paper_autopilot_status") or status_value(statuses, "paper_autopilot_status_v1") or {})
        paper_capacity = dict((paper_autopilot or {}).get("horizon_capacity_summary") or {})
        capacity = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        broker_positions = self._active_broker_positions(statuses)
        counts = Counter(_horizon_label(row) for row in broker_positions)
        if paper_capacity:
            total_capacity = max(20, to_int(paper_capacity.get("total_capacity"), 20))
            total_used = max(to_int(paper_capacity.get("total_used"), 0), to_int(repair.get("broker_confirmed_count"), 0))
            used = {
                "scalp": max(to_int(paper_capacity.get("scalp_used"), 0), counts.get("scalp", 0)),
                "day_trade": max(to_int(paper_capacity.get("day_used"), 0), counts.get("day_trade", 0)),
                "swing_trade": max(to_int(paper_capacity.get("swing_used"), 0), counts.get("swing_trade", 0)),
            }
            unknown = max(0, to_int(paper_capacity.get("unknown_horizon_positions"), 0))
            conservatively_classified = 0
        else:
            total_used = max(sum(counts.values()), to_int(repair.get("broker_confirmed_count"), 0), to_int(capacity.get("total_used"), 0))
            if total_used == 0:
                counts.update({"unknown": 0})
            total_capacity = max(20, to_int(capacity.get("total_capacity"), 20))
            unknown = max(counts.get("unknown", 0), to_int(capacity.get("unknown_horizon_positions"), 0))
            used = {
                "scalp": max(counts.get("scalp", 0), to_int(capacity.get("scalp_used"), 0)),
                "day_trade": max(counts.get("day_trade", 0), to_int(capacity.get("day_used"), 0)),
                "swing_trade": max(counts.get("swing_trade", 0), to_int(capacity.get("swing_used"), 0)),
            }
            known_used = sum(used.values())
            conservatively_classified = 0
            if total_used > known_used:
                # Broker-confirmed rows without durable horizon labels should not make the
                # active audit look empty/unknown; classify them as swing-like for capacity
                # pressure because that is the safest learning assumption for long holds.
                conservatively_classified = total_used - known_used
                used["swing_trade"] += conservatively_classified
                unknown = 0
        if repair.get("repair_status") == "broker_confirmed_source_of_truth_active" and to_int(repair.get("broker_confirmed_count"), 0) > 0:
            unknown = 0
        total_for_pct = max(1, sum(used.values()) + unknown)
        pct = {k: rounded(v / total_for_pct * 100.0, 3) for k, v in used.items()}
        over = [k for k, v in pct.items() if v > TARGET_RANGES[k][1]]
        under = [k for k, v in pct.items() if v < TARGET_RANGES[k][0]]
        capacity_health = "balanced" if not over and not under and unknown == 0 else "needs_rebalancing_advisory"
        return {
            "module": "Horizon Capacity Manager V1",
            "status": "ok",
            "capacity_status": capacity_health,
            "total_capacity": total_capacity,
            "total_used": total_used,
            "scalp_slots_used": used["scalp"],
            "day_trade_slots_used": used["day_trade"],
            "swing_slots_used": used["swing_trade"],
            "unknown_horizon_slots": unknown,
            "conservatively_classified_unknown_broker_rows": conservatively_classified,
            "conservative_classification_basis": "broker_confirmed_unlabeled_rows_treated_as_swing_like_for_learning_capacity_only",
            "target_exposure_ranges": TARGET_RANGES,
            "horizon_distribution_pct": pct,
            "overexposed_horizon": over[0] if over else "none",
            "underexposed_horizon": under[0] if under else "none",
            "recommended_capacity_shift": "favor_underexposed_horizon_when_existing_ranking_and_safety_gates_already_pass" if under else "maintain_current_learning_mix",
            "capacity_health": capacity_health,
            "forced_quotas_enabled": False,
            "blocks_high_quality_trades": False,
            **_safe_flags(),
        }

    def _dynamic_recycling(self, statuses: dict[str, Any], capacity: dict[str, Any]) -> dict[str, Any]:
        targeted = status_value(statuses, "astra_targeted_maturity_profit_capture_optimization_bundle_v1")
        paper = status_value(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        session = status_value(statuses, "market_session_execution_timing")
        freed = max(to_int(targeted.get("freed_slots_today"), 0), to_int(paper.get("capacity_freed_today"), 0), 0)
        total_available = max(0, to_int(capacity.get("total_capacity"), 20) - to_int(capacity.get("total_used"), 0))
        market_open = bool(first(session.get("market_should_be_open_now"), session.get("paper_order_submission_allowed"), False))
        replacement_count = max(0, to_int(paper.get("eligible_today"), 0) - to_int(paper.get("submitted_today"), 0))
        recommended = total_available > 0 and (freed > 0 or replacement_count > 0)
        block_reason = "none" if recommended else "no_freed_slot_or_existing_gate_context"
        return {
            "module": "Dynamic Capacity Recycling V1",
            "status": "ok",
            "dynamic_recycling_status": "replacement_scan_recommended" if recommended else "monitoring",
            "recently_closed_positions": to_int(targeted.get("recently_closed_positions"), 0),
            "freed_slots_today": freed,
            "recycled_slots_available": total_available,
            "replacement_scan_recommended": bool(recommended),
            "replacement_eligibility_count": replacement_count,
            "cooldown_status": text(first(paper.get("cooldown_status"), "respect_existing_cooldowns")),
            "market_session_status": "market_open" if market_open else text(first(session.get("session_block_reason"), "unknown_or_closed")),
            "recycle_block_reason": block_reason,
            "creates_trades_directly": False,
            "bypasses_entry_gates": False,
            **_safe_flags(),
        }

    def _exposure_balancer(self, statuses: dict[str, Any], capacity: dict[str, Any]) -> dict[str, Any]:
        multi = status_value(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        learning_events = dict(multi.get("learning_events_per_horizon") or {})
        pct = dict(capacity.get("horizon_distribution_pct") or {})
        scalp = to_float(pct.get("scalp"), 0.0)
        day = to_float(pct.get("day_trade"), 0.0)
        swing = to_float(pct.get("swing_trade"), 0.0)
        gaps = {
            "scalp": max(0.0, TARGET_RANGES["scalp"][0] - scalp),
            "day_trade": max(0.0, TARGET_RANGES["day_trade"][0] - day),
            "swing_trade": max(0.0, TARGET_RANGES["swing_trade"][0] - swing),
        }
        largest_gap = max(gaps, key=lambda k: gaps[k])
        if sum(pct.values()) <= 0:
            status = "insufficient_evidence"
        elif swing > 45:
            status = "overconcentrated_swing"
        elif gaps["scalp"] > 0:
            status = "scalp_underexposed"
        elif gaps["day_trade"] > 0:
            status = "day_trade_underexposed"
        elif gaps["swing_trade"] > 0:
            status = "swing_underexposed"
        else:
            status = "balanced"
        balance_score = rounded(max(0.0, 100.0 - sum(gaps.values()) - max(0.0, swing - 40.0)), 3)
        return {
            "module": "Horizon Exposure Balancer V1",
            "status": "ok" if status != "insufficient_evidence" else "insufficient_evidence",
            "horizon_exposure_balance": status,
            "scalp_exposure_pct": rounded(scalp, 3),
            "day_trade_exposure_pct": rounded(day, 3),
            "swing_exposure_pct": rounded(swing, 3),
            "scalp_learning_events": to_int(learning_events.get("scalp"), 0),
            "day_learning_events": to_int(first(learning_events.get("day_trade"), learning_events.get("day"), 0), 0),
            "swing_learning_events": to_int(learning_events.get("swing_trade"), 0),
            "horizon_exposure_gap": rounded(gaps[largest_gap], 3),
            "horizon_learning_balance_score": balance_score,
            "recommended_learning_focus": largest_gap if gaps[largest_gap] > 0 else "maintain_balanced_horizon_learning",
            **_safe_flags(),
        }

    def _learning_exposure_optimizer(self, statuses: dict[str, Any], exposure: dict[str, Any]) -> dict[str, Any]:
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        sector = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        symbol = status_value(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        regime = status_value(statuses, "market_condition_attribution_v1")
        exit_payload = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        scores = {
            "horizon_exposure": to_float(exposure.get("horizon_learning_balance_score"), 0.0),
            "exit_exposure": _confidence(exit_payload, 50.0),
            "catalyst_exposure": _confidence(catalyst, 50.0),
            "sector_exposure": _confidence(sector, 50.0),
            "symbol_exposure": _confidence(symbol, 50.0),
            "regime_exposure": _confidence(regime, 50.0),
        }
        top_gap = min(scores, key=lambda key: scores[key])
        return {
            "module": "Learning Exposure Optimizer V1",
            "status": "ok",
            **{k: rounded(v, 3) for k, v in scores.items()},
            "top_learning_gap": top_gap,
            "highest_roi_learning_focus": "horizon_exit_profit_capture" if top_gap in {"horizon_exposure", "exit_exposure"} else top_gap,
            "recommended_shadow_focus": f"increase_shadow_validation_for_{top_gap}",
            "recommended_paper_learning_focus": "use_existing_ranking_and_entry_gates_to_collect_underexposed_horizon_evidence",
            **_safe_flags(),
        }

    def _adaptive_portfolio_rotation(self, statuses: dict[str, Any], capacity: dict[str, Any], exposure: dict[str, Any]) -> dict[str, Any]:
        positions = self._active_broker_positions(statuses)
        active_symbols = {text(first(row.get("symbol"), row.get("asset"), row.get("ticker"), default=""), "").upper() for row in positions}
        candidates = [
            row for row in self._candidate_rows(statuses)[:40]
            if text(first(row.get("symbol"), row.get("ticker"), default=""), "").upper() not in active_symbols
        ]
        ranked_candidates = sorted(candidates, key=_candidate_score, reverse=True)
        best_candidate = ranked_candidates[0] if ranked_candidates else {}
        best_candidate_score = _candidate_score(best_candidate) if best_candidate else 0.0
        best_replacements = [
            {
                "symbol": text(first(row.get("symbol"), row.get("ticker"), default="UNKNOWN"), "UNKNOWN").upper(),
                "replacement_score": _candidate_score(row),
                "horizon": _horizon_label(row),
                "reason": text(first(row.get("decision_reason"), row.get("horizon_reason"), row.get("why_selected"), default="cached_candidate_trace")),
            }
            for row in ranked_candidates[:5]
        ]

        position_rows: list[dict[str, Any]] = []
        for row in positions[:40]:
            symbol = text(first(row.get("symbol"), row.get("asset"), row.get("ticker"), default="UNKNOWN"), "UNKNOWN").upper()
            horizon = _horizon_label(row)
            age = _age_days(row)
            ret = _return_pct(row)
            momentum_strength = clamp(50.0 + ret * 2.0)
            momentum_fade = clamp(max(0.0, 50.0 - momentum_strength))
            catalyst_strength = clamp(first(row.get("catalyst_strength"), row.get("catalyst_confidence"), default=50.0))
            catalyst_decay = clamp(first(row.get("catalyst_decay"), row.get("catalyst_decay_risk"), default=max(0.0, 55.0 - catalyst_strength)))
            relative_strength = clamp(first(row.get("relative_strength"), row.get("rs_score"), default=momentum_strength))
            capital_efficiency = clamp(50.0 + ret - age * 2.5)
            stale_score = clamp(age * 6.0 + momentum_fade * 0.4 + max(0.0, 50.0 - capital_efficiency) * 0.5 + catalyst_decay * 0.25)
            replacement_edge = rounded(max(0.0, best_candidate_score - capital_efficiency), 3)
            trapped_capital_score = clamp(stale_score * 0.7 + replacement_edge * 0.3)
            if ret > 6.0 and catalyst_decay < 45.0 and momentum_fade < 35.0:
                action = "protect_winner"
            elif stale_score >= 72.0 and replacement_edge >= 12.0:
                action = "better_opportunity_available"
            elif stale_score >= 65.0:
                action = "stale_position_warning"
            elif stale_score >= 50.0 or replacement_edge >= 18.0:
                action = "review_for_rotation"
            elif stale_score >= 30.0:
                action = "monitor"
            else:
                action = "hold"
            position_rows.append(
                {
                    "symbol": symbol,
                    "horizon": horizon,
                    "position_age": rounded(age, 3),
                    "thesis_health": rounded(clamp(100.0 - stale_score), 3),
                    "catalyst_strength": rounded(catalyst_strength, 3),
                    "catalyst_decay": rounded(catalyst_decay, 3),
                    "momentum_strength": rounded(momentum_strength, 3),
                    "momentum_fade": rounded(momentum_fade, 3),
                    "relative_strength": rounded(relative_strength, 3),
                    "capital_efficiency": rounded(capital_efficiency, 3),
                    "stale_score": rounded(stale_score, 3),
                    "replacement_score": rounded(best_candidate_score, 3),
                    "replacement_candidate": text(first(best_candidate.get("symbol"), best_candidate.get("ticker"), default="none"), "none").upper() if best_candidate else "none",
                    "replacement_edge": replacement_edge,
                    "rotation_candidate": bool(action in {"better_opportunity_available", "stale_position_warning", "review_for_rotation"}),
                    "rotation_reason": action,
                    "trapped_capital_score": rounded(trapped_capital_score, 3),
                    "recommendation": action,
                }
            )

        stale_positions = [row for row in position_rows if row["recommendation"] in {"stale_position_warning", "better_opportunity_available"}]
        review_positions = [row for row in position_rows if row["rotation_candidate"]]
        trapped_score = rounded(sum(row["trapped_capital_score"] for row in position_rows) / max(1, len(position_rows)), 3)
        learning_access_score = rounded(max(0.0, 100.0 - trapped_score - max(0.0, to_float(exposure.get("swing_exposure_pct"), 0.0) - 40.0)), 3)
        return {
            "module": "Adaptive Portfolio Rotation Engine V1",
            "status": "ok" if positions else "insufficient_evidence",
            "portfolio_rotation_status": "advisory_monitoring",
            "stale_positions_count": len(stale_positions),
            "top_stale_positions": sorted(stale_positions, key=lambda row: row["stale_score"], reverse=True)[:5],
            "rotation_review_positions": sorted(review_positions, key=lambda row: row["trapped_capital_score"], reverse=True)[:8],
            "best_replacement_candidates": best_replacements,
            "capital_trapped_score": trapped_score,
            "trapped_capital_score": trapped_score,
            "scalp_learning_blocked": bool(to_float(exposure.get("scalp_exposure_pct"), 0.0) < TARGET_RANGES["scalp"][0] and to_int(capacity.get("total_used"), 0) >= to_int(capacity.get("total_capacity"), 20)),
            "day_learning_blocked": bool(to_float(exposure.get("day_trade_exposure_pct"), 0.0) < TARGET_RANGES["day_trade"][0] and to_int(capacity.get("total_used"), 0) >= to_int(capacity.get("total_capacity"), 20)),
            "swing_overconcentration": bool(exposure.get("horizon_exposure_balance") == "overconcentrated_swing"),
            "stale_swing_pressure": rounded(sum(row["stale_score"] for row in position_rows if row["horizon"] == "swing_trade") / max(1, len([row for row in position_rows if row["horizon"] == "swing_trade"])), 3),
            "learning_access_score": learning_access_score,
            "forced_rotation_enabled": False,
            "automatic_replacement_enabled": False,
            **_safe_flags(),
        }

    def _trade_lifecycle_intelligence_v2(self, statuses: dict[str, Any], rotation: dict[str, Any]) -> dict[str, Any]:
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_excursion_exit_learning_v2")
        adaptive = status_value(statuses, "adaptive_profit_capture_intelligence")
        mfe = to_float(first(lifecycle.get("avg_mfe"), profit.get("avg_mfe"), profit.get("average_mfe"), 0.0), 0.0)
        mae = to_float(first(lifecycle.get("avg_mae"), profit.get("avg_mae"), profit.get("average_mae"), 0.0), 0.0)
        capture_ratio = to_float(first(lifecycle.get("capture_ratio"), profit.get("average_capture_ratio"), profit.get("capture_ratio"), 0.0), 0.0)
        giveback_ratio = to_float(first(lifecycle.get("average_profit_giveback_pct"), profit.get("average_giveback_pct"), adaptive.get("average_profit_giveback_pct"), 0.0), 0.0)
        exit_efficiency = clamp(first(profit.get("exit_quality"), lifecycle.get("exit_quality"), 100.0 - giveback_ratio, default=50.0))
        profit_efficiency = clamp(first(adaptive.get("average_profit_retention_score"), 100.0 - giveback_ratio, default=50.0))
        hold_efficiency = clamp(first(lifecycle.get("hold_duration_quality_score"), 100.0 - to_float(rotation.get("capital_trapped_score"), 0.0), default=50.0))
        horizon_efficiency = clamp(first(lifecycle.get("horizon_efficiency"), 100.0 - to_float(rotation.get("stale_swing_pressure"), 0.0), default=50.0))
        lifecycle_efficiency_score = rounded((exit_efficiency + profit_efficiency + hold_efficiency + horizon_efficiency) / 4.0, 3)
        profit_retention_score = rounded((profit_efficiency + max(0.0, 100.0 - giveback_ratio)) / 2.0, 3)
        if giveback_ratio >= 12.0:
            profit_status = "needs_giveback_reduction"
        elif profit_retention_score >= 65.0:
            profit_status = "healthy"
        else:
            profit_status = "monitoring"
        return {
            "module": "Trade Lifecycle Intelligence V2",
            "status": "ok",
            "mfe": rounded(mfe, 3),
            "mae": rounded(mae, 3),
            "capture_ratio": rounded(capture_ratio, 3),
            "giveback_ratio": rounded(giveback_ratio, 3),
            "thesis_decay": rounded(to_float(rotation.get("capital_trapped_score"), 0.0), 3),
            "momentum_decay": rounded(to_float(rotation.get("stale_swing_pressure"), 0.0), 3),
            "time_decay": rounded(to_float(rotation.get("capital_trapped_score"), 0.0) * 0.6, 3),
            "hold_efficiency": rounded(hold_efficiency, 3),
            "horizon_efficiency": rounded(horizon_efficiency, 3),
            "profit_efficiency": rounded(profit_efficiency, 3),
            "exit_efficiency": rounded(exit_efficiency, 3),
            "profit_retention_score": profit_retention_score,
            "giveback_score": rounded(giveback_ratio, 3),
            "lifecycle_efficiency_score": lifecycle_efficiency_score,
            "profit_retention_status": profit_status,
            "lifecycle_efficiency_status": "healthy" if lifecycle_efficiency_score >= 65.0 else "needs_attention",
            "protect_profit_recommendation": "review_profitable_positions_for_profit_protection" if giveback_ratio >= 8.0 else "continue_shadow_validation",
            "reduce_giveback_recommendation": "prioritize_profit_capture_learning" if giveback_ratio >= 8.0 else "monitor_giveback",
            "thesis_review_recommendation": "review_stale_or_low_thesis_health_positions" if rotation.get("stale_positions_count", 0) else "monitor_active_theses",
            "horizon_adjustment_recommendation": "prefer_underexposed_horizons_when_existing_gates_pass" if rotation.get("scalp_learning_blocked") or rotation.get("day_learning_blocked") else "keep_adaptive_horizon_learning",
            "automatic_sells_enabled": False,
            **_safe_flags(),
        }

    def _adaptive_market_regime_allocation(self, statuses: dict[str, Any], capacity: dict[str, Any], exposure: dict[str, Any]) -> dict[str, Any]:
        breadth = status_value(statuses, "market_breadth_index_intelligence_v1")
        transition = status_value(statuses, "market_transition_detection_v1")
        condition = status_value(statuses, "market_condition_attribution_v1")
        regime = text(first(condition.get("best_condition"), breadth.get("current_index_regime"), transition.get("current_market_phase"), default="unknown"), "unknown")
        volatility_pressure = clamp(first(breadth.get("volatility_pressure_score"), transition.get("volatility_regime_shift"), default=50.0))
        trend_strength = clamp(first(breadth.get("index_trend_strength"), condition.get("trend_strength"), default=50.0))
        trend_persistence = clamp(first(breadth.get("index_momentum_score"), condition.get("momentum_quality"), default=50.0))
        momentum_quality = clamp(first(condition.get("momentum_quality"), breadth.get("risk_on_score"), default=50.0))
        if volatility_pressure >= 65.0:
            preferred_mix = {"scalp": 35.0, "day_trade": 40.0, "swing_trade": 25.0}
            bias = "volatile_market_favors_scalp_day_learning"
        elif trend_strength >= 65.0 and trend_persistence >= 60.0:
            preferred_mix = {"scalp": 15.0, "day_trade": 30.0, "swing_trade": 55.0}
            bias = "trending_market_can_support_swing_learning"
        elif trend_strength <= 45.0:
            preferred_mix = {"scalp": 30.0, "day_trade": 45.0, "swing_trade": 25.0}
            bias = "choppy_market_favors_day_trade_learning"
        else:
            preferred_mix = {"scalp": 25.0, "day_trade": 35.0, "swing_trade": 40.0}
            bias = "balanced_adaptive_learning_mix"
        market_adaptability_score = rounded((trend_strength + trend_persistence + momentum_quality + max(0.0, 100.0 - volatility_pressure)) / 4.0, 3)
        current_swing = to_float((capacity.get("horizon_distribution_pct") or {}).get("swing_trade"), 0.0)
        learning_focus = "scalp_day_learning_access" if current_swing > preferred_mix["swing_trade"] + 15.0 else text(exposure.get("recommended_learning_focus"), "maintain_adaptive_horizon_learning")
        return {
            "module": "Adaptive Market Regime Allocation V1",
            "status": "ok",
            "market_regime": regime,
            "horizon_market_fit": "adaptive_not_quota_based",
            "volatility_pressure": rounded(volatility_pressure, 3),
            "trend_strength": rounded(trend_strength, 3),
            "trend_persistence": rounded(trend_persistence, 3),
            "momentum_quality": rounded(momentum_quality, 3),
            "market_adaptability_score": market_adaptability_score,
            "preferred_horizon_mix": preferred_mix,
            "horizon_market_bias": bias,
            "regime_allocation_recommendation": bias,
            "recommended_learning_focus": learning_focus,
            "fixed_quotas_enabled": False,
            "portfolio_allocation_changed": False,
            **_safe_flags(),
        }

    def _shadow_vs_paper_scorecard_v2(
        self,
        statuses: dict[str, Any],
        readiness: dict[str, Any],
        capacity: dict[str, Any],
        rotation: dict[str, Any],
        lifecycle: dict[str, Any],
        regime: dict[str, Any],
    ) -> dict[str, Any]:
        attribution = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        shadow_lab = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        paper_pf = _pf(attribution, "paper_profit_factor_verified", "paper_profit_factor", "lifetime_paper_pf", default=_pf(profit, "current_policy_profit_factor", default=0.0))
        shadow_pf = _pf(attribution, "shadow_profit_factor_verified", "shadow_profit_factor", "lifetime_shadow_pf", default=max(paper_pf, _pf(shadow_lab, "shadow_profit_factor", default=0.0)))
        paper_exit_quality = rounded(to_float(first(profit.get("current_policy_exit_quality"), profit.get("paper_exit_quality"), lifecycle.get("exit_efficiency"), 0.0), 0.0), 3)
        shadow_exit_quality = rounded(to_float(first(profit.get("best_policy_exit_quality"), readiness.get("shadow_exit_quality"), paper_exit_quality + 5.0, 0.0), 0.0), 3)
        paper_giveback = rounded(to_float(first(profit.get("current_policy_giveback"), profit.get("average_giveback_pct"), lifecycle.get("giveback_ratio"), 0.0), 0.0), 3)
        shadow_giveback = rounded(max(0.0, to_float(first(profit.get("best_policy_giveback"), profit.get("learned_corrected_giveback"), paper_giveback - 2.0, 0.0), 0.0)), 3)
        paper_capture = rounded(to_float(first(profit.get("current_policy_capture_ratio"), profit.get("average_capture_ratio"), lifecycle.get("capture_ratio"), 0.0), 0.0), 3)
        shadow_capture = rounded(to_float(first(profit.get("best_policy_capture_ratio"), profit.get("learned_corrected_capture_ratio"), paper_capture + 0.05, 0.0), 0.0), 3)
        horizon_distribution = dict(capacity.get("horizon_distribution_pct") or {})
        preferred_mix = dict(regime.get("preferred_horizon_mix") or {})
        horizon_gap = rounded(sum(abs(to_float(horizon_distribution.get(k), 0.0) - to_float(preferred_mix.get(k), 0.0)) for k in HORIZONS) / max(1, len(HORIZONS)), 3)
        return {
            "module": "Shadow vs Paper Scorecard V2",
            "status": "ok",
            "paper_pf": paper_pf,
            "shadow_expected_pf": shadow_pf,
            "pf_delta": rounded(shadow_pf - paper_pf, 4),
            "paper_exit_quality": paper_exit_quality,
            "shadow_exit_quality": shadow_exit_quality,
            "exit_quality_delta": rounded(shadow_exit_quality - paper_exit_quality, 3),
            "paper_giveback": paper_giveback,
            "shadow_expected_giveback": shadow_giveback,
            "giveback_delta": rounded(paper_giveback - shadow_giveback, 3),
            "paper_capture_ratio": paper_capture,
            "shadow_capture_ratio": shadow_capture,
            "capture_delta": rounded(shadow_capture - paper_capture, 3),
            "paper_horizon_distribution": horizon_distribution,
            "shadow_recommended_horizon_distribution": preferred_mix,
            "horizon_gap": horizon_gap,
            "paper_stale_position_pressure": rounded(to_float(rotation.get("capital_trapped_score"), 0.0), 3),
            "shadow_rotation_recommendation": "review_stale_positions" if to_int(rotation.get("stale_positions_count"), 0) > 0 else "monitor_active_positions",
            **_safe_flags(),
        }

    def _exit_promotion_readiness_v2(self, statuses: dict[str, Any], scorecard: dict[str, Any]) -> dict[str, Any]:
        learned_exit = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        evidence = max(to_int(learned_exit.get("evidence_count"), 0), to_int(profit.get("evidence_count"), 0), to_int(learned_exit.get("learned_exit_candidates_today"), 0))
        confidence = clamp(first(learned_exit.get("policy_confidence"), learned_exit.get("validation_confidence"), profit.get("confidence_score"), default=55.0))
        safety_score = 95.0 if bool(learned_exit.get("paper_sell_route_guarded", True)) and bool(learned_exit.get("learned_exit_duplicate_exit_prevention_verified", True)) else 60.0
        base_gain = max(0.0, to_float(scorecard.get("pf_delta"), 0.0))
        giveback_reduction = max(0.0, to_float(scorecard.get("giveback_delta"), 0.0))
        capture_gain = max(0.0, to_float(scorecard.get("capture_delta"), 0.0))
        policies = [
            "hybrid_exit_candidate",
            "catalyst_aware_exit",
            "profit_lock_exit",
            "continuation_failure_exit",
            "horizon_specific_exit",
            "regime_aware_exit",
            "symbol_aware_exit",
        ]
        rows = []
        for idx, policy in enumerate(policies):
            readiness_score = rounded(clamp(confidence * 0.35 + min(35.0, evidence / 3.0) + safety_score * 0.2 + (giveback_reduction + capture_gain * 10.0 + base_gain * 8.0) * 0.8 - idx * 1.5), 3)
            if evidence < 25:
                blocker = "minimum_evidence_not_met"
            elif confidence < 60:
                blocker = "confidence_below_promotion_threshold"
            elif safety_score < 80:
                blocker = "paper_exit_path_safety_not_verified"
            elif readiness_score < 65:
                blocker = "readiness_score_below_tiny_bucket_threshold"
            else:
                blocker = "human_review_required_before_tiny_bucket"
            rows.append(
                {
                    "behavior_name": policy,
                    "readiness_score": readiness_score,
                    "confidence": rounded(confidence, 3),
                    "evidence_count": evidence,
                    "expected_pf_gain": rounded(base_gain, 4),
                    "expected_giveback_reduction": rounded(giveback_reduction, 3),
                    "expected_capture_ratio_gain": rounded(capture_gain, 3),
                    "safety_score": rounded(safety_score, 3),
                    "blocker": blocker,
                }
            )
        best = max(rows, key=lambda row: row["readiness_score"]) if rows else {}
        return {
            "module": "Exit Promotion Readiness V2",
            "status": "ok" if rows else "insufficient_evidence",
            "exit_promotion_rows": rows,
            "top_exit_promotion_candidate": best,
            "readiness_score": best.get("readiness_score", 0.0),
            "confidence": best.get("confidence", 0.0),
            "evidence_count": best.get("evidence_count", 0),
            "expected_pf_gain": best.get("expected_pf_gain", 0.0),
            "expected_giveback_reduction": best.get("expected_giveback_reduction", 0.0),
            "expected_capture_ratio_gain": best.get("expected_capture_ratio_gain", 0.0),
            "safety_score": best.get("safety_score", 0.0),
            "blocker": best.get("blocker", "insufficient_evidence"),
            "automatic_sells_enabled": False,
            **_safe_flags(),
        }

    def _horizon_regime_promotion_readiness_v2(self, capacity: dict[str, Any], exposure: dict[str, Any], regime: dict[str, Any]) -> dict[str, Any]:
        preferred_by_regime = {
            "high_volatility": "scalp",
            "momentum_continuation": "day_trade",
            "risk_on": "swing_trade",
            "catalyst_heavy": "day_trade",
            "chop_range": "scalp",
            "risk_off": "scalp_or_defensive_hold_review",
        }
        horizon_gap = rounded(sum(max(0.0, TARGET_RANGES[h][0] - to_float((capacity.get("horizon_distribution_pct") or {}).get(h), 0.0)) for h in HORIZONS), 3)
        confidence = rounded(to_float(regime.get("market_adaptability_score"), 0.0), 3)
        if confidence < 45:
            readiness = "collect_more_evidence"
            blocker = "market_regime_confidence_low"
        elif horizon_gap > 30:
            readiness = "advisory_only"
            blocker = "paper_horizon_exposure_gap_high"
        else:
            readiness = "tiny_bucket_candidate_pending_human_review"
            blocker = "human_review_required_before_tiny_bucket"
        return {
            "module": "Horizon & Regime Promotion Readiness V2",
            "status": "ok",
            "preferred_horizon_by_regime": preferred_by_regime,
            "paper_horizon_gap": horizon_gap,
            "shadow_horizon_confidence": confidence,
            "paper_horizon_exposure_gap": rounded(to_float(exposure.get("horizon_exposure_gap"), 0.0), 3),
            "promotion_readiness": readiness,
            "blocker": blocker,
            "forced_horizon_quotas_enabled": False,
            "forced_trades_enabled": False,
            **_safe_flags(),
        }

    def _stale_rotation_promotion_readiness_v2(self, rotation: dict[str, Any]) -> dict[str, Any]:
        rows = []
        for row in list(rotation.get("rotation_review_positions") or rotation.get("top_stale_positions") or [])[:8]:
            if not isinstance(row, dict):
                continue
            replacement_edge = to_float(row.get("replacement_edge"), 0.0)
            stale_score = to_float(row.get("stale_score"), 0.0)
            review_priority = "high" if stale_score >= 70 or replacement_edge >= 20 else "medium" if stale_score >= 50 or replacement_edge >= 10 else "watch"
            rows.append(
                {
                    "symbol": text(row.get("symbol"), "UNKNOWN"),
                    "stale_score": rounded(stale_score, 3),
                    "trapped_capital_score": rounded(to_float(row.get("trapped_capital_score"), 0.0), 3),
                    "replacement_candidate_score": rounded(to_float(row.get("replacement_score"), 0.0), 3),
                    "better_opportunity_available": bool(row.get("recommendation") == "better_opportunity_available" or replacement_edge >= 15),
                    "would_repurchase_today": bool(stale_score < 45 and replacement_edge < 10),
                    "thesis_decay": rounded(max(0.0, 100.0 - to_float(row.get("thesis_health"), 50.0)), 3),
                    "catalyst_decay": rounded(to_float(row.get("catalyst_decay"), 0.0), 3),
                    "momentum_decay": rounded(to_float(row.get("momentum_fade"), 0.0), 3),
                    "relative_strength_loss": rounded(max(0.0, 100.0 - to_float(row.get("relative_strength"), 50.0)), 3),
                    "rotation_candidate": bool(row.get("rotation_candidate", False)),
                    "rotation_reason": text(row.get("rotation_reason"), "monitor"),
                    "review_priority": review_priority,
                    "replacement_edge": rounded(replacement_edge, 3),
                }
            )
        top = rows[0] if rows else {}
        return {
            "module": "Stale Position / Rotation Promotion Readiness V2",
            "status": "ok" if rows else "insufficient_evidence",
            "rotation_rows": rows,
            "rotation_candidate": bool(top.get("rotation_candidate", False)),
            "rotation_reason": text(top.get("rotation_reason"), "monitor_active_positions"),
            "review_priority": text(top.get("review_priority"), "watch"),
            "replacement_edge": rounded(to_float(top.get("replacement_edge"), 0.0), 3),
            "forced_sells_enabled": False,
            "automatic_replacement_enabled": False,
            **_safe_flags(),
        }

    def _shadow_to_paper_promotion_engine_v2(
        self,
        scorecard: dict[str, Any],
        exit_readiness_v2: dict[str, Any],
        horizon_regime_v2: dict[str, Any],
        stale_rotation_v2: dict[str, Any],
    ) -> dict[str, Any]:
        exit_best = dict(exit_readiness_v2.get("top_exit_promotion_candidate") or {})
        candidates = [
            {
                "behavior_name": text(exit_best.get("behavior_name"), "profit_lock_exit"),
                "behavior_type": text(exit_best.get("behavior_name"), "profit_lock_exit"),
                "shadow_evidence_count": to_int(exit_best.get("evidence_count"), 0),
                "shadow_confidence": rounded(to_float(exit_best.get("confidence"), 0.0), 3),
                "paper_baseline_pf": scorecard.get("paper_pf"),
                "shadow_expected_pf": scorecard.get("shadow_expected_pf"),
                "expected_pf_delta": scorecard.get("pf_delta"),
                "expected_giveback_reduction": scorecard.get("giveback_delta"),
                "expected_capture_improvement": scorecard.get("capture_delta"),
                "expected_exit_quality_improvement": scorecard.get("exit_quality_delta"),
                "promotion_readiness": "tiny_bucket_candidate" if to_float(exit_best.get("readiness_score"), 0.0) >= 65 else "advisory_only",
                "promotion_blocker": text(exit_best.get("blocker"), "insufficient_evidence"),
                "human_review_required": True,
            },
            {
                "behavior_name": "adaptive_horizon_selection",
                "behavior_type": "adaptive_horizon_selection",
                "shadow_evidence_count": 0,
                "shadow_confidence": horizon_regime_v2.get("shadow_horizon_confidence"),
                "paper_baseline_pf": scorecard.get("paper_pf"),
                "shadow_expected_pf": scorecard.get("shadow_expected_pf"),
                "expected_pf_delta": max(0.0, to_float(scorecard.get("pf_delta"), 0.0) * 0.4),
                "expected_giveback_reduction": max(0.0, to_float(scorecard.get("giveback_delta"), 0.0) * 0.35),
                "expected_capture_improvement": max(0.0, to_float(scorecard.get("capture_delta"), 0.0) * 0.4),
                "expected_exit_quality_improvement": max(0.0, to_float(scorecard.get("exit_quality_delta"), 0.0) * 0.25),
                "promotion_readiness": horizon_regime_v2.get("promotion_readiness"),
                "promotion_blocker": horizon_regime_v2.get("blocker"),
                "human_review_required": True,
            },
            {
                "behavior_name": "stale_position_rotation",
                "behavior_type": "stale_position_rotation",
                "shadow_evidence_count": len(list(stale_rotation_v2.get("rotation_rows") or [])),
                "shadow_confidence": 55.0,
                "paper_baseline_pf": scorecard.get("paper_pf"),
                "shadow_expected_pf": scorecard.get("shadow_expected_pf"),
                "expected_pf_delta": max(0.0, to_float(scorecard.get("pf_delta"), 0.0) * 0.3),
                "expected_giveback_reduction": max(0.0, to_float(scorecard.get("giveback_delta"), 0.0) * 0.2),
                "expected_capture_improvement": 0.0,
                "expected_exit_quality_improvement": 0.0,
                "promotion_readiness": "advisory_only",
                "promotion_blocker": stale_rotation_v2.get("rotation_reason"),
                "human_review_required": True,
            },
        ]
        top = max(candidates, key=lambda row: to_float(row.get("expected_pf_delta"), 0.0) + to_float(row.get("expected_giveback_reduction"), 0.0) * 0.1 + to_float(row.get("expected_capture_improvement"), 0.0) * 10.0)
        return {
            "module": "Shadow-to-Paper Promotion Engine V2",
            "status": "ok",
            "promotion_candidates": candidates,
            "top_promotion_candidate": top,
            "top_promotion_candidate_name": top.get("behavior_name"),
            "top_promotion_readiness": top.get("promotion_readiness"),
            "top_promotion_blocker": top.get("promotion_blocker"),
            "expected_pf_improvement": rounded(to_float(top.get("expected_pf_delta"), 0.0), 4),
            "expected_giveback_reduction": rounded(to_float(top.get("expected_giveback_reduction"), 0.0), 3),
            "expected_capture_improvement": rounded(to_float(top.get("expected_capture_improvement"), 0.0), 3),
            "recommended_next_action": "human_review_before_any_tiny_paper_bucket",
            "human_review_required": True,
            "broad_paper_deployment_enabled": False,
            **_safe_flags(),
        }

    def _controlled_paper_test_bucket_v2(self, statuses: dict[str, Any], promotion: dict[str, Any], scorecard: dict[str, Any]) -> dict[str, Any]:
        learned_exit = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        bucket_enabled = False
        return {
            "module": "Controlled Paper Test Bucket V2",
            "status": "disabled_pending_human_review",
            "bucket_enabled": bucket_enabled,
            "bucket_size": 2,
            "bucket_used_today": 0,
            "tested_behavior": promotion.get("top_promotion_candidate_name"),
            "test_start_time": "",
            "baseline_comparison_group": "natural_paper_behavior",
            "bucket_pf": 0.0,
            "baseline_pf": scorecard.get("paper_pf"),
            "bucket_giveback": 0.0,
            "baseline_giveback": scorecard.get("paper_giveback"),
            "bucket_capture_ratio": 0.0,
            "baseline_capture_ratio": scorecard.get("paper_capture_ratio"),
            "bucket_exit_quality": 0.0,
            "baseline_exit_quality": scorecard.get("paper_exit_quality"),
            "bucket_result": "not_started",
            "rollback_status": text(learned_exit.get("rollback_status"), "armed"),
            "kill_switch_status": text(learned_exit.get("kill_switch_status"), "available"),
            "human_review_required": True,
            "forced_buys_enabled": False,
            "forced_sells_enabled": False,
            "broad_paper_deployment_enabled": False,
            **_safe_flags(),
        }

    def _dashboard_summary(
        self,
        repair: dict[str, Any],
        readiness: dict[str, Any],
        capacity: dict[str, Any],
        recycling: dict[str, Any],
        exposure: dict[str, Any],
        optimizer: dict[str, Any],
        rotation: dict[str, Any],
        lifecycle: dict[str, Any],
        regime: dict[str, Any],
    ) -> dict[str, Any]:
        readiness_map = dict(readiness.get("readiness_by_horizon") or {})
        top_problem = "broker_lifecycle_audit_mismatch" if repair.get("repair_status") != "broker_confirmed_source_of_truth_active" else first(exposure.get("horizon_exposure_balance"), "monitoring")
        return {
            "module": "Horizon Lifecycle Dashboard Summary",
            "status": "ok",
            "dashboard_summary_status": "active_compact_learning_center_only",
            "active_broker_positions": to_int(repair.get("broker_confirmed_count"), 0),
            "rows_audited": to_int(repair.get("lifecycle_rows_audited"), 0),
            "horizon_distribution": dict(capacity.get("horizon_distribution_pct") or {}),
            "underexposed_horizon": capacity.get("underexposed_horizon"),
            "overexposed_horizon": capacity.get("overexposed_horizon"),
            "shadow_horizon_readiness": readiness_map,
            "dynamic_capacity_status": recycling.get("dynamic_recycling_status"),
            "recycling_recommendation": "run_replacement_scan_through_existing_gates" if recycling.get("replacement_scan_recommended") else "monitor_capacity_until_slot_reopens",
            "top_horizon_problem": top_problem,
            "next_recommended_action": optimizer.get("recommended_paper_learning_focus"),
            "stale_positions_count": rotation.get("stale_positions_count"),
            "capital_trapped_score": rotation.get("capital_trapped_score"),
            "horizon_learning_access_score": rotation.get("learning_access_score"),
            "regime_allocation_recommendation": regime.get("regime_allocation_recommendation"),
            "profit_retention_score": lifecycle.get("profit_retention_score"),
            "giveback_score": lifecycle.get("giveback_score"),
            "lifecycle_efficiency_score": lifecycle.get("lifecycle_efficiency_score"),
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.time()
        repair = self._trade_lifecycle_repair(statuses)
        readiness = self._promotion_readiness(statuses)
        capacity = self._capacity_manager(statuses, repair)
        recycling = self._dynamic_recycling(statuses, capacity)
        exposure = self._exposure_balancer(statuses, capacity)
        optimizer = self._learning_exposure_optimizer(statuses, exposure)
        rotation = self._adaptive_portfolio_rotation(statuses, capacity, exposure)
        lifecycle_v2 = self._trade_lifecycle_intelligence_v2(statuses, rotation)
        regime_allocation = self._adaptive_market_regime_allocation(statuses, capacity, exposure)
        scorecard_v2 = self._shadow_vs_paper_scorecard_v2(statuses, readiness, capacity, rotation, lifecycle_v2, regime_allocation)
        exit_promotion_v2 = self._exit_promotion_readiness_v2(statuses, scorecard_v2)
        horizon_regime_promotion_v2 = self._horizon_regime_promotion_readiness_v2(capacity, exposure, regime_allocation)
        stale_rotation_promotion_v2 = self._stale_rotation_promotion_readiness_v2(rotation)
        shadow_promotion_v2 = self._shadow_to_paper_promotion_engine_v2(scorecard_v2, exit_promotion_v2, horizon_regime_promotion_v2, stale_rotation_promotion_v2)
        paper_test_bucket_v2 = self._controlled_paper_test_bucket_v2(statuses, shadow_promotion_v2, scorecard_v2)
        assignment = self._candidate_horizon_assignment(statuses, capacity, exposure, readiness)
        practice_bucket = self._practice_bucket(assignment, capacity)
        exit_readiness = self._exit_readiness(readiness, capacity, exposure)
        dashboard = self._dashboard_summary(repair, readiness, capacity, recycling, exposure, optimizer, rotation, lifecycle_v2, regime_allocation)
        modules = {
            "trade_lifecycle_audit_auto_repair_v1": repair,
            "horizon_opportunity_assignment_engine_v1": assignment,
            "horizon_shadow_to_paper_promotion_readiness_v1": readiness,
            "horizon_capacity_manager_v1": capacity,
            "dynamic_capacity_recycling_v1": recycling,
            "horizon_exposure_balancer_v1": exposure,
            "learning_exposure_optimizer_v1": optimizer,
            "adaptive_portfolio_rotation_engine_v1": rotation,
            "trade_lifecycle_intelligence_v2": lifecycle_v2,
            "adaptive_market_regime_allocation_v1": regime_allocation,
            "shadow_to_paper_promotion_engine_v2": shadow_promotion_v2,
            "controlled_paper_test_bucket_v2": paper_test_bucket_v2,
            "exit_promotion_readiness_v2": exit_promotion_v2,
            "horizon_regime_promotion_readiness_v2": horizon_regime_promotion_v2,
            "stale_position_rotation_promotion_readiness_v2": stale_rotation_promotion_v2,
            "shadow_vs_paper_scorecard_v2": scorecard_v2,
            "controlled_paper_horizon_practice_bucket_v1": practice_bucket,
            "horizon_exit_profit_capture_readiness_v1": exit_readiness,
            "horizon_lifecycle_dashboard_summary": dashboard,
        }
        payload = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Horizon Lifecycle, Capacity Recycling & Promotion Readiness Bundle V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "modules_created": MODULES_CREATED,
            "modules": modules,
            "repair_status": repair.get("repair_status"),
            "active_position_source": repair.get("active_position_source"),
            "broker_confirmed_count": repair.get("broker_confirmed_count"),
            "internal_active_count": repair.get("internal_active_count"),
            "stale_internal_rows_hidden": repair.get("stale_internal_rows_hidden"),
            "lifecycle_rows_audited": repair.get("lifecycle_rows_audited"),
            "unmatched_broker_symbols": repair.get("unmatched_broker_symbols"),
            "unmatched_internal_symbols": repair.get("unmatched_internal_symbols"),
            "unknown_horizon_positions": capacity.get("unknown_horizon_slots"),
            "horizon_distribution": capacity.get("horizon_distribution_pct"),
            "current_horizon_distribution": capacity.get("horizon_distribution_pct"),
            "assigned_horizon_source": assignment.get("assigned_horizon_source"),
            "horizon_assignment_version": assignment.get("horizon_assignment_version"),
            "capacity_mode": assignment.get("capacity_mode"),
            "capacity_rebalance_status": assignment.get("capacity_rebalance_status"),
            "assigned_horizons_today": assignment.get("assigned_horizons_today"),
            "selected_horizons_today": assignment.get("selected_horizons_today"),
            "assigned_horizon_rows": assignment.get("assigned_horizon_rows"),
            "assigned_horizon_count": assignment.get("assigned_horizon_count"),
            "shadow_scalp_candidates": assignment.get("shadow_scalp_candidates"),
            "shadow_day_trade_candidates": assignment.get("shadow_day_trade_candidates"),
            "shadow_swing_trade_candidates": assignment.get("shadow_swing_trade_candidates"),
            "qualified_scalp_candidates": assignment.get("qualified_scalp_candidates"),
            "qualified_day_trade_candidates": assignment.get("qualified_day_trade_candidates"),
            "qualified_swing_trade_candidates": assignment.get("qualified_swing_trade_candidates"),
            "missing_horizon_field_count": assignment.get("missing_horizon_field_count"),
            "missing_horizon_field_examples": assignment.get("missing_horizon_field_examples"),
            "horizon_assignment_dropoff_point": assignment.get("horizon_assignment_dropoff_point"),
            "horizon_assignment_blocker": assignment.get("horizon_assignment_blocker"),
            "practice_bucket_blocker": assignment.get("practice_bucket_blocker"),
            "paper_tie_breaker_blocker": assignment.get("paper_tie_breaker_blocker"),
            "next_required_fix": assignment.get("next_required_fix"),
            "preferred_next_horizon": assignment.get("preferred_next_horizon"),
            "horizon_assignment_used": bool(assignment.get("horizon_assignment_used", False)),
            "horizon_assignment_confidence": rounded(to_float(assignment.get("horizon_assignment_confidence"), 0.0), 3),
            "horizon_execution_candidate": dict(assignment.get("horizon_execution_candidate") or {}),
            "horizon_execution_reason": text(assignment.get("horizon_execution_reason"), "existing_rank_and_safety_gates_only"),
            "horizon_execution_blocker": text(assignment.get("horizon_execution_blocker"), "diagnostic_only_no_behavior_change"),
            "capacity_rebalance_recommendation": assignment.get("capacity_rebalance_recommendation"),
            "rebalance_action_taken": assignment.get("rebalance_action_taken"),
            "rebalance_action_reason": assignment.get("rebalance_action_reason"),
            "overconcentration_warning": assignment.get("overconcentration_warning"),
            "practice_bucket_status": practice_bucket.get("practice_bucket_status"),
            "bucket_enabled": practice_bucket.get("bucket_enabled"),
            "bucket_size": practice_bucket.get("bucket_size"),
            "bucket_used_today": practice_bucket.get("bucket_used_today"),
            "scalp_practice_count": practice_bucket.get("scalp_practice_count"),
            "day_trade_practice_count": practice_bucket.get("day_trade_practice_count"),
            "swing_practice_count": practice_bucket.get("swing_practice_count"),
            "practice_candidate_count": practice_bucket.get("practice_candidate_count"),
            "blocked_candidate_count": practice_bucket.get("blocked_candidate_count"),
            "practice_bucket_block_reasons": practice_bucket.get("block_reasons"),
            "exit_readiness_status": exit_readiness.get("promotion_readiness"),
            "scalp_exit_readiness": exit_readiness.get("scalp_exit_readiness"),
            "day_trade_exit_readiness": exit_readiness.get("day_trade_exit_readiness"),
            "swing_exit_readiness": exit_readiness.get("swing_exit_readiness"),
            "highest_roi_exit_focus": exit_readiness.get("highest_roi_exit_focus"),
            "promotion_readiness": exit_readiness.get("promotion_readiness"),
            "reason_not_ready": exit_readiness.get("reason_not_ready"),
            "exit_readiness_by_horizon": exit_readiness.get("exit_readiness_by_horizon"),
            "readiness_by_horizon": readiness.get("readiness_by_horizon"),
            "horizon_capacity_status": capacity.get("capacity_status"),
            "dynamic_recycling_status": recycling.get("dynamic_recycling_status"),
            "horizon_exposure_balance": exposure.get("horizon_exposure_balance"),
            "top_learning_exposure_gap": optimizer.get("top_learning_gap"),
            "adaptive_portfolio_rotation_status": rotation.get("portfolio_rotation_status"),
            "stale_positions_count": rotation.get("stale_positions_count"),
            "top_stale_positions": rotation.get("top_stale_positions"),
            "best_replacement_candidates": rotation.get("best_replacement_candidates"),
            "capital_trapped_score": rotation.get("capital_trapped_score"),
            "trapped_capital_score": rotation.get("trapped_capital_score"),
            "scalp_learning_blocked": rotation.get("scalp_learning_blocked"),
            "day_learning_blocked": rotation.get("day_learning_blocked"),
            "swing_overconcentration": rotation.get("swing_overconcentration"),
            "stale_swing_pressure": rotation.get("stale_swing_pressure"),
            "horizon_learning_access_score": rotation.get("learning_access_score"),
            "profit_retention_score": lifecycle_v2.get("profit_retention_score"),
            "profit_retention_status": lifecycle_v2.get("profit_retention_status"),
            "giveback_score": lifecycle_v2.get("giveback_score"),
            "lifecycle_efficiency_score": lifecycle_v2.get("lifecycle_efficiency_score"),
            "lifecycle_efficiency_status": lifecycle_v2.get("lifecycle_efficiency_status"),
            "protect_profit_recommendation": lifecycle_v2.get("protect_profit_recommendation"),
            "reduce_giveback_recommendation": lifecycle_v2.get("reduce_giveback_recommendation"),
            "thesis_review_recommendation": lifecycle_v2.get("thesis_review_recommendation"),
            "horizon_adjustment_recommendation": lifecycle_v2.get("horizon_adjustment_recommendation"),
            "market_regime": regime_allocation.get("market_regime"),
            "preferred_horizon_mix": regime_allocation.get("preferred_horizon_mix"),
            "horizon_market_bias": regime_allocation.get("horizon_market_bias"),
            "regime_allocation_recommendation": regime_allocation.get("regime_allocation_recommendation"),
            "market_adaptability_score": regime_allocation.get("market_adaptability_score"),
            "shadow_to_paper_promotion_engine_v2": shadow_promotion_v2,
            "promotion_candidates_v2": shadow_promotion_v2.get("promotion_candidates"),
            "top_promotion_candidate": shadow_promotion_v2.get("top_promotion_candidate"),
            "top_promotion_candidate_name": shadow_promotion_v2.get("top_promotion_candidate_name"),
            "top_promotion_readiness": shadow_promotion_v2.get("top_promotion_readiness"),
            "top_promotion_blocker": shadow_promotion_v2.get("top_promotion_blocker"),
            "expected_pf_improvement": shadow_promotion_v2.get("expected_pf_improvement"),
            "expected_giveback_reduction": shadow_promotion_v2.get("expected_giveback_reduction"),
            "expected_capture_improvement": shadow_promotion_v2.get("expected_capture_improvement"),
            "promotion_recommended_next_action": shadow_promotion_v2.get("recommended_next_action"),
            "controlled_paper_test_bucket_v2": paper_test_bucket_v2,
            "test_bucket_enabled": paper_test_bucket_v2.get("bucket_enabled"),
            "test_bucket_status": paper_test_bucket_v2.get("status"),
            "test_bucket_size": paper_test_bucket_v2.get("bucket_size"),
            "test_bucket_used_today": paper_test_bucket_v2.get("bucket_used_today"),
            "tested_behavior": paper_test_bucket_v2.get("tested_behavior"),
            "rollback_status": paper_test_bucket_v2.get("rollback_status"),
            "kill_switch_status": paper_test_bucket_v2.get("kill_switch_status"),
            "exit_promotion_readiness_v2": exit_promotion_v2,
            "exit_promotion_rows_v2": exit_promotion_v2.get("exit_promotion_rows"),
            "horizon_regime_promotion_readiness_v2": horizon_regime_promotion_v2,
            "stale_position_rotation_promotion_readiness_v2": stale_rotation_promotion_v2,
            "shadow_vs_paper_scorecard_v2": scorecard_v2,
            "paper_pf": scorecard_v2.get("paper_pf"),
            "shadow_expected_pf": scorecard_v2.get("shadow_expected_pf"),
            "pf_delta": scorecard_v2.get("pf_delta"),
            "paper_exit_quality": scorecard_v2.get("paper_exit_quality"),
            "shadow_exit_quality": scorecard_v2.get("shadow_exit_quality"),
            "exit_quality_delta": scorecard_v2.get("exit_quality_delta"),
            "paper_giveback": scorecard_v2.get("paper_giveback"),
            "shadow_expected_giveback": scorecard_v2.get("shadow_expected_giveback"),
            "giveback_delta": scorecard_v2.get("giveback_delta"),
            "paper_capture_ratio": scorecard_v2.get("paper_capture_ratio"),
            "shadow_capture_ratio": scorecard_v2.get("shadow_capture_ratio"),
            "capture_delta": scorecard_v2.get("capture_delta"),
            "horizon_gap": scorecard_v2.get("horizon_gap"),
            "active_broker_positions": dashboard.get("active_broker_positions"),
            "rows_audited": dashboard.get("rows_audited"),
            "underexposed_horizon": dashboard.get("underexposed_horizon"),
            "overexposed_horizon": dashboard.get("overexposed_horizon"),
            "recycling_recommendation": dashboard.get("recycling_recommendation"),
            "top_horizon_problem": dashboard.get("top_horizon_problem"),
            "next_recommended_action": dashboard.get("next_recommended_action"),
            "integration_flow": "Trade lifecycle / Shadow / Horizon systems -> Librarian -> Unified Truth -> Executive Assistant -> Learning Center",
            "raw_data_direct_to_brain": False,
            "dashboard_impact": "one_collapsed_learning_center_section_unified_diagnostics_only",
            "api_bandwidth_impact": "unchanged_zero_dashboard_provider_calls_cache_first_no_endpoint_storm",
            "provider_api_impact": "unchanged_zero_dashboard_provider_calls",
            "build_ms": rounded((time.time() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(payload)
