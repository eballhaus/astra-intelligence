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


if __name__ == "__main__":
    unittest.main()
