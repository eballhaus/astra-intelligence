import unittest

from engine.astra_portfolio_capacity_release_review_v1 import (
    build_portfolio_release_review,
    classify_position,
    fallback_concentration_audit,
    reconstruct_position_lineage,
    replacement_analysis,
    validate_excursion_record,
)


class PositionLineageExcursionTests(unittest.TestCase):
    def test_exact_broker_order_lineage_wins(self):
        result = reconstruct_position_lineage(
            {"symbol": "NVDA", "broker_order_id": "order-1"},
            [{"symbol": "NVDA", "broker_order_id": "order-1", "recommendation_id": "rec-1"}],
        )
        self.assertEqual(result["reconstruction_confidence"], "BROKER_LINKED_EXACT")
        self.assertEqual(result["record"]["recommendation_id"], "rec-1")

    def test_client_order_and_timestamp_linkages_are_bounded(self):
        client = reconstruct_position_lineage(
            {"symbol": "AAPL", "client_order_id": "client-1"},
            [{"symbol": "AAPL", "client_order_id": "client-1"}],
        )
        stamp = reconstruct_position_lineage(
            {"symbol": "AAPL", "entry_timestamp": "2026-07-14T14:30:00Z"},
            [{"symbol": "AAPL", "timestamp_utc": "2026-07-14T14:33:00Z"}],
        )
        self.assertEqual(client["reconstruction_confidence"], "IDENTIFIER_LINKED_HIGH_CONFIDENCE")
        self.assertEqual(stamp["reconstruction_confidence"], "TIMESTAMP_LINKED_HIGH_CONFIDENCE")

    def test_ambiguous_or_missing_lineage_is_never_guessed(self):
        ambiguous = reconstruct_position_lineage(
            {"symbol": "AAPL", "broker_order_id": "same"},
            [{"broker_order_id": "same"}, {"broker_order_id": "same"}],
        )
        missing = reconstruct_position_lineage({"symbol": "AAPL"}, [])
        self.assertEqual(ambiguous["reconstruction_confidence"], "AMBIGUOUS_REJECTED")
        self.assertEqual(missing["reconstruction_confidence"], "NOT_RECOVERABLE")

    def test_valid_excursion_reconstructs_giveback_and_capture(self):
        result = validate_excursion_record(
            {
                "entry_price": 100,
                "current_price": 104,
                "max_favorable_excursion_pct": 10,
                "max_adverse_excursion_pct": -3,
                "profit_giveback_pct": 6,
                "profit_capture_ratio": 0.4,
                "lifecycle_id": "life-1",
            },
            entry_price=100,
            current_price=104,
        )
        self.assertEqual(result["status"], "BROKER_AND_MARKET_OBSERVED")
        self.assertEqual(result["giveback_pct"], 6.0)
        self.assertEqual(result["capture_ratio"], 0.4)

    def test_impossible_excursion_is_quarantined(self):
        result = validate_excursion_record(
            {"max_favorable_excursion_pct": 1, "max_adverse_excursion_pct": 2},
            entry_price=100,
            current_price=110,
        )
        self.assertEqual(result["status"], "QUARANTINED_IMPOSSIBLE_EXCURSION")
        self.assertIn("mfe_below_current_return", result["errors"])

    def test_replacement_requires_existing_eligible_candidate(self):
        none = replacement_analysis({"symbol": "AAPL", "return_per_day": -1}, [{"symbol": "MSFT", "confidence": 99}])
        available = replacement_analysis(
            {"symbol": "AAPL", "return_per_day": -1},
            [{"symbol": "MSFT", "qualification": "paper_ready_candidate", "confidence": 90, "expected_return_per_day": 2}],
        )
        self.assertEqual(none["replacement_state"], "NO_ELIGIBLE_REPLACEMENT")
        self.assertIn(available["replacement_state"], {"REPLACEMENT_ADVANTAGE_HIGH", "REPLACEMENT_ADVANTAGE_MODERATE"})

    def test_loss_alone_is_not_controlled_loss_or_exit(self):
        result = classify_position({"symbol": "AAPL", "avg_entry_price": 100, "current_price": 90, "market_value": 100})
        self.assertEqual(result["primary_state"], "WATCH")
        self.assertNotIn("CONTROLLED_LOSS_ACCEPTABLE", result["secondary_labels"])

    def test_profit_protection_requires_explicit_linked_trigger(self):
        result = classify_position(
            {
                "symbol": "AAPL", "avg_entry_price": 100, "current_price": 105,
                "market_value": 100, "profit_giveback_pct": 5, "profit_protection_trigger": True,
            }
        )
        self.assertEqual(result["primary_state"], "PROTECT_PROFIT")

    def test_thesis_broken_requires_explicit_condition(self):
        result = classify_position(
            {"symbol": "AAPL", "avg_entry_price": 100, "current_price": 95, "market_value": 100, "thesis_state": "THESIS_BROKEN"}
        )
        self.assertEqual(result["primary_state"], "THESIS_BROKEN")

    def test_fallback_concentration_and_dust_exclusion(self):
        review = build_portfolio_release_review([
            {"symbol": "AAPL", "avg_entry_price": 100, "current_price": 101, "market_value": 100},
            {"symbol": "MSFT", "avg_entry_price": 100, "current_price": 101, "market_value": 100},
            {"symbol": "PH", "avg_entry_price": 1, "current_price": 1, "market_value": 0},
        ])
        audit = fallback_concentration_audit(review["review_rows"])
        self.assertEqual(audit["meaningful_positions"], 2)
        self.assertTrue(audit["blanket_fallback_detected"])
        self.assertEqual(review["primary_state_counts"]["DUST_CLEANUP_REVIEW"], 1)

    def test_classifier_never_authorizes_broker_action(self):
        result = classify_position({"symbol": "AAPL", "avg_entry_price": 100, "current_price": 101, "market_value": 100})
        self.assertFalse(result["automatic_action_authorized"])


if __name__ == "__main__":
    unittest.main()
