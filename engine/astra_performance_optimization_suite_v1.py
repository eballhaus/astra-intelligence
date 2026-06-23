from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
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


WEAKNESS_CATEGORIES = (
    "panic_exit",
    "profit_capture",
    "giveback",
    "horizon_accuracy",
    "overholding",
    "early_exit",
    "late_exit",
    "weak_follow_through",
    "speculative_asset_weakness",
    "overfiltering",
    "underlearning",
)

LESSON_CATEGORIES = (
    "profit_capture",
    "exit_quality",
    "giveback_reduction",
    "horizon_selection",
    "speculative_asset_behavior",
    "market_regime_behavior",
    "symbol_behavior",
    "portfolio_fit",
    "confidence_calibration",
)

HORIZONS = ("scalp", "day_trade", "swing", "multi_day", "longer_hold", "unknown")


def _safe_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "shadow_safe": True,
        "cache_first": True,
        "advisory_only": True,
        "rollback_aware": True,
        "human_review_required": True,
        "broker_execution_added": False,
        "automatic_entries_enabled": False,
        "automatic_exits_enabled": False,
        "automatic_sizing_enabled": False,
        "automatic_allocations_enabled": False,
        "automatic_shadow_promotion_enabled": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "thresholds_changed": False,
        "confidence_scoring_changed": False,
        "shadow_logic_changed": False,
        "paper_execution_changed": False,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "provider_ownership_changed": False,
        "provider_polling_changed": False,
        "aios_behavior_changed": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _normalize_horizon(value: Any) -> str:
    raw = text(value, "unknown").lower().replace("-", "_").replace(" ", "_")
    if "scalp" in raw or raw in {"15m", "30m", "45m", "60m"}:
        return "scalp"
    if "day" in raw or "intraday" in raw or "eod" in raw or raw in {"2h", "4h"}:
        return "day_trade"
    if "long" in raw or raw in {"10d+", "longer_hold"}:
        return "longer_hold"
    if "multi" in raw or raw in {"2d", "3d", "5d", "10d"}:
        return "multi_day"
    if "swing" in raw or "overnight" in raw or raw == "1d":
        return "swing"
    return "unknown"


def _as_rows(value: Any, limit: int = 80) -> list[dict[str, Any]]:
    return [dict(row) for row in (value or [])[:limit] if isinstance(row, dict)]


def _source_rows(statuses: dict[str, Any]) -> list[dict[str, Any]]:
    foundation = status_value(statuses, "astra_trading_intelligence_foundation_v1")
    lifecycle = dict(foundation.get("trade_lifecycle_intelligence_v1") or {})
    rows = _as_rows(lifecycle.get("sample_trades"), 80)
    if rows:
        return rows
    audit = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
    return _as_rows(first(audit.get("position_audit_rows"), audit.get("truth_validation_rows"), []), 80)


def _age_date(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(0, days))).date().isoformat()


