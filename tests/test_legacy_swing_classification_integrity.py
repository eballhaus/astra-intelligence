import unittest

from engine.astra_unified_position_lifecycle_v1 import build_legacy_swing_required_evidence_v1, classify_legacy_swing_lifecycle_v1


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
            ({"momentum_state": "COLLAPSE", "thesis_state": "DETERIORATING"}, "REDUCE_RISK"),
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

    def test_reduce_risk_requires_current_risk_evidence_not_missing_or_liquidity_alone(self):
        self.assertEqual(_classify(liquidity_state="POOR")["classification"], "HOLD_WITH_WATCH")
        self.assertEqual(_classify(liquidity_state="POOR", momentum_state="NEGATIVE")["classification"], "REDUCE_RISK")
        self.assertEqual(_classify(liquidity_state="", momentum_state="") ["classification"], "INSUFFICIENT_EVIDENCE")

    def test_reason_and_components_are_explicit(self):
        result = _classify(momentum_state="WEAK")
        self.assertEqual(result["classification_reason"], "MONITORED_LIFECYCLE_RISK")
        self.assertIn("momentum", result["classification_components"])
        self.assertFalse(result["default_branch_used"])

    def test_required_evidence_is_current_or_explicitly_unavailable(self):
        baseline = {"baseline_id": "baseline", "activation_price": 10}
        missing = build_legacy_swing_required_evidence_v1({"symbol": "FIX", "current_price": 10}, baseline)
        self.assertEqual(missing["MOMENTUM"]["status"], "UNAVAILABLE")
        self.assertEqual(missing["THESIS_STATE"]["thesis_state"], "UNKNOWN")
        self.assertEqual(missing["LIQUIDITY"]["status"], "UNAVAILABLE")
        current = build_legacy_swing_required_evidence_v1({"symbol": "FIX", "current_price": 11, "recent_price_path": [10, 11], "thesis_state": "INTACT", "bid": 10.9, "ask": 11.0, "tradable": True}, baseline)
        self.assertEqual(current["MOMENTUM"]["status"], "CURRENT")
        self.assertEqual(current["THESIS_STATE"]["status"], "CURRENT")
        self.assertEqual(current["LIQUIDITY"]["liquidity_state"], "ACCEPTABLE")


if __name__ == "__main__":
    unittest.main()
