from __future__ import annotations

import time
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
    "Horizon Intelligence Maturation Suite V1",
    "Exit Quality Optimization V1",
    "Profit Capture & Giveback Reduction V1",
    "Executive Summary Engine V1",
    "Learning Center Consolidation V1",
    "Duplicate Intelligence Detection V1",
    "Root Cause Engine V1",
    "Intelligence Throughput Meter V1",
    "Intelligence Saturation Meter V1",
    "Dynamic Universe Manager V1",
]


SAFE_ACTIONS = [
    "hold",
    "protect_profit",
    "exit_review",
    "promote_horizon",
    "demote_horizon",
    "continue_collecting_evidence",
]


def _safe_flags(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
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
        payload.get("historical_confidence"),
        payload.get("horizon_confidence"),
        payload.get("exit_confidence"),
        payload.get("ranking_confidence_score"),
        payload.get("condition_confidence_score"),
    ]
    nums = [clamp(v) for v in vals if v is not None]
    return rounded(sum(nums) / len(nums), 3) if nums else default


def _evidence(payload: dict[str, Any]) -> int:
    return max(
        to_int(payload.get("evidence_count"), 0),
        to_int(payload.get("closed_trade_count"), 0),
        to_int(payload.get("canonical_closed_trade_count"), 0),
        to_int(payload.get("weighted_evidence_count"), 0),
        to_int(payload.get("shadow_opportunities"), 0),
        to_int(payload.get("learning_events"), 0),
        to_int(payload.get("virtual_paths"), 0),
        to_int(payload.get("compressed_lessons"), 0),
        to_int(payload.get("compressed_lessons_created"), 0),
    )


def _status(score: float) -> str:
    if score >= 75:
        return "healthy"
    if score >= 50:
        return "maturing"
    if score > 0:
        return "warming_up"
    return "insufficient_evidence"


def _avg(vals: list[float], default: float = 0.0) -> float:
    clean = [v for v in vals if v is not None]
    return rounded(sum(clean) / len(clean), 3) if clean else default


def _brief(parts: list[Any]) -> str:
    clean = [str(part).strip().replace("_", " ") for part in parts if str(part or "").strip()]
    return "; ".join(clean[:6]) or "insufficient cached context"


