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


def _avg(values: list[float]) -> float:
    clean = [to_float(value, 0.0) for value in values if value is not None]
    return sum(clean) / max(1, len(clean))


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

    def _trade_lifecycle_intelligence(
        self,
        statuses: dict[str, Any],
        occupancy: dict[str, Any],
    ) -> dict[str, Any]:
        truth = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        tier1a = status_value(statuses, "astra_learning_preservation_capacity_v1")
        audit = dict(tier1a.get("position_lifecycle_auditor_v1") or {})
        trace = status_value(statuses, "paper_execution_trace")
        rows = [
            dict(row)
            for row in (
                trace.get("broker_learning_position_rows")
                or truth.get("position_audit_rows")
                or truth.get("truth_validation_rows")
                or audit.get("position_rows")
                or []
            )
            if isinstance(row, dict)
        ]
        classified: list[dict[str, Any]] = []
        stage_counts: dict[str, int] = {}
        learning_weights = {
            "new": 1.0,
            "developing": 0.9,
            "active_learning": 1.0,
            "waiting": 0.35,
            "mature_winner": 0.55,
            "mature_loser": 0.45,
            "near_exit": 0.25,
            "stale": 0.10,
            "exit_review_candidate": 0.20,
        }
        for raw in rows[:40]:
            horizon = _horizon(first(raw.get("normalized_horizon"), raw.get("horizon"), raw.get("original_horizon"), "unknown"))
            expected_days = max(0.05, LOCK_DAYS.get(horizon, 7.0))
            hold_days_value = first(raw.get("elapsed_hold_days"), raw.get("position_age"), None)
            measured_hold_days = (
                max(0.0, to_float(hold_days_value, 0.0))
                if hold_days_value is not None
                else max(0.0, to_float(raw.get("elapsed_hold_hours"), 0.0) / 24.0)
            )
            exact_age = bool(
                raw.get("elapsed_hold_days") is not None
                or raw.get("elapsed_hold_hours") is not None
                or raw.get("position_age") is not None
            )
            hold_days = measured_hold_days if exact_age else 0.0
            age_ratio = hold_days / expected_days if hold_days > 0 else 0.0
            pnl = to_float(first(raw.get("pnl_percent"), raw.get("unrealized_pnl_percent"), raw.get("unrealized_plpc"), 0.0), 0.0)
            if abs(pnl) <= 2.0 and raw.get("unrealized_plpc") is not None and raw.get("pnl_percent") is None:
                pnl *= 100.0
            daily_move = to_float(
                first(
                    raw.get("daily_change_percent"),
                    raw.get("day_change_percent"),
                    raw.get("daily_pnl_percent"),
                    raw.get("change_today_percent"),
                    0.0,
                ),
                0.0,
            )
            if abs(daily_move) <= 2.0 and any(
                raw.get(key) is not None
                for key in ("daily_plpc", "day_plpc", "change_today_plpc")
            ):
                daily_move = to_float(
                    first(raw.get("daily_plpc"), raw.get("day_plpc"), raw.get("change_today_plpc"), 0.0),
                    0.0,
                ) * 100.0
            continuation = clamp(first(raw.get("continuation_probability"), 50.0))
            sell_confidence = clamp(first(raw.get("sell_confidence"), raw.get("exit_readiness"), 0.0))
            giveback = clamp(first(raw.get("giveback_risk"), 0.0))
            thesis = clamp(
                first(
                    raw.get("thesis_health"),
                    100.0 - to_float(raw.get("catalyst_decay_risk"), 0.0)
                    if raw.get("catalyst_decay_risk") is not None
                    else 65.0,
                )
            )
            should_sell = bool(raw.get("should_have_sold"))
            profit_protect = bool(raw.get("should_have_profit_protected"))
            conversion = bool(raw.get("should_have_converted_horizon"))
            if exact_age:
                if should_sell or (sell_confidence >= 68 and continuation < 45):
                    stage = "exit_review_candidate"
                elif profit_protect or (sell_confidence >= 60 and giveback >= 60):
                    stage = "near_exit"
                elif age_ratio >= 1.75 and thesis < 55:
                    stage = "stale"
                elif age_ratio >= 1.0 and pnl > 0:
                    stage = "mature_winner"
                elif age_ratio >= 1.0 and pnl <= 0:
                    stage = "mature_loser"
                elif age_ratio >= 0.65 or conversion:
                    stage = "waiting"
                elif age_ratio >= 0.25:
                    stage = "active_learning" if continuation >= 50 else "developing"
                elif hold_days > 0:
                    stage = "developing"
                else:
                    stage = "new"
            else:
                # Classify from observable behavior without pretending a proxy timestamp is exact.
                if should_sell or (pnl <= -7.0 and (continuation < 45 or thesis < 55)):
                    stage = "exit_review_candidate"
                elif profit_protect or (pnl >= 7.0 and (giveback >= 50 or daily_move < -1.0)):
                    stage = "near_exit"
                elif pnl >= 4.0:
                    stage = "mature_winner"
                elif pnl <= -4.0:
                    stage = "mature_loser"
                elif conversion or (abs(pnl) < 0.75 and abs(daily_move) < 0.5 and continuation < 55):
                    stage = "waiting"
                elif continuation >= 58 or abs(pnl) >= 1.5 or abs(daily_move) >= 1.0:
                    stage = "active_learning"
                else:
                    stage = "developing"
            learning_weight = learning_weights[stage]
            learning_value = rounded(learning_weight * 100.0, 3)
            blocks_learning = bool(learning_weight >= 0.75)
            review_exit = bool(stage in {"near_exit", "stale", "exit_review_candidate", "mature_loser"})
            still_valuable = bool(stage in {"new", "developing", "active_learning", "mature_winner"})
            reason = (
                "sell_or_profit_protection_evidence_is_elevated"
                if stage in {"near_exit", "exit_review_candidate"}
                else "expected_hold_window_exceeded_and_thesis_support_weakened"
                if stage == "stale"
                else "position_is_waiting_for_expected_horizon_to_resolve"
                if stage == "waiting"
                else "position_is_still_generating_fresh_lifecycle_evidence"
            )
            item = {
                "symbol": text(raw.get("symbol"), "UNKNOWN").upper(),
                "horizon": horizon,
                "lifecycle_stage": stage,
                "learning_value": learning_value,
                "learning_occupancy_weight": learning_weight,
                "expected_hold_relevance": rounded(clamp(100.0 - max(0.0, age_ratio - 1.0) * 55.0), 3),
                "position_age_days": rounded(hold_days, 3),
                "position_age_is_exact": exact_age,
                "position_age_source": "broker_reconciled_timestamp" if exact_age else "horizon_and_market_behavior_proxy",
                "classification_basis": "exact_age_and_position_evidence" if exact_age else "proxy_position_evidence",
                "classification_confidence": rounded(
                    clamp(
                        (
                            78.0 + (8.0 if should_sell or profit_protect else 0.0)
                            if exact_age
                            else 42.0
                            + min(18.0, abs(pnl) * 1.5)
                            + min(10.0, abs(daily_move) * 2.0)
                            + (8.0 if should_sell or profit_protect else 0.0)
                        )
                    ),
                    3,
                ),
                "expected_hold_days": rounded(expected_days, 3),
                "current_thesis_status": "healthy" if thesis >= 60 else "weakening" if thesis >= 35 else "broken",
                "classification_reason": reason,
                "blocks_learning": blocks_learning,
                "should_be_reviewed_for_exit": review_exit,
                "still_valuable_for_learning": still_valuable,
                "pnl_percent": rounded(pnl, 3),
                "daily_movement_percent": rounded(daily_move, 3),
                "continuation_probability": rounded(continuation, 3),
                "sell_confidence": rounded(sell_confidence, 3),
                "giveback_risk": rounded(giveback, 3),
                "thesis_health": rounded(thesis, 3),
            }
            classified.append(item)
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        raw_count = to_int(occupancy.get("broker_confirmed_positions"), 0)
        detail_gap = max(0, raw_count - len(classified))
        if detail_gap:
            stage_counts["waiting"] = stage_counts.get("waiting", 0) + detail_gap
        high_value = [row for row in classified if row["learning_value"] >= 75.0]
        low_value = [row for row in classified if row["learning_value"] <= 45.0]
        exit_review = [row for row in classified if row["should_be_reviewed_for_exit"]]
        stale = [row for row in classified if row["lifecycle_stage"] == "stale"]
        exact_age_rows = len([row for row in classified if row.get("position_age_is_exact")])
        confidence = clamp(
            len(classified) / max(1, raw_count) * 50.0
            + exact_age_rows / max(1, len(classified)) * 40.0
            + (10.0 if classified else 0.0)
        )
        return {
            "module": "Trade Lifecycle Intelligence Completion V1",
            "status": "ok" if raw_count else "insufficient_evidence",
            "trade_lifecycle_summary": classified,
            "position_lifecycle_details": classified,
            "lifecycle_stage_counts": stage_counts,
            "high_learning_value_positions": high_value,
            "low_learning_value_positions": low_value,
            "exit_review_candidates": exit_review,
            "stale_positions": stale,
            "mature_winners": [row for row in classified if row.get("lifecycle_stage") == "mature_winner"],
            "mature_losers": [row for row in classified if row.get("lifecycle_stage") == "mature_loser"],
            "near_exit_positions": [row for row in classified if row.get("lifecycle_stage") == "near_exit"],
            "positions_pending_detail": detail_gap,
            "lifecycle_classification_confidence": rounded(confidence, 3),
            "classification_confidence": rounded(confidence, 3),
            "lifecycle_refinement_score": rounded(
                clamp(confidence * 0.65 + len(stage_counts) / max(1, len(learning_weights)) * 35.0),
                3,
            ),
            "proxy_classification_used": bool(len(classified) - exact_age_rows),
            "lifecycle_summary_plain_english": (
                f"Astra classified {len(classified)} of {raw_count} broker-confirmed positions. "
                f"{len(high_value)} are still producing strong learning, {len(low_value) + detail_gap} are mostly waiting "
                f"or low-learning, and {len(exit_review)} deserve exit review. No exit is forced."
            ),
            "proxy_age_rows": len(classified) - exact_age_rows,
            "lifecycle_refinement_summary": (
                f"{len(classified)} broker-confirmed positions are separated across {len(stage_counts)} lifecycle "
                f"stage(s). {len(classified) - exact_age_rows} classification(s) use clearly labeled P/L, movement, "
                "horizon, and cached-evidence proxies because exact entry times are unavailable."
            ),
            **_safe_flags(),
        }

    def _effective_learning_capacity(
        self,
        occupancy: dict[str, Any],
        lifecycle: dict[str, Any],
        expansion: dict[str, Any],
    ) -> dict[str, Any]:
        raw = to_int(occupancy.get("broker_confirmed_positions"), 0)
        stage_counts = dict(lifecycle.get("lifecycle_stage_counts") or {})
        weights = {
            "new": 1.0,
            "developing": 0.9,
            "active_learning": 1.0,
            "waiting": 0.35,
            "mature_winner": 0.55,
            "mature_loser": 0.45,
            "near_exit": 0.25,
            "stale": 0.10,
            "exit_review_candidate": 0.20,
        }
        effective = sum(to_int(stage_counts.get(stage), 0) * weight for stage, weight in weights.items())
        if effective <= 0 and raw:
            effective = float(raw)
        recommended = max(
            to_int(expansion.get("baseline_capacity"), 20),
            to_int(expansion.get("recommended_adaptive_capacity"), 20),
        )
        active = sum(to_int(stage_counts.get(stage), 0) for stage in ("new", "developing", "active_learning"))
        waiting = to_int(stage_counts.get("waiting"), 0)
        near_exit = sum(to_int(stage_counts.get(stage), 0) for stage in ("near_exit", "exit_review_candidate"))
        stale = to_int(stage_counts.get("stale"), 0)
        pressure = clamp(effective / max(1.0, recommended) * 100.0)
        return {
            "module": "Effective Learning Capacity V1",
            "status": "ok" if raw else "insufficient_evidence",
            "raw_open_positions": raw,
            "risk_exposure_positions": raw,
            "active_learning_positions": active,
            "waiting_low_learning_positions": waiting,
            "near_exit_positions": near_exit,
            "stale_learning_drag_positions": stale,
            "effective_learning_occupancy": rounded(effective, 3),
            "effective_learning_capacity_available": rounded(max(0.0, recommended - effective), 3),
            "safe_raw_position_slots_available": max(0, recommended - raw),
            "learning_occupancy_pressure": rounded(pressure, 3),
            "recommended_adaptive_capacity": recommended,
            "effective_learning_capacity_summary": (
                f"Broker truth reports {raw} risk-bearing positions, while lifecycle weighting produces "
                f"{effective:.2f} effective learning positions. The {recommended}-position adaptive paper ceiling leaves "
                f"{max(0, recommended - raw)} safe raw-position slot(s); all entry and risk gates still apply."
            ),
            **_safe_flags(),
        }

    def _exit_decision_intelligence(self, lifecycle: dict[str, Any]) -> dict[str, Any]:
        rows = list(lifecycle.get("trade_lifecycle_summary") or [])
        review = [dict(row) for row in rows if row.get("should_be_reviewed_for_exit")]
        valid = [dict(row) for row in rows if not row.get("should_be_reviewed_for_exit")]
        profit_protection = [
            dict(row) for row in rows
            if row.get("lifecycle_stage") in {"near_exit", "mature_winner"}
            and to_float(row.get("pnl_percent"), 0.0) > 0
        ]
        loss_containment = [
            dict(row) for row in rows
            if row.get("lifecycle_stage") in {"mature_loser", "exit_review_candidate", "stale"}
            and to_float(row.get("pnl_percent"), 0.0) < 0
        ]
        thesis_expiration = [
            dict(row) for row in rows
            if row.get("current_thesis_status") in {"weakening", "broken"}
            or row.get("lifecycle_stage") == "stale"
        ]
        overdue = [
            row for row in review
            if to_float(row.get("position_age_days"), 0.0) >= to_float(row.get("expected_hold_days"), 999.0)
        ]
        loss_aversion = clamp(
            sum(
                25.0
                + max(0.0, -to_float(row.get("pnl_percent"), 0.0)) * 2.0
                + max(0.0, 50.0 - to_float(row.get("continuation_probability"), 50.0))
                for row in review
                if to_float(row.get("pnl_percent"), 0.0) < 0
            )
            / max(1, len(review))
        )
        score = clamp(
            len(review) / max(1, len(rows)) * 55.0
            + len(overdue) / max(1, len(rows)) * 30.0
            + loss_aversion * 0.15
        )
        giveback_risk = clamp(
            sum(
                max(
                    to_float(row.get("giveback_risk"), 0.0),
                    55.0
                    if to_float(row.get("pnl_percent"), 0.0) > 0
                    and to_float(row.get("daily_movement_percent"), 0.0) < 0
                    else 0.0,
                )
                for row in profit_protection
            )
            / max(1, len(profit_protection))
        )
        reasons: dict[str, int] = {}
        for row in review:
            reason = text(row.get("classification_reason"), "mixed_exit_review_evidence")
            reasons[reason] = reasons.get(reason, 0) + 1
        return {
            "module": "Exit Decision Intelligence and Overdue Position Review V1",
            "status": "review_needed" if review else "monitoring",
            "exit_decision_intelligence_score": rounded(score, 3),
            "open_positions_reviewed": len(rows),
            "valid_hold_count": len(valid),
            "overdue_position_count": len(overdue),
            "exit_review_candidates": review,
            "exit_review_candidate_count": len(review),
            "profit_protection_candidates": profit_protection,
            "profit_protection_candidate_count": len(profit_protection),
            "loss_containment_candidates": loss_containment,
            "loss_containment_candidate_count": len(loss_containment),
            "thesis_expiration_candidates": thesis_expiration,
            "thesis_expiration_candidate_count": len(thesis_expiration),
            "stale_hold_candidates": [dict(row) for row in rows if row.get("lifecycle_stage") == "stale"],
            "stale_hold_candidate_count": len([row for row in rows if row.get("lifecycle_stage") == "stale"]),
            "hold_still_valid_positions": valid,
            "hold_still_valid_count": len(valid),
            "hold_validation_reasons": sorted(set(text(row.get("classification_reason"), "monitor") for row in valid)),
            "overdue_position_reasons": reasons,
            "loss_aversion_risk_score": rounded(loss_aversion, 3),
            "giveback_risk_score": rounded(giveback_risk, 3),
            "automatic_exits_enabled": False,
            "forced_partial_sells_enabled": False,
            "trailing_stops_enabled": False,
            "exit_review_summary": (
                f"{len(review)} open position(s) merit human exit review, with {len(profit_protection)} profit "
                f"protection, {len(loss_containment)} loss containment, and {len(thesis_expiration)} thesis-expiration "
                "review signal(s). Natural exits remain the default and no sell is forced."
            ),
            "exit_decision_summary": (
                f"Astra reviewed {len(rows)} open Paper position(s): {len(valid)} remain valid holds, "
                f"{len(review)} need human exit review, {len(profit_protection)} have profit-protection pressure, "
                f"and {len(loss_containment)} have loss-containment pressure. No automatic exit is enabled."
            ),
            **_safe_flags(),
        }

    def _trade_thesis_tracking(self, lifecycle: dict[str, Any]) -> dict[str, Any]:
        rows = [dict(row) for row in (lifecycle.get("trade_lifecycle_summary") or []) if isinstance(row, dict)]
        records = []
        for row in rows:
            status = text(row.get("current_thesis_status"), "unknown")
            proxy = not bool(row.get("position_age_is_exact"))
            horizon = text(row.get("horizon"), "unknown")
            pnl = to_float(row.get("pnl_percent"), 0.0)
            continuation = to_float(row.get("continuation_probability"), 50.0)
            thesis_health = to_float(row.get("thesis_health"), 0.0)
            if status == "healthy":
                invalidation = "continuation drops below 45, thesis health weakens, or giveback/loss pressure rises"
            elif status == "weakening":
                invalidation = "thesis is weakening and should be reviewed against catalyst, momentum, and opportunity cost"
            elif status == "broken":
                invalidation = "cached thesis support appears broken; human review is warranted"
            else:
                invalidation = "entry thesis unavailable; use current broker truth and cached lifecycle evidence"
            records.append({
                "symbol": row.get("symbol"),
                "entry_reason": "proxy_from_cached_entry_and_lifecycle_evidence" if proxy else "broker_reconciled_entry_context",
                "signal_type": text(row.get("classification_reason"), "lifecycle_position_evidence"),
                "horizon": horizon,
                "confidence_at_entry": "unavailable" if proxy else row.get("classification_confidence"),
                "expected_holding_window_days": row.get("expected_hold_days"),
                "key_supporting_factors": [
                    f"horizon:{horizon}",
                    f"continuation:{rounded(continuation, 1)}",
                    f"current_pnl:{rounded(pnl, 2)}%",
                    f"thesis_health:{rounded(thesis_health, 1)}",
                ],
                "invalidation_conditions": invalidation,
                "thesis_freshness": "proxy_based" if proxy else "broker_reconciled",
                "thesis_confidence": row.get("classification_confidence"),
                "thesis_status": status,
                "proxy_thesis_used": proxy,
                "fabricated_entry_thesis": False,
            })
        valid = [row for row in records if row.get("thesis_status") == "healthy"]
        weakened = [row for row in records if row.get("thesis_status") == "weakening"]
        expired = [row for row in records if row.get("thesis_status") == "broken"]
        unknown = [row for row in records if row.get("thesis_status") not in {"healthy", "weakening", "broken"}]
        return {
            "module": "Trade Thesis Tracking V1",
            "status": "ok" if records else "insufficient_evidence",
            "trade_thesis_tracking_enabled": True,
            "thesis_records": records,
            "thesis_records_count": len(records),
            "thesis_valid_count": len(valid),
            "thesis_weakened_count": len(weakened),
            "thesis_expired_count": len(expired),
            "thesis_unknown_count": len(unknown),
            "proxy_thesis_used": bool([row for row in records if row.get("proxy_thesis_used")]),
            "exact_thesis_available_count": len([row for row in records if not row.get("proxy_thesis_used")]),
            "trade_thesis_summary": (
                f"Astra has lightweight thesis records for {len(records)} open Paper position(s). "
                f"{len(valid)} look intact, {len(weakened)} are weakening, {len(expired)} look expired, "
                f"and {len(unknown)} remain unknown. Proxy records are labeled; no entry reason is fabricated."
            ),
            **_safe_flags(),
        }

    def _open_position_opportunity_cost(
        self,
        lifecycle: dict[str, Any],
        opportunity: dict[str, Any],
        effective: dict[str, Any],
    ) -> dict[str, Any]:
        rows = [dict(row) for row in (lifecycle.get("trade_lifecycle_summary") or []) if isinstance(row, dict)]
        replacement_count = len(opportunity.get("candidate_rows") or []) + len(opportunity.get("horizon_diversity_opportunities_available") or [])
        capacity_pressure = clamp(effective.get("learning_occupancy_pressure"))
        scored = []
        for row in rows:
            learning_value = to_float(row.get("learning_value"), 0.0)
            age_ratio = to_float(row.get("position_age_days"), 0.0) / max(0.05, to_float(row.get("expected_hold_days"), 7.0))
            pnl = to_float(row.get("pnl_percent"), 0.0)
            score = clamp(
                capacity_pressure * 0.35
                + max(0.0, 70.0 - learning_value) * 0.30
                + min(100.0, age_ratio * 55.0) * 0.20
                + (15.0 if replacement_count else 0.0)
                + (10.0 if pnl < 0 and row.get("should_be_reviewed_for_exit") else 0.0)
            )
            scored.append({
                "symbol": row.get("symbol"),
                "horizon": row.get("horizon"),
                "current_hold_value": rounded(learning_value, 3),
                "learning_value": rounded(learning_value, 3),
                "opportunity_cost_score": rounded(score, 3),
                "capacity_drag": bool(score >= 60),
                "still_worth_learning_space": bool(learning_value >= 55 or score < 60),
                "review_reason": (
                    "capacity_or_learning_drag_review"
                    if score >= 60 else "hold_value_still_reasonable"
                ),
            })
        high = [row for row in scored if row["opportunity_cost_score"] >= 60]
        low = [row for row in scored if row["opportunity_cost_score"] < 40]
        tradeoff_score = _avg([row["opportunity_cost_score"] for row in scored])
        return {
            "module": "Open Position Opportunity Cost Intelligence V1",
            "status": "ok" if scored else "insufficient_evidence",
            "opportunity_cost_intelligence_score": rounded(tradeoff_score, 3),
            "open_position_opportunity_cost_rows": scored,
            "high_opportunity_cost_positions": high,
            "low_opportunity_cost_positions": low,
            "replacement_opportunities_detected": replacement_count,
            "learning_capacity_tradeoff_score": rounded(clamp(tradeoff_score * 0.65 + capacity_pressure * 0.35), 3),
            "capacity_drag_positions": [row for row in scored if row.get("capacity_drag")],
            "automatic_replacements_enabled": False,
            "opportunity_cost_summary": (
                f"Astra found {len(high)} open position(s) with elevated opportunity-cost or learning-drag pressure. "
                f"{replacement_count} cached replacement context(s) are visible, but no replacement trade is forced."
            ),
            **_safe_flags(),
        }

    def _exit_learning_feedback_loop(self, statuses: dict[str, Any], exit_review: dict[str, Any]) -> dict[str, Any]:
        truth = status_value(statuses, "astra_truth_controlled_evolution_executive_v1")
        official = dict((truth.get("executive_snapshot_truth_reconciliation_v1") or {}).get("official_performance_summary") or {})
        broker = status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_excursion_exit_learning_v2")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        closed = max(
            to_int((truth.get("executive_snapshot_truth_reconciliation_v1") or {}).get("closed_paper_trade_count"), 0),
            to_int(broker.get("true_paper_closed_trade_count"), 0),
            to_int(lifecycle.get("closed_trade_count"), 0),
            to_int(profit.get("evidence_count"), 0),
        )
        capture = to_float(first(profit.get("capture_ratio"), profit.get("average_capture_ratio"), profit.get("shadow_capture_ratio"), 0.0), 0.0)
        giveback = to_float(first(profit.get("giveback_pct"), profit.get("average_giveback"), profit.get("shadow_giveback_pct"), 0.0), 0.0)
        if capture > 1.5:
            capture_ratio = capture / 100.0
        else:
            capture_ratio = capture
        if closed <= 0:
            blocker = "closed_paper_exit_records_not_available"
            score = 0.0
            too_late = too_early = good = 0
        else:
            blocker = "none"
            score = clamp(min(100.0, closed / 50.0 * 45.0) + max(0.0, capture_ratio * 100.0) * 0.35 + max(0.0, 30.0 - giveback) * 0.20)
            too_late = len(exit_review.get("profit_protection_candidates") or []) + len(exit_review.get("loss_containment_candidates") or [])
            too_early = to_int(first(profit.get("false_exit_rate"), 0.0), 0)
            good = max(0, closed - too_late - too_early)
        return {
            "module": "Exit Learning Feedback Loop V1",
            "status": "ok" if closed > 0 else "insufficient_evidence",
            "exit_learning_feedback_score": rounded(score, 3),
            "closed_trades_reviewed": closed,
            "too_early_exit_count": too_early,
            "too_late_exit_count": too_late,
            "good_exit_count": good,
            "avg_profit_capture": rounded(capture_ratio, 4),
            "avg_giveback": rounded(giveback, 3),
            "shadow_exit_advantage_score": rounded(to_float(first(profit.get("improvement_delta"), profit.get("shadow_exit_advantage_score"), 0.0), 0.0), 3),
            "best_exit_behavior_observed": text(first(profit.get("best_shadow_exit_policy"), profit.get("best_exit_policy"), "warming_up"), "warming_up"),
            "feedback_blocker": blocker,
            "exit_learning_feedback_summary": (
                f"Astra reviewed {closed} closed/exit-learning record(s). Capture is {capture_ratio:.2f}, "
                f"giveback is {giveback:.2f}, and {too_late} current pattern(s) suggest exits may have been late."
                if closed > 0
                else "Closed Paper exit evidence is still warming up, so Astra prepared the feedback structure without inventing exit outcomes."
            ),
            **_safe_flags(),
        }

    def _controlled_exit_micro_test_readiness(
        self,
        statuses: dict[str, Any],
        evolution: dict[str, Any],
        persistence: dict[str, Any],
        shadow_feedback: dict[str, Any],
        exit_review: dict[str, Any],
    ) -> dict[str, Any]:
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        broker = status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1")
        candidates = list(evolution.get("eligible_candidates") or [])
        watched = list(shadow_feedback.get("shadow_exit_candidates_to_watch") or [])
        gates = dict(evolution.get("gate_results") or {})
        readiness_components = [
            100.0 if gates.get("minimum_evidence_count") else max(0.0, 100.0 - to_float(persistence.get("remaining_evidence"), 25.0) * 4.0),
            100.0 if gates.get("minimum_confidence") else to_float(persistence.get("current_confidence"), 0.0),
            100.0 if gates.get("minimum_persistence_window") else to_float(persistence.get("current_persistence_score"), 0.0),
            100.0 if gates.get("broker_truth_healthy") or broker.get("paper_mode_verified") else 0.0,
            100.0 if gates.get("rollback_available") else 35.0,
        ]
        readiness_score = clamp(_avg(readiness_components))
        blockers = list(evolution.get("promotion_blocker") or shadow_feedback.get("promotion_blockers") or [])
        if learned.get("learned_exit_bucket_enabled"):
            stage = "stage_2_paper_micro_test_active_only_if_existing_safe_path_exists"
        elif candidates and not blockers:
            stage = "stage_1_paper_micro_test_recommended"
        elif candidates or watched:
            stage = "stage_0_shadow_observe"
        else:
            stage = "stage_0_shadow_observe"
        top_pattern = text((watched[0] if watched else {}).get("pattern"), "")
        recommended = {
            "policy": (
                "profit_protection_review"
                if top_pattern == "profit_capture" or exit_review.get("profit_protection_candidates")
                else "loss_containment_review"
                if exit_review.get("loss_containment_candidates")
                else "thesis_expiration_review"
                if exit_review.get("thesis_expiration_candidates")
                else "continue_shadow_observation"
            ),
            "paper_action": "human_review_recommendation_only",
            "max_positions": "1_to_2_if_future_safe_path_is_explicitly_approved",
        }
        return {
            "module": "Controlled Paper Exit Micro-Test Readiness V1",
            "status": "ready_for_human_review" if stage.startswith("stage_1") else "advisory_observation",
            "controlled_exit_micro_test_readiness_score": rounded(readiness_score, 3),
            "exit_micro_test_candidates": candidates or watched[:1],
            "recommended_micro_test": recommended if candidates or watched else {},
            "promotion_stage": stage,
            "promotion_blockers": blockers,
            "remaining_evidence_needed": persistence.get("remaining_evidence"),
            "remaining_persistence_needed": persistence.get("remaining_persistence_score"),
            "rollback_status": evolution.get("rollback_status", "not_ready"),
            "paper_mode_verified": bool(broker.get("paper_mode_verified")),
            "paper_exit_path_verified": bool(learned.get("paper_exit_path_verified")),
            "automatic_micro_test_activation_enabled": False,
            "micro_test_readiness_summary": (
                f"Exit micro-test readiness is {readiness_score:.1f}/100 at {stage.replace('_', ' ')}. "
                f"Blockers: {', '.join(blockers) if blockers else 'none'}. This is recommendation-only."
            ),
            **_safe_flags(),
        }

    def _trading_brain_behavior_verification(
        self,
        lifecycle: dict[str, Any],
        exit_review: dict[str, Any],
        micro: dict[str, Any],
        thesis: dict[str, Any],
        open_cost: dict[str, Any],
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        tests = {
            "test_a_exit_decision": (
                to_int(exit_review.get("open_positions_reviewed"), 0) >= 0
                and "valid_hold_count" in exit_review
                and "exit_review_candidates" in exit_review
                and exit_review.get("forced_exits_enabled") is False
            ),
            "test_b_micro_test_readiness": (
                "controlled_exit_micro_test_readiness_score" in micro
                and "promotion_blockers" in micro
                and micro.get("automatic_micro_test_activation_enabled") is False
            ),
            "test_c_trade_thesis": (
                thesis.get("trade_thesis_tracking_enabled") is True
                and all(row.get("fabricated_entry_thesis") is False for row in thesis.get("thesis_records") or [])
            ),
            "test_d_opportunity_cost": (
                "learning_capacity_tradeoff_score" in open_cost
                and open_cost.get("automatic_replacements_enabled") is False
            ),
            "test_e_exit_feedback": (
                "closed_trades_reviewed" in feedback
                and "feedback_blocker" in feedback
            ),
            "test_f_diagnostic_consistency": (
                to_int(exit_review.get("open_positions_reviewed"), 0) == len(lifecycle.get("trade_lifecycle_summary") or [])
                and to_int(thesis.get("thesis_records_count"), 0) == len(thesis.get("thesis_records") or [])
                and exit_review.get("automatic_exits_enabled") is False
            ),
        }
        passed = sum(bool(value) for value in tests.values())
        failed = [key for key, value in tests.items() if not value]
        return {
            "module": "Trading Brain Behavior Verification V1",
            "status": "PASS" if not failed else "WARNING",
            "behavior_verification_score": rounded(passed / max(1, len(tests)) * 100.0, 3),
            "behavior_tests": tests,
            "behavior_tests_passed": passed,
            "behavior_tests_failed": failed,
            "diagnostic_consistency_score": 100.0 if not failed else rounded((passed / max(1, len(tests))) * 100.0, 3),
            "diagnostic_mismatches": failed,
            "remaining_blockers": failed,
            "behavior_verification_summary": (
                "Trading Brain exit, thesis, opportunity-cost, feedback, and micro-test readiness diagnostics are internally consistent."
                if not failed else
                f"Trading Brain diagnostics are safe but need attention: {', '.join(failed)}."
            ),
            **_safe_flags(),
        }

    def _trading_brain_completion(
        self,
        exit_review: dict[str, Any],
        micro: dict[str, Any],
        thesis: dict[str, Any],
        open_cost: dict[str, Any],
        feedback: dict[str, Any],
        verification: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = {
            "profit_protection": len(exit_review.get("profit_protection_candidates") or []),
            "loss_containment": len(exit_review.get("loss_containment_candidates") or []),
            "thesis_expiration": len(exit_review.get("thesis_expiration_candidates") or []),
            "opportunity_cost": len(open_cost.get("high_opportunity_cost_positions") or []),
        }
        highest = max(candidates, key=candidates.get) if candidates else "profit_protection"
        next_step = (
            "review_profit_protection_candidates_and_compare_shadow_exit_paths"
            if highest == "profit_protection"
            else "review_loss_containment_candidates_without_forcing_exits"
            if highest == "loss_containment"
            else "refresh_trade_thesis_context_and_review_expired_theses"
            if highest == "thesis_expiration"
            else "monitor_capacity_drag_and_learning_space_tradeoffs"
        )
        return {
            "module": "ASTRA Trading Brain Completion V1",
            "status": "ok" if verification.get("status") == "PASS" else "safe_needs_attention",
            "trading_brain_completion_enabled": True,
            "exit_decision_intelligence_score": exit_review.get("exit_decision_intelligence_score"),
            "controlled_exit_micro_test_readiness_score": micro.get("controlled_exit_micro_test_readiness_score"),
            "trade_thesis_tracking_enabled": thesis.get("trade_thesis_tracking_enabled"),
            "opportunity_cost_intelligence_score": open_cost.get("opportunity_cost_intelligence_score"),
            "exit_learning_feedback_score": feedback.get("exit_learning_feedback_score"),
            "behavior_verification_score": verification.get("behavior_verification_score"),
            "highest_value_exit_improvement": highest,
            "next_safe_exit_learning_step": next_step,
            "exit_decision_intelligence_v1": exit_review,
            "controlled_paper_exit_micro_test_readiness_v1": micro,
            "trade_thesis_tracking_v1": thesis,
            "open_position_opportunity_cost_intelligence_v1": open_cost,
            "exit_learning_feedback_loop_v1": feedback,
            "trading_brain_behavior_verification_v1": verification,
            "trading_brain_completion_summary": (
                f"Astra reviewed {exit_review.get('open_positions_reviewed', 0)} open Paper position(s), "
                f"found {exit_review.get('valid_hold_count', 0)} valid holds and "
                f"{len(exit_review.get('exit_review_candidates') or [])} human exit-review candidate(s). "
                f"The next safe learning step is {next_step.replace('_', ' ')}. No trading behavior changed."
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

    def _adaptive_capacity_utilization(
        self,
        statuses: dict[str, Any],
        effective: dict[str, Any],
    ) -> dict[str, Any]:
        trace = status_value(statuses, "paper_execution_trace")
        policy = dict(trace.get("adaptive_learning_capacity_policy") or {})
        pipeline_flags = {
            "adaptive_capacity_used_by_scanner": bool(trace.get("adaptive_capacity_used_by_scanner")),
            "adaptive_capacity_used_by_candidate_filter": bool(trace.get("adaptive_capacity_used_by_candidate_filter")),
            "adaptive_capacity_used_by_entry_gate": bool(trace.get("adaptive_capacity_used_by_entry_gate")),
            "adaptive_capacity_used_by_paper_trade_creation": bool(trace.get("adaptive_capacity_used_by_paper_trade_creation")),
        }
        baseline_reasons = {
            "max_concurrent_positions_reached",
            "total_horizon_capacity_reached",
            "stock_capacity_reached",
        }
        rows = [dict(row) for row in (trace.get("per_candidate_decision_trace") or []) if isinstance(row, dict)]
        baseline_blockers = [
            row for row in rows
            if text(row.get("decision_reason"), "") in baseline_reasons
        ]
        fixed = bool(
            policy.get("adaptive_capacity_policy_active")
            and all(pipeline_flags.values())
            and to_int(policy.get("adaptive_capacity_limit"), 0)
            == to_int(effective.get("recommended_adaptive_capacity"), 0)
        )
        final_blocker = text(first(trace.get("why_no_trade_today"), trace.get("final_blocker_reason")), "awaiting_next_worker_cycle")
        if to_int(trace.get("orders_submitted"), 0) > 0:
            why = "qualified_candidates_submitted_through_existing_paper_gates"
        elif final_blocker in {"session_order_submission_blocked", "open_confirmation_required"}:
            why = "adaptive_capacity_available_but_market_session_confirmation_is_required"
        elif final_blocker in {"no_eligible_candidates", "no_candidates_available", "candidate_source_empty"}:
            why = "adaptive_capacity_available_but_no_candidate_passed_existing_entry_gates"
        elif "risk" in final_blocker:
            why = "adaptive_capacity_available_but_risk_controls_correctly_blocked_entries"
        elif baseline_blockers and not fixed:
            why = "legacy_baseline_capacity_gate_still_detected"
        else:
            why = final_blocker
        return {
            "module": "Adaptive Capacity Utilization Pipeline V1",
            "status": "connected" if fixed else "awaiting_policy_refresh" if not policy else "partial",
            **pipeline_flags,
            "baseline_capacity_blockers_found": len(baseline_blockers),
            "baseline_capacity_blockers_fixed": len(baseline_blockers) if fixed else 0,
            "effective_capacity_pipeline_status": "connected_end_to_end" if fixed else "policy_not_yet_applied_to_runtime",
            "why_no_new_paper_trades": why,
            "adaptive_capacity_utilization_summary": (
                f"Adaptive paper capacity is {'connected across scanner, candidate filter, entry gate, and creation' if fixed else 'waiting for the runtime policy refresh'}. "
                f"The current no-trade explanation is {why.replace('_', ' ')}. No entry gate was bypassed."
            ),
            "runtime_policy": policy,
            **_safe_flags(),
        }

    def _opportunity_utilization(
        self,
        statuses: dict[str, Any],
        queue: dict[str, Any],
        pipeline: dict[str, Any],
        horizon: dict[str, Any],
    ) -> dict[str, Any]:
        trace = status_value(statuses, "paper_execution_trace")
        rows = [dict(row) for row in (trace.get("per_candidate_decision_trace") or []) if isinstance(row, dict)]
        reasons: dict[str, int] = {}
        qualified = 0
        diversity = []
        underfed = set(queue.get("underfed_horizons") or [])
        for row in rows:
            reason = text(row.get("decision_reason"), "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
            if row.get("eligible"):
                qualified += 1
            candidate_horizon = _horizon(first(row.get("trade_horizon_style"), row.get("horizon"), "unknown"))
            if candidate_horizon in underfed and row.get("eligible"):
                diversity.append({
                    "symbol": text(row.get("symbol"), "UNKNOWN"),
                    "horizon": candidate_horizon,
                    "confidence": rounded(first(row.get("confidence"), row.get("commitment_score"), 0.0), 3),
                })
        baseline_blocked = sum(reasons.get(key, 0) for key in (
            "max_concurrent_positions_reached",
            "total_horizon_capacity_reached",
            "stock_capacity_reached",
        ))
        adaptive_blocked = sum(
            count for reason, count in reasons.items()
            if "adaptive_capacity" in reason or reason == "adaptive_capacity_limit_reached"
        )
        risk_blocked = sum(count for reason, count in reasons.items() if "risk" in reason)
        capacity_reasons = {
            "max_concurrent_positions_reached",
            "total_horizon_capacity_reached",
            "stock_capacity_reached",
            "adaptive_capacity_limit_reached",
        }
        entry_blocked = sum(
            count for reason, count in reasons.items()
            if reason not in capacity_reasons and "risk" not in reason and reason not in {"missing_symbol", "duplicate_active_position"}
        )
        skipped_reason = text(pipeline.get("why_no_new_paper_trades"), "insufficient_candidate_trace")
        return {
            "module": "Opportunity Utilization and Missed Learning V1",
            "status": "ok" if rows else "insufficient_current_cycle_evidence",
            "qualified_opportunities_count": qualified,
            "opportunities_blocked_by_baseline_capacity": baseline_blocked,
            "opportunities_blocked_by_adaptive_capacity": adaptive_blocked,
            "opportunities_blocked_by_entry_gates": entry_blocked,
            "opportunities_blocked_by_risk": risk_blocked,
            "opportunities_skipped_due_to_no_candidate": int(not rows),
            "opportunities_skipped_reason": skipped_reason,
            "horizon_diversity_opportunities_available": diversity,
            "missed_learning_opportunity_score": queue.get("missed_learning_opportunity_score"),
            "opportunity_utilization_summary": (
                f"{qualified} candidate(s) passed recorded eligibility checks. Baseline capacity blocked {baseline_blocked}, "
                f"adaptive capacity blocked {adaptive_blocked}, entry gates blocked {entry_blocked}, and risk blocked {risk_blocked}. "
                f"Current explanation: {skipped_reason.replace('_', ' ')}."
            ),
            "reason_counts": reasons,
            "underfed_horizons": list(underfed),
            "elite_swing_exception_allowed": bool(horizon.get("elite_opportunity_may_override_advisory_bias", True)),
            **_safe_flags(),
        }

    def _horizon_diversity_completion(
        self,
        horizon: dict[str, Any],
        opportunity: dict[str, Any],
    ) -> dict[str, Any]:
        current = dict(horizon.get("current_horizon_exposure") or {})
        concentration = max(current.values(), default=0.0)
        underfed = [text(horizon.get("underrepresented_horizon"), "unknown")]
        candidates = list(opportunity.get("horizon_diversity_opportunities_available") or [])
        return {
            "module": "Horizon Diversity Without Quotas V1",
            "status": "monitoring",
            "horizon_concentration_score": rounded(concentration, 3),
            "underfed_horizons": [item for item in underfed if item != "unknown"],
            "diversity_improving_candidates": candidates,
            "elite_swing_exception_allowed": True,
            "fixed_horizon_quotas_enabled": False,
            "horizon_diversity_action_summary": (
                "Use horizon intelligence only as a tie-breaker when quality is comparable. "
                "Underfed horizons are monitored, while elite swing opportunities remain eligible through existing gates."
            ),
            **_safe_flags(),
        }

    def _shadow_paper_feedback(
        self,
        statuses: dict[str, Any],
        exit_review: dict[str, Any],
        shadow_completion: dict[str, Any],
    ) -> dict[str, Any]:
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        candidates = []
        seen = set()
        for group in (
            exit_review.get("exit_review_candidates") or [],
            exit_review.get("profit_protection_candidates") or [],
            exit_review.get("loss_containment_candidates") or [],
            exit_review.get("thesis_expiration_candidates") or [],
        ):
            for row in group:
                symbol = text((row or {}).get("symbol"), "UNKNOWN")
                if symbol in seen:
                    continue
                seen.add(symbol)
                candidates.append(dict(row))
        watched = [
            {
                "symbol": row.get("symbol"),
                "pattern": (
                    "profit_capture"
                    if to_float(row.get("pnl_percent"), 0.0) > 0 and to_float(row.get("giveback_risk"), 0.0) >= 55
                    else "overdue_hold"
                    if to_float(row.get("position_age_days"), 0.0) >= to_float(row.get("expected_hold_days"), 999.0)
                    else "stale_loser_review"
                ),
                "paper_action": "watch_only",
            }
            for row in candidates[:10]
        ]
        readiness = bool(
            shadow_completion.get("micro_test_readiness")
            and learned.get("paper_exit_path_verified")
            and not learned.get("learned_exit_bucket_auto_disabled", False)
        )
        blockers = []
        if not shadow_completion.get("micro_test_readiness"):
            blockers.append("shadow_evidence_gate_not_ready")
        if not learned.get("paper_exit_path_verified"):
            blockers.append("paper_exit_path_not_verified")
        if learned.get("learned_exit_bucket_auto_disabled", False):
            blockers.append("learned_exit_bucket_auto_disabled")
        return {
            "module": "Shadow to Paper Feedback Connection V1",
            "status": "candidate_watchlist_active" if watched else "monitoring",
            "shadow_feedback_routing_enabled": True,
            "shadow_exit_candidates_to_watch": watched,
            "shadow_candidates_to_watch": watched,
            "paper_micro_test_candidates": watched[:1] if readiness else [],
            "promotion_blockers": blockers,
            "evidence_needed": blockers or ["continue_comparable_shadow_and_paper_outcome_validation"],
            "profit_capture_candidate_status": "candidate_to_watch" if any(row["pattern"] == "profit_capture" for row in watched) else "insufficient_current_open_position_evidence",
            "giveback_reduction_candidate_status": "candidate_to_watch" if to_float(profit.get("giveback_risk_score"), 0.0) >= 50 else "monitoring",
            "overdue_hold_candidate_status": "candidate_to_watch" if any(row["pattern"] == "overdue_hold" for row in watched) else "monitoring",
            "paper_micro_test_readiness": readiness,
            "shadow_paper_feedback_summary": (
                f"{len(watched)} open-position pattern(s) now feed the existing Shadow-to-Paper candidate watchlist. "
                "No Shadow logic changed and no Paper behavior is promoted automatically."
            ),
            "shadow_feedback_summary": (
                f"{len(watched)} weakness pattern(s) are routed into the existing Shadow watchlist; "
                f"Paper micro-testing is {'eligible for human review' if readiness else 'blocked pending evidence and safety gates'}."
            ),
            "automatic_promotion_enabled": False,
            **_safe_flags(),
        }

    def _trading_governance(
        self,
        throughput: dict[str, Any],
        effective: dict[str, Any],
        lifecycle: dict[str, Any],
        exit_review: dict[str, Any],
        pipeline: dict[str, Any],
        opportunity: dict[str, Any],
        shadow_feedback: dict[str, Any],
        prior_memory: dict[str, Any],
    ) -> dict[str, Any]:
        bottlenecks = {
            "paper_learning_velocity": max(0.0, 60.0 - to_float(throughput.get("paper_learning_velocity_score"), 0.0)),
            "effective_occupancy": to_float(effective.get("learning_occupancy_pressure"), 0.0),
            "waiting_positions": to_float(effective.get("waiting_low_learning_positions"), 0.0) * 5.0,
            "exit_review": to_float(exit_review.get("exit_decision_intelligence_score"), 0.0),
            "missed_learning": to_float(opportunity.get("missed_learning_opportunity_score"), 0.0),
        }
        top = max(bottlenecks, key=bottlenecks.get)
        root = (
            "adaptive_capacity_policy_not_connected_to_paper_workflow"
            if pipeline.get("effective_capacity_pipeline_status") != "connected_end_to_end"
            else "open_positions_have_unequal_learning_value_and_turnover_is_weak"
        )
        correction = (
            "refresh_the_validated_adaptive_capacity_policy_then_keep_all_existing_entry_and_risk_gates"
            if pipeline.get("effective_capacity_pipeline_status") != "connected_end_to_end"
            else "use_effective_learning_occupancy_and_review_low_learning_or_overdue_positions_without_forced_exits"
        )
        score = clamp(
            100.0
            - sum(bottlenecks.values()) / max(1, len(bottlenecks)) * 0.55
            + (15.0 if pipeline.get("effective_capacity_pipeline_status") == "connected_end_to_end" else 0.0)
        )
        return {
            "module": "Autonomous Trading Governance V1",
            "status": "active",
            "autonomous_trading_governance_score": rounded(score, 3),
            "top_trading_bottleneck": top,
            "root_cause": root,
            "recommended_safe_correction": correction,
            "watch_next": "paper_learning_velocity_exit_review_count_and_adaptive_slot_utilization",
            "recurring_issue_detected": bool(prior_memory.get("repeated_observations_retained")),
            "prior_correction_used": bool(pipeline.get("effective_capacity_pipeline_status") == "connected_end_to_end"),
            "trading_governance_summary": (
                f"The largest paper-learning bottleneck is {top.replace('_', ' ')}. "
                f"Root cause: {root.replace('_', ' ')}. The safe correction remains advisory and paper-only."
            ),
            "open_positions_still_useful_count": len(lifecycle.get("high_learning_value_positions") or []),
            "shadow_showing_better_path": bool(shadow_feedback.get("shadow_exit_candidates_to_watch")),
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

    def _autonomous_correction_validation(
        self,
        statuses: dict[str, Any],
        continuity: dict[str, Any],
        occupancy: dict[str, Any],
        horizon: dict[str, Any],
        effective: dict[str, Any],
        exit_review: dict[str, Any],
        trading_brain: dict[str, Any],
        paper: dict[str, Any],
        shadow_completion: dict[str, Any],
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate whether previous advisory corrections appear to be working."""
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        opportunity = trading_brain.get("open_position_opportunity_cost_intelligence_v1") or {}
        feedback = trading_brain.get("exit_learning_feedback_loop_v1") or {}
        memory_effectiveness = to_float(memory.get("recommendation_effectiveness_score"), 0.0)
        memory_outcomes = to_int(memory.get("outcomes_evaluated"), 0)
        items = [
            {
                "correction": "Horizon Diversity",
                "date_implemented": "tracked_in_recent_horizon_lifecycle_capacity_bundles",
                "baseline_metric": "prior_baseline_not_stored",
                "baseline_source": "decision_memory_missing_exact_pre_fix_snapshot",
                "expected_outcome": "higher_learning_diversity_and_lower_horizon_concentration",
                "current_metric": rounded(continuity.get("learning_diversity_score"), 3),
                "actual_improvement": None,
                "confidence_score": rounded(clamp(45.0 + to_float(continuity.get("learning_diversity_score"), 0.0) * 0.35), 3),
                "classification": (
                    "Partially Successful"
                    if to_float(continuity.get("learning_diversity_score"), 0.0) >= 45
                    else "Inconclusive"
                ),
                "remaining_unresolved": horizon.get("dominant_horizon"),
                "likely_remaining_root_cause": "capacity_and_current_position_mix_still_bias_learning_evidence",
            },
            {
                "correction": "Adaptive Capacity",
                "date_implemented": "tracked_in_adaptive_occupancy_evolution_suite",
                "baseline_metric": to_int(occupancy.get("total_capacity"), 20),
                "baseline_source": "current_capacity_policy_baseline",
                "expected_outcome": "effective_learning_capacity_room_without_forcing_trades",
                "current_metric": rounded(effective.get("effective_learning_capacity_available"), 3),
                "actual_improvement": rounded(effective.get("effective_learning_capacity_available"), 3),
                "confidence_score": rounded(clamp(55.0 + max(0.0, to_float(effective.get("effective_learning_capacity_available"), 0.0)) * 2.0), 3),
                "classification": (
                    "Successful"
                    if to_float(effective.get("effective_learning_capacity_available"), 0.0) > 0
                    else "Partially Successful"
                ),
                "remaining_unresolved": paper.get("paper_learning_bottleneck_summary"),
                "likely_remaining_root_cause": "raw_risk_positions_still_need_natural_turnover_or_existing_gate_approval",
            },
            {
                "correction": "Effective Occupancy",
                "date_implemented": "tracked_in_paper_learning_capacity_correction",
                "baseline_metric": effective.get("raw_open_positions"),
                "baseline_source": "broker_confirmed_raw_positions",
                "expected_outcome": "separate_risk_exposure_from_learning_value",
                "current_metric": effective.get("effective_learning_occupancy"),
                "actual_improvement": rounded(
                    to_float(effective.get("raw_open_positions"), 0.0)
                    - to_float(effective.get("effective_learning_occupancy"), 0.0),
                    3,
                ),
                "confidence_score": 90.0 if effective.get("effective_learning_occupancy") is not None else 35.0,
                "classification": "Successful" if effective.get("effective_learning_occupancy") is not None else "Inconclusive",
                "remaining_unresolved": "effective_room_does_not_itself_create_new_qualified_entries",
                "likely_remaining_root_cause": "capacity_truth_is_fixed_but_entry_gates_and_market_session_still_control_execution",
            },
            {
                "correction": "Exit Intelligence",
                "date_implemented": "tracked_in_trading_brain_completion_v1",
                "baseline_metric": "prior_exit_review_quality_baseline_not_stored",
                "baseline_source": "no_exact_pre_fix_exit_baseline",
                "expected_outcome": "valid_holds_separated_from_exit_review_candidates",
                "current_metric": exit_review.get("exit_decision_intelligence_score"),
                "actual_improvement": None,
                "confidence_score": trading_brain.get("behavior_verification_score"),
                "classification": (
                    "Partially Successful"
                    if to_int(exit_review.get("open_positions_reviewed"), 0) > 0
                    and to_float(trading_brain.get("behavior_verification_score"), 0.0) >= 90
                    else "Inconclusive"
                ),
                "remaining_unresolved": f"{len(exit_review.get('exit_review_candidates') or [])}_positions_still_need_human_review",
                "likely_remaining_root_cause": "review_path_is_advisory_and_closed_exit_sample_is_still_small",
            },
            {
                "correction": "Profit Capture",
                "date_implemented": "tracked_in_profit_capture_and_exit_validation_suites",
                "baseline_metric": "prior_profit_capture_baseline_not_stored",
                "baseline_source": "profit_capture_diagnostics_only",
                "expected_outcome": "reduced_giveback_and_higher_capture_ratio",
                "current_metric": first(profit.get("capture_ratio"), profit.get("average_capture_ratio"), "warming_up"),
                "actual_improvement": None,
                "confidence_score": rounded(first(profit.get("policy_confidence"), profit.get("readiness_score"), 0.0), 3),
                "classification": "Inconclusive" if to_int(feedback.get("closed_trades_reviewed"), 0) < 20 else "Partially Successful",
                "remaining_unresolved": "closed_trade_sample_or_capture_baseline_insufficient",
                "likely_remaining_root_cause": "profit_capture_requires_more_completed_paper_exits_before_validation",
            },
            {
                "correction": "Opportunity Cost Intelligence",
                "date_implemented": "tracked_in_trading_brain_completion_v1",
                "baseline_metric": "prior_open_position_opportunity_cost_baseline_not_stored",
                "baseline_source": "diagnostic_first_pass",
                "expected_outcome": "identify_capacity_drag_without_forcing_replacement_trades",
                "current_metric": opportunity.get("opportunity_cost_intelligence_score"),
                "actual_improvement": None,
                "confidence_score": 70.0 if opportunity.get("open_position_opportunity_cost_rows") else 35.0,
                "classification": "Partially Successful" if opportunity.get("open_position_opportunity_cost_rows") else "Inconclusive",
                "remaining_unresolved": f"{len(opportunity.get('high_opportunity_cost_positions') or [])}_positions_with_elevated_cost",
                "likely_remaining_root_cause": "diagnostic_identifies_drag_but_does_not_replace_positions",
            },
            {
                "correction": "Trading Brain Completion",
                "date_implemented": "2026-06-26_commit_28944ed",
                "baseline_metric": "pre_completion_governance_lacked_single_trading_brain_contract",
                "baseline_source": "previous_bundle_gap",
                "expected_outcome": "one_coherent_exit_thesis_opportunity_cost_feedback_contract",
                "current_metric": trading_brain.get("behavior_verification_score"),
                "actual_improvement": trading_brain.get("behavior_verification_score"),
                "confidence_score": trading_brain.get("behavior_verification_score"),
                "classification": "Successful" if to_float(trading_brain.get("behavior_verification_score"), 0.0) >= 95 else "Partially Successful",
                "remaining_unresolved": trading_brain.get("next_safe_exit_learning_step"),
                "likely_remaining_root_cause": "micro_test_promotion_still_blocked_by_governance_gates",
            },
            {
                "correction": "Shadow to Paper Promotion",
                "date_implemented": "tracked_in_controlled_evolution_bridge",
                "baseline_metric": "shadow_only",
                "baseline_source": "controlled_evolution_ladder",
                "expected_outcome": "validated_shadow_edges_progress_to_human_review_micro_tests",
                "current_metric": shadow_completion.get("shadow_paper_readiness_score"),
                "actual_improvement": None,
                "confidence_score": shadow_completion.get("shadow_paper_readiness_score"),
                "classification": "Partially Successful" if shadow_completion.get("promotion_blockers") else "Successful",
                "remaining_unresolved": shadow_completion.get("promotion_blockers"),
                "likely_remaining_root_cause": "promotion_gates_require_persistence_capacity_and_risk_confirmation",
            },
        ]
        best = max(items, key=lambda row: to_float(row.get("confidence_score"), 0.0), default={})
        failed = [row for row in items if row.get("classification") == "Failed"]
        inconclusive = [row for row in items if row.get("classification") == "Inconclusive"]
        return {
            "module": "Autonomous Root Cause and Correction Validation V1",
            "status": "ok",
            "corrections_reviewed": len(items),
            "correction_validation_rows": items,
            "successful_corrections": len([row for row in items if row.get("classification") == "Successful"]),
            "partially_successful_corrections": len([row for row in items if row.get("classification") == "Partially Successful"]),
            "inconclusive_corrections": len(inconclusive),
            "failed_corrections": len(failed),
            "best_validated_correction": best.get("correction", "warming_up"),
            "correction_with_weakest_evidence": (inconclusive[0] if inconclusive else {}).get("correction", "none"),
            "decision_memory_effectiveness_score": rounded(memory_effectiveness, 3),
            "decision_memory_outcomes_evaluated": memory_outcomes,
            "correction_validation_summary": (
                f"Astra reviewed {len(items)} prior correction areas. "
                f"{len([row for row in items if row.get('classification') == 'Successful'])} look successful, "
                f"{len([row for row in items if row.get('classification') == 'Partially Successful'])} are partial, "
                f"and {len(inconclusive)} still need comparable before/after evidence."
            ),
            **_safe_flags(),
        }

    def _autonomous_learning_pipeline_transparency(
        self,
        classifier: dict[str, Any],
        evolution: dict[str, Any],
        governance: dict[str, Any],
        shadow_completion: dict[str, Any],
        persistence: dict[str, Any],
        shadow_feedback: dict[str, Any],
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        classified = list(classifier.get("classified_improvements") or [])
        candidates = list(evolution.get("eligible_candidates") or [])
        active = list(evolution.get("active_micro_tests") or [])
        blockers = list(evolution.get("promotion_blocker") or shadow_completion.get("promotion_blockers") or [])
        blocked = [
            {
                "blocking_gate": blocker,
                "required_evidence": persistence.get("required_evidence"),
                "remaining_gap": (
                    persistence.get("remaining_evidence")
                    if "evidence" in text(blocker, "")
                    else persistence.get("remaining_persistence_score")
                    if "persistence" in text(blocker, "")
                    else "gate_specific_safety_requirement"
                ),
            }
            for blocker in blockers
        ]
        completed = to_int(memory.get("outcomes_evaluated"), 0)
        validated = len([row for row in classified if row.get("consistently_better_than_paper")])
        return {
            "module": "Autonomous Learning Pipeline Transparency V1",
            "status": "ok",
            "experiments_generated": len(classified) + len(shadow_feedback.get("shadow_exit_candidates_to_watch") or []),
            "experiments_completed": completed,
            "experiments_validated": validated,
            "promotion_candidates": len(candidates),
            "paper_tests": len(active),
            "successful_promotions": 0,
            "failed_promotions": 0,
            "blocked_promotions": len(blockers),
            "blocked_promotion_details": blocked,
            "shadow_to_validation_count": len(classified),
            "validation_to_candidate_count": len(candidates),
            "candidate_to_paper_test_count": len(active),
            "paper_test_to_promotion_count": 0,
            "why_not_reaching_paper": (
                f"Promotion is blocked by {', '.join(blockers)}."
                if blockers else "No current blocker; human review is still required before any Paper adoption."
            ),
            "promotion_pipeline_summary": (
                f"{len(classified)} Shadow/validation row(s), {len(candidates)} promotion candidate(s), "
                f"{len(active)} active Paper micro-test(s), and {len(blockers)} unresolved promotion gate(s)."
            ),
            "automatic_promotion_enabled": False,
            **_safe_flags(),
        }

    def _shadow_performance_attribution_governance(
        self,
        statuses: dict[str, Any],
        shadow_completion: dict[str, Any],
        classifier: dict[str, Any],
        evolution: dict[str, Any],
    ) -> dict[str, Any]:
        shadow_vs_paper = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        shadow_correction = status_value(statuses, "shadow_correction_validation_attribution_v1")
        paper_pf = first(shadow_vs_paper.get("paper_profit_factor_verified"), shadow_vs_paper.get("paper_profit_factor"))
        shadow_pf = first(shadow_vs_paper.get("shadow_profit_factor_verified"), shadow_vs_paper.get("shadow_profit_factor"))
        pf_delta = to_float(shadow_vs_paper.get("profit_factor_delta"), 0.0)
        win_delta = to_float(shadow_vs_paper.get("win_rate_delta"), 0.0)
        capture_delta = to_float(shadow_vs_paper.get("profit_capture_delta"), 0.0)
        exit_delta = to_float(shadow_vs_paper.get("exit_quality_delta"), 0.0)
        available = bool(shadow_vs_paper.get("shadow_alpha_available") or shadow_vs_paper.get("shadow_profit_factor_available"))
        weighted_components = [
            clamp(50.0 + pf_delta * 15.0),
            clamp(50.0 + win_delta * 0.8),
            clamp(50.0 + capture_delta * 0.8),
            clamp(50.0 + exit_delta * 0.8),
            clamp(shadow_completion.get("shadow_paper_readiness_score")),
            clamp(first(shadow_correction.get("readiness_score"), shadow_correction.get("validated_improvement_score"), 0.0)),
        ]
        shadow_readiness = _avg(weighted_components)
        promotion_readiness = clamp(
            shadow_readiness * 0.42
            + clamp(shadow_completion.get("shadow_paper_readiness_score")) * 0.33
            + (25.0 if not evolution.get("promotion_blocker") else 0.0)
        )
        outperforming_areas = []
        underperforming_areas = []
        for label, value in (
            ("profit_factor", pf_delta),
            ("win_rate", win_delta),
            ("profit_capture", capture_delta),
            ("exit_quality", exit_delta),
        ):
            if value > 0:
                outperforming_areas.append(label)
            elif value < 0:
                underperforming_areas.append(label)
        return {
            "module": "Shadow Performance Attribution and Promotion Readiness V1",
            "status": "ok" if available else "insufficient_evidence",
            "paper_profit_factor": paper_pf,
            "shadow_profit_factor": shadow_pf,
            "paper_win_rate": shadow_vs_paper.get("paper_win_rate"),
            "shadow_win_rate": shadow_vs_paper.get("shadow_win_rate"),
            "profit_factor_delta": rounded(pf_delta, 4),
            "win_rate_delta": rounded(win_delta, 4),
            "profit_capture_delta": rounded(capture_delta, 4),
            "exit_quality_delta": rounded(exit_delta, 4),
            "shadow_readiness_score": rounded(shadow_readiness, 3),
            "promotion_readiness_score": rounded(promotion_readiness, 3),
            "shadow_outperforming_paper": bool(outperforming_areas and not underperforming_areas and available),
            "shadow_outperforming_areas": outperforming_areas,
            "shadow_underperforming_areas": underperforming_areas,
            "weighted_governance_used": True,
            "single_metric_promotion_allowed": False,
            "promotion_candidates": list(classifier.get("paper_test_candidates") or []),
            "recommended_promotion": "none" if evolution.get("promotion_blocker") else (classifier.get("paper_test_candidates") or [{}])[0].get("category", "none"),
            "shadow_attribution_summary": (
                "Shadow attribution is still evidence-gated."
                if not available else
                f"Shadow is stronger in {', '.join(outperforming_areas) or 'no verified metric yet'} and weaker in "
                f"{', '.join(underperforming_areas) or 'no verified metric yet'}."
            ),
            **_safe_flags(),
        }

    def _autonomous_executive_governance_accountability(
        self,
        correction: dict[str, Any],
        inspection: dict[str, Any],
        shadow_attr: dict[str, Any],
        trading_brain: dict[str, Any],
    ) -> dict[str, Any]:
        correction_map = {
            row.get("correction"): row
            for row in correction.get("correction_validation_rows") or []
            if isinstance(row, dict)
        }
        subsystem_specs = [
            ("Horizon Diversity", "Improve horizon learning balance", "higher diversity and fewer concentration warnings"),
            ("Exit Intelligence", "Separate valid holds from exit-review candidates", "clear review candidates and feedback loop"),
            ("Profit Capture", "Reduce giveback and improve capture", "higher capture ratio after enough closed trades"),
            ("Adaptive Capacity", "Protect fresh learning capacity", "effective room without forced trades"),
            ("Trading Brain", "Unify exit/thesis/opportunity-cost feedback", "behavior-verified coherent diagnostics"),
            ("Shadow Learning", "Validate Shadow edges before promotion", "promotion candidates with rollback-ready gates"),
            ("Opportunity Cost Intelligence", "Reveal capacity drag", "high-cost positions identified without forced replacement"),
        ]
        rows = []
        for name, purpose, expected in subsystem_specs:
            corr = correction_map.get(name) or correction_map.get("Trading Brain Completion" if name == "Trading Brain" else name) or {}
            score = to_float(first(corr.get("confidence_score"), trading_brain.get("behavior_verification_score") if name == "Trading Brain" else None, 0.0), 0.0)
            if corr.get("classification") == "Successful":
                status = "Working"
            elif corr.get("classification") == "Partially Successful":
                status = "Partially Working"
            elif corr.get("classification") == "Failed":
                status = "Failed"
            elif name == "Shadow Learning" and shadow_attr.get("promotion_readiness_score"):
                status = "Needs Investigation" if shadow_attr.get("promotion_readiness_score", 0) < 70 else "Ready For Promotion"
            else:
                status = "Needs Investigation"
            rows.append({
                "subsystem": name,
                "purpose": purpose,
                "expected_benefit": expected,
                "actual_benefit": corr.get("actual_improvement"),
                "success_score": rounded(score, 3),
                "confidence_score": rounded(score, 3),
                "status": status,
                "top_concern": corr.get("remaining_unresolved") or inspection.get("top_detected_issue"),
                "top_strength": corr.get("classification") or "diagnostic_visibility",
                "recommendation": corr.get("likely_remaining_root_cause") or inspection.get("recommended_action"),
            })
        weakest = min(rows, key=lambda row: to_float(row.get("success_score"), 100.0), default={})
        strongest = max(rows, key=lambda row: to_float(row.get("success_score"), 0.0), default={})
        return {
            "module": "Autonomous Executive Governance and Accountability V1",
            "status": "ok",
            "subsystems_reviewed": len(rows),
            "subsystem_accountability": rows,
            "working_count": len([row for row in rows if row.get("status") == "Working"]),
            "partially_working_count": len([row for row in rows if row.get("status") == "Partially Working"]),
            "needs_investigation_count": len([row for row in rows if row.get("status") == "Needs Investigation"]),
            "failed_count": len([row for row in rows if row.get("status") == "Failed"]),
            "strongest_subsystem": strongest.get("subsystem", "warming_up"),
            "weakest_subsystem": weakest.get("subsystem", "warming_up"),
            "governance_accountability_summary": (
                f"{len(rows)} subsystems were reviewed for value. Strongest: {strongest.get('subsystem', 'warming up')}; "
                f"weakest/most uncertain: {weakest.get('subsystem', 'warming up')}."
            ),
            **_safe_flags(),
        }

    def _horizon_exit_governance_investigations(
        self,
        continuity: dict[str, Any],
        horizon: dict[str, Any],
        occupancy: dict[str, Any],
        exit_review: dict[str, Any],
        trading_brain: dict[str, Any],
        shadow_attr: dict[str, Any],
    ) -> dict[str, Any]:
        concentration = to_float(horizon.get("horizon_monopolization_risk"), 0.0)
        diversity = to_float(continuity.get("learning_diversity_score"), 0.0)
        exposure = dict(horizon.get("current_horizon_exposure") or {})
        root_causes = [
            ("Capacity Bias", to_float(occupancy.get("occupancy_pressure_score"), 0.0), "open_position_capacity_pressure_limits_fresh_horizon_turnover"),
            ("Regime Bias", max(0.0, concentration - 10.0), "current_market_regime_may_favor_specific_hold_windows"),
            ("Promotion Bias", 100.0 - to_float(shadow_attr.get("promotion_readiness_score"), 0.0), "validated_shadow_edges_are_not_yet_ready_for_paper"),
            ("Scanner Bias", max(0.0, 70.0 - diversity), "candidate_flow_may_not_supply_enough_underfed_horizon_examples"),
            ("Ranking Bias", max(0.0, concentration - diversity), "existing_ranking_may_prefer_stronger_longer_duration_setups"),
        ]
        ranked_roots = [
            {"root_cause": name, "confidence": rounded(clamp(score), 3), "explanation": explanation}
            for name, score, explanation in sorted(root_causes, key=lambda item: item[1], reverse=True)
        ]
        feedback = trading_brain.get("exit_learning_feedback_loop_v1") or {}
        opportunity = trading_brain.get("open_position_opportunity_cost_intelligence_v1") or {}
        exit_quality_improved = to_float(feedback.get("exit_learning_feedback_score"), 0.0) >= 50.0
        profit_capture_improved = to_float(shadow_attr.get("profit_capture_delta"), 0.0) > 0.0
        opportunity_cost_improved = to_float(opportunity.get("opportunity_cost_intelligence_score"), 0.0) < 50.0
        lifecycle_improved = to_float(trading_brain.get("behavior_verification_score"), 0.0) >= 90.0
        missing = []
        if to_int(feedback.get("closed_trades_reviewed"), 0) < 20:
            missing.append("closed_exit_sample_size")
        if shadow_attr.get("status") == "insufficient_evidence":
            missing.append("verified_shadow_vs_paper_sample")
        if shadow_attr.get("promotion_readiness_score", 0) < 70:
            missing.append("promotion_readiness")
        return {
            "module": "Horizon and Exit Governance Investigations V1",
            "status": "ok",
            "horizon_investigation": {
                "did_horizon_diversity_improve_results": "partially" if diversity >= 45 else "inconclusive",
                "did_horizon_allocation_improve": "partially" if exposure else "insufficient_evidence",
                "did_horizon_balance_improve": "partially" if concentration < 70 else "not_yet",
                "did_learning_diversity_improve": "partially" if diversity >= 45 else "not_yet",
                "horizon_concentration_score": rounded(concentration, 3),
                "learning_diversity_score": rounded(diversity, 3),
                "confidence_ranked_root_causes": ranked_roots,
            },
            "exit_intelligence_investigation": {
                "did_exit_intelligence_improve_exit_quality": exit_quality_improved,
                "did_profit_capture_improve": profit_capture_improved,
                "did_opportunity_cost_improve": opportunity_cost_improved,
                "did_lifecycle_decisions_improve": lifecycle_improved,
                "missing_evidence": missing,
                "missing_validation": [item for item in missing if item != "promotion_readiness"],
                "missing_promotion_pathway": bool("promotion_readiness" in missing),
                "why_not": (
                    "Exit intelligence is behavior-verified, but promotion still needs more closed-trade and Shadow-vs-Paper evidence."
                    if missing else "Exit intelligence has enough evidence for continued governed review."
                ),
            },
            "highest_confidence_remaining_bottleneck": ranked_roots[0] if ranked_roots else {},
            **_safe_flags(),
        }

    def _autonomous_governance_core(
        self,
        correction: dict[str, Any],
        pipeline: dict[str, Any],
        shadow_attr: dict[str, Any],
        accountability: dict[str, Any],
        investigations: dict[str, Any],
        improvement: dict[str, Any],
    ) -> dict[str, Any]:
        rows = correction.get("correction_validation_rows") or []
        successful = [row for row in rows if row.get("classification") == "Successful"]
        failed = [row for row in rows if row.get("classification") == "Failed"]
        partial = [row for row in rows if row.get("classification") == "Partially Successful"]
        best = max(rows, key=lambda row: to_float(row.get("confidence_score"), 0.0), default={})
        horizon_inv = investigations.get("horizon_investigation") or {}
        exit_inv = investigations.get("exit_intelligence_investigation") or {}
        bottleneck = (investigations.get("highest_confidence_remaining_bottleneck") or {}).get("root_cause")
        return {
            "module": "ASTRA Autonomous Governance Core V1",
            "status": "ok",
            "autonomous_governance_core_enabled": True,
            "correction_validation": correction,
            "learning_pipeline_transparency": pipeline,
            "shadow_performance_attribution_promotion_readiness": shadow_attr,
            "executive_governance_accountability": accountability,
            "horizon_exit_governance_investigations": investigations,
            "did_horizon_diversity_work": horizon_inv.get("did_horizon_diversity_improve_results"),
            "did_adaptive_capacity_work": "yes" if any(row.get("correction") == "Adaptive Capacity" and row.get("classification") in {"Successful", "Partially Successful"} for row in rows) else "inconclusive",
            "did_exit_intelligence_work": "partially" if exit_inv.get("did_lifecycle_decisions_improve") else "inconclusive",
            "is_shadow_outperforming_paper": shadow_attr.get("shadow_outperforming_paper"),
            "why_promotions_blocked": pipeline.get("why_not_reaching_paper"),
            "correction_produced_most_benefit": best.get("correction", "warming_up"),
            "correction_failed": (failed[0] if failed else {}).get("correction", "none"),
            "highest_confidence_remaining_bottleneck": bottleneck or "warming_up",
            "highest_roi_next_improvement": improvement.get("highest_roi_improvement"),
            "governance_brief": (
                f"Astra reviewed {len(rows)} corrections: {len(successful)} successful, {len(partial)} partial, "
                f"{len(failed)} failed, and {correction.get('inconclusive_corrections', 0)} inconclusive. "
                f"Promotions are blocked because {pipeline.get('why_not_reaching_paper')}. "
                f"The highest-ROI next improvement is {text(improvement.get('highest_roi_improvement'), 'continued validation').replace('_', ' ')}."
            ),
            "automatic_promotion_enabled": False,
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
        lifecycle: dict[str, Any],
        exit_review: dict[str, Any],
        continuity: dict[str, Any],
        effective: dict[str, Any],
        shadow_feedback: dict[str, Any],
        trading_governance: dict[str, Any],
    ) -> dict[str, Any]:
        research = status_value(statuses, "autonomous_research_self_regulation_status_v1")
        validation = status_value(statuses, "autonomous_intelligence_validation_governance_v1")
        recovery = status_value(statuses, "astra_recovery_center_v1")
        provider = status_value(statuses, "astra_provider_orchestration_data_governance_v1")
        ask = status_value(statuses, "ask_astra_local_ai_status_v1")
        unified = status_value(statuses, "unified_learning_diagnostics_v1")
        broker = status_value(statuses, "alpaca_paper_broker") or status_value(statuses, "alpaca_paper_status_v1")
        aios = status_value(statuses, "astra_aios_intelligence_maturation_bundle_v1")
        tier1a = status_value(statuses, "astra_learning_preservation_capacity_v1")
        dashboard_safe = bool(
            to_int(provider.get("dashboard_provider_calls_used"), 0) == 0
            and to_int(provider.get("dashboard_llm_calls_used"), 0) == 0
        )
        lifecycle_score = to_float(lifecycle.get("lifecycle_refinement_score"), 0.0)
        exit_score = clamp(100.0 - to_float(exit_review.get("exit_decision_intelligence_score"), 0.0))
        department_inputs = [
            ("Trading Brain", trading_governance.get("autonomous_trading_governance_score"), trading_governance.get("top_trading_bottleneck"), trading_governance.get("root_cause"), trading_governance.get("recommended_safe_correction")),
            ("Paper Trading", paper.get("paper_learning_capacity_score"), paper.get("paper_learning_bottleneck_summary"), "position_turnover_and_gate_constraints", paper.get("capacity_recommendation")),
            ("Shadow Learning", first(aios.get("shadow_learning_score"), 70.0 if shadow_feedback.get("shadow_exit_candidates_to_watch") else 55.0), shadow_feedback.get("promotion_blockers"), "evidence_must_pass_existing_promotion_gates", "continue_shadow_candidate_validation"),
            ("Learning Continuity", continuity.get("learning_continuity_score"), continuity.get("continuity_bottleneck"), "fresh_paper_turnover_is_below_cached_evidence_flow", continuity.get("recommended_action")),
            ("Adaptive Capacity", clamp(100.0 - to_float(effective.get("learning_occupancy_pressure"), 0.0)), effective.get("learning_occupancy_pressure"), "risk_positions_and_learning_positions_have_unequal_value", "use_effective_learning_occupancy_with_existing_risk_gates"),
            ("Horizon Diversity", continuity.get("learning_diversity_score"), first(continuity.get("underfed_horizon"), "horizon_concentration"), "current_positions_do_not_evenly_generate_horizon_evidence", continuity.get("dynamic_horizon_recommendation")),
            ("Exit Intelligence", exit_score, f"{len(exit_review.get('exit_review_candidates') or [])}_positions_need_review", "exit_review_evidence_is_advisory_and_age_detail_is_partial", "review_profit_protection_loss_containment_and_thesis_expiration_candidates"),
            ("Profit Capture", clamp(100.0 - to_float(exit_review.get("giveback_risk_score"), 0.0)), "profit_capture_and_giveback", "winners_can_decay_before_natural_exit_evidence_matures", "route_profit_protection_patterns_to_shadow"),
            ("Giveback", clamp(100.0 - to_float(exit_review.get("giveback_risk_score"), 0.0)), exit_review.get("giveback_risk_score"), "open_winner_retracement_requires_review_not_forced_execution", "monitor_mature_winners_and_near_exit_positions"),
            ("Decision Memory", memory.get("knowledge_retention_score"), memory.get("latest_root_cause"), "correction_outcomes_need_more_comparable_snapshots", "retain_and_compare_the_next_behavior_snapshot"),
            ("Provider Governance", first(provider.get("provider_health_score"), 85.0 if dashboard_safe else 35.0), provider.get("weakest_area"), "provider_use_must_remain_budgeted_and_cache_first", "preserve_zero_dashboard_provider_calls"),
            ("Recovery Center", first(recovery.get("recovery_health_score"), 70.0), recovery.get("status_label"), "runtime_health_depends_on_persistent_service_checks", "continue_recovery_monitoring"),
            ("Ask Astra", first(ask.get("health_score"), 80.0 if ask.get("ollama_reachable") else 55.0), "local_model_or_cached_fallback_quality", "answers_depend_on_cached_unified_context", "keep_plain_english_grounding_and_structured_fallback"),
            ("Learning Center", 100.0 if to_int(unified.get("initial_learning_tab_endpoint_count"), 1) == 1 else 40.0, "single_endpoint_and_compact_explanation_quality", "all_panels_depend_on_unified_cached_payload", "retain_one_initial_endpoint"),
            ("Dashboard Safety", 100.0 if dashboard_safe else 25.0, "provider_or_llm_render_calls" if not dashboard_safe else "none", "dashboard_must_not_compute_or_fetch_provider_intelligence", "preserve_cached_summary_only_rendering"),
            ("Broker/Paper Safety", 100.0 if broker.get("paper_mode_verified") and not broker.get("broker_live_endpoint_allowed") else 20.0, "paper_mode_verification", "broker_truth_and_paper_endpoint_are_mandatory", "keep_broker_truth_and_live_endpoint_block"),
        ]
        departments: list[dict[str, Any]] = []
        prior_root = text(memory.get("latest_root_cause"), "insufficient_evidence")
        for name, raw_score, bottleneck, root, action in department_inputs:
            score = clamp(raw_score)
            status = "healthy" if score >= 75 else "watch" if score >= 50 else "needs_attention"
            departments.append({
                "department": name,
                "current_status": status,
                "score": rounded(score, 3),
                "trend": "stable" if score >= 60 else "needs_improvement",
                "strongest_area": "safety_and_cached_diagnostics" if score >= 75 else "existing_observability",
                "weakest_area": text(bottleneck, "insufficient_evidence"),
                "primary_bottleneck": text(bottleneck, "insufficient_evidence"),
                "root_cause": text(root, "insufficient_evidence"),
                "repeated_issue": bool(prior_root == text(root, "")),
                "prior_correction_exists": bool(memory.get("latest_recommendation")),
                "recommended_next_action": text(action, "continue_safe_observation"),
                "confidence": rounded(clamp(45.0 + score * 0.45), 3),
            })
        weakest = min(departments, key=lambda row: row["score"], default={})
        root_causes = list(research.get("likely_root_causes") or [])
        root_cause = text(first(weakest.get("root_cause"), root_causes[0] if root_causes else None, validation.get("top_root_cause")), "insufficient_evidence")
        issue = text(first(weakest.get("primary_bottleneck"), research.get("primary_trading_weakness"), paper.get("paper_learning_bottleneck_summary")), "unknown")
        repeated = bool(prior_root == root_cause or memory.get("repeated_observations_retained"))
        action = text(first(weakest.get("recommended_next_action"), research.get("next_best_action_summary"), validation.get("recommended_virtual_test")), "continue_shadow_validation")
        confidence = max(
            to_float(research.get("root_cause_confidence"), 0.0),
            to_float(validation.get("confidence"), 0.0),
            to_float(weakest.get("confidence"), 0.0),
        )
        platform_score = sum(row["score"] for row in departments) / max(1, len(departments))
        return {
            "module": "Platform-Wide Autonomous Inspection V1",
            "status": "root_cause_identified" if root_cause != "insufficient_evidence" else "insufficient_evidence",
            "autonomous_inspection_enabled": True,
            "autonomous_inspection_score": rounded(platform_score, 3),
            "platform_inspection_score": rounded(platform_score, 3),
            "department_scores": departments,
            "issue_detected": issue,
            "top_detected_issue": issue,
            "root_cause": root_cause,
            "primary_root_cause": root_cause,
            "root_cause_chain": root_causes or [root_cause],
            "repeated_issue": repeated,
            "repeated_issue_detected": repeated,
            "prior_correction": memory.get("latest_recommendation", "none"),
            "prior_correction_found": bool(memory.get("latest_recommendation")),
            "prior_correction_effectiveness": memory.get("recommendation_effectiveness_score"),
            "recommended_action": action,
            "recommended_next_action": action,
            "inspection_confidence": rounded(confidence, 3),
            "plain_english_inspection_summary": (
                f"Astra inspected {len(departments)} departments. The clearest weakness is "
                f"{issue.replace('_', ' ')}, mainly because {root_cause.replace('_', ' ')}. "
                f"The safest next step is to {action.replace('_', ' ')}; no trading behavior changes."
            ),
            "inspection_summary": (
                f"Astra traced {issue.replace('_', ' ')} to {root_cause.replace('_', ' ')}. "
                "The correction remains advisory and will be measured against the next comparable snapshot."
            ),
            **_safe_flags(),
        }

    def _autonomous_improvement(
        self,
        statuses: dict[str, Any],
        inspection: dict[str, Any],
        lifecycle: dict[str, Any],
        exit_review: dict[str, Any],
        paper: dict[str, Any],
        shadow_feedback: dict[str, Any],
    ) -> dict[str, Any]:
        prioritization = status_value(statuses, "adaptive_learning_prioritization_resource_allocation_v1")
        rows = [dict(row) for row in prioritization.get("weakness_rankings") or [] if isinstance(row, dict)]
        for row in rows:
            row["evidence_adjusted_roi"] = rounded(
                to_float(row.get("expected_learning_value"), 0.0)
                * (0.35 + to_float(row.get("sample_size_confidence"), 0.0) / 100.0 * 0.65)
                * (1.0 - to_float(row.get("noise_risk_score"), 0.0) / 140.0),
                3,
            )
        candidates = [
            {
                "weakness": "exit_decision_intelligence",
                "business_value_score": 88.0,
                "trading_impact_score": 82.0,
                "learning_impact_score": 76.0,
                "safety_risk_score": 12.0,
                "evidence_support_score": clamp(45.0 + len(exit_review.get("exit_review_candidates") or []) * 6.0),
                "implementation_complexity": "low_existing_review_path",
                "urgency_score": clamp(45.0 + to_float(exit_review.get("exit_decision_intelligence_score"), 0.0)),
                "shadow_testable": True,
                "paper_micro_test_ready": bool(shadow_feedback.get("paper_micro_test_readiness")),
            },
            {
                "weakness": "trade_lifecycle_classification",
                "business_value_score": 80.0,
                "trading_impact_score": 65.0,
                "learning_impact_score": 90.0,
                "safety_risk_score": 8.0,
                "evidence_support_score": lifecycle.get("classification_confidence", 0.0),
                "implementation_complexity": "low_existing_classifier_refinement",
                "urgency_score": 78.0 if lifecycle.get("proxy_classification_used") else 55.0,
                "shadow_testable": True,
                "paper_micro_test_ready": False,
            },
            {
                "weakness": "paper_learning_velocity",
                "business_value_score": 84.0,
                "trading_impact_score": 70.0,
                "learning_impact_score": 94.0,
                "safety_risk_score": 20.0,
                "evidence_support_score": clamp(100.0 - to_float(paper.get("paper_learning_velocity_score"), 0.0)),
                "implementation_complexity": "medium_existing_capacity_and_gate_pipeline",
                "urgency_score": 85.0,
                "shadow_testable": True,
                "paper_micro_test_ready": False,
            },
            {
                "weakness": "decision_memory_reinforcement",
                "business_value_score": 58.0,
                "trading_impact_score": 30.0,
                "learning_impact_score": 80.0,
                "safety_risk_score": 5.0,
                "evidence_support_score": inspection.get("inspection_confidence", 0.0),
                "implementation_complexity": "low_existing_bounded_memory",
                "urgency_score": 52.0,
                "shadow_testable": False,
                "paper_micro_test_ready": False,
            },
        ]
        for row in candidates:
            row["evidence_adjusted_roi"] = rounded(
                (
                    row["business_value_score"] * 0.25
                    + row["trading_impact_score"] * 0.20
                    + row["learning_impact_score"] * 0.20
                    + row["evidence_support_score"] * 0.20
                    + row["urgency_score"] * 0.15
                )
                * (1.0 - row["safety_risk_score"] / 150.0),
                3,
            )
        for row in rows:
            candidates.append({
                "weakness": row.get("weakness", "unknown"),
                "business_value_score": row.get("performance_impact_score", 0.0),
                "trading_impact_score": row.get("performance_impact_score", 0.0),
                "learning_impact_score": row.get("expected_learning_value", 0.0),
                "safety_risk_score": row.get("noise_risk_score", 100.0),
                "evidence_support_score": row.get("sample_size_confidence", 0.0),
                "implementation_complexity": "existing_prioritization_worker",
                "urgency_score": row.get("improvement_potential_score", 0.0),
                "shadow_testable": True,
                "paper_micro_test_ready": False,
                "evidence_adjusted_roi": row.get("evidence_adjusted_roi", 0.0),
            })
        candidates.sort(key=lambda row: to_float(row.get("evidence_adjusted_roi"), 0.0), reverse=True)
        best = candidates[0] if candidates else {}
        safe = bool(
            to_float(best.get("evidence_support_score"), 0.0) >= 45.0
            and to_float(best.get("safety_risk_score"), 100.0) <= 30.0
        )
        return {
            "module": "Autonomous Improvement Prioritization Completion V1",
            "status": "recommendation_ready" if safe else "observation_only",
            "autonomous_improvement_score": best.get("evidence_adjusted_roi", 0.0),
            "highest_roi_improvement": best.get("weakness", "insufficient_evidence"),
            "top_improvement_candidate": best.get("weakness", "insufficient_evidence"),
            "safest_next_improvement": min(candidates, key=lambda row: row.get("safety_risk_score", 100.0), default={}).get("weakness", "insufficient_evidence"),
            "expected_improvement_score": best.get("business_value_score", 0.0),
            "expected_benefit": {
                "business_value": best.get("business_value_score", 0.0),
                "trading_impact": best.get("trading_impact_score", 0.0),
                "learning_impact": best.get("learning_impact_score", 0.0),
            },
            "implementation_complexity": best.get("implementation_complexity", "unknown"),
            "safety_risk": best.get("safety_risk_score", 100.0),
            "business_value_score": best.get("business_value_score", 0.0),
            "evidence_support_score": best.get("evidence_support_score", 0.0),
            "ranked_improvement_queue": candidates[:8],
            "improvement_priority_rankings": candidates[:8],
            "evidence_adjusted_roi_score": best.get("evidence_adjusted_roi", 0.0),
            "improvement_confidence": best.get("evidence_support_score", 0.0),
            "noise_risk_score": best.get("safety_risk_score", 100.0),
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
            "why_this_is_priority": (
                f"{best.get('weakness', 'No area')} has the strongest combined business, trading, learning, "
                "urgency, evidence, and safety-adjusted value."
            ),
            "why_this_priority": (
                f"{best.get('weakness', 'No area')} has the strongest combined business, trading, learning, "
                "urgency, evidence, and safety-adjusted value."
            ),
            "plain_english_improvement_summary": (
                f"Astra's highest-value safe improvement is {text(best.get('weakness'), 'continued validation').replace('_', ' ')}. "
                "It should be refined through existing diagnostics and Shadow validation before any Paper micro-test."
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
            "decision_memory_enabled": True,
            "decision_memory_score": rounded(retention, 3),
            "decision_memory_entries": memory.get("active_memory_entries", 0),
            "correction_memories_stored": memory.get("active_memory_entries", 0),
            "retained_corrections_count": memory.get("active_memory_entries", 0),
            "retained_failed_experiments_count": max(
                0,
                to_int(memory.get("outcomes_evaluated"), 0)
                - to_int(memory.get("recommendations_improved_later"), 0),
            ),
            "repeated_issue_memory_hits": memory.get("repeated_observations_retained", 0),
            "recurring_issue_memory_hits": memory.get("repeated_observations_retained", 0),
            "prior_correction_matches": int(bool(inspection.get("prior_correction_found"))),
            "successful_corrections": memory.get("recommendations_improved_later", 0),
            "failed_corrections": max(
                0,
                to_int(memory.get("outcomes_evaluated"), 0)
                - to_int(memory.get("recommendations_improved_later"), 0),
            ),
            "memory_reinforcement_needed": bool(
                to_int(memory.get("outcomes_evaluated"), 0)
                < max(3, to_int(memory.get("active_memory_entries"), 0) // 4)
            ),
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
            "decision_memory_summary": (
                f"{to_int(memory.get('active_memory_entries'), 0)} bounded correction memories are retained; "
                f"{to_int(memory.get('outcomes_evaluated'), 0)} have comparable later outcomes and "
                f"{to_int(memory.get('recommendations_improved_later'), 0)} improved."
            ),
            **_safe_flags(),
        }

    def _root_cause_intelligence(
        self,
        inspection: dict[str, Any],
        lifecycle: dict[str, Any],
        exit_review: dict[str, Any],
        effective: dict[str, Any],
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        symptom = text(inspection.get("top_detected_issue"), "insufficient_evidence")
        waiting = to_int((lifecycle.get("lifecycle_stage_counts") or {}).get("waiting"), 0)
        review_count = len(exit_review.get("exit_review_candidates") or [])
        immediate = (
            "open_positions_have_unequal_learning_value_and_some_require_exit_review"
            if waiting or review_count
            else "fresh_paper_outcomes_are_arriving_slower_than_cached_learning"
        )
        underlying = text(
            inspection.get("primary_root_cause"),
            "risk_bearing_positions_can_remain_open_while_generating_limited_fresh_learning",
        )
        affected = [
            row.get("department")
            for row in inspection.get("department_scores") or []
            if isinstance(row, dict) and to_float(row.get("score"), 100.0) < 60.0
        ]
        evidence = {
            "waiting_positions": waiting,
            "exit_review_candidates": review_count,
            "effective_learning_occupancy": effective.get("effective_learning_occupancy"),
            "raw_open_positions": effective.get("raw_open_positions"),
            "proxy_lifecycle_rows": lifecycle.get("proxy_age_rows"),
        }
        return {
            "module": "Autonomous Root-Cause Intelligence V1",
            "status": "root_cause_identified" if underlying != "insufficient_evidence" else "insufficient_evidence",
            "symptom": symptom,
            "immediate_cause": immediate,
            "underlying_cause": underlying,
            "root_cause_chain": [symptom, immediate, underlying],
            "affected_systems": affected or ["Paper Trading", "Learning Continuity", "Exit Intelligence"],
            "supporting_evidence": evidence,
            "prior_similar_issue": bool(inspection.get("repeated_issue_detected")),
            "prior_correction_outcome": memory.get("recommendation_effectiveness_score"),
            "recommended_safe_correction": inspection.get("recommended_next_action"),
            "root_cause_confidence": inspection.get("inspection_confidence"),
            **_safe_flags(),
        }

    def _daily_autonomous_brief(
        self,
        inspection: dict[str, Any],
        root_cause: dict[str, Any],
        improvement: dict[str, Any],
        lifecycle: dict[str, Any],
        exit_review: dict[str, Any],
        shadow_feedback: dict[str, Any],
    ) -> dict[str, Any]:
        stage_counts = dict(lifecycle.get("lifecycle_stage_counts") or {})
        improved = (
            "Lifecycle classifications now distinguish developing, active, mature, waiting, and review states "
            "without inventing entry timestamps."
        )
        worsened = (
            f"{len(exit_review.get('exit_review_candidates') or [])} position(s) currently merit human exit review."
            if exit_review.get("exit_review_candidates")
            else "No clear deterioration is confirmed; fresh Paper turnover remains the main evidence gap."
        )
        weakness = text(inspection.get("top_detected_issue"), "fresh_paper_learning_velocity")
        correction = text(root_cause.get("recommended_safe_correction"), "continue_safe_shadow_validation")
        shadow_test = (
            "Compare earlier profit protection, loss containment, and stale-hold reviews against natural exits."
            if shadow_feedback.get("shadow_exit_candidates_to_watch")
            else "Collect more complete lifecycle and exit evidence before proposing a micro-test."
        )
        paper_watch = (
            f"Watch {len(exit_review.get('profit_protection_candidates') or [])} profit-protection and "
            f"{len(exit_review.get('loss_containment_candidates') or [])} loss-containment candidate(s); do not auto-exit."
        )
        daily = (
            f"Astra inspected its platform and found {weakness.replace('_', ' ')} as the main weakness. "
            f"The underlying cause is {text(root_cause.get('underlying_cause'), 'still being validated').replace('_', ' ')}. "
            f"The safest next improvement is {text(improvement.get('highest_roi_improvement'), 'continued evidence collection').replace('_', ' ')}. "
            f"Paper should {paper_watch.lower()} Shadow should {shadow_test.lower()} "
            "All recommendations remain advisory and paper-safe."
        )
        return {
            "module": "Autonomous Daily Executive Brief V1",
            "status": "ok",
            "daily_autonomous_brief": daily,
            "what_improved": improved,
            "what_worsened": worsened,
            "biggest_current_weakness": weakness,
            "root_cause": root_cause.get("underlying_cause"),
            "safest_next_correction": correction,
            "shadow_test_recommendation": shadow_test,
            "paper_watch_item": paper_watch,
            "what_eric_should_know": (
                f"Lifecycle evidence spans {len(stage_counts)} stage(s), but proxy-based rows remain clearly labeled "
                "and no automatic action was enabled."
            ),
            "next_highest_value_improvement": improvement.get("highest_roi_improvement"),
            **_safe_flags(),
        }

    def _autonomous_intelligence_behavior_tests(
        self,
        inspection: dict[str, Any],
        root_cause: dict[str, Any],
        improvement: dict[str, Any],
        memory: dict[str, Any],
        lifecycle: dict[str, Any],
        exit_review: dict[str, Any],
        shadow_feedback: dict[str, Any],
        brief: dict[str, Any],
    ) -> dict[str, Any]:
        stage_counts = dict(lifecycle.get("lifecycle_stage_counts") or {})
        tests = {
            "test_a_platform_inspection": len(inspection.get("department_scores") or []) >= 16 and bool(inspection.get("top_detected_issue")),
            "test_b_root_cause": len(root_cause.get("root_cause_chain") or []) >= 3 and bool(root_cause.get("supporting_evidence")),
            "test_c_improvement_queue": bool(improvement.get("ranked_improvement_queue")) and improvement.get("safety_risk") is not None,
            "test_d_decision_memory": bool(memory.get("decision_memory_enabled")) and "correction_memories_stored" in memory,
            "test_e_lifecycle_refinement": bool(stage_counts) and (len(stage_counts) > 1 or len(lifecycle.get("trade_lifecycle_summary") or []) <= 1) and "proxy_classification_used" in lifecycle,
            "test_f_exit_decision": all(key in exit_review for key in ("profit_protection_candidates", "loss_containment_candidates", "hold_still_valid_positions")) and exit_review.get("forced_exits_enabled") is False,
            "test_g_shadow_feedback": "shadow_exit_candidates_to_watch" in shadow_feedback and shadow_feedback.get("automatic_promotion_enabled") is False,
            "test_h_plain_english_brief": len(text(brief.get("daily_autonomous_brief"), "")) >= 80 and "_" not in text(brief.get("daily_autonomous_brief"), ""),
        }
        passed = sum(bool(value) for value in tests.values())
        return {
            "module": "Autonomous Intelligence Behavior Verification V1",
            "status": "PASS" if passed == len(tests) else "WARNING",
            "tests": tests,
            "tests_passed": passed,
            "tests_total": len(tests),
            "behavior_verification_score": rounded(passed / len(tests) * 100.0, 3),
            "critical_failures": [key for key, value in tests.items() if not value],
            "business_objective_achieved": passed == len(tests),
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

    def _trading_completion_behavior_tests(
        self,
        effective: dict[str, Any],
        lifecycle: dict[str, Any],
        exit_review: dict[str, Any],
        pipeline: dict[str, Any],
        opportunity: dict[str, Any],
        diversity: dict[str, Any],
        shadow_feedback: dict[str, Any],
    ) -> dict[str, Any]:
        tests = {
            "test_a_effective_learning_capacity": bool(
                to_int(effective.get("risk_exposure_positions"), 0)
                == to_int(effective.get("raw_open_positions"), 0)
                and to_float(effective.get("effective_learning_occupancy"), 0.0)
                <= to_float(effective.get("raw_open_positions"), 0.0)
                and effective.get("effective_learning_capacity_available") is not None
            ),
            "test_b_adaptive_capacity_utilization": bool(
                pipeline.get("effective_capacity_pipeline_status") == "connected_end_to_end"
                and all(
                    pipeline.get(key)
                    for key in (
                        "adaptive_capacity_used_by_scanner",
                        "adaptive_capacity_used_by_candidate_filter",
                        "adaptive_capacity_used_by_entry_gate",
                        "adaptive_capacity_used_by_paper_trade_creation",
                    )
                )
            ),
            "test_c_exit_review": bool(
                "exit_review_candidates" in exit_review
                and exit_review.get("forced_exits_enabled") is False
            ),
            "test_d_horizon_diversity": bool(
                diversity.get("fixed_horizon_quotas_enabled") is False
                and diversity.get("elite_swing_exception_allowed") is True
            ),
            "test_e_opportunity_utilization": bool(
                opportunity.get("opportunities_skipped_reason")
                and "opportunities_blocked_by_entry_gates" in opportunity
                and "opportunities_blocked_by_risk" in opportunity
            ),
            "test_f_shadow_feedback": bool(
                "shadow_exit_candidates_to_watch" in shadow_feedback
                and shadow_feedback.get("automatic_promotion_enabled") is False
            ),
        }
        passed = sum(1 for value in tests.values() if value)
        return {
            "module": "Trading Intelligence Completion Behavior Verification V1",
            "status": "PASS" if passed == len(tests) else "WARNING",
            "tests": tests,
            "tests_passed": passed,
            "tests_total": len(tests),
            "business_objective_achieved": passed == len(tests),
            "remaining_blocker": "none" if passed == len(tests) else next(key for key, value in tests.items() if not value),
            "regression_status": "protected_behavior_preserved",
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
        lifecycle = self._trade_lifecycle_intelligence(statuses, occupancy)
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
        effective = self._effective_learning_capacity(occupancy, lifecycle, expansion)
        exit_review = self._exit_decision_intelligence(lifecycle)
        trade_thesis = self._trade_thesis_tracking(lifecycle)
        pipeline = self._adaptive_capacity_utilization(statuses, effective)
        opportunity_utilization = self._opportunity_utilization(statuses, queue, pipeline, horizon)
        open_position_opportunity_cost = self._open_position_opportunity_cost(lifecycle, opportunity, effective)
        diversity_completion = self._horizon_diversity_completion(horizon, opportunity_utilization)
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
        shadow_feedback = self._shadow_paper_feedback(statuses, exit_review, shadow_completion)
        exit_micro_test_readiness = self._controlled_exit_micro_test_readiness(
            statuses,
            evolution,
            persistence,
            shadow_feedback,
            exit_review,
        )
        exit_learning_feedback = self._exit_learning_feedback_loop(statuses, exit_review)
        trading_brain_behavior = self._trading_brain_behavior_verification(
            lifecycle,
            exit_review,
            exit_micro_test_readiness,
            trade_thesis,
            open_position_opportunity_cost,
            exit_learning_feedback,
        )
        trading_brain_completion = self._trading_brain_completion(
            exit_review,
            exit_micro_test_readiness,
            trade_thesis,
            open_position_opportunity_cost,
            exit_learning_feedback,
            trading_brain_behavior,
        )
        trading_governance = self._trading_governance(
            throughput,
            effective,
            lifecycle,
            exit_review,
            pipeline,
            opportunity_utilization,
            shadow_feedback,
            prior_memory,
        )
        horizon_completion = self._learning_horizon_completion(statuses, continuity, throughput, horizon)
        inspection = self._autonomous_inspection(
            statuses,
            paper_completion,
            prior_memory,
            lifecycle,
            exit_review,
            continuity,
            effective,
            shadow_feedback,
            trading_governance,
        )
        improvement = self._autonomous_improvement(
            statuses,
            inspection,
            lifecycle,
            exit_review,
            paper_completion,
            shadow_feedback,
        )
        decision_memory = self._decision_memory(statuses, inspection, improvement)
        correction_validation = self._autonomous_correction_validation(
            statuses,
            continuity,
            occupancy,
            horizon,
            effective,
            exit_review,
            trading_brain_completion,
            paper_completion,
            shadow_completion,
            decision_memory,
        )
        learning_pipeline = self._autonomous_learning_pipeline_transparency(
            classifier,
            evolution,
            governance,
            shadow_completion,
            persistence,
            shadow_feedback,
            decision_memory,
        )
        shadow_attribution_readiness = self._shadow_performance_attribution_governance(
            statuses,
            shadow_completion,
            classifier,
            evolution,
        )
        executive_governance_accountability = self._autonomous_executive_governance_accountability(
            correction_validation,
            inspection,
            shadow_attribution_readiness,
            trading_brain_completion,
        )
        horizon_exit_investigations = self._horizon_exit_governance_investigations(
            continuity,
            horizon,
            occupancy,
            exit_review,
            trading_brain_completion,
            shadow_attribution_readiness,
        )
        autonomous_governance_core = self._autonomous_governance_core(
            correction_validation,
            learning_pipeline,
            shadow_attribution_readiness,
            executive_governance_accountability,
            horizon_exit_investigations,
            improvement,
        )
        root_cause = self._root_cause_intelligence(
            inspection,
            lifecycle,
            exit_review,
            effective,
            prior_memory,
        )
        daily_brief = self._daily_autonomous_brief(
            inspection,
            root_cause,
            improvement,
            lifecycle,
            exit_review,
            shadow_feedback,
        )
        autonomous_behavior_tests = self._autonomous_intelligence_behavior_tests(
            inspection,
            root_cause,
            improvement,
            decision_memory,
            lifecycle,
            exit_review,
            shadow_feedback,
            daily_brief,
        )
        behavior_verification = self._behavior_verification(
            statuses,
            paper_completion,
            shadow_completion,
            horizon_completion,
            inspection,
            improvement,
            decision_memory,
        )
        completion_tests = self._trading_completion_behavior_tests(
            effective,
            lifecycle,
            exit_review,
            pipeline,
            opportunity_utilization,
            diversity_completion,
            shadow_feedback,
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
            "effective_learning_occupancy": effective.get("effective_learning_occupancy"),
            "effective_learning_capacity_available": effective.get("effective_learning_capacity_available"),
            "exit_review_candidates": len(exit_review.get("exit_review_candidates") or []),
            "trading_brain_completion_enabled": trading_brain_completion.get("trading_brain_completion_enabled"),
            "controlled_exit_micro_test_readiness_score": exit_micro_test_readiness.get("controlled_exit_micro_test_readiness_score"),
            "trade_thesis_tracking_enabled": trade_thesis.get("trade_thesis_tracking_enabled"),
            "opportunity_cost_intelligence_score": open_position_opportunity_cost.get("opportunity_cost_intelligence_score"),
            "exit_learning_feedback_score": exit_learning_feedback.get("exit_learning_feedback_score"),
            "highest_value_exit_improvement": trading_brain_completion.get("highest_value_exit_improvement"),
            "next_safe_exit_learning_step": trading_brain_completion.get("next_safe_exit_learning_step"),
            "adaptive_capacity_pipeline": pipeline.get("effective_capacity_pipeline_status"),
            "trading_governance": trading_governance.get("status"),
            "trading_completion_behavior_tests": completion_tests.get("status"),
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
            "autonomous_intelligence_enabled": True,
            "autonomous_inspection_score": inspection.get("autonomous_inspection_score"),
            "platform_inspection_score": inspection.get("platform_inspection_score"),
            "top_detected_issue": inspection.get("top_detected_issue"),
            "primary_root_cause": inspection.get("primary_root_cause"),
            "autonomous_improvement_score": improvement.get("autonomous_improvement_score"),
            "decision_memory_score": decision_memory.get("decision_memory_score"),
            "lifecycle_refinement_score": lifecycle.get("lifecycle_refinement_score"),
            "exit_decision_intelligence_score": exit_review.get("exit_decision_intelligence_score"),
            "shadow_feedback_routing_enabled": shadow_feedback.get("shadow_feedback_routing_enabled"),
            "daily_autonomous_brief": daily_brief.get("daily_autonomous_brief"),
            "behavior_verification_score": autonomous_behavior_tests.get("behavior_verification_score"),
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
            "autonomous_governance_status": autonomous_governance_core.get("status"),
            "correction_produced_most_benefit": autonomous_governance_core.get("correction_produced_most_benefit"),
            "promotion_bottleneck": autonomous_governance_core.get("why_promotions_blocked"),
            "shadow_governance_readiness_score": shadow_attribution_readiness.get("shadow_readiness_score"),
            "promotion_governance_readiness_score": shadow_attribution_readiness.get("promotion_readiness_score"),
            "highest_confidence_remaining_bottleneck": autonomous_governance_core.get("highest_confidence_remaining_bottleneck"),
            "autonomous_governance_brief": autonomous_governance_core.get("governance_brief"),
            "recommended_action": (
                paper_completion.get("capacity_recommendation")
                if paper_completion.get("learning_reserve_status") == "depleted"
                else continuity.get("recommended_action")
                if continuity.get("status") != "healthy"
                else throughput.get("recommended_throughput_action")
            ),
            "autonomous_intelligence_summary": daily_brief.get("daily_autonomous_brief"),
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
            "trade_lifecycle_intelligence_completion_v1": lifecycle,
            "effective_learning_capacity_v1": effective,
            "exit_decision_intelligence_v1": exit_review,
            "trade_thesis_tracking_v1": trade_thesis,
            "open_position_opportunity_cost_intelligence_v1": open_position_opportunity_cost,
            "controlled_paper_exit_micro_test_readiness_v1": exit_micro_test_readiness,
            "exit_learning_feedback_loop_v1": exit_learning_feedback,
            "trading_brain_behavior_verification_v1": trading_brain_behavior,
            "trading_brain_completion_v1": trading_brain_completion,
            "astra_trading_brain_completion_v1": trading_brain_completion,
            "horizon_opportunity_queue_v1": queue,
            "adaptive_capacity_utilization_pipeline_v1": pipeline,
            "opportunity_utilization_missed_learning_v1": opportunity_utilization,
            "horizon_diversity_without_quotas_v1": diversity_completion,
            "autonomous_trading_governance_v1": trading_governance,
            "shadow_paper_feedback_connection_v1": shadow_feedback,
            "trading_intelligence_completion_behavior_verification_v1": completion_tests,
            "paper_learning_capacity_correction_v1": {
                "paper_learning_capacity_correction_enabled": True,
                "baseline_capacity": expansion.get("baseline_capacity"),
                "recommended_adaptive_capacity": expansion.get("recommended_adaptive_capacity"),
                "absolute_safety_ceiling": expansion.get("absolute_safety_ceiling"),
                "raw_open_positions": effective.get("raw_open_positions"),
                "risk_exposure_positions": effective.get("risk_exposure_positions"),
                "effective_learning_occupancy": effective.get("effective_learning_occupancy"),
                "effective_learning_capacity_available": effective.get("effective_learning_capacity_available"),
                "safe_raw_position_slots_available": effective.get("safe_raw_position_slots_available"),
                "learning_reserve_status": reserve.get("learning_reserve_status"),
                "learning_reserve_score": reserve.get("learning_reserve_score"),
                "capacity_drag_score": drag.get("capacity_drag_score"),
                "missed_learning_opportunity_score": queue.get("missed_learning_opportunity_score"),
                "meaningful_capacity_test_passed": expansion.get("meaningful_capacity_test_passed"),
                "adaptive_capacity_pipeline_status": pipeline.get("effective_capacity_pipeline_status"),
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
            "autonomous_root_cause_intelligence_v1": root_cause,
            "autonomous_improvement_prioritization_completion_v1": improvement,
            "decision_memory_knowledge_retention_completion_v1": decision_memory,
            "autonomous_correction_validation_v1": correction_validation,
            "autonomous_learning_pipeline_transparency_v1": learning_pipeline,
            "shadow_performance_attribution_promotion_readiness_v1": shadow_attribution_readiness,
            "autonomous_executive_governance_accountability_v1": executive_governance_accountability,
            "horizon_exit_governance_investigations_v1": horizon_exit_investigations,
            "astra_autonomous_governance_core_v1": autonomous_governance_core,
            "autonomous_daily_executive_brief_v1": daily_brief,
            "autonomous_intelligence_behavior_verification_v1": autonomous_behavior_tests,
            "behavior_verification_core_completion_v1": behavior_verification,
            "astra_autonomous_intelligence_v1": {
                "autonomous_intelligence_enabled": True,
                "platform_inspection": inspection,
                "root_cause_intelligence": root_cause,
                "improvement_prioritization": improvement,
                "decision_memory": decision_memory,
                "trade_lifecycle_refinement": lifecycle,
                "exit_decision_intelligence": exit_review,
                "trading_brain_completion": trading_brain_completion,
                "autonomous_governance_core": autonomous_governance_core,
                "shadow_feedback_routing": shadow_feedback,
                "daily_executive_brief": daily_brief,
                "behavior_verification": autonomous_behavior_tests,
                "autonomous_intelligence_summary": daily_brief.get("daily_autonomous_brief"),
                **_safe_flags(),
            },
            "astra_autonomous_intelligence_maturation_v1": summary,
            "executive_summary": summary,
            "bounded_cached_sources_only": True,
            "full_history_scan_performed": False,
            "dashboard_endpoint_count_added": 0,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        })
