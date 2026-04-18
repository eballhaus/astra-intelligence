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
from datetime import UTC, datetime
from typing import Any

import requests

from api_keys import API_POOLS, ALPACA_SECRET_KEY


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
        self._provider_stats: dict[str, dict[str, Any]] = {}
        self._last_cycle_attempt_order: list[str] = []

    def _key_for(self, provider: str, asset_type: str) -> str:
        p = str(provider or "").upper()
        if asset_type == "crypto" and p in self._crypto_keys:
            return self._crypto_keys.get(p, "")
        return self._stock_keys.get(p, "") or self._crypto_keys.get(p, "")

    def _provider_active(self, provider: str, asset_type: str) -> bool:
        key = self._key_for(provider, asset_type)
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
    ) -> dict[str, Any]:
        valid = bool(price > 0)
        return {
            "symbol": symbol,
            "provider_used": str(provider or "none").lower(),
            "price": round(_to_float(price, 0.0), 8),
            "prev_close": round(_to_float(prev_close, 0.0), 8) if prev_close is not None else None,
            "provider_agreement": 1.0 if valid else 0.0,
            "quote_quality": str(quote_quality or "placeholder"),
            "cache_hit": bool(cache_hit),
            "data_unavailable_reason": data_unavailable_reason,
            "valid_quote": valid,
            "rejection_reason": rejection_reason,
            "raw_price_present": bool(price > 0),
            "raw_prev_close_present": bool(prev_close is not None and _to_float(prev_close, 0.0) > 0),
            "quote_timestamp": _now_iso(),
            "quote_age_seconds": max(0.0, _to_float(quote_age_seconds, 0.0)),
            "provider_attempt_count": int(len(attempted)),
            "provider_success_count": int(1 if valid else 0),
            "attempted_providers": list(attempted),
            "cycle_trace": list(attempted),
        }

    def _cache_get(self, asset_type: str, symbol: str, max_age: float) -> dict[str, Any] | None:
        key = (str(asset_type or "stock"), _safe_symbol(symbol))
        with self._lock:
            cached = dict(self._quote_cache.get(key) or {})
        if not cached:
            return None
        age = time.time() - _to_float(cached.get("_cached_at"), 0.0)
        if age > max_age:
            return None
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
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=4.5)
            latency = (time.perf_counter() - t0) * 1000.0
            status = int(resp.status_code)
            if status >= 400:
                text = f"http_{status}"
                return {}, status, text, latency
            data = resp.json() if resp.content else {}
            return data if isinstance(data, dict) else {"_list": data}, status, "", latency
        except Exception as e:  # noqa: BLE001
            latency = (time.perf_counter() - t0) * 1000.0
            return {}, None, str(e)[:200], latency

    def _fetch_quote_from_provider(self, provider: str, symbol: str, asset_type: str) -> dict[str, Any]:
        p = str(provider or "").upper()
        key = self._key_for(p, asset_type)
        if not key:
            return {"ok": False, "error": "missing_api_key", "status": None}
        if self._provider_in_cooldown(p):
            return {"ok": False, "error": "provider_cooldown", "status": None}

        if p == "FMP":
            if self._fmp_probe_hard_limited():
                return {"ok": False, "error": "fmp_rest_probe_skipped_hard_limit", "status": 429}
            url = f"https://financialmodelingprep.com/api/v3/quote/{symbol}"
            data, status, err, latency = self._request(p, url, params={"apikey": key})
            if err:
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            rows = data.get("_list") if isinstance(data.get("_list"), list) else data
            if isinstance(rows, list) and rows:
                row = dict(rows[0] or {})
            else:
                row = dict(data or {})
            return {
                "ok": _to_float(row.get("price"), 0.0) > 0,
                "price": _to_float(row.get("price"), 0.0),
                "prev_close": _to_float(row.get("previousClose"), 0.0) or None,
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
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "close/previousClose",
            }

        if p == "ALPACA":
            secret = str(ALPACA_SECRET_KEY or "")
            if not secret:
                return {"ok": False, "error": "missing_alpaca_secret", "status": None}
            url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
            headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
            data, status, err, latency = self._request(p, url, headers=headers)
            if err:
                return {"ok": False, "error": err, "status": status, "latency_ms": latency}
            quote = dict(data.get("quote") or {})
            ask = _to_float(quote.get("ap"), 0.0)
            bid = _to_float(quote.get("bp"), 0.0)
            price = ((ask + bid) / 2.0) if ask > 0 and bid > 0 else max(ask, bid)
            return {
                "ok": price > 0,
                "price": price,
                "prev_close": None,
                "status": status,
                "error": "",
                "latency_ms": latency,
                "field_path": "quote.ap/quote.bp",
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
        max_age = _to_float(cache_max_age_seconds, 20.0)
        excluded = {str(p).upper() for p in (exclude_providers or []) if str(p).strip()}

        if not bypass_cache:
            cached = self._cache_get(at, sym, max_age)
            if cached:
                return cached

        default_order = list(self.CRYPTO_PROVIDER_ORDER if at == "crypto" else self.STOCK_PROVIDER_ORDER)
        if preferred_providers:
            pref = [str(p).upper() for p in preferred_providers if str(p).strip()]
            merged = []
            for p in pref + default_order:
                if p not in merged:
                    merged.append(p)
            default_order = merged

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
                # Conservative: stop at first valid quote to avoid pressure.
                break

        if successes:
            used, q = successes[0]
            payload = self._normalize_quote_payload(
                symbol=sym,
                provider=used,
                price=_to_float(q.get("price"), 0.0),
                prev_close=q.get("prev_close"),
                attempted=attempted,
                cache_hit=False,
                quote_quality="live",
                quote_age_seconds=0.0,
                data_unavailable_reason=None,
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
            "http_status": status,
            "error": err,
            "field_path": str(probe.get("field_path") or ""),
            "latency_ms": round(_to_float(probe.get("latency_ms"), 0.0), 3),
            "rest_probe_skipped_due_to_hard_limit": bool(
                p == "FMP" and self._fmp_probe_hard_limited()
            ),
        }

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            stats = {k: dict(v or {}) for k, v in self._provider_stats.items()}
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
        }
