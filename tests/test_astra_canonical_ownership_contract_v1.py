"""Tests for canonical ownership contract, dust persistence, and ownership score."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from engine.astra_canonical_ownership_contract_v1 import (
    build_ownership_integrity_report_v1,
    classify_canonical_ownership_v1,
    classify_dust_position_v1,
    clear_dust_positions_v1,
    dust_position_key,
    is_broker_linked_active_position,
    load_dust_positions_v1,
    persist_dust_position_v1,
    broker_residual_lookup,
)


class DustClassificationTests(unittest.TestCase):
    def test_dust_by_quantity(self):
        result = classify_dust_position_v1({"symbol": "SHIB", "quantity": 0.0005})
        self.assertTrue(result["is_dust"])
        self.assertEqual(result["dust_state"], "BROKER_DUST_MONITORED")
        self.assertTrue(result["counts_toward_reconciliation"])
        self.assertFalse(result["tradable"])

    def test_dust_by_notional(self):
        result = classify_dust_position_v1({"symbol": "BTC", "quantity": 1.0, "market_value": 0.005})
        self.assertTrue(result["is_dust"])
        self.assertIn("market_value_below_notional_minimum", result["dust_reasons"])

    def test_not_dust(self):
        result = classify_dust_position_v1({"symbol": "AAPL", "quantity": 10.0, "market_value": 1000.0})
        self.assertFalse(result["is_dust"])
        self.assertEqual(result["dust_state"], "NOT_DUST")

    def test_micro_fractional_crypto_residue_is_dust_below_canonical_notional_floor(self):
        # A broker-held BTC residual at micro-fractional quantity (~5e-07) and
        # notional ~$0.03 must be an untradable BROKER_DUST_MONITORED residual,
        # not a meaningful exposure that consumes crypto capacity/reserve or
        # claims an active broker position count.
        result = classify_dust_position_v1({
            "symbol": "BTC/USD",
            "asset_type": "crypto",
            "asset_class": "crypto",
            "qty": "0.0000005",
            "market_value": 0.03,
        })
        self.assertTrue(result["is_dust"])
        self.assertEqual(result["dust_state"], "BROKER_DUST_MONITORED")
        self.assertTrue(result["counts_toward_reconciliation"])
        self.assertFalse(result["tradable"])
        self.assertIn("market_value_below_notional_minimum", result["dust_reasons"])

    def test_crypto_at_or_above_canonical_notional_floor_is_not_dust(self):
        # A meaningful crypto position at or above the canonical minimum
        # tradable notional (>= 1.0) remains an active exposure.
        result = classify_dust_position_v1({
            "symbol": "BTC/USD",
            "asset_type": "crypto",
            "qty": "0.0000005",
            "market_value": 10.0,
        })
        self.assertFalse(result["is_dust"])
        self.assertEqual(result["dust_state"], "NOT_DUST")

    def test_equity_notional_dust_floor_is_unchanged(self):
        # Equity notional dust floor stays at 0.01; a $0.005 equity residual is
        # dust while a $0.05 equity residual is not automatically a dust row on
        # the shared floor.
        self.assertTrue(classify_dust_position_v1({"symbol": "AAPL", "quantity": 1.0, "market_value": 0.005})["is_dust"])
        self.assertFalse(classify_dust_position_v1({"symbol": "AAPL", "quantity": 1.0, "market_value": 0.05})["is_dust"])


class DustPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        clear_dust_positions_v1(self.tmpdir)
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_persist_and_load_dust(self):
        pos = {"symbol": "PEPE", "quantity": 0.0001, "market_value": 0.005, "position_id": "pos-dust-1"}
        result = persist_dust_position_v1(pos, state_dir=self.tmpdir)
        self.assertTrue(result["persisted"])
        self.assertEqual(result["registry_key"], dust_position_key("PEPE", "pos-dust-1"))

        loaded = load_dust_positions_v1(self.tmpdir)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["symbol"], "PEPE")
        self.assertTrue(loaded[0]["counts_toward_reconciliation"])

    def test_non_dust_is_not_persisted(self):
        pos = {"symbol": "AAPL", "quantity": 10.0, "market_value": 1000.0}
        result = persist_dust_position_v1(pos, state_dir=self.tmpdir)
        self.assertFalse(result["persisted"])
        self.assertEqual(load_dust_positions_v1(self.tmpdir), [])

    def test_load_by_symbol(self):
        persist_dust_position_v1({"symbol": "PEPE", "quantity": 0.0001, "position_id": "p1"}, self.tmpdir)
        persist_dust_position_v1({"symbol": "DOGE", "quantity": 0.0001, "position_id": "p2"}, self.tmpdir)
        pepe = load_dust_positions_v1(self.tmpdir, symbol="PEPE")
        self.assertEqual(len(pepe), 1)
        self.assertEqual(pepe[0]["symbol"], "PEPE")


class OwnershipScoreTests(unittest.TestCase):
    def _position(self, **kwargs):
        base = {
            "position_id": "p1",
            "symbol": "AAPL",
            "lane_id": "SWING",
            "candidate_id": "c1",
            "contract_id": "c1",
            "lifecycle_id": "l1",
            "status": "OPEN",
            "quantity": 1.0,
            "broker_linked": "TRUE",
        }
        base.update(kwargs)
        return base

    def test_score_100_when_all_reconciled(self):
        positions = [self._position()]
        report = build_ownership_integrity_report_v1(positions, broker_symbols={"AAPL"}, db_open_symbols={"AAPL"})
        self.assertEqual(report["ownership_integrity"]["ownership_score"], 100.0)
        self.assertEqual(report["ownership_integrity"]["first_blocker"], "")

    def test_score_drops_when_broker_only_position_appears(self):
        positions = []
        report = build_ownership_integrity_report_v1(positions, broker_symbols={"AAPL"}, db_open_symbols=set())
        score = report["ownership_integrity"]["ownership_score"]
        self.assertEqual(score, 0.0)
        self.assertEqual(report["ownership_integrity"]["first_blocker"], "BROKER_ONLY_POSITIONS_WITHOUT_ASTRA_RECORD")

    def test_dust_counts_toward_reconciliation(self):
        positions = [{"symbol": "PEPE", "quantity": 0.0001, "market_value": 0.005, "position_id": "dust-1", "status": "OPEN", "broker_linked": "TRUE"}]
        report = build_ownership_integrity_report_v1(positions, broker_symbols={"PEPE"}, db_open_symbols={"PEPE"})
        self.assertEqual(report["ownership_integrity"]["dust_positions_monitored"], 1)
        self.assertEqual(report["ownership_integrity"]["ownership_score"], 100.0)


class BrokerResidualLookupTests(unittest.TestCase):
    def test_residual_zero_allows_exit(self):
        result = broker_residual_lookup(
            {"symbol": "AAPL", "position_id": "p1"},
            {"qty": 0.0, "remaining_qty": 0.0, "residual_lookup_authoritative": True, "lookup_status": "ZERO_CONFIRMED", "symbol": "AAPL"},
        )
        self.assertTrue(result["residual_zero"])
        self.assertTrue(result["exit_allowed"])
        self.assertEqual(result["broker_residual_quantity"], 0.0)

    def test_residual_positive_blocks_exit(self):
        result = broker_residual_lookup(
            {"symbol": "AAPL", "position_id": "p1"},
            {"qty": 5.0, "remaining_qty": 5.0, "residual_lookup_authoritative": True, "lookup_status": "NONZERO_CONFIRMED", "symbol": "AAPL"},
        )
        self.assertFalse(result["residual_zero"])
        self.assertFalse(result["exit_allowed"])
        self.assertEqual(result["broker_residual_quantity"], 5.0)

    def test_lookup_callable_used(self):
        def lookup(symbol, position_id):
            return {"quantity": 0.00000001, "lookup_status": "ZERO_CONFIRMED", "symbol": "AAPL"}
        result = broker_residual_lookup(
            {"symbol": "AAPL", "position_id": "p1", "quantity": 100.0},
            None,
            broker_lookup=lookup,
        )
        self.assertTrue(result["exit_allowed"])
        self.assertEqual(result["source"], "independent_broker_lookup")

    def test_position_row_never_proves_residual(self):
        result = broker_residual_lookup(
            {"symbol": "AAPL", "position_id": "p1", "quantity": 0.0},
        )
        self.assertFalse(result["exit_allowed"])
        self.assertEqual(result["lookup_status"], "UNKNOWN")


class ActivePositionPredicateTests(unittest.TestCase):
    def test_active_position_true(self):
        self.assertFalse(is_broker_linked_active_position({"status": "OPEN", "quantity": 1.0}))

    def test_open_crypto_requires_broker_linkage_not_only_local_status_and_quantity(self):
        self.assertTrue(is_broker_linked_active_position({
            "status": "OPEN", "quantity": 1.0, "entry_fill_id": "broker-fill-1",
        }))

    def test_simulated_position_false(self):
        self.assertFalse(is_broker_linked_active_position({"status": "SIMULATED", "quantity": 1.0}))

    def test_zero_quantity_false(self):
        self.assertFalse(is_broker_linked_active_position({"status": "OPEN", "quantity": 0.0}))

    def test_dust_allowed_by_default(self):
        self.assertTrue(is_broker_linked_active_position({"status": "OPEN", "quantity": 0.0005, "broker_linked": "TRUE"}))

    def test_dust_excluded_when_disallowed(self):
        self.assertFalse(is_broker_linked_active_position({"status": "OPEN", "quantity": 0.0005, "broker_linked": "TRUE"}, allow_dust=False))


if __name__ == "__main__":
    unittest.main()
