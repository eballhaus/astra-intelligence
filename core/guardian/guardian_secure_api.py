import os
import socket
import time

from api_keys import API_POOLS
from engine.api_call_manager import get_provider_status_summary
from engine.api_caches import get_cache
from engine.provider_router import ProviderRouter


class GuardianSecureAPI:
    PROVIDER_DOMAINS = {
        "FINNHUB": "finnhub.io",
        "FMP": "financialmodelingprep.com",
        "ALPHAVANTAGE": "www.alphavantage.co",
        "TWELVEDATA": "api.twelvedata.com",
        "POLYGON": "api.polygon.io",
        "EODHD": "eodhd.com",
        "ALPACA": "data.alpaca.markets",
        "MORALIS": "deep-index.moralis.io",
    }
    _startup_checked = False
    _dns_status = {}
    _keys_logged = False
    _router = ProviderRouter()
    _batch_seq = 0
    _batch_id = ""
    _batch_ts = 0.0
    _provider_status_cache = {"ts": 0.0, "symbol": "", "rows": []}
    _provider_status_ttl = 20.0

    @staticmethod
    def _env_flag(name, default=False):
        raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @classmethod
    def _fmp_probe_hard_limited(cls):
        return bool(
            cls._env_flag("ASTRA_FMP_REST_HARD_LIMIT_ENABLED", True)
            and cls._env_flag("ASTRA_FMP_SKIP_PROBES_WHEN_LIMITED", True)
        )

    def __init__(self):
        self._stock_pool = list(API_POOLS.get("stocks", []))
        self._crypto_pool = list(API_POOLS.get("crypto", []))
        self._initialize_runtime_checks()
        self._log_key_status_once()

    @staticmethod
    def _mask_key(key):
        s = str(key or "")
        if len(s) <= 4:
            return "****" if s else ""
        return "*" * (len(s) - 4) + s[-4:]

    def _initialize_runtime_checks(self):
        if GuardianSecureAPI._startup_checked:
            return
        GuardianSecureAPI._startup_checked = True
        for provider, domain in self.PROVIDER_DOMAINS.items():
            try:
                socket.gethostbyname(domain)
                GuardianSecureAPI._dns_status[provider] = True
            except Exception as e:
                GuardianSecureAPI._dns_status[provider] = False
                print(f"[GuardianSecureAPI] NETWORK_DNS_FAILURE provider={provider} domain={domain} error={e}")

    def _log_key_status_once(self):
        if GuardianSecureAPI._keys_logged:
            return
        GuardianSecureAPI._keys_logged = True
        for provider, key in self._stock_pool + self._crypto_pool:
            if key and not str(key).startswith("YOUR_"):
                print(f"[GuardianSecureAPI] API_KEY_LOADED: {provider} key={self._mask_key(key)}")
            else:
                print(f"[GuardianSecureAPI] API_KEY_MISSING: {provider}")

    @staticmethod
    def _asset_type_for_symbol(symbol):
        return "crypto" if str(symbol or "").upper() in {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"} else "stock"

    @classmethod
    def _active_batch_id(cls):
        now = time.time()
        if (now - cls._batch_ts) > 1.0 or not cls._batch_id:
            cls._batch_seq += 1
            cls._batch_id = f"quote-batch-{cls._batch_seq}"
            cls._batch_ts = now
        return cls._batch_id

    def fetch_stock(
        self,
        symbol="AAPL",
        preferred_provider=None,
        preferred_providers=None,
        exclude_providers=None,
        cache_max_age_seconds=None,
        bypass_cache=False,
        protected_tier1=False,
        use_selective_backups=False,
    ):
        asset_type = self._asset_type_for_symbol(symbol)
        batch_id = self._active_batch_id()
        pref_list = []
        if preferred_provider:
            pref_list.append(str(preferred_provider).upper())
        if preferred_providers:
            pref_list.extend([str(p).upper() for p in preferred_providers if p])
        dedup_pref = []
        for p in pref_list:
            if p and p not in dedup_pref:
                dedup_pref.append(p)
        quote = self._router.get_quote(
            symbol=symbol,
            asset_type=asset_type,
            batch_id=batch_id,
            preferred_providers=dedup_pref or None,
            exclude_providers=exclude_providers,
            cache_max_age_seconds=cache_max_age_seconds,
            bypass_cache=bypass_cache,
            protected_tier1=protected_tier1,
            use_selective_backups=use_selective_backups,
        )
        return {
            "symbol": str(symbol).upper(),
            "price": float(quote.get("price", 0.0) or 0.0),
            "prev_close": quote.get("prev_close"),
            "source": quote.get("provider_used", "none"),
            "provider_used": quote.get("provider_used", "none"),
            "provider_agreement": float(quote.get("provider_agreement", 0.0) or 0.0),
            "quote_quality": quote.get("quote_quality", "placeholder"),
            "cache_hit": bool(quote.get("cache_hit", False)),
            "feed_degraded_reason": quote.get("data_unavailable_reason"),
            "data_unavailable_reason": quote.get("data_unavailable_reason"),
            "valid_quote": bool(quote.get("valid_quote", False)),
            "rejection_reason": quote.get("rejection_reason"),
            "raw_price_present": bool(quote.get("raw_price_present", False)),
            "raw_prev_close_present": bool(quote.get("raw_prev_close_present", False)),
            "quote_batch_id": batch_id,
            "quote_timestamp": quote.get("quote_timestamp"),
            "quote_age_seconds": quote.get("quote_age_seconds"),
            "provider_attempt_count": int(quote.get("provider_attempt_count", 0) or 0),
            "provider_success_count": int(quote.get("provider_success_count", 0) or 0),
            "attempted_providers": list(quote.get("attempted_providers") or []),
            "cycle_trace": list(quote.get("cycle_trace") or []),
        }

    def fetch_stock_batch(
        self,
        symbols,
        preferred_providers_by_symbol=None,
        exclude_providers_by_symbol=None,
        cache_max_age_seconds=None,
        bypass_cache=False,
        protected_tier1_symbols=None,
        selective_backup_symbols=None,
    ):
        GuardianSecureAPI._batch_seq += 1
        GuardianSecureAPI._batch_id = f"quote-batch-{GuardianSecureAPI._batch_seq}"
        GuardianSecureAPI._batch_ts = time.time()
        out = []
        protected_set = {str(s).upper() for s in (protected_tier1_symbols or [])}
        selective_set = {str(s).upper() for s in (selective_backup_symbols or [])}
        for sym in symbols or []:
            symbol = str(sym).upper()
            out.append(
                self.fetch_stock(
                    symbol,
                    preferred_providers=(preferred_providers_by_symbol or {}).get(symbol),
                    exclude_providers=(exclude_providers_by_symbol or {}).get(symbol),
                    cache_max_age_seconds=cache_max_age_seconds,
                    bypass_cache=bypass_cache,
                    protected_tier1=bool(symbol in protected_set),
                    use_selective_backups=bool(symbol in selective_set),
                )
            )
        return out

    def _fallback_provider_status(self, rows, symbol):
        if not isinstance(rows, list):
            return rows
        if any(bool((r or {}).get("success_boolean", False)) for r in rows):
            return rows

        # 1) Prefer cached quote evidence if available.
        cached = get_cache("price", "ANY", str(symbol or "AAPL").upper(), "quote", ttl=300)
        if isinstance(cached, dict):
            price = float(cached.get("price", 0.0) or 0.0)
            prev = float(cached.get("prev_close", 0.0) or 0.0)
            src = str(cached.get("source") or "").upper()
            if price > 0 and prev > 0 and src:
                for row in rows:
                    if str(row.get("provider_name", "")).upper() == src:
                        row["success_boolean"] = True
                        row["parsed_price"] = price
                        row["parsed_prev_close"] = prev
                        row["error"] = "dns_fallback_cached_quote"
                        row["health_source"] = "cached_quote"
                        return rows

        # 2) If all DNS tests failed, mark one key-loaded, non-cooldown provider as degraded-healthy.
        key_map = {}
        for p, k in self._stock_pool + self._crypto_pool:
            if k and not str(k).startswith("YOUR_"):
                key_map[str(p).upper()] = True
        preferred = ["FINNHUB", "POLYGON", "TWELVEDATA", "ALPACA", "EODHD", "ALPHAVANTAGE", "MORALIS"]
        rows_by_name = {str((r or {}).get("provider_name", "")).upper(): r for r in rows}
        for name in preferred:
            row = rows_by_name.get(name)
            if not row or not key_map.get(name, False):
                continue
            if str(row.get("provider_cooldown_state", "active")).lower() == "cooldown":
                continue
            row["success_boolean"] = True
            row["error"] = "dns_fallback_key_loaded"
            row["health_source"] = "key_presence"
            row["degraded"] = True
            return rows

        return rows

    def provider_status(self, symbol="AAPL"):
        now = time.time()
        cached = GuardianSecureAPI._provider_status_cache
        cache_symbol = str(cached.get("symbol", "")).upper()
        req_symbol = str(symbol or "AAPL").upper()
        crypto_symbols = {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "DOT", "LINK"}
        asset_type = "crypto" if req_symbol in crypto_symbols else "stock"
        providers = (
            ["MORALIS", "FINNHUB", "POLYGON", "TWELVEDATA", "ALPHAVANTAGE"]
            if asset_type == "crypto"
            else ["FMP", "ALPHAVANTAGE", "TWELVEDATA", "FINNHUB", "POLYGON", "EODHD", "ALPACA"]
        )
        if cached.get("rows") and cache_symbol == req_symbol and (now - float(cached.get("ts", 0.0))) <= self._provider_status_ttl:
            return list(cached.get("rows", []))

        rows = []
        pools = dict(self._stock_pool)
        manager_map = {
            str(r.get("provider", "")).upper(): r
            for r in get_provider_status_summary()
            if isinstance(r, dict)
        }
        for provider in providers:
            key = pools.get(provider) or dict(self._crypto_pool).get(provider)
            dns_ok = GuardianSecureAPI._dns_status.get(provider, False)
            parsed_price = 0.0
            parsed_prev_close = None
            success = False
            http_status = None
            error = None
            field_path = ""
            if key and dns_ok and not str(key).startswith("YOUR_"):
                if provider == "FMP" and self._fmp_probe_hard_limited():
                    success = False
                    http_status = 429
                    error = "fmp_rest_probe_skipped_hard_limit"
                    field_path = "skipped:hard_limit"
                else:
                    diag = self._router.test_provider_quote(
                        provider=provider,
                        symbol=symbol,
                        asset_type=asset_type,
                    )
                    parsed_price = diag.get("parsed_price", 0.0)
                    parsed_prev_close = diag.get("parsed_prev_close")
                    success = bool(diag.get("success_boolean", False))
                    http_status = diag.get("http_status")
                    error = diag.get("error")
                    field_path = diag.get("field_path", "")
            mgr = manager_map.get(provider, {})
            rows.append(
                {
                    "provider_name": provider,
                    "dns_ok": bool(dns_ok),
                    "http_status": http_status,
                    "parsed_price": parsed_price,
                    "parsed_prev_close": parsed_prev_close,
                    "field_path": field_path,
                    "error": error,
                    "success_boolean": bool(success),
                    "provider_calls_last_minute": int(mgr.get("provider_calls_last_minute", 0) or 0),
                    "provider_success_rate": float(mgr.get("provider_success_rate", 0.0) or 0.0),
                    "provider_cooldown_state": mgr.get("provider_cooldown_state", "active"),
                    "provider_average_latency": float(mgr.get("provider_average_latency", 0.0) or 0.0),
                    "rest_probe_skipped_due_to_hard_limit": bool(provider == "FMP" and self._fmp_probe_hard_limited()),
                }
            )
        rows = self._fallback_provider_status(rows, symbol=req_symbol)
        GuardianSecureAPI._provider_status_cache = {
            "ts": time.time(),
            "symbol": req_symbol,
            "rows": list(rows),
        }
        return rows

    def provider_diagnostics(self):
        return self._router.diagnostics()
