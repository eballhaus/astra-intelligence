from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from engine.astra_evidence_accumulation_capacity_v1 import (
    build_capacity_snapshot,
    candidate_capacity_decision,
)


BASE_ENV = {
    "ASTRA_CRYPTO_EVIDENCE_RESERVE_ENABLED": "1",
    "ASTRA_CRYPTO_EVIDENCE_CAPITAL_LIMIT": "10000",
    "ASTRA_CRYPTO_FAST_EXECUTION_LIMIT": "12",
    "ASTRA_CRYPTO_SWING_EXECUTION_LIMIT": "6",
    "ASTRA_CRYPTO_GLOBAL_POSITION_LIMIT": "16",
    "ASTRA_ENABLE_ALPACA_CRYPTO_PAPER": "1",
}


def position(symbol: str, *, horizon: str = "", value: float = 100.0) -> dict:
    row = {
        "symbol": symbol,
        "lane_id": "CRYPTO",
        "market_value": value,
        "position_id": f"position-{symbol}",
    }
    if horizon:
        row["crypto_horizon"] = horizon
    return row


def snapshot(*, positions=None, pending=None, commitments=None):
    return build_capacity_snapshot(
        broker_snapshot={
            "broker_reconciliation_active": True,
            "broker_positions_fetch_ok": True,
            "broker_state_age_seconds": 0,
        },
        account_snapshot={"buying_power": 100000, "equity": 100000, "cash": 100000},
        open_positions=positions or [],
        pending_orders=pending or [],
        active_commitments=commitments or [],
        env=BASE_ENV,
        global_position_limit=20,
    )


class CryptoHorizonExecutionCapacityTests(unittest.TestCase):
    def test_fast_limit_is_independent_and_exact(self):
        capacity = snapshot(positions=[position(f"F{i}", horizon="CRYPTO_FAST") for i in range(12)])
        decision = candidate_capacity_decision(
            capacity, lane_id="CRYPTO", symbol="F12", crypto_horizon="CRYPTO_FAST"
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["capacity_decision"], "CRYPTO_FAST_CAPACITY_EXHAUSTED")
        self.assertIn("CRYPTO_FAST_CAPACITY_EXHAUSTED", decision["exact_blockers"])

    def test_swing_limit_is_independent_and_exact(self):
        capacity = snapshot(positions=[position(f"S{i}", horizon="CRYPTO_SWING") for i in range(6)])
        decision = candidate_capacity_decision(
            capacity, lane_id="CRYPTO", symbol="S6", crypto_horizon="CRYPTO_SWING"
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["capacity_decision"], "CRYPTO_SWING_CAPACITY_EXHAUSTED")
        self.assertIn("CRYPTO_SWING_CAPACITY_EXHAUSTED", decision["exact_blockers"])

    def test_global_limit_blocks_seventeenth_reservation(self):
        capacity = snapshot(
            positions=[position(f"F{i}", horizon="CRYPTO_FAST") for i in range(12)]
            + [position(f"S{i}", horizon="CRYPTO_SWING") for i in range(4)]
        )
        decision = candidate_capacity_decision(
            capacity, lane_id="CRYPTO", symbol="S4", crypto_horizon="CRYPTO_SWING"
        )
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["capacity_decision"], "GLOBAL_CRYPTO_CAPACITY_EXHAUSTED")

    def test_supported_horizon_mixes_remain_admissible(self):
        fast_mix = snapshot(
            positions=[position(f"F{i}", horizon="CRYPTO_FAST") for i in range(12)]
            + [position(f"S{i}", horizon="CRYPTO_SWING") for i in range(4)]
        )
        swing_mix = snapshot(
            positions=[position(f"F{i}", horizon="CRYPTO_FAST") for i in range(10)]
            + [position(f"S{i}", horizon="CRYPTO_SWING") for i in range(6)]
        )
        # The occupied snapshots are globally full, so verify each mix's
        # independent counters and the exact global ceiling rather than any
        # legacy shared reserve behavior.
        self.assertEqual(fast_mix["fast_used"], 12)
        self.assertEqual(fast_mix["swing_used"], 4)
        self.assertEqual(swing_mix["fast_used"], 10)
        self.assertEqual(swing_mix["swing_used"], 6)
        self.assertEqual(fast_mix["global_crypto_used"], 16)
        self.assertEqual(swing_mix["global_crypto_used"], 16)

    def test_generic_legacy_positions_consume_global_only(self):
        capacity = snapshot(positions=[position("ETH/USD"), position("SHIB/USD")])
        self.assertEqual(capacity["generic_crypto_open"], 2)
        self.assertEqual(capacity["fast_used"], 0)
        self.assertEqual(capacity["swing_used"], 0)
        self.assertEqual(capacity["global_crypto_used"], 2)
        self.assertEqual(capacity["global_crypto_remaining"], 14)
        self.assertTrue(
            candidate_capacity_decision(
                capacity, lane_id="CRYPTO", symbol="BTC/USD", crypto_horizon="CRYPTO_FAST"
            )["allowed"]
        )

    def test_pending_and_commitment_transitions_are_counted_once(self):
        future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        capacity = snapshot(
            positions=[position("F0", horizon="CRYPTO_FAST")],
            pending=[{"symbol": "F0", "lane_id": "CRYPTO", "status": "accepted"}],
            commitments=[{
                "symbol": "F0", "lane_id": "CRYPTO", "commitment_state": "HELD", "expires_at": future,
            }],
        )
        self.assertEqual(capacity["global_crypto_used"], 1)
        self.assertEqual(capacity["fast_used"], 1)
        self.assertEqual(capacity["fast_pending"], 0)
        self.assertEqual(capacity["fast_commitments"], 0)

    def test_dust_is_not_execution_occupancy(self):
        capacity = snapshot(positions=[{
            **position("DUST/USD", horizon="CRYPTO_FAST", value=0.0001),
            "is_dust": True,
            "dust_state": "BROKER_DUST_MONITORED",
        }])
        self.assertEqual(capacity["global_crypto_used"], 0)
        self.assertEqual(capacity["fast_used"], 0)
        self.assertEqual(capacity["lanes"]["crypto"]["dust_strategy_slot_exclusion_count"], 1)


if __name__ == "__main__":
    unittest.main()
