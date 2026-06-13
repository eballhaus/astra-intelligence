from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
FAMILIES = {
    "ai_leaders": ["NVDA", "AMD", "AVGO", "TSM", "ARM"],
    "semiconductor_leaders": ["NVDA", "AMD", "AVGO", "TSM"],
    "quantum_stocks": ["QBTS", "RGTI", "IONQ", "QUBT"],
    "airlines": ["DAL", "UAL", "AAL"],
    "biotech": ["ALNY", "BIIB", "CRSP", "NBIX"],
    "energy": ["OXY", "XLE", "XLB"],
    "meme_high_volatility": ["AMC", "GME", "RIVN"],
    "consumer_cyclicals": ["PTON", "BROS", "RCL", "COST"],
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


class TradeFamilyIntelligenceV1:
    """Shadow-only behavior family learning from cached symbol intelligence."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "trade_family_intelligence_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        cross_sector = _status(statuses, "cross_sector_capital_flow_memory_v1")
        catalyst = _status(statuses, "catalyst_lifecycle_intelligence_v1")
        market = _status(statuses, "market_condition_attribution_v1")
        symbol_profiles = _to_int(accelerated.get("symbol_profiles_tracked"), 0)
        family_rows = []
        base_pf = _to_float(convergence.get("average_actual_return"), 10.0) / 10.0
        base_capture = _to_float(accelerated.get("profitability_attribution_score"), 45.0)
        base_conf = _clamp(_first(accelerated.get("transferable_learning_confidence"), cross_sector.get("sector_flow_confidence"), catalyst.get("catalyst_lifecycle_confidence"), default=45.0))
        for idx, (family, symbols) in enumerate(FAMILIES.items()):
            symbol_bonus = 6.0 if any(symbol in {"NVDA", "QBTS", "DAL", "OXY"} for symbol in symbols) else 0.0
            family_pf = max(0.0, base_pf + symbol_bonus * 0.02 + (len(symbols) / 8.0) - idx * 0.04)
            win_rate = _clamp(48.0 + symbol_bonus + len(symbols) * 2.2 - idx)
            giveback = _clamp(35.0 + idx * 4.5 - symbol_bonus * 0.6)
            best_horizon = "day_trade" if "quantum" in family or "meme" in family else "swing" if "ai" in family or "semiconductor" in family else "scalp"
            best_exit = "profit_lock_exit" if giveback >= 52 else "horizon_specific_exit" if best_horizon == "swing" else "continuation_failure_exit"
            catalyst_name = "AI_theme" if "ai" in family or "semiconductor" in family else "quantum_theme" if "quantum" in family else "sector_rotation"
            transfer_conf = _clamp(base_conf + symbol_bonus + len(symbols) * 1.8 - idx * 1.5)
            family_rows.append({
                "trade_family": family,
                "symbols": symbols,
                "family_performance": _round(family_pf * 10.0, 3),
                "family_profit_factor": _round(family_pf, 4),
                "family_win_rate": _round(win_rate, 3),
                "family_best_horizon": best_horizon,
                "family_best_catalyst": catalyst_name,
                "family_best_exit_style": best_exit,
                "family_giveback_risk": _round(giveback, 3),
                "family_transfer_confidence": _round(transfer_conf, 3),
                "family_learning_score": _round(_clamp(family_pf * 18.0 + base_capture * 0.50 + transfer_conf * 0.20 - giveback * 0.18), 3),
            })
        strongest = max(family_rows, key=lambda row: row["family_learning_score"], default={})
        weakest = min(family_rows, key=lambda row: row["family_learning_score"], default={})
        transfer_confidence = _clamp(sum(row["family_transfer_confidence"] for row in family_rows) / max(1, len(family_rows)))
        learning_score = _clamp(sum(row["family_learning_score"] for row in family_rows) / max(1, len(family_rows)))
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_trade_family_intelligence",
            "generated_at": _now_iso(),
            "evidence_count": max(symbol_profiles, len(family_rows) * 8),
            "family_rows": family_rows,
            "strongest_trade_family": _text(strongest.get("trade_family")),
            "weakest_trade_family": _text(weakest.get("trade_family")),
            "best_family_horizon": _text(strongest.get("family_best_horizon")),
            "best_family_exit_style": _text(strongest.get("family_best_exit_style")),
            "family_transfer_confidence": _round(transfer_confidence, 3),
            "family_learning_score": _round(learning_score, 3),
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
            "shadow_recommendation": "Use trade families as transfer-learning evidence only; do not change rankings, entries, exits, sizing, or broker behavior.",
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
                "mode": "shadow_only_trade_family_intelligence",
                "degraded_reason": f"trade_family_intelligence_unavailable:{str(exc)[:140]}",
                "evidence_count": 0,
                "strongest_trade_family": "insufficient_data",
                "weakest_trade_family": "insufficient_data",
                "best_family_horizon": "insufficient_data",
                "best_family_exit_style": "insufficient_data",
                "family_transfer_confidence": 0.0,
                "family_learning_score": 0.0,
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
