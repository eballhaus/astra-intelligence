"""Targeted tests for profit protection, peak-gain preservation, and giveback control.

These tests use synthetic positions and temporary stores. They do not connect to
Alpaca or access live runtime data.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

from engine.astra_profit_protection_giveback_v1 import (
    LANE_GIVEBACK_BANDS,
    evaluate_position_profit_protection_v1,
    load_profit_protection_state_v1,
    run_profit_protection_review_v1,
    save_profit_protection_state_v1,
)
from engine.astra_legacy_quarantine_v1 import resolve_canonical_position_ownership_v1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _position(
    symbol: str = "AAPL",
    lane: str = "DAY",
    entry_price: float = 100.0,
    current_price: float = 110.0,
    quantity: float = 10.0,
    position_id: str = "p1",
    **kwargs,
):
    if entry_price > 0:
        unrealized_plpc = ((current_price - entry_price) / entry_price) * 100.0
    else:
        unrealized_plpc = 0.0
    return {
        "position_id": position_id,
        "symbol": symbol,
        "lane_id": lane,
        "entry_price": entry_price,
        "current_price": current_price,
        "qty": quantity,
        "market_value": current_price * quantity,
        "cost_basis": entry_price * quantity,
        "unrealized_pl": (current_price - entry_price) * quantity,
        "unrealized_plpc": unrealized_plpc,
        "last_update_ts": _now_iso(),
        **kwargs,
    }


class PeakEvidenceTests(unittest.TestCase):
    def test_no_peak_evidence_does_not_fabricate_protection(self):
        pos = _position(current_price=110.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "NO_PROFIT_HISTORY")
        self.assertEqual(d["canonical_recommendation"], "HOLD")
        self.assertIsNone(d["peak_gain_pct"])
        self.assertIsNone(d["giveback_ratio"])

    def test_peak_below_threshold_does_not_monitor(self):
        pos = _position(current_price=100.5, peak_unrealized_gain_pct=0.3)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["data_completeness"], "incomplete")
        self.assertTrue(any(b.startswith("PEAK_GAIN_BELOW_MONITORING_THRESHOLD") for b in d["exact_blockers"]))

    def test_peak_price_can_derive_peak_gain(self):
        pos = _position(current_price=110.0, peak_price=120.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["peak_gain_pct"], 20.0)
        self.assertTrue(d["peak_gain_pct"] > 0)

    def test_peak_dollars_can_derive_peak_gain(self):
        pos = _position(current_price=110.0, peak_unrealized_gain_dollars=200.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["peak_gain_pct"], 20.0)


class GivebackBandTests(unittest.TestCase):
    def test_small_giveback_remains_healthy(self):
        # peak 20%, current 18% -> 10% giveback -> healthy
        pos = _position(current_price=118.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "PROFIT_HEALTHY")
        self.assertEqual(d["canonical_recommendation"], "HOLD")

    def test_early_giveback_enters_watch(self):
        # peak 20%, current 15% -> 25% giveback -> watch
        pos = _position(current_price=115.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "PROFIT_WATCH")
        self.assertEqual(d["canonical_recommendation"], "WATCH")

    def test_material_giveback_produces_protect_profit(self):
        # peak 20%, current 11% -> 45% giveback -> protect profit
        pos = _position(current_price=111.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "PROTECT_PROFIT")
        self.assertEqual(d["canonical_recommendation"], "PROTECT_PROFIT")

    def test_severe_giveback_produces_exit_review(self):
        # peak 20%, current 7% -> 65% giveback -> exit review
        pos = _position(current_price=107.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "EXIT_REVIEW")
        self.assertEqual(d["canonical_recommendation"], "EXIT_REVIEW")

    def test_current_loss_not_mislabeled_as_protected_profit(self):
        pos = _position(current_price=95.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "EXIT_REVIEW")
        self.assertEqual(d["canonical_recommendation"], "EXIT_REVIEW")
        self.assertNotEqual(d["canonical_recommendation"], "PROTECT_PROFIT")


class LossContainmentPriorityTests(unittest.TestCase):
    def test_hard_boundary_defer_to_loss_containment(self):
        pos = _position(current_price=110.0, peak_unrealized_gain_pct=20.0)
        lc = {"threshold_state": "HARD_BOUNDARY_BREACH", "canonical_recommendation": "HARD_LOSS_EXIT_REQUIRED_ADVISORY"}
        d = evaluate_position_profit_protection_v1(pos, loss_containment_decision=lc)
        self.assertEqual(d["profit_state"], "LOSS_CONTAINMENT_PRIORITY")
        self.assertEqual(d["canonical_recommendation"], "DEFER_TO_LOSS_CONTAINMENT")

    def test_thesis_broken_loss_containment_overrides(self):
        pos = _position(current_price=110.0, peak_unrealized_gain_pct=20.0)
        lc = {"threshold_state": "THESIS_BROKEN", "canonical_recommendation": "THESIS_BROKEN"}
        d = evaluate_position_profit_protection_v1(pos, loss_containment_decision=lc)
        self.assertEqual(d["profit_state"], "LOSS_CONTAINMENT_PRIORITY")
        self.assertEqual(d["canonical_recommendation"], "DEFER_TO_LOSS_CONTAINMENT")

    def test_mandatory_review_loss_containment_overrides(self):
        pos = _position(current_price=110.0, peak_unrealized_gain_pct=20.0)
        lc = {"threshold_state": "MANDATORY_REVIEW", "canonical_recommendation": "EXIT_REVIEW"}
        d = evaluate_position_profit_protection_v1(pos, loss_containment_decision=lc)
        self.assertEqual(d["profit_state"], "LOSS_CONTAINMENT_PRIORITY")


class ThesisSupportMomentumTests(unittest.TestCase):
    def test_thesis_failure_overrides_profit_logic(self):
        pos = _position(
            current_price=115.0,
            peak_unrealized_gain_pct=20.0,
            thesis_broken=True,
        )
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "THESIS_BROKEN")
        self.assertEqual(d["canonical_recommendation"], "THESIS_BROKEN")

    def test_thesis_broken_without_peak_evidence_not_hold(self):
        """Regression: thesis broken without LC decision and without peak evidence must not return HOLD."""
        pos = _position(
            current_price=95.0,
            thesis_broken=True,
        )
        d = evaluate_position_profit_protection_v1(pos)
        self.assertNotEqual(d["canonical_recommendation"], "HOLD")
        self.assertNotEqual(d["profit_state"], "NO_PROFIT_HISTORY")
        self.assertEqual(d["canonical_recommendation"], "THESIS_BROKEN")
        self.assertEqual(d["profit_state"], "THESIS_BROKEN")

    def test_support_failure_increases_severity(self):
        pos = _position(
            current_price=115.0,
            peak_unrealized_gain_pct=20.0,
            support_failed=True,
        )
        d = evaluate_position_profit_protection_v1(pos)
        # Support failure reduces continuation confidence, likely moves to WATCH.
        self.assertIn(d["profit_state"], {"PROFIT_WATCH", "GIVEBACK_ELEVATED"})
        self.assertLess(d["continuation_confidence"], 0.7)

    def test_momentum_deterioration_increases_severity(self):
        pos = _position(
            current_price=115.0,
            peak_unrealized_gain_pct=20.0,
            momentum_state="DETERIORATING",
        )
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["momentum_state"], "DETERIORATING")
        self.assertIn(d["profit_state"], {"PROFIT_WATCH", "GIVEBACK_ELEVATED", "PROTECT_PROFIT", "EXIT_REVIEW"})

    def test_strong_continuation_preserves_hold(self):
        pos = _position(
            current_price=118.0,
            peak_unrealized_gain_pct=20.0,
            thesis="solid",
            thesis_supporting_conditions=["a", "b"],
            catalyst_state="active",
            momentum_state="IMPROVING",
        )
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "PROFIT_HEALTHY")
        self.assertEqual(d["canonical_recommendation"], "HOLD")
        self.assertGreaterEqual(d["continuation_confidence"], 0.7)


class RecoveryBoundsTests(unittest.TestCase):
    def test_recovery_cannot_continue_indefinitely(self):
        # Excessive giveback with intact thesis still produces exit review.
        pos = _position(
            current_price=107.0,
            peak_unrealized_gain_pct=20.0,
            thesis="still valid",
            thesis_supporting_conditions=["a"],
            momentum_state="IMPROVING",
        )
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "EXIT_REVIEW")


class FailClosedTests(unittest.TestCase):
    def _assert_safety(self, d):
        self.assertTrue(d["advisory_only"])
        self.assertFalse(d["execution_authorized"])
        self.assertFalse(d["paper_action_ready"])
        self.assertFalse(d["broker_submission_allowed"])

    def test_missing_lane_fails_closed(self):
        pos = _position(lane="")
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertIn("MISSING_LANE", d["exact_blockers"])
        self._assert_safety(d)

    def test_unknown_lane_fails_closed(self):
        pos = _position(lane="WEIRD")
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertIn("UNKNOWN_LANE:WEIRD", d["exact_blockers"])
        self._assert_safety(d)

    def test_missing_current_price_fails_closed(self):
        pos = _position(current_price=0.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertIn("MISSING_OR_INVALID_CURRENT_PRICE", d["exact_blockers"])

    def test_missing_entry_price_fails_closed(self):
        pos = _position(entry_price=0.0, cost_basis=0.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertIn("MISSING_OR_INVALID_ENTRY_PRICE", d["exact_blockers"])

    def test_stale_evidence_fails_closed(self):
        pos = _position(last_update_ts="2025-01-01T00:00:00Z")
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertTrue(any("STALE" in b for b in d["exact_blockers"]))

    def test_contradictory_peak_evidence_fails_closed(self):
        pos = _position(
            current_price=110.0,
            peak_unrealized_gain_pct=-5.0,
        )
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertTrue(any(b.startswith("PEAK_GAIN_BELOW_MONITORING_THRESHOLD") for b in d["exact_blockers"]))

    def test_unknown_ownership_fails_closed(self):
        pos = _position(lane="DAY")
        ownership = {"ownership": "UNKNOWN", "legacy_quarantined": False, "unresolved": True}
        d = evaluate_position_profit_protection_v1(pos, ownership=ownership)
        self.assertEqual(d["ownership_classification"], "UNRESOLVED_FAIL_CLOSED")

    def test_every_output_has_immutable_advisory_flags(self):
        pos = _position()
        d = evaluate_position_profit_protection_v1(pos)
        self._assert_safety(d)


class BrokerCanarySafetyTests(unittest.TestCase):
    def test_no_broker_method_called(self):
        pos = _position()
        # The engine is pure-Python and has no broker adapter references.
        self.assertNotIn("submit", evaluate_position_profit_protection_v1.__code__.co_names)

    def test_no_canary_path_exists(self):
        pos = _position()
        d = evaluate_position_profit_protection_v1(pos)
        self.assertNotIn("canary", d)
        self.assertNotIn("canary", str(d).lower())


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="astra_profit_protection_test_")
        self.path = os.path.join(self.tmpdir, "state.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_atomic_state_write_and_load(self):
        state = {
            "decisions": {"p1": {"symbol": "AAPL"}},
            "events": {"e1": {"event_type": "PROTECT_PROFIT"}},
        }
        save_profit_protection_state_v1(self.path, state)
        loaded = load_profit_protection_state_v1(self.path)
        self.assertTrue(loaded["loaded"])
        self.assertEqual(loaded["decisions"]["p1"]["symbol"], "AAPL")
        self.assertEqual(loaded["events"]["e1"]["event_type"], "PROTECT_PROFIT")

    def test_duplicate_events_prevented(self):
        pos = _position(current_price=111.0, peak_unrealized_gain_pct=20.0)
        result1 = run_profit_protection_review_v1([pos])
        state1 = result1["state"]
        result2 = run_profit_protection_review_v1([pos], prior_state=state1)
        events1 = {k: v for k, v in result1["state"]["events"].items() if v["event_type"] == "PROTECT_PROFIT"}
        events2 = {k: v for k, v in result2["state"]["events"].items() if v["event_type"] == "PROTECT_PROFIT"}
        self.assertEqual(len(events1), len(events2))

    def test_state_continuity_survives_restart(self):
        pos = _position(current_price=111.0, peak_unrealized_gain_pct=20.0)
        result = run_profit_protection_review_v1([pos])
        save_profit_protection_state_v1(self.path, result["state"])
        loaded = load_profit_protection_state_v1(self.path)
        result2 = run_profit_protection_review_v1([pos], prior_state=loaded)
        self.assertEqual(result2["position_decisions"][0]["symbol"], "AAPL")

    def test_retention_bounded(self):
        positions = [_position(position_id=f"p{i}", symbol=f"S{i}") for i in range(600)]
        result = run_profit_protection_review_v1(positions)
        self.assertLessEqual(len(result["state"]["decisions"]), 500)

    def test_malformed_prior_state_fails_closed(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not json")
        loaded = load_profit_protection_state_v1(self.path)
        self.assertFalse(loaded["loaded"])
        self.assertIsNone(loaded["forensic"])


class ReviewEnvelopeTests(unittest.TestCase):
    def test_lane_summaries_aggregated(self):
        positions = [
            _position(position_id="d1", symbol="AAPL", lane="DAY", current_price=118.0, peak_unrealized_gain_pct=20.0),
            _position(position_id="c1", symbol="BTC/USD", lane="CRYPTO", current_price=111.0, peak_unrealized_gain_pct=20.0),
            _position(position_id="s1", symbol="TSLA", lane="SWING", current_price=107.0, peak_unrealized_gain_pct=20.0),
        ]
        result = run_profit_protection_review_v1(positions)
        self.assertEqual(result["lane_summaries"]["DAY"]["healthy_profit"], 1)
        self.assertEqual(result["lane_summaries"]["CRYPTO"]["protect_profit"], 1)
        self.assertEqual(result["lane_summaries"]["SWING"]["exit_review"], 1)
        self.assertEqual(result["metrics"]["protect_profit_recommendations"], 1)
        self.assertEqual(result["metrics"]["exit_review_recommendations"], 1)

    def test_metrics_label_provisional(self):
        positions = [_position()]
        result = run_profit_protection_review_v1(positions)
        self.assertTrue(result["metrics"]["provisional_metrics"])
        self.assertIsNone(result["metrics"]["estimated_profit_preserved"])


class LegacyOwnershipTests(unittest.TestCase):
    def test_legacy_position_included_in_review(self):
        pos = _position(
            lane_id="SWING",
            position_owner="LEGACY_SWING_CANARY",
            exit_policy_owner="LEGACY_SWING_CONTROLLED_PAPER_CANARY_V1",
            current_price=115.0,
            peak_unrealized_gain_pct=20.0,
        )
        ownership = resolve_canonical_position_ownership_v1(pos)
        self.assertTrue(ownership["legacy_quarantined"])
        result = run_profit_protection_review_v1([pos], ownership_map={"p1": ownership})
        self.assertEqual(result["metrics"]["positions_evaluated"], 1)
        self.assertEqual(result["position_decisions"][0]["ownership_classification"], "LEGACY_QUARANTINED")

    def test_active_day_position_included(self):
        pos = _position(
            lane_id="DAY",
            position_owner="DAY",
            exit_policy_owner="DAY",
            current_price=118.0,
            peak_unrealized_gain_pct=20.0,
        )
        ownership = resolve_canonical_position_ownership_v1(pos)
        self.assertEqual(ownership["ownership"], "ACTIVE_DAY")
        result = run_profit_protection_review_v1([pos], ownership_map={"p1": ownership})
        self.assertEqual(result["position_decisions"][0]["ownership_classification"], "ACTIVE_DAY")


class PolicyContractTests(unittest.TestCase):
    def test_lane_bands_present(self):
        self.assertIn("DAY", LANE_GIVEBACK_BANDS)
        self.assertIn("CRYPTO", LANE_GIVEBACK_BANDS)
        self.assertIn("SWING", LANE_GIVEBACK_BANDS)
        for lane in LANE_GIVEBACK_BANDS:
            self.assertIn("early_watch_ratio", LANE_GIVEBACK_BANDS[lane])
            self.assertIn("protect_profit_ratio", LANE_GIVEBACK_BANDS[lane])
            self.assertIn("exit_review_ratio", LANE_GIVEBACK_BANDS[lane])
            self.assertIn("minimum_retained_gain_pct", LANE_GIVEBACK_BANDS[lane])

    def test_day_reacts_faster_than_swing(self):
        self.assertLess(LANE_GIVEBACK_BANDS["DAY"]["protect_profit_ratio"], LANE_GIVEBACK_BANDS["SWING"]["protect_profit_ratio"])

    def test_crypto_tolerates_more_volatility(self):
        self.assertGreater(LANE_GIVEBACK_BANDS["CRYPTO"]["early_watch_ratio"], LANE_GIVEBACK_BANDS["DAY"]["early_watch_ratio"])


class GivebackBoundaryTests(unittest.TestCase):
    """Exact threshold boundary tests to prevent decimal/percentage confusion."""

    def test_current_gain_above_recorded_peak_no_false_protection(self):
        pos = _position(current_price=120.0, peak_unrealized_gain_pct=10.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "PROFIT_HEALTHY")
        self.assertLess(d["giveback_ratio"], 0)
        self.assertIsNotNone(d["giveback_ratio"])

    def test_day_early_watch_boundary(self):
        pos = _position(current_price=114.9, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        expected_watch = d["profit_state"] in {"PROFIT_WATCH", "GIVEBACK_ELEVATED"}
        self.assertTrue(expected_watch, f"got {d['profit_state']}")
        self.assertIn(d["canonical_recommendation"], {"WATCH", "TIGHTEN_REVIEW"})

    def test_day_protect_profit_boundary(self):
        pos = _position(current_price=112.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "PROTECT_PROFIT")
        self.assertEqual(d["canonical_recommendation"], "PROTECT_PROFIT")

    def test_day_exit_review_boundary(self):
        pos = _position(current_price=108.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "EXIT_REVIEW")
        self.assertEqual(d["canonical_recommendation"], "EXIT_REVIEW")

    def test_current_return_at_zero_after_peak(self):
        pos = _position(current_price=100.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "EXIT_REVIEW")
        self.assertEqual(d["canonical_recommendation"], "EXIT_REVIEW")

    def test_crypto_early_watch_band_exercised(self):
        pos = _position(symbol="BTC/USD", lane="CRYPTO", current_price=113.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertIn(d["profit_state"], {"PROFIT_WATCH", "GIVEBACK_ELEVATED"})

    def test_loss_containment_fail_closed_takes_priority(self):
        pos = _position(current_price=110.0, peak_unrealized_gain_pct=20.0)
        lc = {"threshold_state": "DATA_INCOMPLETE_FAIL_CLOSED", "canonical_recommendation": "DATA_INCOMPLETE_FAIL_CLOSED"}
        d = evaluate_position_profit_protection_v1(pos, loss_containment_decision=lc)
        self.assertEqual(d["profit_state"], "LOSS_CONTAINMENT_PRIORITY")
        self.assertEqual(d["canonical_recommendation"], "DEFER_TO_LOSS_CONTAINMENT")

    def test_swing_giveback_bands_exercised(self):
        pos = _position(symbol="TSLA", lane="SWING", current_price=108.0, peak_unrealized_gain_pct=20.0)
        d = evaluate_position_profit_protection_v1(pos)
        self.assertEqual(d["profit_state"], "EXIT_REVIEW")
        self.assertEqual(d["canonical_recommendation"], "EXIT_REVIEW")


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="astra_profit_protection_intel_")
        self.db_path = os.path.join(self.tmpdir, "ai_trading_memory.db")
        self.state_path = os.path.join(self.tmpdir, "paper_autopilot_state.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _can_import_paper_autopilot(self):
        try:
            from engine.paper_autopilot import PaperAutopilotEngine
            return PaperAutopilotEngine
        except Exception as exc:
            self.skipTest(f"PaperAutopilotEngine unavailable: {exc}")

    def test_profit_protection_broker_failed_metadata(self):
        """Failed broker fetch must produce correct metadata in profit protection."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        result = engine._profit_protection_review_phase(
            broker_fetch_succeeded=False,
            max_positions=100,
        )
        self.assertFalse(result.get("broker_fetch_succeeded", True))
        self.assertFalse(result.get("position_truth_available", True))
        self.assertEqual(result.get("observation_state"), "FAILED")
        self.assertIsNone(result.get("confirmed_open_position_count"))
        self.assertEqual(result.get("first_phase_blocker"), "BROKER_POSITION_EVIDENCE_UNAVAILABLE")

    def test_profit_protection_broker_empty_metadata(self):
        """Successful empty broker fetch must produce correct metadata in profit protection."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        result = engine._profit_protection_review_phase(
            broker_position_by_symbol={},
            broker_fetch_succeeded=True,
            max_positions=100,
        )
        self.assertTrue(result.get("broker_fetch_succeeded", False))
        self.assertTrue(result.get("position_truth_available", False))
        self.assertEqual(result.get("observation_state"), "READY")
        self.assertEqual(result.get("confirmed_open_position_count"), 0)
        self.assertIsNone(result.get("first_phase_blocker"))

    def test_broker_positions_override_explicit_db_rows(self):
        """When broker fetch succeeded, broker positions must override explicit DB rows."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        open_rows = [
            {
                "position_id": "d1",
                "symbol": "AAPL",
                "asset_type": "stock",
                "status": "OPEN",
                "quantity": 10,
                "qty": 10,
                "entry_price": 100.0,
                "current_price": 105.0,
                "market_value": 1050.0,
                "cost_basis": 1000.0,
                "unrealized_pl": 50.0,
                "unrealized_plpc": 5.0,
                "peak_unrealized_gain_pct": 10.0,
                "lane_id": "DAY",
                "position_owner": "DAY",
                "exit_policy_owner": "DAY",
                "last_update_ts": _now_iso(),
            }
        ]
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": 10,
                "avg_entry_price": 100.0,
                "current_price": 101.0,
                "asset_class": "stock",
                "lane_id": "DAY",
            }
        }
        result = engine._profit_protection_review_phase(
            open_rows=open_rows,
            broker_position_by_symbol=broker_positions,
            broker_fetch_succeeded=True,
            max_positions=100,
        )
        self.assertEqual(result.get("positions_evaluated"), 1)
        self.assertEqual(result["metrics"]["protect_profit_recommendations"], 0)
        decision = result["position_decisions"][0]
        self.assertEqual(decision["profit_state"], "NO_PROFIT_HISTORY")
        self.assertEqual(decision["symbol"], "AAPL")

    def test_broker_rows_enriched_with_db_lane_metadata(self):
        """Broker rows without lane/horizon must be enriched from DB rows for the same symbol."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        open_rows = [
            {
                "position_id": "d1",
                "symbol": "AAPL",
                "asset_type": "stock",
                "status": "OPEN",
                "quantity": 10,
                "qty": 10,
                "entry_price": 100.0,
                "current_price": 105.0,
                "market_value": 1050.0,
                "cost_basis": 1000.0,
                "unrealized_pl": 50.0,
                "unrealized_plpc": 5.0,
                "peak_unrealized_gain_pct": 10.0,
                "lane_id": "DAY",
                "paper_entry_horizon_style": "day_trade",
                "position_owner": "DAY",
                "exit_policy_owner": "DAY",
                "last_update_ts": _now_iso(),
            }
        ]
        # Broker position lacks lane/horizon/peak; broker price is healthy.
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": 10,
                "avg_entry_price": 100.0,
                "current_price": 101.0,
                "asset_class": "stock",
            }
        }
        result = engine._profit_protection_review_phase(
            open_rows=open_rows,
            broker_position_by_symbol=broker_positions,
            broker_fetch_succeeded=True,
            max_positions=100,
        )
        self.assertEqual(result.get("positions_evaluated"), 1)
        self.assertEqual(result["metrics"]["incomplete_data_fail_closed"], 0)
        self.assertEqual(result["metrics"]["protect_profit_recommendations"], 0)
        decision = result["position_decisions"][0]
        self.assertEqual(decision["profit_state"], "NO_PROFIT_HISTORY")
        self.assertEqual(decision["lane"], "DAY")
        self.assertEqual(decision["symbol"], "AAPL")

    def test_failed_broker_fetch_evicts_prior_decisions(self):
        """When broker fetch fails, prior profit-protection decisions must be evicted."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        engine._save_profit_protection_state({
            "schema_version": "astra_profit_protection_state_v1",
            "decisions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "profit_state": "PROTECT_PROFIT",
                    "canonical_recommendation": "PROTECT_PROFIT_ADVISORY",
                },
            },
            "events": {},
            "as_of": _now_iso(),
        })
        open_rows = [
            {
                "position_id": "d1",
                "symbol": "AAPL",
                "asset_type": "stock",
                "status": "OPEN",
                "quantity": 10,
                "qty": 10,
                "entry_price": 100.0,
                "current_price": 105.0,
                "market_value": 1050.0,
                "cost_basis": 1000.0,
                "unrealized_pl": 50.0,
                "unrealized_plpc": 5.0,
                "peak_unrealized_gain_pct": 10.0,
                "lane_id": "DAY",
                "last_update_ts": _now_iso(),
            }
        ]
        result = engine._profit_protection_review_phase(
            open_rows=open_rows,
            broker_fetch_succeeded=False,
            max_positions=100,
        )
        self.assertEqual(result.get("positions_evaluated"), 0)
        self.assertEqual(result.get("observation_state"), "FAILED")
        self.assertEqual(result.get("first_phase_blocker"), "BROKER_POSITION_EVIDENCE_UNAVAILABLE")
        self.assertEqual(len(result.get("position_decisions", [])), 0)
        state = engine._load_profit_protection_state()
        self.assertEqual(state.get("decisions"), {})
        # Phase metadata is preserved in the durable state file
        self.assertEqual(state.get("observation_state"), "FAILED")
        self.assertFalse(state.get("broker_fetch_succeeded"))
        self.assertIsNone(state.get("confirmed_open_position_count"))

    def test_durable_state_preserves_phase_metadata(self):
        """Phase metadata must round-trip through profit-protection state save/load."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": 10,
                "avg_entry_price": 100.0,
                "current_price": 101.0,
                "asset_class": "stock",
                "lane_id": "DAY",
            }
        }
        result = engine._profit_protection_review_phase(
            broker_position_by_symbol=broker_positions,
            broker_fetch_succeeded=True,
            max_positions=100,
        )
        self.assertEqual(result.get("observation_state"), "READY")
        self.assertTrue(result.get("broker_fetch_succeeded"))
        self.assertEqual(result.get("confirmed_open_position_count"), 1)
        self.assertIsNone(result.get("first_phase_blocker"))

        state = result.get("state", {})
        self.assertEqual(state.get("observation_state"), "READY")
        self.assertTrue(state.get("broker_fetch_succeeded"))
        self.assertEqual(state.get("confirmed_open_position_count"), 1)
        self.assertIsNone(state.get("first_phase_blocker"))

        loaded = engine._load_profit_protection_state()
        self.assertEqual(loaded.get("observation_state"), "READY")
        self.assertTrue(loaded.get("broker_fetch_succeeded"))
        self.assertEqual(loaded.get("confirmed_open_position_count"), 1)
        self.assertIsNone(loaded.get("first_phase_blocker"))


if __name__ == "__main__":
    unittest.main()
