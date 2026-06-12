from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
PROFIT_PROTECTION_INFLUENCE_CAP_PCT = 3.0
MIN_CLOSED_TRADE_EVIDENCE = 50
MIN_SHADOW_VALIDATION_CONFIDENCE = 65.0
MIN_POLICY_READINESS = 40.0
MAX_GIVEBACK_FOR_MATURITY = 8.0


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


def _ratio_to_score(value: Any) -> float:
    ratio = _to_float(value, 0.0)
    if ratio <= 1.25:
        ratio *= 100.0
    return _clamp(ratio)


class ControlledPaperProfitProtectionPilotV1:
    """Paper-only profit-protection readiness and attribution diagnostics.

    The pilot is intentionally advisory. It consumes cached learning summaries,
    performs no provider or broker calls, and never submits or forces exits.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "controlled_paper_profit_protection_pilot_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _base_metrics(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        lifecycle = _status(statuses, "trade_lifecycle_excursion_v2")
        profit_lock = _status(statuses, "profit_lock_profit_capture_maturation_v2")
        catalyst_decay = _status(statuses, "catalyst_persistence_decay_curves_v2")
        replay = _status(statuses, "replay_counterfactual_learning_v2")
        shadow = _status(statuses, "shadow_correction_validation_attribution_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        exit_expansion = _status(statuses, "exit_learning_expansion_suite_v1")
        profit_validation = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        learned_exit = _status(statuses, "controlled_paper_learned_exit_validation_v1")
        multi_horizon = _status(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        catalyst_history = _status(statuses, "catalyst_classification_historical_exit_maturation_suite_v1")

        closed_trade_evidence = max(
            _to_int(lifecycle.get("tracked_closed_trades"), 0),
            _to_int(lifecycle.get("closed_trade_count"), 0),
            _to_int(profit_lock.get("tracked_trades"), 0),
            _to_int(profit_validation.get("tracked_trades"), 0),
            _to_int(exit_expansion.get("tracked_trades"), 0),
            _to_int(replay.get("tracked_lifecycles"), 0),
        )
        capture_ratio = _first(
            profit_lock.get("average_capture_ratio"),
            profit_validation.get("average_capture_ratio"),
            lifecycle.get("average_profit_capture_ratio"),
            learned_exit.get("baseline_capture_ratio"),
            default=0.0,
        )
        profit_capture_score = _clamp(_first(
            profit_lock.get("profit_capture_maturity_score"),
            profit_validation.get("capture_quality_score"),
            _ratio_to_score(capture_ratio),
            default=0.0,
        ))
        giveback_rate = max(0.0, _to_float(_first(
            profit_lock.get("average_giveback_pct"),
            profit_validation.get("average_giveback_pct"),
            lifecycle.get("average_profit_giveback_pct"),
            learned_exit.get("baseline_giveback"),
            default=0.0,
        )))
        shadow_validation_confidence = _clamp(_first(
            shadow.get("confidence_score"),
            shadow.get("validated_improvement_score"),
            default=0.0,
        ))
        policy_readiness = _clamp(_first(
            profit_lock.get("profit_lock_readiness_score"),
            profit_validation.get("readiness_score"),
            learned_exit.get("validation_confidence"),
            shadow.get("readiness_score"),
            default=0.0,
        ))
        continuation_failure_probability = _clamp(_first(
            profit_validation.get("continuation_failure_probability"),
            profit_lock.get("continuation_failure_learning_score"),
            exit_expansion.get("continuation_failure_probability"),
            multi_horizon.get("horizon_mismatch_risk_score"),
            default=0.0,
        ))
        catalyst_decay_risk = _clamp(_first(
            catalyst_decay.get("catalyst_decay_score"),
            catalyst_decay.get("catalyst_exhaustion_probability"),
            catalyst_history.get("catalyst_decay_learning_score"),
            profit_validation.get("catalyst_decay_exit_value"),
            default=0.0,
        ))
        peak_decay_risk = _clamp(_first(
            profit_validation.get("peak_decay_risk"),
            profit_validation.get("reversal_after_milestone"),
            profit_lock.get("giveback_reduction_score"),
            default=giveback_rate * 6.0,
        ))
        hold_duration_efficiency = _clamp(_first(
            profit_lock.get("hold_duration_learning_score"),
            profit_validation.get("hold_duration_quality_score"),
            exit_expansion.get("hold_duration_quality_score"),
            default=max(0.0, 100.0 - giveback_rate * 4.0),
        ))
        giveback_risk_score = _clamp(giveback_rate * 8.0 + max(0.0, 60.0 - profit_capture_score) * 0.45 + peak_decay_risk * 0.20)
        profit_lock_readiness = _clamp(_first(profit_lock.get("profit_lock_readiness_score"), policy_readiness, default=0.0))
        recommendation_count = max(
            _to_int(shadow.get("validated_recommendations"), 0) + _to_int(shadow.get("rejected_recommendations"), 0),
            _to_int(shadow.get("shadow_recommendations_reviewed"), 0),
            _to_int(profit_validation.get("tracked_trades"), 0),
            _to_int(profit_lock.get("tracked_trades"), 0),
        )
        return {
            "closed_trade_evidence": int(closed_trade_evidence),
            "profit_capture_score": _round(profit_capture_score, 3),
            "giveback_rate": _round(giveback_rate, 4),
            "shadow_validation_confidence": _round(shadow_validation_confidence, 3),
            "policy_readiness": _round(policy_readiness, 3),
            "profit_lock_readiness": _round(profit_lock_readiness, 3),
            "continuation_failure_probability": _round(continuation_failure_probability, 3),
            "catalyst_decay_risk": _round(catalyst_decay_risk, 3),
            "peak_decay_risk": _round(peak_decay_risk, 3),
            "hold_duration_efficiency": _round(hold_duration_efficiency, 3),
            "giveback_risk_score": _round(giveback_risk_score, 3),
            "recommendation_count": int(recommendation_count),
            "most_improved_symbol": _text(_first(
                convergence.get("most_reliable_symbol"),
                accelerated.get("most_reliable_symbol"),
                profit_validation.get("best_capture_trade"),
                default="insufficient_data",
            )),
            "most_improved_archetype": _text(_first(
                multi_horizon.get("strongest_setup_horizon"),
                accelerated.get("strongest_cross_symbol_pattern"),
                default="insufficient_data",
            )),
            "strongest_source_pattern": _text(_first(
                profit_validation.get("strongest_failure_signal"),
                profit_lock.get("best_virtual_profit_lock_model"),
                shadow.get("strongest_validated_improvement"),
                default="profit_lock_after_peak_decay",
            )),
            "weakest_source_pattern": _text(_first(
                profit_validation.get("weakest_policy"),
                shadow.get("weakest_validated_improvement"),
                default="insufficient_data",
            )),
        }

    def _eligibility(self, base: dict[str, Any]) -> tuple[bool, list[str]]:
        blockers: list[str] = []
        if _to_int(base.get("closed_trade_evidence"), 0) < MIN_CLOSED_TRADE_EVIDENCE:
            blockers.append("minimum_closed_trade_evidence_below_50")
        if _to_float(base.get("profit_capture_score"), 0.0) >= 60.0:
            blockers.append("profit_capture_score_not_below_60")
        if _to_float(base.get("giveback_rate"), 0.0) <= MAX_GIVEBACK_FOR_MATURITY:
            blockers.append("giveback_rate_not_above_8pct")
        if _to_float(base.get("shadow_validation_confidence"), 0.0) < MIN_SHADOW_VALIDATION_CONFIDENCE:
            blockers.append("shadow_validation_confidence_below_65")
        if _to_float(base.get("policy_readiness"), 0.0) < MIN_POLICY_READINESS:
            blockers.append("policy_readiness_below_40")
        return (not blockers, blockers)

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        base = self._base_metrics(statuses)
        active, blockers = self._eligibility(base)
        confidence = _clamp(
            _to_float(base.get("shadow_validation_confidence"), 0.0) * 0.40
            + _to_float(base.get("policy_readiness"), 0.0) * 0.25
            + min(100.0, _to_int(base.get("closed_trade_evidence"), 0) * 1.2) * 0.20
            + _to_float(base.get("giveback_risk_score"), 0.0) * 0.15
        )
        readiness = _clamp(
            _to_float(base.get("profit_lock_readiness"), 0.0) * 0.35
            + _to_float(base.get("shadow_validation_confidence"), 0.0) * 0.25
            + max(0.0, 60.0 - _to_float(base.get("profit_capture_score"), 0.0)) * 0.20
            + min(100.0, max(0.0, _to_float(base.get("giveback_rate"), 0.0) - 8.0) * 8.0) * 0.20
        )
        giveback_reduction = _clamp(max(0.0, _to_float(base.get("giveback_rate"), 0.0) - MAX_GIVEBACK_FOR_MATURITY) * 3.2 + _to_float(base.get("giveback_risk_score"), 0.0) * 0.18)
        profit_capture_improvement = _clamp(giveback_reduction * 0.65 + max(0.0, 60.0 - _to_float(base.get("profit_capture_score"), 0.0)) * 0.32)
        expectancy_improvement = _clamp(profit_capture_improvement * 0.45 + _to_float(base.get("continuation_failure_probability"), 0.0) * 0.08)
        recommendation_count = _to_int(base.get("recommendation_count"), 0)
        validation_scale = min(1.0, recommendation_count / max(1.0, float(MIN_CLOSED_TRADE_EVIDENCE)))
        validated_profit_lock_events = int(round(recommendation_count * validation_scale * (confidence / 100.0) * 0.24))
        validated_hold_improvements = int(round(recommendation_count * validation_scale * (readiness / 100.0) * 0.18))
        validated_continuation_failures = int(round(recommendation_count * validation_scale * (_to_float(base.get("continuation_failure_probability"), 0.0) / 100.0) * 0.14))
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_profit_protection_pilot_shadow_validated",
            "generated_at": _now_iso(),
            "profit_protection_active": bool(active),
            "activation_blockers": blockers,
            "minimum_closed_trade_evidence": MIN_CLOSED_TRADE_EVIDENCE,
            "closed_trade_evidence": _to_int(base.get("closed_trade_evidence"), 0),
            "profit_capture_score": _round(base.get("profit_capture_score"), 3),
            "giveback_rate": _round(base.get("giveback_rate"), 4),
            "shadow_validation_confidence": _round(base.get("shadow_validation_confidence"), 3),
            "policy_readiness": _round(base.get("policy_readiness"), 3),
            "profit_protection_influence_cap_pct": PROFIT_PROTECTION_INFLUENCE_CAP_PCT,
            "profit_lock_guidance_influence_pct": PROFIT_PROTECTION_INFLUENCE_CAP_PCT if active else 0.0,
            "exit_review_influence_pct": PROFIT_PROTECTION_INFLUENCE_CAP_PCT if active else 0.0,
            "hold_review_influence_pct": PROFIT_PROTECTION_INFLUENCE_CAP_PCT if active else 0.0,
            "continuation_review_influence_pct": PROFIT_PROTECTION_INFLUENCE_CAP_PCT if active else 0.0,
            "profit_lock_readiness": _round(base.get("profit_lock_readiness"), 3),
            "giveback_risk_score": _round(base.get("giveback_risk_score"), 3),
            "catalyst_decay_risk": _round(base.get("catalyst_decay_risk"), 3),
            "continuation_failure_probability": _round(base.get("continuation_failure_probability"), 3),
            "peak_decay_risk": _round(base.get("peak_decay_risk"), 3),
            "hold_duration_efficiency": _round(base.get("hold_duration_efficiency"), 3),
            "recommendation_count": recommendation_count,
            "validated_profit_lock_events": int(validated_profit_lock_events),
            "validated_hold_improvements": int(validated_hold_improvements),
            "validated_continuation_failures": int(validated_continuation_failures),
            "estimated_giveback_reduction": _round(giveback_reduction, 3),
            "estimated_profit_capture_improvement": _round(profit_capture_improvement, 3),
            "estimated_expectancy_improvement": _round(expectancy_improvement, 3),
            "strongest_profit_protection_pattern": _text(base.get("strongest_source_pattern"), "profit_lock_after_peak_decay"),
            "weakest_profit_protection_pattern": _text(base.get("weakest_source_pattern"), "insufficient_data"),
            "most_improved_symbol": _text(base.get("most_improved_symbol"), "insufficient_data"),
            "most_improved_archetype": _text(base.get("most_improved_archetype"), "insufficient_data"),
            "confidence_score": _round(confidence, 3),
            "readiness_score": _round(readiness, 3),
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "forced_exits_enabled": False,
            "forced_trades_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "portfolio_allocation_changed": False,
            "thresholds_changed": False,
            "behavior_safe_to_apply": False,
            "shadow_recommendation": (
                "Profit-protection advisory influence is eligible inside the capped paper-only review layer; do not place or force exits."
                if active else
                "Keep profit-protection pilot observation-only until evidence, giveback pressure, shadow confidence, and readiness thresholds all pass."
            ),
            "cache_freshness": "fresh",
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
                "mode": "paper_only_profit_protection_pilot_shadow_validated",
                "degraded_reason": f"controlled_paper_profit_protection_pilot_unavailable:{str(exc)[:140]}",
                "profit_protection_active": False,
                "profit_protection_influence_cap_pct": PROFIT_PROTECTION_INFLUENCE_CAP_PCT,
                "profit_lock_readiness": 0.0,
                "giveback_risk_score": 0.0,
                "catalyst_decay_risk": 0.0,
                "continuation_failure_probability": 0.0,
                "hold_duration_efficiency": 0.0,
                "estimated_giveback_reduction": 0.0,
                "estimated_profit_capture_improvement": 0.0,
                "estimated_expectancy_improvement": 0.0,
                "recommendation_count": 0,
                "validated_profit_lock_events": 0,
                "confidence_score": 0.0,
                "readiness_score": 0.0,
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "human_review_required": True,
                "auto_apply_allowed": False,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "forced_exits_enabled": False,
                "forced_trades_enabled": False,
                "partial_sells_enabled": False,
                "automatic_trailing_stops_enabled": False,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "entry_behavior_changed": False,
                "exit_behavior_changed": False,
                "position_sizing_changed": False,
                "portfolio_allocation_changed": False,
                "thresholds_changed": False,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = time.time()
        return out
