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


class CrossMarketAttributionTransferLearningV1:
    """Attribution-only cross-market relationship learning."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "cross_market_attribution_transfer_learning_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        breadth = _status(statuses, "market_breadth_index_intelligence_v1")
        etf = _status(statuses, "etf_sector_rotation_intelligence_v1")
        crypto = _status(statuses, "crypto_shadow_learning_v1")
        shadow_vs_paper = _status(statuses, "shadow_vs_paper_performance_attribution_v1")
        condition = _status(statuses, "market_condition_attribution_v1")
        catalyst = _status(statuses, "catalyst_lifecycle_intelligence_v1")

        index_signal = _clamp(_to_float(breadth.get("market_support_for_equity_trades"), 50.0))
        etf_signal = _clamp(_to_float(etf.get("sector_rotation_confidence"), 45.0))
        crypto_signal = _clamp(_to_float(crypto.get("crypto_risk_appetite_score"), 45.0))
        risk_appetite = _clamp(_to_float(breadth.get("risk_on_score"), 50.0) * 0.45 + crypto_signal * 0.30 + index_signal * 0.25)
        psychology = _clamp(risk_appetite * 0.42 + _to_float(crypto.get("crypto_momentum_learning_score"), 45.0) * 0.28 + _to_float(breadth.get("breadth_proxy_score"), 50.0) * 0.30)
        speculation = _clamp(_to_float(crypto.get("crypto_volatility_learning_score"), 45.0) * 0.42 + _to_float(breadth.get("volatility_pressure_score"), 45.0) * 0.30 + _to_float(catalyst.get("average_continuation_probability"), 50.0) * 0.28)
        transfer_conf = _clamp(index_signal * 0.25 + etf_signal * 0.25 + crypto_signal * 0.20 + _to_float(condition.get("condition_confidence_score"), 35.0) * 0.15 + _to_float(shadow_vs_paper.get("shadow_alpha_confidence"), 0.0) * 0.15)
        relationships = [
            {"relationship": "indexes_to_stocks", "score": _round(index_signal), "use": "equity_market_support"},
            {"relationship": "etfs_to_stocks", "score": _round(etf_signal), "use": "sector_rotation_context"},
            {"relationship": "crypto_to_stocks", "score": _round(crypto_signal), "use": "risk_appetite_proxy"},
            {"relationship": "vix_to_profit_protection", "score": _round(_to_float(breadth.get("volatility_pressure_score"), 45.0)), "use": "giveback_pressure_context"},
            {"relationship": "qqq_to_growth_ai_continuation", "score": _round(_to_float(breadth.get("market_support_for_growth_trades"), 50.0)), "use": "growth_continuation_context"},
        ]
        strongest = max(relationships, key=lambda row: row["score"], default={})
        weakest = min(relationships, key=lambda row: row["score"], default={})
        alpha_available = transfer_conf >= 70.0 and bool(shadow_vs_paper.get("paper_pf_matches_unified"))
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_cross_market_attribution_transfer_learning",
            "generated_at": _now_iso(),
            "relationship_rows": relationships,
            "cross_market_transfer_confidence": _round(transfer_conf),
            "crypto_to_stock_signal_score": _round(crypto_signal),
            "index_to_stock_signal_score": _round(index_signal),
            "etf_to_stock_signal_score": _round(etf_signal),
            "risk_appetite_transfer_score": _round(risk_appetite),
            "market_psychology_score": _round(psychology),
            "speculation_score": _round(speculation),
            "cross_market_alpha_available": alpha_available,
            "cross_market_alpha_confidence": _round(transfer_conf if alpha_available else 0.0),
            "strongest_cross_market_relationship": _text(strongest.get("relationship")),
            "weakest_cross_market_relationship": _text(weakest.get("relationship")),
            "recommended_cross_market_use": "attribution_only_collect_more_evidence" if not alpha_available else "human_review_context_only",
            **self._safety_fields(breadth, etf, crypto),
            "shadow_recommendation": "Keep cross-market relationships attribution-only until human-reviewed policy readiness exists.",
            "build_ms": _round((time.perf_counter() - start) * 1000.0),
        }
        _write_json(self.cache_path, out)
        return out

    def _safety_fields(self, breadth: dict[str, Any] | None = None, etf: dict[str, Any] | None = None, crypto: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "bandwidth_used_gb": 0.0,
            "bandwidth_budget_status": "cache_only_safe",
            "crypto_scan_symbols_today": _to_float((crypto or {}).get("crypto_scan_symbols_today"), 0.0),
            "crypto_rotating_symbols_today": list((crypto or {}).get("crypto_rotating_symbols_today") or [])[:20],
            "etf_symbols_tracked": list((etf or {}).get("etf_symbols_tracked") or [])[:24],
            "index_symbols_tracked": list((breadth or {}).get("index_symbols_tracked") or [])[:12],
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
                "mode": "shadow_only_cross_market_attribution_transfer_learning",
                "degraded_reason": f"cross_market_attribution_transfer_learning_unavailable:{str(exc)[:140]}",
                "cross_market_transfer_confidence": 0.0,
                "cross_market_alpha_available": False,
                "strongest_cross_market_relationship": "insufficient_data",
                "weakest_cross_market_relationship": "insufficient_data",
                **self._safety_fields(),
                "build_ms": _round((time.perf_counter() - start) * 1000.0),
            }
        self._cache = dict(out)
        self._cache_ts = time.time()
        return out
