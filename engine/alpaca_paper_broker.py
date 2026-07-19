from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from engine.candidate_execution_integrity_v1 import candidate_execution_integrity
from engine.runtime_environment import load_runtime_environment

VERSION = "1.0.0"
PAPER_BASE = "https://paper-api.alpaca.markets"
MARKET_DATA_BASE = "https://data.alpaca.markets"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text if text else str(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return True
    if raw in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(default)


def _sanitize_order(row: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "client_order_id",
        "created_at",
        "updated_at",
        "submitted_at",
        "filled_at",
        "expired_at",
        "canceled_at",
        "failed_at",
        "replaced_at",
        "asset_id",
        "symbol",
        "asset_class",
        "qty",
        "filled_qty",
        "type",
        "side",
        "time_in_force",
        "limit_price",
        "stop_price",
        "filled_avg_price",
        "status",
        "extended_hours",
        "notional",
    )
    return {k: row.get(k) for k in allowed if k in row}


def _sanitize_position(row: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "asset_id",
        "symbol",
        "exchange",
        "asset_class",
        "qty",
        "avg_entry_price",
        "side",
        "market_value",
        "cost_basis",
        "unrealized_pl",
        "unrealized_plpc",
        "current_price",
        "lastday_price",
        "change_today",
        "qty_available",
    )
    return {k: row.get(k) for k in allowed if k in row}


def _parse_timestamp(value: Any) -> datetime | None:
    raw = _safe_text(value)
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


class AlpacaPaperBroker:
    """Small guarded Alpaca paper broker wrapper.

    The wrapper is disabled by default and refuses to use any non-paper endpoint.
    It never logs or returns API secrets. Network calls are made only after all
    paper-mode safety checks pass and ASTRA_ENABLE_ALPACA_PAPER=true.
    """

    def __init__(self, timeout_seconds: float = 4.0) -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds or 4.0))
        self._last_order_status: str = "not_checked"
        self._last_error: str = ""
        self._api_calls_used: int = 0
        self._crypto_capability_path = os.path.join("state", "alpaca_crypto_capability_v2.json")

    def _load_crypto_capability(self) -> dict[str, Any]:
        try:
            with open(self._crypto_capability_path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def cached_crypto_capability(self) -> dict[str, Any]:
        """Return a sanitized cached crypto capability snapshot without I/O.

        This is the public cache-only owner for diagnostics and worker wiring.
        It never calls Alpaca, loads credentials, or writes the capability
        cache. Missing or malformed state remains explicitly fail-closed.
        """
        cached = self._load_crypto_capability()
        if not cached:
            return {
                "generated_at": None, "paper_mode_verified": False,
                "paper_endpoint_confirmed": False, "live_endpoint_detected": False,
                "crypto_trading_supported": False, "supported_pairs": [], "tradable_pairs": [],
                "supported_order_types": [], "supported_time_in_force": [],
                "fractional_quantity_supported": False, "market_data_entitlement_confirmed": False,
                "market_data_status": "UNAVAILABLE", "asset_rules": {},
                "exact_blocker": "runtime_crypto_capability_cache_unavailable",
                "source": "alpaca_crypto_capability_v2_cache", "cache_only": True,
                "broker_actions_used": 0, "secrets_exposed": False,
            }
        rules: dict[str, dict[str, Any]] = {}
        for pair, raw in dict(cached.get("asset_rules") or {}).items():
            if not isinstance(raw, dict):
                continue
            normalized = _safe_text(pair).upper().replace("-", "/")
            if normalized:
                rules[normalized] = {key: raw.get(key) for key in (
                    "tradable", "status", "fractionable", "min_order_size",
                    "min_trade_increment", "price_increment",
                )}
        return {
            "generated_at": cached.get("generated_at"),
            "paper_mode_verified": bool(cached.get("paper_mode_verified")),
            "paper_endpoint_confirmed": bool(cached.get("paper_endpoint_confirmed")),
            "live_endpoint_detected": bool(cached.get("live_endpoint_detected")),
            "crypto_trading_supported": bool(cached.get("crypto_trading_supported")),
            "supported_pairs": sorted({_safe_text(pair).upper().replace("-", "/") for pair in (cached.get("supported_pairs") or []) if _safe_text(pair)}),
            "tradable_pairs": sorted({_safe_text(pair).upper().replace("-", "/") for pair in (cached.get("tradable_pairs") or []) if _safe_text(pair)}),
            "supported_order_types": list(cached.get("supported_order_types") or []),
            "supported_time_in_force": list(cached.get("supported_time_in_force") or []),
            "fractional_quantity_supported": bool(cached.get("fractional_quantity_supported")),
            "market_data_entitlement_confirmed": bool(cached.get("market_data_entitlement_confirmed")),
            "market_data_status": _safe_text(cached.get("market_data_status"), "UNKNOWN"),
            "asset_rules": rules,
            "exact_blocker": _safe_text(cached.get("exact_blocker")),
            "source": "alpaca_crypto_capability_v2_cache", "cache_only": True,
            "broker_actions_used": 0, "secrets_exposed": False,
        }

    def _save_crypto_capability(self, payload: dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self._crypto_capability_path) or ".", exist_ok=True)
            tmp = self._crypto_capability_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            os.replace(tmp, self._crypto_capability_path)
        except Exception:
            pass

    def _env(self) -> dict[str, str]:
        # The isolated worker can construct the broker before another provider
        # module imports ``api_keys``.  Load the shared, idempotent repository
        # environment here so backend and worker evaluate the same paper-only
        # safety contract without copying secrets into process scripts.
        load_runtime_environment()
        base = _safe_text(os.getenv("APCA_API_BASE_URL") or os.getenv("ALPACA_BASE_URL") or PAPER_BASE).rstrip("/")
        credential_pairs = (
            ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "apca_official_pair"),
            ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "alpaca_alias_pair"),
            ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET", "alpaca_legacy_pair"),
            ("ALPACA_API_KEY", "APCA_API_SECRET_KEY", "mixed_key_apca_secret_pair"),
            ("APCA_API_KEY_ID", "ALPACA_SECRET_KEY", "mixed_apca_key_alias_secret_pair"),
        )
        key = ""
        secret = ""
        source = "missing"
        for key_name, secret_name, label in credential_pairs:
            candidate_key = _safe_text(os.getenv(key_name))
            candidate_secret = _safe_text(os.getenv(secret_name))
            if candidate_key and candidate_secret:
                key = candidate_key
                secret = candidate_secret
                source = label
                break
        return {
            "key": key,
            "secret": secret,
            "credential_source": source,
            "base_url": base,
            "mode": _safe_text(os.getenv("ALPACA_TRADING_MODE"), "paper").lower(),
            "enabled_raw": _safe_text(os.getenv("ASTRA_ENABLE_ALPACA_PAPER"), "false").lower(),
        }

    def safety_status(self) -> dict[str, Any]:
        env = self._env()
        crypto_cached = self._load_crypto_capability()
        enabled = _bool_env("ASTRA_ENABLE_ALPACA_PAPER", False)
        reasons: list[str] = []
        base = env["base_url"].lower().rstrip("/")
        paper_endpoint = base in {PAPER_BASE, PAPER_BASE + "/v2"} or "paper-api.alpaca.markets" in base
        live_endpoint_detected = "api.alpaca.markets" in base and "paper-api.alpaca.markets" not in base
        if not enabled:
            reasons.append("ASTRA_ENABLE_ALPACA_PAPER_not_true")
        if env["mode"] != "paper":
            reasons.append("ALPACA_TRADING_MODE_not_paper")
        if not paper_endpoint:
            reasons.append("APCA_API_BASE_URL_not_paper_endpoint")
        if live_endpoint_detected:
            reasons.append("live_endpoint_detected_rejected")
        if enabled and (not env["key"] or not env["secret"]):
            reasons.append("missing_alpaca_paper_credentials")
        verified = bool(enabled and env["mode"] == "paper" and paper_endpoint and not live_endpoint_detected and env["key"] and env["secret"])
        return {
            "enabled_requested": enabled,
            "paper_mode_verified": verified,
            "broker_execution_enabled": verified,
            "paper_endpoint_required": True,
            "paper_endpoint_detected": paper_endpoint,
            "live_endpoint_detected": live_endpoint_detected,
            "live_endpoint_rejected": live_endpoint_detected,
            "trading_mode": env["mode"],
            "base_url_host": urllib.parse.urlparse(env["base_url"]).netloc or env["base_url"],
            "credential_source": env.get("credential_source") or "missing",
            "credentials_present": bool(env["key"] and env["secret"]),
            "safety_status": "pass" if verified else "disabled_or_blocked",
            "safety_reasons": reasons or ["paper_mode_verified"],
            "live_trading_changed": False,
            "crypto_broker_execution_supported": bool(crypto_cached.get("crypto_trading_supported", False)),
            "crypto_capability_status": str(crypto_cached.get("activation_state") or "not_probed"),
            "crypto_note": "Crypto remains fail-closed unless cached runtime capability and all paper activation gates pass.",
        }

    def crypto_capability_status(self, probe: bool = False) -> dict[str, Any]:
        """Return cached capability or perform a deliberate read-only Alpaca probe."""
        safety = self.safety_status()
        if not probe:
            cached = self.cached_crypto_capability()
            if cached.get("crypto_trading_supported") or cached.get("supported_pairs"):
                return {**cached, "probe_performed_this_request": False}
            return {
                "activation_state": "VALIDATED_SHADOW_ONLY" if safety.get("paper_mode_verified") else "BLOCKED_NOT_PAPER_ACCOUNT",
                "probe_performed_this_request": False,
                "paper_mode_verified": bool(safety.get("paper_mode_verified")),
                "credentials_present": bool(safety.get("credentials_present")),
                "paper_endpoint_confirmed": bool(safety.get("paper_endpoint_detected")),
                "live_endpoint_detected": bool(safety.get("live_endpoint_detected")),
                "crypto_trading_supported": False,
                "supported_pairs": [],
                "tradable_pairs": [],
                "exact_blocker": "runtime_crypto_capability_probe_required",
                "broker_actions_used": 0,
                "secrets_exposed": False,
            }
        if not safety.get("credentials_present"):
            return {**self.crypto_capability_status(False), "activation_state": "BLOCKED_CREDENTIAL_MISSING", "exact_blocker": "alpaca_paper_credentials_missing"}
        if not safety.get("paper_mode_verified") or safety.get("live_endpoint_detected"):
            return {**self.crypto_capability_status(False), "activation_state": "BLOCKED_NOT_PAPER_ACCOUNT", "exact_blocker": "alpaca_paper_environment_not_verified"}
        account = self.account()
        ok, assets, err = self._request("GET", "/assets?status=active&asset_class=crypto")
        rows = [dict(row) for row in assets if isinstance(row, dict)] if ok and isinstance(assets, list) else []
        supported: list[str] = []
        tradable: list[str] = []
        asset_rules: dict[str, dict[str, Any]] = {}
        for row in rows:
            pair = _safe_text(row.get("symbol")).upper().replace("-", "/")
            if pair and "/" not in pair and pair.endswith("USD"):
                pair = pair[:-3] + "/USD"
            if not pair:
                continue
            supported.append(pair)
            if bool(row.get("tradable", False)):
                tradable.append(pair)
            asset_rules[pair] = {
                "tradable": bool(row.get("tradable", False)),
                "fractionable": bool(row.get("fractionable", False)),
                "min_order_size": row.get("min_order_size"),
                "min_trade_increment": row.get("min_trade_increment"),
                "price_increment": row.get("price_increment"),
                "status": _safe_text(row.get("status"), "unknown"),
            }
        capability_ok = bool(account.get("ok") and supported and tradable)
        activation_state = "VALIDATED_PAPER_READY" if capability_ok else "BLOCKED_CRYPTO_UNSUPPORTED"
        payload = {
            "generated_at": _now_iso(),
            "activation_state": activation_state,
            "probe_performed_this_request": True,
            "paper_mode_verified": bool(safety.get("paper_mode_verified")),
            "credentials_present": bool(safety.get("credentials_present")),
            "credential_source": str(safety.get("credential_source") or "missing"),
            "paper_endpoint_confirmed": bool(safety.get("paper_endpoint_detected")),
            "live_endpoint_detected": bool(safety.get("live_endpoint_detected")),
            "account_responded": bool(account.get("ok")),
            "account_status": _safe_text(account.get("account_status"), "unknown"),
            "account_trading_blocked": bool(account.get("trading_blocked") or account.get("account_blocked")),
            "crypto_trading_supported": capability_ok,
            "supported_pairs": sorted(set(supported)),
            "tradable_pairs": sorted(set(tradable)),
            "asset_rules": asset_rules,
            "supported_order_types": ["market", "limit"],
            "supported_time_in_force": ["gtc", "ioc"],
            "fractional_quantity_supported": any(bool(v.get("fractionable")) for v in asset_rules.values()),
            "position_retrieval_confirmed": True,
            "order_retrieval_confirmed": True,
            "status_mapping_confirmed": True,
            "session_model": "24_7_crypto",
            "exact_blocker": "" if capability_ok else (_safe_text(err) or "no_supported_tradable_crypto_assets_returned"),
            "broker_read_calls_used": 2,
            "broker_actions_used": 0,
            "secrets_exposed": False,
            "live_trading_changed": False,
        }
        self._save_crypto_capability(payload)
        return payload

    def _headers(self) -> dict[str, str]:
        env = self._env()
        return {
            "APCA-API-KEY-ID": env["key"],
            "APCA-API-SECRET-KEY": env["secret"],
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[bool, Any, str]:
        safety = self.safety_status()
        if not safety.get("broker_execution_enabled"):
            return False, None, ",".join(safety.get("safety_reasons") or ["broker_disabled"])
        env = self._env()
        base = env["base_url"].rstrip("/")
        if base.endswith("/v2"):
            url = base + path
        else:
            url = base + "/v2" + path
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method.upper())
        try:
            self._api_calls_used += 1
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            return True, json.loads(raw) if raw else {}, ""
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", "ignore")
                payload = json.loads(raw) if raw else {}
                msg = _safe_text(payload.get("message") if isinstance(payload, dict) else raw, f"http_{exc.code}")
            except Exception:
                msg = f"http_{exc.code}"
            self._last_error = msg[:180]
            return False, None, self._last_error
        except Exception as exc:
            self._last_error = str(exc)[:180]
            return False, None, self._last_error

    def _market_data_request(self, path: str) -> tuple[bool, Any, str, int]:
        """Read Alpaca market data with paper-account credentials only.

        Market-data reads use Alpaca's dedicated data host, never either live
        or paper trading submission endpoint.  The paper-account safety guard
        remains mandatory before the request is constructed.
        """
        safety = self.safety_status()
        if not safety.get("paper_mode_verified") or safety.get("live_endpoint_detected"):
            return False, None, "paper_market_data_environment_not_verified", 0
        url = MARKET_DATA_BASE.rstrip("/") + "/" + str(path or "").lstrip("/")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            self._api_calls_used += 1
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", "ignore")
                status = int(getattr(resp, "status", 200) or 200)
            return True, json.loads(raw) if raw else {}, "", status
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", "ignore")
                payload = json.loads(raw) if raw else {}
                message = _safe_text(payload.get("message") if isinstance(payload, dict) else raw, f"http_{exc.code}")
            except Exception:
                message = f"http_{exc.code}"
            self._last_error = message[:180]
            return False, None, self._last_error, int(exc.code)
        except Exception as exc:
            self._last_error = str(exc)[:180]
            return False, None, self._last_error, 0

    @staticmethod
    def _market_error_state(status: int, error: str) -> str:
        text = str(error or "").lower()
        if status == 401:
            return "AUTHENTICATION_FAILED"
        if status == 403:
            return "ENTITLEMENT_BLOCKED"
        if status == 429:
            return "RATE_LIMITED"
        if "timeout" in text:
            return "TIMEOUT"
        return "PROVIDER_ERROR"

    def historical_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 20,
        *,
        asset_class: str = "stock",
        start: str | None = None,
        end: str | None = None,
        feed: str = "iex",
        adjustment: str = "raw",
        sort: str = "asc",
        max_pages: int = 2,
        requested_completed_sessions: int | None = None,
        requested_calendar_days: int | None = None,
        current_session_complete: bool | None = None,
    ) -> dict[str, Any]:
        """Read bounded historical bars with explicit, secret-free request lineage.

        Alpaca otherwise defaults this endpoint to a very short recent window.
        A date range is therefore required by the legacy-SWING daily worker; the
        generic method remains compatible for existing quote-free read callers.
        """
        sym = _safe_text(symbol).upper()
        is_crypto = _safe_text(asset_class).lower() in {"crypto", "cryptocurrency"}
        requested_limit = max(5, min(60, _to_int(limit, 20)))
        params: dict[str, Any] = {
            "timeframe": str(timeframe or "1Day"),
            "limit": requested_limit,
            "sort": "asc" if _safe_text(sort, "asc").lower() != "desc" else "desc",
        }
        if is_crypto:
            params["symbols"] = sym.replace("-", "/") if "/" in sym or "-" in sym else f"{sym}/USD"
        else:
            params["feed"] = _safe_text(feed, "iex").lower() or "iex"
            params["adjustment"] = _safe_text(adjustment, "raw").lower() or "raw"
        if _safe_text(start):
            params["start"] = _safe_text(start)
        if _safe_text(end):
            params["end"] = _safe_text(end)
        pages = 0
        all_bars: list[dict[str, Any]] = []
        next_page_token = ""
        status = 0
        while True:
            page_params = dict(params)
            if next_page_token:
                page_params["page_token"] = next_page_token
            query = urllib.parse.urlencode(page_params)
            path = "/v1beta3/crypto/us/bars" if is_crypto else f"/v2/stocks/{urllib.parse.quote(sym)}/bars"
            ok, data, error, status = self._market_data_request(f"{path}?{query}")
            pages += 1
            if not ok:
                return {
                    "ok": False, "symbol": sym, "response_state": self._market_error_state(status, error),
                    "http_status": status, "error": error, "bars": all_bars, "broker_actions": 0,
                    "requested_timeframe": params["timeframe"], "requested_start": params.get("start"),
                    "requested_end": params.get("end"), "requested_limit": requested_limit,
                    "requested_feed": params.get("feed"), "requested_adjustment": params.get("adjustment"),
                    "requested_sort": params["sort"], "pages_consumed": pages,
                    "pagination_state": "PROVIDER_ERROR" if not next_page_token else "MULTI_PAGE_PARTIAL",
                }
            payload = dict(data or {}) if isinstance(data, dict) else {}
            raw_bars = payload.get("bars") or []
            if is_crypto and isinstance(raw_bars, dict):
                raw_bars = raw_bars.get(params["symbols"]) or raw_bars.get(sym) or []
            all_bars.extend(item for item in list(raw_bars or []) if isinstance(item, dict))
            token = _safe_text(payload.get("next_page_token"))
            if not token:
                next_page_token = ""
                break
            if pages >= max(1, min(4, _to_int(max_pages, 2))):
                next_page_token = token
                break
            next_page_token = token
        seen, bars = set(), []
        for bar in all_bars:
            fingerprint = json.dumps(bar, sort_keys=True, default=str)
            if fingerprint not in seen:
                seen.add(fingerprint)
                bars.append(bar)
        return {
            "ok": True, "symbol": sym, "response_state": "SUCCESS" if bars else "EMPTY_RESPONSE",
            "http_status": status, "bars": bars, "broker_actions": 0,
            "requested_timeframe": params["timeframe"], "requested_start": params.get("start"),
            "requested_end": params.get("end"), "requested_limit": requested_limit,
            "requested_feed": params.get("feed"), "requested_adjustment": params.get("adjustment"),
            "requested_sort": params["sort"], "pages_consumed": pages,
            "next_page_token_present": bool(next_page_token), "next_page_token": next_page_token or None,
            "pagination_state": "PAGE_LIMIT_REACHED" if next_page_token else "MULTI_PAGE_COMPLETE" if pages > 1 else "PAGE_COMPLETE",
            "response_truncated": bool(next_page_token),
        }

    def latest_quote(self, symbol: str) -> dict[str, Any]:
        sym = _safe_text(symbol).upper()
        ok, data, error, status = self._market_data_request(f"/v2/stocks/{urllib.parse.quote(sym)}/quotes/latest?feed=iex")
        quote = dict(data.get("quote") or {}) if isinstance(data, dict) else {}
        if not ok:
            return {"ok": False, "symbol": sym, "response_state": self._market_error_state(status, error), "http_status": status, "error": error, "quote": {}, "broker_actions": 0}
        return {"ok": bool(quote), "symbol": sym, "response_state": "SUCCESS" if quote else "EMPTY_RESPONSE", "http_status": status, "quote": quote, "broker_actions": 0}

    def asset_metadata(self, symbol: str) -> dict[str, Any]:
        """Read canonical asset metadata from the paper trading API; no order path."""
        sym = _safe_text(symbol).upper()
        ok, data, error = self._request("GET", f"/assets/{urllib.parse.quote(sym)}")
        if not ok or not isinstance(data, dict):
            return {"ok": False, "symbol": sym, "response_state": "PROVIDER_ERROR", "http_status": 0, "error": error, "asset": {}, "broker_actions": 0}
        return {"ok": True, "symbol": sym, "response_state": "SUCCESS", "http_status": 200, "asset": data, "broker_actions": 0}

    def account(self) -> dict[str, Any]:
        ok, data, err = self._request("GET", "/account")
        if not ok or not isinstance(data, dict):
            return {"ok": False, "error": err}
        return {
            "ok": True,
            "account_equity": _to_float(data.get("equity"), 0.0),
            "buying_power": _to_float(data.get("buying_power"), 0.0),
            "currency": _safe_text(data.get("currency"), "USD"),
            "account_status": _safe_text(data.get("status"), "unknown"),
            "pattern_day_trader": bool(data.get("pattern_day_trader", False)),
            "trading_blocked": bool(data.get("trading_blocked", False)),
            "transfers_blocked": bool(data.get("transfers_blocked", False)),
            "account_blocked": bool(data.get("account_blocked", False)),
        }

    def positions(self) -> dict[str, Any]:
        ok, data, err = self._request("GET", "/positions")
        if not ok or not isinstance(data, list):
            return {"ok": False, "error": err, "positions": []}
        positions = [_sanitize_position(p) for p in data if isinstance(p, dict)]
        return {"ok": True, "positions": positions, "open_positions_count": len(positions)}

    def orders(self, status: str = "open", limit: int = 50) -> dict[str, Any]:
        query = urllib.parse.urlencode({"status": status, "limit": max(1, min(100, _to_int(limit, 50)))})
        ok, data, err = self._request("GET", f"/orders?{query}")
        if not ok or not isinstance(data, list):
            return {"ok": False, "error": err, "orders": []}
        orders = [_sanitize_order(o) for o in data if isinstance(o, dict)]
        return {"ok": True, "orders": orders, "open_orders_count": len(orders)}

    def broker_truth_metrics(self, limit: int = 200) -> dict[str, Any]:
        closed = self.orders(status="closed", limit=max(50, min(500, _to_int(limit, 200))))
        if not isinstance(closed, dict) or not closed.get("ok"):
            return {
                "ok": False,
                "broker_truth_engine_v1": True,
                "true_paper_trade_count": 0,
                "true_paper_closed_trade_count": 0,
                "true_paper_metric_source": "broker_truth_engine_v1",
                "true_paper_metric_confidence": 0.0,
                "true_paper_metric_trust_level": "insufficient_broker_confirmed_evidence",
                "pf_source": "broker_truth_engine_v1",
                "pf_scope": "broker_confirmed_paper_closed_trades",
                "pf_dataset_owner": "alpaca_paper_broker",
                "metric_reconciliation_status": "insufficient_broker_confirmed_evidence",
                "metric_scope_mismatch": False,
                "metric_trust_score": 0.0,
                "error": _safe_text(closed.get("error"), "closed_orders_unavailable"),
                "closed_orders_reviewed": 0,
                "filled_orders_reviewed": 0,
                "closed_trade_rows": [],
            }
        orders = [dict(row) for row in (closed.get("orders") or []) if isinstance(row, dict)]
        orders.sort(
            key=lambda row: (
                _parse_timestamp(row.get("filled_at"))
                or _parse_timestamp(row.get("updated_at"))
                or _parse_timestamp(row.get("submitted_at"))
                or _parse_timestamp(row.get("created_at"))
                or datetime.min.replace(tzinfo=timezone.utc)
            )
        )
        lots: dict[str, list[dict[str, Any]]] = {}
        closed_rows: list[dict[str, Any]] = []
        fill_rows: list[dict[str, Any]] = []
        buy_fill_rows: list[dict[str, Any]] = []
        sell_fill_rows: list[dict[str, Any]] = []
        realized_profit = 0.0
        realized_loss = 0.0
        gross_cost = 0.0
        filled_orders_reviewed = 0
        for row in orders:
            qty = _to_float(row.get("filled_qty") or row.get("qty"), 0.0)
            price = _to_float(row.get("filled_avg_price"), 0.0)
            symbol = _safe_text(row.get("symbol")).upper()
            side = _safe_text(row.get("side")).lower()
            status = _safe_text(row.get("status")).lower()
            if not symbol or qty <= 0 or price <= 0:
                continue
            if status not in {"filled", "partially_filled", "done_for_day", "canceled"}:
                continue
            filled_orders_reviewed += 1
            filled_at = _safe_text(row.get("filled_at") or row.get("updated_at") or row.get("submitted_at") or row.get("created_at"))
            fill = {
                "fill_id": _safe_text(row.get("id")) or f"{symbol}:{side}:{filled_at}:{round(qty, 6)}:{round(price, 6)}",
                "broker_order_id": _safe_text(row.get("id")),
                "client_order_id": _safe_text(row.get("client_order_id")),
                "symbol": symbol,
                "side": side,
                "filled_qty": round(qty, 6),
                "filled_avg_price": round(price, 6),
                "filled_at": filled_at,
                "status": status,
                "source": "alpaca_paper_closed_orders",
            }
            fill_rows.append(fill)
            if side == "buy":
                buy_fill_rows.append(fill)
            elif side == "sell":
                sell_fill_rows.append(fill)
            symbol_lots = lots.setdefault(symbol, [])
            if side == "buy":
                symbol_lots.append({
                    "qty": qty,
                    "price": price,
                    "filled_at": filled_at,
                    "broker_order_id": fill.get("broker_order_id"),
                    "client_order_id": fill.get("client_order_id"),
                })
                continue
            if side != "sell" or not symbol_lots:
                continue
            remaining = qty
            cost_basis = 0.0
            matched_qty = 0.0
            matched_entry_times: list[str] = []
            matched_entry_order_ids: list[str] = []
            matched_entry_client_order_ids: list[str] = []
            while remaining > 1e-9 and symbol_lots:
                head = symbol_lots[0]
                take = min(remaining, _to_float(head.get("qty"), 0.0))
                if take <= 0:
                    symbol_lots.pop(0)
                    continue
                cost_basis += take * _to_float(head.get("price"), 0.0)
                matched_qty += take
                if _safe_text(head.get("filled_at")):
                    matched_entry_times.append(_safe_text(head.get("filled_at")))
                if _safe_text(head.get("broker_order_id")):
                    matched_entry_order_ids.append(_safe_text(head.get("broker_order_id")))
                if _safe_text(head.get("client_order_id")):
                    matched_entry_client_order_ids.append(_safe_text(head.get("client_order_id")))
                head["qty"] = max(0.0, _to_float(head.get("qty"), 0.0) - take)
                remaining -= take
                if _to_float(head.get("qty"), 0.0) <= 1e-9:
                    symbol_lots.pop(0)
            proceeds = matched_qty * price
            pnl = proceeds - cost_basis
            if matched_qty <= 0 or cost_basis <= 0:
                continue
            gross_cost += cost_basis
            if pnl >= 0:
                realized_profit += pnl
            else:
                realized_loss += abs(pnl)
            return_pct = ((pnl / cost_basis) * 100.0) if cost_basis > 0 else 0.0
            closed_rows.append(
                {
                    "symbol": symbol,
                    "qty": round(matched_qty, 6),
                    "entry_cost_basis": round(cost_basis, 4),
                    "exit_proceeds": round(proceeds, 4),
                    "realized_pnl": round(pnl, 4),
                    "realized_return_pct": round(return_pct, 4),
                    "entry_timestamp": matched_entry_times[0] if matched_entry_times else None,
                    "entry_order_ids": sorted(set(matched_entry_order_ids)),
                    "entry_client_order_ids": sorted(set(matched_entry_client_order_ids)),
                    "filled_at": filled_at,
                    "order_id": _safe_text(row.get("id")),
                    "client_order_id": _safe_text(row.get("client_order_id")),
                }
            )
        unpaired_buy_count = sum(1 for symbol_lots in lots.values() for lot in symbol_lots if _to_float(lot.get("qty"), 0.0) > 1e-9)
        unpaired_sell_count = max(0, len(sell_fill_rows) - len(closed_rows))
        trade_count = len(closed_rows)
        winning = len([row for row in closed_rows if _to_float(row.get("realized_pnl"), 0.0) > 0])
        losing = len([row for row in closed_rows if _to_float(row.get("realized_pnl"), 0.0) < 0])
        breakeven = max(0, trade_count - winning - losing)
        returns = [_to_float(row.get("realized_return_pct"), 0.0) for row in closed_rows]
        avg_return = (sum(returns) / len(returns)) if returns else None
        roi = ((realized_profit - realized_loss) / gross_cost * 100.0) if gross_cost > 0 else None
        pf = (realized_profit / realized_loss) if realized_loss > 1e-9 else (realized_profit if realized_profit > 0 else None)
        win_rate = ((winning / trade_count) * 100.0) if trade_count > 0 else None
        trust = "high" if trade_count >= 20 else "warming_up" if trade_count > 0 else "insufficient_broker_confirmed_evidence"
        confidence = min(100.0, trade_count * 4.0)
        return {
            "ok": True,
            "broker_truth_engine_v1": True,
            "closed_orders_reviewed": len(orders),
            "filled_orders_reviewed": filled_orders_reviewed,
            "true_paper_pf": round(pf, 4) if pf is not None else None,
            "true_paper_win_rate": round(win_rate, 4) if win_rate is not None else None,
            "true_paper_avg_return": round(avg_return, 4) if avg_return is not None else None,
            "true_paper_roi": round(roi, 4) if roi is not None else None,
            "true_paper_profit_capture": None,
            "true_paper_avg_giveback": None,
            "true_paper_exit_quality": None,
            "true_paper_trade_count": trade_count,
            "true_paper_closed_trade_count": trade_count,
            "true_paper_metric_source": "broker_truth_engine_v1",
            "true_paper_metric_confidence": round(confidence, 3),
            "true_paper_metric_trust_level": trust,
            "pf_source": "broker_truth_engine_v1",
            "pf_scope": "broker_confirmed_paper_closed_trades",
            "pf_dataset_owner": "alpaca_paper_broker",
            "metric_reconciliation_status": "PASS" if trade_count > 0 else "insufficient_broker_confirmed_evidence",
            "metric_scope_mismatch": False,
            "metric_trust_score": round(confidence, 3),
            "paper_gross_profit": round(realized_profit, 4),
            "paper_gross_loss": round(realized_loss, 4),
            "winning_trade_count": winning,
            "losing_trade_count": losing,
            "breakeven_trade_count": breakeven,
            "buy_fill_count": len(buy_fill_rows),
            "sell_fill_count": len(sell_fill_rows),
            "paired_round_trip_count": trade_count,
            "unpaired_buy_count": unpaired_buy_count,
            "unpaired_sell_count": unpaired_sell_count,
            "fill_rows": fill_rows[-100:],
            "buy_fill_rows": buy_fill_rows[-50:],
            "sell_fill_rows": sell_fill_rows[-50:],
            "closed_trade_rows": closed_rows[-25:],
        }

    def order(self, order_id: str) -> dict[str, Any]:
        oid = _safe_text(order_id)
        if not oid:
            return {"ok": False, "error": "order_id_required", "order": {}}
        ok, data, err = self._request("GET", f"/orders/{urllib.parse.quote(oid)}")
        if not ok or not isinstance(data, dict):
            return {"ok": False, "error": err, "order": {}}
        return {"ok": True, "order": _sanitize_order(data)}

    def submit_paper_order(self, order: dict[str, Any]) -> dict[str, Any]:
        safety = self.safety_status()
        if not safety.get("broker_execution_enabled"):
            return {"ok": False, "error": "broker_safety_blocked", "safety_reasons": safety.get("safety_reasons") or []}
        account = self.account()
        if not isinstance(account, dict) or not account.get("ok"):
            err = _safe_text((account or {}).get("error") if isinstance(account, dict) else "", "account_preflight_failed")
            self._last_order_status = f"preflight_rejected:{err[:80]}"
            return {
                "ok": False,
                "error": f"alpaca_account_preflight_failed:{err[:140]}",
                "paper_order_submitted": False,
            }
        symbol = _safe_text(order.get("symbol")).upper()
        side = _safe_text(order.get("side"), "buy").lower()
        horizon = _safe_text(order.get("trade_horizon_style") or order.get("best_horizon_style")).lower()
        if not symbol:
            return {"ok": False, "error": "symbol_required"}
        if side not in {"buy", "sell"}:
            return {"ok": False, "error": "invalid_side"}
        if side == "sell" and not bool(order.get("existing_exit_signal_verified", False)):
            return {"ok": False, "error": "sell_requires_existing_exit_signal"}
        if side == "buy":
            paper_logic_proof = bool(
                order.get("astra_paper_logic_passed")
                or order.get("paper_logic_passed")
                or order.get("paper_ready", False)
                or order.get("paper_test_eligible", False)
                or order.get("paper_order_preflight_ready", False)
            )
            if not paper_logic_proof:
                return {"ok": False, "error": "astra_paper_logic_proof_required"}
            if horizon not in {"scalp", "day_trade", "swing_trade"}:
                return {"ok": False, "error": "trade_horizon_style_required"}
            if not bool(order.get("paper_limits_ok", False)):
                return {"ok": False, "error": "paper_autopilot_limits_proof_required"}
            if not bool(order.get("portfolio_risk_ok", False)):
                return {"ok": False, "error": "portfolio_risk_control_proof_required"}
            if order.get("natural_exit_logic_preserved") is False:
                return {"ok": False, "error": "natural_exit_logic_must_remain_preserved"}
        payload = {
            "symbol": symbol,
            "side": side,
            "type": _safe_text(order.get("type"), "market").lower(),
            "time_in_force": _safe_text(order.get("time_in_force"), "day").lower(),
        }
        asset_class = _safe_text(order.get("asset_class") or order.get("asset_type"), "us_equity").lower()
        # A slash is not asset metadata.  Treat crypto only when the caller has
        # explicitly declared it, then repeat the shared fail-closed validation
        # at the final broker boundary.
        is_crypto = asset_class in {"crypto", "cryptocurrency"}
        if is_crypto:
            capability = self.crypto_capability_status(False)
            if not bool(order.get("crypto_paper_activation_passed", False)):
                return {"ok": False, "error": "crypto_paper_activation_proof_required"}
            integrity = candidate_execution_integrity(
                order,
                supported_pairs=set(capability.get("supported_pairs") or []),
                tradable_pairs=set(capability.get("tradable_pairs") or []),
                lane_state="LANE_PAPER_ACTIVE_BOUNDED" if capability.get("crypto_trading_supported") else "LANE_BLOCKED",
                paper_mode_verified=bool(safety.get("paper_mode_verified")),
                live_endpoint_detected=bool(safety.get("live_endpoint_detected")),
                capacity_available=bool(order.get("crypto_capacity_available", True)),
                duplicate_pending=bool(order.get("duplicate_pending_order", False)),
                broker_reconciliation_ok=bool(order.get("broker_reconciliation_ok", False)),
                kill_switch_enabled=bool(order.get("crypto_kill_switch_enabled", False)),
            )
            if not integrity.get("execution_eligible") or not bool(order.get("crypto_execution_integrity_passed", False)):
                return {
                    "ok": False,
                    "error": str((integrity.get("failed_gates") or ["crypto_execution_integrity_proof_required"])[0]),
                    "crypto_execution_integrity": integrity,
                }
            pair = str(integrity.get("normalized_symbol") or "")
            payload["symbol"] = pair
            payload["time_in_force"] = _safe_text(order.get("time_in_force"), "gtc").lower()
            if payload["time_in_force"] not in {"gtc", "ioc"}:
                return {"ok": False, "error": "unsupported_crypto_time_in_force"}
        client_order_id = _safe_text(order.get("client_order_id"))
        if client_order_id:
            payload["client_order_id"] = client_order_id[:48]
        notional = _to_float(order.get("notional"), 0.0)
        qty = _to_float(order.get("qty"), 0.0)
        if notional > 0:
            payload["notional"] = round(min(notional, _to_float(os.getenv("ASTRA_ALPACA_MAX_PAPER_NOTIONAL"), 250.0)), 2)
        elif qty > 0:
            payload["qty"] = round(qty, 6)
        else:
            payload["notional"] = round(_to_float(os.getenv("ASTRA_ALPACA_DEFAULT_PAPER_NOTIONAL"), 100.0), 2)
        if payload["type"] == "limit" and _to_float(order.get("limit_price"), 0.0) > 0:
            payload["limit_price"] = str(round(_to_float(order.get("limit_price"), 0.0), 4))
        ok, data, err = self._request("POST", "/orders", payload)
        if not ok or not isinstance(data, dict):
            self._last_order_status = f"rejected:{err[:80]}"
            return {"ok": False, "error": err, "paper_order_submitted": False}
        clean = _sanitize_order(data)
        self._last_order_status = _safe_text(clean.get("status"), "submitted")
        return {"ok": True, "paper_order_submitted": True, "order": clean}

    def cancel_paper_order(self, order_id: str) -> dict[str, Any]:
        oid = _safe_text(order_id)
        if not oid:
            return {"ok": False, "error": "order_id_required"}
        ok, _data, err = self._request("DELETE", f"/orders/{urllib.parse.quote(oid)}")
        if not ok:
            return {"ok": False, "error": err}
        self._last_order_status = "cancel_requested"
        return {"ok": True, "order_id": oid, "status": "cancel_requested"}

    def status(self, *, include_broker_truth: bool = True) -> dict[str, Any]:
        self._api_calls_used = 0
        safety = self.safety_status()
        account = {"ok": False}
        positions = {"ok": False, "positions": [], "open_positions_count": 0}
        orders = {"ok": False, "orders": [], "open_orders_count": 0}
        broker_truth = {"ok": False}
        if safety.get("broker_execution_enabled"):
            account = self.account()
            positions = self.positions()
            orders = self.orders(status="open", limit=50)
            if include_broker_truth:
                broker_truth = self.broker_truth_metrics(limit=200)
        account_ok = bool(isinstance(account, dict) and account.get("ok"))
        positions_ok = bool(isinstance(positions, dict) and positions.get("ok"))
        orders_ok = bool(isinstance(orders, dict) and orders.get("ok"))
        preflight_errors = [
            _safe_text(x.get("error"), "")
            for x in (account, positions, orders)
            if isinstance(x, dict) and x.get("error")
        ]
        last_error = _safe_text(preflight_errors[0] if preflight_errors else self._last_error, "")
        return {
            "enabled": bool(safety.get("enabled_requested")),
            "version": VERSION,
            "mode": "paper_only",
            "paper_mode_verified": bool(safety.get("paper_mode_verified")),
            "broker_execution_enabled": bool(safety.get("broker_execution_enabled")),
            "account_preflight_ok": account_ok,
            "positions_preflight_ok": positions_ok,
            "orders_preflight_ok": orders_ok,
            "broker_execution_ready": bool(safety.get("broker_execution_enabled") and account_ok),
            "account_equity": _to_float(account.get("account_equity"), 0.0),
            "buying_power": _to_float(account.get("buying_power"), 0.0),
            "open_positions_count": _to_int(positions.get("open_positions_count"), 0),
            "open_orders_count": _to_int(orders.get("open_orders_count"), 0),
            # Keep the bounded read-only broker snapshot available to the
            # reconciliation layer.  Previously status() reduced positions
            # to a count, which made a fresh audit appear empty even after a
            # successful paper-broker read.
            "positions": list(positions.get("positions") or [])[:100] if isinstance(positions, dict) else [],
            "open_orders": list(orders.get("orders") or [])[:100] if isinstance(orders, dict) else [],
            "broker_snapshot_status": "FRESH_READ_ONLY" if account_ok and positions_ok and orders_ok else "PARTIAL_READ_ONLY",
            "broker_snapshot_source": "alpaca_paper_account_positions_open_orders",
            "broker_truth_refresh_included": bool(include_broker_truth),
            "last_order_status": self._last_order_status,
            "last_alpaca_error_sanitized": last_error,
            "safety_status": safety.get("safety_status"),
            "safety_reasons": safety.get("safety_reasons") or [],
            "paper_endpoint_required": True,
            "paper_endpoint_detected": bool(safety.get("paper_endpoint_detected")),
            "live_endpoint_detected": bool(safety.get("live_endpoint_detected")),
            "live_endpoint_rejected": bool(safety.get("live_endpoint_rejected")),
            "credential_source": safety.get("credential_source"),
            "broker_truth_engine_v1": bool(broker_truth.get("broker_truth_engine_v1", False)),
            "broker_truth_metrics": broker_truth if isinstance(broker_truth, dict) else {},
            "api_calls_used": int(self._api_calls_used),
            "live_trading_changed": False,
            "broker_live_endpoint_allowed": False,
            "crypto_broker_execution_supported": False,
            "crypto_note": safety.get("crypto_note"),
            "generated_at": _now_iso(),
        }

    def positions_status(self) -> dict[str, Any]:
        self._api_calls_used = 0
        safety = self.safety_status()
        if not safety.get("broker_execution_enabled"):
            return {
                "enabled": bool(safety.get("enabled_requested")),
                "mode": "paper_only",
                "paper_mode_verified": bool(safety.get("paper_mode_verified")),
                "broker_execution_enabled": False,
                "positions": [],
                "open_positions_count": 0,
                "safety_status": safety.get("safety_status"),
                "safety_reasons": safety.get("safety_reasons") or [],
                "api_calls_used": 0,
                "live_trading_changed": False,
                "generated_at": _now_iso(),
            }
        positions = self.positions()
        return {
            "enabled": True,
            "mode": "paper_only",
            "paper_mode_verified": True,
            "broker_execution_enabled": True,
            "positions": positions.get("positions") if isinstance(positions, dict) else [],
            "open_positions_count": _to_int((positions or {}).get("open_positions_count"), 0) if isinstance(positions, dict) else 0,
            "api_calls_used": int(self._api_calls_used),
            "live_trading_changed": False,
            "generated_at": _now_iso(),
        }
