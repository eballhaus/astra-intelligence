"""Off-hours completed-bar downside helper.

When the market is closed or order submission is blocked, the most recent
completed bar's downside still matters for the equity risk envelope.  This module
computes that downside from the completed bar's high/low/close (or open) and
produces a deterministic envelope value that can be included in the status
before an early return.
"""
from __future__ import annotations

from typing import Any, Mapping


SCHEMA_VERSION = "astra_off_hours_completed_bar_v1"


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        out = float(value)
        if not isinstance(out, float):
            return default
        return out
    except (TypeError, ValueError):
        return default


def compute_completed_bar_downside_v1(
    bar: Mapping[str, Any] | None,
    use_true_range: bool = False,
) -> dict[str, Any]:
    """Compute the downside risk of the most recent completed bar.

    By default the downside is `previous_close - low` as a percentage of the
    previous close.  When `use_true_range` is True, the downside is the true
    range of the bar: max(high - low, |high - previous_close|, |low - previous_close|)
    expressed as a percentage of the previous close.

    Returns a dict with:
      - downside_pct: negative percentage (or 0 if no downside)
      - downside_basis: the base price used for the percentage
      - completed_bar_low: the bar low
      - completed_bar_high: the bar high
      - completed_bar_close: the bar close
      - source: the field that supplied the close/basis
    """
    row = dict(bar or {})
    if not row:
        return {
            "schema_version": SCHEMA_VERSION,
            "downside_pct": None,
            "downside_basis": None,
            "completed_bar_low": None,
            "completed_bar_high": None,
            "completed_bar_close": None,
            "source": "no_bar",
        }

    high = _num(row.get("high") or row.get("h"))
    low = _num(row.get("low") or row.get("l"))
    close = _num(row.get("close") or row.get("c"))
    open_ = _num(row.get("open") or row.get("o"))
    previous_close = _num(row.get("previous_close"))

    basis = previous_close or close or open_
    if basis is None or basis <= 0:
        return {
            "schema_version": SCHEMA_VERSION,
            "downside_pct": None,
            "downside_basis": None,
            "completed_bar_low": low,
            "completed_bar_high": high,
            "completed_bar_close": close,
            "source": "insufficient_price",
        }

    if low is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "downside_pct": None,
            "downside_basis": basis,
            "completed_bar_low": None,
            "completed_bar_high": high,
            "completed_bar_close": close,
            "source": "previous_close" if previous_close else ("close" if close else "open"),
        }

    if use_true_range and high is not None:
        true_range = max(
            high - low,
            abs(high - basis),
            abs(low - basis),
        )
        downside_pct = -(true_range / basis) * 100.0
    else:
        downside_pct = -((basis - low) / basis) * 100.0

    return {
        "schema_version": SCHEMA_VERSION,
        "downside_pct": round(downside_pct, 6),
        "downside_basis": round(basis, 8),
        "completed_bar_low": round(low, 8),
        "completed_bar_high": round(high, 8) if high is not None else None,
        "completed_bar_close": round(close, 8) if close is not None else None,
        "source": "previous_close" if previous_close else ("close" if close else "open"),
    }


def attach_completed_bar_downside_to_status(
    status: dict[str, Any] | None,
    bar: Mapping[str, Any] | None,
    use_true_range: bool = False,
) -> dict[str, Any]:
    """Merge the completed-bar downside into a status/equity risk envelope."""
    envelope = dict(status or {})
    downside = compute_completed_bar_downside_v1(bar, use_true_range)
    envelope["completed_bar_downside"] = downside
    envelope["completed_bar_downside_included_before_early_return"] = True
    return envelope
