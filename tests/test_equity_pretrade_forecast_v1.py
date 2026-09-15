from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
import time

from engine.astra_premarket_certification_v1 import (
    build_pretrade_decision_contract,
    derive_equity_pretrade_forecast_v1,
    enrich_candidate_for_pretrade_contract,
)


NOW = datetime(2026, 9, 15, 17, 45, tzinfo=timezone.utc)


def _bars(now: datetime = NOW, *, rising: bool = True, age_minutes: int = 0) -> list[dict]:
    start = now - timedelta(minutes=135 + age_minutes)
    rows = []
    for index in range(8):
        close = 100.0 + (index * 0.2 if rising else -index * 0.2)
        timestamp = (start + timedelta(minutes=index * 15)).isoformat().replace("+00:00", "Z")
        rows.append({
            "provider_native_timestamp": timestamp,
            "open": close - 0.05,
            "high": close + 0.15,
            "low": close - 0.15,
            "close": close,
            "volume": 100_000 + index,
            "is_complete": True,
        })
    return rows


def _candidate(now: datetime = NOW, **overrides) -> dict:
    quote_time = (now - timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
    row = {
        "symbol": "HWM",
        "candidate_id": "cand-hwm-day",
        "recommendation_id": "rec-hwm-day",
        "decision_id": "decision-hwm-day",
        "asset_class": "equity",
        "asset_type": "stock",
        "lane_id": "DAY",
        "paper_entry_horizon_style": "day_trade",
        "expected_hold_minutes": 120,
        "strategy_archetype": "momentum_continuation",
        "trade_style": "day_trade",
        "ranking_score": 89.42,
        "qualification_score": 71.73,
        "confidence": 78.0,
        "setup_type": "momentum_continuation",
        "summary": "Current completed-bar continuation is positive.",
        "thesis": "Current provider-backed continuation remains positive.",
        "thesis_supporting_conditions": ["positive completed-bar trend"],
        "thesis_invalidation_conditions": ["continuation reverses"],
        "price": 102.0,
        "bid": 101.99,
        "ask": 102.01,
        "provider_quote_timestamp": quote_time,
        "quote_timestamp": quote_time,
        "quote_timestamp_origin": "provider",
        "freshness_state": "CURRENT",
        "atr_pct": 0.35,
        "risk_evidence_valid_until": (now + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
        "equity_risk_evidence_join_v1": {
            "status": "CURRENT_SYMBOL_MATCHED", "symbol": "HWM",
            "owner": "worker_only_equity_risk_observer",
        },
        "bar_evidence": {
            "source": "AlpacaPaperBroker.historical_bars",
            "provider": "ALPACA_PAPER_BROKER",
            "evidence_class": "CURRENT_PROVIDER_BAR",
            "resolution": "15Min",
            "count": 8,
            "bar_window_start": _bars(now)[0]["provider_native_timestamp"],
            "bar_window_end": _bars(now)[-1]["provider_native_timestamp"],
            "completed_bars": _bars(now),
        },
        "expires_at": (now + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
    }
    row.update(overrides)
    return row


class EquityPretradeForecastV1Tests(unittest.TestCase):
    def test_fresh_day_bars_produce_traceable_upside_and_valid_existing_contract(self):
        row = enrich_candidate_for_pretrade_contract(_candidate(), now=NOW)
        forecast = row["equity_pretrade_forecast_v1"]
        self.assertEqual(forecast["forecast_state"], "FORECAST_COMPLETE")
        self.assertGreater(forecast["expected_return_range"]["low_pct"], 0.0)
        self.assertEqual(forecast["source_provenance"]["source_provider"], "ALPACA_PAPER_BROKER")
        self.assertFalse(forecast["source_provenance"]["future_data_used"])
        self.assertEqual(forecast["source_provenance"]["completed_bar_timestamps"], [bar["provider_native_timestamp"] for bar in _bars()])

        inputs = forecast["source_inputs"]
        low = inputs["drift_per_bar_pct"] * inputs["remaining_session_intervals"]
        high = low + inputs["mean_bar_range_pct"] * inputs["remaining_session_intervals"] ** 0.5
        self.assertAlmostEqual(forecast["expected_return_range"]["low_pct"], low, places=5)
        self.assertAlmostEqual(forecast["expected_return_range"]["high_pct"], high, places=5)
        self.assertAlmostEqual(forecast["expected_target_low"], 102.0 * (1.0 + low / 100.0), places=6)
        self.assertAlmostEqual(forecast["expected_target_high"], 102.0 * (1.0 + high / 100.0), places=6)

        risk = row["candidate_risk_envelope_v1"]
        self.assertEqual(risk["risk_envelope_state"], "RISK_ENVELOPE_COMPLETE")
        self.assertEqual(
            risk["field_provenance_v1"]["expected_upside_range"]["source_system"],
            "engine.astra_premarket_certification_v1.derive_equity_pretrade_forecast_v1",
        )
        self.assertNotEqual(
            risk["field_provenance_v1"]["expected_downside_range"]["source_system"],
            "engine.astra_premarket_certification_v1.derive_equity_pretrade_forecast_v1",
        )
        contract = build_pretrade_decision_contract(row, now=NOW)
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertTrue(contract["order_ready_allowed"])
        self.assertAlmostEqual(contract["expected_return_range"]["low_pct"], forecast["expected_return_range"]["low_pct"], places=4)
        self.assertAlmostEqual(contract["expected_return_range"]["high_pct"], forecast["expected_return_range"]["high_pct"], places=4)

    def test_nonpositive_continuation_remains_fail_closed(self):
        row = _candidate()
        row["bar_evidence"]["completed_bars"] = _bars(rising=False)
        forecast = derive_equity_pretrade_forecast_v1(row, now=NOW)
        self.assertEqual(forecast["forecast_state"], "INSUFFICIENT_FORECAST_EVIDENCE")
        self.assertIn("POSITIVE_NONCONTRADICTORY_CONTINUATION_REQUIRED", forecast["missing_inputs"])
        enriched = enrich_candidate_for_pretrade_contract(row, now=NOW)
        self.assertNotIn("expected_return_range", enriched)
        self.assertFalse(build_pretrade_decision_contract(row, now=NOW)["order_ready_allowed"])

    def test_stale_quote_and_stale_bar_windows_are_rejected(self):
        stale_quote = _candidate(provider_quote_timestamp=(NOW - timedelta(minutes=6)).isoformat().replace("+00:00", "Z"))
        self.assertEqual(derive_equity_pretrade_forecast_v1(stale_quote, now=NOW)["forecast_state"], "STALE_FORECAST_EVIDENCE")

        stale_bars = _candidate()
        stale_bars["bar_evidence"]["completed_bars"] = _bars(age_minutes=45)
        self.assertEqual(derive_equity_pretrade_forecast_v1(stale_bars, now=NOW)["forecast_state"], "STALE_FORECAST_EVIDENCE")

    def test_future_and_unfinished_bars_are_rejected(self):
        future_bar = _candidate()
        future_bar["bar_evidence"]["completed_bars"][-1]["provider_native_timestamp"] = (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        self.assertEqual(derive_equity_pretrade_forecast_v1(future_bar, now=NOW)["forecast_state"], "CONFLICTING_FORECAST_EVIDENCE")

        unfinished_bar = _candidate()
        unfinished_bar["bar_evidence"]["completed_bars"][-1]["is_complete"] = False
        self.assertEqual(derive_equity_pretrade_forecast_v1(unfinished_bar, now=NOW)["forecast_state"], "INSUFFICIENT_FORECAST_EVIDENCE")

    def test_explainability_and_abstract_scores_cannot_create_forecast(self):
        row = {
            "symbol": "HWM", "lane_id": "DAY", "paper_entry_horizon_style": "day_trade",
            "ranking_score": 99.0, "confidence": 98.0, "grade": 97.0,
            "expected_value_score": 96.0, "expected_move": "Ollama says +4%",
            "projected_move": "strong upside", "ollama_expected_move": "+4%",
        }
        forecast = derive_equity_pretrade_forecast_v1(row, now=NOW)
        self.assertEqual(forecast["forecast_state"], "INSUFFICIENT_FORECAST_EVIDENCE")
        contract = build_pretrade_decision_contract({
            **row, "candidate_id": "cand-score", "recommendation_id": "rec-score",
            "expires_at": (NOW + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
        }, now=NOW)
        self.assertIn("expected_return_range", contract["missing_required_fields"])
        self.assertFalse(contract["order_ready_allowed"])

    def test_lane_horizon_ownership_and_crypto_are_unchanged(self):
        for lane, horizon in (("SCALP", "scalp"), ("SWING", "swing_trade")):
            row = _candidate(lane_id=lane, paper_entry_horizon_style=horizon)
            forecast = derive_equity_pretrade_forecast_v1(row, now=NOW)
            self.assertEqual(forecast["forecast_state"], "INSUFFICIENT_FORECAST_EVIDENCE")
            self.assertEqual(forecast["lane"], lane)
            self.assertEqual(forecast["horizon"], horizon)

        crypto_forecast = {
            "forecast_state": "FORECAST_COMPLETE", "schema_version": "1.0.0",
            "calculation_method": "existing_crypto_test", "forecast_timestamp": NOW.isoformat(),
            "source_inputs": {}, "source_provenance": {"source_system": "crypto_test", "evidence_class": "CURRENT_CANDIDATE_DIRECT"},
            "expected_return_range": {"low_pct": 0.5, "high_pct": 1.0},
            "expected_downside_range": {"low_pct": -1.0, "high_pct": -0.5},
            "expected_drawdown": {"low_pct": -2.0, "high_pct": -1.0},
        }
        crypto_row = enrich_candidate_for_pretrade_contract({
            "symbol": "ETH/USD", "candidate_id": "cand-eth", "recommendation_id": "rec-eth",
            "asset_class": "crypto", "asset_type": "crypto", "lane_id": "CRYPTO",
            "paper_entry_horizon_style": "day_trade", "crypto_pretrade_forecast_v1": crypto_forecast,
        }, now=NOW)
        self.assertNotIn("equity_pretrade_forecast_v1", crypto_row)
        self.assertEqual(crypto_row["expected_return_range"]["low_pct"], crypto_forecast["expected_return_range"]["low_pct"])
        self.assertEqual(crypto_row["expected_return_range"]["high_pct"], crypto_forecast["expected_return_range"]["high_pct"])

    def test_forecast_enrichment_is_read_only_and_has_no_broker_effects(self):
        row = _candidate()
        enriched = enrich_candidate_for_pretrade_contract(row, now=NOW)
        self.assertNotIn("equity_pretrade_forecast_v1", row)
        self.assertEqual(enriched["pretrade_enrichment_v1"]["provider_calls_used"], 0)
        self.assertEqual(enriched["pretrade_enrichment_v1"]["broker_actions_used"], 0)
        self.assertEqual(enriched["equity_pretrade_forecast_v1"]["source_provenance"]["source_system"], "engine.astra_premarket_certification_v1.derive_equity_pretrade_forecast_v1")

    def test_worker_snapshot_bars_reach_candidate_forecast_through_existing_join(self):
        from engine.paper_autopilot import PaperAutopilotEngine

        source = _candidate()
        evidence = {
            "symbol": "HWM",
            "quote_execution_eligible": True,
            "quote_timestamp": source["provider_quote_timestamp"],
            "completed_bar_timestamp": source["bar_evidence"]["bar_window_end"],
            "atr_pct": source["atr_pct"],
            "risk_evidence_generated_at": NOW.isoformat().replace("+00:00", "Z"),
            "risk_evidence_valid_until": (NOW + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
            "risk_evidence_source": "AlpacaPaperBroker.latest_quote+historical_bars",
            "freshness_state": "CURRENT",
            "bar_evidence": source["bar_evidence"],
        }
        engine = PaperAutopilotEngine.__new__(PaperAutopilotEngine)
        engine._runtime_state = {
            "equity_risk_envelopes_snapshot_v1": {
                "status": "CURRENT",
                "valid_until_epoch": time.time() + 300,
                "rows": [evidence],
            }
        }
        candidate = dict(source)
        for field in (
            "bar_evidence", "atr_pct", "risk_evidence_generated_at",
            "risk_evidence_valid_until", "risk_evidence_source", "freshness_state",
        ):
            candidate.pop(field, None)

        joined = engine._attach_current_equity_risk_evidence_v1(candidate)
        self.assertEqual(joined["equity_risk_evidence_join_v1"]["status"], "CURRENT_SYMBOL_MATCHED")
        self.assertEqual(joined["bar_evidence"]["resolution"], "15Min")
        enriched = enrich_candidate_for_pretrade_contract(joined, now=NOW)
        self.assertEqual(enriched["equity_pretrade_forecast_v1"]["forecast_state"], "FORECAST_COMPLETE")
        self.assertEqual(enriched["pretrade_enrichment_v1"]["provider_calls_used"], 0)
        self.assertEqual(enriched["pretrade_enrichment_v1"]["broker_actions_used"], 0)


if __name__ == "__main__":
    unittest.main()
