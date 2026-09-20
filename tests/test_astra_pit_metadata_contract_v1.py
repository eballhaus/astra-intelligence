from __future__ import annotations

import pytest

from engine.astra_pit_metadata_contract_v1 import (
    UnsafeReplayRecord,
    normalize_historical_record,
    replay_readiness,
    require_replay_safe,
)


def test_completed_bar_requires_explicit_completion_contract_and_preserves_raw_fields():
    raw = {
        "symbol": "AAPL",
        "asset_type": "stock",
        "timeframe": "5Min",
        "ts": 1789156500,
        "provider": "FMP_HIST",
        "ingested_at": "2026-09-12T00:00:00Z",
        "provider_native_timestamp": "2026-09-11 19:55:00",
    }
    unsafe = normalize_historical_record(raw, dataset_type="market_bar")
    assert unsafe["point_in_time_status"] == "TIMESTAMP_INSUFFICIENT"
    assert unsafe["replay_safe"] is False
    assert unsafe["original_timestamp_fields"]["ts"] == 1789156500

    safe = normalize_historical_record(
        raw,
        dataset_type="market_bar",
        source_context={"completed_bar_proven": True, "replay_contract_valid": True},
    )
    assert safe["point_in_time_status"] == "POINT_IN_TIME_SAFE"
    assert safe["replay_safe"] is True
    assert safe["available_to_astra_time"] == safe["event_time"]


def test_filing_publication_is_not_period_end():
    row = {
        "symbol": "AAPL",
        "period_end": "2025-12-31",
        "acceptedDate": "2026-02-01T21:10:00Z",
        "source": "SEC_EDGAR",
    }
    normalized = normalize_historical_record(row, dataset_type="sec_filing")
    assert normalized["event_time"] == "2025-12-31T00:00:00Z"
    assert normalized["publication_time"] == "2026-02-01T21:10:00Z"
    assert normalized["available_to_astra_time"] == normalized["publication_time"]
    assert normalized["replay_safe"] is True


def test_earnings_without_release_time_fails_closed():
    normalized = normalize_historical_record({"symbol": "AAPL", "date": "2026-01-30"}, dataset_type="earnings")
    assert normalized["replay_safe"] is False
    assert replay_readiness(normalized)["replay_allowed"] is False
    with pytest.raises(UnsafeReplayRecord):
        require_replay_safe(normalized)


def test_macro_vintage_is_required_and_raw_fields_are_retained():
    normalized = normalize_historical_record(
        {"series_id": "CPIAUCSL", "observation_date": "2026-01-01", "vintage_timestamp": "2026-02-12T13:30:00Z", "value": 1.2},
        dataset_type="fred",
    )
    assert normalized["event_time"] == "2026-01-01T00:00:00Z"
    assert normalized["available_to_astra_time"] == "2026-02-12T13:30:00Z"
    assert normalized["replay_safe"] is True
    assert normalized["original_timestamp_fields"]["vintage_timestamp"] == "2026-02-12T13:30:00Z"


def test_news_requires_publication_not_event_time():
    normalized = normalize_historical_record(
        {"symbol": "AAPL", "event_time": "2026-02-01T12:00:00Z"}, dataset_type="news"
    )
    assert normalized["point_in_time_status"] == "TIMESTAMP_INSUFFICIENT"
    assert normalized["replay_safe"] is False


def test_replay_guard_rejects_future_or_incomplete_record():
    record = {
        "record_id": "pit:test:future",
        "point_in_time_status": "PARTIALLY_POINT_IN_TIME",
        "lookahead_risk": "HIGH",
        "replay_safe": False,
    }
    assert replay_readiness(record)["replay_allowed"] is False
    with pytest.raises(UnsafeReplayRecord):
        require_replay_safe(record)
