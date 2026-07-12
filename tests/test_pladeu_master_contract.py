import tempfile
import unittest

from engine.astra_pladeu_master_v1 import (
    DayLaneDiversityGovernorV1,
    PaperLearningEvidenceLadderV1,
    PladeuMasterValidationV1,
    TradeLifecycleProfitCaptureSatelliteV1,
)
from engine.astra_trade_lane_registry_v1 import AstraTradeLaneRegistryV1
from engine.astra_historical_lifecycle_reconstruction_v1 import AstraHistoricalLifecycleReconstructionV1


class PladeuMasterContractTests(unittest.TestCase):
    def test_master_passes_with_deferred_evidence_when_wiring_and_safety_hold(self):
        with tempfile.TemporaryDirectory() as state_dir:
            statuses = {"pladeu_candidate_rows": [], "pladeu_open_positions": []}
            statuses["trade_lane_registry"] = AstraTradeLaneRegistryV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["historical_reconstruction"] = AstraHistoricalLifecycleReconstructionV1(state_dir=state_dir).status(
                statuses={**statuses, "pladeu_reconstruction_sources": {}}, force=True
            )
            statuses["evidence_ladder"] = PaperLearningEvidenceLadderV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["lifecycle_satellite"] = TradeLifecycleProfitCaptureSatelliteV1(state_dir=state_dir).status(statuses=statuses, force=True)
            statuses["day_lane_governor"] = DayLaneDiversityGovernorV1(state_dir=state_dir).status(statuses=statuses, force=True)
            payload = PladeuMasterValidationV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(payload["status"], "ASTRA_PLADEU_MASTER_PASS_WITH_DEFERRED_EVIDENCE")
        self.assertEqual(payload["failed_checks"], [])
        self.assertFalse(payload["behavior_safe_to_apply"])
