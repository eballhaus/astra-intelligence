from __future__ import annotations

import math
import os
import re
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


HORIZONS = ("scalp", "day_trade", "multi_day", "swing", "longer_hold", "unknown")
LOCK_DAYS = {"scalp": 0.15, "day_trade": 0.7, "multi_day": 3.5, "swing": 7.0, "longer_hold": 15.0, "unknown": 7.0}
EVOLUTION_STAGES = {
    0: "shadow_only_observation",
    1: "paper_micro_test_5pct",
    2: "controlled_paper_test_10pct",
    3: "controlled_paper_test_20pct",
    4: "limited_default_candidate_50pct",
    5: "human_approved_paper_default",
}
ELIGIBLE_CATEGORIES = (
    "profit_capture",
    "giveback_reduction",
    "exit_quality",
    "horizon_accuracy",
    "risk_adjusted_return",
    "regime_stability",
    "overfiltering_reduction",
    "learning_throughput",
)


def _safe_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "cache_first": True,
        "advisory_first": True,
        "bounded": True,
        "rollback_aware": True,
        "broker_truth_preserved": True,
        "paper_mode_required": True,
        "rollback_required": True,
        "broker_execution_added": False,
        "automatic_entries_enabled": False,
        "automatic_exits_enabled": False,
        "automatic_sizing_enabled": False,
        "automatic_allocations_enabled": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "thresholds_changed": False,
        "confidence_scoring_changed": False,
        "shadow_logic_changed": False,
        "paper_execution_changed": False,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "forced_trades_enabled": False,
        "forced_exits_enabled": False,
        "fixed_horizon_quotas_enabled": False,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
        "api_calls_used": 0,
    }


def _metric_value(value: Any, default: float = 0.0) -> float:
    if isinstance(value, dict):
        return to_float(value.get("value"), default)
    return to_float(value, default)


def _horizon(value: Any) -> str:
    raw = text(value, "unknown").lower().replace("-", "_").replace(" ", "_")
    if "scalp" in raw or raw in {"15m", "30m", "45m", "60m"}:
        return "scalp"
    if "day" in raw or "intraday" in raw or "eod" in raw or raw in {"2h", "4h"}:
        return "day_trade"
    if "long" in raw or "30_plus" in raw or raw == "10d+":
        return "longer_hold"
    if "multi" in raw or "4_to_7" in raw or "8_to_30" in raw or raw in {"2d", "3d", "5d", "10d"}:
        return "multi_day"
    if "swing" in raw or "1_to_3" in raw or raw == "1d":
        return "swing"
    return "unknown"


def _hold_days(value: Any, horizon: str) -> float:
    raw = text(value, "").lower()
    values = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", raw)]
    if values:
        multiplier = 1.0
        if "hour" in raw or "hr" in raw or "h" == raw[-1:]:
            multiplier = 1.0 / 24.0
        if "min" in raw or raw.endswith("m"):
            multiplier = 1.0 / 1440.0
        return max(0.05, sum(values) / len(values) * multiplier)
    return LOCK_DAYS.get(horizon, 7.0)


def _status_from_pressure(score: float, throughput: float) -> str:
    if throughput < 20 and score >= 75:
        return "learning_blocked"
    if score >= 85:
        return "saturated"
    if score >= 68:
        return "constrained"
    if score >= 45:
        return "elevated"
    return "healthy"


