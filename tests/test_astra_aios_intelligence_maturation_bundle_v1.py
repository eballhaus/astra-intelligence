from __future__ import annotations

import tempfile
import unittest

from engine.astra_aios_intelligence_maturation_bundle_v1 import AstraAiosIntelligenceMaturationBundleV1


def bundle(statuses: dict):
    with tempfile.TemporaryDirectory() as state_dir:
        return AstraAiosIntelligenceMaturationBundleV1(state_dir=state_dir)._symbol_behavioral_memory_expansion_v1(statuses)


def capacity_layers(shadow: dict | None = None, memory: dict | None = None):
    with tempfile.TemporaryDirectory() as state_dir:
        bundle_obj = AstraAiosIntelligenceMaturationBundleV1(state_dir=state_dir)
        return bundle_obj._aios_capacity_manager_v1(
            {}, {}, shadow or {}, {}, {}, {}, memory or {}, {}, {}, {}
        )["layers"]


def exit_maturity(statuses: dict):
    with tempfile.TemporaryDirectory() as state_dir:
        return AstraAiosIntelligenceMaturationBundleV1(state_dir=state_dir)._exit_intelligence_maturation_v2(statuses)


def satellite(statuses: dict, satellite_key: str = "market_breadth_satellite"):
    with tempfile.TemporaryDirectory() as state_dir:
        out = AstraAiosIntelligenceMaturationBundleV1(state_dir=state_dir)._satellite_request_manager(statuses)
        return next(row for row in out["satellites"] if row["satellite_key"] == satellite_key)


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


class AstraAiosControlPlaneMetricIntegrityTests(unittest.TestCase):
    def test_shadow_lab_quality_no_longer_hardcoded_to_zero(self):
        layers = capacity_layers(shadow={"experiments_today": 50, "experiment_confidence_average": 56.095, "experiment_quality_score": 56.095})
        lab = next(row for row in layers if row["layer"] == "Shadow Lab")
        self.assertEqual(lab["quality_score"], 56.095)

    def test_shadow_quality_falls_back_to_existing_confidence(self):
        layers = capacity_layers(shadow={"experiments_today": 50, "experiment_confidence_average": 48.0})
        lab = next(row for row in layers if row["layer"] == "Shadow Lab")
        self.assertEqual(lab["quality_score"], 48.0)

    def test_shadow_quality_unmodified_when_missing(self):
        layers = capacity_layers(shadow={"experiments_today": 10})
        lab = next(row for row in layers if row["layer"] == "Shadow Lab")
        self.assertEqual(lab["quality_score"], 0.0)

    def test_high_storage_health_produces_low_storage_pressure(self):
        layers = capacity_layers(memory={"storage_health_score": 99.0, "memory_pressure_score": 12.0})
        self.assertEqual(layers[0]["storage_pressure"], 1.0)
        self.assertEqual(layers[0]["memory_pressure"], 12.0)

    def test_low_storage_health_produces_higher_storage_pressure(self):
        layers = capacity_layers(memory={"storage_health_score": 30.0, "memory_pressure_score": 12.0})
        self.assertEqual(layers[0]["storage_pressure"], 70.0)

    def test_explicit_storage_pressure_field_is_preferred(self):
        layers = capacity_layers(memory={"storage_health_score": 99.0, "storage_pressure_score": 55.0})
        self.assertEqual(layers[0]["storage_pressure"], 55.0)

    def test_memory_pressure_behavior_unchanged(self):
        layers = capacity_layers(memory={"storage_health_score": 50.0, "memory_pressure_score": 88.0})
        self.assertEqual(layers[0]["storage_pressure"], 50.0)
        self.assertEqual(layers[0]["memory_pressure"], 88.0)

    def test_stale_lifecycle_source_does_not_inflate_exit_maturity(self):
        stale = exit_maturity({
            "trade_lifecycle_audit_truth_horizon_integrity_suite_v1": {"status": "ok", "generated_at": "2026-06-15T00:00:00Z", "session_refresh_status": "stale_cache_detected_waiting_rebuild"},
            "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1": {"status": "ok", "session_is_stale": True},
        })
        self.assertEqual(stale["exit_intelligence_maturity"], 0.0)

    def test_insufficient_evidence_lifecycle_receives_no_fixed_mature_contribution(self):
        out = exit_maturity({
            "trade_lifecycle_audit_truth_horizon_integrity_suite_v1": {"status": "insufficient_evidence"},
            "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1": {"status": "ok"},
        })
        self.assertEqual(out["exit_intelligence_maturity"], 70.0)

    def test_fresh_valid_lifecycle_and_horizon_remain_supported(self):
        out = exit_maturity({
            "trade_lifecycle_audit_truth_horizon_integrity_suite_v1": {"status": "ok", "cache_freshness": "current"},
            "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1": {"status": "ok", "cache_freshness": "current"},
        })
        self.assertEqual(out["exit_intelligence_maturity"], 71.0)


