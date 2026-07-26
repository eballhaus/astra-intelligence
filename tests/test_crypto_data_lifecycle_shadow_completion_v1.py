from __future__ import annotations

from datetime import datetime, timezone
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from engine import data_orchestrator
from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.shadow_profit_loss_protection_validation_v1 import build_shadow_profit_loss_protection_validation_v1
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
