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
        "position_owner": "DAY", "exit_policy_owner": "DAY",
        "candidate_id": "candidate-1", "recovery_source_type": "ACTIVE_POSITION_LIFECYCLE", **extra,
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
        broker = _broker(asset_id="alpaca-asset", entry_fill_id="fill-1")
        snapshot = build_canonical_position_snapshot({"PH": broker})
        ledger = build_position_lane_horizon_recovery_v1({"PH": broker}, evidence_rows=[_evidence()])
        enriched = enrich_canonical_position_snapshot_v1(snapshot, ledger)["positions"]["PH"]
        self.assertEqual(enriched["quantity"], 4.0)
        self.assertEqual(enriched["average_entry_price"], 100.0)
        self.assertEqual(enriched["current_price"], 97.0)
        self.assertEqual(enriched["market_value"], 388.0)
        self.assertEqual(enriched["cost_basis"], 400.0)
        self.assertEqual(enriched["lane"], "DAY")
        self.assertEqual(enriched["canonical_position_id"], "pos-1")
        self.assertEqual(enriched["position_id"], "pos-1")
        self.assertEqual(enriched["broker_asset_id"], "alpaca-asset")
        self.assertEqual(enriched["lifecycle_id"], "pos-1")
        self.assertEqual(enriched["candidate_id"], "candidate-1")
        self.assertEqual(enriched["exit_policy_owner"], "DAY")

    def test_exact_identity_recovers_candidate_from_persisted_position_metadata(self):
        broker = _broker(asset_id="alpaca-asset", entry_fill_id="fill-1")
        ledger = build_position_lane_horizon_recovery_v1(
            {"PH": broker}, evidence_rows=[_evidence(candidate_id="", row_json='{"candidate_id":"candidate-from-row-json"}')]
        )
        self.assertEqual(ledger["positions"][0]["candidate_id"], "candidate-from-row-json")

    def test_timestamp_fallback_never_promotes_broker_asset_id_to_canonical_identity(self):
        broker = _broker(asset_id="alpaca-asset")
        snapshot = build_canonical_position_snapshot({"PH": broker})
        ledger = build_position_lane_horizon_recovery_v1({"PH": broker}, evidence_rows=[_evidence()])
        recovered = ledger["positions"][0]
        enriched = enrich_canonical_position_snapshot_v1(snapshot, ledger)["positions"]["PH"]
        row = snapshot_to_loss_containment_rows({"positions": {"PH": enriched}})[0]
        self.assertEqual(recovered["recovery_method"], "CURRENT_RECONCILED_SYMBOL_TIMESTAMP")
        self.assertEqual(recovered["canonical_identity_status"], "UNAVAILABLE")
        self.assertEqual(enriched.get("canonical_position_id"), None)
        self.assertEqual(enriched["broker_asset_id"], "alpaca-asset")
        self.assertEqual(row["position_id"], "unresolved:PH")
        self.assertEqual(row["broker_asset_id"], "alpaca-asset")

    def test_same_symbol_different_exact_lifecycles_fail_closed_for_identity(self):
        broker = _broker(asset_id="alpaca-asset", entry_fill_id="fill-1")
        snapshot = build_canonical_position_snapshot({"PH": broker})
        ledger = build_position_lane_horizon_recovery_v1(
            {"PH": broker}, evidence_rows=[_evidence(position_id="pos-1"), _evidence(position_id="pos-2")]
        )
        recovered = ledger["positions"][0]
        enriched = enrich_canonical_position_snapshot_v1(snapshot, ledger)["positions"]["PH"]
        self.assertEqual(recovered["canonical_identity_status"], "AMBIGUOUS")
        self.assertEqual(recovered["canonical_position_id"], "")
        self.assertNotIn("canonical_position_id", enriched)
        self.assertNotIn("position_id", enriched)

    def test_loss_containment_uses_exact_astra_position_identity(self):
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
                    "entry_fill_id": "fill-1", "entry_order_id": "order-1", "position_id": "pos-1",
                }],
            }
            result = engine._loss_containment_review_phase(
                open_rows=[_evidence(entry_metadata_generation="V1_MANDATORY")],
                broker_position_by_symbol={"PH": _broker(asset_id="alpaca-asset", entry_fill_id="")},
                broker_fetch_succeeded=True,
            )
        decision = result["state"]["decisions"]["pos-1"]
        self.assertEqual(decision["position_id"], "pos-1")
        self.assertEqual(decision["lane"], "DAY")
        self.assertEqual(decision["ownership_classification"], "ACTIVE_DAY")

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
        # When recovery returns UNAVAILABLE, the engine derives CRYPTO from
        # asset_class for threshold rails. The lane_recovery_status=UNAVAILABLE
        # flag tells consumers the lane is unverified.
        self.assertEqual(decision["lane"], "CRYPTO")
        self.assertEqual(decision["lane_recovery_status"], "UNAVAILABLE")

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

    def test_autopilot_uses_current_fill_identity_when_broker_and_db_timestamps_differ(self):
        from engine.paper_autopilot import PaperAutopilotEngine

        with tempfile.TemporaryDirectory() as directory:
            engine = PaperAutopilotEngine(
                db_path=f"{directory}/positions.db",
                state_path=f"{directory}/paper_autopilot_state.json",
                enabled=False,
            )
            engine._runtime_state["last_evidence_capacity_snapshot"] = {
                "position_rows_for_read_only_consumers": [{
                    "symbol": "PH", "asset_class": "us_equity", "entry_timestamp": "2026-07-14T13:31:28Z",
                    "entry_fill_id": "fill-1", "entry_order_id": "order-1", "position_id": "pos-1",
                }],
            }
            ledger = engine._recover_broker_position_lane_horizon_v1(
                {"PH": _broker(entry_fill_id="", entry_timestamp="2026-07-14T13:31:31Z")},
                [_evidence(entry_timestamp="2026-07-14T13:31:28Z", entry_filled_at="2026-07-14T13:31:28Z")],
            )
        row = ledger["positions"][0]
        self.assertEqual((row["lane"], row["horizon"]), ("DAY", "scalp"))
        self.assertEqual(row["recovery_method"], "EXACT_ID_LINK")

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
