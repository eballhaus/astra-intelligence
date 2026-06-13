from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
CONDITIONS = (
    "high_volatility",
    "low_volatility",
    "momentum_continuation",
    "chop_range",
    "risk_on",
    "risk_off",
    "sector_rotation",
    "catalyst_heavy_market",
    "low_catalyst_market",
)


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


class MarketConditionAttributionV1:
    """Shadow-only market condition attribution from cached diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "market_condition_attribution_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        market = _status(statuses, "market_context_learning_suite_v1")
        profit = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        transition = _status(statuses, "market_transition_detection_v1")
        family = _status(statuses, "trade_family_intelligence_v1")
        evidence = max(
            _to_int(profit.get("tracked_trades"), 0),
            _to_int(convergence.get("tracked_trades"), 0),
            _to_int(family.get("evidence_count"), 0),
        )
        base_capture = _clamp(_first(profit.get("capture_quality_score"), 52.0))
        base_exit = _clamp(_first(profit.get("policy_confidence"), 48.0))
        base_horizon_conf = _clamp(_first(convergence.get("horizon_fit_confidence"), 45.0))
        transition_risk = _clamp(_first(transition.get("transition_risk_score"), 50.0))
        rows = []
        for idx, condition in enumerate(CONDITIONS):
            supportive = 12.0 if condition in {"momentum_continuation", "risk_on", "catalyst_heavy_market"} else 0.0
            defensive = 10.0 if condition in {"risk_off", "low_volatility", "chop_range"} else 0.0
            condition_capture = _clamp(base_capture + supportive - defensive * 0.35 - idx * 0.6)
            condition_exit = _clamp(base_exit + supportive * 0.8 - defensive * 0.25 - transition_risk * 0.05)
            horizon = "swing" if condition in {"low_volatility", "risk_on"} else "day_trade" if condition in {"momentum_continuation", "catalyst_heavy_market"} else "scalp"
            weakness_horizon = "scalp" if horizon == "swing" else "swing"
            condition_score = _clamp(condition_capture * 0.42 + condition_exit * 0.28 + base_horizon_conf * 0.20 - transition_risk * 0.10)
            rows.append({
                "market_condition": condition,
                "condition_score": _round(condition_score, 3),
                "best_horizon": horizon,
                "weakest_horizon": weakness_horizon,
                "profit_capture": _round(condition_capture, 3),
                "exit_quality": _round(condition_exit, 3),
                "evidence_count": max(1, int(evidence / max(1, len(CONDITIONS)))),
            })
        best = max(rows, key=lambda row: row["condition_score"], default={})
        weakest = min(rows, key=lambda row: row["condition_score"], default={})
        confidence = _clamp(base_horizon_conf * 0.38 + base_capture * 0.24 + base_exit * 0.20 + min(100.0, evidence / 8.0) * 0.18)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_market_condition_attribution",
            "generated_at": _now_iso(),
            "evidence_count": int(evidence),
            "condition_rows": rows,
            "best_condition": _text(best.get("market_condition")),
            "weakest_condition": _text(weakest.get("market_condition")),
            "best_horizon_by_condition": {row["market_condition"]: row["best_horizon"] for row in rows},
            "weakest_horizon_by_condition": {row["market_condition"]: row["weakest_horizon"] for row in rows},
            "profit_capture_by_condition": {row["market_condition"]: row["profit_capture"] for row in rows},
            "exit_quality_by_condition": {row["market_condition"]: row["exit_quality"] for row in rows},
            "condition_confidence_score": _round(confidence, 3),
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
            "shadow_recommendation": "Use market-condition attribution for learning only; do not change rankings, entries, exits, sizing, or broker behavior.",
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
                "mode": "shadow_only_market_condition_attribution",
                "degraded_reason": f"market_condition_attribution_unavailable:{str(exc)[:140]}",
                "evidence_count": 0,
                "best_condition": "insufficient_data",
                "weakest_condition": "insufficient_data",
                "condition_confidence_score": 0.0,
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
