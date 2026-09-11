import json
import sqlite3
from pathlib import Path

from scripts.fmp_weekend_archive_v1 import (
    MAX_CALLS_PER_MINUTE,
    RateGovernor,
    build_symbol_manifest,
    normalize_daily_rows,
    open_current_read_only,
    normalize_rows,
)


def test_normalize_daily_rows_preserves_valid_ohlcv_and_optional_adjusted_close():
    rows, quality = normalize_daily_rows(
        "AAPL",
        [
            {"symbol": "AAPL", "date": "2026-01-02", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100, "adjClose": 10.5},
            {"symbol": "AAPL", "date": "2026-01-02", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"symbol": "MSFT", "date": "2026-01-03", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        ],
    )
    assert [row["date"] for row in rows] == ["2026-01-02"]
    assert rows[0]["adjusted_close"] == 10.5
    assert quality["duplicate_records"] == 1
    assert quality["invalid_records"] == 1
    assert quality["chronologically_valid"] is True


def test_normalize_rows_accepts_fmp_list_shapes_only():
    assert normalize_rows([{"date": "2026-01-01"}]) == [{"date": "2026-01-01"}]
    assert normalize_rows({"historical": [{"date": "2026-01-01"}]}) == [{"date": "2026-01-01"}]
    assert normalize_rows({"unexpected": "shape"}) == []


def test_manifest_is_bounded_to_existing_sources_and_excludes_crypto(tmp_path: Path):
    (tmp_path / "broad_universe_intake_promotion_v1.json").write_text(
        json.dumps({"symbols": ["AAPL", "MSFT", "ETH/USD", "SPY"]}), encoding="utf-8"
    )
    db = tmp_path / "ai_trading_memory.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE historical_market_bars (symbol TEXT, asset_type TEXT)")
        conn.executemany("INSERT INTO historical_market_bars VALUES (?, ?)", [("JPM", "stock"), ("BTC/USD", "crypto")])
        conn.commit()
    manifest = build_symbol_manifest(tmp_path, limit=2)
    assert len(manifest) == 2
    assert {row["symbol"] for row in manifest} <= {"AAPL", "JPM", "MSFT", "SPY"}
    assert all("/" not in row["symbol"] for row in manifest)


def test_rate_governor_clamps_to_safe_absolute_ceiling_without_sleeping_for_first_call():
    sleeps = []
    governor = RateGovernor(MAX_CALLS_PER_MINUTE + 100, sleep_fn=sleeps.append)
    governor.wait()
    assert governor.interval == 60.0 / MAX_CALLS_PER_MINUTE
    assert sleeps == []


def test_current_read_only_reader_includes_committed_wal_state(tmp_path: Path):
    db = tmp_path / "current.db"
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("CREATE TABLE records (value TEXT)")
    writer.execute("INSERT INTO records VALUES ('current')")
    writer.commit()
    try:
        with open_current_read_only(db) as reader:
            assert reader.execute("SELECT value FROM records").fetchone()[0] == "current"
    finally:
        writer.close()
