"""Observability-only persistence of the CRYPTO final stale-quote refresh diagnostics.

These fields document a single already-bounded refresh decision.  They are
never read by any eligibility, ranking, risk, capital, or broker path, so
persisting them must not change trading behavior, provider calls, or broker
actions.  The trace ledger remains append-only and bounded.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1
from engine.paper_autopilot import PaperAutopilotEngine


def _iso(offset: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


def _base_row(lane: str = "CRYPTO") -> dict:
    return {
        "lane_id": lane, "candidate_id": "cand-refresh-1", "recommendation_id": "rec-refresh-1",
        "symbol": "BTC/USD", "asset_type": "crypto", "candidate_generated_at": _iso(),
        "generated_at": _iso(), "eligible": False, "selected": False, "order_ready": False,
    }


class CryptoFinalRefreshTracePersistenceTests(unittest.TestCase):
    def test_refresh_attempted_persists_when_present(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {**_base_row(), "crypto_final_quote_refresh_attempted": True}
            ledger.record([row], cycle_id="cycle-1")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertIs(record["crypto_final_quote_refresh_attempted"], True)

    def test_refresh_attempt_count_persists(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {**_base_row(), "crypto_final_quote_refresh_attempt_count": 1}
            ledger.record([row], cycle_id="cycle-2")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["crypto_final_quote_refresh_attempt_count"], 1)

    def test_refresh_result_persists(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {**_base_row(), "crypto_final_quote_refresh_result": "STALE_PROVIDER_NATIVE_TIMESTAMP"}
            ledger.record([row], cycle_id="cycle-3")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["crypto_final_quote_refresh_result"], "STALE_PROVIDER_NATIVE_TIMESTAMP")

    def test_hot_refresh_provenance_persists(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                **_base_row("SCALP"),
                "hot_candidate_quote_refresh_lane": "SCALP",
                "hot_candidate_quote_refresh_attempted": True,
                "hot_candidate_quote_refresh_attempt_count": 1,
                "hot_candidate_quote_refresh_result": "FRESH",
                "hot_candidate_quote_refresh_cache_bypass_requested": True,
            }
            ledger.record([row], cycle_id="cycle-hot")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["hot_candidate_quote_refresh_lane"], "SCALP")
            self.assertIs(record["hot_candidate_quote_refresh_attempted"], True)
            self.assertEqual(record["hot_candidate_quote_refresh_result"], "FRESH")
            self.assertIs(record["hot_candidate_quote_refresh_cache_bypass_requested"], True)

    def test_refreshed_quote_timestamp_and_age_persist_when_present(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                **_base_row(),
                "crypto_final_quote_refresh_attempted": True,
                "crypto_final_refresh_quote_timestamp": _iso(-2),
                "crypto_final_refresh_quote_age_seconds": 2.0,
            }
            ledger.record([row], cycle_id="cycle-4")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertTrue(record["crypto_final_refresh_quote_timestamp"])
            self.assertEqual(record["crypto_final_refresh_quote_age_seconds"], 2.0)

    def test_absence_preserves_existing_behavior(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            ledger.record([_base_row()], cycle_id="cycle-5")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertIs(record["crypto_final_quote_refresh_attempted"], False)
            self.assertIsNone(record["crypto_final_quote_refresh_attempt_count"])
            self.assertEqual(record["crypto_final_quote_refresh_result"], "")
            self.assertEqual(record["crypto_final_refresh_quote_timestamp"], "")
            self.assertIsNone(record["crypto_final_refresh_quote_age_seconds"])
            self.assertEqual(record["lane_id"], "CRYPTO")

    def test_trace_remains_bounded_and_append_only(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {**_base_row(), "crypto_final_quote_refresh_attempted": True, "crypto_final_quote_refresh_attempt_count": 1}
            for cycle in ("cycle-a", "cycle-b"):
                ledger.record([row], cycle_id=cycle)
            lines = [line for line in open(ledger.path, "r", encoding="utf-8") if line.strip()]
            self.assertEqual(len(lines), 2)
            summary = ledger.summary()
            self.assertEqual(summary["total_trace_rows"], 2)
            self.assertEqual(summary["lanes"]["CRYPTO"]["candidates_seen"], 2)

    def test_blocker_specific_observability_persists_in_existing_trace(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                **_base_row("SCALP"),
                "decision_reason": "PRETRADE_DECISION_CONTRACT_MISSING_FIELDS",
                "entry_commitment_trace_v1": {
                    "commitment_score": 53.2,
                    "applied_minimum": 58.0,
                    "defaulted_inputs": ["consensus_strength"],
                },
                "pretrade_contract_missing_fields_trace_v1": {
                    "missing_required_fields": ["candidate_risk_envelope_v1"],
                    "contract_lane": "SCALP",
                    "intended_horizon": "scalp",
                    "risk_envelope_missing_fields": ["expected_downside_range"],
                },
            }
            ledger.record([row], cycle_id="cycle-blocker")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["entry_commitment_trace_v1"]["commitment_score"], 53.2)
            self.assertEqual(record["entry_commitment_trace_v1"]["defaulted_inputs"], ["consensus_strength"])
            self.assertEqual(
                record["pretrade_contract_missing_fields_trace_v1"]["missing_required_fields"],
                ["candidate_risk_envelope_v1"],
            )
            self.assertEqual(record["pretrade_contract_missing_fields_trace_v1"]["contract_lane"], "SCALP")

    def test_inner_freshness_trace_persists_without_quote_payload(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                **_base_row(),
                "crypto_inner_freshness_trace_v1": {
                    "candidate_id": "cand-refresh-1",
                    "inner_timestamp_used": _iso(-1),
                    "inner_timestamp_source": "provider_quote_timestamp",
                    "inner_age_seconds": 1.0,
                    "freshness_limit_seconds": 120.0,
                    "failed_condition": "PASS",
                },
            }
            ledger.record([row], cycle_id="cycle-inner-freshness")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            trace = record["crypto_inner_freshness_trace_v1"]
            self.assertEqual(trace["inner_timestamp_source"], "provider_quote_timestamp")
            self.assertEqual(trace["freshness_limit_seconds"], 120.0)
            self.assertNotIn("raw_quote", trace)


class CryptoFinalRefreshTraceFlowTests(unittest.TestCase):

    def test_inner_freshness_trace_uses_the_provider_timestamp_consumed_by_integrity(self):
        fresh_timestamp = _iso(-1)
        trace = PaperAutopilotEngine._crypto_inner_freshness_trace_v1(
            {
                "candidate_id": "cand-inner", "lifecycle_id": "life-inner", "symbol": "BTC/USD",
                "lane_id": "CRYPTO", "provider_quote_timestamp": fresh_timestamp,
                "quote_timestamp": _iso(-30), "quote_age_seconds": 1.0,
                "hot_candidate_quote_refresh_cache_bypass_requested": True,
                "final_executable_quote_refresh_authoritative": True,
            },
            {"quote_age_seconds": 1.0, "gate_status": {"timestamp_freshness": "PASS"}},
        )
        self.assertEqual(trace["inner_timestamp_used"], fresh_timestamp)
        self.assertEqual(trace["inner_timestamp_source"], "provider_quote_timestamp")
        self.assertEqual(trace["outer_final_quote_timestamp"], fresh_timestamp)
        self.assertEqual(trace["outer_freshness_limit_seconds"], 20.0)
        self.assertTrue(trace["cache_bypass_requested"])

    def test_terminal_submission_rejection_is_preserved_over_obsolete_pre_refresh_blocker(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = LaneExecutionTraceLedgerV1(root)
            row = {
                **_base_row(),
                "eligible": True,
                "selected": True,
                "order_ready": True,
                "order_result": "rejected",
                "decision_reason": "timestamp_freshness",
                "order_rejection_reason": "broker_preflight_rejected",
                "broker_error_sanitized": "broker_preflight_rejected",
            }
            ledger.record([row], cycle_id="cycle-terminal-rejection")
            with open(ledger.path, "r", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
            self.assertEqual(record["exact_blocker"], "broker_preflight_rejected")
            self.assertEqual(record["order_rejection_reason"], "broker_preflight_rejected")
            self.assertEqual(record["broker_error_sanitized"], "broker_preflight_rejected")

    def test_inner_freshness_trace_keeps_missing_native_timestamp_fail_closed(self):
        trace = PaperAutopilotEngine._crypto_inner_freshness_trace_v1(
            {"candidate_id": "cand-missing", "symbol": "BTC/USD", "lane_id": "CRYPTO"},
            {"quote_age_seconds": -1.0, "gate_status": {"timestamp_freshness": "PENDING_QUOTE_FRESHNESS"}},
        )
        self.assertEqual(trace["inner_timestamp_source"], "UNAVAILABLE")
        self.assertEqual(trace["failed_condition"], "PENDING_QUOTE_FRESHNESS")
    def test_candidate_trace_carries_refresh_fields_into_trace_dict(self):
        directory = tempfile.TemporaryDirectory(prefix="astra_crypto_refresh_flow_")
        self.addCleanup(directory.cleanup)
        calls: list[int] = []
        engine = PaperAutopilotEngine(
            db_path=os.path.join(directory.name, "paper.db"),
            state_path=os.path.join(directory.name, "state.json"),
            enabled=False,
            get_latest_row_fn=lambda _symbol, _asset: calls.append(1) or {
                "symbol": "BTC/USD", "asset_type": "crypto", "price": 101.0,
                "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
            },
        )
        assigned = engine._assign_trusted_quote_to_candidate({
            "symbol": "BTC/USD", "asset_type": "crypto", "price": 100.0,
            "provider_quote_timestamp": _iso(-45), "market_source_type": "QUOTE",
            "generated_at": _iso(), "candidate_generated_at": _iso(),
        })
        self.assertEqual(assigned["crypto_final_quote_refresh_attempted"], True)
        self.assertEqual(assigned["crypto_final_quote_refresh_attempt_count"], 1)
        self.assertEqual(assigned["crypto_final_quote_refresh_result"], "FRESH")
        trace, _allowed, _reason, _meta = engine._candidate_trace_row(
            assigned,
            open_syms=set(),
            stock_capacity=10,
            crypto_capacity=10,
            total_capacity=10,
        )
        self.assertIs(trace["crypto_final_quote_refresh_attempted"], True)
        self.assertEqual(trace["crypto_final_quote_refresh_attempt_count"], 1)
        self.assertEqual(trace["crypto_final_quote_refresh_result"], "FRESH")
        self.assertTrue(trace["crypto_final_refresh_quote_timestamp"])
        self.assertIsNotNone(trace["crypto_final_refresh_quote_age_seconds"])
        self.assertEqual(len(calls), 1)

    def test_no_trading_decision_change_from_refresh_fields(self):
        directory = tempfile.TemporaryDirectory(prefix="astra_crypto_refresh_noop_")
        self.addCleanup(directory.cleanup)
        calls: list[int] = []
        engine = PaperAutopilotEngine(
            db_path=os.path.join(directory.name, "paper.db"),
            state_path=os.path.join(directory.name, "state.json"),
            enabled=False,
            get_latest_row_fn=lambda _symbol, _asset: calls.append(1) or {
                "symbol": "AAPL", "asset_type": "stock", "price": 101.0,
                "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
            },
        )
        assigned = engine._assign_trusted_quote_to_candidate({
            "symbol": "AAPL", "asset_type": "stock", "price": 100.0,
        })
        self.assertTrue(assigned["trusted_quote_for_buys"])
        self.assertNotIn("crypto_final_quote_refresh_attempted", assigned)
        self.assertEqual(len(calls), 1)
        trace, _allowed, _reason, _meta = engine._candidate_trace_row(
            assigned,
            open_syms=set(),
            stock_capacity=10,
            crypto_capacity=10,
            total_capacity=10,
        )
        self.assertIs(trace["crypto_final_quote_refresh_attempted"], False)
        self.assertEqual(trace["crypto_final_quote_refresh_attempt_count"], 0)
        self.assertEqual(trace["crypto_final_refresh_quote_timestamp"], "")
        self.assertIsNone(trace["crypto_final_refresh_quote_age_seconds"])


if __name__ == "__main__":
    unittest.main()
