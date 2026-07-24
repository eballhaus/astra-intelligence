from __future__ import annotations

import tempfile
import unittest

from engine.astra_position_evidence_completeness_v1 import (
    build_position_evidence_completeness_v1,
    load_position_evidence_completeness_v1,
    save_position_evidence_completeness_v1,
)
from engine.astra_unified_position_advisory_v1 import (
    build_unified_position_advisory_v1,
    load_unified_position_advisory_v1,
    save_unified_position_advisory_v1,
)


class PositionEvidenceAndAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.positions = {"AAA": {"symbol": "AAA", "unrealized_plpc": -0.01}, "BBB": {"symbol": "BBB", "unrealized_plpc": -0.02}}
        self.recovery = {"positions": [
            {"symbol": "AAA", "metadata_generation": "LEGACY", "lane_status": "UNAVAILABLE", "horizon_status": "UNAVAILABLE"},
            {"symbol": "BBB", "metadata_generation": "V1_MANDATORY", "lane_status": "RESOLVED", "horizon_status": "RESOLVED"},
        ]}

    def test_every_broker_position_has_one_exact_evidence_row(self):
        evidence = build_position_evidence_completeness_v1(self.positions, self.recovery)
        self.assertEqual(evidence["positions_represented"], 2)
        rows = {row["symbol"]: row for row in evidence["positions"]}
        self.assertEqual(rows["AAA"]["first_causal_blocker"], "OPEN_POSITION_EVIDENCE_REGISTRATION_MISSING")
        self.assertEqual(rows["BBB"]["legacy_status"], "V1_MANDATORY")

    def test_current_quote_and_bars_are_assigned_by_symbol_not_shared(self):
        market = {"id-a": {
            "LATEST_QUOTE": {"symbol": "AAA", "response_state": "SUCCESS", "freshness_state": "CURRENT", "quote_timestamp": "2999-01-01T00:00:00Z", "bid": 10, "ask": 11},
            "HISTORICAL_BARS": {"symbol": "AAA", "response_state": "SUCCESS", "freshness_state": "CURRENT", "last_bar_at": "2999-01-01T00:00:00Z", "bars": [{"close": 10, "volume": 1}, {"close": 11, "volume": 2}]},
        }}
        evidence = build_position_evidence_completeness_v1(self.positions, self.recovery, market_evidence=market)
        rows = {row["symbol"]: row for row in evidence["positions"]}
        self.assertEqual(rows["AAA"]["momentum_status"], "IMPROVING")
        self.assertEqual(rows["BBB"]["quote_status"], "MISSING")

    def test_advisory_has_one_row_per_broker_position_and_never_executes(self):
        evidence = build_position_evidence_completeness_v1(self.positions, self.recovery)
        triage = {"positions": [{"symbol": "AAA", "recommendation": "WATCH", "confidence": "LOW", "first_causal_blocker": "FMP_CONTEXT_UNAVAILABLE", "advisory_only": True}]}
        advisory = build_unified_position_advisory_v1(self.positions, evidence=evidence, triage=triage)
        self.assertEqual(advisory["advisory_count"], 2)
        self.assertEqual(advisory["silent_drop_count"], 0)
        self.assertTrue(all(row["execution_authority"] == "DISABLED" for row in advisory["positions"]))

    def test_evidence_and_advisory_persistence_are_bounded(self):
        evidence = build_position_evidence_completeness_v1(self.positions, self.recovery)
        advisory = build_unified_position_advisory_v1(self.positions, evidence=evidence, triage={})
        with tempfile.TemporaryDirectory() as directory:
            save_position_evidence_completeness_v1(evidence, directory)
            save_unified_position_advisory_v1(advisory, directory)
            self.assertEqual(load_position_evidence_completeness_v1(directory)["positions_represented"], 2)
            self.assertEqual(load_unified_position_advisory_v1(directory)["advisory_count"], 2)


if __name__ == "__main__":
    unittest.main()
