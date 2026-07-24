"""Fail-closed recovery tests for current broker-position lane metadata."""
from __future__ import annotations

import tempfile
import unittest

from engine.astra_canonical_position_snapshot_v1 import build_canonical_position_snapshot, snapshot_to_loss_containment_rows
from engine.astra_loss_containment_engine_v1 import evaluate_position_loss_containment_v1
from engine.astra_position_lane_horizon_recovery_v1 import (
    AstraPositionLaneHorizonRecoveryV1,
    build_position_lane_horizon_recovery_v1,
    enrich_canonical_position_snapshot_v1,
)
from engine.astra_profit_protection_giveback_v1 import evaluate_position_profit_protection_v1


STAMP = "2026-07-14T13:31:31.656238Z"


def _broker(**extra):
    return {
        "symbol": "PH", "asset_class": "us_equity", "qty": "4", "avg_entry_price": "100",
        "current_price": "97", "market_value": "388", "cost_basis": "400", "entry_timestamp": STAMP,
        **extra,
    }


def _evidence(**extra):
    return {
        "symbol": "PH", "asset_type": "stock", "position_id": "pos-1", "entry_order_id": "order-1",
        "entry_fill_id": "fill-1", "entry_timestamp": STAMP, "entry_filled_at": STAMP,
        "lane_id": "DAY", "canonical_horizon": "scalp", "current_reconciled": True,
        "recovery_source_type": "ACTIVE_POSITION_LIFECYCLE", **extra,
    }


