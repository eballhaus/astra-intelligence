from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
MOBILE_ACTIVE_POSITION_LIMIT = 5
DESKTOP_ACTIVE_POSITION_LIMIT = 10
RECENT_ORDER_PREVIEW_LIMIT = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "") -> str:
    s = str(value if value is not None else default).strip()
    return s or str(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        if not math.isfinite(out):
            return float(default)
        return out
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker")).upper()


def _order_is_canceled_zero_fill(row: dict[str, Any]) -> bool:
    status = _text(row.get("status")).lower()
    filled = _to_float(row.get("filled_qty") or row.get("filled_quantity"), 0.0)
    return status in {"canceled", "cancelled"} and filled <= 0.0


def _order_time(row: dict[str, Any]) -> str:
    for key in ("canceled_at", "updated_at", "submitted_at", "created_at", "filled_at"):
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _sanitize_position(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    symbol = _symbol(row)
    current = row.get("current_price") or row.get("price") or row.get("mark_price") or row.get("lastday_price")
    entry = row.get("avg_entry_price") or row.get("entry_price") or row.get("average_entry_price")
    pnl_pc = row.get("unrealized_plpc")
    if pnl_pc is not None:
        pnl_pct = _to_float(pnl_pc, 0.0) * (100.0 if abs(_to_float(pnl_pc, 0.0)) <= 1.5 else 1.0)
    else:
        pnl_pct = _to_float(row.get("pnl_percent") or row.get("unrealized_pnl_percent"), 0.0)
    return {
        **dict(row),
        "symbol": symbol or _text(row.get("symbol") or row.get("ticker") or "—"),
        "broker_position_source": source,
        "display_position_source": source,
        "position_truth_source": source,
        "status": _text(row.get("status") or row.get("position_status") or ("broker_active" if source == "broker" else "internal_workflow")),
        "current_price": _to_float(current, 0.0) if current is not None else None,
        "price": _to_float(current, 0.0) if current is not None else None,
        "entry_price": _to_float(entry, 0.0) if entry is not None else None,
        "pnl_percent": round(pnl_pct, 4),
        "management_note": _text(
            row.get("management_note")
            or row.get("position_note")
            or row.get("rationale")
            or ("Broker-confirmed Alpaca paper position." if source == "broker" else "Internal paper workflow row; not broker-confirmed."),
        ),
    }


class MobileRuntimeCompactionV1:
    """Compact mobile runtime payloads without deleting broker or learning history."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def build(
        self,
        *,
        internal_positions: list[dict[str, Any]] | None = None,
        broker_positions_payload: dict[str, Any] | None = None,
        broker_orders_payload: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached

        internal_rows = [dict(r) for r in (internal_positions or []) if isinstance(r, dict)]
        broker_payload = dict(broker_positions_payload or {}) if isinstance(broker_positions_payload, dict) else {}
        orders_payload = dict(broker_orders_payload or {}) if isinstance(broker_orders_payload, dict) else {}
        broker_fetch_ok = bool(broker_payload.get("ok", True) if broker_payload else False)
        broker_enabled = bool(broker_payload.get("broker_execution_enabled") or broker_payload.get("enabled") or broker_payload.get("paper_mode_verified"))
        broker_positions_raw = broker_payload.get("positions") if isinstance(broker_payload.get("positions"), list) else []
        broker_positions = [_sanitize_position(r, source="broker") for r in broker_positions_raw if isinstance(r, dict)]
        broker_symbols = {_symbol(r) for r in broker_positions if _symbol(r)}
        internal_symbols = {_symbol(r) for r in internal_rows if _symbol(r)}
        stale_rows = []
        workflow_rows = []
        for row in internal_rows:
            sym = _symbol(row)
            item = _sanitize_position(row, source="internal_workflow")
            if broker_enabled and broker_fetch_ok and sym and sym not in broker_symbols:
                item["broker_confirmation_status"] = "stale_internal_position"
                item["stale_internal_position"] = True
                stale_rows.append(item)
            else:
                item["broker_confirmation_status"] = "broker_unconfirmed" if broker_enabled else "internal_only"
                item["broker_unconfirmed"] = bool(broker_enabled and sym not in broker_symbols)
                workflow_rows.append(item)

        orders = [dict(r) for r in (orders_payload.get("orders") if isinstance(orders_payload.get("orders"), list) else []) if isinstance(r, dict)]
        canceled = [r for r in orders if _order_is_canceled_zero_fill(r)]
        meaningful_orders = [r for r in orders if not _order_is_canceled_zero_fill(r)]
        canceled_symbols = sorted({_symbol(r) for r in canceled if _symbol(r)})[:12]
        canceled_times = sorted([_order_time(r) for r in canceled if _order_time(r)])
        time_range = {
            "start": canceled_times[0] if canceled_times else "",
            "end": canceled_times[-1] if canceled_times else "",
        }
        display_positions = broker_positions if broker_enabled and broker_fetch_ok else workflow_rows
        stale_hidden = len(stale_rows) if broker_enabled and broker_fetch_ok else 0
        hidden_mobile = max(0, len(display_positions) - MOBILE_ACTIVE_POSITION_LIMIT)
        hidden_desktop = max(0, len(display_positions) - DESKTOP_ACTIVE_POSITION_LIMIT)
        canceled_count = int(len(canceled))
        compaction_reason = (
            f"{canceled_count} canceled zero-fill paper orders hidden from compact runtime views; full broker history remains in Alpaca."
            if canceled_count > 0
            else "No canceled zero-fill broker orders were included in the compact runtime payload."
        )
        payload = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_display_compaction",
            "mobile_runtime_compaction_active": True,
            "true_broker_active_positions": int(len(broker_positions)) if broker_enabled and broker_fetch_ok else None,
            "broker_positions_fetch_ok": bool(broker_fetch_ok),
            "internal_open_workflow_rows": int(len(internal_rows)),
            "stale_internal_positions": int(len(stale_rows)),
            "stale_internal_positions_symbols": sorted({_symbol(r) for r in stale_rows if _symbol(r)})[:24],
            "display_active_positions_count": int(len(display_positions)),
            "active_positions_count": int(len(display_positions)),
            "hidden_positions_count": int(hidden_mobile),
            "desktop_hidden_positions_count": int(hidden_desktop),
            "active_positions_preview_limit": MOBILE_ACTIVE_POSITION_LIMIT,
            "desktop_active_positions_preview_limit": DESKTOP_ACTIVE_POSITION_LIMIT,
            "recent_orders_preview_limit": RECENT_ORDER_PREVIEW_LIMIT,
            "recent_orders_displayed_count": int(min(len(meaningful_orders), RECENT_ORDER_PREVIEW_LIMIT)),
            "canceled_order_history_count": int(canceled_count),
            "canceled_order_compaction_active": True,
            "canceled_orders_compacted_count": int(canceled_count),
            "canceled_symbols_summary": canceled_symbols,
            "canceled_order_time_range": time_range,
            "compaction_reason": compaction_reason,
            "stale_rows_hidden_count": int(stale_hidden),
            "learning_fast_path_active": True,
            "canceled_order_scan_skipped": bool(not orders),
            "learning_payload_compacted": True,
            "mobile_payload_compacted": True,
            "full_history_preserved": True,
            "replay_learning_preserved": True,
            "true_broker_positions_preview": display_positions[:MOBILE_ACTIVE_POSITION_LIMIT],
            "desktop_positions_preview": display_positions[:DESKTOP_ACTIVE_POSITION_LIMIT],
            "internal_workflow_preview": workflow_rows[:3],
            "stale_internal_positions_preview": stale_rows[:5],
            "recent_meaningful_orders_preview": meaningful_orders[:RECENT_ORDER_PREVIEW_LIMIT],
            "summary": self.summary_from_counts(len(broker_positions), len(internal_rows), len(stale_rows), canceled_count),
            "api_calls_used": _to_int(broker_payload.get("api_calls_used"), 0) + _to_int(orders_payload.get("api_calls_used"), 0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "market_session_blocking_preserved": True,
            "generated_at": _now_iso(),
        }
        payload["cache_hit"] = False
        payload["cache_age_seconds"] = 0.0
        payload["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        self._cache = dict(payload)
        self._cache_ts = now
        return payload

    @staticmethod
    def summary_from_counts(broker_count: int, internal_count: int, stale_count: int, canceled_count: int) -> str:
        if broker_count <= 0:
            base = "No broker-confirmed active positions."
        else:
            base = f"{broker_count} broker-confirmed active position{'s' if broker_count != 1 else ''}."
        details: list[str] = []
        if stale_count > 0:
            details.append(f"{stale_count} stale internal workflow row{'s' if stale_count != 1 else ''} hidden from active view")
        elif internal_count > broker_count:
            details.append(f"{max(0, internal_count - broker_count)} internal workflow row{'s' if internal_count - broker_count != 1 else ''} kept out of broker-active view")
        if canceled_count > 0:
            details.append(f"{canceled_count} canceled paper order{'s' if canceled_count != 1 else ''} compacted")
        if not details:
            details.append("runtime payload already compact")
        return base + " " + "; ".join(details) + "."

    def compact_positions_response(
        self,
        base_payload: dict[str, Any],
        *,
        compaction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(base_payload or {})
        compact = dict(compaction or self._cache or {})
        if compact.get("mobile_runtime_compaction_active"):
            positions = compact.get("desktop_positions_preview") or compact.get("true_broker_positions_preview")
            if isinstance(positions, list):
                payload["positions"] = positions
                payload["count"] = int(compact.get("display_active_positions_count") or len(positions))
                payload["total_open_positions"] = int(compact.get("display_active_positions_count") or len(positions))
            payload["mobile_runtime_compaction"] = {k: v for k, v in compact.items() if k not in {"true_broker_positions_preview", "desktop_positions_preview", "internal_workflow_preview", "stale_internal_positions_preview", "recent_meaningful_orders_preview"}}
            payload["position_display_truth_source"] = "alpaca_broker_positions" if compact.get("broker_positions_fetch_ok") else "internal_workflow_fallback"
            payload["true_broker_active_positions"] = compact.get("true_broker_active_positions")
            payload["internal_open_workflow_rows"] = compact.get("internal_open_workflow_rows")
            payload["stale_internal_positions"] = compact.get("stale_internal_positions")
            payload["display_active_positions_count"] = compact.get("display_active_positions_count")
            payload["stale_rows_hidden_count"] = compact.get("stale_rows_hidden_count")
            payload["canceled_orders_compacted_count"] = compact.get("canceled_orders_compacted_count")
            payload["mobile_payload_compacted"] = True
            payload["learning_payload_compacted"] = True
            payload["full_history_preserved"] = True
            payload["replay_learning_preserved"] = True
        return payload
