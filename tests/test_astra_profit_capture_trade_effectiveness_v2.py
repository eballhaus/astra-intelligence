from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.adaptive_profit_capture_intelligence_v1 import build_profit_capture_trade_effectiveness_v2
from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1


NOW = datetime(2026, 8, 19, 16, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z")
ENTRY = (datetime(2026, 8, 19, 16, 0, tzinfo=UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")


def _truth(
    *,
    lifecycle_id: str = "life-1",
    symbol: str = "ABC",
    lane: str = "DAY",
    horizon: str = "day_trade",
    realized: float = 5.0,
    peak: float | None = 10.0,
    mfe_available: bool = True,
    exit_reason: str = "TAKE_PROFIT",
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "lifecycle_id": lifecycle_id,
        "stable_key": f"truth:{lifecycle_id}",
        "symbol": symbol,
        "lane_id": lane,
        "intended_horizon": horizon,
        "truth_quality": "BROKER_CONFIRMED_COMPLETE",
        "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        "entry_fill_id": f"entry:{lifecycle_id}",
        "exit_fill_id": f"exit:{lifecycle_id}",
        "entry_price": 100.0,
        "exit_price": 100.0 + realized,
        "entry_timestamp": ENTRY,
        "realized_return_pct": realized,
        "max_favorable_excursion_pct": peak,
        "mfe_evidence_available": mfe_available,
        "hold_duration_seconds": 86_400,
        "exit_timestamp": NOW,
        "exit_reason": exit_reason,
    }
    row.update(extra)
    return row


class ProfitCaptureTradeEffectivenessV2Tests(unittest.TestCase):
    def test_winning_trade_capture_and_giveback_use_canonical_peak(self) -> None:
        result = build_profit_capture_trade_effectiveness_v2([_truth(realized=5.0, peak=10.0)])
        row = result["trade_rows"][0]
        self.assertEqual(row["profit_capture_pct"], 50.0)
        self.assertEqual(row["profit_giveback_pct"], 5.0)
        self.assertEqual(row["profit_giveback_from_peak_pct"], 50.0)
        self.assertEqual(row["profit_capture_classification"], "MODERATE_GIVEBACK")
        self.assertEqual(row["evidence_quality"], "BROKER_TRUTH_WITH_CANONICAL_EXCURSION")

    def test_never_profitable_and_missing_peak_remain_explicitly_unavailable(self) -> None:
        never = build_profit_capture_trade_effectiveness_v2([_truth(realized=-2.0, peak=-0.2, exit_reason="STOP_LOSS")])["trade_rows"][0]
        self.assertEqual(never["profit_capture_classification"], "NEVER_PROFITABLE")
        self.assertIsNone(never["profit_capture_pct"])
        self.assertEqual(never["exit_effectiveness"], "LOSS_ACCEPTANCE_EFFECTIVE")

        missing = build_profit_capture_trade_effectiveness_v2([_truth(peak=None, mfe_available=False)])
        self.assertEqual(missing["trade_rows"][0]["profit_capture_classification"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(missing["integrity_facts"][0]["kind"], "PRODUCER_MISSING")

    def test_controlled_loss_is_not_labeled_as_a_bad_exit(self) -> None:
        row = build_profit_capture_trade_effectiveness_v2([_truth(realized=-1.0, peak=0.0, exit_reason="THESIS_INVALIDATION")])["trade_rows"][0]
        self.assertEqual(row["exit_effectiveness"], "LOSS_ACCEPTANCE_EFFECTIVE")
        self.assertEqual(row["entry_management_exit_attribution"], "POOR_ENTRY_EFFECTIVE_LOSS_CONTROL")

    def test_lane_partition_and_shadow_are_separate_from_official_truth(self) -> None:
        records = [
            _truth(lifecycle_id="day", lane="DAY", realized=8.0, peak=10.0),
            _truth(lifecycle_id="crypto", lane="CRYPTO", realized=2.0, peak=10.0),
            {**_truth(lifecycle_id="shadow-like", realized=99.0, peak=100.0), "truth_quality": "RECONSTRUCTED"},
        ]
        result = build_profit_capture_trade_effectiveness_v2(
            records,
            shadow_exit_performance={"sample_size": 4, "metrics": {"shadow_win_rate": 0.75, "shadow_average_return": 7.0}},
        )
        self.assertEqual(result["completed_broker_truth_sample_size"], 2)
        self.assertEqual(result["horizon_lane_breakdown"]["DAY"]["completed_broker_truth_sample_size"], 1)
        self.assertEqual(result["horizon_lane_breakdown"]["CRYPTO"]["completed_broker_truth_sample_size"], 1)
        self.assertEqual(result["average_profit_capture_pct"], 50.0)
        self.assertEqual(result["shadow_exit_sample_size"], 4)
        self.assertTrue(result["shadow_metrics_never_promoted"])

        compared = build_profit_capture_trade_effectiveness_v2(
            [_truth(lifecycle_id="day", realized=5.0, peak=10.0)],
            shadow_exit_outputs={"outputs": [{"lifecycle_id": "day", "shadow_return_pct": 7.0}]},
        )
        self.assertEqual(compared["counterfactual_exit_comparisons"][0]["return_difference_pct"], 2.0)
        self.assertTrue(compared["counterfactual_exit_comparisons"][0]["shadow_only"])

    def test_stale_peak_cannot_become_official_capture(self) -> None:
        result = build_profit_capture_trade_effectiveness_v2([
            _truth(peak=10.0, peak_evidence_freshness="STALE"),
        ])
        row = result["trade_rows"][0]
        self.assertIsNone(row["profit_capture_pct"])
        self.assertEqual(row["evidence_quality"], "STALE_OR_RECONSTRUCTED_EVIDENCE")
        self.assertEqual(result["integrity_facts"][0]["kind"], "HISTORICAL")

    def test_peak_handoff_loss_reaches_existing_sentinel_classifier(self) -> None:
        effectiveness = build_profit_capture_trade_effectiveness_v2([
            _truth(peak=None, mfe_available=True),
        ])
        with tempfile.TemporaryDirectory() as directory:
            scan = ContinuousSystemIntegrityScannerV1(Path(directory)).run_if_due(
                worker_state={
                    "process_role": "PAPER_AUTOPILOT_WORKER", "active_worker_present": True,
                    "ownership_state": "SINGLE_WORKER_ACTIVE", "heartbeat_at": NOW,
                    "worker_generation_id": "g-v2", "resource_state": "RESOURCE_NORMAL",
                },
                runtime_state={}, safety={},
                context={"targeted_reasons": ["test"], "profit_capture_trade_effectiveness": effectiveness},
            )
        causal = scan["causal_handoff_integrity_v1"]["signals"]
        self.assertTrue(any(row["category"] == "CAUSAL_HANDOFF_LOSS" for row in causal))
        self.assertEqual(scan["resource_usage"]["provider_calls_used"], 0)
        self.assertEqual(scan["resource_usage"]["broker_actions_used"], 0)

    def test_analytics_are_observational_and_lane_behavior_is_unchanged(self) -> None:
        result = build_profit_capture_trade_effectiveness_v2([_truth(lane="SCALP"), _truth(lifecycle_id="swing", lane="SWING")])
        self.assertFalse(result["execution_behavior_changed"])
        self.assertTrue(result["paper_only_preserved"])
        self.assertFalse(result["live_trading_changed"])
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_calls_used"], 0)
        self.assertEqual(result["llm_calls_used"], 0)


if __name__ == "__main__":
    unittest.main()
