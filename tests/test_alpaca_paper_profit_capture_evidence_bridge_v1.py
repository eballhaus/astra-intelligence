from __future__ import annotations

import unittest

from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.trade_lifecycle_tracker import _normalize_record


def _orders(*, sell_price: str = "105") -> list[dict[str, str]]:
    return [
        {
            "id": "entry-1", "symbol": "AAPL", "side": "buy", "status": "filled",
            "filled_qty": "1", "filled_avg_price": "100", "filled_at": "2026-08-14T14:30:00Z",
        },
        {
            "id": "exit-1", "symbol": "AAPL", "side": "sell", "status": "filled",
            "filled_qty": "1", "filled_avg_price": sell_price, "filled_at": "2026-08-14T15:30:00Z",
        },
    ]


def _lifecycle(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "lifecycle_id": "life-1",
        "symbol": "AAPL",
        "lifecycle_stage": "closed",
        "exit_timestamp": "2026-08-14T15:30:00Z",
        "exit_order_id": "exit-1",
        "entry_order_id": "entry-1",
        "max_favorable_excursion_pct": 10.0,
        "max_adverse_excursion_pct": -3.0,
        "mfe_evidence_available": True,
        "mae_evidence_available": True,
        "peak_return_percent": 10.0,
        "drawdown_from_peak_percent": 5.0,
        "hold_time_seconds": 3600.0,
        "exit_quality_score": 55.0,
        "exit_quality_evidence_available": True,
    }
    row.update(overrides)
    return row


