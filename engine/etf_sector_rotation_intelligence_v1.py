from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
ETF_UNIVERSE = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLB", "XLU", "XLRE", "XLC", "SMH", "SOXX", "ARKK", "IBB", "XBI", "KRE", "IYT")
SECTOR_MAP = {
    "Technology": ("XLK", "SMH", "SOXX", "ARKK"),
    "Financials": ("XLF", "KRE"),
    "Energy": ("XLE",),
    "Healthcare": ("XLV", "IBB", "XBI"),
    "Industrials": ("XLI", "IYT"),
    "Consumer": ("XLY", "XLP"),
    "Materials": ("XLB",),
    "Utilities": ("XLU",),
    "Real Estate": ("XLRE",),
    "Communications": ("XLC",),
}


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


class EtfSectorRotationIntelligenceV1:
    """Context-only ETF and sector rotation intelligence from cached summaries."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "etf_sector_rotation_intelligence_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        flow = _status(statuses, "cross_sector_capital_flow_memory_v1")
        breadth = _status(statuses, "market_breadth_index_intelligence_v1")
        transition = _status(statuses, "market_transition_detection_v1")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")

        rotation_speed = _clamp(_first(flow.get("rotation_speed"), transition.get("transition_risk_score"), 45.0))
        flow_conf = _clamp(_first(flow.get("sector_flow_confidence"), 45.0))
        market_support = _clamp(_first(breadth.get("market_support_for_equity_trades"), 50.0))
        persistence_base = _clamp(_first(flow.get("flow_persistence"), 50.0))
        decay_base = _clamp(rotation_speed * 0.55 + _clamp(transition.get("transition_risk_score"), 45.0) * 0.45)
        rows: list[dict[str, Any]] = []
        for idx, (sector, etfs) in enumerate(SECTOR_MAP.items()):
            leadership = _clamp(market_support * 0.28 + persistence_base * 0.28 + flow_conf * 0.24 + (len(etfs) * 4.0) - idx * 1.8)
            inflow = _clamp(leadership * 0.62 + persistence_base * 0.38)
            outflow = _clamp(100.0 - inflow + decay_base * 0.18)
            rows.append({
                "sector": sector,
                "etfs": list(etfs),
                "leadership_score": _round(leadership),
                "sector_inflow_score": _round(inflow),
                "sector_outflow_score": _round(outflow),
                "sector_momentum_persistence": _round(_clamp(persistence_base + leadership * 0.12 - idx)),
                "sector_decay_risk": _round(_clamp(decay_base + outflow * 0.10)),
            })
        strongest = max(rows, key=lambda row: row["leadership_score"], default={})
        weakest = min(rows, key=lambda row: row["leadership_score"], default={})
        leadership_map = {row["sector"]: row["leadership_score"] for row in rows}
        support_positions = _clamp(_to_float(strongest.get("leadership_score"), 0.0) * 0.45 + market_support * 0.35 + flow_conf * 0.20)
        context_selection = "favor_leadership_confirmation_only" if support_positions >= 60 else "rotation_context_observation_only"
        context_capture = "watch_sector_decay_for_profit_giveback" if decay_base >= 55 else "sector_support_stable_watch_profit_capture"
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "context_only_etf_sector_rotation_intelligence",
            "generated_at": _now_iso(),
            "etf_symbols_tracked": list(ETF_UNIVERSE),
            "etf_symbol_count": len(ETF_UNIVERSE),
            "sector_rows": rows,
            "strongest_sector": _text(strongest.get("sector")),
            "weakest_sector": _text(weakest.get("sector")),
            "sector_inflow_score": _round(_to_float(strongest.get("sector_inflow_score"), 0.0)),
            "sector_outflow_score": _round(_to_float(weakest.get("sector_outflow_score"), 0.0)),
            "rotation_speed": _round(rotation_speed),
            "sector_momentum_persistence": _round(persistence_base),
            "sector_decay_risk": _round(decay_base),
            "sector_support_for_current_positions": _round(support_positions),
            "etf_leadership_score": _round(_to_float(strongest.get("leadership_score"), 0.0)),
            "sector_rotation_confidence": _round(_clamp(flow_conf * 0.48 + _clamp(accelerated.get("transferable_learning_confidence"), 45.0) * 0.22 + market_support * 0.30)),
            "strongest_sector_rotation": f"{_text(flow.get('strongest_sector_rotation'), _text(strongest.get('sector')))}",
            "weakest_sector_rotation": f"{_text(weakest.get('sector'))}_lagging",
            "sector_leadership_map": leadership_map,
            "sector_rotation_summary": f"{_text(strongest.get('sector'))} leadership with rotation speed {rotation_speed:.1f}",
            "sector_context_for_stock_selection": context_selection,
            "sector_context_for_profit_capture": context_capture,
            **self._safety_fields(),
            "shadow_recommendation": "Use ETF sector rotation as context only; do not trade ETFs or change stock execution.",
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
            "index_symbols_tracked": [],
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
                "mode": "context_only_etf_sector_rotation_intelligence",
                "degraded_reason": f"etf_sector_rotation_intelligence_unavailable:{str(exc)[:140]}",
                "etf_symbols_tracked": list(ETF_UNIVERSE),
                "strongest_sector": "insufficient_data",
                "weakest_sector": "insufficient_data",
                "sector_rotation_confidence": 0.0,
                **self._safety_fields(),
                "build_ms": _round((time.perf_counter() - start) * 1000.0),
            }
        self._cache = dict(out)
        self._cache_ts = time.time()
        return out
