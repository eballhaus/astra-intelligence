"""Tests for false crypto OPEN migration."""
from __future__ import annotations

import os
import tempfile
import unittest

import sqlite3

from engine.astra_crypto_false_open_migration_v1 import migrate_false_crypto_open


class CryptoFalseOpenMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self._create_schema()

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass
        for ext in ("", "-wal", "-shm"):
            try:
                os.unlink(self.db_path + ext)
            except OSError:
                pass

    def _create_schema(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""CREATE TABLE paper_positions (
            position_id TEXT, symbol TEXT, asset_type TEXT, status TEXT,
            entry_price REAL, entry_price_verified INTEGER DEFAULT 0,
            entry_price_provisional INTEGER DEFAULT 0,
            entry_fill_id TEXT, entry_order_id TEXT,
            reconciliation_reason TEXT, prior_status TEXT,
            lifecycle_notes TEXT, source_candidate_id TEXT,
            lane_id TEXT, position_owner TEXT, quantity REAL DEFAULT 0,
            entry_price_source TEXT, source_bucket TEXT
        )""")
        conn.commit()
        conn.close()

    def _insert(self, **overrides):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        row = {
            "position_id": "pos-1", "symbol": "ETH/USD", "asset_type": "crypto",
            "status": "OPEN", "entry_price": 2000.0, "entry_price_verified": 0,
            "entry_fill_id": "", "entry_order_id": "",
            "reconciliation_reason": "SIMULATED_OPEN_NO_BROKER_LINKAGE",
            "lane_id": "CRYPTO", "position_owner": "CRYPTO", "quantity": 1.0,
        }
        row.update(overrides)
        cols = "position_id,symbol,asset_type,status,entry_price,entry_price_verified,entry_price_provisional,entry_fill_id,entry_order_id,reconciliation_reason,prior_status,lifecycle_notes,source_candidate_id,lane_id,position_owner,quantity,entry_price_source,source_bucket"
        cur.execute(f"INSERT INTO paper_positions ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            row["position_id"], row["symbol"], row["asset_type"], row["status"],
            row["entry_price"], row["entry_price_verified"], 0,
            row["entry_fill_id"], row["entry_order_id"],
            row["reconciliation_reason"], None,
            None, None, row["lane_id"], row["position_owner"],
            row["quantity"], None, None,
        ))
        conn.commit()
        conn.close()

    def test_migration_marks_eligible_simulated(self):
        self._insert()
        result = migrate_false_crypto_open(self.db_path, apply=True)
        self.assertGreater(result["eligible_pre_migration"], 0)
        self.assertEqual(result["migrated_this_run"], result["eligible_pre_migration"])
        self.assertEqual(result["false_crypto_open_count"], 0)
        self.assertEqual(result["remaining_eligible"], 0)

    def test_migration_is_idempotent(self):
        self._insert()
        result1 = migrate_false_crypto_open(self.db_path, apply=True)
        self.assertEqual(result1["migrated_this_run"], 1)
        result2 = migrate_false_crypto_open(self.db_path, apply=True)
        self.assertEqual(result2["migrated_this_run"], 0)
        self.assertEqual(result2["remaining_eligible"], 0)
        self.assertEqual(result2["false_crypto_open_count"], 0)

    def test_does_not_touch_legitimate_open(self):
        self._insert(status="OPEN", entry_fill_id="fill-1", entry_price_verified=1,
                      reconciliation_reason=None)
        result = migrate_false_crypto_open(self.db_path, apply=True)
        self.assertEqual(result["eligible_pre_migration"], 0)
        self.assertEqual(result["migrated_this_run"], 0)
        # The legitimate record remains OPEN (it was not migrated)
        self.assertEqual(result["false_crypto_open_count"], 1)

    def test_does_not_touch_non_crypto(self):
        self._insert(asset_type="stock")
        result = migrate_false_crypto_open(self.db_path, apply=True)
        self.assertEqual(result["migrated_this_run"], 0)

    def test_preserves_original_status(self):
        self._insert()
        migrate_false_crypto_open(self.db_path, apply=True)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT status, prior_status FROM paper_positions")
        row = cur.fetchone()
        self.assertEqual(row[0], "SIMULATED")
        self.assertEqual(row[1], "OPEN")
        conn.close()

    def test_dry_run_does_not_modify(self):
        self._insert()
        result = migrate_false_crypto_open(self.db_path, apply=False)
        self.assertEqual(result["eligible_pre_migration"], 1)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT status FROM paper_positions")
        row = cur.fetchone()
        self.assertEqual(row[0], "OPEN")
        conn.close()
