"""Focused native-market timestamp handoff regression tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from engine.astra_canonical_market_timestamp_v1 import canonical_market_timestamp_v1
from engine.astra_loss_containment_engine_v1 import evaluate_position_loss_containment_v1
from engine.astra_profit_protection_giveback_v1 import evaluate_position_profit_protection_v1
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

    def test_fresh_crypto_handoff_reaches_management_for_compact_position_symbol(self):
        engine = self._engine()
        native_timestamp = _iso(-2)
        receive_timestamp = _iso(-1)
        engine.get_latest_row_fn = lambda *_args: self.fail("canonical crypto handoff should avoid a new quote request")
        engine._runtime_state["crypto_rankings_snapshot_v1"] = {
            "rows": [],
            "crypto_quote_handoffs_v1": [{
                "symbol": "SHIB/USD",
                "quote_received": True,
                "provider_bid": 0.00000538,
                "provider_ask": 0.00000540,
                "provider_quote_timestamp": native_timestamp,
                "quote_observed_at": receive_timestamp,
                "quote_provider": "alpaca",
            }],
        }
        managed = {
            "SHIBUSD": {
                "symbol": "SHIBUSD", "asset_type": "crypto", "lane_id": "CRYPTO",
                "position_id": "crypto-position",
            },
        }
        observations = engine._canonical_active_position_observations_v1(managed)
        quote = observations["SHIBUSD"]
        self.assertEqual(quote["canonical_market_symbol"], "SHIB/USD")
        self.assertEqual(quote["provider_native_timestamp"], native_timestamp)
        self.assertEqual(quote["receive_timestamp"], receive_timestamp)
        self.assertAlmostEqual(quote["price"], 0.00000539)
        self.assertTrue(canonical_market_timestamp_v1(quote, source_type="QUOTE", max_age_seconds=20)["executable_freshness"])

        quotes = engine._loss_containment_quote_evidence(
            {"SHIBUSD": {"symbol": "SHIBUSD", "asset_type": "crypto", "current_price": 0.00000539}},
            managed_rows_by_symbol=managed,
        )
        self.assertEqual(quotes["SHIBUSD"]["provider_native_timestamp"], native_timestamp)
        self.assertEqual(quotes["SHIBUSD"]["position_id"], "crypto-position")

    def test_stale_crypto_handoff_remains_fail_closed(self):
        engine = self._engine()
        engine.get_latest_row_fn = lambda *_args: {}
        engine._runtime_state["crypto_rankings_snapshot_v1"] = {
            "crypto_quote_handoffs_v1": [{
                "symbol": "ETH/USD",
                "quote_received": True,
                "provider_bid": 2490.0,
                "provider_ask": 2491.0,
                "provider_quote_timestamp": _iso(-60),
                "quote_observed_at": _iso(-59),
                "quote_provider": "alpaca",
            }],
        }
        quotes = engine._loss_containment_quote_evidence(
            {"ETHUSD": {"symbol": "ETHUSD", "asset_type": "crypto", "current_price": 2490.5}},
            managed_rows_by_symbol={"ETHUSD": {"symbol": "ETHUSD", "asset_type": "crypto", "lane_id": "CRYPTO", "position_id": "eth-position"}},
        )
        evidence = canonical_market_timestamp_v1(quotes["ETHUSD"], source_type="QUOTE", max_age_seconds=20)
        self.assertFalse(evidence["executable_freshness"])
        self.assertEqual(evidence["freshness_status"], "UNAVAILABLE")

    def test_fresh_crypto_handoff_wins_over_stale_legacy_observation(self):
        engine = self._engine()
        native_timestamp = _iso(-2)
        engine.get_latest_row_fn = lambda *_args: self.fail("fresh canonical handoff should win without a provider call")
        engine._runtime_state["active_equity_fmp_observations_v1"] = {
            "observations": {
                "ETHUSD": {
                    "symbol": "ETHUSD", "canonical_position_id": "eth-position",
                    "provider_native_timestamp": _iso(-60), "price": 2480.0,
                },
            },
        }
        engine._runtime_state["crypto_rankings_snapshot_v1"] = {
            "crypto_quote_handoffs_v1": [{
                "symbol": "ETH/USD", "quote_received": True,
                "provider_bid": 2490.0, "provider_ask": 2491.0,
                "provider_quote_timestamp": native_timestamp,
                "quote_observed_at": _iso(-1), "quote_provider": "alpaca",
            }],
        }
        observations = engine._canonical_active_position_observations_v1({
            "ETHUSD": {"symbol": "ETHUSD", "asset_type": "crypto", "lane_id": "CRYPTO", "position_id": "eth-position"},
        })
        self.assertEqual(observations["ETHUSD"]["provider_native_timestamp"], native_timestamp)
        self.assertEqual(observations["ETHUSD"]["observation_source"], "crypto_rankings_snapshot_v1.crypto_quote_handoffs_v1")

    def test_crypto_handoff_is_consumed_by_loss_and_profit_management(self):
        engine = self._engine()
        native_timestamp = _iso(-2)
        engine._runtime_state["crypto_rankings_snapshot_v1"] = {
            "crypto_quote_handoffs_v1": [{
                "symbol": "ETH/USD", "quote_received": True,
                "provider_bid": 2490.0, "provider_ask": 2491.0,
                "provider_quote_timestamp": native_timestamp,
                "quote_observed_at": _iso(-1), "quote_provider": "alpaca",
            }],
        }
        open_row = {
            "symbol": "ETHUSD", "asset_type": "crypto", "asset_class": "crypto",
            "position_id": "eth-position", "lane_id": "CRYPTO", "entry_price": 2480.0,
        }
        broker_row = {
            "symbol": "ETHUSD", "asset_type": "crypto", "asset_class": "crypto",
            "current_price": 2490.5, "avg_entry_price": 2480.0, "qty": 1.0,
        }
        quotes = engine._loss_containment_quote_evidence(
            {"ETHUSD": broker_row}, managed_rows_by_symbol={"ETHUSD": open_row},
        )
        with patch("engine.paper_autopilot.run_loss_containment_review_v1", return_value={"state": {"decisions": {}}}) as loss_review:
            engine._loss_containment_review_phase(
                open_rows=[open_row], broker_position_by_symbol={"ETHUSD": broker_row},
                latest_price_by_symbol=quotes, broker_fetch_succeeded=True,
            )
        self.assertEqual(
            loss_review.call_args.kwargs["latest_price_by_symbol"]["ETHUSD"]["provider_native_timestamp"],
            native_timestamp,
        )
        with patch("engine.paper_autopilot.run_profit_protection_review_v1", return_value={"state": {"decisions": {}}}) as profit_review:
            engine._profit_protection_review_phase(
                open_rows=[open_row], broker_position_by_symbol={"ETHUSD": broker_row},
                broker_fetch_succeeded=True,
            )
        self.assertEqual(
            profit_review.call_args.kwargs["broker_positions"]["ETHUSD"]["provider_native_timestamp"],
            native_timestamp,
        )

    def test_loss_management_reuses_recovery_identity_when_db_projection_is_missing(self):
        engine = self._engine()
        native_timestamp = _iso(-2)
        engine._runtime_state["crypto_rankings_snapshot_v1"] = {
            "crypto_quote_handoffs_v1": [{
                "symbol": "ETH/USD", "quote_received": True,
                "provider_bid": 2490.0, "provider_ask": 2491.0,
                "provider_quote_timestamp": native_timestamp,
                "quote_observed_at": _iso(-1), "quote_provider": "alpaca",
            }],
        }
        engine._runtime_state["position_lane_horizon_recovery_v1"] = {
            "positions": [{
                "symbol": "ETHUSD", "asset_class": "crypto", "lane": "CRYPTO",
                "canonical_position_id": "ETH/USD:2026-08-26T20:19:05",
                "canonical_lifecycle_id": "ETH/USD:2026-08-26T20:19:05",
            }],
        }
        quotes = engine._loss_containment_quote_evidence(
            {"ETHUSD": {"symbol": "ETHUSD", "asset_type": "crypto", "current_price": 2490.5}},
            managed_rows_by_symbol={},
        )
        self.assertEqual(quotes["ETHUSD"]["provider_native_timestamp"], native_timestamp)
        self.assertEqual(quotes["ETHUSD"]["canonical_position_id"], "ETH/USD:2026-08-26T20:19:05")

    def test_profit_management_replaces_missing_broker_timestamp_from_fmp_observation(self):
        engine = self._engine()
        native_timestamp = _iso(-2)
        engine._runtime_state["position_lane_horizon_recovery_v1"] = {
            "positions": [{"symbol": "AAPL", "asset_type": "stock", "position_id": "position-a", "lane_id": "DAY"}],
        }
        engine._runtime_state["active_equity_fmp_observations_v1"] = {
            "observations": {
                "AAPL": {
                    "symbol": "AAPL",
                    "canonical_position_id": "position-a",
                    "provider": "FMP",
                    "provider_native_timestamp": native_timestamp,
                    "receive_timestamp": _iso(),
                    "price": 100.0,
                }
            }
        }
        with patch("engine.paper_autopilot.run_profit_protection_review_v1", return_value={"decisions": {}}) as review:
            engine._profit_protection_review_phase(
                open_rows=[{"symbol": "AAPL", "asset_type": "stock", "position_id": "position-a", "lane_id": "DAY"}],
                broker_position_by_symbol={"AAPL": {"symbol": "AAPL", "current_price": 100.0, "provider_native_timestamp": None}},
                broker_fetch_succeeded=True,
            )
        broker_row = review.call_args.kwargs["broker_positions"]["AAPL"]
        self.assertEqual(broker_row["provider_native_timestamp"], native_timestamp)
        self.assertEqual(broker_row["provider_used"], "FMP")
        self.assertNotEqual(broker_row["retrieval_timestamp"], native_timestamp)

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

    def test_management_consumers_accept_existing_native_timestamp_field(self):
        position = {"position_id": "position-a", "symbol": "AAPL", "quantity": 1, "entry_price": 100.0}
        broker = {"symbol": "AAPL", "qty": 1, "avg_entry_price": 100.0, "current_price": 101.0, "provider_native_timestamp": _iso(-2), "retrieval_timestamp": _iso()}
        loss = evaluate_position_loss_containment_v1(position, broker_position=broker, latest_price={})
        profit = evaluate_position_profit_protection_v1(position, broker_position=broker)
        self.assertEqual(loss["provider_native_timestamp"], broker["provider_native_timestamp"])
        self.assertNotIn("MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE", loss["exact_blockers"])
        self.assertEqual(profit["provider_native_timestamp"], broker["provider_native_timestamp"])
        self.assertNotIn("MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE", profit["exact_blockers"])


if __name__ == "__main__":
    unittest.main()
