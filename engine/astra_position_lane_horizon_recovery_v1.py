"""Canonical, fail-closed lane and horizon recovery for current broker positions.

Broker positions remain authoritative for membership and financial facts.  This
module only attaches Astra-owned metadata when an entry-linked record proves
the ownership.  It deliberately never derives a lane from price, age, or a
symbol alone without a unique current reconciliation record.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "astra_position_lane_horizon_recovery_v1"
LANES = frozenset({"DAY", "SCALP", "SWING", "CRYPTO"})
STATUS_RESOLVED = "RESOLVED"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_CONFLICT = "CONFLICT"
STATUS_AMBIGUOUS = "AMBIGUOUS"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbol(value: Any) -> str:
    return _text(value).upper()


def _symbol_aliases(value: Any, asset: Any) -> set[str]:
    """Match only the documented compact/internal representation of crypto pairs."""
    symbol = _symbol(value)
    if _asset(asset) != "crypto":
        return {symbol} if symbol else set()
    compact = symbol.replace("/", "").replace("-", "").replace("_", "")
    if compact.endswith("USD") and len(compact) > 3:
        return {symbol, compact, f"{compact[:-3]}/USD"}
    return {symbol} if symbol else set()


def _asset(value: Any) -> str:
    raw = _text(value).lower()
    if raw in {"stock", "equity", "us_equity", "us equity"}:
        return "equity"
    if raw in {"crypto", "cryptocurrency"}:
        return "crypto"
    if raw in {"etf"}:
        return "etf"
    return raw


def _lane(value: Any) -> str:
    candidate = _text(value).upper()
    return candidate if candidate in LANES else ""


def _horizon(value: Any) -> str:
    candidate = _text(value)
    return "" if candidate.upper() in {"", "UNKNOWN", "UNAVAILABLE", "NONE", "N/A"} else candidate


def _contract_value(key: str, *sources: Mapping[str, Any]) -> Any:
    """Return only an explicitly persisted contract value, never a default."""
    for source in sources:
        if key in source and source.get(key) not in (None, ""):
            return source.get(key)
    return None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None


def _timestamp(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw or raw.upper() in {"UNKNOWN", "UNAVAILABLE"}:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def _timestamps_consistent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_time = _timestamp(left.get("entry_filled_at") or left.get("entry_timestamp") or left.get("created_at"))
    right_time = _timestamp(right.get("entry_filled_at") or right.get("entry_timestamp") or right.get("created_at"))
    if left_time is None or right_time is None:
        return False
    return abs((left_time - right_time).total_seconds()) <= 300.0


def _identifiers(row: Mapping[str, Any]) -> set[str]:
    keys = (
        "entry_order_id", "source_broker_order_id", "broker_order_id", "order_id",
        "source_client_order_id", "client_order_id", "entry_fill_id", "fill_id",
        "lifecycle_id", "source_lifecycle_id", "position_id", "candidate_id", "source_candidate_id",
    )
    return {_text(row.get(key)) for key in keys if _text(row.get(key))}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _source_claim(
    row: Mapping[str, Any],
    *,
    source_type: str,
    source_id: str,
    source_timestamp: str,
    match_method: str,
) -> dict[str, Any]:
    metadata = row.get("entry_metadata_json") or row.get("entry_lane_horizon_contract_v1") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    row_metadata = row.get("row_json") or {}
    if isinstance(row_metadata, str):
        try:
            row_metadata = json.loads(row_metadata)
        except (TypeError, ValueError):
            row_metadata = {}
    row_metadata = dict(row_metadata) if isinstance(row_metadata, Mapping) else {}
    expected_max_hold = _text(_contract_value("expected_max_hold", metadata, row, row_metadata))
    same_session_exit_required = _bool_or_none(
        _contract_value("same_session_exit_required", metadata, row, row_metadata)
    )
    overnight_allowed = _bool_or_none(
        _contract_value("overnight_allowed", metadata, row, row_metadata)
    )
    return {
        "source_type": source_type,
        "source_id": source_id,
        "source_timestamp": source_timestamp,
        "match_method": match_method,
        "lane": _lane(metadata.get("lane") or metadata.get("lane_id") or row.get("lane_id") or row.get("original_lane") or row.get("lane")),
        "horizon": _horizon(
            metadata.get("horizon") or metadata.get("intended_horizon") or row.get("canonical_horizon")
            or row.get("paper_entry_horizon_style")
            or row.get("original_horizon")
            or row.get("intended_horizon")
        ),
        "expected_max_hold": expected_max_hold,
        "same_session_exit_required": same_session_exit_required,
        "overnight_allowed": overnight_allowed,
        # These fields are Astra-owned identity/ownership metadata.  They are
        # populated only from a matched lifecycle record, never from the
        # broker's asset identifier or a same-symbol fallback.
        "canonical_position_id": _text(row.get("position_id")),
        "canonical_lifecycle_id": _text(
            row.get("lifecycle_id") or row.get("source_lifecycle_id") or row.get("position_id")
        ),
        "candidate_id": _text(
            row.get("candidate_id") or row.get("source_candidate_id") or row_metadata.get("candidate_id")
        ),
        "entry_fill_id": _text(row.get("entry_fill_id") or row.get("fill_id")),
        "entry_order_id": _text(row.get("entry_order_id") or row.get("source_broker_order_id")),
        "position_owner": _text(row.get("position_owner")),
        "management_owner": _text(row.get("management_owner") or row.get("position_owner")),
        "exit_owner": _text(row.get("exit_policy_owner") or row.get("exit_owner")),
    }


def _select_fact(claims: list[dict[str, Any]], field: str, unavailable_blocker: str) -> dict[str, Any]:
    values = {str(claim[field]) for claim in claims if claim.get(field)}
    conflict_blocker = "CANONICAL_LANE_CONFLICT" if field == "lane" else "CANONICAL_HORIZON_CONFLICT"
    if len(values) > 1:
        return {
            "value": "UNAVAILABLE", "status": STATUS_CONFLICT, "source": "UNAVAILABLE",
            "source_id": "", "source_timestamp": "", "claims": claims,
            "blockers": [conflict_blocker],
        }
    if not values:
        return {
            "value": "UNAVAILABLE", "status": STATUS_UNAVAILABLE, "source": "UNAVAILABLE",
            "source_id": "", "source_timestamp": "", "claims": [],
            "blockers": [unavailable_blocker],
        }
    value = next(iter(values))
    ranked = sorted(
        (claim for claim in claims if claim.get(field) == value),
        key=lambda claim: {
            "EXECUTED_ENTRY_FILL": 0,
            "ACTIVE_POSITION_LIFECYCLE": 1,
            "ORDER_LINKED_ASSIGNMENT": 2,
            "CURRENT_RECONCILIATION_RECORD": 3,
        }.get(str(claim.get("source_type")), 9),
    )
    selected = ranked[0]
    return {
        "value": value, "status": STATUS_RESOLVED, "source": selected["source_type"],
        "source_id": selected["source_id"], "source_timestamp": selected["source_timestamp"],
        "claims": ranked, "blockers": [],
    }


def _claims_for_position(
    broker: Mapping[str, Any],
    evidence_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Return only exact or uniquely current, timestamp-consistent evidence."""
    asset = _asset(broker.get("asset_class") or broker.get("asset_type"))
    broker_symbols = _symbol_aliases(broker.get("symbol"), asset)
    broker_ids = _identifiers(broker)
    matching: list[tuple[Mapping[str, Any], str]] = []
    saw_symbol = False
    for evidence in evidence_rows:
        evidence_asset = _asset(evidence.get("asset_class") or evidence.get("asset_type"))
        if asset and evidence_asset and asset != evidence_asset:
            continue
        if not broker_symbols.intersection(_symbol_aliases(evidence.get("symbol"), evidence_asset or asset)):
            continue
        saw_symbol = True
        evidence_ids = _identifiers(evidence)
        if broker_ids and evidence_ids and broker_ids.intersection(evidence_ids):
            matching.append((evidence, "EXACT_ID_LINK"))
        elif bool(evidence.get("current_reconciled")) and _timestamps_consistent(broker, evidence):
            matching.append((evidence, "CURRENT_RECONCILED_SYMBOL_TIMESTAMP"))
    # Symbol fallback is permitted only for exactly one current reconciled row
    # with an entry timestamp.  Historical rows never reach this branch.
    fallback = [pair for pair in matching if pair[1] == "CURRENT_RECONCILED_SYMBOL_TIMESTAMP"]
    exact = [pair for pair in matching if pair[1] == "EXACT_ID_LINK"]
    if exact:
        return exact, saw_symbol
    if len(fallback) == 1:
        return fallback, saw_symbol
    if len(fallback) > 1:
        return [], True
    return [], saw_symbol


