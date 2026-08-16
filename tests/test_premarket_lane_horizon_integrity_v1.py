from __future__ import annotations

from datetime import datetime, timezone
import unittest

from engine.astra_premarket_certification_v1 import (
    _lane,
    build_candidate_risk_envelope_v1,
    build_pretrade_decision_contract,
    enrich_candidate_for_pretrade_contract,
)


class PremarketLaneHorizonIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)
        self.timestamp = self.now.isoformat().replace("+00:00", "Z")

    def _candidate(self, *, lane: str, horizon: str) -> dict[str, object]:
        return {
            "symbol": "TEST",
            "candidate_id": f"cand-{lane.lower()}",
            "recommendation_id": f"rec-{lane.lower()}",
            "decision_id": f"dec-{lane.lower()}",
            "lane_id": lane,
            "asset_class": "equity",
            "asset_type": "stock",
            "paper_entry_horizon_style": horizon,
            "strategy_archetype": "momentum_continuation",
            "trade_style": horizon,
            "ranking_score": 80.0,
            "confidence": 80.0,
            "summary": "Current attributable momentum remains positive.",
            "thesis_supporting_conditions": ["current momentum support"],
            "thesis_invalidation_conditions": ["momentum deteriorates"],
            "expected_hold_window": "authoritative supplied duration",
            "expected_return_range": {"low_pct": 7.0, "high_pct": 14.0},
            "expected_downside_range": {"low_pct": -3.0, "high_pct": -2.0},
            "expected_drawdown": {"low_pct": -4.0, "high_pct": -2.0},
            "price": 100.0,
            "bid": 99.9,
            "ask": 100.1,
            "quote_volume": 10000.0,
            "quote_timestamp": self.timestamp,
            "candidate_generated_at": self.timestamp,
        }

    def test_scalp_is_a_distinct_supported_pretrade_lane(self) -> None:
        candidate = self._candidate(lane="SCALP", horizon="scalp")
        candidate["expected_hold_minutes"] = 30.0

        contract = build_pretrade_decision_contract(candidate, now=self.now)

        self.assertEqual(_lane("SCALP"), "SCALP")
        self.assertEqual(contract["lane"], "SCALP")
        self.assertNotEqual(contract["lane"], "SWING")
        self.assertNotIn("lane", contract["missing_required_fields"])
        self.assertTrue(contract["order_ready_allowed"])

    def test_scalp_without_return_and_risk_evidence_stays_fail_closed(self) -> None:
        candidate = self._candidate(lane="SCALP", horizon="scalp")
        candidate.pop("expected_return_range")
        candidate.pop("expected_downside_range")
        candidate.pop("expected_drawdown")

        contract = build_pretrade_decision_contract(candidate, now=self.now)

        self.assertEqual(contract["lane"], "SCALP")
        self.assertFalse(contract["order_ready_allowed"])
        self.assertIn("expected_return_range", contract["missing_required_fields"])
        self.assertIn("candidate_risk_envelope_v1", contract["missing_required_fields"])

    def test_lane_aliases_preserve_canonical_identity(self) -> None:
        self.assertEqual(_lane("DAY"), "DAY")
        self.assertEqual(_lane("SWING"), "SWING")
        self.assertEqual(_lane("CRYPTO"), "CRYPTO")
        for alias in ("SWING_TRADE", "SHORT_SWING", "STANDARD_SWING", "EXTENDED_SWING"):
            self.assertEqual(_lane(alias), "SWING")

    def test_swing_expected_hold_days_drive_per_day_math_and_provenance(self) -> None:
        candidate = self._candidate(lane="SWING", horizon="swing")
        candidate["expected_hold_days"] = 7.0
        candidate.pop("expected_hold_window")

        enriched = enrich_candidate_for_pretrade_contract(candidate, now=self.now)
        risk = build_candidate_risk_envelope_v1(enriched, now=self.now)

        self.assertEqual(enriched["expected_hold_window"], "7 trading days")
        self.assertEqual(enriched["expected_return_per_day_range"]["low_pct_per_day"], 1.0)
        self.assertEqual(enriched["expected_return_per_day_range"]["high_pct_per_day"], 2.0)
        self.assertIn("expected_hold_days", enriched["field_provenance_v1"]["expected_return_per_day_range"]["source_field"])
        self.assertEqual(risk["expected_return_per_day_range"]["low_pct_per_day"], 1.0)
        self.assertIn("expected_hold_days", risk["field_provenance_v1"]["expected_return_per_day_range"]["source_field"])

    def test_swing_minutes_keep_existing_precedence_over_days(self) -> None:
        candidate = self._candidate(lane="SWING", horizon="swing")
        candidate.update({"expected_hold_minutes": 1440.0, "expected_hold_days": 7.0})

        risk = build_candidate_risk_envelope_v1(candidate, now=self.now)

        self.assertEqual(risk["expected_return_per_day_range"]["low_pct_per_day"], 7.0)
        self.assertIn("expected_hold_minutes", risk["field_provenance_v1"]["expected_return_per_day_range"]["source_field"])

    def test_swing_without_explicit_duration_retains_existing_fallback(self) -> None:
        candidate = self._candidate(lane="SWING", horizon="swing")

        risk = build_candidate_risk_envelope_v1(candidate, now=self.now)

        self.assertEqual(risk["expected_return_per_day_range"]["low_pct_per_day"], round(7.0 / 3.0, 4))
        self.assertIn("existing_swing_trade_policy", risk["field_provenance_v1"]["expected_return_per_day_range"]["source_field"])


if __name__ == "__main__":
    unittest.main()
