import gzip

from scripts.fmp_archive_enrichment_v1 import (
    ETF_CATEGORIES,
    ETF_SYMBOLS,
    build_enrichment_manifest,
    normalize_identity_record,
    restore_manifest_verification,
    verified_etf_profile,
)
from scripts.fmp_weekend_archive_v1 import normalize_rows


def test_enrichment_universe_is_bounded_and_categorized():
    manifest = build_enrichment_manifest()
    assert 25 <= len(manifest) <= 50
    assert {"SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "TLT", "GLD"} <= set(ETF_SYMBOLS)
    assert len(ETF_CATEGORIES) == len(ETF_SYMBOLS)
    assert all(row["instrument_type"] == "ETF" for row in manifest)


def test_etf_verification_requires_explicit_provider_flag():
    assert verified_etf_profile({"symbol": "SPY", "isEtf": True}) is True
    assert verified_etf_profile({"symbol": "SPY", "name": "SPDR S&P 500 ETF"}) is False
    assert verified_etf_profile({"symbol": "SPY", "isEtf": False}) is False


def test_symbol_change_preserves_original_and_new_identity_with_provenance():
    row = normalize_identity_record(
        {"oldSymbol": "OLD", "newSymbol": "NEW", "date": "2020-01-02", "companyName": "Example Co"},
        "SYMBOL_CHANGE",
        "2026-09-12T00:00:00Z",
    )
    assert row["old_symbol"] == "OLD"
    assert row["new_symbol"] == "NEW"
    assert row["effective_date"] == "2020-01-02"
    assert row["ambiguity_state"] == "VALIDATED"
    assert row["source"] == "FMP"
    assert row["retrieved_at"] == "2026-09-12T00:00:00Z"


def test_ambiguous_symbol_change_is_retained_as_ambiguous_not_rewritten():
    row = normalize_identity_record({"oldSymbol": "OLD", "date": "2020-01-02"}, "SYMBOL_CHANGE", "now")
    assert row["new_symbol"] == ""
    assert row["ambiguity_state"] == "AMBIGUOUS"
    assert row["confidence"] == "LOW"


def test_identity_id_is_stable_across_retrievals_for_resume_idempotency():
    first = normalize_identity_record(
        {"oldSymbol": "OLD", "newSymbol": "NEW", "date": "2020-01-02"},
        "SYMBOL_CHANGE",
        "2026-09-12T00:00:00Z",
    )
    second = normalize_identity_record(
        {"oldSymbol": "OLD", "newSymbol": "NEW", "date": "2020-01-02"},
        "SYMBOL_CHANGE",
        "2026-09-13T00:00:00Z",
    )
    assert first["continuity_id"] == second["continuity_id"]


def test_delisting_is_inactive_status_without_a_new_symbol():
    row = normalize_identity_record(
        {"symbol": "OLD", "delistedDate": "2021-03-04", "reason": "acquired"},
        "DELISTING",
        "now",
    )
    assert row["old_symbol"] == "OLD"
    assert row["new_symbol"] == ""
    assert row["active_status"] == "INACTIVE"
    assert row["ambiguity_state"] == "VALIDATED"


def test_global_identity_response_shapes_are_normalized_without_symbol_rewrite():
    assert normalize_rows({"symbolChanges": [{"oldSymbol": "A", "newSymbol": "B"}]})[0]["oldSymbol"] == "A"
    assert normalize_rows({"delistedCompanies": [{"symbol": "OLD"}]})[0]["symbol"] == "OLD"


def test_resume_restores_verified_etf_flags_from_profile_context(tmp_path):
    manifest = build_enrichment_manifest()[:1]
    context = tmp_path / "context.jsonl.gz"
    with gzip.open(context, "wt", encoding="utf-8") as handle:
        handle.write('{"family":"etf_profile","symbol":"SPY","record":{"symbol":"SPY","isEtf":true}}\n')
    restore_manifest_verification(manifest, context)
    assert manifest[0]["verified_is_etf"] is True
    assert manifest[0]["profile_status"] == "VERIFIED_ETF"
