import json
import time
from datetime import datetime, timedelta, timezone

from engine.astra_canonical_lane_evidence_v1 import build_lane_evidence_v1
from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1


NOW = datetime(2026, 9, 18, 18, 0, 0, tzinfo=timezone.utc)


def _quote(**overrides):
    row = {
        "symbol": "TEST",
        "price": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "provider": "ALPACA_SIP",
        "provider_native_timestamp": "2026-09-18T17:59:55Z",
        "quote_age_seconds": 5.0,
        "freshness_state": "CURRENT",
        "execution_freshness_state": "CURRENT",
    }
    row.update(overrides)
    return row


def _bars(count, *, timeframe="15Min", start_hour=17, start_at=None):
    bars = []
    for index in range(count):
        if timeframe == "1Day":
            stamp = (datetime(2026, 8, 25, 20, tzinfo=timezone.utc) + timedelta(days=index)).isoformat().replace("+00:00", "Z")
        else:
            base = start_at or datetime(2026, 9, 18, start_hour, 0, tzinfo=timezone.utc)
            step_minutes = 15 if timeframe.lower() in {"15min", "15m"} else 60
            stamp = (base + timedelta(minutes=step_minutes * index)).isoformat().replace("+00:00", "Z")
        close = 100.0 + index * 0.25
        bars.append({
            "provider_native_timestamp": stamp,
            "open": close - 0.05,
            "high": close + 0.10,
            "low": close - 0.10,
            "close": close,
            "volume": 1000.0 + index,
            "is_complete": True,
        })
    return {"resolution": timeframe, "completed_bars": bars}


def test_scalp_contract_derives_spread_freshness_and_fit_from_real_inputs():
    row = _quote(
        liquidity_score=82,
        relative_volume_score=76,
        intraday_acceleration_score=74,
        momentum_expansion_score=71,
        bar_evidence=_bars(4, start_hour=17),
    )
    result = build_lane_evidence_v1(row, now=NOW)
    derived = result["derived_evidence"]

    assert derived["spread_quality_state"] == "ACCEPTABLE"
    assert derived["spread_quality_score"] == 100.0
    assert derived["freshness_quality_score"] == 75.0
    assert derived["scalp_fit_score"] > 0
    assert derived["scalp_horizon_evidence_v1"]["horizon"] == "SCALP"
    assert result["sufficiency"]["SCALP"]["state"] == "COMPLETE"
    assert result["authority_class"] == "PRETRADE_CANONICAL_EVIDENCE"
    assert result["observation_authority"] is False
    assert result["executable_evidence"] is False
    assert result["provenance"]["spread_quality_score"]["source_timestamp"]


def test_scalp_invalid_quote_or_timestamp_fails_closed():
    missing_quote = build_lane_evidence_v1(_quote(bid=None), now=NOW)
    assert "spread_quality_score" in missing_quote["sufficiency"]["SCALP"]["missing_fields"]
    assert "scalp_fit_score" not in missing_quote["derived_evidence"]

    stale = build_lane_evidence_v1(
        _quote(provider_native_timestamp="2026-09-18T17:50:00Z", bar_evidence=_bars(4, start_hour=14)),
        now=NOW,
    )
    assert "freshness_quality_score" in stale["sufficiency"]["SCALP"]["missing_fields"]
    assert "scalp_fit_score" not in stale["derived_evidence"]


def test_swing_contract_uses_completed_daily_structure_and_volatility_percentile():
    row = _quote(
        symbol="TREND",
        market_regime="TRENDING",
        sector="technology",
        bar_evidence=_bars(20, timeframe="1Day", start_hour=0),
    )
    result = build_lane_evidence_v1(row, now=datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc))
    derived = result["derived_evidence"]

    assert derived["multi_day_structure_v1"]["no_future_bars"] is True
    assert derived["trend_persistence_score"] > 0
    assert derived["trend_quality_score"] > 0
    assert 0 <= derived["volatility_score"] <= 100
    assert derived["swing_fit_score"] > 0
    assert derived["swing_horizon_evidence_v1"]["horizon"] == "SWING"
    assert result["sufficiency"]["SWING"]["state"] == "COMPLETE"


def test_swing_future_or_incomplete_bar_does_not_produce_structure():
    evidence = _bars(20, timeframe="1Day", start_hour=0)
    evidence["completed_bars"][-1]["is_complete"] = False
    result = build_lane_evidence_v1(
        _quote(market_regime="TRENDING", sector="technology", bar_evidence=evidence),
        now=datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc),
    )
    assert "multi_day_structure_v1" not in result["derived_evidence"]
    assert "swing_fit_score" not in result["derived_evidence"]


def test_allocator_joins_canonical_evidence_without_execution_authority(tmp_path):
    live_now = datetime.now(timezone.utc)
    live_quote = (live_now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    runtime = {
        "equity_risk_envelopes_snapshot_v1": {
            "valid_until_epoch": time.time() + 600,
            "rows": [{
                "symbol": "TEST",
                "quote_execution_eligible": True,
                "atr_pct": 1.2,
                "completed_bar_timestamp": "2026-09-18T17:45:00Z",
                "bar_evidence": _bars(4, start_at=live_now - timedelta(minutes=60)),
            }],
        }
    }
    (tmp_path / "paper_autopilot_state.json").write_text(json.dumps(runtime))
    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))
    enriched = allocator.enrich_broad_observation_features_v1(_quote(
        provider_native_timestamp=live_quote,
        liquidity_score=82,
        relative_volume_score=76,
        intraday_acceleration_score=74,
        momentum_expansion_score=71,
    ))

    assert enriched["spread_quality_score"] == 100.0
    assert 74.0 < enriched["freshness_quality_score"] <= 75.0
    assert enriched["scalp_fit_score"] > 0
    assert enriched["observation_authority"] is False
    assert enriched["executable_evidence"] is False
    assert enriched["candidate_evidence_fabricated"] is False
