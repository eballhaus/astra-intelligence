from __future__ import annotations

import time
from datetime import datetime, timezone
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


OFFICIAL_METRICS = (
    "profit_factor",
    "win_rate",
    "average_return",
    "portfolio_value",
    "today_pnl",
    "total_pnl",
    "open_positions",
)

PROMOTION_STAGES = {
    0: "shadow_only",
    1: "advisory",
    2: "paper_micro_test_5pct",
    3: "paper_expansion_10_25pct",
    4: "paper_default",
    5: "human_approved_permanent_adoption",
}


def _safe_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "shadow_safe": True,
        "cache_first": True,
        "advisory_first": True,
        "rollback_enabled": True,
        "human_approval_required": True,
        "automatic_adoption_enabled": False,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "confidence_system_changed": False,
        "thresholds_changed": False,
        "paper_execution_changed": False,
        "provider_polling_changed": False,
        "dashboard_polling_changed": False,
        "llm_calls_increased": False,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
        "api_calls_used": 0,
    }


def _age_seconds(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def _metric(
    value: Any,
    *,
    source: str,
    evidence_count: int = 0,
    freshness_seconds: float | None = None,
    diagnostic: bool = False,
) -> dict[str, Any]:
    numeric = None
    try:
        if value is not None and value != "":
            numeric = float(value)
    except Exception:
        numeric = None
    fresh_label = "Cached"
    if freshness_seconds is not None and freshness_seconds > 900:
        fresh_label = "Stale"
    if numeric is None or evidence_count <= 0:
        return {
            "value": None,
            "display_value": "warming up",
            "truth_label": "Diagnostic" if diagnostic else "Warming",
            "label": "Diagnostic" if diagnostic else "Warming",
            "maturity": "warming_up",
            "freshness_label": fresh_label,
            "source": source,
            "evidence_count": max(0, evidence_count),
            "official": not diagnostic,
            "available": False,
        }
    return {
        "value": rounded(numeric, 4),
        "display_value": rounded(numeric, 4),
        "truth_label": "Diagnostic" if diagnostic else "Official",
        "label": "Diagnostic" if diagnostic else "Official",
        "maturity": "healthy",
        "freshness_label": fresh_label,
        "source": source,
        "evidence_count": max(0, evidence_count),
        "official": not diagnostic,
        "available": True,
    }


class AstraTruthControlledEvolutionExecutiveV1(CachedDiagnosticModule):
    """Official broker truth, controlled promotion governance, and executive compression."""

    module_name = "astra_truth_controlled_evolution_executive_v1"
    mode = "paper_only_truth_governance_controlled_evolution"

    def _official_truth(self, statuses: dict[str, Any]) -> dict[str, Any]:
        broker = status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1")
        truth = dict(broker.get("broker_truth_metrics") or {})
        closed_count = max(to_int(truth.get("true_paper_closed_trade_count"), 0), to_int(broker.get("true_paper_closed_trade_count"), 0))
        minimum_performance_sample = 20
        performance_evidence = closed_count if closed_count >= minimum_performance_sample else 0
        freshness = _age_seconds(first(broker.get("generated_at"), truth.get("generated_at"), default=""))
        total_pnl = None
        if closed_count > 0 and truth.get("paper_gross_profit") is not None and truth.get("paper_gross_loss") is not None:
            total_pnl = to_float(truth.get("paper_gross_profit"), 0.0) - to_float(truth.get("paper_gross_loss"), 0.0)
        metrics = {
            "profit_factor": _metric(first(truth.get("true_paper_pf"), broker.get("true_paper_pf")), source="broker_truth_engine_v1.closed_paper_trades", evidence_count=performance_evidence, freshness_seconds=freshness),
            "win_rate": _metric(first(truth.get("true_paper_win_rate"), broker.get("true_paper_win_rate")), source="broker_truth_engine_v1.closed_paper_trades", evidence_count=performance_evidence, freshness_seconds=freshness),
            "average_return": _metric(first(truth.get("true_paper_avg_return"), broker.get("true_paper_avg_return")), source="broker_truth_engine_v1.closed_paper_trades", evidence_count=performance_evidence, freshness_seconds=freshness),
            "portfolio_value": _metric(broker.get("account_equity"), source="alpaca_paper_account_equity", evidence_count=1 if broker.get("account_preflight_ok") else 0, freshness_seconds=freshness),
            "today_pnl": _metric(None, source="alpaca_daily_pnl_not_available_in_cached_truth_payload", evidence_count=0, freshness_seconds=freshness),
            "total_pnl": _metric(total_pnl, source="broker_truth_engine_v1.realized_closed_paper_pnl", evidence_count=closed_count, freshness_seconds=freshness),
            "open_positions": _metric(broker.get("open_positions_count"), source="alpaca_broker_confirmed_open_positions", evidence_count=1 if broker.get("positions_preflight_ok") else 0, freshness_seconds=freshness),
        }
        official_available = sum(1 for row in metrics.values() if row.get("available"))
        contradictions = []
        if closed_count <= 0 and any(metrics[key].get("available") for key in ("profit_factor", "win_rate", "average_return", "total_pnl")):
            contradictions.append("closed_trade_metric_without_broker_confirmed_evidence")
        confidence = clamp(first(truth.get("true_paper_metric_confidence"), broker.get("true_paper_metric_confidence"), 0.0))
        evidence_label = "healthy" if closed_count >= 20 else "warming_up" if closed_count > 0 else "warming_up"
        confidence_label = "high" if confidence >= 75 and closed_count >= 20 else "medium" if confidence >= 45 and closed_count > 0 else "warming_up"
        return {
            "module": "Executive Snapshot Truth Reconciliation V1",
            "status": "PASS" if not contradictions else "WARNING",
            "canonical_source": "alpaca_paper_broker_plus_broker_confirmed_closed_paper_trades",
            "official_metric_names": list(OFFICIAL_METRICS),
            "official_metrics": metrics,
            "official_metrics_available": official_available,
            "closed_paper_trade_count": closed_count,
            "minimum_performance_sample": minimum_performance_sample,
            "evidence_label": evidence_label,
            "confidence_label": confidence_label,
            "metric_confidence": rounded(confidence, 3),
            "diagnostic_metrics_may_override_official": False,
            "fallback_may_replace_official": False,
            "insufficient_evidence_display": "warming up",
            "contradictions_detected": contradictions,
            "executive_summary_consistent": not contradictions,
            "formatting_guard_active": True,
            "official_performance_summary": {
                "profit_factor": metrics["profit_factor"],
                "released_win_rate": metrics["win_rate"],
                "average_return": metrics["average_return"],
                "portfolio_value": metrics["portfolio_value"],
                "today_pnl": metrics["today_pnl"],
                "total_pnl": metrics["total_pnl"],
                "open_positions": metrics["open_positions"],
                "closed_trade_count": closed_count,
                "metric_source": "alpaca_paper_broker_plus_broker_confirmed_closed_paper_trades",
                "truth_scope": "official",
                "diagnostic_metrics_excluded": True,
            },
            **_safe_flags(),
        }

    def _controlled_evolution(self, statuses: dict[str, Any]) -> dict[str, Any]:
        adaptive = status_value(statuses, "astra_adaptive_learning_v1")
        promotion = dict(adaptive.get("incremental_shadow_promotion_v1") or {})
        governor = dict(adaptive.get("promotion_governor_v1") or {})
        reviews = [dict(row) for row in (promotion.get("all_metric_reviews") or []) if isinstance(row, dict)]
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        tier2_candidate = dict(tier2.get("controlled_evolution_integration") or {})
        if tier2_candidate.get("controlled_evolution_candidate"):
            reviews.append({
                "promotion_candidate": True,
                "promotion_metric": text(tier2_candidate.get("candidate_metric"), "Profit Capture"),
                "promotion_delta": to_float(tier2_candidate.get("candidate_delta"), 0.0),
                "promotion_confidence": to_float(tier2_candidate.get("candidate_confidence"), 0.0),
                "promotion_evidence": to_int(tier2_candidate.get("candidate_evidence_count"), 0),
                "promotion_stability": to_float(
                    (tier2.get("learning_persistence_engine_v1") or {}).get("lesson_retention_score"),
                    0.0,
                ),
                "promotion_status": "candidate",
                "promotion_reason": "tier2_advisory_correction_candidate_routed_through_existing_bridge",
                "source_suite": "astra_performance_optimization_suite_v1",
            })
        eligible = [
            row for row in reviews
            if to_float(row.get("promotion_delta"), 0.0) >= 10.0
            and to_int(row.get("promotion_evidence"), 0) >= 25
            and to_float(row.get("promotion_stability"), 0.0) >= 55.0
            and to_float(row.get("promotion_confidence"), 0.0) >= 55.0
        ]
        selected = eligible[0] if eligible else {}
        if not selected:
            recommended_stage = 0
            stage_reason = "no_single_metric_passed_10pct_stability_evidence_repeatability_gate"
        elif to_int(selected.get("promotion_evidence"), 0) >= 50 and to_float(selected.get("promotion_confidence"), 0.0) >= 65:
            recommended_stage = 2
            stage_reason = "single_metric_eligible_for_human_approved_5pct_paper_micro_test"
        else:
            recommended_stage = 1
            stage_reason = "single_metric_ready_for_advisory_review"
        stages = []
        for stage, label in PROMOTION_STAGES.items():
            unlocked = stage <= recommended_stage
            stages.append({
                "stage": stage,
                "label": label,
                "eligible": unlocked,
                "active": stage == 0,
                "requires_human_approval": stage >= 2,
                "automatic_activation_allowed": False,
            })
        return {
            "module": "Shadow to Paper Controlled Evolution Bridge V1",
            "status": "candidate" if selected else "shadow_only",
            "current_active_stage": 0,
            "current_active_stage_label": PROMOTION_STAGES[0],
            "recommended_next_stage": recommended_stage,
            "recommended_next_stage_label": PROMOTION_STAGES[recommended_stage],
            "stage_reason": stage_reason,
            "stages": stages,
            "promotion_candidate": selected,
            "promotion_candidate_count": min(1, len(eligible)),
            "metrics_reviewed": len(reviews),
            "eligible_metrics": list(promotion.get("eligible_metrics") or []),
            "tier2_candidate_reviewed": bool(tier2_candidate),
            "tier2_candidate_eligible": bool(tier2_candidate.get("controlled_evolution_candidate")),
            "minimum_improvement_pct": 10.0,
            "stable_required": True,
            "sufficient_evidence_required": True,
            "repeatable_required": True,
            "one_candidate_per_cycle": bool(governor.get("max_promotion_candidates_per_cycle", 1) == 1),
            "paper_micro_test_active": False,
            "paper_behavior_changed": False,
            "shadow_direct_override_allowed": False,
            "permanent_adoption_requires_human_approval": True,
            "rollback_status": "armed",
            **_safe_flags(),
        }

    @staticmethod
    def _department(name: str, *, health: float, confidence: float, status: str, concern: str, strength: str, recommendation: str) -> dict[str, Any]:
        return {
            "department": name,
            "health": rounded(clamp(health), 2),
            "confidence": rounded(clamp(confidence), 2),
            "status": text(status, "warming_up"),
            "top_concern": text(concern, "warming_up"),
            "top_strength": text(strength, "warming_up"),
            "recommendation": text(recommendation, "continue_cache_first_monitoring"),
        }

    def _executive_departments(self, statuses: dict[str, Any], truth: dict[str, Any], bridge: dict[str, Any]) -> dict[str, Any]:
        learning = status_value(statuses, "astra_learning_preservation_capacity_v1")
        adaptive = status_value(statuses, "astra_adaptive_learning_v1")
        horizon = status_value(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")
        market = status_value(statuses, "astra_market_intelligence_v1")
        portfolio = status_value(statuses, "portfolio_health_summary")
        recovery = status_value(statuses, "astra_recovery_center_v1")
        system = status_value(statuses, "system_health_summary")
        shadow = dict(adaptive.get("shadow_performance_scorecard_v2") or {})
        throughput = dict(learning.get("learning_throughput_preservation_engine_v1") or {})
        official = dict(truth.get("official_metrics") or {})
        closed = to_int(truth.get("closed_paper_trade_count"), 0)
        official_conf = to_float(truth.get("metric_confidence"), 0.0)
        departments = [
            self._department(
                "Trading",
                health=70.0 if official.get("portfolio_value", {}).get("available") else 45.0,
                confidence=official_conf,
                status="official_truth_active" if truth.get("status") == "PASS" else "truth_warning",
                concern="closed_trade_performance_warming_up" if closed < 20 else "profit_capture_and_exit_quality",
                strength="broker_confirmed_portfolio_and_position_truth",
                recommendation="use_only_official_broker_metrics_for_executive_performance",
            ),
            self._department(
                "Learning",
                health=to_float(throughput.get("learning_throughput_score"), 50.0),
                confidence=min(100.0, to_int(throughput.get("evidence_count"), 0) / 25.0),
                status=text(throughput.get("status"), "warming_up"),
                concern=text(throughput.get("primary_throughput_blocker"), "learning_participation"),
                strength="fresh_evidence_flow_preserved" if throughput.get("fresh_evidence_flow_preserved") else "bounded_cache_first_learning",
                recommendation=text(throughput.get("recommended_action"), "protect_fresh_evidence_flow"),
            ),
            self._department(
                "Shadow",
                health=to_float(shadow.get("shadow_health"), 50.0),
                confidence=to_float(shadow.get("shadow_confidence"), 0.0),
                status=text(bridge.get("status"), "shadow_only"),
                concern=text(shadow.get("top_weakness"), "promotion_evidence"),
                strength=text(shadow.get("top_strength"), "replay_and_shadow_validation"),
                recommendation=text(shadow.get("recommendation"), "collect_more_repeatable_evidence"),
            ),
            self._department(
                "Portfolio",
                health=100.0 - to_float(horizon.get("capital_trapped_score"), 50.0),
                confidence=65.0 if to_int(horizon.get("broker_confirmed_count"), 0) > 0 else 30.0,
                status=text(horizon.get("adaptive_portfolio_rotation_status"), "advisory_monitoring"),
                concern=f"{to_int(horizon.get('stale_positions_count'), 0)}_stale_positions",
                strength="broker_truth_wins_and_stale_rows_hidden",
                recommendation=text(horizon.get("horizon_adjustment_recommendation"), "review_capacity_and_horizon_balance"),
            ),
            self._department(
                "Market Intelligence",
                health=to_float(market.get("market_intelligence_score"), 50.0),
                confidence=to_float(market.get("pillar_alignment_score"), 45.0),
                status=text(market.get("market_regime"), "warming_up"),
                concern=text(market.get("weakest_pillar"), "market_condition_confidence"),
                strength=text(market.get("strongest_pillar"), "cached_market_context"),
                recommendation=text(market.get("market_headwind_summary"), "maintain_selective_posture"),
            ),
            self._department(
                "Infrastructure",
                health=100.0 if not status_value(statuses, "unified_learning_diagnostics_v1").get("failed_sources_count") else 55.0,
                confidence=90.0,
                status="healthy" if not status_value(statuses, "unified_learning_diagnostics_v1").get("failed_sources_count") else "degraded",
                concern=text(system.get("degraded_reason"), "none"),
                strength="zero_dashboard_provider_and_llm_calls",
                recommendation="preserve_single_unified_endpoint_and_cache_first_render",
            ),
            self._department(
                "Recovery",
                health=to_float(recovery.get("recovery_health_score"), 70.0),
                confidence=85.0 if recovery else 35.0,
                status=text(recovery.get("status_label"), "warming_up"),
                concern="learning_gap_detected" if bool((recovery.get("learning_protection") or {}).get("learning_gap_detected")) else "none",
                strength="persistent_backend_frontend_and_learning_protection",
                recommendation=text((recovery.get("recovery") or {}).get("recommended_action"), "continue_recovery_monitoring"),
            ),
        ]
        weakest = min(departments, key=lambda row: row["health"])
        strongest = max(departments, key=lambda row: row["health"])
        return {
            "module": "Executive Intelligence Layer V1",
            "status": "ok",
            "departments": departments,
            "department_count": len(departments),
            "strongest_department": strongest["department"],
            "weakest_department": weakest["department"],
            "top_executive_concern": weakest["top_concern"],
            "top_executive_strength": strongest["top_strength"],
            "executive_recommendation": weakest["recommendation"],
            "raw_endpoint_dump_default": False,
            "expandable_details_available": True,
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        truth = self._official_truth(statuses)
        bridge = self._controlled_evolution(statuses)
        executive = self._executive_departments(statuses, truth, bridge)
        out = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Tier 1B - Truth Layer, Controlled Evolution & Executive Intelligence Suite V1",
            "status": "ok" if truth.get("status") == "PASS" else "warning",
            "mode": self.mode,
            "generated_at": now_iso(),
            "executive_snapshot_truth_reconciliation_v1": truth,
            "shadow_paper_controlled_evolution_bridge_v1": bridge,
            "executive_intelligence_layer_v1": executive,
            "official_metrics": truth.get("official_metrics"),
            "executive_departments": executive.get("departments"),
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(out)
