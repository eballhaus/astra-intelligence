"""Bounded, provenance-preserving index over the canonical intraday archive.

This module derives compact session summaries from ``historical_market_bars``.
The raw table remains authoritative for replay; summaries are a regenerable
search index and never participate in broker, lifecycle, truth, or learning
acknowledgement state.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time as time_module
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


VERSION = "1.0.0"
FEATURE_SCHEMA_VERSION = "intraday_session_features_v1"
SUMMARY_TABLE = "historical_intraday_session_summaries"
ARCHIVE_TABLE = "historical_market_bars"
PROVIDER = "FMP_HIST"
DEFAULT_TIMEFRAME = "1Min"
# Backward-compatible alias for callers that import the established default.
TIMEFRAME = DEFAULT_TIMEFRAME
MAX_QUERY_ROWS = 5_000
MAX_MATCHES = 24
MAX_RAW_DRILLDOWN_ROWS = 5_000
SETUP_FEATURE_ALIASES = {
    "direction": "setup_direction",
    "return_pct": "setup_return_pct",
    "range_pct": "setup_range_pct",
    "volatility_pct": "setup_realized_volatility_pct",
    "momentum_pct": "setup_max_5m_return_pct",
    "volume_ratio": "setup_volume_acceleration_ratio",
    "volatility_bucket": "setup_volatility_bucket",
    "momentum_bucket": "setup_momentum_bucket",
    "volume_bucket": "setup_volume_bucket",
}
NY_TZ = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


def normalize_intraday_timeframe(timeframe: str | None = None) -> str:
    """Return a non-empty provider timeframe while preserving the 1Min default."""
    value = str(timeframe or DEFAULT_TIMEFRAME).strip()
    return value or DEFAULT_TIMEFRAME


def source_endpoint_for_timeframe(timeframe: str | None = None) -> str:
    """Return the matching FMP stable chart endpoint for an intraday timeframe."""
    value = normalize_intraday_timeframe(timeframe)
    return f"/stable/historical-chart/{value.lower()}"


def _finite(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _bucket(value: float | None, low: float, high: float) -> str:
    if value is None:
        return "UNKNOWN"
    if value < low:
        return "LOW"
    if value < high:
        return "MEDIUM"
    return "HIGH"


def _session_segment(timestamp: int) -> tuple[str, str]:
    local = datetime.fromtimestamp(int(timestamp), UTC).astimezone(NY_TZ)
    if local.time() < REGULAR_OPEN:
        segment = "PREMARKET"
    elif local.time() < REGULAR_CLOSE:
        segment = "REGULAR"
    else:
        segment = "AFTER_HOURS"
    return local.date().isoformat(), segment


def _iso(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(int(timestamp), UTC).isoformat().replace("+00:00", "Z")


def _row_timestamp(row: Mapping[str, Any]) -> int:
    """Accept canonical numeric timestamps and read-only drill-down ISO values."""
    candidate = row.get("ts")
    if candidate is None:
        candidate = row.get("timestamp")
    try:
        return int(candidate or 0)
    except (TypeError, ValueError):
        try:
            return int(datetime.fromisoformat(str(candidate).replace("Z", "+00:00")).timestamp())
        except (TypeError, ValueError, OverflowError):
            return 0


def ensure_summary_schema(connection: sqlite3.Connection) -> None:
    """Create the derived index in the existing historical database only."""
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SUMMARY_TABLE} (
            summary_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            provider TEXT NOT NULL,
            session_date TEXT NOT NULL,
            session_segment TEXT NOT NULL,
            timezone TEXT NOT NULL,
            raw_start_ts INTEGER NOT NULL,
            raw_end_ts INTEGER NOT NULL,
            raw_row_count INTEGER NOT NULL,
            feature_schema_version TEXT NOT NULL,
            generator_version TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            sector TEXT,
            industry TEXT,
            lane_relevance_json TEXT NOT NULL,
            setup_features_json TEXT NOT NULL,
            outcome_features_json TEXT NOT NULL,
            context_json TEXT NOT NULL,
            quality_json TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            UNIQUE(symbol, timeframe, provider, session_date, session_segment, feature_schema_version)
        )
        """
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_intraday_summary_lookup ON {SUMMARY_TABLE}(timeframe, provider, session_segment, session_date)"
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_intraday_summary_symbol ON {SUMMARY_TABLE}(symbol, timeframe, provider, session_date)"
    )
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS idx_intraday_summary_behavior ON {SUMMARY_TABLE}(session_segment, sector, feature_schema_version)"
    )


