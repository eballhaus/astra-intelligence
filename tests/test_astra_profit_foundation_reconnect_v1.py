import json
import os
import tempfile
import unittest

from engine.edge_development_suite_v1 import EdgeDevelopmentSuiteV1
from engine.exit_learning_expansion_suite_v1 import ExitLearningExpansionSuiteV1
from engine.paper_autopilot import PaperAutopilotEngine


def _strict_record(
    *,
    candidate_id: str = "cand-1",
    recommendation_id: str = "rec-1",
    selection_id: str = "sel-1",
    lifecycle_id: str = "life-1",
    entry_price: float = 10.0,
    exit_price: float = 12.0,
    quantity: float = 5.0,
    realized_return: float = 20.0,
    realized_pnl: float = 10.0,
    symbol: str = "AAPL",
    lane_id: str = "DAY",
) -> dict:
    return {
        "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        "truth_quality": "BROKER_CONFIRMED_COMPLETE",
        "source": "paper_autopilot_authorized_lane_exit",
        "candidate_id": candidate_id,
        "recommendation_id": recommendation_id,
        "selection_id": selection_id,
        "lifecycle_id": lifecycle_id,
        "entry_fill_id": f"{lifecycle_id}-entry-fill",
        "exit_fill_id": f"{lifecycle_id}-exit-fill",
        "entry_order_id": f"{lifecycle_id}-entry-order",
        "exit_order_id": f"{lifecycle_id}-exit-order",
        "broker_residual_zero_confirmed": True,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "filled_qty": quantity,
        "exit_filled_quantity": quantity,
        "realized_return": realized_return,
        "realized_pnl": realized_pnl,
        "symbol": symbol,
        "lane_id": lane_id,
        "entry_time": "2026-01-01T10:00:00Z",
        "exit_time": "2026-01-01T11:00:00Z",
    }


def _seed_edge_state(state_dir: str, strict_rows: list[dict] | None = None) -> None:
    with open(os.path.join(state_dir, "broker_truth_records_v1.json"), "w", encoding="utf-8") as handle:
        json.dump({"records": strict_rows if strict_rows is not None else []}, handle)


