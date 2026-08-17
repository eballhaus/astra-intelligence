"""Focused observability tests for the managed-position quote handoff trace."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.paper_autopilot import PaperAutopilotEngine


def _iso(offset_seconds: float = 0.0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


class ExecutableExitQuoteTraceTests(unittest.TestCase):
    def _engine(self, quote_callback, path: str) -> PaperAutopilotEngine:
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {}
        engine.get_latest_row_fn = quote_callback
        engine.executable_exit_quote_trace_path = path
        return engine

    @staticmethod
    def _managed_row() -> dict:
        return {
            "symbol": "UAL",
            "canonical_position_id": "ual-life",
            "lifecycle_id": "ual-life",
            "position_id": "ual-life",
            "lane_id": "SWING",
            "paper_entry_horizon_style": "swing_trade",
            "entry_price": 100.0,
            "hold_seconds": 10_000.0,
            "lifecycle_notes": '{"peak_unrealized_pnl_percent": 4.8}',
        }

    def test_fresh_quote_is_accepted_and_evaluator_exit_is_captured(self):
        calls = []

        def quote(symbol, asset_type):
            calls.append((symbol, asset_type))
            return {
                "symbol": symbol,
                "price": 90.0,
                "provider_used": "alpaca_market_data",
                "provider_quote_timestamp": _iso(),
                "retrieval_timestamp": _iso(),
            }

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "astra_executable_exit_quote_trace_v1.json")
            engine = self._engine(quote, path)
            managed = self._managed_row()
            latest_by_symbol = engine._loss_containment_quote_evidence(
                {"UAL": {"symbol": "UAL", "current_price": "90", "asset_type": "stock"}},
                managed_rows_by_symbol={"UAL": managed},
            )
            should_close, reason = engine._evaluate_exit(managed, latest_by_symbol["UAL"])
            engine._record_executable_exit_quote_evaluation(
                managed, latest_by_symbol["UAL"], should_close=should_close, reason=reason
            )
            engine._persist_executable_exit_quote_trace()

            trace = json.loads(Path(path).read_text())
            row = trace["rows"][0]
            self.assertEqual(calls, [("UAL", "stock")])
            self.assertTrue(row["quote_request_attempted"])
            self.assertTrue(row["accepted_into_latest_price_by_symbol"])
            self.assertTrue(row["present_in_latest_price_by_symbol"])
            self.assertTrue(row["delivered_to_evaluate_exit"])
            self.assertEqual(row["evaluator_exit_reason"], "stop_loss_breach")
            self.assertEqual(row["canonical_position_id"], "ual-life")
            self.assertEqual(row["lane"], "SWING")
            self.assertEqual(row["horizon"], "swing_trade")

    def test_stale_native_quote_is_traced_but_not_accepted(self):
        engine = self._engine(
            lambda symbol, _asset: {
                "symbol": symbol, "price": 100.0,
                "provider_quote_timestamp": _iso(-30), "provider_used": "alpaca_market_data",
            },
            "unused.json",
        )
        engine._loss_containment_quote_evidence(
            {"UAL": {"symbol": "UAL", "current_price": "100"}},
            managed_rows_by_symbol={"UAL": self._managed_row()},
        )
        row = engine._runtime_state["executable_exit_quote_trace_v1"]["rows"][0]
        self.assertFalse(row["accepted_into_latest_price_by_symbol"])
        self.assertEqual(row["freshness_status"], "STALE")
        self.assertEqual(row["rejection_blocker"], "STALE_PROVIDER_NATIVE_TIMESTAMP")
        self.assertGreater(row["quote_age_seconds"], 20.0)

    def test_missing_timestamp_and_broker_mark_remain_fail_closed(self):
        engine = self._engine(lambda _symbol, _asset: {}, "unused.json")
        latest = engine._loss_containment_quote_evidence(
            {"UAL": {"symbol": "UAL", "current_price": "100", "asset_type": "stock"}},
            managed_rows_by_symbol={"UAL": self._managed_row()},
        )
        row = engine._runtime_state["executable_exit_quote_trace_v1"]["rows"][0]
        should_close, reason = engine._evaluate_exit(self._managed_row(), latest["UAL"])
        self.assertFalse(row["accepted_into_latest_price_by_symbol"])
        self.assertTrue(row["present_in_latest_price_by_symbol"])
        self.assertEqual(row["rejection_blocker"], "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE")
        self.assertFalse(should_close)
        self.assertEqual(reason, "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE")

    def test_trace_does_not_request_more_than_existing_quote_collection(self):
        calls = []

        def quote(symbol, _asset):
            calls.append(symbol)
            return {"symbol": symbol, "price": 100.0, "provider_quote_timestamp": _iso()}

        engine = self._engine(quote, "unused.json")
        engine._loss_containment_quote_evidence(
            {"UAL": {"symbol": "UAL", "current_price": "100"}},
            managed_rows_by_symbol={"UAL": self._managed_row()},
        )
        self.assertEqual(calls, ["UAL"])
        self.assertNotIn("alpaca_paper_broker", engine.__dict__)


if __name__ == "__main__":
    unittest.main()
