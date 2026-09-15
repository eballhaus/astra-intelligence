"""Bounded lane-aware selection for the existing SIP observation canary.

Selection consumes only existing qualified lane finalists. It has no ranking,
execution, broker, lifecycle, or truth authority.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

LANES = ("SCALP", "DAY", "SWING")
HARD_CAP = 24
PREFERRED_TARGET = 18
LANE_CANDIDATE_CAP = 6
DEFAULT_HOLD_SECONDS = 600


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "eligible", "qualified"}
    return bool(value)


def _epoch(value: Any) -> float | None:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value or "").strip()
        if not raw:
            return None
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def _rank(row: Mapping[str, Any]) -> int | None:
    for key in ("lane_finalist_rank", "lane_shortlist_rank"):
        try:
            value = int(row.get(key))
        except (TypeError, ValueError, OverflowError):
            continue
        if value > 0:
            return value
    return None


def _current_candidates(
    rows: Sequence[Mapping[str, Any]],
    *,
    now: float,
    max_age_seconds: float,
) -> dict[str, dict[str, dict[str, Any]]]:
    by_lane: dict[str, dict[str, dict[str, Any]]] = {lane: {} for lane in LANES}
    for raw in rows or ():
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        lane = str(row.get("lane_ranked_entry_lane") or "").upper().strip()
        symbol = str(row.get("symbol") or "").upper().strip()
        if lane not in LANES or not symbol or "/" in symbol:
            continue
        if not _truthy(row.get("lane_ranked_entry_funnel_v1")) or not _truthy(row.get("lane_finalist")):
            continue
        if not (_truthy(row.get("qualified")) or _truthy(row.get("eligible"))):
            continue
        rank = _rank(row)
        if rank is None:
            continue
        freshness = str(
            row.get("candidate_snapshot_freshness")
            or row.get("candidate_freshness_status")
            or row.get("freshness_state")
            or ""
        ).upper()
        if any(token in freshness for token in ("STALE", "EXPIRED", "MISSING", "INVALID", "REJECTED")):
            continue
        timestamp = _epoch(
            row.get("candidate_generated_at")
            or row.get("generated_at")
            or row.get("quote_timestamp")
        )
        if timestamp is not None and (timestamp > now + 60.0 or now - timestamp > max_age_seconds):
            continue
        by_lane[lane][symbol] = {
            "symbol": symbol,
            "lane": lane,
            "source_lane": lane,
            "rank": rank,
            "candidate_id": str(row.get("candidate_id") or row.get("recommendation_id") or ""),
            "provenance": str(
                row.get("candidate_source")
                or row.get("source_provenance")
                or "paper_opportunity_allocation_engine_v1"
            ),
            "managed_position": False,
        }
    return by_lane


def _prior_candidates(previous: Mapping[str, Any], now: float) -> dict[str, list[dict[str, Any]]]:
    prior: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    for raw in previous.get("symbols") or []:
        if not isinstance(raw, Mapping) or _truthy(raw.get("managed_position")):
            continue
        lane = str(raw.get("source_lane") or raw.get("lane") or "").upper().strip()
        symbol = str(raw.get("symbol") or "").upper().strip()
        expiry = _epoch(raw.get("expires_at"))
        if lane in LANES and symbol and expiry is not None and expiry > now:
            prior[lane].append(dict(raw))
    for lane in LANES:
        prior[lane].sort(key=lambda row: (_rank(row) or HARD_CAP + 1, str(row.get("symbol") or "")))
    return prior


def build_sip_dynamic_canary_selection_v1(
    *,
    candidate_rows: Sequence[Mapping[str, Any]] = (),
    managed_positions: Sequence[Mapping[str, Any]] = (),
    previous_state: Mapping[str, Any] | None = None,
    now_epoch: float | None = None,
    candidate_source_current: bool = True,
    candidate_max_age_seconds: float = 900.0,
    hold_seconds: float = DEFAULT_HOLD_SECONDS,
) -> dict[str, Any]:
    """Select pinned managed equities and sticky, qualified lane finalists."""
    now = float(now_epoch if now_epoch is not None else datetime.now(UTC).timestamp())
    hold = min(900.0, max(300.0, float(hold_seconds)))
    max_age = min(1800.0, max(60.0, float(candidate_max_age_seconds)))
    positions: dict[str, dict[str, Any]] = {}
    overflow: list[str] = []
    for raw in managed_positions or ():
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        symbol = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
        asset = str(row.get("asset_type") or row.get("asset_class") or "stock").lower()
        lane = str(row.get("lane_id") or row.get("lane") or "MANAGED").upper().strip()
        if not symbol or "/" in symbol or asset in {"crypto", "cryptocurrency"} or lane == "CRYPTO":
            continue
        positions.setdefault(symbol, {
            "symbol": symbol,
            "lane": lane if lane in LANES else "MANAGED",
            "source_lane": lane if lane in LANES else "MANAGED",
            "reason": "MANAGED_POSITION_OBSERVATION",
            "rank": None,
            "candidate_id": "",
            "managed_position": True,
            "selected_at": _iso(now),
            "expires_at": None,
            "review_at": _iso(now),
            "provenance": "canonical_broker_linked_active_position",
        })
    managed_rows = sorted(positions.values(), key=lambda row: row["symbol"])
    if len(managed_rows) > HARD_CAP:
        overflow = [row["symbol"] for row in managed_rows[HARD_CAP:]]
        managed_rows = managed_rows[:HARD_CAP]

    current = _current_candidates(
        candidate_rows if candidate_source_current else (),
        now=now,
        max_age_seconds=max_age,
    )
    previous = dict(previous_state or {})
    prior = _prior_candidates(previous, now)
    managed_symbols = {row["symbol"] for row in managed_rows}
    target = HARD_CAP if len(positions) > PREFERRED_TARGET else PREFERRED_TARGET
    target = max(len(managed_rows), min(HARD_CAP, target))
    candidates_by_lane: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    for lane in LANES:
        eligible = current[lane]
        held: list[dict[str, Any]] = []
        for old in prior[lane]:
            symbol = str(old.get("symbol") or "").upper()
            if not symbol or symbol in managed_symbols or any(row["symbol"] == symbol for row in held):
                continue
            fresh = eligible.get(symbol)
            if candidate_source_current and fresh is None:
                continue
            selected = dict(fresh or old)
            selected_at = _epoch(old.get("selected_at")) or now
            expires = _epoch(old.get("expires_at")) or (selected_at + hold)
            selected.update({
                "reason": "RECENT_VALID_LANE_CANDIDATE",
                "managed_position": False,
                "selected_at": _iso(selected_at),
                "expires_at": _iso(expires),
                "review_at": _iso(expires),
            })
            held.append(selected)
        held.sort(key=lambda row: (_rank(row) or HARD_CAP + 1, str(row.get("symbol") or "")))
        lane_rows = list(held)
        challengers = sorted(
            (row for symbol, row in eligible.items() if symbol not in {item["symbol"] for item in lane_rows} and symbol not in managed_symbols),
            key=lambda row: (int(row["rank"]), row["symbol"]),
        )
        if candidate_source_current:
            for candidate in challengers:
                if len(lane_rows) < LANE_CANDIDATE_CAP:
                    chosen = dict(candidate)
                else:
                    worst = max(lane_rows, key=lambda row: (_rank(row) or HARD_CAP + 1, str(row.get("symbol") or "")))
                    if int(candidate["rank"]) > (_rank(worst) or HARD_CAP + 1) - 2:
                        continue
                    lane_rows.remove(worst)
                    chosen = dict(candidate)
                chosen.update({
                    "reason": "EXISTING_LANE_FINALIST",
                    "managed_position": False,
                    "selected_at": _iso(now),
                    "expires_at": _iso(now + hold),
                    "review_at": _iso(now + hold),
                })
                lane_rows.append(chosen)
        lane_rows.sort(key=lambda row: (_rank(row) or HARD_CAP + 1, str(row.get("symbol") or "")))
        candidates_by_lane[lane] = lane_rows[:LANE_CANDIDATE_CAP]

    remaining = max(0, target - len(managed_rows))
    selected_candidates: list[dict[str, Any]] = []
    used = set(managed_symbols)
    cursor = 0
    while remaining and any(cursor < len(candidates_by_lane[lane]) for lane in LANES):
        progressed = False
        for lane in LANES:
            if cursor >= len(candidates_by_lane[lane]):
                continue
            row = candidates_by_lane[lane][cursor]
            if row["symbol"] not in used:
                selected_candidates.append(row)
                used.add(row["symbol"])
                remaining -= 1
                progressed = True
                if not remaining:
                    break
        if not progressed and all(cursor >= len(candidates_by_lane[lane]) for lane in LANES):
            break
        cursor += 1

    symbols = managed_rows + selected_candidates
    lane_counts: dict[str, int] = {lane: 0 for lane in LANES}
    candidate_counts: dict[str, int] = {lane: 0 for lane in LANES}
    for row in symbols:
        lane = str(row.get("source_lane") or row.get("lane") or "").upper()
        if lane in lane_counts:
            lane_counts[lane] += 1
            if not row.get("managed_position"):
                candidate_counts[lane] += 1
    eligible_counts = {lane: len(current[lane]) for lane in LANES}
    return {
        "schema_version": "astra_sip_dynamic_canary_v1",
        "generated_at": _iso(now),
        "status": "MANAGED_POSITION_CAP_CONFLICT" if overflow else ("READY" if symbols else "NO_ELIGIBLE_SYMBOLS"),
        "selection_source": "paper_opportunity_allocation_engine_v1_lane_finalists",
        "diagnostic_only": True,
        "execution_authority": False,
        "broker_actions": 0,
        "truth_mutations": 0,
        "hard_cap": HARD_CAP,
        "preferred_target": PREFERRED_TARGET,
        "target_count": target,
        "total_count": len(symbols),
        "managed_position_count": len(managed_rows),
        "managed_position_overflow_symbols": overflow,
        "candidate_source_current": bool(candidate_source_current),
        "candidate_max_age_seconds": max_age,
        "hold_seconds": hold,
        "lane_candidate_cap": LANE_CANDIDATE_CAP,
        "eligible_count_by_lane": eligible_counts,
        "selected_count_by_lane": lane_counts,
        "selected_candidate_count_by_lane": candidate_counts,
        "symbols": symbols,
    }
