from __future__ import annotations

from datetime import UTC, datetime
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
