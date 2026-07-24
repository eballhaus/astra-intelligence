from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from threading import Lock
import os
import time

_LOCK = Lock()
_CALLS = defaultdict(int)
_ERRORS = defaultdict(int)
_RATE_LIMITS = defaultdict(int)
_LAST_CALL_TS = defaultdict(float)
_WINDOW_CALL_TS = defaultdict(list)
_COOLDOWN_UNTIL = defaultdict(float)
_DEFAULT_CAP_PER_MIN = int(float(os.getenv("ASTRA_PROVIDER_DEFAULT_CAP_PER_MIN", "120")))


def _env_bool(name: str, default: bool) -> bool:
    value = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _temp_strategy_enabled() -> bool:
    return _env_bool("ASTRA_TEMP_PROVIDER_STRATEGY_V1", True)


def _fmp_smart_budget_enabled() -> bool:
    return _env_bool("ASTRA_FMP_SMART_BUDGET_ENABLED", True)


def _fmp_rest_disable_explicit() -> bool:
    return "ASTRA_TEMP_FMP_REST_DISABLED" in os.environ


def _fmp_rest_disabled() -> bool:
    return _fmp_rest_disable_explicit() and _env_bool("ASTRA_TEMP_FMP_REST_DISABLED", False)


def _normalize(provider: str) -> str:
    return str(provider or "UNKNOWN").strip().upper()


def _cap_per_min(provider: str) -> int:
    p = _normalize(provider)
    override = os.getenv(f"ASTRA_PROVIDER_CAP_{p}_PER_MIN", "").strip()
    if override:
        try:
            return max(0, int(float(override)))
        except Exception:
            pass
    if _temp_strategy_enabled():
        temporary_caps = {
            "ALPACA": 240,
            "TWELVEDATA": 35,
            "FINNHUB": 30,
            "EODHD": 25,
            "POLYGON": 30,
            "ALPHAVANTAGE": 8,
            "MORALIS": 20,
            "FRED": 4,
            # FMP is a premium, bounded context provider.  Four shared calls
            # were routinely consumed by candidate enrichment before the
            # worker could refresh an open position.  Twelve remains far below
            # the account cap while reserving enough bounded capacity for the
            # open-position evidence queue.  Thirty calls/minute is still far
            # below the Premium account limit and does not change any trade
            # authority.
            "FMP": 0 if _fmp_rest_disabled() else 30,
        }
        if p in temporary_caps:
            return int(temporary_caps[p])
    return max(1, int(_DEFAULT_CAP_PER_MIN))


def _provider_role(provider: str) -> str:
    p = _normalize(provider)
    if p == "ALPACA":
        return "primary_live_monitoring"
    if p == "TWELVEDATA":
        return "coverage_expansion_backup"
    if p == "FINNHUB":
        return "context_and_backup_quote"
    if p == "EODHD":
        return "backup_quote_validation"
    if p == "ALPHAVANTAGE":
        return "low_frequency_backup"
    if p == "POLYGON":
        return "backup_quote_feed"
    if p == "FMP":
        if _fmp_rest_disabled():
            return "rest_conserved_websocket_monitor_only"
        if _fmp_smart_budget_enabled():
            return "smart_budget_cache_first_bounded_rest"
        return "fmp_rest_standard_budgeted"
    if p == "FRED":
        return "macro_regime_low_frequency"
    if p == "MORALIS":
        return "crypto_support"
    return "general"


def get_call_permission(provider: str, cost: int = 1) -> bool:
    p = _normalize(provider)
    n = max(1, int(cost or 1))
    now = time.time()
    with _LOCK:
        if _COOLDOWN_UNTIL[p] > now:
            return False
        if _temp_strategy_enabled() and _fmp_rest_disabled() and p == "FMP":
            return False
        cap = _cap_per_min(p)
        if cap <= 0:
            return False
        bucket = [ts for ts in _WINDOW_CALL_TS[p] if (now - float(ts)) <= 60.0]
        _WINDOW_CALL_TS[p] = bucket
        return (len(bucket) + n) <= cap


def record_call(provider: str, cost: int = 1):
    p = _normalize(provider)
    n = max(1, int(cost or 1))
    now = datetime.now(UTC).timestamp()
    with _LOCK:
        _CALLS[p] += n
        _LAST_CALL_TS[p] = now
        for _ in range(n):
            _WINDOW_CALL_TS[p].append(now)
        # Keep window compact.
        _WINDOW_CALL_TS[p] = [ts for ts in _WINDOW_CALL_TS[p] if (now - float(ts)) <= 60.0]


def record_error(provider: str):
    p = _normalize(provider)
    with _LOCK:
        _ERRORS[p] += 1


def record_rate_limit(provider: str, http_status: int | None = None):
    p = _normalize(provider)
    now = time.time()
    with _LOCK:
        _RATE_LIMITS[p] += 1
        _COOLDOWN_UNTIL[p] = max(_COOLDOWN_UNTIL[p], now + 120.0)


def get_provider_status_summary() -> list[dict]:
    now = time.time()
    with _LOCK:
        providers = sorted(set(_CALLS) | set(_ERRORS) | set(_RATE_LIMITS) | set(_WINDOW_CALL_TS) | set(_COOLDOWN_UNTIL))
        rows = []
        for p in providers:
            minute_calls = len([ts for ts in _WINDOW_CALL_TS[p] if (now - float(ts)) <= 60.0])
            _WINDOW_CALL_TS[p] = [ts for ts in _WINDOW_CALL_TS[p] if (now - float(ts)) <= 60.0]
            calls = int(_CALLS.get(p, 0))
            errors = int(_ERRORS.get(p, 0))
            rate_limits = int(_RATE_LIMITS.get(p, 0))
            success_rate = 100.0 if calls == 0 else max(0.0, min(100.0, ((calls - errors) / max(1, calls)) * 100.0))
            cooldown_state = "cooldown" if _COOLDOWN_UNTIL[p] > now else "active"
            rows.append(
                {
                    "provider": p,
                    "provider_role": _provider_role(p),
                    "calls": calls,
                    "errors": errors,
                    "rate_limits": rate_limits,
                    "last_call_ts": float(_LAST_CALL_TS.get(p, 0.0)),
                    "provider_calls_last_minute": int(minute_calls),
                    "provider_success_rate": round(success_rate, 4),
                    "provider_cooldown_state": cooldown_state,
                    "provider_average_latency": 0.0,
                    "healthy": bool(success_rate >= 30.0 and cooldown_state != "cooldown"),
                    "cap_per_minute": int(_cap_per_min(p)),
                    "temp_strategy_mode": bool(_temp_strategy_enabled()),
                }
            )
    return rows


def get_usage_summary() -> dict:
    with _LOCK:
        return {
            "total_calls": int(sum(_CALLS.values())),
            "total_errors": int(sum(_ERRORS.values())),
            "total_rate_limits": int(sum(_RATE_LIMITS.values())),
            "temporary_provider_strategy_v1": bool(_temp_strategy_enabled()),
            "fmp_rest_temporarily_disabled": bool(_temp_strategy_enabled() and _fmp_rest_disabled()),
            "fmp_rest_disable_explicit": bool(_fmp_rest_disable_explicit()),
            "fmp_smart_budget_enabled": bool(_fmp_smart_budget_enabled()),
        }