class AstraPerformanceOptimizationSuiteV1(CachedDiagnosticModule):
    """Tier 2 advisory synthesis over existing cached learning evidence."""

    module_name = "astra_performance_optimization_suite_v1"
    mode = "paper_only_shadow_safe_performance_optimization_advisory"

    def _fallback(self, reason: str = "insufficient_evidence", **extra: Any) -> dict[str, Any]:
        payload = super()._fallback(reason, **extra)
        payload.update(_safe_flags())
        return payload

    @staticmethod
    def _foundation(statuses: dict[str, Any]) -> dict[str, Any]:
        return status_value(statuses, "astra_trading_intelligence_foundation_v1")

    def _weakness_inputs(self, statuses: dict[str, Any]) -> dict[str, dict[str, Any]]:
        foundation = self._foundation(statuses)
        lifecycle = dict(foundation.get("trade_lifecycle_intelligence_v1") or {})
        horizon = dict(foundation.get("horizon_intelligence_v2") or {})
        shadow = dict(foundation.get("shadow_weakness_detector_v1") or {})
        tier1a = status_value(statuses, "astra_learning_preservation_capacity_v1")
        throughput = dict(tier1a.get("learning_throughput_preservation_engine_v1") or {})
        capacity = dict(tier1a.get("dynamic_horizon_allocation_diversity_engine_v1") or {})
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        capture = to_float(first(lifecycle.get("avg_profit_capture"), profit.get("average_capture_ratio"), 0.0), 0.0)
        if 0.0 < capture <= 1.5:
            capture *= 100.0
        giveback = to_float(first(lifecycle.get("avg_giveback"), profit.get("average_giveback_pct"), 0.0), 0.0)
        trades = max(to_int(lifecycle.get("trades_reviewed"), 0), to_int(profit.get("evidence_count"), 0))
        shadow_gaps = list(shadow.get("top_5_shadow_weaknesses") or [])
        speculative = next(
            (row for row in shadow_gaps if "specul" in text(row.get("area"), "").lower()),
            {},
        )
        return {
            "panic_exit": {"frequency": to_int(lifecycle.get("early_exit_count"), 0), "severity": clamp(100.0 - capture), "evidence": trades, "focus": "reduce_panic_exit"},
            "profit_capture": {"frequency": max(1 if capture < 60 and trades else 0, to_int(lifecycle.get("profit_reversal_count"), 0)), "severity": clamp(100.0 - capture), "evidence": trades, "focus": "protect_profit_earlier"},
            "giveback": {"frequency": to_int(lifecycle.get("profit_reversal_count"), 0), "severity": clamp(giveback * 8.0), "evidence": trades, "focus": "reduce_profit_giveback"},
            "horizon_accuracy": {"frequency": 1 if to_float(horizon.get("horizon_accuracy_score"), 0.0) < 65 else 0, "severity": clamp(100.0 - to_float(horizon.get("horizon_accuracy_score"), 0.0)), "evidence": trades, "focus": "improve_horizon_context_fit"},
            "overholding": {"frequency": to_int(lifecycle.get("overheld_count"), 0), "severity": clamp(to_int(lifecycle.get("overheld_count"), 0) * 14.0 + giveback * 3.0), "evidence": trades, "focus": "reduce_overholding"},
            "early_exit": {"frequency": to_int(lifecycle.get("early_exit_count"), 0), "severity": clamp(to_int(lifecycle.get("early_exit_count"), 0) * 16.0), "evidence": trades, "focus": "hold_winners_longer"},
            "late_exit": {"frequency": to_int(lifecycle.get("late_exit_count"), 0), "severity": clamp(to_int(lifecycle.get("late_exit_count"), 0) * 16.0 + giveback * 2.0), "evidence": trades, "focus": "tighten_thesis_break_detection"},
            "weak_follow_through": {"frequency": 1 if to_float(profit.get("follow_through"), 100.0) < 55 else 0, "severity": clamp(100.0 - to_float(profit.get("follow_through"), 50.0)), "evidence": trades, "focus": "separate_pullback_from_failure"},
            "speculative_asset_weakness": {"frequency": to_int(speculative.get("count"), 0), "severity": clamp(first(speculative.get("severity"), 45.0 if speculative else 0.0)), "evidence": to_int(speculative.get("evidence_count"), trades), "focus": "validate_speculative_asset_behavior"},
            "overfiltering": {"frequency": to_int(ranking.get("missed_winners"), 0), "severity": clamp(to_float(ranking.get("ranking_miss_rate"), 0.0)), "evidence": to_int(ranking.get("evidence_count"), 0), "focus": "review_missed_winner_patterns"},
            "underlearning": {"frequency": 1 if not throughput.get("fresh_evidence_flow_preserved") else 0, "severity": clamp(100.0 - to_float(throughput.get("learning_throughput_score"), 0.0)), "evidence": to_int(throughput.get("evidence_count"), 0), "focus": text(capacity.get("recommended_action"), "protect_fresh_evidence_flow")},
        }

    def _performance_correction(self, statuses: dict[str, Any]) -> dict[str, Any]:
        inputs = self._weakness_inputs(statuses)
        rows = []
        for category in WEAKNESS_CATEGORIES:
            item = inputs.get(category, {})
            frequency = to_int(item.get("frequency"), 0)
            severity = clamp(item.get("severity"))
            evidence = to_int(item.get("evidence"), 0)
            detected = frequency > 0 or severity >= 40
            if evidence <= 0:
                status = "insufficient_evidence"
            elif severity >= 65 and frequency >= 3:
                status = "regressed"
            elif detected and severity >= 40:
                status = "validated"
            elif detected:
                status = "detected"
            elif evidence >= 25:
                status = "resolved"
            else:
                status = "improving"
            trend = "worsening" if status == "regressed" else "improving" if status in {"improving", "resolved"} else "persistent"
            age_days = min(90, max(7, frequency * 7))
            rows.append({
                "weakness": category,
                "rolling_periods": {"7d": frequency, "14d": frequency, "30d": frequency, "90d": frequency},
                "first_detected": _age_date(age_days) if detected else None,
                "last_detected": _age_date(0) if detected else None,
                "frequency": frequency,
                "severity": rounded(severity, 3),
                "trend": trend,
                "status": status,
                "evidence_count": evidence,
                "confidence": rounded(clamp(min(90.0, evidence / 3.0) + severity * 0.35), 3),
                "correction_candidate": bool(status in {"validated", "regressed"} and evidence >= 25),
                "recommended_focus": text(item.get("focus"), f"monitor_{category}"),
            })
        persistent = sorted(
            [row for row in rows if row["status"] in {"detected", "validated", "regressed"}],
            key=lambda row: (row["severity"], row["frequency"]),
            reverse=True,
        )
        corrected = [row for row in rows if row["status"] in {"improving", "resolved"}]
        regressed = [row for row in rows if row["status"] == "regressed"]
        return {
            "module": "Performance Correction Engine V1",
            "status": "ok" if any(row["evidence_count"] for row in rows) else "insufficient_evidence",
            "rolling_periods_days": [7, 14, 30, 90],
            "weakness_rows": rows,
            "persistent_weaknesses": persistent[:6],
            "corrected_weaknesses": corrected[:6],
            "regressed_weaknesses": regressed[:6],
            "highest_priority_correction": persistent[0]["weakness"] if persistent else "collect_more_evidence",
            **_safe_flags(),
        }

    def _learning_persistence(self, statuses: dict[str, Any], correction: dict[str, Any]) -> dict[str, Any]:
        adaptive = status_value(statuses, "astra_adaptive_learning_v1")
        retention = status_value(statuses, "learning_acceleration_retention_suite_v1")
        foundation = self._foundation(statuses)
        lifecycle = dict(foundation.get("trade_lifecycle_intelligence_v1") or {})
        symbol = dict(foundation.get("symbol_behavioral_memory_v1") or {})
        horizon = dict(foundation.get("horizon_intelligence_v2") or {})
        market = status_value(statuses, "market_condition_attribution_v1")
        confidence = status_value(statuses, "confidence_calibration_performance_attribution_v1")
        evidence_base = max(
            to_int((adaptive.get("learning_accelerator_v2") or {}).get("evidence_count"), 0),
            to_int(lifecycle.get("trades_reviewed"), 0),
            to_int(retention.get("evidence_count"), 0),
        )
        category_sources = {
            "profit_capture": (lifecycle.get("avg_profit_capture"), ["trade_lifecycle_intelligence_v1", "profit_capture_intelligence"]),
            "exit_quality": (100.0 - to_float(lifecycle.get("avg_giveback"), 0.0) * 8.0, ["trade_lifecycle_intelligence_v1", "exit_intelligence"]),
            "giveback_reduction": (100.0 - to_float(lifecycle.get("avg_giveback"), 0.0) * 10.0, ["trade_lifecycle_intelligence_v1", "profit_capture_intelligence"]),
            "horizon_selection": (horizon.get("horizon_accuracy_score"), ["horizon_intelligence_v2", "dynamic_horizon_allocation"]),
            "speculative_asset_behavior": (symbol.get("symbol_memory_confidence"), ["symbol_behavioral_memory_v1", "shadow_weakness_detector_v1"]),
            "market_regime_behavior": (market.get("condition_confidence_score"), ["market_condition_attribution_v1"]),
            "symbol_behavior": (symbol.get("symbol_memory_confidence"), ["symbol_behavioral_memory_v1"]),
            "portfolio_fit": (status_value(statuses, "portfolio_health_summary").get("portfolio_health_score"), ["portfolio_health_summary"]),
            "confidence_calibration": (confidence.get("calibration_score"), ["confidence_calibration_performance_attribution_v1"]),
        }
        correction_map = {row["weakness"]: row for row in correction.get("weakness_rows") or []}
        lessons = []
        for index, category in enumerate(LESSON_CATEGORIES):
            score, sources = category_sources.get(category, (0.0, []))
            score = clamp(score)
            weakness_key = {
                "exit_quality": "late_exit",
                "giveback_reduction": "giveback",
                "horizon_selection": "horizon_accuracy",
                "speculative_asset_behavior": "speculative_asset_weakness",
            }.get(category, category)
            weak = correction_map.get(weakness_key, {})
            repeat_count = max(1 if score else 0, to_int(weak.get("frequency"), 0))
            evidence = max(0, int(evidence_base / max(1, len(LESSON_CATEGORIES))))
            persistence = clamp(score * 0.55 + min(35.0, evidence / 2.0) + min(10.0, repeat_count * 2.0))
            decay = clamp(100.0 - persistence + repeat_count * 3.0)
            if evidence <= 0:
                status = "learned"
            elif repeat_count >= 3 and persistence < 55:
                status = "regressed"
            elif persistence >= 80:
                status = "maintained"
            elif persistence >= 65:
                status = "monitored"
            elif persistence >= 50:
                status = "reinforced"
            else:
                status = "validated"
            lessons.append({
                "lesson_id": f"tier2-{index + 1:02d}-{category}",
                "lesson_category": category,
                "lesson_summary": f"Retain and monitor {category.replace('_', ' ')} evidence across repeated market cycles.",
                "source_systems": sources,
                "first_seen": _age_date(min(90, repeat_count * 10)),
                "last_seen": _age_date(0),
                "repeat_count": repeat_count,
                "confidence": rounded(clamp(score * 0.65 + min(35.0, evidence)), 3),
                "evidence_count": evidence,
                "reinforcement_count": max(0, repeat_count - 1),
                "persistence_score": rounded(persistence, 3),
                "application_readiness": "advisory_only" if persistence >= 50 else "collect_more_evidence",
                "decay_risk": rounded(decay, 3),
                "status": status,
            })
        retained = sorted(lessons, key=lambda row: row["persistence_score"], reverse=True)
        at_risk = sorted(lessons, key=lambda row: row["decay_risk"], reverse=True)
        repeated = [row for row in at_risk if row["repeat_count"] >= 3 and row["status"] != "maintained"]
        return {
            "module": "Learning Persistence Engine V1",
            "status": "ok" if evidence_base else "insufficient_evidence",
            "lesson_rows": lessons,
            "learning_persistence_score": rounded(sum(row["persistence_score"] for row in lessons) / max(1, len(lessons)), 3),
            "lesson_retention_score": rounded(sum(100.0 - row["decay_risk"] for row in lessons) / max(1, len(lessons)), 3),
            "lesson_reinforcement_score": rounded(sum(min(100.0, row["reinforcement_count"] * 20.0) for row in lessons) / max(1, len(lessons)), 3),
            "lesson_decay_risk": rounded(sum(row["decay_risk"] for row in lessons) / max(1, len(lessons)), 3),
            "repeat_learning_rate": rounded(sum(1 for row in lessons if row["repeat_count"] >= 2) / max(1, len(lessons)) * 100.0, 3),
            "top_retained_lessons": retained[:5],
            "top_at_risk_lessons": at_risk[:5],
            "lessons_repeated_without_resolution": repeated[:5],
            "recommended_reinforcement_focus": at_risk[0]["lesson_category"] if at_risk else "collect_more_evidence",
            **_safe_flags(),
        }

    def _repeated_mistakes(self, statuses: dict[str, Any], correction: dict[str, Any]) -> dict[str, Any]:
        rows = _source_rows(statuses)
        mistakes = []
        for weak in correction.get("weakness_rows") or []:
            repeat_count = to_int(weak.get("frequency"), 0)
            if repeat_count < 3 and weak.get("status") != "regressed":
                continue
            mistake_type = text(weak.get("weakness"), "unknown")
            affected = [text(row.get("symbol"), "").upper() for row in rows if mistake_type in text(first(row.get("exit_classification"), row.get("lifecycle_status"), ""), "").lower()]
            severity = clamp(weak.get("severity"))
            if severity >= 85 or repeat_count >= 10:
                escalation = "critical"
            elif severity >= 65 or repeat_count >= 6:
                escalation = "high_priority"
            elif repeat_count >= 3:
                escalation = "priority"
            else:
                escalation = "watch"
            mistakes.append({
                "mistake_type": mistake_type,
                "repeat_count": repeat_count,
                "affected_symbols": sorted(set(symbol for symbol in affected if symbol))[:10],
                "affected_horizons": sorted(set(_normalize_horizon(row.get("horizon")) for row in rows if row.get("horizon")))[:6],
                "affected_regimes": [],
                "affected_asset_types": [],
                "severity": rounded(severity, 3),
                "trend": weak.get("trend"),
                "recommended_correction": weak.get("recommended_focus"),
                "escalation_level": escalation,
            })
        mistakes.sort(key=lambda row: (row["escalation_level"] == "critical", row["severity"], row["repeat_count"]), reverse=True)
        return {
            "module": "Repeated Mistake Detector V1",
            "status": "ok" if correction.get("weakness_rows") else "insufficient_evidence",
            "top_repeated_mistakes": mistakes[:6],
            "critical_repeated_mistakes": [row for row in mistakes if row["escalation_level"] == "critical"][:6],
            "mistakes_improving": [
                {"mistake_type": row["weakness"], "trend": row["trend"], "recommended_correction": row["recommended_focus"]}
                for row in correction.get("corrected_weaknesses") or []
            ][:6],
            "repeated_mistake_count": len(mistakes),
            **_safe_flags(),
        }

    def _profit_optimization(self, statuses: dict[str, Any]) -> dict[str, Any]:
        foundation = self._foundation(statuses)
        lifecycle = dict(foundation.get("trade_lifecycle_intelligence_v1") or {})
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        protection = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        rows = _source_rows(statuses)
        capture = to_float(first(lifecycle.get("avg_profit_capture"), profit.get("average_capture_ratio"), 0.0), 0.0)
        if 0.0 < capture <= 1.5:
            capture *= 100.0
        giveback = to_float(first(lifecycle.get("avg_giveback"), profit.get("average_giveback_pct"), protection.get("giveback_rate"), 0.0), 0.0)
        mfe = sum(to_float(row.get("mfe_pct"), 0.0) for row in rows) / max(1, len(rows))
        current = sum(to_float(first(row.get("realized_return_pct"), row.get("current_return_pct"), 0.0), 0.0) for row in rows) / max(1, len(rows))
        left = max(0.0, mfe - current)
        issue_counts: dict[str, int] = {}
        for row in rows:
            issue = text(first(row.get("exit_classification"), row.get("lifecycle_status"), "unknown"), "unknown")
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
        highest = max(issue_counts, key=issue_counts.get) if issue_counts else text(lifecycle.get("dominant_lifecycle_issue"), "insufficient_evidence")
        correction_map = {
            "early_exit": "hold_winners_longer",
            "panic_exit": "reduce_panic_exit",
            "late_exit": "protect_profit_earlier",
            "overheld": "reduce_overholding",
            "profit_reversal": "protect_profit_earlier",
            "thesis_broken": "tighten_thesis_break_detection",
        }
        correction = correction_map.get(highest, "separate_pullback_from_failure")
        return {
            "module": "Profit Optimization Engine V1",
            "status": "ok" if rows or to_int(profit.get("evidence_count"), 0) else "insufficient_evidence",
            "avg_profit_capture": rounded(capture, 3),
            "avg_giveback": rounded(giveback, 3),
            "profit_left_on_table": rounded(left, 4),
            "missed_profit_estimate": rounded(left * max(1, len(rows)), 4),
            "profit_capture_score": rounded(clamp(capture), 3),
            "giveback_reduction_score": rounded(clamp(100.0 - giveback * 8.0), 3),
            "exit_quality_score": rounded(clamp(100.0 - giveback * 7.0), 3),
            "hold_extension_score": rounded(clamp(100.0 - to_int(lifecycle.get("early_exit_count"), 0) * 12.0), 3),
            "profit_lock_readiness": rounded(clamp(first(protection.get("profit_lock_readiness"), 100.0 - capture + giveback * 3.0)), 3),
            "pattern_counts": issue_counts,
            "highest_profit_leak": highest,
            "best_profit_capture_context": text(first(profit.get("best_policy"), protection.get("strongest_profit_protection_pattern"), "healthy_continuation")),
            "worst_profit_capture_context": text(first(profit.get("worst_policy"), protection.get("weakest_profit_protection_pattern"), highest)),
            "recommended_profit_correction": correction,
            "future_controlled_evolution_candidate": True if capture < 60 and max(len(rows), to_int(profit.get("evidence_count"), 0)) >= 25 else False,
            **_safe_flags(),
        }

    def _horizon_optimization(self, statuses: dict[str, Any]) -> dict[str, Any]:
        foundation = self._foundation(statuses)
        horizon = dict(foundation.get("horizon_intelligence_v2") or {})
        scorecard = dict(horizon.get("horizon_scorecard") or {})
        market = status_value(statuses, "market_condition_attribution_v1")
        rows = []
        aliases = {
            "scalp": ("scalp", "under_1_day"),
            "day_trade": ("day_trade", "intraday", "day", "0_to_1_days"),
            "swing": ("swing", "swing_trade", "1_to_3_days"),
            "multi_day": ("multi_day", "4_to_7_days", "8_to_30_days"),
            "longer_hold": ("longer_hold", "long", "30_plus_days"),
            "unknown": ("unknown",),
        }
        for name in HORIZONS:
            raw = next((dict(scorecard.get(key) or {}) for key in aliases[name] if scorecard.get(key)), {})
            evidence = to_int(first(raw.get("trade_count"), raw.get("evidence_count"), 0), 0)
            rows.append({
                "horizon": name,
                "evidence_count": evidence,
                "win_rate": rounded(raw.get("win_rate"), 3),
                "avg_return": rounded(raw.get("avg_return"), 4),
                "profit_capture": rounded(first(raw.get("avg_profit_capture"), raw.get("capture_ratio"), 0.0), 3),
                "giveback": rounded(first(raw.get("avg_giveback"), raw.get("giveback"), 0.0), 3),
                "exit_quality": rounded(raw.get("exit_quality"), 3),
                "continuation_quality": rounded(raw.get("continuation_quality"), 3),
                "best_market_context": text(first((market.get("best_horizon_by_condition") or {}).get(name) if isinstance(market.get("best_horizon_by_condition"), dict) else None, market.get("best_condition"), "unknown")),
                "worst_market_context": text(first(market.get("weakest_condition"), "unknown")),
                "best_asset_type": "insufficient_evidence",
                "worst_asset_type": "insufficient_evidence",
                "confidence": rounded(first(raw.get("confidence"), min(95.0, evidence * 4.0)), 3),
            })
        supported = [row for row in rows if row["evidence_count"] > 0]
        best = max(supported, key=lambda row: (row["avg_return"], row["profit_capture"]), default={})
        weakest = min(supported, key=lambda row: (row["avg_return"], -row["giveback"]), default={})
        accuracy = to_float(horizon.get("horizon_accuracy_score"), 0.0)
        context_fit = sum(row["confidence"] for row in supported) / max(1, len(supported))
        efficiency = sum(row["profit_capture"] for row in supported) / max(1, len(supported))
        return {
            "module": "Horizon Optimization Engine V1",
            "status": "ok" if supported else "insufficient_evidence",
            "horizon_rows": rows,
            "horizon_context_matrix": {row["horizon"]: {"best": row["best_market_context"], "worst": row["worst_market_context"]} for row in rows},
            "horizon_accuracy_score": rounded(accuracy, 3),
            "horizon_context_fit_score": rounded(context_fit, 3),
            "horizon_profit_efficiency": rounded(efficiency, 3),
            "horizon_mismatch_risk": rounded(clamp(100.0 - accuracy), 3),
            "best_current_horizon": text(first(best.get("horizon"), _normalize_horizon(horizon.get("best_horizon")), "unknown")),
            "weakest_current_horizon": text(first(weakest.get("horizon"), _normalize_horizon(horizon.get("worst_horizon")), "unknown")),
            "recommended_horizon_focus": text(horizon.get("recommended_horizon_focus"), "collect_more_context_specific_horizon_evidence"),
            "horizon_mismatch_patterns": [
                {"horizon": row["horizon"], "risk": rounded(clamp(100.0 - row["exit_quality"]), 3)}
                for row in rows if row["evidence_count"] > 0
            ],
            "recommended_horizon_optimization": "use_context_fit_for_advisory_learning_only",
            "tier1_dynamic_horizon_allocation_overridden": False,
            **_safe_flags(),
        }

    def _market_asset_intelligence(self, statuses: dict[str, Any]) -> dict[str, Any]:
        foundation = self._foundation(statuses)
        symbol_memory = dict(foundation.get("symbol_behavioral_memory_v1") or {})
        profiles = _as_rows(symbol_memory.get("symbol_profiles"), 40)
        family = status_value(statuses, "trade_family_intelligence_v1")
        market = status_value(statuses, "market_condition_attribution_v1")
        context_rows = _as_rows(first(market.get("condition_rows"), market.get("market_condition_rows"), []), 12)
        if not context_rows:
            context_rows = [{
                "market_context": text(first(market.get("best_condition"), "unknown")),
                "confidence": to_float(market.get("condition_confidence_score"), 0.0),
                "best_horizon": text(first(market.get("best_horizon_by_condition"), "unknown")),
            }]
        asset_rows = []
        for row in profiles:
            asset_type = text(first(row.get("behavior_label"), "unknown"), "unknown")
            asset_rows.append({
                "symbol": text(row.get("symbol"), "unknown"),
                "asset_type": asset_type if asset_type in {
                    "compounder", "momentum_leader", "speculative_momentum", "retail_sentiment",
                    "defensive", "cyclical", "high_volatility", "mean_reversion", "catalyst_driven",
                } else "unknown",
                "best_horizon": text(row.get("best_horizon"), "unknown"),
                "worst_horizon": text(row.get("worst_horizon"), "unknown"),
                "best_exit_style": text(row.get("best_exit_style"), "unknown"),
                "worst_exit_style": text(row.get("weakest_exit_style"), "unknown"),
                "avg_profit_capture": rounded(row.get("avg_profit_capture"), 3),
                "avg_giveback": rounded(row.get("avg_giveback"), 3),
                "continuation_tendency": rounded(row.get("continuation_tendency"), 3),
                "reversal_tendency": rounded(row.get("reversal_tendency"), 3),
                "volatility_profile": text(row.get("volatility_personality"), "unknown"),
                "catalyst_sensitivity": text(row.get("catalyst_sensitivity"), "unknown"),
                "market_regime_fit": text(row.get("best_regime"), "unknown"),
                "confidence": rounded(row.get("profile_confidence"), 3),
            })
        strongest = max(asset_rows, key=lambda row: (row["confidence"], row["avg_profit_capture"]), default={})
        weakest = max(asset_rows, key=lambda row: row["avg_giveback"], default={})
        return {
            "module": "Market Context & Asset Intelligence V1",
            "status": "ok" if asset_rows or context_rows else "insufficient_evidence",
            "asset_personality_profiles": asset_rows[:20],
            "market_context_rows": context_rows,
            "best_asset_contexts": [{
                "asset_type": strongest.get("asset_type", text(family.get("strongest_trade_family"), "unknown")),
                "best_horizon": strongest.get("best_horizon", text(family.get("best_family_horizon"), "unknown")),
                "market_context": text(market.get("best_condition"), "unknown"),
            }],
            "weakest_asset_contexts": [{
                "asset_type": weakest.get("asset_type", text(family.get("weakest_trade_family"), "unknown")),
                "worst_horizon": weakest.get("worst_horizon", "unknown"),
                "market_context": text(market.get("weakest_condition"), "unknown"),
            }],
            "recommended_asset_focus": text(first(strongest.get("asset_type"), family.get("strongest_trade_family"), "collect_more_asset_behavior_evidence")),
            "weakest_asset_type": text(first(weakest.get("asset_type"), family.get("weakest_trade_family"), "unknown")),
            "rankings_or_entries_changed": False,
            **_safe_flags(),
        }

    def _controlled_candidate(
        self,
        statuses: dict[str, Any],
        correction: dict[str, Any],
        persistence: dict[str, Any],
        profit: dict[str, Any],
        horizon: dict[str, Any],
    ) -> dict[str, Any]:
        tier1b = status_value(statuses, "astra_truth_controlled_evolution_executive_v1")
        bridge = dict(tier1b.get("shadow_paper_controlled_evolution_bridge_v1") or {})
        evidence = max(
            to_int(status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1").get("evidence_count"), 0),
            to_int((self._foundation(statuses).get("trade_lifecycle_intelligence_v1") or {}).get("trades_reviewed"), 0),
        )
        capture = to_float(profit.get("profit_capture_score"), 0.0)
        improvement = rounded(max(0.0, 60.0 - capture) + to_float(profit.get("avg_giveback"), 0.0), 3)
        confidence = rounded(clamp(
            to_float(persistence.get("learning_persistence_score"), 0.0) * 0.45
            + to_float(horizon.get("horizon_context_fit_score"), 0.0) * 0.20
            + min(35.0, evidence / 8.0)
        ), 3)
        stable = to_float(persistence.get("lesson_retention_score"), 0.0) >= 55
        qualifies = bool(improvement >= 10.0 and evidence >= 25 and confidence >= 55 and stable)
        return {
            "controlled_evolution_candidate": qualifies,
            "candidate_metric": "Profit Capture" if qualifies else "none",
            "candidate_delta": improvement if qualifies else 0.0,
            "candidate_confidence": confidence if qualifies else 0.0,
            "candidate_evidence_count": evidence if qualifies else 0,
            "candidate_status": "advisory_only",
            "human_review_required": True,
            "recommended_micro_test": bool(qualifies),
            "micro_test_activated": False,
            "existing_bridge_active_stage": to_int(bridge.get("current_active_stage"), 0),
            "existing_bridge_active_stage_label": text(bridge.get("current_active_stage_label"), "shadow_only"),
            "bridge_bypassed": False,
            "one_candidate_per_cycle": True,
            "rollback_available": True,
            "qualification_reason": (
                "profit_capture_improvement_meets_single_metric_evidence_confidence_stability_gate"
                if qualifies else "candidate_below_improvement_evidence_confidence_or_stability_gate"
            ),
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        correction = self._performance_correction(statuses)
        persistence = self._learning_persistence(statuses, correction)
        mistakes = self._repeated_mistakes(statuses, correction)
        profit = self._profit_optimization(statuses)
        horizon = self._horizon_optimization(statuses)
        market_asset = self._market_asset_intelligence(statuses)
        candidate = self._controlled_candidate(statuses, correction, persistence, profit, horizon)
        repeated_rows = list(mistakes.get("top_repeated_mistakes") or [])
        top_mistake = dict(repeated_rows[0]) if repeated_rows and isinstance(repeated_rows[0], dict) else {}
        summary = {
            "persistent_weakness": correction.get("highest_priority_correction"),
            "correction_status": text(first((correction.get("persistent_weaknesses") or [{}])[0].get("status") if correction.get("persistent_weaknesses") else None, "warming_up")),
            "profit_leak": profit.get("highest_profit_leak"),
            "repeated_mistake": top_mistake.get("mistake_type", "none"),
            "best_horizon_context": f"{horizon.get('best_current_horizon', 'unknown')} / {text(first((horizon.get('horizon_rows') or [{}])[0].get('best_market_context') if horizon.get('horizon_rows') else None, 'unknown'))}",
            "weakest_asset_type": market_asset.get("weakest_asset_type"),
            "recommended_focus": profit.get("recommended_profit_correction"),
            "controlled_evolution_candidate": candidate.get("candidate_metric") if candidate.get("controlled_evolution_candidate") else "none",
        }
        payload = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Tier 2 - Performance Optimization, Learning Persistence & Market Intelligence Suite V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "performance_correction_engine_v1": correction,
            "learning_persistence_engine_v1": persistence,
            "repeated_mistake_detector_v1": mistakes,
            "profit_optimization_engine_v1": profit,
            "horizon_optimization_engine_v1": horizon,
            "market_context_asset_intelligence_v1": market_asset,
            "controlled_evolution_integration": candidate,
            "executive_summary": summary,
            "bounded_cached_sources_only": True,
            "full_history_scan_performed": False,
            "dashboard_endpoint_count_added": 0,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(payload)
