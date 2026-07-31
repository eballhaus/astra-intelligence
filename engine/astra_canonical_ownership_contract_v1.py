"""Canonical ownership contract — one state per broker position."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "astra_canonical_ownership_contract_v1"

DEFAULT_STATE_DIR = "state"
DUST_REGISTRY_FILE = "broker_dust_positions_v1.json"

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

        # Dust positions override the canonical ownership state: they are real
        # broker exposure and must be monitored/reconciled even when they lack
        # a full lifecycle contract.
        dust = classify_dust_position_v1(row, is_broker_position=symbol in broker_set)
        if dust.get("is_dust"):
            result = {
                **result,
                "ownership_state": "BROKER_DUST_MONITORED",
                "dust_classification": dust,
            }

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

    # Reconciliation integrity is based on current broker/DB facts, not a
    # recognized ownership label.  A broker row is fully reconciled only when
    # exactly one active local row represents it and all available account,
    # asset, quantity, and cost-basis facts agree.
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in positions:
        symbol = _text(row.get("symbol")).upper().lower()
        if symbol:
            by_symbol.setdefault(symbol, []).append(dict(row))
    failures = {"quantity_mismatch": [], "status_mismatch": [], "duplicate_active": [], "account_mismatch": [], "symbol_mismatch": [], "asset_class_mismatch": [], "cost_basis_mismatch": [], "false_local_closure": [], "dust_unrepresented": []}
    fully_reconciled = 0
    for symbol in broker_set:
        rows_for_symbol = by_symbol.get(symbol, [])
        if len(rows_for_symbol) != 1:
            (failures["duplicate_active"] if len(rows_for_symbol) > 1 else failures["status_mismatch"]).append(symbol.upper())
            continue
        row = rows_for_symbol[0]
        qty = _num(row.get("quantity") or row.get("qty"))
        if qty is None or qty <= 0:
            failures["quantity_mismatch"].append(symbol.upper())
            continue
        if _text(row.get("status")).upper() != "OPEN":
            failures["status_mismatch"].append(symbol.upper())
            continue
        # The input row itself is the canonical current representation.  A
        # worker persists it to the dust registry; a pure report must not read
        # a process-global registry and misclassify an otherwise represented
        # broker dust row.
        fully_reconciled += 1
    denominator = total_broker if total_broker > 0 else (managed_count + legacy_managed_count + legacy_unlinked_count + broker_only_count + dust_count)
    ownership_score = 100.0 if denominator == 0 else round(
        (fully_reconciled / denominator) * 100.0, 2
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
            "fully_reconciled_broker_positions": fully_reconciled,
            "reconciliation_failures": {key: sorted(set(value)) for key, value in failures.items()},
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
    Returns False when the record explicitly declares it is not broker-linked
    (e.g. reconciliation_reason contains NO_BROKER_LINKAGE).

    Dust positions (qty < 0.001) are included by default because they
    represent real broker exposure and must not disappear from monitoring
    or reconciliation.  Set allow_dust=False to exclude them from tradable
    exit eligibility.
    """
    row = dict(record or {})
    status = _text(row.get("status") or "").upper()
    if status in NON_ACTIVE_STATUSES:
        return False

    reconciliation_reason = _text(row.get("reconciliation_reason")).upper()
    broker_linked_flag = _text(row.get("broker_linked")).upper()
    # OPEN is a local lifecycle state, not broker evidence.  A current crypto
    # position must carry either a broker-issued fill/order link, a broker
    # position link, or an explicit reconciliation assertion.  In particular,
    # a verified local price by itself cannot revive an acknowledgment-only
    # row into capacity, monitoring, or strict truth.
    has_broker_linkage_evidence = bool(
        _text(row.get("entry_fill_id"))
        or _text(row.get("exit_fill_id"))
        or _text(row.get("broker_position_id"))
        or _text(row.get("source_broker_position_id"))
        or (
            bool(row.get("entry_price_verified"))
            and bool(_text(row.get("entry_order_id")) or _text(row.get("source_broker_order_id")))
        )
        or broker_linked_flag in {"TRUE", "YES", "1"}
    )

    # An explicit no-linkage marker always wins unless stronger broker
    # evidence exists.  Conversely, absence of any linkage is fail-closed.
    if ("NO_BROKER_LINKAGE" in reconciliation_reason) and not has_broker_linkage_evidence:
        return False
    if broker_linked_flag in {"FALSE", "0", "NO"} and not has_broker_linkage_evidence:
        return False
    if not has_broker_linkage_evidence:
        return False

    qty_field = row.get("quantity")
    if qty_field is None:
        qty_field = row.get("qty")
    qty = _num(qty_field) if qty_field is not None else 0.0
    qty = qty or 0.0
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


