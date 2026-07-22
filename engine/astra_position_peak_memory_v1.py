"""Position peak-gain memory with restart-safe persistence.

Tracks the highest observed unrealized gain for every meaningful broker position
and persists it across worker cycles, CYCLE_PARTIAL, and restarts. Provides
canonical peak evidence for Profit Protection and Loss Containment without
fabricating historical data.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "astra_position_peak_memory_v1"


def _iso() -> str:
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


def _load_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _atomic_write(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
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


def _dust_excluded(market_value: float, quantity: float) -> bool:
    return market_value < 0.01 or quantity <= 0.0


def build_peak_memory(
    broker_positions: Mapping[str, Mapping[str, Any]],
    prior_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build or update peak-gain memory from broker position snapshots.

    Does not fabricate historical peaks. When a position first appears, labels
    its peak as OBSERVED_SINCE_TRACKING_START.
    """
    as_of = _iso()
    prior = dict(prior_state or {})
    prior_peaks = dict(prior.get("positions") or {})
    new_positions: dict[str, dict[str, Any]] = {}
    total_tracked = 0
    dust_skipped = 0

    for symbol, bp in (broker_positions or {}).items():
        bp = dict(bp or {})
        if not bp:
            continue

        position_id = _text(
            bp.get("asset_id") or bp.get("symbol") or symbol
        )
        symbol_name = _text(bp.get("symbol") or symbol).upper()
        quantity = abs(_num(bp.get("qty") or bp.get("qty_available"), 0.0) or 0.0)
        entry_price = _num(bp.get("avg_entry_price")) or _num(bp.get("cost_basis")) or 0.0
        current_price = (
            _num(bp.get("current_price"))
            or _num(bp.get("lastday_price"))
            or _num(bp.get("market_price"))
            or 0.0
        )
        market_value = _num(bp.get("market_value")) or (quantity * current_price if quantity > 0 else 0.0) or 0.0

        if _dust_excluded(market_value, quantity):
            dust_skipped += 1
            continue

        cost_basis = entry_price * quantity if entry_price > 0 and quantity > 0 else market_value or 0.0
        current_return_pct = (
            ((market_value - cost_basis) / cost_basis) * 100.0
            if cost_basis > 0
            else 0.0
        )
        current_return_dollars = market_value - cost_basis if cost_basis > 0 else 0.0

        prior_peak = dict(prior_peaks.get(position_id) or {})

        peak_price = _num(bp.get("current_price")) or current_price
        peak_return_pct = current_return_pct
        peak_return_dollars = current_return_dollars
        peak_timestamp = _iso()

        prior_peak_price = _num(prior_peak.get("peak_price")) or 0.0
        prior_peak_return_pct = _num(prior_peak.get("peak_return_pct")) or 0.0
        prior_peak_return_dollars = _num(prior_peak.get("peak_return_dollars")) or 0.0

        # Use the higher of current observation or prior recorded peak
        if prior_peak_price > 0 and prior_peak_price > (peak_price or 0):
            peak_price = prior_peak_price
            peak_return_pct = prior_peak_return_pct
            peak_return_dollars = prior_peak_return_dollars
            peak_timestamp = _text(prior_peak.get("peak_timestamp")) or _iso()
        elif current_return_pct > prior_peak_return_pct:
            peak_price = current_price
            peak_return_pct = current_return_pct
            peak_return_dollars = current_return_dollars
            peak_timestamp = _iso()

        giveback_pct_points = peak_return_pct - current_return_pct
        giveback_ratio = (giveback_pct_points / peak_return_pct) if peak_return_pct > 0 else None
        capture_ratio = (current_return_pct / peak_return_pct) if peak_return_pct > 0 else None

        provenance = (
            "OBSERVED_SINCE_TRACKING_START"
            if not prior_peak
            else "CONTINUOUS_TRACKING"
        )

        new_positions[position_id] = {
            "position_id": position_id,
            "symbol": symbol_name,
            "entry_price": entry_price,
            "quantity": round(quantity, 9),
            "current_price": current_price,
            "market_value": round(market_value, 4),
            "cost_basis": round(cost_basis, 4),
            "current_return_pct": round(current_return_pct, 6),
            "current_return_dollars": round(current_return_dollars, 4),
            "peak_price": round(peak_price, 6),
            "peak_return_pct": round(peak_return_pct, 6),
            "peak_return_dollars": round(peak_return_dollars, 4),
            "peak_timestamp": peak_timestamp,
            "giveback_pct_points": round(giveback_pct_points, 6) if giveback_pct_points is not None else None,
            "giveback_ratio": round(giveback_ratio, 6) if giveback_ratio is not None else None,
            "capture_ratio": round(capture_ratio, 6) if capture_ratio is not None else None,
            "peak_provenance": provenance,
            "peak_evidence_source": "broker_position_snapshot",
            "last_observed_at": as_of,
        }
        total_tracked += 1

    # Retain prior positions not in current snapshot (may have been sold)
    for pid, prior_peak in prior_peaks.items():
        if pid not in new_positions:
            prior_peak["last_observed_at"] = as_of
            new_positions[pid] = dict(prior_peak)

    # Retention: keep most recent 500 positions
    if len(new_positions) > 500:
        sorted_ids = sorted(new_positions.keys(), key=lambda pid: new_positions[pid].get("last_observed_at", ""))
        new_positions = {pid: new_positions[pid] for pid in sorted_ids[-500:]}

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": as_of,
        "positions_tracked": total_tracked,
        "dust_skipped": dust_skipped,
        "positions": new_positions,
    }


def load_peak_memory(path: str) -> dict[str, Any]:
    raw = _load_json(path)
    if not raw:
        return {
            "schema_version": SCHEMA_VERSION,
            "loaded": False,
            "positions": {},
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "loaded": True,
        "positions": dict(raw.get("positions") or {}),
    }


def save_peak_memory(path: str, state: Mapping[str, Any]) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "positions": dict(dict(state).get("positions") or {}),
        "generated_at": _iso(),
    }
    _atomic_write(path, payload)


def get_peak_for_position(state: dict[str, Any], position_id: str) -> dict[str, Any]:
    return dict(state.get("positions", {}).get(position_id) or {})
