from __future__ import annotations

from datetime import UTC, datetime
import json
import tempfile
import unittest

from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.astra_evidence_accumulation_capacity_v1 import (
    build_capacity_snapshot,
    canonical_candidate_capacity_fact,
)
from engine.candidate_execution_integrity_v1 import (
    candidate_execution_integrity,
    derive_crypto_horizon_evidence_v1,
)
from engine.astra_entry_lane_horizon_contract_v1 import build_entry_lane_horizon_contract_v1
from engine.paper_autopilot import PaperAutopilotEngine


def _snapshot():
    return build_capacity_snapshot(
        broker_snapshot={
            "broker_reconciliation_active": True,
            "broker_positions_fetch_ok": True,
            "broker_state_age_seconds": 0,
        },
        account_snapshot={"buying_power": 50_000, "equity": 50_000, "cash": 50_000},
        open_positions=[],
        env={
            "ASTRA_CRYPTO_EVIDENCE_RESERVE_ENABLED": "1",
            "ASTRA_CRYPTO_EVIDENCE_CAPITAL_LIMIT": "1000",
            "ASTRA_CRYPTO_EVIDENCE_POSITION_LIMIT": "1",
        },
    )


def _candidate(**overrides):
    row = {
        "symbol": "BTC/USD", "asset_class": "crypto", "quote_timestamp": datetime.now(UTC).isoformat(),
        "quote_age_seconds": 1, "bid": 100.0, "ask": 100.1, "volume_24h": 1_000.0,
        "data_quality_score": 90.0, "confidence": 85.0, "crypto_risk_pct": 1.2,
        "completed_bar_return_pct": 0.4,
        "bar_evidence": {"resolution": "15Min", "completed_bar_count": 12, "rolling_completed_bar_volume": 1_000.0},
        "market_regime": "neutral", "notional": 25.0,
    }
    row.update(overrides)
    return row


