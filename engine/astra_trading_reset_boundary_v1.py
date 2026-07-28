"""Astra trading reset boundary and legacy evidence separation contract.

This module owns the single shared classification boundary between pre-reset
legacy evidence and post-reset current trading truth.  It is side-effect free
apart from optional state persistence helpers; it never submits broker orders,
changes central execution, or deletes records.
"""
from __future__ import annotations

import json
import os
import tempfile
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.astra_canonical_ownership_contract_v1 import (
    classify_canonical_ownership_v1,
    classify_dust_position_v1,
)


SCHEMA_VERSION = "astra_trading_reset_boundary_v1"
RESET_BOUNDARY_STATE_FILE = "astra_trading_reset_boundary_v1.json"

DEFAULT_RESET_ID = "ASTRA_CORRECTED_TRADING_RESET_2026_07_28"
DEFAULT_RESET_DATE = "2026-07-28"
DEFAULT_RESET_TIMESTAMP_UTC = "2026-07-28T17:20:15Z"
DEFAULT_RESET_SOURCE_COMMIT = "ada1c8d201adc1137a2316d5e57ede174d41d253"
DEFAULT_RESET_TIMESTAMP_SOURCE = "git_commit_timestamp_of_earliest_corrected_trading_commit"

# Reset scope classifications
PRE_RESET_LEGACY = "PRE_RESET_LEGACY"
LEGACY_PRE_RESET_POSITION = "LEGACY_PRE_RESET_POSITION"
LEGACY_RETIREMENT = "LEGACY_RETIREMENT"
POST_RESET_CURRENT = "POST_RESET_CURRENT"
MIXED_BOUNDARY_LIFECYCLE = "MIXED_BOUNDARY_LIFECYCLE"
DUST = "DUST"
OWNERSHIP_UNKNOWN = "OWNERSHIP_UNKNOWN"
RESET_BOUNDARY_REVIEW_REQUIRED = "RESET_BOUNDARY_REVIEW_REQUIRED"

VALID_POST_RESET_LANES = frozenset({"DAY", "SWING", "CRYPTO"})


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "on"}


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp to a timezone-aware UTC datetime."""
    raw = _text(value)
    if not raw:
        return None
    # Reject date-only strings: same-day records without a precise time are
    # ambiguous and must fail closed to review.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    return None


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _record_timestamp(record: Mapping[str, Any]) -> datetime | None:
    """Return the best available timestamp for a generic record."""
    row = dict(record or {})
    for key in (
        "entry_timestamp",
        "entry_filled_at",
        "opened_at",
        "created_at",
        "timestamp",
        "generated_at",
        "updated_at",
        "exit_timestamp",
        "closed_at",
        "broker_fill_timestamp",
    ):
        value = row.get(key)
        if value not in (None, ""):
            parsed = _parse_iso(value)
            if parsed is not None:
                return parsed
    return None


def _entry_timestamp(lifecycle: Mapping[str, Any]) -> datetime | None:
    row = dict(lifecycle or {})
    for key in ("entry_timestamp", "entry_filled_at", "opened_at", "created_at", "timestamp"):
        value = row.get(key)
        if value not in (None, ""):
            parsed = _parse_iso(value)
            if parsed is not None:
                return parsed
    return None


def _exit_timestamp(lifecycle: Mapping[str, Any]) -> datetime | None:
    row = dict(lifecycle or {})
    for key in ("exit_timestamp", "exit_filled_at", "closed_at", "updated_at"):
        value = row.get(key)
        if value not in (None, ""):
            parsed = _parse_iso(value)
            if parsed is not None:
                return parsed
    return None


def _boundary_datetime(boundary: Mapping[str, Any] | None = None) -> datetime:
    boundary = boundary or determine_reset_boundary_v1()
    dt = _parse_iso(boundary.get("reset_timestamp_utc"))
    if dt is None:
        dt = _parse_iso(DEFAULT_RESET_TIMESTAMP_UTC)
    return dt or datetime(2026, 7, 28, 17, 20, 15, tzinfo=timezone.utc)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
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


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


def determine_reset_boundary_v1(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the canonical reset boundary object."""
    cfg = dict(config or {})

    reset_timestamp_utc = _text(
        os.environ.get("ASTRA_RESET_TIMESTAMP_UTC")
        or cfg.get("reset_timestamp_utc")
        or DEFAULT_RESET_TIMESTAMP_UTC
    )
    source_commit = _text(
        os.environ.get("ASTRA_RESET_SOURCE_COMMIT")
        or cfg.get("source_commit")
        or cfg.get("production_commit")
        or DEFAULT_RESET_SOURCE_COMMIT
    )
    timestamp_source = _text(
        cfg.get("timestamp_source") or DEFAULT_RESET_TIMESTAMP_SOURCE
    )
    reset_id = _text(cfg.get("reset_id") or DEFAULT_RESET_ID)
    reset_date = _text(cfg.get("reset_date") or DEFAULT_RESET_DATE)
    reason = _text(
        cfg.get("reason")
        or "Astra corrected trading baseline established from earliest corrected trading commit timestamp."
    )
    status = _text(cfg.get("status") or "ACTIVE")
    human_declared = bool(
        cfg.get("human_declared") if "human_declared" in cfg else True
    )
    machine_ts = _parse_iso(reset_timestamp_utc)
    machine_derived = _iso(machine_ts) if machine_ts else reset_timestamp_utc

    return {
        "schema_version": SCHEMA_VERSION,
        "reset_id": reset_id,
        "reset_date": reset_date,
        "reset_timestamp_utc": reset_timestamp_utc,
        "timestamp_source": timestamp_source,
        "production_commit": source_commit,
        "reason": reason,
        "status": status,
        "human_declared": human_declared,
        "machine_derived_activation_timestamp_utc": machine_derived,
        "generated_at": _iso(),
    }


