import json

import scripts.fmp_archive_tier3_tier4_v1 as archive

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
