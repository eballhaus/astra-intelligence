"""Conservative provider routing for live quote lookups.

This module intentionally implements a minimal, stable interface expected by
current runtime callers:
- ProviderRouter()
- get_quote(...)
- test_provider_quote(...)
- diagnostics()
"""

from __future__ import annotations

import os
import threading
import time
import json
from datetime import UTC, datetime
from typing import Any

import requests

from api_keys import API_POOLS
from engine.api_call_manager import (
    get_call_permission,
    record_call,
    record_error,
    record_rate_limit,
)


def _alpaca_secret_key() -> str:
    for name in ("APCA_API_SECRET_KEY", "ALPACA_SECRET_KEY", "ALPACA_API_SECRET"):
        value = str(os.getenv(name, "") or "").strip()
        if value:
            return value
    return ""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def _coerce_ts_seconds(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            ts = float(value)
            # Handle common millisecond epochs.
            if ts > 1_000_000_000_000:
                ts = ts / 1000.0
            if ts > 1_000_000_000:
                return ts
            return None
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def _provider_base_confidence(provider: str) -> float:
    p = str(provider or "").upper()
    table = {
        "ALPACA": 0.86,
        "FINNHUB": 0.82,
        "TWELVEDATA": 0.78,
        "EODHD": 0.75,
        "POLYGON": 0.72,
        "ALPHAVANTAGE": 0.66,
        "FMP": 0.80,
        "MORALIS": 0.58,
    }
    return float(table.get(p, 0.55))


_FMP_EFFICIENCY_LEDGER_PATH = os.path.join("state", "fmp_efficiency_ledger_v1.jsonl")
_FMP_EFFICIENCY_MANIFEST_PATH = os.path.join("state", "fmp_efficiency_manifest_v1.json")
_FMP_EFFICIENCY_LOCK = threading.Lock()
_FMP_RECENT_CALLS: dict[tuple[str, str], float] = {}
_FMP_RECENT_CALL_TTL_SECONDS = 90.0
_FMP_LARGE_ENDPOINTS_ALLOW_FLAG = str(os.getenv("ASTRA_FMP_LARGE_ENDPOINTS_ALLOW", "0")).strip().lower() in {"1", "true", "yes", "on"}
_FMP_HISTORICAL_FALLBACK_ENABLED = str(os.getenv("ASTRA_FMP_HISTORICAL_FALLBACK_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
_FMP_SMART_BUDGET_ENABLED = str(os.getenv("ASTRA_FMP_SMART_BUDGET_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
_TEMP_FMP_REST_DISABLED_EXPLICIT = "ASTRA_TEMP_FMP_REST_DISABLED" in os.environ
_FMP_ENDPOINT_POLICY = {
    "small_quote_profile": {"allowed_default": True, "family": "quote_profile"},
    "historical": {"allowed_default": False, "family": "historical"},
    "bulk": {"allowed_default": False, "family": "bulk"},
    "screener": {"allowed_default": False, "family": "screener"},
}


def _fmp_efficiency_default_manifest() -> dict[str, Any]:
    return {
        "enabled": True,
        "total_fmp_calls_tracked": 0,
        "total_cache_hits": 0,
        "total_cache_misses": 0,
        "total_bytes_estimated": 0,
        "bytes_by_endpoint_family": {},
        "calls_by_endpoint_family": {},
        "avg_bytes_per_call": 0.0,
        "best_value_endpoints": [],
        "worst_value_endpoints": [],
        "blocked_due_bandwidth": 0,
        "blocked_due_call_limit": 0,
        "last_updated_at": "",
    }


def _fmp_efficiency_manifest_load() -> dict[str, Any]:
    try:
        with open(_FMP_EFFICIENCY_MANIFEST_PATH, "r", encoding="utf-8") as f:
            obj = json.load(f)
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return _fmp_efficiency_default_manifest()


def _fmp_efficiency_manifest_write(payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_FMP_EFFICIENCY_MANIFEST_PATH) or ".", exist_ok=True)
    tmp = f"{_FMP_EFFICIENCY_MANIFEST_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, _FMP_EFFICIENCY_MANIFEST_PATH)


def _fmp_efficiency_record(row: dict[str, Any]) -> None:
    rec = dict(row or {})
    rec["timestamp"] = str(rec.get("timestamp") or _now_iso())
    rec.setdefault("api_calls_delta", 0)
    rec.setdefault("bandwidth_delta", 0)
    rec.setdefault("provider_governor_allowed", True)
    rec.setdefault("bytes_estimated", 0)
    rec.setdefault("bytes_actual_if_available", 0)
    rec.setdefault("useful_fields_count", 0)
    rec.setdefault("useful_score", 0.0)
    rec.setdefault("endpoint_family", "unknown")
    rec.setdefault("endpoint_path_template", "")
    rec.setdefault("status_code", 0)
    rec.setdefault("ok", False)
    rec.setdefault("cache_hit", False)
    rec.setdefault("blocked_reason", "")
    rec.setdefault("symbol_count", 1)
    rec.setdefault("call_reason", "")
    rec.setdefault("caller_context", "")
    rec.setdefault("ttl_seconds", 0)
    with _FMP_EFFICIENCY_LOCK:
        os.makedirs(os.path.dirname(_FMP_EFFICIENCY_LEDGER_PATH) or ".", exist_ok=True)
        with open(_FMP_EFFICIENCY_LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        manifest = _fmp_efficiency_manifest_load()
        manifest["enabled"] = True
        manifest["total_fmp_calls_tracked"] = int(_to_float(manifest.get("total_fmp_calls_tracked"), 0.0)) + 1
        if bool(rec.get("cache_hit", False)):
            manifest["total_cache_hits"] = int(_to_float(manifest.get("total_cache_hits"), 0.0)) + 1
        else:
            manifest["total_cache_misses"] = int(_to_float(manifest.get("total_cache_misses"), 0.0)) + 1
        bytes_est = int(_to_float(rec.get("bytes_actual_if_available"), _to_float(rec.get("bytes_estimated"), 0.0)))
        manifest["total_bytes_estimated"] = int(_to_float(manifest.get("total_bytes_estimated"), 0.0)) + max(0, bytes_est)
        fam = str(rec.get("endpoint_family") or "unknown")
        fam_calls = dict(manifest.get("calls_by_endpoint_family") or {})
        fam_bytes = dict(manifest.get("bytes_by_endpoint_family") or {})
        fam_calls[fam] = int(_to_float(fam_calls.get(fam), 0.0)) + 1
        fam_bytes[fam] = int(_to_float(fam_bytes.get(fam), 0.0)) + max(0, bytes_est)
        manifest["calls_by_endpoint_family"] = fam_calls
        manifest["bytes_by_endpoint_family"] = fam_bytes
        total_calls = int(_to_float(manifest.get("total_fmp_calls_tracked"), 0.0))
        total_bytes = int(_to_float(manifest.get("total_bytes_estimated"), 0.0))
        manifest["avg_bytes_per_call"] = round(total_bytes / max(1.0, float(total_calls)), 2)
        if str(rec.get("blocked_reason") or "").strip().lower() == "bandwidth_budget":
            manifest["blocked_due_bandwidth"] = int(_to_float(manifest.get("blocked_due_bandwidth"), 0.0)) + 1
        if str(rec.get("blocked_reason") or "").strip().lower() in {"call_limit", "budget_guard_block"}:
            manifest["blocked_due_call_limit"] = int(_to_float(manifest.get("blocked_due_call_limit"), 0.0)) + 1
        endpoint_key = str(rec.get("endpoint_path_template") or "")
        value_score = float(_to_float(rec.get("useful_score"), 0.0))
        if bytes_est > 0:
            value_score = round(value_score / float(bytes_est), 8)
        roll = dict(manifest.get("_endpoint_value_rollup") or {})
        e = dict(roll.get(endpoint_key) or {"n": 0, "v": 0.0})
        e["n"] = int(_to_float(e.get("n"), 0.0)) + 1
        e["v"] = float(_to_float(e.get("v"), 0.0)) + float(value_score)
        roll[endpoint_key] = e
        ranked = []
        for k, vv in roll.items():
            n = max(1, int(_to_float((vv or {}).get("n"), 0.0)))
            avg_v = float(_to_float((vv or {}).get("v"), 0.0)) / float(n)
            ranked.append({"endpoint": str(k), "value_per_byte": round(avg_v, 8), "samples": int(n)})
        ranked.sort(key=lambda x: x["value_per_byte"], reverse=True)
        manifest["best_value_endpoints"] = ranked[:5]
        manifest["worst_value_endpoints"] = list(reversed(ranked[-5:])) if ranked else []
        manifest["last_updated_at"] = _now_iso()
        manifest["_endpoint_value_rollup"] = roll
        _fmp_efficiency_manifest_write(manifest)


def _fmp_endpoint_policy(path_template: str) -> tuple[str, str, bool]:
    p = str(path_template or "").lower()
    if "historical" in p or "historical-price-full" in p:
        policy = "historical"
    elif "screener" in p:
        policy = "screener"
    elif "bulk" in p or "stock/list" in p:
        policy = "bulk"
    else:
        policy = "small_quote_profile"
    family = str((_FMP_ENDPOINT_POLICY.get(policy) or {}).get("family") or "unknown")
    allowed = bool((_FMP_ENDPOINT_POLICY.get(policy) or {}).get("allowed_default", False))
    if policy in {"screener", "bulk"} and not _FMP_LARGE_ENDPOINTS_ALLOW_FLAG:
        allowed = False
    if policy == "historical":
        # This is the bounded worker fallback, not a broad historical scan.
        allowed = bool(_FMP_LARGE_ENDPOINTS_ALLOW_FLAG or _FMP_HISTORICAL_FALLBACK_ENABLED)
    return family, policy, allowed


class ProviderRouter:
    """Minimal quote router with conservative fallback behavior.

    Design choices are intentionally defensive:
    - never raises for quote-fetch path
    - returns stable payload keys expected by caller modules
    - avoids aggressive retry loops under provider pressure
    """

    STOCK_PROVIDER_ORDER = [
        "ALPACA",
        "FINNHUB",
        "POLYGON",
        "TWELVEDATA",
        "ALPHAVANTAGE",
        "EODHD",
        "FMP",
    ]
    CRYPTO_PROVIDER_ORDER = [
        "MORALIS",
        "FINNHUB",
        "POLYGON",
        "TWELVEDATA",
        "ALPHAVANTAGE",
        "FMP",
        "ALPACA",
    ]

    RATE_LIMIT_COOLDOWN_SECONDS = 120

    def __init__(self) -> None:
        self._stock_keys = {
            str(name).upper(): str(key or "") for name, key in (API_POOLS.get("stocks") or [])
        }
        self._crypto_keys = {
            str(name).upper(): str(key or "") for name, key in (API_POOLS.get("crypto") or [])
        }
        self._lock = threading.Lock()
        self._quote_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._request_inflight: dict[str, threading.Event] = {}
        self._request_results: dict[str, tuple[float, tuple[dict[str, Any], int | None, str, float]]] = {}
        self._request_metrics = {
            "requests_submitted": 0,
            "provider_calls_executed": 0,
            "requests_coalesced": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "failed_requests": 0,
            "provider_calls_avoided": 0,
        }
        self._provider_stats: dict[str, dict[str, Any]] = {}
        self._last_cycle_attempt_order: list[str] = []
        self._temp_strategy_enabled = str(os.getenv("ASTRA_TEMP_PROVIDER_STRATEGY_V1", "1")).strip().lower() in {"1", "true", "yes", "on"}
        self._fmp_smart_budget_enabled = bool(_FMP_SMART_BUDGET_ENABLED)
        self._temp_fmp_rest_disabled_explicit = bool(_TEMP_FMP_REST_DISABLED_EXPLICIT)
        self._temp_fmp_rest_disabled = (
            str(os.getenv("ASTRA_TEMP_FMP_REST_DISABLED", "0" if self._fmp_smart_budget_enabled else "1")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self._temp_fmp_ws_monitor_only = str(os.getenv("ASTRA_TEMP_FMP_WEBSOCKET_MONITOR_ONLY", "1")).strip().lower() in {"1", "true", "yes", "on"}
        self._temp_discovery_cache_age = max(
            10.0,
            _to_float(os.getenv("ASTRA_TEMP_DISCOVERY_CACHE_MAX_AGE_SECONDS", "45"), 45.0),
        )
        try:
            self._max_backfill_provider_probes = max(
                0,
                min(2, int(float(os.getenv("ASTRA_PROVIDER_BACKFILL_MAX_PROBES", "1")))),
            )
        except Exception:
            self._max_backfill_provider_probes = 1

    def provider_role_matrix(self) -> dict[str, Any]:
        return {
            "strategy_mode": "temporary_provider_strategy_v1" if self._temp_strategy_enabled else "standard",
            "effective_window": "2-3_weeks",
            "providers": {
                "ALPACA": {
                    "role": ["primary_live_monitoring", "position_tracking", "shortlist_confirmation"],
                    "mode": "active_primary",
                },
                "TWELVEDATA": {
                    "role": ["coverage_expansion", "shortlist_broadening", "backup_quotes"],
                    "mode": "active_secondary",
                },
                "FINNHUB": {
                    "role": ["context_sentiment_helper", "shortlist_quote_backup"],
                    "mode": "active_secondary",
                },
                "EODHD": {
                    "role": ["backup_quote_validation", "shortlist_support"],
                    "mode": "active_backup",
                },
                "ALPHAVANTAGE": {
                    "role": ["low_frequency_backup", "secondary_confirmation"],
                    "mode": "active_limited",
                },
                "POLYGON": {
                    "role": ["quote_backup", "shortlist_support"],
                    "mode": "active_backup",
                },
                "FMP": {
                    "role": ["cache_first_context_refresh", "bounded_smart_budget_rest"],
                    "mode": "smart_budget_rest" if self._fmp_smart_budget_enabled and not self._temp_fmp_rest_disabled else "rest_conserved",
                    "rest_disabled": bool(self._temp_strategy_enabled and self._temp_fmp_rest_disabled),
                    "rest_disable_explicit": bool(self._temp_fmp_rest_disabled_explicit),
                    "smart_budget_enabled": bool(self._fmp_smart_budget_enabled),
                    "websocket_monitor_only": bool(self._temp_fmp_ws_monitor_only),
                },
                "FRED": {
                    "role": ["macro_regime_low_frequency"],
                    "mode": "context_low_frequency",
                },
                "MORALIS": {
                    "role": ["crypto_support_fallback"],
                    "mode": "crypto_support",
                },
            },
        }

    def _key_for(self, provider: str, asset_type: str) -> str:
        p = str(provider or "").upper()
        if asset_type == "crypto" and p in self._crypto_keys:
            return self._crypto_keys.get(p, "")
        return self._stock_keys.get(p, "") or self._crypto_keys.get(p, "")

    def _provider_active(self, provider: str, asset_type: str) -> bool:
        key = self._key_for(provider, asset_type)
        p = str(provider or "").upper()
        if (
            p == "FMP"
            and self._temp_strategy_enabled
            and self._temp_fmp_rest_disabled
        ):
            return False
        return bool(key and not key.startswith("YOUR_"))

    def _provider_in_cooldown(self, provider: str) -> bool:
        p = str(provider or "").upper()
        with self._lock:
            until = _to_float((self._provider_stats.get(p) or {}).get("cooldown_until"), 0.0)
        return until > time.time()

    def _mark_result(self, provider: str, success: bool, latency_ms: float, *, rate_limited: bool = False) -> None:
        p = str(provider or "").upper()
        with self._lock:
            s = self._provider_stats.setdefault(
                p,
                {
                    "calls": 0,
                    "success": 0,
                    "errors": 0,
                    "rate_limits": 0,
                    "avg_latency_ms": 0.0,
                    "cooldown_until": 0.0,
                    "last_error": "",
                    "last_seen_utc": None,
                },
            )
            s["calls"] = int(s.get("calls", 0)) + 1
            if success:
                s["success"] = int(s.get("success", 0)) + 1
            else:
                s["errors"] = int(s.get("errors", 0)) + 1
            prev_lat = _to_float(s.get("avg_latency_ms"), 0.0)
            n = max(1, int(s["calls"]))
            s["avg_latency_ms"] = round(((prev_lat * (n - 1)) + max(0.0, latency_ms)) / n, 4)
            s["last_seen_utc"] = _now_iso()
            if rate_limited:
                s["rate_limits"] = int(s.get("rate_limits", 0)) + 1
                s["cooldown_until"] = max(_to_float(s.get("cooldown_until"), 0.0), time.time() + self.RATE_LIMIT_COOLDOWN_SECONDS)

    def _set_last_error(self, provider: str, error_text: str) -> None:
        p = str(provider or "").upper()
        with self._lock:
            s = self._provider_stats.setdefault(p, {})
            s["last_error"] = str(error_text or "")[:200]

    @staticmethod
    def _is_rate_limited(status_code: int | None, error_text: str) -> bool:
        if int(status_code or 0) == 429:
            return True
        t = str(error_text or "").lower()
        return "rate" in t and "limit" in t

    @staticmethod
    def _fmp_probe_hard_limited() -> bool:
        hard_limit = str(os.getenv("ASTRA_FMP_REST_HARD_LIMIT_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
        skip_probes = str(os.getenv("ASTRA_FMP_SKIP_PROBES_WHEN_LIMITED", "1")).strip().lower() in {"1", "true", "yes", "on"}
        return bool(hard_limit and skip_probes)

    def _effective_provider_order(self, asset_type: str, preferred_providers: list[str] | None = None) -> list[str]:
        at = "crypto" if str(asset_type or "stock").lower() == "crypto" else "stock"
        if self._temp_strategy_enabled:
            default_order = (
                ["MORALIS", "ALPACA", "FINNHUB", "TWELVEDATA", "POLYGON", "ALPHAVANTAGE", "FMP"]
                if at == "crypto"
                else ["ALPACA", "TWELVEDATA", "FINNHUB", "EODHD", "POLYGON", "ALPHAVANTAGE", "FMP"]
            )
        else:
            default_order = list(self.CRYPTO_PROVIDER_ORDER if at == "crypto" else self.STOCK_PROVIDER_ORDER)
        if preferred_providers:
            pref = [str(p).upper() for p in preferred_providers if str(p).strip()]
            merged = []
            for p in pref + default_order:
                if p not in merged:
                    merged.append(p)
            return merged
        return default_order

    @staticmethod
    def _normalize_quote_payload(
        *,
        symbol: str,
        provider: str,
        price: float,
        prev_close: float | None,
        attempted: list[str],
        cache_hit: bool,
        quote_quality: str,
        quote_age_seconds: float,
        data_unavailable_reason: str | None,
        rejection_reason: str | None = None,
        open_price: float | None = None,
        high_price: float | None = None,
        low_price: float | None = None,
        volume: float | None = None,
        change: float | None = None,
        change_percent: float | None = None,
        quote_timestamp: Any | None = None,
        provider_confidence: float | None = None,
        data_quality_score: float | None = None,
        quote_enriched: bool = False,
        quote_enrichment_sources: list[str] | None = None,
        enriched_previous_close_source: str | None = None,
        enriched_volume_source: str | None = None,
        enriched_history_source: str | None = None,
        enriched_signal_ready: bool = False,
        enriched_signal_limitations: list[str] | None = None,
    ) -> dict[str, Any]:
        valid = bool(price > 0)
        now_ts = time.time()
        ts_seconds = _coerce_ts_seconds(quote_timestamp)
        if ts_seconds is None:
            ts_seconds = now_ts
        freshness_seconds = max(0.0, now_ts - ts_seconds)
        ts_iso = datetime.fromtimestamp(ts_seconds, tz=UTC).isoformat().replace("+00:00", "Z")
        prev_close_val = _to_float(prev_close, 0.0) if prev_close is not None else 0.0
        open_val = _to_float(open_price, 0.0) if open_price is not None else 0.0
        high_val = _to_float(high_price, 0.0) if high_price is not None else 0.0
        low_val = _to_float(low_price, 0.0) if low_price is not None else 0.0
        volume_val = _to_float(volume, 0.0) if volume is not None else 0.0
        change_val = _to_float(change, 0.0) if change is not None else 0.0
        change_pct_val = _to_float(change_percent, 0.0) if change_percent is not None else 0.0
        conf = _to_float(provider_confidence, _provider_base_confidence(provider))
        conf = max(0.1, min(0.99, conf))
        if data_quality_score is None:
            field_bonus = 0.0
            if prev_close_val > 0:
                field_bonus += 12.0
            if volume_val > 0:
                field_bonus += 10.0
            if open_val > 0 and high_val > 0 and low_val > 0:
                field_bonus += 8.0
            if change_pct_val != 0.0 or change_val != 0.0:
                field_bonus += 6.0
            freshness_pen = min(18.0, freshness_seconds / 20.0)
            data_quality_score = max(
                0.0,
                min(100.0, 52.0 + (conf * 30.0) + field_bonus - freshness_pen),
            )
        signal_limitations = list(enriched_signal_limitations or [])
        if prev_close_val <= 0:
            signal_limitations.append("missing_previous_close")
        if volume_val <= 0:
            signal_limitations.append("missing_volume")
        if freshness_seconds > 120.0:
            signal_limitations.append("stale_quote_timestamp")
        return {
            "symbol": symbol,
            "provider_used": str(provider or "none").lower(),
            "price": round(_to_float(price, 0.0), 8),
            "prev_close": round(prev_close_val, 8) if prev_close_val > 0 else None,
            "previous_close": round(prev_close_val, 8) if prev_close_val > 0 else None,
            "open": round(open_val, 8) if open_val > 0 else None,
            "high": round(high_val, 8) if high_val > 0 else None,
            "low": round(low_val, 8) if low_val > 0 else None,
            "volume": round(volume_val, 4) if volume_val > 0 else None,
            "change": round(change_val, 8) if change_val != 0.0 else None,
            "change_percent": round(change_pct_val, 6) if change_pct_val != 0.0 else None,
            "provider_name": str(provider or "none").upper(),
            "provider_confidence": round(conf, 4),
            "freshness_seconds": round(freshness_seconds, 3),
            "data_quality_score": round(_to_float(data_quality_score, 0.0), 2),
            "provider_agreement": 1.0 if valid else 0.0,
            "quote_quality": str(quote_quality or "placeholder"),
            "cache_hit": bool(cache_hit),
            "data_unavailable_reason": data_unavailable_reason,
            "valid_quote": valid,
            "rejection_reason": rejection_reason,
            "raw_price_present": bool(price > 0),
            "raw_prev_close_present": bool(prev_close_val > 0),
            "quote_timestamp": ts_iso,
            "quote_age_seconds": max(0.0, _to_float(quote_age_seconds, freshness_seconds)),
            "provider_attempt_count": int(len(attempted)),
            "provider_success_count": int(1 if valid else 0),
            "attempted_providers": list(attempted),
            "cycle_trace": list(attempted),
            "quote_enriched": bool(quote_enriched),
            "quote_enrichment_sources": list(dict.fromkeys(quote_enrichment_sources or [])),
            "enriched_previous_close_source": str(enriched_previous_close_source or ""),
            "enriched_volume_source": str(enriched_volume_source or ""),
            "enriched_history_source": str(enriched_history_source or ""),
            "enriched_signal_ready": bool(enriched_signal_ready),
            "enriched_signal_limitations": list(dict.fromkeys(signal_limitations)),
            "price_source": str(provider or "none").upper() if valid else "",
            "previous_close_source": str(enriched_previous_close_source or provider or "").upper() if prev_close_val > 0 else "",
            "volume_source": str(enriched_volume_source or provider or "").upper() if volume_val > 0 else "",
            "change_percent_source": str(provider or "").upper() if change_pct_val != 0.0 else "",
            "history_source": str(enriched_history_source or "").upper(),
            "field_source_summary": {
                "price": str(provider or "none").upper() if valid else "",
                "previous_close": str(enriched_previous_close_source or provider or "").upper() if prev_close_val > 0 else "",
                "volume": str(enriched_volume_source or provider or "").upper() if volume_val > 0 else "",
                "change_percent": str(provider or "").upper() if change_pct_val != 0.0 else "",
                "history": str(enriched_history_source or "").upper(),
            },
        }

    def _cache_get(self, asset_type: str, symbol: str, max_age: float) -> dict[str, Any] | None:
        key = (str(asset_type or "stock"), _safe_symbol(symbol))
        with self._lock:
            cached = dict(self._quote_cache.get(key) or {})
        if not cached:
            with self._lock:
                self._request_metrics["cache_misses"] += 1
            return None
        age = time.time() - _to_float(cached.get("_cached_at"), 0.0)
        if age > max_age:
            with self._lock:
                self._request_metrics["cache_misses"] += 1
            return None
        with self._lock:
            self._request_metrics["cache_hits"] += 1
        cached["cache_hit"] = True
        cached["quote_age_seconds"] = round(age, 3)
        if str(cached.get("quote_quality") or "").lower() in {"", "live"}:
            cached["quote_quality"] = "cached"
        return cached

    def _cache_set(self, asset_type: str, symbol: str, payload: dict[str, Any]) -> None:
        key = (str(asset_type or "stock"), _safe_symbol(symbol))
        rec = dict(payload or {})
        rec["_cached_at"] = time.time()
        with self._lock:
            self._quote_cache[key] = rec

    def _request(self, provider: str, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> tuple[dict[str, Any], int | None, str, float]:
        t0 = time.perf_counter()
        provider_name = str(provider or "").upper()
        safe_params = tuple(sorted((str(k), "<credential>" if str(k).lower() in {"apikey", "token", "api_key"} else str(v)) for k, v in (params or {}).items()))
        request_key = json.dumps([provider_name, str(url).split("?", 1)[0], safe_params], separators=(",", ":"))
        with self._lock:
            self._request_metrics["requests_submitted"] += 1
            cached_result = self._request_results.get(request_key)
            if cached_result and (time.time() - float(cached_result[0])) <= 2.0:
                self._request_metrics["requests_coalesced"] += 1
                self._request_metrics["provider_calls_avoided"] += 1
                return cached_result[1]
            event = self._request_inflight.get(request_key)
            owner = event is None
            if owner:
                event = threading.Event()
                self._request_inflight[request_key] = event
        if not owner:
            event.wait(timeout=6.0)
            with self._lock:
                result = self._request_results.get(request_key)
                if result:
                    self._request_metrics["requests_coalesced"] += 1
                    self._request_metrics["provider_calls_avoided"] += 1
                    return result[1]
        if not get_call_permission(provider_name, cost=1):
            latency = (time.perf_counter() - t0) * 1000.0
            result = ({}, 429, "budget_guard_block", latency)
            with self._lock:
                self._request_results[request_key] = (time.time(), result)
                self._request_inflight.pop(request_key, None)
                event.set()
            return result
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=4.5)
            latency = (time.perf_counter() - t0) * 1000.0
            record_call(provider_name, cost=1)
            with self._lock:
                self._request_metrics["provider_calls_executed"] += 1
            status = int(resp.status_code)
            if status >= 400:
                if status == 429:
                    record_rate_limit(provider_name, http_status=status)
                else:
                    record_error(provider_name)
                text = f"http_{status}"
                result = ({}, status, text, latency)
                with self._lock:
                    self._request_metrics["failed_requests"] += 1
                    self._request_results[request_key] = (time.time(), result)
                return result
            data = resp.json() if resp.content else {}
            result = (data if isinstance(data, dict) else {"_list": data}, status, "", latency)
            with self._lock:
                self._request_results[request_key] = (time.time(), result)
            return result
        except Exception as e:  # noqa: BLE001
            latency = (time.perf_counter() - t0) * 1000.0
            record_error(provider_name)
            result = ({}, None, str(e)[:200], latency)
            with self._lock:
                self._request_metrics["failed_requests"] += 1
                self._request_results[request_key] = (time.time(), result)
            return result
        finally:
            with self._lock:
                self._request_results = {
                    key: value for key, value in self._request_results.items()
                    if (time.time() - float(value[0])) <= 10.0
                }
                inflight = self._request_inflight.pop(request_key, None)
                if inflight is not None:
                    inflight.set()

    def _fetch_quote_from_provider(self, provider: str, symbol: str, asset_type: str) -> dict[str, Any]:
        p = str(provider or "").upper()
        key = self._key_for(p, asset_type)
        if not key:
            return {"ok": False, "error": "missing_api_key", "status": None}
        if self._provider_in_cooldown(p):
            return {"ok": False, "error": "provider_cooldown", "status": None}

        if p == "FMP":
            endpoint_template = "/stable/quote?symbol={symbol}"
            endpoint_family, endpoint_policy, endpoint_allowed = _fmp_endpoint_policy(endpoint_template)
            if not endpoint_allowed:
                _fmp_efficiency_record(
                    {
                        "endpoint_family": endpoint_family,
                        "endpoint_path_template": endpoint_template,
                        "symbol_count": 1,
                        "status_code": 0,
                        "ok": False,
                        "cache_hit": False,
                        "bytes_estimated": 0,
                        "bytes_actual_if_available": 0,
                        "useful_fields_count": 0,
                        "useful_score": 0.0,
                        "call_reason": "live_quote_fetch",
                        "caller_context": "provider_router_fmp_quote",
                        "ttl_seconds": int(self.CACHE_TTL_SECONDS),
                        "blocked_reason": f"policy_blocked_{endpoint_policy}",
                        "api_calls_delta": 0,
                        "bandwidth_delta": 0,
                        "provider_governor_allowed": False,
                    }
                )
                return {"ok": False, "error": f"fmp_endpoint_policy_blocked:{endpoint_policy}", "status": 403}
            recent_key = ("FMP", f"{endpoint_template}:{str(symbol or '').upper().strip()}")
            now_ts = time.time()
            last_ts = _to_float(_FMP_RECENT_CALLS.get(recent_key), 0.0)
            if now_ts - last_ts < _FMP_RECENT_CALL_TTL_SECONDS:
                _fmp_efficiency_record(
                    {
                        "endpoint_family": endpoint_family,
                        "endpoint_path_template": endpoint_template,
                        "symbol_count": 1,
                        "status_code": 0,
                        "ok": False,
                        "cache_hit": True,
                        "bytes_estimated": 0,
                        "bytes_actual_if_available": 0,
                        "useful_fields_count": 0,
                        "useful_score": 0.0,
                        "call_reason": "live_quote_fetch",
                        "caller_context": "provider_router_fmp_quote",
                        "ttl_seconds": int(_FMP_RECENT_CALL_TTL_SECONDS),
                        "blocked_reason": "recent_call_ttl_active",
                        "api_calls_delta": 0,
                        "bandwidth_delta": 0,
                        "provider_governor_allowed": True,
                    }
                )
                return {"ok": False, "error": "fmp_recent_call_ttl_active", "status": 429}
            if self._fmp_probe_hard_limited():
                _fmp_efficiency_record(
                    {
                        "endpoint_family": endpoint_family,
                        "endpoint_path_template": endpoint_template,
                        "symbol_count": 1,
                        "status_code": 429,
                        "ok": False,
                        "cache_hit": False,
                        "bytes_estimated": 0,
                        "bytes_actual_if_available": 0,
                        "useful_fields_count": 0,
                        "useful_score": 0.0,
                        "call_reason": "live_quote_fetch",
                        "caller_context": "provider_router_fmp_quote",
                        "ttl_seconds": int(self.CACHE_TTL_SECONDS),
                        "blocked_reason": "call_limit",
                        "api_calls_delta": 0,
                        "bandwidth_delta": 0,
                        "provider_governor_allowed": False,
                    }
                )
                return {"ok": False, "error": "fmp_rest_probe_skipped_hard_limit", "status": 429}
            url = "https://financialmodelingprep.com/stable/quote"
            data, status, err, latency = self._request(p, url, params={"symbol": symbol, "apikey": key})
            if err:
                _fmp_efficiency_record(
                    {
                        "endpoint_family": endpoint_family,
                        "endpoint_path_template": endpoint_template,
                        "symbol_count": 1,
                        "status_code": int(status or 0),
                        "ok": False,
                        "cache_hit": False,
                        "bytes_estimated": 0,
                        "bytes_actual_if_available": 0,
                        "useful_fields_count": 0,
                        "useful_score": 0.0,
                        "call_reason": "live_quote_fetch",
                        "caller_context": "provider_router_fmp_quote",
                        "ttl_seconds": int(self.CACHE_TTL_SECONDS),
                        "blocked_reason": str(err or ""),
                        "api_calls_delta": 0,
                        "bandwidth_delta": 0,
                        "provider_governor_allowed": bool(status != 429),
                    }
                )
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            rows = data.get("_list") if isinstance(data.get("_list"), list) else data
            if isinstance(rows, list) and rows:
                row = dict(rows[0] or {})
            else:
                row = dict(data or {})
            price_v = _to_float(row.get("price"), 0.0)
            useful_fields_count = int(
                sum(
                    1
                    for k in ("price", "previousClose", "open", "dayHigh", "dayLow", "volume", "change", "changesPercentage", "timestamp")
                    if row.get(k) not in (None, "", 0, 0.0)
                )
            )
            bytes_actual = len(json.dumps(row, ensure_ascii=False).encode("utf-8")) if row else 0
            _fmp_efficiency_record(
                {
                    "endpoint_family": endpoint_family,
                    "endpoint_path_template": endpoint_template,
                    "symbol_count": 1,
                    "status_code": int(status or 200),
                    "ok": bool(price_v > 0),
                    "cache_hit": False,
                    "bytes_estimated": int(max(64, bytes_actual)),
                    "bytes_actual_if_available": int(bytes_actual),
                    "useful_fields_count": int(useful_fields_count),
                    "useful_score": float(max(0, useful_fields_count * 10)),
                    "call_reason": "live_quote_fetch",
                    "caller_context": "provider_router_fmp_quote",
                    "ttl_seconds": int(self.CACHE_TTL_SECONDS),
                    "blocked_reason": "",
                    "api_calls_delta": 1,
                    "bandwidth_delta": int(max(0, bytes_actual)),
                    "provider_governor_allowed": True,
                }
            )
            _FMP_RECENT_CALLS[recent_key] = now_ts
            return {
                "ok": price_v > 0,
                "price": price_v,
                "prev_close": _to_float(row.get("previousClose"), 0.0) or None,
                "open": _to_float(row.get("open"), 0.0) or None,
                "high": _to_float(row.get("dayHigh"), 0.0) or None,
                "low": _to_float(row.get("dayLow"), 0.0) or None,
                "volume": _to_float(row.get("volume"), 0.0) or None,
                "change": _to_float(row.get("change"), 0.0) or None,
                "change_percent": _to_float(row.get("changesPercentage"), 0.0) or None,
                "quote_timestamp": row.get("timestamp"),
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "price/previousClose",
            }

        if p == "FINNHUB":
            url = "https://finnhub.io/api/v1/quote"
            data, status, err, latency = self._request(p, url, params={"symbol": symbol, "token": key})
            if err:
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            price = _to_float(data.get("c"), 0.0)
            prev = _to_float(data.get("pc"), 0.0) or None
            return {
                "ok": price > 0,
                "price": price,
                "prev_close": prev,
                "open": _to_float(data.get("o"), 0.0) or None,
                "high": _to_float(data.get("h"), 0.0) or None,
                "low": _to_float(data.get("l"), 0.0) or None,
                "volume": _to_float(data.get("v"), 0.0) or None,
                "change": _to_float(data.get("d"), 0.0) or None,
                "change_percent": _to_float(data.get("dp"), 0.0) or None,
                "quote_timestamp": data.get("t"),
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "c/pc",
            }

        if p == "POLYGON":
            url = f"https://api.polygon.io/v2/last/trade/{symbol}"
            data, status, err, latency = self._request(p, url, params={"apiKey": key})
            if err:
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            result = dict(data.get("results") or {})
            price = _to_float(result.get("p"), 0.0)
            return {
                "ok": price > 0,
                "price": price,
                "prev_close": None,
                "quote_timestamp": result.get("t"),
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "results.p",
            }

        if p == "TWELVEDATA":
            url = "https://api.twelvedata.com/quote"
            data, status, err, latency = self._request(p, url, params={"symbol": symbol, "apikey": key})
            if err:
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            price = _to_float(data.get("close"), 0.0)
            prev = _to_float(data.get("previous_close"), 0.0) or None
            return {
                "ok": price > 0,
                "price": price,
                "prev_close": prev,
                "open": _to_float(data.get("open"), 0.0) or None,
                "high": _to_float(data.get("high"), 0.0) or None,
                "low": _to_float(data.get("low"), 0.0) or None,
                "volume": _to_float(data.get("volume"), 0.0) or None,
                "change": _to_float(data.get("change"), 0.0) or None,
                "change_percent": _to_float(data.get("percent_change"), 0.0) or None,
                "quote_timestamp": data.get("datetime"),
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "close/previous_close",
            }

        if p == "ALPHAVANTAGE":
            url = "https://www.alphavantage.co/query"
            data, status, err, latency = self._request(
                p,
                url,
                params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": key},
            )
            if err:
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            q = dict(data.get("Global Quote") or {})
            price = _to_float(q.get("05. price"), 0.0)
            prev = _to_float(q.get("08. previous close"), 0.0) or None
            return {
                "ok": price > 0,
                "price": price,
                "prev_close": prev,
                "open": _to_float(q.get("02. open"), 0.0) or None,
                "high": _to_float(q.get("03. high"), 0.0) or None,
                "low": _to_float(q.get("04. low"), 0.0) or None,
                "volume": _to_float(q.get("06. volume"), 0.0) or None,
                "change": _to_float(q.get("09. change"), 0.0) or None,
                "change_percent": _to_float(str(q.get("10. change percent", "")).replace("%", ""), 0.0) or None,
                "quote_timestamp": q.get("07. latest trading day"),
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "Global Quote/05. price",
            }

        if p == "EODHD":
            url = f"https://eodhd.com/api/real-time/{symbol}"
            data, status, err, latency = self._request(p, url, params={"api_token": key, "fmt": "json"})
            if err:
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            price = _to_float(data.get("close"), 0.0)
            prev = _to_float(data.get("previousClose"), 0.0) or None
            return {
                "ok": price > 0,
                "price": price,
                "prev_close": prev,
                "open": _to_float(data.get("open"), 0.0) or None,
                "high": _to_float(data.get("high"), 0.0) or None,
                "low": _to_float(data.get("low"), 0.0) or None,
                "volume": _to_float(data.get("volume"), 0.0) or None,
                "change": _to_float(data.get("change"), 0.0) or None,
                "change_percent": _to_float(data.get("change_p"), 0.0) or _to_float(data.get("pchange"), 0.0) or None,
                "quote_timestamp": data.get("timestamp"),
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "close/previousClose",
            }

        if p == "ALPACA":
            secret = _alpaca_secret_key()
            if not secret:
                return {"ok": False, "error": "missing_alpaca_secret", "status": None}
            headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
            if asset_type == "crypto":
                pair = str(symbol or "").upper().replace("-", "/")
                if "/" not in pair:
                    pair = f"{pair}/USD"
                url = "https://data.alpaca.markets/v1beta3/crypto/us/latest/quotes"
                data, status, err, latency = self._request(p, url, params={"symbols": pair}, headers=headers)
            else:
                pair = str(symbol or "").upper()
                url = f"https://data.alpaca.markets/v2/stocks/{pair}/quotes/latest"
                data, status, err, latency = self._request(p, url, headers=headers)
            if err:
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            quote = dict((data.get("quotes") or {}).get(pair) or {}) if asset_type == "crypto" else dict(data.get("quote") or {})
            ask = _to_float(quote.get("ap"), 0.0)
            bid = _to_float(quote.get("bp"), 0.0)
            price = ((ask + bid) / 2.0) if ask > 0 and bid > 0 else max(ask, bid)
            return {
                "ok": price > 0,
                "price": price,
                "prev_close": None,
                "open": None,
                "high": max(ask, bid) if max(ask, bid) > 0 else None,
                "low": min(x for x in (ask, bid) if x > 0) if (ask > 0 or bid > 0) else None,
                "volume": None,
                "change": None,
                "change_percent": None,
                "quote_timestamp": quote.get("t"),
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "quotes.<pair>.ap/bp" if asset_type == "crypto" else "quote.ap/quote.bp",
            }

        # MORALIS and unsupported providers return conservative failure.
        return {"ok": False, "error": "provider_not_implemented", "status": None}

    def get_quote(
        self,
        symbol: str,
        asset_type: str = "stock",
        batch_id: str | None = None,
        preferred_providers: list[str] | None = None,
        exclude_providers: list[str] | None = None,
        cache_max_age_seconds: int | float | None = None,
        bypass_cache: bool = False,
        protected_tier1: bool = False,
        use_selective_backups: bool = False,
    ) -> dict[str, Any]:
        sym = _safe_symbol(symbol)
        at = "crypto" if str(asset_type or "stock").lower() == "crypto" else "stock"
        default_cache_age = self._temp_discovery_cache_age if self._temp_strategy_enabled else 20.0
        max_age = _to_float(cache_max_age_seconds, default_cache_age)
        excluded = {str(p).upper() for p in (exclude_providers or []) if str(p).strip()}

        if not bypass_cache:
            cached = self._cache_get(at, sym, max_age)
            if cached:
                return cached

        default_order = self._effective_provider_order(at, preferred_providers=preferred_providers)

        providers = [p for p in default_order if p not in excluded and self._provider_active(p, at)]
        if not providers:
            payload = self._normalize_quote_payload(
                symbol=sym,
                provider="none",
                price=0.0,
                prev_close=None,
                attempted=[],
                cache_hit=False,
                quote_quality="placeholder",
                quote_age_seconds=0.0,
                data_unavailable_reason="no_active_provider",
                rejection_reason="no_active_provider",
            )
            return payload

        attempted: list[str] = []
        successes: list[tuple[str, dict[str, Any]]] = []
        first_success: tuple[str, dict[str, Any]] | None = None
        enrichment_sources: list[str] = []
        enriched_prev_close_source = ""
        enriched_volume_source = ""
        enriched_history_source = ""
        backfill_probes_used = 0
        self._last_cycle_attempt_order = []

        for p in providers:
            attempted.append(p)
            self._last_cycle_attempt_order.append(p)
            probe = self._fetch_quote_from_provider(p, sym, at)
            latency = _to_float(probe.get("latency_ms"), 0.0)
            ok = bool(probe.get("ok", False) and _to_float(probe.get("price"), 0.0) > 0)
            err = str(probe.get("error") or "")
            status = probe.get("status")
            rate_limited = self._is_rate_limited(status if isinstance(status, int) else None, err)
            self._mark_result(p, ok, latency, rate_limited=rate_limited)
            if err:
                self._set_last_error(p, err)
            if ok:
                successes.append((p, probe))
                if first_success is None:
                    first_success = (p, probe)
                    enrichment_sources.append(p)
                    needs_prev_close = _to_float(probe.get("prev_close"), 0.0) <= 0.0
                    needs_volume = _to_float(probe.get("volume"), 0.0) <= 0.0
                    needs_change = _to_float(probe.get("change_percent"), 0.0) == 0.0 and _to_float(probe.get("change"), 0.0) == 0.0
                    if not (needs_prev_close or needs_volume or needs_change) or self._max_backfill_provider_probes <= 0:
                        break
                    continue
                if backfill_probes_used < self._max_backfill_provider_probes:
                    backfill_probes_used += 1
                    enrichment_sources.append(p)
                # Stop once conservative backfill budget is exhausted.
                if backfill_probes_used >= self._max_backfill_provider_probes:
                    break

        if successes:
            used, q = first_success if first_success is not None else successes[0]
            enriched = dict(q or {})
            for src_name, src_probe in successes[1:]:
                if _to_float(enriched.get("prev_close"), 0.0) <= 0.0 and _to_float(src_probe.get("prev_close"), 0.0) > 0.0:
                    enriched["prev_close"] = _to_float(src_probe.get("prev_close"), 0.0)
                    enriched_prev_close_source = src_name
                if _to_float(enriched.get("volume"), 0.0) <= 0.0 and _to_float(src_probe.get("volume"), 0.0) > 0.0:
                    enriched["volume"] = _to_float(src_probe.get("volume"), 0.0)
                    enriched_volume_source = src_name
                if _to_float(enriched.get("change_percent"), 0.0) == 0.0 and _to_float(src_probe.get("change_percent"), 0.0) != 0.0:
                    enriched["change_percent"] = _to_float(src_probe.get("change_percent"), 0.0)
                if _to_float(enriched.get("change"), 0.0) == 0.0 and _to_float(src_probe.get("change"), 0.0) != 0.0:
                    enriched["change"] = _to_float(src_probe.get("change"), 0.0)
                if _to_float(enriched.get("open"), 0.0) <= 0.0 and _to_float(src_probe.get("open"), 0.0) > 0.0:
                    enriched["open"] = _to_float(src_probe.get("open"), 0.0)
                if _to_float(enriched.get("high"), 0.0) <= 0.0 and _to_float(src_probe.get("high"), 0.0) > 0.0:
                    enriched["high"] = _to_float(src_probe.get("high"), 0.0)
                if _to_float(enriched.get("low"), 0.0) <= 0.0 and _to_float(src_probe.get("low"), 0.0) > 0.0:
                    enriched["low"] = _to_float(src_probe.get("low"), 0.0)
            if used == "FINNHUB":
                enriched_history_source = "FINNHUB"
            limitations = []
            if _to_float(enriched.get("prev_close"), 0.0) <= 0.0:
                limitations.append("missing_previous_close")
            if _to_float(enriched.get("volume"), 0.0) <= 0.0:
                limitations.append("missing_volume")
            signal_ready = bool(
                _to_float(enriched.get("price"), 0.0) > 0.0
                and _to_float(enriched.get("prev_close"), 0.0) > 0.0
                and (_to_float(enriched.get("volume"), 0.0) > 0.0 or str(used).upper() == "FINNHUB")
            )
            quote_enriched = bool(
                bool(enriched_prev_close_source)
                or bool(enriched_volume_source)
                or len(successes) > 1
            )
            payload = self._normalize_quote_payload(
                symbol=sym,
                provider=used,
                price=_to_float(enriched.get("price"), 0.0),
                prev_close=enriched.get("prev_close"),
                attempted=attempted,
                cache_hit=False,
                quote_quality="live",
                quote_age_seconds=0.0,
                data_unavailable_reason=None,
                open_price=enriched.get("open"),
                high_price=enriched.get("high"),
                low_price=enriched.get("low"),
                volume=enriched.get("volume"),
                change=enriched.get("change"),
                change_percent=enriched.get("change_percent"),
                quote_timestamp=enriched.get("quote_timestamp"),
                quote_enriched=quote_enriched,
                quote_enrichment_sources=enrichment_sources,
                enriched_previous_close_source=enriched_prev_close_source,
                enriched_volume_source=enriched_volume_source,
                enriched_history_source=enriched_history_source,
                enriched_signal_ready=signal_ready,
                enriched_signal_limitations=limitations,
            )
            payload["provider_agreement"] = 1.0 if len(successes) == 1 else round(1.0 / float(len(successes)), 4)
            if protected_tier1:
                payload["tier1_protected"] = True
            if use_selective_backups:
                payload["selective_backups_used"] = bool(len(attempted) > 1)
            if batch_id:
                payload["quote_batch_id"] = str(batch_id)
            self._cache_set(at, sym, payload)
            return payload

        reason = "provider_unavailable"
        if attempted:
            reason = "all_providers_failed"
        payload = self._normalize_quote_payload(
            symbol=sym,
            provider="none",
            price=0.0,
            prev_close=None,
            attempted=attempted,
            cache_hit=False,
            quote_quality="placeholder",
            quote_age_seconds=0.0,
            data_unavailable_reason=reason,
            rejection_reason=reason,
            quote_enriched=False,
            quote_enrichment_sources=[],
            enriched_previous_close_source="",
            enriched_volume_source="",
            enriched_history_source="",
            enriched_signal_ready=False,
            enriched_signal_limitations=[reason],
        )
        if batch_id:
            payload["quote_batch_id"] = str(batch_id)
        return payload

    def test_provider_quote(self, provider: str, symbol: str, asset_type: str = "stock") -> dict[str, Any]:
        p = str(provider or "").upper()
        sym = _safe_symbol(symbol)
        at = "crypto" if str(asset_type or "stock").lower() == "crypto" else "stock"
        probe = self._fetch_quote_from_provider(p, sym, at)
        status = probe.get("status")
        err = str(probe.get("error") or "")
        ok = bool(probe.get("ok", False) and _to_float(probe.get("price"), 0.0) > 0)
        self._mark_result(
            p,
            ok,
            _to_float(probe.get("latency_ms"), 0.0),
            rate_limited=self._is_rate_limited(status if isinstance(status, int) else None, err),
        )
        if err:
            self._set_last_error(p, err)
        return {
            "provider": p,
            "symbol": sym,
            "asset_type": at,
            "success_boolean": ok,
            "parsed_price": _to_float(probe.get("price"), 0.0),
            "parsed_prev_close": probe.get("prev_close"),
            "parsed_open": probe.get("open"),
            "parsed_high": probe.get("high"),
            "parsed_low": probe.get("low"),
            "parsed_volume": probe.get("volume"),
            "parsed_change": probe.get("change"),
            "parsed_change_percent": probe.get("change_percent"),
            "parsed_timestamp": probe.get("quote_timestamp"),
            "http_status": status,
            "error": err,
            "field_path": str(probe.get("field_path") or ""),
            "latency_ms": round(_to_float(probe.get("latency_ms"), 0.0), 3),
            "rest_probe_skipped_due_to_hard_limit": bool(
                p == "FMP" and self._fmp_probe_hard_limited()
            ),
        }

    def deliberate_fmp_probe(self, symbol: str = "AAPL") -> dict[str, Any]:
        """Perform one explicit, bounded FMP quote probe with no retries."""
        p = "FMP"
        sym = _safe_symbol(symbol) or "AAPL"
        key = self._key_for(p, "stock")
        before = int((self.diagnostics().get("calls_used_per_provider") or {}).get("FMP", 0))
        if not key:
            return {"probe_attempted": False, "probe_success": False, "exact_blocker": "missing_fmp_credential", "calls_delta": 0}
        if self._temp_fmp_rest_disabled_explicit and self._temp_fmp_rest_disabled:
            return {"probe_attempted": False, "probe_success": False, "exact_blocker": "explicit_fmp_emergency_disable", "calls_delta": 0}
        data, status, error, latency = self._request(
            p,
            "https://financialmodelingprep.com/stable/quote",
            params={"symbol": sym, "apikey": key},
        )
        rows = data.get("_list") if isinstance(data, dict) and isinstance(data.get("_list"), list) else data
        row = dict(rows[0] or {}) if isinstance(rows, list) and rows else dict(rows or {}) if isinstance(rows, dict) else {}
        success = bool(_to_float(row.get("price"), 0.0) > 0.0 and not error)
        self._mark_result(p, success, latency, rate_limited=int(status or 0) == 429)
        if error:
            self._set_last_error(p, error)
        response_bytes = len(json.dumps(row, separators=(",", ":")).encode("utf-8")) if row else 0
        _fmp_efficiency_record({
            "endpoint_family": "quote_profile",
            "endpoint_path_template": "/stable/quote?symbol={symbol}",
            "symbol_count": 1,
            "status_code": int(status or 0),
            "ok": success,
            "cache_hit": False,
            "bytes_estimated": response_bytes,
            "bytes_actual_if_available": response_bytes,
            "useful_fields_count": len([value for value in row.values() if value not in (None, "")]),
            "useful_score": 1.0 if success else 0.0,
            "call_reason": "deliberate_validation_probe",
            "caller_context": "provider_router_deliberate_fmp_probe",
            "ttl_seconds": int(self.CACHE_TTL_SECONDS),
            "blocked_reason": str(error or "")[:120],
            "api_calls_delta": 1,
            "bandwidth_delta": response_bytes,
            "provider_governor_allowed": True,
        })
        after = int((self.diagnostics().get("calls_used_per_provider") or {}).get("FMP", 0))
        manifest = _fmp_efficiency_manifest_load()
        manifest.update({
            "last_probe_attempt_at": _now_iso(),
            "last_probe_success_at": _now_iso() if success else str(manifest.get("last_probe_success_at") or ""),
            "last_probe_status_code": int(status or 0),
            "last_probe_response_bytes": int(response_bytes),
            "last_probe_latency_ms": round(latency, 3),
            "last_probe_exact_error": str(error or "")[:120],
        })
        _fmp_efficiency_manifest_write(manifest)
        return {
            "probe_attempted": True,
            "probe_success": success,
            "symbol": sym,
            "status_code": int(status or 0),
            "latency_ms": round(latency, 3),
            "response_bytes": int(response_bytes),
            "calls_before": before,
            "calls_after": after,
            "calls_delta": max(0, after - before),
            "exact_blocker": str(error or "")[:120],
            "retry_count": 0,
            "broker_actions_used": 0,
            "secret_exposed": False,
        }

    def fetch_fmp_profile_context(self, symbol: str) -> dict[str, Any]:
        """Fetch one bounded, secret-free FMP profile record for a worker.

        This is intentionally narrower than quote routing: legacy lifecycle
        monitoring needs thesis context, not a second quote system.  The
        existing request coalescing, API governor, timeout, and FMP ledger
        remain the sole owners of provider access and accounting.
        """
        provider = "FMP"
        sym = _safe_symbol(symbol)
        requested_at = _now_iso()
        endpoint_family = "company_profile"
        endpoint_template = "/stable/profile?symbol={symbol}"

        def outcome(
            response_state: str,
            *,
            http_status: int | None = None,
            error_category: str = "",
            normalized_fields: dict[str, Any] | None = None,
            records_received: int = 0,
            records_valid: int = 0,
            latency_ms: float = 0.0,
        ) -> dict[str, Any]:
            success = response_state == "SUCCESS"
            _fmp_efficiency_record(
                {
                    "endpoint_family": endpoint_family,
                    "endpoint_path_template": endpoint_template,
                    "symbol_count": 1,
                    "status_code": int(http_status or 0),
                    "ok": success,
                    "cache_hit": False,
                    "bytes_estimated": 0,
                    "bytes_actual_if_available": 0,
                    "useful_fields_count": len(normalized_fields or {}),
                    "useful_score": float(min(100, len(normalized_fields or {}) * 12)) if success else 0.0,
                    "call_reason": "legacy_swing_thesis_context",
                    "caller_context": "paper_autopilot_legacy_swing_worker",
                    "ttl_seconds": 3600,
                    "blocked_reason": str(error_category or ""),
                    "api_calls_delta": 1 if http_status is not None else 0,
                    "bandwidth_delta": 0,
                    "provider_governor_allowed": response_state not in {"RATE_LIMITED", "PROVIDER_UNAVAILABLE"},
                }
            )
            return {
                "provider": provider,
                "endpoint_family": endpoint_family,
                "endpoint_template": endpoint_template,
                "symbol": sym,
                "requested_at": requested_at,
                "response_at": _now_iso(),
                "http_status": int(http_status or 0),
                "authentication_state": "PRESENT" if bool(self._key_for(provider, "stock")) else "MISSING",
                "entitlement_state": "UNKNOWN" if success else "BLOCKED" if response_state == "ENTITLEMENT_BLOCKED" else "UNVERIFIED",
                "response_state": response_state,
                "error_category": str(error_category or ""),
                "records_received": int(records_received),
                "records_valid": int(records_valid),
                "normalized_fields": dict(normalized_fields or {}),
                "latency_ms": round(_to_float(latency_ms, 0.0), 3),
                "broker_actions": 0,
                "secret_exposed": False,
            }

        if not sym:
            return outcome("MALFORMED_RESPONSE", error_category="symbol_required")
        key = self._key_for(provider, "stock")
        if not key:
            return outcome("AUTHENTICATION_FAILED", error_category="missing_fmp_credential")
        if self._temp_fmp_rest_disabled:
            return outcome("PROVIDER_UNAVAILABLE", error_category="fmp_rest_temporarily_disabled")
        if self._provider_in_cooldown(provider):
            return outcome("RATE_LIMITED", error_category="provider_cooldown")

        data, status, error, latency = self._request(
            provider,
            "https://financialmodelingprep.com/stable/profile",
            params={"symbol": sym, "apikey": key},
        )
        if error:
            category = str(error or "provider_error")
            state = (
                "AUTHENTICATION_FAILED" if int(status or 0) == 401 else
                "ENTITLEMENT_BLOCKED" if int(status or 0) == 403 else
                "RATE_LIMITED" if int(status or 0) == 429 or "budget" in category else
                "TIMEOUT" if "timeout" in category.lower() else
                "PROVIDER_ERROR"
            )
            self._mark_result(provider, False, latency, rate_limited=state == "RATE_LIMITED")
            self._set_last_error(provider, category)
            return outcome(state, http_status=status, error_category=category, latency_ms=latency)

        rows = data.get("_list") if isinstance(data, dict) and isinstance(data.get("_list"), list) else data
        row = dict(rows[0] or {}) if isinstance(rows, list) and rows else dict(rows or {}) if isinstance(rows, dict) else {}
        if not row:
            self._mark_result(provider, False, latency)
            return outcome("EMPTY_RESPONSE", http_status=status, error_category="empty_profile_response", latency_ms=latency)
        returned_symbol = _safe_symbol(row.get("symbol"))
        if returned_symbol and returned_symbol != sym:
            self._mark_result(provider, False, latency)
            return outcome("MALFORMED_RESPONSE", http_status=status, error_category="symbol_mismatch", records_received=1, latency_ms=latency)
        normalized = {
            "company_name": str(row.get("companyName") or row.get("company_name") or "").strip(),
            "sector": str(row.get("sector") or "").strip(),
            "industry": str(row.get("industry") or "").strip(),
            "exchange": str(row.get("exchange") or "").strip(),
            "market_cap": _to_float(row.get("mktCap") or row.get("marketCap"), 0.0) or None,
            "beta": _to_float(row.get("beta"), 0.0) or None,
            "is_etf": bool(row.get("isEtf") or row.get("isETF")),
        }
        normalized = {key: value for key, value in normalized.items() if value not in (None, "")}
        if not normalized:
            self._mark_result(provider, False, latency)
            return outcome("EMPTY_RESPONSE", http_status=status, error_category="profile_fields_empty", records_received=1, latency_ms=latency)
        self._mark_result(provider, True, latency)
        return outcome(
            "SUCCESS", http_status=status, normalized_fields=normalized,
            records_received=1, records_valid=1, latency_ms=latency,
        )

    def fetch_fmp_historical_bars(self, symbol: str, *, timeframe: str = "1Hour", limit: int = 20) -> dict[str, Any]:
        """Fetch bounded FMP intraday bars for the legacy-SWING worker.

        This is deliberately a narrow fallback API.  It shares the router's
        credential lookup, request coalescing, governor, timeout, and FMP
        efficiency ledger rather than creating another FMP client.
        """
        provider = "FMP"
        sym = _safe_symbol(symbol)
        requested_at = _now_iso()
        normalized_timeframe = str(timeframe or "1Hour").strip()
        interval = {"1hour": "1hour", "1h": "1hour"}.get(normalized_timeframe.lower())
        endpoint_family = "historical_prices"
        endpoint_template = "/stable/historical-chart/1hour?symbol={symbol}"

        def outcome(
            response_state: str,
            *,
            http_status: int | None = None,
            error_category: str = "",
            bars: list[dict[str, Any]] | None = None,
            records_received: int = 0,
            records_valid: int = 0,
            latency_ms: float = 0.0,
        ) -> dict[str, Any]:
            clean_bars = list(bars or [])
            success = response_state == "SUCCESS"
            _fmp_efficiency_record(
                {
                    "endpoint_family": endpoint_family,
                    "endpoint_path_template": endpoint_template,
                    "symbol_count": 1,
                    "status_code": int(http_status or 0),
                    "ok": success,
                    "cache_hit": False,
                    "bytes_estimated": 0,
                    "bytes_actual_if_available": 0,
                    "useful_fields_count": int(records_valid),
                    "useful_score": float(min(100, records_valid * 5)) if success else 0.0,
                    "call_reason": "legacy_swing_historical_bar_fallback",
                    "caller_context": "paper_autopilot_legacy_swing_worker",
                    "ttl_seconds": 6 * 60 * 60,
                    "blocked_reason": str(error_category or ""),
                    "api_calls_delta": 1 if http_status is not None else 0,
                    "bandwidth_delta": 0,
                    "provider_governor_allowed": response_state not in {"RATE_LIMITED", "BUDGET_BLOCKED"},
                }
            )
            return {
                "provider": provider,
                "endpoint_family": endpoint_family,
                "endpoint_template": endpoint_template,
                "symbol": sym,
                "timeframe": normalized_timeframe,
                "requested_at": requested_at,
                "response_at": _now_iso(),
                "http_status": int(http_status or 0),
                "authentication_state": "PRESENT" if bool(self._key_for(provider, "stock")) else "MISSING",
                "entitlement_state": "UNKNOWN" if success else "BLOCKED" if response_state == "ENTITLEMENT_BLOCKED" else "UNVERIFIED",
                "response_state": response_state,
                "error_category": str(error_category or ""),
                "bars": clean_bars,
                "records_received": int(records_received),
                "records_valid": int(records_valid),
                "latency_ms": round(_to_float(latency_ms, 0.0), 3),
                "broker_actions": 0,
                "secret_exposed": False,
            }

        if not sym or not interval:
            return outcome("UNSUPPORTED_ENDPOINT", error_category="unsupported_timeframe")
        _family, _policy, allowed = _fmp_endpoint_policy(endpoint_template)
        if not allowed:
            return outcome("BUDGET_BLOCKED", error_category="historical_fallback_policy_blocked")
        key = self._key_for(provider, "stock")
        if not key:
            return outcome("AUTHENTICATION_FAILED", error_category="missing_fmp_credential")
        if self._temp_fmp_rest_disabled:
            return outcome("PROVIDER_ERROR", error_category="fmp_rest_temporarily_disabled")
        if self._provider_in_cooldown(provider) or self._fmp_probe_hard_limited():
            return outcome("RATE_LIMITED", error_category="provider_cooldown_or_budget")

        data, status, error, latency = self._request(
            provider,
            f"https://financialmodelingprep.com/stable/historical-chart/{interval}",
            params={"symbol": sym, "apikey": key},
        )
        if error:
            category = str(error or "provider_error")
            state = (
                "AUTHENTICATION_FAILED" if int(status or 0) == 401 else
                "ENTITLEMENT_BLOCKED" if int(status or 0) == 403 else
                "RATE_LIMITED" if int(status or 0) == 429 else
                "TIMEOUT" if "timeout" in category.lower() else "PROVIDER_ERROR"
            )
            self._mark_result(provider, False, latency, rate_limited=state == "RATE_LIMITED")
            return outcome(state, http_status=status, error_category=category, latency_ms=latency)
        rows = data.get("_list") if isinstance(data, dict) and isinstance(data.get("_list"), list) else data
        if not isinstance(rows, list) or not rows:
            self._mark_result(provider, False, latency)
            return outcome("EMPTY_RESPONSE", http_status=status, error_category="empty_historical_response", latency_ms=latency)
        normalized: list[dict[str, Any]] = []
        for raw in rows[: max(1, min(int(limit or 20) * 3, 200))]:
            row = dict(raw or {}) if isinstance(raw, dict) else {}
            returned_symbol = _safe_symbol(row.get("symbol"))
            if returned_symbol and returned_symbol != sym:
                continue
            normalized.append({
                "timestamp": row.get("date") or row.get("datetime") or row.get("timestamp"),
                "open": row.get("open"), "high": row.get("high"), "low": row.get("low"),
                "close": row.get("close"), "volume": row.get("volume"),
            })
        self._mark_result(provider, bool(normalized), latency)
        return outcome(
            "SUCCESS" if normalized else "MALFORMED_RESPONSE",
            http_status=status,
            error_category="" if normalized else "historical_rows_unusable",
            bars=normalized,
            records_received=len(rows),
            records_valid=len(normalized),
            latency_ms=latency,
        )

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            stats = {k: dict(v or {}) for k, v in self._provider_stats.items()}
            request_metrics = dict(self._request_metrics)
        calls_used_per_provider = {k: int(v.get("calls", 0) or 0) for k, v in stats.items()}
        success_rate = {}
        error_rate = {}
        cooldown = []
        healthy = []
        total_sr = 0.0
        sr_n = 0
        now = time.time()

        for p, v in stats.items():
            calls = max(1, int(v.get("calls", 0) or 0))
            succ = int(v.get("success", 0) or 0)
            errs = int(v.get("errors", 0) or 0)
            sr = (succ / calls) * 100.0
            er = (errs / calls) * 100.0
            success_rate[p] = round(sr, 4)
            error_rate[p] = round(er, 4)
            total_sr += sr
            sr_n += 1
            if _to_float(v.get("cooldown_until"), 0.0) > now:
                cooldown.append(p)
            if succ > 0 and er < 90.0:
                healthy.append(p)

        enabled = sorted(
            {
                p
                for p in set(self.STOCK_PROVIDER_ORDER + self.CRYPTO_PROVIDER_ORDER)
                if self._provider_active(p, "stock") or self._provider_active(p, "crypto")
            }
        )

        return {
            "providers_enabled": enabled,
            "providers_healthy": sorted(set(healthy)),
            "providers_in_cooldown": sorted(set(cooldown)),
            "calls_used_per_provider": calls_used_per_provider,
            "error_rate_per_provider": error_rate,
            "provider_success_rate": success_rate,
            "provider_agreement_average": round((total_sr / sr_n), 4) if sr_n else 0.0,
            "rotation_events_last_cycle": max(0, len(self._last_cycle_attempt_order) - 1),
            "last_cycle_attempt_order": list(self._last_cycle_attempt_order),
            "fmp_rest_probe_hard_limited": bool(self._fmp_probe_hard_limited()),
            "provider_role_matrix": self.provider_role_matrix(),
            "temporary_provider_strategy_v1": bool(self._temp_strategy_enabled),
            "fmp_rest_disabled_temporarily": bool(self._temp_strategy_enabled and self._temp_fmp_rest_disabled),
            "fmp_rest_disable_explicit": bool(self._temp_fmp_rest_disabled_explicit),
            "fmp_smart_budget_enabled": bool(self._fmp_smart_budget_enabled),
            "fmp_websocket_monitor_only": bool(self._temp_strategy_enabled and self._temp_fmp_ws_monitor_only),
            "temp_discovery_cache_max_age_seconds": float(self._temp_discovery_cache_age),
            "provider_backfill_max_probes": int(self._max_backfill_provider_probes),
            "shared_request_cache_metrics": request_metrics,
            "inflight_request_count": int(len(self._request_inflight)),
            "request_deduplication_connected": True,
            "secret_free_request_keys": True,
        }
