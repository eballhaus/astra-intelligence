import tempfile
import unittest

from engine.astra_historical_lifecycle_reconstruction_v1 import AstraHistoricalLifecycleReconstructionV1


class DayLaneBrokerTruthCompletionContractTests(unittest.TestCase):
    def test_reconstruction_cannot_create_authoritative_day_truth(self):
        with tempfile.TemporaryDirectory() as state_dir:
            payload = AstraHistoricalLifecycleReconstructionV1(state_dir=state_dir).status(
                statuses={
                    "authoritative_broker_truth": {"broker_confirmed_complete_records": 5},
                    "pladeu_reconstruction_sources": {
                        "trade_lifecycle": [{"trade_id": "t1", "symbol": "NVDA", "lane_id": "DAY", "realized_pnl": 1.0}],
                    },
                }, force=True,
            )
        self.assertEqual(payload["authoritative_broker_confirmed_complete_count"], 5)
        self.assertNotEqual(payload["newly_reconstructed_complete_count"], payload["authoritative_broker_confirmed_complete_count"])
        self.assertTrue(payload["evidence_separation"]["reconstructed_records_never_promoted_to_broker_truth"])


if __name__ == "__main__":
    unittest.main()
