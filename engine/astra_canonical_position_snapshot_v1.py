"""Canonical broker-position snapshot normalization.

Normalizes current Alpaca paper broker positions into a consistent format
for consumption by Peak Memory, Loss Containment, Profit Protection,
Exit Readiness, and Unified Position Advisory.

Does NOT make broker or network calls. Pure normalization of already-fetched data.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_canonical_position_snapshot_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _atomic_write(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _load_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_canonical_position_snapshot(
    broker_positions: Mapping[str, Mapping[str, Any]],
    *,
    snapshot_timestamp: str | None = None,
) -> dict[str, Any]:
    """Build a canonical normalized snapshot from broker position data.

    Input: broker_position_by_symbol dict (symbol -> Alpaca position dict)
    Output: canonical snapshot with normalized positions

    Deduplicates by symbol. Preserves broker timestamps. Marks dust.
    """
    as_of = snapshot_timestamp or _now_iso()
    positions: dict[str, dict[str, Any]] = {}
    dust_positions: list[str] = []
    closed_positions: list[str] = []
    errors: list[str] = []

    for symbol, bp in broker_positions.items():
        if not isinstance(bp, dict):
            continue

        symbol_upper = _text(bp.get("symbol") or symbol).upper()
        if not symbol_upper:
            continue

        qty = _num(bp.get("qty"), 0.0)
        if qty is None or qty <= 0:
            closed_positions.append(symbol_upper)
            continue

        avg_entry_price = _num(bp.get("avg_entry_price"), 0.0)
        current_price = _num(bp.get("current_price"), 0.0)
        market_value = _num(bp.get("market_value"), 0.0)
        cost_basis = _num(bp.get("cost_basis"), 0.0)
        unrealized_pl = _num(bp.get("unrealized_pl"), 0.0)
        unrealized_plpc = _num(bp.get("unrealized_plpc"), 0.0)
        change_today = _num(bp.get("change_today"), 0.0)
        qty_available = _num(bp.get("qty_available"), 0.0)
        asset_class = _text(bp.get("asset_class"), "equity").lower()
        side = _text(bp.get("side"), "long")

        # Calculate return percentage
        if cost_basis and cost_basis > 0:
            return_pct = ((market_value - cost_basis) / cost_basis) * 100.0
        elif avg_entry_price and avg_entry_price > 0 and current_price > 0:
            return_pct = ((current_price - avg_entry_price) / avg_entry_price) * 100.0
        else:
            return_pct = unrealized_plpc * 100.0 if unrealized_plpc else 0.0

        # Dust detection
        is_dust = False
        dust_reason = ""
        if market_value and market_value < 0.01:
            is_dust = True
            dust_reason = "market_value_below_threshold"
        elif qty and qty < 0.001 and asset_class != "crypto":
            is_dust = True
            dust_reason = "quantity_below_threshold"

        if is_dust:
            dust_positions.append(symbol_upper)

        # Broker timestamp preservation - separate from snapshot time
        broker_timestamp = _text(bp.get("timestamp") or bp.get("filled_at") or bp.get("created_at"))
        price_evidence_at = broker_timestamp if broker_timestamp else None

        # Lane and horizon from position data
        # Note: Alpaca positions do NOT have Astra lane/horizon fields.
        # These will be UNAVAILABLE unless enriched from Astra-owned metadata.
        lane = _text(bp.get("lane_id") or bp.get("lane"), "")
        horizon = _text(bp.get("paper_entry_horizon_style") or bp.get("intended_horizon") or bp.get("original_horizon"), "")

        lane_source = "broker_position" if lane else "UNAVAILABLE"
        horizon_source = "broker_position" if horizon else "UNAVAILABLE"

        # Position opened time - from broker if available
        position_opened_at = _text(bp.get("created_at") or bp.get("filled_at"))

        # Evidence freshness - based on actual evidence age, not just price positivity
        if broker_timestamp:
            evidence_freshness = "current"  # Has broker evidence time
        elif current_price and current_price > 0:
            evidence_freshness = "UNAVAILABLE"  # Has price but no broker timestamp
        else:
            evidence_freshness = "stale"

        # Data quality assessment
        data_quality = "complete"
        first_blocker = ""

        if not current_price or current_price <= 0:
            data_quality = "missing_current_price"
            first_blocker = "MISSING_CURRENT_PRICE"
        elif not avg_entry_price or avg_entry_price <= 0:
            data_quality = "missing_entry_price"
            first_blocker = "MISSING_ENTRY_PRICE"
        elif not market_value and not cost_basis:
            data_quality = "missing_value_data"
            first_blocker = "MISSING_VALUE_DATA"

        # Build canonical position record
        positions[symbol_upper] = {
            "symbol": symbol_upper,
            "asset_class": asset_class,
            "quantity": qty,
            "quantity_available": qty_available or qty,
            "side": side,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "average_entry_price": avg_entry_price,
            "current_price": current_price,
            "unrealized_pl": unrealized_pl,
            "unrealized_pl_pct": return_pct,
            "today_pl": change_today * qty if change_today else 0.0,
            "today_pl_pct": change_today * 100.0 if change_today else 0.0,
            "broker_timestamp": broker_timestamp,
            "snapshot_timestamp": as_of,
            "broker_position_evidence_at": broker_timestamp if broker_timestamp else "UNAVAILABLE",
            "price_evidence_at": price_evidence_at if price_evidence_at else "UNAVAILABLE",
            "lane_evidence_at": "UNAVAILABLE",  # Will be enriched from Astra metadata
            "horizon_evidence_at": "UNAVAILABLE",  # Will be enriched from Astra metadata
            "lane": lane if lane else "UNAVAILABLE",
            "lane_source": lane_source,
            "horizon": horizon if horizon else "UNAVAILABLE",
            "horizon_source": horizon_source,
            "position_opened_at": position_opened_at if position_opened_at else "UNAVAILABLE",
            "position_opened_at_source": "broker" if position_opened_at else "UNAVAILABLE",
            "position_age": None,  # Cannot calculate without opened_at
            "evidence_freshness": evidence_freshness,
            "data_quality": data_quality,
            "first_causal_blocker": first_blocker,
            "is_dust": is_dust,
            "dust_reason": dust_reason,
            "broker_asset_id": _text(bp.get("asset_id") or bp.get("id")),
            "exchange": _text(bp.get("exchange")),
            "qty_available_for_sell": qty_available or qty,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_timestamp": as_of,
        "position_count": len(positions),
        "dust_count": len(dust_positions),
        "closed_count": len(closed_positions),
        "error_count": len(errors),
        "positions": positions,
        "dust_symbols": dust_positions,
        "closed_symbols": closed_positions,
        "errors": errors,
    }


def snapshot_to_loss_containment_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert canonical snapshot to loss containment input rows.

    Each row is formatted to be compatible with
    astra_loss_containment_engine_v1.evaluate_position_loss_containment_v1()
    """
    rows = []
    for symbol, pos in snapshot.get("positions", {}).items():
        if pos.get("is_dust"):
            continue

        row = {
            "position_id": pos.get("broker_asset_id") or f"broker:{symbol}",
            "symbol": symbol,
            "asset_class": pos.get("asset_class"),
            "asset_type": pos.get("asset_class"),
            "lane_id": pos.get("lane") if pos.get("lane") != "UNAVAILABLE" else "",
            "paper_entry_horizon_style": pos.get("horizon") if pos.get("horizon") != "UNAVAILABLE" else "",
            "qty": pos.get("quantity"),
            "quantity": pos.get("quantity"),
            "avg_entry_price": pos.get("average_entry_price"),
            "entry_price": pos.get("average_entry_price"),
            "cost_basis": pos.get("cost_basis"),
            "current_price": pos.get("current_price"),
            "market_value": pos.get("market_value"),
            "unrealized_pl": pos.get("unrealized_pl"),
            "unrealized_plpc": pos.get("unrealized_pl_pct", 0) / 100.0,
            "unrealized_pl_pct": pos.get("unrealized_pl_pct"),
            "unrealized_return_pct": pos.get("unrealized_pl_pct"),
            "unrealized_pct": pos.get("unrealized_pl_pct"),
            "unrealized_pnl": pos.get("unrealized_pl"),
            "last_update_ts": pos.get("snapshot_timestamp"),
            "updated_at": pos.get("snapshot_timestamp"),
            "entry_timestamp": pos.get("position_opened_at"),
            "entry_filled_at": pos.get("position_opened_at"),
            "created_at": pos.get("position_opened_at"),
            "exchange": pos.get("exchange"),
            "data_quality": pos.get("data_quality"),
            "first_causal_blocker": pos.get("first_causal_blocker"),
        }
        rows.append(row)
    return rows


def snapshot_to_broker_position_by_symbol(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Convert canonical snapshot to broker_position_by_symbol format for Peak Memory."""
    result = {}
    for symbol, pos in snapshot.get("positions", {}).items():
        result[symbol] = {
            "symbol": symbol,
            "asset_id": pos.get("broker_asset_id"),
            "qty": pos.get("quantity"),
            "qty_available": pos.get("quantity_available"),
            "avg_entry_price": pos.get("average_entry_price"),
            "current_price": pos.get("current_price"),
            "market_value": pos.get("market_value"),
            "cost_basis": pos.get("cost_basis"),
            "unrealized_pl": pos.get("unrealized_pl"),
            "unrealized_plpc": pos.get("unrealized_pl_pct", 0) / 100.0,
            "asset_class": pos.get("asset_class"),
            "timestamp": pos.get("broker_timestamp"),
            "exchange": pos.get("exchange"),
        }
    return result


def load_snapshot(path: str) -> dict[str, Any]:
    return _load_json(path)


def save_snapshot(path: str, snapshot: dict[str, Any]) -> None:
    _atomic_write(path, snapshot)