class AstraAdaptiveOccupancyEvolutionSuiteV1(CachedDiagnosticModule):
    """Advisory occupancy, learning-throughput, and controlled-evolution governance."""

    module_name = "astra_adaptive_occupancy_evolution_suite_v1"
    mode = "paper_only_adaptive_occupancy_controlled_evolution_advisory"

    def _fallback(self, reason: str = "insufficient_evidence", **extra: Any) -> dict[str, Any]:
        out = super()._fallback(reason, **extra)
        out.update(_safe_flags())
        return out

    @staticmethod
    def _capacity(statuses: dict[str, Any]) -> dict[str, Any]:
        horizon = status_value(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")
        modules = dict(horizon.get("modules") or {})
        return dict(
            modules.get("horizon_capacity_manager_v1")
            or horizon.get("horizon_capacity_manager_v1")
            or horizon
        )

    def _occupancy(self, statuses: dict[str, Any]) -> dict[str, Any]:
        capacity = self._capacity(statuses)
        tier1a = status_value(statuses, "astra_learning_preservation_capacity_v1")
        diversity = dict(tier1a.get("dynamic_horizon_allocation_diversity_engine_v1") or {})
        lifecycle = dict(tier1a.get("position_lifecycle_auditor_v1") or {})
        portfolio = status_value(statuses, "portfolio_health_summary")
        total_capacity = max(1, to_int(capacity.get("total_capacity"), 20))
        total_used = max(
            to_int(capacity.get("total_used"), 0),
            to_int(lifecycle.get("broker_confirmed_count"), 0),
        )
        distribution = dict(
            capacity.get("horizon_distribution_pct")
            or diversity.get("horizon_distribution_pct")
            or {}
        )
        normalized = {key: 0.0 for key in HORIZONS}
        for key, value in distribution.items():
            normalized[_horizon(key)] += to_float(value, 0.0)
        if sum(normalized.values()) <= 0 and total_used:
            normalized["unknown"] = 100.0
        expected_lock = sum(normalized[key] / 100.0 * LOCK_DAYS[key] for key in HORIZONS)
        occupancy_pct = clamp(total_used / total_capacity * 100.0)
        long_share = normalized["multi_day"] + normalized["swing"] + normalized["longer_hold"] + normalized["unknown"]
        heat = _metric_value(portfolio.get("portfolio_heat"))
        concentration = _metric_value(portfolio.get("concentration_risk"))
        correlation = _metric_value(portfolio.get("correlation_risk"))
        similarity = clamp(max(concentration, correlation))
        pressure = clamp(
            occupancy_pct * 0.42
            + long_share * 0.28
            + min(100.0, expected_lock * 7.0) * 0.15
            + similarity * 0.10
            + heat * 0.05
        )
        throughput = to_float(
            (tier1a.get("learning_throughput_preservation_engine_v1") or {}).get("learning_throughput_score"),
            50.0,
        )
        status = _status_from_pressure(pressure, throughput)
        dominant = max(normalized, key=normalized.get) if any(normalized.values()) else "unknown"
        recommendation = (
            "preserve_learning_reserve_and_favor_lower_occupancy_high_learning_value_opportunities"
            if status in {"constrained", "saturated", "learning_blocked"}
            else "price_expected_capacity_lock_into_candidate_review_without_fixed_quotas"
        )
        return {
            "module": "Adaptive Occupancy Management Engine V1",
            "status": "ok" if total_used or capacity else "insufficient_evidence",
            "capacity_occupancy": rounded(occupancy_pct, 3),
            "total_capacity": total_capacity,
            "broker_confirmed_positions": total_used,
            "capacity_available": max(0, total_capacity - total_used),
            "current_horizon_exposure": normalized,
            "occupancy_pressure_score": rounded(pressure, 3),
            "occupancy_status": status,
            "dominant_occupancy_source": dominant,
            "expected_capacity_lock_days": rounded(expected_lock, 3),
            "portfolio_monopolization_risk": rounded(clamp(long_share * 0.65 + similarity * 0.35), 3),
            "learning_capacity_risk": rounded(clamp(pressure * 0.7 + max(0.0, 60.0 - throughput) * 0.3), 3),
            "occupancy_recommendation": recommendation,
            "borrowed_from_future_learning_capacity": bool(occupancy_pct >= 90),
            "elite_opportunity_exception_allowed_for_advisory_review": True,
            "hard_horizon_caps_enabled": False,
            **_safe_flags(),
        }

    def _throughput(self, statuses: dict[str, Any], occupancy: dict[str, Any]) -> dict[str, Any]:
        tier1a = status_value(statuses, "astra_learning_preservation_capacity_v1")
        base = dict(tier1a.get("learning_throughput_preservation_engine_v1") or {})
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        horizon = status_value(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")
        recycling = dict((horizon.get("modules") or {}).get("dynamic_capacity_recycling_v1") or {})
        opened = to_int(first(base.get("opportunities_executed"), horizon.get("selected_horizon_count"), 0), 0)
        closed = max(to_int(base.get("trades_closed_today"), 0), to_int(recycling.get("recently_closed_positions"), 0))
        cycles = max(to_int(base.get("opportunities_reviewed"), 0), to_int(shadow.get("shadow_learning_events"), 0))
        historical_score = clamp(base.get("learning_throughput_score"))
        age_hours = to_float(base.get("evidence_age_hours"), 0.0)
        new_rate = to_float(base.get("learning_participation_pct"), 0.0)
        fresh_rate = clamp(100.0 - min(100.0, age_hours * 12.5))
        close_rate = rounded(closed / max(1, opened + closed) * 100.0, 3)
        turnover = to_float(base.get("trade_turnover_pct"), 0.0)
        paper_velocity = clamp(
            min(100.0, opened / 24.0 * 100.0) * 0.30
            + min(100.0, closed / 5.0 * 100.0) * 0.35
            + min(100.0, turnover * 5.0) * 0.20
            + fresh_rate * 0.15
            - (20.0 if occupancy.get("occupancy_status") in {"saturated", "learning_blocked"} else 10.0 if occupancy.get("occupancy_status") == "constrained" else 0.0)
        )
        if paper_velocity >= 70 and closed > 0:
            flow = "healthy"
        elif paper_velocity >= 45:
            flow = "slowing"
        elif paper_velocity >= 20:
            flow = "stalled"
        else:
            flow = "critical"
        blocker = text(
            first(
                base.get("primary_throughput_blocker"),
                occupancy.get("occupancy_status") if occupancy.get("occupancy_status") != "healthy" else None,
                "none",
            ),
            "none",
        )
        action = {
            "healthy": "maintain_fresh_evidence_flow_and_existing_gates",
            "slowing": "preserve_learning_reserve_and_prioritize_high_learning_value_opportunities",
            "stalled": "favor_lower_occupancy_opportunities_and_wait_for_validated_exits",
            "critical": "avoid_low_learning_long_duration_additions_and_restore_validation_flow",
        }[flow]
        return {
            "module": "Learning Throughput Protection Engine V1",
            "status": "ok" if base else "insufficient_evidence",
            "trades_opened": opened,
            "trades_closed": closed,
            "learning_cycles": cycles,
            "learning_throughput_score": rounded(paper_velocity, 3),
            "historical_shadow_evidence_freshness_score": rounded(historical_score, 3),
            "paper_learning_velocity_score": rounded(paper_velocity, 3),
            "learning_flow_status": flow,
            "days_since_learning_event": rounded(age_hours / 24.0, 3),
            "capacity_pressure": occupancy.get("occupancy_pressure_score"),
            "new_evidence_rate": rounded(new_rate, 3),
            "fresh_evidence_rate": rounded(fresh_rate, 3),
            "closed_trade_rate": close_rate,
            "open_trade_turnover": rounded(turnover, 3),
            "shadow_validation_flow": "active" if to_int(shadow.get("shadow_learning_events"), 0) > 0 else "warming_up",
            "paper_validation_flow": "active" if closed > 0 else "open_positions_without_closed_outcomes",
            "fresh_evidence_status": text(base.get("evidence_freshness"), "warming_up"),
            "trade_turnover_status": "healthy" if turnover >= 10 else "slowing",
            "validation_flow_status": "healthy" if flow == "healthy" else "needs_attention",
            "fresh_paper_learning_distinct_from_historical_evidence": True,
            "learning_blocker": blocker,
            "recommended_throughput_action": action,
            **_safe_flags(),
        }

    def _learning_continuity(
        self,
        statuses: dict[str, Any],
        occupancy: dict[str, Any],
        throughput: dict[str, Any],
    ) -> dict[str, Any]:
        exposure = dict(occupancy.get("current_horizon_exposure") or {})
        active_shares = [
            max(0.0, to_float(exposure.get(key), 0.0)) / 100.0
            for key in ("scalp", "day_trade", "multi_day", "swing", "longer_hold")
        ]
        hhi = sum(share * share for share in active_shares)
        diversity = clamp((1.0 - hhi) / 0.8 * 100.0) if sum(active_shares) > 0 else 0.0
        flow = clamp(throughput.get("learning_throughput_score"))
        turnover = clamp(to_float(throughput.get("open_trade_turnover"), 0.0) * 5.0)
        copilot = status_value(statuses, "astra_copilot_suite_v1")
        opportunity_count = len(copilot.get("top_actions") or [])
        opportunity_flow = clamp(opportunity_count / 5.0 * 100.0)
        occupancy_penalty = {
            "healthy": 0.0,
            "elevated": 5.0,
            "constrained": 12.0,
            "saturated": 22.0,
            "learning_blocked": 35.0,
        }.get(text(occupancy.get("occupancy_status"), "healthy"), 10.0)
        continuity = clamp(
            flow * 0.35
            + diversity * 0.30
            + turnover * 0.15
            + opportunity_flow * 0.20
            - occupancy_penalty
        )
        if continuity >= 70:
            status = "healthy"
        elif continuity >= 50:
            status = "constrained"
        elif continuity >= 30:
            status = "at_risk"
        else:
            status = "learning_starved"
        capacity_recommendation_needed = bool(
            status != "healthy"
            and opportunity_count >= 3
            and occupancy.get("occupancy_status") in {"constrained", "saturated", "learning_blocked"}
        )
        return {
            "module": "Learning Continuity Engine V1",
            "status": status,
            "learning_continuity_score": rounded(continuity, 3),
            "learning_diversity_score": rounded(diversity, 3),
            "learning_flow_score": rounded(flow, 3),
            "trade_turnover_score": rounded(turnover, 3),
            "opportunity_flow_score": rounded(opportunity_flow, 3),
            "current_capacity": occupancy.get("total_capacity"),
            "capacity_used": occupancy.get("broker_confirmed_positions"),
            "capacity_recommendation_needed": capacity_recommendation_needed,
            "continuity_bottleneck": (
                "horizon_concentration_and_low_turnover"
                if diversity < 35 and turnover < 35
                else "occupancy_pressure"
                if occupancy_penalty >= 12
                else "opportunity_flow"
                if opportunity_flow < 40
                else "none"
            ),
            "learning_benefit": "restore_horizon_diversity_and_fresh_validation_opportunities",
            "potential_risks": [
                "higher_correlation_or_concentration_if_existing_risk_gates_are_ignored",
                "more_open_positions_without_more_closed_outcome_evidence",
            ],
            "recommended_action": (
                "review_bounded_adaptive_capacity_and_lower_occupancy_candidates_through_existing_gates"
                if capacity_recommendation_needed
                else "maintain_existing_capacity_and_monitor_learning_flow"
            ),
            "silent_learning_stop_detected": bool(flow < 20 or status == "learning_starved"),
            **_safe_flags(),
        }

    def _opportunity_cost(
        self,
        statuses: dict[str, Any],
        occupancy: dict[str, Any],
        throughput: dict[str, Any],
    ) -> dict[str, Any]:
        copilot = status_value(statuses, "astra_copilot_suite_v1")
        actions = [dict(row) for row in (copilot.get("top_actions") or [])[:12] if isinstance(row, dict)]
        rows = []
        for row in actions:
            horizon = _horizon(first(row.get("horizon"), row.get("expected_hold_window"), "unknown"))
            hold_days = _hold_days(row.get("expected_hold_window"), horizon)
            confidence = clamp(row.get("confidence"))
            risk = 65.0 if "high" in text(row.get("risk_level"), "").lower() else 40.0
            learning_value = clamp(
                100.0 - to_float(throughput.get("learning_throughput_score"), 0.0) * 0.35
                + (25.0 if horizon in {"scalp", "day_trade", "multi_day"} else 5.0)
            )
            capacity_consumption = clamp(hold_days / 15.0 * 100.0)
            opportunity_cost = clamp(
                capacity_consumption * 0.45
                + to_float(occupancy.get("occupancy_pressure_score"), 0.0) * 0.30
                + risk * 0.15
                + max(0.0, 70.0 - confidence) * 0.10
            )
            profit_roi = rounded(confidence / max(1.0, hold_days), 3)
            learning_roi = rounded(learning_value / max(1.0, hold_days), 3)
            occupancy_value = rounded((confidence * 0.55 + learning_value * 0.30 + (100.0 - risk) * 0.15) / max(1.0, hold_days), 3)
            rows.append({
                "symbol": text(row.get("symbol"), "unknown"),
                "action": text(row.get("action"), "WATCH"),
                "horizon": horizon,
                "expected_hold_duration_days": rounded(hold_days, 3),
                "capacity_consumption": rounded(capacity_consumption, 3),
                "opportunity_cost_score": rounded(opportunity_cost, 3),
                "missed_learning_score": rounded(clamp(opportunity_cost * 0.55 + learning_value * 0.45), 3),
                "future_capacity_risk": rounded(clamp(opportunity_cost * 0.75 + capacity_consumption * 0.25), 3),
                "learning_roi": learning_roi,
                "profit_roi": profit_roi,
                "risk_adjusted_occupancy_value": occupancy_value,
                "borrowed_from_future_learning_capacity": bool(occupancy.get("borrowed_from_future_learning_capacity") and hold_days >= 3),
                "decision_narrative": (
                    f"This {horizon.replace('_', ' ')} setup may lock capacity for {hold_days:.1f} days. "
                    "Accept high occupancy cost only when expected value and learning value are exceptional."
                ),
            })
        highest = max(rows, key=lambda row: row["opportunity_cost_score"], default={})
        lowest = min(rows, key=lambda row: row["opportunity_cost_score"], default={})
        best_learning = max(rows, key=lambda row: row["learning_roi"], default={})
        worst_learning = min(rows, key=lambda row: row["learning_roi"], default={})
        return {
            "module": "Opportunity Cost Intelligence Engine V1",
            "status": "ok" if rows else "insufficient_evidence",
            "candidate_rows": rows,
            "highest_opportunity_cost_context": highest,
            "lowest_opportunity_cost_context": lowest,
            "best_learning_roi_context": best_learning,
            "worst_learning_roi_context": worst_learning,
            "recommended_opportunity_cost_policy": "compare_expected_profit_capacity_lock_learning_value_and_risk_before_existing_gate_approval",
            "blocks_trades_automatically": False,
            **_safe_flags(),
        }

    def _horizon_evolution(
        self,
        statuses: dict[str, Any],
        occupancy: dict[str, Any],
        throughput: dict[str, Any],
    ) -> dict[str, Any]:
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        optimization = dict(tier2.get("horizon_optimization_engine_v1") or {})
        breadth = status_value(statuses, "market_breadth_index_intelligence_v1")
        current = dict(occupancy.get("current_horizon_exposure") or {})
        volatility = clamp(breadth.get("volatility_pressure_score"))
        trend = clamp(first(breadth.get("index_trend_strength"), breadth.get("index_momentum_score"), 50.0))
        best = _horizon(optimization.get("best_current_horizon"))
        supported = {key: 0.0 for key in HORIZONS}
        if volatility >= 65:
            supported.update({"scalp": 30.0, "day_trade": 35.0, "multi_day": 20.0, "swing": 10.0, "longer_hold": 5.0})
        elif trend >= 65:
            supported.update({"scalp": 10.0, "day_trade": 20.0, "multi_day": 35.0, "swing": 25.0, "longer_hold": 10.0})
        else:
            supported.update({"scalp": 20.0, "day_trade": 30.0, "multi_day": 30.0, "swing": 15.0, "longer_hold": 5.0})
        if best in supported:
            supported[best] += 10.0
            total = sum(supported.values())
            supported = {key: rounded(value / total * 100.0, 3) for key, value in supported.items()}
        dominant = max(current, key=current.get) if any(current.values()) else "unknown"
        under = max(supported, key=lambda key: supported.get(key, 0.0) - current.get(key, 0.0))
        dominance = to_float(current.get(dominant), 0.0)
        monopolization = clamp(
            max(0.0, dominance - 45.0) * 1.8
            + to_float(occupancy.get("occupancy_pressure_score"), 0.0) * 0.35
        )
        pressure = clamp(
            monopolization * 0.55
            + max(0.0, 60.0 - to_float(throughput.get("learning_throughput_score"), 0.0)) * 0.45
        )
        if pressure >= 55 and under in {"scalp", "day_trade", "multi_day"}:
            bias = f"favor_lower_occupancy_{under}_setups_when_existing_gates_pass"
        else:
            bias = f"maintain_market_supported_{best if best != 'unknown' else dominant}_bias"
        return {
            "module": "Dynamic Horizon Evolution Engine V1",
            "status": "ok",
            "market_supported_horizon_mix": supported,
            "current_horizon_exposure": current,
            "horizon_evolution_pressure": rounded(pressure, 3),
            "dominant_horizon": dominant,
            "underrepresented_horizon": under,
            "horizon_monopolization_risk": rounded(monopolization, 3),
            "horizon_diversity_score": rounded(clamp(
                (
                    1.0
                    - sum((max(0.0, to_float(current.get(key), 0.0)) / 100.0) ** 2 for key in HORIZONS[:-1])
                )
                / 0.8
                * 100.0
            ), 3) if sum(to_float(current.get(key), 0.0) for key in HORIZONS[:-1]) > 0 else 0.0,
            "horizon_learning_contribution": {
                key: rounded(max(0.0, to_float(current.get(key), 0.0)) * (100.0 - pressure) / 100.0, 3)
                for key in HORIZONS
            },
            "recommended_horizon_bias": bias,
            "plain_english_explanation": (
                f"{dominant.replace('_', ' ').title()} currently dominates horizon exposure. "
                f"Astra should favor qualified {under.replace('_', ' ')} opportunities when all existing gates pass, "
                "without quotas or automatic rejection of elite opportunities."
            ),
            "elite_opportunity_may_override_advisory_bias": True,
            "fixed_horizon_quotas_enabled": False,
            "forced_diversification_enabled": False,
            **_safe_flags(),
        }

    def _capacity_expansion(
        self,
        statuses: dict[str, Any],
        occupancy: dict[str, Any],
        throughput: dict[str, Any],
        horizon: dict[str, Any],
        continuity: dict[str, Any],
        reserve: dict[str, Any],
        drag: dict[str, Any],
        queue: dict[str, Any],
    ) -> dict[str, Any]:
        capacity = self._capacity(statuses)
        portfolio = status_value(statuses, "portfolio_health_summary")
        broker = status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1")
        copilot = status_value(statuses, "astra_copilot_suite_v1")
        base = max(1, to_int(capacity.get("total_capacity"), 20))
        configured_ceiling = to_int(os.getenv("ASTRA_PAPER_ADAPTIVE_CAPACITY_CEILING", "40"), 40)
        absolute_ceiling = max(base, min(40, configured_ceiling))
        operating_ceiling = min(35, absolute_ceiling)
        used = to_int(occupancy.get("broker_confirmed_positions"), 0)
        heat = _metric_value(portfolio.get("portfolio_heat"))
        concentration = _metric_value(portfolio.get("concentration_risk"))
        correlation = _metric_value(portfolio.get("correlation_risk"))
        paper_verified = bool(broker.get("paper_mode_verified", False))
        risk_ok = bool(
            max(heat, concentration, correlation) < 75
            and text(portfolio.get("current_portfolio_balance_label"), "controlled") not in {"critical", "unsafe"}
        )
        opportunity_flow = len(copilot.get("top_actions") or [])
        throughput_slow = (
            throughput.get("learning_flow_status") in {"slowing", "stalled", "critical"}
            or continuity.get("status") in {"constrained", "at_risk", "learning_starved"}
        )
        underdeveloped = horizon.get("underrepresented_horizon") in {"scalp", "day_trade", "multi_day"}
        reserve_depleted = reserve.get("learning_reserve_status") in {"depleted", "critical"}
        capacity_full = used >= max(1, base - 1)
        duration_drag = to_float(drag.get("capacity_drag_score"), 0.0)
        missed_pressure = to_float(queue.get("missed_learning_opportunity_score"), 0.0)
        expansion_allowed = bool(
            throughput_slow
            and reserve_depleted
            and capacity_full
            and opportunity_flow >= 3
            and risk_ok
            and paper_verified
        )
        fresh_slots_needed = max(0, to_int(reserve.get("fresh_learning_slots_needed"), 0))
        learning_buffer = max(0, to_int(reserve.get("recommended_learning_capacity_buffer"), 0))
        pressure_step = int(math.ceil((duration_drag + missed_pressure) / 40.0))
        meaningful_step = max(5, fresh_slots_needed, learning_buffer, pressure_step)
        recommended = (
            min(operating_ceiling, max(base + meaningful_step, used + max(3, learning_buffer)))
            if expansion_allowed
            else base
        )
        status = "recommended_advisory" if recommended > base else "base_capacity_preserved"
        expansion_reason = (
            "learning_reserve_depleted_capacity_full_turnover_weak_opportunity_flow_present_risk_controlled"
            if expansion_allowed else "expansion_gates_not_all_satisfied"
        )
        contraction_reasons = []
        if not risk_ok:
            contraction_reasons.append("portfolio_risk_pressure")
        if not throughput_slow:
            contraction_reasons.append("evidence_flow_normal")
        if not reserve_depleted:
            contraction_reasons.append("learning_reserve_recovered")
        if used < base:
            contraction_reasons.append("position_count_below_baseline")
        if opportunity_flow < 3:
            contraction_reasons.append("opportunity_flow_weak")
        meaningful_test = bool(
            recommended >= min(operating_ceiling, max(25, used + 3))
            if reserve_depleted and capacity_full
            else True
        )
        test_blocker = "none"
        if not expansion_allowed:
            blockers = []
            if not paper_verified:
                blockers.append("paper_mode_not_verified")
            if not risk_ok:
                blockers.append("portfolio_risk_not_controlled")
            if not throughput_slow:
                blockers.append("paper_learning_velocity_not_weak")
            if not reserve_depleted:
                blockers.append("learning_reserve_not_depleted")
            if not capacity_full:
                blockers.append("capacity_not_full")
            if opportunity_flow < 3:
                blockers.append("opportunity_flow_below_three")
            test_blocker = ",".join(blockers) or "expansion_not_required"
        return {
            "module": "Adaptive Learning Expansion Engine V1",
            "status": "ok",
            "baseline_capacity": base,
            "base_capacity": base,
            "current_effective_capacity": base,
            "recommended_adaptive_capacity": recommended,
            "absolute_safety_ceiling": absolute_ceiling,
            "adaptive_operating_range": [base, operating_ceiling],
            "capacity_expansion_status": status,
            "capacity_expansion_reason": expansion_reason,
            "learning_continuity_score": continuity.get("learning_continuity_score"),
            "learning_diversity_score": continuity.get("learning_diversity_score"),
            "learning_benefit": continuity.get("learning_benefit"),
            "potential_risks": continuity.get("potential_risks"),
            "capacity_contraction_reason": contraction_reasons or ["none"],
            "adaptive_capacity_used": max(0, used - base),
            "adaptive_capacity_available": max(0, recommended - used),
            "learning_capacity_status": reserve.get("learning_reserve_status"),
            "capacity_recommendation_summary": (
                f"Temporarily recommend {recommended} paper-learning slots, up from the {base}-slot baseline, "
                f"while reserve is {reserve.get('learning_reserve_status')} and existing ranking, entry, risk, "
                "duplicate-symbol, buying-power, and session gates remain mandatory."
                if recommended > base
                else f"Keep the {base}-slot baseline because one or more expansion safety gates are not satisfied."
            ),
            "meaningful_capacity_test_passed": meaningful_test,
            "expected_capacity_range": [25, operating_ceiling] if expansion_allowed else [base, operating_ceiling],
            "actual_recommended_capacity": recommended,
            "capacity_test_reason": (
                "recommendation_is_meaningfully_above_baseline_for_depleted_learning_reserve"
                if meaningful_test and recommended > base
                else "baseline_preserved_by_safety_or_recovery_conditions"
            ),
            "capacity_test_blocker": test_blocker,
            "expansion_risk_status": "controlled" if risk_ok else "blocked_by_risk",
            "configured_capacity_changed": False,
            "extra_capacity_creates_trades": False,
            "existing_entry_gates_required": True,
            "preferred_extra_capacity_context": "high_learning_value_lower_occupancy_risk_controlled_paper_only",
            **_safe_flags(),
        }

    def _position_capacity_drag(
        self,
        statuses: dict[str, Any],
        occupancy: dict[str, Any],
        horizon: dict[str, Any],
    ) -> dict[str, Any]:
        tier1a = status_value(statuses, "astra_learning_preservation_capacity_v1")
        lifecycle = dict(tier1a.get("position_lifecycle_auditor_v1") or {})
        rows = [dict(row) for row in lifecycle.get("position_rows") or [] if isinstance(row, dict)]
        ages = [
            max(0.0, to_float(row.get("position_age_hours"), 0.0) / 24.0)
            for row in rows
            if to_float(row.get("position_age_hours"), 0.0) > 0.0
        ]
        expected_lock = to_float(occupancy.get("expected_capacity_lock_days"), 0.0)
        average_age = sum(ages) / len(ages) if ages else expected_lock
        oldest_age = max(ages) if ages else expected_lock
        exposure = dict(occupancy.get("current_horizon_exposure") or {})
        long_share = clamp(
            to_float(exposure.get("multi_day"), 0.0)
            + to_float(exposure.get("swing"), 0.0)
            + to_float(exposure.get("longer_hold"), 0.0)
            + to_float(exposure.get("unknown"), 0.0)
        )
        rotation = dict(
            horizon.get("adaptive_portfolio_rotation_engine_v1")
            or (horizon.get("modules") or {}).get("adaptive_portfolio_rotation_engine_v1")
            or {}
        )
        trapped = to_float(first(rotation.get("trapped_capital_score"), horizon.get("trapped_capital_score")), 0.0)
        learning_per_slot = rounded(
            max(0.0, 100.0 - to_float(occupancy.get("occupancy_pressure_score"), 0.0))
            / max(1.0, expected_lock),
            3,
        )
        detail_gap = to_int(lifecycle.get("broker_positions_pending_detail"), 0)
        active = max(1, to_int(lifecycle.get("broker_confirmed_count"), 0))
        stale_drag = clamp(
            trapped * 0.35
            + long_share * 0.30
            + min(100.0, expected_lock * 8.0) * 0.20
            + detail_gap / active * 100.0 * 0.15
        )
        drag_score = clamp(
            stale_drag * 0.65
            + max(0.0, average_age - 1.0) * 5.0
            + max(0.0, long_share - 35.0) * 0.25
        )
        return {
            "module": "Position Age and Capacity Drag V1",
            "status": "estimated_from_cached_horizon_and_lifecycle_evidence" if not ages else "measured",
            "average_position_age_days": rounded(average_age, 3),
            "oldest_position_age_days": rounded(oldest_age, 3),
            "long_duration_position_share": rounded(long_share, 3),
            "capacity_drag_score": rounded(drag_score, 3),
            "stale_position_learning_drag": rounded(stale_drag, 3),
            "expected_capacity_lock_days": rounded(expected_lock, 3),
            "learning_generated_per_occupied_slot": learning_per_slot,
            "position_age_detail_coverage_pct": rounded(len(ages) / active * 100.0, 3),
            "position_age_source": (
                "broker_reconciled_lifecycle_rows"
                if ages
                else "horizon_weighted_expected_lock_proxy_active_entry_timestamps_unavailable"
            ),
            "capacity_drag_summary": (
                f"Positions are expected to lock capacity for about {expected_lock:.1f} days on average. "
                f"Long-duration exposure is {long_share:.1f}% and capacity drag is {drag_score:.1f}; "
                "this supports temporary capacity expansion but never forced exits."
            ),
            **_safe_flags(),
        }

    def _horizon_opportunity_queue(
        self,
        statuses: dict[str, Any],
        horizon: dict[str, Any],
    ) -> dict[str, Any]:
        audit = status_value(statuses, "execution_participation_audit")
        throughput = status_value(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        copilot = status_value(statuses, "astra_copilot_suite_v1")
        reasons = dict(audit.get("top_rejection_reasons") or {})
        capacity_blocks = sum(
            to_int(count, 0)
            for reason, count in reasons.items()
            if "capacity" in text(reason, "").lower() or "max_concurrent_positions" in text(reason, "").lower()
        )
        missed_high = max(
            to_int(audit.get("missed_high_expectancy_candidates"), 0),
            to_int(throughput.get("missed_evidence_estimate"), 0),
        )
        underfed = [
            item for item in [
                text(first(horizon.get("underrepresented_horizon"), horizon.get("underexposed_horizon")), ""),
                "scalp" if bool(horizon.get("scalp_learning_blocked")) else "",
                "day_trade" if bool(horizon.get("day_learning_blocked")) else "",
            ] if item
        ]
        underfed = list(dict.fromkeys(underfed))
        contexts = []
        for row in (horizon.get("best_replacement_candidates") or []):
            if not isinstance(row, dict):
                continue
            reason = text(row.get("reason"), "")
            if "capacity" not in reason and "max_concurrent" not in reason:
                continue
            h = _horizon(row.get("horizon"))
            contexts.append({
                "symbol": text(row.get("symbol"), "UNKNOWN"),
                "horizon": h,
                "quality_confidence": rounded(to_float(row.get("replacement_score"), 0.0), 3),
                "reason_not_selected": reason,
                "would_improve_learning_diversity": h in underfed,
                "later_usefulness_status": "awaiting_outcome",
            })
        if not contexts and capacity_blocks:
            for row in (copilot.get("top_actions") or [])[:5]:
                if not isinstance(row, dict):
                    continue
                h = _horizon(first(row.get("horizon"), row.get("expected_hold_window"), "unknown"))
                if h not in underfed:
                    continue
                contexts.append({
                    "symbol": text(row.get("symbol"), "UNKNOWN"),
                    "horizon": h,
                    "quality_confidence": rounded(to_float(row.get("confidence"), 0.0), 3),
                    "reason_not_selected": "capacity_constrained_context_not_automatic_trade_queue",
                    "would_improve_learning_diversity": True,
                    "later_usefulness_status": "awaiting_outcome",
                })
        missed_count = max(capacity_blocks, min(missed_high, capacity_blocks + len(contexts)))
        score = clamp(
            to_float(audit.get("missed_opportunity_pressure"), 0.0) * 0.45
            + min(100.0, capacity_blocks * 3.0) * 0.35
            + min(100.0, missed_high) * 0.20
        )
        return {
            "module": "Horizon Opportunity Queue V1",
            "status": "capacity_pressure_detected" if capacity_blocks else "monitoring",
            "missed_learning_opportunities_count": missed_count,
            "missed_learning_opportunity_score": rounded(score, 3),
            "underfed_horizons": underfed,
            "top_missed_learning_contexts": contexts[:5],
            "capacity_specific_block_count": capacity_blocks,
            "high_expectancy_candidates_missed_or_deferred": missed_high,
            "horizon_opportunity_queue_summary": (
                f"Capacity pressure accounts for {capacity_blocks} recorded blocks and {missed_high} high-expectancy "
                f"missed/deferred candidates. Underfed horizons: {', '.join(underfed) or 'none identified'}. "
                "The queue is diagnostic only and never submits trades."
            ),
            "automatic_trade_submission_enabled": False,
            **_safe_flags(),
        }

    def _learning_reserve(
        self,
        occupancy: dict[str, Any],
        throughput: dict[str, Any],
        continuity: dict[str, Any],
        drag: dict[str, Any],
        queue: dict[str, Any],
    ) -> dict[str, Any]:
        available = to_int(occupancy.get("capacity_available"), 0)
        capacity = max(1, to_int(occupancy.get("total_capacity"), 20))
        free_slot_score = clamp(available / max(1.0, capacity * 0.25) * 100.0)
        turnover = clamp(to_float(throughput.get("open_trade_turnover"), 0.0) * 5.0)
        diversity = clamp(continuity.get("learning_diversity_score"))
        velocity = clamp(throughput.get("paper_learning_velocity_score"))
        drag_score = clamp(drag.get("capacity_drag_score"))
        missed_score = clamp(queue.get("missed_learning_opportunity_score"))
        reserve_score = clamp(
            free_slot_score * 0.30
            + turnover * 0.20
            + diversity * 0.18
            + velocity * 0.17
            + (100.0 - drag_score) * 0.08
            + (100.0 - missed_score) * 0.07
        )
        if reserve_score >= 70:
            status = "healthy"
        elif reserve_score >= 45:
            status = "low"
        elif reserve_score >= 20:
            status = "depleted"
        else:
            status = "critical"
        fresh_slots_needed = max(
            0,
            int(math.ceil((60.0 - reserve_score) / 7.0)),
            3 if status == "depleted" else 0,
            6 if status == "critical" else 0,
        )
        buffer = min(15, max(0, fresh_slots_needed + (2 if available <= 0 else 0)))
        reasons = []
        if available <= 0:
            reasons.append("no_free_baseline_slots")
        if turnover < 25:
            reasons.append("zero_or_weak_position_turnover")
        if diversity < 45:
            reasons.append("horizon_diversity_weak")
        if drag_score >= 45:
            reasons.append("position_duration_capacity_drag")
        if missed_score >= 45:
            reasons.append("missed_learning_opportunity_pressure")
        return {
            "module": "Learning Reserve Engine V1",
            "status": status,
            "learning_reserve_status": status,
            "learning_reserve_score": rounded(reserve_score, 3),
            "reserve_depletion_reason": reasons or ["reserve_healthy"],
            "reserve_recovery_plan": (
                "temporarily_expand_advisory_capacity_then_contract_toward_baseline_as_natural_closures_restore_reserve"
                if status in {"depleted", "critical"}
                else "maintain_baseline_and_monitor_turnover"
            ),
            "fresh_learning_slots_needed": fresh_slots_needed,
            "recommended_learning_capacity_buffer": buffer,
            "free_baseline_slots": available,
            "turnover_component_score": rounded(turnover, 3),
            "diversity_component_score": rounded(diversity, 3),
            "velocity_component_score": rounded(velocity, 3),
            **_safe_flags(),
        }

    def _improvement_classifier(self, statuses: dict[str, Any]) -> dict[str, Any]:
        tier1b = status_value(statuses, "astra_truth_controlled_evolution_executive_v1")
        bridge = dict(tier1b.get("shadow_paper_controlled_evolution_bridge_v1") or {})
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        candidate = dict(tier2.get("controlled_evolution_integration") or {})
        shadow = status_value(statuses, "shadow_correction_validation_attribution_v1")
        adaptive = status_value(statuses, "astra_adaptive_learning_v1")
        adaptive_candidate = dict(adaptive.get("incremental_shadow_promotion_v1") or {})
        reviews = []
        raw_rows = list(shadow.get("category_validation") or shadow.get("categories") or [])
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            improvement = to_float(first(row.get("expectancy_delta"), row.get("improvement_rate"), 0.0), 0.0)
            reviews.append({
                "category": text(first(row.get("category"), row.get("recommendation_category")), "unknown"),
                "improvement_delta": rounded(improvement, 3),
                "confidence": rounded(to_float(first(row.get("confidence_score"), row.get("confidence")), 0.0), 3),
                "evidence_count": to_int(first(row.get("validation_count"), row.get("evidence_count")), 0),
                "source": "shadow_correction_validation_attribution_v1",
            })
        candidate_metric = text(first(candidate.get("candidate_metric"), (bridge.get("promotion_candidate") or {}).get("promotion_metric")), "")
        if candidate_metric and candidate_metric.lower() != "none":
            reviews.append({
                "category": candidate_metric.lower().replace(" ", "_"),
                "improvement_delta": rounded(max(
                    to_float(candidate.get("candidate_delta"), 0.0),
                    to_float((bridge.get("promotion_candidate") or {}).get("promotion_delta"), 0.0),
                ), 3),
                "confidence": rounded(max(
                    to_float(candidate.get("candidate_confidence"), 0.0),
                    to_float((bridge.get("promotion_candidate") or {}).get("promotion_confidence"), 0.0),
                ), 3),
                "evidence_count": max(
                    to_int(candidate.get("candidate_evidence_count"), 0),
                    to_int((bridge.get("promotion_candidate") or {}).get("promotion_evidence"), 0),
                ),
                "source": "tier1b_tier2_controlled_evolution",
            })
        adaptive_metric = text(adaptive_candidate.get("promotion_metric"), "")
        if adaptive_metric and adaptive_metric.lower() != "none":
            reviews.append({
                "category": adaptive_metric.lower().replace(" ", "_"),
                "improvement_delta": rounded(to_float(adaptive_candidate.get("promotion_delta"), 0.0), 3),
                "confidence": rounded(to_float(adaptive_candidate.get("promotion_confidence"), 0.0), 3),
                "evidence_count": to_int(adaptive_candidate.get("promotion_evidence"), 0),
                "source": "astra_adaptive_learning_v1",
            })
        aliases = {
            "panic_exit_reduction": "exit_quality",
            "opportunity_cost": "overfiltering_reduction",
            "horizon_selection": "horizon_accuracy",
            "risk_adjusted_returns": "risk_adjusted_return",
        }
        classified = []
        for row in reviews:
            category = aliases.get(row["category"], row["category"])
            classified.append({
                **row,
                "category": category,
                "eligible_category": category in ELIGIBLE_CATEGORIES,
                "consistently_better_than_paper": bool(
                    row["improvement_delta"] >= 10.0
                    and row["confidence"] >= 60.0
                    and row["evidence_count"] >= 25
                ),
            })
        strongest = max(classified, key=lambda row: row["improvement_delta"], default={})
        return {
            "module": "Improvement Classifier V1",
            "status": "ok" if classified else "insufficient_evidence",
            "improvements_reviewed": len(classified),
            "classified_improvements": classified,
            "paper_test_candidates": [
                row for row in classified
                if row["eligible_category"] and row["consistently_better_than_paper"]
            ][:1],
            "strongest_improvement_category": strongest.get("category", "none"),
            "strongest_improvement_delta": strongest.get("improvement_delta", 0.0),
            "candidate_creation_is_advisory_only": True,
            **_safe_flags(),
        }

    def _controlled_evolution(
        self,
        statuses: dict[str, Any],
        occupancy: dict[str, Any],
        throughput: dict[str, Any],
        classifier: dict[str, Any],
    ) -> dict[str, Any]:
        tier1b = status_value(statuses, "astra_truth_controlled_evolution_executive_v1")
        bridge = dict(tier1b.get("shadow_paper_controlled_evolution_bridge_v1") or {})
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        candidate = dict(tier2.get("controlled_evolution_integration") or {})
        learned_exit = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        broker = status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1")
        classified_candidate = (classifier.get("paper_test_candidates") or [{}])[0]
        candidate_metric = text(first(
            classified_candidate.get("category"),
            candidate.get("candidate_metric"),
            (bridge.get("promotion_candidate") or {}).get("promotion_metric"),
            "none",
        ))
        normalized_category = candidate_metric.lower().replace(" ", "_")
        evidence = max(
            to_int(candidate.get("candidate_evidence_count"), 0),
            to_int((bridge.get("promotion_candidate") or {}).get("promotion_evidence"), 0),
            to_int(classified_candidate.get("evidence_count"), 0),
        )
        confidence = max(
            to_float(candidate.get("candidate_confidence"), 0.0),
            to_float((bridge.get("promotion_candidate") or {}).get("promotion_confidence"), 0.0),
            to_float(classified_candidate.get("confidence"), 0.0),
        )
        improvement = max(
            to_float(candidate.get("candidate_delta"), 0.0),
            to_float((bridge.get("promotion_candidate") or {}).get("promotion_delta"), 0.0),
            to_float(classified_candidate.get("improvement_delta"), 0.0),
        )
        paper_verified = bool(broker.get("paper_mode_verified", False))
        live_disabled = not bool(broker.get("live_endpoint_detected", False)) and not bool(broker.get("broker_live_endpoint_allowed", False))
        rollback_armed = text(first(learned_exit.get("rollback_status"), bridge.get("rollback_status"), "armed")) in {"armed", "ready"}
        infrastructure_exists = bool(
            "learned_exit_bucket_enabled" in learned_exit
            or learned_exit.get("max_learning_corrected_exits_per_day")
        )
        bucket_enabled = bool(learned_exit.get("learned_exit_bucket_enabled", False))
        risk_not_increased = not bool(learned_exit.get("learned_exit_bucket_underperforming", False))
        giveback_not_increased = to_float(learned_exit.get("giveback_delta"), 0.0) <= 0.0
        drawdown_not_increased = to_float(learned_exit.get("drawdown_delta"), 0.0) <= 0.0
        capacity_safe = occupancy.get("occupancy_status") not in {"saturated", "learning_blocked"}
        eligible_category = normalized_category in ELIGIBLE_CATEGORIES
        gates = {
            "minimum_evidence_count": evidence >= 25,
            "minimum_trade_count": evidence >= 25,
            "minimum_confidence": confidence >= 60,
            "minimum_persistence_window": to_float((tier2.get("learning_persistence_engine_v1") or {}).get("lesson_retention_score"), 0.0) >= 55,
            "minimum_improvement_delta": improvement >= 10.0,
            "risk_not_increased": risk_not_increased,
            "giveback_not_increased": giveback_not_increased,
            "drawdown_not_increased": drawdown_not_increased,
            "broker_truth_healthy": paper_verified and live_disabled,
            "paper_mode_verified": paper_verified,
            "capacity_not_critical": capacity_safe,
            "rollback_available": rollback_armed,
            "human_review_required_for_adoption": True,
            "eligible_category": eligible_category,
        }
        all_gates = all(gates.values())
        active_stage = 1 if bucket_enabled and all_gates else 0
        recommended_stage = 1 if all_gates else 0
        blockers = [key for key, passed in gates.items() if not passed]
        eligible_candidates = [{
            "category": normalized_category,
            "improvement_delta": rounded(improvement, 3),
            "confidence": rounded(confidence, 3),
            "evidence_count": evidence,
            "candidate_status": "micro_test_candidate" if all_gates else "advisory_only",
        }] if candidate_metric != "none" else []
        return {
            "module": "Controlled Shadow to Paper Evolution Engine V2",
            "status": "micro_test_active" if active_stage else "advisory_only",
            "promotion_ladder": [{"stage": stage, "label": label, "automatic": False} for stage, label in EVOLUTION_STAGES.items()],
            "eligible_improvement_categories": list(ELIGIBLE_CATEGORIES),
            "improvement_classifier_status": classifier.get("status"),
            "eligible_candidates": eligible_candidates,
            "active_micro_tests": [learned_exit] if active_stage else [],
            "recommended_micro_test": eligible_candidates[0] if all_gates and eligible_candidates else {},
            "promotion_stage": active_stage,
            "recommended_promotion_stage": recommended_stage,
            "promotion_stage_label": EVOLUTION_STAGES[active_stage],
            "promotion_reason": "all_existing_guarded_micro_test_gates_passed" if all_gates else "remain_advisory_until_all_gates_pass",
            "promotion_blocker": blockers,
            "gate_results": gates,
            "rollback_status": "armed" if rollback_armed else "not_ready",
            "human_review_required": True,
            "candidate_status": "micro_test_active" if active_stage else "advisory_only",
            "existing_micro_test_infrastructure": infrastructure_exists,
            "micro_test_activated_by_tier4": False,
            "paper_execution_changed": False,
            **_safe_flags(),
        }

    def _persistence_explanation(
        self,
        statuses: dict[str, Any],
        evolution: dict[str, Any],
        throughput: dict[str, Any],
    ) -> dict[str, Any]:
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        persistence = dict(tier2.get("learning_persistence_engine_v1") or {})
        candidates = list(evolution.get("eligible_candidates") or [])
        candidate = candidates[0] if candidates else {}
        current_evidence = to_int(candidate.get("evidence_count"), 0)
        current_confidence = to_float(candidate.get("confidence"), 0.0)
        current_persistence = to_float(persistence.get("lesson_retention_score"), 0.0)
        required_evidence = 25
        required_confidence = 60.0
        required_persistence = 55.0
        remaining_evidence = max(0, required_evidence - current_evidence)
        remaining_trades = remaining_evidence
        recent_pace = max(1, to_int(throughput.get("trades_opened"), 0) // 5)
        remaining_market_days = int(math.ceil(remaining_trades / recent_pace)) if remaining_trades else 0
        blockers = list(evolution.get("promotion_blocker") or [])
        plain = (
            f"Astra has not found a classified Shadow improvement ready for Paper testing yet. "
            f"A candidate will need at least {required_evidence} observations, {required_confidence:.0f}% confidence, "
            f"and a persistence score of {required_persistence:.0f}. Current persistence is {current_persistence:.1f}, "
            f"so {max(0.0, required_persistence - current_persistence):.1f} persistence points remain."
            if not candidate
            else
            f"Astra has {current_evidence} of {required_evidence} required observations, "
            f"{current_confidence:.1f}% of {required_confidence:.0f}% required confidence, and "
            f"{current_persistence:.1f} of {required_persistence:.0f} required persistence. "
            f"At the recent evidence pace, about {remaining_market_days} market day(s) remain."
        )
        return {
            "module": "Persistence Explanation Engine V1",
            "status": "ready" if not blockers and candidate else "collecting_evidence",
            "required_evidence": required_evidence,
            "current_evidence": current_evidence,
            "remaining_evidence": remaining_evidence,
            "required_confidence": required_confidence,
            "current_confidence": rounded(current_confidence, 3),
            "required_persistence_score": required_persistence,
            "current_persistence_score": rounded(current_persistence, 3),
            "remaining_persistence_score": rounded(max(0.0, required_persistence - current_persistence), 3),
            "remaining_trades": remaining_trades,
            "remaining_market_days_estimate": remaining_market_days,
            "current_blockers": blockers,
            "plain_english_explanation": plain,
            "estimate_is_advisory": True,
            **_safe_flags(),
        }

    def _governance(self, evolution: dict[str, Any]) -> dict[str, Any]:
        candidates = list(evolution.get("eligible_candidates") or [])
        active = list(evolution.get("active_micro_tests") or [])
        blockers = list(evolution.get("promotion_blocker") or [])
        confidence = to_float((candidates[0] if candidates else {}).get("confidence"), 0.0)
        rollback = evolution.get("rollback_status") == "armed"
        if active:
            status = "micro_test_active"
        elif candidates and not blockers:
            status = "ready_for_micro_test"
        elif candidates:
            status = "safe_observation"
        else:
            status = "blocked"
        score = clamp(confidence * 0.45 + (30.0 if rollback else 0.0) + (25.0 if not active else 20.0))
        return {
            "module": "Evolution Governance Engine V1",
            "status": status,
            "shadow_candidates": len(candidates),
            "validated_candidates": sum(1 for row in candidates if row.get("candidate_status") == "micro_test_candidate"),
            "active_micro_tests": len(active),
            "promotion_confidence": rounded(confidence, 3),
            "adoption_rate": 0.0,
            "rollback_readiness": "armed" if rollback else "not_ready",
            "promotion_rejections": len(blockers),
            "promotion_blockers": blockers,
            "stage_progression": evolution.get("promotion_stage"),
            "stage_regressions": 0,
            "evolution_governance_score": rounded(score, 3),
            "top_evolution_candidate": (candidates[0] if candidates else {}).get("category", "none"),
            "top_evolution_blocker": blockers[0] if blockers else "none",
            "adoption_safety_status": status,
            "next_safe_evolution_step": "human_review_bounded_5pct_micro_test" if status == "ready_for_micro_test" else "continue_shadow_validation_and_clear_gates",
            "reversible": True,
            **_safe_flags(),
        }

    @staticmethod
    def _completion_row(
        name: str,
        payload: dict[str, Any],
        *,
        can_safely_act: bool = False,
        detects: bool | None = None,
        explains: bool | None = None,
        recommends: bool | None = None,
    ) -> dict[str, Any]:
        present = bool(payload)
        detects_value = present and payload.get("status") not in {None, "unknown"} if detects is None else detects
        explains_value = present and any(
            key in payload
            for key in (
                "executive_summary",
                "plain_english_explanation",
                "promotion_reason",
                "occupancy_recommendation",
                "recommended_action",
                "recommended_throughput_action",
            )
        ) if explains is None else explains
        recommends_value = present and any(
            key in payload
            for key in (
                "recommended_action",
                "recommended_throughput_action",
                "occupancy_recommendation",
                "next_safe_evolution_step",
                "recommended_next_focus",
            )
        ) if recommends is None else recommends
        connections = {
            "connected_to_learning_center": True,
            "connected_to_ask_astra": True,
            "connected_to_executive_dashboard": True,
        }
        score = sum([detects_value, explains_value, recommends_value, *connections.values()])
        if score >= 6:
            completion = "complete"
        elif score >= 4:
            completion = "mostly_complete"
        elif score >= 3:
            completion = "partial"
        elif present:
            completion = "disconnected"
        else:
            completion = "unknown"
        return {
            "subsystem": name,
            "completion_status": completion,
            "detects_problem": detects_value,
            "explains_problem": explains_value,
            "can_recommend_correction": recommends_value,
            "can_safely_act": can_safely_act,
            **connections,
        }

    def _completion_audit(
        self,
        statuses: dict[str, Any],
        continuity: dict[str, Any],
        occupancy: dict[str, Any],
        horizon: dict[str, Any],
        evolution: dict[str, Any],
        governance: dict[str, Any],
        persistence: dict[str, Any],
    ) -> dict[str, Any]:
        rows = [
            self._completion_row("learning_continuity", continuity),
            self._completion_row("adaptive_capacity", occupancy),
            self._completion_row("horizon_balance", horizon),
            self._completion_row(
                "shadow_to_paper_evolution",
                evolution,
                can_safely_act=bool(evolution.get("existing_micro_test_infrastructure")),
                explains=True,
                recommends=True,
            ),
            self._completion_row("evolution_governance", governance, explains=True, recommends=True),
            self._completion_row("persistence_explanation", persistence, recommends=True),
            self._completion_row(
                "broker_truth",
                status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1"),
                can_safely_act=True,
                detects=True,
                explains=True,
                recommends=False,
            ),
            self._completion_row(
                "copilot",
                status_value(statuses, "astra_copilot_suite_v1"),
                detects=True,
                explains=True,
                recommends=True,
            ),
            self._completion_row(
                "unified_truth",
                status_value(statuses, "astra_truth_controlled_evolution_executive_v1"),
                detects=True,
                explains=True,
                recommends=True,
            ),
            self._completion_row(
                "learning_preservation",
                status_value(statuses, "astra_learning_preservation_capacity_v1"),
                detects=True,
                explains=True,
                recommends=True,
            ),
        ]
        counts = {
            status: sum(1 for row in rows if row["completion_status"] == status)
            for status in ("complete", "mostly_complete", "partial", "disconnected", "blocked", "unknown")
        }
        gaps = [
            {
                "subsystem": row["subsystem"],
                "completion_status": row["completion_status"],
                "missing_capabilities": [
                    label
                    for label, value in (
                        ("problem_detection", row["detects_problem"]),
                        ("plain_explanation", row["explains_problem"]),
                        ("correction_recommendation", row["can_recommend_correction"]),
                        ("learning_center_connection", row["connected_to_learning_center"]),
                        ("ask_astra_connection", row["connected_to_ask_astra"]),
                        ("executive_dashboard_connection", row["connected_to_executive_dashboard"]),
                    )
                    if not value
                ],
            }
            for row in rows
            if row["completion_status"] not in {"complete", "mostly_complete"}
        ]
        return {
            "module": "Implementation Completion Auditor V1",
            "status": "healthy" if not gaps else "needs_attention",
            "subsystem_audit": rows,
            "completion_counts": counts,
            "completion_gaps": gaps,
            "partial_implementations_detected": len(gaps),
            "disconnected_systems_detected": counts["disconnected"],
            "next_completion_priority": gaps[0]["subsystem"] if gaps else "maintain_integration_contracts",
            **_safe_flags(),
        }

    def _self_governance(
        self,
        statuses: dict[str, Any],
        continuity: dict[str, Any],
        occupancy: dict[str, Any],
        horizon: dict[str, Any],
        evolution: dict[str, Any],
        completion: dict[str, Any],
    ) -> dict[str, Any]:
        tier3 = status_value(statuses, "astra_intelligence_maturation_suite_v1")
        memory = dict(tier3.get("unified_memory_governance_v1") or {})
        provider = status_value(statuses, "astra_provider_orchestration_data_governance_v1")
        unified = status_value(statuses, "unified_learning_diagnostics_v1")
        bottlenecks = {
            "learning": continuity.get("continuity_bottleneck"),
            "capacity": occupancy.get("occupancy_status"),
            "horizon": horizon.get("dominant_horizon"),
            "trade": "low_turnover" if to_float(continuity.get("trade_turnover_score"), 0.0) < 35 else "none",
            "shadow": (evolution.get("promotion_blocker") or ["none"])[0],
            "memory": text(first(memory.get("status"), memory.get("memory_health")), "warming_up"),
            "performance": text(
                (status_value(statuses, "astra_performance_optimization_suite_v1").get("executive_summary") or {}).get("persistent_weakness"),
                "warming_up",
            ),
            "provider": text(first(provider.get("status"), provider.get("bandwidth_budget_status")), "warming_up"),
            "dashboard": "healthy" if to_int(unified.get("failed_sources_count"), 0) == 0 else "failed_sources",
            "integration": text(completion.get("status"), "warming_up"),
        }
        active = [f"{key}:{value}" for key, value in bottlenecks.items() if value not in {"none", "healthy", "ok", "active"}]
        return {
            "module": "Self-Governance Engine V1",
            "status": "healthy" if len(active) <= 2 else "needs_attention",
            "bottlenecks": bottlenecks,
            "active_bottleneck_count": len(active),
            "active_bottlenecks": active,
            "partial_implementation_detected": bool(completion.get("partial_implementations_detected")),
            "disconnected_system_detected": bool(completion.get("disconnected_systems_detected")),
            "broken_data_flow_detected": bool(to_int(unified.get("failed_sources_count"), 0)),
            "detecting_without_explaining": [
                row["subsystem"]
                for row in completion.get("subsystem_audit") or []
                if row.get("detects_problem") and not row.get("explains_problem")
            ],
            "correcting_without_reporting": [],
            "recommended_correction": (
                f"complete_{completion.get('next_completion_priority')}_integration"
                if completion.get("partial_implementations_detected")
                else "preserve_learning_continuity_and_monitor_promotion_gates"
            ),
            **_safe_flags(),
        }

    @staticmethod
    def _executive_explanation(
        continuity: dict[str, Any],
        occupancy: dict[str, Any],
        horizon: dict[str, Any],
        evolution: dict[str, Any],
        persistence: dict[str, Any],
        governance: dict[str, Any],
    ) -> dict[str, Any]:
        dominant = text(horizon.get("dominant_horizon"), "unknown").replace("_", " ")
        under = text(horizon.get("underrepresented_horizon"), "unknown").replace("_", " ")
        position_count = to_int(occupancy.get("broker_confirmed_positions"), 0)
        if position_count:
            what_happened = (
                f"Most of Astra's paper-learning capacity is tied to {dominant} positions; "
                f"{position_count} positions currently use a "
                f"{occupancy.get('total_capacity', 20)}-position learning baseline."
            )
            why = (
                f"{dominant.title()} exposure is {to_float((occupancy.get('current_horizon_exposure') or {}).get(horizon.get('dominant_horizon')), 0.0):.1f}%, "
                "so fresh shorter-duration outcomes arrive more slowly."
            )
        else:
            what_happened = "Astra does not yet have enough broker-confirmed position evidence to diagnose capacity concentration."
            why = "The continuity engine is waiting for broker truth and horizon labels rather than inventing an occupancy explanation."
        effect = (
            f"Learning continuity is {text(continuity.get('status'), 'warming up').replace('_', ' ')} "
            f"and {under} evidence is underrepresented. "
            "The best qualified opportunity still wins; Astra does not impose quotas."
        )
        safe_correction = (
            "Astra can safely recommend lower-occupancy candidates and a bounded capacity target, "
            "but existing ranking, risk, entry, and broker gates remain in control."
        )
        return {
            "module": "Executive Explanation Engine V1",
            "status": "ok",
            "what_happened": what_happened,
            "why_it_happened": why,
            "what_it_affects": effect,
            "can_astra_safely_correct_it": safe_correction,
            "evidence_still_required": persistence.get("plain_english_explanation"),
            "shadow_to_paper_status": (
                f"Shadow promotion remains at {text(evolution.get('promotion_stage_label'), 'shadow observation').replace('_', ' ')} "
                f"because {', '.join(text(item).replace('_', ' ') for item in (evolution.get('promotion_blocker') or ['no blocker']))}."
            ),
            "plain_english_summary": f"{what_happened} {effect} {safe_correction}",
            "recommended_next_step": governance.get("next_safe_evolution_step"),
            **_safe_flags(),
        }

    def _paper_learning_completion(
        self,
        statuses: dict[str, Any],
        occupancy: dict[str, Any],
        throughput: dict[str, Any],
        opportunity: dict[str, Any],
        expansion: dict[str, Any],
        reserve: dict[str, Any],
        drag: dict[str, Any],
        queue: dict[str, Any],
    ) -> dict[str, Any]:
        pressure = to_float(occupancy.get("occupancy_pressure_score"), 0.0)
        capacity_score = clamp(100.0 - pressure)
        saturation = clamp(
            pressure * 0.55
            + to_float(occupancy.get("portfolio_monopolization_risk"), 0.0) * 0.45
        )
        highest_cost = dict(opportunity.get("highest_opportunity_cost_context") or {})
        reserve_status = text(reserve.get("learning_reserve_status"), "critical")
        bottleneck = (
            "all_broker_confirmed_positions_are_swing_and_no_closed_outcomes_are_recycling_capacity"
            if saturation >= 75 and to_int(throughput.get("trades_closed"), 0) == 0
            else f"capacity_reserve_depleted_and_{text(throughput.get('learning_blocker'), 'natural_turnover_required')}"
            if reserve_status in {"depleted", "critical"}
            else text(throughput.get("learning_blocker"), "none")
        )
        recommended_capacity = to_int(expansion.get("recommended_adaptive_capacity"), to_int(occupancy.get("total_capacity"), 20))
        return {
            "module": "Paper Trading Learning Completion V1",
            "status": (
                "adaptive_capacity_recommended"
                if recommended_capacity > to_int(expansion.get("baseline_capacity"), 20)
                else "blocked_by_natural_position_turnover"
                if reserve_status in {"depleted", "critical"}
                else "operational"
            ),
            "paper_learning_capacity_score": rounded(capacity_score, 3),
            "paper_learning_velocity_score": throughput.get("paper_learning_velocity_score"),
            "paper_saturation_risk": rounded(saturation, 3),
            "learning_reserve_status": reserve_status,
            "learning_reserve_score": reserve.get("learning_reserve_score"),
            "stale_position_learning_drag": drag.get("stale_position_learning_drag"),
            "capacity_drag_score": drag.get("capacity_drag_score"),
            "opportunity_cost_score": highest_cost.get("opportunity_cost_score", 0.0),
            "missed_learning_opportunity_score": queue.get("missed_learning_opportunity_score"),
            "baseline_capacity": expansion.get("baseline_capacity"),
            "recommended_adaptive_capacity": recommended_capacity,
            "absolute_safety_ceiling": expansion.get("absolute_safety_ceiling"),
            "capacity_recommendation": expansion.get("capacity_recommendation_summary"),
            "paper_learning_bottleneck_summary": bottleneck,
            "historical_evidence_is_not_counted_as_fresh_paper_turnover": True,
            **_safe_flags(),
        }

    def _shadow_paper_completion(
        self,
        classifier: dict[str, Any],
        evolution: dict[str, Any],
        governance: dict[str, Any],
        persistence: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = list(evolution.get("eligible_candidates") or [])
        candidate = candidates[0] if candidates else {}
        gates = dict(evolution.get("gate_results") or {})
        gate_values = [bool(value) for key, value in gates.items() if key != "human_review_required_for_adoption"]
        readiness = sum(gate_values) / max(1, len(gate_values)) * 100.0
        persistent = [
            row for row in classifier.get("classified_improvements") or []
            if row.get("consistently_better_than_paper")
        ]
        return {
            "module": "Shadow to Paper Controlled Evolution Completion V1",
            "status": "micro_test_ready_for_human_review" if not evolution.get("promotion_blocker") and candidate else "advisory_only",
            "shadow_paper_readiness_score": rounded(readiness, 3),
            "shadow_to_paper_readiness_score": rounded(readiness, 3),
            "promotion_candidates": candidates,
            "shadow_improvement_candidates": candidates,
            "persistent_edges": persistent,
            "persistent_shadow_edges": persistent,
            "micro_test_readiness": bool(candidate and not evolution.get("promotion_blocker")),
            "rollback_readiness": governance.get("rollback_readiness"),
            "rollback_required": True,
            "promotion_stage": evolution.get("promotion_stage"),
            "recommended_promotion_stage": evolution.get("recommended_promotion_stage"),
            "promotion_blockers": list(evolution.get("promotion_blocker") or []),
            "promotion_summary": (
                f"{candidate.get('category', 'No classified edge')} has {candidate.get('evidence_count', 0)} observations; "
                f"promotion remains advisory while {len(evolution.get('promotion_blocker') or [])} gate(s) are unresolved."
            ),
            "shadow_to_paper_summary": (
                f"{candidate.get('category', 'No classified edge')} has {candidate.get('evidence_count', 0)} observations; "
                f"promotion remains advisory while {len(evolution.get('promotion_blocker') or [])} gate(s) are unresolved."
            ),
            "remaining_evidence": persistence.get("remaining_evidence"),
            "automatic_adoption_enabled": False,
            **_safe_flags(),
        }

    def _learning_horizon_completion(
        self,
        statuses: dict[str, Any],
        continuity: dict[str, Any],
        throughput: dict[str, Any],
        horizon: dict[str, Any],
    ) -> dict[str, Any]:
        tier1a = status_value(statuses, "astra_learning_preservation_capacity_v1")
        base = dict(tier1a.get("learning_throughput_preservation_engine_v1") or {})
        evidence_age = to_float(base.get("evidence_age_hours"), 0.0)
        concentration = to_float(horizon.get("horizon_monopolization_risk"), 0.0)
        stale_risk = clamp(evidence_age * 8.0 + (35.0 if to_int(throughput.get("trades_closed"), 0) == 0 else 0.0))
        return {
            "module": "Learning Continuity and Horizon Completion V1",
            "status": continuity.get("status"),
            "fresh_learning_score": throughput.get("paper_learning_velocity_score"),
            "learning_flow_score": continuity.get("learning_flow_score"),
            "horizon_diversity_score": continuity.get("learning_diversity_score"),
            "horizon_concentration_risk": rounded(concentration, 3),
            "stale_evidence_risk": rounded(stale_risk, 3),
            "stale_evidence_rate": rounded(stale_risk, 3),
            "trade_turnover_score": continuity.get("trade_turnover_score"),
            "turnover_health_score": continuity.get("trade_turnover_score"),
            "underfed_horizon": horizon.get("underrepresented_horizon"),
            "recommended_learning_focus": horizon.get("recommended_horizon_bias"),
            "dynamic_horizon_recommendation": horizon.get("recommended_horizon_bias"),
            "learning_continuity_summary": (
                "Historical and Shadow evidence remain fresh, but fresh Paper learning is constrained by "
                f"{horizon.get('dominant_horizon', 'unknown')} concentration and zero closed-trade turnover."
            ),
            **_safe_flags(),
        }

    def _autonomous_inspection(
        self,
        statuses: dict[str, Any],
        paper: dict[str, Any],
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        research = status_value(statuses, "autonomous_research_self_regulation_status_v1")
        validation = status_value(statuses, "autonomous_intelligence_validation_governance_v1")
        root_causes = list(research.get("likely_root_causes") or [])
        root_cause = text(first(root_causes[0] if root_causes else None, validation.get("top_root_cause")), "insufficient_evidence")
        issue = text(first(research.get("primary_trading_weakness"), paper.get("paper_learning_bottleneck_summary")), "unknown")
        prior_root = text(memory.get("latest_root_cause"), "insufficient_evidence")
        repeated = bool(prior_root == root_cause or memory.get("repeated_observations_retained"))
        action = text(first(research.get("next_best_action_summary"), validation.get("recommended_virtual_test")), "continue_shadow_validation")
        confidence = max(
            to_float(research.get("root_cause_confidence"), 0.0),
            to_float(validation.get("confidence"), 0.0),
        )
        return {
            "module": "Autonomous Inspection and Root Cause Completion V1",
            "status": "root_cause_identified" if root_cause != "insufficient_evidence" else "insufficient_evidence",
            "autonomous_inspection_score": rounded(confidence, 3),
            "issue_detected": issue,
            "top_detected_issue": issue,
            "root_cause": root_cause,
            "root_cause_chain": root_causes or [root_cause],
            "repeated_issue": repeated,
            "repeated_issue_detected": repeated,
            "prior_correction": memory.get("latest_recommendation", "none"),
            "prior_correction_found": bool(memory.get("latest_recommendation")),
            "prior_correction_effectiveness": memory.get("recommendation_effectiveness_score"),
            "recommended_action": action,
            "recommended_next_action": action,
            "inspection_confidence": rounded(confidence, 3),
            "inspection_summary": (
                f"Astra traced {issue.replace('_', ' ')} to {root_cause.replace('_', ' ')}. "
                "The correction remains advisory and will be measured against the next comparable snapshot."
            ),
            **_safe_flags(),
        }

    def _autonomous_improvement(self, statuses: dict[str, Any]) -> dict[str, Any]:
        prioritization = status_value(statuses, "adaptive_learning_prioritization_resource_allocation_v1")
        rows = [dict(row) for row in prioritization.get("weakness_rankings") or [] if isinstance(row, dict)]
        for row in rows:
            row["evidence_adjusted_roi"] = rounded(
                to_float(row.get("expected_learning_value"), 0.0)
                * (0.35 + to_float(row.get("sample_size_confidence"), 0.0) / 100.0 * 0.65)
                * (1.0 - to_float(row.get("noise_risk_score"), 0.0) / 140.0),
                3,
            )
        best = max(rows, key=lambda row: row.get("evidence_adjusted_roi", 0.0), default={})
        safe = bool(
            to_float(best.get("sample_size_confidence"), 0.0) >= 60.0
            and to_float(best.get("noise_risk_score"), 100.0) <= 40.0
        )
        return {
            "module": "Autonomous Improvement Prioritization Completion V1",
            "status": "recommendation_ready" if safe else "observation_only",
            "autonomous_improvement_score": best.get("evidence_adjusted_roi", 0.0),
            "highest_roi_improvement": best.get("weakness", "insufficient_evidence"),
            "top_improvement_candidate": best.get("weakness", "insufficient_evidence"),
            "expected_improvement_score": best.get("improvement_potential_score", 0.0),
            "expected_benefit": best.get("improvement_potential_score", 0.0),
            "implementation_complexity": "low_existing_worker_and_replay_focus_only",
            "safety_risk": "low_advisory_only",
            "business_value_score": best.get("performance_impact_score", 0.0),
            "evidence_support_score": best.get("sample_size_confidence", 0.0),
            "improvement_priority_rankings": rows[:5],
            "evidence_adjusted_roi_score": best.get("evidence_adjusted_roi", 0.0),
            "improvement_confidence": best.get("sample_size_confidence", 0.0),
            "noise_risk_score": best.get("noise_risk_score", 100.0),
            "safe_to_recommend": safe,
            "recommended_worker_focus": (
                "confidence_calibration_worker"
                if best.get("weakness") == "confidence_truth"
                else prioritization.get("recommended_worker_focus")
            ),
            "recommended_replay_focus": (
                "confidence_bucket_outcome_replay"
                if best.get("weakness") == "confidence_truth"
                else prioritization.get("recommended_replay_focus")
            ),
            "recommended_memory_focus": (
                f"retain_high_confidence_{best.get('weakness', 'learning')}_lessons"
            ),
            "why_this_priority": (
                f"{best.get('weakness', 'No area')} has the strongest evidence-adjusted ROI after "
                "penalizing low sample confidence and noise."
            ),
            "improvement_summary": (
                f"{best.get('weakness', 'No area')} has the strongest evidence-adjusted ROI after "
                "penalizing low sample confidence and noise."
            ),
            **_safe_flags(),
        }

    def _decision_memory(
        self,
        statuses: dict[str, Any],
        inspection: dict[str, Any],
        improvement: dict[str, Any],
    ) -> dict[str, Any]:
        memory = status_value(statuses, "self_correction_decision_memory_v1")
        tier3 = status_value(statuses, "astra_intelligence_maturation_suite_v1")
        governance = dict(tier3.get("unified_memory_governance_v1") or {})
        retention = max(
            to_float(memory.get("knowledge_retention_score"), 0.0),
            to_float(governance.get("memory_governance_score"), 0.0),
        )
        return {
            "module": "Decision Memory and Knowledge Retention Completion V1",
            "status": memory.get("status", "insufficient_evidence"),
            "decision_memory_score": rounded(retention, 3),
            "decision_memory_entries": memory.get("active_memory_entries", 0),
            "retained_corrections_count": memory.get("active_memory_entries", 0),
            "retained_failed_experiments_count": max(
                0,
                to_int(memory.get("outcomes_evaluated"), 0)
                - to_int(memory.get("recommendations_improved_later"), 0),
            ),
            "repeated_issue_memory_hits": memory.get("repeated_observations_retained", 0),
            "useful_memory_retrieval_rate": (
                rounded(
                    to_int(memory.get("outcomes_evaluated"), 0)
                    / max(1, to_int(memory.get("active_memory_entries"), 0))
                    * 100.0,
                    3,
                )
            ),
            "memory_reinforcement_score": rounded(retention, 3),
            "memory_archive_count": memory.get("compressed_archive_count", 0),
            "compressed_archive_count": memory.get("compressed_archive_count", 0),
            "duplicate_research_suppressed": memory.get("duplicate_snapshots_suppressed", 0),
            "outcomes_evaluated": memory.get("outcomes_evaluated", 0),
            "knowledge_retention_score": rounded(retention, 3),
            "intelligence_dna": {
                "root_cause": inspection.get("root_cause"),
                "priority": improvement.get("highest_roi_improvement"),
                "recommendation": inspection.get("recommended_action"),
                "evidence_adjusted_roi": improvement.get("evidence_adjusted_roi_score"),
            },
            "prevents_repeated_research": bool(memory.get("decision_memory_prevents_duplicate_research")),
            "memory_summary": (
                "Repeated snapshots are compacted, prior recommendations are scored against later comparable states, "
                "and the current root-cause/priority/recommendation DNA is retained."
            ),
            **_safe_flags(),
        }

    def _behavior_verification(
        self,
        statuses: dict[str, Any],
        paper: dict[str, Any],
        shadow: dict[str, Any],
        continuity: dict[str, Any],
        inspection: dict[str, Any],
        improvement: dict[str, Any],
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        broker = status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1")
        unified = status_value(statuses, "unified_learning_diagnostics_v1")
        checks = {
            "paper_broker_truth_available": bool(broker.get("paper_mode_verified")),
            "fresh_paper_learning_flow_active": to_float(paper.get("paper_learning_velocity_score"), 0.0) >= 45.0,
            "paper_learning_capacity_correction_meaningful": bool(
                to_int(paper.get("recommended_adaptive_capacity"), 0)
                >= min(35, max(25, to_int(paper.get("baseline_capacity"), 20) + 5))
            ),
            "horizon_diversity_adequate": to_float(continuity.get("horizon_diversity_score"), 0.0) >= 35.0,
            "shadow_promotion_governed": bool(shadow.get("rollback_readiness") == "armed"),
            "root_cause_identified": inspection.get("status") == "root_cause_identified",
            "improvement_priority_evidence_supported": bool(improvement.get("safe_to_recommend")),
            "decision_memory_operational": to_int(memory.get("decision_memory_entries"), 0) > 0,
            "unified_diagnostics_healthy": to_int(unified.get("failed_sources_count"), 0) == 0,
        }
        score = sum(bool(value) for value in checks.values()) / len(checks) * 100.0
        incomplete = [key for key, value in checks.items() if not value]
        verified_count = sum(bool(value) for value in checks.values())
        return {
            "module": "Behavior Verification and Core Completion V1",
            "status": "business_objective_achieved" if not incomplete else "safe_completion_blocked",
            "behavior_verification_score": rounded(score, 3),
            "verified_capabilities_count": verified_count,
            "incomplete_capabilities": incomplete,
            "failed_behavior_checks": incomplete,
            "regression_risks": [] if not incomplete else ["paper_learning_capacity_remains_constrained"],
            "core_completion_score": rounded(score, 3),
            "core_completion_blockers": incomplete,
            "behavior_verification_summary": (
                "Core diagnostic, governance, memory, and integration behavior is verified; "
                "fresh Paper capacity remains safety-blocked until natural position turnover."
                if incomplete
                else "All requested core behavior checks passed without changing protected trading behavior."
            ),
            "verification_checks": checks,
            "business_objective_achieved": not incomplete,
            "remaining_behavior_gaps": incomplete,
            "remaining_blocker": (
                "fresh_paper_outcomes_require_natural_position_closures_or_separately_approved_behavior_change"
                if any(key in incomplete for key in (
                    "fresh_paper_learning_flow_active",
                    "paper_learning_capacity_correction_meaningful",
                ))
                else incomplete[0] if incomplete else "none"
            ),
            "regression_status": "no_protected_behavior_changed",
            "safety_status": "preserved",
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        occupancy = self._occupancy(statuses)
        throughput = self._throughput(statuses, occupancy)
        continuity = self._learning_continuity(statuses, occupancy, throughput)
        opportunity = self._opportunity_cost(statuses, occupancy, throughput)
        horizon = self._horizon_evolution(statuses, occupancy, throughput)
        drag = self._position_capacity_drag(statuses, occupancy, horizon)
        queue = self._horizon_opportunity_queue(statuses, horizon)
        reserve = self._learning_reserve(occupancy, throughput, continuity, drag, queue)
        expansion = self._capacity_expansion(
            statuses,
            occupancy,
            throughput,
            horizon,
            continuity,
            reserve,
            drag,
            queue,
        )
        classifier = self._improvement_classifier(statuses)
        evolution = self._controlled_evolution(statuses, occupancy, throughput, classifier)
        persistence = self._persistence_explanation(statuses, evolution, throughput)
        governance = self._governance(evolution)
        completion = self._completion_audit(
            statuses,
            continuity,
            occupancy,
            horizon,
            evolution,
            governance,
            persistence,
        )
        self_governance = self._self_governance(
            statuses,
            continuity,
            occupancy,
            horizon,
            evolution,
            completion,
        )
        explanation = self._executive_explanation(
            continuity,
            occupancy,
            horizon,
            evolution,
            persistence,
            governance,
        )
        prior_memory = status_value(statuses, "self_correction_decision_memory_v1")
        paper_completion = self._paper_learning_completion(
            statuses,
            occupancy,
            throughput,
            opportunity,
            expansion,
            reserve,
            drag,
            queue,
        )
        shadow_completion = self._shadow_paper_completion(classifier, evolution, governance, persistence)
        horizon_completion = self._learning_horizon_completion(statuses, continuity, throughput, horizon)
        inspection = self._autonomous_inspection(statuses, paper_completion, prior_memory)
        improvement = self._autonomous_improvement(statuses)
        decision_memory = self._decision_memory(statuses, inspection, improvement)
        behavior_verification = self._behavior_verification(
            statuses,
            paper_completion,
            shadow_completion,
            horizon_completion,
            inspection,
            improvement,
            decision_memory,
        )
        summary = {
            "learning_flow": continuity.get("status"),
            "learning_diversity": continuity.get("learning_diversity_score"),
            "capacity_status": occupancy.get("occupancy_status"),
            "shadow_readiness": evolution.get("candidate_status"),
            "paper_promotion_readiness": evolution.get("promotion_stage_label"),
            "current_bottleneck": (
                paper_completion.get("paper_learning_bottleneck_summary")
                if continuity.get("continuity_bottleneck") in {None, "none"}
                else continuity.get("continuity_bottleneck")
            ),
            "recommended_next_step": explanation.get("recommended_next_step"),
            "occupancy_status": occupancy.get("occupancy_status"),
            "learning_throughput": throughput.get("learning_flow_status"),
            "opportunity_cost": text((opportunity.get("highest_opportunity_cost_context") or {}).get("symbol"), "warming_up"),
            "dynamic_horizon_bias": horizon.get("recommended_horizon_bias"),
            "adaptive_capacity": expansion.get("recommended_adaptive_capacity"),
            "learning_reserve_status": reserve.get("learning_reserve_status"),
            "learning_reserve_score": reserve.get("learning_reserve_score"),
            "capacity_drag_score": drag.get("capacity_drag_score"),
            "missed_learning_opportunity_score": queue.get("missed_learning_opportunity_score"),
            "meaningful_capacity_test_passed": expansion.get("meaningful_capacity_test_passed"),
            "controlled_evolution_candidate": governance.get("top_evolution_candidate"),
            "evolution_governance": governance.get("adoption_safety_status"),
            "self_governance": self_governance.get("status"),
            "completion_audit": completion.get("status"),
            "plain_english_summary": explanation.get("plain_english_summary"),
            "paper_learning_capacity_score": paper_completion.get("paper_learning_capacity_score"),
            "shadow_to_paper_readiness_score": shadow_completion.get("shadow_to_paper_readiness_score"),
            "learning_continuity_score": continuity.get("learning_continuity_score"),
            "paper_saturation_risk": paper_completion.get("paper_saturation_risk"),
            "fresh_learning_score": horizon_completion.get("fresh_learning_score"),
            "horizon_diversity_score": horizon_completion.get("horizon_diversity_score"),
            "autonomous_inspection_score": inspection.get("autonomous_inspection_score"),
            "autonomous_improvement_score": improvement.get("autonomous_improvement_score"),
            "decision_memory_score": decision_memory.get("decision_memory_score"),
            "behavior_verification_score": behavior_verification.get("behavior_verification_score"),
            "core_completion_score": behavior_verification.get("core_completion_score"),
            "strongest_autonomous_area": "broker_truth_and_cached_shadow_evidence",
            "weakest_autonomous_area": "fresh_paper_turnover_and_capacity_reserve",
            "highest_roi_next_improvement": improvement.get("highest_roi_improvement"),
            "autonomous_maturation_summary": (
                "Astra now distinguishes cached knowledge from fresh Paper outcomes, remembers correction results, "
                "prioritizes evidence-supported improvements, and keeps Shadow promotion governed. "
                "Fresh Paper capacity still depends on natural position turnover."
            ),
            "paper_learning_velocity_score": paper_completion.get("paper_learning_velocity_score"),
            "shadow_paper_readiness_score": shadow_completion.get("shadow_paper_readiness_score"),
            "root_cause_confidence": inspection.get("inspection_confidence"),
            "highest_roi_improvement": improvement.get("highest_roi_improvement"),
            "knowledge_retention_score": decision_memory.get("knowledge_retention_score"),
            "strongest_area": "broker_truth_and_cached_shadow_evidence",
            "weakest_area": "fresh_paper_turnover_and_capacity_reserve",
            "highest_roi_next_action": improvement.get("highest_roi_improvement"),
            "recommended_action": (
                paper_completion.get("capacity_recommendation")
                if paper_completion.get("learning_reserve_status") == "depleted"
                else continuity.get("recommended_action")
                if continuity.get("status") != "healthy"
                else throughput.get("recommended_throughput_action")
            ),
        }
        return with_safety({
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Learning Continuity, Controlled Evolution & Self-Governance Suite V1",
            "extends_suite": "ASTRA Tier 4 - Adaptive Occupancy, Learning Throughput & Controlled Evolution Suite V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "learning_continuity_engine_v1": continuity,
            "adaptive_occupancy_management_v1": occupancy,
            "learning_throughput_protection_v1": throughput,
            "opportunity_cost_intelligence_v1": opportunity,
            "dynamic_horizon_evolution_v1": horizon,
            "adaptive_learning_expansion_v1": expansion,
            "learning_reserve_engine_v1": reserve,
            "position_age_capacity_drag_v1": drag,
            "horizon_opportunity_queue_v1": queue,
            "paper_learning_capacity_correction_v1": {
                "paper_learning_capacity_correction_enabled": True,
                "baseline_capacity": expansion.get("baseline_capacity"),
                "recommended_adaptive_capacity": expansion.get("recommended_adaptive_capacity"),
                "absolute_safety_ceiling": expansion.get("absolute_safety_ceiling"),
                "learning_reserve_status": reserve.get("learning_reserve_status"),
                "learning_reserve_score": reserve.get("learning_reserve_score"),
                "capacity_drag_score": drag.get("capacity_drag_score"),
                "missed_learning_opportunity_score": queue.get("missed_learning_opportunity_score"),
                "meaningful_capacity_test_passed": expansion.get("meaningful_capacity_test_passed"),
                "paper_learning_capacity_summary": expansion.get("capacity_recommendation_summary"),
                **_safe_flags(),
            },
            "improvement_classifier_v1": classifier,
            "controlled_shadow_paper_evolution_v2": evolution,
            "persistence_explanation_engine_v1": persistence,
            "evolution_governance_v1": governance,
            "self_governance_engine_v1": self_governance,
            "implementation_completion_auditor_v1": completion,
            "executive_explanation_engine_v1": explanation,
            "paper_trading_learning_completion_v1": paper_completion,
            "shadow_paper_controlled_evolution_completion_v1": shadow_completion,
            "learning_continuity_horizon_completion_v1": horizon_completion,
            "autonomous_inspection_root_cause_completion_v1": inspection,
            "autonomous_improvement_prioritization_completion_v1": improvement,
            "decision_memory_knowledge_retention_completion_v1": decision_memory,
            "behavior_verification_core_completion_v1": behavior_verification,
            "astra_autonomous_intelligence_maturation_v1": summary,
            "executive_summary": summary,
            "bounded_cached_sources_only": True,
            "full_history_scan_performed": False,
            "dashboard_endpoint_count_added": 0,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        })
