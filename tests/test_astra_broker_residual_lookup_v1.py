"""Tests for broker residual lookup before exit closure."""
from __future__ import annotations

import unittest

from engine.astra_canonical_ownership_contract_v1 import broker_residual_lookup


class BrokerResidualLookupTests(unittest.TestCase):
    def test_residual_zero_allows_exit(self):
        result = broker_residual_lookup(
            {"symbol": "AAPL", "position_id": "p1"},
            {"qty": 0.0, "remaining_qty": 0.0},
        )
        self.assertTrue(result["residual_zero"])
        self.assertTrue(result["exit_allowed"])
        self.assertEqual(result["broker_residual_quantity"], 0.0)

    def test_residual_positive_blocks_exit(self):
        result = broker_residual_lookup(
            {"symbol": "AAPL", "position_id": "p1"},
            {"qty": 5.0, "remaining_qty": 5.0},
        )
        self.assertFalse(result["residual_zero"])
        self.assertFalse(result["exit_allowed"])
        self.assertEqual(result["broker_residual_quantity"], 5.0)

    def test_lookup_callable_used(self):
        def lookup(symbol, position_id):
            return {"quantity": 0.00000001}
        result = broker_residual_lookup(
            {"symbol": "AAPL", "position_id": "p1", "quantity": 100.0},
            None,
            broker_lookup=lookup,
        )
        self.assertTrue(result["exit_allowed"])
        self.assertEqual(result["source"], "broker_lookup")

    def test_position_row_fallback(self):
        result = broker_residual_lookup(
            {"symbol": "AAPL", "position_id": "p1", "quantity": 0.0},
        )
        self.assertTrue(result["exit_allowed"])
        self.assertEqual(result["source"], "position_row")

    def test_fractional_crypto_residual_blocks_exit(self):
        result = broker_residual_lookup(
            {"symbol": "BTC", "position_id": "p-crypto"},
            {"qty": 0.0001, "remaining_qty": 0.0001},
        )
        self.assertFalse(result["exit_allowed"])
        self.assertGreater(result["broker_residual_quantity"], 0.0)


if __name__ == "__main__":
    unittest.main()
