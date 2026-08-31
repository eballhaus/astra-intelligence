"""Durable, idempotent learning acknowledgement for strict paper truths.

This is intentionally a narrow canonical consumer: it records only completed
broker-confirmed lifecycles and never makes a broker, provider, or policy call.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


class TradeIntelligenceEngine:
    def __init__(self, db_path: str = "state/ai_trading_memory.db", *args: Any, **kwargs: Any) -> None:
        self.db_path = str(db_path or "state/ai_trading_memory.db")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS trade_journal (
                trade_id TEXT PRIMARY KEY,
                lifecycle_id TEXT,
                candidate_id TEXT,
                symbol TEXT,
                asset_type TEXT,
                mode TEXT,
                lane_id TEXT,
                entry_timestamp TEXT,
                entry_price REAL,
                exit_timestamp TEXT,
                exit_price REAL,
                exit_reason TEXT,
                return_percent REAL,
                friction_adjusted_return REAL,
                trade_origin TEXT,
                risk_context_json TEXT
            )"""
        )
        columns = {str(item[1]) for item in conn.execute("PRAGMA table_info(trade_journal)").fetchall()}
        # Older journals predate durable lifecycle joins. Add only these
        # nullable provenance columns; this never changes historical rows.
        for name in (
            "lifecycle_id", "candidate_id", "lane_id", "strict_truth_stable_key",
            "learning_acknowledged_at", "learning_consumer", "learning_provenance",
        ):
            if name not in columns:
                conn.execute(f"ALTER TABLE trade_journal ADD COLUMN {name} TEXT")

    def record_trade(self, row: dict[str, Any]) -> dict[str, Any]:
        """Acknowledge one strict lifecycle using its immutable position id."""
        payload = dict(row or {})
        trade_id = str(payload.get("trade_id") or "").strip()
        if not trade_id:
            return {"ok": False, "reason": "STRICT_TRUTH_TRADE_ID_REQUIRED"}
        payload.setdefault("learning_acknowledged_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        payload.setdefault("learning_consumer", "TradeIntelligenceEngine.record_trade")
        payload.setdefault("learning_provenance", "broker_truth_records_v1 -> trade_journal")
        with self._connect() as conn:
            self._ensure_table(conn)
            columns = {str(item[1]) for item in conn.execute("PRAGMA table_info(trade_journal)").fetchall()}
            values: dict[str, Any] = {"trade_id": trade_id}
            for key, value in payload.items():
                if key not in columns or key == "trade_id":
                    continue
                values[key] = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
            names = list(values)
            placeholders = ",".join("?" for _ in names)
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO trade_journal ({','.join(names)}) VALUES ({placeholders})",
                [values[name] for name in names],
            )
            conn.commit()
        return {"ok": True, "acknowledged": True, "deduplicated": cursor.rowcount == 0, "trade_id": trade_id}

    def acknowledgements_for_truths(
        self,
        truth_records: list[dict[str, Any]] | None,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Read bounded authoritative acknowledgements for known strict truths.

        The journal is the consumer's durable idempotency boundary. This view
        does not mutate journal rows and never treats a lesson application as a
        prerequisite for acknowledging the already-consumed strict truth.
        """
        truths = [dict(row) for row in (truth_records or []) if isinstance(row, dict)]
        lifecycle_ids = list(dict.fromkeys(
            str(row.get("lifecycle_id") or "").strip()
            for row in truths
            if str(row.get("lifecycle_id") or "").strip()
        ))[: max(1, min(200, int(limit)))]
        if not lifecycle_ids:
            return []
        placeholders = ",".join("?" for _ in lifecycle_ids)
        try:
            with self._connect() as conn:
                # Add only nullable acknowledgment columns needed by the
                # current consumer contract. Existing journal rows remain
                # untouched and continue to prove consumption by identity.
                self._ensure_table(conn)
                rows = conn.execute(
                    f"""SELECT trade_id,lifecycle_id,candidate_id,symbol,asset_type,lane_id,
                              strict_truth_stable_key,learning_acknowledged_at,
                              learning_consumer,learning_provenance
                         FROM trade_journal
                        WHERE lifecycle_id IN ({placeholders})
                        ORDER BY rowid ASC
                        LIMIT ?""",
                    [*lifecycle_ids, max(1, min(200, int(limit)))],
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        by_lifecycle: dict[str, dict[str, Any]] = {}
        truth_by_lifecycle = {
            str(row.get("lifecycle_id") or "").strip(): row
            for row in truths
            if str(row.get("lifecycle_id") or "").strip()
        }
        for raw in rows:
            row = dict(raw)
            lifecycle_id = str(row.get("lifecycle_id") or "").strip()
            if not lifecycle_id or lifecycle_id in by_lifecycle:
                continue
            truth = truth_by_lifecycle.get(lifecycle_id, {})
            by_lifecycle[lifecycle_id] = {
                **row,
                "truth_id": str(truth.get("truth_id") or truth.get("stable_key") or "").strip(),
                "lane": str(row.get("lane_id") or truth.get("lane_id") or truth.get("lane") or "").upper(),
                "consumer": str(row.get("learning_consumer") or "TradeIntelligenceEngine.record_trade"),
                "consumption_result": "CONSUMED",
                "final_state": "CONSUMED",
                "source": "trade_journal",
                "provenance": str(row.get("learning_provenance") or "broker_truth_records_v1 -> trade_journal"),
            }
        return list(by_lifecycle.values())

    def compute_decision_feedback(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def compute_decision_feedback_segments(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def compute_paper_cohort_trends(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def diagnostics(self) -> dict[str, Any]:
        return {"enabled": True, "consumer": "strict_broker_truth_learning", "db_path": self.db_path}
