from __future__ import annotations

import tempfile
import unittest

from engine.astra_aios_intelligence_maturation_bundle_v1 import AstraAiosIntelligenceMaturationBundleV1


def bundle(statuses: dict):
    with tempfile.TemporaryDirectory() as state_dir:
        return AstraAiosIntelligenceMaturationBundleV1(state_dir=state_dir)._symbol_behavioral_memory_expansion_v1(statuses)


ACCELERATED = {
    "cache_freshness": "live",
    "current_behavior_confidence": 71.25,
    "symbol_exit_confidence": 100.0,
    "horizon_confidence": 20.0,
    "regime_symbol_confidence": 10.35,
    "transferable_learning_confidence": 66.11,
    "transferable_pattern_confidence": 66.11,
    "symbol_personality_quality_score": 74.95,
    "symbol_profiles_tracked": 25,
}

LONG_MEMORY = {
    "symbol_memory_quality_score": 80.0,
}

FAMILY = {
    "family_transfer_confidence": 71.36,
}

TIER3_FRESH = {
    "cache_freshness": "live",
    "confidence": 55.0,
}

TIER3_STALE = {
    "generated_at": "2026-06-16T23:12:15.061765Z",
    "confidence": 55.0,
}


class AstraAiosSymbolBehavioralMemoryHandoffTests(unittest.TestCase):
    def test_specialized_symbol_fields_are_recognized(self):
        result = bundle({
            "long_term_memory_symbol_retrieval_suite_v1": LONG_MEMORY,
            "accelerated_learning_symbol_intelligence_suite_v1": ACCELERATED,
            "trade_family_intelligence_v1": FAMILY,
            "astra_tier3_historical_satellite_shadow_acceleration_v1": TIER3_FRESH,
        })
        self.assertGreater(result["symbol_behavioral_memory_maturity"], 0.0)
        source_conf = result["symbol_behavioral_memory_source_confidence"]
        self.assertEqual(source_conf["long_term_memory_symbol_retrieval_suite_v1"], 80.0)
        self.assertAlmostEqual(source_conf["accelerated_learning_symbol_intelligence_suite_v1"], 57.11, delta=0.01)
        self.assertEqual(source_conf["trade_family_intelligence_v1"], 71.36)

    def test_missing_evidence_stays_missing_and_not_fabricated(self):
        empty = bundle({})
        self.assertEqual(empty["status"], "insufficient_evidence")
        self.assertEqual(empty["symbol_behavioral_memory_maturity"], 0.0)
        self.assertTrue(all(v is None for v in empty["symbol_behavioral_memory_source_confidence"].values()))

    def test_generic_only_payload_does_not_fabricate_symbol_confidence(self):
        out = bundle({"long_term_memory_symbol_retrieval_suite_v1": {"confidence": 90.0}})
        self.assertIsNone(out["symbol_behavioral_memory_source_confidence"]["long_term_memory_symbol_retrieval_suite_v1"])
        self.assertEqual(out["symbol_behavioral_memory_maturity"], 0.0)

    def test_stale_tier3_cannot_inflate_current_maturity(self):
        out = bundle({"astra_tier3_historical_satellite_shadow_acceleration_v1": TIER3_STALE})
        self.assertIsNone(out["symbol_behavioral_memory_source_confidence"]["astra_tier3_historical_satellite_shadow_acceleration_v1"])
        self.assertEqual(out["symbol_behavioral_memory_maturity"], 0.0)

    def test_fresh_tier3_contributes_via_existing_canonical_confidence(self):
        out = bundle({"astra_tier3_historical_satellite_shadow_acceleration_v1": TIER3_FRESH})
        self.assertEqual(out["symbol_behavioral_memory_source_confidence"]["astra_tier3_historical_satellite_shadow_acceleration_v1"], 55.0)

    def test_fresh_contributions_ripple_from_each_canonical_field(self):
        out = bundle({
            "long_term_memory_symbol_retrieval_suite_v1": LONG_MEMORY,
            "trade_family_intelligence_v1": FAMILY,
        })
        self.assertAlmostEqual(out["symbol_behavioral_memory_maturity"], 75.68, delta=0.01)

    def test_symbol_behavioral_memory_v2_insufficient_evidence_not_overridden(self):
        out = bundle({"symbol_behavioral_memory_v2": {"state": "INSUFFICIENT_EVIDENCE"}})
        self.assertEqual(out["status"], "insufficient_evidence")
        self.assertEqual(out["symbol_behavioral_memory_maturity"], 0.0)

    def test_evidence_tiers_unchanged(self):
        out = bundle(
            {
                "long_term_memory_symbol_retrieval_suite_v1": LONG_MEMORY,
                "astra_tier3_historical_satellite_shadow_acceleration_v1": TIER3_STALE,
            }
        )
        self.assertNotIn("evidence_tier", out)
        self.assertNotIn("promoted_evidence", out)

    def test_no_behavior_or_broker_lifecycle_changes(self):
        out = bundle(
            {
                "long_term_memory_symbol_retrieval_suite_v1": LONG_MEMORY,
                "accelerated_learning_symbol_intelligence_suite_v1": ACCELERATED,
            }
        )
        self.assertIs(False, out["entry_behavior_changed"])
        self.assertIs(False, out["exit_behavior_changed"])
        self.assertIs(False, out["position_sizing_changed"])
        self.assertIs(False, out["broker_behavior_changed"])
        self.assertIs(False, out["ranking_behavior_changed"])
        self.assertIs(False, out["promotion_logic_changed"])
        self.assertIs(False, out["live_trading_changed"])
        self.assertEqual(out["provider_calls_used"], 0)
        self.assertEqual(out["llm_calls_used"], 0)
        self.assertEqual(out["api_calls_used"], 0)
        self.assertEqual(out["dashboard_provider_calls_used"], 0)
        flagged_behavior = [
            key for key in (
                "live_trading_changed", "broker_behavior_changed", "ranking_behavior_changed",
                "promotion_logic_changed", "entry_behavior_changed", "exit_behavior_changed",
                "position_sizing_changed", "portfolio_allocation_changed", "automatic_exits_enabled",
                "automatic_entries_enabled", "broker_execution_added",
            ) if out.get(key)
        ]
        self.assertEqual(flagged_behavior, [])
        self.assertIs(True, out["advisory_only"])
        self.assertIs(True, out["shadow_analysis_mode"])


if __name__ == "__main__":
    unittest.main()