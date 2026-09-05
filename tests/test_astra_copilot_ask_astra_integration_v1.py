"""Regression coverage for the bounded Copilot and Ask Astra truth handoff."""

from __future__ import annotations

import pathlib
import unittest
from unittest.mock import patch

import server_extend
from engine.astra_build_i_decision_intelligence_v1 import resolve_question_route


ROOT = pathlib.Path(__file__).resolve().parents[1]
COPILOT_PAGE = ROOT / "astra_dashboard" / "ui" / "src" / "dashboard" / "pages" / "CopilotPage.jsx"


def _recommendation(**overrides):
    row = {
        "recommendation_id": "copilot:abc",
        "symbol": "NVDA",
        "action": "WATCH",
        "canonical_lifecycle_state": "WATCH",
        "candidate_execution_state": "CANDIDATE",
        "confidence": 91.0,
        "preferred_horizon": "day_trade",
        "paper_autopilot_eligible": False,
        "position_state": "NO_OPEN_POSITION",
        "advisory_exit_state": "INSUFFICIENT_EVIDENCE",
        "freshness": "CACHED",
        "source_freshness_state": "UNVERIFIED",
        "blockers": [],
    }
    row.update(overrides)
    return row


class CopilotAskAstraIntegrationTests(unittest.TestCase):
    def test_confidence_alone_never_labels_candidate_buy_now(self):
        action = server_extend._copilot_action_from_row({"symbol": "NVDA", "confidence": 99.0})
        self.assertEqual(action["action"], "WATCH")
        self.assertEqual(action["candidate_execution_state"], "CANDIDATE")
        self.assertFalse(action["paper_autopilot_eligible"])

    def test_existing_eligibility_can_be_presented_without_recalculating_it(self):
        action = server_extend._copilot_action_from_row({"symbol": "NVDA", "confidence": 75.0, "paper_eligible": True})
        self.assertEqual(action["action"], "BUY_NOW")
        self.assertEqual(action["candidate_execution_state"], "ELIGIBLE")
        self.assertTrue(action["paper_autopilot_eligible"])

    def test_question_routing_uses_smallest_canonical_owner(self):
        statuses = {
            "astra_copilot_suite_v1": {"recommendations": [_recommendation(blockers=["STALE_PROVIDER_NATIVE_TIMESTAMP"])]},
            "astra_trading_readiness_v1": {"status": "ok"},
            "astra_operating_health_contract_v1": {"status": "ok"},
            "unified_learning_diagnostics_v1": {"status": "ok"},
        }
        rejected = resolve_question_route("Why did Astra reject NVDA?", statuses=statuses)
        self.assertEqual(rejected["intent"], "candidate_rejection")
        self.assertIn("lane_execution_trace_ledger_v1", rejected["canonical_sources"])
        self.assertEqual(rejected["answer_state"], "ANSWERED_FROM_CANONICAL_CURRENT_DATA")

        freshness = resolve_question_route("How current is Astra's NVDA recommendation?", statuses=statuses)
        self.assertEqual(freshness["intent"], "freshness")
        self.assertEqual(freshness["answer_state"], "FRESHNESS_UNCERTAIN")

        opportunities = resolve_question_route("What stocks does Astra like right now?", statuses=statuses)
        self.assertEqual(opportunities["intent"], "copilot_recommendation")

        quiet = resolve_question_route("Why isn't Astra trading right now?", statuses=statuses)
        self.assertEqual(quiet["intent"], "candidate_rejection")

    def test_fast_response_discloses_unverified_freshness_instead_of_currentness(self):
        copilot = {"top_actions": [_recommendation()]}
        result = server_extend._ask_astra_fast_grounded_response_v1(
            "How current is Astra's NVDA recommendation?",
            selected_symbol="NVDA",
            copilot=copilot,
            cached_unified={"astra_copilot_suite_v1": copilot},
            local_status={},
            request_context={},
        )
        self.assertIn("cannot verify", result["short_answer"].lower())
        self.assertEqual(result["answer_grounding"]["answer_state"], "FRESHNESS_UNCERTAIN")
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_behavior_changed"], False)

    def test_fast_response_explains_recorded_blocker_without_generic_fallback(self):
        row = _recommendation(blockers=["STALE_PROVIDER_NATIVE_TIMESTAMP"])
        copilot = {"top_actions": [row]}
        result = server_extend._ask_astra_fast_grounded_response_v1(
            "Why did Astra reject NVDA?",
            selected_symbol="NVDA",
            copilot=copilot,
            cached_unified={"astra_copilot_suite_v1": copilot},
            local_status={},
            request_context={},
        )
        self.assertIn("STALE_PROVIDER_NATIVE_TIMESTAMP", result["short_answer"])
        self.assertEqual(result["answer_grounding"]["intent"], "candidate_rejection")

    def test_open_position_is_answered_even_without_candidate_record(self):
        position = {
            "recommendation_id": "position:gehc",
            "symbol": "GEHC",
            "lane_id": "SCALP",
            "position_state": "POSITION_OPEN",
            "canonical_lifecycle_state": "HOLD",
            "advisory_exit_state": "INSUFFICIENT_EVIDENCE",
            "source_freshness_state": "CACHED",
        }
        result = server_extend._ask_astra_fast_grounded_response_v1(
            "Is Astra still holding GEHC and is it close to selling?",
            selected_symbol="GEHC",
            copilot={"current_positions": [position], "current_opportunities": []},
            cached_unified={},
            local_status={},
            request_context={},
        )
        self.assertIn("open Paper position", result["short_answer"])
        self.assertIn("GEHC", result["short_answer"])
        self.assertIn("SCALP", result["short_answer"])
        self.assertIn("Insufficient Evidence", result["short_answer"])
        self.assertTrue(result["answer_grounding"]["canonical_source_available"])

    def test_current_position_route_prefers_current_position_over_candidate_row(self):
        statuses = {
            "astra_copilot_suite_v1": {
                "recommendations": [_recommendation(symbol="GEHC", position_state="NO_OPEN_POSITION")],
                "current_positions": [{"symbol": "GEHC", "position_state": "POSITION_OPEN", "canonical_lifecycle_state": "HOLD"}],
            },
        }
        result = resolve_question_route("Is Astra still holding GEHC?", statuses=statuses)
        self.assertTrue(result["canonical_source_available"])
        self.assertEqual(result["deterministic_facts"]["position_state"], "POSITION_OPEN")

    def test_empty_current_opportunities_do_not_substitute_historical_top_action(self):
        result = server_extend._ask_astra_fast_grounded_response_v1(
            "What are Astra's best stocks right now?",
            selected_symbol="",
            copilot={"top_actions": [_recommendation(symbol="NVDA")], "current_opportunities": [], "current_positions": []},
            cached_unified={},
            local_status={},
            request_context={},
        )
        self.assertIn("does not currently report", result["short_answer"])
        self.assertNotIn("NVDA is", result["short_answer"])

    def test_current_eligible_opportunity_wins_over_historical_top_action(self):
        current = _recommendation(
            symbol="RIOT",
            recommendation_id="copilot:riot",
            candidate_execution_state="ELIGIBLE",
            paper_autopilot_eligible=True,
            source_freshness_state="CACHED",
        )
        result = server_extend._ask_astra_fast_grounded_response_v1(
            "What are Astra's best stocks right now?",
            selected_symbol="",
            copilot={"top_actions": [_recommendation(symbol="NVDA")], "current_opportunities": [current], "current_positions": []},
            cached_unified={},
            local_status={},
            request_context={},
        )
        self.assertIn("RIOT", result["short_answer"])
        self.assertNotIn("NVDA", result["short_answer"])

    def test_freshness_without_symbol_uses_candidate_snapshot_timestamp(self):
        copilot = {
            "current_opportunities": [],
            "source_summary": {"candidate_snapshot_timestamp": "2026-09-05T12:00:00Z"},
        }
        result = server_extend._ask_astra_fast_grounded_response_v1(
            "How current is this information?",
            selected_symbol="",
            copilot=copilot,
            cached_unified={},
            local_status={},
            request_context={},
        )
        self.assertIn("2026-09-05T12:00:00Z", result["key_supporting_astra_signals"][0])
        self.assertEqual(result["answer_grounding"]["answer_state"], "FRESHNESS_UNCERTAIN")

    def test_lane_question_for_open_symbol_uses_current_position_route(self):
        statuses = {
            "astra_copilot_suite_v1": {
                "current_positions": [{"symbol": "GEHC", "lane_id": "SCALP", "position_state": "POSITION_OPEN"}],
            },
        }
        result = resolve_question_route("What lane is GEHC in?", statuses=statuses)
        self.assertEqual(result["intent"], "current_position")
        self.assertEqual(result["deterministic_facts"]["position_state"], "POSITION_OPEN")

    def test_candidate_snapshot_timestamp_is_propagated_to_copilot_freshness(self):
        rows = server_extend._candidate_rows_from_payload({
            "generated_at": "2026-09-05T12:00:00Z",
            "stocks": {"final": [{"symbol": "RIOT", "confidence": 80.0}]},
        })
        action = server_extend._copilot_action_from_row(rows[0])
        self.assertEqual(action["source_timestamp"], "2026-09-05T12:00:00Z")
        self.assertEqual(action["source_freshness_state"], "CACHED")

    def test_copilot_selection_uses_stable_identity_and_user_refresh(self):
        source = COPILOT_PAGE.read_text(encoding="utf-8")
        self.assertIn("COPILOT_CACHE_TTL_MS", source)
        self.assertIn("Refresh current state", source)
        self.assertIn("selectedId", source)
        self.assertIn("selectionNotice", source)
        self.assertIn("candidate_execution_state", source)


if __name__ == "__main__":
    unittest.main()
