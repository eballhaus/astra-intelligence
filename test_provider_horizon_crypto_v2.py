from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api_keys import API_POOLS
from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.execution_participation_audit_v1 import ExecutionParticipationAuditV1, _build_record
from engine.paper_autopilot import PaperAutopilotEngine, _infer_horizon_style
from engine.provider_data_knowledge_v2 import ProviderDataKnowledgeV2
from engine.runtime_environment import ENV_PATH, REPOSITORY_ROOT, resolve_fmp_key


class ProviderRuntimeV2Tests(unittest.TestCase):
    def test_environment_path_is_absolute_repository_root(self):
        self.assertTrue(ENV_PATH.is_absolute())
        self.assertEqual(ENV_PATH, REPOSITORY_ROOT / ".env")

    def test_fmp_key_is_resolved_without_value_exposure(self):
        key, source = resolve_fmp_key()
        self.assertTrue(bool(key))
        self.assertIn(source, {"FMP_API_KEY", "FINANCIALMODELINGPREP_API_KEY", "FINANCIAL_MODELING_PREP_API_KEY", "FINANCIAL_MODELING_PREP_KEY"})

    def test_fmp_and_alpaca_are_registered(self):
        names = {name for name, value in API_POOLS["stocks"] if value}
        self.assertIn("FMP", names)
        self.assertIn("ALPACA", names)

    def test_provider_facade_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = ProviderDataKnowledgeV2(tmp)
            result = suite.build(router={"providers_enabled": ["FMP", "ALPACA"], "request_deduplication_connected": True}, usage={}, manager_rows=[], shared_cache={"bounded_cache": True}, top_buys={})
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)
        self.assertFalse(result["behavior_safe_to_apply"])


class CandidateLineageV2Tests(unittest.TestCase):
    def test_day_trade_alias_normalization(self):
        self.assertEqual(_infer_horizon_style({"trade_horizon_style": "intraday"})[0], "day_trade")

    def test_score_scale_normalization(self):
        self.assertEqual(_infer_horizon_style({"day_trade_fit_score": 0.82})[0], "day_trade")

    def test_terminal_duplicate_mapping(self):
        record = _build_record({"symbol": "AAPL", "asset_type": "stock", "decision_reason": "duplicate_active_position"}, {"cycle_timestamp": "2026-07-10T12:00:00Z"})
        self.assertEqual(record["terminal_status"], "REJECTED_DUPLICATE_SYMBOL")
        self.assertTrue(record["candidate_id"].startswith("paper_candidate:"))

    def test_terminal_horizon_mapping(self):
        record = _build_record({"symbol": "AAPL", "asset_type": "stock", "decision_reason": "horizon_assignment_failed", "paper_entry_horizon_style": "day_trade", "confidence": 70}, {"cycle_timestamp": "2026-07-10T12:00:00Z"})
        self.assertEqual(record["terminal_status"], "REJECTED_HORIZON_ASSIGNMENT")

    def test_audit_deduplicates_same_candidate_in_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = ExecutionParticipationAuditV1(state_dir=tmp)
            traces = [{"symbol": "AAPL", "decision_reason": "duplicate_active_position"}] * 2
            result = audit.record_candidate_traces(traces, {"cycle_timestamp": "2026-07-10T12:00:00Z"})
            self.assertEqual(result["records_written"], 1)

    def test_invalid_candidate_preserves_confidence_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperAutopilotEngine(db_path=str(Path(tmp) / "paper.db"), state_path=str(Path(tmp) / "state.json"), enabled=False)
            allowed, reason, _ = engine._is_candidate_paper_eligible({"symbol": "AAPL", "confidence": 10, "buy_quality_score": 10, "paper_entry_horizon_style": "day_trade"})
            self.assertFalse(allowed)
            self.assertEqual(reason, "quality_confidence_too_low")

    def test_crypto_capacity_is_bounded_to_approved_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperAutopilotEngine(
                db_path=str(Path(tmp) / "paper.db"),
                state_path=str(Path(tmp) / "state.json"),
                enabled=False,
                max_crypto=99,
            )
        self.assertEqual(engine.crypto_day_capacity, 6)
        self.assertEqual(engine.crypto_short_swing_capacity, 2)
        self.assertEqual(engine.max_crypto, 8)

    def test_crypto_execution_requires_fresh_liquid_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperAutopilotEngine(
                db_path=str(Path(tmp) / "paper.db"),
                state_path=str(Path(tmp) / "state.json"),
                enabled=False,
            )
            missing_ok, missing_reason, _ = engine._crypto_execution_data_gate({})
            valid_ok, valid_reason, _ = engine._crypto_execution_data_gate({
                "quote_age_seconds": 5,
                "spread_pct": 0.2,
                "volume_24h": 1_000_000,
                "data_quality_score": 85,
            })
        self.assertFalse(missing_ok)
        self.assertEqual(missing_reason, "crypto_quote_freshness_missing")
        self.assertTrue(valid_ok)
        self.assertEqual(valid_reason, "crypto_market_data_gates_passed")


class AlpacaCryptoSafetyV2Tests(unittest.TestCase):
    def test_live_endpoint_is_rejected(self):
        broker = AlpacaPaperBroker()
        env = {"ASTRA_ENABLE_ALPACA_PAPER": "true", "ALPACA_TRADING_MODE": "paper", "APCA_API_BASE_URL": "https://api.alpaca.markets", "APCA_API_KEY_ID": "x", "APCA_API_SECRET_KEY": "y"}
        with patch.dict(os.environ, env, clear=False):
            safety = broker.safety_status()
        self.assertTrue(safety["live_endpoint_detected"])
        self.assertFalse(safety["broker_execution_enabled"])

    def test_crypto_capability_fails_closed_without_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker = AlpacaPaperBroker()
            broker._crypto_capability_path = str(Path(tmp) / "capability.json")
            status = broker.crypto_capability_status(False)
        self.assertFalse(status["crypto_trading_supported"])
        self.assertEqual(status["broker_actions_used"], 0)

    def test_crypto_order_requires_activation_proof(self):
        broker = AlpacaPaperBroker()
        with patch.object(broker, "safety_status", return_value={"broker_execution_enabled": True}), patch.object(broker, "account", return_value={"ok": True}):
            result = broker.submit_paper_order({"symbol": "BTC/USD", "asset_class": "crypto", "side": "buy", "trade_horizon_style": "day_trade", "paper_ready": True, "paper_limits_ok": True, "portfolio_risk_ok": True})
        self.assertEqual(result.get("error"), "crypto_paper_activation_proof_required")


if __name__ == "__main__":
    unittest.main()