class PositionLaneHorizonRecoveryTests(unittest.TestCase):
    def test_exact_fill_link_recovers_lane_and_horizon(self):
        ledger = build_position_lane_horizon_recovery_v1(
            {"PH": _broker(entry_fill_id="fill-1")}, evidence_rows=[_evidence()]
        )
        row = ledger["positions"][0]
        self.assertEqual((row["lane"], row["horizon"]), ("DAY", "scalp"))
        self.assertEqual((row["lane_status"], row["horizon_status"]), ("RESOLVED", "RESOLVED"))
        self.assertEqual(row["recovery_method"], "EXACT_ID_LINK")

    def test_unique_timestamp_consistent_current_record_is_bounded_fallback(self):
        ledger = build_position_lane_horizon_recovery_v1({"PH": _broker()}, evidence_rows=[_evidence()])
        row = ledger["positions"][0]
        self.assertEqual(row["lane"], "DAY")
        self.assertEqual(row["recovery_method"], "CURRENT_RECONCILED_SYMBOL_TIMESTAMP")

    def test_missing_evidence_is_explicitly_unavailable(self):
        ledger = build_position_lane_horizon_recovery_v1({"PH": _broker()}, evidence_rows=[])
        row = ledger["positions"][0]
        self.assertEqual(row["lane_status"], "UNAVAILABLE")
        self.assertEqual(row["horizon_status"], "UNAVAILABLE")
        self.assertIn("CANONICAL_LANE_EVIDENCE_UNAVAILABLE", row["exact_blockers"])
        self.assertIn("CANONICAL_HORIZON_EVIDENCE_UNAVAILABLE", row["exact_blockers"])
        self.assertEqual(row["first_causal_blocker"], "CANONICAL_LANE_EVIDENCE_UNAVAILABLE")

    def test_conflicting_canonical_claims_fail_closed(self):
        first, second = _evidence(entry_fill_id="fill-1"), _evidence(entry_fill_id="fill-1", lane_id="SWING")
        ledger = build_position_lane_horizon_recovery_v1(
            {"PH": _broker(entry_fill_id="fill-1")}, evidence_rows=[first, second]
        )
        row = ledger["positions"][0]
        self.assertEqual(row["lane_status"], "CONFLICT")
        self.assertEqual(row["lane"], "UNAVAILABLE")
        self.assertIn("CANONICAL_LANE_CONFLICT", row["exact_blockers"])

    def test_reopened_or_ambiguous_symbol_fallback_is_rejected(self):
        first, second = _evidence(position_id="old-1"), _evidence(position_id="old-2")
        ledger = build_position_lane_horizon_recovery_v1({"PH": _broker()}, evidence_rows=[first, second])
        row = ledger["positions"][0]
        self.assertEqual(row["lane_status"], "AMBIGUOUS")
        self.assertIn("AMBIGUOUS_SYMBOL_ONLY_MATCH", row["exact_blockers"])

    def test_enrichment_cannot_overwrite_broker_financial_facts(self):
        snapshot = build_canonical_position_snapshot({"PH": _broker()})
        ledger = build_position_lane_horizon_recovery_v1({"PH": _broker()}, evidence_rows=[_evidence()])
        enriched = enrich_canonical_position_snapshot_v1(snapshot, ledger)["positions"]["PH"]
        self.assertEqual(enriched["quantity"], 4.0)
        self.assertEqual(enriched["average_entry_price"], 100.0)
        self.assertEqual(enriched["current_price"], 97.0)
        self.assertEqual(enriched["market_value"], 388.0)
        self.assertEqual(enriched["cost_basis"], 400.0)
        self.assertEqual(enriched["lane"], "DAY")

    def test_both_protection_engines_consume_identical_recovery(self):
        snapshot = build_canonical_position_snapshot({"PH": _broker()})
        ledger = build_position_lane_horizon_recovery_v1({"PH": _broker()}, evidence_rows=[_evidence()])
        row = snapshot_to_loss_containment_rows(enrich_canonical_position_snapshot_v1(snapshot, ledger))[0]
        loss = evaluate_position_loss_containment_v1(row, broker_position=_broker())
        profit = evaluate_position_profit_protection_v1(row, broker_position=_broker())
        self.assertEqual((loss["lane"], loss["horizon"]), ("DAY", "scalp"))
        self.assertEqual((profit["lane"], profit["horizon"]), ("DAY", "scalp"))
        self.assertEqual(loss["thresholds"]["hard_boundary_pct"], -4.0)
        self.assertFalse(loss["execution_authorized"])
        self.assertFalse(profit["execution_authorized"])

    def test_unavailable_recovery_cannot_infer_crypto_lane(self):
        snapshot = build_canonical_position_snapshot({"BTC/USD": _broker(symbol="BTC/USD", asset_class="crypto")})
        ledger = build_position_lane_horizon_recovery_v1({"BTC/USD": _broker(symbol="BTC/USD", asset_class="crypto")}, evidence_rows=[])
        row = snapshot_to_loss_containment_rows(enrich_canonical_position_snapshot_v1(snapshot, ledger))[0]
        decision = evaluate_position_loss_containment_v1(row, broker_position=_broker(symbol="BTC/USD", asset_class="crypto"))
        self.assertEqual(decision["lane"], "UNAVAILABLE")
        self.assertIn("CANONICAL_LANE_EVIDENCE_UNAVAILABLE", decision["exact_blockers"])

    def test_ledger_persists_and_loads_bounded_current_positions(self):
        ledger = build_position_lane_horizon_recovery_v1({"PH": _broker()}, evidence_rows=[_evidence()])
        with tempfile.TemporaryDirectory() as directory:
            store = AstraPositionLaneHorizonRecoveryV1(directory)
            store.persist(ledger)
            loaded = store.snapshot()
        self.assertEqual(loaded["position_count"], 1)
        self.assertEqual(loaded["positions"][0]["symbol"], "PH")

    def test_autopilot_accepts_only_current_timestamp_linked_sqlite_metadata(self):
        from engine.paper_autopilot import PaperAutopilotEngine

        with tempfile.TemporaryDirectory() as directory:
            engine = PaperAutopilotEngine(
                db_path=f"{directory}/positions.db",
                state_path=f"{directory}/paper_autopilot_state.json",
                enabled=False,
            )
            engine._runtime_state["last_evidence_capacity_snapshot"] = {
                "position_rows_for_read_only_consumers": [{
                    "symbol": "PH", "asset_class": "us_equity", "entry_timestamp": STAMP,
                }],
            }
            ledger = engine._recover_broker_position_lane_horizon_v1(
                {"PH": _broker()}, [_evidence(asset_type="stock")]
            )
        row = ledger["positions"][0]
        self.assertEqual((row["lane"], row["horizon"]), ("DAY", "scalp"))

    def test_retained_advisory_decision_receives_current_recovery_metadata(self):
        from engine.paper_autopilot import PaperAutopilotEngine

        state = {"decisions": {"PH": {
            "symbol": "PH", "as_of": "2026-07-24T03:55:00Z",
            "average_entry_price": 100.0, "current_price": 97.0,
            "exact_blockers": ["PRICE_STALE_FAIL_CLOSED"],
        }}}
        recovery = build_position_lane_horizon_recovery_v1({"PH": _broker()}, evidence_rows=[_evidence()])
        updated = PaperAutopilotEngine._attach_current_recovery_metadata_v1(state, recovery)
        decision = updated["decisions"]["PH"]
        self.assertEqual((decision["lane"], decision["horizon"]), ("DAY", "scalp"))
        self.assertEqual(decision["lane_source"], "ACTIVE_POSITION_LIFECYCLE")
        self.assertEqual(decision["as_of"], "2026-07-24T03:55:00Z")
        self.assertEqual((decision["average_entry_price"], decision["current_price"]), (100.0, 97.0))
        self.assertIn("position_lane_horizon_recovery_v1", decision["evidence_provenance"])


if __name__ == "__main__":
    unittest.main()
