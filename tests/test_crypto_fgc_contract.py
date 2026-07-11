import ast
import pathlib
import unittest

from engine.candidate_execution_integrity_v1 import normalize_crypto_pair_strict


ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "server_extend.py"


class CryptoFGCContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SERVER.read_text(encoding="utf-8")
        ast.parse(cls.source)

    def test_readiness_route_and_builder_exist(self):
        self.assertIn("_crypto_paper_execution_readiness_v1_payload", self.source)
        self.assertIn('/api/crypto_paper_execution_readiness_v1', self.source)

    def test_readiness_is_fail_closed_and_diagnostic_only(self):
        self.assertIn('"CRYPTO_PAPER_READY_NO_ELIGIBLE_TRADE"', self.source)
        self.assertIn('"no_order_submitted": True', self.source)
        self.assertIn('"broker_read_calls_used": 0', self.source)
        self.assertIn('"automatic_promotions_enabled": False', self.source)

    def test_strict_pair_normalization_preserves_asset_class_boundary(self):
        valid = normalize_crypto_pair_strict("btc-usd", asset_class="crypto")
        self.assertEqual(valid["normalized_symbol"], "BTC/USD")
        self.assertFalse(normalize_crypto_pair_strict("BTC/USD", asset_class="equity")["ok"])
        self.assertFalse(normalize_crypto_pair_strict("BTC", asset_class="crypto")["ok"])


if __name__ == "__main__":
    unittest.main()
