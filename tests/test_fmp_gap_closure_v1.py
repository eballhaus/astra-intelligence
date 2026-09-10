from __future__ import annotations

import tempfile
import time

from engine.broad_universe_intake_promotion_v1 import BroadUniverseIntakePromotionV1
from engine.astra_legacy_position_risk_triage_v1 import triage_legacy_position_v1
from engine.astra_unified_position_lifecycle_v1 import build_legacy_swing_required_evidence_v1
from engine.paper_autopilot import PaperAutopilotEngine
from engine.provider_router import ProviderRouter


def _router_with_response(payload):
    router = ProviderRouter()
    router._key_for = lambda provider, _asset: "fixture-key" if provider == "FINNHUB" else ""  # type: ignore[method-assign]
    router._request = lambda *_args, **_kwargs: (payload, 200, "", 2.5)  # type: ignore[method-assign]
    return router


def _registry():
    return {
        "activation-a": {
            "activation_id": "activation-a",
            "baseline_id": "legacy-forward:asset-a",
            "position_id": "asset-a",
            "symbol": "AAA",
            "legacy_activation_timestamp": "2026-07-15T12:00:00Z",
            "activation_price": 10,
        }
    }


def test_finnhub_news_context_preserves_timestamp_and_provenance():
    router = _router_with_response({
        "_list": [{
            "id": 123,
            "headline": "Fixture headline",
            "summary": "Fixture summary",
            "datetime": 1789050000,
            "source": "Fixture Wire",
            "related": "AAA",
            "url": "https://example.test/news/123",
        }]
    })

    result = router.fetch_finnhub_news_context("AAA")

    assert result["response_state"] == "SUCCESS"
    assert result["provider"] == "FINNHUB"
    assert result["normalized_fields"]["published_timestamp"] == 1789050000
    assert result["normalized_fields"]["published_at"].endswith("Z")
    assert result["normalized_fields"]["url"].endswith("/123")
    assert result["secret_exposed"] is False


def test_finnhub_earnings_context_normalizes_calendar_and_history():
    router = _router_with_response({
        "earningsCalendar": [
            {"symbol": "AAA", "date": "2026-08-01", "epsActual": 1.1, "epsEstimate": 1.0, "revenueActual": 10},
            {"symbol": "AAA", "date": "2026-11-01", "epsEstimate": 1.3, "revenueEstimate": 12},
        ]
    })

    result = router.fetch_finnhub_earnings_context("AAA")

    assert result["response_state"] == "SUCCESS"
    fields = result["normalized_fields"]
    assert fields["next_earnings_date"] == "2026-11-01"
    assert fields["previous_earnings_date"] == "2026-08-01"
    assert fields["earnings_history"]
    assert fields["eps_estimate"] == 1.3


def test_finnhub_context_fails_closed_without_native_news_timestamp():
    router = _router_with_response({"_list": [{"headline": "No timestamp"}]})

    result = router.fetch_finnhub_news_context("AAA")

    assert result["response_state"] == "MALFORMED_RESPONSE"
    assert result["normalized_fields"] == {}


def test_sec_profile_context_wins_over_fmp_fallback_in_legacy_refresh():
    engine = object.__new__(PaperAutopilotEngine)
    engine._runtime_state = {}
    fmp_calls = []

    def sec_fetcher(symbol):
        return {
            "provider": "SEC_EDGAR",
            "endpoint_family": "company_profile",
            "symbol": symbol,
            "response_state": "PARTIAL",
            "response_at": "2026-09-10T14:00:00Z",
            "normalized_fields": {"company_name": "Fixture Co", "sic": "7372"},
        }

    def fmp_fetcher(symbol):
        fmp_calls.append(symbol)
        raise AssertionError("FMP should be fallback only when SEC context is unavailable")

    engine._legacy_swing_sec_fetcher = sec_fetcher
    engine._legacy_swing_fmp_fetcher = fmp_fetcher
    records, _activity = engine._refresh_legacy_swing_fmp_evidence(_registry())

    assert fmp_calls == []
    assert records["activation-a"]["provider"] == "SEC_EDGAR"
    assert records["activation-a"]["freshness_state"] == "CURRENT"


def test_sec_profile_context_reaches_existing_advisory_consumers_without_fmp_label():
    context = {
        "provider": "SEC_EDGAR",
        "record_id": "SEC:0001:AAA",
        "endpoint_family": "company_profile",
        "response_state": "PARTIAL",
        "normalized_fields": {"company_name": "Fixture Co", "sic": "7372"},
    }
    evidence = build_legacy_swing_required_evidence_v1(
        {"symbol": "AAA", "current_price": 10, "fmp_thesis_context": context},
        {"baseline_id": "baseline-a", "activation_price": 10},
    )
    assert evidence["THESIS_STATE"]["source"] == "SEC_EDGAR.company_profile"
    triage = triage_legacy_position_v1({"symbol": "AAA"}, fmp_context=context, evidence={"momentum_status": "CURRENT"})
    assert triage["provider_sources"] == ["SEC_EDGAR"]
    assert "SEC_EDGAR_CONTEXT_UNAVAILABLE" not in triage["evidence_missing"]


def test_finnhub_event_context_is_used_before_fmp_fallback():
    engine = object.__new__(PaperAutopilotEngine)
    engine._runtime_state = {"legacy_swing_fmp_activity": {"event_rotation_cursor": 1}}
    engine._legacy_swing_sec_fetcher = lambda _symbol: {"response_state": "AUTHENTICATION_FAILED"}
    engine._legacy_swing_fmp_fetcher = lambda _symbol: {
        "provider": "FMP", "response_state": "SUCCESS", "response_at": "2026-09-10T14:00:00Z",
        "normalized_fields": {"company_name": "Fixture Co"},
    }

    class Router:
        def fetch_finnhub_news_context(self, symbol):
            return {
                "provider": "FINNHUB", "response_state": "SUCCESS", "response_at": "2026-09-10T14:00:00Z",
                "normalized_fields": {"headline": f"News for {symbol}"},
            }

        def fetch_fmp_news_context(self, _symbol):
            raise AssertionError("FMP should not be called when Finnhub succeeds")

    engine._legacy_swing_fmp_router = Router()
    records, _activity = engine._refresh_legacy_swing_fmp_evidence(_registry())

    event = records["activation-a"]["auxiliary_context"]["news_catalyst"]
    assert event["provider"] == "FINNHUB"
    assert event["normalized_fields"]["headline"] == "News for AAA"


def test_future_sip_mover_wiring_reuses_broad_discovery_owner_without_calls():
    now = time.time()
    rows = [
        {
            "symbol": "AAA",
            "provider": "ALPACA_SIP",
            "provider_native_timestamp": now,
            "price": 110.0,
            "previous_close": 100.0,
            "volume": 1_000_000,
            "isActivelyTrading": True,
            "isEtf": False,
            "isFund": False,
            "name": "Common Stock",
            "exchange": "NASDAQ",
        }
    ]
    with tempfile.TemporaryDirectory() as state_dir:
        owner = BroadUniverseIntakePromotionV1(state_dir=state_dir)
        owner._provider_router = None
        result = owner.market_discovery_from_canonical_rows_v1(rows, now_timestamp=now)

    assert result["provider"] == "ALPACA_SIP"
    assert result["rows"][0]["symbol"] == "AAA"
    assert result["executable_evidence"] is False
    assert result["candidate_evidence_fabricated"] is False
