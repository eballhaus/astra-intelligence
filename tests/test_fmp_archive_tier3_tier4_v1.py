import json
import sqlite3
import urllib.request
from datetime import UTC, date, datetime

import pytest

import scripts.fmp_archive_tier3_tier4_v1 as archive
import scripts.fmp_intraday_archive_compression_v1 as compression
from scripts.fmp_weekend_archive_v1 import ArchiveStop

from scripts.fmp_archive_tier3_tier4_v1 import (
    INTRADAY_SYMBOLS,
    INTRADAY_TIMEFRAME,
    normalize_intraday_rows,
    parse_intraday_timestamp,
)


def test_intraday_manifest_has_exactly_100_deterministic_symbols():
    assert len(INTRADAY_SYMBOLS) == 100
    assert len(set(INTRADAY_SYMBOLS)) == 100


def test_intraday_timestamp_preserves_native_text_and_normalizes_new_york():
    timestamp, native = parse_intraday_timestamp("2026-09-11 09:30:00")
    assert native == "2026-09-11 09:30:00"
    assert timestamp is not None


def test_intraday_rows_validate_ohlcv_and_deduplicate_canonical_timestamp():
    rows = [
        {"date": "2026-09-11 09:30:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"date": "2026-09-11 09:30:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"date": "2026-09-11 09:31:00", "open": 10.5, "high": 10.4, "low": 10, "close": 10.2, "volume": 100},
    ]
    clean, quality = normalize_intraday_rows("AAA", rows)
    assert len(clean) == 1
    assert clean[0]["provider_native_timestamp"] == "2026-09-11 09:30:00"
    assert quality["duplicate_records"] == 1
    assert quality["invalid_records"] == 1
    assert quality["chronologically_valid"] is True


def test_intraday_resolution_is_explicit_and_not_five_minute_fallback():
    assert INTRADAY_TIMEFRAME == "1Min"


