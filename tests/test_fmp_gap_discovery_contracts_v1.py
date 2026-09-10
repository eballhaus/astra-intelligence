from __future__ import annotations

from engine.broad_universe_intake_promotion_v1 import (
    build_alpaca_reference_universe_v1,
    derive_alpaca_sip_market_discovery_v1,
)


BASE_ROW = {
    "isActivelyTrading": True,
    "isEtf": False,
    "isFund": False,
    "name": "Common Stock",
    "exchange": "NASDAQ",
    "provider": "ALPACA_SIP",
    "provider_native_timestamp": "2026-09-10T14:30:00Z",
}


def test_sip_gainers_are_derived_from_canonical_price_and_previous_close() -> None:
    rows = [
        {**BASE_ROW, "symbol": "AAA", "price": 110.0, "previous_close": 100.0, "volume": 1_000_000},
        {**BASE_ROW, "symbol": "BBB", "price": 105.0, "previous_close": 100.0, "volume": 2_000_000},
        {**BASE_ROW, "symbol": "BAD", "price": 140.0, "previous_close": 100.0, "volume": 2_000_000, "provider_native_timestamp": None},
    ]
    result = derive_alpaca_sip_market_discovery_v1(rows, mode="biggest_gainers", limit=10)
    assert result["status"] == "READY"
    assert [row["symbol"] for row in result["rows"]] == ["AAA", "BBB"]
    assert result["rows"][0]["change_percent"] == 10.0
    assert result["rows"][0]["provider_native_timestamp"] == BASE_ROW["provider_native_timestamp"]
    assert result["executable_evidence"] is False
    assert result["candidate_evidence_fabricated"] is False


def test_sip_most_actives_use_existing_volume_or_trade_activity() -> None:
    rows = [
        {**BASE_ROW, "symbol": "AAA", "price": 10.0, "volume": 1_000_000},
        {**BASE_ROW, "symbol": "BBB", "price": 10.0, "volume": 2_000_000},
        {**BASE_ROW, "symbol": "CCC", "price": 10.0, "trade_count": 3_000},
    ]
    result = derive_alpaca_sip_market_discovery_v1(rows, mode="most_actives", limit=10)
    assert result["status"] == "READY"
    assert [row["symbol"] for row in result["rows"]] == ["BBB", "AAA", "CCC"]
    assert result["rows"][0]["discovery_source"] == "alpaca_sip_derived_most_actives"


def test_reference_universe_reuses_existing_liquid_common_stock_filter() -> None:
    rows = [
        {**BASE_ROW, "symbol": "AAA", "provider": "ALPACA_REFERENCE", "market_cap": 2_000_000_000, "last_price": 20.0, "session_volume": 1_000_000},
        {**BASE_ROW, "symbol": "ETF", "provider": "ALPACA_REFERENCE", "market_cap": 2_000_000_000, "last_price": 20.0, "session_volume": 1_000_000, "is_etf": True},
        {**BASE_ROW, "symbol": "THIN", "provider": "ALPACA_REFERENCE", "market_cap": 2_000_000_000, "last_price": 20.0, "session_volume": 10},
    ]
    result = build_alpaca_reference_universe_v1(rows)
    assert result["symbols"] == ["AAA"]
    assert result["provider"] == "ALPACA_REFERENCE"
    assert result["candidate_evidence_fabricated"] is False
