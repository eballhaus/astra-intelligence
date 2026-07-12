import tempfile
import unittest

from engine.astra_historical_lifecycle_reconstruction_v1 import AstraHistoricalLifecycleReconstructionV1
from engine.astra_pladeu_master_v1 import PaperLearningEvidenceLadderV1


class BrokerTruthReconciliationContractTests(unittest.TestCase):
    def test_authoritative_count_is_separate_from_reconstruction_count(self):
        with tempfile.TemporaryDirectory() as state_dir:
            statuses = {
                "authoritative_broker_truth": {
                    "broker_confirmed_complete_records": 5,
                    "truth_registry_path": "state/broker_truth_records_v1.json",
                },
                "pladeu_reconstruction_sources": {
                    "candidate_decisions": [{"candidate_id": "c-1", "symbol": "NVDA"}],
                },
            }
            reconstruction = AstraHistoricalLifecycleReconstructionV1(state_dir=state_dir).status(statuses=statuses, force=True)
            details = reconstruction["reconstruction"]
            ladder = PaperLearningEvidenceLadderV1(state_dir=state_dir).status(
                statuses={"historical_reconstruction": reconstruction}, force=True
            )
        self.assertEqual(reconstruction["authoritative_broker_confirmed_complete_count"], 5)
        self.assertEqual(reconstruction["newly_reconstructed_complete_count"], 0)
        self.assertEqual(details["broker_confirmed_complete_count"], 0)
        self.assertEqual(ladder["broker_truth_count"], 5)
        self.assertTrue(reconstruction["evidence_separation"]["reconstructed_records_never_promoted_to_broker_truth"])

    def test_missing_authoritative_owner_does_not_inflate_truth(self):
        with tempfile.TemporaryDirectory() as state_dir:
            reconstruction = AstraHistoricalLifecycleReconstructionV1(state_dir=state_dir).status(
                statuses={"pladeu_reconstruction_sources": {}}, force=True
            )
        self.assertEqual(reconstruction["authoritative_broker_confirmed_complete_count"], 0)
        self.assertEqual(reconstruction["authoritative_truth_source"], "state/broker_truth_records_v1.json")


if __name__ == "__main__":
    unittest.main()
