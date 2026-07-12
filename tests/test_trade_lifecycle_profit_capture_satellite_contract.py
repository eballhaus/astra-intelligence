import tempfile
import unittest

from engine.astra_pladeu_master_v1 import TradeLifecycleProfitCaptureSatelliteV1


class TradeLifecycleProfitCaptureSatelliteContractTests(unittest.TestCase):
    def test_satellite_is_a_facade_and_does_not_enable_learned_exits(self):
        with tempfile.TemporaryDirectory() as state_dir:
            payload = TradeLifecycleProfitCaptureSatelliteV1(state_dir=state_dir).status(
                statuses={"exit_readiness": {"status": "ok"}, "horizon_turnover": {"status": "ok"}}, force=True
            )
        self.assertEqual(payload["owners"]["lifecycle_truth"], "trade_lifecycle_tracker")
        self.assertFalse(payload["learned_exit_execution_enabled"])
        self.assertFalse(payload["behavior_safe_to_apply"])
