"""Targeted tests for legacy quarantine, canonical ownership, and exit readiness.

These tests use temporary stores and mocks. They do not connect to Alpaca or
access live runtime data.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_legacy_quarantine_v1 import (
    bounded_legacy_quarantine_review_v1,
    build_legacy_exit_readiness_v1,
    build_position_attribution_summary_v1,
    ensure_fail_closed_canary_control_v1,
    resolve_canonical_lifecycle_decision_v1,
    resolve_canonical_position_ownership_v1,
)


class CanonicalOwnershipTests(unittest.TestCase):
    def test_active_day_position(self):
        row = {
            "position_id": "p1",
            "symbol": "AAPL",
            "qty": 10,
            "market_value": 2500.0,
            "lane_id": "DAY",
            "position_owner": "DAY",
            "exit_policy_owner": "DAY",
            "trade_horizon_style": "day_trade",
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "ACTIVE_DAY")
        self.assertTrue(ownership["active_strategy"])
        self.assertTrue(ownership["included_in_total_exposure"])
        self.assertTrue(ownership["included_in_active_strategy"])
        self.assertFalse(ownership["legacy_quarantined"])

    def test_active_swing_position(self):
        row = {
            "position_id": "p2",
            "symbol": "TSLA",
            "qty": 5,
            "market_value": 1200.0,
            "trade_horizon_style": "swing_trade",
            "position_owner": "SWING",
            "exit_policy_owner": "SWING",
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "ACTIVE_SWING")
        self.assertTrue(ownership["active_strategy"])

    def test_active_crypto_position(self):
        row = {
            "position_id": "p3",
            "symbol": "BTC/USD",
            "qty": 0.5,
            "market_value": 30000.0,
            "asset_class": "crypto",
            "position_owner": "CRYPTO",
            "exit_policy_owner": "CRYPTO",
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "ACTIVE_CRYPTO")
        self.assertTrue(ownership["active_strategy"])

    def test_legacy_quarantined_by_cohort(self):
        row = {
            "position_id": "p4",
            "symbol": "FIX",
            "qty": 100,
            "market_value": 5000.0,
            "lane_id": "SWING",
            "position_owner": "SWING",
            "exit_policy_owner": "SWING",
        }
        cohort = {"cohort": "LEGACY_PRE_CONTRACT_POSITION", "position_id": "p4"}
        ownership = resolve_canonical_position_ownership_v1(row, cohort=cohort)
        self.assertEqual(ownership["ownership"], "LEGACY_QUARANTINED")
        self.assertFalse(ownership["active_strategy"])
        self.assertTrue(ownership["legacy_quarantined"])
        self.assertTrue(ownership["included_in_total_exposure"])
        self.assertTrue(ownership["included_in_legacy_quarantine"])
        self.assertFalse(ownership["included_in_active_strategy"])

    def test_legacy_quarantined_by_overlay(self):
        row = {
            "position_id": "p5",
            "symbol": "OLD",
            "qty": 50,
            "market_value": 2500.0,
            "lane_id": "DAY",
            "position_owner": "DAY",
            "exit_policy_owner": "DAY",
            "legacy_forward_only_management": True,
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "LEGACY_QUARANTINED")

    def test_legacy_quarantined_by_legacy_owner(self):
        row = {
            "position_id": "p6",
            "symbol": "LEG",
            "qty": 20,
            "market_value": 1000.0,
            "lane_id": "SWING",
            "position_owner": "LEGACY_SWING_CANARY",
            "exit_policy_owner": "LEGACY_SWING_CONTROLLED_PAPER_CANARY_V1",
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "LEGACY_QUARANTINED")

    def test_dust_position(self):
        row = {
            "position_id": "p7",
            "symbol": "DUST",
            "qty": 0,
            "market_value": 0.0,
            "lane_id": "DAY",
            "position_owner": "DAY",
            "exit_policy_owner": "DAY",
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "DUST_REVIEW")
        self.assertTrue(ownership["dust"])
        self.assertTrue(ownership["included_in_total_exposure"])
        self.assertFalse(ownership["included_in_active_strategy"])

    def test_dust_by_value(self):
        row = {
            "position_id": "p8",
            "symbol": "TINY",
            "qty": 1,
            "market_value": 0.005,
            "lane_id": "DAY",
            "position_owner": "DAY",
            "exit_policy_owner": "DAY",
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "DUST_REVIEW")

    def test_broker_residue_position(self):
        row = {
            "qty": 10,
            "market_value": 500.0,
            "lane_id": "DAY",
            "position_owner": "DAY",
            "exit_policy_owner": "DAY",
        }
        cohort = {"cohort": "BROKER_RESIDUE_POSITION", "position_id": ""}
        ownership = resolve_canonical_position_ownership_v1(row, cohort=cohort)
        self.assertEqual(ownership["ownership"], "BROKER_RESIDUE_REVIEW")
        self.assertTrue(ownership["broker_residue"])

    def test_unresolved_empty_lane(self):
        row = {
            "position_id": "p9",
            "symbol": "WEIRD",
            "qty": 10,
            "market_value": 1000.0,
            "position_owner": "SOMETHING",
            "exit_policy_owner": "SOMETHING",
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "UNRESOLVED_FAIL_CLOSED")
        self.assertTrue(ownership["unresolved"])
        self.assertTrue(ownership["included_in_total_exposure"])
        self.assertFalse(ownership["included_in_active_strategy"])

    def test_unresolved_empty_owner(self):
        row = {
            "position_id": "p10",
            "symbol": "NOOWNER",
            "qty": 10,
            "market_value": 1000.0,
            "lane_id": "DAY",
            "position_owner": "",
            "exit_policy_owner": "",
        }
        ownership = resolve_canonical_position_ownership_v1(row)
        self.assertEqual(ownership["ownership"], "UNRESOLVED_FAIL_CLOSED")


class CanonicalDecisionTests(unittest.TestCase):
    def test_unified_classification_preserved(self):
        row = {"position_id": "p1", "symbol": "AAPL", "qty": 10, "market_value": 1000.0}
        unified = {"classification": "THESIS_BROKEN", "forecast_confidence": 0.85}
        decision = resolve_canonical_lifecycle_decision_v1(row, unified_decision=unified)
        self.assertEqual(decision["classification"], "THESIS_BROKEN")
        self.assertEqual(decision["decision_owner"], "astra_canonical_lifecycle_decision_v1")
        self.assertFalse(decision["execution_authorized"])
        self.assertFalse(decision["paper_action_ready"])
        self.assertTrue(decision["advisory_only"])

    def test_portfolio_disagreement_tracked(self):
        row = {"position_id": "p2", "symbol": "TSLA", "qty": 5, "market_value": 1000.0}
        unified = {"classification": "HOLD_AS_PLANNED", "forecast_confidence": 0.7}
        portfolio = {"primary_state": "EXIT_REVIEW", "confidence_score": 0.8}
        decision = resolve_canonical_lifecycle_decision_v1(row, unified_decision=unified, portfolio_review=portfolio)
        self.assertEqual(decision["classification"], "EXIT_REVIEW")
        self.assertIn("unified_disagreement:HOLD_AS_PLANNED", decision["evidence_conflicts"])

    def test_legacy_quarantine_prefers_unified(self):
        row = {"position_id": "p3", "symbol": "LEG", "qty": 5, "market_value": 1000.0, "legacy_forward_only_management": True}
        unified = {"classification": "HOLD_WITH_WATCH", "forecast_confidence": 0.6}
        portfolio = {"primary_state": "EXIT_REVIEW", "confidence_score": 0.9}
        decision = resolve_canonical_lifecycle_decision_v1(row, unified_decision=unified, portfolio_review=portfolio)
        self.assertEqual(decision["classification"], "HOLD_WITH_WATCH")
        self.assertIn("portfolio_disagreement:EXIT_REVIEW", decision["evidence_conflicts"])

    def test_insufficient_evidence_fail_closed(self):
        row = {"position_id": "p4", "symbol": "MISS", "qty": 5, "market_value": 1000.0}
        decision = resolve_canonical_lifecycle_decision_v1(row)
        self.assertEqual(decision["classification"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(decision["execution_authorized"])
        self.assertEqual(decision["execution_readiness"], "NOT_READY")

    def test_disposition_mapping(self):
        row = {"position_id": "p5", "symbol": "AAPL", "qty": 10, "market_value": 1000.0}
        unified = {"classification": "THESIS_BROKEN"}
        decision = resolve_canonical_lifecycle_decision_v1(row, unified_decision=unified)
        readiness = build_legacy_exit_readiness_v1(decision, position=row)
        self.assertEqual(readiness["proposed_disposition"], "EXIT_NOW_REVIEW")
        self.assertFalse(readiness["execution_authorized"])
        self.assertFalse(readiness["execution_ready"])
        self.assertIn("LEGACY_CANARY_EXECUTION_DISABLED_BY_POLICY", readiness["execution_blockers"])


class AttributionSummaryTests(unittest.TestCase):
    def test_legacy_remains_in_total_exposure(self):
        positions = [
            {"position_id": "a1", "symbol": "AAPL", "qty": 10, "market_value": 2500.0, "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY", "unrealized_pl": 50.0},
            {"position_id": "l1", "symbol": "LEG", "qty": 100, "market_value": 5000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_forward_only_management": True, "unrealized_pl": -100.0},
        ]
        summary = build_position_attribution_summary_v1(positions)
        self.assertEqual(summary["total_open_positions"], 2)
        self.assertEqual(summary["active_strategy_positions"], 1)
        self.assertEqual(summary["legacy_quarantined_positions"], 1)
        self.assertEqual(summary["total_committed_capital"], 7500.0)
        self.assertEqual(summary["active_strategy_committed_capital"], 2500.0)
        self.assertEqual(summary["legacy_committed_capital"], 5000.0)
        self.assertEqual(summary["total_unrealized_pnl"], -50.0)
        self.assertEqual(summary["active_strategy_unrealized_pnl"], 50.0)
        self.assertEqual(summary["legacy_unrealized_pnl"], -100.0)

    def test_dust_and_broker_residue_separate(self):
        positions = [
            {"position_id": "d1", "symbol": "DUST", "qty": 0, "market_value": 0.0, "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY"},
            {"symbol": "RES", "qty": 1, "market_value": 100.0, "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY", "cohort": "BROKER_RESIDUE_POSITION"},
        ]
        summary = build_position_attribution_summary_v1(positions)
        self.assertEqual(summary["dust_review_positions"], 1)
        self.assertEqual(summary["broker_residue_review_positions"], 1)
        self.assertEqual(summary["active_strategy_positions"], 0)

    def test_active_strategy_count_distinct_from_total(self):
        positions = [
            {"position_id": "a1", "symbol": "AAPL", "qty": 10, "market_value": 1000.0, "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY"},
            {"position_id": "l1", "symbol": "LEG", "qty": 10, "market_value": 1000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_resolution_approved": True},
        ]
        summary = build_position_attribution_summary_v1(positions)
        self.assertEqual(summary["total_open_positions"], 2)
        self.assertEqual(summary["active_strategy_positions"], 1)
        self.assertIn("AAPL", summary["active_strategy_symbols"])
        self.assertIn("LEG", summary["legacy_quarantined_symbols"])


class BoundedReviewTests(unittest.TestCase):
    def test_review_bounded_to_max(self):
        positions = [
            {"position_id": f"l{i}", "symbol": f"LEG{i}", "qty": 10, "market_value": 1000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_forward_only_management": True}
            for i in range(5)
        ]
        result = bounded_legacy_quarantine_review_v1(positions, max_reviews=1)
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(result["max_reviews"], 1)
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["canary_enabled"])
        self.assertTrue(result["kill_switch_active"])

    def test_review_respects_max_two(self):
        positions = [
            {"position_id": f"l{i}", "symbol": f"LEG{i}", "qty": 10, "market_value": 1000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_forward_only_management": True}
            for i in range(5)
        ]
        result = bounded_legacy_quarantine_review_v1(positions, max_reviews=2)
        self.assertEqual(result["reviewed_count"], 2)

    def test_review_idempotent(self):
        positions = [
            {"position_id": "l1", "symbol": "LEG1", "qty": 10, "market_value": 1000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_forward_only_management": True}
        ]
        prior_reviews = {
            "l1": {
                "activation_timestamp": "2025-01-01T00:00:00Z",
                "canonical_decision": {"classification": "HOLD_WITH_WATCH"},
            }
        }
        result1 = bounded_legacy_quarantine_review_v1(positions, prior_reviews=prior_reviews, max_reviews=1)
        result2 = bounded_legacy_quarantine_review_v1(positions, prior_reviews=prior_reviews, max_reviews=1)
        self.assertEqual(result1["reviewed"][0]["activation_timestamp"], "2025-01-01T00:00:00Z")
        self.assertEqual(result2["reviewed"][0]["activation_timestamp"], "2025-01-01T00:00:00Z")

    def test_non_legacy_positions_skipped(self):
        positions = [
            {"position_id": "a1", "symbol": "AAPL", "qty": 10, "market_value": 1000.0, "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY"},
            {"position_id": "l1", "symbol": "LEG1", "qty": 10, "market_value": 1000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_forward_only_management": True},
        ]
        result = bounded_legacy_quarantine_review_v1(positions, max_reviews=5)
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(result["reviewed"][0]["symbol"], "LEG1")

    def test_no_duplicate_exit_action(self):
        positions = [
            {"position_id": "l1", "symbol": "LEG1", "qty": 10, "market_value": 1000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_forward_only_management": True}
        ]
        pending_map = {"some-id": {"position_id": "l1", "symbol": "LEG1"}}
        result = bounded_legacy_quarantine_review_v1(positions, pending_map=pending_map, max_reviews=1)
        readiness = result["reviewed"][0]["exit_readiness"]
        self.assertTrue(readiness["pending_sell"])
        self.assertTrue(readiness["duplicate_action"])
        self.assertIn("DUPLICATE_PENDING_SELL", readiness["execution_blockers"])


class ExitReadinessTests(unittest.TestCase):
    def test_execution_always_unauthorized(self):
        decision = {"classification": "THESIS_BROKEN", "position_id": "p1", "symbol": "AAPL"}
        readiness = build_legacy_exit_readiness_v1(decision)
        self.assertFalse(readiness["execution_authorized"])
        self.assertFalse(readiness["execution_ready"])
        self.assertEqual(readiness["proposed_disposition"], "EXIT_NOW_REVIEW")

    def test_quantity_reconciliation_status(self):
        decision = {"classification": "EXIT_REVIEW", "position_id": "p1", "symbol": "AAPL"}
        row = {"position_id": "p1", "symbol": "AAPL", "qty": 10, "market_value": 1000.0}
        broker = {"qty": 10}
        readiness = build_legacy_exit_readiness_v1(decision, position=row, broker_position=broker)
        self.assertEqual(readiness["broker_quantity_evidence_status"], "RECONCILED")
        self.assertEqual(readiness["reconciliation_status"], "RECONCILED")

    def test_quantity_mismatch_detected(self):
        decision = {"classification": "EXIT_REVIEW", "position_id": "p1", "symbol": "AAPL"}
        row = {"position_id": "p1", "symbol": "AAPL", "qty": 10, "market_value": 1000.0}
        broker = {"qty": 8}
        readiness = build_legacy_exit_readiness_v1(decision, position=row, broker_position=broker)
        self.assertEqual(readiness["broker_quantity_evidence_status"], "MISMATCH")
        self.assertIn("QUANTITY_NOT_RECONCILED", readiness["execution_blockers"])

    def test_asset_not_tradable_blocked(self):
        decision = {"classification": "THESIS_BROKEN", "position_id": "p1", "symbol": "AAPL"}
        readiness = build_legacy_exit_readiness_v1(decision, asset_metadata={"tradable": False})
        self.assertFalse(readiness["asset_tradable"])
        self.assertIn("ASSET_NOT_TRADABLE", readiness["execution_blockers"])

    def test_market_session_not_tradable_blocked(self):
        decision = {"classification": "THESIS_BROKEN", "position_id": "p1", "symbol": "AAPL"}
        readiness = build_legacy_exit_readiness_v1(decision, market_session={"market_is_tradable": False})
        self.assertFalse(readiness["market_session_tradable"])
        self.assertIn("MARKET_SESSION_NOT_TRADABLE", readiness["execution_blockers"])


class CanaryControlTests(unittest.TestCase):
    def test_fail_closed_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "missing_canary.json")
            control = ensure_fail_closed_canary_control_v1(path)
            self.assertFalse(control["enabled"])
            self.assertTrue(control["kill_switch"])
            self.assertFalse(control["execution_authorized"])
            self.assertEqual(control["activation_state"], "DISABLED_FAIL_CLOSED")
            self.assertEqual(control["readiness_state"], "NOT_READY")

    def test_existing_control_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "canary.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"enabled": false, "kill_switch": true, "readiness_state": "NOT_READY"}')
            control = ensure_fail_closed_canary_control_v1(path)
            self.assertFalse(control["enabled"])
            self.assertTrue(control["kill_switch"])

    def test_existing_malicious_enabled_preserved_but_not_execution_authorized(self):
        # The function returns the file state but execution_authorized is always False here.
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "canary.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"enabled": true, "kill_switch": false}')
            control = ensure_fail_closed_canary_control_v1(path)
            # The helper reports the file state; execution_authorized remains False.
            self.assertFalse(control["execution_authorized"])


class PaperAutopilotIntegrationTests(unittest.TestCase):
    """Lightweight integration with a temporary PaperAutopilotEngine store."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="astra_quarantine_test_")
        self.db_path = os.path.join(self.tmpdir, "ai_trading_memory.db")
        self.state_path = os.path.join(self.tmpdir, "paper_autopilot_state.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status_reports_quarantine_summary(self):
        from engine.paper_autopilot import PaperAutopilotEngine
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        # Seed a legacy open position directly.
        engine._ensure_schema()
        with engine._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_positions (position_id, symbol, asset_type, status, quantity, entry_price, entry_timestamp, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("leg1", "LEG", "stock", "OPEN", 10, 100.0, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
            conn.commit()
        # Run the bounded quarantine review phase directly with parsed legacy rows.
        open_rows = [
            {
                "position_id": "leg1",
                "symbol": "LEG",
                "asset_type": "stock",
                "status": "OPEN",
                "quantity": 10,
                "entry_price": 100.0,
                "market_value": 1000.0,
                "lane_id": "SWING",
                "position_owner": "SWING",
                "exit_policy_owner": "SWING",
                "legacy_forward_only_management": True,
            }
        ]
        result = engine._bounded_legacy_quarantine_review_phase(
            open_rows=open_rows,
            broker_position_by_symbol={"LEG": {"qty": 10, "tradable": True}},
            max_reviews=1,
        )
        self.assertEqual(result["reviewed_count"], 1)
        self.assertEqual(result["reviewed"][0]["symbol"], "LEG")
        self.assertFalse(result["execution_authorized"])
        # Status should surface attribution summary without creating evidence.
        status = engine.status()
        self.assertIn("legacy_quarantine_review_v1", status)
        self.assertIn("legacy_quarantine_attribution_summary_v1", status)
        attribution = status["legacy_quarantine_attribution_summary_v1"]
        self.assertEqual(attribution["total_open_positions"], 1)
        self.assertEqual(attribution["legacy_quarantined_positions"], 1)
        self.assertEqual(attribution["active_strategy_positions"], 0)

    def test_status_does_not_create_review_evidence(self):
        from engine.paper_autopilot import PaperAutopilotEngine
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        # Status should not perform a review.
        status = engine.status()
        self.assertEqual(status["legacy_quarantine_review_v1"].get("reviewed_count", 0), 0)
        self.assertEqual(status["legacy_quarantine_attribution_summary_v1"].get("total_open_positions", 0), 0)
        # Explicit review is required to create evidence.
        engine._bounded_legacy_quarantine_review_phase(max_reviews=1)
        status = engine.status()
        self.assertEqual(status["legacy_quarantine_review_v1"].get("reviewed_count", 0), 0)

    def test_disabled_run_cycle_calls_quarantine_review(self):
        from engine.paper_autopilot import PaperAutopilotEngine
        engine = PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )
        engine._ensure_schema()
        with engine._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_positions (position_id, symbol, asset_type, status, quantity, entry_price, entry_timestamp, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("leg1", "LEG", "stock", "OPEN", 10, 100.0, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
            conn.commit()
        # Mock broker snapshot to avoid any provider calls.
        def mock_broker_snapshot():
            return {
                "broker_open_symbols": set(),
                "broker_position_by_symbol": {},
                "broker_reconciliation_active": False,
                "broker_positions_fetch_ok": False,
            }
        engine._broker_open_symbols_snapshot = mock_broker_snapshot
        result = engine.run_cycle()
        self.assertEqual(result["cycle_reason"], "disabled")
        self.assertIn("legacy_quarantine_review_v1", result)
        self.assertFalse(result["legacy_quarantine_review_v1"].get("execution_authorized", True))


class SafetyTests(unittest.TestCase):
    """Execution-safety and side-effect-free guarantees."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="astra_quarantine_safety_")
        self.db_path = os.path.join(self.tmpdir, "ai_trading_memory.db")
        self.state_path = os.path.join(self.tmpdir, "paper_autopilot_state.json")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def _make_engine(self):
        from engine.paper_autopilot import PaperAutopilotEngine
        return PaperAutopilotEngine(
            db_path=self.db_path,
            state_path=self.state_path,
            enabled=False,
        )

    def _seed_legacy_open_position(self, engine):
        engine._ensure_schema()
        with engine._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_positions (position_id, symbol, asset_type, status, quantity, entry_price, entry_timestamp, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("leg1", "LEG", "stock", "OPEN", 10, 100.0, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
            conn.commit()

    def test_bounded_review_never_submits_authorized_lane_exit(self):
        engine = self._make_engine()
        self._seed_legacy_open_position(engine)
        original = engine._submit_authorized_lane_exit
        called = []

        def fake_submit(*args, **kwargs):
            called.append((args, kwargs))
            return {"ok": False}

        engine._submit_authorized_lane_exit = fake_submit
        try:
            engine._bounded_legacy_quarantine_review_phase(max_reviews=1)
        finally:
            engine._submit_authorized_lane_exit = original
        self.assertEqual(called, [])

    def test_bounded_review_never_calls_broker_submission_methods(self):
        engine = self._make_engine()
        self._seed_legacy_open_position(engine)

        class MockBroker:
            def __init__(self):
                self.submit_paper_order_calls = []

            def submit_paper_order(self, order):
                self.submit_paper_order_calls.append(order)
                return {"ok": False}

        mock_broker = MockBroker()
        engine.alpaca_paper_broker = mock_broker
        original_writer = engine.legacy_swing_canary_writer_pre_submit
        writer_calls = []

        def fake_writer(*args, **kwargs):
            writer_calls.append((args, kwargs))
            return {"ok": False}

        engine.legacy_swing_canary_writer_pre_submit = fake_writer
        try:
            engine._bounded_legacy_quarantine_review_phase(max_reviews=1)
        finally:
            engine.legacy_swing_canary_writer_pre_submit = original_writer
        self.assertEqual(mock_broker.submit_paper_order_calls, [])
        self.assertEqual(writer_calls, [])

    def test_canary_remains_disabled_after_review_cycle(self):
        engine = self._make_engine()
        self._seed_legacy_open_position(engine)
        result = engine._bounded_legacy_quarantine_review_phase(max_reviews=1)
        self.assertFalse(result.get("canary_enabled", True))
        self.assertTrue(result.get("kill_switch_active", False))
        self.assertFalse(result.get("execution_authorized", True))
        status = engine.status()
        control = status.get("legacy_canary_control_v1", {})
        self.assertFalse(control.get("enabled", True))
        self.assertTrue(control.get("kill_switch", False))
        self.assertFalse(control.get("execution_authorized", True))

    def test_canary_remains_disabled_after_repeated_reviews(self):
        engine = self._make_engine()
        self._seed_legacy_open_position(engine)
        for _ in range(3):
            result = engine._bounded_legacy_quarantine_review_phase(max_reviews=1)
            self.assertFalse(result.get("canary_enabled", True))
            self.assertFalse(result.get("execution_authorized", True))
        status = engine.status()
        control = status.get("legacy_canary_control_v1", {})
        self.assertFalse(control.get("enabled", True))
        self.assertFalse(control.get("execution_authorized", True))

    def test_canonical_decision_always_advisory_and_unauthorized(self):
        row = {"position_id": "p1", "symbol": "LEG", "qty": 10, "market_value": 1000.0, "legacy_forward_only_management": True}
        decision = resolve_canonical_lifecycle_decision_v1(row)
        self.assertFalse(decision["execution_authorized"])
        self.assertFalse(decision["paper_action_ready"])
        self.assertTrue(decision["advisory_only"])

    def test_reviewed_decision_always_advisory_and_unauthorized(self):
        positions = [
            {"position_id": "l1", "symbol": "LEG1", "qty": 10, "market_value": 1000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_forward_only_management": True}
        ]
        result = bounded_legacy_quarantine_review_v1(positions, max_reviews=1)
        for item in result["reviewed"]:
            decision = item["canonical_decision"]
            self.assertFalse(decision["execution_authorized"])
            self.assertFalse(decision["paper_action_ready"])
            self.assertTrue(decision["advisory_only"])
            readiness = item["exit_readiness"]
            self.assertFalse(readiness["execution_authorized"])
            self.assertFalse(readiness["execution_ready"])

    def test_activation_timestamp_not_refreshed_by_repeated_reviews(self):
        engine = self._make_engine()
        self._seed_legacy_open_position(engine)
        open_rows = [
            {
                "position_id": "leg1",
                "symbol": "LEG",
                "asset_type": "stock",
                "status": "OPEN",
                "quantity": 10,
                "entry_price": 100.0,
                "market_value": 1000.0,
                "lane_id": "SWING",
                "position_owner": "SWING",
                "exit_policy_owner": "SWING",
                "legacy_forward_only_management": True,
                "legacy_activation_timestamp": "2024-06-01T12:00:00Z",
            }
        ]
        result1 = engine._bounded_legacy_quarantine_review_phase(open_rows=open_rows, max_reviews=1)
        ts1 = result1["reviewed"][0]["activation_timestamp"]
        self.assertEqual(ts1, "2024-06-01T12:00:00Z")
        result2 = engine._bounded_legacy_quarantine_review_phase(open_rows=open_rows, max_reviews=1)
        ts2 = result2["reviewed"][0]["activation_timestamp"]
        self.assertEqual(ts2, "2024-06-01T12:00:00Z")

    def test_status_is_side_effect_free_and_fail_closed_default(self):
        import os as _os
        engine = self._make_engine()
        original_cwd = _os.getcwd()
        try:
            _os.chdir(self.tmpdir)
            control_path = _os.path.join("state", "legacy_swing_canary_control_v1.json")
            # Ensure the file does not exist before status.
            if _os.path.exists(control_path):
                _os.remove(control_path)
            before = set(_os.listdir(self.tmpdir))
            status = engine.status()
            after = set(_os.listdir(self.tmpdir))
            self.assertEqual(before, after)
            self.assertFalse(_os.path.exists(control_path))
            control = status.get("legacy_canary_control_v1", {})
            self.assertFalse(control.get("enabled", True))
            self.assertTrue(control.get("kill_switch", False))
            self.assertFalse(control.get("execution_authorized", True))
            self.assertEqual(control.get("readiness_state"), "NOT_READY")
            self.assertEqual(control.get("source"), "in_memory_fail_closed_default")
            # Runtime state must not be mutated by status.
            self.assertIsNone(engine._runtime_state.get("legacy_canary_control_v1"))
        finally:
            _os.chdir(original_cwd)

    def test_day_and_crypto_processing_unchanged(self):
        positions = [
            {"position_id": "d1", "symbol": "AAPL", "qty": 10, "market_value": 2500.0, "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY"},
            {"position_id": "c1", "symbol": "BTC/USD", "qty": 0.5, "market_value": 30000.0, "asset_class": "crypto", "position_owner": "CRYPTO", "exit_policy_owner": "CRYPTO"},
        ]
        summary = build_position_attribution_summary_v1(positions)
        self.assertEqual(summary["total_open_positions"], 2)
        self.assertEqual(summary["active_strategy_positions"], 2)
        self.assertEqual(summary["legacy_quarantined_positions"], 0)
        for row in positions:
            ownership = resolve_canonical_position_ownership_v1(row)
            self.assertIn(ownership["ownership"], {"ACTIVE_DAY", "ACTIVE_CRYPTO"})
            self.assertTrue(ownership["active_strategy"])
            self.assertTrue(ownership["included_in_active_strategy"])
            self.assertFalse(ownership["legacy_quarantined"])

    def test_legacy_positions_included_in_totals_but_separated_from_active_attribution(self):
        positions = [
            {"position_id": "a1", "symbol": "AAPL", "qty": 10, "market_value": 2500.0, "lane_id": "DAY", "position_owner": "DAY", "exit_policy_owner": "DAY", "unrealized_pl": 50.0},
            {"position_id": "l1", "symbol": "LEG", "qty": 100, "market_value": 5000.0, "lane_id": "SWING", "position_owner": "SWING", "exit_policy_owner": "SWING", "legacy_forward_only_management": True, "unrealized_pl": -100.0},
        ]
        summary = build_position_attribution_summary_v1(positions)
        self.assertEqual(summary["total_open_positions"], 2)
        self.assertEqual(summary["active_strategy_positions"], 1)
        self.assertEqual(summary["legacy_quarantined_positions"], 1)
        self.assertEqual(summary["total_committed_capital"], 7500.0)
        self.assertEqual(summary["active_strategy_committed_capital"], 2500.0)
        self.assertEqual(summary["legacy_committed_capital"], 5000.0)
        self.assertEqual(summary["total_unrealized_pnl"], -50.0)
        self.assertEqual(summary["active_strategy_unrealized_pnl"], 50.0)
        self.assertEqual(summary["legacy_unrealized_pnl"], -100.0)


if __name__ == "__main__":
    unittest.main()
