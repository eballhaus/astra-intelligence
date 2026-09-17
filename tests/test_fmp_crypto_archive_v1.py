from pathlib import Path

from scripts.fmp_crypto_archive_v1 import build_crypto_manifest


def _state(tmp_path: Path) -> Path:
    (tmp_path / "alpaca_crypto_capability_v2.json").write_text(
        '{"supported_pairs":["ETH/USD","SHIB/USD","BTC/USD","BTC/USDC"],"tradable_pairs":["ETH/USD","SHIB/USD","BTC/USD"]}',
        encoding="utf-8",
    )
    (tmp_path / "astra_crypto_market_data_capability_matrix_v1.json").write_text(
        '{"pairs":[{"symbol":"BTC/USD"},{"symbol":"ETH/USD"}]}',
        encoding="utf-8",
    )
    return tmp_path


def test_manifest_uses_existing_supported_tradable_usd_pairs_and_required_pairs(tmp_path):
    manifest = build_crypto_manifest(_state(tmp_path), "1Hour")

    assert [row["canonical_pair"] for row in manifest] == ["BTC/USD", "ETH/USD", "SHIB/USD"]
    assert all(row["asset_type"] == "crypto" for row in manifest)
    assert all(row["horizon_attribution"] == "UNRESOLVED_HISTORICAL_CRYPTO" for row in manifest)
    assert all(row["historical_replay_only"] is True and row["natural_truth_eligible"] is False for row in manifest)


def test_focused_manifest_is_bounded_but_retains_required_pairs(tmp_path):
    manifest = build_crypto_manifest(_state(tmp_path), "1Min")

    assert len(manifest) <= 4
    assert {row["canonical_pair"] for row in manifest} == {"ETH/USD", "SHIB/USD", "BTC/USD"}
    btc = next(row for row in manifest if row["canonical_pair"] == "BTC/USD")
    assert btc["provider_alias_candidates"] == ["BTCUSD", "BTC/USD", "BTC-USD"]


def test_ambiguous_cross_quote_pair_is_not_admitted(tmp_path):
    state = _state(tmp_path)
    (state / "alpaca_crypto_capability_v2.json").write_text(
        '{"supported_pairs":["ETH/USD","SHIB/USD","ETH/USDC"],"tradable_pairs":["ETH/USD","SHIB/USD","ETH/USDC"]}',
        encoding="utf-8",
    )
    manifest = build_crypto_manifest(state, "1Day")

    assert all(row["canonical_pair"].endswith("/USD") for row in manifest)