def aic(statuses: dict):
    with tempfile.TemporaryDirectory() as state_dir:
        return AstraAiosIntelligenceMaturationBundleV1(state_dir=state_dir)._aic(
            statuses,
            {"average_satellite_confidence": 80.0, "satellites_registered": 5},
            {"confidence": 75.0, "status": "ok"},
            {"status": "ok"},
            {"status": "ok", "successful_retrievals": 12},
        )


GOVERNANCE = {
    "status": "ok",
    "consensus_score": 83.0,
    "knowledge_graph_score": 70.0,
}

CONSENSUS = {
    "ok": True,
    "suite": "Consensus Engine V1",
    "consensus_score": 83.0,
}

KNOWLEDGE_GRAPH = {
    "ok": True,
    "suite": "Knowledge Graph Foundation V1",
    "graph_confidence": 70.0,
}


class AstraAiosAicUpstreamFactOrderingTests(unittest.TestCase):
    def test_upstream_facts_are_consumed_when_present(self):
        out = aic({
            "astra_intelligence_governance_v1": GOVERNANCE,
            "consensus_engine_v1": CONSENSUS,
            "knowledge_graph_foundation_v1": KNOWLEDGE_GRAPH,
        })
        self.assertEqual(out["governance_status"], "ok")
        self.assertEqual(out["consensus_status"], "ok")
        self.assertEqual(out["knowledge_graph_status"], "ok")
        self.assertEqual(out["consensus_items"], 1)
        self.assertEqual(out["priorities_by_domain"]["governance"], 1)
        self.assertEqual(out["priorities_by_domain"]["consensus"], 1)
        self.assertEqual(out["priorities_by_domain"]["knowledge_graph"], 1)
        self.assertAlmostEqual(out["aic_coordination_score"], (80.0 + 75.0 + 83.0 + 70.0 + 70.0) / 5.0, delta=0.01)

    def test_missing_facts_stay_warming_up_and_not_fabricated(self):
        out = aic({})
        self.assertEqual(out["governance_status"], "warming_up")
        self.assertEqual(out["consensus_status"], "warming_up")
        self.assertEqual(out["knowledge_graph_status"], "warming_up")
        self.assertEqual(out["consensus_items"], 0)
        self.assertEqual(out["priorities_by_domain"]["governance"], 0)
        self.assertEqual(out["priorities_by_domain"]["consensus"], 0)
        self.assertEqual(out["priorities_by_domain"]["knowledge_graph"], 0)
        self.assertEqual(out["aic_coordination_score"], (80.0 + 75.0 + 0.0 + 0.0 + 70.0) / 5.0)

    def test_canonical_ok_flag_is_recognized_as_healthy_not_warming(self):
        out = aic({
            "astra_intelligence_governance_v1": {"status": "ok", "consensus_score": 83.0, "knowledge_graph_score": 70.0},
            "consensus_engine_v1": {"ok": True, "consensus_score": 83.0},
            "knowledge_graph_foundation_v1": {"ok": True, "graph_confidence": 70.0},
        })
        self.assertEqual(out["consensus_status"], "ok")
        self.assertEqual(out["knowledge_graph_status"], "ok")

    def test_false_ok_flag_keeps_warming_up(self):
        out = aic({
            "astra_intelligence_governance_v1": {"status": "ok", "consensus_score": 83.0, "knowledge_graph_score": 70.0},
            "consensus_engine_v1": {"ok": False},
            "knowledge_graph_foundation_v1": {"ok": False},
        })
        self.assertEqual(out["consensus_status"], "warming_up")
        self.assertEqual(out["knowledge_graph_status"], "warming_up")

    def test_aic_adds_no_provider_or_broker_calls(self):
        out = aic({
            "astra_intelligence_governance_v1": GOVERNANCE,
            "consensus_engine_v1": CONSENSUS,
            "knowledge_graph_foundation_v1": KNOWLEDGE_GRAPH,
        })
        self.assertEqual(out["provider_calls_used"], 0)
        self.assertEqual(out["llm_calls_used"], 0)
        self.assertEqual(out["api_calls_used"], 0)
        self.assertEqual(out["broker_execution_added"], False)
        self.assertEqual(out["live_trading_changed"], False)
        self.assertEqual(out["behavior_safe_to_apply"], False)


