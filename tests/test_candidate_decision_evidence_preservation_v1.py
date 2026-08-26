from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine.astra_daily_intelligence_summary_v1 import build_astra_daily_intelligence_summary_v1
from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1
from engine.paper_autopilot import PaperAutopilotEngine


def candidate(**extra):
    row = {
        "symbol": "BTC/USD",
        "canonical_symbol": "BTC/USD",
        "asset_class": "crypto",
        "asset_type": "crypto",
        "lane_id": "CRYPTO",
        "candidate_id": "cand-btc-1",
        "recommendation_id": "rec-btc-1",
        "selection_id": "sel-btc-1",
        "candidate_generated_at": "2026-08-21T13:00:00Z",
        "generated_at": "2026-08-21T13:00:00Z",
        "price": 100.0,
        "eligible": False,
        "selected": False,
        "order_ready": False,
        "decision_reason": "PRETRADE_DECISION_CONTRACT_MISSING_FIELDS",
        "candidate_decision_evidence_v1": {
            "candidate_rank": 2,
            "candidate_score": 88.0,
            "qualification_score": 71.0,
            "forecast_state": "INSUFFICIENT_FORECAST_EVIDENCE",
            "forecast_evidence_status": "INCOMPLETE",
            "commitment_state": "qualified_buy",
            "commitment_score": 59.0,
            "momentum_state": "POSITIVE",
            "regime": "RISK_ON",
            "entry_quality": 70.0,
            "expected_return": None,
            "expected_hold": "day_trade",
            "risk_contract_status": "CONTRACT_INCOMPLETE",
            "freshness_status": "FRESH",
            "quote_timestamp": "2026-08-21T13:00:00Z",
            "bar_timestamp": "2026-08-21T12:59:00Z",
            "crypto_gate_evidence": {"forecast_missing_inputs": ["trend_not_positive"]},
            "source_ids": {"source_snapshot_id": "crypto-snapshot-1"},
            # This must never become a later real-price outcome.
            "hypothetical_return": 9.0,
        },
        **extra,
    }
    return row


