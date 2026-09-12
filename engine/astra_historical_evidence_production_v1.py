"""Bounded historical evidence production over Astra's existing archive.

This adapter reads ``historical_market_bars`` in SQLite read-only mode, derives
bounded forward outcomes, and hands the resulting replay evidence to the
existing Knowledge Compression and Teacher contracts.  It is intentionally
not part of the live candidate, execution, lifecycle, truth, or learning-ack
paths.
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from engine.astra_historical_learning_compression_helpers_v1 import (
    profile_and_compress_partition_v1,
)


VERSION = "1.0.0"
ARCHIVE_TABLE = "historical_market_bars"
LANES = ("DAY", "SCALP", "SWING", "CRYPTO")
MAX_SYMBOLS = 8
MAX_ROWS = 5_000
MAX_MATCHES = 24
MAX_FORWARD_BARS = 390
MAX_PROVENANCE_ROWS = 64

LANE_CONTRACTS = {
    "DAY": {"default_timeframe": "1Min", "session_scope": "same_session_archive_rows_only"},
    "SCALP": {"default_timeframe": "1Min", "session_scope": "same_session_archive_rows_only"},
    "SWING": {"default_timeframe": "1Day", "session_scope": "multi_day_daily_bars"},
    "CRYPTO": {"default_timeframe": "1Min", "session_scope": "24_7_no_equity_session_filter"},
}

SAFETY = {
    "historical_replay_only": True,
    "evidence_class": "HISTORICAL_REPLAY",
    "broker_truth_eligible": False,
    "natural_truth_eligible": False,
    "lifecycle_completion_eligible": False,
    "learning_ack_eligible": False,
    "broker_actions_added": 0,
    "provider_calls_added": 0,
    "execution_behavior_changed": False,
    "trading_policy_changed": False,
    "risk_sizing_capacity_changed": False,
    "freshness_contract_changed": False,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "") -> str:
    value = str(value if value is not None else default).strip()
    return value or default


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
        if math.isfinite(number):
            number = number / 1000.0 if number > 10_000_000_000 else number
            return int(number)
    except (TypeError, ValueError):
        pass
    raw = _text(value).replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp())


def _iso(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


def _symbol(value: Any, asset_type: str) -> str:
    raw = _text(value).upper()
    return raw if asset_type == "crypto" else raw.replace(" ", "")


def _asset_type(lane: str) -> str:
    return "crypto" if lane == "CRYPTO" else "stock"


def _valid_bar(row: Mapping[str, Any]) -> bool:
    values = [_finite(row.get(key)) for key in ("o", "h", "l", "c")]
    if any(value is None or value <= 0 for value in values):
        return False
    opening, high, low, close = values
    volume = _finite(row.get("v"))
    return bool(high >= max(opening, close) and low <= min(opening, close) and (volume is None or volume >= 0))


def _archive_row(row: Mapping[str, Any], asset_type: str) -> dict[str, Any] | None:
    row = dict(row)
    timestamp = _timestamp(row.get("ts"))
    if timestamp is None or not _valid_bar(row):
        return None
    symbol = _symbol(row.get("symbol"), asset_type)
    if not symbol:
        return None
    return {
        "symbol": symbol,
        "asset_type": _text(row.get("asset_type"), asset_type).lower(),
        "timeframe": _text(row.get("timeframe")),
        "ts": timestamp,
        "timestamp": _iso(timestamp),
        "open": _finite(row.get("o")),
        "high": _finite(row.get("h")),
        "low": _finite(row.get("l")),
        "close": _finite(row.get("c")),
        "volume": _finite(row.get("v")),
        "provider": _text(row.get("provider"), "UNKNOWN"),
        "archive_ingested_at": row.get("ingested_at"),
    }


def _derived_features(row: Mapping[str, Any]) -> dict[str, Any]:
    opening = float(row["open"])
    return_pct = (float(row["close"]) / opening - 1.0) * 100.0
    range_pct = (float(row["high"]) - float(row["low"])) / opening * 100.0
    direction = "UP" if return_pct > 0 else "DOWN" if return_pct < 0 else "FLAT"
    return {"bar_return_pct": round(return_pct, 8), "range_pct": round(range_pct, 8), "direction": direction, "volume": row.get("volume")}


def _similarity(row: Mapping[str, Any], setup: Mapping[str, Any]) -> tuple[float, list[str]]:
    if not setup:
        return 1.0, []
    actual = _derived_features(row)
    scores: list[float] = []
    used: list[str] = []
    for key in ("direction", "bar_return_pct", "range_pct", "volume"):
        expected = setup.get(key)
        if expected in (None, ""):
            continue
        used.append(key)
        if key == "direction":
            scores.append(1.0 if _text(expected).upper() == actual[key] else 0.0)
            continue
        expected_number = _finite(expected)
        actual_number = _finite(actual[key])
        if expected_number is None or actual_number is None:
            scores.append(0.0)
        elif key == "volume":
            denominator = max(abs(expected_number), abs(actual_number), 1.0)
            scores.append(max(0.0, 1.0 - abs(expected_number - actual_number) / denominator))
        else:
            denominator = max(abs(expected_number), abs(actual_number), 0.01)
            scores.append(max(0.0, 1.0 - abs(expected_number - actual_number) / denominator))
    return (round(sum(scores) / len(scores), 6) if scores else 1.0), used


def _signed_return(price: float, entry: float, side: str) -> float:
    sign = -1.0 if side == "SHORT" else 1.0
    return (price / entry - 1.0) * 100.0 * sign


def _forward_outcome(entry: Mapping[str, Any], forward: Sequence[Mapping[str, Any]], side: str) -> dict[str, Any]:
    entry_price = float(entry["close"])
    short = side == "SHORT"
    favorable = [((entry_price - float(row["low"])) / entry_price * 100.0) if short else ((float(row["high"]) / entry_price - 1.0) * 100.0) for row in forward]
    adverse = [((entry_price - float(row["high"])) / entry_price * 100.0) if short else ((float(row["low"]) / entry_price - 1.0) * 100.0) for row in forward]
    mfe = max(favorable)
    peak_index = favorable.index(mfe)
    final_return = _signed_return(float(forward[-1]["close"]), entry_price, side)
    mae = min(adverse)
    giveback = max(0.0, mfe - final_return)
    if final_return < 0:
        label = "REVERSAL"
    elif mfe > 0 and final_return < mfe * 0.5:
        label = "FADE"
    else:
        label = "CONTINUATION"
    return {
        "realized_return_pct": round(final_return, 8),
        "mfe_pct": round(mfe, 8),
        "mae_pct": round(mae, 8),
        "time_to_peak_seconds": max(0, int(forward[peak_index]["ts"] - entry["ts"])),
        "giveback_pct": round(giveback, 8),
        "holding_duration_seconds": max(0, int(forward[-1]["ts"] - entry["ts"])),
        "outcome_label": label,
        "forward_bars_observed": len(forward),
    }


def _same_archive_session(entry: Mapping[str, Any], forward: Sequence[Mapping[str, Any]]) -> bool:
    """Keep equity DAY/SCALP comparisons within the archived calendar day."""
    session = int(entry["ts"]) // 86_400
    return all(int(row["ts"]) // 86_400 == session for row in forward)


def _decision_support(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in items]
    return {
        "historical_evidence_consulted": bool(rows),
        "evidence_ids": [item["evidence_id"] for item in rows],
        "match_count": len(rows),
        "advisory_only": True,
        "natural_paper_truth_remains_final_authority": True,
        "no_retroactive_natural_truth_attribution": True,
    }


def _evidence_item(
    entry: Mapping[str, Any],
    forward: Sequence[Mapping[str, Any]],
    *,
    lane: str,
    target_symbol: str,
    setup: Mapping[str, Any],
    similarity: float,
    setup_fields: Sequence[str],
    side: str,
    query: Mapping[str, Any],
) -> dict[str, Any]:
    raw_keys = [f"{entry['symbol']}|{entry['asset_type']}|{entry['timeframe']}|{entry['ts']}"] + [
        f"{row['symbol']}|{row['asset_type']}|{row['timeframe']}|{row['ts']}" for row in forward
    ]
    evidence_id = "historical-evidence:" + hashlib.sha256(("|".join(raw_keys) + f"|{lane}|{side}").encode()).hexdigest()[:24]
    outcome = _forward_outcome(entry, forward, side)
    provider = entry["provider"]
    return {
        "evidence_id": evidence_id,
        "id": evidence_id,
        "schema_version": VERSION,
        "evidence_class": "HISTORICAL_REPLAY",
        "evidence_tier": "HISTORICAL_REPLAY",
        "lane": lane,
        "horizon": lane,
        "target_symbol": target_symbol,
        "historical_comparison_symbol": entry["symbol"],
        "symbol": entry["symbol"],
        "historical_timestamp": entry["timestamp"],
        "entry_price": entry["close"],
        "forward_end_timestamp": forward[-1]["timestamp"],
        "timestamp": entry["timestamp"],
        "resolution": entry["timeframe"],
        "source": provider,
        "provider": provider,
        "provider_native_timestamp": entry["timestamp"],
        "retrieved_at": _now_iso(),
        "setup_features_used": list(setup_fields),
        "setup_features": {key: setup.get(key) for key in setup_fields},
        "similarity_score": similarity,
        "observed_outcome": outcome["outcome_label"],
        "outcome_label": outcome["outcome_label"],
        "realized_return_pct": outcome["realized_return_pct"],
        "mfe_pct": outcome["mfe_pct"],
        "mae_pct": outcome["mae_pct"],
        "time_to_peak_seconds": outcome["time_to_peak_seconds"],
        "giveback_pct": outcome["giveback_pct"],
        "holding_duration_seconds": outcome["holding_duration_seconds"],
        "forward_bars_observed": outcome["forward_bars_observed"],
        "side": side,
        "confidence_score": 30.0,
        "confidence_state": "SINGLE_COMPARISON_NOT_PATTERN_PROOF",
        "sample_size": 1,
        "pattern_generalization_allowed": False,
        "data_quality": {"entry_bar_valid": True, "forward_bars_valid": len(forward), "complete_forward_window": True, "data_quality_score": 100.0},
        "sector_context": setup.get("sector"),
        "etf_context": setup.get("etf_context"),
        "catalyst_context": setup.get("catalyst"),
        "macro_context": setup.get("regime"),
        "provenance": {
            "database": str(query["database"]),
            "table": ARCHIVE_TABLE,
            "provider": provider,
            "query": dict(query),
            "entry_raw_key": raw_keys[0],
            "forward_raw_keys": raw_keys[1:MAX_PROVENANCE_ROWS],
            "archive_ingested_at": entry.get("archive_ingested_at"),
        },
        "unsupported_metrics": ["news_reaction", "macro_factor_effect", "catalyst_effect"] if not setup.get("catalyst") else ["news_reaction", "macro_factor_effect"],
        "historical_replay_only": True,
        "broker_truth_eligible": False,
        "natural_truth_eligible": False,
        "lifecycle_completion_eligible": False,
        "learning_ack_eligible": False,
        "advisory_only": True,
    }


def _read_rows(db_path: Path, symbols: Sequence[str], asset_type: str, timeframe: str, start_ts: int, end_ts: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not db_path.exists():
        return [], {"status": "ARCHIVE_UNAVAILABLE", "raw_rows_read": 0, "invalid_rows": 0}
    placeholders = ",".join("?" for _ in symbols)
    query = f"SELECT symbol,asset_type,timeframe,ts,o,h,l,c,v,provider,ingested_at FROM {ARCHIVE_TABLE} WHERE asset_type=? AND timeframe=? AND symbol IN ({placeholders}) AND ts>=? AND ts<=? ORDER BY symbol,ts LIMIT ?"
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (ARCHIVE_TABLE,)).fetchone()
            if not table:
                return [], {"status": "ARCHIVE_TABLE_UNAVAILABLE", "raw_rows_read": 0, "invalid_rows": 0}
            raw = connection.execute(query, (asset_type, timeframe, *symbols, start_ts, end_ts, MAX_ROWS)).fetchall()
    except (OSError, sqlite3.Error):
        return [], {"status": "ARCHIVE_READ_FAILED", "raw_rows_read": 0, "invalid_rows": 0}
    rows, invalid = [], 0
    for item in raw:
        parsed = _archive_row(item, asset_type)
        if parsed is None:
            invalid += 1
        else:
            rows.append(parsed)
    chronology_failures = 0
    previous: dict[str, int] = {}
    for row in rows:
        if row["symbol"] in previous and row["ts"] <= previous[row["symbol"]]:
            chronology_failures += 1
        previous[row["symbol"]] = row["ts"]
    return rows, {"status": "OK", "raw_rows_read": len(raw), "invalid_rows": invalid, "chronology_failures": chronology_failures}


def compress_historical_evidence_v1(evidence_items: Sequence[Mapping[str, Any]], *, database: str) -> dict[str, Any]:
    """Use the existing pure compression/Teacher handoff for replay evidence."""
    rows = [dict(item) for item in evidence_items if isinstance(item, Mapping)]
    if not rows:
        return {"status": "INSUFFICIENT_EVIDENCE", "persisted": False, **SAFETY}
    result = profile_and_compress_partition_v1(
        {"source_identity": "historical_market_bars", "path": database, "source_snapshot": "read_only_archive_query"},
        "historical-evidence-production-v1",
        rows,
    )
    return {
        "status": "READY_FOR_TEACHER" if result.get("canonical_teacher_handoff") else "INSUFFICIENT_EVIDENCE",
        "persisted": False,
        "historical_replay_only": True,
        "evidence_items_compressed": len(rows),
        "canonical_compression_handoff": result.get("canonical_compression_handoff"),
        "canonical_teacher_handoff": result.get("canonical_teacher_handoff"),
        "packets": result.get("packets", []),
        **SAFETY,
    }


def produce_historical_evidence_v1(
    database: str | Path,
    *,
    lane: str,
    symbol: str,
    history_start: Any,
    history_end: Any,
    comparison_symbols: Sequence[str] | None = None,
    timeframe: str | None = None,
    forward_bars: int = 10,
    max_matches: int = 12,
    setup_features: Mapping[str, Any] | None = None,
    side: str = "LONG",
    include_compression: bool = True,
) -> dict[str, Any]:
    """Return a bounded, provenance-backed historical comparison set."""
    lane = _text(lane).upper()
    asset_type = _asset_type(lane)
    target_symbol = _symbol(symbol, asset_type)
    start_ts, end_ts = _timestamp(history_start), _timestamp(history_end)
    forward_bars = max(1, min(MAX_FORWARD_BARS, int(forward_bars or 1)))
    max_matches = max(1, min(MAX_MATCHES, int(max_matches or 1)))
    setup = dict(setup_features or {})
    side = "SHORT" if _text(side).upper() == "SHORT" else "LONG"
    requested_timeframe = _text(timeframe, LANE_CONTRACTS.get(lane, {}).get("default_timeframe", "1Day"))
    symbols = [_symbol(item, asset_type) for item in ([target_symbol] + list(comparison_symbols or []))]
    symbols = list(dict.fromkeys(item for item in symbols if item))[:MAX_SYMBOLS]
    base = {
        "schema_version": VERSION,
        "lane": lane,
        "target_symbol": target_symbol,
        "asset_type": asset_type,
        "timeframe": requested_timeframe,
        "lane_contract": dict(LANE_CONTRACTS.get(lane, {"session_scope": "explicit_caller_contract"})),
        "query": {"database": str(database), "table": ARCHIVE_TABLE, "asset_type": asset_type, "timeframe": requested_timeframe, "symbols": symbols, "start": _iso(start_ts), "end": _iso(end_ts), "forward_bars": forward_bars, "max_matches": max_matches},
        **SAFETY,
    }
    if lane not in LANES:
        return {**base, "status": "INVALID_LANE", "evidence_items": [], "compression_handoff": None, "decision_support": _decision_support([])}
    if not target_symbol or start_ts is None or end_ts is None or end_ts <= start_ts or not symbols:
        return {**base, "status": "INVALID_QUERY", "evidence_items": [], "compression_handoff": None, "decision_support": _decision_support([])}
    rows, read_status = _read_rows(Path(database), symbols, asset_type, requested_timeframe, start_ts, end_ts)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["symbol"], []).append(row)
    candidates: list[tuple[float, str, dict[str, Any], list[dict[str, Any]], list[str]]] = []
    for comparison_symbol, series in grouped.items():
        for index in range(max(0, len(series) - forward_bars)):
            entry = series[index]
            forward = series[index + 1 : index + 1 + forward_bars]
            if len(forward) != forward_bars:
                continue
            if lane in {"DAY", "SCALP"} and asset_type == "stock" and not _same_archive_session(entry, forward):
                continue
            similarity, used = _similarity(entry, setup)
            candidates.append((similarity, comparison_symbol, entry, forward, used))
    candidates.sort(key=lambda item: (-item[0], item[2]["ts"], item[1]))
    query = base["query"]
    items = [_evidence_item(entry, forward, lane=lane, target_symbol=target_symbol, setup=setup, similarity=score, setup_fields=used, side=side, query=query) for score, _symbol_name, entry, forward, used in candidates[:max_matches]]
    status = "READY" if items else "NO_MATCHES" if read_status.get("status") == "OK" else read_status.get("status")
    compression = compress_historical_evidence_v1(items, database=str(database)) if include_compression and items else None
    return {
        **base,
        "status": status,
        "retrieval": {**read_status, "symbols_returned": sorted(grouped), "candidate_windows": len(candidates), "matches_returned": len(items), "bounded": True, "full_history_scan_used": False},
        "evidence_items": items,
        "compression_handoff": compression,
        "decision_support": _decision_support(items),
    }
