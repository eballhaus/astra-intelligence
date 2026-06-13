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


class MarketTransitionDetectionV1:
    """Shadow-only early market transition warnings from cached diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "market_transition_detection_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        market = _status(statuses, "market_context_learning_suite_v1")
        catalyst_decay = _status(statuses, "catalyst_persistence_decay_curves_v2")
        flow = _status(statuses, "cross_sector_capital_flow_memory_v1")
        profit = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        catalyst_theme = _status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        shadow = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        adaptive = _status(statuses, "adaptive_execution_exit_intelligence_v3")
        thesis = _status(statuses, "trade_thesis_validation_v1")

        evidence = max(
            _to_int(shadow.get("shadow_learning_events"), 0),
            _to_int(catalyst_decay.get("catalysts_tracked"), 0) * 10,
            _to_int(profit.get("tracked_trades"), 0),
            _to_int(thesis.get("evidence_count"), 0),
        )
        leadership_weakening = _clamp(100.0 - _to_float(flow.get("flow_persistence"), 50.0))
        sector_rotation_acceleration = _clamp(_to_float(flow.get("rotation_speed"), 0.0))
        catalyst_decay_acceleration = _clamp(_to_float(catalyst_decay.get("catalyst_decay_confidence"), 0.0))
        continuation_deterioration = _clamp(_to_float(profit.get("continuation_failure_probability"), 0.0))
        profit_capture_deterioration = _clamp(100.0 - _to_float(profit.get("capture_quality_score"), 50.0))
        volatility_regime_shift = _clamp(_first(market.get("volatility_regime_shift_score"), adaptive.get("volatility_shift_score"), default=48.0))
        breadth_weakening = _clamp(_first(catalyst_theme.get("breadth_weakening_score"), market.get("breadth_quality_score"), default=46.0))
        risk_transition = _clamp(_first(market.get("risk_off_transition_score"), catalyst_theme.get("risk_on_risk_off_score"), default=44.0))
        transition_risk = _clamp(
            leadership_weakening * 0.16
            + sector_rotation_acceleration * 0.14
            + catalyst_decay_acceleration * 0.14
            + continuation_deterioration * 0.14
            + profit_capture_deterioration * 0.12
            + volatility_regime_shift * 0.12
            + breadth_weakening * 0.10
            + risk_transition * 0.08
        )
        regime_stability = _clamp(100.0 - transition_risk * 0.88)
        warnings = {
            "leadership_weakening": leadership_weakening,
            "sector_rotation_acceleration": sector_rotation_acceleration,
            "catalyst_decay_acceleration": catalyst_decay_acceleration,
            "continuation_deterioration": continuation_deterioration,
            "profit_capture_deterioration": profit_capture_deterioration,
            "volatility_regime_shift": volatility_regime_shift,
            "breadth_weakening": breadth_weakening,
            "risk_on_risk_off_transition": risk_transition,
        }
        strongest_warning = max(warnings.items(), key=lambda item: item[1])[0]
        current_market_phase = _text(_first(market.get("current_market_phase"), market.get("current_regime"), "transition_watch"))
        likely_next_phase = "risk_off_rotation" if transition_risk >= 68 else "volatile_rotation" if transition_risk >= 52 else "trend_continuation"
        confidence = _clamp(min(100.0, evidence / 12.0) * 0.35 + regime_stability * 0.30 + _to_float(thesis.get("thesis_confidence"), 0.0) * 0.20 + _to_float(flow.get("rotation_confidence"), 0.0) * 0.15)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_market_transition_detection",
            "generated_at": _now_iso(),
            "evidence_count": int(evidence),
            "regime_stability_score": _round(regime_stability, 3),
            "transition_risk_score": _round(transition_risk, 3),
            "transition_confidence": _round(confidence, 3),
            "strongest_transition_warning": strongest_warning,
            "current_market_phase": current_market_phase,
            "likely_next_market_phase": likely_next_phase,
            "transition_warning_rows": [{"warning": key, "score": _round(value, 3)} for key, value in warnings.items()],
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
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
            "shadow_recommendation": "Use market transition warnings for observation-only learning; do not change trades, exits, sizing, or broker behavior.",
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
                "mode": "shadow_only_market_transition_detection",
                "degraded_reason": f"market_transition_detection_unavailable:{str(exc)[:140]}",
                "evidence_count": 0,
                "regime_stability_score": 0.0,
                "transition_risk_score": 0.0,
                "transition_confidence": 0.0,
                "strongest_transition_warning": "insufficient_data",
                "current_market_phase": "insufficient_data",
                "likely_next_market_phase": "insufficient_data",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
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
