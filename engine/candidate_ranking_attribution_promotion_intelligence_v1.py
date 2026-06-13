from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _round(value: Any, digits: int = 3) -> float:
    return round(_to_float(value), digits)


def _text(value: Any, default: str = "insufficient_data") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        return


def _status(statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    value = statuses.get(key) or {}
    return dict(value) if isinstance(value, dict) else {}


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (dict, list)) and not value:
            continue
        return value
    return default


def _humanize(value: str) -> str:
    return _text(value, "insufficient_data").replace("_", " ")


class CandidateRankingAttributionPromotionIntelligenceV1:
    """Shadow-only ranking audit layer built from cached Astra evidence.

    This suite explains promotion/rejection quality and factor attribution
    without altering the live ranking path.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(
            self.state_dir,
            "dashboard_cache",
            "candidate_ranking_attribution_promotion_intelligence_v1.json",
        )
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _shadow_category_map(self, shadow: dict[str, Any]) -> dict[str, dict[str, Any]]:
        rows = list(shadow.get("validation_categories") or [])
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            category = _text(row.get("category"), "")
            if category:
                out[category] = dict(row)
        return out

    def _factor_rows(self, statuses: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        confidence = _status(statuses, "confidence_calibration_performance_attribution_v1")
        archetype = _status(statuses, "trade_archetype_regime")
        catalyst_lifecycle = _status(statuses, "catalyst_lifecycle_intelligence_v1")
        catalyst_decay = _status(statuses, "catalyst_persistence_decay_curves_v2")
        etf = _status(statuses, "etf_sector_rotation_intelligence_v1")
        breadth = _status(statuses, "market_breadth_index_intelligence_v1")
        cross_market = _status(statuses, "cross_market_attribution_transfer_learning_v1")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        memory = _status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        historical = _status(statuses, "historical_intelligence_market_memory_suite_v1")
        opportunity = _status(statuses, "opportunity_cost_learning")
        full = _status(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        decision = _status(statuses, "decision_optimization_trade_management_suite_v1")
        trade_family = _status(statuses, "trade_family_intelligence_v1")
        market_condition = _status(statuses, "market_condition_attribution_v1")
        shadow = self._shadow_category_map(_status(statuses, "shadow_correction_validation_attribution_v1"))

        factors = [
            ("confidence_score", _to_float(confidence.get("confidence_predictive_power"), 50.0), _to_float(confidence.get("confidence_predictive_power"), 50.0), _to_int(confidence.get("evidence_count"), 0)),
            ("archetype", _to_float(archetype.get("current_archetype_regime_alignment_score"), 50.0), _to_float(decision.get("decision_quality_score"), 50.0), _to_int(_first(archetype.get("tracked_trades"), decision.get("tracked_trades"), default=0), 0)),
            ("regime_fit", _to_float(market_condition.get("condition_confidence_score"), 50.0), _to_float(market_condition.get("condition_confidence_score"), 50.0), _to_int(market_condition.get("evidence_count"), 0)),
            ("catalyst_quality", _to_float(catalyst_lifecycle.get("catalyst_lifecycle_confidence"), 50.0), _to_float(catalyst_lifecycle.get("catalyst_lifecycle_confidence"), 50.0), _to_int(catalyst_lifecycle.get("evidence_count"), 0)),
            ("catalyst_persistence", _to_float(catalyst_decay.get("catalyst_decay_confidence"), 50.0), _to_float(catalyst_decay.get("catalyst_decay_readiness"), _to_float(catalyst_decay.get("catalyst_decay_confidence"), 50.0)), _to_int(catalyst_decay.get("catalysts_tracked"), 0)),
            ("sector_leadership", _to_float(etf.get("sector_rotation_confidence"), 50.0), _to_float(etf.get("etf_leadership_score"), 50.0), len(list(etf.get("etf_symbols_tracked") or []))),
            ("market_breadth_support", _to_float(breadth.get("index_confidence_score"), 50.0), _to_float(breadth.get("market_support_for_equity_trades"), 50.0), len(list(breadth.get("index_symbols_tracked") or []))),
            ("cross_market_support", _to_float(cross_market.get("cross_market_transfer_confidence"), 50.0), _to_float(cross_market.get("index_to_stock_signal_score"), 50.0), len(list(cross_market.get("relationship_rows") or []))),
            ("profitability_context", _to_float(accelerated.get("profitability_attribution_score"), 50.0), _to_float(decision.get("decision_quality_score"), 50.0), _to_int(accelerated.get("accelerated_learning_events"), 0)),
            ("buy_purity_context", _to_float((shadow.get("buy_purity") or {}).get("confidence_score"), 50.0), _to_float((shadow.get("buy_purity") or {}).get("readiness_score"), 50.0), _to_int((shadow.get("buy_purity") or {}).get("evidence_count"), 0)),
            ("opportunity_cost_context", _to_float(opportunity.get("selection_quality_score"), 50.0), _to_float(opportunity.get("ranking_quality_score"), 50.0), _to_int(_first(opportunity.get("selected_candidates_reviewed"), opportunity.get("rejected_candidates_reviewed"), default=0), 0)),
            ("trade_family_support", _to_float(trade_family.get("family_transfer_confidence"), 50.0), _to_float(trade_family.get("family_learning_score"), 50.0), _to_int(trade_family.get("evidence_count"), 0)),
            ("symbol_intelligence", _to_float(accelerated.get("symbol_personality_quality_score"), 50.0), _to_float(accelerated.get("transferable_learning_confidence"), 50.0), _to_int(accelerated.get("symbol_profiles_tracked"), 0)),
            ("historical_memory_support", _to_float(_first(historical.get("market_memory_quality_score"), memory.get("symbol_memory_quality_score"), full.get("memory_quality_score"), default=50.0)), _to_float(_first(memory.get("symbol_memory_quality_score"), historical.get("market_memory_quality_score"), default=50.0)), _to_int(_first(memory.get("symbol_profiles_tracked"), historical.get("evidence_count"), full.get("opportunities_tracked"), default=0), 0)),
        ]

        rows: list[dict[str, Any]] = []
        for name, support, predictive, evidence in factors:
            evidence_norm = min(100.0, max(0.0, evidence) * 1.8)
            alpha_score = _clamp(predictive * 0.60 + support * 0.25 + evidence_norm * 0.15)
            mistake_risk = _clamp((100.0 - predictive) * 0.55 + max(0.0, support - predictive) * 0.45)
            overvalued = _clamp(max(0.0, support - predictive) * 1.25 + max(0.0, 55.0 - evidence_norm) * 0.20)
            undervalued = _clamp(max(0.0, predictive - support) * 1.25 + evidence_norm * 0.10)
            rows.append({
                "factor": name,
                "support_score": _round(support, 3),
                "predictive_score": _round(predictive, 3),
                "factor_evidence": int(evidence),
                "alpha_contribution_score": _round(alpha_score, 3),
                "mistake_risk_score": _round(mistake_risk, 3),
                "overvaluation_risk": _round(overvalued, 3),
                "undervaluation_opportunity": _round(undervalued, 3),
            })
        return rows

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        execution = _status(statuses, "execution_participation_audit")
        paper_trace = _status(statuses, "paper_execution_trace")
        opportunity = _status(statuses, "opportunity_cost_learning")
        confidence = _status(statuses, "confidence_calibration_performance_attribution_v1")
        decision = _status(statuses, "decision_optimization_trade_management_suite_v1")
        archetype = _status(statuses, "trade_archetype_regime")
        catalyst_lifecycle = _status(statuses, "catalyst_lifecycle_intelligence_v1")
        catalyst_decay = _status(statuses, "catalyst_persistence_decay_curves_v2")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        memory = _status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        historical = _status(statuses, "historical_intelligence_market_memory_suite_v1")
        trade_family = _status(statuses, "trade_family_intelligence_v1")
        market_condition = _status(statuses, "market_condition_attribution_v1")
        market_breadth = _status(statuses, "market_breadth_index_intelligence_v1")
        etf = _status(statuses, "etf_sector_rotation_intelligence_v1")
        cross_market = _status(statuses, "cross_market_attribution_transfer_learning_v1")
        trade_thesis = _status(statuses, "trade_thesis_validation_v1")
        full = _status(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        shadow_vs_paper = _status(statuses, "shadow_vs_paper_performance_attribution_v1")
        shadow_correction = _status(statuses, "shadow_correction_validation_attribution_v1")
        shadow_category_map = self._shadow_category_map(shadow_correction)

        promoted_candidates = max(
            _to_int(execution.get("candidates_promoted"), 0),
            _to_int(((paper_trace.get("broad_universe_intake_promotion") or {}).get("promoted_to_top_buys_count")), 0),
        )
        selected_candidates = max(
            _to_int(paper_trace.get("selected_candidates"), 0),
            _to_int(execution.get("candidates_submitted"), 0),
            _to_int(opportunity.get("selected_candidates_reviewed"), 0),
        )
        rejected_candidates = max(
            _to_int(opportunity.get("rejected_candidates_reviewed"), 0),
            _to_int(execution.get("reviewed_total"), 0) - selected_candidates,
            _to_int(execution.get("candidates_portfolio_rejected"), 0)
            + _to_int(execution.get("candidates_timing_rejected"), 0)
            + _to_int(execution.get("candidates_correlation_rejected"), 0)
            + _to_int(execution.get("candidates_confirmation_rejected"), 0)
            + _to_int(execution.get("candidates_exploration_rejected"), 0)
            + _to_int(execution.get("candidates_position_limit_rejected"), 0),
        )
        top_ranked_candidates = max(
            _to_int(execution.get("reviewed_total"), 0),
            _to_int(execution.get("candidates_seen"), 0),
            selected_candidates + rejected_candidates,
            _to_int(full.get("opportunities_tracked"), 0),
        )
        missed_candidates = max(
            _to_int(opportunity.get("missed_opportunity_count"), 0),
            _to_int(execution.get("missed_high_expectancy_candidates"), 0),
        )
        actual_winners = _to_int(shadow_vs_paper.get("winning_trade_count"), 0)
        actual_losers = _to_int(shadow_vs_paper.get("losing_trade_count"), 0)
        evidence_count = max(
            top_ranked_candidates,
            _to_int(shadow_correction.get("shadow_recommendations_reviewed"), 0),
            _to_int(full.get("opportunities_tracked"), 0),
            _to_int(confidence.get("evidence_count"), 0),
        )

        selection_quality = _clamp(opportunity.get("selection_quality_score"), 50.0)
        ranking_quality_base = _clamp(_first(opportunity.get("ranking_quality_score"), decision.get("decision_quality_score"), default=50.0))
        confidence_power = _clamp(confidence.get("confidence_predictive_power"), 50.0)
        decision_quality = _clamp(decision.get("decision_quality_score"), 50.0)
        feature_confidence = _clamp(_first(full.get("feature_attribution_confidence"), confidence.get("feature_attribution_confidence"), default=50.0))
        memory_quality = _clamp(_first(historical.get("market_memory_quality_score"), memory.get("symbol_memory_quality_score"), full.get("memory_quality_score"), default=50.0))
        candidate_ranking_row = shadow_category_map.get("candidate_ranking") or {}
        buy_purity_row = shadow_category_map.get("buy_purity") or {}
        opportunity_cost_row = shadow_category_map.get("opportunity_cost") or {}

        missed_alpha = _round(
            max(0.0, _to_float(opportunity.get("average_opportunity_cost"), 0.0))
            * max(1.0, _to_float(missed_candidates, 0.0)),
            3,
        )
        opportunity_ranking_gap = _round(
            abs(_to_float(opportunity.get("average_opportunity_cost"), 0.0))
            + max(0.0, _to_float(execution.get("missed_profit_capture_pct"), 0.0) / 8.0),
            3,
        )
        ranking_miss_rate = _clamp((float(missed_candidates) / max(1.0, float(evidence_count))) * 100.0)
        ranking_accuracy = _clamp(
            selection_quality * 0.40
            + ranking_quality_base * 0.30
            + confidence_power * 0.20
            + _to_float(candidate_ranking_row.get("confidence_score"), 50.0) * 0.10
        )
        promotion_accuracy = _clamp(
            selection_quality * 0.55
            + ranking_accuracy * 0.25
            + _to_float(candidate_ranking_row.get("readiness_score"), 50.0) * 0.20
        )
        rejection_accuracy = _clamp(
            (100.0 - ranking_miss_rate) * 0.45
            + _to_float(opportunity_cost_row.get("confidence_score"), 50.0) * 0.25
            + confidence_power * 0.15
            + decision_quality * 0.15
        )
        ranking_consistency = _clamp(
            decision_quality * 0.35
            + feature_confidence * 0.30
            + memory_quality * 0.20
            + _to_float(trade_thesis.get("thesis_accuracy_score"), 50.0) * 0.15
        )
        ranking_overconfidence = _clamp(
            max(0.0, 100.0 - confidence_power) * 0.45
            + max(0.0, 100.0 - rejection_accuracy) * 0.30
            + min(100.0, opportunity_ranking_gap * 4.0) * 0.25
        )
        ranking_underconfidence = _clamp(
            ranking_miss_rate * 0.50
            + min(100.0, missed_alpha / max(1.0, float(evidence_count)) * 3.0) * 0.30
            + max(0.0, 100.0 - _to_float(buy_purity_row.get("confidence_score"), 50.0)) * 0.20
        )

        factor_rows = self._factor_rows(statuses)
        strongest_positive = max(factor_rows, key=lambda row: _to_float(row.get("alpha_contribution_score"), 0.0), default={})
        strongest_negative = max(factor_rows, key=lambda row: _to_float(row.get("mistake_risk_score"), 0.0), default={})
        most_predictive = max(factor_rows, key=lambda row: _to_float(row.get("predictive_score"), 0.0), default={})
        least_predictive = min(factor_rows, key=lambda row: _to_float(row.get("predictive_score"), 0.0), default={})
        most_overvalued = max(factor_rows, key=lambda row: _to_float(row.get("overvaluation_risk"), 0.0), default={})
        most_undervalued = max(factor_rows, key=lambda row: _to_float(row.get("undervaluation_opportunity"), 0.0), default={})

        promotion_success_rate = _round(promotion_accuracy, 3)
        promotion_failure_rate = _round(_clamp(100.0 - promotion_success_rate), 3)
        promotion_alpha_score = _round(
            _clamp(
                ranking_accuracy * 0.30
                + _to_float(most_predictive.get("alpha_contribution_score"), 50.0) * 0.25
                + _to_float(trade_family.get("family_learning_score"), 50.0) * 0.15
                + _to_float(accelerated.get("profitability_attribution_score"), 50.0) * 0.15
                + (100.0 - ranking_miss_rate) * 0.15
            ),
            3,
        )
        promotion_confidence_score = _round(
            _clamp(
                confidence_power * 0.30
                + feature_confidence * 0.25
                + memory_quality * 0.20
                + _to_float(candidate_ranking_row.get("confidence_score"), 50.0) * 0.25
            ),
            3,
        )

        best_promoted_candidate = _text(_first(opportunity.get("best_selected_symbol"), shadow_vs_paper.get("paper_best_symbol"), default="insufficient_data"))
        worst_promoted_candidate = _text(_first(opportunity.get("worst_selected_symbol"), opportunity.get("largest_negative_gap_symbol"), default="insufficient_data"))
        biggest_missed_promotion = _text(_first(opportunity.get("missed_best_symbol"), opportunity.get("best_rejected_symbol"), default="insufficient_data"))
        biggest_false_promotion = _text(_first(opportunity.get("largest_negative_gap_symbol"), opportunity.get("worst_selected_symbol"), default="insufficient_data"))

        strongest_promotion_archetype = _text(_first(archetype.get("best_archetype"), archetype.get("current_best_supported_archetype"), default="insufficient_data"))
        strongest_promotion_regime = _text(_first(archetype.get("best_regime"), market_condition.get("best_condition"), default="insufficient_data"))
        strongest_promotion_sector = _text(_first(etf.get("strongest_sector"), historical.get("strongest_sector_behavior"), default="insufficient_data"))
        strongest_promotion_catalyst = _text(_first(catalyst_lifecycle.get("best_catalyst_lifecycle"), catalyst_decay.get("strongest_persistence_pattern"), default="insufficient_data"))
        weakest_promotion_archetype = _text(_first(archetype.get("weakest_archetype"), default="insufficient_data"))
        weakest_promotion_regime = _text(_first(archetype.get("weakest_regime"), market_condition.get("weakest_condition"), default="insufficient_data"))
        weakest_promotion_sector = _text(_first(etf.get("weakest_sector"), default="insufficient_data"))
        weakest_promotion_catalyst = _text(_first(catalyst_lifecycle.get("worst_catalyst_lifecycle"), catalyst_decay.get("strongest_decay_pattern"), default="insufficient_data"))

        dominant_ranking_mistake = _text(
            _first(
                opportunity.get("ranking_improvement_recommendation"),
                execution.get("eligible_not_submitted_reason"),
                execution.get("final_blocker_reason"),
                default="ranking_signal_not_yet_explained",
            )
        )
        dominant_rejection_mistake = _text(_first(execution.get("eligible_not_submitted_reason"), opportunity.get("ranking_improvement_recommendation"), default="candidate_rejected_without_follow_through_capture"))
        dominant_missed_winner_pattern = _text(
            _first(
                opportunity.get("ranking_improvement_recommendation"),
                trade_family.get("strongest_trade_family"),
                market_condition.get("best_condition"),
                default="momentum_and_context_underweighted",
            )
        )
        most_common_missed_catalyst = _text(_first(catalyst_lifecycle.get("best_catalyst_lifecycle"), strongest_promotion_catalyst, default="unknown_catalyst"))
        most_common_missed_sector_rotation = _text(_first(etf.get("strongest_sector_rotation"), historical.get("strongest_sector_behavior"), default="sector_rotation_underweighted"))
        most_common_missed_regime_signal = _text(_first(market_condition.get("best_condition"), market_breadth.get("current_index_regime"), default="risk_transition_underweighted"))

        ranking_predictive_power = _round(
            _clamp(
                _to_float(most_predictive.get("predictive_score"), 50.0) * 0.35
                + confidence_power * 0.25
                + selection_quality * 0.20
                + ranking_quality_base * 0.20
            ),
            3,
        )
        ranking_reliability = _round(_clamp(ranking_accuracy * 0.45 + ranking_consistency * 0.35 + rejection_accuracy * 0.20), 3)
        ranking_confidence_score = _round(
            _clamp(
                promotion_confidence_score * 0.40
                + memory_quality * 0.20
                + _to_float(trade_thesis.get("thesis_confidence"), 50.0) * 0.20
                + _to_float(shadow_correction.get("confidence_score"), 50.0) * 0.20
            ),
            3,
        )
        ranking_quality_score = _round(
            _clamp(
                promotion_accuracy * 0.22
                + rejection_accuracy * 0.22
                + ranking_consistency * 0.18
                + ranking_predictive_power * 0.20
                + max(0.0, 100.0 - min(100.0, opportunity_ranking_gap * 5.0)) * 0.18
            ),
            3,
        )
        ranking_truth_score = _round(_clamp(confidence_power * 0.40 + feature_confidence * 0.30 + ranking_predictive_power * 0.30), 3)
        consistency_score = _round(ranking_consistency, 3)
        attribution_quality = _round(
            _clamp(
                feature_confidence * 0.35
                + memory_quality * 0.20
                + _to_float(most_predictive.get("factor_evidence"), 0.0) * 0.12
                + _to_float(candidate_ranking_row.get("confidence_score"), 50.0) * 0.18
                + _to_float(opportunity_cost_row.get("confidence_score"), 50.0) * 0.15
            ),
            3,
        )
        confidence_score = _round(
            _clamp(
                ranking_confidence_score * 0.45
                + ranking_truth_score * 0.25
                + attribution_quality * 0.15
                + consistency_score * 0.15
            ),
            3,
        )

        if evidence_count >= 300 and confidence_score >= 75.0 and ranking_truth_score >= 70.0 and ranking_quality_score >= 72.0:
            ranking_maturity = "high_evidence_shadow_only"
            candidate_ranking_influence_readiness = "overwhelming_evidence_still_shadow_only"
        elif evidence_count >= 180 and confidence_score >= 65.0:
            ranking_maturity = "validation_building"
            candidate_ranking_influence_readiness = "shadow_validation_building"
        elif evidence_count >= 60:
            ranking_maturity = "emerging"
            candidate_ranking_influence_readiness = "collect_more_candidate_truth_evidence"
        else:
            ranking_maturity = "warming_up"
            candidate_ranking_influence_readiness = "insufficient_evidence"

        predictive_score_text = str(_round(most_predictive.get("predictive_score"), 1))
        strongest_ranking_lesson = (
            f"Weight {_humanize(_text(most_predictive.get('factor')))} more heavily in future ranking audits; "
            f"it is currently the most predictive factor with score {predictive_score_text}."
        )
        strongest_promotion_lesson = (
            f"Promotions work best when {_humanize(strongest_promotion_archetype)} aligns with "
            f"{_humanize(strongest_promotion_regime)} and {_humanize(strongest_promotion_catalyst)} context."
        )
        strongest_rejection_lesson = (
            f"Rejected candidates most often become missed winners when {_humanize(_text(most_undervalued.get('factor')))} is underweighted."
        )
        dominant_ranking_blind_spot = _humanize(_text(most_overvalued.get("factor")))
        next_ranking_focus = _humanize(_text(most_undervalued.get("factor")))
        highest_expected_ranking_improvement = (
            f"Reduce {_humanize(_text(most_overvalued.get('factor')))} overvaluation and "
            f"raise {_humanize(_text(most_undervalued.get('factor')))} support."
        )

        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_candidate_ranking_audit",
            "generated_at": _now_iso(),
            "evidence_count": int(evidence_count),
            "promoted_candidates": int(promoted_candidates),
            "rejected_candidates": int(max(0, rejected_candidates)),
            "selected_candidates": int(selected_candidates),
            "missed_candidates": int(missed_candidates),
            "top_ranked_candidates": int(top_ranked_candidates),
            "actual_winners": int(actual_winners),
            "actual_losers": int(actual_losers),
            "ranking_accuracy": _round(ranking_accuracy, 3),
            "promotion_accuracy": _round(promotion_accuracy, 3),
            "rejection_accuracy": _round(rejection_accuracy, 3),
            "ranking_miss_rate": _round(ranking_miss_rate, 3),
            "ranking_overconfidence": _round(ranking_overconfidence, 3),
            "ranking_underconfidence": _round(ranking_underconfidence, 3),
            "ranking_consistency": _round(ranking_consistency, 3),
            "ranking_factor_rows": factor_rows,
            "strongest_positive_ranking_factor": _text(strongest_positive.get("factor")),
            "strongest_negative_ranking_factor": _text(strongest_negative.get("factor")),
            "most_predictive_ranking_factor": _text(most_predictive.get("factor")),
            "least_predictive_ranking_factor": _text(least_predictive.get("factor")),
            "most_overvalued_factor": _text(most_overvalued.get("factor")),
            "most_undervalued_factor": _text(most_undervalued.get("factor")),
            "promotion_success_rate": promotion_success_rate,
            "promotion_failure_rate": promotion_failure_rate,
            "promotion_alpha_score": promotion_alpha_score,
            "promotion_confidence_score": promotion_confidence_score,
            "best_promoted_candidate": best_promoted_candidate,
            "worst_promoted_candidate": worst_promoted_candidate,
            "biggest_missed_promotion": biggest_missed_promotion,
            "biggest_false_promotion": biggest_false_promotion,
            "missed_winners": int(missed_candidates),
            "missed_alpha": missed_alpha,
            "opportunity_ranking_gap": opportunity_ranking_gap,
            "dominant_missed_winner_pattern": dominant_missed_winner_pattern,
            "dominant_ranking_mistake": dominant_ranking_mistake,
            "dominant_rejection_mistake": dominant_rejection_mistake,
            "most_common_missed_catalyst": most_common_missed_catalyst,
            "most_common_missed_sector_rotation": most_common_missed_sector_rotation,
            "most_common_missed_regime_signal": most_common_missed_regime_signal,
            "ranking_quality_score": ranking_quality_score,
            "ranking_confidence_score": ranking_confidence_score,
            "ranking_predictive_power": ranking_predictive_power,
            "ranking_reliability": ranking_reliability,
            "ranking_maturity": ranking_maturity,
            "strongest_promotion_archetype": strongest_promotion_archetype,
            "strongest_promotion_regime": strongest_promotion_regime,
            "strongest_promotion_sector": strongest_promotion_sector,
            "strongest_promotion_catalyst": strongest_promotion_catalyst,
            "weakest_promotion_archetype": weakest_promotion_archetype,
            "weakest_promotion_regime": weakest_promotion_regime,
            "weakest_promotion_sector": weakest_promotion_sector,
            "weakest_promotion_catalyst": weakest_promotion_catalyst,
            "strongest_ranking_lesson": strongest_ranking_lesson,
            "strongest_promotion_lesson": strongest_promotion_lesson,
            "strongest_rejection_lesson": strongest_rejection_lesson,
            "dominant_ranking_blind_spot": dominant_ranking_blind_spot,
            "next_ranking_focus": next_ranking_focus,
            "highest_expected_ranking_improvement": highest_expected_ranking_improvement,
            "candidate_ranking_influence_readiness": candidate_ranking_influence_readiness,
            "confidence_score": confidence_score,
            "consistency_score": consistency_score,
            "attribution_quality": attribution_quality,
            "ranking_truth_score": ranking_truth_score,
            "influence_ready": False,
            "influence_confidence": _round(min(confidence_score, 69.0), 3),
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "portfolio_allocation_changed": False,
            "thresholds_changed": False,
            "forced_exits_enabled": False,
            "forced_trades_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "behavior_safe_to_apply": False,
            "shadow_recommendation": "Use this suite to audit ranking truth and promotion quality only; do not change ranking, promotion logic, entries, exits, sizing, thresholds, or broker behavior.",
            "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
        }
        _write_json(self.cache_path, out)
        return out

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = _round(now - self._cache_ts, 3)
            out["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
            return out
        if not force:
            disk = _read_json(self.cache_path)
            if disk:
                try:
                    age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
                except Exception:
                    age = 999999.0
                if age <= self.ttl_seconds:
                    disk["cache_hit"] = True
                    disk["cache_age_seconds"] = _round(age, 3)
                    disk["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
                    self._cache = dict(disk)
                    self._cache_ts = now - age
                    return disk
        try:
            out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = {
                "enabled": False,
                "version": VERSION,
                "mode": "shadow_only_candidate_ranking_audit",
                "degraded_reason": f"candidate_ranking_attribution_unavailable:{str(exc)[:140]}",
                "evidence_count": 0,
                "ranking_quality_score": 0.0,
                "promotion_accuracy": 0.0,
                "rejection_accuracy": 0.0,
                "ranking_predictive_power": 0.0,
                "strongest_positive_ranking_factor": "insufficient_data",
                "least_predictive_ranking_factor": "insufficient_data",
                "biggest_missed_promotion": "insufficient_data",
                "dominant_ranking_mistake": "insufficient_data",
                "candidate_ranking_influence_readiness": "insufficient_evidence",
                "confidence_score": 0.0,
                "influence_ready": False,
                "influence_confidence": 0.0,
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "entry_behavior_changed": False,
                "exit_behavior_changed": False,
                "position_sizing_changed": False,
                "portfolio_allocation_changed": False,
                "thresholds_changed": False,
                "forced_exits_enabled": False,
                "forced_trades_enabled": False,
                "partial_sells_enabled": False,
                "automatic_trailing_stops_enabled": False,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = time.time()
        return out
