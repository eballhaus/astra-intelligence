import unittest

from engine.astra_multilane_operational_completion_v1 import build_multilane_operational_status


class CryptoOperationalContractTests(unittest.TestCase):
    def test_crypto_shadow_only_is_honest_and_not_equity_session_gated(self):
        payload = build_multilane_operational_status(
            candidates=[{"symbol": "BTC/USD", "asset_class": "crypto", "quote_age_seconds": 1}],
            open_positions=[], broker_truth_records=[], source_metadata={"candidate_freshness_status": "CURRENT"},
            crypto_lane={"paper_crypto_enabled": False, "mode": "separate_crypto_shadow_learning_no_trading", "capital_configured": False},
        )
        self.assertEqual(payload["lanes"]["crypto"]["operational_status"], "SHADOW_ONLY")
        self.assertEqual(payload["lanes"]["crypto"]["capital_book_id"], "paper_crypto_separate")
        self.assertEqual(payload["provider_calls_used"], 0)


if __name__ == "__main__":
    unittest.main()
