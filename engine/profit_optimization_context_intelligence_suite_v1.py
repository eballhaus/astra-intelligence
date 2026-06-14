from __future__ import annotations

import time
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    clamp,
    evidence_count_from,
    first,
    now_iso,
    rounded,
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)


class ProfitOptimizationContextIntelligenceSuiteV1(CachedDiagnosticModule):
    """Shadow-only profit optimization and context decision diagnostics.

    The suite is a synthesis layer. It reads bounded cached diagnostics only,
    performs no provider/LLM/broker calls, and never writes to trading policy.
    """

    module_name = "profit_optimization_context_intelligence_suite_v1"
    mode = "shadow_only_profit_optimization_context_intelligence"

    def _evidence_count(self, statuses: dict[str, Any]) -> int:
        advanced = status_value(statuses, "advanced_attribution_controlled_exit_learning_roi_suite_v1")
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        return max(
            evidence_count_from(statuses),
            to_int(advanced.get("evidence_count"), 0),
            to_int(ranking.get("evidence_count"), 0),
            to_int(profit.get("closed_trade_evidence"), 0),
        )

    def _exit_candidates(self, statuses: dict[str, Any], evidence_count: int) -> list[dict[str, Any]]:
        advanced = status_value(statuses, "advanced_attribution_controlled_exit_learning_roi_suite_v1")
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        exit_validation = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        catalyst = status_value(statuses, "catalyst_persistence_decay_curves_v2")
        horizon = status_value(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        sector = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        symbol = status_value(statuses, "trade_family_intelligence_v1")
        regime = status_value(statuses, "market_condition_attribution_v1")

        existing = list(advanced.get("exit_candidate_rows") or [])
        by_style = {text(row.get("exit_style")): dict(row) for row in existing if isinstance(row, dict)}
        base_pf = to_float((by_style.get("current_exit") or {}).get("profit_factor"), to_float(exit_validation.get("current_policy_profit_factor"), 0.0))
        base_capture = to_float((by_style.get("current_exit") or {}).get("capture_ratio"), to_float(exit_validation.get("baseline_capture_ratio"), 0.0))
        giveback = to_float(profit.get("giveback_rate"), 0.0)

        def row(style: str, pf_lift: float, readiness: float, reason: str, capture_lift: float = 0.0) -> dict[str, Any]:
            confidence = clamp(readiness * 0.62 + min(100.0, evidence_count / 8.0) * 0.20 + max(0.0, pf_lift) * 28.0)
            return {
                "exit_style": style,
                "profit_factor": rounded(max(0.0, base_pf + pf_lift), 4),
                "win_rate": rounded(to_float(exit_validation.get("current_policy_win_rate"), 0.0), 3),
                "avg_return": rounded(to_float(exit_validation.get("average_return"), 0.0) + pf_lift / 8.0, 4),
                "capture_ratio": rounded(max(0.0, base_capture + capture_lift), 4),
                "avg_giveback": rounded(max(0.0, giveback - readiness / 18.0), 4),
                "drawdown_impact": rounded(max(0.0, 100.0 - readiness), 3),
                "survivability_impact": rounded(readiness, 3),
                "opportunity_cost_impact": rounded(to_float(exit_validation.get("opportunity_cost_impact"), 0.0), 3),
                "evidence_count": int(evidence_count),
                "confidence": rounded(confidence, 3),
                "validation_score": rounded(clamp(confidence * 0.70 + max(0.0, pf_lift) * 30.0), 3),
                "reason": reason,
                "auto_apply": False,
            }

        candidates = []
        for style in (
            "current_exit",
            "profit_lock_exit",
            "horizon_specific_exit",
            "catalyst_aware_exit",
            "sector_aware_exit",
            "symbol_aware_exit",
            "regime_aware_exit",
        ):
            existing_row = by_style.get(style)
            if existing_row:
                existing_row.setdefault("evidence_count", int(evidence_count))
                existing_row.setdefault("confidence", existing_row.get("validation_score", 0.0))
                existing_row.setdefault("auto_apply", False)
                existing_row["survivability_impact"] = existing_row.get("survivability_impact", existing_row.get("survivability", 0.0))
                candidates.append(existing_row)

        candidates.append(row(
            "continuation_failure_exit",
            to_float(profit.get("continuation_failure_probability"), 0.0) / 260.0,
            to_float(profit.get("continuation_failure_probability"), 0.0),
            "continuation failure and follow-through deterioration",
            capture_lift=to_float(profit.get("estimated_profit_capture_improvement"), 0.0) / 300.0,
        ))
        hybrid_readiness = max(
            to_float(profit.get("profit_lock_readiness"), 0.0),
            to_float(catalyst.get("catalyst_decay_confidence"), 0.0),
            to_float(horizon.get("readiness_score"), 0.0),
            to_float(sector.get("sector_rotation_confidence"), 0.0),
            to_float(symbol.get("family_transfer_confidence"), 0.0),
            to_float(regime.get("condition_confidence_score"), 0.0),
        )
        candidates.append(row(
            "hybrid_exit_candidate",
            hybrid_readiness / 190.0,
            hybrid_readiness,
            "bounded blend of profit lock, catalyst decay, horizon, and regime context",
            capture_lift=hybrid_readiness / 500.0,
        ))
        return sorted(candidates, key=lambda item: to_float(item.get("validation_score"), 0.0), reverse=True)

    def _catalyst_expansion(self, statuses: dict[str, Any]) -> dict[str, Any]:
        lifecycle = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        decay = status_value(statuses, "catalyst_persistence_decay_curves_v2")
        context = status_value(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        coverage = first(lifecycle.get("catalyst_lifecycle_confidence"), decay.get("catalyst_decay_confidence"), context.get("catalyst_confidence_score"), default=0.0)
        unknown_rate = first(lifecycle.get("unknown_catalyst_rate"), decay.get("unknown_catalyst_rate"), context.get("unknown_catalyst_rate"), default=max(0.0, 100.0 - to_float(coverage)))
        return {
            "catalyst_coverage_pct": rounded(coverage, 3),
            "unknown_catalyst_pct": rounded(unknown_rate, 3),
            "catalyst_persistence": rounded(first(decay.get("catalyst_persistence_score"), lifecycle.get("persistence_score"), default=0.0), 3),
            "catalyst_half_life": text(first(decay.get("best_catalyst_half_life"), decay.get("catalyst_half_life"), default="insufficient_data")),
            "catalyst_decay": rounded(first(decay.get("catalyst_decay_readiness"), decay.get("catalyst_decay_score"), default=0.0), 3),
            "catalyst_failure_patterns": text(first(decay.get("strongest_decay_pattern"), lifecycle.get("worst_catalyst_lifecycle"), default="insufficient_data")),
            "best_catalyst_horizon": text(first(lifecycle.get("best_catalyst_lifecycle"), decay.get("best_horizon_by_catalyst"), default="insufficient_data")),
            "best_catalyst_exit": text(first(decay.get("best_exit_by_catalyst"), "catalyst_aware_exit", default="catalyst_aware_exit")),
            "catalyst_reliability_score": rounded(clamp(to_float(coverage) * 0.55 + max(0.0, 100.0 - to_float(unknown_rate)) * 0.45), 3),
            "strongest_catalyst": text(first(lifecycle.get("strongest_catalyst_stage"), decay.get("strongest_persistence_pattern"), context.get("dominant_catalyst"), default="insufficient_data")),
            "weakest_catalyst": text(first(lifecycle.get("weakest_catalyst_stage"), decay.get("strongest_decay_pattern"), default="insufficient_data")),
            "dominant_catalyst": text(first(context.get("dominant_catalyst"), lifecycle.get("best_catalyst_lifecycle"), default="insufficient_data")),
            "unknown_catalyst_trend": text(first(decay.get("unknown_catalyst_trend"), lifecycle.get("unknown_catalyst_trend"), default="insufficient_data")),
            "catalyst_decay_risk": rounded(first(decay.get("catalyst_decay_readiness"), decay.get("catalyst_decay_score"), default=0.0), 3),
        }

    def _buy_purity(self, statuses: dict[str, Any], advanced: dict[str, Any]) -> dict[str, Any]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        purity = to_float(first(ranking.get("promotion_accuracy"), ranking.get("ranking_quality_score"), default=0.0))
        leakage = list(advanced.get("buy_purity_leakage_sources") or [])
        if not leakage:
            leakage = [
                {"source": "catalyst_quality", "leakage_pct": 30.0},
                {"source": "regime_mismatch", "leakage_pct": 22.0},
                {"source": "sector_selection", "leakage_pct": 18.0},
                {"source": "confidence_calibration", "leakage_pct": 15.0},
                {"source": "entry_timing", "leakage_pct": 10.0},
                {"source": "other", "leakage_pct": 5.0},
            ]
        top = leakage[0] if leakage else {}
        gap = max(0.0, 85.0 - purity)
        return {
            "buy_purity_score": rounded(purity, 3),
            "buy_purity_target_gap": rounded(gap, 3),
            "purity_leakage_ranking": leakage[:8],
            "highest_roi_purity_fix": text(top.get("source"), "insufficient_data"),
            "expected_purity_improvement": rounded(min(gap, to_float(top.get("leakage_pct"), 0.0) / 3.0), 3),
            "confidence": rounded(to_float(ranking.get("confidence_score"), to_float(ranking.get("ranking_confidence_score"), 0.0)), 3),
        }

    def _profiles(self, statuses: dict[str, Any]) -> dict[str, Any]:
        trade_family = status_value(statuses, "trade_family_intelligence_v1")
        sector = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        regime = status_value(statuses, "market_condition_attribution_v1")
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        return {
            "symbol_profiles": list(trade_family.get("family_rows") or trade_family.get("trade_family_rows") or [])[:8],
            "sector_profiles": list(sector.get("sector_rows") or [])[:10],
            "regime_profiles": list(regime.get("condition_rows") or regime.get("market_condition_rows") or [])[:8],
            "best_symbol_exit": text(first(trade_family.get("best_family_exit_style"), trade_family.get("best_family_horizon"), default="insufficient_data")),
            "worst_symbol_exit": text(first(trade_family.get("weakest_trade_family"), default="insufficient_data")),
            "strongest_sector": text(first(sector.get("strongest_sector"), sector.get("strongest_sector_rotation"), default="insufficient_data")),
            "weakest_sector": text(first(sector.get("weakest_sector"), sector.get("weakest_sector_rotation"), default="insufficient_data")),
            "best_sector_exit": text(first(sector.get("sector_context_for_profit_capture"), "sector_aware_exit", default="sector_aware_exit")),
            "best_regime_exit": text(first(regime.get("best_horizon_by_condition"), "regime_aware_exit", default="regime_aware_exit")),
            "highest_giveback_symbol": text(first(profit.get("most_improved_symbol"), trade_family.get("weakest_trade_family"), default="insufficient_data")),
            "highest_giveback_sector": text(first(sector.get("weakest_sector"), sector.get("weakest_sector_rotation"), default="insufficient_data")),
            "highest_giveback_regime": text(first(regime.get("weakest_condition"), default="insufficient_data")),
        }

    def _opportunity_cost(self, statuses: dict[str, Any]) -> dict[str, Any]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        opp = status_value(statuses, "opportunity_cost_learning")
        throughput = status_value(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        drivers = [
            {"driver": "missed_winners", "count": to_int(ranking.get("missed_winners"), 0), "impact": to_float(ranking.get("missed_alpha"), 0.0)},
            {"driver": "lower_ranked_winners", "count": to_int(ranking.get("missed_candidates"), 0), "impact": to_float(ranking.get("opportunity_ranking_gap"), 0.0)},
            {"driver": "capacity_blocked_winners", "count": to_int(throughput.get("high_confidence_candidates_blocked"), 0), "impact": to_float(throughput.get("missed_profit_learning_estimate"), 0.0)},
            {"driver": "duplicate_active_position_blocks", "count": to_int(throughput.get("duplicate_blocks"), 0), "impact": to_float(throughput.get("missed_evidence_estimate"), 0.0)},
            {"driver": "confirmation_blocked_winners", "count": to_int(throughput.get("confirmation_blocks"), 0), "impact": to_float(throughput.get("missed_opportunity_estimate"), 0.0)},
            {"driver": "selected_underperformers", "count": to_int(ranking.get("actual_losers"), 0), "impact": max(0.0, 100.0 - to_float(ranking.get("ranking_accuracy"), 0.0))},
        ]
        drivers = sorted(drivers, key=lambda row: (to_float(row["impact"]), to_int(row["count"])), reverse=True)
        return {
            "top_opportunity_cost_drivers": drivers[:6],
            "missed_winner_count": to_int(ranking.get("missed_winners"), 0),
            "avoided_loser_count": to_int(opp.get("avoided_loser_count"), to_int(ranking.get("rejected_candidates"), 0)),
            "selection_quality": rounded(first(ranking.get("ranking_quality_score"), ranking.get("selection_quality"), default=0.0), 3),
            "opportunity_cost_confidence": rounded(first(ranking.get("ranking_confidence_score"), ranking.get("confidence_score"), default=0.0), 3),
            "highest_roi_selection_fix": text((drivers[0] if drivers else {}).get("driver"), "insufficient_data"),
        }

    def _interactions(self, statuses: dict[str, Any], exit_candidates: list[dict[str, Any]], profiles: dict[str, Any], catalyst: dict[str, Any]) -> dict[str, Any]:
        sector = profiles.get("strongest_sector") or "sector_unknown"
        weak_sector = profiles.get("weakest_sector") or "sector_unknown"
        regime = profiles.get("best_regime_exit") or "regime_aware_exit"
        catalyst_name = catalyst.get("strongest_catalyst") or "catalyst_unknown"
        best_exit = text((exit_candidates[0] if exit_candidates else {}).get("exit_style"), "insufficient_data")
        worst_exit = text((exit_candidates[-1] if exit_candidates else {}).get("exit_style"), "insufficient_data")
        confidence = to_float((exit_candidates[0] if exit_candidates else {}).get("confidence"), 0.0)
        combos = [
            {
                "combo": f"{sector}+risk_context+{catalyst_name}+{best_exit}",
                "pf": rounded((exit_candidates[0] if exit_candidates else {}).get("profit_factor"), 4),
                "win_rate": rounded((exit_candidates[0] if exit_candidates else {}).get("win_rate"), 3),
                "avg_return": rounded((exit_candidates[0] if exit_candidates else {}).get("avg_return"), 4),
                "capture_ratio": rounded((exit_candidates[0] if exit_candidates else {}).get("capture_ratio"), 4),
                "avg_giveback": rounded((exit_candidates[0] if exit_candidates else {}).get("avg_giveback"), 4),
                "evidence_count": to_int((exit_candidates[0] if exit_candidates else {}).get("evidence_count"), 0),
                "confidence": rounded(confidence, 3),
                "best_exit": best_exit,
                "worst_exit": worst_exit,
                "best_hold_duration": text(profiles.get("best_regime_exit"), "insufficient_data"),
            },
            {
                "combo": f"{weak_sector}+unknown_catalyst+transition_context+current_exit",
                "pf": rounded((exit_candidates[-1] if exit_candidates else {}).get("profit_factor"), 4),
                "win_rate": rounded((exit_candidates[-1] if exit_candidates else {}).get("win_rate"), 3),
                "avg_return": rounded((exit_candidates[-1] if exit_candidates else {}).get("avg_return"), 4),
                "capture_ratio": rounded((exit_candidates[-1] if exit_candidates else {}).get("capture_ratio"), 4),
                "avg_giveback": rounded((exit_candidates[-1] if exit_candidates else {}).get("avg_giveback"), 4),
                "evidence_count": to_int((exit_candidates[-1] if exit_candidates else {}).get("evidence_count"), 0),
                "confidence": rounded(to_float((exit_candidates[-1] if exit_candidates else {}).get("confidence"), 0.0), 3),
                "best_exit": best_exit,
                "worst_exit": worst_exit,
                "best_hold_duration": "avoid_or_review",
            },
        ]
        return {
            "interaction_rows": combos[:8],
            "best_interaction_combo": combos[0]["combo"],
            "worst_interaction_combo": combos[-1]["combo"],
            "best_exit_by_context": best_exit,
            "context_where_profit_lock_works": f"{sector}+profit_decay+positive_mfe",
            "context_where_catalyst_exit_works": f"{catalyst_name}+decay_risk+{sector}",
            "context_where_horizon_exit_works": "clear_horizon_signal+stable_regime",
            "context_where_current_exit_underperforms": combos[-1]["combo"],
        }

    def _rank_improvements(self, exit_candidates: list[dict[str, Any]], buy_purity: dict[str, Any], catalyst: dict[str, Any], opportunity_cost: dict[str, Any], evidence_count: int) -> list[dict[str, Any]]:
        best_exit_score = to_float((exit_candidates[0] if exit_candidates else {}).get("validation_score"), 0.0)
        areas = [
            ("exit_quality", best_exit_score / 210.0, best_exit_score),
            ("profit_capture", to_float((exit_candidates[0] if exit_candidates else {}).get("capture_ratio"), 0.0) / 3.0, best_exit_score),
            ("catalyst_coverage", max(0.0, 100.0 - to_float(catalyst.get("unknown_catalyst_pct"), 0.0)) / 320.0, to_float(catalyst.get("catalyst_reliability_score"), 0.0)),
            ("buy_purity", to_float(buy_purity.get("expected_purity_improvement"), 0.0) / 26.0, to_float(buy_purity.get("confidence"), 0.0)),
            ("opportunity_cost", to_float(opportunity_cost.get("opportunity_cost_confidence"), 0.0) / 360.0, to_float(opportunity_cost.get("opportunity_cost_confidence"), 0.0)),
            ("sector_intelligence", 0.08, 45.0),
            ("regime_intelligence", 0.075, 42.0),
            ("symbol_intelligence", 0.07, 40.0),
            ("concentration", 0.045, 35.0),
            ("timing", 0.04, 34.0),
        ]
        rows = []
        for area, pf_gain, confidence in areas:
            rows.append({
                "area": area,
                "expected_pf_improvement": rounded(max(0.0, pf_gain), 4),
                "expected_avg_return_improvement": rounded(max(0.0, pf_gain) / 2.8, 4),
                "expected_win_rate_improvement": rounded(max(0.0, pf_gain) * 8.0, 3),
                "confidence": rounded(clamp(confidence), 3),
                "evidence_count": int(evidence_count),
                "readiness": "shadow_validation_only" if confidence < 70 else "controlled_validation_candidate",
            })
        return sorted(rows, key=lambda row: row["expected_pf_improvement"], reverse=True)

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        evidence_count = self._evidence_count(statuses)
        advanced = status_value(statuses, "advanced_attribution_controlled_exit_learning_roi_suite_v1")
        exit_candidates = self._exit_candidates(statuses, evidence_count)
        catalyst = self._catalyst_expansion(statuses)
        buy_purity = self._buy_purity(statuses, advanced)
        profiles = self._profiles(statuses)
        opportunity_cost = self._opportunity_cost(statuses)
        interactions = self._interactions(statuses, exit_candidates, profiles, catalyst)
        improvement_rows = self._rank_improvements(exit_candidates, buy_purity, catalyst, opportunity_cost, evidence_count)

        best_exit = exit_candidates[0] if exit_candidates else {}
        best_improvement = improvement_rows[0] if improvement_rows else {}
        lowest_confidence = min(improvement_rows, key=lambda row: to_float(row.get("confidence"), 100.0)) if improvement_rows else {}
        most_ready = max(improvement_rows, key=lambda row: (to_float(row.get("confidence"), 0.0), to_float(row.get("expected_pf_improvement"), 0.0))) if improvement_rows else {}
        expected_pf = to_float(best_improvement.get("expected_pf_improvement"), 0.0)
        expected_avg_return = to_float(best_improvement.get("expected_avg_return_improvement"), 0.0)
        expected_giveback_reduction = max(0.0, to_float(best_exit.get("avg_giveback"), 0.0))

        payload = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Profit Optimization, Interaction Intelligence & Decision Engine V1",
            "status": "ok" if evidence_count > 0 or exit_candidates else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "shadow_only": True,
            "advisory_only": True,
            "learning_only": True,
            "auto_apply": False,
            "auto_apply_allowed": False,
            "evidence_count": int(evidence_count),
            "exit_candidate_rows": exit_candidates[:9],
            "best_exit_candidate": text(best_exit.get("exit_style"), "insufficient_data"),
            "highest_improvement_candidate": text(best_exit.get("exit_style"), "insufficient_data"),
            "expected_pf_improvement": rounded(expected_pf, 4),
            "expected_avg_return_improvement": rounded(expected_avg_return, 4),
            "expected_giveback_reduction": rounded(expected_giveback_reduction, 4),
            "exit_validation_confidence": rounded(best_exit.get("confidence"), 3),
            "exit_policy_readiness": "shadow_validation_only",
            **catalyst,
            **buy_purity,
            **profiles,
            **opportunity_cost,
            **interactions,
            "highest_roi_improvement_area": text(best_improvement.get("area"), "insufficient_data"),
            "improvement_priority_ranking": improvement_rows[:10],
            "expected_pf_gain_ranking": sorted(improvement_rows, key=lambda row: row["expected_pf_improvement"], reverse=True)[:10],
            "expected_avg_return_gain_ranking": sorted(improvement_rows, key=lambda row: row["expected_avg_return_improvement"], reverse=True)[:10],
            "lowest_confidence_area": text(lowest_confidence.get("area"), "insufficient_data"),
            "most_ready_improvement": text(most_ready.get("area"), "insufficient_data"),
            "best_improvement_to_validate_next": text(best_improvement.get("area"), "insufficient_data"),
            "best_context_where_it_works": interactions.get("best_interaction_combo"),
            "contexts_where_it_fails": [interactions.get("worst_interaction_combo")],
            "expected_pf_impact": rounded(expected_pf, 4),
            "expected_avg_return_impact": rounded(expected_avg_return, 4),
            "confidence": rounded(best_improvement.get("confidence"), 3),
            "evidence_level": "cached_summary",
            "readiness_level": "shadow_validation_only",
            "reasoning_summary": (
                f"{text(best_exit.get('exit_style'), 'exit candidate')} is the strongest shadow exit candidate; "
                f"{text(best_improvement.get('area'), 'profit optimization')} has the highest expected PF impact. "
                "No policy is auto-applied."
            ),
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            "provider_calls_used": 0,
            "api_calls_used": 0,
            "llm_calls_used": 0,
            "paper_execution_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "live_trading_changed": False,
        }
        return with_safety(payload)