class CandidateDecisionEvidencePreservationV1Tests(unittest.TestCase):
    def _rows(self, path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def test_blocked_snapshot_is_immutable_and_preserves_exact_first_blocker(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = LaneExecutionTraceLedgerV1(directory)
            source = candidate()
            result = ledger.record([source], cycle_id="cycle-1")
            rows = self._rows(Path(directory) / "candidate_decision_ledger_v1.jsonl")

            self.assertEqual(result["candidate_decision_evidence_v1"]["snapshots_written"], 1)
            self.assertEqual(rows[0]["decision"], "BLOCKED")
            self.assertEqual(rows[0]["first_causal_blocker"], "PRETRADE_DECISION_CONTRACT_MISSING_FIELDS")
            self.assertEqual(rows[0]["candidate_decision_snapshot_v1"]["candidate_score"], 88.0)
            self.assertEqual(rows[0]["candidate_decision_snapshot_v1"]["crypto_gate_evidence"]["forecast_missing_inputs"], ["trend_not_positive"])
            self.assertNotIn("hypothetical_return", rows[0]["candidate_decision_snapshot_v1"])
            self.assertEqual(rows[0]["later_outcome_state"], "NOT_ATTACHED")

            source["candidate_decision_evidence_v1"]["candidate_score"] = 1.0
            again = ledger.record([source], cycle_id="cycle-2")
            self.assertEqual(again["candidate_decision_evidence_v1"]["snapshots_written"], 0)
            self.assertEqual(again["candidate_decision_evidence_v1"]["snapshots_deduped"], 1)
            self.assertEqual(self._rows(Path(directory) / "candidate_decision_ledger_v1.jsonl")[0]["candidate_score"], 88.0)

    def test_lesson_retrieval_is_preserved_but_not_promoted_to_application(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = LaneExecutionTraceLedgerV1(directory)
            source = candidate()
            source["candidate_decision_evidence_v1"]["lesson_retrieval_v1"] = {
                "lesson_application_state": "LESSON_RETRIEVED",
                "lesson_ids": ["lesson-day-1"],
                "decision_owner": "PaperAutopilot._candidate_trace_row",
                "consumed": False,
            }
            ledger.record([source], cycle_id="cycle-1")
            row = self._rows(Path(directory) / "candidate_decision_ledger_v1.jsonl")[0]

            self.assertEqual(row["canonical_lesson_ids"], ["lesson-day-1"])
            self.assertEqual(row["lesson_retrieval_v1"]["lesson_application_state"], "LESSON_RETRIEVED")
            self.assertEqual(row["lesson_application_evidence_v1"], {})

    def test_candidate_retrieval_is_bounded_lane_and_horizon_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            lessons_path = Path(directory) / "canonical_lifecycle_lessons_v1.jsonl"
            lessons_path.write_text(
                "\n".join([
                    json.dumps({"lesson_id": "day-lesson", "lane_id": "DAY", "horizon_style": "day_trade", "broker_truth_linkage_status": "PROVEN_STRICT_BROKER_TRUTH"}),
                    json.dumps({"lesson_id": "crypto-lesson", "lane_id": "CRYPTO", "horizon_style": "crypto", "broker_truth_linkage_status": "PROVEN_STRICT_BROKER_TRUTH"}),
                ]) + "\n"
            )
            engine = PaperAutopilotEngine(
                db_path=str(Path(directory) / "paper_autopilot.db"),
                state_path=str(Path(directory) / "paper_autopilot_state.json"),
                enabled=False,
            )
            retrieval = engine._lesson_retrieval_for_candidate_v1({
                "candidate_id": "candidate-day-1",
                "lane_id": "DAY",
                "paper_entry_horizon_style": "day_trade",
            })

            self.assertEqual(retrieval["lesson_ids"], ["day-lesson"])
            self.assertEqual(retrieval["lesson_application_state"], "LESSON_RETRIEVED")
            self.assertFalse(retrieval["consumed"])

    def test_accepted_candidate_has_exact_lifecycle_link_without_broker_action(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = LaneExecutionTraceLedgerV1(directory)
            result = ledger.record([candidate(
                candidate_id="cand-gehc-1", symbol="GEHC", lane_id="SCALP", asset_class="equity", asset_type="stock",
                decision_reason="", eligible=True, selected=True, order_ready=True,
                lifecycle_id="life-gehc-1", position_id="position-gehc-1", broker_order_id="order-gehc-1",
            )], cycle_id="cycle-1")
            row = self._rows(Path(directory) / "candidate_decision_ledger_v1.jsonl")[0]

            self.assertEqual(row["decision"], "ACCEPTED")
            self.assertEqual(row["trade_linkage_status"], "EXACTLY_LINKED")
            self.assertEqual(row["lifecycle_id"], "life-gehc-1")
            self.assertEqual(result["candidate_decision_evidence_v1"]["provider_calls"], 0)
            self.assertEqual(result["candidate_decision_evidence_v1"]["broker_calls"], 0)
            self.assertEqual(result["candidate_decision_evidence_v1"]["llm_calls"], 0)

    def test_lane_identity_and_safe_states_remain_separated(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = LaneExecutionTraceLedgerV1(directory)
            result = ledger.record([
                candidate(lane_id="SCALP", symbol="GEHC", asset_class="equity", asset_type="stock", decision_reason="duplicate_active_position"),
                candidate(lane_id="SWING", symbol="XYZ", asset_class="equity", asset_type="stock", decision_reason="", eligible=True),
            ], cycle_id="cycle-1")
            rows = self._rows(Path(directory) / "candidate_decision_ledger_v1.jsonl")

            self.assertEqual({row["lane_id"] for row in rows}, {"SCALP", "SWING"})
            self.assertEqual(rows[0]["decision"], "BLOCKED")
            self.assertEqual(rows[1]["decision"], "DEFERRED")
            self.assertEqual(result["candidate_decision_evidence_v1"]["by_lane"]["SCALP"], 1)
            self.assertEqual(result["candidate_decision_evidence_v1"]["by_lane"]["SWING"], 1)

    def test_partial_fresh_crypto_observation_is_deferred_not_stale_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = LaneExecutionTraceLedgerV1(directory)
            source = candidate(
                candidate_id="cand-aave-1",
                symbol="AAVE/USD",
                candidate_generated_at="2026-08-21T21:18:00Z",
                decision_reason="timestamp_freshness",
                eligible=True,
                selected=False,
                order_ready=False,
                partial_cycle_observation_only=True,
                crypto_final_quote_refresh_attempted=True,
                crypto_final_quote_refresh_result="FRESH",
                crypto_final_refresh_quote_age_seconds=4.6,
            )
            result = ledger.record([source], cycle_id="partial:cycle-1")
            trace = self._rows(Path(directory) / "lane_execution_trace_v1.jsonl")[0]
            snapshot = self._rows(Path(directory) / "candidate_decision_ledger_v1.jsonl")[0]

            self.assertEqual(trace["exact_blocker"], "CANDIDATE_ELIGIBLE_AWAITING_FULL_CYCLE")
            self.assertEqual(trace["freshness_result"], "FRESH")
            self.assertTrue(trace["partial_cycle_observation_only"])
            self.assertEqual(snapshot["decision"], "DEFERRED")
            self.assertEqual(snapshot["first_causal_blocker"], "CANDIDATE_ELIGIBLE_AWAITING_FULL_CYCLE")
            self.assertEqual(result["candidate_decision_evidence_v1"]["deferred"], 1)
            self.assertEqual(result["candidate_decision_evidence_v1"]["provider_calls"], 0)
            self.assertEqual(result["candidate_decision_evidence_v1"]["broker_calls"], 0)

    def test_daily_summary_consumes_worker_capture_without_raw_ledger_scan(self):
        summary = build_astra_daily_intelligence_summary_v1(
            canonical_truths=[], bundle1={}, bundle2={}, operating_health={},
            worker_state={"last_execution_trace": {"candidate_decision_evidence_v1": {
                "snapshots_written": 3, "accepted": 1, "rejected": 0, "blocked": 1, "deferred": 1,
                "later_outcomes_linked": 0, "exact_trade_links": 1, "unresolved_links": 2,
                "by_lane": {"DAY": 1, "SCALP": 1, "CRYPTO": 1}, "full_history_scan_count": 0,
            }}},
        )
        capture = summary["candidate_evidence_capture"]
        self.assertEqual(capture["snapshots_today"], 3)
        self.assertEqual(capture["by_lane"]["CRYPTO"], 1)
        self.assertEqual(capture["full_history_scan_count"], 0)
        self.assertEqual(summary["efficiency"]["large_file_full_scans"], 0)

    def test_partial_cycle_trace_uses_existing_candidate_ledger_without_external_actions(self):
        class Ledger:
            def __init__(self):
                self.rows = None
                self.cycle_id = None

            def record(self, rows, *, cycle_id):
                self.rows = rows
                self.cycle_id = cycle_id
                return {"candidate_decision_evidence_v1": {"snapshots_written": len(rows), "provider_calls": 0, "broker_calls": 0, "llm_calls": 0}}

        engine = PaperAutopilotEngine.__new__(PaperAutopilotEngine)
        ledger = Ledger()
        engine.execution_trace_ledger = ledger

        receipt = engine._record_candidate_decision_trace_v1([candidate()], cycle_id="partial:cycle-1")

        self.assertEqual(ledger.cycle_id, "partial:cycle-1")
        self.assertEqual(ledger.rows[0]["candidate_id"], "cand-btc-1")
        self.assertEqual(receipt["candidate_decision_evidence_v1"]["snapshots_written"], 1)
        self.assertEqual(receipt["candidate_decision_evidence_v1"]["provider_calls"], 0)
        self.assertEqual(receipt["candidate_decision_evidence_v1"]["broker_calls"], 0)

    def test_existing_outcome_owner_requires_attributable_stored_price_for_snapshot(self):
        root = Path(__file__).resolve().parents[1]
        script = """
import json
import server_extend
server_extend.LAST_RANKINGS[\"crypto\"] = [{
    \"symbol\": \"BTC/USD\", \"price\": 110.0,
    \"market_observation_timestamp\": \"2026-08-20T14:00:00Z\",
    \"quote_source\": \"stored_test_quote\",
}]
row = {
    \"ledger_id\": \"decision:test\", \"candidate_decision_snapshot_id\": \"decision:test\",
    \"symbol\": \"BTC/USD\", \"asset_type\": \"crypto\", \"price_at_decision\": 100.0,
    \"timestamp_utc\": \"2026-08-20T12:00:00Z\",
}
print(json.dumps(server_extend._evaluate_outcome_label_v1(row, horizon_minutes=15)))
"""
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(root)
            completed = subprocess.run(
                [sys.executable, "-c", script], cwd=directory, env=environment,
                check=True, capture_output=True, text=True,
            )
        outcome = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(outcome["ledger_id"], "decision:test")
        self.assertEqual(outcome["candidate_decision_snapshot_id"], "decision:test")
        self.assertEqual(outcome["outcome_evidence_class"], "REAL_STORED_LATER_PRICE")
        self.assertEqual(outcome["outcome_observation_timestamp"], "2026-08-20T14:00:00Z")


if __name__ == "__main__":
    unittest.main()
