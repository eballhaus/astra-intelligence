import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.astra_multilane_activation_v2 import natural_lane_performance_attribution
from engine.astra_multilane_market_hours_audit_v1 import _scheduled_slot_et, blocker_class, build_audit
from engine.astra_premarket_certification_v1 import enrich_candidate_for_pretrade_contract
from engine.astra_trade_lane_registry_v1 import apply_trade_lane_contract


class MultilaneNaturalAuditTests(unittest.TestCase):
    def test_etf_uses_canonical_registry_with_explicit_source(self):
        row = apply_trade_lane_contract({"symbol": "XLB", "paper_entry_horizon_style": "day_trade"})
        self.assertEqual(row["asset_class"], "equity")
        self.assertEqual(row["asset_type"], "ETF")
        self.assertEqual(row["instrument_type"], "ETF")
        self.assertEqual(row["asset_classification_source"], "existing_canonical_etf_registry")
        self.assertEqual(row["lane_id"], "DAY")

    def test_etf_audit_bucket_prefers_instrument_cohort_over_execution_asset(self):
        payload = build_audit({"per_candidate_decision_trace": [{
            "candidate_id": "etf-1", "symbol": "XLB", "lane_id": "SWING", "asset_type": "stock",
            "instrument_type": "ETF", "pretrade_decision_contract": {"contract_state": "CONTRACT_COMPLETE"},
        }]})
        self.assertIn("SWING_ETF", payload["counts_by_lane_asset"])
        self.assertEqual(payload["candidate_rows"][0]["lane_id"], "SWING")

    def test_etf_audit_recovers_legacy_abbreviated_trace_from_canonical_registry(self):
        payload = build_audit({"per_candidate_decision_trace": [{
            "candidate_id": "etf-legacy", "symbol": "XLB", "lane_id": "SWING", "asset_type": "stock",
            "pretrade_decision_contract": {"contract_state": "CONTRACT_COMPLETE"},
        }]})
        self.assertEqual(payload["candidate_rows"][0]["asset_type"], "ETF")
        self.assertEqual(payload["candidate_rows"][0]["asset_classification_source"], "existing_canonical_etf_registry")

    def test_crypto_direct_risk_envelope_enriches_without_fabrication(self):
        row = enrich_candidate_for_pretrade_contract({
            "symbol": "BTC/USD", "asset_class": "crypto", "candidate_id": "crypto-1",
            "recommendation_id": "rec-1", "setup_type": "momentum", "intended_horizon": "swing_trade",
            "summary": "BTC momentum has current support", "confidence": 70,
            "expected_return_pct": 4.0, "crypto_risk_pct": 2.5, "price": 100.0,
            "candidate_generated_at": "2026-07-15T12:00:00Z",
        })
        downside = row["expected_downside_range"]
        self.assertEqual(downside["low_pct"], -2.5)
        self.assertEqual(row["field_provenance_v1"]["expected_downside_range"]["source_system"], "crypto_candidate_risk_envelope")
        self.assertEqual(row["field_provenance_v1"]["expected_downside_range"]["evidence_class"], "CURRENT_CANDIDATE_DIRECT")

    def test_audit_reports_exact_non_trading_blocker_without_broker_action(self):
        payload = build_audit({
            "market_session_mode": "market_closed",
            "final_blocker_reason": "session_order_submission_blocked",
            "per_candidate_decision_trace": [{
                "candidate_id": "day-1", "symbol": "TSLA", "lane_id": "DAY", "asset_type": "EQUITY",
                "pretrade_decision_contract_state": "CONTRACT_COMPLETE", "eligible": True,
                "selected": True, "order_ready": False, "order_readiness_reason": "BLOCKED_MARKET_SESSION",
            }],
        })
        self.assertEqual(payload["candidate_rows"][0]["blocker_class"], "SESSION_CLOSED")
        self.assertEqual(payload["broker_actions_used"], 0)
        self.assertTrue(payload["read_only"])
        self.assertEqual(blocker_class("crypto_quote_stale"), "STALE_MARKET_DATA")

    def test_contract_failure_precedes_downstream_capacity_or_duplicate_blocker(self):
        payload = build_audit({"per_candidate_decision_trace": [{
            "candidate_id": "day-2", "symbol": "COST", "lane_id": "DAY", "instrument_type": "EQUITY",
            "decision_reason": "duplicate_active_position", "pretrade_decision_contract": {
                "contract_state": "CONTRACT_INCOMPLETE", "missing_required_fields": ["expected_downside_range"],
            },
        }]})
        row = payload["candidate_rows"][0]
        self.assertEqual(row["first_blocker"], "CONTRACT_INCOMPLETE:expected_downside_range")
        self.assertEqual(row["downstream_blocker_observed"], "duplicate_active_position")

    def test_each_market_hours_schedule_slot_has_a_distinct_deduplication_key(self):
        morning = datetime(2026, 7, 15, 9, 40, tzinfo=ZoneInfo("America/New_York"))
        noon = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(_scheduled_slot_et(morning), "2026-07-15T09:40")
        self.assertEqual(_scheduled_slot_et(noon), "2026-07-15T12:00")
        self.assertNotEqual(_scheduled_slot_et(morning), _scheduled_slot_et(noon))

    def test_only_labeled_natural_paired_truths_are_in_official_cohorts(self):
        natural = {
            "evidence_class": "BROKER_CONFIRMED_COMPLETE", "lane_id": "DAY", "asset_class": "equity",
            "instrument_type": "ETF", "natural_trade_label": "NATURAL_PAPER_DAY_ETF",
            "entry_fill_id": "entry", "exit_fill_id": "exit", "entry_order_id": "bo", "exit_order_id": "so",
            "lifecycle_id": "life", "realized_return": 1.25,
            "broker_residual_zero_confirmed": True,
        }
        fixture = {**natural, "natural_trade_label": "FIXTURE_DAY_ETF", "entry_fill_id": "fixture-entry"}
        result = natural_lane_performance_attribution([natural, fixture])
        self.assertEqual(result["total_natural_strict_truths"], 1)
        self.assertEqual(result["cohorts"]["DAY_ETF"]["sample_size"], 1)
        self.assertFalse(result["cohorts"]["DAY_ETF"]["official_metric_eligible"])


if __name__ == "__main__":
    unittest.main()
