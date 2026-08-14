"""Bounded, observational crypto executable-quote quality evidence.

This module only summarizes provider-native quote observations that the
canonical worker already collected.  It never requests data, changes the
20-second execution gate, or makes a pair executable on its own.
"""
from __future__ import annotations

from datetime import UTC, datetime
from functools import cmp_to_key
from typing import Any, Mapping


SCHEMA_VERSION = "1.0.0"
MAX_PAIRS = 32
MAX_OBSERVATIONS_PER_PAIR = 12
MIN_SAMPLES_FOR_QUALITY = 4
EXECUTABLE_QUOTE_MAX_AGE_SECONDS = 20.0
ROTATION_QUALITY_MAX_AGE_SECONDS = 60 * 60


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _symbol(value: Any) -> str:
    return str(value or "").upper().strip()


def _observed_epoch(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except (TypeError, ValueError):
        return None


def _quality_summary(symbol: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
    native = [row for row in observations if bool(row.get("native_timestamp_present"))]
    sample_size = len(native)
    fresh_count = sum(1 for row in native if bool(row.get("executable_fresh")))
    stale_count = sample_size - fresh_count
    pass_rate = round(fresh_count / sample_size, 4) if sample_size else None
    consecutive_fresh = 0
    consecutive_stale = 0
    for row in reversed(native):
        if bool(row.get("executable_fresh")):
            if consecutive_stale:
                break
            consecutive_fresh += 1
        else:
            if consecutive_fresh:
                break
            consecutive_stale += 1
    latest = observations[-1] if observations else {}
    last_fresh = next((row for row in reversed(native) if bool(row.get("executable_fresh"))), {})
    bid_ask_available = sum(1 for row in native if bool(row.get("bid_ask_available")))
    if sample_size < MIN_SAMPLES_FOR_QUALITY:
        quality = "UNKNOWN_NEUTRAL"
        preference = 0
    elif (pass_rate or 0.0) >= 0.75 and consecutive_stale == 0:
        quality = "RELIABLE_EXECUTABLE"
        preference = 1
    elif (pass_rate or 0.0) <= 0.25 and consecutive_fresh == 0:
        quality = "CHRONICALLY_STALE"
        preference = -1
    else:
        quality = "MIXED_EXECUTABILITY"
        preference = 0
    return {
        "symbol": symbol,
        "native_quote_observation_count": sample_size,
        "fresh_quote_count": fresh_count,
        "stale_quote_count": stale_count,
        "freshness_pass_rate": pass_rate,
        "last_native_quote_age_seconds": latest.get("quote_age_seconds"),
        "bid_ask_available_count": bid_ask_available,
        "last_spread_pct": latest.get("spread_pct"),
        "consecutive_fresh_observations": consecutive_fresh,
        "consecutive_stale_observations": consecutive_stale,
        "last_fresh_executable_observation_at": last_fresh.get("observed_at") or None,
        "quality": quality,
        # This is an ordering-only tie-break. It is not alpha, profitability,
        # or a replacement for final quote freshness.
        "quality_preference": preference,
        "sample_sufficient": sample_size >= MIN_SAMPLES_FOR_QUALITY,
        "data_quality_only": True,
        "execution_gate_unchanged": True,
    }


def record_crypto_quote_observation_v1(
    state: Mapping[str, Any] | None,
    observation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Append one already-collected native quote observation, bounded per pair."""
    out = dict(state or {})
    pairs = {
        _symbol(symbol): dict(value or {})
        for symbol, value in dict(out.get("pairs") or {}).items()
        if _symbol(symbol)
    }
    row = dict(observation or {})
    symbol = _symbol(row.get("symbol"))
    if not symbol:
        return {"schema_version": SCHEMA_VERSION, "pairs": pairs}
    age = _number(row.get("quote_age_seconds"))
    timestamp = str(row.get("provider_quote_timestamp") or row.get("quote_timestamp") or "")
    native_timestamp_present = bool(timestamp)
    bid = row.get("bid") if row.get("bid") not in (None, "") else row.get("provider_bid")
    ask = row.get("ask") if row.get("ask") not in (None, "") else row.get("provider_ask")
    spread = _number(row.get("spread_pct"))
    if spread is None:
        bid_number = _number(bid)
        ask_number = _number(ask)
        midpoint = ((bid_number + ask_number) / 2.0) if bid_number is not None and ask_number is not None else 0.0
        spread = ((ask_number - bid_number) / midpoint) * 100.0 if midpoint > 0 else None
    compact = {
        "observed_at": str(row.get("quote_observed_at") or row.get("observed_at") or ""),
        "native_timestamp_present": native_timestamp_present,
        "quote_age_seconds": round(age, 3) if age is not None else None,
        "executable_fresh": bool(native_timestamp_present and age is not None and age <= EXECUTABLE_QUOTE_MAX_AGE_SECONDS),
        "bid_ask_available": bid not in (None, "") and ask not in (None, ""),
        "spread_pct": round(spread, 6) if spread is not None else None,
    }
    prior = dict(pairs.get(symbol) or {})
    observations = [dict(item) for item in list(prior.get("observations") or []) if isinstance(item, Mapping)]
    observations.append(compact)
    observations = observations[-MAX_OBSERVATIONS_PER_PAIR:]
    pairs[symbol] = {"observations": observations, **_quality_summary(symbol, observations)}
    # Keep the persisted snapshot bounded even when the discoverable universe changes.
    if len(pairs) > MAX_PAIRS:
        ordered = sorted(pairs, key=lambda key: str((pairs[key].get("observations") or [{}])[-1].get("observed_at") or ""), reverse=True)
        pairs = {key: pairs[key] for key in ordered[:MAX_PAIRS]}
    return {"schema_version": SCHEMA_VERSION, "pairs": pairs, "execution_gate_unchanged": True}


def quality_for_crypto_pair_v1(state: Mapping[str, Any] | None, symbol: Any) -> dict[str, Any]:
    pair = dict(dict(state or {}).get("pairs") or {}).get(_symbol(symbol)) or {}
    if not pair:
        return _quality_summary(_symbol(symbol), [])
    return {key: value for key, value in pair.items() if key != "observations"}


def select_crypto_hybrid_rotation_batch_v1(
    universe: list[str] | tuple[str, ...] | None,
    cursor: int,
    state: Mapping[str, Any] | None,
    *,
    batch_size: int = 3,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Choose one quality-priority observation plus fair exploration slots.

    This consumes only the existing bounded executable-pair observations. It
    does not rank candidates or authorize execution; final quote freshness
    remains owned by the existing entry path.
    """
    pairs = sorted({_symbol(symbol) for symbol in (universe or []) if _symbol(symbol)})
    size = max(1, min(int(batch_size or 1), len(pairs))) if pairs else 0
    if not pairs:
        return {
            "crypto_rotation_mode": "FAIR_FALLBACK",
            "priority_pair": "",
            "priority_reason": "EMPTY_UNIVERSE",
            "priority_pass_rate": None,
            "priority_source": "crypto_executable_pair_quality_v1",
            "exploration_pairs": [],
            "batch_pairs": [],
            "next_cursor": 0,
        }

    start = int(cursor or 0) % len(pairs)

    def fair_batch(exclude: set[str], count: int) -> tuple[list[str], int]:
        selected: list[str] = []
        scanned = 0
        while scanned < len(pairs) and len(selected) < count:
            symbol = pairs[(start + scanned) % len(pairs)]
            scanned += 1
            if symbol not in exclude and symbol not in selected:
                selected.append(symbol)
        return selected, (start + scanned) % len(pairs)

    raw_pairs = dict(state or {}).get("pairs")
    if not isinstance(raw_pairs, Mapping):
        explored, next_cursor = fair_batch(set(), size)
        return {
            "crypto_rotation_mode": "FAIR_FALLBACK",
            "priority_pair": "",
            "priority_reason": "QUALITY_EVIDENCE_UNAVAILABLE",
            "priority_pass_rate": None,
            "priority_source": "crypto_executable_pair_quality_v1",
            "exploration_pairs": explored,
            "batch_pairs": explored,
            "next_cursor": next_cursor,
        }

    now = float(now_epoch) if now_epoch is not None else datetime.now(UTC).timestamp()
    candidates: list[tuple[int, float, int, float, str, dict[str, Any]]] = []
    for symbol in pairs:
        raw_quality = raw_pairs.get(symbol)
        if not isinstance(raw_quality, Mapping):
            continue
        quality = dict(raw_quality)
        observations = list(quality.get("observations") or [])
        last_observed_at = _observed_epoch((observations[-1] if observations else {}).get("observed_at"))
        sample_size = int(_number(quality.get("native_quote_observation_count"), 0) or 0)
        pass_rate = _number(quality.get("freshness_pass_rate"))
        quality_name = str(quality.get("quality") or "")
        if (
            not observations
            or last_observed_at is None
            or now - last_observed_at > ROTATION_QUALITY_MAX_AGE_SECONDS
            or not bool(quality.get("sample_sufficient"))
            or sample_size < MIN_SAMPLES_FOR_QUALITY
            or pass_rate is None
            or quality_name not in {"RELIABLE_EXECUTABLE", "MIXED_EXECUTABILITY", "CHRONICALLY_STALE"}
        ):
            continue
        class_rank = {
            "RELIABLE_EXECUTABLE": 2,
            "MIXED_EXECUTABILITY": 1,
            "CHRONICALLY_STALE": 0,
        }[quality_name]
        latest_age = _number(quality.get("last_native_quote_age_seconds"), float("inf"))
        candidates.append((class_rank, float(pass_rate), sample_size, float(latest_age if latest_age is not None else float("inf")), symbol, quality))

    if not candidates:
        explored, next_cursor = fair_batch(set(), size)
        return {
            "crypto_rotation_mode": "FAIR_FALLBACK",
            "priority_pair": "",
            "priority_reason": "QUALITY_EVIDENCE_INSUFFICIENT_OR_STALE",
            "priority_pass_rate": None,
            "priority_source": "crypto_executable_pair_quality_v1",
            "exploration_pairs": explored,
            "batch_pairs": explored,
            "next_cursor": next_cursor,
        }

    # Prefer reliable, then mixed, then chronically stale evidence. Within a
    # class, existing pass rate/sample/age facts and the symbol are a stable
    # deterministic tie-break; no alpha or trade ranking input is introduced.
    candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3], item[4]))
    _, pass_rate, _sample_size, _latest_age, priority_pair, priority_quality = candidates[0]
    exploration, next_cursor = fair_batch({priority_pair}, max(0, size - 1))
    batch_pairs = [priority_pair, *exploration]
    return {
        "crypto_rotation_mode": "HYBRID",
        "priority_pair": priority_pair,
        "priority_reason": f"{priority_quality.get('quality')}_SAMPLE_SUFFICIENT",
        "priority_pass_rate": pass_rate,
        "priority_source": "crypto_executable_pair_quality_v1",
        "exploration_pairs": exploration,
        "batch_pairs": batch_pairs,
        "next_cursor": next_cursor,
    }


