"""Tests for canonical broker-position snapshot normalization."""
import unittest
from engine.astra_canonical_position_snapshot_v1 import (
    build_canonical_position_snapshot,
    snapshot_to_loss_containment_rows,
    snapshot_to_broker_position_by_symbol,
)


class TestCanonicalPositionSnapshot(unittest.TestCase):
    def test_normalizes_single_position(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "asset_class": "us_equity",
                "qty": "10",
                "avg_entry_price": "150.00",
                "current_price": "155.00",
                "market_value": "1550.00",
                "cost_basis": "1500.00",
                "unrealized_pl": "50.00",
                "unrealized_plpc": "0.0333",
                "side": "long",
                "qty_available": "10",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)

        self.assertEqual(snapshot["position_count"], 1)
        self.assertIn("AAPL", snapshot["positions"])
        pos = snapshot["positions"]["AAPL"]
        self.assertEqual(pos["symbol"], "AAPL")
        self.assertEqual(pos["current_price"], 155.0)
        self.assertEqual(pos["average_entry_price"], 150.0)
        self.assertEqual(pos["quantity"], 10.0)

    def test_excludes_closed_positions(self):
        broker_positions = {
            "AAPL": {"symbol": "AAPL", "qty": "0", "current_price": "150.00"},
            "MSFT": {"symbol": "MSFT", "qty": "10", "current_price": "300.00"},
        }
        snapshot = build_canonical_position_snapshot(broker_positions)

        self.assertEqual(snapshot["position_count"], 1)
        self.assertNotIn("AAPL", snapshot["positions"])
        self.assertIn("MSFT", snapshot["positions"])
        self.assertIn("AAPL", snapshot["closed_symbols"])

    def test_deduplicates_by_symbol(self):
        broker_positions = {
            "AAPL": {"symbol": "AAPL", "qty": "5", "current_price": "150.00"},
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        self.assertEqual(snapshot["position_count"], 1)

    def test_preserves_decimal_quantity(self):
        broker_positions = {
            "BTC": {
                "symbol": "BTC",
                "qty": "0.00123456",
                "avg_entry_price": "50000.00",
                "current_price": "55000.00",
                "market_value": "67.39",
                "asset_class": "crypto",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["BTC"]
        self.assertAlmostEqual(pos["quantity"], 0.00123456, places=5)

    def test_marks_dust_positions(self):
        broker_positions = {
            "DUST": {
                "symbol": "DUST",
                "qty": "0.001",
                "market_value": "0.005",
                "current_price": "5.00",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        self.assertEqual(snapshot["dust_count"], 1)
        self.assertIn("DUST", snapshot["dust_symbols"])

    def test_calculates_return_percentage(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "avg_entry_price": "100.00",
                "current_price": "110.00",
                "market_value": "1100.00",
                "cost_basis": "1000.00",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["AAPL"]
        self.assertAlmostEqual(pos["unrealized_pl_pct"], 10.0, places=1)

    def test_handles_negative_return(self):
        broker_positions = {
            "QBTS": {
                "symbol": "QBTS",
                "qty": "100",
                "avg_entry_price": "25.00",
                "current_price": "16.00",
                "market_value": "1600.00",
                "cost_basis": "2500.00",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["QBTS"]
        self.assertLess(pos["unrealized_pl_pct"], -30)

    def test_lane_unavailable_when_missing(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "current_price": "150.00",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["AAPL"]
        self.assertEqual(pos["lane"], "UNAVAILABLE")
        self.assertEqual(pos["lane_source"], "UNAVAILABLE")  # Corrected from "unavailable"

    def test_lane_preserved_when_present(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "current_price": "150.00",
                "lane_id": "DAY",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["AAPL"]
        self.assertEqual(pos["lane"], "DAY")
        self.assertEqual(pos["lane_source"], "broker_position")


class TestSnapshotToLossContainmentRows(unittest.TestCase):
    def test_converts_snapshot_to_rows(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "asset_class": "us_equity",
                "qty": "10",
                "avg_entry_price": "150.00",
                "current_price": "155.00",
                "market_value": "1550.00",
                "cost_basis": "1500.00",
                "lane_id": "DAY",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        rows = snapshot_to_loss_containment_rows(snapshot)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["symbol"], "AAPL")
        self.assertEqual(row["current_price"], 155.0)
        self.assertEqual(row["avg_entry_price"], 150.0)
        self.assertEqual(row["lane_id"], "DAY")

    def test_excludes_dust_from_rows(self):
        broker_positions = {
            "DUST": {
                "symbol": "DUST",
                "qty": "0.001",
                "market_value": "0.005",
                "current_price": "5.00",
            },
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "current_price": "150.00",
                "market_value": "1500.00",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        rows = snapshot_to_loss_containment_rows(snapshot)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "AAPL")


class TestSnapshotToBrokerPositionBySymbol(unittest.TestCase):
    def test_converts_snapshot_to_broker_format(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "avg_entry_price": "150.00",
                "current_price": "155.00",
                "market_value": "1550.00",
                "cost_basis": "1500.00",
                "asset_class": "us_equity",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        result = snapshot_to_broker_position_by_symbol(snapshot)

        self.assertIn("AAPL", result)
        self.assertEqual(result["AAPL"]["symbol"], "AAPL")
        self.assertEqual(result["AAPL"]["qty"], 10.0)


class TestMultiplePositions(unittest.TestCase):
    def test_handles_multiple_symbols(self):
        broker_positions = {
            "AAPL": {"symbol": "AAPL", "qty": "10", "current_price": "150.00", "market_value": "1500.00", "cost_basis": "1500.00"},
            "TSLA": {"symbol": "TSLA", "qty": "5", "current_price": "200.00", "market_value": "1000.00", "cost_basis": "900.00"},
            "QBTS": {"symbol": "QBTS", "qty": "100", "current_price": "16.00", "market_value": "1600.00", "cost_basis": "2500.00"},
        }
        snapshot = build_canonical_position_snapshot(broker_positions)

        self.assertEqual(snapshot["position_count"], 3)
        self.assertGreater(snapshot["positions"]["TSLA"]["unrealized_pl_pct"], 0)
        self.assertLess(snapshot["positions"]["QBTS"]["unrealized_pl_pct"], 0)

    def test_handles_empty_broker_positions(self):
        snapshot = build_canonical_position_snapshot({})
        self.assertEqual(snapshot["position_count"], 0)
        rows = snapshot_to_loss_containment_rows(snapshot)
        self.assertEqual(len(rows), 0)


class TestTimestampSeparation(unittest.TestCase):
    def test_snapshot_time_separate_from_broker_evidence_time(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "current_price": "150.00",
                "timestamp": "2026-07-22T10:30:00Z",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions, snapshot_timestamp="2026-07-22T10:35:00Z")
        pos = snapshot["positions"]["AAPL"]
        self.assertEqual(pos["snapshot_timestamp"], "2026-07-22T10:35:00Z")
        self.assertEqual(pos["broker_position_evidence_at"], "2026-07-22T10:30:00Z")
        self.assertNotEqual(pos["snapshot_timestamp"], pos["broker_position_evidence_at"])

    def test_missing_broker_timestamp_remains_unavailable(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "current_price": "150.00",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["AAPL"]
        self.assertEqual(pos["broker_position_evidence_at"], "UNAVAILABLE")
        self.assertEqual(pos["price_evidence_at"], "UNAVAILABLE")
        self.assertEqual(pos["evidence_freshness"], "UNAVAILABLE")

    def test_positive_price_alone_does_not_prove_freshness(self):
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "current_price": "150.00",  # Positive price
                "timestamp": "",  # No timestamp
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["AAPL"]
        self.assertEqual(pos["evidence_freshness"], "UNAVAILABLE")  # Not "current"


class TestFractionalQuantityPreservation(unittest.TestCase):
    def test_preserves_very_small_quantities(self):
        broker_positions = {
            "FRAC": {
                "symbol": "FRAC",
                "qty": "0.000000321",
                "avg_entry_price": "50000.00",
                "current_price": "55000.00",
                "market_value": "0.017655",
                "cost_basis": "0.01605",
                "asset_class": "crypto",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["FRAC"]
        # Should preserve quantity with reasonable precision
        self.assertGreater(pos["quantity"], 0)
        self.assertLess(pos["quantity"], 0.001)

    def test_dust_classification_does_not_remove_legitimate_residuals(self):
        broker_positions = {
            "RESIDUAL": {
                "symbol": "RESIDUAL",
                "qty": "0.000000926",
                "avg_entry_price": "100.00",
                "current_price": "15000.00",  # High price to keep market_value above threshold
                "market_value": "0.01389",  # Above 0.01 threshold
                "cost_basis": "0.0000926",
                "asset_class": "crypto",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["RESIDUAL"]
        # Crypto small quantity should not be dust when market_value is above threshold
        self.assertEqual(pos["is_dust"], False)


class TestLaneHorizonUnavailable(unittest.TestCase):
    def test_mocked_alpaca_position_has_no_false_lane(self):
        """Alpaca positions do NOT have Astra lane/horizon fields."""
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": "10",
                "current_price": "150.00",
                "asset_class": "us_equity",
                # No lane_id, no horizon fields
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["AAPL"]
        self.assertEqual(pos["lane"], "UNAVAILABLE")
        self.assertEqual(pos["lane_source"], "UNAVAILABLE")
        self.assertEqual(pos["horizon"], "UNAVAILABLE")
        self.assertEqual(pos["horizon_source"], "UNAVAILABLE")

    def test_no_lane_inferred_from_loss_percentage(self):
        """Lane must NOT be inferred from loss percentage."""
        broker_positions = {
            "QBTS": {
                "symbol": "QBTS",
                "qty": "100",
                "avg_entry_price": "25.00",
                "current_price": "16.00",
                "market_value": "1600.00",
                "cost_basis": "2500.00",
            }
        }
        snapshot = build_canonical_position_snapshot(broker_positions)
        pos = snapshot["positions"]["QBTS"]
        # Even though -36% loss, lane should be UNAVAILABLE, not inferred
        self.assertEqual(pos["lane"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
