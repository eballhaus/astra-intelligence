"""Regression coverage for crypto duplicate admission and lifecycle recovery identity."""
from __future__ import annotations

import os
import tempfile
import unittest

from engine.paper_autopilot import PaperAutopilotEngine


class CryptoDuplicateEntryIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="astra_crypto_duplicate_identity_")
        self.addCleanup(self.directory.cleanup)
        self.engine = PaperAutopilotEngine(
            db_path=os.path.join(self.directory.name, "paper.db"),
            state_path=os.path.join(self.directory.name, "state.json"),
            enabled=False,
        )
        self.engine._alpaca_safety_snapshot = lambda: {
            "paper_mode_verified": True,
            "broker_execution_enabled": True,
            "live_endpoint_detected": False,
            "live_endpoint_rejected": True,
        }

    def _candidate(self, horizon: str) -> dict:
        return {
            "symbol": "ETH/USD",
            "asset_type": "crypto",
            "asset_class": "crypto",
            "lane_id": "CRYPTO",
            "crypto_horizon": horizon,
            "candidate_generated_at": "2026-09-19T03:00:00Z",
            "valid_quote": True,
            "trusted_quote_for_buys": True,
            "buy_eligibility": "qualified",
            "buy_quality_score": 80.0,
            "confidence": 80.0,
            "action": "Buy",
        }

    def _broker_duplicate(self, *, pending: bool = False) -> dict:
        return self.engine._duplicate_exposure_snapshot(
            {
                "broker_reconciliation_active": True,
                "broker_positions_fetch_ok": True,
                "broker_position_by_symbol": {
                    "ETHUSD": {
                        "symbol": "ETHUSD",
                        "asset_type": "crypto",
                        "qty": "1",
                        "market_value": "100",
                    }
                },
                "broker_pending_orders": (
                    [{"symbol": "ETHUSD", "side": "buy", "status": "accepted"}]
                    if pending else []
                ),
            },
            [],
        )

    def _trace(self, horizon: str, duplicate: dict) -> tuple[dict, bool, str]:
        trace, allowed, reason, _meta = self.engine._candidate_trace_row(
            self._candidate(horizon),
            open_syms=set(duplicate["blocking_symbols"]),
            stock_capacity=10,
            crypto_capacity=10,
            total_capacity=10,
            broker_open_syms=set(duplicate["broker_meaningful_symbols"]),
            duplicate_exposure_snapshot=duplicate,
            capacity_decision={"allowed": True, "capacity_decision": "AVAILABLE"},
            capacity_snapshot={"snapshot_id": "test"},
            broker_reconciliation_active=True,
        )
        return trace, allowed, reason

    def test_compact_broker_symbol_blocks_same_fast_horizon(self):
        duplicate = self._broker_duplicate()
        self.assertIn("ETH/USD", duplicate["blocking_symbols"])
        _trace, allowed, reason = self._trace("CRYPTO_FAST", duplicate)
        self.assertFalse(allowed)
        self.assertEqual(reason, "DUPLICATE_ACTIVE_CRYPTO_SYMBOL_HORIZON")

    def test_compact_broker_symbol_blocks_same_swing_horizon(self):
        duplicate = self._broker_duplicate()
        _trace, allowed, reason = self._trace("CRYPTO_SWING", duplicate)
        self.assertFalse(allowed)
        self.assertEqual(reason, "DUPLICATE_ACTIVE_CRYPTO_SYMBOL_HORIZON")

    def test_pending_compact_broker_symbol_blocks_before_submission(self):
        duplicate = self._broker_duplicate(pending=True)
        self.assertIn("ETH/USD", duplicate["pending_order_symbols"])
        _trace, allowed, reason = self._trace("CRYPTO_FAST", duplicate)
        self.assertFalse(allowed)
        self.assertEqual(reason, "DUPLICATE_ACTIVE_CRYPTO_SYMBOL_HORIZON")

    def test_recovery_projection_requires_exact_lifecycle_identity(self):
        old_id = "ETH/USD:2026-08-26T20:19:05"
        current_id = "ETH/USD:2026-09-19T03:03:31"
        state = {
            "decisions": {
                old_id: {
                    "position_id": old_id,
                    "symbol": "ETHUSD",
                    "lane": "CRYPTO",
                    "horizon": "day_trade",
                    "evidence_provenance": {
                        "position_lane_horizon_recovery_v1": {
                            "lane_source_id": current_id,
                            "horizon_source_id": current_id,
                        }
                    },
                },
                current_id: {"position_id": current_id, "symbol": "ETHUSD"},
            }
        }
        recovery = {
            "generated_at": "2026-09-19T08:31:47Z",
            "positions": [{
                "canonical_identity_status": "RESOLVED",
                "canonical_lifecycle_id": current_id,
                "canonical_position_id": current_id,
                "symbol": "ETHUSD",
                "lane": "CRYPTO",
                "horizon": "CRYPTO_FAST",
                "lane_status": "RESOLVED",
                "horizon_status": "RESOLVED",
                "lane_source": "ORDER_LINKED_ASSIGNMENT",
                "horizon_source": "ORDER_LINKED_ASSIGNMENT",
                "lane_source_id": current_id,
                "horizon_source_id": current_id,
                "recovery_method": "ORDER_LINKED",
            }],
        }
        result = self.engine._attach_current_recovery_metadata_v1(state, recovery)
        old = result["decisions"][old_id]
        current = result["decisions"][current_id]
        self.assertNotIn("position_lane_horizon_recovery_v1", old["evidence_provenance"])
        self.assertIn("AMBIGUOUS_SYMBOL_ONLY_MATCH", old["exact_blockers"])
        self.assertEqual(current["horizon"], "CRYPTO_FAST")
        self.assertEqual(
            current["evidence_provenance"]["position_lane_horizon_recovery_v1"]["horizon_source_id"],
            current_id,
        )


if __name__ == "__main__":
    unittest.main()
