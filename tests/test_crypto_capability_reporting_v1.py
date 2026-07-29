"""Production contracts for cache-only Alpaca crypto capability reporting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from engine.alpaca_paper_broker import AlpacaPaperBroker
import server_extend


def _capability(*, generated_at: str | None = None, **overrides):
    payload = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "activation_state": "VALIDATED_PAPER_READY",
        "paper_mode_verified": True,
        "paper_endpoint_confirmed": True,
        "live_endpoint_detected": False,
        "account_status": "ACTIVE",
        "crypto_trading_supported": True,
        "market_data_entitlement_confirmed": True,
        "tradable_pairs": ["BTC/USD"],
        "supported_pairs": ["BTC/USD"],
        "exact_blocker": "",
    }
    payload.update(overrides)
    return payload


class CryptoCapabilityReportingTests(unittest.TestCase):
    def _broker(self, payload):
        directory = tempfile.TemporaryDirectory(prefix="astra_crypto_capability_")
        self.addCleanup(directory.cleanup)
        broker = AlpacaPaperBroker()
        broker._crypto_capability_path = f"{directory.name}/capability.json"
        with open(broker._crypto_capability_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        broker._env = lambda: {
            "key": "paper-key", "secret": "paper-secret", "credential_source": "test",
            "base_url": "https://paper-api.alpaca.markets", "mode": "paper", "enabled_raw": "true",
        }
        return broker

    def test_valid_current_capability_reports_execution_support_from_canonical_cache(self):
        broker = self._broker(_capability())
        with patch.dict(os.environ, {"ASTRA_ENABLE_ALPACA_PAPER": "true", "ALPACA_TRADING_MODE": "paper"}, clear=False):
            safety = broker.safety_status()
        self.assertTrue(safety["crypto_broker_execution_supported"])
        self.assertEqual(safety["crypto_capability_status"], "VALIDATED_CURRENT")
        self.assertTrue(safety["crypto_capability_cache_only"])

    def test_missing_invalid_or_stale_capability_fails_closed(self):
        cases = (
            {},
            _capability(activation_state="VALIDATED_SHADOW_ONLY"),
            _capability(generated_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()),
            _capability(live_endpoint_detected=True),
            _capability(market_data_entitlement_confirmed=False),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                fact = AlpacaPaperBroker._crypto_capability_execution_fact(payload)
                self.assertFalse(fact["crypto_broker_execution_supported"])
                self.assertEqual(fact["crypto_capability_validation_status"], "BLOCKED_FAIL_CLOSED")
                self.assertTrue(fact["crypto_capability_exact_blocker"])

    def test_broker_status_preserves_capability_fact_without_broker_call(self):
        broker = self._broker(_capability())
        broker.account = Mock(return_value={"ok": True})
        broker.positions = Mock(return_value={"ok": True, "positions": [], "open_positions_count": 0})
        broker.orders = Mock(return_value={"ok": True, "orders": [], "open_orders_count": 0})
        with patch.dict(os.environ, {"ASTRA_ENABLE_ALPACA_PAPER": "true", "ALPACA_TRADING_MODE": "paper"}, clear=False):
            status = broker.status(include_broker_truth=False)
        self.assertTrue(status["crypto_broker_execution_supported"])
        self.assertEqual(status["crypto_capability_validation_status"], "VALIDATED_CURRENT")

    def test_cache_first_server_status_reports_capability_but_marks_broker_truth_deferred(self):
        safety = {
            "enabled_requested": True, "paper_mode_verified": True,
            "broker_execution_enabled": True, "paper_endpoint_detected": True,
            "live_endpoint_detected": False, "live_endpoint_rejected": True,
            "safety_status": "pass", "safety_reasons": ["paper_mode_verified"],
            "crypto_broker_execution_supported": True,
            "crypto_capability_status": "VALIDATED_CURRENT",
            "crypto_capability_source": "alpaca_crypto_capability_v2_cache",
            "crypto_capability_cache_only": True,
        }
        broker = Mock()
        broker.safety_status.return_value = safety
        with patch.object(server_extend, "ALPACA_PAPER_BROKER", broker), patch.object(
            server_extend, "_canonical_worker_state", return_value={}
        ), patch.object(server_extend, "_astra_evidence_state_json", return_value={}):
            result = server_extend._alpaca_paper_status_fast_fallback_v1()
        self.assertTrue(result["crypto_broker_execution_supported"])
        self.assertTrue(result["crypto_capability_cache_only"])
        self.assertTrue(result["broker_status_refresh_deferred"])
        self.assertIsNone(result["account_preflight_ok"])

    def test_lane_validation_cannot_revive_execution_from_stale_raw_capability(self):
        """The real lane payload must honour the canonical safety rejection."""
        broker = Mock()
        broker.safety_status.return_value = {
            "paper_mode_verified": True,
            "crypto_broker_execution_supported": False,
            "crypto_capability_status": "BLOCKED_FAIL_CLOSED",
            "crypto_capability_exact_blocker": "crypto_capability_cache_stale",
        }
        broker.cached_crypto_capability.return_value = {
            "crypto_trading_supported": True,  # Raw stale field is not authority.
            "paper_mode_verified": True,
            "market_data_entitlement_confirmed": True,
            "supported_pairs": ["BTC/USD"],
            "tradable_pairs": ["BTC/USD"],
            "activation_state": "VALIDATED_PAPER_READY",
        }
        with patch.object(server_extend, "ALPACA_PAPER_BROKER", broker), patch.object(
            server_extend, "_crypto_ranking_rows_cached_v1", return_value=[]
        ), patch.object(
            server_extend, "_crypto_operational_candidate_rows_v3", return_value=[]
        ), patch.object(
            server_extend, "_paper_autopilot_crypto_open_rows_v1", return_value=[]
        ), patch.object(
            server_extend, "lane_capital_status", return_value={"capital_configured": True}
        ):
            result = server_extend._crypto_paper_lane_validation_v1_payload({})
        self.assertFalse(result["paper_account_crypto_support"])
        self.assertFalse(result["broker_capability_available"])
        self.assertIn("alpaca_crypto_execution_support_unverified_or_deferred", result["activation_blockers"])


if __name__ == "__main__":
    unittest.main()
