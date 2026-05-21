from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
PAPER_BASE = "https://paper-api.alpaca.markets"


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

    def _env(self) -> dict[str, str]:
        base = _safe_text(os.getenv("APCA_API_BASE_URL") or os.getenv("ALPACA_BASE_URL") or PAPER_BASE).rstrip("/")
        return {
            "key": _safe_text(os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY_ID")),
            "secret": _safe_text(os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")),
            "base_url": base,
            "mode": _safe_text(os.getenv("ALPACA_TRADING_MODE"), "paper").lower(),
            "enabled_raw": _safe_text(os.getenv("ASTRA_ENABLE_ALPACA_PAPER"), "false").lower(),
        }

    def safety_status(self) -> dict[str, Any]:
        env = self._env()
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
            "credentials_present": bool(env["key"] and env["secret"]),
            "safety_status": "pass" if verified else "disabled_or_blocked",
            "safety_reasons": reasons or ["paper_mode_verified"],
            "live_trading_changed": False,
            "crypto_broker_execution_supported": False,
            "crypto_note": "Crypto broker execution deferred until exchange/broker coverage is selected.",
        }

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

    def submit_paper_order(self, order: dict[str, Any]) -> dict[str, Any]:
        safety = self.safety_status()
        if not safety.get("broker_execution_enabled"):
            return {"ok": False, "error": "broker_safety_blocked", "safety_reasons": safety.get("safety_reasons") or []}
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

    def status(self) -> dict[str, Any]:
        self._api_calls_used = 0
        safety = self.safety_status()
        account = {"ok": False}
        positions = {"ok": False, "positions": [], "open_positions_count": 0}
        orders = {"ok": False, "orders": [], "open_orders_count": 0}
        if safety.get("broker_execution_enabled"):
            account = self.account()
            positions = self.positions()
            orders = self.orders(status="open", limit=50)
        return {
            "enabled": bool(safety.get("enabled_requested")),
            "version": VERSION,
            "mode": "paper_only",
            "paper_mode_verified": bool(safety.get("paper_mode_verified")),
            "broker_execution_enabled": bool(safety.get("broker_execution_enabled")),
            "account_equity": _to_float(account.get("account_equity"), 0.0),
            "buying_power": _to_float(account.get("buying_power"), 0.0),
            "open_positions_count": _to_int(positions.get("open_positions_count"), 0),
            "open_orders_count": _to_int(orders.get("open_orders_count"), 0),
            "last_order_status": self._last_order_status,
            "safety_status": safety.get("safety_status"),
            "safety_reasons": safety.get("safety_reasons") or [],
            "paper_endpoint_required": True,
            "paper_endpoint_detected": bool(safety.get("paper_endpoint_detected")),
            "live_endpoint_detected": bool(safety.get("live_endpoint_detected")),
            "live_endpoint_rejected": bool(safety.get("live_endpoint_rejected")),
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
