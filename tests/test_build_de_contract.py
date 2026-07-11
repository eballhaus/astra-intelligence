import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "server_extend.py"


class BuildDEContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SERVER.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_required_build_de_routes_exist(self):
        required = {
            "/api/astra_full_system_proof_v1",
            "/api/astra_runtime_performance_audit_v1",
            "/api/broker_truth_accumulation_v2",
            "/api/copilot_effectiveness_attribution_v1",
            "/api/copilot_state_effectiveness_v1",
            "/api/trade_style_horizon_effectiveness_v1",
            "/api/top5_recommendation_attribution_v1",
            "/api/build_de_final_validation_v1",
        }
        self.assertTrue(required.issubset(set(self.source.split('"'))))

    def test_canonical_builder_is_reused(self):
        self.assertIn("_astra_copilot_suite_v1(limit=12, force=False)", self.source)
        self.assertIn('"canonical_engine": "_astra_copilot_suite_v1"', self.source)

    def test_safety_and_evidence_guards_are_present(self):
        self.assertIn('"BUILD_DE_PASS_WITH_DEFERRED_EVIDENCE"', self.source)
        self.assertIn('"recommendation_id_not_persisted_into_broker_truth_records"', self.source)
        self.assertIn('"provider_calls_used": 0', self.source)
        self.assertIn('"broker_actions_used": 0', self.source)
        self.assertIn('"llm_calls_used": 0', self.source)


if __name__ == "__main__":
    unittest.main()
