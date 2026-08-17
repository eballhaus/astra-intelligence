"""Mandatory metadata coverage for future paper entries."""
from __future__ import annotations

import tempfile
import unittest

from engine.astra_entry_lane_horizon_contract_v1 import (
    AstraEntryLaneHorizonLedgerV1,
    build_entry_lane_horizon_contract_v1,
    link_entry_contract_v1,
    validate_entry_submission_contract_v1,
)
from engine.astra_position_lane_horizon_recovery_v1 import build_position_lane_horizon_recovery_v1
from engine.paper_autopilot import _normalize_paper_entry_bridge


def _row(**extra):
    return {
        "symbol": "DAYX", "asset_class": "equity", "lane_id": "DAY",
        "trade_horizon_style": "intraday", "lane_assignment_source": "TEST_ASSIGNMENT",
        "paper_entry_horizon_source": "TEST_HORIZON_ASSIGNMENT", "candidate_id": "cand-1",
        "selection_id": "sel-1", "candidate_generated_at": "2026-07-24T00:00:00Z", **extra,
    }


class EntryLaneHorizonContractTests(unittest.TestCase):
    def test_aliases_normalize_without_defaulting(self):
        day = build_entry_lane_horizon_contract_v1(_row())
        scalp = build_entry_lane_horizon_contract_v1(_row(lane_id="SCALP", trade_horizon_style="scalp"))
        swing = build_entry_lane_horizon_contract_v1(_row(lane_id="SWING", trade_horizon_style="multi_day"))
        crypto = build_entry_lane_horizon_contract_v1(_row(symbol="BTC/USD", asset_class="crypto", lane_id="CRYPTO", trade_horizon_style="crypto_short"))
        self.assertEqual((day["lane"], day["horizon"]), ("DAY", "day_trade"))
        self.assertEqual((scalp["lane"], scalp["horizon"]), ("SCALP", "scalp"))
        self.assertEqual((swing["lane"], swing["horizon"]), ("SWING", "swing_trade"))
        self.assertEqual((crypto["lane"], crypto["horizon"]), ("CRYPTO", "crypto_multi_horizon"))

    def test_blank_raw_lane_yields_to_canonical_scalp_identity_after_registry_derivation(self):
        candidate = _row(
            symbol="GEHC",
            lane_id="SCALP",
            _entry_raw_lane="",
            trade_style="scalp",
            trade_horizon_style="scalp",
        )
        bridged = _normalize_paper_entry_bridge(candidate)
        contract = dict(bridged["entry_lane_horizon_contract_v1"])

        self.assertEqual(bridged["_entry_raw_lane"], "")
        self.assertEqual(bridged["lane_id"], "SCALP")
        self.assertEqual((contract["lane"], contract["horizon"]), ("SCALP", "scalp"))
        self.assertTrue(validate_entry_submission_contract_v1(contract)["allowed"])

    def test_raw_placeholders_do_not_shadow_valid_canonical_lane(self):
        for placeholder in ("", "unknown", "UNAVAILABLE", "missing", "None", "null", "N/A"):
            with self.subTest(placeholder=placeholder):
                contract = build_entry_lane_horizon_contract_v1(_row(
                    lane_id="SCALP",
                    trade_horizon_style="scalp",
                    _entry_raw_lane=placeholder,
                ))
                self.assertEqual(contract["lane"], "SCALP")
                self.assertTrue(validate_entry_submission_contract_v1(contract)["allowed"])

    def test_blank_raw_lane_preserves_existing_day_swing_and_crypto_contracts(self):
        cases = (
            ("DAY", "intraday", "equity", "DAY", "day_trade"),
            ("SWING", "swing_trade", "equity", "SWING", "swing_trade"),
            ("CRYPTO", "crypto_short", "crypto", "CRYPTO", "crypto_multi_horizon"),
        )
        for lane_id, horizon, asset_class, expected_lane, expected_horizon in cases:
            with self.subTest(lane=lane_id):
                contract = build_entry_lane_horizon_contract_v1(_row(
                    lane_id=lane_id,
                    asset_class=asset_class,
                    trade_horizon_style=horizon,
                    _entry_raw_lane="UNAVAILABLE",
                ))
                self.assertEqual((contract["lane"], contract["horizon"]), (expected_lane, expected_horizon))
                self.assertTrue(validate_entry_submission_contract_v1(contract)["allowed"])

    def test_genuinely_unclassified_lane_remains_unavailable_and_blocks_without_calls(self):
        contract = build_entry_lane_horizon_contract_v1(_row(
            lane_id="",
            _entry_raw_lane="unknown",
            trade_horizon_style="scalp",
        ))
        verdict = validate_entry_submission_contract_v1(contract)

        self.assertEqual(contract["lane"], "UNAVAILABLE")
        self.assertFalse(verdict["allowed"])
        self.assertIn("MISSING_CANONICAL_ENTRY_LANE", verdict["exact_blockers"])
        self.assertEqual((verdict["broker_actions_used"], verdict["provider_calls_used"]), (0, 0))

    def test_missing_or_invalid_metadata_fails_closed(self):
        for row, blocker in [
            (_row(lane_id=""), "MISSING_CANONICAL_ENTRY_LANE"),
            (_row(trade_horizon_style=""), "MISSING_CANONICAL_ENTRY_HORIZON"),
            (_row(lane_id="DEFAULT"), "INVALID_CANONICAL_ENTRY_LANE"),
            (_row(trade_horizon_style="forever"), "INVALID_CANONICAL_ENTRY_HORIZON"),
        ]:
            contract = build_entry_lane_horizon_contract_v1(row)
            verdict = validate_entry_submission_contract_v1(contract)
            self.assertFalse(verdict["allowed"])
            self.assertIn(blocker, verdict["exact_blockers"])

    def test_identity_ack_fill_and_restart_persist(self):
        contract = build_entry_lane_horizon_contract_v1(_row())
        linked = link_entry_contract_v1(contract, broker_client_order_id="client-1", broker_order_id="order-1", entry_fill_id="fill-1", lifecycle_id="life-1")
        with tempfile.TemporaryDirectory() as directory:
            ledger = AstraEntryLaneHorizonLedgerV1(directory)
            ledger.record(contract, "ORDER_INTENT_PERSISTED")
            ledger.record(linked, "ENTRY_FILL_LINKED")
            loaded = ledger.snapshot()["entries"][0]
        self.assertEqual(loaded["stage"], "ENTRY_FILL_LINKED")
        self.assertEqual((loaded["broker_order_id"], loaded["entry_fill_id"]), ("order-1", "fill-1"))

    def test_empty_worker_window_is_durably_timestamped(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = AstraEntryLaneHorizonLedgerV1(directory).ensure_snapshot()
        self.assertTrue(snapshot["generated_at"])
        self.assertEqual(snapshot["summary"]["entries"], 0)

    def test_exact_new_entry_recovery_prefers_order_link(self):
        contract = link_entry_contract_v1(build_entry_lane_horizon_contract_v1(_row()), broker_order_id="order-1")
        ledger = build_position_lane_horizon_recovery_v1(
            {"DAYX": {"symbol": "DAYX", "asset_class": "equity", "entry_order_id": "order-1"}},
            evidence_rows=[{
                "symbol": "DAYX", "asset_type": "equity", "entry_order_id": "order-1",
                "entry_metadata_generation": "V1_MANDATORY", "entry_metadata_json": contract,
                "recovery_source_type": "ORDER_LINKED_ASSIGNMENT",
            }],
        )
        row = ledger["positions"][0]
        self.assertEqual((row["lane"], row["horizon"], row["recovery_method"]), ("DAY", "day_trade", "ORDER_LINKED"))

    def test_production_submission_blocks_before_broker_call(self):
        from engine.paper_autopilot import PaperAutopilotEngine

        class Broker:
            called = False
            def submit_paper_order(self, _order):
                self.called = True
                return {"ok": True}

        with tempfile.TemporaryDirectory() as directory:
            engine = PaperAutopilotEngine(db_path=f"{directory}/db.sqlite", state_path=f"{directory}/state.json", enabled=False)
            broker = Broker(); engine.alpaca_paper_broker = broker
            engine._alpaca_paper_broker_enabled = lambda: True
            result = engine._submit_alpaca_paper_entry_order(_row(lane_id=""), 10.0, gate_meta={})
        self.assertFalse(result["paper_order_submitted"])
        self.assertEqual(result["error"], "MISSING_CANONICAL_ENTRY_LANE")
        self.assertFalse(broker.called)


if __name__ == "__main__":
    unittest.main()
