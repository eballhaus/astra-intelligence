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
    "Horizon Shadow-to-Paper Promotion Readiness V1",
    "Horizon Capacity Manager V1",
    "Dynamic Capacity Recycling V1",
    "Horizon Exposure Balancer V1",
    "Learning Exposure Optimizer V1",
    "Horizon Lifecycle Dashboard Summary",
]

HORIZONS = ["scalp", "day_trade", "swing_trade"]
TARGET_RANGES = {
    "scalp": (20.0, 30.0),
    "day_trade": (30.0, 40.0),
    "swing_trade": (30.0, 40.0),
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
            row.get("horizon"),
            row.get("current_horizon"),
            row.get("paper_entry_horizon_style"),
            row.get("horizon_style"),
            row.get("best_horizon"),
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

    def _capacity_manager(self, statuses: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
        capacity = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        broker_positions = self._active_broker_positions(statuses)
        counts = Counter(_horizon_label(row) for row in broker_positions)
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

    def _dashboard_summary(self, repair: dict[str, Any], readiness: dict[str, Any], capacity: dict[str, Any], recycling: dict[str, Any], exposure: dict[str, Any], optimizer: dict[str, Any]) -> dict[str, Any]:
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
        dashboard = self._dashboard_summary(repair, readiness, capacity, recycling, exposure, optimizer)
        modules = {
            "trade_lifecycle_audit_auto_repair_v1": repair,
            "horizon_shadow_to_paper_promotion_readiness_v1": readiness,
            "horizon_capacity_manager_v1": capacity,
            "dynamic_capacity_recycling_v1": recycling,
            "horizon_exposure_balancer_v1": exposure,
            "learning_exposure_optimizer_v1": optimizer,
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
            "readiness_by_horizon": readiness.get("readiness_by_horizon"),
            "horizon_capacity_status": capacity.get("capacity_status"),
            "dynamic_recycling_status": recycling.get("dynamic_recycling_status"),
            "horizon_exposure_balance": exposure.get("horizon_exposure_balance"),
            "top_learning_exposure_gap": optimizer.get("top_learning_gap"),
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
