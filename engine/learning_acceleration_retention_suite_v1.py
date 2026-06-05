from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1800
CACHE_TTL_SECONDS = 10.0

EVIDENCE_WEIGHTS = {
    "broker_confirmed_paper_trade": 100,
    "lifecycle_evidence": 80,
    "advanced_learning_reconciled_metrics": 75,
    "replay_counterfactual": 50,
    "opportunity_cost": 40,
    "rejected_candidate_tracking": 35,
    "market_context_observation": 30,
    "simulation_only": 20,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _values(rows: list[dict[str, Any]], *keys: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        for key in keys:
            if row.get(key) not in (None, ""):
                out.append(_to_float(row.get(key)))
                break
    return out


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker")).upper()


def _return_pct(row: dict[str, Any]) -> float:
    return _to_float(
        row.get("current_or_exit_profit_pct"),
        _to_float(row.get("current_return_pct"), _to_float(row.get("continuation_after_entry_pct"), _to_float(row.get("actual_return_pct"), _to_float(row.get("return_pct"))))),
    )


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("hold_duration_bucket"), "unknown").lower()
    hold = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes") or row.get("hold_time_minutes"))
    if "scalp" in raw or hold < 30:
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw or hold >= 1440:
        return "swing"
    if "day" in raw or hold < 390:
        return "day_trade"
    return "short_swing"


def _counter_best(counter: Counter[str], default: str = "insufficient_data") -> str:
    return counter.most_common(1)[0][0] if counter else default


class LearningAccelerationRetentionSuiteV1:
    """Shadow-only meta-learning, evidence weighting, retention, and conflict diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0
        self.state_path = os.path.join(self.state_dir, "learning_acceleration_retention_suite_v1.jsonl")

    def _rows(self, name: str, max_rows: int = MAX_ROWS) -> list[dict[str, Any]]:
        return _tail_jsonl(os.path.join(self.state_dir, name), max_rows=max_rows)

    def _collect_rows(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "lifecycle": self._rows("trade_lifecycle_excursion_v2.jsonl", 520) + self._rows("trade_lifecycle_excursion_v1.jsonl", 420),
            "profit_capture": self._rows("adaptive_profit_capture_intelligence_v1.jsonl", 520),
            "replay": self._rows("replay_counterfactual_learning_v2.jsonl", 520),
            "opportunity_cost": self._rows("opportunity_cost_learning_v1.jsonl", 520),
            "market_context": self._rows("market_context_learning_suite_v1.jsonl", 520),
            "exit_learning": self._rows("exit_learning_expansion_suite_v1.jsonl", 520),
            "v3": self._rows("adaptive_execution_exit_intelligence_v3.jsonl", 520),
            "archetype_regime": self._rows("trade_archetype_regime_intelligence_v1.jsonl", 420),
            "audit": self._rows("execution_suppression_audit_v1.jsonl", 520),
            "candidate": self._rows("candidate_decision_ledger_v1.jsonl", 420),
            "context_evidence_expansion": self._rows("context_evidence_expansion_suite_v1.jsonl", 320),
            "catalyst_theme_narrative_v2": self._rows("catalyst_theme_narrative_capital_flow_intelligence_v2.jsonl", 320),
        }

    def _evidence_mix(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, int]:
        broker_positions = _to_int((statuses.get("alpaca_paper_broker") or {}).get("broker_open_positions_count"), 0)
        broker_closes = _to_int((statuses.get("paper_execution_trace") or {}).get("closed_positions_today"), 0)
        return {
            "broker_confirmed_paper_trade": max(broker_positions + broker_closes, _to_int((statuses.get("paper_execution_trace") or {}).get("orders_submitted"), 0)),
            "lifecycle_evidence": len(rows["lifecycle"]),
            "advanced_learning_reconciled_metrics": _to_int((statuses.get("advanced_learning_intelligence") or {}).get("supporting_evidence_count"), 0) or _to_int((statuses.get("advanced_learning_intelligence") or {}).get("advanced_learning_sample_size"), 0),
            "replay_counterfactual": len(rows["replay"]),
            "opportunity_cost": len(rows["opportunity_cost"]),
            "rejected_candidate_tracking": len(rows["audit"]) + len(rows["candidate"]),
            "market_context_observation": len(rows["market_context"]) or _to_int((statuses.get("market_context_learning_suite_v1") or {}).get("context_records"), 0),
            "simulation_only": len(rows["exit_learning"]) + len(rows["v3"]),
        }

    def _priority(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        v3 = statuses.get("adaptive_execution_exit_intelligence_v3") or {}
        exit_learning = statuses.get("exit_learning_expansion_suite_v1") or {}
        profit_capture = statuses.get("adaptive_profit_capture") or {}
        issue = statuses.get("learning_issue_audit") or {}
        market_context = statuses.get("market_context_learning_suite_v1") or {}
        blind = statuses.get("blind_spot_detection") or {}
        portfolio = statuses.get("portfolio_diversification_correlation_v2") or {}
        confidence_attr = statuses.get("confidence_calibration_performance_attribution_v1") or {}
        context_expansion = statuses.get("context_evidence_expansion_suite_v1") or {}
        catalyst_v2 = statuses.get("catalyst_theme_narrative_capital_flow_intelligence_v2") or {}
        scores = {
            "profit_capture_and_giveback": max(_to_float(v3.get("protect_profit_score"), 0.0), 100.0 - _to_float(v3.get("avg_capture_ratio"), 0.5) * 100.0, _to_float(profit_capture.get("average_profit_giveback_pct"), 0.0) * 2.0),
            "exit_quality_and_hold_duration": max(_to_float(exit_learning.get("protect_profit_score"), 0.0), _to_float(exit_learning.get("hold_longer_score"), 0.0), _to_float(v3.get("hold_longer_score"), 0.0)),
            "follow_through_continuation": max(0.0, 70.0 - _to_float(v3.get("continuation_probability"), _to_float(exit_learning.get("continuation_after_profit_score"), 50.0))),
            "market_context_horizon_fit": max(0.0, 75.0 - _to_float(market_context.get("context_confidence"), 45.0)),
            "opportunity_cost_and_buy_purity": abs(_to_float((issue.get("opportunity_cost_diagnostics") or {}).get("average_opportunity_cost"), 0.0)) * 0.35,
            "blind_spot_coverage": _to_float(blind.get("blind_spot_score"), 0.0),
            "portfolio_risk_balance": max(_to_float(portfolio.get("average_correlation_pressure_score"), 0.0), _to_float(portfolio.get("average_concentration_pressure_score"), 0.0)),
            "confidence_grade_attribution": max(0.0, 70.0 - _to_float(confidence_attr.get("confidence_predictive_power"), 45.0)) if _to_int(confidence_attr.get("evidence_count"), 0) else 25.0,
            "context_evidence_expansion": max(
                0.0,
                100.0 - min(
                    _to_float(context_expansion.get("open_trade_learning_confidence"), 35.0),
                    _to_float(context_expansion.get("rejected_candidate_learning_confidence"), 35.0),
                    _to_float(context_expansion.get("catalyst_learning_confidence"), 35.0),
                ),
            ) if _to_int(context_expansion.get("evidence_count"), 0) else 35.0,
            "catalyst_theme_narrative_capital_flow": max(
                _to_float(catalyst_v2.get("unknown_catalyst_rate"), 60.0),
                100.0 - _to_float(catalyst_v2.get("catalyst_coverage_score"), 35.0),
                100.0 - _to_float(catalyst_v2.get("capital_flow_confidence"), 35.0),
            ) if _to_int(catalyst_v2.get("evidence_count"), 0) else 45.0,
        }
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top = ordered[0][0] if ordered else "insufficient_evidence"
        secondary = ordered[1][0] if len(ordered) > 1 else "insufficient_evidence"
        lowest = ordered[-1][0] if ordered else "insufficient_evidence"
        focus_map = {
            "profit_capture_and_giveback": "hold_duration_giveback_profit_protection_exit_quality",
            "exit_quality_and_hold_duration": "exit_quality_hold_time_peak_decay",
            "follow_through_continuation": "follow_through_continuation_after_entry",
            "market_context_horizon_fit": "premarket_catalyst_after_hours_horizon_context",
            "opportunity_cost_and_buy_purity": "selected_vs_rejected_candidate_outcomes",
            "blind_spot_coverage": "underexplored_context_evidence_collection",
            "portfolio_risk_balance": "portfolio_fit_correlation_concentration_learning",
            "confidence_grade_attribution": "confidence_grade_horizon_attribution_validation",
            "context_evidence_expansion": "open_trade_rejected_candidate_catalyst_evidence_collection",
            "catalyst_theme_narrative_capital_flow": "catalyst_theme_narrative_capital_flow_coverage",
        }
        return {
            "scores": {k: round(v, 4) for k, v in scores.items()},
            "top_learning_priority": top,
            "secondary_learning_priority": secondary,
            "lowest_learning_priority": lowest,
            "priority_reason": f"Highest shadow-learning pressure is {top.replace('_', ' ')} based on current diagnostics.",
            "priority_confidence": _clamp(35.0 + ordered[0][1] * 0.55 if ordered else 20.0),
            "recommended_worker_focus": focus_map.get(top, "collect_more_completed_lifecycle_evidence"),
        }

    def _coverage(self, all_rows: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        context = statuses.get("market_context_learning_suite_v1") or {}
        dimensions = {
            "horizon": Counter(_horizon(r) for r in all_rows if _symbol(r)),
            "archetype": Counter(_text(r.get("trade_archetype") or r.get("archetype"), "unknown") for r in all_rows if _symbol(r)),
            "market_regime": Counter(_text(r.get("market_regime") or r.get("regime"), "unknown") for r in all_rows if _symbol(r)),
            "catalyst_type": Counter((context.get("catalyst_type_distribution") or {}).keys()),
            "market_cap_tier": Counter(_text(r.get("cap_tier") or r.get("market_cap_bucket") or r.get("market_cap_tier"), "unknown") for r in all_rows if _symbol(r)),
            "sector": Counter(_text(r.get("sector") or r.get("sector_context_label"), "unknown") for r in all_rows if _symbol(r)),
            "premarket_profile": Counter((context.get("premarket_profile_distribution") or {}).keys()),
            "after_hours_profile": Counter((context.get("after_hours_profile_distribution") or {}).keys()),
            "trade_personality": Counter(_text(r.get("trade_personality"), "unknown") for r in all_rows if _symbol(r)),
        }
        areas: dict[str, int] = {name: len([k for k, v in counter.items() if k and k != "unknown" and v >= 1]) for name, counter in dimensions.items()}
        strongest = max(areas.items(), key=lambda item: item[1], default=("insufficient_data", 0))[0]
        weakest = min(areas.items(), key=lambda item: item[1], default=("insufficient_data", 0))[0]
        under = [name for name, count in areas.items() if count <= 1][:8]
        over = [name for name, count in areas.items() if count >= 5][:8]
        score = _clamp(sum(min(10, v) for v in areas.values()) / max(1, len(areas)) * 10.0)
        focus = under[0] if under else weakest
        return {
            "coverage_dimensions": areas,
            "strongest_coverage_area": strongest,
            "weakest_coverage_area": weakest,
            "underexplored_contexts": under,
            "overrepresented_contexts": over,
            "coverage_score": _round(score, 2),
            "recommended_evidence_collection_focus": f"collect_more_{focus}_evidence" if focus else "collect_more_lifecycle_evidence",
        }

    def _agreement_conflict(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        claims: dict[str, str] = {}
        market = statuses.get("market_context_learning_suite_v1") or {}
        exit_learning = statuses.get("exit_learning_expansion_suite_v1") or {}
        v3 = statuses.get("adaptive_execution_exit_intelligence_v3") or {}
        replay = statuses.get("replay_counterfactual_learning_v2") or {}
        archetype = statuses.get("trade_archetype_regime") or {}
        profit = statuses.get("adaptive_profit_capture") or {}
        claims["market_context"] = _text(market.get("best_context_horizon"), "insufficient_data")
        claims["exit_learning"] = _text(exit_learning.get("milestone_exit_bias") or exit_learning.get("best_hold_window"), "insufficient_data")
        claims["adaptive_exit_v3"] = _text(v3.get("shadow_exit_bias") or v3.get("most_profitable_horizon"), "insufficient_data")
        claims["replay"] = _text(replay.get("best_counterfactual_pattern") or replay.get("most_common_missed_improvement"), "insufficient_data")
        claims["archetype_regime"] = _text(archetype.get("current_best_supported_archetype") or archetype.get("best_archetype"), "insufficient_data")
        claims["profit_capture"] = _text(profit.get("profit_capture_recommendation"), "insufficient_data")
        normalized: dict[str, str] = {}
        for system, claim in claims.items():
            low = claim.lower()
            if any(token in low for token in ("scalp", "protect", "fade", "giveback", "earlier", "decay")):
                normalized[system] = "protect_profit_or_shorter_horizon"
            elif any(token in low for token in ("hold", "runner", "continuation", "longer", "swing")):
                normalized[system] = "hold_longer_or_continuation"
            elif "insufficient" in low or not low:
                normalized[system] = "insufficient_data"
            else:
                normalized[system] = low[:48]
        counts = Counter(v for v in normalized.values() if v != "insufficient_data")
        strongest = _counter_best(counts)
        agreeing = [system for system, claim in normalized.items() if claim == strongest]
        disagreement = [system for system, claim in normalized.items() if claim not in {strongest, "insufficient_data"}]
        score = _clamp((len(agreeing) / max(1, len([v for v in normalized.values() if v != "insufficient_data"]))) * 100.0)
        conflict = bool(strongest != "insufficient_data" and disagreement)
        conflict_type = "profit_protection_vs_hold_patience" if {"protect_profit_or_shorter_horizon", "hold_longer_or_continuation"}.issubset(set(normalized.values())) else "mixed_learning_signals" if conflict else "none"
        severity = "medium" if conflict and score < 67.0 else "low" if conflict else "none"
        return {
            "strongest_cross_system_agreement": strongest,
            "agreement_score": _round(score, 2),
            "agreeing_systems": agreeing,
            "disagreement_systems": disagreement,
            "confidence_boost_reason": f"{len(agreeing)} systems align on {strongest.replace('_', ' ')}." if agreeing else "No strong cross-system agreement yet.",
            "cross_learning_summary": f"Agreement={strongest}; conflicts={', '.join(disagreement) if disagreement else 'none'}.",
            "conflict_detected": conflict,
            "conflict_type": conflict_type,
            "conflicting_systems": disagreement,
            "conflict_severity": severity,
            "likely_resolution": "keep_recommendations_shadow_only_until_more_broker_confirmed_outcomes" if conflict else "no_resolution_needed",
            "recommended_human_review": bool(conflict),
        }

    def _meta_learning(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        system_scores = {
            "lifecycle_evidence": min(100.0, len(rows["lifecycle"]) * 0.8),
            "profit_capture_intelligence": _to_float((statuses.get("adaptive_profit_capture") or {}).get("profit_capture_quality_score"), 0.0),
            "adaptive_execution_exit_v3": _to_float((statuses.get("adaptive_execution_exit_intelligence_v3") or {}).get("profit_capture_score"), 0.0),
            "exit_learning_expansion": max(_to_float((statuses.get("exit_learning_expansion_suite_v1") or {}).get("protect_profit_score"), 0.0), _to_float((statuses.get("exit_learning_expansion_suite_v1") or {}).get("hold_longer_score"), 0.0)),
            "market_context_learning": _to_float((statuses.get("market_context_learning_suite_v1") or {}).get("context_confidence"), 0.0),
            "replay_counterfactual": _to_float((statuses.get("replay_counterfactual_learning_v2") or {}).get("replay_learning_score"), 0.0),
            "opportunity_cost_learning": _to_float((statuses.get("opportunity_cost_learning") or {}).get("selection_quality_score"), 0.0),
            "archetype_regime_learning": _to_float((statuses.get("trade_archetype_regime") or {}).get("current_archetype_regime_alignment_score"), 0.0),
            "confidence_calibration_attribution": _to_float((statuses.get("confidence_calibration_performance_attribution_v1") or {}).get("confidence_calibration_score"), 0.0),
            "context_evidence_expansion": _to_float((statuses.get("context_evidence_expansion_suite_v1") or {}).get("catalyst_coverage_score"), 0.0),
            "catalyst_theme_narrative_capital_flow": _to_float((statuses.get("catalyst_theme_narrative_capital_flow_intelligence_v2") or {}).get("catalyst_truth_score"), 0.0),
        }
        meaningful = {k: v for k, v in system_scores.items() if v > 0}
        most = max(meaningful.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        least = min(meaningful.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        score = _avg(list(meaningful.values())) or 0.0
        adjustments = {k: "maintain_shadow_weight" for k in system_scores}
        if least != "insufficient_data":
            adjustments[least] = "collect_more_validation_before_trusting"
        if most != "insufficient_data":
            adjustments[most] = "prioritize_as_reference_signal_shadow_only"
        return {
            "most_predictive_learning_system": most,
            "least_predictive_learning_system": least,
            "meta_learning_score": _round(score, 2),
            "system_reliability_map": {k: round(v, 2) for k, v in system_scores.items()},
            "recommended_learning_weight_adjustments": adjustments,
            "meta_learning_confidence": _clamp(30.0 + len(meaningful) * 7.0),
        }

    def _consolidation(self, all_rows: list[dict[str, Any]], priority: dict[str, Any], agreement: dict[str, Any]) -> dict[str, Any]:
        lessons: list[str] = []
        top = _text(priority.get("top_learning_priority"), "insufficient_evidence")
        if top != "insufficient_evidence":
            lessons.append(f"Prioritize {top.replace('_', ' ')} until evidence pressure declines.")
        if agreement.get("strongest_cross_system_agreement") not in (None, "", "insufficient_data"):
            lessons.append(f"Cross-system agreement favors {str(agreement.get('strongest_cross_system_agreement')).replace('_', ' ')}.")
        personalities = Counter(_text(r.get("trade_personality"), "unknown") for r in all_rows if _text(r.get("trade_personality"), "unknown") != "unknown")
        if personalities:
            lessons.append(f"Most repeated trade personality is {_counter_best(personalities).replace('_', ' ')}.")
        promoted = lessons[:5]
        tentative = ["Context and replay signals remain shadow-only until more broker-confirmed closes accumulate."]
        retired = ["One-off low-evidence findings are deprioritized automatically."] if all_rows else []
        score = _clamp(35.0 + len(promoted) * 12.0 + min(25.0, len(all_rows) * 0.05))
        return {
            "consolidated_lessons_count": len(promoted) + len(tentative),
            "promoted_lessons": promoted,
            "tentative_lessons": tentative,
            "retired_or_deprioritized_lessons": retired,
            "strongest_new_lesson": promoted[0] if promoted else "insufficient_evidence",
            "overnight_consolidation_status": "ready_for_background_worker" if promoted else "warming_up",
            "knowledge_retention_score": _round(score, 2),
        }

    def _write_summary(self, out: dict[str, Any]) -> None:
        now = time.time()
        if now - self._last_write < 90.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            row = {k: out.get(k) for k in (
                "generated_at", "evidence_count", "top_learning_priority", "weighted_confidence_score",
                "knowledge_retention_score", "coverage_score", "agreement_score", "conflict_detected",
                "meta_learning_score", "strongest_new_lesson", "recommended_worker_focus",
            )}
            with open(self.state_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        status_map = {k: dict(v) for k, v in dict(statuses or {}).items() if isinstance(v, dict)}
        rows = self._collect_rows()
        all_rows = [row for values in rows.values() for row in values]
        evidence_mix = self._evidence_mix(rows, status_map)
        weighted_total = sum(EVIDENCE_WEIGHTS[k] * min(1.0, count / 25.0) for k, count in evidence_mix.items())
        max_total = sum(EVIDENCE_WEIGHTS.values())
        weighted_confidence = _clamp(weighted_total / max(1.0, max_total) * 100.0)
        strongest_source = max(evidence_mix.items(), key=lambda item: EVIDENCE_WEIGHTS[item[0]] * min(1.0, item[1] / 25.0), default=("insufficient_data", 0))[0]
        weakest_source = min(evidence_mix.items(), key=lambda item: item[1], default=("insufficient_data", 0))[0]
        quality_label = "strong_evidence_mix" if weighted_confidence >= 70 else "developing_evidence_mix" if weighted_confidence >= 45 else "warming_up"
        priority = self._priority(rows, status_map)
        coverage = self._coverage(all_rows, status_map)
        agreement = self._agreement_conflict(status_map)
        meta = self._meta_learning(rows, status_map)
        consolidation = self._consolidation(all_rows, priority, agreement)
        conflict = bool(agreement.get("conflict_detected"))
        recommendation = (
            f"Shadow-only: focus workers on {priority['recommended_worker_focus'].replace('_', ' ')}; "
            f"trust {strongest_source.replace('_', ' ')} most; keep behavior unchanged."
        )
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_learning_acceleration_retention",
            "generated_at": _now_iso(),
            "evidence_count": sum(evidence_mix.values()),
            "top_learning_priority": priority["top_learning_priority"],
            "secondary_learning_priority": priority["secondary_learning_priority"],
            "lowest_learning_priority": priority["lowest_learning_priority"],
            "priority_reason": priority["priority_reason"],
            "priority_confidence": _round(priority["priority_confidence"], 2),
            "recommended_worker_focus": priority["recommended_worker_focus"],
            "priority_scores": priority["scores"],
            "weighted_confidence_score": _round(weighted_confidence, 2),
            "strongest_evidence_source": strongest_source,
            "weakest_evidence_source": weakest_source,
            "evidence_mix": evidence_mix,
            "evidence_quality_label": quality_label,
            "evidence_weighting_reason": "Broker-confirmed and lifecycle evidence receive the most trust; replay, opportunity cost, context, and simulation evidence remain useful but lower-weighted.",
            **consolidation,
            **coverage,
            **agreement,
            **meta,
            "shadow_learning_recommendation": recommendation,
            "future_worker_contract": {
                "adaptive_background_worker_foundation_v1_ready": True,
                "learning_orchestrator_v1_ready": True,
                "persona_learning_expansion_v1_ready": True,
                "open_trade_learning_v1_ready": True,
                "rejected_candidate_learning_expansion_v1_ready": True,
                "required_fields": ["top_learning_priority", "recommended_worker_focus", "evidence_mix", "conflict_detected", "behavior_safe_to_apply"],
            },
            "behavior_safe_to_apply": False,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "thresholds_changed": False,
            "position_sizing_changed": False,
        }
        self._write_summary(out)
        self._cache = dict(out)
        self._cache_ts = now
        return out
