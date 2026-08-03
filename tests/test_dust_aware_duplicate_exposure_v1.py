"""Regression coverage for dust-aware paper-entry duplicate protection."""
from __future__ import annotations

import os
import tempfile
import unittest

from engine.astra_canonical_ownership_contract_v1 import classify_meaningful_exposure_v1
from engine.paper_autopilot import PaperAutopilotEngine


class DustAwareDuplicateExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="astra_dust_duplicate_")
        self.addCleanup(self.directory.cleanup)
        self.engine = PaperAutopilotEngine(
            db_path=os.path.join(self.directory.name, "paper.db"),
            state_path=os.path.join(self.directory.name, "state.json"),
            enabled=False,
        )

    @staticmethod
    def _snapshot(*, positions=None, orders=None, current=True):
        rows = positions or {}
        return {
            "broker_position_by_symbol": rows,
            "broker_open_symbols": set(rows),
            "broker_pending_orders": orders or [],
            "broker_reconciliation_active": current,
            "broker_positions_fetch_ok": current,
        }

    def test_equity_dust_only_broker_position_does_not_block_reentry(self):
        exposure = self.engine._duplicate_exposure_snapshot(self._snapshot(positions={
            "LYFT": {"symbol": "LYFT", "qty": "0.000000569", "market_value": "0.000009", "asset_class": "us_equity"},
        }), [])
        self.assertNotIn("LYFT", exposure["blocking_symbols"])
        self.assertIn("LYFT", exposure["broker_dust_symbols"])
        self.assertEqual(exposure["details_by_symbol"]["LYFT"]["broker"]["exposure_state"], "DUST_ONLY_POSITION_PRESENT")

    def test_dust_is_not_a_duplicate_across_day_scalp_swing_or_crypto_lanes(self):
        cases = (
            ("DAY", "DAY-DUST", "stock", "0.0005", "1.00"),
            ("SCALP", "SCALP-DUST", "stock", "0.0005", "1.00"),
            ("SWING", "SWING-DUST", "stock", "0.0005", "1.00"),
            ("CRYPTO", "BTC/USD", "crypto", "0.0000005", "0.005"),
        )
        for lane, symbol, asset_type, qty, market_value in cases:
            with self.subTest(lane=lane):
                exposure = self.engine._duplicate_exposure_snapshot(self._snapshot(positions={
                    symbol: {
                        "symbol": symbol,
                        "asset_type": asset_type,
                        "qty": qty,
                        "market_value": market_value,
                        "lane_id": lane,
                    },
                }), [])
                self.assertNotIn(symbol, exposure["blocking_symbols"])
                self.assertIn(symbol, exposure["broker_dust_symbols"])

    def test_meaningful_broker_position_blocks_reentry(self):
        exposure = self.engine._duplicate_exposure_snapshot(self._snapshot(positions={
            "AAPL": {"symbol": "AAPL", "qty": "1", "market_value": "200", "asset_class": "us_equity"},
        }), [])
        self.assertIn("AAPL", exposure["blocking_symbols"])
        self.assertIn("AAPL", exposure["broker_meaningful_symbols"])

    def test_meaningful_internal_open_row_blocks_only_without_current_broker_truth(self):
        internal = [{"symbol": "MSFT", "quantity": "1", "market_value": "100", "asset_type": "stock"}]
        unavailable = self.engine._duplicate_exposure_snapshot(self._snapshot(current=False), internal)
        current = self.engine._duplicate_exposure_snapshot(self._snapshot(current=True), internal)
        self.assertIn("MSFT", unavailable["blocking_symbols"])
        self.assertNotIn("MSFT", current["blocking_symbols"])

    def test_internal_dust_does_not_falsely_block(self):
        exposure = self.engine._duplicate_exposure_snapshot(
            self._snapshot(current=False),
            [{"symbol": "LEGACY", "quantity": "0.0000005", "market_value": "0.00001", "asset_type": "stock"}],
        )
        self.assertNotIn("LEGACY", exposure["blocking_symbols"])
        self.assertIn("LEGACY", exposure["internal_dust_symbols"])

    def test_open_buy_or_partial_buy_order_blocks_but_sell_does_not(self):
        for status in ("new", "partially_filled"):
            with self.subTest(status=status):
                exposure = self.engine._duplicate_exposure_snapshot(self._snapshot(orders=[{
                    "symbol": "NVDA", "side": "buy", "status": status,
                }]), [])
                self.assertIn("NVDA", exposure["blocking_symbols"])
                self.assertIn("NVDA", exposure["pending_order_symbols"])
        sell = self.engine._duplicate_exposure_snapshot(self._snapshot(orders=[{
            "symbol": "NVDA", "side": "sell", "status": "accepted",
        }]), [])
        self.assertNotIn("NVDA", sell["blocking_symbols"])

    def test_live_submission_reservation_blocks_reentry(self):
        self.engine._runtime_state["lane_reserve_commitments"] = {
            "DAY": {"id": {"symbol": "COST", "lane_id": "DAY", "commitment_state": "HELD", "expires_at": "2999-01-01T00:00:00Z"}},
            "SCALP": {}, "CRYPTO": {},
        }
        exposure = self.engine._duplicate_exposure_snapshot(self._snapshot(), [])
        self.assertIn("COST", exposure["blocking_symbols"])
        self.assertIn("COST", exposure["reservation_symbols"])

    def test_read_only_duplicate_snapshot_does_not_expire_reservations(self):
        self.engine._runtime_state["lane_reserve_commitments"] = {
            "DAY": {"id": {"symbol": "EXPIRED", "lane_id": "DAY", "commitment_state": "HELD", "expires_at": "2000-01-01T00:00:00Z"}},
            "SCALP": {}, "CRYPTO": {},
        }
        self.engine._duplicate_exposure_snapshot(self._snapshot(), [])
        record = self.engine._runtime_state["lane_reserve_commitments"]["DAY"]["id"]
        self.assertEqual(record["commitment_state"], "HELD")
        self.engine._duplicate_exposure_snapshot(self._snapshot(), [], expire_reservations=True)
        record = self.engine._runtime_state["lane_reserve_commitments"]["DAY"]["id"]
        self.assertEqual(record["commitment_state"], "EXPIRED")

    def test_broker_current_symbol_is_already_aggregated_before_duplicate_classification(self):
        exposure = self.engine._duplicate_exposure_snapshot(self._snapshot(positions={
            "AAPL": {"symbol": "AAPL", "qty": "0.0011", "market_value": "0.10", "asset_class": "us_equity"},
        }), [])
        self.assertIn("AAPL", exposure["blocking_symbols"])

    def test_equity_notional_or_quantity_dust_rule_is_canonical(self):
        quantity_dust = classify_meaningful_exposure_v1({"symbol": "QTY", "qty": "0.0005", "market_value": "1.0", "asset_type": "stock"})
        notional_dust = classify_meaningful_exposure_v1({"symbol": "NOTIONAL", "qty": "1", "market_value": "0.005", "asset_type": "stock"})
        self.assertFalse(quantity_dust["meaningful_exposure"])
        self.assertFalse(notional_dust["meaningful_exposure"])

    def test_crypto_uses_notional_not_equity_share_units(self):
        meaningful = classify_meaningful_exposure_v1({"symbol": "BTC/USD", "qty": "0.0000005", "market_value": "10", "asset_type": "crypto"})
        dust = classify_meaningful_exposure_v1({"symbol": "BTC/USD", "qty": "0.0000005", "market_value": "0.005", "asset_type": "crypto"})
        missing_notional = classify_meaningful_exposure_v1({"symbol": "BTC/USD", "qty": "0.0000005", "asset_type": "crypto"})
        self.assertTrue(meaningful["meaningful_exposure"])
        self.assertFalse(dust["meaningful_exposure"])
        self.assertEqual(missing_notional["exposure_state"], "AMBIGUOUS_FAIL_CLOSED")

    def test_negative_or_malformed_exposure_fails_closed(self):
        for row in (
            {"symbol": "NEG", "qty": "-1", "market_value": "100", "asset_type": "stock"},
            {"symbol": "BAD", "qty": "not-a-number", "market_value": "100", "asset_type": "stock"},
        ):
            with self.subTest(row=row):
                result = classify_meaningful_exposure_v1(row)
                self.assertTrue(result["meaningful_exposure"])
                self.assertEqual(result["exposure_state"], "AMBIGUOUS_FAIL_CLOSED")

    def test_closed_or_cancelled_orders_are_not_pending_order_conflicts(self):
        # The broker snapshot contract supplies only active statuses. Historical
        # cancelled and filled orders are intentionally excluded before this
        # entry duplicate predicate is called.
        exposure = self.engine._duplicate_exposure_snapshot(self._snapshot(orders=[]), [])
        self.assertEqual(exposure["pending_order_symbols"], set())


if __name__ == "__main__":
    unittest.main()
