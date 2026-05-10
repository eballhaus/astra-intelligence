from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


class PositionTracker:
    def __init__(self, db_path: str = "state/ai_trading_memory.db", *args, **kwargs):
        self.db_path = db_path
        self._open_table = "open_positions_v2"
        self._lifecycle_table = "lifecycle_tracking_v2"
        self._ensure_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._open_table} (
                    position_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    row_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._open_table}_symbol ON {self._open_table}(symbol)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._open_table}_asset ON {self._open_table}(asset_type)")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._lifecycle_table} (
                    lifecycle_key TEXT PRIMARY KEY,
                    position_id TEXT,
                    symbol TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    closed INTEGER NOT NULL DEFAULT 0,
                    row_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._lifecycle_table}_symbol ON {self._lifecycle_table}(symbol)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._lifecycle_table}_source ON {self._lifecycle_table}(source)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._lifecycle_table}_asset ON {self._lifecycle_table}(asset_type)")
            conn.commit()

    def _dump(self, row: dict[str, Any]) -> str:
        try:
            return json.dumps(dict(row or {}), separators=(",", ":"), ensure_ascii=True)
        except Exception:
            return "{}"

    def _load(self, blob: Any) -> dict[str, Any]:
        try:
            if isinstance(blob, str) and blob:
                parsed = json.loads(blob)
                if isinstance(parsed, dict):
                    return parsed
        except Exception:
            pass
        return {}

    def _normalize_asset(self, asset_type: Any) -> str:
        raw = str(asset_type or "stock").strip().lower()
        return "crypto" if raw == "crypto" else "stock"

    def _row_to_payload(self, row_obj: sqlite3.Row | None) -> dict[str, Any]:
        if row_obj is None:
            return {}
        if "row_json" in row_obj.keys():
            return self._load(row_obj["row_json"])
        # Legacy table fallback: rows are columnar, not JSON blobs.
        try:
            return dict(row_obj)
        except Exception:
            return {}

    def _lifecycle_key(self, row: dict[str, Any]) -> str:
        position_id = str(row.get("position_id") or "").strip()
        symbol = str(row.get("symbol") or "").strip().upper()
        asset = self._normalize_asset(row.get("asset_type") or "stock")
        source = str(row.get("source") or "auto_top_candidate_v1").strip().lower() or "auto_top_candidate_v1"
        if position_id:
            return f"pid:{position_id}|src:{source}"
        return f"sym:{symbol}|asset:{asset}|src:{source}"

    def open_position(self, symbol, asset_type="stock", entry_price=0.0, quantity=None, notes=None, snapshot_fields=None, mode="intraday", **kwargs):
        now = _now_iso()
        row = {
            "position_id": str(uuid.uuid4()),
            "symbol": str(symbol).upper(),
            "asset_type": self._normalize_asset(asset_type),
            "entry_price": float(entry_price or 0.0),
            "quantity": quantity,
            "notes": notes or "",
            "mode": mode or "intraday",
            "entry_timestamp": now,
            "last_update_ts": now,
        }
        if isinstance(snapshot_fields, dict):
            row.update({f"entry_{k}": v for k, v in snapshot_fields.items()})

        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._open_table}(position_id, symbol, asset_type, row_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (row["position_id"], row["symbol"], row["asset_type"], self._dump(row), now, now),
            )
            conn.commit()
        return {"ok": True, "position_id": row["position_id"], "opened": dict(row)}

    def close_position(self, identifier, exit_price=0.0, exit_timestamp=None, exit_reason_manual=None, **kwargs):
        probe = self._get_open_by_identifier(identifier)
        if probe is None:
            return {"ok": False, "error": "position_not_found"}

        closed = dict(probe)
        closed["exit_price"] = float(exit_price or 0.0)
        closed["exit_timestamp"] = exit_timestamp or _now_iso()
        closed["exit_reason_manual"] = exit_reason_manual or ""
        closed["last_update_ts"] = closed["exit_timestamp"]

        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self._open_table} WHERE position_id=?", (str(probe.get("position_id") or ""),))
            conn.commit()
        return {"ok": True, "closed": closed}

    def get_open_positions(self, asset_type=None, **kwargs):
        where = []
        params = []
        if asset_type:
            where.append("asset_type=?")
            params.append(self._normalize_asset(asset_type))
        query = f"SELECT row_json FROM {self._open_table}"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY updated_at DESC"
        with self._connect() as conn:
            try:
                rows = conn.execute(query, params).fetchall()
            except sqlite3.OperationalError:
                # Schema-compatibility fallback for legacy columnar tables.
                fallback_query = f"SELECT * FROM {self._open_table}"
                if where:
                    fallback_query += " WHERE " + " AND ".join(where)
                fallback_query += " ORDER BY updated_at DESC"
                rows = conn.execute(fallback_query, params).fetchall()
        return [self._row_to_payload(r) for r in rows]

    def update_position_snapshot(self, identifier=None, *args, **fields):
        probe = self._get_open_by_identifier(identifier)
        if probe is None:
            return {"ok": False, "error": "position_not_found"}

        payload: dict[str, Any] = {}
        if args and isinstance(args[0], dict):
            payload.update(dict(args[0]))
        payload.update(fields)
        if not payload:
            return {"ok": True, "position": dict(probe)}

        merged = dict(probe)
        merged.update(payload)
        merged["last_update_ts"] = _now_iso()
        pid = str(merged.get("position_id") or "")
        with self._connect() as conn:
            conn.execute(
                f"UPDATE {self._open_table} SET row_json=?, updated_at=? WHERE position_id=?",
                (self._dump(merged), merged["last_update_ts"], pid),
            )
            conn.commit()
        return {"ok": True, "position": dict(merged)}

    def _get_open_by_identifier(self, identifier=None, **kwargs):
        symbol_kw = str(kwargs.get("symbol") or "").strip().upper()
        ident = str(identifier or "").strip()
        ident_u = ident.upper()
        with self._connect() as conn:
            try:
                rows = conn.execute(f"SELECT row_json FROM {self._open_table} ORDER BY updated_at DESC").fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(f"SELECT * FROM {self._open_table} ORDER BY updated_at DESC").fetchall()
        for r in rows:
            row = self._row_to_payload(r)
            if not isinstance(row, dict) or not row:
                continue
            if symbol_kw and str(row.get("symbol") or "").upper() == symbol_kw:
                return row
            if ident and (str(row.get("position_id") or "") == ident or str(row.get("symbol") or "").upper() == ident_u):
                return row
        return None

    def upsert_lifecycle_tracking(self, **row):
        data = dict(row or {})
        if not str(data.get("symbol") or "").strip():
            return {"ok": False, "error": "symbol_required"}
        data["symbol"] = str(data.get("symbol") or "").strip().upper()
        data["asset_type"] = self._normalize_asset(data.get("asset_type") or "stock")
        data["source"] = str(data.get("source") or "auto_top_candidate_v1").strip().lower() or "auto_top_candidate_v1"
        data["status"] = str(data.get("status") or "tracked").strip().lower() or "tracked"
        now = _now_iso()

        key = self._lifecycle_key(data)
        existing = self._get_open_lifecycle_row(identifier=key, include_closed=True)
        if isinstance(existing, dict) and existing:
            merged = dict(existing)
            merged.update(data)
            merged.setdefault("created_at", str(existing.get("created_at") or now))
        else:
            merged = dict(data)
            merged.setdefault("created_at", now)
        merged["updated_at"] = now
        merged["closed"] = bool(merged.get("closed", False) or str(merged.get("status") or "") == "closed")

        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._lifecycle_table}(lifecycle_key, position_id, symbol, asset_type, source, status, closed, row_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lifecycle_key) DO UPDATE SET
                    position_id=excluded.position_id,
                    symbol=excluded.symbol,
                    asset_type=excluded.asset_type,
                    source=excluded.source,
                    status=excluded.status,
                    closed=excluded.closed,
                    row_json=excluded.row_json,
                    updated_at=excluded.updated_at
                """,
                (
                    key,
                    str(merged.get("position_id") or ""),
                    str(merged.get("symbol") or ""),
                    str(merged.get("asset_type") or "stock"),
                    str(merged.get("source") or "auto_top_candidate_v1"),
                    str(merged.get("status") or "tracked"),
                    1 if bool(merged.get("closed")) else 0,
                    self._dump(merged),
                    str(merged.get("created_at") or now),
                    now,
                ),
            )
            conn.commit()
        return {"ok": True, "row": dict(merged)}

    def update_lifecycle_tracking_snapshot(self, identifier=None, **fields):
        row = self._get_open_lifecycle_row(identifier=identifier, **fields)
        if row is None:
            return {"ok": False, "error": "lifecycle_row_not_found"}

        merged = dict(row)
        merged.update(fields)
        merged["asset_type"] = self._normalize_asset(merged.get("asset_type") or "stock")
        merged["source"] = str(merged.get("source") or "auto_top_candidate_v1").strip().lower() or "auto_top_candidate_v1"
        status = str(merged.get("status") or "tracked").strip().lower() or "tracked"
        merged["status"] = status
        merged["closed"] = bool(status == "closed" or merged.get("closed"))
        merged["updated_at"] = _now_iso()
        key = self._lifecycle_key(merged)

        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {self._lifecycle_table}(lifecycle_key, position_id, symbol, asset_type, source, status, closed, row_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lifecycle_key) DO UPDATE SET
                    position_id=excluded.position_id,
                    symbol=excluded.symbol,
                    asset_type=excluded.asset_type,
                    source=excluded.source,
                    status=excluded.status,
                    closed=excluded.closed,
                    row_json=excluded.row_json,
                    updated_at=excluded.updated_at
                """,
                (
                    key,
                    str(merged.get("position_id") or ""),
                    str(merged.get("symbol") or ""),
                    str(merged.get("asset_type") or "stock"),
                    str(merged.get("source") or "auto_top_candidate_v1"),
                    status,
                    1 if bool(merged.get("closed")) else 0,
                    self._dump(merged),
                    str(merged.get("created_at") or _now_iso()),
                    str(merged.get("updated_at") or _now_iso()),
                ),
            )
            conn.commit()
        return {"ok": True, "row": dict(merged)}

    def get_lifecycle_tracking(self, asset_type=None, source=None, include_closed=True, limit=400, **kwargs):
        where = []
        params = []
        if asset_type:
            where.append("asset_type=?")
            params.append(self._normalize_asset(asset_type))
        if source:
            where.append("source=?")
            params.append(str(source).strip().lower())
        if not bool(include_closed):
            where.append("closed=0")

        query = f"SELECT row_json FROM {self._lifecycle_table}"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(5000, int(limit or 400))))
        with self._connect() as conn:
            try:
                rows = conn.execute(query, params).fetchall()
            except sqlite3.OperationalError:
                # Schema-compatibility fallback for legacy lifecycle table layout.
                fallback_query = f"SELECT * FROM {self._lifecycle_table}"
                if where:
                    fallback_query += " WHERE " + " AND ".join(where)
                fallback_query += " ORDER BY updated_at DESC LIMIT ?"
                rows = conn.execute(fallback_query, params).fetchall()
        return [self._row_to_payload(r) for r in rows]

    def _get_open_lifecycle_row(self, identifier=None, **filters):
        include_closed = bool(filters.get("include_closed", False))
        ident = str(identifier or "").strip()
        symbol = str(filters.get("symbol") or "").strip().upper()
        source = str(filters.get("source") or "").strip().lower()
        asset_type = self._normalize_asset(filters.get("asset_type") or "stock") if filters.get("asset_type") else ""

        rows = self.get_lifecycle_tracking(
            asset_type=asset_type or None,
            source=source or None,
            include_closed=include_closed,
            limit=1000,
        )
        ident_u = ident.upper()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if ident:
                if (
                    str(row.get("position_id") or "") == ident
                    or str(row.get("symbol") or "").upper() == ident_u
                    or self._lifecycle_key(row) == ident
                ):
                    return row
            else:
                if symbol and str(row.get("symbol") or "").upper() != symbol:
                    continue
                if source and str(row.get("source") or "").strip().lower() != source:
                    continue
                if asset_type and str(row.get("asset_type") or "").strip().lower() != asset_type:
                    continue
                return row
        return None
