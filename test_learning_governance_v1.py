from __future__ import annotations

import unittest

import server_extend


class LearningGovernanceV1Tests(unittest.TestCase):
    def test_catalog_has_separated_evidence_classes(self):
        payload = server_extend._backend_intelligence_payload_v1("catalog")
        classes = {row["evidence_class"] for row in payload["records"]}
        self.assertIn("SHADOW_ONLY", classes)
        self.assertIn("REPLAY_COUNTERFACTUAL", classes)
        self.assertFalse(any(row["outcome_proven"] for row in payload["records"]))

    def test_coverage_does_not_fabricate_material_influence(self):
        payload = server_extend._backend_intelligence_payload_v1("coverage")
        self.assertEqual(payload["material_use_relationships"], 0)
        self.assertEqual(payload["provider_calls_used"], 0)
        self.assertEqual(payload["llm_calls_used"], 0)

    def test_critical_buy_now_contradiction_fails_closed(self):
        original = server_extend._backend_intelligence_context_v1
        try:
            server_extend._backend_intelligence_context_v1 = lambda: {"rows": [{"recommendation_id": "x", "canonical_lifecycle_state": "BUY_NOW", "freshness": "STALE", "blockers": ["stale"]}]}
            payload = server_extend._backend_intelligence_payload_v1("semantic")
            self.assertEqual(payload["status"], "SEMANTIC_FAIL_CLOSED")
            self.assertEqual(payload["critical_contradiction_count"], 1)
            phase_two = server_extend._backend_intelligence_payload_v1("phase2")
            self.assertEqual(phase_two["status"], "PHASE_2_BLOCKED")
        finally:
            server_extend._backend_intelligence_context_v1 = original

    def test_horizon_and_symbol_views_do_not_fabricate_evidence(self):
        horizons = server_extend._backend_intelligence_payload_v1("horizons")
        symbols = server_extend._backend_intelligence_payload_v1("symbol")
        for row in horizons.get("candidates", []):
            self.assertTrue(all(item["completeness"] == "INSUFFICIENT_EVIDENCE" for item in row["horizons"]))
        for row in symbols.get("profiles", []):
            self.assertEqual(row["quality_label"], "INSUFFICIENT_EVIDENCE")

    def test_sector_and_fundamental_context_are_cache_only(self):
        for kind in ("sector", "catalyst"):
            payload = server_extend._backend_intelligence_payload_v1(kind)
            self.assertEqual(payload["provider_calls_used"], 0)
            self.assertEqual(payload["broker_actions_used"], 0)
            self.assertEqual(payload["llm_calls_used"], 0)
            for row in payload.get("rows", []):
                self.assertTrue(row["advisory_only"])

    def test_entry_readiness_preserves_execution_distinctions(self):
        original = server_extend._backend_intelligence_context_v1
        try:
            server_extend._backend_intelligence_context_v1 = lambda: {
                "rows": [{
                    "recommendation_id": "entry:NVDA",
                    "symbol": "NVDA",
                    "asset_type": "equity",
                    "canonical_lifecycle_state": "BUY_NOW",
                    "freshness": "FRESH",
                    "evidence_quality": "MODERATE",
                    "blockers": [],
                    "horizon": "day_trade",
                    "risk_state": "MODERATE",
                    "liquidity_state": "SUFFICIENT",
                    "paper_autopilot_eligible": False,
                    "broker_eligible": True,
                    "order_submitted": False,
                    "fill_confirmed": False,
                }]
            }
            payload = server_extend._backend_intelligence_payload_v1("entry")
            row = payload["rows"][0]
            self.assertEqual(row["advisory_entry_state"], "BUY_NOW_ADVISORY")
            self.assertTrue(row["advisory_only"])
            self.assertFalse(row["paper_autopilot_eligible"])
            self.assertTrue(row["broker_eligible"])
            self.assertFalse(row["order_submitted"])
            self.assertFalse(row["fill_confirmed"])
            self.assertEqual(payload["provider_calls_used"], 0)
            self.assertEqual(payload["broker_actions_used"], 0)
            self.assertEqual(payload["llm_calls_used"], 0)
        finally:
            server_extend._backend_intelligence_context_v1 = original

    def test_entry_states_fail_closed_or_preserve_canonical_advice(self):
        base = {
            "asset_type": "equity",
            "freshness": "FRESH",
            "evidence_quality": "MODERATE",
            "horizon": "day_trade",
            "risk_state": "MODERATE",
            "liquidity_state": "SUFFICIENT",
            "blockers": [],
        }
        cases = [
            ("NOT_READY", {}, "NOT_READY"),
            ("WATCH", {}, "WATCH"),
            ("APPROACHING_BUY", {}, "APPROACHING_BUY"),
            ("BUY_NOW", {}, "BUY_NOW_ADVISORY"),
            ("WATCH", {"blockers": ["risk_limit"]}, "BLOCKED"),
            ("BUY_NOW", {"freshness": "STALE"}, "INSUFFICIENT_EVIDENCE"),
            ("BUY_NOW", {"liquidity_state": "UNAVAILABLE"}, "INSUFFICIENT_EVIDENCE"),
        ]
        rows = []
        for index, (lifecycle_state, overrides, _) in enumerate(cases):
            rows.append({
                **base,
                **overrides,
                "recommendation_id": f"entry:{index}",
                "symbol": f"E{index}",
                "canonical_lifecycle_state": lifecycle_state,
            })
        output = server_extend._advisory_entry_rows_v1(rows)
        for (_, _, expected), row in zip(cases, output):
            self.assertEqual(row["advisory_entry_state"], expected)
            self.assertTrue(row["advisory_only"])
            self.assertIn("completed_lifecycle", row)

    def test_exit_states_are_evidence_gated_and_never_execute(self):
        base = {
            "asset_type": "equity",
            "position_state": "POSITION_OPEN",
            "freshness": "FRESH",
            "evidence_quality": "MODERATE",
            "blockers": [],
        }
        cases = [
            ("HOLD", {}, "HOLD"),
            ("WATCH", {}, "WATCH"),
            ("HOLD", {"momentum_state": "LOSING_MOMENTUM"}, "LOSING_MOMENTUM"),
            ("HOLD", {"profit_giveback_risk": "HIGH"}, "PROTECT_PROFIT"),
            ("HOLD", {"opportunity_cost_state": "HIGH"}, "APPROACHING_SELL"),
            ("HOLD", {"thesis_state": "BROKEN"}, "SELL_RECOMMENDED"),
            ("SELL_RECOMMENDED", {"freshness": "STALE"}, "INSUFFICIENT_EVIDENCE"),
        ]
        rows = []
        for index, (lifecycle_state, overrides, _) in enumerate(cases):
            rows.append({
                **base,
                **overrides,
                "recommendation_id": f"exit:{index}",
                "symbol": f"X{index}",
                "canonical_lifecycle_state": lifecycle_state,
            })
        output = server_extend._advisory_exit_rows_v1(rows)
        for (_, _, expected), row in zip(cases, output):
            self.assertEqual(row["advisory_exit_state"], expected)
            self.assertTrue(row["advisory_only"])
            self.assertFalse(row["automatic_exit_enabled"])

    def test_exit_practice_never_enables_automatic_exit(self):
        original = server_extend._backend_intelligence_context_v1
        try:
            server_extend._backend_intelligence_context_v1 = lambda: {
                "rows": [{
                    "recommendation_id": "exit:NVDA",
                    "symbol": "NVDA",
                    "asset_type": "equity",
                    "position_state": "POSITION_OPEN",
                    "freshness": "FRESH",
                    "evidence_quality": "MODERATE",
                }]
            }
            payload = server_extend._backend_intelligence_payload_v1("exit")
            row = payload["rows"][0]
            self.assertEqual(row["advisory_exit_state"], "HOLD")
            self.assertTrue(row["advisory_only"])
            self.assertFalse(row["automatic_exit_enabled"])
            self.assertEqual(payload["broker_actions_used"], 0)
        finally:
            server_extend._backend_intelligence_context_v1 = original

    def test_phase_two_validation_checks_actual_adapter_semantics(self):
        original = server_extend._backend_intelligence_context_v1
        try:
            server_extend._backend_intelligence_context_v1 = lambda: {
                "rows": [{
                    "recommendation_id": "phase:NVDA",
                    "symbol": "NVDA",
                    "asset_type": "equity",
                    "canonical_lifecycle_state": "BUY_NOW",
                    "freshness": "FRESH",
                    "evidence_quality": "MODERATE",
                    "horizon": "day_trade",
                    "risk_state": "MODERATE",
                    "liquidity_state": "SUFFICIENT",
                    "blockers": [],
                }]
            }
            payload = server_extend._backend_intelligence_payload_v1("phase2")
            self.assertEqual(payload["status"], "PHASE_2_PASS")
            self.assertFalse(payload["failed_checks"])
            self.assertTrue(payload["checks"]["advisory_execution_distinct"])
            self.assertTrue(payload["checks"]["buy_now_advisory_evidence_gated"])
            self.assertTrue(payload["checks"]["zero_rendering_calls"])
            self.assertTrue(payload["checks"]["behavior_unchanged"])
        finally:
            server_extend._backend_intelligence_context_v1 = original

    def test_cortex_audit_emits_structured_advisory_issues(self):
        payload = server_extend._cortex_effectiveness_audit_payload_v1()
        self.assertEqual(payload["endpoint"], "/api/cortex_effectiveness_audit_v1")
        self.assertTrue(payload["cortex_advisory_only"])
        self.assertGreater(payload["issue_count"], 0)
        required = {
            "issue_id", "category", "severity", "source", "affected_consumers", "asset_class",
            "symbols", "evidence", "root_cause", "current_impact", "future_impact",
            "safe_repair_available", "human_review_required", "next_action", "first_observed",
            "last_observed", "recurrence_count", "resolved",
        }
        for issue in payload["issues"]:
            self.assertTrue(required.issubset(issue))
        self.assertEqual(payload["provider_calls_used"], 0)
        self.assertFalse(payload["behavior_safe_to_apply"])

    def test_future_bottleneck_audit_is_bounded_and_classifies_repairs(self):
        payload = server_extend._intelligence_future_bottleneck_audit_payload_v1()
        self.assertEqual(payload["endpoint"], "/api/intelligence_future_bottleneck_audit_v1")
        self.assertTrue(payload["full_history_scan_performed"] is False)
        self.assertGreater(payload["bottleneck_count"], 0)
        for item in payload["bottlenecks"]:
            for field in ("category", "severity", "evidence", "affected_files_or_functions", "current_impact", "future_impact", "safe_immediate_repair", "deferred_repair", "human_review_required"):
                self.assertIn(field, item)

    def test_copilot_wiring_preserves_canonical_state_and_execution_fields(self):
        payload = server_extend._backend_intelligence_copilot_wiring_audit_payload_v1()
        self.assertEqual(payload["canonical_engine"], "_astra_copilot_suite_v1")
        self.assertTrue(payload["stable_recommendation_ids"])
        self.assertTrue(payload["canonical_state_preserved"])
        self.assertTrue(payload["no_fabricated_context"])
        self.assertTrue(payload["advisory_execution_distinctions_preserved"])

    def test_build_a_validator_passes_with_cached_inputs(self):
        payload = server_extend._astra_backend_intelligence_build_validation_payload_v1()
        self.assertEqual(payload["status"], "BUILD_A_PASS")
        self.assertFalse(payload["failed_checks"])
        self.assertEqual(payload["semantic_contradiction_count"], 0)
        self.assertEqual(payload["provider_calls_used"], 0)
        self.assertEqual(payload["broker_actions_used"], 0)
        self.assertEqual(payload["llm_calls_used"], 0)

    def test_build_a_validator_blocks_critical_semantic_contradiction(self):
        original = server_extend._backend_intelligence_context_v1
        try:
            server_extend._backend_intelligence_context_v1 = lambda: {
                "rows": [{
                    "recommendation_id": "contradiction:NVDA",
                    "symbol": "NVDA",
                    "asset_type": "equity",
                    "canonical_lifecycle_state": "BUY_NOW",
                    "freshness": "STALE",
                    "evidence_quality": "MODERATE",
                    "horizon": "day_trade",
                    "blockers": ["stale_context"],
                }]
            }
            payload = server_extend._astra_backend_intelligence_build_validation_payload_v1()
            self.assertEqual(payload["status"], "BUILD_A_BLOCKED")
            self.assertGreater(payload["semantic_contradiction_count"], 0)
            self.assertIn("critical_semantic_contradictions_zero", payload["failed_checks"])
        finally:
            server_extend._backend_intelligence_context_v1 = original


if __name__ == "__main__":
    unittest.main()
