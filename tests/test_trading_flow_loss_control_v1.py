"""Production-path regressions for trusted quote assignment and loss safety."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from engine.astra_loss_containment_engine_v1 import evaluate_position_loss_containment_v1
from engine.paper_autopilot import PaperAutopilotEngine
import server_extend


def _iso(offset_seconds: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def _candidate(symbol: str = "AAPL") -> dict:
    return {
        "symbol": symbol,
        "asset_type": "stock",
        "asset_class": "equity",
        "lane_id": "DAY",
        "paper_entry_horizon_style": "day_trade",
        "candidate_id": f"candidate-{symbol}",
        "recommendation_id": f"recommendation-{symbol}",
        "candidate_generated_at": _iso(),
        "generated_at": _iso(),
        "quality_score": 90.0,
        "buy_quality_score": 90.0,
        "confidence": 90.0,
        "consensus_strength": 90.0,
        "consensus_score": 90.0,
        "paper_ready": True,
        "buy_eligibility": "paper_ready_candidate",
    }


class TrustedQuoteCandidateFlowTests(unittest.TestCase):
    def _engine(self, latest_quote: dict) -> PaperAutopilotEngine:
        directory = tempfile.TemporaryDirectory(prefix="astra_trusted_quote_")
        self.addCleanup(directory.cleanup)
        engine = PaperAutopilotEngine(
            db_path=os.path.join(directory.name, "paper.db"),
            state_path=os.path.join(directory.name, "state.json"),
            enabled=False,
            get_latest_row_fn=lambda _symbol, _asset: dict(latest_quote),
        )
        engine._alpaca_safety_snapshot = lambda: {
            "paper_mode_verified": True,
            "broker_execution_enabled": True,
            "live_endpoint_rejected": True,
        }
        return engine

    def _trace(self, engine: PaperAutopilotEngine, row: dict) -> tuple[dict, bool, str]:
        activation = {
            "execution_enabled": True,
            "exact_blockers": [],
            "lane_enabled": True,
        }
        contract = {"order_ready_allowed": True, "contract_state": "CONTRACT_COMPLETE", "consumer_acknowledgements": {}}
        with patch("engine.paper_autopilot.canonical_lane_activation_contract", return_value=activation), patch(
            "engine.paper_autopilot.build_pretrade_decision_contract", return_value=contract
        ):
            trace, allowed, reason, _meta = engine._candidate_trace_row(
                row,
                open_syms=set(),
                stock_capacity=1,
                crypto_capacity=0,
                total_capacity=1,
            )
        return trace, allowed, reason

    def test_fresh_fmp_quote_is_assigned_before_day_preflight(self):
        engine = self._engine({
            "symbol": "AAPL", "price": 101.25, "provider_used": "FMP",
            "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
        })
        trace, allowed, reason = self._trace(engine, _candidate())
        self.assertTrue(allowed, reason)
        self.assertTrue(trace["valid_quote"])
        self.assertTrue(trace["trusted_quote_for_buys"])
        self.assertEqual(trace["quote_assignment_state"], "ASSIGNED_AND_CONSUMED")
        self.assertEqual(trace["quote_assignment_consumer"], "PaperAutopilot.candidate_preflight")
        self.assertEqual(trace["market_observation_timestamp"], trace["provider_quote_timestamp"])

    def test_fresh_alpaca_quote_is_assigned_before_swing_preflight(self):
        engine = self._engine({
            "symbol": "MSFT", "price": 420.0, "provider_used": "ALPACA",
            "quote_timestamp": _iso(), "market_source_type": "QUOTE",
        })
        row = _candidate("MSFT")
        row.update({"lane_id": "SWING", "paper_entry_horizon_style": "swing_trade"})
        trace, allowed, reason = self._trace(engine, row)
        self.assertTrue(allowed, reason)
        self.assertEqual(trace["provider_used"], "ALPACA")
        self.assertTrue(trace["trusted_quote_for_buys"])

    def test_assigned_quote_is_revalidated_without_a_second_provider_lookup(self):
        calls = []
        quote = {
            "symbol": "AAPL", "price": 101.25, "provider_used": "FMP",
            "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
        }
        directory = tempfile.TemporaryDirectory(prefix="astra_quote_dedup_")
        self.addCleanup(directory.cleanup)
        engine = PaperAutopilotEngine(
            db_path=os.path.join(directory.name, "paper.db"),
            state_path=os.path.join(directory.name, "state.json"),
            enabled=False,
            get_latest_row_fn=lambda _symbol, _asset: calls.append(1) or dict(quote),
        )
        assigned = engine._assign_trusted_quote_to_candidate(_candidate())
        self.assertEqual(len(calls), 1)
        self._trace(engine, assigned)
        self.assertEqual(len(calls), 1)

    def test_missing_or_stale_native_quote_blocks_candidate_without_utc_fallback(self):
        for quote, expected in (
            ({"symbol": "AAPL", "price": 100.0, "provider_used": "FMP"}, "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE"),
            ({"symbol": "AAPL", "price": 100.0, "provider_used": "FMP", "quote_timestamp": _iso(-120)}, "STALE_PROVIDER_NATIVE_TIMESTAMP"),
        ):
            with self.subTest(expected=expected):
                engine = self._engine(quote)
                trace, allowed, _reason = self._trace(engine, _candidate())
                self.assertFalse(allowed)
                self.assertFalse(trace["valid_quote"])
                self.assertFalse(trace["trusted_quote_for_buys"])
                self.assertEqual(trace["quote_assignment_blocker"], expected)

    def test_submission_preflight_never_marks_timestampless_price_fresh(self):
        engine = self._engine({})
        merged = engine._merge_latest_quote_for_submission(
            _candidate(), {"symbol": "AAPL", "price": 100.0, "provider_used": "ALPACA"}, 100.0
        )
        self.assertFalse(merged["valid_quote"])
        self.assertFalse(merged["trusted_quote_for_buys"])
        self.assertIsNone(merged["quote_age_seconds"])
        self.assertEqual(merged["quote_assignment_blocker"], "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE")

    def test_exit_evaluation_rejects_broker_snapshot_retrieval_time_as_quote_evidence(self):
        engine = self._engine({})
        should_exit, reason = engine._evaluate_exit(
            {"symbol": "AAPL", "entry_price": 100.0, "hold_seconds": 9999, "lifecycle_notes": "{}"},
            {
                "symbol": "AAPL", "price": 90.0,
                "market_source_type": "BROKER_POSITION_SNAPSHOT",
                "retrieval_timestamp": _iso(), "source": "alpaca_broker_positions",
            },
        )
        self.assertFalse(should_exit)
        self.assertEqual(reason, "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE")

    def test_symbol_mismatch_and_empty_quote_are_rejected_before_preflight(self):
        for quote, expected in (
            ({"symbol": "MSFT", "price": 100.0, "quote_timestamp": _iso()}, "QUOTE_SYMBOL_MISMATCH"),
            ({"symbol": "AAPL", "price": 0.0, "quote_timestamp": _iso()}, "QUOTE_PRICE_UNAVAILABLE"),
        ):
            with self.subTest(expected=expected):
                engine = self._engine(quote)
                trace, allowed, _reason = self._trace(engine, _candidate())
                self.assertFalse(allowed)
                self.assertEqual(trace["quote_assignment_blocker"], expected)

    def test_partial_cycle_uses_canonical_quote_preflight_without_submission(self):
        """The bounded legacy path must not infer quote freshness from a row timestamp."""
        directory = tempfile.TemporaryDirectory(prefix="astra_partial_quote_")
        self.addCleanup(directory.cleanup)
        engine = PaperAutopilotEngine(
            db_path=os.path.join(directory.name, "paper.db"),
            state_path=os.path.join(directory.name, "state.json"),
            enabled=True,
            get_latest_row_fn=lambda _symbol, _asset: {
                "symbol": "AAPL",
                "price": 101.25,
                "provider_used": "FMP",
                "provider_quote_timestamp": _iso(),
                "market_source_type": "QUOTE",
            },
        )
        engine._refresh_legacy_swing_canary_pre_submit = lambda _positions: {
            "market_activity": {"cycle_state": "CYCLE_PARTIAL_BUDGET"}
        }
        engine._alpaca_safety_snapshot = lambda: {
            "paper_mode_verified": True,
            "broker_execution_enabled": True,
            "live_endpoint_rejected": True,
        }
        engine._broker_open_symbols_snapshot = lambda: {
            "broker_open_symbols": set(),
            "broker_position_by_symbol": {},
            "broker_reconciliation_active": True,
            "broker_positions_fetch_ok": True,
            "broker_open_positions_count": 0,
        }
        engine._fetch_open_positions = lambda: []
        engine._evidence_capacity_snapshot_v1 = lambda *_args: {"capacity_authority_state": "CURRENT"}
        engine._collect_candidate_rows = lambda: [_candidate()]
        engine.refresh_crypto_rankings_fn = lambda: {"status": "CURRENT"}
        activation = {"execution_enabled": True, "exact_blockers": [], "lane_enabled": True}
        contract = {"order_ready_allowed": True, "contract_state": "CONTRACT_COMPLETE", "consumer_acknowledgements": {}}

        with patch("engine.paper_autopilot.canonical_lane_activation_contract", return_value=activation), patch(
            "engine.paper_autopilot.build_pretrade_decision_contract", return_value=contract
        ):
            result = engine.run_cycle()

        trace = engine._runtime_state["last_execution_trace"]
        candidate_trace = trace["per_candidate_decision_trace"][0]
        self.assertEqual(result["orders_submitted"], 0)
        self.assertTrue(candidate_trace["valid_quote"])
        self.assertEqual(candidate_trace["quote_assignment_state"], "ASSIGNED_AND_CONSUMED")
        self.assertTrue(candidate_trace["partial_cycle_observation_only"])
        self.assertFalse(candidate_trace["submit_order"])


class ServerQuoteAdapterTests(unittest.TestCase):
    def test_worker_adapter_preserves_router_native_timestamp_without_utc_fallback(self):
        provider_timestamp = _iso()
        with patch.object(
            server_extend.PAPER_AUTOPILOT._legacy_swing_fmp_router,
            "get_quote",
            return_value={"symbol": "AAPL", "price": 101.0, "provider_used": "ALPACA", "quote_timestamp": provider_timestamp},
        ):
            quote = server_extend._paper_single_symbol_quote("AAPL", "stock")
        self.assertEqual(quote["quote_timestamp"], provider_timestamp)
        self.assertEqual(quote["market_source_type"], "QUOTE")
        self.assertNotIn("timestamp", quote)

    def test_rankings_generic_timestamp_cannot_become_quote_timestamp(self):
        provider_timestamp = _iso()
        with patch.object(server_extend, "LAST_RANKINGS", {"stocks": [{"symbol": "AAPL", "price": 99.0, "timestamp": _iso()}], "crypto": {}}), patch.object(
            server_extend.PAPER_AUTOPILOT._legacy_swing_fmp_router,
            "get_quote",
            return_value={"symbol": "AAPL", "price": 101.0, "provider_used": "FMP", "quote_timestamp": provider_timestamp},
        ), patch.object(server_extend, "_ensure_latest_rankings"), patch.object(server_extend, "_snapshot_age_seconds", return_value=0.0):
            quote = server_extend._paper_latest_symbol_snapshot("AAPL", "stock")
        self.assertEqual(quote["quote_timestamp"], provider_timestamp)
        self.assertEqual(quote["price"], 101.0)

    def test_unproven_cached_quote_timestamp_cannot_bypass_worker_router(self):
        provider_timestamp = _iso()
        with patch.object(
            server_extend,
            "LAST_RANKINGS",
            {"stocks": [{"symbol": "AAPL", "price": 99.0, "quote_timestamp": _iso()}], "crypto": {}},
        ), patch.object(
            server_extend.PAPER_AUTOPILOT._legacy_swing_fmp_router,
            "get_quote",
            return_value={"symbol": "AAPL", "price": 101.0, "provider_used": "ALPACA", "quote_timestamp": provider_timestamp},
        ) as router, patch.object(server_extend, "_ensure_latest_rankings"), patch.object(server_extend, "_snapshot_age_seconds", return_value=0.0):
            quote = server_extend._paper_latest_symbol_snapshot("AAPL", "stock")
        router.assert_called_once()
        self.assertEqual(quote["price"], 101.0)
        self.assertEqual(quote["quote_timestamp"], provider_timestamp)

    def test_stale_or_future_cached_provider_time_routes_to_fresh_worker_quote(self):
        provider_timestamp = _iso()
        for cached_timestamp in (_iso(-60), _iso(30)):
            with self.subTest(cached_timestamp=cached_timestamp), patch.object(
                server_extend,
                "LAST_RANKINGS",
                {"stocks": [{"symbol": "AAPL", "price": 99.0, "provider_quote_timestamp": cached_timestamp}], "crypto": {}},
            ), patch.object(
                server_extend.PAPER_AUTOPILOT._legacy_swing_fmp_router,
                "get_quote",
                return_value={"symbol": "AAPL", "price": 101.0, "provider_used": "ALPACA", "quote_timestamp": provider_timestamp},
            ) as router, patch.object(server_extend, "_ensure_latest_rankings"), patch.object(server_extend, "_snapshot_age_seconds", return_value=0.0):
                quote = server_extend._paper_latest_symbol_snapshot("AAPL", "stock")
            router.assert_called_once()
            self.assertEqual(quote["price"], 101.0)
            self.assertEqual(quote["quote_timestamp"], provider_timestamp)


class LossControlProductionContractTests(unittest.TestCase):
    def test_existing_hard_loss_policy_never_returns_healthy_hold(self):
        decision = evaluate_position_loss_containment_v1({
            "position_id": "managed-aapl", "symbol": "AAPL", "lane_id": "DAY",
            "entry_price": 100.0, "current_price": 96.0, "qty": 10.0,
            "quote_timestamp": _iso(), "position_owner": "DAY", "exit_policy_owner": "DAY",
        })
        self.assertEqual(decision["threshold_state"], "HARD_BOUNDARY_BREACH")
        self.assertEqual(decision["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")
        self.assertFalse(decision["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