class AstraTargetedMaturityProfitCaptureOptimizationBundleV1(CachedDiagnosticModule):
    """Advisory maturity layer for horizon, exit, profit-capture, and clarity.

    This module only composes cached diagnostics. It does not alter rankings,
    entries, exits, sizing, allocation, broker state, thresholds, or paper orders.
    """

    module_name = "astra_targeted_maturity_profit_capture_optimization_bundle_v1"
    mode = "shadow_only_targeted_maturity_profit_capture_optimization"

    def _horizon_maturation(self, statuses: dict[str, Any]) -> dict[str, Any]:
        horizon = status_value(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        capacity = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        foundation = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        rows = list(foundation.get("horizon_exit_candidate_rows") or [])[:20]
        unknown = to_int(capacity.get("unknown_horizon_positions"), to_int(foundation.get("unknown_horizon_positions"), 0))
        confidence = _avg([_confidence(p) for p in (horizon, capacity, foundation, lifecycle) if p], 0.0)
        drift_count = sum(1 for row in rows if text(row.get("horizon_drift_status"), "stable") not in {"stable", "none"})
        pf_delta = rounded(max(0.0, (70.0 - confidence) * 0.002), 4)
        return {
            "module": "Horizon Intelligence Maturation Suite V1",
            "status": "ok" if any((horizon, capacity, foundation, lifecycle)) else "insufficient_evidence",
            "horizon_status": _status(confidence),
            "positions_reviewed": len(rows),
            "unknown_horizon_positions": unknown,
            "horizon_drift_count": drift_count,
            "allowed_horizon_actions": SAFE_ACTIONS,
            "recommended_horizon_action": first(horizon.get("next_recommended_test"), "continue_collecting_evidence"),
            "current_vs_dynamic_horizon_comparison": "shadow_comparison_active_advisory_only",
            "pf_delta_estimate": pf_delta,
            "capture_improvement_estimate": rounded(pf_delta * 18.0, 3),
            "giveback_reduction_estimate": rounded(pf_delta * 12.0, 3),
            "exit_quality_improvement_estimate": rounded(pf_delta * 15.0, 3),
            "sample_positions": [
                {
                    "symbol": text(row.get("symbol"), "unknown"),
                    "original_horizon": text(row.get("original_horizon") or row.get("horizon"), "unknown"),
                    "current_horizon": text(row.get("current_horizon") or row.get("horizon"), "unknown"),
                    "horizon_confidence": clamp(first(row.get("confidence"), confidence)),
                    "horizon_age": text(row.get("elapsed_hold_duration") or row.get("horizon_age"), "unknown"),
                    "expected_hold_window": text(row.get("expected_hold_duration") or row.get("expected_hold_window"), "unknown"),
                    "horizon_drift_status": text(row.get("horizon_drift_status"), "stable"),
                    "recommended_horizon_action": text(row.get("recommended_horizon_action") or row.get("reason"), "continue_collecting_evidence"),
                }
                for row in rows[:8]
            ],
            **_safe_flags(),
        }

    def _exit_quality(self, statuses: dict[str, Any]) -> dict[str, Any]:
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        optimization = status_value(statuses, "profit_optimization_context_intelligence_suite_v1")
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        confidence = _avg([_confidence(p) for p in (profit, optimization, learned, lifecycle) if p], 0.0)
        exit_quality = clamp(first(optimization.get("exit_quality"), profit.get("exit_quality"), learned.get("policy_confidence"), confidence))
        review_candidates = max(
            to_int(learned.get("learned_exit_candidates_today"), 0),
            to_int(profit.get("exit_review_candidates"), 0),
            1 if exit_quality < 70 and confidence > 0 else 0,
        )
        return {
            "module": "Exit Quality Optimization V1",
            "status": "ok" if any((profit, optimization, learned, lifecycle)) else "insufficient_evidence",
            "exit_quality_status": _status(exit_quality),
            "best_virtual_exit": text(first(profit.get("best_shadow_exit_policy"), learned.get("best_policy"), "profit_lock_exit")),
            "natural_exit": "preserved_default",
            "missed_exit": bool(review_candidates),
            "late_exit": bool(exit_quality < 60),
            "continuation_failure": text(first(profit.get("strongest_failure_signal"), "monitoring")),
            "profit_decay": text(first(profit.get("peak_decay_status"), "monitoring")),
            "exit_confidence": rounded(confidence, 3),
            "exit_review_candidate": bool(review_candidates),
            "review_only_exit_candidates": review_candidates,
            "sell_orders_allowed": False,
            **_safe_flags(),
        }

    def _profit_capture(self, statuses: dict[str, Any]) -> dict[str, Any]:
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        protection = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        foundation = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        capture = clamp(first(profit.get("capture_ratio"), profit.get("average_capture_ratio"), protection.get("profit_lock_readiness"), 52.0))
        giveback = clamp(first(profit.get("average_giveback_pct"), protection.get("giveback_risk_score"), 14.0))
        biggest_symbol = text(first(profit.get("biggest_giveback_symbol"), lifecycle.get("highest_giveback_symbol"), foundation.get("biggest_profit_leak_symbol"), "unknown"))
        estimated_pf = rounded(max(0.0, (70.0 - capture) * 0.003 + giveback * 0.001), 4)
        return {
            "module": "Profit Capture & Giveback Reduction V1",
            "status": "ok" if any((profit, protection, foundation, lifecycle)) else "insufficient_evidence",
            "profit_capture_status": _status(capture),
            "mfe": first(profit.get("average_mfe"), lifecycle.get("average_mfe"), "monitoring"),
            "mae": first(profit.get("average_mae"), lifecycle.get("average_mae"), "monitoring"),
            "current_profit": first(foundation.get("current_profit"), "monitoring"),
            "realized_profit": first(profit.get("realized_profit"), "monitoring"),
            "giveback": rounded(giveback, 3),
            "capture_ratio": rounded(capture, 3),
            "peak_decay": text(first(profit.get("peak_decay_status"), protection.get("peak_decay_risk"), "monitoring")),
            "profit_lock_candidate": bool(capture < 65 or giveback > 8),
            "protect_profit_confidence": rounded(_confidence(protection, _confidence(profit, 55.0)), 3),
            "biggest_giveback_symbol": biggest_symbol,
            "biggest_capture_leak": text(first(profit.get("biggest_capture_leak"), "exit_intelligence_profit_capture")),
            "best_profit_protection_candidate": text(first(protection.get("strongest_profit_protection_pattern"), biggest_symbol)),
            "estimated_pf_gain": estimated_pf,
            **_safe_flags(),
        }

    def _executive_summary(self, statuses: dict[str, Any], horizon: dict[str, Any], exit_quality: dict[str, Any], profit_capture: dict[str, Any]) -> dict[str, Any]:
        unified = status_value(statuses, "unified_learning_diagnostics_v1")
        perf = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        final = status_value(statuses, "astra_final_intelligence_maturation_bundle_v1")
        pf = first(unified.get("profit_factor"), perf.get("paper_profit_factor_verified"), perf.get("canonical_profit_factor"), "n/a")
        win_rate = first(unified.get("win_rate"), perf.get("paper_win_rate"), "n/a")
        buy_purity = first(unified.get("buy_purity"), ranking.get("promotion_accuracy"), "n/a")
        top_weakness = text(first(final.get("top_weakness"), "profit_capture_exit_quality"))
        top_opportunity = text(first(final.get("top_opportunity"), "reduce giveback and improve exit review quality"))
        expected_pf = max(to_float(profit_capture.get("estimated_pf_gain"), 0.0), to_float(final.get("expected_pf_improvement"), 0.0))
        return {
            "module": "Executive Summary Engine V1",
            "status": "ok",
            "executive_summary_status": "active_compact_human_readable",
            "pf": pf,
            "win_rate": win_rate,
            "buy_purity": buy_purity,
            "exit_quality": exit_quality.get("exit_quality_status"),
            "capture_ratio": profit_capture.get("capture_ratio"),
            "avg_giveback": profit_capture.get("giveback"),
            "system_health": text(first(final.get("health_monitoring_status"), "monitoring")),
            "top_weakness": top_weakness,
            "top_opportunity": top_opportunity,
            "top_root_cause": "exit_intelligence_profit_capture",
            "highest_roi_improvement": "profit_capture_and_horizon_exit_review",
            "expected_pf_improvement": rounded(expected_pf, 4),
            "recommended_next_focus": "Keep stock selection intact; mature horizon classification, exit review, and profit capture diagnostics.",
            "summary": _brief([f"PF {pf}", f"buy purity {buy_purity}", top_weakness, top_opportunity]),
            **_safe_flags(),
        }

    def _learning_center_consolidation(self) -> dict[str, Any]:
        departments = [
            "Executive Summary",
            "Trading & Profit Capture",
            "Horizon & Exit Intelligence",
            "Historical Intelligence",
            "Satellites & Market Context",
            "Research & Shadow Lab",
            "Portfolio & Risk",
            "System Health & Governance",
            "Deep Diagnostics",
        ]
        return {
            "module": "Learning Center Consolidation V1",
            "status": "ok",
            "learning_center_consolidation_status": "one_collapsed_section_added_existing_diagnostics_preserved",
            "departments": departments,
            "existing_diagnostics_removed": False,
            "collapsed_by_default": True,
            "initial_learning_tab_endpoint_count": 1,
            "new_top_level_dashboard_panels": 0,
            **_safe_flags(),
        }

    def _duplicate_detection(self, exit_quality: dict[str, Any], profit_capture: dict[str, Any], horizon: dict[str, Any]) -> dict[str, Any]:
        findings = []
        if exit_quality.get("late_exit") or exit_quality.get("exit_review_candidate"):
            findings.append("exit_quality_weak")
        if to_float(profit_capture.get("giveback"), 0.0) > 8:
            findings.append("giveback_high")
        if profit_capture.get("profit_lock_candidate"):
            findings.append("profit_lock_needed")
        if to_int(horizon.get("horizon_drift_count"), 0) > 0:
            findings.append("horizon_drift")
        duplicate_count = len(findings)
        master_issue = "Exit Intelligence / Profit Capture" if duplicate_count >= 2 else first(findings, "monitoring")
        return {
            "module": "Duplicate Intelligence Detection V1",
            "status": "ok",
            "duplicate_detection_status": "active",
            "duplicate_findings_detected": duplicate_count,
            "merged_findings": 1 if duplicate_count >= 2 else 0,
            "master_issue": master_issue,
            "systems_contributing": findings,
            "confidence": rounded(min(95.0, 55.0 + duplicate_count * 10.0), 3),
            "priority": "high" if master_issue == "Exit Intelligence / Profit Capture" else "medium",
            **_safe_flags(),
        }

    def _root_cause(self, duplicate: dict[str, Any], profit_capture: dict[str, Any], horizon: dict[str, Any]) -> dict[str, Any]:
        top = "exit_intelligence_profit_capture"
        if to_int(horizon.get("horizon_drift_count"), 0) > 0:
            top = "horizon_management_drift"
        if to_float(profit_capture.get("giveback"), 0.0) > 12:
            top = "peak_profit_giveback"
        return {
            "module": "Root Cause Engine V1",
            "status": "ok",
            "root_cause_status": "active_advisory_only",
            "top_root_cause": top,
            "affected_metrics": ["exit_quality", "capture_ratio", "avg_giveback", "capital_efficiency", "hold_quality"],
            "confidence": rounded(first(duplicate.get("confidence"), 60.0), 3),
            "highest_roi_fix": "review-only profit protection and dynamic horizon diagnostics; no execution changes",
            "symptoms_consolidated": duplicate.get("systems_contributing", []),
            **_safe_flags(),
        }

    def _throughput_meter(self, statuses: dict[str, Any]) -> dict[str, Any]:
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        satellite = status_value(statuses, "astra_satellite_network_v1")
        tier3 = status_value(statuses, "astra_tier3_historical_satellite_shadow_acceleration_v1")
        tier2a = status_value(statuses, "astra_tier2a_librarian_executive_truth_layer_v1")
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        symbols = max(to_int(satellite.get("symbols_observed"), 0), to_int(shadow.get("shadow_opportunities"), 0), 0)
        packets = max(to_int(satellite.get("compressed_lessons_count"), 0), to_int(tier3.get("compressed_lessons_created"), 0), to_int(tier2a.get("lessons_organized"), 0))
        efficiency = rounded(packets / max(1, symbols) * 100.0 if symbols else _confidence(tier2a, 50.0), 3)
        return {
            "module": "Intelligence Throughput Meter V1",
            "status": "ok" if any((shadow, satellite, tier3, tier2a)) else "insufficient_evidence",
            "throughput_meter_status": "active_cache_first" if any((shadow, satellite, tier3, tier2a)) else "insufficient_evidence",
            "symbols_observed": symbols,
            "symbols_deeply_analyzed": max(0, int(symbols * 0.35)),
            "satellites_active": to_int(satellite.get("satellites_registered"), 0),
            "satellite_intelligence_packets": to_int(satellite.get("compressed_lessons_count"), 0),
            "historical_memories_used": to_int(tier3.get("compressed_lessons_created"), 0),
            "historical_memories_created": to_int(tier3.get("compressed_lessons_created"), 0),
            "catalysts_analyzed": max(to_int(catalyst.get("evidence_count"), 0), to_int(catalyst.get("recommendation_count"), 0)),
            "shadow_experiments": to_int(shadow.get("learning_events"), 0),
            "virtual_simulations": to_int(shadow.get("virtual_paths"), 0),
            "compressed_lessons": packets,
            "master_truths_created": to_int(tier2a.get("master_truths_created"), 0),
            "executive_insights_delivered": len(tier2a.get("top_5_insights") or []),
            "brain_packets_delivered": packets,
            "intelligence_efficiency_ratio": efficiency,
            **_safe_flags(),
        }

    def _saturation_meter(self, statuses: dict[str, Any], throughput: dict[str, Any]) -> dict[str, Any]:
        foundation = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        resource = status_value(statuses, "astra_resource_manager_v1")
        compression_load = clamp(to_float(throughput.get("compressed_lessons"), 0.0) / max(1.0, to_float(throughput.get("symbols_observed"), 1.0)) * 100.0)
        storage_pressure = clamp(first(resource.get("storage_pressure_score"), foundation.get("storage_pressure_score"), 25.0))
        memory_pressure = clamp(first(resource.get("memory_pressure_score"), foundation.get("memory_pressure_score"), 25.0))
        dashboard_pressure = 5.0
        saturation = rounded((compression_load * 0.35 + storage_pressure * 0.25 + memory_pressure * 0.25 + dashboard_pressure * 0.15), 3)
        return {
            "module": "Intelligence Saturation Meter V1",
            "status": "ok",
            "saturation_meter_status": _status(100.0 - saturation),
            "collection_load": rounded(clamp(to_float(throughput.get("symbols_observed"), 0.0) / 500.0 * 100.0), 3),
            "compression_load": rounded(compression_load, 3),
            "validation_load": rounded(clamp(to_float(throughput.get("shadow_experiments"), 0.0) / 1000.0 * 100.0), 3),
            "librarian_load": rounded(clamp(to_float(throughput.get("master_truths_created"), 0.0) / 50.0 * 100.0), 3),
            "executive_assistant_load": rounded(clamp(to_float(throughput.get("executive_insights_delivered"), 0.0) / 20.0 * 100.0), 3),
            "brain_load": rounded(clamp(to_float(throughput.get("brain_packets_delivered"), 0.0) / 500.0 * 100.0), 3),
            "memory_pressure": rounded(memory_pressure, 3),
            "storage_pressure": rounded(storage_pressure, 3),
            "dashboard_pressure": dashboard_pressure,
            "saturation_percentage": saturation,
            "safe_expansion_capacity": rounded(max(0.0, 100.0 - saturation), 3),
            "expand_data_yes_no": "yes" if saturation < 65 else "no",
            "improve_quality_yes_no": "yes" if saturation >= 45 else "monitor",
            "recommended_next_capacity": "gradual_quality_first_expansion" if saturation < 65 else "compress_before_expansion",
            **_safe_flags(),
        }

    def _dynamic_universe(self, statuses: dict[str, Any], saturation: dict[str, Any]) -> dict[str, Any]:
        broad = status_value(statuses, "broad_universe_intake_promotion")
        current = max(to_int(broad.get("current_universe_size"), 0), to_int(broad.get("symbols_reviewed"), 0), 250)
        safe_capacity = to_float(saturation.get("safe_expansion_capacity"), 0.0)
        next_target = current if safe_capacity < 25 else min(350, max(current + 50, 350))
        mature_low = 750
        mature_high = 1000
        return {
            "module": "Dynamic Universe Manager V1",
            "status": "ok",
            "dynamic_universe_status": "recommendation_only_no_auto_expansion",
            "categories_tracked": ["large_caps", "mid_caps", "small_caps", "ETFs", "indexes", "crypto_shadow_only", "fast_movers", "high_momentum_names", "event_driven_names", "sector_leaders"],
            "current_universe": current,
            "next_safe_target": next_target,
            "mature_target": "750-1000 curated assets",
            "mature_target_low": mature_low,
            "mature_target_high": mature_high,
            "learning_roi": "positive_if_cache_first_and_gradual",
            "api_pressure": "unchanged_dashboard_zero_provider_calls",
            "bandwidth_pressure": text(saturation.get("recommended_next_capacity"), "monitor"),
            "saturation_pressure": to_float(saturation.get("saturation_percentage"), 0.0),
            "recommendation": "expand gradually only through governed cached intake; do not expand trading automatically",
            "auto_expand_trading": False,
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.time()
        horizon = self._horizon_maturation(statuses)
        exit_quality = self._exit_quality(statuses)
        profit_capture = self._profit_capture(statuses)
        executive = self._executive_summary(statuses, horizon, exit_quality, profit_capture)
        consolidation = self._learning_center_consolidation()
        duplicate = self._duplicate_detection(exit_quality, profit_capture, horizon)
        root = self._root_cause(duplicate, profit_capture, horizon)
        throughput = self._throughput_meter(statuses)
        saturation = self._saturation_meter(statuses, throughput)
        universe = self._dynamic_universe(statuses, saturation)
        modules = {
            "horizon_intelligence_maturation_suite_v1": horizon,
            "exit_quality_optimization_v1": exit_quality,
            "profit_capture_giveback_reduction_v1": profit_capture,
            "executive_summary_engine_v1": executive,
            "learning_center_consolidation_v1": consolidation,
            "duplicate_intelligence_detection_v1": duplicate,
            "root_cause_engine_v1": root,
            "intelligence_throughput_meter_v1": throughput,
            "intelligence_saturation_meter_v1": saturation,
            "dynamic_universe_manager_v1": universe,
        }
        status = "ok" if any(m.get("status") == "ok" for m in modules.values()) else "insufficient_evidence"
        payload = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Targeted Maturity & Profit-Capture Optimization Bundle V1",
            "status": status,
            "mode": self.mode,
            "generated_at": now_iso(),
            "modules_created": MODULES_CREATED,
            "modules": modules,
            "horizon_status": horizon.get("horizon_status"),
            "exit_quality_status": exit_quality.get("exit_quality_status"),
            "profit_capture_status": profit_capture.get("profit_capture_status"),
            "executive_summary_status": executive.get("executive_summary_status"),
            "learning_center_consolidation_status": consolidation.get("learning_center_consolidation_status"),
            "duplicate_detection_status": duplicate.get("duplicate_detection_status"),
            "root_cause_status": root.get("root_cause_status"),
            "throughput_meter_status": throughput.get("throughput_meter_status"),
            "saturation_meter_status": saturation.get("saturation_meter_status"),
            "dynamic_universe_status": universe.get("dynamic_universe_status"),
            "top_root_cause": root.get("top_root_cause"),
            "duplicate_findings_detected": duplicate.get("duplicate_findings_detected"),
            "merged_findings": duplicate.get("merged_findings"),
            "biggest_giveback_symbol": profit_capture.get("biggest_giveback_symbol"),
            "biggest_capture_leak": profit_capture.get("biggest_capture_leak"),
            "best_profit_protection_candidate": profit_capture.get("best_profit_protection_candidate"),
            "expected_pf_improvement": executive.get("expected_pf_improvement"),
            "dynamic_universe_recommendation": universe.get("recommendation"),
            "current_universe": universe.get("current_universe"),
            "next_safe_universe_target": universe.get("next_safe_target"),
            "mature_universe_target": universe.get("mature_target"),
            "intelligence_efficiency_ratio": throughput.get("intelligence_efficiency_ratio"),
            "saturation_percentage": saturation.get("saturation_percentage"),
            "safe_expansion_capacity": saturation.get("safe_expansion_capacity"),
            "executive_summary": executive.get("summary"),
            "recommended_next_focus": executive.get("recommended_next_focus"),
            "integration_flow": "Satellites/Historical/Shadow -> Librarian -> Unified Truth -> Executive Assistant -> Astra Brain",
            "raw_data_direct_to_brain": False,
            "dashboard_impact": "one_collapsed_learning_center_section_unified_diagnostics_only",
            "api_bandwidth_impact": "unchanged_zero_dashboard_provider_calls_cache_first_no_endpoint_storm",
            "provider_api_impact": "unchanged_zero_dashboard_provider_calls",
            "build_ms": rounded((time.time() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(payload)
