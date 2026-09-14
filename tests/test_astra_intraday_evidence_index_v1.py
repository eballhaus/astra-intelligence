from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from engine.astra_historical_evidence_production_v1 import produce_historical_evidence_v1
from engine.astra_intraday_evidence_index_v1 import (
    FEATURE_SCHEMA_VERSION,
    SUMMARY_TABLE,
    build_intraday_session_summaries,
    ensure_summary_schema,
    fetch_intraday_raw_window,
    retrieve_intraday_session_matches,
    upsert_intraday_session_summaries,
)
from scripts.fmp_intraday_archive_compression_v1 import build_intraday_manifest_300


def _bars(symbol: str, start: datetime, count: int = 40) -> list[dict]:
    rows = []
    for index in range(count):
        price = 100.0 + index * 0.01
        if index == 35:
            price += 4.0
        timestamp = int((start + timedelta(minutes=index)).timestamp())
        rows.append({"symbol": symbol, "timestamp": timestamp, "open": price, "high": price + 0.05, "low": price - 0.05, "close": price + 0.02, "volume": 1000 + index})
    return rows


def _archive_db(tmp_path):
    path = tmp_path / "archive.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE historical_market_bars (symbol TEXT, asset_type TEXT, timeframe TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, provider TEXT, ingested_at TEXT, PRIMARY KEY(symbol,asset_type,timeframe,ts))")
        start = datetime(2026, 9, 10, 13, 30, tzinfo=UTC)
        all_rows = _bars("AAPL", start) + _bars("MSFT", start + timedelta(days=1))
        connection.executemany(
            "INSERT INTO historical_market_bars VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(row["symbol"], "stock", "1Min", row["timestamp"], row["open"], row["high"], row["low"], row["close"], row["volume"], "FMP_HIST", "2026-09-12T00:00:00Z") for row in all_rows],
        )
        ensure_summary_schema(connection)
        summaries = []
        for symbol, offset in (("AAPL", 0), ("MSFT", 1)):
            summaries.extend(build_intraday_session_summaries(_bars(symbol, start + timedelta(days=offset)), symbol=symbol, metadata={"sector": "Technology", "industry": "Software"}))
        upsert_intraday_session_summaries(connection, summaries, generated_at="2026-09-12T00:00:00Z")
        connection.commit()
    return path, start


def test_intraday_summary_uses_new_york_session_and_separates_setup_from_outcome():
    start = datetime(2026, 9, 10, 13, 30, tzinfo=UTC)
    summary = build_intraday_session_summaries(_bars("AAPL", start), symbol="AAPL", metadata={"sector": "Technology"})[0]
    assert summary["session_date"] == "2026-09-10"
    assert summary["session_segment"] == "REGULAR"
    assert summary["timezone"] == "America/New_York"
    assert summary["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert summary["setup_features"]["setup_cutoff_timestamp"] == _bars("AAPL", start)[29]["timestamp"]
    assert summary["outcome_features"]["time_to_peak_seconds"] >= 35 * 60
    assert summary["provenance"]["raw_table"] == "historical_market_bars"
    assert summary["provenance"]["regenerable_from_raw"] is True
    assert "raw bars" not in json.dumps(summary["setup_features"]).lower()


def test_summary_storage_is_compact_and_indexed(tmp_path):
    path, _ = _archive_db(tmp_path)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({SUMMARY_TABLE})")}
        assert {"setup_features_json", "outcome_features_json", "provenance_json", "feature_schema_version"} <= columns
        assert connection.execute(f"SELECT COUNT(*) FROM {SUMMARY_TABLE}").fetchone()[0] == 2
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_intraday_summary_lookup'").fetchone()
        payload = connection.execute(f"SELECT setup_features_json,outcome_features_json,provenance_json FROM {SUMMARY_TABLE} LIMIT 1").fetchone()
        assert all("historical_market_bars" not in value for value in payload[:2])


def test_raw_drilldown_rows_regenerate_summary_deterministically(tmp_path):
    path, start = _archive_db(tmp_path)
    raw = fetch_intraday_raw_window(path, symbol="AAPL", start_ts=int(start.timestamp()), end_ts=int((start + timedelta(minutes=39)).timestamp()))
    first = build_intraday_session_summaries(raw, symbol="AAPL")
    second = build_intraday_session_summaries(raw, symbol="AAPL")
    assert first == second
    assert first[0]["provenance"]["raw_source_endpoint"] == "/stable/historical-chart/1min"


def test_indexed_retrieval_excludes_self_and_future_windows(tmp_path):
    path, start = _archive_db(tmp_path)
    start_ts = int(start.timestamp())
    end_ts = int((start + timedelta(minutes=40)).timestamp())
    result = retrieve_intraday_session_matches(
        path,
        lane="SCALP",
        setup={"direction": "UP"},
        symbols=["AAPL", "MSFT"],
        history_start_ts=start_ts,
        history_end_ts=end_ts + 86_400,
        query_symbol="AAPL",
        query_start_ts=start_ts,
        query_end_ts=end_ts,
        as_of_ts=end_ts + 86_400,
        max_matches=5,
    )
    assert result["status"] == "OK"
    assert result["summary_rows_searched"] == 2
    assert [row["symbol"] for row in result["matches"]] == ["MSFT"]
    assert result["self_match_exclusions"] == 1
    assert result["raw_rows_read"] == 0
    assert result["full_raw_scan_used"] is False

    future = retrieve_intraday_session_matches(path, lane="DAY", symbols=["MSFT"], as_of_ts=start_ts, max_matches=5)
    assert future["status"] == "NO_MATCHES"
    assert future["self_match_exclusions"] == 1

    same_session_future = retrieve_intraday_session_matches(
        path,
        lane="DAY",
        symbols=["MSFT"],
        as_of_ts=int((start + timedelta(days=1, minutes=1)).timestamp()),
        max_matches=5,
    )
    assert same_session_future["status"] == "NO_MATCHES"
    assert same_session_future["self_match_exclusions"] == 1


def test_historical_evidence_prefers_summary_index_then_bounded_raw_drilldown(tmp_path):
    path, start = _archive_db(tmp_path)
    result = produce_historical_evidence_v1(
        path,
        lane="SCALP",
        symbol="AAPL",
        comparison_symbols=["MSFT"],
        history_start=start,
        history_end=start + timedelta(days=2),
        forward_bars=3,
        max_matches=1,
    )
    assert result["status"] == "READY"
    assert result["retrieval"]["retrieval_mode"] == "INDEXED_INTRADAY_SUMMARY_FIRST"
    assert result["retrieval"]["full_history_scan_used"] is False
    assert result["retrieval"]["raw_rows_read"] <= 4
    assert result["evidence_items"][0]["provenance"]["summary_table"] == SUMMARY_TABLE
    assert result["evidence_items"][0]["natural_truth_eligible"] is False


def test_300_symbol_manifest_is_deterministic_and_source_bounded(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    rows = [{"symbol": f"X{index:03d}", "sector": ("Technology" if index % 2 == 0 else "Industrials"), "industry": "Test", "asset_type": "stock"} for index in range(300)]
    (state / "fmp_archive_manifest_v1.json").write_text(json.dumps({"symbols": rows}), encoding="utf-8")
    first = build_intraday_manifest_300(state)
    second = build_intraday_manifest_300(state)
    assert len(first) == 300
    assert [row["symbol"] for row in first] == [row["symbol"] for row in second]
    assert all(row["asset_type"] == "stock" and "/" not in row["symbol"] for row in first)
    assert {row["sector"] for row in first} == {"Technology", "Industrials"}
