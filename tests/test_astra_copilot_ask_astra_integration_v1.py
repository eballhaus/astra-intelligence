"""Regression coverage for the bounded Copilot and Ask Astra truth handoff."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import server_extend
from engine.astra_build_i_decision_intelligence_v1 import resolve_question_route


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


if __name__ == "__main__":
    unittest.main()
