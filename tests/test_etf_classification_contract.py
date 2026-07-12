import unittest

from engine.astra_trade_lane_registry_v1 import apply_trade_lane_contract


class EtfClassificationContractTests(unittest.TestCase):
    def test_known_etfs_are_equity_asset_class_with_etf_instrument_type(self):
        for symbol in ("XLB", "SPY", "QQQ", "IWM"):
            with self.subTest(symbol=symbol):
                row = apply_trade_lane_contract({"symbol": symbol, "paper_entry_horizon_style": "day_trade"})
                self.assertEqual(row["asset_class"], "equity")
                self.assertEqual(row["instrument_type"], "ETF")
                self.assertEqual(row["lane_id"], "DAY")

    def test_etf_remains_a_cohort_not_a_lane(self):
        row = apply_trade_lane_contract({"symbol": "XLB", "paper_entry_horizon_style": "swing_trade"})
        self.assertEqual(row["lane_id"], "SWING")
        self.assertEqual(row["strategy_cohort"], "ETF_SWING")


if __name__ == "__main__":
    unittest.main()