def load_reset_boundary_v1(state_dir: str | Path) -> dict[str, Any]:
    """Load a previously persisted reset boundary."""
    path = Path(state_dir) / RESET_BOUNDARY_STATE_FILE
    payload = _load_json(path, {})
    if not payload:
        return determine_reset_boundary_v1()
    # Validate essential fields; fall back to defaults if corrupted.
    if not payload.get("reset_id") or not payload.get("reset_timestamp_utc"):
        return determine_reset_boundary_v1()
    return payload


def save_reset_boundary_v1(boundary: dict[str, Any], state_dir: str | Path) -> dict[str, Any]:
    """Persist the reset boundary atomically for restart-safe reload."""
    path = Path(state_dir) / RESET_BOUNDARY_STATE_FILE
    payload = {
        **dict(boundary),
        "schema_version": SCHEMA_VERSION,
        "saved_at": _iso(),
    }
    _atomic_write_json(path, payload)
    return {"saved": True, "path": str(path), "boundary": payload}


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _lane(row: Mapping[str, Any]) -> str:
    return _text(row.get("lane_id") or row.get("lane")).upper()


def _horizon(row: Mapping[str, Any]) -> str:
    return _text(
        row.get("trade_horizon_style")
        or row.get("horizon")
        or row.get("trade_horizon")
        or row.get("best_horizon_style")
    ).lower()


def _is_lane_known(row: Mapping[str, Any]) -> bool:
    return _lane(row) in VALID_POST_RESET_LANES


def _is_horizon_known(row: Mapping[str, Any]) -> bool:
    return _horizon(row) in {"scalp", "day_trade", "swing_trade"}


def _is_current_astra_owned(row: Mapping[str, Any]) -> bool:
    ownership = classify_canonical_ownership_v1(
        row, is_broker_position=True, has_db_record=True
    )
    return ownership.get("ownership_state") == "MANAGED" and ownership.get("has_lane") is True


def _dust_info(record: Mapping[str, Any]) -> dict[str, Any]:
    return classify_dust_position_v1(record)


# ---------------------------------------------------------------------------
# Classifications
# ---------------------------------------------------------------------------


