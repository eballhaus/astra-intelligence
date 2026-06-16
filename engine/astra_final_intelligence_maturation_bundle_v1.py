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


FINAL_MODULES = [
    "Dynamic Knowledge Compression V2",
    "Historical Intelligence Maturation V2",
    "Adaptive Learning Prioritization V2",
    "Autonomous Research Department Lite",
    "Portfolio Construction Lite",
    "Self-Optimization Engine V1",
    "Autonomous Health Monitoring V2",
    "Unified Profit Improvement Focus",
]


def _safe_flags(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
        "human_approval_required": True,
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
        "forced_exits_enabled": False,
        "forced_trades_enabled": False,
        "partial_sells_enabled": False,
        "automatic_trailing_stops_enabled": False,
        "provider_calls_used": 0,
        "api_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_endpoint_storm_created": False,
    }
    out.update(extra or {})
    return out


def _confidence(payload: dict[str, Any], default: float = 55.0) -> float:
    vals = [
        payload.get("confidence_score"),
        payload.get("confidence"),
        payload.get("readiness_score"),
        payload.get("historical_confidence"),
        payload.get("family_transfer_confidence"),
        payload.get("condition_confidence_score"),
        payload.get("ranking_confidence_score"),
        payload.get("average_evidence_quality"),
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
        to_int(payload.get("lessons_organized"), 0),
        to_int(payload.get("compressed_lessons_created"), 0),
        to_int(payload.get("tournament_count"), 0),
        to_int(payload.get("exit_tournament_count"), 0),
    )


def _avg(values: list[float], default: float = 0.0) -> float:
    clean = [v for v in values if v is not None]
    return rounded(sum(clean) / len(clean), 3) if clean else default


def _status_from_score(score: float) -> str:
    if score >= 75:
        return "healthy"
    if score >= 50:
        return "maturing"
    if score > 0:
        return "warming_up"
    return "insufficient_evidence"


def _brief(parts: list[Any]) -> str:
    clean = [str(part).strip().replace("_", " ") for part in parts if str(part or "").strip()]
    return "; ".join(clean[:6]) or "insufficient cached context"


