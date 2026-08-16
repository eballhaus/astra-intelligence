from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from engine.astra_premarket_certification_v1 import (
    build_pretrade_decision_contract,
    enrich_candidate_for_pretrade_contract,
)
from engine.candidate_execution_integrity_v1 import derive_crypto_pretrade_forecast_v1


class CryptoPretradeRiskEnvelopeHandoffTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)

    def _bars(self, now: datetime) -> list[dict[str, object]]:
        return [
            {
                "t": (now - timedelta(minutes=(8 - index) * 15)).isoformat().replace("+00:00", "Z"),
                "c": 100.0 + index,
                "h": 100.6 + index,
                "l": 99.6 + index,
            }
            for index in range(9)
        ]

    def _candidate(self, now: datetime, *, quote_at: datetime | None = None) -> dict[str, object]:
        timestamp = (quote_at or now).isoformat().replace("+00:00", "Z")
        return {
            "symbol": "LINK/USD",
            "candidate_id": "cand-link-risk-envelope",
            "recommendation_id": "rec-link-risk-envelope",
            "decision_id": "dec-link-risk-envelope",
            "asset_class": "crypto",
            "asset_type": "crypto",
            "lane_id": "CRYPTO",
            "paper_entry_horizon_style": "day_trade",
            "strategy_archetype": "momentum_continuation",
            "summary": "Current completed-bar continuation remains positive.",
            "thesis_supporting_conditions": ["positive completed-bar continuation"],
            "thesis_invalidation_conditions": ["continuation evidence deteriorates"],
            "ranking_score": 82.0,
            "confidence": 82.0,
            "market_regime": "risk_on",
            "price": 108.0,
            "bid": 107.9,
            "ask": 108.1,
            "quote_volume": 5000.0,
            "provider_quote_timestamp": timestamp,
            "quote_timestamp": timestamp,
            "bar_timestamp": timestamp,
            "candidate_generated_at": timestamp,
            "crypto_risk_pct": 1.0,
            "completed_bar_return_pct": 0.9,
        }

    def _complete_forecast(self, candidate: dict[str, object], now: datetime) -> dict[str, object]:
        forecast = derive_crypto_pretrade_forecast_v1(candidate, completed_bars=self._bars(now), now=now)
        self.assertEqual(forecast["forecast_state"], "FORECAST_COMPLETE")
        return forecast

    def test_complete_nested_crypto_forecast_materializes_into_risk_contract(self) -> None:
        now = self._now()
        candidate = self._candidate(now)
        candidate["crypto_pretrade_forecast_v1"] = self._complete_forecast(candidate, now)

        enriched = enrich_candidate_for_pretrade_contract(candidate, now=now)
        contract = build_pretrade_decision_contract(
            enriched,
            certification_snapshot_id="cert-crypto-handoff",
            now=now,
        )

        self.assertIsNotNone(enriched["expected_return_range"])
        self.assertIsNotNone(enriched["expected_return_per_day_range"])
        self.assertEqual(enriched["candidate_risk_envelope_v1"]["risk_envelope_state"], "RISK_ENVELOPE_COMPLETE")
        self.assertNotIn("expected_return_range", contract["missing_required_fields"])
        self.assertNotIn("expected_return_per_day_range", contract["missing_required_fields"])
        self.assertNotIn("candidate_risk_envelope_v1", contract["missing_required_fields"])
        self.assertEqual(
            contract["field_provenance_v1"]["expected_return_range"]["source_system"],
            "PaperAutopilotWorker.crypto_rankings_snapshot_v1",
        )

    def test_stale_nested_crypto_forecast_remains_fail_closed(self) -> None:
        now = self._now()
        candidate = self._candidate(now, quote_at=now - timedelta(minutes=6))
        candidate["crypto_pretrade_forecast_v1"] = self._complete_forecast(candidate, now)

        contract = build_pretrade_decision_contract(candidate, now=now)

        self.assertEqual(contract["candidate_risk_envelope_v1"]["risk_envelope_state"], "RISK_ENVELOPE_STALE")
        self.assertIn("candidate_risk_envelope_v1", contract["missing_required_fields"])
        self.assertIn("stale_risk_envelope", contract["conflicting_fields"])
        self.assertFalse(contract["order_ready_allowed"])

    def test_incomplete_forecast_does_not_fabricate_return_or_risk(self) -> None:
        now = self._now()
        candidate = self._candidate(now)
        candidate["crypto_pretrade_forecast_v1"] = {
            "forecast_state": "INSUFFICIENT_FORECAST_EVIDENCE",
            "expected_return_range": {"low_pct": 1.0, "high_pct": 2.0},
            "source_provenance": {"evidence_class": "CURRENT_CANDIDATE_DIRECT"},
        }

        enriched = enrich_candidate_for_pretrade_contract(candidate, now=now)

        self.assertIsNone(enriched.get("expected_return_range"))
        self.assertIsNone(enriched.get("expected_return_per_day_range"))
        self.assertEqual(enriched["candidate_risk_envelope_v1"]["risk_envelope_state"], "RISK_ENVELOPE_INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
