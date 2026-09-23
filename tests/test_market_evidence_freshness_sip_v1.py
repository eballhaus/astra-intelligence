from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.astra_canonical_lane_evidence_v1 import build_lane_evidence_v1
from engine.provider_router import ProviderRouter


def _quote_timestamp(seconds_ago: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _bars(count: int, *, interval_minutes: int, latest_start: datetime) -> list[dict]:
    return [
        {
            "provider_native_timestamp": (latest_start - timedelta(minutes=interval_minutes * (count - index - 1))).isoformat().replace("+00:00", "Z"),
            "open": 99.0 + index,
            "high": 100.0 + index,
            "low": 98.0 + index,
            "close": 99.5 + index,
            "volume": 1000 + index,
            "is_complete": True,
        }
        for index in range(count)
    ]


def test_paper_broker_latest_quote_supports_explicit_sip_read_only_fallback():
    broker = AlpacaPaperBroker()
    paths = []

    def request(path):
        paths.append(path)
        return True, {"quote": {"bp": 100.0, "ap": 100.1, "t": _quote_timestamp()}}, "", 200

    broker._market_data_request = request  # type: ignore[method-assign]
    result = broker.latest_quote("AAPL", feed="sip")

    assert result["response_state"] == "SUCCESS"
    assert result["feed"] == "sip"
    assert "feed=sip" in paths[0]
    assert result["broker_actions"] == 0


def test_provider_router_uses_verified_sip_for_single_quote_and_preserves_provenance():
    router = ProviderRouter()
    router._key_for = lambda *_args: "key"  # type: ignore[method-assign]
    captured = {}

    def request(_provider, _url, *, params=None, headers=None):
        captured.update(params or {})
        return {"quote": {"bp": 100.0, "ap": 100.1, "t": _quote_timestamp()}}, 200, "", 1.0

    router._request = request  # type: ignore[method-assign]
    with patch.dict("os.environ", {"ASTRA_ALPACA_SIP_ENTITLEMENT_VERIFIED": "1"}, clear=False):
        result = router._fetch_quote_from_provider("ALPACA", "AAPL", "stock")

    assert captured["feed"] == "sip"
    assert result["feed"] == "sip"
    assert result["quote_source"] == "ALPACA_SIP_MARKET_DATA"


def test_unverified_sip_keeps_existing_iex_fallback():
    router = ProviderRouter()
    router._key_for = lambda *_args: "key"  # type: ignore[method-assign]
    captured = {}

    def request(_provider, _url, *, params=None, headers=None):
        captured.update(params or {})
        return {"quote": {"bp": 100.0, "ap": 100.1, "t": _quote_timestamp()}}, 200, "", 1.0

    router._request = request  # type: ignore[method-assign]
    with patch.dict("os.environ", {"ASTRA_ALPACA_SIP_ENTITLEMENT_VERIFIED": "0"}, clear=False):
        result = router._fetch_quote_from_provider("ALPACA", "AAPL", "stock")

    assert captured["feed"] == "iex"
    assert result["feed"] == "iex"
    assert result["quote_source"] == "ALPACA_IEX_MARKET_DATA"


def test_completed_15m_and_1h_bars_use_interval_aware_freshness():
    now = datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc)
    base = {
        "symbol": "AAPL",
        "price": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "provider_native_timestamp": "2026-09-23T15:29:55Z",
        "liquidity_score": 90,
        "relative_volume_score": 90,
        "intraday_acceleration_score": 90,
        "momentum_expansion_score": 90,
        "market_regime": "TRENDING",
        "sector": "technology",
    }
    fifteen = dict(base)
    fifteen["bar_evidence"] = {"resolution": "15Min", "completed_bars": _bars(4, interval_minutes=15, latest_start=datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc))}
    assert "scalp_intraday_structure_v1" in build_lane_evidence_v1(fifteen, now=now)["derived_evidence"]

    hour = dict(base)
    hour["swing_bar_evidence"] = {"resolution": "1Hour", "completed_bars": _bars(20, interval_minutes=60, latest_start=datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc))}
    assert "multi_day_structure_v1" in build_lane_evidence_v1(hour, now=now)["derived_evidence"]


def test_old_completed_bars_and_unfinished_bars_fail_closed():
    now = datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc)
    row = {
        "symbol": "AAPL",
        "price": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "provider_native_timestamp": "2026-09-23T15:29:55Z",
        "liquidity_score": 90,
        "relative_volume_score": 90,
        "intraday_acceleration_score": 90,
        "momentum_expansion_score": 90,
        "bar_evidence": {"resolution": "15Min", "completed_bars": _bars(4, interval_minutes=15, latest_start=datetime(2026, 9, 23, 13, 0, tzinfo=timezone.utc))},
    }
    stale = build_lane_evidence_v1(row, now=now)
    assert "scalp_intraday_structure_v1" not in stale["derived_evidence"]
    row["bar_evidence"]["completed_bars"][-1]["is_complete"] = False
    unfinished = build_lane_evidence_v1(row, now=now)
    assert "scalp_intraday_structure_v1" not in unfinished["derived_evidence"]
