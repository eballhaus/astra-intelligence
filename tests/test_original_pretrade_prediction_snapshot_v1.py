from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.astra_entry_lane_horizon_contract_v1 import (
    AstraEntryLaneHorizonLedgerV1,
    build_entry_lane_horizon_contract_v1,
    link_entry_contract_v1,
)
from engine.astra_truth_learning_enrichment_v1 import (
    build_original_pretrade_prediction_snapshot_v1,
    build_pretrade_truth_context_v1,
    build_truth_learning_enrichment_v1,
)
from engine.paper_autopilot import PaperAutopilotEngine


def candidate(lane: str = "DAY", horizon: str = "intraday", **extra):
    row = {
        "symbol": "ABC", "asset_class": "crypto" if lane == "CRYPTO" else "equity", "asset_type": "crypto" if lane == "CRYPTO" else "stock",
        "lane_id": lane, "trade_horizon_style": horizon, "paper_entry_horizon_style": horizon,
        "lane_assignment_source": "TEST", "paper_entry_horizon_source": "TEST", "candidate_id": f"cand-{lane}", "selection_id": "sel-1",
        "predicted_direction": "UP", "thesis": "original thesis", "expected_return_pct": 3.0, "expected_downside": 1.5,
        "expected_hold_minutes": 60, "confidence": 81, "market_regime": "RISK_ON", "catalyst": "TEST", "ranking_factors": {"momentum": 0.8},
        "risk_envelope": {"maximum_loss_pct": 1.5}, "quantity": 2.0, "notional": 20.0,
        **extra,
    }
    return row


