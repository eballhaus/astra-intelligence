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


EXIT_STYLES = (
    "current_exit",
    "profit_lock_exit",
    "horizon_specific_exit",
    "catalyst_aware_exit",
    "sector_aware_exit",
    "symbol_aware_exit",
    "regime_aware_exit",
)


class AdvancedAttributionControlledExitLearningRoiSuiteV1(CachedDiagnosticModule):
    """Shadow-only attribution, exit validation, and learning ROI diagnostics.

    This suite intentionally consumes cached diagnostic summaries only. It does
    not read broker state, place orders, alter policy, or write to protected
    trading/learning state.
    """

    module_name = "advanced_attribution_controlled_exit_learning_roi_suite_v1"
    mode = "shadow_only_advanced_attribution_controlled_exit_learning_roi"

    def _metric(self, statuses: dict[str, Any], key: str, *fields: str, default: float = 0.0) -> float:
        payload = status_value(statuses, key)
        for field in fields:
            if field in payload:
                return to_float(payload.get(field), default)
        return float(default)

    def _label(self, statuses: dict[str, Any], key: str, *fields: str, default: str = "insufficient_data") -> str:
        payload = status_value(statuses, key)
        for field in fields:
            value = payload.get(field)
            if value is not None and str(value).strip():
                return text(value, default)
        return default

    def _evidence_count(self, statuses: dict[str, Any]) -> int:
        counts = [
            evidence_count_from(statuses),
            self._metric(statuses, "trade_lifecycle_excursion_v2", "closed_trade_count", "tracked_closed_trades"),
            self._metric(statuses, "profit_capture_peak_decay_exit_validation_suite_v1", "tracked_trades", "evidence_count"),
            self._metric(statuses, "candidate_ranking_attribution_promotion_intelligence_v1", "evidence_count"),
            self._metric(statuses, "shadow_correction_validation_attribution_v1", "total_validated_recommendations", "validation_count"),
            self._metric(statuses, "controlled_paper_profit_protection_pilot_v1", "closed_trade_evidence"),
        ]
        return max(to_int(value, 0) for value in counts)

    def _factor_rows(self, statuses: dict[str, Any]) -> list[dict[str, Any]]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        confidence = status_value(statuses, "confidence_decomposition_engine_v1")
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        sector = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        regime = status_value(statuses, "market_condition_attribution_v1")
        trade_family = status_value(statuses, "trade_family_intelligence_v1")

        rows = [
            {
                "factor": "exit_quality",
                "score": clamp(100.0 - to_float(profit.get("giveback_risk_score"), 50.0)),
                "loss_pressure": clamp(to_float(profit.get("giveback_risk_score"), 0.0)),
                "source": "controlled_paper_profit_protection_pilot_v1",
            },
            {
                "factor": "profit_capture",
                "score": clamp(to_float(profit.get("profit_capture_score"), 0.0)),
                "loss_pressure": clamp(100.0 - to_float(profit.get("profit_capture_score"), 50.0)),
                "source": "controlled_paper_profit_protection_pilot_v1",
            },
            {
                "factor": "ranking_quality",
                "score": clamp(to_float(ranking.get("ranking_quality_score"), 0.0)),
                "loss_pressure": clamp(100.0 - to_float(ranking.get("ranking_quality_score"), 50.0)),
                "source": "candidate_ranking_attribution_promotion_intelligence_v1",
            },
            {
                "factor": "buy_purity",
                "score": clamp(to_float(ranking.get("promotion_accuracy"), 0.0)),
                "loss_pressure": clamp(100.0 - to_float(ranking.get("promotion_accuracy"), 50.0)),
                "source": "candidate_ranking_attribution_promotion_intelligence_v1",
            },
            {
                "factor": "catalyst_quality",
                "score": clamp(to_float(catalyst.get("catalyst_lifecycle_confidence"), to_float(confidence.get("catalyst_confidence"), 0.0))),
                "loss_pressure": clamp(to_float(profit.get("catalyst_decay_risk"), 0.0)),
                "source": "catalyst_lifecycle_intelligence_v1",
            },
            {
                "factor": "sector_selection",
                "score": clamp(to_float(sector.get("sector_rotation_confidence"), 0.0)),
                "loss_pressure": clamp(100.0 - to_float(sector.get("sector_rotation_confidence"), 50.0)),
                "source": "etf_sector_rotation_intelligence_v1",
            },
            {
                "factor": "regime_fit",
                "score": clamp(to_float(regime.get("condition_confidence_score"), 0.0)),
                "loss_pressure": clamp(100.0 - to_float(regime.get("condition_confidence_score"), 50.0)),
                "source": "market_condition_attribution_v1",
            },
            {
                "factor": "symbol_intelligence",
                "score": clamp(to_float(trade_family.get("family_transfer_confidence"), 0.0)),
                "loss_pressure": clamp(100.0 - to_float(trade_family.get("family_transfer_confidence"), 50.0)),
                "source": "trade_family_intelligence_v1",
            },
        ]
        return sorted(rows, key=lambda row: row["loss_pressure"], reverse=True)

    def _buy_purity_leakage(self, factor_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        loss_total = sum(max(0.0, to_float(row.get("loss_pressure"), 0.0)) for row in factor_rows) or 1.0
        mapped = []
        for row in factor_rows[:6]:
            mapped.append({
                "source": row["factor"],
                "leakage_pct": rounded((to_float(row.get("loss_pressure"), 0.0) / loss_total) * 100.0, 3),
                "score": rounded(row.get("score"), 3),
            })
        return mapped

    def _exit_candidates(self, statuses: dict[str, Any]) -> list[dict[str, Any]]:
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        profit_lock = status_value(statuses, "profit_lock_profit_capture_maturation_v2")
        exit_validation = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        multi_horizon = status_value(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        catalyst = status_value(statuses, "catalyst_persistence_decay_curves_v2")
        sector = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        symbol = status_value(statuses, "trade_family_intelligence_v1")
        regime = status_value(statuses, "market_condition_attribution_v1")

        current_pf = to_float(exit_validation.get("current_policy_profit_factor"), to_float(exit_validation.get("baseline_profit_factor"), 0.0))
        current_capture = to_float(exit_validation.get("baseline_capture_ratio"), to_float(profit.get("profit_capture_score"), 0.0) / 100.0)
        rows = [
            ("current_exit", current_pf, to_float(exit_validation.get("current_policy_win_rate"), 0.0), current_capture, 100.0 - to_float(profit.get("giveback_risk_score"), 0.0), "current paper/natural exit baseline"),
            ("profit_lock_exit", current_pf + to_float(profit_lock.get("profit_capture_improvement_potential"), to_float(profit.get("estimated_profit_capture_improvement"), 0.0)) / 100.0, 0.0, to_float(profit.get("estimated_profit_capture_improvement"), 0.0) / 100.0, to_float(profit.get("profit_lock_readiness"), 0.0), "profit lock / peak decay protection"),
            ("horizon_specific_exit", current_pf + to_float(multi_horizon.get("horizon_mismatch_risk_score"), 0.0) / 180.0, 0.0, to_float(multi_horizon.get("capture_ratio"), 0.0), to_float(multi_horizon.get("readiness_score"), 0.0), "best shadow horizon alignment"),
            ("catalyst_aware_exit", current_pf + to_float(catalyst.get("catalyst_decay_readiness"), to_float(profit.get("catalyst_decay_risk"), 0.0)) / 200.0, 0.0, to_float(catalyst.get("profit_capture_before_decay"), 0.0), to_float(catalyst.get("catalyst_decay_confidence"), 0.0), "catalyst persistence / decay curve"),
            ("sector_aware_exit", current_pf + to_float(sector.get("sector_rotation_confidence"), 0.0) / 260.0, 0.0, to_float(sector.get("sector_context_for_profit_capture"), 0.0), to_float(sector.get("sector_rotation_confidence"), 0.0), "sector rotation / ETF leadership context"),
            ("symbol_aware_exit", current_pf + to_float(symbol.get("family_transfer_confidence"), 0.0) / 260.0, 0.0, to_float(symbol.get("family_learning_score"), 0.0) / 100.0, to_float(symbol.get("family_transfer_confidence"), 0.0), "symbol and trade-family behavior"),
            ("regime_aware_exit", current_pf + to_float(regime.get("condition_confidence_score"), 0.0) / 280.0, 0.0, to_float(regime.get("exit_quality_by_condition"), 0.0) / 100.0, to_float(regime.get("condition_confidence_score"), 0.0), "market condition / regime attribution"),
        ]
        out = []
        for style, pf, wr, capture, readiness, reason in rows:
            readiness_score = clamp(readiness)
            out.append({
                "exit_style": style,
                "profit_factor": rounded(max(0.0, pf), 4),
                "win_rate": rounded(max(0.0, wr), 3),
                "avg_return": rounded(to_float(exit_validation.get("average_return"), 0.0), 4),
                "capture_ratio": rounded(capture if capture <= 1.5 else capture / 100.0, 4),
                "avg_giveback": rounded(to_float(profit.get("giveback_rate"), 0.0), 4),
                "survivability": rounded(readiness_score, 3),
                "drawdown_impact": rounded(max(0.0, 100.0 - readiness_score), 3),
                "opportunity_cost_impact": rounded(to_float(exit_validation.get("opportunity_cost_impact"), to_float(profit.get("estimated_expectancy_improvement"), 0.0)), 3),
                "validation_score": rounded(clamp(readiness_score * 0.55 + max(0.0, pf) * 12.0 + (capture if capture <= 1.5 else capture / 100.0) * 20.0), 3),
                "reason": reason,
            })
        return sorted(out, key=lambda row: row["validation_score"], reverse=True)

    def _policy_readiness(self, exit_candidates: list[dict[str, Any]], evidence_count: int) -> list[dict[str, Any]]:
        readiness = []
        for row in exit_candidates:
            if row["exit_style"] == "current_exit":
                continue
            confidence = clamp(row.get("validation_score"))
            readiness.append({
                "policy_candidate": row["exit_style"],
                "policy_readiness_score": rounded(clamp(confidence * 0.70 + min(100.0, evidence_count / 5.0) * 0.30), 3),
                "evidence_count": int(evidence_count),
                "confidence": rounded(confidence, 3),
                "estimated_impact": rounded(max(0.0, to_float(row.get("profit_factor"), 0.0) - to_float((exit_candidates[-1] if exit_candidates else {}).get("profit_factor"), 0.0)), 4),
                "auto_apply_allowed": False,
            })
        return sorted(readiness, key=lambda row: row["policy_readiness_score"], reverse=True)

    def _learning_roi(self, factor_rows: list[dict[str, Any]], exit_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best_exit = exit_candidates[0] if exit_candidates else {}
        rows = []
        for row in factor_rows[:8]:
            pressure = to_float(row.get("loss_pressure"), 0.0)
            rows.append({
                "area": row["factor"],
                "potential_pf_improvement": rounded(pressure / 260.0, 4),
                "potential_win_rate_improvement": rounded(pressure / 20.0, 3),
                "potential_avg_return_improvement": rounded(pressure / 45.0, 3),
                "confidence_level": rounded(clamp(row.get("score")), 3),
                "evidence_level": "cached_summary",
            })
        if best_exit:
            rows.append({
                "area": f"validate_{best_exit.get('exit_style')}",
                "potential_pf_improvement": rounded(to_float(best_exit.get("validation_score"), 0.0) / 220.0, 4),
                "potential_win_rate_improvement": rounded(to_float(best_exit.get("validation_score"), 0.0) / 25.0, 3),
                "potential_avg_return_improvement": rounded(to_float(best_exit.get("validation_score"), 0.0) / 55.0, 3),
                "confidence_level": rounded(best_exit.get("validation_score"), 3),
                "evidence_level": "shadow_exit_candidate",
            })
        return sorted(rows, key=lambda row: row["potential_pf_improvement"], reverse=True)

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        evidence_count = self._evidence_count(statuses)
        factor_rows = self._factor_rows(statuses)
        exit_candidates = self._exit_candidates(statuses)
        roi_rows = self._learning_roi(factor_rows, exit_candidates)
        policy_readiness = self._policy_readiness(exit_candidates, evidence_count)
        top_loss = factor_rows[0] if factor_rows else {}
        top_win = sorted(factor_rows, key=lambda row: row["score"], reverse=True)[0] if factor_rows else {}
        best_exit = exit_candidates[0] if exit_candidates else {}
        best_roi = roi_rows[0] if roi_rows else {}

        catalyst_lifecycle = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        catalyst_decay = status_value(statuses, "catalyst_persistence_decay_curves_v2")
        sector = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        market_condition = status_value(statuses, "market_condition_attribution_v1")
        trade_family = status_value(statuses, "trade_family_intelligence_v1")
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")

        payload = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Advanced Attribution, Controlled Exit Validation & Learning ROI Suite V1",
            "status": "ok" if evidence_count > 0 or factor_rows else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "shadow_only": True,
            "learning_only": True,
            "auto_apply_allowed": False,
            "evidence_count": int(evidence_count),
            "top_win_drivers": sorted(factor_rows, key=lambda row: row["score"], reverse=True)[:5],
            "top_loss_drivers": factor_rows[:5],
            "most_predictive_factors": factor_rows[:5],
            "buy_purity_leakage_sources": self._buy_purity_leakage(factor_rows),
            "highest_roi_improvement_areas": roi_rows[:6],
            "highest_roi_improvement_area": text(best_roi.get("area"), "insufficient_data"),
            "estimated_pf_gain": rounded(best_roi.get("potential_pf_improvement"), 4),
            "best_exit_candidate": text(best_exit.get("exit_style"), "insufficient_data"),
            "highest_improvement_candidate": text(best_exit.get("exit_style"), "insufficient_data"),
            "exit_validation_score": rounded(best_exit.get("validation_score"), 3),
            "policy_readiness_score": rounded((policy_readiness[0] if policy_readiness else {}).get("policy_readiness_score"), 3),
            "exit_candidate_rows": exit_candidates,
            "policy_readiness": policy_readiness,
            "profit_lost_estimate": rounded(to_float(profit.get("estimated_giveback_reduction"), 0.0) + to_float(profit.get("estimated_profit_capture_improvement"), 0.0), 3),
            "giveback_attribution": text(top_loss.get("factor"), "insufficient_data"),
            "capture_attribution": text(top_win.get("factor"), "insufficient_data"),
            "lifecycle_quality_score": rounded(100.0 - to_float(profit.get("giveback_risk_score"), 50.0), 3),
            "best_hold_window": self._label(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1", "best_horizon", "best_shadow_hold_window", default="insufficient_data"),
            "best_capture_window": text(best_exit.get("exit_style"), "insufficient_data"),
            "highest_giveback_window": self._label(statuses, "profit_capture_peak_decay_exit_validation_suite_v1", "highest_giveback_window", "worst_horizon", default="insufficient_data"),
            "best_profit_retention_window": self._label(statuses, "profit_lock_profit_capture_maturation_v2", "best_virtual_profit_capture_model", "best_virtual_profit_lock_model", default="insufficient_data"),
            "continuation_failure_patterns": self._label(statuses, "profit_capture_peak_decay_exit_validation_suite_v1", "strongest_failure_signal", default="insufficient_data"),
            "catalyst_coverage": rounded(first(catalyst_lifecycle.get("catalyst_lifecycle_confidence"), catalyst_decay.get("catalyst_decay_confidence"), default=0.0), 3),
            "unknown_catalyst_rate": rounded(first(catalyst_lifecycle.get("unknown_catalyst_rate"), catalyst_decay.get("unknown_catalyst_rate"), default=0.0), 3),
            "strongest_sector": text(first(sector.get("strongest_sector"), sector.get("strongest_sector_rotation"), default="insufficient_data")),
            "weakest_sector": text(first(sector.get("weakest_sector"), sector.get("weakest_sector_rotation"), default="insufficient_data")),
            "strongest_catalyst": text(first(catalyst_lifecycle.get("strongest catalyst stage"), catalyst_lifecycle.get("strongest_catalyst_stage"), catalyst_decay.get("strongest_persistence_pattern"), default="insufficient_data")),
            "weakest_catalyst": text(first(catalyst_lifecycle.get("weakest catalyst stage"), catalyst_lifecycle.get("weakest_catalyst_stage"), catalyst_decay.get("strongest_decay_pattern"), default="insufficient_data")),
            "best_regime": text(first(market_condition.get("best_condition"), market_condition.get("current_market_phase"), default="insufficient_data")),
            "best_sector_regime_pair": f"{text(first(sector.get('strongest_sector'), default='sector_unknown'))}/{text(first(market_condition.get('best_condition'), default='regime_unknown'))}",
            "unknown_catalyst_trend": text(first(catalyst_decay.get("unknown_catalyst_trend"), catalyst_lifecycle.get("unknown_catalyst_trend"), default="insufficient_data")),
            "strongest_symbol_family": text(first(trade_family.get("strongest_trade_family"), trade_family.get("best_family_horizon"), default="insufficient_data")),
            "weakest_symbol_family": text(first(trade_family.get("weakest_trade_family"), default="insufficient_data")),
            "why_profits_are_being_lost": text(top_loss.get("factor"), "insufficient_data"),
            "why_buy_purity_is_below_target": text((self._buy_purity_leakage(factor_rows)[0] if factor_rows else {}).get("source"), "insufficient_data"),
            "why_exits_underperform": text(best_exit.get("reason"), "insufficient_data"),
            "future_policy_candidate_closest_to_readiness": text((policy_readiness[0] if policy_readiness else {}).get("policy_candidate"), "insufficient_data"),
            "summary": {
                "top_profit_loss_driver": text(top_loss.get("factor"), "insufficient_data"),
                "strongest_current_edge": text(top_win.get("factor"), "insufficient_data"),
                "best_exit_candidate": text(best_exit.get("exit_style"), "insufficient_data"),
                "highest_expected_pf_impact": text(best_roi.get("area"), "insufficient_data"),
                "recommended_next_focus": text(best_roi.get("area"), "continue_shadow_attribution"),
            },
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        payload.update({
            "forced_exits_enabled": False,
            "forced_trades_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "paper_execution_changed": False,
        })
        return with_safety(payload)
