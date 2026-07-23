"""Canonical per-lane candidate snapshots for partial-cycle reuse.

Produced during the full cycle when equity candidates (top-buys) are ranked and
lane-attributed. Consumed during CYCLE_PARTIAL to provide actual candidate rows
without an additional provider sweep.

No broker positions are included. No provider calls are added.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "astra_lane_candidate_snapshot_v1"
MAX_ROWS_PER_LANE = 10


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


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


def _load_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return dict(data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _age_minutes(value: Any, now: datetime | None = None) -> float | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return max(0.0, (ref - dt).total_seconds() / 60.0)
    except Exception:
        return None


def build_lane_candidate_snapshots(
    candidate_rows: Sequence[Mapping[str, Any]],
    cycle_id: str = "",
    max_rows: int = MAX_ROWS_PER_LANE,
) -> dict[str, Any]:
    """Build bounded per-lane snapshots from ranked equity candidates.

    Expects rows with lane/horizon attribution already applied by
    the canonical candidate producer. Broker positions are excluded.
    """
    as_of = _iso()
    day_rows: list[dict[str, Any]] = []
    swing_rows: list[dict[str, Any]] = []

    for row in (candidate_rows or []):
        if not isinstance(row, dict):
            continue
        lane = _text(row.get("lane_id") or row.get("lane")).upper()
        horizon = _text(
            row.get("paper_entry_horizon_style")
            or row.get("intended_horizon")
            or row.get("assigned_horizon")
        ).lower()
        asset_class = _text(
            row.get("asset_class") or row.get("asset_type")
        ).lower()

        if asset_class in ("crypto", "cryptocurrency"):
            continue  # crypto has its own snapshot

        # Skip rows that are clearly broker positions, not candidate rankings
        has_candidate_fields = (
            _text(row.get("candidate_id") or row.get("recommendation_id") or row.get("rank"))
            or (lane or horizon)
        )
        if not has_candidate_fields:
            continue

        if lane == "DAY" or horizon in ("scalp", "day_trade", "day", "intraday"):
            if len(day_rows) < max_rows:
                day_rows.append(_normalize_row(row, "DAY", as_of))
        elif lane == "SWING" or horizon in ("swing_trade", "swing", "position_trade"):
            if len(swing_rows) < max_rows:
                swing_rows.append(_normalize_row(row, "SWING", as_of))
        else:
            if len(swing_rows) < max_rows:
                swing_rows.append(_normalize_row(row, "SWING", as_of))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": as_of,
        "cycle_id": _text(cycle_id),
        "producer": "equity_top_buys",
        "source_name": "top_buys_runtime_snapshot",
        "provider_calls_added": 0,
        "max_rows_per_lane": max_rows,
        "lanes": {
            "DAY": {
                "lane": "DAY",
                "candidate_count": len(day_rows),
                "bounded": True,
                "candidates": day_rows,
            },
            "SWING": {
                "lane": "SWING",
                "candidate_count": len(swing_rows),
                "bounded": True,
                "candidates": swing_rows,
            },
        },
    }


def _normalize_row(row: Mapping[str, Any], lane: str, as_of: str) -> dict[str, Any]:
    r = dict(row or {})
    return {
        "candidate_id": _text(r.get("candidate_id") or r.get("recommendation_id") or r.get("id")),
        "symbol": _text(r.get("symbol")).upper(),
        "lane": lane,
        "horizon": _text(
            r.get("paper_entry_horizon_style")
            or r.get("assigned_horizon")
            or r.get("intended_horizon")
            or r.get("horizon")
        ),
        "rank": r.get("rank") if r.get("rank") is not None else r.get("score"),
        "quote_timestamp": _text(r.get("quote_timestamp") or r.get("generated_at")),
        "bar_timestamp": _text(r.get("bar_timestamp")),
        "freshness_state": _text(r.get("candidate_snapshot_freshness") or r.get("freshness_result")),
        "candidate_integrity_state": _text(r.get("eligibility_result") or r.get("integrity_state")),
        "eligibility_state": _text(r.get("eligibility_result")),
        "first_causal_blocker": _text(r.get("exact_blocker") or r.get("reason") or r.get("final_blocker_reason")),
        "source_provenance": _text(r.get("candidate_source") or r.get("paper_autopilot_candidate_source") or "top_buys"),
        "snapshot_normalized_at": as_of,
    }


def load_lane_snapshots(path: str) -> dict[str, Any]:
    raw = _load_json(path)
    if not raw:
        return {
            "schema_version": SCHEMA_VERSION,
            "loaded": False,
            "lanes": {},
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "loaded": True,
        "generated_at": raw.get("generated_at"),
        "cycle_id": raw.get("cycle_id"),
        "lanes": dict(raw.get("lanes") or {}),
    }


def save_lane_snapshots(path: str, state: Mapping[str, Any]) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dict(state).get("generated_at") or _iso(),
        "cycle_id": dict(state).get("cycle_id", ""),
        "producer": dict(state).get("producer", "equity_top_buys"),
        "source_name": dict(state).get("source_name", "top_buys_runtime_snapshot"),
        "provider_calls_added": 0,
        "max_rows_per_lane": MAX_ROWS_PER_LANE,
        "lanes": dict(dict(state).get("lanes") or {}),
    }
    _atomic_write(path, payload)


def get_candidates_for_lane(state: dict[str, Any], lane: str) -> list[dict[str, Any]]:
    lanes = dict(state.get("lanes") or {})
    lane_data = dict(lanes.get(lane) or {})
    return list(lane_data.get("candidates") or [])


def snapshot_freshness(state: dict[str, Any], max_age_minutes: float = 30.0) -> str:
    generated = state.get("generated_at", "")
    age = _age_minutes(generated)
    if age is None:
        return "SNAPSHOT_MISSING"
    if age > max_age_minutes:
        return "SNAPSHOT_STALE"
    return "SNAPSHOT_CURRENT"