def test_intraday_runner_keeps_1min_defaults_and_isolates_15min_checkpoint(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(compression, "resolve_fmp_key", lambda: ("test-key", "test"))
    manifest = [{"symbol": "AAPL", "sector": "Technology", "selection_group": "test"}]
    one_minute = compression.IntradayArchiveRunner(
        state_dir=state_dir,
        manifest=manifest,
        lookback_days=compression.DEFAULT_LOOKBACK_DAYS,
        window_days=compression.DEFAULT_WINDOW_DAYS,
        calls_per_minute=25,
    )
    fifteen_minute = compression.IntradayArchiveRunner(
        state_dir=state_dir,
        manifest=manifest,
        lookback_days=730,
        window_days=45,
        calls_per_minute=25,
        timeframe="15Min",
    )
    assert one_minute.timeframe == "1Min"
    assert one_minute.endpoint == "/stable/historical-chart/1min"
    assert one_minute.manifest_path.name == "fmp_intraday_archive_compression_v1_manifest.json"
    assert fifteen_minute.timeframe == "15Min"
    assert fifteen_minute.endpoint == "/stable/historical-chart/15min"
    assert fifteen_minute.manifest_path.name == "fmp_intraday_archive_compression_v1_15min_manifest.json"
    assert fifteen_minute.progress_path != one_minute.progress_path
    assert fifteen_minute.payload_ceiling_bytes == compression.FIFTEEN_MIN_PAYLOAD_CEILING_BYTES


def test_manifest_can_expand_to_existing_equities_and_verified_etf_context(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    equities = [
        {"symbol": f"EQ{index:03d}", "sector": "Industrials", "asset_type": "stock"}
        for index in range(497)
    ]
    etfs = [
        {"symbol": f"ETF{index:02d}", "verified_is_etf": True, "instrument_type": "ETF"}
        for index in range(38)
    ]
    (state_dir / "fmp_archive_manifest_v1.json").write_text(json.dumps({"symbols": equities}), encoding="utf-8")
    (state_dir / "fmp_archive_tier3_tier4_manifest_v1.json").write_text(json.dumps({"tier4_symbols": []}), encoding="utf-8")
    (state_dir / "fmp_archive_enrichment_manifest_v1.json").write_text(json.dumps({"symbols": etfs}), encoding="utf-8")

    manifest = compression.build_intraday_manifest_300(state_dir, timeframe="1Hour", limit=535)

    assert len(manifest) == 535
    assert len({row["symbol"] for row in manifest}) == 535
    assert sum(row["instrument_category"] == "ETF_CONTEXT" for row in manifest) == 38
    assert all(row["resolution"] == "1Hour" for row in manifest)


def test_one_hour_runner_has_deep_bounded_checkpoint_contract(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(compression, "resolve_fmp_key", lambda: ("test-key", "test"))
    runner = compression.IntradayArchiveRunner(
        state_dir=state_dir,
        manifest=[{"symbol": "AAPL", "sector": "Technology", "selection_group": "test"}],
        lookback_days=6100,
        window_days=90,
        calls_per_minute=25,
        timeframe="1Hour",
        end_date=date(2026, 9, 11),
    )
    assert runner.endpoint == "/stable/historical-chart/1hour"
    assert runner.request_limit == compression.MAX_1HOUR_REQUESTS
    assert runner.lookback_days == 6100
    assert runner.window_days == 90
    assert runner.progress_path.name.endswith("_1hour_progress.json")


def test_hourly_history_starts_use_known_daily_listing_depth(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "ai_trading_memory.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE historical_market_bars "
            "(symbol TEXT, timeframe TEXT, provider TEXT, ts INTEGER)"
        )
        connection.execute(
            "INSERT INTO historical_market_bars VALUES(?,?,?,?)",
            ("NEWCO", "1Day", "FMP_HIST", int(datetime(2018, 5, 2, tzinfo=UTC).timestamp())),
        )
    manifest = [{"symbol": "NEWCO"}, {"symbol": "OLDCO"}]

    result = compression.apply_daily_history_start_dates(state_dir, manifest)

    assert result[0]["history_start_date"] == "2018-05-02"
    assert result[0]["history_start_source"] == "canonical_FMP_HIST_1Day_min"
    assert result[1]["history_start_date"] == "2010-01-04"
    assert result[1]["history_start_source"] == "proven_1Hour_retention_floor"


def test_request_never_reads_beyond_remaining_payload_budget(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(compression, "resolve_fmp_key", lambda: ("test-key", "test"))
    runner = compression.IntradayArchiveRunner(
        state_dir=state_dir,
        manifest=[{"symbol": "AAPL", "sector": "Technology", "selection_group": "test"}],
        lookback_days=1,
        window_days=1,
        calls_per_minute=25,
        timeframe="1Hour",
        end_date=date(2026, 9, 11),
        payload_ceiling_bytes=100,
    )
    runner._guard_runtime = lambda: None
    runner.governor.wait = lambda: None

    class FakeResponse:
        status = 200

        def __init__(self):
            self.body = b"x" * 200
            self.bytes_read = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, size):
            chunk = self.body[self.bytes_read:self.bytes_read + size]
            self.bytes_read += len(chunk)
            return chunk

    response = FakeResponse()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(ArchiveStop, match="payload_ceiling_reached"):
        runner._request(family="1Hour_raw", symbol="AAPL", endpoint=runner.endpoint, params={"symbol": "AAPL"})

    assert response.bytes_read == 100
    assert runner.progress["total_payload_bytes"] == 100
    assert runner.progress["total_api_calls"] == 1


def test_existing_tier4_profile_metadata_survives_runner_reinitialization(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    manifest_path = state_dir / "fmp_archive_tier3_tier4_manifest_v1.json"
    manifest_path.write_text(
        json.dumps({"tier4_symbols": [{"symbol": "AAA", "profile_status": "RECEIVED", "sector": "Technology"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(archive, "resolve_fmp_key", lambda: ("test-key", "test"))
    runner = archive.Tier34Runner(state_dir=state_dir, intraday_manifest=[], tier4_manifest=[{"symbol": "AAA"}])
    assert runner.tier4_manifest[0]["profile_status"] == "RECEIVED"
    assert runner.tier4_manifest[0]["sector"] == "Technology"
