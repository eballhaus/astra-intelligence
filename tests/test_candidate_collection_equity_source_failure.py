import os
import unittest
from unittest.mock import Mock, patch

from engine.paper_autopilot import PaperAutopilotEngine


class CandidateCollectionEquitySourceFailureTests(unittest.TestCase):
    def _engine(self, top_buys_fn):
        engine = PaperAutopilotEngine.__new__(PaperAutopilotEngine)
        engine.get_crypto_candidate_rows_fn = None
        engine.get_top_buys_fn = top_buys_fn
        engine._runtime_state = {
            "crypto_rankings_snapshot_v1": {
                "rows": [
                    {"symbol": "ETH/USD", "price": 2500.0},
                    {"symbol": "ETH/USD", "price": 2500.0},
                ]
            }
        }
        for name in (
            "edge_development_suite",
            "trade_management_portfolio_suite",
            "adaptive_learning_infrastructure_suite",
            "replay_lifecycle_expectancy_suite",
            "regime_execution_survivability_suite",
            "adaptive_execution_exit_v2_suite",
            "market_calendar_knowledge_suite",
            "broad_universe_intake_promotion_suite",
            "paper_opportunity_allocator",
            "profit_seeking_exploration_suite",
            "portfolio_diversification_v2_suite",
        ):
            setattr(engine, name, None)
        engine.broker = Mock()
        return engine

    def _assert_crypto_row_survives(self, top_buys_fn):
        engine = self._engine(top_buys_fn)
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api"}):
            rows = engine._collect_candidate_rows()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "ETH/USD")
        self.assertEqual(rows[0]["asset_class"], "crypto")
        self.assertEqual(rows[0]["asset_type"], "crypto")
        self.assertEqual(rows[0]["lane_id"], "CRYPTO")
        engine.broker.assert_not_called()
        return engine, rows

    def test_crypto_rows_survive_equity_source_exception_and_are_deduplicated(self):
        source = Mock(side_effect=RuntimeError("equity discovery unavailable"))
        engine, _ = self._assert_crypto_row_survives(source)
        source.assert_called_once_with()
        self.assertNotIn("equity_discovery_rebuild_v1", engine._runtime_state)

    def test_crypto_rows_survive_non_dict_equity_payload(self):
        source = Mock(return_value=[{"symbol": "AAPL"}])
        self._assert_crypto_row_survives(source)
        source.assert_called_once_with()

    def test_normal_equity_and_crypto_collection_keeps_deduplication(self):
        source = Mock(return_value={
            "stocks": {
                "final": [{"symbol": "AAPL"}, {"symbol": "AAPL", "price": 100.0}],
                "qualified": [{"symbol": "MSFT"}],
            },
            "crypto": {"final": [{"symbol": "ETH/USD", "price": 2500.0}]},
        })
        engine = self._engine(source)
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api"}):
            rows = engine._collect_candidate_rows()

        self.assertEqual([row["symbol"] for row in rows], ["ETH/USD", "AAPL", "MSFT"])
        self.assertEqual(rows[0]["asset_class"], "crypto")
        self.assertEqual(rows[0]["asset_type"], "crypto")
        self.assertEqual(rows[0]["lane_id"], "CRYPTO")
        engine.broker.assert_not_called()
        source.assert_called_once_with()

    def test_absent_equity_source_keeps_existing_crypto_only_behavior(self):
        engine = self._engine(None)
        engine.get_top_buys_fn = None
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api"}):
            rows = engine._collect_candidate_rows()

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["asset_type"] == "crypto" for row in rows))
        engine.broker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
