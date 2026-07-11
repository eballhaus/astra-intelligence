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


if __name__ == "__main__":
    unittest.main()