def classify_record_reset_scope_v1(
    record: Mapping[str, Any], boundary: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Classify a generic record relative to the reset boundary."""
    boundary = boundary or determine_reset_boundary_v1()
    boundary_dt = _boundary_datetime(boundary)
    ts = _record_timestamp(record)
    dust = _dust_info(record)
    is_dust = bool(dust.get("is_dust"))

    if ts is None:
        scope = RESET_BOUNDARY_REVIEW_REQUIRED
        reason = "missing_or_invalid_record_timestamp"
        origin = "unknown"
    elif ts < boundary_dt:
        scope = PRE_RESET_LEGACY
        reason = "pre_reset_timestamp_before_boundary"
        origin = "pre"
    else:
        scope = POST_RESET_CURRENT
        reason = "post_reset_timestamp_on_or_after_boundary"
        origin = "post"

    if is_dust:
        scope = DUST
        reason = "dust_position_irrespective_of_reset_origin"

    return {
        "reset_scope": scope,
        "reset_reason": reason,
        "record_timestamp_utc": _iso(ts) if ts else None,
        "boundary_timestamp_utc": _iso(boundary_dt),
        "dust": is_dust,
        "dust_classification": dust,
        "is_post_reset_candidate": scope == POST_RESET_CURRENT,
        "reset_origin": origin,
        "reset_id": boundary.get("reset_id"),
    }


def classify_position_reset_scope_v1(
    position: Mapping[str, Any], boundary: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Classify an open position relative to the reset boundary."""
    boundary = boundary or determine_reset_boundary_v1()
    boundary_dt = _boundary_datetime(boundary)
    ts = _record_timestamp(position)
    dust = _dust_info(position)
    is_dust = bool(dust.get("is_dust"))

    if is_dust:
        scope = DUST
        reason = "dust_position_irrespective_of_reset_origin"
        origin = "post" if ts is not None and ts >= boundary_dt else "pre"
        return {
            "position_id": _text(position.get("position_id") or position.get("asset_id") or position.get("symbol")),
            "symbol": _text(position.get("symbol")).upper(),
            "reset_scope": scope,
            "reset_reason": reason,
            "record_timestamp_utc": _iso(ts) if ts else None,
            "boundary_timestamp_utc": _iso(boundary_dt),
            "dust": True,
            "dust_classification": dust,
            "is_post_reset_candidate": False,
            "reset_origin": origin,
            "reset_id": boundary.get("reset_id"),
        }

    if ts is None:
        scope = RESET_BOUNDARY_REVIEW_REQUIRED
        reason = "missing_or_invalid_position_timestamp"
        origin = "unknown"
    elif ts < boundary_dt:
        scope = LEGACY_PRE_RESET_POSITION
        reason = "position_opened_before_reset_boundary"
        origin = "pre"
    elif _is_current_astra_owned(position) and _is_lane_known(position):
        scope = POST_RESET_CURRENT
        reason = "post_reset_position_with_current_ownership_and_lane"
        origin = "post"
    else:
        scope = RESET_BOUNDARY_REVIEW_REQUIRED
        reason = "post_reset_position_lacks_current_ownership_or_lane"
        origin = "post"

    ownership = classify_canonical_ownership_v1(
        position, is_broker_position=True, has_db_record=True
    )

    return {
        "position_id": _text(position.get("position_id") or position.get("asset_id") or position.get("symbol")),
        "symbol": _text(position.get("symbol")).upper(),
        "reset_scope": scope,
        "reset_reason": reason,
        "record_timestamp_utc": _iso(ts) if ts else None,
        "boundary_timestamp_utc": _iso(boundary_dt),
        "dust": False,
        "dust_classification": dust,
        "is_post_reset_candidate": scope == POST_RESET_CURRENT,
        "ownership_state": ownership.get("ownership_state"),
        "lane": ownership.get("lane"),
        "reset_origin": origin,
        "reset_id": boundary.get("reset_id"),
    }


def classify_lifecycle_reset_scope_v1(
    lifecycle: Mapping[str, Any], boundary: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Classify a completed lifecycle relative to the reset boundary."""
    boundary = boundary or determine_reset_boundary_v1()
    boundary_dt = _boundary_datetime(boundary)
    entry_ts = _entry_timestamp(lifecycle)
    exit_ts = _exit_timestamp(lifecycle)

    if entry_ts is None or exit_ts is None:
        return {
            "lifecycle_id": _text(lifecycle.get("lifecycle_id")),
            "symbol": _text(lifecycle.get("symbol")).upper(),
            "reset_scope": RESET_BOUNDARY_REVIEW_REQUIRED,
            "reset_reason": "missing_entry_or_exit_timestamp",
            "entry_timestamp_utc": _iso(entry_ts) if entry_ts else None,
            "exit_timestamp_utc": _iso(exit_ts) if exit_ts else None,
            "boundary_timestamp_utc": _iso(boundary_dt),
            "strict_truth_eligible": False,
            "blockers": ["MISSING_ENTRY_OR_EXIT_TIMESTAMP"],
            "reset_id": boundary.get("reset_id"),
        }

    entry_before = entry_ts < boundary_dt
    exit_before = exit_ts < boundary_dt

    if entry_before and exit_before:
        scope = PRE_RESET_LEGACY
        reason = "complete_lifecycle_before_reset_boundary"
    elif entry_before and not exit_before:
        scope = LEGACY_RETIREMENT
        reason = "lifecycle_entered_before_reset_and_exited_after"
    elif not entry_before and not exit_before:
        eligibility = is_strict_truth_eligible_v1(lifecycle, boundary)
        if eligibility.get("eligible"):
            scope = POST_RESET_CURRENT
            reason = "post_reset_strict_truth_lifecycle"
        else:
            scope = MIXED_BOUNDARY_LIFECYCLE
            reason = "post_reset_timestamps_but_incomplete_truth_provenance"
    else:
        scope = MIXED_BOUNDARY_LIFECYCLE
        reason = "exit_timestamp_precedes_entry_timestamp_or_mixed_provenance"

    eligibility = is_strict_truth_eligible_v1(lifecycle, boundary)

    return {
        "lifecycle_id": _text(lifecycle.get("lifecycle_id")),
        "symbol": _text(lifecycle.get("symbol")).upper(),
        "reset_scope": scope,
        "reset_reason": reason,
        "entry_timestamp_utc": _iso(entry_ts),
        "exit_timestamp_utc": _iso(exit_ts),
        "boundary_timestamp_utc": _iso(boundary_dt),
        "strict_truth_eligible": eligibility.get("eligible"),
        "blockers": eligibility.get("blockers", []),
        "reset_id": boundary.get("reset_id"),
    }


# ---------------------------------------------------------------------------
# Strict truth eligibility
# ---------------------------------------------------------------------------


def is_strict_truth_eligible_v1(
    lifecycle: Mapping[str, Any], boundary: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return whether a lifecycle is a strict post-reset broker truth."""
    boundary = boundary or determine_reset_boundary_v1()
    boundary_dt = _boundary_datetime(boundary)
    row = dict(lifecycle or {})
    blockers: list[str] = []

    if not _text(row.get("candidate_id")):
        blockers.append("MISSING_CANDIDATE_ID")

    entry_ts = _entry_timestamp(row)
    if not (
        _truthy(row.get("entry_decision_after_reset"))
        or (entry_ts is not None and entry_ts >= boundary_dt)
    ):
        blockers.append("ENTRY_DECISION_NOT_AFTER_RESET")

    if not _truthy(row.get("trusted_quote_provenance")):
        blockers.append("TRUSTED_QUOTE_PROVENANCE_MISSING")

    if not (
        _truthy(row.get("paper_order_submitted_after_reset"))
        or _text(row.get("entry_order_id"))
    ):
        blockers.append("PAPER_ORDER_NOT_SUBMITTED_AFTER_RESET")

    if not (
        _truthy(row.get("broker_entry_fill_confirmed"))
        or _text(row.get("entry_fill_id"))
    ):
        blockers.append("BROKER_ENTRY_FILL_NOT_CONFIRMED")

    current_ownership = _text(row.get("current_astra_ownership"))
    if current_ownership == "":
        ownership = classify_canonical_ownership_v1(
            row, is_broker_position=True, has_db_record=True
        )
        current_ownership = ownership.get("ownership_state", "")
    if current_ownership != "MANAGED":
        blockers.append("CURRENT_ASTRA_OWNERSHIP_MISSING")

    exit_ts = _exit_timestamp(row)
    if not (
        _truthy(row.get("exit_decision_after_reset"))
        or (exit_ts is not None and exit_ts >= boundary_dt)
    ):
        blockers.append("EXIT_DECISION_NOT_AFTER_RESET")

    if not _truthy(row.get("human_approval_satisfied")):
        blockers.append("HUMAN_APPROVAL_NOT_SATISFIED")

    if not (
        _truthy(row.get("broker_exit_fill_confirmed"))
        or _text(row.get("exit_fill_id"))
    ):
        blockers.append("BROKER_EXIT_FILL_NOT_CONFIRMED")

    if not _truthy(row.get("broker_residual_zero_confirmed")):
        blockers.append("BROKER_RESIDUAL_ZERO_NOT_CONFIRMED")

    if not _truthy(row.get("lifecycle_closed_once")):
        if not (_text(row.get("exit_fill_id")) and _text(row.get("closed_at"))):
            blockers.append("LIFECYCLE_NOT_CLOSED_ONCE")

    if not _is_lane_known(row):
        blockers.append("LANE_UNKNOWN")

    if not _is_horizon_known(row):
        blockers.append("HORIZON_UNKNOWN")

    if not _truthy(row.get("truth_provenance_complete")):
        blockers.append("TRUTH_PROVENANCE_INCOMPLETE")

    return {
        "eligible": len(blockers) == 0,
        "blockers": blockers,
        "candidate_id": _text(row.get("candidate_id")),
        "lifecycle_id": _text(row.get("lifecycle_id")),
        "symbol": _text(row.get("symbol")).upper(),
    }


def build_post_reset_strict_truth_v1(
    lifecycle: Mapping[str, Any], boundary: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build a single post-reset strict-truth record, or return the first blocker."""
    eligibility = is_strict_truth_eligible_v1(lifecycle, boundary)
    if not eligibility.get("eligible"):
        return {
            "error": "not_strict_truth_eligible",
            "first_blocker": eligibility.get("blockers", ["UNKNOWN"])[0],
            **eligibility,
        }

    row = dict(lifecycle)
    lane = _lane(row)
    realized_return = _num(row.get("realized_return_pct") or row.get("return_pct")) or 0.0
    realized_pnl = _num(row.get("realized_pnl") or row.get("dollar_pl")) or 0.0

    return {
        "truth_scope": POST_RESET_CURRENT,
        "lifecycle_id": _text(row.get("lifecycle_id")),
        "candidate_id": _text(row.get("candidate_id")),
        "symbol": _text(row.get("symbol")).upper(),
        "lane": lane,
        "horizon": _horizon(row),
        "entry_fill_id": _text(row.get("entry_fill_id")),
        "exit_fill_id": _text(row.get("exit_fill_id")),
        "entry_timestamp_utc": _iso(_entry_timestamp(row)),
        "exit_timestamp_utc": _iso(_exit_timestamp(row)),
        "realized_return_pct": realized_return,
        "realized_dollar_pl": realized_pnl,
        "post_reset_day_strict_truth": lane == "DAY",
        "post_reset_swing_strict_truth": lane == "SWING",
        "post_reset_crypto_strict_truth": lane == "CRYPTO",
        "strict_truth_eligible": True,
        "blockers": [],
        "reset_id": (boundary or determine_reset_boundary_v1()).get("reset_id"),
    }


def build_lane_strict_truth_counts_v1(
    lifecycles: list[Mapping[str, Any]], boundary: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Count post-reset strict truths by lane."""
    counts = {
        "POST_RESET_DAY_STRICT_TRUTH": 0,
        "POST_RESET_SWING_STRICT_TRUTH": 0,
        "POST_RESET_CRYPTO_STRICT_TRUTH": 0,
        "total": 0,
    }
    for lifecycle in lifecycles:
        truth = build_post_reset_strict_truth_v1(lifecycle, boundary)
        if truth.get("error"):
            continue
        lane = _text(truth.get("lane")).upper()
        if lane == "DAY":
            counts["POST_RESET_DAY_STRICT_TRUTH"] += 1
        elif lane == "SWING":
            counts["POST_RESET_SWING_STRICT_TRUTH"] += 1
        elif lane == "CRYPTO":
            counts["POST_RESET_CRYPTO_STRICT_TRUTH"] += 1
        counts["total"] += 1
    return counts


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _return_pct_value(row: Mapping[str, Any]) -> float | None:
    for key in ("realized_return_pct", "return_pct", "return_percent", "pnl_pct", "profit_pct"):
        value = row.get(key)
        if value not in (None, ""):
            n = _num(value)
            if n is not None:
                return n
    return None


def _dollar_pl_value(row: Mapping[str, Any]) -> float | None:
    for key in ("realized_pnl", "dollar_pl", "pnl", "profit_loss", "realized_dollar_pl"):
        value = row.get(key)
        if value not in (None, ""):
            n = _num(value)
            if n is not None:
                return n
    return None


def _hold_minutes(row: Mapping[str, Any]) -> float | None:
    for key in ("hold_duration_minutes", "actual_hold_duration_minutes", "hold_time_minutes"):
        value = row.get(key)
        if value not in (None, ""):
            n = _num(value)
            if n is not None:
                return n
    entry_ts = _entry_timestamp(row)
    exit_ts = _exit_timestamp(row)
    if entry_ts is not None and exit_ts is not None:
        return max(0.0, (exit_ts - entry_ts).total_seconds() / 60.0)
    return None


def _mfe(row: Mapping[str, Any]) -> float | None:
    return _num(row.get("max_favorable_excursion") or row.get("mfe"))


def _mae(row: Mapping[str, Any]) -> float | None:
    return _num(row.get("max_adverse_excursion") or row.get("mae"))


def _profit_giveback(row: Mapping[str, Any]) -> float | None:
    mfe = _mfe(row)
    ret = _return_pct_value(row)
    if mfe is not None and ret is not None:
        return max(0.0, mfe - max(0.0, ret))
    return _num(row.get("profit_giveback"))


def _matches_scope(classification: dict[str, Any], scope: str) -> bool:
    reset_scope = classification.get("reset_scope")
    if scope == "CURRENT_POST_RESET":
        return reset_scope == POST_RESET_CURRENT
    if scope == "LEGACY_PRE_RESET":
        return reset_scope in {PRE_RESET_LEGACY, LEGACY_RETIREMENT}
    if scope == "LIFETIME_ALL_BROKER_FACTS":
        return reset_scope not in {RESET_BOUNDARY_REVIEW_REQUIRED, OWNERSHIP_UNKNOWN}
    if scope == "SHADOW_LEGACY_ANALYSIS":
        return reset_scope in {
            PRE_RESET_LEGACY,
            LEGACY_RETIREMENT,
            MIXED_BOUNDARY_LIFECYCLE,
            DUST,
            LEGACY_PRE_RESET_POSITION,
        }
    return False


def compute_reset_aware_metrics_v1(
    lifecycles: list[Mapping[str, Any]],
    boundary: Mapping[str, Any] | None = None,
    scope: str = "CURRENT_POST_RESET",
) -> dict[str, Any]:
    """Compute metrics only for lifecycles matching the requested scope."""
    boundary = boundary or determine_reset_boundary_v1()
    boundary_dt = _boundary_datetime(boundary)

    classifications = [classify_lifecycle_reset_scope_v1(lc, boundary) for lc in lifecycles]
    eligible = []
    excluded_reasons: dict[str, int] = {}
    for lc, classification in zip(lifecycles, classifications):
        if _matches_scope(classification, scope):
            eligible.append(dict(lc))
        else:
            reason = classification.get("reset_scope", "UNKNOWN")
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1

    eligible_count = len(eligible)
    excluded_count = len(lifecycles) - eligible_count

    if eligible_count == 0:
        return {
            "completed_trades": 0,
            "strict_broker_truths": 0,
            "day_truths": 0,
            "swing_truths": 0,
            "crypto_truths": 0,
            "win_rate": None,
            "profit_factor": None,
            "average_return": None,
            "average_dollar_pl": None,
            "entry_quality": None,
            "exit_quality": None,
            "avg_hold_duration_minutes": None,
            "max_adverse_excursion": None,
            "max_favorable_excursion": None,
            "profit_giveback": None,
            "loss_rule_compliance": None,
            "lane_performance": {},
            "horizon_performance": {},
            "metric_scope": scope,
            "reset_id": boundary.get("reset_id"),
            "reset_timestamp": boundary.get("reset_timestamp_utc"),
            "eligible_sample_count": 0,
            "excluded_sample_count": excluded_count,
            "exclusion_reasons": excluded_reasons,
            "evidence_status": "insufficient_evidence",
        }

    returns: list[float] = []
    dollar_pls: list[float] = []
    holds: list[float] = []
    mfes: list[float] = []
    maes: list[float] = []
    givebacks: list[float] = []
    winners = 0
    losers = 0
    strict_count = 0
    day_count = 0
    swing_count = 0
    crypto_count = 0
    lane_perf: dict[str, dict[str, Any]] = {}
    horizon_perf: dict[str, dict[str, Any]] = {}
    rule_violations = 0
    rule_checks = 0

    for row in eligible:
        ret = _return_pct_value(row)
        pl = _dollar_pl_value(row)
        hold = _hold_minutes(row)
        mfe = _mfe(row)
        mae = _mae(row)
        giveback = _profit_giveback(row)
        lane = _lane(row) or "UNKNOWN"
        horizon = _horizon(row) or "unknown"

        if ret is not None:
            returns.append(ret)
            if ret > 0:
                winners += 1
            elif ret < 0:
                losers += 1
        if pl is not None:
            dollar_pls.append(pl)
        if hold is not None:
            holds.append(hold)
        if mfe is not None:
            mfes.append(mfe)
        if mae is not None:
            maes.append(mae)
        if giveback is not None:
            givebacks.append(giveback)

        strict = is_strict_truth_eligible_v1(row, boundary).get("eligible", False)
        if strict:
            strict_count += 1
            if lane == "DAY":
                day_count += 1
            elif lane == "SWING":
                swing_count += 1
            elif lane == "CRYPTO":
                crypto_count += 1

        for key, perf_store in ((lane, lane_perf), (horizon, horizon_perf)):
            bucket = perf_store.setdefault(key, {"count": 0, "wins": 0, "losses": 0, "returns": []})
            bucket["count"] += 1
            if ret is not None:
                bucket["returns"].append(ret)
                if ret > 0:
                    bucket["wins"] += 1
                elif ret < 0:
                    bucket["losses"] += 1

        # Loss-rule compliance: a simple check that losses did not exceed -8%
        if ret is not None and ret < 0:
            rule_checks += 1
            if ret < -8.0:
                rule_violations += 1

    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    def _pf(rets: list[float]) -> float | None:
        wins = [r for r in rets if r > 0]
        losses = [abs(r) for r in rets if r < 0]
        if not wins and not losses:
            return None
        if not losses:
            return round(sum(wins), 4)
        return round(sum(wins) / max(1e-9, sum(losses)), 4)

    def _finalize_perf(store: dict[str, dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, bucket in store.items():
            rets = bucket["returns"]
            out[key] = {
                "count": bucket["count"],
                "win_rate": round(bucket["wins"] / bucket["count"], 4) if bucket["count"] else None,
                "average_return": _avg(rets),
                "profit_factor": _pf(rets),
            }
        return out

    win_rate = round(winners / eligible_count, 4) if eligible_count else None
    profit_factor = _pf(returns)
    avg_return = _avg(returns)
    avg_dollar_pl = _avg(dollar_pls)
    avg_hold = _avg(holds)
    max_mae = round(max(maes), 4) if maes else None
    max_mfe = round(max(mfes), 4) if mfes else None
    avg_giveback = _avg(givebacks)
    loss_compliance = (
        round(1.0 - (rule_violations / rule_checks), 4) if rule_checks else None
    )

    entry_quality = _num(eligible[0].get("entry_quality")) if eligible else None
    exit_quality = _num(eligible[0].get("exit_quality")) if eligible else None
    if entry_quality is None:
        entry_quality = _avg([_num(r.get("entry_quality")) for r in eligible if _num(r.get("entry_quality")) is not None])
    if exit_quality is None:
        exit_quality = _avg([_num(r.get("exit_quality")) for r in eligible if _num(r.get("exit_quality")) is not None])

    return {
        "completed_trades": eligible_count,
        "strict_broker_truths": strict_count,
        "day_truths": day_count,
        "swing_truths": swing_count,
        "crypto_truths": crypto_count,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "average_return": avg_return,
        "average_dollar_pl": avg_dollar_pl,
        "entry_quality": entry_quality,
        "exit_quality": exit_quality,
        "avg_hold_duration_minutes": avg_hold,
        "max_adverse_excursion": max_mae,
        "max_favorable_excursion": max_mfe,
        "profit_giveback": avg_giveback,
        "loss_rule_compliance": loss_compliance,
        "lane_performance": _finalize_perf(lane_perf),
        "horizon_performance": _finalize_perf(horizon_perf),
        "metric_scope": scope,
        "reset_id": boundary.get("reset_id"),
        "reset_timestamp": boundary.get("reset_timestamp_utc"),
        "eligible_sample_count": eligible_count,
        "excluded_sample_count": excluded_count,
        "exclusion_reasons": excluded_reasons,
        "evidence_status": "sufficient_evidence" if eligible_count >= 5 else "warming_up",
    }


# ---------------------------------------------------------------------------
# Learning eligibility
# ---------------------------------------------------------------------------


def classify_learning_eligibility_v1(
    lifecycle: Mapping[str, Any], boundary: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Classify whether a lifecycle is eligible to feed learning."""
    boundary = boundary or determine_reset_boundary_v1()
    scope_info = classify_lifecycle_reset_scope_v1(lifecycle, boundary)
    scope = scope_info.get("reset_scope")
    eligibility = is_strict_truth_eligible_v1(lifecycle, boundary)
    broker_zero = bool(
        _truthy(lifecycle.get("broker_residual_zero_confirmed"))
        or _truthy(lifecycle.get("broker_zero_confirmed"))
    )

    if scope != POST_RESET_CURRENT:
        reason = f"scope_is_{scope}"
        return {
            "learning_eligible": False,
            "truth_scope": scope,
            "learning_exclusion_reason": reason,
            "reset_id": boundary.get("reset_id"),
            "broker_zero_confirmed": broker_zero,
            "strict_truth_eligible": eligibility.get("eligible"),
            "blockers": eligibility.get("blockers", []),
        }

    if not eligibility.get("eligible"):
        return {
            "learning_eligible": False,
            "truth_scope": scope,
            "learning_exclusion_reason": eligibility.get("blockers", ["UNKNOWN"])[0],
            "reset_id": boundary.get("reset_id"),
            "broker_zero_confirmed": broker_zero,
            "strict_truth_eligible": False,
            "blockers": eligibility.get("blockers", []),
        }

    return {
        "learning_eligible": True,
        "truth_scope": POST_RESET_CURRENT,
        "learning_exclusion_reason": "",
        "reset_id": boundary.get("reset_id"),
        "broker_zero_confirmed": broker_zero,
        "strict_truth_eligible": True,
        "blockers": [],
    }


# ---------------------------------------------------------------------------
# Shadow legacy analysis
# ---------------------------------------------------------------------------


def build_legacy_shadow_analysis_v1(
    legacy_lifecycles: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bounded advisory analysis of legacy evidence.  Cannot authorize trades."""
    patterns: dict[str, int] = {
        "LEGACY_OVERHOLD_PATTERN": 0,
        "LEGACY_LOSS_AVOIDANCE_PATTERN": 0,
        "LEGACY_PROFIT_SURRENDER_PATTERN": 0,
        "LEGACY_DUST_RECONCILIATION_PATTERN": 0,
        "LEGACY_LIQUIDITY_EXIT_PATTERN": 0,
    }

    horizon_limit_hours = {
        "scalp": 1.5,
        "day_trade": 10.0,
        "swing_trade": 120.0,
    }

    for row in legacy_lifecycles:
        ret = _return_pct_value(row) or 0.0
        hold = _hold_minutes(row)
        horizon = _horizon(row)
        mfe = _mfe(row) or 0.0
        liquidity = _text(row.get("liquidity_evidence")).upper()
        spread = _text(row.get("spread_evidence")).upper()

        if row.get("dust") or classify_dust_position_v1(row).get("is_dust"):
            patterns["LEGACY_DUST_RECONCILIATION_PATTERN"] += 1

        if hold is not None:
            limit = horizon_limit_hours.get(horizon, 48.0) * 60.0
            if hold > limit:
                patterns["LEGACY_OVERHOLD_PATTERN"] += 1
            if ret < -5.0 and hold > 24.0 * 60.0:
                patterns["LEGACY_LOSS_AVOIDANCE_PATTERN"] += 1

        if mfe > 5.0 and (ret < 1.0 or ret < 0.0):
            patterns["LEGACY_PROFIT_SURRENDER_PATTERN"] += 1

        if "ILLIQUID" in liquidity or "WIDE_SPREAD" in spread:
            patterns["LEGACY_LIQUIDITY_EXIT_PATTERN"] += 1

    sample_size = len(legacy_lifecycles)
    confidence = (
        "HIGH"
        if sample_size >= 50
        else "MODERATE"
        if sample_size >= 10
        else "LOW"
        if sample_size > 0
        else "INSUFFICIENT"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "sample_size": sample_size,
        "confidence": confidence,
        "patterns": patterns,
        "advisory_only": True,
        "execution_authority": "DISABLED",
        "cannot_authorize_trade": True,
        "cannot_alter_loss_thresholds": True,
        "cannot_promote_policy": True,
        "analysis_scope": "legacy_shadow_only",
        "generated_at": _iso(),
    }


# ---------------------------------------------------------------------------
# Leakage detection
# ---------------------------------------------------------------------------


def detect_reset_scope_leakage_v1(payload: dict[str, Any]) -> dict[str, Any]:
    """Detect legacy/mixed/dust/unknown evidence leaking into current metrics or learning."""
    boundary = payload.get("boundary") or determine_reset_boundary_v1()
    lifecycles = list(payload.get("lifecycles") or [])
    metrics = dict(payload.get("metrics") or {})
    learning_reports = list(payload.get("learning_reports") or [])
    classifications = list(payload.get("classifications") or [])

    leakage_reasons: list[str] = []
    affected_ids: list[str] = []

    current_scopes = {POST_RESET_CURRENT}
    non_current_scopes = {
        PRE_RESET_LEGACY,
        LEGACY_PRE_RESET_POSITION,
        LEGACY_RETIREMENT,
        MIXED_BOUNDARY_LIFECYCLE,
        DUST,
        OWNERSHIP_UNKNOWN,
        RESET_BOUNDARY_REVIEW_REQUIRED,
    }

    # Inspect explicit classifications if provided.
    for classification in classifications:
        scope = classification.get("reset_scope")
        record_id = _text(
            classification.get("lifecycle_id")
            or classification.get("position_id")
            or classification.get("record_id")
        )
        if scope in non_current_scopes and classification.get("is_post_reset_candidate"):
            leakage_reasons.append(f"non_current_scope_marked_candidate:{scope}")
            if record_id:
                affected_ids.append(record_id)

    # Inspect lifecycles directly.
    for lifecycle in lifecycles:
        classification = classify_lifecycle_reset_scope_v1(lifecycle, boundary)
        scope = classification.get("reset_scope")
        lifecycle_id = _text(lifecycle.get("lifecycle_id"))
        if scope in non_current_scopes:
            # If it appears in current metrics or learning, it is leakage.
            if metrics.get("metric_scope") == "CURRENT_POST_RESET":
                leakage_reasons.append(f"legacy_lifecycle_in_current_metrics:{scope}")
                if lifecycle_id:
                    affected_ids.append(lifecycle_id)
            for report in learning_reports:
                if _text(report.get("lifecycle_id")) == lifecycle_id and report.get("learning_eligible"):
                    leakage_reasons.append(f"legacy_lifecycle_marked_learning_eligible:{scope}")
                    affected_ids.append(lifecycle_id)

    # Inspect learning reports.
    for report in learning_reports:
        if report.get("learning_eligible") and report.get("truth_scope") != POST_RESET_CURRENT:
            rid = _text(report.get("lifecycle_id") or report.get("truth_id"))
            leakage_reasons.append(f"non_current_truth_in_learning:{report.get('truth_scope')}")
            if rid:
                affected_ids.append(rid)

    # Inspect metrics for obvious inconsistency.
    if metrics.get("metric_scope") == "CURRENT_POST_RESET" and metrics.get("excluded_sample_count", 0) < 0:
        leakage_reasons.append("metrics_report_negative_exclusion_count")

    leakage_detected = bool(leakage_reasons)

    return {
        "leakage_detected": leakage_detected,
        "leakage_reasons": list(dict.fromkeys(leakage_reasons)),
        "affected_ids": list(dict.fromkeys(affected_ids)),
        "reset_id": boundary.get("reset_id"),
    }
