"""Focused native-market timestamp handoff regression tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from engine.astra_canonical_market_timestamp_v1 import canonical_market_timestamp_v1
from engine.paper_autopilot import PaperAutopilotEngine


def _iso(offset_seconds: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


class MarketObservationTimestampHandoffTests(unittest.TestCase):
    def _engine(self) -> PaperAutopilotEngine:
        directory = tempfile.TemporaryDirectory(prefix="astra_timestamp_handoff_")
        self.addCleanup(directory.cleanup)
        return PaperAutopilotEngine(
            db_path=os.path.join(directory.name, "paper.db"),
            state_path=os.path.join(directory.name, "state.json"),
            enabled=False,
        )

    def test_quote_contract_accepts_native_time_without_using_receive_time(self):
        result = canonical_market_timestamp_v1(
            {"provider_native_timestamp": _iso(-2), "receive_timestamp": _iso()},
            source_type="QUOTE",
            max_age_seconds=20,
        )
        self.assertEqual(result["source_field"], "provider_native_timestamp")
        self.assertEqual(result["provider_native_timestamp"], result["canonical_timestamp"])
        self.assertNotEqual(result["provider_native_timestamp"], result["retrieval_timestamp"])
        self.assertTrue(result["executable_freshness"])

    def test_missing_or_stale_native_time_remains_fail_closed(self):
        missing = canonical_market_timestamp_v1({"receive_timestamp": _iso()}, source_type="QUOTE", max_age_seconds=20)
        stale = canonical_market_timestamp_v1({"provider_native_timestamp": _iso(-60)}, source_type="QUOTE", max_age_seconds=20)
        self.assertEqual(missing["freshness_status"], "UNAVAILABLE")
        self.assertTrue(missing["market_observation_unavailable"])
        self.assertEqual(stale["freshness_status"], "STALE")
        self.assertFalse(stale["executable_freshness"])

    def test_management_reuses_only_exact_position_matched_observation(self):
        engine = self._engine()
        engine.get_latest_row_fn = lambda *_args: self.fail("cached observation should avoid a new quote request")
        engine._runtime_state["active_equity_fmp_observations_v1"] = {
            "observations": {
                "AAPL": {
                    "symbol": "AAPL",
                    "canonical_position_id": "position-a",
                    "provider": "FMP",
                    "provider_native_timestamp": _iso(-2),
                    "receive_timestamp": _iso(),
                    "price": 100.0,
                }
            }
        }
        quotes = engine._loss_containment_quote_evidence(
            {"AAPL": {"asset_type": "stock", "current_price": 99.0}},
            managed_rows_by_symbol={"AAPL": {"symbol": "AAPL", "position_id": "position-a", "lane_id": "DAY"}},
        )
        quote = quotes["AAPL"]
        self.assertEqual(quote["provider_native_timestamp"], engine._runtime_state["active_equity_fmp_observations_v1"]["observations"]["AAPL"]["provider_native_timestamp"])
        self.assertEqual(quote["retrieval_timestamp"], quote["receive_timestamp"])
        self.assertTrue(canonical_market_timestamp_v1(quote, source_type="QUOTE", max_age_seconds=20)["executable_freshness"])
        self.assertEqual(engine._open_position_review_quote_v1({"symbol": "AAPL", "asset_type": "stock"}, {}, quotes), quote)

    def test_fmp_observation_accepts_canonical_position_id_without_legacy_lifecycle_id(self):
        engine = self._engine()

        class Router:
            def get_quote(self, *_args, **_kwargs):
                return {
                    "provider_used": "FMP",
                    "price": 100.0,
                    "provider_quote_timestamp": _iso(-2),
                    "attempted_providers": ["FMP"],
                }

        engine._legacy_swing_fmp_router = Router()
        engine._fetch_open_positions = lambda asset_type=None: [{
            "symbol": "AAPL", "asset_type": "stock", "status": "OPEN", "quantity": 1,
            "lane_id": "DAY", "position_id": "position-a", "entry_fill_id": "fill-a",
        }]
        state = engine._refresh_active_equity_fmp_observations_v1()
        self.assertEqual(state["canonical_active_equity_symbols"], ["AAPL"])
        self.assertEqual(state["observations"]["AAPL"]["canonical_position_id"], "position-a")

    def test_mismatched_position_observation_cannot_be_reused(self):
        engine = self._engine()
        engine.get_latest_row_fn = lambda *_args: {}
        engine._runtime_state["active_equity_fmp_observations_v1"] = {
            "observations": {
                "AAPL": {"canonical_position_id": "old-position", "provider_native_timestamp": _iso(), "price": 100.0}
            }
        }
        quotes = engine._loss_containment_quote_evidence(
            {"AAPL": {"asset_type": "stock", "current_price": 99.0}},
            managed_rows_by_symbol={"AAPL": {"symbol": "AAPL", "position_id": "position-a", "lane_id": "DAY"}},
        )
        result = canonical_market_timestamp_v1(quotes["AAPL"], source_type="QUOTE", max_age_seconds=20)
        self.assertTrue(result["market_observation_unavailable"])

    def test_stale_observation_does_not_suppress_existing_fallback(self):
        engine = self._engine()
        calls: list[str] = []
        engine.get_latest_row_fn = lambda symbol, _asset: calls.append(symbol) or {
            "symbol": symbol,
            "provider_used": "ALPACA",
            "provider_native_timestamp": _iso(-2),
            "price": 101.0,
        }
        engine._runtime_state["active_equity_fmp_observations_v1"] = {
            "observations": {
                "AAPL": {
                    "symbol": "AAPL",
                    "canonical_position_id": "position-a",
                    "provider": "FMP",
                    "provider_native_timestamp": _iso(-60),
                    "receive_timestamp": _iso(-55),
                    "price": 100.0,
                }
            }
        }
        quotes = engine._loss_containment_quote_evidence(
            {"AAPL": {"asset_type": "stock", "current_price": 99.0}},
            managed_rows_by_symbol={"AAPL": {"symbol": "AAPL", "position_id": "position-a", "lane_id": "DAY"}},
        )
        self.assertEqual(calls, ["AAPL"])
        self.assertEqual(quotes["AAPL"]["provider_used"], "ALPACA")
        self.assertTrue(canonical_market_timestamp_v1(quotes["AAPL"], source_type="QUOTE", max_age_seconds=20)["executable_freshness"])


if __name__ == "__main__":
    unittest.main()