def apply_crypto_executable_quality_tiebreak_v1(
    rows: list[Mapping[str, Any]] | None,
    state: Mapping[str, Any] | None,
    *,
    comparable_score_margin: float = 1.0,
) -> list[dict[str, Any]]:
    """Prefer proven executable data only when candidate scores are comparable.

    The original ranking score remains dominant. Insufficient samples preserve
    stable input order and cannot promote or blacklist a pair.
    """
    prepared: list[tuple[int, dict[str, Any], float, int]] = []
    for index, raw in enumerate(rows or []):
        row = dict(raw or {})
        quality = quality_for_crypto_pair_v1(state, row.get("symbol"))
        row["crypto_executable_pair_quality_v1"] = quality
        row["crypto_executable_quality_factor"] = quality.get("quality")
        row["crypto_executable_quality_tiebreak_only"] = True
        score = _number(row.get("ranking_score"), None)
        if score is None:
            score = _number(row.get("grade_percent"), None)
        if score is None:
            score = _number(row.get("buy_quality_score"), None)
        if score is None:
            score = _number(row.get("confidence"), 0.0) or 0.0
        prepared.append((index, row, float(score), int(quality.get("quality_preference") or 0)))

    def compare(left: tuple[int, dict[str, Any], float, int], right: tuple[int, dict[str, Any], float, int]) -> int:
        if abs(left[2] - right[2]) <= comparable_score_margin and left[3] != right[3]:
            return -1 if left[3] > right[3] else 1
        if left[2] != right[2]:
            return -1 if left[2] > right[2] else 1
        return -1 if left[0] < right[0] else (1 if left[0] > right[0] else 0)

    ordered = sorted(prepared, key=cmp_to_key(compare))
    for position, (_, row, _, _) in enumerate(ordered, start=1):
        row["crypto_executable_quality_preference_order"] = position
    return [row for _, row, _, _ in ordered]
