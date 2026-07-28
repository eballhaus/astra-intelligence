"""Idempotent dry-run migration of records into reset-scope classifications."""
from __future__ import annotations

from typing import Any, Mapping

from engine.astra_trading_reset_boundary_v1 import (
    DUST,
    LEGACY_PRE_RESET_POSITION,
    LEGACY_RETIREMENT,
    MIXED_BOUNDARY_LIFECYCLE,
    OWNERSHIP_UNKNOWN,
    POST_RESET_CURRENT,
    PRE_RESET_LEGACY,
    RESET_BOUNDARY_REVIEW_REQUIRED,
    classify_lifecycle_reset_scope_v1,
    classify_position_reset_scope_v1,
    classify_record_reset_scope_v1,
    determine_reset_boundary_v1,
    _iso,
    _text,
)


SCHEMA_VERSION = "astra_reset_boundary_migration_v1"


def _infer_record_type(record: Mapping[str, Any]) -> str:
    """Infer whether a record is a completed lifecycle or a position."""
    row = dict(record or {})
    # A completed lifecycle must have both entry and exit timestamps.
    if _text(row.get("entry_timestamp")) and _text(row.get("exit_timestamp")):
        return "lifecycle"
    # A bare lifecycle_id without position identity is treated as a lifecycle
    # fragment; anything else is a position.
    if _text(row.get("lifecycle_id")) and not _text(row.get("position_id")):
        return "lifecycle"
    return "position"


def migrate_records_to_reset_scope_v1(
    records: list[Mapping[str, Any]],
    boundary: Mapping[str, Any] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Classify records by reset scope and report dry-run totals.

    This function never rewrites broker facts, deletes records, or submits orders.
    """
    boundary = boundary or determine_reset_boundary_v1()

    totals = {
        "positions_scanned": 0,
        "legacy_positions": 0,
        "dust_positions": 0,
        "current_positions": 0,
        "unknown_positions": 0,
        "completed_lifecycles_scanned": 0,
        "pre_reset_completed_lifecycles": 0,
        "post_reset_eligible_lifecycles": 0,
        "mixed_lifecycles": 0,
        "records_excluded_from_current_learning": 0,
        "records_eligible_for_shadow_analysis": 0,
    }

    classifications: list[dict[str, Any]] = []

    for record in records:
        record_type = _infer_record_type(record)
        if record_type == "lifecycle":
            classification = classify_lifecycle_reset_scope_v1(record, boundary)
            totals["completed_lifecycles_scanned"] += 1
        else:
            classification = classify_position_reset_scope_v1(record, boundary)
            totals["positions_scanned"] += 1

        scope = classification.get("reset_scope")
        classifications.append({
            "record_type": record_type,
            "record_id": _text(
                record.get("lifecycle_id")
                or record.get("position_id")
                or record.get("asset_id")
                or record.get("symbol")
            ),
            "reset_scope": scope,
            "classification": classification,
        })

        if record_type == "position":
            if scope == LEGACY_PRE_RESET_POSITION:
                totals["legacy_positions"] += 1
            elif scope == DUST:
                totals["dust_positions"] += 1
            elif scope == POST_RESET_CURRENT:
                totals["current_positions"] += 1
            elif scope in {RESET_BOUNDARY_REVIEW_REQUIRED, OWNERSHIP_UNKNOWN}:
                totals["unknown_positions"] += 1
        else:
            if scope == PRE_RESET_LEGACY:
                totals["pre_reset_completed_lifecycles"] += 1
            elif scope == POST_RESET_CURRENT:
                totals["post_reset_eligible_lifecycles"] += 1
            elif scope == MIXED_BOUNDARY_LIFECYCLE:
                totals["mixed_lifecycles"] += 1
            elif scope == LEGACY_RETIREMENT:
                # Lifecycle that crossed the boundary is still legacy for learning.
                totals["pre_reset_completed_lifecycles"] += 1

        if scope != POST_RESET_CURRENT:
            totals["records_excluded_from_current_learning"] += 1
        if scope in {
            PRE_RESET_LEGACY,
            LEGACY_RETIREMENT,
            MIXED_BOUNDARY_LIFECYCLE,
            DUST,
            LEGACY_PRE_RESET_POSITION,
        }:
            totals["records_eligible_for_shadow_analysis"] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "migration_version": "1.0.0",
        "migration_timestamp_utc": _iso(),
        "apply": bool(apply),
        "dry_run": not bool(apply),
        "boundary": {
            "reset_id": boundary.get("reset_id"),
            "reset_timestamp_utc": boundary.get("reset_timestamp_utc"),
        },
        "totals": totals,
        "classifications": classifications,
        "note": (
            "Dry-run classification complete. No broker facts were rewritten, "
            "no records were deleted, and no orders were submitted."
        ),
    }
