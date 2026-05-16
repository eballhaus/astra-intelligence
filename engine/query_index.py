"""SQLite Query Index V1.

Lightweight planning layer for fast metadata lookup. It reports schema/index
readiness without performing a data migration during status calls.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class SQLiteQueryIndex:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.db_path = os.path.join(self.state_dir, "astra_query_index.db")
        self.planned_tables = [
            "trade_events",
            "replay_scenario_metadata",
            "learning_rows_metadata",
            "symbol_metadata",
            "feature_metadata",
            "advanced_metric_snapshots",
            "cache_manifests",
        ]
        self.planned_indexes = [
            "idx_trade_events_symbol",
            "idx_trade_events_timestamp",
            "idx_replay_scenario_regime",
            "idx_learning_rows_setup",
            "idx_symbol_metadata_symbol",
            "idx_feature_metadata_data_type",
            "idx_cache_manifests_source",
        ]

    def _inspect_existing_db(self) -> tuple[list[str], list[str], int]:
        if not os.path.exists(self.db_path):
            return [], [], 0
        try:
            with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=1.0) as conn:
                tables = [row[0] for row in conn.execute("select name from sqlite_master where type='table' order by name")]
                indexes = [row[0] for row in conn.execute("select name from sqlite_master where type='index' order by name")]
                row_estimate = 0
                for table in tables[:20]:
                    try:
                        row_estimate += int(conn.execute(f"select count(*) from {table}").fetchone()[0])
                    except Exception:
                        continue
                return tables, indexes, row_estimate
        except Exception:
            return [], [], 0

    def status(self) -> dict[str, Any]:
        tables, indexes, row_estimate = self._inspect_existing_db()
        existing = os.path.exists(self.db_path)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "sqlite_query_index_planning_only" if not existing else "sqlite_query_index_existing_db_read_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "query_index_status_v1": True,
            "sqlite_enabled": True,
            "sqlite_status": "existing_read_only" if existing else "planned_not_created",
            "db_path": self.db_path,
            "tables_available": tables,
            "indexes_available": indexes,
            "planned_tables": self.planned_tables,
            "planned_indexes": self.planned_indexes,
            "indexed_rows_estimate": row_estimate,
            "query_speed_benefit_estimate": "5-20x for symbol/date/setup/regime metadata filters after index materialization",
            "migration_mode": "planning_only_no_destructive_migrations",
            "schema_create_safe_when_enabled": True,
            "confidence_score": 80 if not existing else 88,
            "next_recommended_action": "create_empty_schema_then_backfill_metadata_in_small_operator_approved_batches",
            "generated_at": _now_iso(),
        }
