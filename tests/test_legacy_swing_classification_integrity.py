import unittest

from engine.astra_unified_position_lifecycle_v1 import classify_legacy_swing_lifecycle_v1


def _classify(**overrides):
    row = {"symbol": "FIX", "current_price": 10, "momentum_state": "HEALTHY", "thesis_state": "INTACT", "liquidity_state": "ADEQUATE"}
    row.update(overrides)
    evidence = {"evidence_rows": [{"source": "current_direct", "available": True, "consumed": True}]}
    return classify_legacy_swing_lifecycle_v1(row, evidence=evidence, confidence=float(row.pop("_confidence", 0.85)))


class LegacySwingClassificationIntegrityTests(unittest.TestCase):
    def test_differentiated_fixtures(self):
        cases = [
            ({}, "HOLD_AS_PLANNED"),
            ({"momentum_state": "WEAK"}, "HOLD_WITH_WATCH"),
            ({"exit_concern": True}, "EXIT_REVIEW"),
            ({"current_price": None}, "INSUFFICIENT_EVIDENCE"),
            ({"evidence_conflicting": True}, "CONFLICTING_EVIDENCE"),
            ({"_confidence": 0.4}, "LOW_CONFIDENCE"),
            ({"unrealized_return_pct": 5, "profit_giveback_pct": 3}, "PROTECT_PROFIT"),
            ({"momentum_state": "COLLAPSE"}, "REDUCE_RISK"),
            ({"thesis_state": "BROKEN", "direct_thesis_invalidation": True}, "THESIS_BROKEN"),
            ({"thesis_state": "BROKEN", "unrealized_return_pct": -5, "controlled_loss_preferred": True}, "CONTROLLED_LOSS_ACCEPTABLE"),
            ({"replacement_qualified": True, "opportunity_cost_state": "HIGH"}, "REPLACE_CANDIDATE"),
            ({"symbol": "", "current_price": None}, "INSUFFICIENT_EVIDENCE"),
        ]
        for values, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(_classify(**values)["classification"], expected)

    def test_missing_or_stale_never_defaults_to_hold(self):
        self.assertEqual(_classify(momentum_state="")["classification"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(_classify(quote_stale=True)["classification"], "INSUFFICIENT_EVIDENCE")

    def test_reason_and_components_are_explicit(self):
        result = _classify(momentum_state="WEAK")
        self.assertEqual(result["classification_reason"], "MONITORED_LIFECYCLE_RISK")
        self.assertIn("momentum", result["classification_components"])
        self.assertFalse(result["default_branch_used"])


if __name__ == "__main__":
    unittest.main()