class AstraAiosSatelliteConfidenceHandoffTests(unittest.TestCase):
    def test_specialized_source_confidence_fields_are_recognized(self):
        out = satellite({
            "market_breadth_index_intelligence_v1": {
                "cache_freshness": "current",
                "index_confidence_score": 62.0,
            },
        })
        self.assertEqual(out["status"], "ok")
        self.assertAlmostEqual(out["confidence_budget"], 62.0, delta=0.01)
        self.assertAlmostEqual(out["average_confidence"], 62.0, delta=0.01)

    def test_generic_canonical_confidence_still_works(self):
        out = satellite({
            "astra_satellite_network_v1": {
                "cache_freshness": "current",
                "confidence": 78.0,
            },
        })
        self.assertAlmostEqual(out["confidence_budget"], 78.0, delta=0.01)

    def test_missing_source_remains_missing_not_fabricated(self):
        out = satellite({})
        self.assertEqual(out["status"], "insufficient_evidence")
        self.assertEqual(out["health"], "insufficient_evidence")
        self.assertEqual(out["confidence_budget"], 0.0)

    def test_cio_insufficient_when_no_canonical_payload(self):
        out = satellite({}, satellite_key="cio_satellite")
        self.assertEqual(out["status"], "insufficient_evidence")
        self.assertEqual(out["confidence_budget"], 0.0)

    def test_stale_source_cannot_inflate_confidence(self):
        out = satellite({
            "market_breadth_index_intelligence_v1": {
                "cache_freshness": "stale",
                "index_confidence_score": 90.0,
            },
        })
        self.assertEqual(out["status"], "insufficient_evidence")
        self.assertEqual(out["confidence_budget"], 0.0)

    def test_fresh_source_confidence_is_averaged_across_present_sources(self):
        out = satellite({
            "astra_satellite_network_v1": {"cache_freshness": "current", "confidence": 70.0},
            "market_breadth_index_intelligence_v1": {"cache_freshness": "current", "index_confidence_score": 90.0},
            "market_transition_detection_v1": {"cache_freshness": "stale", "transition_confidence": 99.0},
        }, satellite_key="market_satellite")
        self.assertEqual(out["status"], "ok")
        self.assertAlmostEqual(out["confidence_budget"], (70.0 + 90.0) / 2.0, delta=0.01)

    def test_no_provider_calls_or_behavior_changes(self):
        out = satellite({
            "astra_satellite_network_v1": {"cache_freshness": "current", "confidence": 78.0},
        })
        self.assertEqual(out["provider_calls_used"], 0)
        self.assertIs(False, out["direct_trade_influence_enabled"])


def copilot_capacity(statuses: dict | None = None):
    with tempfile.TemporaryDirectory() as state_dir:
        bundle_obj = AstraAiosIntelligenceMaturationBundleV1(state_dir=state_dir)
        out = bundle_obj._aios_capacity_manager_v1(
            {}, {}, {}, {}, {}, {}, {}, {}, {}, statuses or {}
        )
        return next(row for row in out["layers"] if row["layer"] == "Copilot")


CANONICAL_COPILOT = {
    "ok": True,
    "status": "ok",
    "top_actions": [{"action": "EXIT_REVIEW", "symbol": "AAA", "confidence": "HIGH"}] * 5,
    "recommendations": [{"action": "EXIT_REVIEW", "symbol": "AAA", "confidence": "HIGH"}] * 12,
    "generated_at": "2026-08-08T12:00:00Z",
}


class AstraAiosCopilotFactHandoffTests(unittest.TestCase):
    def test_copilot_top_action_count_reaches_capacity_manager(self):
        out = copilot_capacity({"astra_copilot_suite_v1": CANONICAL_COPILOT})
        self.assertEqual(out["current_utilization"], 5)
        self.assertEqual(out["throughput_today"], 5)

    def test_missing_copilot_remains_zero_not_fabricated(self):
        out = copilot_capacity({})
        self.assertEqual(out["current_utilization"], 0)
        self.assertEqual(out["throughput_today"], 0)

    def test_no_actions_is_not_healthy_evidence(self):
        out = copilot_capacity({"astra_copilot_suite_v1": {"ok": True, "status": "warming_up", "top_actions": []}})
        self.assertEqual(out["current_utilization"], 0)
        self.assertEqual(out["throughput_today"], 0)

    def test_server_attach_aios_upstream_facts_exposes_canonical_copilot(self):
        import server_extend
        out = server_extend._attach_aios_upstream_facts({})
        copilot = out.get("astra_copilot_suite_v1")
        self.assertIsInstance(copilot, dict)
        self.assertTrue(copilot.get("canonical_recommendation_contract_v1"))

    def test_server_attach_reuses_existing_copilot_payload(self):
        import server_extend
        statuses = server_extend._attach_aios_upstream_facts({"astra_copilot_suite_v1": CANONICAL_COPILOT})
        self.assertEqual(statuses["astra_copilot_suite_v1"]["top_actions"], CANONICAL_COPILOT["top_actions"])
        self.assertEqual(statuses["astra_copilot_suite_v1"]["ok"], True)


if __name__ == "__main__":
    unittest.main()