def _valid_row(row: Mapping[str, Any]) -> bool:
    values = [_finite(row.get(key)) for key in ("open", "high", "low", "close")]
    if any(value is None or value <= 0 for value in values):
        return False
    opening, high, low, close = values
    volume = _finite(row.get("volume"))
    return bool(high >= max(opening, close) and low <= min(opening, close) and high >= low and (volume is None or volume >= 0))


def _feature_summary(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    session_date: str,
    segment: str,
    metadata: Mapping[str, Any],
    timeframe: str = DEFAULT_TIMEFRAME,
) -> dict[str, Any] | None:
    if not rows:
        return None
    timeframe = normalize_intraday_timeframe(timeframe)
    rows = sorted(rows, key=lambda row: int(row["timestamp"]))
    opening = float(rows[0]["open"])
    closing = float(rows[-1]["close"])
    highs = [float(row["high"]) for row in rows]
    lows = [float(row["low"]) for row in rows]
    closes = [float(row["close"]) for row in rows]
    volumes = [float(row["volume"]) for row in rows if _finite(row.get("volume")) is not None]
    minute_returns = [(closes[index] / closes[index - 1] - 1.0) * 100.0 for index in range(1, len(closes)) if closes[index - 1] > 0]
    session_return = (closing / opening - 1.0) * 100.0
    session_range = (max(highs) / min(lows) - 1.0) * 100.0 if min(lows) > 0 else None
    realized_volatility = math.sqrt(sum(value * value for value in minute_returns)) if minute_returns else 0.0
    mfe = (max(highs) / opening - 1.0) * 100.0
    mae = (min(lows) / opening - 1.0) * 100.0
    peak_index = highs.index(max(highs))
    trough_index = lows.index(min(lows))
    giveback = max(0.0, mfe - session_return)
    first_window_index = min(29, len(rows) - 1)
    first_window_return = (closes[first_window_index] / opening - 1.0) * 100.0
    max_5m = max(((closes[index] / closes[index - 5] - 1.0) * 100.0 for index in range(5, len(closes))), default=None)
    min_5m = min(((closes[index] / closes[index - 5] - 1.0) * 100.0 for index in range(5, len(closes))), default=None)
    max_30m = max(((closes[index] / closes[index - 30] - 1.0) * 100.0 for index in range(30, len(closes))), default=None)
    min_30m = min(((closes[index] / closes[index - 30] - 1.0) * 100.0 for index in range(30, len(closes))), default=None)
    sign_changes = sum(1 for left, right in zip(minute_returns, minute_returns[1:]) if _sign(left) and _sign(right) and _sign(left) != _sign(right))
    positive_returns = sum(1 for value in minute_returns if value > 0)
    negative_returns = sum(1 for value in minute_returns if value < 0)
    opening_volume = sum(volumes[: min(30, len(volumes))]) if volumes else None
    late_volume = sum(volumes[-min(30, len(volumes)):]) if volumes else None
    volume_acceleration = late_volume / opening_volume if opening_volume else None
    if session_return < -0.10 and mfe > 0.10:
        outcome_class = "REVERSAL"
    elif mfe > 0.10 and session_return < mfe * 0.50:
        outcome_class = "FADE"
    elif session_return > 0.10:
        outcome_class = "CONTINUATION"
    else:
        outcome_class = "LOW_FOLLOW_THROUGH"
    local_start = datetime.fromtimestamp(int(rows[0]["timestamp"]), UTC).astimezone(NY_TZ)
    local_end = datetime.fromtimestamp(int(rows[-1]["timestamp"]), UTC).astimezone(NY_TZ)
    def section_return(start: time, end: time) -> float | None:
        selected = [row for row in rows if start <= datetime.fromtimestamp(int(row["timestamp"]), UTC).astimezone(NY_TZ).time() < end]
        if len(selected) < 2:
            return None
        return (float(selected[-1]["close"]) / float(selected[0]["open"]) - 1.0) * 100.0

    features = {
        "open": opening,
        "high": max(highs),
        "low": min(lows),
        "close": closing,
        "session_return_pct": round(session_return, 8),
        "range_pct": round(session_range, 8) if session_range is not None else None,
        "realized_volatility_pct": round(realized_volatility, 8),
        "first_30m_return_pct": round(first_window_return, 8),
        "max_5m_return_pct": round(max_5m, 8) if max_5m is not None else None,
        "min_5m_return_pct": round(min_5m, 8) if min_5m is not None else None,
        "max_30m_return_pct": round(max_30m, 8) if max_30m is not None else None,
        "min_30m_return_pct": round(min_30m, 8) if min_30m is not None else None,
        "direction": "UP" if session_return > 0 else "DOWN" if session_return < 0 else "FLAT",
        "directional_persistence": round((positive_returns - negative_returns) / max(1, len(minute_returns)), 8),
        "sign_changes": sign_changes,
        "total_volume": sum(volumes) if volumes else None,
        "peak_volume": max(volumes) if volumes else None,
        "opening_volume": opening_volume,
        "late_volume": late_volume,
        "volume_acceleration_ratio": round(volume_acceleration, 8) if volume_acceleration is not None else None,
        "mfe_pct": round(mfe, 8),
        "mae_pct": round(mae, 8),
        "time_to_peak_seconds": max(0, int(rows[peak_index]["timestamp"]) - int(rows[0]["timestamp"])),
        "time_to_trough_seconds": max(0, int(rows[trough_index]["timestamp"]) - int(rows[0]["timestamp"])),
        "giveback_pct": round(giveback, 8),
        "holding_duration_seconds": max(0, int(rows[-1]["timestamp"]) - int(rows[0]["timestamp"])),
        "outcome_class": outcome_class,
        "opening_30m_return_pct": section_return(time(9, 30), time(10, 0)),
        "midday_return_pct": section_return(time(11, 30), time(14, 0)),
        "late_session_return_pct": section_return(time(14, 0), time(16, 0)),
        "volatility_bucket": _bucket(session_range, 1.0, 3.0),
        "momentum_bucket": _bucket(abs(max_30m or min_30m or 0.0), 1.0, 3.0),
        "volume_bucket": _bucket(volume_acceleration, 1.2, 2.0),
    }
    setup_rows = rows[: first_window_index + 1]
    setup_open = float(setup_rows[0]["open"])
    setup_close = float(setup_rows[-1]["close"])
    setup_high = max(float(row["high"]) for row in setup_rows)
    setup_low = min(float(row["low"]) for row in setup_rows)
    setup_closes = [float(row["close"]) for row in setup_rows]
    setup_returns = [(setup_closes[index] / setup_closes[index - 1] - 1.0) * 100.0 for index in range(1, len(setup_closes)) if setup_closes[index - 1] > 0]
    setup_volumes = [float(row["volume"]) for row in setup_rows if _finite(row.get("volume")) is not None]
    setup_opening_volume = sum(setup_volumes[: max(1, len(setup_volumes) // 2)]) if setup_volumes else None
    setup_late_volume = sum(setup_volumes[-max(1, len(setup_volumes) // 2):]) if setup_volumes else None
    setup_volume_ratio = setup_late_volume / setup_opening_volume if setup_opening_volume else None
    setup_max_5m = max(((setup_closes[index] / setup_closes[index - 5] - 1.0) * 100.0 for index in range(5, len(setup_closes))), default=None)
    setup_features = {
        "setup_open": setup_open,
        "setup_high": setup_high,
        "setup_low": setup_low,
        "setup_close": setup_close,
        "setup_return_pct": round((setup_close / setup_open - 1.0) * 100.0, 8),
        "setup_range_pct": round((setup_high / setup_low - 1.0) * 100.0, 8) if setup_low > 0 else None,
        "setup_realized_volatility_pct": round(math.sqrt(sum(value * value for value in setup_returns)), 8) if setup_returns else 0.0,
        "setup_max_5m_return_pct": round(setup_max_5m, 8) if setup_max_5m is not None else None,
        "setup_volume": sum(setup_volumes) if setup_volumes else None,
        "setup_volume_acceleration_ratio": round(setup_volume_ratio, 8) if setup_volume_ratio is not None else None,
        "setup_direction": "UP" if setup_close > setup_open else "DOWN" if setup_close < setup_open else "FLAT",
        "setup_volatility_bucket": _bucket((setup_high / setup_low - 1.0) * 100.0 if setup_low > 0 else None, 1.0, 3.0),
        "setup_momentum_bucket": _bucket(abs(setup_max_5m or 0.0), 1.0, 3.0),
        "setup_volume_bucket": _bucket(setup_volume_ratio, 1.2, 2.0),
        "setup_cutoff_timestamp": int(setup_rows[-1]["timestamp"]),
    }
    summary_id = f"intraday-summary:{symbol}:{timeframe}:{PROVIDER}:{session_date}:{segment}:{FEATURE_SCHEMA_VERSION}"
    regular = segment == "REGULAR"
    context = {
        "sector": metadata.get("sector"),
        "industry": metadata.get("industry"),
        "etf_flag": metadata.get("etf_flag"),
        "macro_context": None,
        "catalyst_context": None,
        "session_timezone": "America/New_York",
        "price_adjustment_status": "PROVIDER_NATIVE_UNADJUSTED_STATUS_NOT_TRANSFORMED",
    }
    quality = {
        "raw_rows_valid": len(rows),
        "chronologically_valid": all(int(left["timestamp"]) < int(right["timestamp"]) for left, right in zip(rows, rows[1:])),
        "regular_session": regular,
        "extended_hours_kept_separate": True,
        "holiday_or_half_day_not_inferred": True,
        "unsupported_features": ["spread", "order_book", "news_reaction", "future_macro_effect"],
    }
    provenance = {
        "raw_table": ARCHIVE_TABLE,
        "raw_provider": PROVIDER,
        "raw_source_endpoint": source_endpoint_for_timeframe(timeframe),
        "raw_timeframe": timeframe,
        "raw_symbol": symbol,
        "raw_start_ts": int(rows[0]["timestamp"]),
        "raw_end_ts": int(rows[-1]["timestamp"]),
        "raw_start_timestamp": _iso(int(rows[0]["timestamp"])),
        "raw_end_timestamp": _iso(int(rows[-1]["timestamp"])),
        "raw_key_pattern": f"{symbol}|stock|{timeframe}|<timestamp>|{PROVIDER}",
        "regenerable_from_raw": True,
        "historical_replay_only": True,
        "broker_truth_eligible": False,
        "natural_truth_eligible": False,
        "learning_ack_eligible": False,
    }
    return {
        "summary_id": summary_id,
        "symbol": symbol,
        "asset_type": "stock",
        "timeframe": timeframe,
        "provider": PROVIDER,
        "session_date": session_date,
        "session_segment": segment,
        "timezone": "America/New_York",
        "raw_start_ts": int(rows[0]["timestamp"]),
        "raw_end_ts": int(rows[-1]["timestamp"]),
        "raw_row_count": len(rows),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "generator_version": VERSION,
        "sector": metadata.get("sector"),
        "industry": metadata.get("industry"),
        "lane_relevance": ["SCALP", "DAY", "SWING_SUPPORT"] if regular else [],
        "features": {"setup": setup_features, "outcome": features},
        "setup_features": setup_features,
        "outcome_features": features,
        "context": context,
        "quality": quality,
        "provenance": provenance,
    }


def build_intraday_session_summaries(
    rows: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    metadata: Mapping[str, Any] | None = None,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> list[dict[str, Any]]:
    """Build deterministic summaries without copying raw bars into them."""
    metadata = dict(metadata or {})
    timeframe = normalize_intraday_timeframe(timeframe)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    seen: set[int] = set()
    for source in rows:
        row = dict(source)
        timestamp = _row_timestamp(row)
        if timestamp <= 0 or timestamp in seen or not _valid_row(row):
            continue
        seen.add(timestamp)
        row["timestamp"] = timestamp
        grouped.setdefault(_session_segment(timestamp), []).append(row)
    summaries = []
    for (session_date, segment), session_rows in sorted(grouped.items()):
        summary = _feature_summary(session_rows, symbol=symbol, session_date=session_date, segment=segment, metadata=metadata, timeframe=timeframe)
        if summary:
            summaries.append(summary)
    return summaries


def upsert_intraday_session_summaries(connection: sqlite3.Connection, summaries: Sequence[Mapping[str, Any]], *, generated_at: str) -> int:
    ensure_summary_schema(connection)
    inserted = 0
    for summary in summaries:
        cursor = connection.execute(
            f"""
            INSERT INTO {SUMMARY_TABLE}(
                summary_id,symbol,asset_type,timeframe,provider,session_date,session_segment,timezone,
                raw_start_ts,raw_end_ts,raw_row_count,feature_schema_version,generator_version,generated_at,
                sector,industry,lane_relevance_json,setup_features_json,outcome_features_json,context_json,quality_json,provenance_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(summary_id) DO UPDATE SET
                raw_start_ts=excluded.raw_start_ts, raw_end_ts=excluded.raw_end_ts, raw_row_count=excluded.raw_row_count,
                generator_version=excluded.generator_version, generated_at=excluded.generated_at,
                sector=excluded.sector, industry=excluded.industry, lane_relevance_json=excluded.lane_relevance_json,
                setup_features_json=excluded.setup_features_json, outcome_features_json=excluded.outcome_features_json,
                context_json=excluded.context_json, quality_json=excluded.quality_json,
                provenance_json=excluded.provenance_json
            """,
            (
                summary["summary_id"], summary["symbol"], summary["asset_type"], summary["timeframe"], summary["provider"],
                summary["session_date"], summary["session_segment"], summary["timezone"], summary["raw_start_ts"], summary["raw_end_ts"],
                summary["raw_row_count"], summary["feature_schema_version"], summary["generator_version"], generated_at,
                summary.get("sector"), summary.get("industry"), json.dumps(summary.get("lane_relevance") or [], sort_keys=True, separators=(",", ":")),
                json.dumps(summary.get("setup_features") or {}, sort_keys=True, separators=(",", ":")), json.dumps(summary.get("outcome_features") or {}, sort_keys=True, separators=(",", ":")),
                json.dumps(summary.get("context") or {}, sort_keys=True, separators=(",", ":")),
                json.dumps(summary.get("quality") or {}, sort_keys=True, separators=(",", ":")), json.dumps(summary.get("provenance") or {}, sort_keys=True, separators=(",", ":")),
            ),
        )
        inserted += max(0, int(cursor.rowcount or 0))
    return inserted


def _summary_row(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    get = row.get if isinstance(row, Mapping) else row.__getitem__
    setup_features = json.loads(get("setup_features_json") or "{}")
    outcome_features = json.loads(get("outcome_features_json") or "{}")
    context = json.loads(get("context_json") or "{}")
    provenance = json.loads(get("provenance_json") or "{}")
    return {
        "summary_id": get("summary_id"), "symbol": get("symbol"), "asset_type": get("asset_type"), "timeframe": get("timeframe"),
        "provider": get("provider"), "session_date": get("session_date"), "session_segment": get("session_segment"),
        "raw_start_ts": int(get("raw_start_ts")), "raw_end_ts": int(get("raw_end_ts")), "raw_row_count": int(get("raw_row_count")),
        "feature_schema_version": get("feature_schema_version"), "generated_at": get("generated_at"), "sector": get("sector"), "industry": get("industry"),
        "features": {"setup": setup_features, "outcome": outcome_features}, "setup_features": setup_features, "outcome_features": outcome_features,
        "context": context, "provenance": provenance,
    }


def _score_summary(summary: Mapping[str, Any], setup: Mapping[str, Any]) -> tuple[float, list[str]]:
    features = dict(summary.get("setup_features") or {})
    scores: list[float] = []
    used: list[str] = []
    for key, expected in setup.items():
        feature_key = SETUP_FEATURE_ALIASES.get(key)
        if expected in (None, "") or feature_key not in features:
            continue
        actual = features.get(feature_key)
        used.append(key)
        if isinstance(expected, str) and isinstance(actual, str):
            scores.append(1.0 if expected.upper() == actual.upper() else 0.0)
            continue
        expected_number, actual_number = _finite(expected), _finite(actual)
        if expected_number is None or actual_number is None:
            scores.append(0.0)
        else:
            denominator = max(abs(expected_number), abs(actual_number), 0.01)
            scores.append(max(0.0, 1.0 - abs(expected_number - actual_number) / denominator))
    sector = setup.get("sector")
    if sector not in (None, ""):
        used.append("sector")
        scores.append(1.0 if str(sector).strip().lower() == str(summary.get("sector") or "").strip().lower() else 0.0)
    return (round(sum(scores) / len(scores), 6) if scores else 1.0), used


def retrieve_intraday_session_matches(
    database: str | Path,
    *,
    lane: str,
    setup: Mapping[str, Any] | None = None,
    symbols: Sequence[str] | None = None,
    history_start_ts: int | None = None,
    history_end_ts: int | None = None,
    query_symbol: str | None = None,
    query_start_ts: int | None = None,
    query_end_ts: int | None = None,
    as_of_ts: int | None = None,
    max_matches: int = MAX_MATCHES,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> dict[str, Any]:
    """Search summaries first; return bounded matches and no raw bars."""
    started = time_module.perf_counter()
    lane = str(lane or "").upper()
    timeframe = normalize_intraday_timeframe(timeframe)
    if lane not in {"DAY", "SCALP"}:
        return {"status": "LANE_NOT_INTRADAY", "matches": [], "summary_rows_searched": 0, "raw_rows_read": 0, "full_raw_scan_used": False, "latency_ms": round((time_module.perf_counter() - started) * 1000.0, 3)}
    path = Path(database)
    if not path.exists():
        return {"status": "ARCHIVE_UNAVAILABLE", "matches": [], "summary_rows_searched": 0, "raw_rows_read": 0, "full_raw_scan_used": False, "latency_ms": round((time_module.perf_counter() - started) * 1000.0, 3)}
    max_matches = max(1, min(MAX_MATCHES, int(max_matches or MAX_MATCHES)))
    params: list[Any] = [timeframe, PROVIDER, "REGULAR"]
    clauses = ["timeframe=?", "provider=?", "session_segment=?"]
    if symbols:
        normalized = list(dict.fromkeys(str(symbol).upper() for symbol in symbols if str(symbol).strip()))
        if normalized:
            clauses.append("symbol IN (" + ",".join("?" for _ in normalized) + ")")
            params.extend(normalized)
    if history_start_ts is not None:
        clauses.append("raw_end_ts>=?")
        params.append(int(history_start_ts))
    if history_end_ts is not None:
        clauses.append("raw_start_ts<=?")
        params.append(int(history_end_ts))
    sql = f"SELECT * FROM {SUMMARY_TABLE} WHERE " + " AND ".join(clauses) + " ORDER BY session_date DESC, symbol ASC LIMIT ?"
    params.append(MAX_QUERY_ROWS)
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0) as connection:
            connection.row_factory = sqlite3.Row
            table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (SUMMARY_TABLE,)).fetchone()
            if not table:
                return {"status": "SUMMARY_TABLE_UNAVAILABLE", "matches": [], "summary_rows_searched": 0, "raw_rows_read": 0, "full_raw_scan_used": False, "latency_ms": round((time_module.perf_counter() - started) * 1000.0, 3)}
            candidates = [_summary_row(row) for row in connection.execute(sql, params).fetchall()]
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return {"status": "SUMMARY_READ_FAILED", "matches": [], "summary_rows_searched": 0, "raw_rows_read": 0, "full_raw_scan_used": False, "latency_ms": round((time_module.perf_counter() - started) * 1000.0, 3)}
    matches = []
    excluded = 0
    for summary in candidates:
        start, end = summary["raw_start_ts"], summary["raw_end_ts"]
        if as_of_ts is not None and end > int(as_of_ts):
            excluded += 1
            continue
        if query_symbol and summary["symbol"] == str(query_symbol).upper() and query_start_ts is not None and query_end_ts is not None and end >= int(query_start_ts) and start <= int(query_end_ts):
            excluded += 1
            continue
        score, used = _score_summary(summary, setup or {})
        matches.append({**summary, "similarity_score": score, "setup_fields": used})
    matches.sort(key=lambda row: (-float(row["similarity_score"]), row["raw_start_ts"], row["symbol"]))
    return {
        "status": "OK" if matches else "NO_MATCHES",
        "matches": matches[:max_matches],
        "summary_rows_searched": len(candidates),
        "raw_rows_read": 0,
        "full_raw_scan_used": False,
        "index_used": [f"{SUMMARY_TABLE}.idx_intraday_summary_lookup", f"{SUMMARY_TABLE}.idx_intraday_summary_symbol"],
        "self_match_exclusions": excluded,
        "bounded": True,
        "latency_ms": round((time_module.perf_counter() - started) * 1000.0, 3),
    }


def fetch_intraday_raw_window(
    database: str | Path,
    *,
    symbol: str,
    start_ts: int,
    end_ts: int,
    max_rows: int = MAX_RAW_DRILLDOWN_ROWS,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> list[dict[str, Any]]:
    path = Path(database)
    timeframe = normalize_intraday_timeframe(timeframe)
    if not path.exists():
        return []
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT symbol,asset_type,timeframe,ts,o,h,l,c,v,provider,ingested_at FROM {ARCHIVE_TABLE} WHERE symbol=? AND asset_type='stock' AND timeframe=? AND provider=? AND ts>=? AND ts<=? ORDER BY ts LIMIT ?",
                (str(symbol).upper(), timeframe, PROVIDER, int(start_ts), int(end_ts), max(1, min(MAX_RAW_DRILLDOWN_ROWS, int(max_rows or MAX_RAW_DRILLDOWN_ROWS)))),
            ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    return [{"symbol": row[0], "asset_type": row[1], "timeframe": row[2], "ts": int(row[3]), "timestamp": _iso(int(row[3])), "open": row[4], "high": row[5], "low": row[6], "close": row[7], "volume": row[8], "provider": row[9], "archive_ingested_at": row[10]} for row in rows]


def summary_payload_size(connection: sqlite3.Connection, *, timeframe: str | None = None) -> int:
    try:
        if timeframe:
            value = connection.execute(
                f"SELECT COALESCE(SUM(LENGTH(setup_features_json)+LENGTH(outcome_features_json)+LENGTH(context_json)+LENGTH(quality_json)+LENGTH(provenance_json)+LENGTH(lane_relevance_json)),0) FROM {SUMMARY_TABLE} WHERE timeframe=?",
                (normalize_intraday_timeframe(timeframe),),
            ).fetchone()[0]
        else:
            value = connection.execute(
                f"SELECT COALESCE(SUM(LENGTH(setup_features_json)+LENGTH(outcome_features_json)+LENGTH(context_json)+LENGTH(quality_json)+LENGTH(provenance_json)+LENGTH(lane_relevance_json)),0) FROM {SUMMARY_TABLE}"
            ).fetchone()[0]
        return int(value or 0)
    except sqlite3.Error:
        return 0
