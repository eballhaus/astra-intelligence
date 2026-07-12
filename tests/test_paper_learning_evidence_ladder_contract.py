import tempfile
import unittest

from engine.astra_pladeu_master_v1 import PaperLearningEvidenceLadderV1


class PaperLearningEvidenceLadderContractTests(unittest.TestCase):
    def test_reconstructed_and_broker_evidence_are_separated(self):
        statuses = {
            "historical_reconstruction": {
                "reconstruction": {
                    "evidence_class_counts": {
                        "HIGH_CONFIDENCE_RECONSTRUCTED": 3,
                        "BROKER_CONFIRMED_COMPLETE": 2,
                        "SHADOW_ONLY": 7,
                    },
                    "reconstructed_records": [
                        {"lane_id": "DAY", "asset_class": "equity", "evidence_class": "HIGH_CONFIDENCE_RECONSTRUCTED"},
                        {"lane_id": "DAY", "asset_class": "equity", "evidence_class": "BROKER_CONFIRMED_COMPLETE"},
                    ],
                }
            },
            "build_j": {"active_learning": {"evidence_count": 4}},
        }
        with tempfile.TemporaryDirectory() as state_dir:
            payload = PaperLearningEvidenceLadderV1(state_dir=state_dir).status(statuses=statuses, force=True)
        self.assertEqual(payload["official_performance_tier"], 6)
        self.assertEqual(payload["broker_truth_count"], 2)
        self.assertEqual(payload["reconstructed_context_count"], 3)
        self.assertTrue(payload["reconstructed_records_excluded_from_official_performance"])
