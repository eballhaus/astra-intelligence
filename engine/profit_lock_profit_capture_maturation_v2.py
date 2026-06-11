from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "2.0.0"
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


class ProfitLockProfitCaptureMaturationV2:
    """Shadow-only profit-lock and profit-capture maturation diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "profit_lock_profit_capture_maturation_v2.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _base_metrics(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        profit = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        lifecycle = _status(statuses, "trade_lifecycle_excursion_v2")
        adaptive = _status(statuses, "adaptive_profit_capture")
        exit_v3 = _status(statuses, "adaptive_execution_exit_intelligence_v3")
        replay = _status(statuses, "replay_counterfactual_learning_v2")
        exit_expansion = _status(statuses, "exit_learning_expansion_suite_v1")

        tracked = max(
            _to_int(profit.get("tracked_trades"), 0),
            _to_int(lifecycle.get("tracked_closed_trades"), 0),
            _to_int(adaptive.get("tracked_lifecycles"), 0),
            _to_int(replay.get("tracked_lifecycles"), 0),
            _to_int(exit_expansion.get("tracked_trades"), 0),
        )
        capture = _to_float(_first(
            profit.get("average_capture_ratio"),
            lifecycle.get("average_profit_capture_ratio"),
            adaptive.get("average_profit_capture_ratio"),
            exit_v3.get("capture_ratio"),
            default=0.0,
        ))
        if capture > 1.5:
            capture /= 100.0
        giveback = _to_float(_first(
            profit.get("average_giveback_pct"),
            lifecycle.get("average_profit_giveback_pct"),
            adaptive.get("average_profit_giveback_pct"),
            exit_v3.get("avg_giveback"),
            default=0.0,
        ))
        mfe = _to_float(_first(lifecycle.get("average_MFE"), lifecycle.get("average_mfe_pct"), profit.get("shadow_avg_MFE"), default=max(0.5, giveback + 1.0)))
        mae = _to_float(_first(lifecycle.get("average_MAE"), lifecycle.get("average_mae_pct"), profit.get("shadow_avg_MAE"), default=0.0))
        hold_quality = _clamp(_first(profit.get("hold_duration_quality_score"), exit_expansion.get("hold_duration_quality_score"), exit_v3.get("hold_longer_score"), default=0.0))
        continuation_failure = _clamp(_first(profit.get("continuation_failure_probability"), exit_v3.get("peak_decay_risk"), default=0.0))
        policy_conf = _clamp(_first(profit.get("policy_confidence"), profit.get("readiness_score"), exit_v3.get("protect_profit_score"), default=0.0))
        return {
            "tracked_trades": int(tracked),
            "capture_ratio": _clamp(capture, 0.0, 1.25),
            "giveback_pct": max(0.0, giveback),
            "mfe_pct": max(0.0, mfe),
            "mae_pct": max(0.0, mae),
            "hold_duration_learning_score": hold_quality,
            "continuation_failure_learning_score": continuation_failure,
            "policy_confidence": policy_conf,
        }

    def _scenario_models(self, base: dict[str, Any]) -> list[dict[str, Any]]:
        capture = _to_float(base.get("capture_ratio"), 0.0)
        giveback = _to_float(base.get("giveback_pct"), 0.0)
        mfe = max(0.01, _to_float(base.get("mfe_pct"), 1.0))
        continuation = _to_float(base.get("continuation_failure_learning_score"), 0.0)
        confidence = _to_float(base.get("policy_confidence"), 0.0)
        models = [
            ("protect_25", 0.25, 0.88),
            ("protect_50", 0.50, 0.76),
            ("protect_75", 0.75, 0.62),
            ("full_hold", 0.00, 1.00),
            ("partial_profit_protection", 0.45, 0.84),
        ]
        out: list[dict[str, Any]] = []
        for name, protect, continuation_retention in models:
            locked_capture = max(capture, protect)
            giveback_reduction = giveback * protect
            adjusted_giveback = max(0.0, giveback - giveback_reduction)
            upside_penalty = max(0.0, protect - 0.45) * max(0.0, 100.0 - continuation) / 100.0
            profitability_impact = (locked_capture - capture) * mfe - upside_penalty
            scenario_conf = _clamp(confidence * 0.45 + min(100.0, _to_int(base.get("tracked_trades"), 0) * 1.8) * 0.30 + continuation_retention * 100.0 * 0.25)
            out.append({
                "model": name,
                "capture_ratio": _round(locked_capture, 4),
                "giveback_reduction": _round(giveback_reduction, 4),
                "adjusted_giveback_pct": _round(adjusted_giveback, 4),
                "continuation_retention": _round(continuation_retention * 100.0, 3),
                "profitability_impact": _round(profitability_impact, 4),
                "confidence_score": _round(scenario_conf, 3),
            })
        return out

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        base = self._base_metrics(statuses)
        scenarios = self._scenario_models(base)
        best_lock = max(scenarios, key=lambda row: (row["giveback_reduction"], row["confidence_score"]), default={})
        best_capture = max(scenarios, key=lambda row: (row["profitability_impact"], row["capture_ratio"]), default={})
        sample_score = _clamp(_to_int(base.get("tracked_trades"), 0) * 1.8)
        giveback_pressure = _clamp(_to_float(base.get("giveback_pct"), 0.0) * 5.0)
        capture_gap = _clamp((1.0 - _to_float(base.get("capture_ratio"), 0.0)) * 100.0)
        profit_lock_readiness = _clamp(sample_score * 0.25 + capture_gap * 0.30 + giveback_pressure * 0.25 + _to_float(base.get("policy_confidence"), 0.0) * 0.20)
        capture_maturity = _clamp(_to_float(base.get("capture_ratio"), 0.0) * 100.0 * 0.35 + sample_score * 0.25 + _to_float(base.get("policy_confidence"), 0.0) * 0.25 + max(0.0, 100.0 - giveback_pressure) * 0.15)
        giveback_reduction = _clamp(_to_float(best_lock.get("giveback_reduction"), 0.0) * 8.0 + profit_lock_readiness * 0.45)
        improvement = _clamp(_to_float(best_capture.get("profitability_impact"), 0.0) * 20.0 + capture_gap * 0.45 + giveback_pressure * 0.25)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_profit_lock_profit_capture_maturation",
            "generated_at": _now_iso(),
            "tracked_trades": _to_int(base.get("tracked_trades"), 0),
            "average_capture_ratio": _round(base.get("capture_ratio"), 4),
            "average_giveback_pct": _round(base.get("giveback_pct"), 4),
            "average_MFE": _round(base.get("mfe_pct"), 4),
            "average_MAE": _round(base.get("mae_pct"), 4),
            "virtual_profit_lock_scenarios": scenarios,
            "profit_lock_readiness_score": _round(profit_lock_readiness, 3),
            "profit_capture_maturity_score": _round(capture_maturity, 3),
            "giveback_reduction_score": _round(giveback_reduction, 3),
            "continuation_failure_learning_score": _round(base.get("continuation_failure_learning_score"), 3),
            "hold_duration_learning_score": _round(base.get("hold_duration_learning_score"), 3),
            "profit_capture_improvement_potential": _round(improvement, 3),
            "best_virtual_profit_lock_model": _text(best_lock.get("model"), "insufficient_data"),
            "best_virtual_profit_capture_model": _text(best_capture.get("model"), "insufficient_data"),
            "cache_freshness": "fresh",
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
            "ranking_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "behavior_safe_to_apply": False,
            "shadow_recommendation": "Compare virtual profit-lock models against natural exits only; do not apply exit changes without future human-reviewed validation.",
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
                "mode": "shadow_only_profit_lock_profit_capture_maturation",
                "degraded_reason": f"profit_lock_profit_capture_maturation_unavailable:{str(exc)[:140]}",
                "profit_lock_readiness_score": 0.0,
                "profit_capture_maturity_score": 0.0,
                "giveback_reduction_score": 0.0,
                "continuation_failure_learning_score": 0.0,
                "hold_duration_learning_score": 0.0,
                "profit_capture_improvement_potential": 0.0,
                "best_virtual_profit_lock_model": "insufficient_data",
                "best_virtual_profit_capture_model": "insufficient_data",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = now
        return out