class Task1RealizedDollarPnlStrictTruthTests(unittest.TestCase):
    def _engine(self, state_dir: str) -> PaperAutopilotEngine:
        return PaperAutopilotEngine(
            db_path=os.path.join(state_dir, "ai_trading_memory.db"),
            state_path=os.path.join(state_dir, "paper_autopilot_state.json"),
        )

    def _open_row(self, **overrides) -> dict:
        row = {
            "lane_id": "DAY",
            "position_id": "life-1",
            "entry_order_id": "entry-order-1",
            "entry_fill_id": "entry-fill-1",
            "entry_price_verified": True,
            "broker_filled_avg_price": 10.0,
            "source_bucket": "CANONICAL_MANAGED",
            "symbol": "AAPL",
            "asset_type": "stock",
            "quantity": 5.0,
            "entry_timestamp": "2026-01-01T10:00:00Z",
            "source_candidate_id": "cand-1",
            "source_recommendation_id": "rec-1",
            "source_decision_id": "sel-1",
            "row_json": json.dumps({"candidate_id": "cand-1", "instrument_type": "STOCK", "strategy_cohort": "day"}),
            "entry_metadata_json": json.dumps({}),
            "lifecycle_notes": json.dumps({}),
        }
        row.update(overrides)
        return row

    def test_exact_realized_dollar_pnl_persists_beside_realized_return(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine = self._engine(state_dir)
            result = engine._persist_strict_lane_truth(
                self._open_row(),
                {
                    "exit_order_id": "exit-order-1",
                    "exit_fill_id": "exit-fill-1",
                    "filled_at": "2026-01-01T11:00:00Z",
                    "filled_qty": 5.0,
                    "remaining_qty": 0.0,
                    "broker_residual_zero_confirmed": True,
                },
                exit_price=12.0,
                return_percent=20.0,
                hold_seconds=3600.0,
                exit_reason="take_profit",
            )
            self.assertTrue(result.get("persisted"))
            with open(os.path.join(state_dir, "broker_truth_records_v1.json"), "r", encoding="utf-8") as handle:
                registry = json.load(handle)
            records = registry.get("records") or []
            self.assertTrue(records)
            record = records[-1]
            self.assertEqual(record["realized_return"], 20.0)
            self.assertEqual(record["realized_pnl"], 10.0)
            self.assertTrue(record["realized_pnl_available"])
            self.assertEqual(record["realized_pnl_source"], "broker_confirmed_paired_fill_prices_and_quantity")

    def test_missing_dollar_pnl_stays_none_when_broker_value_unavailable(self):
        with tempfile.TemporaryDirectory() as state_dir:
            engine = self._engine(state_dir)
            result = engine._persist_strict_lane_truth(
                self._open_row(quantity=0.0),
                {
                    "exit_order_id": "exit-order-1",
                    "exit_fill_id": "exit-fill-1",
                    "filled_at": "2026-01-01T11:00:00Z",
                    "filled_qty": 0.0,
                    "remaining_qty": 0.0,
                    "broker_residual_zero_confirmed": True,
                },
                exit_price=12.0,
                return_percent=0.0,
                hold_seconds=3600.0,
                exit_reason="take_profit",
            )
            self.assertTrue(result.get("persisted"))
            with open(os.path.join(state_dir, "broker_truth_records_v1.json"), "r", encoding="utf-8") as handle:
                registry = json.load(handle)
            records = registry.get("records") or []
            record = records[-1]
            self.assertIsNone(record["realized_pnl"])
            self.assertFalse(record["realized_pnl_available"])
            self.assertEqual(record["realized_pnl_source"], "UNAVAILABLE_BROKER_VALUE")


class Task2ExactIdentityCandidateOutcomeJoinTests(unittest.TestCase):
    def test_exact_identity_join_links_and_nonmatching_is_unlinked(self):
        with tempfile.TemporaryDirectory() as state_dir:
            _seed_edge_state(state_dir, [_strict_record(candidate_id="cand-exact", realized_return=15.0, realized_pnl=7.5)])
            suite = EdgeDevelopmentSuiteV1(state_dir=state_dir)
            candidates = [
                {"candidate_id": "cand-exact", "action": "Buy Candidate", "grade": "A"},
                {"candidate_id": "cand-no-match", "action": "Buy Candidate", "grade": "B"},
                {"symbol": "XYZ", "action": "Buy Candidate"},
            ]
            result = suite.strict_outcome_join_v1(candidate_rows=candidates)
            self.assertTrue(result["exact_identity_only"])
            self.assertFalse(result["fuzzy_matching_used"])
            self.assertEqual(result["linked_candidate_count"], 1)
            self.assertEqual(result["unlinked_candidate_count"], 2)
            self.assertEqual(result["linked_candidates"][0]["linkage_method"], "EXACT_IDENTITY")
            self.assertEqual(result["linked_candidates"][0]["realized_return_pct"], 15.0)
            self.assertEqual(result["linked_candidates"][0]["realized_pnl"], 7.5)

    def test_missing_id_remains_unlinked_never_approximated(self):
        with tempfile.TemporaryDirectory() as state_dir:
            _seed_edge_state(state_dir, [_strict_record(candidate_id="cand-a", symbol="AAPL", entry_price=10.0)])
            suite = EdgeDevelopmentSuiteV1(state_dir=state_dir)
            candidate = {"candidate_id": "", "symbol": "AAPL", "action": "Buy Candidate"}
            result = suite.strict_outcome_join_v1(candidate_rows=[candidate])
            self.assertEqual(result["linked_candidate_count"], 0)
            self.assertEqual(result["unlinked_candidate_count"], 1)
            self.assertEqual(result["unlinked_candidates"][0]["linkage_status"], "UNLINKED")


class Task3EvCalibrationTests(unittest.TestCase):
    def _joined(self, count: int) -> list[dict]:
        rows = []
        for index in range(count):
            win = index % 2 == 0
            rows.append({
                "candidate_id": f"cand-{index}",
                "expected_value_score": 78.0 if win else 52.0,
                "expected_value_ratio": 1.2 if win else 0.4,
                "expected_win_probability": 75.0 if win else 35.0,
                "realized_return_pct": 8.0 if win else -4.0,
                "realized_pnl": 8.0 if win else -4.0,
            })
        return rows

    def test_insufficient_sample_fails_closed(self):
        with tempfile.TemporaryDirectory() as state_dir:
            suite = EdgeDevelopmentSuiteV1(state_dir=state_dir)
            result = suite.calibrate_expected_value_vs_outcomes(self._joined(5))
            self.assertEqual(result["calibration_status"], "INSUFFICIENT_STRICT_OUTCOME_SAMPLE")
            self.assertFalse(result["rankings_changed"])
            self.assertFalse(result["behavior_safe_to_apply"])

    def test_sufficient_sample_produces_observational_calibration(self):
        with tempfile.TemporaryDirectory() as state_dir:
            suite = EdgeDevelopmentSuiteV1(state_dir=state_dir)
            result = suite.calibrate_expected_value_vs_outcomes(self._joined(40))
            self.assertEqual(result["calibration_status"], "OBSERVATIONAL_PASS")
            self.assertEqual(result["sample_count"], 40)
            self.assertFalse(result["rankings_changed"])
            self.assertFalse(result["ev_formula_changed"])
            self.assertFalse(result["behavior_safe_to_apply"])

    def test_calibration_does_not_alter_ranking_behavior(self):
        with tempfile.TemporaryDirectory() as state_dir:
            strict_rows = [
                _strict_record(
                    candidate_id=f"cand-{index}",
                    lifecycle_id=f"life-{index}",
                    symbol="AAPL",
                    entry_price=10.0,
                    exit_price=12.0 if index % 2 == 0 else 9.6,
                    quantity=5.0,
                    realized_return=20.0 if index % 2 == 0 else -4.0,
                    realized_pnl=10.0 if index % 2 == 0 else -2.0,
                )
                for index in range(40)
            ]
            _seed_edge_state(state_dir, strict_rows)
            suite = EdgeDevelopmentSuiteV1(state_dir=state_dir)
            status = suite.status(rows=self._joined(40))
            calibration = status["ev_calibration_vs_outcomes_v1"]
            self.assertEqual(calibration["calibration_status"], "OBSERVATIONAL_PASS")
            self.assertFalse(calibration["rankings_changed"])
            self.assertEqual(status["production_rankings_changed"], False)
            self.assertEqual(status["production_weights_changed"], False)


class Task4AvoidableLossExitLearningTests(unittest.TestCase):
    def _seed_v2(self, state_dir: str, rows: list[dict]) -> None:
        with open(os.path.join(state_dir, "trade_lifecycle_excursion_v2.jsonl"), "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def test_avoidable_loss_aggregation_uses_excursion_v2(self):
        with tempfile.TemporaryDirectory() as state_dir:
            self._seed_v2(state_dir, [
                {"symbol": "AAPL", "lifecycle_id": f"life-{i}", "current_or_exit_profit_pct": -6.0, "avoided_loss_pct": 2.5, "horizon_style": "day_trade", "market_regime": "neutral"}
                for i in range(8)
            ] + [
                {"symbol": "MSFT", "lifecycle_id": "life-lossless", "current_or_exit_profit_pct": 5.0, "avoided_loss_pct": 0.0, "horizon_style": "swing", "market_regime": "risk_on"}
            ])
            suite = ExitLearningExpansionSuiteV1(state_dir=state_dir)
            status = suite.status(force=True)
            evidence = status["avoidable_loss_evidence_v1"]
            self.assertEqual(evidence["avoidable_loss_known_rows"], 9)
            self.assertEqual(evidence["avoidable_loss_status"], "KNOWN")
            self.assertGreater(evidence["average_avoidable_loss_pct"], 2.0)
            self.assertFalse(evidence["behavior_safe_to_apply"])

    def test_missing_avoidable_loss_stays_unknown(self):
        with tempfile.TemporaryDirectory() as state_dir:
            self._seed_v2(state_dir, [
                {"symbol": "NVDA", "lifecycle_id": "life-1", "current_or_exit_profit_pct": -3.0}
            ])
            suite = ExitLearningExpansionSuiteV1(state_dir=state_dir)
            status = suite.status(force=True)
            evidence = status["avoidable_loss_evidence_v1"]
            self.assertEqual(evidence["avoidable_loss_status"], "UNKNOWN")
            self.assertIsNone(evidence["average_avoidable_loss_pct"])
            self.assertFalse(evidence["behavior_safe_to_apply"])

    def test_exit_behavior_unchanged_by_aggregation(self):
        with tempfile.TemporaryDirectory() as state_dir:
            self._seed_v2(state_dir, [
                {"symbol": "AAPL", "lifecycle_id": f"life-{i}", "current_or_exit_profit_pct": -4.0, "avoided_loss_pct": 1.0, "horizon_style": "day_trade", "market_regime": "neutral"}
                for i in range(6)
            ])
            suite = ExitLearningExpansionSuiteV1(state_dir=state_dir)
            status = suite.status(force=True)
            self.assertEqual(status["behavior_safe_to_apply"], False)
            self.assertEqual(status["live_trading_changed"], False)
            self.assertEqual(status["broker_behavior_changed"], False)
            self.assertEqual(status["forced_exits_enabled"], False)
            self.assertEqual(status["automatic_trailing_stops_enabled"], False)


if __name__ == "__main__":
    unittest.main()