from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from engine import data_orchestrator
from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.shadow_profit_loss_protection_validation_v1 import build_shadow_profit_loss_protection_validation_v1
from engine.candidate_execution_integrity_v1 import derive_crypto_pretrade_forecast_v1
from engine.astra_premarket_certification_v1 import build_pretrade_decision_contract, enrich_candidate_for_pretrade_contract
import server_extend


NOW = datetime.now(timezone.utc).isoformat()


def _quote(**overrides):
    row = {
        "valid_quote": True, "price": 10.05, "prev_close": 10.0,
        "provider_used": "ALPACA", "provider_name": "ALPACA_MARKET_DATA",
        "quote_timestamp": NOW, "quote_source": "ALPACA_MARKET_DATA",
        "quote_record_id": "alpaca-quote-1", "bid": 10.0, "ask": 10.1,
    }
    row.update(overrides)
    return row


def _lifecycle(lifecycle_id: str, *, closed: bool, verified: bool = True):
    return {
        "lifecycle_id": lifecycle_id, "symbol": "LINK/USD", "asset_class": "crypto", "lane_id": "CRYPTO",
        "entry_price": 10.0, "current_price": 10.2, "entry_price_verified": verified,
        "loss_calibration_eligible": verified, "diagnostic_only": not verified,
        "entry_timestamp": NOW, "current_timestamp": NOW, "closed": closed,
    }