class CryptoCapacityHorizonIntegrityRepairTests(unittest.TestCase):
    def test_horizon_requires_persisted_evidence_and_never_uses_default(self):
        missing = candidate_execution_integrity(
            _candidate(), supported_pairs={"BTC/USD"}, tradable_pairs={"BTC/USD"},
            lane_state="LANE_PAPER_ACTIVE_BOUNDED", paper_mode_verified=True,
            broker_reconciliation_ok=True, capacity_fact=canonical_candidate_capacity_fact(_snapshot(), lane_id="CRYPTO"),
        )
        self.assertTrue(missing["gate_status"]["horizon_assignment"].startswith("PENDING_HORIZON_EVIDENCE"))
        evidence = derive_crypto_horizon_evidence_v1(_candidate())
        self.assertEqual(evidence["assigned_horizon"], "day_trade")
        passed = candidate_execution_integrity(
            {**_candidate(), **evidence}, supported_pairs={"BTC/USD"}, tradable_pairs={"BTC/USD"},
            lane_state="LANE_PAPER_ACTIVE_BOUNDED", paper_mode_verified=True,
            broker_reconciliation_ok=True, capacity_fact=canonical_candidate_capacity_fact(_snapshot(), lane_id="CRYPTO"),
        )
        self.assertEqual(passed["gate_status"]["horizon_assignment"], "PASS")

    def test_horizon_envelope_preserves_canonical_aliases_and_provenance(self):
        evidence = derive_crypto_horizon_evidence_v1(_candidate(
            source_snapshot_id="crypto_rankings:123",
            ranking_run_id="crypto-worker:123",
            bar_timestamp="2026-08-28T15:00:00Z",
        ))
        self.assertEqual(evidence["horizon"], "day_trade")
        self.assertEqual(evidence["horizon_source"], evidence["horizon_provenance"])
        self.assertEqual(evidence["horizon_source_id"], "crypto_rankings:123")
        self.assertEqual(evidence["horizon_source_timestamp"], "2026-08-28T15:00:00Z")
        contract = build_entry_lane_horizon_contract_v1({
            **_candidate(), "lane_id": "CRYPTO", "candidate_id": "cand-1",
            **evidence,
        })
        self.assertEqual(contract["horizon"], "day_trade")
        self.assertEqual(contract["horizon_source_id"], "crypto_rankings:123")

    def test_missing_horizon_remains_unavailable_without_contract_defaults(self):
        evidence = derive_crypto_horizon_evidence_v1(_candidate(
            completed_bar_return_pct=0.0,
        ))
        self.assertEqual(evidence["horizon_evidence_status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(evidence["assigned_horizon"])
        self.assertNotIn("horizon", evidence)
        contract = build_entry_lane_horizon_contract_v1({
            "symbol": "BTC/USD", "asset_class": "crypto", "lane_id": "CRYPTO",
            "candidate_id": "cand-missing", **evidence,
        })
        self.assertEqual(contract["horizon"], "UNAVAILABLE")
        self.assertNotIn("horizon_source_id", contract)

    def test_materialized_position_reads_persisted_horizon_only(self):
        row = {
            "symbol": "BTC/USD", "horizon": "day_trade",
            "horizon_source": "crypto_15m_completed_bar_horizon_v1",
            "horizon_evidence_status": "PERSISTED_CANONICAL",
        }
        materialized = PaperAutopilotEngine._materialize_open_position_entry_contract({
            "paper_entry_horizon_style": "", "entry_metadata_json": json.dumps(row),
        })
        self.assertEqual(materialized["horizon"], "day_trade")
        self.assertEqual(materialized["horizon_source"], "crypto_15m_completed_bar_horizon_v1")
        missing = PaperAutopilotEngine._materialize_open_position_entry_contract({
            "paper_entry_horizon_style": "", "entry_metadata_json": json.dumps({"symbol": "ETH/USD"}),
        })
        self.assertNotIn("horizon", missing)

    def test_horizon_evidence_cannot_create_exit_or_strict_truth(self):
        evidence = derive_crypto_horizon_evidence_v1(_candidate())
        self.assertEqual(evidence["horizon_evidence_status"], "PERSISTED_CANONICAL")
        self.assertNotIn("exit_signal", evidence)
        self.assertNotIn("exit_order_id", evidence)
        self.assertNotIn("truth_id", evidence)

    def test_legacy_capacity_boolean_cannot_override_stale_canonical_fact(self):
        fact = canonical_candidate_capacity_fact({}, lane_id="CRYPTO")
        evidence = derive_crypto_horizon_evidence_v1(_candidate())
        payload = candidate_execution_integrity(
            {**_candidate(), **evidence}, supported_pairs={"BTC/USD"}, tradable_pairs={"BTC/USD"},
            lane_state="LANE_PAPER_ACTIVE_BOUNDED", paper_mode_verified=True, capacity_available=True,
            broker_reconciliation_ok=True, capacity_fact=fact,
        )
        self.assertEqual(payload["gate_status"]["capacity_concentration"], "PENDING_CANONICAL_CAPACITY_AUTHORITY")
        self.assertFalse(payload["execution_eligible"])

    def test_matrix_warning_is_promoted_to_a_scanner_root_cause(self):
        with tempfile.TemporaryDirectory() as directory:
            scanner = ContinuousSystemIntegrityScannerV1(directory)
            payload = scanner.run_if_due(
                worker_state={"active_worker_present": True, "process_role": "PAPER_AUTOPILOT_WORKER"},
                runtime_state={}, safety={},
                context={"multilane_completion_matrix": {"status": "WARNING", "lanes": {"CRYPTO": {"first_blocker": "horizon_assignment"}}}},
            )
        self.assertIn("MONITORING_COVERAGE_GAP", [row["category"] for row in payload["active_root_causes"]])


if __name__ == "__main__":
    unittest.main()
