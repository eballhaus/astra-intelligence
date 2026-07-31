from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from engine.astra_canonical_truth_registry_v1 import canonical_fact_registry_v1, fact_envelope_v1
from engine.astra_truth_arbitration_v1 import TruthContradictionRegistryV1, arbitrate_truth_claims_v1, cortex_truth_summary_v1, read_canonical_open_crypto_positions


class CanonicalTruthGovernanceCortexTests(unittest.TestCase):
    def _db(self) -> tuple[tempfile.TemporaryDirectory, str]:
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        path = os.path.join(temp.name, "paper.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE paper_positions (position_id TEXT, symbol TEXT, asset_type TEXT, status TEXT, quantity REAL, broker_linked TEXT)")
        conn.executemany("INSERT INTO paper_positions VALUES (?,?,?,?,?,?)", [
            ("closed-crypto", "BTC/USD", "crypto", "CLOSED", 0, "FALSE"), ("open-equity", "AAPL", "stock", "OPEN", 1, "TRUE"),
            ("reconstructed", "ETH/USD", "crypto", "REJECTED", 0, "FALSE"),
        ])
        conn.commit(); conn.close()
        return temp, path

    def test_canonical_reader_excludes_historical_and_reconstructed_rows(self):
        _, path = self._db()
        self.assertEqual(read_canonical_open_crypto_positions(path), [])

    def test_canonical_value_beats_broad_adapter_claim(self):
        claims = [fact_envelope_v1("LOCAL_OPEN_CRYPTO_POSITION_COUNT", 0), {
            "fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT", "value": 670,
            "claimed_scope": "all crypto rows", "source_owner": "PAPER_AUTOPILOT.paper_positions",
            "source_type": "adapter", "canonical": False,
        }]
        payload = arbitrate_truth_claims_v1(claims)
        self.assertEqual(payload["critical_facts"]["LOCAL_OPEN_CRYPTO_POSITION_COUNT"]["value"], 0)
        self.assertEqual(payload["contradictions"][0]["contradiction_type"], "NONCANONICAL_SOURCE_OVERRIDE")
        self.assertTrue(payload["contradictions"][0]["fail_closed_state"])

    def test_matching_canonical_counts_have_no_contradiction(self):
        payload = arbitrate_truth_claims_v1([
            fact_envelope_v1("LOCAL_OPEN_CRYPTO_POSITION_COUNT", 0),
            fact_envelope_v1("BROKER_OPEN_CRYPTO_POSITION_COUNT", 0),
        ])
        self.assertEqual(payload["contradictions"], [])

    def test_canonical_reader_counts_only_open_crypto_rows(self):
        _, path = self._db()
        conn = sqlite3.connect(path)
        conn.execute("INSERT INTO paper_positions VALUES (?,?,?,?,?,?)", ("open-crypto", "BTC/USD", "crypto", "OPEN", 1, "TRUE"))
        conn.commit(); conn.close()
        rows = read_canonical_open_crypto_positions(path)
        self.assertEqual([row["position_id"] for row in rows], ["open-crypto"])

    def test_fact_envelope_has_required_canonical_provenance(self):
        fact = fact_envelope_v1("LOCAL_OPEN_CRYPTO_POSITION_COUNT", 0)
        self.assertTrue(fact["canonical"])
        self.assertEqual(fact["source_store"], "PaperAutopilotEngine.db_path.paper_positions")
        self.assertEqual(fact["scope"], "OPEN + asset_type=crypto + canonical SQLite")

    def test_scope_mismatch_is_not_numeric_reconciliation(self):
        payload = arbitrate_truth_claims_v1([fact_envelope_v1("LOCAL_OPEN_CRYPTO_POSITION_COUNT", 0), {
            "fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT", "value": 0, "claimed_scope": "all historical crypto lifecycle rows",
            "source_owner": "lifecycle adapter", "source_type": "diagnostic", "canonical": False,
        }])
        self.assertEqual(payload["contradictions"][0]["contradiction_type"], "SCOPE_MISMATCH")

    def test_registry_requires_sustained_consistency_and_marks_recurrence(self):
        with tempfile.TemporaryDirectory() as root:
            registry = TruthContradictionRegistryV1(root)
            contradiction = arbitrate_truth_claims_v1([fact_envelope_v1("LOCAL_OPEN_CRYPTO_POSITION_COUNT", 0), {
                "fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT", "value": 1, "claimed_scope": "OPEN + asset_type=crypto + canonical SQLite",
                "source_owner": "bad adapter", "source_type": "adapter", "canonical": False,
            }])["contradictions"]
            first = registry.observe(contradiction, verification_window=2)["issues"][0]
            second = registry.observe(contradiction, verification_window=2)["issues"][0]
            self.assertEqual(first["contradiction_id"], second["contradiction_id"])
            self.assertEqual(second["occurrence_count"], 2)
            self.assertEqual(registry.observe([], verification_window=2)["issues"][0]["state"], "VERIFYING")
            self.assertEqual(registry.observe([], verification_window=2)["issues"][0]["state"], "RESOLVED")
            self.assertEqual(registry.observe(contradiction, verification_window=2)["issues"][0]["state"], "RECURRENT")

    def test_cortex_explains_rejected_claim_without_truth_promotion(self):
        arbitration = arbitrate_truth_claims_v1([fact_envelope_v1("LOCAL_OPEN_CRYPTO_POSITION_COUNT", 0), {
            "fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT", "value": 670, "claimed_scope": "all crypto rows",
            "source_owner": "adapter", "source_type": "adapter", "canonical": False,
        }])
        cortex = cortex_truth_summary_v1(arbitration)
        self.assertFalse(cortex["truth_promotion_allowed"])
        self.assertTrue(cortex["human_review_required"])

    def test_registry_declares_unique_canonical_owners(self):
        registry = canonical_fact_registry_v1()
        self.assertIn("LOCAL_OPEN_CRYPTO_POSITION_COUNT", registry)
        self.assertEqual(
            registry["LOCAL_OPEN_CRYPTO_POSITION_COUNT"]["canonical_store"],
            "PaperAutopilotEngine.db_path.paper_positions",
        )
        self.assertIn("paper_positions", registry["LOCAL_OPEN_CRYPTO_POSITION_COUNT"]["canonical_store"])


if __name__ == "__main__":
    unittest.main()
