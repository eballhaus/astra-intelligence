"""Canonical ownership contract — one state per broker position."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_canonical_ownership_contract_v1"

OWNERSHIP_STATES = frozenset({
    "MANAGED",
    "LEGACY_MANAGED",
    "LEGACY_UNLINKED",
    "BROKER_ONLY",
    "BROKER_DUST_MONITORED",
})

VALID_LANES = frozenset({"DAY", "SWING", "CRYPTO"})

# Statuses that are NOT active broker-linked positions
NON_ACTIVE_STATUSES = frozenset({
    "SIMULATED", "SHADOW", "STALE_RUNTIME_ARTIFACT", "FAILED_ENTRY",
    "CLOSED", "CLOSED_STALE_RECONCILED", "DUPLICATE_STALE",
    "HISTORICAL_SIMULATION", "HISTORICAL_CONVERSION",
})


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _has_lane(row: Mapping[str, Any]) -> bool:
    lane = _text(row.get("lane_id") or row.get("lane")).upper()
    return lane in VALID_LANES


def _has_complete_lifecycle(row: Mapping[str, Any]) -> bool:
    return bool(
        _text(row.get("candidate_id"))
        and _text(row.get("contract_id") or row.get("pretrade_decision_contract_id"))
        and _text(row.get("lifecycle_id"))
    )


def _has_broker_id(row: Mapping[str, Any]) -> bool:
    return bool(_text(
        row.get("broker_asset_id") or row.get("asset_id") or row.get("position_id") or row.get("symbol")
    ))


def classify_canonical_ownership_v1(
    position: Mapping[str, Any],
    *,
    is_broker_position: bool = True,
    has_db_record: bool = True,
) -> dict[str, Any]:
    """Classify a position into exactly one canonical ownership state."""
    row = dict(position or {})
    symbol = _text(row.get("symbol")).upper()
    position_id = _text(row.get("position_id") or row.get("asset_id") or row.get("broker_asset_id") or symbol)

    if not is_broker_position:
        return {
            "position_id": position_id,
            "symbol": symbol,
            "ownership_state": "BROKER_ONLY" if is_broker_position else "UNTRACKED",
            "has_lane": False,
            "has_lifecycle": False,
            "lane": "",
            "first_blocker": "NOT_AT_BROKER",
            "as_of": _iso(),
        }

    if not has_db_record:
        return {
            "position_id": position_id,
            "symbol": symbol,
            "ownership_state": "BROKER_ONLY",
            "has_lane": False,
            "has_lifecycle": False,
            "lane": "",
            "first_blocker": "NO_ASTRA_DB_RECORD",
            "as_of": _iso(),
        }

    has_lane = _has_lane(row)
    has_lifecycle = _has_complete_lifecycle(row)
    lane = _text(row.get("lane_id") or row.get("lane")).upper()

    classification = _text(row.get("classification") or row.get("classification_reason") or "").upper()

    if has_lane and has_lifecycle:
        state = "MANAGED"
        blocker = ""
    elif has_lane and not has_lifecycle:
        state = "LEGACY_MANAGED"
        blocker = "MISSING_LIFECYCLE_CONTRACT"
    elif not has_lane:
        state = "LEGACY_UNLINKED"
        blocker = "MISSING_CANONICAL_LANE"
    else:
        state = "LEGACY_UNLINKED"
        blocker = "CLASSIFICATION_AMBIGUOUS"

    return {
        "position_id": position_id,
        "symbol": symbol,
        "ownership_state": state,
        "has_lane": has_lane,
        "has_lifecycle": has_lifecycle,
        "lane": lane if has_lane else "UNAVAILABLE",
        "classification": classification if classification else "UNAVAILABLE",
        "first_blocker": blocker,
        "as_of": _iso(),
    }


def build_ownership_integrity_report_v1(
    positions: list[dict[str, Any]],
    broker_symbols: set[str],
    db_open_symbols: set[str],
) -> dict[str, Any]:
    """Build canonical ownership integrity report.

    Detects: duplicates, broker-only, DB-only, ownership distribution.
    """
    as_of = _iso()
    classified = []
    broker_set = set(s.lower() for s in broker_symbols)
    db_set = set(s.lower() for s in db_open_symbols)

    broker_only_symbols = sorted(broker_set - db_set)
    db_only_symbols = sorted(db_set - broker_set)

    state_counts = {s: 0 for s in OWNERSHIP_STATES}
    state_counts["UNTRACKED"] = 0

    seen_symbols: dict[str, int] = {}
    duplicate_symbols: list[str] = []
    affected_symbols: list[str] = []

    for pos in positions:
        row = dict(pos or {})
        symbol = _text(row.get("symbol")).upper().lower()
        if symbol in seen_symbols:
            seen_symbols[symbol] += 1
            duplicate_symbols.append(symbol)
        else:
            seen_symbols[symbol] = 1

    for pos in positions:
        row = dict(pos or {})
        symbol = _text(row.get("symbol")).upper().lower()
        has_db = symbol in db_set

        result = classify_canonical_ownership_v1(
            row,
            is_broker_position=symbol in broker_set,
            has_db_record=has_db,
        )
        state = result["ownership_state"]
        state_counts[state] = state_counts.get(state, 0) + 1

        if state != "MANAGED":
            affected_symbols.append(_text(row.get("symbol")).upper())

        classified.append(result)

    broker_only_symbols = sorted(set(
        s.upper() for s in (broker_set - db_set)
    ))

    total_broker = len(broker_set)
    total_db_open = len(db_set)
    managed_count = state_counts.get("MANAGED", 0)
    legacy_managed_count = state_counts.get("LEGACY_MANAGED", 0)
    legacy_unlinked_count = state_counts.get("LEGACY_UNLINKED", 0)
    broker_only_count = len(broker_only_symbols)
    db_only_count = len(db_only_symbols)
    duplicate_count = len(set(s for s in duplicate_symbols if duplicate_symbols.count(s) > 1))
    dust_count = state_counts.get("BROKER_DUST_MONITORED", 0)

    # Ownership score: positions with accurate DB representation (MANAGED or
    # LEGACY_MANAGED) divided by all broker positions requiring representation.
    # Legacy positions count as reconciled when their current broker state is
    # mirrored, even if historical lane is UNKNOWN.  Dust is in denominator.
    represented = managed_count + legacy_managed_count
    ownership_score = 100.0 if total_broker == 0 else round(
        (represented / total_broker) * 100.0, 2
    )

    first_blocker = ""
    if broker_only_count > 0:
        first_blocker = "BROKER_ONLY_POSITIONS_WITHOUT_ASTRA_RECORD"
    elif legacy_unlinked_count > 0:
        first_blocker = "LEGACY_UNLINKED_POSITIONS_MISSING_LANE_DATA"
    elif legacy_managed_count > 0:
        first_blocker = "LEGACY_MANAGED_POSITIONS_MISSING_LIFECYCLE"
    elif db_only_count > 0:
        first_blocker = "DB_ONLY_POSITIONS_NOT_AT_BROKER"
    elif duplicate_count > 0:
        first_blocker = "DUPLICATE_OWNERSHIP_DETECTED"

    return {
        "schema_version": SCHEMA_VERSION,
        "ownership_integrity": {
            "total_broker_positions": total_broker,
            "total_db_open_positions": total_db_open,
            "managed_positions": managed_count,
            "legacy_managed_positions": legacy_managed_count,
            "legacy_unlinked_positions": legacy_unlinked_count,
            "broker_only_positions_without_astra_record": broker_only_count,
            "db_only_positions_not_at_broker": db_only_count,
            "duplicate_ownership_count": duplicate_count,
            "dust_positions_monitored": dust_count,
            "ownership_score": ownership_score,
            "first_blocker": first_blocker,
            "affected_symbols": list(dict.fromkeys(affected_symbols)),
            "broker_only_symbols": broker_only_symbols,
            "db_only_symbols": db_only_symbols,
            "duplicate_symbols": list(dict.fromkeys(duplicate_symbols)),
        },
        "positions": classified,
        "as_of": as_of,
    }


def is_broker_linked_active_position(
    record: Mapping[str, Any],
    *,
    allow_dust: bool = True,
    min_qty: float | None = None,
) -> bool:
    """Canonical predicate: is this a genuine, broker-linked, actively-held position?

    Returns False for: SIMULATED, SHADOW, STALE, FAILED, CLOSED, and
    other non-active statuses.  Returns False for zero-quantity positions.

    Dust positions (qty < 0.001) are included by default because they
    represent real broker exposure and must not disappear from monitoring
    or reconciliation.  Set allow_dust=False to exclude them from tradable
    exit eligibility.
    """
    row = dict(record or {})
    status = _text(row.get("status") or "").upper()
    if status in NON_ACTIVE_STATUSES:
        return False
    qty = _num(row.get("quantity") or row.get("qty") or 0.0) or 0.0
    if min_qty is not None and abs(qty) < min_qty:
        return False
    if abs(qty) < 0.0000001:
        return False
    if not allow_dust and abs(qty) < 0.001:
        return False
    return True


def classify_dust_position_v1(
    position: Mapping[str, Any],
    is_broker_position: bool = True,
) -> dict[str, Any]:
    """Classify a dust position for durable representation."""
    row = dict(position or {})
    symbol = _text(row.get("symbol")).upper()
    qty = _num(row.get("quantity") or row.get("qty") or 0.0) or 0.0
    market_value = _num(row.get("market_value") or 0.0) or 0.0

    is_dust = 0.0 < abs(qty) < 0.001
    is_below_notional = market_value > 0 and market_value < 0.01

    if not is_dust and not is_below_notional:
        return {
            "symbol": symbol,
            "is_dust": False,
            "dust_state": "NOT_DUST",
            "qty": round(qty, 8),
            "market_value": round(market_value, 6),
        }

    reasons: list[str] = []
    if is_dust:
        reasons.append("quantity_below_tradable_minimum")
    if is_below_notional:
        reasons.append("market_value_below_notional_minimum")

    return {
        "symbol": symbol,
        "is_dust": True,
        "dust_state": "BROKER_DUST_MONITORED",
        "qty": round(qty, 8),
        "market_value": round(market_value, 6),
        "dust_reasons": reasons,
        "tradable": False,
        "eligible_for_exit": False,
        "counts_toward_exposure": True,
        "counts_toward_reconciliation": True,
        "as_of": _iso(),
    }
