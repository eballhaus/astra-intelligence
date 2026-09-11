"""Focused tests for lifecycle-specific broker residual reconciliation."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest

from engine.astra_canonical_ownership_contract_v1 import broker_residual_lookup
from engine.paper_autopilot import PaperAutopilotEngine


class _ReadOnlyBroker:
    def __init__(self, positions: list[dict] | None = None, *, ok: bool = True) -> None:
        self._positions = list(positions or [])
        self.ok = ok
        self.position_reads = 0
        self.reconstruct_reads = 0
        self.submissions = 0

    def positions(self):
        self.position_reads += 1
        return {"ok": self.ok, "positions": list(self._positions)}

    def reconstruct_open_position_provenance(self, positions, *, limit=500):
        self.reconstruct_reads += 1
        return {
            "ok": True,
            "positions": positions,
            "broker_read_calls_used": 1,
        }


def _provenance(lots: list[dict], quantity: float) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "BROKER_FILL_PROVENANCE_CURRENT",
        "rows": {
            "LYFT": {
                "symbol": "LYFT",
                "current_quantity": quantity,
                "matching_entry_fills": lots,
                "quantity_coverage_complete": True,
                "entry_provenance_status": "BROKER_FIFO_FILL_MATCHED",
                "entry_provenance_source": "alpaca_paper_closed_orders_fifo",
            },
        },
    }


def _engine(broker: _ReadOnlyBroker, lots: list[dict], *, quantity: float, other_rows=None):
    engine = object.__new__(PaperAutopilotEngine)
    engine.alpaca_paper_broker = broker
    target = {
        "position_id": "target-life",
        "lifecycle_id": "target-life",
        "symbol": "LYFT",
        "lane_id": "DAY",
        "entry_order_id": "target-entry-order",
        "entry_fill_id": "target-entry-fill",
    }
    engine._runtime_state = {
        "authorized_lane_exit_pending": {
            "target-exit": {
                "position_id": "target-life",
                "symbol": "LYFT",
                "contract": {
                    "entry_order_id": "target-entry-order",
                    "entry_fill_id": "target-entry-fill",
                },
            },
        },
        "native_lane_exit_lifecycle_v1": {"target-life": target},
        "legacy_retirement_entry_provenance_v1": _provenance(lots, quantity),
    }
    rows = [target, *(other_rows or [])]
    engine._fetch_open_positions = lambda: list(rows)
    return engine


class LifecycleSpecificBrokerResidualTests(unittest.TestCase):
    def test_fully_exited_lifecycle_with_no_symbol_lots_confirms_zero(self):
        broker = _ReadOnlyBroker([])
        engine = _engine(broker, [], quantity=0.0)

        lookup = engine._independent_broker_residual_lookup("LYFT", "target-life")
        result = broker_residual_lookup(
            {"symbol": "LYFT", "position_id": "target-life", "asset_type": "stock"},
            broker_lookup=lambda *_args: lookup,
        )

        self.assertEqual(lookup["lookup_status"], "BROKER_ZERO_CONFIRMED")
        self.assertEqual(result["lookup_status"], "BROKER_ZERO_CONFIRMED")
        self.assertTrue(result["exit_allowed"])
        self.assertEqual(broker.position_reads, 1)
        self.assertEqual(broker.submissions, 0)

    def test_target_residual_dust_preserves_existing_dust_policy(self):
        broker = _ReadOnlyBroker([{"symbol": "LYFT", "qty": "0.0000021"}])
        lots = [{
            "remaining_qty": 0.0000021,
            "broker_order_id": "target-entry-order",
            "client_order_id": "target-entry-client",
        }]
        engine = _engine(broker, lots, quantity=0.0000021)

        lookup = engine._independent_broker_residual_lookup("LYFT", "target-life")
        result = broker_residual_lookup(
            {"symbol": "LYFT", "position_id": "target-life", "asset_type": "stock"},
            broker_lookup=lambda *_args: lookup,
        )

        self.assertEqual(lookup["lookup_status"], "TARGET_RESIDUAL_DUST")
        self.assertEqual(result["lookup_status"], "TARGET_RESIDUAL_DUST")
        self.assertTrue(result["exit_allowed"])
        self.assertTrue(result["dust_classification"]["is_dust"])
        self.assertEqual(result["zero_tolerance"], 0.0000001)

    def test_independently_owned_same_symbol_lot_does_not_block_target_zero(self):
        broker = _ReadOnlyBroker([{"symbol": "LYFT", "qty": "5.0"}])
        lots = [{
            "remaining_qty": 5.0,
            "broker_order_id": "other-entry-order",
            "client_order_id": "other-entry-client",
        }]
        other = {
            "position_id": "other-life",
            "lifecycle_id": "other-life",
            "symbol": "LYFT",
            "lane_id": "DAY",
            "entry_order_id": "other-entry-order",
            "entry_fill_id": "other-entry-fill",
        }
        engine = _engine(broker, lots, quantity=5.0, other_rows=[other])

        lookup = engine._independent_broker_residual_lookup("LYFT", "target-life")
        result = broker_residual_lookup(
            {"symbol": "LYFT", "position_id": "target-life", "asset_type": "stock"},
            broker_lookup=lambda *_args: lookup,
        )

        self.assertEqual(lookup["lookup_status"], "BROKER_ZERO_CONFIRMED")
        self.assertEqual(lookup["target_residual_quantity"], 0.0)
        self.assertEqual(len(lookup["independent_lots"]), 1)
        self.assertTrue(result["exit_allowed"])
        self.assertEqual(result["broker_aggregate_quantity"], 5.0)

    def test_unowned_same_symbol_lot_is_aggregate_ambiguity(self):
        broker = _ReadOnlyBroker([{"symbol": "LYFT", "qty": "5.789811019"}])
        lots = [{
            "remaining_qty": 5.78980892,
            "broker_order_id": "unowned-buy",
            "client_order_id": "unowned-client",
        }]
        engine = _engine(broker, lots, quantity=5.78980892)

        lookup = engine._independent_broker_residual_lookup("LYFT", "target-life")
        result = broker_residual_lookup(
            {"symbol": "LYFT", "position_id": "target-life", "asset_type": "stock"},
            broker_lookup=lambda *_args: lookup,
        )

        self.assertEqual(lookup["lookup_status"], "AGGREGATE_POSITION_AMBIGUITY")
        self.assertEqual(result["lookup_status"], "AGGREGATE_POSITION_AMBIGUITY")
        self.assertFalse(result["exit_allowed"])
        self.assertEqual(result["broker_aggregate_quantity"], 5.789811019)
        self.assertEqual(len(result["unowned_lots"]), 1)
        self.assertEqual(broker.submissions, 0)

    def test_broker_lookup_failure_remains_fail_closed(self):
        broker = _ReadOnlyBroker(ok=False)
        engine = _engine(broker, [], quantity=0.0)

        lookup = engine._independent_broker_residual_lookup("LYFT", "target-life")
        result = broker_residual_lookup(
            {"symbol": "LYFT", "position_id": "target-life", "asset_type": "stock"},
            broker_lookup=lambda *_args: lookup,
        )

        self.assertEqual(lookup["lookup_status"], "BROKER_LOOKUP_FAILED")
        self.assertEqual(result["lookup_status"], "BROKER_LOOKUP_FAILED")
        self.assertFalse(result["exit_allowed"])
        self.assertEqual(broker.position_reads, 1)
        self.assertEqual(broker.submissions, 0)

    def test_cached_provenance_avoids_second_provider_history_read(self):
        broker = _ReadOnlyBroker([{"symbol": "LYFT", "qty": "5.0"}])
        lots = [{
            "remaining_qty": 5.0,
            "broker_order_id": "unowned-buy",
            "client_order_id": "unowned-client",
        }]
        engine = _engine(broker, lots, quantity=5.0)

        lookup = engine._independent_broker_residual_lookup("LYFT", "target-life")

        self.assertEqual(lookup["lookup_status"], "AGGREGATE_POSITION_AMBIGUITY")
        self.assertEqual(broker.position_reads, 1)
        self.assertEqual(broker.reconstruct_reads, 0)
        self.assertEqual(lookup["broker_actions_used"], 0)


if __name__ == "__main__":
    unittest.main()