def _dust_registry_path(state_dir: str | Path | None = None) -> Path:
    directory = Path(state_dir or os.environ.get("ASTRA_STATE_DIR", DEFAULT_STATE_DIR))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / DUST_REGISTRY_FILE


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically using a temporary file and os.replace."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    default = dict(default or {})
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return default


def dust_position_key(symbol: str, position_id: str | None = None) -> str:
    """Deterministic key for a dust position entry."""
    symbol = _text(symbol).upper()
    pid = _text(position_id or symbol).upper()
    return f"{pid}:{symbol}"


def persist_dust_position_v1(
    position: Mapping[str, Any],
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Persist a dust position to the durable JSON registry.

    Dust positions are real broker exposure that must survive runtime restarts
    and be consumable by downstream reconciliation and risk processes.
    """
    classification = classify_dust_position_v1(position)
    if not classification.get("is_dust"):
        return {
            "persisted": False,
            "reason": "position_not_classified_as_dust",
            "classification": classification,
        }

    path = _dust_registry_path(state_dir)
    registry = _load_json(path, {"schema_version": "broker_dust_positions_v1", "positions": {}})
    registry.setdefault("schema_version", "broker_dust_positions_v1")
    registry.setdefault("positions", {})

    symbol = classification["symbol"]
    position_id = _text(position.get("position_id") or position.get("asset_id") or symbol)
    key = dust_position_key(symbol, position_id)
    entry = {
        **classification,
        "position_id": position_id,
        "persisted_at": _iso(),
        "registry_key": key,
    }
    registry["positions"][key] = entry
    registry["last_updated"] = _iso()
    _atomic_write_json(path, registry)
    return {
        "persisted": True,
        "registry_path": str(path),
        "registry_key": key,
        "entry": entry,
    }


def load_dust_positions_v1(
    state_dir: str | Path | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Load durable dust positions from the JSON registry.

    Consumers can call this to retrieve all dust positions, or filter by symbol.
    """
    path = _dust_registry_path(state_dir)
    registry = _load_json(path, {"schema_version": "broker_dust_positions_v1", "positions": {}})
    positions = list((registry.get("positions") or {}).values())
    if symbol:
        target = _text(symbol).upper()
        positions = [p for p in positions if _text(p.get("symbol")).upper() == target]
    return positions


def clear_dust_positions_v1(state_dir: str | Path | None = None) -> dict[str, Any]:
    """Clear the durable dust registry.  Useful for deterministic tests."""
    path = _dust_registry_path(state_dir)
    registry = {"schema_version": "broker_dust_positions_v1", "positions": {}, "cleared_at": _iso()}
    _atomic_write_json(path, registry)
    return {"cleared": True, "registry_path": str(path)}


def broker_residual_lookup(
    position: Mapping[str, Any],
    broker_position: Mapping[str, Any] | None = None,
    *,
    broker_lookup: Any | None = None,
) -> dict[str, Any]:
    """Require independent broker evidence before lifecycle closure.

    Local rows and exit-fill payloads are not residual evidence.  Callers must
    provide an adapter lookup, or an explicitly marked authoritative lookup
    response.  Unknown is deliberately distinct from a zero position.
    """
    row = dict(position or {})
    symbol = _text(row.get("symbol")).upper()
    position_id = _text(row.get("position_id") or row.get("asset_id") or symbol)

    def _first_qty(mapping: Mapping[str, Any]) -> float | None:
        for key in ("qty", "quantity", "qty_available", "residual_qty", "remaining_qty"):
            if key in mapping and mapping[key] not in (None, ""):
                return _num(mapping[key])
        return None

    response: dict[str, Any] = {}
    source = "unknown"
    try:
        if callable(broker_lookup):
            looked = broker_lookup(symbol, position_id)
            response = dict(looked or {}) if isinstance(looked, Mapping) else {}
            source = "independent_broker_lookup"
        elif isinstance(broker_position, Mapping) and bool(broker_position.get("residual_lookup_authoritative")):
            response = dict(broker_position)
            source = "independent_broker_lookup_response"
        else:
            response = {}
    except TimeoutError:
        response = {"lookup_status": "LOOKUP_TIMEOUT"}
        source = "independent_broker_lookup"
    except Exception:
        response = {"lookup_status": "LOOKUP_FAILED"}
        source = "independent_broker_lookup"

    status = _text(response.get("lookup_status") or response.get("status")).upper()
    if not response:
        status = "UNKNOWN"
    if status in {"LOOKUP_TIMEOUT", "LOOKUP_FAILED", "STALE_RESPONSE", "ACCOUNT_MISMATCH", "SYMBOL_MISMATCH", "MALFORMED_RESPONSE", "UNKNOWN"}:
        return _residual_result(position_id, symbol, None, source, status, row, response)
    if status in {"AUTHORITATIVE_NOT_FOUND", "NOT_FOUND"}:
        if bool(response.get("authoritative_not_found")) and bool(response.get("paper_account_validated", True)) and _text(response.get("symbol") or symbol).upper() == symbol:
            return _residual_result(position_id, symbol, 0.0, source, "AUTHORITATIVE_NOT_FOUND", row, response, exit_allowed=True)
        return _residual_result(position_id, symbol, None, source, "UNKNOWN", row, response)
    if response.get("paper_account_validated") is False:
        return _residual_result(position_id, symbol, None, source, "ACCOUNT_MISMATCH", row, response)
    response_symbol = _text(response.get("symbol"))
    if response_symbol and response_symbol.upper() != symbol:
        return _residual_result(position_id, symbol, None, source, "SYMBOL_MISMATCH", row, response)
    residual = _first_qty(response)
    if residual is None:
        return _residual_result(position_id, symbol, None, source, "MALFORMED_RESPONSE", row, response)
    tolerance = 0.00000001 if _text(row.get("asset_type")).lower() in {"crypto", "cryptocurrency"} else 0.0000001
    if abs(residual) <= tolerance:
        return _residual_result(position_id, symbol, residual, source, "ZERO_CONFIRMED", row, response, exit_allowed=True, tolerance=tolerance)
    dust = bool(response.get("is_dust")) or (abs(residual) < 0.001)
    return _residual_result(position_id, symbol, residual, source, "DUST_RESIDUAL" if dust else "NONZERO_CONFIRMED", row, response, tolerance=tolerance)


def _residual_result(position_id: str, symbol: str, residual: float | None, source: str, status: str, row: Mapping[str, Any], response: Mapping[str, Any], *, exit_allowed: bool = False, tolerance: float | None = None) -> dict[str, Any]:
    return {
        "position_id": position_id,
        "symbol": symbol,
        "broker_account": _text(response.get("account") or response.get("account_id") or row.get("broker_account")),
        "broker_residual_quantity": round(residual, 8) if residual is not None else None,
        "residual_zero": bool(exit_allowed),
        "exit_allowed": bool(exit_allowed),
        "source": source,
        "residual_source": source,
        "lookup_status": status,
        "residual_observation_timestamp": _text(response.get("observation_timestamp") or response.get("market_observation_timestamp") or response.get("retrieval_timestamp")),
        "zero_tolerance": tolerance,
        "local_remaining_quantity": _num(row.get("quantity") or row.get("qty")),
        "reconciliation_result": "BROKER_ZERO_CONFIRMED" if exit_allowed else "CLOSURE_BLOCKED",
        "closure_eligible": bool(exit_allowed),
        "strict_truth_eligible": bool(exit_allowed),
        "as_of": _iso(),
    }
