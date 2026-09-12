from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.astra_historical_evidence_production_v1 import produce_historical_evidence_v1


class HistoricalEvidenceProductionV1Tests(unittest.TestCase):
    def _db(self) -> tuple[Path, datetime]:
        root = Path(tempfile.mkdtemp())
        path = root / "archive.db"
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE historical_market_bars (symbol TEXT, asset_type TEXT, timeframe TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL, provider TEXT, ingested_at TEXT)"
        )
        start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
        rows = []
        for index in range(8):
            price = 100.0 + index
            rows.append(("AAPL", "stock", "1Min", int((start + timedelta(minutes=index)).timestamp()), price, price + 1.0, price - 0.5, price + 0.8, 1000 + index, "FMP_HIST", "2024-01-03T00:00:00Z"))
        daily_start = datetime(2024, 1, 2, tzinfo=UTC)
        for index in range(8):
            price = 200.0 + index
            rows.append(("RIOT", "stock", "1Day", int((daily_start + timedelta(days=index)).timestamp()), price, price + 2.0, price - 1.0, price + 1.0, 2000 + index, "FMP_HIST", "2024-01-03T00:00:00Z"))
        for index in range(8):
            price = 0.00001 + index * 0.000001
            rows.append(("SHIB/USD", "crypto", "1Min", int((start + timedelta(minutes=index)).timestamp()), price, price * 1.1, price * 0.9, price * 1.05, 3000 + index, "CRYPTO_HIST", "2024-01-03T00:00:00Z"))
        connection.executemany("INSERT INTO historical_market_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        connection.commit()
        connection.close()
        return path, start

    def test_day_produces_bounded_provenance_backed_replay_evidence(self):
        path, start = self._db()
        result = produce_historical_evidence_v1(path, lane="DAY", symbol="AAPL", history_start=start, history_end=start + timedelta(hours=1), forward_bars=3, max_matches=2)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(result["evidence_items"]), 2)
        item = result["evidence_items"][0]
        self.assertEqual(item["evidence_class"], "HISTORICAL_REPLAY")
        self.assertEqual(item["provider"], "FMP_HIST")
        self.assertEqual(item["provenance"]["table"], "historical_market_bars")
        self.assertTrue(item["provenance"]["forward_raw_keys"])
        self.assertFalse(item["broker_truth_eligible"])
        self.assertFalse(item["natural_truth_eligible"])
        self.assertFalse(item["learning_ack_eligible"])
        self.assertEqual(item["confidence_state"], "SINGLE_COMPARISON_NOT_PATTERN_PROOF")
        self.assertEqual(item["data_quality"]["data_quality_score"], 100.0)
        self.assertEqual(result["compression_handoff"]["persisted"], False)

    def test_scalp_uses_one_minute_and_reports_bounded_depth(self):
        path, start = self._db()
        result = produce_historical_evidence_v1(path, lane="SCALP", symbol="AAPL", history_start=start, history_end=start + timedelta(hours=1), forward_bars=3)
        self.assertEqual(result["timeframe"], "1Min")
        self.assertEqual(result["lane_contract"]["session_scope"], "same_session_archive_rows_only")
        self.assertLessEqual(result["retrieval"]["raw_rows_read"], 5000)

    def test_swing_uses_daily_history_without_intraday_requirement(self):
        path, start = self._db()
        result = produce_historical_evidence_v1(path, lane="SWING", symbol="RIOT", history_start=start, history_end=start + timedelta(days=10), forward_bars=3)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["timeframe"], "1Day")
        self.assertEqual(result["lane_contract"]["session_scope"], "multi_day_daily_bars")

    def test_crypto_is_asset_isolated_and_has_no_equity_session_assumption(self):
        path, start = self._db()
        result = produce_historical_evidence_v1(path, lane="CRYPTO", symbol="SHIB/USD", history_start=start, history_end=start + timedelta(hours=1), forward_bars=3)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["asset_type"], "crypto")
        self.assertEqual(result["lane_contract"]["session_scope"], "24_7_no_equity_session_filter")
        self.assertEqual(result["evidence_items"][0]["historical_comparison_symbol"], "SHIB/USD")

    def test_missing_depth_fails_gracefully_without_truth_or_archive_mutation(self):
        path, start = self._db()
        before = path.stat().st_mtime_ns
        result = produce_historical_evidence_v1(path, lane="SCALP", symbol="AAPL", history_start=start, history_end=start + timedelta(minutes=2), forward_bars=10)
        self.assertEqual(result["status"], "NO_MATCHES")
        self.assertEqual(result["evidence_items"], [])
        self.assertIsNone(result["compression_handoff"])
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertFalse(result["natural_truth_eligible"])
        self.assertFalse(result["lifecycle_completion_eligible"])

    def test_stale_or_empty_archive_is_explicitly_unavailable(self):
        root = Path(tempfile.mkdtemp())
        start = datetime(2024, 1, 2, tzinfo=UTC)
        result = produce_historical_evidence_v1(root / "missing.db", lane="DAY", symbol="AAPL", history_start=start, history_end=start + timedelta(days=1))
        self.assertEqual(result["status"], "ARCHIVE_UNAVAILABLE")
        self.assertFalse(result["decision_support"]["historical_evidence_consulted"] if "decision_support" in result else False)

    def test_compressed_handoff_is_advisory_and_preserves_ids(self):
        path, start = self._db()
        result = produce_historical_evidence_v1(path, lane="DAY", symbol="AAPL", history_start=start, history_end=start + timedelta(hours=1), forward_bars=3, max_matches=1)
        handoff = result["compression_handoff"]
        self.assertTrue(handoff["historical_replay_only"])
        self.assertFalse(handoff["broker_truth_eligible"])
        self.assertFalse(handoff["learning_ack_eligible"])
        self.assertEqual(handoff["packets"][0]["provenance_references"], [result["evidence_items"][0]["evidence_id"]])
        self.assertEqual(handoff["canonical_teacher_handoff"]["persisted"], False)


if __name__ == "__main__":
    unittest.main()
