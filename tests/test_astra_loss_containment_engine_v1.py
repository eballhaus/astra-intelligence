"""Targeted tests for lane-specific loss containment, bounce-back preservation,
and hard drawdown protection.

These tests use temporary stores and synthetic positions. They do not connect to
Alpaca or access live runtime data.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from datetime import datetime, timezone

from engine.astra_loss_containment_engine_v1 import (
    LANE_LOSS_THRESHOLDS,
    evaluate_position_loss_containment_v1,
    load_loss_containment_state_v1,
    run_loss_containment_review_v1,
    save_loss_containment_state_v1,
)
from engine.astra_legacy_quarantine_v1 import resolve_canonical_position_ownership_v1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _position(
    symbol: str = "AAPL",
    lane: str = "DAY",
    entry_price: float = 100.0,
    current_price: float = 100.0,
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


class ThresholdTests(unittest.TestCase):
    def test_day_just_below_early_review(self):
        pos = _position(current_price=98.11)  # -1.889%
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "HEALTHY")
        self.assertEqual(d["canonical_recommendation"], "HOLD")

    def test_day_at_early_review(self):
        pos = _position(current_price=98.0)  # -2.0%
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "EARLY_REVIEW")
        self.assertEqual(d["canonical_recommendation"], "WATCH")

    def test_day_at_mandatory_review(self):
        pos = _position(current_price=97.0)  # -3.0%
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "MANDATORY_REVIEW")
        self.assertEqual(d["canonical_recommendation"], "EXIT_REVIEW")

    def test_day_at_hard_boundary(self):
        pos = _position(current_price=96.0)  # -4.0%
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "HARD_BOUNDARY_BREACH")
        self.assertEqual(d["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")
        self.assertFalse(d["execution_authorized"])

    def test_crypto_at_hard_boundary(self):
        pos = _position(symbol="BTC/USD", lane="CRYPTO", entry_price=100.0, current_price=94.0)
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "HARD_BOUNDARY_BREACH")
        self.assertEqual(d["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")

    def test_swing_at_hard_boundary(self):
        pos = _position(symbol="TSLA", lane="SWING", entry_price=100.0, current_price=92.0)
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "HARD_BOUNDARY_BREACH")
        self.assertEqual(d["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")

    def test_values_immediately_around_thresholds_deterministic(self):
        # DAY thresholds at -2.0, -3.0, -4.0
        for price, expected in [(98.01, "HEALTHY"), (98.0, "EARLY_REVIEW"), (97.01, "EARLY_REVIEW"), (97.0, "MANDATORY_REVIEW"), (96.01, "MANDATORY_REVIEW"), (96.0, "HARD_BOUNDARY_BREACH")]:
            with self.subTest(price=price, expected=expected):
                d = evaluate_position_loss_containment_v1(_position(current_price=price))
                self.assertEqual(d["threshold_state"], expected)

    def test_positive_positions_never_trigger_loss_logic(self):
        pos = _position(current_price=150.0)
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "HEALTHY")
        self.assertEqual(d["canonical_recommendation"], "HOLD")

    def test_thresholds_match_policy_version(self):
        self.assertEqual(LANE_LOSS_THRESHOLDS["DAY"]["early_review_pct"], -2.0)
        self.assertEqual(LANE_LOSS_THRESHOLDS["DAY"]["mandatory_review_pct"], -3.0)
        self.assertEqual(LANE_LOSS_THRESHOLDS["DAY"]["hard_boundary_pct"], -4.0)
        self.assertEqual(LANE_LOSS_THRESHOLDS["CRYPTO"]["hard_boundary_pct"], -6.0)
        self.assertEqual(LANE_LOSS_THRESHOLDS["SWING"]["hard_boundary_pct"], -8.0)


class RecoveryTests(unittest.TestCase):
    def test_mandatory_review_with_intact_thesis_and_improving_momentum_recovery(self):
        pos = _position(
            current_price=97.0,
            thesis="strong catalyst",
            thesis_supporting_conditions=["support intact", "catalyst active"],
            momentum_state="IMPROVING",
        )
        d = evaluate_position_loss_containment_v1(pos)
        # The loss threshold is MANDATORY_REVIEW, but intact thesis and improving
        # momentum promote the canonical state to BOUNDED_RECOVERY.
        self.assertEqual(d["threshold_state"], "BOUNDED_RECOVERY")
        self.assertTrue(d["recovery"]["recovery_eligible"])
        self.assertEqual(d["canonical_recommendation"], "BOUNDED_RECOVERY")
        self.assertIn("recovery_window_minutes", d["recovery"])
        self.assertIn("recovery_expires_at", d["recovery"])

    def test_recovery_has_expiration(self):
        pos = _position(
            current_price=97.0,
            thesis="x",
            thesis_supporting_conditions=["a"],
            momentum_state="IMPROVING",
        )
        d = evaluate_position_loss_containment_v1(pos)
        self.assertIsNotNone(d["recovery"]["recovery_expires_at"])
        self.assertIsNotNone(d["recovery"]["recovery_window_minutes"])

    def test_recovery_cannot_continue_after_hard_boundary(self):
        pos = _position(
            current_price=95.0,
            thesis="x",
            thesis_supporting_conditions=["a"],
            momentum_state="IMPROVING",
        )
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "HARD_BOUNDARY_BREACH")
        self.assertFalse(d["recovery"]["recovery_eligible"])
        self.assertIn("hard_boundary_breached", d["recovery"]["recovery_ineligible_reasons"])
        self.assertEqual(d["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")

    def test_recovery_cannot_continue_after_thesis_failure(self):
        pos = _position(
            current_price=97.0,
            thesis_broken=True,
            momentum_state="IMPROVING",
        )
        d = evaluate_position_loss_containment_v1(pos)
        self.assertFalse(d["recovery"]["recovery_eligible"])
        self.assertIn("thesis_broken", d["recovery"]["recovery_ineligible_reasons"])

    def test_recovery_cannot_continue_with_stale_evidence(self):
        pos = _position(
            current_price=97.0,
            last_update_ts="2025-01-15T00:00:00Z",
            momentum_state="IMPROVING",
        )
        d = evaluate_position_loss_containment_v1(pos)
        self.assertFalse(d["recovery"]["recovery_eligible"])
        self.assertIn("critical_evidence_incomplete", d["recovery"]["recovery_ineligible_reasons"])

    def test_rebound_alone_cannot_override_hard_breach(self):
        pos = _position(
            current_price=94.0,
            thesis="x",
            thesis_supporting_conditions=["a"],
            momentum_state="IMPROVING",
            catalyst_state="active",
        )
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "HARD_BOUNDARY_BREACH")
        self.assertEqual(d["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")
        self.assertFalse(d["recovery"]["recovery_eligible"])


class LegacyTests(unittest.TestCase):
    def test_legacy_position_beyond_boundary_is_preexisting_breach(self):
        pos = _position(
            current_price=95.0,
            lane_id="DAY",
            position_owner="DAY",
            exit_policy_owner="DAY",
            legacy_forward_only_management=True,
        )
        ownership = resolve_canonical_position_ownership_v1(pos)
        d = evaluate_position_loss_containment_v1(pos, ownership=ownership)
        self.assertTrue(d["hard_boundary"]["preexisting_breach"])
        self.assertFalse(d["hard_boundary"]["new_breach"])
        self.assertEqual(d["threshold_state"], "HARD_BOUNDARY_BREACH")

    def test_legacy_position_included_in_total_exposure_via_review(self):
        pos = _position(
            current_price=98.0,
            lane_id="DAY",
            position_owner="DAY",
            exit_policy_owner="DAY",
            legacy_forward_only_management=True,
        )
        ownership = resolve_canonical_position_ownership_v1(pos)
        result = run_loss_containment_review_v1([pos], ownership_map={"p1": ownership})
        self.assertEqual(result["metrics"]["positions_evaluated"], 1)
        self.assertEqual(result["position_decisions"][0]["ownership_classification"], "LEGACY_QUARANTINED")

    def test_legacy_classification_consumed_from_quarantine_owner(self):
        pos = _position(
            lane_id="SWING",
            position_owner="LEGACY_SWING_CANARY",
            exit_policy_owner="LEGACY_SWING_CONTROLLED_PAPER_CANARY_V1",
        )
        ownership = resolve_canonical_position_ownership_v1(pos)
        self.assertTrue(ownership["legacy_quarantined"])
        d = evaluate_position_loss_containment_v1(pos, ownership=ownership)
        self.assertEqual(d["ownership_classification"], "LEGACY_QUARANTINED")


class SafetyTests(unittest.TestCase):
    def _assert_safety_flags(self, d):
        self.assertTrue(d["advisory_only"])
        self.assertFalse(d["execution_authorized"])
        self.assertFalse(d["paper_action_ready"])
        self.assertFalse(d["broker_submission_allowed"])

    def test_every_output_has_safety_flags(self):
        pos = _position()
        d = evaluate_position_loss_containment_v1(pos)
        self._assert_safety_flags(d)

    def test_hard_boundary_still_unauthorized(self):
        pos = _position(current_price=90.0)
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")
        self._assert_safety_flags(d)

    def test_missing_lane_fails_closed(self):
        pos = _position(lane="")
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertIn("MISSING_LANE", d["exact_blockers"])
        self._assert_safety_flags(d)

    def test_missing_entry_price_fails_closed(self):
        pos = _position(entry_price=0.0, cost_basis=0.0)
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertIn("MISSING_OR_INVALID_ENTRY_PRICE", d["exact_blockers"])

    def test_missing_current_price_fails_closed(self):
        pos = _position(current_price=0.0)
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertIn("MISSING_OR_INVALID_CURRENT_PRICE", d["exact_blockers"])

    def test_stale_data_fails_closed(self):
        pos = _position(last_update_ts="2025-01-01T00:00:00Z")
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertTrue(any("STALE" in b for b in d["exact_blockers"]))

    def test_unknown_lane_fails_closed(self):
        pos = _position(lane="WEIRD")
        d = evaluate_position_loss_containment_v1(pos)
        self.assertEqual(d["threshold_state"], "DATA_INCOMPLETE_FAIL_CLOSED")
        self.assertIn("UNKNOWN_LANE:WEIRD", d["exact_blockers"])

    def test_review_output_has_all_safety_flags(self):
        pos = _position()
        result = run_loss_containment_review_v1([pos])
        self.assertTrue(result["advisory_only"])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["paper_action_ready"])
        self.assertFalse(result["broker_submission_allowed"])


class ProfitProtectionTests(unittest.TestCase):
    def test_peak_gain_then_giveback_protect_profit(self):
        pos = _position(
            current_price=110.0,
            peak_unrealized_gain_pct=25.0,
        )
        d = evaluate_position_loss_containment_v1(pos)
        self.assertTrue(d["profit_protection"]["protect_profit"])
        self.assertEqual(d["canonical_recommendation"], "PROTECT_PROFIT")

    def test_missing_peak_evidence_does_not_fabricate(self):
        pos = _position(current_price=110.0)
        d = evaluate_position_loss_containment_v1(pos)
        self.assertFalse(d["profit_protection"]["protect_profit"])
        self.assertFalse(d["profit_protection"]["profit_protection_available"])
        self.assertEqual(d["profit_protection"]["profit_protection_reason"], "peak_unrealized_gain_evidence_missing")

    def test_current_loss_not_mislabeled_as_protected_profit(self):
        pos = _position(
            current_price=95.0,
            peak_unrealized_gain_pct=10.0,
        )
        d = evaluate_position_loss_containment_v1(pos)
        self.assertFalse(d["profit_protection"]["protect_profit"])
        self.assertEqual(d["profit_protection"]["profit_protection_reason"], "current_loss_not_profit_protection_candidate")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="astra_loss_containment_test_")
        self.path = os.path.join(self.tmpdir, "state.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_atomic_state_write_and_load(self):
        state = {
            "schema_version": "astra_loss_containment_state_v1",
            "decisions": {"p1": {"symbol": "AAPL"}},
            "events": {"e1": {"event_type": "NEW_HARD_BOUNDARY_BREACH"}},
        }
        save_loss_containment_state_v1(self.path, state)
        loaded = load_loss_containment_state_v1(self.path)
        self.assertTrue(loaded["loaded"])
        self.assertEqual(loaded["decisions"]["p1"]["symbol"], "AAPL")
        self.assertEqual(loaded["events"]["e1"]["event_type"], "NEW_HARD_BOUNDARY_BREACH")

    def test_repeated_identical_cycle_does_not_duplicate_breach_events(self):
        pos = _position(current_price=90.0)
        result1 = run_loss_containment_review_v1([pos])
        state1 = result1["state"]
        result2 = run_loss_containment_review_v1([pos], prior_state=state1)
        events1 = {k: v for k, v in result1["state"]["events"].items() if v["event_type"] == "NEW_HARD_BOUNDARY_BREACH"}
        events2 = {k: v for k, v in result2["state"]["events"].items() if v["event_type"] == "NEW_HARD_BOUNDARY_BREACH"}
        self.assertEqual(len(events1), len(events2))

    def test_changed_severity_creates_updated_event(self):
        pos = _position(current_price=98.0)
        result1 = run_loss_containment_review_v1([pos])
        state1 = result1["state"]
        pos2 = _position(current_price=90.0)
        result2 = run_loss_containment_review_v1([pos2], prior_state=state1)
        breach_events = {k: v for k, v in result2["state"]["events"].items() if v["event_type"] == "NEW_HARD_BOUNDARY_BREACH"}
        self.assertEqual(len(breach_events), 1)

    def test_worker_restart_preserves_decision_continuity(self):
        pos = _position(current_price=90.0)
        result = run_loss_containment_review_v1([pos])
        save_loss_containment_state_v1(self.path, result["state"])
        loaded = load_loss_containment_state_v1(self.path)
        result2 = run_loss_containment_review_v1([pos], prior_state=loaded)
        self.assertEqual(result2["position_decisions"][0]["symbol"], "AAPL")

    def test_malformed_prior_state_fails_closed(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not json")
        loaded = load_loss_containment_state_v1(self.path)
        self.assertFalse(loaded["loaded"])
        self.assertIsNone(loaded["forensic"])

    def test_retention_bounded(self):
        positions = [_position(position_id=f"p{i}", symbol=f"S{i}") for i in range(600)]
        result = run_loss_containment_review_v1(positions)
        self.assertLessEqual(len(result["state"]["decisions"]), 500)


class ReviewEnvelopeTests(unittest.TestCase):
    def test_lane_summaries_aggregated(self):
        positions = [
            _position(position_id="d1", symbol="AAPL", lane="DAY", current_price=96.0),
            _position(position_id="c1", symbol="BTC/USD", lane="CRYPTO", current_price=93.0),
            _position(position_id="s1", symbol="TSLA", lane="SWING", current_price=94.0),  # -6% -> mandatory review
        ]
        result = run_loss_containment_review_v1(positions)
        self.assertEqual(result["lane_summaries"]["DAY"]["hard_boundary_breaches"], 1)
        self.assertEqual(result["lane_summaries"]["CRYPTO"]["hard_boundary_breaches"], 1)
        self.assertEqual(result["lane_summaries"]["SWING"]["mandatory_reviews"], 1)
        self.assertEqual(result["metrics"]["hard_boundary_breaches"], 2)

    def test_metrics_label_provisional(self):
        positions = [_position()]
        result = run_loss_containment_review_v1(positions)
        self.assertTrue(result["metrics"]["provisional_metrics"])
        self.assertIsNone(result["metrics"]["avoided_loss_estimate"])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="astra_loss_containment_paper_autopilot_test_")
        self.db_path = os.path.join(self.tmpdir, "ai_trading_memory.db")
        self.state_path = os.path.join(self.tmpdir, "paper_autopilot_state.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _can_import_paper_autopilot(self):
        try:
            from engine.paper_autopilot import PaperAutopilotEngine
            return PaperAutopilotEngine
        except Exception as exc:
            self.skipTest(f"PaperAutopilotEngine unavailable in this environment: {exc}")

    def test_paper_autopilot_loss_containment_phase_runs_and_is_advisory(self):
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        # Exercise the exact code path that previously referenced undefined _text
        # by passing open_rows with lane ownership directly to the review phase.
        open_rows = [
            {
                "position_id": "d1",
                "symbol": "AAPL",
                "asset_type": "stock",
                "status": "OPEN",
                "quantity": 10,
                "qty": 10,
                "entry_price": 100.0,
                "current_price": 90.0,
                "market_value": 900.0,
                "cost_basis": 1000.0,
                "unrealized_pl": -100.0,
                "unrealized_plpc": -10.0,
                "lane_id": "DAY",
                "position_owner": "DAY",
                "exit_policy_owner": "DAY",
                "last_update_ts": _now_iso(),
            }
        ]
        broker_positions = {
            "AAPL": {"qty": 10, "avg_entry_price": 100.0, "current_price": 90.0, "asset_class": "stock", "lane_id": "DAY"},
        }
        result = engine._loss_containment_review_phase(
            open_rows=open_rows,
            broker_position_by_symbol=broker_positions,
            max_positions=100,
        )
        self.assertEqual(result["metrics"]["hard_boundary_breaches"], 1)
        self.assertEqual(result["position_decisions"][0]["canonical_recommendation"], "HARD_LOSS_EXIT_REQUIRED_ADVISORY")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["paper_action_ready"])
        self.assertFalse(result["broker_submission_allowed"])

        # Also run the disabled cycle and confirm the summary is surfaced safely.
        cycle_result = engine.run_cycle()
        self.assertIn("loss_containment_review_v1", cycle_result)
        lc = cycle_result["loss_containment_review_v1"]
        self.assertNotEqual(lc.get("execution_authorized"), True)
        self.assertNotEqual(lc.get("paper_action_ready"), True)
        self.assertNotEqual(lc.get("broker_submission_allowed"), True)

    def test_review_phase_never_calls_broker_submission(self):
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        calls = []
        original = getattr(engine, "_submit_authorized_lane_exit", None)
        def fake(*args, **kwargs):
            calls.append((args, kwargs))
        engine._submit_authorized_lane_exit = fake
        try:
            engine._loss_containment_review_phase(open_rows=[], broker_position_by_symbol={})
        finally:
            if original is not None:
                engine._submit_authorized_lane_exit = original
        self.assertEqual(calls, [])

    def test_cycle_partial_path_includes_loss_containment(self):
        """Regression: CYCLE_PARTIAL short-cycle path must run loss containment.

        The enabled worker cycle returns early at the CYCLE_PARTIAL budget check
        before reaching the main loss-containment block. This test verifies that
        the short-cycle path now includes its own loss-containment review.
        """
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=True,
        )
        engine._ensure_schema()
        with engine._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_positions
                  (position_id, symbol, asset_type, status, quantity,
                   entry_price, entry_timestamp, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("d1", "AAPL", "stock", "OPEN", 10, 100.0,
                 "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z",
                 "2025-01-15T12:00:00Z"),
            )
            conn.commit()

        # Mock the canary pre-submit to return a CYCLE_PARTIAL state.
        def _partial_mock(_broker_positions):
            return {"market_activity": {"cycle_state": "CYCLE_PARTIAL_BUDGET"}}
        engine._refresh_legacy_swing_canary_pre_submit = _partial_mock

        # Mock broker snapshot to provide price data for loss containment.
        def _broker_snapshot():
            return {
                "broker_open_symbols": {"AAPL"},
                "broker_position_by_symbol": {
                    "AAPL": {
                        "qty": 10, "avg_entry_price": 100.0,
                        "current_price": 90.0, "asset_class": "stock",
                    },
                },
                "broker_reconciliation_active": True,
                "broker_positions_fetch_ok": True,
                "broker_open_positions_count": 1,
            }
        engine._broker_open_symbols_snapshot = _broker_snapshot

        # Must also supply refresh_crypto_rankings_fn and
        # refresh_equity_risk_envelopes_fn to avoid AttributeError.
        engine.refresh_crypto_rankings_fn = lambda: {}
        engine.refresh_equity_risk_envelopes_fn = lambda: {}

        result = engine.run_cycle()
        self.assertIn("loss_containment_review_v1", result)
        lc = result["loss_containment_review_v1"]
        self.assertNotEqual(lc.get("execution_authorized"), True)
        self.assertNotEqual(lc.get("paper_action_ready"), True)
        self.assertNotEqual(lc.get("broker_submission_allowed"), True)
        self.assertGreater(lc.get("positions_evaluated", 0), 0)

    def test_broker_fetch_failed_does_not_use_stale_db_positions(self):
        """When broker fetch fails, stale DB positions must not be evaluated."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        # Insert a stale-looking position into the DB
        with engine._connect() as conn:
            conn.execute(
                "INSERT INTO paper_positions (position_id, symbol, asset_type, status, quantity, "
                "entry_price, entry_timestamp, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("d1", "AAPL", "stock", "OPEN", 10, 100.0,
                 "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "2025-01-15T12:00:00Z"),
            )
            conn.commit()
        result = engine._loss_containment_review_phase(
            broker_fetch_succeeded=False,
            max_positions=100,
        )
        # DB rows must not be evaluated as current positions
        self.assertEqual(result.get("positions_evaluated", 0), 0)
        self.assertFalse(result.get("execution_authorized", True))
        self.assertEqual(len(result.get("position_decisions", [])), 0)
        # Failed-fetch metadata
        self.assertFalse(result.get("broker_fetch_succeeded", True))
        self.assertFalse(result.get("position_truth_available", True))
        self.assertEqual(result.get("observation_state"), "FAILED")
        self.assertIsNone(result.get("confirmed_open_position_count"))
        self.assertEqual(result.get("first_phase_blocker"), "BROKER_POSITION_EVIDENCE_UNAVAILABLE")

    def test_broker_fetch_empty_overrides_stale_db(self):
        """Successful empty broker result must clear stale DB positions."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        with engine._connect() as conn:
            conn.execute(
                "INSERT INTO paper_positions (position_id, symbol, asset_type, status, quantity, "
                "entry_price, entry_timestamp, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("d1", "AAPL", "stock", "OPEN", 10, 100.0,
                 "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "2025-01-15T12:00:00Z"),
            )
            conn.commit()
        result = engine._loss_containment_review_phase(
            broker_position_by_symbol={},
            broker_fetch_succeeded=True,
            max_positions=100,
        )
        # With successful empty broker, stale DB rows must not be evaluated
        self.assertEqual(result.get("positions_evaluated", 0), 0)
        self.assertFalse(result.get("execution_authorized", True))
        # Successful-empty metadata
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
                "current_price": 90.0,
                "market_value": 900.0,
                "cost_basis": 1000.0,
                "unrealized_pl": -100.0,
                "unrealized_plpc": -10.0,
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
                "current_price": 99.5,
                "asset_class": "stock",
                "lane_id": "DAY",
            }
        }
        result = engine._loss_containment_review_phase(
            open_rows=open_rows,
            broker_position_by_symbol=broker_positions,
            broker_fetch_succeeded=True,
            max_positions=100,
        )
        self.assertEqual(result.get("positions_evaluated"), 1)
        self.assertEqual(result["metrics"]["hard_boundary_breaches"], 0)
        decision = result["position_decisions"][0]
        # Broker position has lane_id="DAY" — enrichment preserves it when
        # recovery returns UNAVAILABLE, so evaluation proceeds at DAY thresholds.
        self.assertEqual(decision["threshold_state"], "HEALTHY")
        self.assertEqual(decision["lane"], "DAY")
        self.assertEqual(decision["lane_recovery_status"], "UNAVAILABLE")
        self.assertEqual(decision["symbol"], "AAPL")

    def test_symbol_only_db_metadata_is_not_used_for_broker_lane(self):
        """A same-symbol historical DB row cannot assign a current broker lane."""
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
                "current_price": 90.0,
                "market_value": 900.0,
                "cost_basis": 1000.0,
                "unrealized_pl": -100.0,
                "unrealized_plpc": -10.0,
                "lane_id": "DAY",
                "paper_entry_horizon_style": "day_trade",
                "position_owner": "DAY",
                "exit_policy_owner": "DAY",
                "last_update_ts": _now_iso(),
            }
        ]
        # Broker position has no lane/horizon, but broker price is healthy.
        broker_positions = {
            "AAPL": {
                "symbol": "AAPL",
                "qty": 10,
                "avg_entry_price": 100.0,
                "current_price": 99.5,
                "asset_class": "stock",
            }
        }
        result = engine._loss_containment_review_phase(
            open_rows=open_rows,
            broker_position_by_symbol=broker_positions,
            broker_fetch_succeeded=True,
            max_positions=100,
        )
        self.assertEqual(result.get("positions_evaluated"), 1)
        self.assertEqual(result["metrics"]["hard_boundary_breaches"], 0)
        decision = result["position_decisions"][0]
        # Broker position has no lane_id; recovery returns UNAVAILABLE.
        # The engine derives SWING from asset_class="stock" for threshold rails.
        # Return is -0.5%, well within SWING healthy range.
        self.assertEqual(decision["threshold_state"], "HEALTHY")
        self.assertEqual(decision["lane"], "SWING")
        self.assertEqual(decision["lane_recovery_status"], "UNAVAILABLE")
        self.assertEqual(decision["exact_blockers"], [])
        self.assertEqual(decision["symbol"], "AAPL")

    def test_failed_broker_fetch_evicts_prior_decisions(self):
        """When broker fetch fails, prior decisions must not drive stale actions."""
        PaperAutopilotEngine = self._can_import_paper_autopilot()
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        engine._save_loss_containment_state({
            "schema_version": "astra_loss_containment_state_v1",
            "decisions": {
                "AAPL": {
                    "symbol": "AAPL",
                    "threshold_state": "HARD_BOUNDARY_BREACH",
                    "canonical_recommendation": "HARD_LOSS_EXIT_REQUIRED_ADVISORY",
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
                "current_price": 90.0,
                "market_value": 900.0,
                "cost_basis": 1000.0,
                "unrealized_pl": -100.0,
                "unrealized_plpc": -10.0,
                "lane_id": "DAY",
                "last_update_ts": _now_iso(),
            }
        ]
        result = engine._loss_containment_review_phase(
            open_rows=open_rows,
            broker_fetch_succeeded=False,
            max_positions=100,
        )
        self.assertEqual(result.get("positions_evaluated"), 0)
        self.assertEqual(result.get("observation_state"), "FAILED")
        self.assertEqual(result.get("first_phase_blocker"), "BROKER_POSITION_EVIDENCE_UNAVAILABLE")
        self.assertEqual(len(result.get("position_decisions", [])), 0)
        state = engine._load_loss_containment_state()
        self.assertEqual(state.get("decisions"), {})
        # Phase metadata is preserved in the durable state file
        self.assertEqual(state.get("observation_state"), "FAILED")
        self.assertFalse(state.get("broker_fetch_succeeded"))
        self.assertIsNone(state.get("confirmed_open_position_count"))

    def test_durable_state_preserves_phase_metadata(self):
        """Phase metadata must round-trip through durable state save/load."""
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
                "current_price": 99.0,
                "asset_class": "stock",
                "lane_id": "DAY",
            }
        }
        result = engine._loss_containment_review_phase(
            broker_position_by_symbol=broker_positions,
            broker_fetch_succeeded=True,
            max_positions=100,
        )
        self.assertEqual(result.get("observation_state"), "READY")
        self.assertTrue(result.get("broker_fetch_succeeded"))
        self.assertEqual(result.get("confirmed_open_position_count"), 1)
        self.assertIsNone(result.get("first_phase_blocker"))

        # Metadata must be present in the in-memory state envelope
        state = result.get("state", {})
        self.assertEqual(state.get("observation_state"), "READY")
        self.assertTrue(state.get("broker_fetch_succeeded"))
        self.assertEqual(state.get("confirmed_open_position_count"), 1)
        self.assertIsNone(state.get("first_phase_blocker"))

        # Metadata must survive the atomic save/load cycle
        loaded = engine._load_loss_containment_state()
        self.assertEqual(loaded.get("observation_state"), "READY")
        self.assertTrue(loaded.get("broker_fetch_succeeded"))
        self.assertEqual(loaded.get("confirmed_open_position_count"), 1)
        self.assertIsNone(loaded.get("first_phase_blocker"))


class ProviderNativeTimestampTests(unittest.TestCase):
    def test_provider_native_timestamp_present_in_decision(self):
        pos = _position(current_price=98.0, last_update_ts="2025-12-18T20:00:00Z")
        d = evaluate_position_loss_containment_v1(pos)
        self.assertIn("provider_native_timestamp", d)
        self.assertEqual(d["provider_native_timestamp"], "2025-12-18T20:00:00Z")
        self.assertEqual(d["provider_native_timestamp_provenance"], "provider_native")

    def test_provider_native_timestamp_fallback_when_absent(self):
        pos = _position(current_price=98.0)
        pos.pop("last_update_ts", None)
        d = evaluate_position_loss_containment_v1(pos)
        self.assertIn("provider_native_timestamp", d)
        self.assertIsNone(d["provider_native_timestamp"])
        self.assertEqual(d["provider_native_timestamp_provenance"], "python_fallback")


if __name__ == "__main__":
    unittest.main()
