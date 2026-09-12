"""Bounded, read-only Alpaca observation streams owned by the PAPER worker."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from engine.provider_router import (
    canonical_crypto_market_symbol_v1,
    normalize_public_crypto_websocket_quote_v1,
    select_crypto_websocket_quote_v1,
)
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


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class AlpacaWSMonitor:
    """Worker-owned market-data streams for equity and crypto observations.

    The monitor is deliberately observation-only.  It holds provider-attributed
    prices for management evidence but has no broker, order, or exit authority.
    Alpaca exposes equity IEX/SIP and US crypto data on separate websocket
    feeds; all production and optional shadow feeds remain lifecycle-managed
    by this one worker-owned monitor.
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
        self._stream_threads: dict[str, threading.Thread] = {}
        self._connection: Any = None
        self._shadow_connection: Any = None
        self._crypto_connection: Any = None
        self._public_crypto_connections: dict[str, Any] = {"KRAKEN": None, "COINBASE": None}
        self._desired_symbols: set[str] = set()
        self._desired_crypto_symbols: set[str] = set()
        self._open_symbols: set[str] = set()
        self._open_crypto_symbols: set[str] = set()
        self._near_entry_symbols: set[str] = set()
        self._subscribed_symbols: set[str] = set()
        self._subscribed_bar_symbols: set[str] = set()
        self._shadow_subscribed_symbols: set[str] = set()
        self._shadow_subscribed_bar_symbols: set[str] = set()
        self._subscribed_crypto_symbols: set[str] = set()
        self._quotes: dict[str, dict[str, Any]] = {}
        self._bars: dict[str, dict[str, Any]] = {}
        self._shadow_quotes: dict[str, dict[str, Any]] = {}
        self._shadow_bars: dict[str, dict[str, Any]] = {}
        self._crypto_quotes: dict[str, dict[str, Any]] = {}
        self._public_crypto_quotes: dict[str, dict[str, dict[str, Any]]] = {"KRAKEN": {}, "COINBASE": {}}
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
        self._crypto_stats: dict[str, Any] = {
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
        self._shadow_stats: dict[str, Any] = {
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
        self._public_crypto_stats: dict[str, dict[str, Any]] = {
            provider: {
                "messages_received": 0,
                "reconnects": 0,
                "errors": 0,
                "last_error": "",
                "subscription_state": "UNSUBSCRIBED",
                "last_message_utc": None,
                "last_connected_utc": None,
                "last_disconnected_utc": None,
            }
            for provider in ("KRAKEN", "COINBASE")
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
    def _equity_symbol_set(values: Any) -> set[str]:
        return {
            str(value or "").upper().strip()
            for value in (values or [])
            if str(value or "").strip() and "/" not in str(value or "")
        }

    @staticmethod
    def _crypto_symbol_set(values: Any) -> set[str]:
        symbols: set[str] = set()
        for value in values or []:
            raw = str(value or "").strip()
            if not raw:
                continue
            try:
                symbols.add(canonical_crypto_market_symbol_v1(raw)["internal_pair"])
            except (TypeError, ValueError, IndexError):
                continue
        return symbols

    @staticmethod
    def _is_canonical_owner() -> bool:
        return str(os.getenv("ASTRA_PROCESS_ROLE", "api") or "api").strip().lower() == "worker"

    @staticmethod
    def _equity_feed(*, shadow: bool = False) -> tuple[str, str]:
        """Return the explicitly configured feed and a fail-closed reason."""
        variable = "ASTRA_ALPACA_WS_SHADOW_FEED" if shadow else "ASTRA_ALPACA_WS_FEED"
        raw = str(os.getenv(variable, "iex") or "iex").strip().lower()
        if raw not in {"iex", "sip"}:
            return "", "invalid_equity_feed"
        if raw == "sip" and not _enabled("ASTRA_ALPACA_SIP_ENTITLEMENT_VERIFIED", False):
            return "", "sip_entitlement_unverified"
        return raw, ""

    @staticmethod
    def _shadow_stream_enabled() -> bool:
        if not _enabled("ASTRA_ALPACA_WS_SHADOW_ENABLED", False):
            return False
        primary, _ = AlpacaWSMonitor._equity_feed()
        shadow, reason = AlpacaWSMonitor._equity_feed(shadow=True)
        return bool(primary and shadow and not reason and primary != shadow)

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
        open_crypto_position_symbols: list[str] | None = None,
        near_entry_symbols: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        """Atomically update bounded subscriptions for both Alpaca feeds."""
        open_symbols = self._equity_symbol_set(open_position_symbols)
        open_crypto_symbols = self._crypto_symbol_set(open_crypto_position_symbols)
        near_symbols = self._equity_symbol_set(near_entry_symbols)
        if symbols is not None:
            open_symbols = self._equity_symbol_set(symbols)
            open_crypto_symbols = self._crypto_symbol_set(symbols)
            near_symbols = set()
        cap = max(1, int(float(os.getenv("ASTRA_ALPACA_WS_MAX_SYMBOLS", "24"))))
        crypto_cap = max(1, int(float(os.getenv("ASTRA_ALPACA_CRYPTO_WS_MAX_SYMBOLS", "8"))))
        open_limited = sorted(open_symbols)[:cap]
        open_crypto_limited = sorted(open_crypto_symbols)[:crypto_cap]
        near_limited = [symbol for symbol in sorted(near_symbols) if symbol not in open_symbols]
        desired = open_limited + near_limited[: max(0, cap - len(open_limited))]
        public_connections_to_close: list[Any] = []
        with self._lock:
            previous_crypto_symbols = set(self._desired_crypto_symbols)
            previous_symbols = set(self._desired_symbols)
            self._open_symbols = set(open_limited)
            self._open_crypto_symbols = set(open_crypto_limited)
            self._near_entry_symbols = set(desired) - self._open_symbols
            self._desired_symbols = set(desired)
            self._desired_crypto_symbols = set(open_crypto_limited)
            self._quotes = {symbol: row for symbol, row in self._quotes.items() if symbol in self._desired_symbols}
            self._bars = {symbol: row for symbol, row in self._bars.items() if symbol in self._desired_symbols}
            self._shadow_quotes = {
                symbol: row for symbol, row in self._shadow_quotes.items()
                if symbol in self._desired_symbols
            }
            self._shadow_bars = {
                symbol: row for symbol, row in self._shadow_bars.items()
                if symbol in self._desired_symbols
            }
            self._crypto_quotes = {
                symbol: row for symbol, row in self._crypto_quotes.items()
                if symbol in self._desired_crypto_symbols
            }
            self._public_crypto_quotes = {
                provider: {
                    symbol: row for symbol, row in quotes.items()
                    if symbol in self._desired_crypto_symbols
                }
                for provider, quotes in self._public_crypto_quotes.items()
            }
            # Public feeds subscribe to the bounded active-position set. A
            # symbol-set change reconnects the existing owner once instead of
            # stacking duplicate subscriptions on a live socket.
            if previous_crypto_symbols != self._desired_crypto_symbols:
                public_connections_to_close = list(self._public_crypto_connections.values())
            if previous_symbols != self._desired_symbols and self._shadow_connection is not None:
                public_connections_to_close.append(self._shadow_connection)
        for connection in public_connections_to_close:
            try:
                if connection is not None:
                    connection.close()
            except Exception:
                pass
        self._ensure_thread()
        self._wake.set()
        return {
            "ok": True,
            "desired_symbol_count": len(desired),
            "desired_crypto_symbol_count": len(open_crypto_limited),
            "symbol_cap": cap,
            "crypto_symbol_cap": crypto_cap,
        }

    def _ensure_thread(self) -> None:
        if not self._is_canonical_owner() or not (
            _enabled("ASTRA_ALPACA_WS_ENABLED", False)
            or self._shadow_stream_enabled()
            or self._crypto_stream_enabled()
        ):
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="astra-alpaca-observer", daemon=True)
            self._thread.start()

    def _endpoint(self, *, shadow: bool = False) -> str:
        feed, _ = self._equity_feed(shadow=shadow)
        return f"wss://stream.data.alpaca.markets/v2/{feed}" if feed else ""

    @staticmethod
    def _crypto_endpoint() -> str:
        return "wss://stream.data.alpaca.markets/v1beta3/crypto/us"

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

    def _sync_subscriptions(
        self,
        connection: Any,
        *,
        stream: str = "equity",
        shadow: bool = False,
        mark_subscribed: bool = True,
    ) -> bool:
        feed, _ = self._equity_feed(shadow=shadow) if stream != "crypto" else ("crypto", "")
        bars_enabled = stream != "crypto" and feed == "sip"
        with self._lock:
            if stream == "crypto":
                desired = set(self._desired_crypto_symbols)
                subscribed = set(self._subscribed_crypto_symbols)
                bar_subscribed: set[str] = set()
            elif shadow:
                desired = set(self._desired_symbols)
                subscribed = set(self._shadow_subscribed_symbols)
                bar_subscribed = set(self._shadow_subscribed_bar_symbols)
            else:
                desired = set(self._desired_symbols)
                subscribed = set(self._subscribed_symbols)
                bar_subscribed = set(self._subscribed_bar_symbols)
        remove = sorted(subscribed - desired)
        add = sorted(desired - subscribed)
        remove_bars = sorted(bar_subscribed - desired) if bars_enabled else sorted(bar_subscribed)
        add_bars = sorted(desired - bar_subscribed) if bars_enabled else []
        if remove:
            payload = {"action": "unsubscribe", "quotes": remove}
            if stream != "crypto":
                payload["trades"] = remove
                if remove_bars:
                    payload["bars"] = remove_bars
            self._send(connection, payload)
        elif remove_bars:
            self._send(connection, {"action": "unsubscribe", "bars": remove_bars})
        if add:
            payload = {"action": "subscribe", "quotes": add}
            if stream != "crypto":
                payload["trades"] = add
                if add_bars:
                    payload["bars"] = add_bars
            self._send(connection, payload)
        elif add_bars:
            self._send(connection, {"action": "subscribe", "bars": add_bars})
        if mark_subscribed:
            with self._lock:
                if stream == "crypto":
                    self._subscribed_crypto_symbols = desired
                elif shadow:
                    self._shadow_subscribed_symbols = desired
                    self._shadow_subscribed_bar_symbols = set(desired) if bars_enabled else set()
                else:
                    self._subscribed_symbols = desired
                    self._subscribed_bar_symbols = set(desired) if bars_enabled else set()
        return bool(remove or add or remove_bars or add_bars)

    def _wait_for_control(
        self,
        connection: Any,
        *,
        message_type: str,
        message: str | None = None,
        stream: str = "equity",
        shadow: bool = False,
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
                self._record_message(row, stream=stream, shadow=shadow)
                if str(row.get("T") or "") != message_type:
                    continue
                if message is not None and str(row.get("msg") or "") != message:
                    continue
                with self._lock:
                    stats = (
                        self._crypto_stats if stream == "crypto"
                        else self._shadow_stats if shadow
                        else self._stats
                    )
                    stats["last_control_message_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                return row

    def _apply_subscription_ack(
        self,
        message: dict[str, Any],
        *,
        stream: str = "equity",
        shadow: bool = False,
    ) -> None:
        acknowledged = {
            str(symbol or "").upper().strip()
            for key in ("quotes", "trades")
            for symbol in (message.get(key) or [])
            if str(symbol or "").strip()
        }
        with self._lock:
            if stream == "crypto":
                normalized = set()
                for symbol in acknowledged:
                    try:
                        normalized.add(canonical_crypto_market_symbol_v1(symbol)["internal_pair"])
                    except (TypeError, ValueError, IndexError):
                        continue
                self._subscribed_crypto_symbols = normalized & set(self._desired_crypto_symbols)
                self._crypto_stats["subscription_state"] = (
                    "SUBSCRIBED"
                    if self._subscribed_crypto_symbols >= set(self._desired_crypto_symbols)
                    else "PARTIAL"
                )
            elif shadow:
                self._shadow_subscribed_symbols = acknowledged & set(self._desired_symbols)
                self._shadow_stats["subscription_state"] = "SUBSCRIBED"
            else:
                self._subscribed_symbols = acknowledged & set(self._desired_symbols)
                self._stats["subscription_state"] = "SUBSCRIBED"
            acknowledged_bars = {
                str(symbol or "").upper().strip()
                for symbol in (message.get("bars") or [])
                if str(symbol or "").strip()
            }
            if stream != "crypto":
                if shadow:
                    self._shadow_subscribed_bar_symbols = acknowledged_bars & set(self._desired_symbols)
                else:
                    self._subscribed_bar_symbols = acknowledged_bars & set(self._desired_symbols)

    def _record_message(
        self,
        message: dict[str, Any],
        *,
        stream: str = "equity",
        shadow: bool = False,
    ) -> None:
        message_type = str(message.get("T") or "")
        if message_type not in {"t", "q", "b"}:
            return
        raw_symbol = str(message.get("S") or "").upper().strip()
        if stream == "crypto":
            try:
                symbol = canonical_crypto_market_symbol_v1(raw_symbol)["internal_pair"]
            except (TypeError, ValueError, IndexError):
                return
        else:
            symbol = raw_symbol
        if not symbol:
            return
        provider_epoch = _utc_epoch(message.get("t"))
        if provider_epoch is None:
            return
        feed, _ = self._equity_feed(shadow=shadow) if stream != "crypto" else ("crypto", "")
        if stream != "crypto" and not feed:
            return
        provider_name = (
            "ALPACA_WS_CRYPTO" if stream == "crypto"
            else "ALPACA_WS_SIP_SHADOW" if shadow
            else "ALPACA_WS_SIP" if feed == "sip"
            else "ALPACA_WS_IEX"
        )
        provider_provenance = (
            "FAST_CRYPTO_WS_OBSERVATION" if stream == "crypto"
            else "SHADOW_SIP_OBSERVATION" if shadow
            else "FAST_SIP_OBSERVATION" if feed == "sip"
            else "FAST_IEX_OBSERVATION"
        )
        if message_type == "b" and stream == "crypto":
            return
        if message_type == "b":
            try:
                open_value = _float_or_none(message.get("o"))
                high_value = _float_or_none(message.get("h"))
                low_value = _float_or_none(message.get("l"))
                close_value = _float_or_none(message.get("c"))
                volume_value = _float_or_none(message.get("v"))
            except (TypeError, ValueError):
                return
            if not all(value is not None for value in (open_value, high_value, low_value, close_value)):
                return
            now = time.time()
            bar = {
                "symbol": symbol,
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": close_value,
                "volume": volume_value,
                "provider_quote_timestamp": str(message.get("t") or ""),
                "provider_native_timestamp": str(message.get("t") or ""),
                "receive_timestamp": now,
                "receive_timestamp_utc": datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z"),
                "provider_used": provider_name,
                "provider": provider_name,
                "provider_provenance": provider_provenance,
                "consolidated_market_truth": False,
                "market_observation_only": True,
                "shadow_only": bool(shadow),
                "observation_authority": not bool(shadow),
                "message_type": "bar",
                "quote_record_id": message.get("i") or message.get("id"),
                "feed": feed,
            }
            with self._lock:
                bar_store = self._shadow_bars if shadow else self._bars
                bar_store[symbol] = bar
                stats = self._shadow_stats if shadow else self._stats
                stats["messages_received"] += 1
                stats["last_message_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            return
        bid = message.get("bp")
        ask = message.get("ap")
        trade = message.get("p")
        bid_value = _float_or_none(bid)
        ask_value = _float_or_none(ask)
        trade_value = _float_or_none(trade)
        try:
            price = trade_value if trade_value is not None else (
                (bid_value + ask_value) / 2.0
                if bid_value is not None and ask_value is not None
                else 0.0
            )
        except (TypeError, ValueError):
            return
        if price <= 0.0:
            return
        now = time.time()
        quote_quality = (
            "live_ws_crypto_observation" if stream == "crypto"
            else "shadow_ws_sip_observation" if shadow
            else "live_ws_sip_observation" if feed == "sip"
            else "live_ws_iex_observation"
        )
        with self._lock:
            quote_store = (
                self._crypto_quotes if stream == "crypto"
                else self._shadow_quotes if shadow
                else self._quotes
            )
            prior = dict(quote_store.get(symbol) or {})
            quote = {
                **prior,
                "symbol": symbol,
                "price": price,
                "bid": bid_value if bid_value is not None else prior.get("bid"),
                "ask": ask_value if ask_value is not None else prior.get("ask"),
                # Crypto consumers use the exact provider string as the
                # canonical timestamp. Equity compatibility retains its
                # historical epoch representation.
                "quote_timestamp": str(message.get("t") or "") if stream == "crypto" else provider_epoch,
                "provider_quote_timestamp": str(message.get("t") or ""),
                "provider_native_timestamp": str(message.get("t") or ""),
                "receive_timestamp": now,
                "receive_timestamp_utc": datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z"),
                "provider_used": provider_name,
                "provider": provider_name,
                "provider_provenance": provider_provenance,
                "quote_quality": quote_quality,
                "consolidated_market_truth": False,
                "market_observation_only": True,
                "shadow_only": bool(shadow),
                "observation_authority": not bool(shadow),
                "message_type": "trade" if message_type == "t" else "quote",
                "quote_record_id": message.get("i") or message.get("id"),
                "feed": "crypto_us" if stream == "crypto" else feed,
            }
            quote_store[symbol] = quote
            stats = self._crypto_stats if stream == "crypto" else self._shadow_stats if shadow else self._stats
            stats["messages_received"] += 1
            stats["last_message_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _read_messages(
        self,
        connection: Any,
        *,
        stream: str = "equity",
        shadow: bool = False,
    ) -> None:
        try:
            raw = connection.recv(timeout=1.0)
        except TimeoutError:
            return
        payload = json.loads(raw)
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if isinstance(row, dict):
                self._record_message(row, stream=stream, shadow=shadow)

    @staticmethod
    def _crypto_stream_enabled() -> bool:
        return _enabled(
            "ASTRA_ALPACA_CRYPTO_WS_ENABLED",
            _enabled("ASTRA_ALPACA_WS_ENABLED", False),
        )

    @staticmethod
    def _public_crypto_stream_enabled() -> bool:
        # Public streams are only subscribed for the worker's bounded active
        # crypto symbol set. They remain read-only fallback observations.
        return _enabled(
            "ASTRA_CRYPTO_PUBLIC_WS_FALLBACK_ENABLED",
            AlpacaWSMonitor._crypto_stream_enabled(),
        )

    @staticmethod
    def _public_crypto_endpoint(provider: str) -> str:
        return {
            "KRAKEN": "wss://ws.kraken.com/v2",
            "COINBASE": "wss://advanced-trade-ws.coinbase.com",
        }.get(str(provider or "").upper(), "")

    def _selected_crypto_quote(self, symbol: str, *, max_age_seconds: float = 20.0) -> dict[str, Any] | None:
        pair = canonical_crypto_market_symbol_v1(symbol)["internal_pair"]
        with self._lock:
            selected = select_crypto_websocket_quote_v1(
                self._crypto_quotes.get(pair),
                self._public_crypto_quotes["KRAKEN"].get(pair),
                self._public_crypto_quotes["COINBASE"].get(pair),
                max_age_seconds=max_age_seconds,
            )
        return selected

    def _record_public_crypto_message(self, provider: str, message: dict[str, Any]) -> None:
        """Record only valid provider-native public BBO observations."""
        name = str(provider or "").upper()
        if name not in self._public_crypto_quotes:
            return
        receive = time.time()
        rows = normalize_public_crypto_websocket_quote_v1(name, message, receive_timestamp=receive)
        if not rows:
            return
        with self._lock:
            quotes = self._public_crypto_quotes[name]
            for row in rows:
                symbol = str(row.get("symbol") or "")
                if symbol in self._desired_crypto_symbols:
                    quotes[symbol] = dict(row)
            stats = self._public_crypto_stats[name]
            stats["messages_received"] += len(rows)
            stats["last_error"] = ""
            stats["last_message_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _send_public_crypto_subscriptions(self, connection: Any, provider: str) -> None:
        with self._lock:
            symbols = sorted(self._desired_crypto_symbols)
        if provider == "KRAKEN":
            self._send(connection, {
                "method": "subscribe",
                "params": {"channel": "ticker", "symbol": symbols, "event_trigger": "bbo", "snapshot": True},
            })
        elif provider == "COINBASE":
            products = [pair.replace("/", "-") for pair in symbols]
            self._send(connection, {"type": "subscribe", "channel": "ticker", "product_ids": products})
            # Coinbase documents heartbeat as the public way to retain sparse
            # subscriptions; heartbeat records are not quote evidence.
            self._send(connection, {"type": "subscribe", "channel": "heartbeats"})

    def _run_public_crypto_stream(self, provider: str) -> None:
        retry_seconds = 1.0
        name = str(provider or "").upper()
        endpoint = self._public_crypto_endpoint(name)
        while not self._stop.is_set() and self._stream_desired("crypto") and endpoint:
            connector = self._connector()
            if connector is None:
                with self._lock:
                    stats = self._public_crypto_stats[name]
                    stats["errors"] += 1
                    stats["last_error"] = "websocket_client_unavailable"
                break
            connection = None
            try:
                connection = connector(endpoint, open_timeout=8, close_timeout=3, ping_interval=20.0, ping_timeout=None)
                with self._lock:
                    self._public_crypto_connections[name] = connection
                    stats = self._public_crypto_stats[name]
                    stats["subscription_state"] = "SUBSCRIBING"
                    stats["last_error"] = ""
                    stats["last_connected_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                self._send_public_crypto_subscriptions(connection, name)
                while not self._stop.is_set() and self._stream_desired("crypto"):
                    try:
                        raw = connection.recv(timeout=1.0)
                    except TimeoutError:
                        continue
                    message = json.loads(raw)
                    with self._lock:
                        stats = self._public_crypto_stats[name]
                        if ((name == "KRAKEN" and message.get("method") == "subscribe" and message.get("success") is True)
                                or (name == "COINBASE" and message.get("channel") == "subscriptions")):
                            stats["subscription_state"] = "SUBSCRIBED"
                    self._record_public_crypto_message(name, message)
                    retry_seconds = 1.0
            except Exception as exc:
                if not self._stop.is_set() and self._stream_desired("crypto"):
                    with self._lock:
                        stats = self._public_crypto_stats[name]
                        stats["errors"] += 1
                        stats["reconnects"] += 1
                        stats["last_error"] = str(exc)[:180]
                        stats["last_disconnected_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                        stats["subscription_state"] = "FAILED"
            finally:
                with self._lock:
                    if self._public_crypto_connections.get(name) is connection:
                        self._public_crypto_connections[name] = None
                try:
                    if connection is not None:
                        connection.close()
                except Exception:
                    pass
            if self._stop.is_set() or not self._stream_desired("crypto"):
                break
            self._wake.wait(timeout=min(30.0, retry_seconds))
            self._wake.clear()
            retry_seconds = min(30.0, retry_seconds * 2.0)

    def _stream_desired(self, stream: str) -> set[str]:
        with self._lock:
            return set(self._desired_crypto_symbols if stream == "crypto" else self._desired_symbols)

    def _run(self) -> None:
        """Supervise all provider streams inside the single worker owner."""
        if not self._is_canonical_owner():
            return
        while not self._stop.is_set():
            streams = ("equity", "equity_shadow", "crypto")
            for stream in streams:
                enabled = (
                    self._crypto_stream_enabled() if stream == "crypto"
                    else self._shadow_stream_enabled() if stream == "equity_shadow"
                    else _enabled("ASTRA_ALPACA_WS_ENABLED", False)
                )
                if not enabled or not self._stream_desired(stream):
                    continue
                thread = self._stream_threads.get(stream)
                if thread is None or not thread.is_alive():
                    thread = threading.Thread(
                        target=self._run_stream,
                        args=(stream,),
                        name=f"astra-alpaca-{stream}-observer",
                        daemon=True,
                    )
                    self._stream_threads[stream] = thread
                    thread.start()
            if self._public_crypto_stream_enabled() and self._stream_desired("crypto"):
                for provider in ("KRAKEN", "COINBASE"):
                    stream = f"public_crypto_{provider.lower()}"
                    thread = self._stream_threads.get(stream)
                    if thread is None or not thread.is_alive():
                        thread = threading.Thread(
                            target=self._run_public_crypto_stream,
                            args=(provider,),
                            name=f"astra-{provider.lower()}-crypto-observer",
                            daemon=True,
                        )
                        self._stream_threads[stream] = thread
                        thread.start()
            self._wake.wait(timeout=0.25)
            self._wake.clear()
        with self._lock:
            connections = [
                self._connection,
                self._shadow_connection,
                self._crypto_connection,
                *self._public_crypto_connections.values(),
            ]
        for connection in connections:
            try:
                if connection is not None:
                    connection.close()
            except Exception:
                pass
        for thread in list(self._stream_threads.values()):
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._stream_threads.clear()

    def _run_stream(self, stream: str) -> None:
        """Run one independently reconnecting feed without affecting the other."""
        retry_seconds = 1.0
        crypto = stream == "crypto"
        shadow = stream == "equity_shadow"
        while not self._stop.is_set() and self._stream_desired(stream):
            feed, feed_error = (
                ("crypto", "") if crypto
                else self._equity_feed(shadow=shadow)
            )
            if feed_error:
                with self._lock:
                    stats = self._crypto_stats if crypto else self._shadow_stats if shadow else self._stats
                    stats["last_error"] = feed_error
                    stats["errors"] += 1
                    stats["auth_state"] = "BLOCKED"
                    stats["subscription_state"] = "BLOCKED"
                self._wake.wait(timeout=15.0)
                self._wake.clear()
                continue
            key, secret = self._credentials()
            connector = self._connector()
            if not key or not secret or connector is None:
                with self._lock:
                    stats = self._crypto_stats if crypto else self._shadow_stats if shadow else self._stats
                    stats["last_error"] = "credentials_or_websocket_client_unavailable"
                    stats["errors"] += 1
                self._wake.wait(timeout=15.0)
                self._wake.clear()
                continue
            connection = None
            try:
                # Keep protocol pings, but use application message flow and
                # explicit acknowledgements as transport health evidence. A
                # missed Pong must not create an unbounded reconnect storm.
                connection = connector(
                    self._crypto_endpoint() if crypto else self._endpoint(shadow=shadow),
                    open_timeout=8,
                    close_timeout=3,
                    ping_interval=20.0,
                    ping_timeout=None,
                )
                with self._lock:
                    stats = self._crypto_stats if crypto else self._shadow_stats if shadow else self._stats
                    if crypto:
                        self._crypto_connection = connection
                        self._subscribed_crypto_symbols = set()
                    elif shadow:
                        self._shadow_connection = connection
                        self._shadow_subscribed_symbols = set()
                        self._shadow_subscribed_bar_symbols = set()
                    else:
                        self._connection = connection
                        self._subscribed_symbols = set()
                        self._subscribed_bar_symbols = set()
                    stats["auth_state"] = "AUTHENTICATING"
                    stats["subscription_state"] = "UNSUBSCRIBED"
                    stats["last_connected_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                self._send(connection, {"action": "auth", "key": key, "secret": secret})
                self._wait_for_control(
                    connection,
                    message_type="success",
                    message="authenticated",
                    stream="crypto" if crypto else "equity",
                    shadow=shadow,
                )
                with self._lock:
                    stats = self._crypto_stats if crypto else self._shadow_stats if shadow else self._stats
                    stats["auth_state"] = "AUTHENTICATED"
                if self._sync_subscriptions(
                    connection,
                    stream="crypto" if crypto else "equity",
                    shadow=shadow,
                    mark_subscribed=False,
                ):
                    subscription_ack = self._wait_for_control(
                        connection,
                        message_type="subscription",
                        stream="crypto" if crypto else "equity",
                        shadow=shadow,
                    )
                    self._apply_subscription_ack(subscription_ack, stream="crypto" if crypto else "equity", shadow=shadow)
                else:
                    with self._lock:
                        stats = self._crypto_stats if crypto else self._shadow_stats if shadow else self._stats
                        stats["subscription_state"] = "EMPTY"
                while not self._stop.is_set() and self._stream_desired(stream):
                    if self._sync_subscriptions(
                        connection,
                        stream="crypto" if crypto else "equity",
                        shadow=shadow,
                        mark_subscribed=False,
                    ):
                        subscription_ack = self._wait_for_control(
                            connection,
                            message_type="subscription",
                            stream="crypto" if crypto else "equity",
                            shadow=shadow,
                        )
                        self._apply_subscription_ack(subscription_ack, stream="crypto" if crypto else "equity", shadow=shadow)
                    with self._lock:
                        stats = self._crypto_stats if crypto else self._shadow_stats if shadow else self._stats
                        messages_before = int(stats.get("messages_received") or 0)
                    self._read_messages(
                        connection,
                        stream="crypto" if crypto else "equity",
                        shadow=shadow,
                    )
                    with self._lock:
                        if int(stats.get("messages_received") or 0) > messages_before:
                            retry_seconds = 1.0
            except Exception as exc:
                if not self._stop.is_set() and self._stream_desired(stream):
                    with self._lock:
                        stats = self._crypto_stats if crypto else self._shadow_stats if shadow else self._stats
                        stats["errors"] += 1
                        stats["last_error"] = str(exc)[:180]
                        stats["reconnects"] += 1
                        stats["last_disconnected_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                        if crypto:
                            self._subscribed_crypto_symbols = set()
                        elif shadow:
                            self._shadow_subscribed_symbols = set()
                            self._shadow_subscribed_bar_symbols = set()
                        else:
                            self._subscribed_symbols = set()
                            self._subscribed_bar_symbols = set()
                        stats["auth_state"] = "FAILED"
                        stats["subscription_state"] = "FAILED"
            finally:
                with self._lock:
                    if crypto and self._crypto_connection is connection:
                        self._crypto_connection = None
                    if shadow and self._shadow_connection is connection:
                        self._shadow_connection = None
                    if not crypto and self._connection is connection:
                        self._connection = None
                try:
                    if connection is not None:
                        connection.close()
                except Exception:
                    pass
            if self._stop.is_set() or not self._stream_desired(stream):
                break
            self._wake.wait(timeout=min(30.0, retry_seconds))
            self._wake.clear()
            retry_seconds = min(30.0, retry_seconds * 2.0)

    def get_quote(self, symbol: str, max_age_seconds: float = 20, **_: Any) -> dict[str, Any] | None:
        sym = str(symbol or "").upper().strip()
        with self._lock:
            quote = dict(self._quotes.get(sym) or {})
            if not quote and ("/" in sym or sym.endswith("USD")):
                try:
                    crypto_sym = canonical_crypto_market_symbol_v1(sym)["internal_pair"]
                except (TypeError, ValueError, IndexError):
                    crypto_sym = ""
                # Preserve the legacy direct-monitor contract for Alpaca rows;
                # authoritative active-position observations use the native
                # freshness selector in status().  Direct callers can use a
                # public fallback only when Alpaca has no current row at all.
                quote = dict(self._crypto_quotes.get(crypto_sym) or {}) if crypto_sym else {}
                if not quote and crypto_sym:
                    quote = dict(select_crypto_websocket_quote_v1(
                        None,
                        self._public_crypto_quotes["KRAKEN"].get(crypto_sym),
                        self._public_crypto_quotes["COINBASE"].get(crypto_sym),
                        max_age_seconds=max_age_seconds,
                    ) or {})
        if not quote:
            shared = self._read_shared_status()
            shared_observations = dict(shared.get("observations") or {})
            quote = dict(shared_observations.get(sym) or {})
            if not quote and ("/" in sym or sym.endswith("USD")):
                try:
                    crypto_sym = canonical_crypto_market_symbol_v1(sym)["internal_pair"]
                except (TypeError, ValueError, IndexError):
                    crypto_sym = ""
                quote = dict(shared_observations.get(crypto_sym) or {}) if crypto_sym else {}
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

    def compare_shadow(self, symbols: list[str] | None = None) -> dict[str, Any]:
        """Return bounded IEX/SIP diagnostics without changing quote authority."""
        requested = self._equity_symbol_set(symbols) if symbols is not None else None
        with self._lock:
            names = sorted(requested or (set(self._desired_symbols) | set(self._shadow_quotes)))
            primary = {symbol: dict(self._quotes.get(symbol) or {}) for symbol in names}
            shadow = {symbol: dict(self._shadow_quotes.get(symbol) or {}) for symbol in names}
            primary_bars = {symbol: dict(self._bars.get(symbol) or {}) for symbol in names}
            shadow_bars = {symbol: dict(self._shadow_bars.get(symbol) or {}) for symbol in names}
        now = time.time()
        comparisons: list[dict[str, Any]] = []
        for symbol in names:
            left = primary[symbol]
            right = shadow[symbol]
            left_receive = _receive_epoch(left.get("receive_timestamp"))
            right_receive = _receive_epoch(right.get("receive_timestamp"))
            left_price = _float_or_none(left.get("price"))
            right_price = _float_or_none(right.get("price"))
            price_delta = None
            if left_price is not None and right_price is not None:
                price_delta = right_price - left_price
            comparisons.append({
                "symbol": symbol,
                "status": "COMPARABLE" if left and right else "MISSING_PRIMARY_OR_SHADOW",
                "primary": {
                    "provider": left.get("provider_used"),
                    "provider_native_timestamp": left.get("provider_native_timestamp"),
                    "receive_timestamp": left.get("receive_timestamp"),
                    "age_seconds": round(max(0.0, now - left_receive), 3) if left_receive is not None else None,
                    "price": left.get("price"),
                    "bid": left.get("bid"),
                    "ask": left.get("ask"),
                    "message_type": left.get("message_type"),
                    "bar": primary_bars[symbol] or None,
                },
                "shadow": {
                    "provider": right.get("provider_used"),
                    "provider_native_timestamp": right.get("provider_native_timestamp"),
                    "receive_timestamp": right.get("receive_timestamp"),
                    "age_seconds": round(max(0.0, now - right_receive), 3) if right_receive is not None else None,
                    "price": right.get("price"),
                    "bid": right.get("bid"),
                    "ask": right.get("ask"),
                    "message_type": right.get("message_type"),
                    "bar": shadow_bars[symbol] or None,
                },
                "price_delta": price_delta,
            })
        return {
            "mode": "shadow_only",
            "production_authority": "primary_equity_observations",
            "shadow_provider": "ALPACA_WS_SIP_SHADOW",
            "broker_actions": 0,
            "comparisons": comparisons,
        }

    def status(self) -> dict[str, Any]:
        shared = self._read_shared_status()
        if shared:
            shared["consumer_process_role"] = str(os.getenv("ASTRA_PROCESS_ROLE", "api") or "api").strip().lower()
            shared["shared_state_consumed"] = True
            return shared
        with self._lock:
            connected = self._connection is not None
            shadow_connected = self._shadow_connection is not None
            crypto_connected = self._crypto_connection is not None
            desired = sorted(self._desired_symbols)
            desired_crypto = sorted(self._desired_crypto_symbols)
            subscribed = sorted(self._subscribed_symbols)
            shadow_subscribed = sorted(self._shadow_subscribed_symbols)
            subscribed_crypto = sorted(self._subscribed_crypto_symbols)
            stats = dict(self._stats)
            shadow_stats = dict(self._shadow_stats)
            crypto_stats = dict(self._crypto_stats)
            public_crypto_stats = {provider: dict(stats) for provider, stats in self._public_crypto_stats.items()}
            public_connections = {provider: connection is not None for provider, connection in self._public_crypto_connections.items()}
            priorities = {
                "open_positions": len(self._open_symbols),
                "open_crypto_positions": len(self._open_crypto_symbols),
                "near_entry": len(self._near_entry_symbols),
            }
            observations = {
                symbol: dict(self._quotes[symbol])
                for symbol in desired
                if isinstance(self._quotes.get(symbol), dict)
            }
            selected_crypto_observations = {
                symbol: selected
                for symbol in desired_crypto
                if (selected := self._selected_crypto_quote(symbol, max_age_seconds=20.0)) is not None
            }
            observations.update(selected_crypto_observations)
        now = time.time()
        configured_feed, feed_error = self._equity_feed()
        shadow_feed, shadow_feed_error = self._equity_feed(shadow=True)
        connected_at = _utc_epoch(stats.get("last_connected_utc"))
        last_message_at = _utc_epoch(stats.get("last_message_utc"))
        shadow_connected_at = _utc_epoch(shadow_stats.get("last_connected_utc"))
        shadow_last_message_at = _utc_epoch(shadow_stats.get("last_message_utc"))
        crypto_connected_at = _utc_epoch(crypto_stats.get("last_connected_utc"))
        crypto_last_message_at = _utc_epoch(crypto_stats.get("last_message_utc"))
        connected_age = max(0.0, now - connected_at) if connected_at is not None else None
        message_age = max(0.0, now - last_message_at) if last_message_at is not None else None
        shadow_connected_age = max(0.0, now - shadow_connected_at) if shadow_connected_at is not None else None
        shadow_message_age = max(0.0, now - shadow_last_message_at) if shadow_last_message_at is not None else None
        crypto_connected_age = max(0.0, now - crypto_connected_at) if crypto_connected_at is not None else None
        crypto_message_age = max(0.0, now - crypto_last_message_at) if crypto_last_message_at is not None else None
        stale_stream = bool(desired and connected and (
            (last_message_at is None and connected_age is not None and connected_age > 30.0)
            or (message_age is not None and message_age > 60.0)
        ))
        crypto_stale_stream = bool(desired_crypto and crypto_connected and (
            (crypto_last_message_at is None and crypto_connected_age is not None and crypto_connected_age > 30.0)
            or (crypto_message_age is not None and crypto_message_age > 60.0)
        ))
        shadow_stale_stream = bool(desired and shadow_connected and (
            (shadow_last_message_at is None and shadow_connected_age is not None and shadow_connected_age > 30.0)
            or (shadow_message_age is not None and shadow_message_age > 60.0)
        ))
        shadow_reconnect_storm = bool(
            desired
            and int(shadow_stats.get("errors") or 0) >= 3
            and int(shadow_stats.get("reconnects") or 0) >= 3
            and int(shadow_stats.get("messages_received") or 0) == 0
        )
        reconnect_storm = bool(
            desired
            and int(stats.get("errors") or 0) >= 3
            and int(stats.get("reconnects") or 0) >= 3
            and int(stats.get("messages_received") or 0) == 0
        )
        crypto_reconnect_storm = bool(
            desired_crypto
            and int(crypto_stats.get("errors") or 0) >= 3
            and int(crypto_stats.get("reconnects") or 0) >= 3
            and int(crypto_stats.get("messages_received") or 0) == 0
        )
        transport_health = "IDLE"
        equity_health = "IDLE"
        if desired:
            if reconnect_storm or not connected:
                equity_health = "UNHEALTHY"
            elif stats.get("auth_state") != "AUTHENTICATED" or stats.get("subscription_state") != "SUBSCRIBED":
                equity_health = "UNHEALTHY"
            elif stale_stream:
                equity_health = "DEGRADED"
            else:
                equity_health = "HEALTHY"
        crypto_health = "IDLE"
        if desired_crypto:
            if crypto_reconnect_storm or not crypto_connected:
                crypto_health = "UNHEALTHY"
            elif crypto_stats.get("auth_state") != "AUTHENTICATED" or crypto_stats.get("subscription_state") != "SUBSCRIBED":
                crypto_health = "UNHEALTHY"
            elif crypto_stale_stream:
                crypto_health = "DEGRADED"
            else:
                crypto_health = "HEALTHY"
        shadow_health = "IDLE"
        if _enabled("ASTRA_ALPACA_WS_SHADOW_ENABLED", False) and desired:
            if shadow_feed_error or shadow_reconnect_storm:
                shadow_health = "UNHEALTHY"
            elif not shadow_connected:
                shadow_health = "UNHEALTHY"
            elif shadow_stats.get("auth_state") != "AUTHENTICATED" or shadow_stats.get("subscription_state") != "SUBSCRIBED":
                shadow_health = "UNHEALTHY"
            elif shadow_stale_stream:
                shadow_health = "DEGRADED"
            else:
                shadow_health = "HEALTHY"
        health_values = [value for value in (equity_health, crypto_health) if value != "IDLE"]
        transport_health = "UNHEALTHY" if "UNHEALTHY" in health_values else (
            "DEGRADED" if "DEGRADED" in health_values else ("HEALTHY" if health_values else "IDLE")
        )
        return {
            "enabled": _enabled("ASTRA_ALPACA_WS_ENABLED", False) or self._shadow_stream_enabled() or self._crypto_stream_enabled(),
            "running": bool(connected or shadow_connected or crypto_connected or any(public_connections.values())),
            "connection_count": int(bool(connected)) + int(bool(shadow_connected)) + int(bool(crypto_connected)) + sum(int(value) for value in public_connections.values()),
            "equity_connection_count": int(bool(connected)),
            "crypto_connection_count": int(bool(crypto_connected)),
            "public_crypto_connection_count": sum(int(value) for value in public_connections.values()),
            "feed": configured_feed or "",
            "endpoint": self._endpoint() if configured_feed else "",
            "feed_selection_error": feed_error,
            "sip_entitlement_verified": _enabled("ASTRA_ALPACA_SIP_ENTITLEMENT_VERIFIED", False),
            "crypto_feed": "us",
            "provider_provenance": "FAST_SIP_OBSERVATION" if configured_feed == "sip" else "FAST_IEX_OBSERVATION",
            "consolidated_market_truth": False,
            "desired_symbol_count": len(desired),
            "active_symbol_count": len(subscribed),
            "subscribed_symbols": subscribed,
            "subscribed_bars": sorted(self._subscribed_bar_symbols),
            "desired_symbols": desired,
            "shadow_enabled": bool(_enabled("ASTRA_ALPACA_WS_SHADOW_ENABLED", False)),
            "shadow_feed": shadow_feed or "",
            "shadow_endpoint": self._endpoint(shadow=True) if shadow_feed else "",
            "shadow_feed_selection_error": shadow_feed_error,
            "shadow_connection_count": int(bool(shadow_connected)),
            "shadow_subscribed_symbols": shadow_subscribed,
            "shadow_subscribed_bars": sorted(self._shadow_subscribed_bar_symbols),
            "shadow_observations": {
                symbol: dict(self._shadow_quotes[symbol])
                for symbol in desired
                if isinstance(self._shadow_quotes.get(symbol), dict)
            },
            "shadow_bars": {
                symbol: dict(self._shadow_bars[symbol])
                for symbol in desired
                if isinstance(self._shadow_bars.get(symbol), dict)
            },
            "shadow_stats": shadow_stats,
            "shadow_transport_health": shadow_health,
            "crypto_desired_symbol_count": len(desired_crypto),
            "crypto_active_symbol_count": len(subscribed_crypto),
            "crypto_subscribed_symbols": subscribed_crypto,
            "crypto_desired_symbols": desired_crypto,
            "priority_classes": priorities,
            "owner_process_role": "worker" if self._is_canonical_owner() else "api",
            "shared_state_consumed": False,
            "observations": observations,
            "crypto_public_fallback_enabled": self._public_crypto_stream_enabled(),
            "crypto_public_fallback_stats": public_crypto_stats,
            "crypto_public_fallback_connections": public_connections,
            "crypto_provider_selection": {
                symbol: selected.get("crypto_fallback_selection_state")
                for symbol, selected in selected_crypto_observations.items()
            },
            "transport_health": transport_health,
            "equity_transport_health": equity_health,
            "crypto_transport_health": crypto_health,
            "stale_stream": stale_stream,
            "crypto_stale_stream": crypto_stale_stream,
            "connected_age_seconds": round(connected_age, 3) if connected_age is not None else None,
            "last_message_age_seconds": round(message_age, 3) if message_age is not None else None,
            "stats": stats,
            "shadow_connected_age_seconds": round(shadow_connected_age, 3) if shadow_connected_age is not None else None,
            "shadow_last_message_age_seconds": round(shadow_message_age, 3) if shadow_message_age is not None else None,
            "shadow_stale_stream": shadow_stale_stream,
            "crypto_stats": crypto_stats,
            "crypto_connected_age_seconds": round(crypto_connected_age, 3) if crypto_connected_age is not None else None,
            "crypto_last_message_age_seconds": round(crypto_message_age, 3) if crypto_message_age is not None else None,
        }

    def contention_diagnostics(self) -> dict[str, Any]:
        status = self.status()
        return {
            "ok": True,
            "connection_count": status["connection_count"],
            "desired_symbol_count": status["desired_symbol_count"] + status.get("crypto_desired_symbol_count", 0),
            "active_symbol_count": status["active_symbol_count"] + status.get("crypto_active_symbol_count", 0),
            "reconnects": status["stats"].get("reconnects", 0),
            "crypto_reconnects": status.get("crypto_stats", {}).get("reconnects", 0),
            "last_error": status["stats"].get("last_error", "") or status.get("crypto_stats", {}).get("last_error", ""),
        }

    def reset_for_diagnostics(self, *, restart: bool = True, **_: Any) -> dict[str, Any]:
        self._wake.set()
        if restart:
            self._ensure_thread()
        return {"ok": True, "restart_requested": bool(restart), "connection_count": self.status()["connection_count"]}

    def request_reconnect(self) -> dict[str, Any]:
        """Request one bounded reconnect on the existing monitor thread."""
        with self._lock:
            connections = [self._connection, self._crypto_connection, *self._public_crypto_connections.values()]
        self._wake.set()
        for connection in connections:
            try:
                if connection is not None:
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
