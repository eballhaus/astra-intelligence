"""Canonical broker-to-Astra reconciliation — one report per cycle."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_canonical_broker_reconciliation_v1"

RECONCILIATION_RESULTS = frozenset({
    "MATCHED", "BROKER_ONLY", "ASTRA_ONLY", "QUANTITY_MISMATCH",
    "COST_MISMATCH", "LIFECYCLE_MISMATCH", "STALE_OWNERSHIP",
    "BROKER_OPEN_DB_CLOSED", "BROKER_CLOSED_DB_OPEN",
})


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def reconcile_broker_position_v1(
    symbol: str,
    broker_position: Mapping[str, Any] | None,
    db_row: Mapping[str, Any] | None,
    *,
    tolerance_pct: float = 0.01,
) -> dict[str, Any]:
    """Reconcile one position between broker and Astra DB."""
    broker = dict(broker_position or {})
    db = dict(db_row or {})

    broker_exists = bool(broker)
    db_exists = bool(db)

    if broker_exists and not db_exists:
        return {
            "symbol": symbol,
            "reconciliation_result": "BROKER_ONLY",
            "broker_qty": _num(broker.get("qty"), 0.0),
            "broker_avg_entry": _num(broker.get("avg_entry_price"), 0.0),
            "db_qty": 0.0,
            "db_avg_entry": 0.0,
            "quantity_match": False,
            "cost_match": False,
            "blocker": "NO_ASTRA_RECORD",
        }

    if not broker_exists and db_exists:
        status = _text(db.get("status")).upper()
        if status == "CLOSED":
            return {
                "symbol": symbol,
                "reconciliation_result": "BROKER_CLOSED_DB_OPEN",
                "broker_qty": 0.0,
                "broker_avg_entry": 0.0,
                "db_qty": _num(db.get("qty"), 0.0),
                "db_avg_entry": _num(db.get("entry_price"), 0.0),
                "quantity_match": False,
                "cost_match": False,
                "blocker": "DB_OPEN_BROKER_CLOSED",
            }
        return {
            "symbol": symbol,
            "reconciliation_result": "ASTRA_ONLY",
            "broker_qty": 0.0,
            "broker_avg_entry": 0.0,
            "db_qty": _num(db.get("qty"), 0.0),
            "db_avg_entry": _num(db.get("entry_price"), 0.0),
            "quantity_match": False,
            "cost_match": False,
            "blocker": "NOT_AT_BROKER",
        }

    if not broker_exists and not db_exists:
        return {
            "symbol": symbol,
            "reconciliation_result": "NOT_FOUND",
            "broker_qty": 0.0,
            "broker_avg_entry": 0.0,
            "db_qty": 0.0,
            "db_avg_entry": 0.0,
            "quantity_match": True,
            "cost_match": True,
            "blocker": "",
        }

    broker_qty = abs(_num(broker.get("qty"), 0.0))
    broker_avg = _num(broker.get("avg_entry_price"), 0.0)
    broker_lifecycle = _text(broker.get("lifecycle_id"))

    db_qty = abs(_num(db.get("qty") or db.get("quantity"), 0.0))
    db_avg = _num(db.get("entry_price") or db.get("avg_entry_price"), 0.0)
    db_lifecycle = _text(db.get("lifecycle_id"))
    db_status = _text(db.get("status")).upper()

    qty_match = abs(broker_qty - db_qty) < 0.001
    cost_match = broker_avg > 0 and db_avg > 0 and abs(broker_avg - db_avg) / broker_avg < tolerance_pct
    lifecycle_match = broker_lifecycle == db_lifecycle if broker_lifecycle else True

    blockers: list[str] = []

    if db_status == "CLOSED":
        result = "BROKER_OPEN_DB_CLOSED"
        blockers.append("DB_STATUS_CLOSED")
    elif not qty_match:
        result = "QUANTITY_MISMATCH"
        blockers.append(f"QTY_DIFF:{broker_qty}v{db_qty}")
    elif not cost_match:
        result = "COST_MISMATCH"
        blockers.append(f"COST_DIFF:{round(broker_avg, 4)}v{round(db_avg, 4)}")
    elif not lifecycle_match:
        result = "LIFECYCLE_MISMATCH"
        blockers.append(f"LIFECYCLE_DIFF:{broker_lifecycle}v{db_lifecycle}")
    else:
        result = "MATCHED"

    return {
        "symbol": symbol,
        "reconciliation_result": result,
        "broker_qty": broker_qty,
        "broker_avg_entry": broker_avg,
        "db_qty": db_qty,
        "db_avg_entry": db_avg,
        "quantity_match": qty_match,
        "cost_match": cost_match,
        "lifecycle_match": lifecycle_match,
        "blocker": "; ".join(blockers),
    }


def build_broker_reconciliation_report_v1(
    broker_positions: Mapping[str, Mapping[str, Any]],
    db_open_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a canonical broker-to-Astra reconciliation report."""
    as_of = _iso()

    broker_by_symbol: dict[str, dict[str, Any]] = {}
    for sym, bp in (broker_positions or {}).items():
        if isinstance(bp, dict):
            broker_by_symbol[_text(sym).upper()] = dict(bp)

    db_by_symbol: dict[str, dict[str, Any]] = {}
    for row in (db_open_rows or []):
        if isinstance(row, dict):
            sym = _text(row.get("symbol")).upper()
            if sym:
                db_by_symbol[sym] = dict(row)

    all_symbols = set(broker_by_symbol.keys()) | set(db_by_symbol.keys())

    results: list[dict[str, Any]] = []
    result_counts: dict[str, int] = {}
    mismatch_count = 0

    for symbol in sorted(all_symbols):
        reconciliation = reconcile_broker_position_v1(
            symbol,
            broker_by_symbol.get(symbol),
            db_by_symbol.get(symbol),
        )
        results.append(reconciliation)
        r = reconciliation["reconciliation_result"]
        result_counts[r] = result_counts.get(r, 0) + 1
        if r != "MATCHED":
            mismatch_count += 1

    total = len(all_symbols)
    matched = result_counts.get("MATCHED", 0)

    return {
        "schema_version": SCHEMA_VERSION,
        "reconciliation_summary": {
            "total_symbols_reconciled": total,
            "matched": matched,
            "mismatched": mismatch_count,
            "result_counts": result_counts,
            "reconciliation_health": "HEALTHY" if matched == total else "MISMATCHES_DETECTED",
            "first_blocker": next(
                (r["symbol"] + ":" + r["blocker"] for r in results if r["reconciliation_result"] != "MATCHED"),
                "",
            ),
        },
        "results": results,
        "as_of": as_of,
    }
