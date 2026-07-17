import unittest

from engine.astra_unified_position_lifecycle_v1 import (
    build_legacy_swing_direct_confirmation_v1,
    build_legacy_swing_direct_evidence_coverage_v1,
    build_legacy_swing_forward_value_v1,
    build_legacy_swing_opportunity_cost_v1,
    build_legacy_swing_profit_capture_v1,
)
from engine.paper_autopilot import PaperAutopilotEngine


def _evidence():
    return {
        "MOMENTUM": {"status": "CURRENT", "record_id": "bar", "short_term_direction": "NEGATIVE"},
        "THESIS_STATE": {"status": "CURRENT", "record_id": "thesis", "thesis_state": "UNKNOWN"},
        "LIQUIDITY": {"status": "CURRENT", "record_id": "liquidity", "liquidity_state": "POOR"},
    }


def _position():
    return {"symbol": "FIXTURE", "position_id": "position-1", "broker_quote_record": {"record_id": "quote", "freshness_state": "CURRENT", "bid": 9.9, "ask": 10.0}}


def _decision():
    return {"position_id": "position-1", "symbol": "FIXTURE", "lane": "SWING", "classification": "REDUCE_RISK", "classification_confidence": 0.9, "forward_baseline": {"baseline_id": "activation-1"}}


class LegacySwingExitTruthClosureTests(unittest.TestCase):
    def test_current_multiple_direct_risk_signals_confirm_risk_reduction(self):
        result = build_legacy_swing_direct_confirmation_v1(_position(), _decision(), _evidence())
        self.assertEqual(result["confirmation_state"], "CONFIRMED_RISK_REDUCTION")
        self.assertGreaterEqual(result["confirmation_confidence"], 0.8)

    def test_fmp_or_single_negative_signal_cannot_confirm_thesis_failure(self):
        decision = {**_decision(), "classification": "THESIS_BROKEN"}
        result = build_legacy_swing_direct_confirmation_v1(_position(), decision, _evidence())
        self.assertEqual(result["confirmation_state"], "UNCONFIRMED")
        only_momentum = {**_evidence(), "LIQUIDITY": {"status": "CURRENT", "liquidity_state": "ACCEPTABLE"}}
        result = build_legacy_swing_direct_confirmation_v1(_position(), _decision(), only_momentum)
        self.assertEqual(result["confirmation_state"], "UNCONFIRMED")

    def test_stale_or_conflicting_evidence_blocks_confirmation(self):
        stale = {**_evidence(), "MOMENTUM": {"status": "CURRENT", "freshness": "STALE", "short_term_direction": "NEGATIVE"}}
        self.assertEqual(build_legacy_swing_direct_confirmation_v1(_position(), _decision(), stale)["confirmation_state"], "STALE")
        self.assertEqual(build_legacy_swing_direct_confirmation_v1({**_position(), "direct_evidence_conflicting": True}, _decision(), _evidence())["confirmation_state"], "CONFLICTING")

    def test_authoritative_full_fill_creates_truth_capacity_and_pending_effectiveness(self):
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {}
        item = {"action_id": "action-1", "order_id": "order-1", "client_order_id": "client-1", "position_id": "position-1", "symbol": "FIXTURE", "quantity": 2, "normalized_sell_qty": 2, "entry_order_id": "entry-1", "entry_fill_id": "entry-fill-1", "legacy_swing_canary_pre_submit": {"activation_id": "activation-1"}}
        result = engine._record_legacy_swing_exit_broker_update(item, {"id": "order-1", "status": "filled", "filled_qty": 2, "filled_avg_price": 10, "fill_id": "exit-fill-1"})
        lifecycle = engine._runtime_state["legacy_swing_exit_lifecycle"]
        self.assertEqual(result["reconciliation_state"], "RECONCILED_CLOSED")
        self.assertEqual(len(lifecycle["closures"]), 1)
        self.assertEqual(len(lifecycle["truths"]), 1)
        self.assertEqual(len(lifecycle["capacity_releases"]), 1)
        self.assertEqual(len(lifecycle["effectiveness"]), 1)
        self.assertTrue(next(iter(lifecycle["effectiveness"].values()))["evaluation_pending"])

    def test_partial_fill_never_closes_or_releases_capacity(self):
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {}
        item = {"action_id": "action-1", "order_id": "order-1", "position_id": "position-1", "symbol": "FIXTURE", "quantity": 2, "normalized_sell_qty": 2, "legacy_swing_canary_pre_submit": {"activation_id": "activation-1"}}
        result = engine._record_legacy_swing_exit_broker_update(item, {"id": "order-1", "status": "partially_filled", "filled_qty": 1, "filled_avg_price": 10}, {"qty": 1})
        lifecycle = engine._runtime_state["legacy_swing_exit_lifecycle"]
        self.assertEqual(result["reconciliation_state"], "RECONCILED_PARTIAL")
        self.assertFalse(lifecycle["closures"])
        self.assertFalse(lifecycle["capacity_releases"])

    def test_coverage_forward_value_opportunity_and_profit_capture_remain_advisory(self):
        position = {**_position(), "broker_asset_record": {"freshness_state": "CURRENT", "tradable": True}, "mfe": 5, "mae": -2, "peak_unrealized": 5, "profit_giveback_pct": 3, "unrealized_return_pct": 2, "days_held": 5, "return_per_day": 0.4}
        coverage = build_legacy_swing_direct_evidence_coverage_v1(position, {"baseline_id": "activation-1"}, _evidence())
        self.assertTrue(coverage["required_evidence_complete"])
        forward = build_legacy_swing_forward_value_v1(position, _decision(), coverage)
        opportunity = build_legacy_swing_opportunity_cost_v1(coverage, forward, {"replacement_analysis": {"qualified": True, "expected_advantage": 1.0}})
        capture = build_legacy_swing_profit_capture_v1(position, coverage)
        self.assertEqual(opportunity["opportunity_cost_state"], "REPLACE_CANDIDATE")
        self.assertTrue(opportunity["advisory_only"])
        self.assertEqual(capture["profit_capture_state"], "PROTECT_PROFIT")

    def test_incomplete_coverage_blocks_confirmation_and_forward_value(self):
        coverage = build_legacy_swing_direct_evidence_coverage_v1(_position(), {"baseline_id": "activation-1"}, {**_evidence(), "LIQUIDITY": {"status": "MISSING"}})
        self.assertFalse(coverage["required_evidence_complete"])
        self.assertEqual(build_legacy_swing_forward_value_v1(_position(), _decision(), coverage)["forward_value_state"], "INSUFFICIENT_FORWARD_EVIDENCE")
        self.assertEqual(build_legacy_swing_direct_confirmation_v1({**_position(), "direct_evidence_coverage": coverage}, _decision(), _evidence())["confirmation_state"], "INSUFFICIENT")


if __name__ == "__main__":
    unittest.main()