def build_position_lane_horizon_recovery_v1(
    broker_positions: Mapping[str, Mapping[str, Any]],
    *,
    evidence_rows: Iterable[Mapping[str, Any]],
    snapshot_generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a bounded ledger for currently open broker positions only.

    Precedence is documented by source type: exact fill/order/lifecycle links
    win; a current reconciliation row may be used only as a unique, timestamp
    consistent fallback.  Conflicting canonical claims are never selected.
    """
    evidence = [dict(row) for row in evidence_rows if isinstance(row, Mapping)][:500]
    positions: list[dict[str, Any]] = []
    for key, raw_broker in list(broker_positions.items())[:200]:
        broker = dict(raw_broker or {})
        broker.setdefault("symbol", key)
        symbol = _symbol(broker.get("symbol"))
        if not symbol:
            continue
        matches, saw_symbol = _claims_for_position(broker, evidence)
        claims: list[dict[str, Any]] = []
        for row, method in matches:
            source_type = _text(row.get("recovery_source_type")) or (
                "CURRENT_RECONCILIATION_RECORD" if method.startswith("CURRENT_") else "ACTIVE_POSITION_LIFECYCLE"
            )
            if _text(row.get("entry_metadata_generation")) == "V1_MANDATORY":
                source_type = "ORDER_LINKED_ASSIGNMENT"
                method = "ORDER_LINKED"
            claims.append(_source_claim(
                row,
                source_type=source_type,
                source_id=_text(row.get("position_id") or row.get("entry_fill_id") or row.get("entry_order_id") or symbol),
                source_timestamp=_text(row.get("entry_filled_at") or row.get("entry_timestamp") or row.get("updated_at") or row.get("as_of")),
                match_method=method,
            ))
        lane = _select_fact(claims, "lane", "CANONICAL_LANE_EVIDENCE_UNAVAILABLE")
        horizon = _select_fact(claims, "horizon", "CANONICAL_HORIZON_EVIDENCE_UNAVAILABLE")
        exact_identity_claims = [
            claim for claim in claims
            if claim.get("match_method") in {"EXACT_ID_LINK", "ORDER_LINKED"}
            and _text(claim.get("canonical_position_id"))
        ]
        identity_ids = {_text(claim.get("canonical_position_id")) for claim in exact_identity_claims}
        identity_status = STATUS_UNAVAILABLE
        identity_claim: dict[str, Any] = {}
        if len(identity_ids) == 1:
            identity_status = STATUS_RESOLVED
            identity_claim = next(claim for claim in exact_identity_claims if _text(claim.get("canonical_position_id")))
        elif len(identity_ids) > 1:
            identity_status = STATUS_AMBIGUOUS
        identity_ambiguous = saw_symbol and not matches and any(
            _symbol(row.get("symbol")) == symbol and bool(row.get("current_reconciled")) for row in evidence
        )
        blockers = list(dict.fromkeys([*lane["blockers"], *horizon["blockers"]]))
        if identity_ambiguous:
            blockers.append("AMBIGUOUS_SYMBOL_ONLY_MATCH")
            if lane["status"] == STATUS_UNAVAILABLE:
                lane["status"] = STATUS_AMBIGUOUS
            if horizon["status"] == STATUS_UNAVAILABLE:
                horizon["status"] = STATUS_AMBIGUOUS
        method = next((claim.get("match_method") for claim in claims if claim.get("match_method")), "NONE")
        contract_claim = identity_claim if identity_status == STATUS_RESOLVED else {}
        contract_complete = (
            lane["status"] == STATUS_RESOLVED
            and horizon["status"] == STATUS_RESOLVED
            and _text(contract_claim.get("expected_max_hold"))
            and contract_claim.get("same_session_exit_required") is not None
            and contract_claim.get("overnight_allowed") is not None
        )
        positions.append({
            "symbol": symbol,
            "asset_class": _asset(broker.get("asset_class") or broker.get("asset_type")) or "UNAVAILABLE",
            "lane": lane["value"], "lane_status": lane["status"], "lane_source": lane["source"],
            "lane_source_id": lane["source_id"], "lane_source_timestamp": lane["source_timestamp"],
            "horizon": horizon["value"], "horizon_status": horizon["status"], "horizon_source": horizon["source"],
            "horizon_source_id": horizon["source_id"], "horizon_source_timestamp": horizon["source_timestamp"],
            "canonical_position_id": identity_claim.get("canonical_position_id") if identity_status == STATUS_RESOLVED else "",
            "canonical_lifecycle_id": identity_claim.get("canonical_lifecycle_id") if identity_status == STATUS_RESOLVED else "",
            "candidate_id": identity_claim.get("candidate_id") if identity_status == STATUS_RESOLVED else "",
            "entry_fill_id": identity_claim.get("entry_fill_id") if identity_status == STATUS_RESOLVED else "",
            "entry_order_id": identity_claim.get("entry_order_id") if identity_status == STATUS_RESOLVED else "",
            "position_owner": identity_claim.get("position_owner") if identity_status == STATUS_RESOLVED else "",
            "management_owner": identity_claim.get("management_owner") if identity_status == STATUS_RESOLVED else "",
            "exit_owner": identity_claim.get("exit_owner") if identity_status == STATUS_RESOLVED else "",
            "canonical_identity_status": identity_status,
            "expected_max_hold": contract_claim.get("expected_max_hold") if contract_complete else None,
            "same_session_exit_required": contract_claim.get("same_session_exit_required") if contract_complete else None,
            "overnight_allowed": contract_claim.get("overnight_allowed") if contract_complete else None,
            "horizon_contract_status": STATUS_RESOLVED if contract_complete else STATUS_UNAVAILABLE,
            "recovery_method": method, "confidence": "CANONICAL" if claims and not blockers else "NONE",
            "conflicts": [claim for claim in claims if claim.get("lane") or claim.get("horizon")] if any("CONFLICT" in blocker for blocker in blockers) else [],
            "exact_blockers": blockers,
            "first_causal_blocker": blockers[0] if blockers else None,
        })
    source_distribution: dict[str, int] = {}
    method_distribution: dict[str, int] = {}
    for row in positions:
        for source in (row["lane_source"], row["horizon_source"]):
            source_distribution[source] = source_distribution.get(source, 0) + 1
        method = str(row["recovery_method"])
        method_distribution[method] = method_distribution.get(method, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "broker_snapshot_generated_at": snapshot_generated_at or _now(),
        "position_count": len(positions),
        "resolved_lane_count": sum(row["lane_status"] == STATUS_RESOLVED for row in positions),
        "unresolved_lane_count": sum(row["lane_status"] == STATUS_UNAVAILABLE for row in positions),
        "lane_conflict_count": sum(row["lane_status"] == STATUS_CONFLICT for row in positions),
        "lane_ambiguous_count": sum(row["lane_status"] == STATUS_AMBIGUOUS for row in positions),
        "resolved_horizon_count": sum(row["horizon_status"] == STATUS_RESOLVED for row in positions),
        "unresolved_horizon_count": sum(row["horizon_status"] == STATUS_UNAVAILABLE for row in positions),
        "horizon_conflict_count": sum(row["horizon_status"] == STATUS_CONFLICT for row in positions),
        "horizon_ambiguous_count": sum(row["horizon_status"] == STATUS_AMBIGUOUS for row in positions),
        "conflict_count": sum(bool(row["conflicts"]) for row in positions),
        "source_distribution": source_distribution,
        "recovery_method_distribution": method_distribution,
        "precedence": ["EXECUTED_ENTRY_FILL", "ACTIVE_POSITION_LIFECYCLE", "ORDER_LINKED_ASSIGNMENT", "CURRENT_RECONCILIATION_RECORD"],
        "positions": positions,
        "paper_only_preserved": True,
        "behavior_safe_to_apply": False,
    }


def enrich_canonical_position_snapshot_v1(snapshot: Mapping[str, Any], recovery: Mapping[str, Any]) -> dict[str, Any]:
    """Attach only metadata; broker membership, price, quantity, and basis stay untouched.

    Lane/horizon from the recovery ledger is authoritative when RESOLVED.
    When recovery returns UNAVAILABLE, the original canonical-snapshot lane
    (which may be broker-provided) is preserved as a reasonable default,
    but the recovery status clearly flags it as unverified.
    """
    result = dict(snapshot or {})
    recovered = {str(row.get("symbol") or "").upper(): dict(row) for row in (recovery.get("positions") or []) if isinstance(row, dict)}
    positions: dict[str, dict[str, Any]] = {}
    for symbol, raw in dict(snapshot.get("positions") or {}).items():
        position = dict(raw or {})
        row = recovered.get(str(symbol).upper())
        if row:
            lane_status = _text(row.get("lane_status")).upper()
            horizon_status = _text(row.get("horizon_status")).upper()
            if lane_status == STATUS_RESOLVED:
                position["lane"] = row["lane"]
                position["lane_source"] = row["lane_source"]
            if horizon_status == STATUS_RESOLVED:
                position["horizon"] = row["horizon"]
                position["horizon_source"] = row["horizon_source"]
            identity_status = _text(row.get("canonical_identity_status")).upper()
            if identity_status == STATUS_RESOLVED:
                # Keep the Alpaca asset ID separate.  The canonical Astra ID
                # is the only identity used by risk and ownership consumers.
                position.update({
                    "canonical_position_id": row.get("canonical_position_id"),
                    "position_id": row.get("canonical_position_id"),
                    "lifecycle_id": row.get("canonical_lifecycle_id"),
                    "candidate_id": row.get("candidate_id"),
                    "entry_fill_id": row.get("entry_fill_id"),
                    "entry_order_id": row.get("entry_order_id"),
                    "position_owner": row.get("position_owner"),
                    "management_owner": row.get("management_owner"),
                    "exit_policy_owner": row.get("exit_owner"),
                    "expected_max_hold": row.get("expected_max_hold"),
                    "same_session_exit_required": row.get("same_session_exit_required"),
                    "overnight_allowed": row.get("overnight_allowed"),
                })
            # Recovery metadata is always attached so consumers can distinguish
            # RESOLVED (verified) from UNAVAILABLE (defaulted) lanes.
            position.update({
                "lane_evidence_at": row.get("lane_source_timestamp") or "UNAVAILABLE",
                "horizon_evidence_at": row.get("horizon_source_timestamp") or "UNAVAILABLE",
                "lane_recovery_status": lane_status or "UNAVAILABLE",
                "horizon_recovery_status": horizon_status or "UNAVAILABLE",
                "lane_recovery_source_id": row.get("lane_source_id") or "",
                "horizon_recovery_source_id": row.get("horizon_source_id") or "",
                "recovery_method": row.get("recovery_method") or "NONE",
                "recovery_confidence": row.get("confidence") or 0.0,
                "recovery_exact_blockers": list(row.get("exact_blockers") or []),
                "canonical_identity_status": identity_status or STATUS_UNAVAILABLE,
            })
        positions[symbol] = position
    result["positions"] = positions
    result["position_lane_horizon_recovery"] = dict(recovery)
    return result


class AstraPositionLaneHorizonRecoveryV1:
    """Worker-owned bounded ledger.  GET consumers only call ``snapshot``."""

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.path = Path(state_dir) / "astra_position_lane_horizon_recovery_v1.json"

    def persist(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload or {})
        _atomic_write(self.path, result)
        return result

    def snapshot(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(payload) if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}