class OriginalPretradePredictionSnapshotV1Tests(unittest.TestCase):
    def test_snapshot_preserves_exact_context_for_all_lanes(self):
        horizons = {"DAY": "intraday", "SWING": "multi_day", "SCALP": "scalp", "CRYPTO": "crypto_short"}
        for lane, horizon in horizons.items():
            row = candidate(lane, horizon)
            contract = build_entry_lane_horizon_contract_v1(row)
            snapshot = build_original_pretrade_prediction_snapshot_v1(row, contract, lifecycle_id=f"life-{lane}", intended_entry_price=10.0)
            self.assertEqual(snapshot["lifecycle_id"], f"life-{lane}")
            self.assertEqual(snapshot["candidate_id"], f"cand-{lane}")
            self.assertEqual(snapshot["prediction_context"]["thesis"], "original thesis")
            self.assertTrue(snapshot["immutable_original_pretrade_prediction"])
            self.assertEqual(snapshot["snapshot_state"], "APPROVED_NOT_SUBMITTED")

    def test_ledger_keeps_first_snapshot_across_retry_and_acknowledgement(self):
        row = candidate()
        contract = build_entry_lane_horizon_contract_v1(row)
        original = build_original_pretrade_prediction_snapshot_v1(row, contract, lifecycle_id="life-1", intended_entry_price=10.0)
        contract["original_pretrade_prediction_snapshot_v1"] = original
        altered = build_original_pretrade_prediction_snapshot_v1(candidate(thesis="later change"), contract, lifecycle_id="life-1", intended_entry_price=20.0)
        with tempfile.TemporaryDirectory() as directory:
            ledger = AstraEntryLaneHorizonLedgerV1(directory)
            ledger.record(contract, "ORIGINAL_PRETRADE_PREDICTION_PERSISTED")
            retry = dict(contract); retry["original_pretrade_prediction_snapshot_v1"] = altered
            ledger.record(link_entry_contract_v1(retry, broker_order_id="broker-1"), "BROKER_ACKNOWLEDGED")
            stored = ledger.snapshot()["entries"][0]["original_pretrade_prediction_snapshot_v1"]
        self.assertEqual(stored["prediction_context"]["thesis"], "original thesis")
        self.assertEqual(stored["intended_entry_price"], 10.0)

    def test_truth_context_prefers_frozen_snapshot_over_later_row_values(self):
        row = candidate()
        contract = build_entry_lane_horizon_contract_v1(row)
        contract["original_pretrade_prediction_snapshot_v1"] = build_original_pretrade_prediction_snapshot_v1(row, contract, lifecycle_id="life-1")
        late = candidate(thesis="later monitoring thesis", expected_return_pct=99.0)
        context = build_pretrade_truth_context_v1(late, contract)
        enriched = build_truth_learning_enrichment_v1({"lifecycle_id": "life-1", "realized_return": 1.0}, pretrade_context=context)
        self.assertEqual(context["thesis"], "original thesis")
        self.assertEqual(context["expected_return_pct"], 3.0)
        self.assertEqual(enriched["prediction_accuracy_v1"]["forecast_error_pct_points"], -2.0)

    def test_missing_fields_remain_missing_not_guessed(self):
        row = candidate(thesis=None, expected_return_pct=None, confidence=None, catalyst=None)
        contract = build_entry_lane_horizon_contract_v1(row)
        snapshot = build_original_pretrade_prediction_snapshot_v1(row, contract, lifecycle_id="life-1")
        self.assertNotIn("thesis", snapshot["prediction_context"])
        self.assertIsNone(snapshot["intended_entry_price"])
        self.assertTrue(snapshot["missing_values_are_unavailable"])

    def test_snapshot_is_persisted_before_the_paper_broker_submit_call(self):
        class Session:
            def confirmation_for_candidate(self, *_args, **_kwargs):
                return {"paper_order_submission_allowed": True, "open_confirmation_label": "confirmed_execute", "market_session_mode": "regular", "quote_freshness_confirmed": True, "spread_liquidity_confirmed": True, "gap_behavior_confirmed": True, "entry_commitment_confirmed": True, "portfolio_risk_confirmed": True, "broker_preflight_confirmed": True}

        class Broker:
            def __init__(self, engine): self.engine = engine; self.snapshot_seen = False
            def submit_paper_order(self, _order):
                entries = self.engine.entry_lane_horizon_ledger.snapshot()["entries"]
                self.snapshot_seen = bool(entries and entries[0].get("original_pretrade_prediction_snapshot_v1"))
                return {"ok": True, "order": {"id": "broker-1", "client_order_id": _order["client_order_id"]}}

        row = candidate(lifecycle_id="life-before-submit", portfolio_risk_ok=True)
        contract = build_entry_lane_horizon_contract_v1(row); contract["lifecycle_id"] = "life-before-submit"; row["entry_lane_horizon_contract_v1"] = contract
        with tempfile.TemporaryDirectory() as directory, patch("engine.paper_autopilot.canonical_lane_activation_contract", return_value={"execution_enabled": True}):
            engine = PaperAutopilotEngine(db_path=f"{directory}/paper.db", state_path=f"{directory}/state.json", enabled=False)
            engine.market_session_timing_suite = Session()
            engine._alpaca_paper_broker_enabled = lambda: True
            engine._broker_open_symbols_snapshot = lambda: {"broker_reconciliation_active": True, "broker_positions_fetch_ok": True}
            broker = Broker(engine); engine.alpaca_paper_broker = broker
            result = engine._submit_alpaca_paper_entry_order(row, 10.0, gate_meta={"paper_autopilot_limits_ok": True})
        self.assertTrue(result["ok"])
        self.assertTrue(broker.snapshot_seen)

    def test_snapshot_is_not_completed_trade_learning_without_strict_truth(self):
        row = candidate(); contract = build_entry_lane_horizon_contract_v1(row)
        snapshot = build_original_pretrade_prediction_snapshot_v1(row, contract, lifecycle_id="life-unsubmitted")
        self.assertEqual(snapshot["snapshot_state"], "APPROVED_NOT_SUBMITTED")
        self.assertNotIn("truth_id", snapshot)


if __name__ == "__main__":
    unittest.main()
