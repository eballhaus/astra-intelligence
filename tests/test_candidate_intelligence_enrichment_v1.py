from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_premarket_certification_v1 import (
    build_lane_certification,
    build_candidate_risk_envelope_v1,
    build_pretrade_decision_contract,
    enrich_candidate_for_pretrade_contract,
)


def future_iso(minutes: int = 10) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def source_row(**overrides):
    row = {
        "symbol": "ENR", "candidate_id": "cand-enr", "recommendation_id": "rec-enr",
        "lane_id": "SWING", "setup_type": "breakout", "summary": "Breakout has current momentum support.",
        "ranking_score": 82.0, "confidence": 78.0, "expected_return_low_pct": 2.0,
        "expected_return_high_pct": 5.0, "price": 100.0, "stop_loss": 96.0,
        "expected_target_high": 105.0, "drawdown_risk_score": 4.0,
        "ranked_reason": "current ranking and liquidity evidence", "trend_state": "supportive",
        "generated_at": future_iso(), "expires_at": future_iso(),
    }
    row.update(overrides)
    return row


class CandidateIntelligenceEnrichmentTests(unittest.TestCase):
    def test_stop_and_drawdown_produce_distinct_supported_risk_ranges(self):
        envelope = build_candidate_risk_envelope_v1(source_row())
        self.assertIn(envelope["risk_envelope_state"], {"RISK_ENVELOPE_COMPLETE", "RISK_ENVELOPE_COMPLETE_WITH_WARNINGS"})
        self.assertEqual(envelope["expected_downside_range"]["high_pct"], -4.0)
        self.assertEqual(envelope["expected_drawdown"]["high_pct"], -4.0)
        self.assertEqual(envelope["field_provenance_v1"]["expected_drawdown"]["source_field"], "drawdown_risk_score")

    def test_volatility_derives_distinct_downside_and_drawdown_ranges(self):
        row = source_row(stop_loss="", drawdown_risk_score="", atr_pct=2.0)
        envelope = build_candidate_risk_envelope_v1(row)
        self.assertEqual(envelope["expected_downside_range"]["high_pct"], -2.0)
        self.assertEqual(envelope["expected_drawdown"]["low_pct"], -4.0)
        self.assertEqual(envelope["field_provenance_v1"]["expected_downside_range"]["evidence_class"], "CURRENT_SYMBOL_RISK")

    def test_etf_and_crypto_use_same_attributable_risk_owner(self):
        etf = build_candidate_risk_envelope_v1(source_row(symbol="XLB", instrument_type="ETF", lane_id="DAY", atr_pct=1.5, stop_loss="", drawdown_risk_score=""))
        crypto = build_candidate_risk_envelope_v1(source_row(symbol="BTC/USD", asset_class="crypto", lane_id="CRYPTO", crypto_risk_pct=3.0, stop_loss="", drawdown_risk_score=""))
        self.assertEqual(etf["asset_type"], "ETF")
        self.assertEqual(crypto["lane"], "CRYPTO")
        self.assertEqual(crypto["expected_downside_range"]["high_pct"], -3.0)

    def test_unsupported_candidate_has_no_generic_risk_fallback(self):
        envelope = build_candidate_risk_envelope_v1({"symbol": "NONE", "candidate_id": "none", "lane_id": "SWING", "expected_return_pct": 3.0})
        self.assertEqual(envelope["risk_envelope_state"], "RISK_ENVELOPE_INCOMPLETE")
        self.assertIsNone(envelope["expected_downside_range"])
    def test_raw_candidate_retrieves_current_symbol_evidence_and_completes_contract(self):
        raw = {"symbol": "ENR", "candidate_id": "cand-enr", "recommendation_id": "rec-enr", "lane_id": "SWING", "expires_at": future_iso()}
        enriched = enrich_candidate_for_pretrade_contract(
            raw,
            statuses={"candidate_ranking_attribution_promotion_intelligence_v1": [source_row()]},
        )
        contract = build_pretrade_decision_contract(enriched)
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertTrue(enriched["pretrade_enrichment_v1"]["enrichment_ran"])
        self.assertEqual(enriched["field_provenance_v1"]["thesis"]["evidence_class"], "CURRENT_SYMBOL_DIRECT")

    def test_candidate_local_evidence_outranks_weaker_symbol_evidence(self):
        raw = source_row(strategy_archetype="candidate_local_strategy", expected_return_pct=3.0)
        weaker = source_row(strategy_archetype="shadow_strategy", expected_return_pct=9.0)
        enriched = enrich_candidate_for_pretrade_contract(
            raw,
            statuses={"shadow_vs_paper_performance_attribution": [weaker]},
        )
        self.assertEqual(enriched["strategy_archetype"], "candidate_local_strategy")
        self.assertEqual(enriched["field_provenance_v1"]["strategy_archetype"]["evidence_class"], "CURRENT_CANDIDATE_DIRECT")

    def test_stale_current_context_does_not_supply_missing_core_evidence(self):
        stale = source_row(generated_at="2020-01-01T00:00:00Z", expires_at="2030-01-01T00:00:00Z")
        raw = {"symbol": "ENR", "candidate_id": "cand-enr", "recommendation_id": "rec-enr", "lane_id": "SWING", "expires_at": future_iso()}
        enriched = enrich_candidate_for_pretrade_contract(
            raw,
            statuses={"candidate_ranking_attribution_promotion_intelligence_v1": [stale]},
        )
        self.assertIn("thesis", enriched["pretrade_enrichment_v1"]["missing_fields"])

    def test_shadow_replay_and_aggregate_labels_remain_honest(self):
        raw = {"symbol": "ENR", "candidate_id": "cand-enr", "recommendation_id": "rec-enr", "lane_id": "SWING", "expires_at": future_iso()}
        replay = source_row(summary="Replay-only outcome context.")
        enriched = enrich_candidate_for_pretrade_contract(
            raw,
            statuses={"replay_counterfactual_learning_v2": [replay]},
        )
        self.assertEqual(enriched["field_provenance_v1"]["thesis"]["evidence_class"], "REPLAY_SUPPORTED")
        self.assertNotIn("BROKER_CONFIRMED_COMPLETE", enriched["evidence_classes"])

    def test_supported_setup_maps_strategy_and_horizon_with_provenance(self):
        enriched = enrich_candidate_for_pretrade_contract({
            "symbol": "MAP", "candidate_id": "cand-map", "recommendation_id": "rec-map", "lane_id": "SWING",
            "setup_type": "breakout", "summary": "Current breakout summary.", "expected_return_pct": 3.0,
            "price": 100, "stop_loss": 97, "drawdown_risk_score": 3, "generated_at": future_iso(), "expires_at": future_iso(),
        })
        self.assertEqual(enriched["strategy_archetype"], "momentum_breakout")
        self.assertEqual(enriched["intended_horizon"], "swing_trade")
        self.assertTrue(enriched["field_provenance_v1"]["intended_horizon"]["derived"])

    def test_aggregate_thesis_score_does_not_create_direct_thesis(self):
        raw = {"symbol": "NONE", "candidate_id": "cand-none", "recommendation_id": "rec-none", "lane_id": "SWING", "expires_at": future_iso()}
        enriched = enrich_candidate_for_pretrade_contract(
            raw,
            statuses={"trade_thesis_validation_v1": {"thesis_confidence": 99.0}},
        )
        self.assertIn("thesis", enriched["pretrade_enrichment_v1"]["missing_fields"])

    def test_expected_ranges_and_forward_review_conditions_are_bounded(self):
        enriched = enrich_candidate_for_pretrade_contract(source_row())
        self.assertEqual(enriched["expected_return_range"]["low_pct"], 2.0)
        self.assertLess(enriched["expected_downside_range"]["high_pct"], 0.0)
        self.assertTrue(enriched["hold_conditions"])
        self.assertTrue(enriched["exit_review_conditions"])
        self.assertIn("no automatic exit", " ".join(enriched["controlled_loss_conditions"]).lower())

    def test_contract_builder_cannot_bypass_enrichment(self):
        contract = build_pretrade_decision_contract(source_row())
        self.assertTrue(contract["pretrade_enrichment_v1"]["enrichment_ran"])
        self.assertEqual(contract["contract_status"], "VALID")

    def test_conflicting_evidence_fails_closed(self):
        contract = build_pretrade_decision_contract(source_row(evidence_conflicts=["strategy_archetype"]))
        self.assertEqual(contract["contract_state"], "CONTRACT_CONFLICTING")
        self.assertFalse(contract["order_ready_allowed"])

    def test_lower_confidence_bounded_defaults_are_valid_with_warnings(self):
        contract = build_pretrade_decision_contract(source_row(setup_type="breakout", strategy_archetype="", paper_entry_horizon_style=""))
        self.assertIn(contract["contract_state"], {"CONTRACT_COMPLETE", "CONTRACT_COMPLETE_WITH_WARNINGS"})

    def test_irrecoverable_candidate_remains_incomplete(self):
        contract = build_pretrade_decision_contract({"symbol": "EMPTY", "candidate_id": "cand-empty", "recommendation_id": "rec-empty", "lane_id": "SWING", "expires_at": future_iso()})
        self.assertEqual(contract["contract_state"], "CONTRACT_INCOMPLETE")
        self.assertFalse(contract["order_ready_allowed"])

    def test_no_candidate_path_remains_ready_no_trade(self):
        result = build_lane_certification("DAY", activation={}, dry_run={}, contracts=[], production_commit="test", snapshot_id="test")
        self.assertEqual(result["status"], "READY_NO_TRADE")

    def test_enrichment_is_read_only(self):
        enriched = enrich_candidate_for_pretrade_contract(source_row())
        diagnostic = enriched["pretrade_enrichment_v1"]
        self.assertEqual(diagnostic["provider_calls_used"], 0)
        self.assertEqual(diagnostic["broker_actions_used"], 0)
        self.assertEqual(diagnostic["llm_calls_used"], 0)
        self.assertEqual(diagnostic["full_history_scan_count"], 0)


if __name__ == "__main__":
    unittest.main()
