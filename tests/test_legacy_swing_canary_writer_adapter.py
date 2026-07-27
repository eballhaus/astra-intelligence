import unittest
from unittest.mock import patch

from engine.astra_unified_position_lifecycle_v1 import (
    build_legacy_swing_canary_pre_submit_v1,
    evaluate_legacy_swing_canary_eligibility_v1,
    legacy_swing_canary_configuration_v1,
    select_legacy_swing_canary_candidate_v1,
)
from engine.paper_autopilot import PaperAutopilotEngine


class _CountingBroker:
    def __init__(self):
        self.submit_calls = 0

    def submit_paper_order(self, _order):
        self.submit_calls += 1
        return {"ok": True}


def _valid_pre_submit() -> tuple[dict, dict]:
    config = legacy_swing_canary_configuration_v1({})
    position = {"symbol": "AAA", "asset_id": "asset-a", "qty": 20, "qty_available": 20, "current_price": 10, "paper_mode_verified": True, "legacy_book_notional": 10_000.0,
                "broker_quote_record": {"response_state": "SUCCESS", "freshness_state": "CURRENT", "bid": 9.99, "ask": 10.0},
                "broker_asset_record": {"response_state": "SUCCESS", "freshness_state": "CURRENT", "tradable": True}}
    decision = {
        "position_id": "asset-a", "symbol": "AAA", "lane": "SWING", "cohort": "LEGACY_PRE_CONTRACT_POSITION",
        "classification": "THESIS_BROKEN", "forecast_confidence": 0.95,
        "current_direct_confirmation": True, "direct_confirmation_confidence": 0.95,
        "forward_baseline": {"baseline_id": "baseline-a", "legacy_activation_timestamp": "2026-07-16T00:00:00Z"},
        "shadow_twin": {"state": "POSITION_SHADOW_TWIN_ACTIVE"},
        "provisional_horizon": {"provisional_horizon": "SWING_MULTI_WEEK"}, "evidence_rows": [],
        "required_evidence": {"MOMENTUM": {"status": "CURRENT"}, "THESIS_STATE": {"status": "CURRENT"}, "LIQUIDITY": {"status": "CURRENT", "liquidity_state": "ACCEPTABLE"}},
    }
    eligibility = evaluate_legacy_swing_canary_eligibility_v1(position, decision, config)
    selection = select_legacy_swing_canary_candidate_v1([{
        "position_id": "asset-a", "symbol": "AAA", "technical_eligibility": True,
        "decision": decision, "eligibility": eligibility,
    }])
    pre_submit = build_legacy_swing_canary_pre_submit_v1(
        position=position, lifecycle_decision=decision, eligibility=eligibility,
        selection=selection, configuration=config,
    )
    pre_submit["legacy_book_notional"] = 10_000.0
    return pre_submit, position


class LegacySwingCanaryWriterAdapterTests(unittest.TestCase):
    def setUp(self):
        self.engine = object.__new__(PaperAutopilotEngine)
        self.broker = _CountingBroker()
        self.engine.alpaca_paper_broker = self.broker
        self.engine._runtime_state = {}
        self.engine.approval_enforcement = False  # Tests bypass approval gate to test lower logic
        self.engine.learned_exit_validation_kill_switch = True
        self.engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "live_endpoint_detected": False}  # type: ignore[method-assign]
        self._disabled_config = patch("engine.paper_autopilot.legacy_swing_canary_configuration_v1", return_value=legacy_swing_canary_configuration_v1({}))
        self._disabled_config.start()
        self.addCleanup(self._disabled_config.stop)

    def test_valid_pre_submit_reaches_writer_and_is_disabled_before_broker(self):
        pre_submit, position = _valid_pre_submit()
        result = self.engine.legacy_swing_canary_writer_pre_submit(pre_submit, {"qty_available": position["qty"]})
        writer = result["writer_result"]
        self.assertEqual(result["adapter_state"], "ADAPTER_MAPPING_VALID")
        self.assertEqual(result["writer_state"], "WRITER_PATH_CONNECTED")
        self.assertEqual(writer["canary_state"], "CANARY_DISABLED")
        self.assertEqual(writer["kill_switch_state"], "KILL_SWITCH_ACTIVE")
        self.assertEqual(writer["execution_state"], "EXECUTION_NOT_AUTHORIZED")
        self.assertTrue(writer["broker_submission_blocked"])
        self.assertEqual(self.broker.submit_calls, 0)
        self.assertLessEqual(result["normalized_notional"], 100.0)
        self.assertLessEqual(result["normalized_notional"], result["max_legacy_book_notional"])

    def test_active_canary_safety_uncertainty_blocks_before_broker_submission(self):
        pre_submit, position = _valid_pre_submit()
        pre_submit["execution_authorized"] = True
        active = {**legacy_swing_canary_configuration_v1({}), "enabled": True, "kill_switch": False}
        self.engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "live_endpoint_detected": True}  # type: ignore[method-assign]
        with patch("engine.paper_autopilot.legacy_swing_canary_configuration_v1", return_value=active):
            result = self.engine.legacy_swing_canary_writer_pre_submit(pre_submit, {"qty_available": position["qty"]})
        self.assertEqual(result["writer_state"], "POLICY_BLOCKED")
        self.assertEqual(result["reason"], "PAPER_ONLY_BROKER_BOUNDARY_REQUIRED")
        self.assertEqual(result["broker_actions"], 0)
        self.assertEqual(self.broker.submit_calls, 0)

    def test_adapter_ids_are_deterministic_and_idempotent(self):
        pre_submit, position = _valid_pre_submit()
        first = self.engine.legacy_swing_canary_writer_pre_submit(pre_submit, {"qty_available": position["qty"]})
        second = self.engine.legacy_swing_canary_writer_pre_submit(pre_submit, {"qty_available": position["qty"]})
        self.assertEqual(first["writer_result"]["contract"]["lane_id"], "SWING")
        self.assertEqual(pre_submit["action_id"], pre_submit["idempotency_key"])
        self.assertEqual(first["writer_result"]["normalized_sell_qty"], second["writer_result"]["normalized_sell_qty"])
        self.assertEqual(self.broker.submit_calls, 0)

    def test_ordinary_swing_remains_blocked_without_adapter_marker(self):
        result = self.engine._submit_authorized_lane_exit(
            {"lane_id": "SWING", "symbol": "AAA", "position_id": "asset-a", "quantity": 1},
            {"qty_available": 1}, "fixture",
        )
        self.assertFalse(result["submitted"])
        self.assertEqual(result["reason"], "lane_not_authorized_for_v2_exit")
        self.assertEqual(self.broker.submit_calls, 0)

    def test_legacy_book_cap_blocks_before_writer_boundary(self):
        pre_submit, position = _valid_pre_submit()
        pre_submit["legacy_book_notional"] = 1_000.0
        result = self.engine.legacy_swing_canary_writer_pre_submit(pre_submit, {"qty_available": position["qty"]})
        self.assertEqual(result["adapter_state"], "ADAPTER_MAPPING_INVALID")
        self.assertEqual(result["reason"], "LEGACY_BOOK_PERCENTAGE_LIMIT_EXCEEDED")
        self.assertEqual(self.broker.submit_calls, 0)


if __name__ == "__main__":
    unittest.main()
