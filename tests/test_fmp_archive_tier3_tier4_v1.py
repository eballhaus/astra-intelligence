import json

import scripts.fmp_archive_tier3_tier4_v1 as archive
import scripts.fmp_intraday_archive_compression_v1 as compression

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
