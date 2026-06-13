from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
INDEX_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA", "VIX", "TLT", "UUP", "HYG", "TQQQ", "SQQQ")


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


def _round(value: Any, digits: int = 3) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


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


class MarketBreadthIndexIntelligenceV1:
    """Context-only market breadth and index intelligence from cached summaries."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "market_breadth_index_intelligence_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        market = _status(statuses, "market_context_learning_suite_v1")
        transition = _status(statuses, "market_transition_detection_v1")
        cross_sector = _status(statuses, "cross_sector_capital_flow_memory_v1")
        catalyst = _status(statuses, "catalyst_lifecycle_intelligence_v1")
        profit = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")

        transition_risk = _clamp(_first(transition.get("transition_risk_score"), 45.0))
        rotation_speed = _clamp(_first(cross_sector.get("rotation_speed"), 40.0))
        catalyst_continuation = _clamp(_first(catalyst.get("average_continuation_probability"), 52.0))
        capture_quality = _clamp(_first(profit.get("capture_quality_score"), 48.0))
        volatility_pressure = _clamp(_first(market.get("volatility_pressure_score"), transition_risk * 0.65 + rotation_speed * 0.25, default=45.0))
        risk_on = _clamp(catalyst_continuation * 0.34 + capture_quality * 0.25 + (100.0 - transition_risk) * 0.26 + (100.0 - volatility_pressure) * 0.15)
        risk_off = _clamp(transition_risk * 0.42 + volatility_pressure * 0.38 + rotation_speed * 0.20)
        index_trend = _clamp(risk_on * 0.56 + (100.0 - risk_off) * 0.24 + catalyst_continuation * 0.20)
        momentum = _clamp(index_trend * 0.52 + catalyst_continuation * 0.28 + capture_quality * 0.20)
        breadth = _clamp(index_trend * 0.38 + risk_on * 0.32 + _clamp(cross_sector.get("flow_persistence"), 48.0) * 0.30)
        health = _clamp(breadth * 0.35 + index_trend * 0.30 + risk_on * 0.20 + (100.0 - volatility_pressure) * 0.15)
        support_equities = _clamp(health * 0.52 + breadth * 0.26 + risk_on * 0.22)
        support_momentum = _clamp(momentum * 0.48 + catalyst_continuation * 0.32 + (100.0 - transition_risk) * 0.20)
        support_small_caps = _clamp(breadth * 0.36 + risk_on * 0.30 + (100.0 - volatility_pressure) * 0.20 + (100.0 - rotation_speed) * 0.14)
        support_growth = _clamp(momentum * 0.42 + risk_on * 0.34 + catalyst_continuation * 0.24)
        rows = [
            {"symbol": "SPY", "signal": _round(health), "role": "broad_market"},
            {"symbol": "QQQ", "signal": _round(support_growth), "role": "growth_support"},
            {"symbol": "IWM", "signal": _round(support_small_caps), "role": "small_cap_support"},
            {"symbol": "DIA", "signal": _round(index_trend), "role": "large_cap_trend"},
            {"symbol": "VIX", "signal": _round(100.0 - volatility_pressure), "role": "volatility_pressure_inverse"},
        ]
        strongest = max(rows, key=lambda row: row["signal"], default={})
        weakest = min(rows, key=lambda row: row["signal"], default={})
        regime = "risk_on_momentum" if risk_on >= 62 and momentum >= 58 else "risk_off_pressure" if risk_off >= 62 else "mixed_rotation"
        confidence = _clamp(min(100.0, _to_int(profit.get("tracked_trades"), 0) / 2.0) * 0.30 + _clamp(cross_sector.get("sector_flow_confidence"), 45.0) * 0.30 + _clamp(transition.get("transition_confidence"), 45.0) * 0.25 + breadth * 0.15)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "context_only_market_breadth_index_intelligence",
            "generated_at": _now_iso(),
            "index_symbols_tracked": list(INDEX_SYMBOLS),
            "index_symbol_count": len(INDEX_SYMBOLS),
            "index_signal_rows": rows,
            "overall_market_health": _round(health),
            "risk_on_score": _round(risk_on),
            "risk_off_score": _round(risk_off),
            "index_trend_strength": _round(index_trend),
            "index_momentum_score": _round(momentum),
            "breadth_proxy_score": _round(breadth),
            "volatility_pressure_score": _round(volatility_pressure),
            "market_transition_risk": _round(transition_risk),
            "market_support_for_equity_trades": _round(support_equities),
            "market_support_for_momentum_trades": _round(support_momentum),
            "market_support_for_small_caps": _round(support_small_caps),
            "market_support_for_growth_trades": _round(support_growth),
            "strongest_index_signal": _text(strongest.get("symbol")),
            "weakest_index_signal": _text(weakest.get("symbol")),
            "current_index_regime": regime,
            "index_confidence_score": _round(confidence),
            "market_breadth_summary": f"{regime} with breadth {breadth:.1f} and volatility pressure {volatility_pressure:.1f}",
            **self._safety_fields(),
            "shadow_recommendation": "Use index and breadth context for diagnostics only; do not trade indexes or ETFs.",
            "build_ms": _round((time.perf_counter() - start) * 1000.0),
        }
        _write_json(self.cache_path, out)
        return out

    def _safety_fields(self) -> dict[str, Any]:
        return {
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "bandwidth_used_gb": 0.0,
            "bandwidth_budget_status": "cache_only_safe",
            "crypto_scan_symbols_today": 0,
            "crypto_rotating_symbols_today": [],
            "etf_symbols_tracked": [],
            "cache_hit_rate": 100.0,
            "provider_budget_safe": True,
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
            "crypto_paper_trading_enabled": False,
            "crypto_live_trading_enabled": False,
            "etf_trading_enabled": False,
            "index_trading_enabled": False,
            "behavior_safe_to_apply": False,
        }

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = _round(now - self._cache_ts)
            out["build_ms"] = _round((time.perf_counter() - start) * 1000.0)
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
                    disk["cache_age_seconds"] = _round(age)
                    disk["build_ms"] = _round((time.perf_counter() - start) * 1000.0)
                    self._cache = dict(disk)
                    self._cache_ts = now - age
                    return disk
        try:
            out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = {
                "enabled": False,
                "version": VERSION,
                "mode": "context_only_market_breadth_index_intelligence",
                "degraded_reason": f"market_breadth_index_intelligence_unavailable:{str(exc)[:140]}",
                "index_symbols_tracked": list(INDEX_SYMBOLS),
                "overall_market_health": 0.0,
                "current_index_regime": "insufficient_data",
                "index_confidence_score": 0.0,
                **self._safety_fields(),
                "build_ms": _round((time.perf_counter() - start) * 1000.0),
            }
        self._cache = dict(out)
        self._cache_ts = time.time()
        return out
