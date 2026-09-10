from __future__ import annotations

from engine.provider_router import ProviderRouter
from engine.sec_edgar_fundamentals_v1 import (
    BETA_CONTRACT_V1,
    SEC_DATA_BASE_URL,
    build_sec_company_context,
    derive_market_cap_from_sec,
    normalize_sec_companyfacts,
    normalize_sec_submissions,
    select_sec_fact,
)


SUBMISSIONS = {
    "cik": "320193",
    "name": "Apple Inc.",
    "tickers": ["AAPL"],
    "exchanges": ["Nasdaq"],
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "entityType": "operating",
}

FACTS = {
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [{
                        "end": "2026-08-01",
                        "filed": "2026-08-02",
                        "val": 1_000_000,
                        "form": "10-Q",
                        "accn": "0000000000-26-000001",
                    }],
                },
            },
        },
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [{
                        "start": "2026-01-01",
                        "end": "2026-06-30",
                        "end": "2026-06-30",
                        "filed": "2026-08-02",
                        "fy": 2026,
                        "fp": "Q2",
                        "form": "10-Q",
                        "val": 10_000_000,
                    }],
                },
            },
            "Assets": {
                "units": {
                    "USD": [{
                        "end": "2026-06-30",
                        "filed": "2026-08-02",
                        "form": "10-Q",
                        "val": 20_000_000,
                    }],
                },
            },
        },
    },
}


def test_submissions_normalization_preserves_identity_and_sic_provenance() -> None:
    result = normalize_sec_submissions(SUBMISSIONS, symbol="aapl", retrieved_at="2026-09-10T12:00:00Z")
    assert result["response_state"] == "SUCCESS"
    assert result["cik"] == "0000320193"
    assert result["normalized_fields"]["company_name"] == "Apple Inc."
    assert result["normalized_fields"]["sic_description"] == "Electronic Computers"
    assert result["filing_provenance"]["source_url_family"] == "data.sec.gov/submissions"


def test_companyfacts_keep_period_rows_and_provider_provenance() -> None:
    result = normalize_sec_companyfacts(FACTS, symbol="AAPL", cik="320193", retrieved_at="2026-09-10T12:00:00Z")
    assert result["response_state"] == "SUCCESS"
    revenue = result["facts_by_field"]["revenue"][0]
    assert revenue["period_kind"] == "duration"
    assert revenue["fiscal_period"] == "Q2"
    assert revenue["provenance"]["provider"] == "SEC_EDGAR"
    assert result["facts_by_field"]["assets"][0]["period_kind"] == "instant"


def test_fact_selection_does_not_flatten_conflicting_latest_values() -> None:
    records = [
        {"value": 10, "filed": "2026-08-02", "end": "2026-06-30", "period_kind": "instant"},
        {"value": 11, "filed": "2026-08-02", "end": "2026-06-30", "period_kind": "instant"},
    ]
    assert select_sec_fact(records, period_kind="instant") is None


def test_market_cap_requires_aligned_source_dates_and_is_advisory_only() -> None:
    shares_fact = {"value": 1_000_000, "end": "2026-08-01", "filed": "2026-08-02"}
    quote = {"price": 100.0, "provider_native_timestamp": "2026-08-01T12:00:00Z", "symbol": "AAPL"}
    result = derive_market_cap_from_sec(shares_fact, quote)
    assert result["state"] == "DERIVED"
    assert result["market_cap"] == 100_000_000
    assert result["execution_authority"] == "DISABLED"
    assert result["use_for_entry_eligibility"] is False


def test_beta_contract_is_explicitly_advisory() -> None:
    assert BETA_CONTRACT_V1["benchmark"] == "SPY"
    assert BETA_CONTRACT_V1["minimum_observations"] == 60
    assert BETA_CONTRACT_V1["authority"] == "ASTRA_DERIVED_ADVISORY_ONLY"


def test_provider_router_exposes_opt_in_sec_context_without_changing_quote_routing(monkeypatch) -> None:
    monkeypatch.setenv("ASTRA_SEC_USER_AGENT", "Astra test contact@example.com")
    router = ProviderRouter()

    def fake_request(provider: str, url: str, **_kwargs):
        assert provider == "SEC_EDGAR"
        if url.endswith(".json") and "/submissions/" in url:
            return SUBMISSIONS, 200, "", 1.0
        assert url == f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK0000320193.json"
        return FACTS, 200, "", 1.0

    router._request = fake_request  # type: ignore[method-assign]
    result = router.fetch_sec_company_context("AAPL", cik="320193")
    assert result["provider"] == "SEC_EDGAR"
    assert result["response_state"] == "SUCCESS"
    assert result["normalized_fields"]["company_name"] == "Apple Inc."


def test_sec_context_requires_identification_header(monkeypatch) -> None:
    monkeypatch.delenv("ASTRA_SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    router = ProviderRouter()
    result = router.fetch_sec_company_context("AAPL", cik="320193")
    assert result["response_state"] == "CONFIGURATION_REQUIRED"
    assert result["secret_exposed"] is False


def test_sec_context_rejects_cik_for_a_different_symbol(monkeypatch) -> None:
    monkeypatch.setenv("ASTRA_SEC_USER_AGENT", "Astra test contact@example.com")
    router = ProviderRouter()

    def fake_request(_provider: str, url: str, **_kwargs):
        if "/submissions/" in url:
            return SUBMISSIONS, 200, "", 1.0
        return FACTS, 200, "", 1.0

    router._request = fake_request  # type: ignore[method-assign]
    result = router.fetch_sec_company_context("MSFT", cik="320193")
    assert result["response_state"] == "MALFORMED_RESPONSE"
    assert result["reason"] == "sec_symbol_mismatch"


def test_combined_context_marks_partial_when_facts_are_missing() -> None:
    result = build_sec_company_context(SUBMISSIONS, {}, symbol="AAPL", cik="320193")
    assert result["response_state"] == "PARTIAL"
    assert result["normalized_fields"]["company_name"] == "Apple Inc."