class CryptoDataLifecycleShadowCompletionTests(unittest.TestCase):
    def _completed_bars(self):
        now = datetime.now(timezone.utc)
        rows = []
        for index in range(8):
            close = 100.0 + index
            rows.append({
                "t": (now.replace(microsecond=0)).isoformat().replace("+00:00", "Z"),
                "c": close,
                "h": close + 0.6,
                "l": close - 0.4,
            })
        return rows

    def test_completed_crypto_bars_produce_provenance_backed_pretrade_forecast(self):
        now = datetime.now(timezone.utc)
        row = {
            "symbol": "LINK/USD", "asset_class": "crypto", "lane_id": "CRYPTO",
            "paper_entry_horizon_style": "day_trade", "price": 107.5,
            "provider_quote_timestamp": now.isoformat().replace("+00:00", "Z"),
            "bar_timestamp": now.isoformat().replace("+00:00", "Z"),
            "crypto_risk_pct": 0.9, "completed_bar_return_pct": 0.8,
        }
        forecast = derive_crypto_pretrade_forecast_v1(row, completed_bars=self._completed_bars(), now=now)
        self.assertEqual(forecast["forecast_state"], "FORECAST_COMPLETE")
        self.assertGreater(forecast["expected_target_low"], row["price"])
        self.assertGreater(forecast["expected_target_high"], forecast["expected_target_low"])
        self.assertLess(forecast["expected_downside_range"]["high_pct"], 0.0)
        self.assertEqual(forecast["source_provenance"]["source_system"], "PaperAutopilotWorker.crypto_rankings_snapshot_v1")

    def test_negative_or_incomplete_completed_bar_evidence_remains_fail_closed(self):
        now = datetime.now(timezone.utc)
        bars = self._completed_bars()
        for index, bar in enumerate(bars):
            close = 108.0 - index
            bar.update({"c": close, "h": close + 0.4, "l": close - 0.6})
        forecast = derive_crypto_pretrade_forecast_v1({
            "symbol": "LINK/USD", "asset_class": "crypto", "lane_id": "CRYPTO",
            "paper_entry_horizon_style": "day_trade", "price": 100.0,
            "provider_quote_timestamp": now.isoformat().replace("+00:00", "Z"),
            "bar_timestamp": now.isoformat().replace("+00:00", "Z"),
            "crypto_risk_pct": 1.0, "completed_bar_return_pct": -0.5,
        }, completed_bars=bars, now=now)
        self.assertEqual(forecast["forecast_state"], "INSUFFICIENT_FORECAST_EVIDENCE")
        self.assertIn("LATEST_COMPLETED_BAR_CONTINUATION_NOT_POSITIVE", forecast["missing_inputs"])
        self.assertNotIn("expected_target_high", forecast)

    def test_crypto_forecast_survives_canonical_contract_with_provenance(self):
        now = datetime.now(timezone.utc)
        quote_timestamp = now.isoformat().replace("+00:00", "Z")
        forecast = derive_crypto_pretrade_forecast_v1({
            "symbol": "LINK/USD", "asset_class": "crypto", "lane_id": "CRYPTO",
            "paper_entry_horizon_style": "day_trade", "price": 107.5,
            "provider_quote_timestamp": quote_timestamp, "bar_timestamp": quote_timestamp,
            "crypto_risk_pct": 0.9, "completed_bar_return_pct": 0.8,
        }, completed_bars=self._completed_bars(), now=now)
        row = {
            "symbol": "LINK/USD", "candidate_id": "cand-link", "recommendation_id": "rec-link",
            "lane_id": "CRYPTO", "asset_class": "crypto", "paper_entry_horizon_style": "day_trade",
            # Broad research labels must not override the worker's concrete
            # execution horizon when the pretrade contract computes per-day evidence.
            "intended_horizon": "crypto_multi_horizon",
            "strategy_archetype": "momentum_continuation", "summary": "Completed-bar momentum remains positive.",
            "ranked_reason": "Current completed-bar continuation and liquidity support.",
            "ranking_score": 82.0, "confidence": 82.0, "price": 107.5,
            "provider_quote_timestamp": quote_timestamp, "quote_timestamp": quote_timestamp,
            "candidate_generated_at": quote_timestamp,
            "expires_at": (now.replace(microsecond=0) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "crypto_risk_pct": 0.9, "completed_bar_return_pct": 0.8,
            "crypto_pretrade_forecast_v1": forecast,
            "expected_return_range": forecast["expected_return_range"],
            "expected_return_pct": forecast["expected_return_pct"],
            "expected_target_low": forecast["expected_target_low"],
            "expected_target_high": forecast["expected_target_high"],
            "expected_downside_range": forecast["expected_downside_range"],
            "expected_drawdown": forecast["expected_drawdown"],
            "invalidation_level": forecast["invalidation_level"],
            "expected_return_method": forecast["calculation_method"],
        }
        enriched = enrich_candidate_for_pretrade_contract(row, now=now)
        contract = build_pretrade_decision_contract(enriched, now=now)
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertEqual(contract["intended_horizon"], "day_trade")
        self.assertIsNotNone(contract["expected_return_per_day_range"])
        self.assertEqual(contract["calculation_method"], "crypto_completed_bar_continuation_v1")
        self.assertEqual(contract["target"]["high"], forecast["expected_target_high"])
        self.assertEqual(contract["source_provenance"]["source_system"], "PaperAutopilotWorker.crypto_rankings_snapshot_v1")
        self.assertEqual(contract["field_provenance_v1"]["expected_return_range"]["source_system"], "PaperAutopilotWorker.crypto_rankings_snapshot_v1")

    def test_normalized_quote_preserves_bid_ask_and_lineage(self):
        row, meta = data_orchestrator._quote_to_rank_row("LINK/USD", _quote(), "crypto", NOW)
        self.assertTrue(meta["valid_quote"])
        self.assertEqual(row["bid"], 10.0)
        self.assertEqual(row["ask"], 10.1)
        self.assertAlmostEqual(row["mid"], 10.05)
        self.assertAlmostEqual(row["spread_pct"], 0.9950248756, places=6)
        self.assertEqual(row["quote_record_id"], "alpaca-quote-1")

    def test_snapshot_boundary_restores_dropped_quote_fields(self):
        source, _ = data_orchestrator._quote_to_rank_row("LINK/USD", _quote(), "crypto", NOW)
        restored = server_extend._preserve_crypto_quote_microstructure_v1({"symbol": "LINK/USD"}, source, "alpaca")
        self.assertEqual(restored["bid"], 10.0)
        self.assertEqual(restored["ask"], 10.1)
        self.assertAlmostEqual(restored["spread_pct"], 0.9950248756, places=6)
        self.assertEqual(restored["quote_provider"], "alpaca")

    def test_portfolio_and_ranking_transforms_preserve_microstructure(self):
        source, _ = data_orchestrator._quote_to_rank_row("LINK/USD", _quote(), "crypto", NOW)
        portfolio_rows = server_extend.PORTFOLIO_INTEL.apply([source], asset_type="crypto")
        ranked = server_extend._prioritize_rankings(portfolio_rows)
        final = server_extend._preserve_crypto_quote_microstructure_v1(ranked[0], source, "alpaca")
        self.assertEqual(final["bid"], 10.0)
        self.assertEqual(final["ask"], 10.1)
        self.assertAlmostEqual(final["spread_pct"], 0.9950248756, places=6)

    def test_missing_quote_side_remains_pending(self):
        row, _ = data_orchestrator._quote_to_rank_row("LINK/USD", _quote(ask=None, price=10.0), "crypto", NOW)
        self.assertIsNone(row["ask"])
        self.assertIsNone(row["spread_pct"])
        self.assertEqual(row["quote_spread"], "PENDING_SPREAD")

    def test_worker_capability_refresh_is_worker_only_and_bounded(self):
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api"}, clear=False):
            rejected = server_extend._worker_refresh_crypto_capability_v1()
        self.assertEqual(rejected["status"], "REJECTED_NOT_WORKER_OWNER")
        broker = Mock()
        broker.crypto_capability_status.side_effect = [
            {"generated_at": "2000-01-01T00:00:00Z"},
            {"crypto_trading_supported": True, "broker_read_calls_used": 2},
        ]
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False), patch.object(server_extend, "ALPACA_PAPER_BROKER", broker):
            refreshed = server_extend._worker_refresh_crypto_capability_v1()
        self.assertEqual(refreshed["status"], "CURRENT")
        self.assertEqual(refreshed["broker_actions_used"], 0)
        broker._save_crypto_capability.assert_called_once()

    def test_capability_refresh_repairs_unverified_market_data_entitlement(self):
        broker = Mock()
        broker.crypto_capability_status.side_effect = [
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "market_data_entitlement_confirmed": False,
                "market_data_status": "UNKNOWN",
            },
            {"crypto_trading_supported": True, "market_data_entitlement_confirmed": True, "broker_read_calls_used": 3},
        ]
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False), patch.object(server_extend, "ALPACA_PAPER_BROKER", broker):
            refreshed = server_extend._worker_refresh_crypto_capability_v1()
        self.assertEqual(refreshed["status"], "CURRENT")
        self.assertEqual(broker.crypto_capability_status.call_count, 2)
        broker._save_crypto_capability.assert_called_once()

    def test_capability_probe_persists_read_only_market_data_entitlement(self):
        with tempfile.TemporaryDirectory() as root:
            broker = AlpacaPaperBroker()
            broker._crypto_capability_path = f"{root}/capability.json"
            broker.safety_status = Mock(return_value={
                "credentials_present": True, "paper_mode_verified": True,
                "paper_endpoint_detected": True, "live_endpoint_detected": False,
            })
            broker.account = Mock(return_value={"ok": True, "account_status": "ACTIVE"})
            broker._request = Mock(return_value=(True, [{
                "symbol": "BTC/USD", "tradable": True, "fractionable": True,
                "status": "active", "min_order_size": "0.0001",
            }], ""))
            broker._market_data_request = Mock(return_value=(True, {"bars": {"BTC/USD": []}}, "", 200))
            payload = broker.crypto_capability_status(True)
        self.assertTrue(payload["market_data_entitlement_confirmed"])
        self.assertEqual(payload["market_data_status"], "CONFIRMED")
        self.assertEqual(payload["market_data_probe_symbol"], "BTC/USD")
        self.assertEqual(payload["broker_actions_used"], 0)
        broker._market_data_request.assert_called_once()

    def test_completed_bar_timestamp_survives_worker_integrity_handoff(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        completed_timestamp = (now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        bars = [
            {"t": (now - timedelta(minutes=45)).isoformat().replace("+00:00", "Z"), "c": 10.0, "h": 10.2, "l": 9.8, "v": 100.0},
            {"t": completed_timestamp, "c": 10.1, "h": 10.3, "l": 9.9, "v": 120.0},
            {"t": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"), "c": 10.2, "h": 10.4, "l": 10.0, "v": 110.0},
        ]
        broker = Mock()
        broker.crypto_capability_status.return_value = {"tradable_pairs": ["LINK/USD"], "supported_pairs": ["LINK/USD"]}
        broker.historical_bars.return_value = {"bars": bars}
        autopilot = SimpleNamespace(_runtime_state={}, _save_state_file=Mock())
        quote_row = {
            "symbol": "LINK/USD", "price": 10.05, "bid": 10.0, "ask": 10.1,
            "quote_timestamp": now.isoformat().replace("+00:00", "Z"), "quote_age_seconds": 1.0,
            "quote_provider": "alpaca", "quote_record_id": "quote-link",
        }
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False), patch.object(
            server_extend, "PAPER_AUTOPILOT", autopilot
        ), patch.object(server_extend, "ALPACA_PAPER_BROKER", broker), patch.object(
            server_extend, "_worker_refresh_crypto_capability_v1", return_value={"status": "CURRENT"}
        ), patch.object(data_orchestrator._router, "get_quote", return_value=_quote()), patch.object(
            data_orchestrator, "_quote_to_rank_row", return_value=(quote_row, {"provider_used": "alpaca"})
        ), patch.object(server_extend, "_prioritize_rankings", side_effect=lambda rows, **_kwargs: rows), patch.object(
            server_extend.PORTFOLIO_INTEL, "apply", side_effect=lambda rows, **_kwargs: rows
        ), patch.object(server_extend.PORTFOLIO_RISK_ENGINE, "enrich", side_effect=lambda rows, **_kwargs: rows), patch.object(
            server_extend.PREDICTIVE_MODEL, "annotate_rows", side_effect=lambda rows: rows
        ), patch.object(server_extend.REGIME_ENGINE, "annotate_rows", side_effect=lambda rows: rows), patch.object(
            server_extend, "_ensure_persona_fields", side_effect=lambda row: dict(row)
        ), patch.object(server_extend, "derive_crypto_horizon_evidence_v1", return_value={}), patch.object(
            server_extend, "derive_crypto_pretrade_forecast_v1", return_value={"forecast_state": "INSUFFICIENT_FORECAST_EVIDENCE"}
        ), patch.object(server_extend, "_update_last_rankings"), patch.object(server_extend, "RANKINGS_ENDPOINT_CACHE", {}):
            result = server_extend._refresh_crypto_rankings_snapshot_v1()

        self.assertEqual(result["status"], "CURRENT")
        integrity = autopilot._runtime_state["crypto_rankings_snapshot_v1"]["crypto_quote_integrity_rows"][0]
        self.assertEqual(integrity["bar_timestamp"], completed_timestamp)
        self.assertEqual(integrity["quote_timestamp"], quote_row["quote_timestamp"])
        self.assertEqual(broker.historical_bars.call_count, 1)

    def test_open_crypto_positions_take_rotation_slots_without_extra_batch_calls(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        completed_timestamp = (now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        bars = [
            {"t": (now - timedelta(minutes=45)).isoformat().replace("+00:00", "Z"), "c": 10.0, "h": 10.2, "l": 9.8, "v": 100.0},
            {"t": completed_timestamp, "c": 10.1, "h": 10.3, "l": 9.9, "v": 120.0},
            {"t": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"), "c": 10.2, "h": 10.4, "l": 10.0, "v": 110.0},
        ]
        broker = Mock()
        broker.crypto_capability_status.return_value = {
            "tradable_pairs": ["ETH/USD", "SHIB/USD", "SOL/USD"],
            "supported_pairs": ["ETH/USD", "SHIB/USD", "SOL/USD"],
        }
        broker.historical_bars.return_value = {"bars": bars}
        autopilot = SimpleNamespace(_runtime_state={}, _save_state_file=Mock())
        quote_row = {
            "symbol": "ETH/USD", "price": 10.05, "bid": 10.0, "ask": 10.1,
            "quote_timestamp": now.isoformat().replace("+00:00", "Z"), "quote_age_seconds": 1.0,
            "quote_provider": "alpaca", "quote_record_id": "quote-open",
        }
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker", "ASTRA_CRYPTO_REFRESH_PAIRS_PER_CYCLE": "3"}, clear=False), patch.object(
            server_extend, "PAPER_AUTOPILOT", autopilot
        ), patch.object(server_extend, "ALPACA_PAPER_BROKER", broker), patch.object(
            server_extend, "_paper_autopilot_crypto_open_rows_v1", return_value=[{"symbol": "ETHUSD"}, {"symbol": "SHIB/USD"}]
        ), patch.object(server_extend, "_worker_refresh_crypto_capability_v1", return_value={"status": "CURRENT"}), patch.object(
            data_orchestrator._router, "get_quote", return_value=_quote()
        ), patch.object(data_orchestrator, "_quote_to_rank_row", return_value=(quote_row, {"provider_used": "alpaca"})), patch.object(
            server_extend, "_prioritize_rankings", side_effect=lambda rows, **_kwargs: rows
        ), patch.object(server_extend.PORTFOLIO_INTEL, "apply", side_effect=lambda rows, **_kwargs: rows), patch.object(
            server_extend.PORTFOLIO_RISK_ENGINE, "enrich", side_effect=lambda rows, **_kwargs: rows
        ), patch.object(server_extend.PREDICTIVE_MODEL, "annotate_rows", side_effect=lambda rows: rows), patch.object(
            server_extend.REGIME_ENGINE, "annotate_rows", side_effect=lambda rows: rows
        ), patch.object(server_extend, "_ensure_persona_fields", side_effect=lambda row: dict(row)), patch.object(
            server_extend, "derive_crypto_horizon_evidence_v1", return_value={}
        ), patch.object(server_extend, "derive_crypto_pretrade_forecast_v1", return_value={"forecast_state": "INSUFFICIENT_FORECAST_EVIDENCE"}), patch.object(
            server_extend, "_update_last_rankings"
        ), patch.object(server_extend, "RANKINGS_ENDPOINT_CACHE", {}):
            result = server_extend._refresh_crypto_rankings_snapshot_v1()

        self.assertEqual(result["status"], "CURRENT")
        snapshot = autopilot._runtime_state["crypto_rankings_snapshot_v1"]
        self.assertEqual(snapshot["rotation_observability"]["evaluated_symbols"][:2], ["ETH/USD", "SHIB/USD"])
        self.assertEqual(snapshot["open_position_management_symbols_evaluated"], ["ETH/USD", "SHIB/USD"])
        self.assertEqual(len(snapshot["rotation_observability"]["evaluated_symbols"]), 3)
        self.assertEqual(broker.historical_bars.call_count, 3)

    def test_shadow_consumes_only_complete_verified_lifecycle(self):
        payload = build_shadow_profit_loss_protection_validation_v1([
            _lifecycle("valid", closed=True), _lifecycle("open", closed=False), _lifecycle("legacy", closed=True, verified=False),
        ])
        self.assertEqual(payload["eligible_complete_lifecycles"], 1)
        self.assertEqual(payload["shadow_profit_loss_consumption"]["valid_records_consumed"], 1)
        self.assertEqual(payload["exclusion_reasons"]["lifecycle_not_complete"], 1)
        self.assertEqual(payload["exclusion_reasons"]["entry_price_unverified"], 1)
        self.assertEqual(payload["lifecycle_evidence_eligibility"]["eligible_by_lane"]["CRYPTO"], 1)

    def test_completion_payload_is_cache_only_and_never_allows_execution(self):
        payload = server_extend._crypto_data_lifecycle_shadow_completion_v1_payload()
        self.assertTrue(payload["get_route_read_only"])
        self.assertEqual(payload["provider_calls_used"], 0)
        self.assertEqual(payload["broker_actions_used"], 0)
        self.assertFalse(payload["paper_execution_currently_allowed"])
        self.assertFalse(payload["automatic_exit_activation_allowed"])


if __name__ == "__main__":
    unittest.main()