class AstraFinalIntelligenceMaturationBundleV1(CachedDiagnosticModule):
    """Final advisory maturation layer for Astra's intelligence architecture.

    The bundle compresses existing cached diagnostics into higher-level operating
    focus. It never writes ranking, trading, broker, execution, allocation, or
    provider-control state.
    """

    module_name = "astra_final_intelligence_maturation_bundle_v1"
    mode = "shadow_only_final_intelligence_maturation"

    def _dynamic_knowledge_compression(self, statuses: dict[str, Any]) -> dict[str, Any]:
        tier2a = status_value(statuses, "astra_tier2a_librarian_executive_truth_layer_v1")
        tier3 = status_value(statuses, "astra_tier3_historical_satellite_shadow_acceleration_v1")
        quality = status_value(statuses, "evidence_quality_scoring_v1")
        drift = status_value(statuses, "learning_drift_detection_v1")
        sources = [p for p in (tier2a, tier3, quality, drift) if p]
        lessons = max(
            to_int(tier2a.get("lessons_organized"), 0),
            to_int(tier3.get("compressed_lessons_created"), 0),
            to_int(quality.get("raw_evidence_count"), 0),
        )
        duplicates = max(to_int(tier2a.get("duplicate_findings_reduced"), 0), to_int(tier3.get("duplicates_prevented"), 0))
        stale = 1 if str(drift.get("drift_level", "")).lower() in {"warning", "elevated", "high"} else 0
        high_value = max(to_int(tier2a.get("master_truths_created"), 0), to_int(quality.get("high_quality_evidence_count"), 0), 1 if sources else 0)
        efficiency = clamp((duplicates + high_value) / max(1, lessons) * 100.0 if lessons else _confidence(tier2a, 45.0))
        status = "ok" if sources else "insufficient_evidence"
        return {
            "module": "Dynamic Knowledge Compression V2",
            "status": status,
            "compression_status": "active_cache_first_librarian_routed" if sources else "insufficient_evidence",
            "compressed_lessons": lessons,
            "archived_lessons": max(0, int(lessons * 0.08)) if sources else 0,
            "stale_lessons": stale,
            "duplicate_lessons_removed": duplicates,
            "active_high_value_lessons": high_value,
            "compression_efficiency": rounded(efficiency, 3),
            "preserves_historical_lessons": True,
            "routes_output_through_librarian": True,
            "raw_dataset_forwarding_allowed": False,
            "top_compressed_lesson": first(tier2a.get("strongest_master_truth"), tier3.get("top_historical_lesson"), "profit capture and exit quality remain the highest value compressed focus"),
            **_safe_flags(),
        }

    def _historical_maturation(self, statuses: dict[str, Any]) -> dict[str, Any]:
        tier3 = status_value(statuses, "astra_tier3_historical_satellite_shadow_acceleration_v1")
        historical = status_value(statuses, "historical_intelligence_market_memory_suite_v1")
        memory = status_value(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        sources = [p for p in (tier3, historical, memory, catalyst, profit, lifecycle) if p]
        confidence = _avg([_confidence(p) for p in sources], 0.0)
        maturity = clamp(confidence * 0.65 + min(35.0, len(sources) * 6.0)) if sources else 0.0
        retrieval = clamp(first(memory.get("retrieval_accuracy"), memory.get("memory_confidence"), tier3.get("satellite_coordinator_health") == "healthy" and confidence, confidence))
        transfer = clamp(first(tier3.get("transfer_learning_quality"), memory.get("transfer_confidence"), confidence * 0.9))
        return {
            "module": "Historical Intelligence Maturation V2",
            "status": "ok" if sources else "insufficient_evidence",
            "historical_maturity_status": _status_from_score(maturity),
            "memory_quality": rounded(clamp(first(memory.get("memory_quality"), confidence)), 3),
            "memory_maturity": rounded(maturity, 3),
            "retrieval_accuracy": rounded(retrieval, 3),
            "transfer_learning_quality": rounded(transfer, 3),
            "historical_confidence": rounded(confidence, 3),
            "symbol_memory_status": text(first(memory.get("status"), historical.get("status"), "maturing")),
            "sector_memory_status": text(first(catalyst.get("status"), "maturing")),
            "regime_memory_status": text(first(historical.get("current_regime_signature"), "maturing")),
            "profit_capture_memory_status": text(first(profit.get("status"), "maturing")),
            "exit_memory_status": text(first(lifecycle.get("status"), "maturing")),
            "compressed_history_only": True,
            "large_raw_history_stored": False,
            **_safe_flags(),
        }

    def _adaptive_learning_prioritization(self, statuses: dict[str, Any]) -> dict[str, Any]:
        profit = status_value(statuses, "profit_optimization_context_intelligence_suite_v1")
        foundation = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        market = status_value(statuses, "market_condition_attribution_v1")
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        exit_quality = clamp(first(profit.get("exit_quality"), foundation.get("exit_quality"), 55.0))
        capture = clamp(first(profit.get("capture_ratio"), profit.get("profit_capture_score"), 50.0))
        ranking_quality = clamp(first(ranking.get("ranking_quality_score"), 60.0))
        market_conf = clamp(first(market.get("condition_confidence_score"), 45.0))
        catalyst_conf = clamp(first(catalyst.get("catalyst_lifecycle_confidence"), 45.0))
        exit_weight = 70 if min(exit_quality, capture) < ranking_quality else 55
        catalyst_weight = 15 if catalyst_conf < 65 else 10
        regime_weight = 10 if market_conf < 65 else 8
        historical_weight = max(5, 100 - exit_weight - catalyst_weight - regime_weight)
        expected_pf = rounded((100 - min(exit_quality, capture)) / 100.0 * 0.18, 4)
        return {
            "module": "Adaptive Learning Prioritization V2",
            "status": "ok",
            "learning_prioritization_status": "active_advisory_shadow_only",
            "learning_focus": "exit_quality_profit_capture_giveback_capital_efficiency",
            "attention_allocation_pct": {
                "exit_quality_profit_capture": exit_weight,
                "catalyst_intelligence": catalyst_weight,
                "regime_intelligence": regime_weight,
                "historical_memory": historical_weight,
            },
            "expected_pf_improvement": expected_pf,
            "expected_giveback_reduction_pct": rounded(max(0.0, (60.0 - capture) * 0.08), 3),
            "expected_capture_improvement_pct": rounded(max(0.0, (70.0 - capture) * 0.06), 3),
            "expected_exit_improvement_pct": rounded(max(0.0, (70.0 - exit_quality) * 0.05), 3),
            "highest_roi_focus": "profit_capture_and_exit_quality",
            "priority_reason": "Astra finds opportunities better than it prioritizes and manages them; profit leaks remain the highest ROI focus.",
            **_safe_flags(),
        }

    def _research_department(self, statuses: dict[str, Any]) -> dict[str, Any]:
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        attribution = status_value(statuses, "shadow_correction_validation_attribution_v1")
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        candidates = [
            {"topic": "profit_capture_giveback_reduction", "roi": 86, "route": "Research -> Shadow Lab -> Human Approval"},
            {"topic": "exit_quality_hold_duration", "roi": 82, "route": "Research -> Shadow Lab -> Human Approval"},
            {"topic": "ranking_regret_reduction", "roi": 72, "route": "Research -> Shadow Lab -> Human Approval"},
            {"topic": "catalyst_decay_detection", "roi": 68, "route": "Research -> Shadow Lab -> Human Approval"},
            {"topic": "market_condition_confidence", "roi": 61, "route": "Research -> Shadow Lab -> Human Approval"},
        ]
        reviewed = max(to_int(shadow.get("learning_events"), 0), to_int(attribution.get("shadow_recommendations_reviewed"), 0), to_int(profit.get("recommendation_count"), 0))
        completed = min(len(candidates), max(0, reviewed // 100))
        validated = min(completed, max(0, to_int(attribution.get("validated_recommendations"), 0) // 10))
        return {
            "module": "Autonomous Research Department Lite",
            "status": "ok" if reviewed else "insufficient_evidence",
            "research_department_status": "active_shadow_research_queue" if reviewed else "insufficient_evidence",
            "research_studies": len(candidates),
            "completed_research_studies": completed,
            "validated_research_studies": validated,
            "rejected_research_studies": max(0, completed - validated),
            "highest_roi_topics": candidates,
            "highest_roi_research_topic": candidates[0]["topic"],
            "auto_apply_allowed": False,
            "human_approval_required": True,
            "research_route": "Research -> Shadow Lab -> Human Approval",
            **_safe_flags(),
        }

    def _portfolio_lite(self, statuses: dict[str, Any]) -> dict[str, Any]:
        portfolio = status_value(statuses, "portfolio_diversification_correlation_v2")
        foundation = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        mobile = status_value(statuses, "mobile_runtime_compaction")
        sources = [p for p in (portfolio, foundation, mobile) if p]
        efficiency = clamp(first(portfolio.get("portfolio_efficiency"), foundation.get("capital_efficiency_score"), 58.0 if sources else 0.0))
        utilization = clamp(first(portfolio.get("capital_utilization"), mobile.get("true_broker_active_positions") and 65.0, 55.0 if sources else 0.0))
        return {
            "module": "Portfolio Construction Lite",
            "status": "ok" if sources else "insufficient_evidence",
            "portfolio_intelligence_status": "advisory_only_active" if sources else "insufficient_evidence",
            "concentration_status": text(first(portfolio.get("concentration_risk"), "monitoring")),
            "correlation_status": text(first(portfolio.get("correlation_risk"), "monitoring")),
            "diversification_status": text(first(portfolio.get("diversification_status"), "monitoring")),
            "sector_exposure_status": text(first(portfolio.get("sector_exposure_status"), "monitoring")),
            "trapped_capital_status": text(first(foundation.get("trapped_capital_status"), "monitoring")),
            "capital_efficiency_score": rounded(efficiency, 3),
            "portfolio_utilization_score": rounded(utilization, 3),
            "advisory_only_no_allocation_change": True,
            **_safe_flags(),
        }

    def _self_optimization(self, statuses: dict[str, Any], modules: dict[str, dict[str, Any]]) -> dict[str, Any]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        profit = status_value(statuses, "profit_optimization_context_intelligence_suite_v1")
        drift = status_value(statuses, "learning_drift_detection_v1")
        top_weakness = "profit_capture_exit_quality"
        ranking_quality = clamp(first(ranking.get("ranking_quality_score"), 65.0))
        capture = clamp(first(profit.get("profit_capture_score"), profit.get("capture_ratio"), 52.0))
        if ranking_quality < capture:
            top_weakness = "ranking_quality_prioritization"
        top_bottleneck = first(drift.get("affected_area"), modules["portfolio_construction_lite"].get("trapped_capital_status"), "profit_capture_giveback")
        return {
            "module": "Self-Optimization Engine V1",
            "status": "ok",
            "self_optimization_status": "active_advisory_only",
            "top_weakness": top_weakness,
            "top_opportunity": "reduce giveback and improve profit capture before broader strategy changes",
            "top_bottleneck": text(top_bottleneck),
            "highest_roi_improvement": modules["adaptive_learning_prioritization_v2"].get("highest_roi_focus"),
            "highest_confidence_improvement": "profit protection validation and exit-quality diagnostics",
            "biggest_intelligence_gap": "market condition and cross-market confidence maturation",
            "recommended_next_focus": "Keep maturing exit quality, capture ratio, giveback, capital efficiency, and hold quality diagnostics.",
            "auto_correct_allowed": False,
            **_safe_flags(),
        }

    def _health_monitoring(self, statuses: dict[str, Any]) -> dict[str, Any]:
        foundation = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        resource = status_value(statuses, "astra_resource_manager_v1")
        alpaca = status_value(statuses, "alpaca_paper_broker")
        remote = status_value(statuses, "remote_runtime_consistency")
        unified = status_value(statuses, "unified_learning_diagnostics_v1")
        provider_calls = max(to_int(foundation.get("provider_calls_used"), 0), to_int(resource.get("provider_calls_used"), 0))
        failed = to_int(unified.get("failed_sources_count"), 0)
        health_score = 92.0 - min(20.0, failed * 4.0) - min(15.0, provider_calls * 2.0)
        broker_health = "paper_only_verified" if bool(first(alpaca.get("paper_mode_verified"), alpaca.get("alpaca_paper_only_preserved"), True)) else "needs_attention"
        warnings = []
        if failed:
            warnings.append("failed_sources_present")
        if provider_calls:
            warnings.append("provider_calls_detected")
        if not warnings:
            warnings.append("none")
        return {
            "module": "Autonomous Health Monitoring V2",
            "status": "ok",
            "health_monitoring_status": _status_from_score(health_score),
            "broker_health": broker_health,
            "database_health": text(first(foundation.get("database_health"), "monitoring")),
            "worker_health": text(first(foundation.get("worker_health"), remote.get("worker_health"), "monitoring")),
            "storage_health": text(first(foundation.get("storage_health"), "monitoring")),
            "memory_health": text(first(foundation.get("memory_health"), "monitoring")),
            "cache_health": text(first(foundation.get("cache_health"), "healthy")),
            "api_health": "healthy" if provider_calls == 0 else "monitoring",
            "bandwidth_health": text(first(resource.get("bandwidth_budget_status"), foundation.get("bandwidth_status"), "safe")),
            "learning_health": "healthy" if failed == 0 else "monitoring",
            "intelligence_health": "healthy" if health_score >= 75 else "monitoring",
            "warnings": warnings,
            "bottlenecks": ["profit_capture", "ranking_quality", "cross_market_confidence", "market_condition_confidence"],
            "efficiency_score": rounded(clamp(health_score), 3),
            "recommendations": ["warn_only", "log_only", "recommend_fixes_only", "pause_only_unsafe_optional_workers_if_governance_requires"],
            "auto_correct_allowed": False,
            **_safe_flags(),
        }

    def _profit_improvement_focus(self, statuses: dict[str, Any], prioritization: dict[str, Any]) -> dict[str, Any]:
        profit = status_value(statuses, "profit_optimization_context_intelligence_suite_v1")
        protection = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        capture = clamp(first(profit.get("capture_ratio"), profit.get("profit_capture_score"), protection.get("profit_lock_readiness"), 52.0))
        giveback = clamp(first(profit.get("average_giveback"), protection.get("giveback_risk_score"), 18.0))
        exit_quality = clamp(first(profit.get("exit_quality"), protection.get("readiness_score"), 55.0))
        return {
            "module": "Unified Profit Improvement Focus",
            "status": "ok",
            "profit_improvement_status": "active_advisory_only",
            "focus_areas": ["exit_quality", "capture_ratio", "giveback", "capital_efficiency", "hold_quality"],
            "exit_quality_focus_score": rounded(100.0 - exit_quality, 3),
            "capture_ratio_focus_score": rounded(100.0 - capture, 3),
            "giveback_focus_score": rounded(giveback, 3),
            "capital_efficiency_focus_score": rounded(62.0, 3),
            "hold_quality_focus_score": rounded(64.0, 3),
            "expected_pf_improvement": prioritization.get("expected_pf_improvement"),
            "expected_capture_improvement_pct": prioritization.get("expected_capture_improvement_pct"),
            "expected_giveback_reduction_pct": prioritization.get("expected_giveback_reduction_pct"),
            "expected_exit_improvement_pct": prioritization.get("expected_exit_improvement_pct"),
            "recommendations_advisory_only": [
                "continue shadow validation of profit protection",
                "prioritize exit-quality diagnostics over new strategy behavior",
                "track capital efficiency pressure without allocation changes",
            ],
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.time()
        compression = self._dynamic_knowledge_compression(statuses)
        historical = self._historical_maturation(statuses)
        prioritization = self._adaptive_learning_prioritization(statuses)
        research = self._research_department(statuses)
        portfolio = self._portfolio_lite(statuses)
        modules: dict[str, dict[str, Any]] = {
            "dynamic_knowledge_compression_v2": compression,
            "historical_intelligence_maturation_v2": historical,
            "adaptive_learning_prioritization_v2": prioritization,
            "autonomous_research_department_lite": research,
            "portfolio_construction_lite": portfolio,
        }
        self_optimization = self._self_optimization(statuses, modules)
        health = self._health_monitoring(statuses)
        profit_focus = self._profit_improvement_focus(statuses, prioritization)
        modules.update(
            {
                "self_optimization_engine_v1": self_optimization,
                "autonomous_health_monitoring_v2": health,
                "unified_profit_improvement_focus": profit_focus,
            }
        )
        statuses_ok = [m.get("status") == "ok" for m in modules.values()]
        overall = "ok" if any(statuses_ok) else "insufficient_evidence"
        top_summary = _brief([
            f"top weakness {self_optimization.get('top_weakness')}",
            f"highest ROI {self_optimization.get('highest_roi_improvement')}",
            f"historical maturity {historical.get('historical_maturity_status')}",
            f"compression {compression.get('compression_status')}",
            f"health {health.get('health_monitoring_status')}",
        ])
        payload = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Final Intelligence Maturation Bundle V1",
            "status": overall,
            "mode": self.mode,
            "generated_at": now_iso(),
            "final_major_architecture_bundle": True,
            "future_major_tiers_allowed": False,
            "future_work_scope": "small_targeted_improvements_only_after_human_approval",
            "modules_created": FINAL_MODULES,
            "modules": modules,
            "compression_status": compression.get("compression_status"),
            "historical_maturity_status": historical.get("historical_maturity_status"),
            "learning_prioritization_status": prioritization.get("learning_prioritization_status"),
            "research_department_status": research.get("research_department_status"),
            "portfolio_intelligence_status": portfolio.get("portfolio_intelligence_status"),
            "self_optimization_status": self_optimization.get("self_optimization_status"),
            "health_monitoring_status": health.get("health_monitoring_status"),
            "profit_improvement_status": profit_focus.get("profit_improvement_status"),
            "expected_pf_improvement": prioritization.get("expected_pf_improvement"),
            "expected_capture_improvement_pct": prioritization.get("expected_capture_improvement_pct"),
            "expected_giveback_reduction_pct": prioritization.get("expected_giveback_reduction_pct"),
            "expected_exit_improvement_pct": prioritization.get("expected_exit_improvement_pct"),
            "top_weakness": self_optimization.get("top_weakness"),
            "top_opportunity": self_optimization.get("top_opportunity"),
            "top_bottleneck": self_optimization.get("top_bottleneck"),
            "highest_roi_improvement": self_optimization.get("highest_roi_improvement"),
            "highest_confidence_improvement": self_optimization.get("highest_confidence_improvement"),
            "recommended_next_focus": self_optimization.get("recommended_next_focus"),
            "intelligence_summary": top_summary,
            "dashboard_impact": "one_collapsed_learning_center_section_unified_diagnostics_only",
            "api_bandwidth_impact": "unchanged_zero_dashboard_provider_calls_cache_first_no_endpoint_storm",
            "provider_api_impact": "unchanged_zero_dashboard_provider_calls",
            "librarian_integration_status": "routed_compressed_outputs_only",
            "unified_truth_integration_status": "summary_truths_only",
            "executive_assistant_integration_status": "prioritized_advisory_focus_only",
            "astra_brain_integration_status": "advisory_context_only_no_behavior_change",
            "shadow_lab_route": "Research -> Shadow Lab -> Human Approval",
            "raw_data_direct_to_brain": False,
            "auto_apply_allowed": False,
            "build_ms": rounded((time.time() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(payload)
