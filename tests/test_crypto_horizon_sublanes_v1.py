from __future__ import annotations

import json
import unittest

from engine.astra_entry_lane_horizon_contract_v1 import build_entry_lane_horizon_contract_v1
from engine.astra_truth_learning_enrichment_v1 import build_pretrade_truth_context_v1
from engine.candidate_execution_integrity_v1 import derive_crypto_horizon_evidence_v1
from engine.paper_autopilot import PaperAutopilotEngine
from engine.trade_lifecycle_tracker import _normalize_record


def _candidate(**overrides):
    row = {
        "symbol": "ETH/USD",
        "asset_class": "crypto",
        "quote_timestamp": "2026-09-16T15:00:00Z",
        "confidence": 84.0,
        "crypto_risk_pct": 1.2,
        "completed_bar_return_pct": 0.4,
        "bar_evidence": {
            "resolution": "15Min",
            "completed_bar_count": 12,
            "rolling_completed_bar_volume": 1_000.0,
        },
        "market_regime": "neutral",
    }
    row.update(overrides)
    return row


class CryptoHorizonSublaneV1Tests(unittest.TestCase):
    def test_explicit_short_and_long_opportunities_classify_independently(self):
        fast = derive_crypto_horizon_evidence_v1(_candidate(expected_hold_minutes=60))
        swing = derive_crypto_horizon_evidence_v1(_candidate(expected_hold_minutes=2880))

        self.assertEqual(fast["crypto_horizon"], "CRYPTO_FAST")
        self.assertEqual(swing["crypto_horizon"], "CRYPTO_SWING")
        self.assertEqual(fast["crypto_horizon_status"], "RESOLVED")
        self.assertEqual(swing["crypto_horizon_status"], "RESOLVED")
        self.assertEqual(fast["crypto_horizon_source"], "expected_hold_minutes")
        self.assertEqual(swing["crypto_horizon_source"], "expected_hold_minutes")

    def test_explicit_window_and_archetype_are_supported(self):
        fast = derive_crypto_horizon_evidence_v1(_candidate(expected_hold_window="multi_hour"))
        swing = derive_crypto_horizon_evidence_v1(_candidate(strategy_archetype="persistent_trend"))

        self.assertEqual(fast["crypto_horizon"], "CRYPTO_FAST")
        self.assertEqual(swing["crypto_horizon"], "CRYPTO_SWING")

    def test_ambiguous_or_conflicting_horizon_fails_closed(self):
        ambiguous = derive_crypto_horizon_evidence_v1(_candidate(completed_bar_return_pct=0.0))
        conflicting = derive_crypto_horizon_evidence_v1(
            _candidate(crypto_horizon="CRYPTO_FAST", expected_hold_minutes=2880)
        )

        self.assertEqual(ambiguous["crypto_horizon"], "UNRESOLVED_CRYPTO_HORIZON")
        self.assertEqual(ambiguous["horizon_evidence_status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(conflicting["crypto_horizon"], "UNRESOLVED_CRYPTO_HORIZON")
        self.assertEqual(conflicting["crypto_horizon_status"], "CONFLICTING")
        self.assertIn("CRYPTO_HORIZON_UNRESOLVED", conflicting["horizon_evidence_missing"])

    def test_current_completed_bar_contract_defaults_to_fast_without_symbol_mapping(self):
        evidence = derive_crypto_horizon_evidence_v1(_candidate())
        self.assertEqual(evidence["crypto_horizon"], "CRYPTO_FAST")
        self.assertEqual(evidence["horizon"], "day_trade")
        self.assertEqual(evidence["crypto_horizon_provenance"], "crypto_15m_completed_bar_horizon_v1")

    def test_attribution_survives_entry_lifecycle_and_truth_context(self):
        evidence = derive_crypto_horizon_evidence_v1(
            _candidate(expected_hold_window="multi_day", source_snapshot_id="crypto:1")
        )
        entry = build_entry_lane_horizon_contract_v1({
            **_candidate(),
            "lane_id": "CRYPTO",
            "candidate_id": "candidate-1",
            "selection_id": "selection-1",
            "trade_horizon_style": "crypto_multi_horizon",
            "lane_assignment_source": "TEST",
            "horizon_source": "TEST",
            **evidence,
        })
        self.assertEqual(entry["crypto_horizon"], "CRYPTO_SWING")
        self.assertEqual(entry["crypto_horizon_provenance"], "expected_hold_window")

        materialized = PaperAutopilotEngine._materialize_open_position_entry_contract({
            "entry_metadata_json": json.dumps(entry),
            "crypto_horizon": "",
        })
        self.assertEqual(materialized["crypto_horizon"], "CRYPTO_SWING")

        lifecycle = _normalize_record({
            "symbol": "ETH/USD",
            "asset_type": "crypto",
            **entry,
            "lifecycle_id": "ETH/USD:2026-08-26T20:19:05",
        })
        self.assertEqual(lifecycle["lifecycle_id"], "ETH/USD:2026-08-26T20:19:05")
        self.assertEqual(lifecycle["crypto_horizon"], "CRYPTO_SWING")

        context = build_pretrade_truth_context_v1({}, entry)
        self.assertEqual(context["crypto_horizon"], "CRYPTO_SWING")
        self.assertEqual(context["crypto_horizon_source"], "expected_hold_window")

    def test_unknown_crypto_horizon_does_not_create_execution_horizon(self):
        evidence = derive_crypto_horizon_evidence_v1(_candidate(crypto_horizon="unknown"))
        self.assertEqual(evidence["horizon_evidence_status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(evidence["assigned_horizon"])
        self.assertNotIn("horizon", evidence)


if __name__ == "__main__":
    unittest.main()