class AlpacaPaperProfitCaptureEvidenceBridgeTests(unittest.TestCase):
    def _broker(self, *, sell_price: str = "105", lifecycle_rows: list[dict[str, object]] | None = None) -> AlpacaPaperBroker:
        broker = AlpacaPaperBroker()
        broker.orders = lambda **_kwargs: {"ok": True, "orders": _orders(sell_price=sell_price)}  # type: ignore[method-assign]
        broker._canonical_closed_lifecycle_rows = lambda limit: list(lifecycle_rows or [])  # type: ignore[method-assign]
        return broker

    def test_exact_lifecycle_match_carries_excursions_and_calculates_capture(self):
        report = self._broker(lifecycle_rows=[_lifecycle()]).broker_truth_metrics()
        row = report["closed_trade_rows"][0]

        self.assertEqual(row["canonical_lifecycle_id"], "life-1")
        self.assertEqual(row["max_favorable_excursion"], 10.0)
        self.assertEqual(row["max_adverse_excursion"], -3.0)
        self.assertEqual(row["hold_time_seconds"], 3600.0)
        self.assertEqual(row["profit_capture_ratio"], 0.5)
        self.assertEqual(row["giveback_pct"], 5.0)
        self.assertEqual(row["exit_quality_score"], 55.0)
        self.assertEqual(report["true_paper_profit_capture"], 0.5)
        self.assertEqual(report["true_paper_avg_giveback"], 5.0)
        self.assertEqual(report["true_paper_exit_quality"], 55.0)
        self.assertEqual(report["profit_capture_trade_count"], 1)
        self.assertEqual(report["profit_capture_coverage_percent"], 100.0)
        self.assertEqual(report["mfe_available_count"], 1)
        self.assertEqual(report["mae_available_count"], 1)

    def test_close_lifecycle_contract_preserves_existing_excursion_and_order_lineage(self):
        record = _normalize_record(_lifecycle())

        self.assertEqual(record["exit_order_id"], "exit-1")
        self.assertEqual(record["entry_order_id"], "entry-1")
        self.assertTrue(record["mfe_evidence_available"])
        self.assertTrue(record["mae_evidence_available"])
        self.assertEqual(record["max_favorable_excursion_pct"], 10.0)
        self.assertEqual(record["max_adverse_excursion_pct"], -3.0)
        self.assertEqual(record["peak_return_percent"], 10.0)
        self.assertEqual(record["drawdown_from_peak_percent"], 5.0)
        self.assertEqual(record["hold_time_seconds"], 3600.0)
        self.assertEqual(record["exit_quality_score"], 55.0)
        self.assertTrue(record["exit_quality_evidence_available"])

    def test_missing_mfe_is_excluded_without_fabrication(self):
        report = self._broker(lifecycle_rows=[_lifecycle(
            max_favorable_excursion_pct=0.0,
            mfe_evidence_available=False,
        )]).broker_truth_metrics()
        row = report["closed_trade_rows"][0]

        self.assertIsNone(row["max_favorable_excursion"])
        self.assertIsNone(row["profit_capture_ratio"])
        self.assertIsNone(row["giveback_pct"])
        self.assertIsNone(report["true_paper_profit_capture"])
        self.assertIsNone(report["true_paper_avg_giveback"])
        self.assertEqual(report["mfe_available_count"], 0)
        self.assertEqual(report["mae_available_count"], 1)
        self.assertEqual(report["missing_excursion_evidence_count"], 1)

    def test_older_exact_lifecycle_with_nonzero_excursion_remains_usable(self):
        report = self._broker(lifecycle_rows=[_lifecycle(
            mfe_evidence_available=False,
            mae_evidence_available=False,
        )]).broker_truth_metrics()

        row = report["closed_trade_rows"][0]
        self.assertEqual(row["max_favorable_excursion"], 10.0)
        self.assertEqual(row["max_adverse_excursion"], -3.0)
        self.assertEqual(row["profit_capture_ratio"], 0.5)

    def test_losing_trade_does_not_create_winner_capture_metrics(self):
        report = self._broker(sell_price="95", lifecycle_rows=[_lifecycle()]).broker_truth_metrics()
        row = report["closed_trade_rows"][0]

        self.assertEqual(row["realized_return_pct"], -5.0)
        self.assertIsNone(row["profit_capture_ratio"])
        self.assertIsNone(row["giveback_pct"])
        self.assertIsNone(report["true_paper_profit_capture"])
        self.assertEqual(report["profit_capture_trade_count"], 0)

    def test_missing_canonical_exit_quality_is_not_reconstructed(self):
        report = self._broker(lifecycle_rows=[_lifecycle(
            exit_quality_score=None,
            exit_quality_evidence_available=False,
        )]).broker_truth_metrics()
        row = report["closed_trade_rows"][0]

        self.assertEqual(row["profit_capture_ratio"], 0.5)
        self.assertIsNone(row["exit_quality_score"])
        self.assertIsNone(report["true_paper_exit_quality"])

    def test_unmatched_lifecycle_is_not_joined_by_symbol_or_timestamp(self):
        report = self._broker(lifecycle_rows=[_lifecycle(exit_order_id="other-exit")]).broker_truth_metrics()
        row = report["closed_trade_rows"][0]

        self.assertEqual(row["lifecycle_excursion_evidence_status"], "UNMATCHED_CANONICAL_LIFECYCLE")
        self.assertIsNone(row["max_favorable_excursion"])
        self.assertEqual(report["missing_excursion_evidence_count"], 1)

    def test_ambiguous_exact_exit_order_match_fails_closed(self):
        second = _lifecycle(lifecycle_id="life-2", max_favorable_excursion_pct=20.0)
        baseline = self._broker(lifecycle_rows=[]).broker_truth_metrics()
        report = self._broker(lifecycle_rows=[_lifecycle(), second]).broker_truth_metrics()
        row = report["closed_trade_rows"][0]

        self.assertEqual(row["lifecycle_excursion_evidence_status"], "UNMATCHED_CANONICAL_LIFECYCLE")
        self.assertIsNone(row["max_favorable_excursion"])
        self.assertIsNone(row["max_adverse_excursion"])
        self.assertIsNone(row["profit_capture_ratio"])
        self.assertIsNone(row["giveback_pct"])
        self.assertIsNone(row["exit_quality_score"])
        self.assertEqual(report["true_paper_pf"], baseline["true_paper_pf"])
        self.assertEqual(report["true_paper_roi"], baseline["true_paper_roi"])

    def test_existing_broker_profit_metrics_are_unchanged_by_enrichment(self):
        baseline = self._broker(lifecycle_rows=[]).broker_truth_metrics()
        enriched = self._broker(lifecycle_rows=[_lifecycle()]).broker_truth_metrics()

        for field in (
            "true_paper_pf", "true_paper_win_rate", "true_paper_avg_return", "true_paper_roi",
            "paper_gross_profit", "paper_gross_loss", "paired_round_trip_count",
        ):
            self.assertEqual(enriched[field], baseline[field], field)

    def test_metrics_are_read_only_and_cannot_submit_cancel_or_close_orders(self):
        broker = self._broker(lifecycle_rows=[_lifecycle()])
        execution_state = (broker._last_order_status, broker._last_error, broker._api_calls_used)

        def unexpected_execution(*_args, **_kwargs):
            raise AssertionError("broker_truth_metrics must not invoke execution")

        broker.submit_paper_order = unexpected_execution  # type: ignore[method-assign]
        broker.cancel_paper_order = unexpected_execution  # type: ignore[method-assign]
        broker.close_paper_position = unexpected_execution  # type: ignore[method-assign]
        report = broker.broker_truth_metrics()

        self.assertTrue(report["ok"])
        self.assertEqual(report["closed_orders_reviewed"], 2)
        self.assertEqual(report["filled_orders_reviewed"], 2)
        self.assertEqual((broker._last_order_status, broker._last_error, broker._api_calls_used), execution_state)


if __name__ == "__main__":
    unittest.main()
