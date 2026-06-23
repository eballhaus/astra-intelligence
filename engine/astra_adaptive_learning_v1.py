from __future__ import annotations

import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_ROWS = 2200
MAX_TAIL_BYTES = 2_500_000
CACHE_TTL_SECONDS = 20.0
ELIGIBLE_PROMOTION_METRICS = [
    "Profit Factor",
    "Win Rate",
    "Average Return",
    "Profit Capture",
    "Exit Quality",
    "Giveback Reduction",
    "Horizon Accuracy",
    "Risk Adjusted Returns",
    "Regime Stability",
]


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


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _avg(values: list[float], default: float = 0.0) -> float:
    vals = [float(v) for v in values if math.isfinite(float(v))]
    return round(mean(vals), 4) if vals else float(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _text(value: Any, default: str = "insufficient_evidence") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


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


def _safe_flags(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "behavior_safe_to_apply": False,
        "broker_execution_added": False,
        "automatic_entries_enabled": False,
        "automatic_exits_enabled": False,
        "automatic_sizing_enabled": False,
        "automatic_allocations_enabled": False,
        "automatic_promotions_enabled": False,
        "automatic_threshold_changes_enabled": False,
        "automatic_horizon_changes_enabled": False,
        "automatic_confidence_changes_enabled": False,
        "autonomous_trading_enabled": False,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "advisory_only": True,
        "recommendation_only": True,
        "human_review_required": True,
        "cache_first": True,
        "live_trading_changed": False,
        "paper_execution_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "allocation_behavior_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "shadow_logic_changed": False,
        "shadow_execution_behavior_changed": False,
        "aios_behavior_changed": False,
        "provider_ownership_changed": False,
        "provider_polling_frequency_changed": False,
        "dashboard_endpoint_storm_created": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }
    out.update(extra or {})
    return out


def _tail_jsonl(path: Path, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            raw = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = raw.splitlines()
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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("summary"), dict):
        merged = dict(payload.get("summary") or {})
        merged.update({k: v for k, v in payload.items() if k != "summary"})
        return merged
    return dict(payload or {})


def _profit_factor(values: list[float]) -> float | None:
    vals = [v for v in values if abs(v) > 1e-9]
    if not vals:
        return None
    gains = sum(v for v in vals if v > 0)
    losses = abs(sum(v for v in vals if v < 0))
    if losses <= 0:
        return round(gains, 4) if gains > 0 else 0.0
    return round(gains / losses, 4)


class AstraAdaptiveLearningV1:
    """Controlled evolution diagnostics for replay, suppression, learning speed, and shadow promotion.

    All outputs are recommendation-only. This module reads bounded local/cache
    evidence and never changes trading behavior, broker behavior, ranking,
    entries, exits, sizing, allocation, thresholds, AIOS, providers, or Shadow
    execution behavior.
    """

    module_name = "astra_adaptive_learning_v1"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = Path(state_dir or "state")
        self.cache_dir = self.state_dir / "dashboard_cache"
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _statuses(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for path in self.cache_dir.glob("*.json"):
            out[path.stem] = _unwrap(_read_json(path))
        return out

    def _replay_rows(self) -> list[dict[str, Any]]:
        return _tail_jsonl(self.state_dir / "replay_counterfactual_learning_v2.jsonl")

    def _suppression_rows(self) -> list[dict[str, Any]]:
        return _tail_jsonl(self.state_dir / "execution_suppression_audit_v1.jsonl") + _tail_jsonl(self.state_dir / "candidate_decision_ledger_v1.jsonl", max_rows=900, max_bytes=1_500_000)

    def _learning_rows(self) -> list[dict[str, Any]]:
        return _tail_jsonl(self.state_dir / "learning_acceleration_retention_suite_v1.jsonl", max_rows=900, max_bytes=1_200_000)

    def _replay_expansion(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        completed = [r for r in rows if r.get("best_counterfactual_path")]
        decisions = Counter()
        deltas: list[float] = []
        confidences: list[float] = []
        for row in completed:
            path = _text(row.get("best_counterfactual_path"), "unknown")
            improvement = _to_float(row.get("improvement_vs_actual"), _to_float(row.get("best_counterfactual_return")) - _to_float(row.get("actual_return_pct")))
            confidence = _to_float(row.get("counterfactual_confidence"), row.get("replay_quality_score"))
            deltas.append(improvement)
            confidences.append(confidence)
            if path in {"held_longer", "longer_hold", "swing_hold"}:
                decisions["would_hold_longer"] += 1
            if path in {"exited_at_mfe", "exited_after_giveback_threshold", "exited_earlier", "exited_on_momentum_decay", "shorter_hold"}:
                decisions["would_exit_earlier"] += 1
                decisions["would_improve_profit_capture"] += 1
            if path in {"exited_after_giveback_threshold", "exited_at_mfe"}:
                decisions["would_scale_out"] += 1
            if path == "avoided_entry":
                decisions["would_skip_trade"] += 1
                decisions["would_reduce_confidence"] += 1
            if improvement >= 1:
                decisions["would_increase_confidence"] += 1
            if path in {"scalp_hold", "day_trade_hold", "swing_hold"}:
                decisions["would_change_horizon"] += 1
            if improvement > 0 and _to_float(row.get("worst_counterfactual_return"), 0) > _to_float(row.get("actual_return_pct"), 0):
                decisions["would_reduce_risk"] += 1
            if path in {"entered_later", "waited_for_confirmation"}:
                decisions["would_delay_entry"] += 1
        count = len(completed)
        positive = sum(1 for v in deltas if v > 0)
        return {
            "status": "ok" if count else "insufficient_evidence",
            "replay_expansion_v1": True,
            "replay_count": count,
            "replay_accuracy": _round((positive / max(1, count)) * 100.0, 3),
            "replay_confidence": _round(_avg(confidences), 3),
            "replay_profit_delta": _round(_avg(deltas), 4),
            "replay_improvement_score": _round(_clamp(_avg(deltas) * 18.0 + _avg(confidences) * 0.45), 3),
            "would_hold_longer": decisions.get("would_hold_longer", 0),
            "would_exit_earlier": decisions.get("would_exit_earlier", 0),
            "would_scale_out": decisions.get("would_scale_out", 0),
            "would_skip_trade": decisions.get("would_skip_trade", 0),
            "would_increase_confidence": decisions.get("would_increase_confidence", 0),
            "would_reduce_confidence": decisions.get("would_reduce_confidence", 0),
            "would_change_horizon": decisions.get("would_change_horizon", 0),
            "would_reduce_risk": decisions.get("would_reduce_risk", 0),
            "would_delay_entry": decisions.get("would_delay_entry", 0),
            "would_improve_profit_capture": decisions.get("would_improve_profit_capture", 0),
            "top_replay_lesson": decisions.most_common(1)[0][0] if decisions else "insufficient_evidence",
        }

    def _suppression_detector(self, rows: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        seen = len(rows)
        rejected = 0
        promoted = 0
        later_success = 0
        missed = 0
        reasons = Counter({
            "observation_too_strict": 0,
            "confidence_too_strict": 0,
            "horizon_too_strict": 0,
            "risk_too_strict": 0,
            "catalyst_too_strict": 0,
            "sector_too_strict": 0,
        })
        for row in rows:
            rejected_flag = bool(row.get("eligible") is False or row.get("order_submitted") is False or row.get("was_released") is False or row.get("final_execution_decision") in {"suppressed", "rejected", "attempted_rejected"})
            if rejected_flag:
                rejected += 1
            if bool(row.get("selected") or row.get("was_paper_ready") or row.get("promoted_status") == "promoted"):
                promoted += 1
            missed_flag = bool(row.get("missed_better_candidate_flag")) or _to_float(row.get("opportunity_cost_pct")) > 0.35
            if missed_flag:
                missed += 1
            if missed_flag and rejected_flag:
                later_success += 1
            reason = " ".join(str(row.get(k) or "") for k in ("rejection_reason", "suppression_reason", "rejection_stage", "signal_quality_decision", "confirmation_path_final_decision")).lower()
            if "confidence" in reason or "grade" in reason:
                reasons["confidence_too_strict"] += 1
            if "horizon" in reason or "session" in reason or "timing" in reason:
                reasons["horizon_too_strict"] += 1
            if "risk" in reason or "market" in reason or "portfolio" in reason or "concentration" in reason or "correlation" in reason:
                reasons["risk_too_strict"] += 1
            if "catalyst" in reason or "news" in reason:
                reasons["catalyst_too_strict"] += 1
            if "sector" in reason or "theme" in reason:
                reasons["sector_too_strict"] += 1
            if "exploration" in reason or "observation" in reason or "signal" in reason or "entry" in reason:
                reasons["observation_too_strict"] += 1
        suppression_score = (rejected / max(1, seen)) * 100.0
        missed_risk = (missed / max(1, rejected)) * 100.0 if rejected else 0.0
        health = _clamp(100.0 - suppression_score * 0.35 - missed_risk * 0.55)
        if seen == 0:
            warning = "evidence_starvation"
        elif missed_risk > 35:
            warning = "missed_opportunity_risk"
        elif suppression_score > 80:
            warning = "overfiltering"
        elif suppression_score > 60:
            warning = "mild_overfiltering"
        else:
            warning = "healthy"
        # Blend in existing participation audit if available, without letting it mutate behavior.
        participation = statuses.get("execution_participation_audit_status_v1") or statuses.get("execution_participation_audit") or {}
        if participation.get("participation_suppression_score") is not None:
            suppression_score = _round(max(suppression_score, _to_float(participation.get("participation_suppression_score"))), 3)
        return {
            "status": "ok" if seen else "insufficient_evidence",
            "suppression_detector_v1": True,
            "candidates_seen": seen,
            "candidates_rejected": rejected,
            "candidates_promoted": promoted,
            "candidates_later_successful": later_success,
            "missed_opportunities": missed,
            "suppression_score": _round(suppression_score, 3),
            "suppression_health_score": _round(health, 3),
            "warning_label": warning,
            "rejection_reasons": dict(reasons),
            "recommended_action": "review_overfiltering_shadow_only_no_filter_relaxation" if warning != "healthy" else "maintain_current_filters_collect_evidence",
        }

    def _learning_accelerator(self, rows: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        latest = rows[-1] if rows else {}
        prev = rows[-25] if len(rows) >= 25 else (rows[0] if rows else {})
        gained = max(0, _to_int(latest.get("evidence_count")) - _to_int(prev.get("evidence_count"))) if latest else 0
        retained = _to_float(latest.get("knowledge_retention_score"), _first((statuses.get("learning_acceleration_retention_suite_v1") or {}).get("knowledge_retention_score"), default=0.0))
        applied = _to_float(latest.get("meta_learning_score"), _first((statuses.get("learning_acceleration_retention_suite_v1") or {}).get("meta_learning_score"), default=0.0))
        agreement = _to_float(latest.get("agreement_score"), 0.0)
        forgotten = max(0.0, 100.0 - retained)
        categories = {
            "entry_learning": _to_float((statuses.get("confidence_calibration_performance_attribution_v1") or {}).get("entry_quality_score"), applied),
            "exit_learning": _to_float((statuses.get("profit_capture_peak_decay_exit_validation_suite_v1") or {}).get("readiness_score"), applied),
            "horizon_learning": _to_float((statuses.get("astra_trading_intelligence_foundation_v1") or {}).get("summary", {}).get("trades_reviewed"), gained),
            "symbol_learning": _to_float((statuses.get("astra_trading_intelligence_foundation_v1") or {}).get("summary", {}).get("symbol_profiles_created"), 0.0),
            "market_learning": _to_float((statuses.get("market_transition_detection_v1") or {}).get("transition_confidence"), applied),
            "portfolio_learning": _to_float((statuses.get("portfolio_diversification_correlation_v2") or {}).get("portfolio_fit_score"), applied),
            "shadow_learning": _to_float((statuses.get("shadow_correction_validation_attribution_v1") or {}).get("confidence_score"), applied),
        }
        return {
            "status": "ok" if latest else "insufficient_evidence",
            "learning_accelerator_v2": True,
            "knowledge_gained": gained,
            "knowledge_retained": _round(retained, 3),
            "knowledge_applied": _round(applied, 3),
            "knowledge_forgotten": _round(forgotten, 3),
            "retention_score": _round(retained, 3),
            "application_score": _round(applied, 3),
            "acceleration_score": _round(_clamp(gained * 0.08 + applied * 0.55 + retained * 0.25 + agreement * 0.12), 3),
            "forgetting_score": _round(forgotten, 3),
            "learning_categories": {k: _round(v, 3) for k, v in categories.items()},
            "top_learning_category": max(categories, key=categories.get) if categories else "insufficient_evidence",
            "weakest_learning_category": min(categories, key=categories.get) if categories else "insufficient_evidence",
            "recommended_learning_focus": _text(latest.get("top_learning_priority") or latest.get("recommended_worker_focus"), "continue_bounded_learning_measurement"),
        }

    def _metric_candidates(self, statuses: dict[str, dict[str, Any]], replay: dict[str, Any], suppression: dict[str, Any], learning: dict[str, Any]) -> list[dict[str, Any]]:
        foundation = statuses.get("astra_trading_intelligence_foundation_v1") or {}
        trading = foundation.get("executive_trading_snapshot_v1") or {}
        lifecycle = foundation.get("trade_lifecycle_intelligence_v1") or {}
        horizon = foundation.get("horizon_intelligence_v2") or {}
        shadow_corr = statuses.get("shadow_correction_validation_attribution_v1") or {}
        perf_attr = statuses.get("shadow_vs_paper_performance_attribution_v1") or {}
        metrics = [
            ("Profit Factor", _to_float(perf_attr.get("profit_factor_delta"), 0.0) * 100.0, _to_int(perf_attr.get("paper_trade_count"), 0) + _to_int(perf_attr.get("shadow_trade_count"), 0), _to_float(perf_attr.get("shadow_alpha_confidence"), 0.0)),
            ("Win Rate", _to_float(perf_attr.get("win_rate_delta"), 0.0), _to_int(perf_attr.get("paper_trade_count"), 0) + _to_int(perf_attr.get("shadow_trade_count"), 0), _to_float(perf_attr.get("shadow_alpha_confidence"), 0.0)),
            ("Average Return", _to_float(perf_attr.get("avg_return_delta"), 0.0), _to_int(perf_attr.get("paper_trade_count"), 0) + _to_int(perf_attr.get("shadow_trade_count"), 0), _to_float(perf_attr.get("shadow_alpha_confidence"), 0.0)),
            ("Profit Capture", max(0.0, _to_float(replay.get("replay_profit_delta"), 0.0) * 10.0), _to_int(replay.get("replay_count"), 0), _to_float(replay.get("replay_confidence"), 0.0)),
            ("Exit Quality", max(0.0, 100.0 - _to_float(lifecycle.get("avg_giveback"), 0.0) * 8.0) - 50.0, _to_int(lifecycle.get("trades_reviewed"), 0), _to_float(trading.get("metric_confidence"), 0.0)),
            ("Giveback Reduction", max(0.0, _to_float(lifecycle.get("avg_giveback"), 0.0) - 5.0) * 3.0, _to_int(lifecycle.get("trades_reviewed"), 0), _to_float(trading.get("metric_confidence"), 0.0)),
            ("Horizon Accuracy", max(0.0, _to_float(horizon.get("horizon_accuracy_score"), 0.0) - 50.0), _to_int(lifecycle.get("trades_reviewed"), 0), _to_float(horizon.get("horizon_confidence"), 0.0)),
            ("Risk Adjusted Returns", _to_float((trading.get("lifecycle_metrics") or {}).get("risk_adjusted_return"), 0.0), _to_int(lifecycle.get("trades_reviewed"), 0), _to_float(trading.get("metric_confidence"), 0.0)),
            ("Regime Stability", max(0.0, _to_float((trading.get("lifecycle_metrics") or {}).get("regime_stability"), 0.0) - 50.0), _to_int(lifecycle.get("trades_reviewed"), 0), _to_float(trading.get("metric_confidence"), 0.0)),
            ("Candidate Ranking", _to_float(shadow_corr.get("validated_improvement_score"), 0.0), _to_int(shadow_corr.get("shadow_recommendations_reviewed"), 0), _to_float(shadow_corr.get("confidence_score"), 0.0)),
        ]
        candidates = []
        for metric, delta, evidence, confidence in metrics:
            stability = _clamp((confidence * 0.55) + min(45.0, evidence / 20.0))
            meaningful = delta >= 10.0 and evidence >= 25 and stability >= 55.0 and confidence >= 55.0
            if evidence <= 0:
                status = "insufficient_evidence"
            elif meaningful and confidence >= 70 and stability >= 70:
                status = "ready_for_review"
            elif meaningful:
                status = "candidate"
            else:
                status = "not_ready"
            candidates.append({
                "promotion_candidate": bool(meaningful),
                "promotion_metric": metric,
                "promotion_delta": _round(delta, 3),
                "promotion_confidence": _round(confidence, 3),
                "promotion_evidence": int(evidence),
                "promotion_stability": _round(stability, 3),
                "promotion_status": status,
                "promotion_reason": "single_metric_shadow_improvement_ready_for_human_review" if meaningful else "below_10pct_or_insufficient_evidence_stability_confidence",
            })
        return sorted(candidates, key=lambda r: (r["promotion_candidate"], r["promotion_delta"], r["promotion_confidence"]), reverse=True)

    def _promotion_engine(self, statuses: dict[str, dict[str, Any]], replay: dict[str, Any], suppression: dict[str, Any], learning: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        ranked = self._metric_candidates(statuses, replay, suppression, learning)
        selected = ranked[:1] if ranked and ranked[0].get("promotion_candidate") else []
        all_candidates = [r for r in ranked if r.get("promotion_candidate")]
        engine = {
            "status": "candidate" if selected else "not_ready",
            "incremental_shadow_promotion_v1": True,
            "eligible_metrics": ELIGIBLE_PROMOTION_METRICS,
            "promotion_candidates": selected,
            "all_metric_reviews": ranked,
            "promotion_metric": selected[0].get("promotion_metric") if selected else "none",
            "promotion_delta": selected[0].get("promotion_delta") if selected else 0.0,
            "promotion_confidence": selected[0].get("promotion_confidence") if selected else 0.0,
            "promotion_evidence": selected[0].get("promotion_evidence") if selected else 0,
            "promotion_stability": selected[0].get("promotion_stability") if selected else 0.0,
            "promotion_status": selected[0].get("promotion_status") if selected else "not_ready",
            "promotion_reason": selected[0].get("promotion_reason") if selected else "no_single_metric_met_10pct_evidence_stability_gate",
            "pipeline": ["Shadow", "Evidence Validation", "Stability Validation", "Promotion Candidate", "Safe Approval Layer", "Human Review", "Future Adoption"],
            "recommendation_only": True,
        }
        governor = {
            "status": "ok",
            "promotion_governor_v1": True,
            "max_promotion_candidates_per_cycle": 1,
            "multiple_simultaneous_promotions_allowed": False,
            "live_trading_modifications_allowed": False,
            "broker_modifications_allowed": False,
            "promotion_queue": selected,
            "promotion_history": [],
            "promotion_attempts": len(all_candidates),
            "promotion_rejections": max(0, len(ranked) - len(all_candidates)),
            "governor_reason": "one_candidate_per_cycle_recommendation_only",
        }
        return engine, governor

    def _shadow_scorecard(self, statuses: dict[str, dict[str, Any]], promotion: dict[str, Any], replay: dict[str, Any]) -> dict[str, Any]:
        shadow_corr = statuses.get("shadow_correction_validation_attribution_v1") or {}
        foundation = statuses.get("astra_trading_intelligence_foundation_v1") or {}
        weakness = foundation.get("shadow_weakness_detector_v1") or {}
        evidence = _to_int(shadow_corr.get("shadow_recommendations_reviewed"), 0) + _to_int(replay.get("replay_count"), 0)
        confidence = _to_float(shadow_corr.get("confidence_score"), _to_float(replay.get("replay_confidence"), 0.0))
        stability = _to_float(promotion.get("promotion_stability"), 0.0)
        readiness = _clamp(confidence * 0.35 + stability * 0.30 + min(35.0, evidence / 150.0))
        metric_rows = promotion.get("all_metric_reviews") or []
        most_improved = metric_rows[0] if metric_rows else {}
        most_stagnant = sorted(metric_rows, key=lambda r: _to_float(r.get("promotion_delta")))[0] if metric_rows else {}
        return {
            "status": "ok" if evidence else "insufficient_evidence",
            "shadow_performance_scorecard_v2": True,
            "shadow_health": _round(_clamp(readiness), 3),
            "shadow_confidence": _round(confidence, 3),
            "shadow_stability": _round(stability, 3),
            "shadow_evidence": evidence,
            "shadow_readiness": _round(readiness, 3),
            "top_strength": _first(shadow_corr.get("strongest_validated_improvement"), (weakness.get("top_5_shadow_strengths") or [{}])[0].get("area") if weakness.get("top_5_shadow_strengths") else None, default="insufficient_evidence"),
            "top_weakness": _first(weakness.get("dominant_shadow_gap"), "insufficient_evidence"),
            "most_improved_metric": most_improved.get("promotion_metric", "insufficient_evidence"),
            "most_stagnant_metric": most_stagnant.get("promotion_metric", "insufficient_evidence"),
            "recommendation": "review_single_metric_candidate_human_only" if promotion.get("promotion_candidates") else "collect_more_stable_shadow_evidence",
        }

    def status(self, statuses: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache and now - self._cache_ts < self.ttl_seconds:
            return dict(self._cache)
        merged = self._statuses()
        if isinstance(statuses, dict):
            merged.update({k: v for k, v in statuses.items() if isinstance(v, dict)})
        replay = self._replay_expansion(self._replay_rows())
        suppression = self._suppression_detector(self._suppression_rows(), merged)
        learning = self._learning_accelerator(self._learning_rows(), merged)
        promotion, governor = self._promotion_engine(merged, replay, suppression, learning)
        scorecard = self._shadow_scorecard(merged, promotion, replay)
        payload = {
            "ok": True,
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Bundle 3B Adaptive Learning & Controlled Evolution V1",
            "module": self.module_name,
            "status": "ok",
            "mode": "cache_first_recommendation_only_controlled_evolution",
            "replay_expansion_v1": replay,
            "suppression_detector_v1": suppression,
            "learning_accelerator_v2": learning,
            "incremental_shadow_promotion_v1": promotion,
            "promotion_governor_v1": governor,
            "shadow_performance_scorecard_v2": scorecard,
            "summary": {
                "replay_count": replay.get("replay_count", 0),
                "suppression_warning": suppression.get("warning_label", "insufficient_evidence"),
                "acceleration_score": learning.get("acceleration_score", 0),
                "promotion_candidate": bool(promotion.get("promotion_candidates")),
                "promotion_metric": promotion.get("promotion_metric", "none"),
                "shadow_readiness": scorecard.get("shadow_readiness", 0),
                "next_focus": scorecard.get("recommendation", "collect_more_stable_shadow_evidence"),
            },
            "generated_at": _now_iso(),
            **_safe_flags(),
        }
        self._cache = dict(payload)
        self._cache_ts = now
        return payload
