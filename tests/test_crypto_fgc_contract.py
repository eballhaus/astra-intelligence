import ast
import pathlib
import tempfile
import unittest

from engine.candidate_execution_integrity_v1 import normalize_crypto_pair_strict
from engine.paper_autopilot import PaperAutopilotEngine, _paper_attribution_client_order_id
import engine.paper_autopilot as paper_autopilot_module


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "server_extend.py"


class CryptoFGCContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SERVER.read_text(encoding="utf-8")
        ast.parse(cls.source)

    def test_readiness_route_and_builder_exist(self):
        self.assertIn("_crypto_paper_execution_readiness_v1_payload", self.source)
        self.assertIn('/api/crypto_paper_execution_readiness_v1', self.source)

    def test_readiness_is_fail_closed_and_diagnostic_only(self):
        self.assertIn('"CRYPTO_PAPER_READY_NO_ELIGIBLE_TRADE"', self.source)
        self.assertIn('"no_order_submitted": True', self.source)
        self.assertIn('"broker_read_calls_used": 0', self.source)
        self.assertIn('"automatic_promotions_enabled": False', self.source)

    def test_canonical_outcome_audit_reports_lineage_and_evidence_separation(self):
        self.assertIn('"broker_truth_attribution_coverage_pct"', self.source)
        self.assertIn('"official_metrics_source": "broker_confirmed_complete_paper_round_trips_only"', self.source)
        self.assertIn('"diagnostic_sources_separated"', self.source)
        self.assertIn('"evidence_consumption_status"', self.source)

    def test_bounded_crypto_audit_script_exists(self):
        script = ROOT / "scripts" / "astra_crypto_audit.sh"
        self.assertTrue(script.exists())
        self.assertIn("/api/crypto_paper_execution_readiness_v1", script.read_text(encoding="utf-8"))
        self.assertNotIn("/probe", script.read_text(encoding="utf-8"))

    def test_strict_pair_normalization_preserves_asset_class_boundary(self):
        valid = normalize_crypto_pair_strict("btc-usd", asset_class="crypto")
        self.assertEqual(valid["normalized_symbol"], "BTC/USD")
        self.assertFalse(normalize_crypto_pair_strict("BTC/USD", asset_class="equity")["ok"])
        self.assertFalse(normalize_crypto_pair_strict("BTC", asset_class="crypto")["ok"])

    def test_attribution_client_order_id_is_stable_and_broker_safe(self):
        row = {
            "symbol": "BTC/USD",
            "recommendation_id": "copilot:abc123",
            "decision_id": "decision:abc123",
            "eligibility_evaluation_id": "eligibility:abc123",
            "candidate_id": "crypto:btc",
        }
        client_id = _paper_attribution_client_order_id(row)
        self.assertEqual(client_id, _paper_attribution_client_order_id(dict(row)))
        self.assertLessEqual(len(client_id), 48)
        self.assertTrue(client_id.startswith("astra-"))

    def test_paper_position_schema_has_attribution_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperAutopilotEngine(db_path=str(pathlib.Path(tmp) / "paper.db"), state_path=str(pathlib.Path(tmp) / "state.json"))
            with engine._connect() as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(paper_positions)").fetchall()}
            self.assertTrue({
                "source_recommendation_id",
                "source_decision_id",
                "source_eligibility_evaluation_id",
            }.issubset(columns))

    def test_paper_position_persists_attribution_after_stubbed_paper_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperAutopilotEngine(
                db_path=str(pathlib.Path(tmp) / "paper.db"),
                state_path=str(pathlib.Path(tmp) / "state.json"),
            )
            engine._position_tracker = None
            engine._alpaca_paper_broker_enabled = lambda: True
            row = {
                "symbol": "NVDA",
                "asset_type": "stock",
                "price": 100.0,
                "recommendation_id": "copilot:rec-1",
                "decision_id": "decision:1",
                "eligibility_evaluation_id": "eligibility:1",
                "candidate_id": "candidate:1",
                "paper_entry_horizon_style": "day_trade",
                "trade_horizon_style": "day_trade",
            }
            client_id = _paper_attribution_client_order_id(row)
            original_lifecycle = paper_autopilot_module.create_lifecycle_record
            paper_autopilot_module.create_lifecycle_record = None
            try:
                engine._submit_alpaca_paper_entry_order = lambda *_args, **_kwargs: {
                    "ok": True,
                    "paper_order_submitted": True,
                    "recommendation_id": row["recommendation_id"],
                    "decision_id": row["decision_id"],
                    "eligibility_evaluation_id": row["eligibility_evaluation_id"],
                    "candidate_id": row["candidate_id"],
                    "client_order_id": client_id,
                    "order": {"id": "broker-order-1", "client_order_id": client_id},
                }
                result = engine._open_position_from_row(row)
            finally:
                paper_autopilot_module.create_lifecycle_record = original_lifecycle
            self.assertTrue(result.get("ok"), result)
            with engine._connect() as conn:
                saved = dict(conn.execute("SELECT * FROM paper_positions").fetchone())
            self.assertEqual(saved["source_recommendation_id"], row["recommendation_id"])
            self.assertEqual(saved["source_decision_id"], row["decision_id"])
            self.assertEqual(saved["source_eligibility_evaluation_id"], row["eligibility_evaluation_id"])
            self.assertEqual(saved["source_client_order_id"], client_id)


if __name__ == "__main__":
    unittest.main()
