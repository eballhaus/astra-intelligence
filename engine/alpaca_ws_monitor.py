"""Bounded, read-only Alpaca IEX observation stream for active equities."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from engine.runtime_environment import load_runtime_environment


def _enabled(name: str, default: bool = False) -> bool:
    value = str(os.getenv(name, "")).strip().lower()
    if value in {"1", "true", "yes", "on", "enabled"}:
        return True
    if value in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _utc_epoch(value: Any) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC).timestamp()
    except (TypeError, ValueError):
        return None


def _receive_epoch(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return _utc_epoch(value)


class AlpacaWSMonitor:
    """One IEX-only market-data connection shared by all equity lanes.

    The monitor is deliberately observation-only.  It holds provider-attributed
    prices for management evidence but has no broker, order, or exit authority.
    """

    def __init__(
        self,
        *,
        connect: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._connect = connect
        self._sleep = sleep
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connection: Any = None
        self._desired_symbols: set[str] = set()
        self._open_symbols: set[str] = set()
        self._near_entry_symbols: set[str] = set()
        self._subscribed_symbols: set[str] = set()
        self._quotes: dict[str, dict[str, Any]] = {}
        self._stats: dict[str, Any] = {
            "messages_received": 0,
            "reconnects": 0,
            "errors": 0,
            "last_error": "",
            "auth_state": "UNKNOWN",
            "subscription_state": "UNKNOWN",
            "last_message_utc": None,
            "last_connected_utc": None,
            "last_disconnected_utc": None,
        }

    @staticmethod
    def _credentials() -> tuple[str, str]:
        load_runtime_environment()
        pairs = (
            ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"),
            ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
            ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET"),
            ("ALPACA_API_KEY", "APCA_API_SECRET_KEY"),
            ("APCA_API_KEY_ID", "ALPACA_SECRET_KEY"),
        )
        for key_name, secret_name in pairs:
            key = str(os.getenv(key_name, "") or "").strip()
            secret = str(os.getenv(secret_name, "") or "").strip()
            if key and secret:
                return key, secret
        return "", ""

    @staticmethod
    def _symbol_set(values: Any) -> set[str]:
        return {
            str(value or "").upper().strip()
            for value in (values or [])
            if str(value or "").strip() and "/" not in str(value or "")
        }

    @staticmethod
    def _is_canonical_owner() -> bool:
        return str(os.getenv("ASTRA_PROCESS_ROLE", "api") or "api").strip().lower() == "worker"

    @staticmethod
    def _shared_state_path() -> Path:
        configured = str(os.getenv("ASTRA_STATE_DIR", "") or "").strip()
        state_dir = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[1] / "state"
        return state_dir / "paper_autopilot_state.json"

    @classmethod
    def _read_shared_status(cls) -> dict[str, Any]:
        if cls._is_canonical_owner():
            return {}
        try:
            with cls._shared_state_path().open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            status = payload.get("alpaca_ws_active_position_monitor_v1") if isinstance(payload, dict) else None
            return dict(status) if isinstance(status, dict) else {}
        except (FileNotFoundError, OSError, TypeError, ValueError):
            return {}

    def configure_symbols(
        self,
        *,
        open_position_symbols: list[str] | None = None,
        near_entry_symbols: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        """Atomically update the single connection's bounded subscriptions."""
        open_symbols = self._symbol_set(open_position_symbols)
        near_symbols = self._symbol_set(near_entry_symbols)
        if symbols is not None:
            open_symbols = self._symbol_set(symbols)
            near_symbols = set()
        cap = max(1, int(float(os.getenv("ASTRA_ALPACA_WS_MAX_SYMBOLS", "24"))))
        open_limited = sorted(open_symbols)[:cap]
        near_limited = [symbol for symbol in sorted(near_symbols) if symbol not in open_symbols]
        desired = open_limited + near_limited[: max(0, cap - len(open_limited))]
        with self._lock:
            self._open_symbols = set(sorted(open_symbols)[:cap])
            self._near_entry_symbols = set(desired) - self._open_symbols
            self._desired_symbols = set(desired)
            self._quotes = {symbol: row for symbol, row in self._quotes.items() if symbol in self._desired_symbols}
        self._ensure_thread()
        self._wake.set()
        return {"ok": True, "desired_symbol_count": len(desired), "symbol_cap": cap}

    def _ensure_thread(self) -> None:
        if not self._is_canonical_owner() or not _enabled("ASTRA_ALPACA_WS_ENABLED", False):
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="astra-alpaca-iex-observer", daemon=True)
            self._thread.start()

    def _endpoint(self) -> str:
        feed = str(os.getenv("ASTRA_ALPACA_WS_FEED", "iex") or "iex").strip().lower()
        # The configured deployment is intentionally IEX-only; accepting a
        # broader feed here could silently change its market-data contract.
        if feed != "iex":
            feed = "iex"
        return f"wss://stream.data.alpaca.markets/v2/{feed}"

    def _connector(self) -> Callable[..., Any] | None:
        if self._connect is not None:
            return self._connect
        try:
            from websockets.sync.client import connect
        except Exception:
            return None
        return connect

    @staticmethod
    def _send(connection: Any, payload: dict[str, Any]) -> None:
        connection.send(json.dumps(payload, separators=(",", ":")))

    def _sync_subscriptions(self, connection: Any, *, mark_subscribed: bool = True) -> bool:
        with self._lock:
            desired = set(self._desired_symbols)
            subscribed = set(self._subscribed_symbols)
        remove = sorted(subscribed - desired)
        add = sorted(desired - subscribed)
        if remove:
            self._send(connection, {"action": "unsubscribe", "trades": remove, "quotes": remove})
        if add:
            self._send(connection, {"action": "subscribe", "trades": add, "quotes": add})
        if mark_subscribed:
            with self._lock:
                self._subscribed_symbols = desired
        return bool(remove or add)

    def _wait_for_control(
        self,
        connection: Any,
        *,
        message_type: str,
        message: str | None = None,
        timeout_seconds: float = 8.0,
    ) -> dict[str, Any]:
        """Wait for the provider acknowledgement that gates the next action."""
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"alpaca_ws_{message_type}_ack_timeout")
            try:
                raw = connection.recv(timeout=min(1.0, remaining))
            except TimeoutError:
                continue
            payload = json.loads(raw)
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("T") or "") == "error":
                    detail = str(row.get("msg") or row.get("code") or "unknown")[:120]
                    raise RuntimeError(f"alpaca_ws_{message_type}_error:{detail}")
                self._record_message(row)
                if str(row.get("T") or "") != message_type:
                    continue
                if message is not None and str(row.get("msg") or "") != message:
                    continue
                with self._lock:
                    self._stats["last_control_message_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                return row

    def _apply_subscription_ack(self, message: dict[str, Any]) -> None:
        acknowledged = {
            str(symbol or "").upper().strip()
            for key in ("quotes", "trades")
            for symbol in (message.get(key) or [])
            if str(symbol or "").strip()
        }
        with self._lock:
            self._subscribed_symbols = acknowledged & set(self._desired_symbols)
            self._stats["subscription_state"] = "SUBSCRIBED"

    def _record_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("T") or "")
        if message_type not in {"t", "q"}:
            return
        symbol = str(message.get("S") or "").upper().strip()
        if not symbol:
            return
        provider_epoch = _utc_epoch(message.get("t"))
        if provider_epoch is None:
            return
        bid = message.get("bp")
        ask = message.get("ap")
        trade = message.get("p")
        try:
            price = float(trade if trade not in (None, "") else (float(bid) + float(ask)) / 2.0)
        except (TypeError, ValueError):
            return
        now = time.time()
        with self._lock:
            prior = dict(self._quotes.get(symbol) or {})
            quote = {
                **prior,
                "symbol": symbol,
                "price": price,
                "bid": bid if bid not in (None, "") else prior.get("bid"),
                "ask": ask if ask not in (None, "") else prior.get("ask"),
                "quote_timestamp": provider_epoch,
                "provider_native_timestamp": str(message.get("t") or ""),
                "receive_timestamp": now,
                "provider_used": "ALPACA_WS_IEX",
                "provider_provenance": "FAST_IEX_OBSERVATION",
                "quote_quality": "live_ws_iex_observation",
                "consolidated_market_truth": False,
                "market_observation_only": True,
                "message_type": "trade" if message_type == "t" else "quote",
            }
            self._quotes[symbol] = quote
            self._stats["messages_received"] += 1
            self._stats["last_message_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _read_messages(self, connection: Any) -> None:
        try:
            raw = connection.recv(timeout=1.0)
        except TimeoutError:
            return
        payload = json.loads(raw)
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if isinstance(row, dict):
                self._record_message(row)

    def _run(self) -> None:
        if not self._is_canonical_owner():
            return
        retry_seconds = 1.0
        while not self._stop.is_set():
            with self._lock:
                has_symbols = bool(self._desired_symbols)
            if not has_symbols:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            key, secret = self._credentials()
            connector = self._connector()
            if not key or not secret or connector is None:
                with self._lock:
                    self._stats["last_error"] = "credentials_or_websocket_client_unavailable"
                    self._stats["errors"] += 1
                self._wake.wait(timeout=15.0)
                self._wake.clear()
                continue
            connection = None
            try:
                # Keep protocol pings, but use application message flow and
                # explicit acknowledgements as transport health evidence. A
                # missed Pong must not create an unbounded reconnect storm.
                connection = connector(
                    self._endpoint(),
                    open_timeout=8,
                    close_timeout=3,
                    ping_interval=20.0,
                    ping_timeout=None,
                )
                with self._lock:
                    self._connection = connection
                    self._subscribed_symbols = set()
                    self._stats["auth_state"] = "AUTHENTICATING"
                    self._stats["subscription_state"] = "UNSUBSCRIBED"
                    self._stats["last_connected_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                self._send(connection, {"action": "auth", "key": key, "secret": secret})
                self._wait_for_control(connection, message_type="success", message="authenticated")
                with self._lock:
                    self._stats["auth_state"] = "AUTHENTICATED"
                if self._sync_subscriptions(connection, mark_subscribed=False):
                    subscription_ack = self._wait_for_control(connection, message_type="subscription")
                    self._apply_subscription_ack(subscription_ack)
                else:
                    with self._lock:
                        self._stats["subscription_state"] = "EMPTY"
                while not self._stop.is_set():
                    if self._wake.is_set():
                        self._wake.clear()
                        if self._sync_subscriptions(connection, mark_subscribed=False):
                            subscription_ack = self._wait_for_control(connection, message_type="subscription")
                            self._apply_subscription_ack(subscription_ack)
                    with self._lock:
                        messages_before = int(self._stats.get("messages_received") or 0)
                    self._read_messages(connection)
                    with self._lock:
                        if int(self._stats.get("messages_received") or 0) > messages_before:
                            retry_seconds = 1.0
            except Exception as exc:
                with self._lock:
                    self._stats["errors"] += 1
                    self._stats["last_error"] = str(exc)[:180]
                    self._stats["reconnects"] += 1
                    self._stats["last_disconnected_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                    self._subscribed_symbols = set()
                    self._stats["auth_state"] = "FAILED"
                    self._stats["subscription_state"] = "FAILED"
            finally:
                with self._lock:
                    self._connection = None
                try:
                    if connection is not None:
                        connection.close()
                except Exception:
                    pass
            self._wake.wait(timeout=min(30.0, retry_seconds))
            self._wake.clear()
            retry_seconds = min(30.0, retry_seconds * 2.0)

    def get_quote(self, symbol: str, max_age_seconds: float = 20, **_: Any) -> dict[str, Any] | None:
        sym = str(symbol or "").upper().strip()
        with self._lock:
            quote = dict(self._quotes.get(sym) or {})
        if not quote:
            shared = self._read_shared_status()
            quote = dict((shared.get("observations") or {}).get(sym) or {})
        if not quote:
            return None
        received_at = _receive_epoch(quote.get("receive_timestamp"))
        if received_at is None:
            return None
        age = max(0.0, time.time() - received_at)
        if age > max(0.0, float(max_age_seconds)):
            return None
        quote["quote_age_seconds"] = round(age, 3)
        return quote

    def status(self) -> dict[str, Any]:
        shared = self._read_shared_status()
        if shared:
            shared["consumer_process_role"] = str(os.getenv("ASTRA_PROCESS_ROLE", "api") or "api").strip().lower()
            shared["shared_state_consumed"] = True
            return shared
        with self._lock:
            connected = self._connection is not None
            desired = sorted(self._desired_symbols)
            subscribed = sorted(self._subscribed_symbols)
            stats = dict(self._stats)
            priorities = {"open_positions": len(self._open_symbols), "near_entry": len(self._near_entry_symbols)}
            observations = {
                symbol: dict(self._quotes[symbol])
                for symbol in desired
                if isinstance(self._quotes.get(symbol), dict)
            }
        now = time.time()
        connected_at = _utc_epoch(stats.get("last_connected_utc"))
        last_message_at = _utc_epoch(stats.get("last_message_utc"))
        connected_age = max(0.0, now - connected_at) if connected_at is not None else None
        message_age = max(0.0, now - last_message_at) if last_message_at is not None else None
        stale_stream = bool(desired and connected and (
            (last_message_at is None and connected_age is not None and connected_age > 30.0)
            or (message_age is not None and message_age > 60.0)
        ))
        reconnect_storm = bool(
            desired
            and int(stats.get("errors") or 0) >= 3
            and int(stats.get("reconnects") or 0) >= 3
            and int(stats.get("messages_received") or 0) == 0
        )
        transport_health = "IDLE"
        if desired:
            if reconnect_storm or not connected:
                transport_health = "UNHEALTHY"
            elif stats.get("auth_state") != "AUTHENTICATED" or stats.get("subscription_state") != "SUBSCRIBED":
                transport_health = "UNHEALTHY"
            elif stale_stream:
                transport_health = "DEGRADED"
            else:
                transport_health = "HEALTHY"
        return {
            "enabled": _enabled("ASTRA_ALPACA_WS_ENABLED", False),
            "running": bool(connected),
            "connection_count": int(bool(connected)),
            "feed": "iex",
            "provider_provenance": "FAST_IEX_OBSERVATION",
            "consolidated_market_truth": False,
            "desired_symbol_count": len(desired),
            "active_symbol_count": len(subscribed),
            "subscribed_symbols": subscribed,
            "desired_symbols": desired,
            "priority_classes": priorities,
            "owner_process_role": "worker" if self._is_canonical_owner() else "api",
            "shared_state_consumed": False,
            "observations": observations,
            "transport_health": transport_health,
            "stale_stream": stale_stream,
            "connected_age_seconds": round(connected_age, 3) if connected_age is not None else None,
            "last_message_age_seconds": round(message_age, 3) if message_age is not None else None,
            "stats": stats,
        }

    def contention_diagnostics(self) -> dict[str, Any]:
        status = self.status()
        return {
            "ok": True,
            "connection_count": status["connection_count"],
            "desired_symbol_count": status["desired_symbol_count"],
            "active_symbol_count": status["active_symbol_count"],
            "reconnects": status["stats"].get("reconnects", 0),
            "last_error": status["stats"].get("last_error", ""),
        }

    def reset_for_diagnostics(self, *, restart: bool = True, **_: Any) -> dict[str, Any]:
        self._wake.set()
        if restart:
            self._ensure_thread()
        return {"ok": True, "restart_requested": bool(restart), "connection_count": self.status()["connection_count"]}

    def request_reconnect(self) -> dict[str, Any]:
        """Request one bounded reconnect on the existing monitor thread."""
        with self._lock:
            connection = self._connection
        self._wake.set()
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        return {
            "status": "RECONNECT_REQUESTED",
            "connection_count": self.status()["connection_count"],
            "provider_calls_added": 0,
            "broker_actions_added": 0,
        }


ALPACA_WS_MONITOR = AlpacaWSMonitor()
