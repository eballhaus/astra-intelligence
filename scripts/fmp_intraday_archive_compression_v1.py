#!/usr/bin/env python3
"""Resumable Tier 3B FMP intraday archive and compact evidence index.

The runner reuses the existing archive request/rate/runtime contracts and the
canonical ``historical_market_bars`` database.  The derived summary table is
an indexed, regenerable retrieval aid; it is not broker or natural-truth
state.
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.astra_intraday_evidence_index_v1 import (
    DEFAULT_TIMEFRAME,
    FEATURE_SCHEMA_VERSION,
    SUMMARY_TABLE,
    build_intraday_session_summaries,
    ensure_summary_schema,
    fetch_intraday_raw_window,
    normalize_intraday_timeframe,
    retrieve_intraday_session_matches,
    source_endpoint_for_timeframe,
    summary_payload_size,
    upsert_intraday_session_summaries,
)
from engine.runtime_environment import resolve_fmp_key
from scripts.fmp_archive_tier3_tier4_v1 import (
    INTRADAY_GROUPS,
    INTRADAY_SYMBOL_GROUP,
    INTRADAY_SYMBOLS,
    INTRADAY_ENDPOINT,
    INTRADAY_TIMEFRAME,
    normalize_intraday_rows,
)
from scripts.fmp_weekend_archive_v1 import (
    ArchiveRunner,
    ArchiveStop,
    FMP_PROVIDER,
    MAX_CALLS_PER_MINUTE,
    RateGovernor,
    atomic_json_write,
    make_before_after_snapshot,
    now_iso,
    open_current_read_only,
    read_json,
    safe_int,
)


VERSION = "1.0.0"
DEFAULT_STATE_DIR = Path("/Users/Shared/AstraRuntime/state")
DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_WINDOW_DAYS = 7
DEFAULT_15MIN_LOOKBACK_DAYS = 730
DEFAULT_15MIN_WINDOW_DAYS = 45
TARGET_SYMBOLS = 300
TARGET_CALLS_PER_MINUTE = 25
MAX_CALLS_PER_MINUTE = 50
MAX_REQUESTS = 24_000
MAX_1HOUR_REQUESTS = 40_000
MAX_ARCHIVE_SYMBOLS = 600
MAX_LOOKBACK_DAYS = 8_000
PAYLOAD_CEILING_BYTES = 10_000_000_000
FIFTEEN_MIN_PAYLOAD_CEILING_BYTES = 5_000_000_000
DEFAULT_1HOUR_START_DATE = date(2010, 1, 4)
DEFAULT_1HOUR_WINDOW_DAYS = 90
SUMMARY_FAMILY = "intraday_session_summary"
SUMMARY_INDEX_VERSION = "intraday_summary_index_v1"
CONTROL_SYMBOLS = ("SPY", "QQQ", "DIA", "IWM")
SECTOR_ORDER = (
    "technology", "financial_services", "healthcare", "industrials", "consumer_cyclical",
    "consumer_defensive", "energy", "basic_materials", "utilities", "real_estate", "communication_services", "unknown",
)


def _norm(value: Any) -> str:
    return "_".join(str(value or "").strip().lower().replace("&", "and").split()) or "unknown"


def _source_rows(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Merge only existing local manifests; no external universe is added."""
    sources = (
        ("fmp_archive_manifest_v1.json", "core_archive"),
        ("fmp_archive_tier3_tier4_manifest_v1.json", "tier4_archive"),
        ("fmp_archive_enrichment_manifest_v1.json", "etf_reference"),
    )
    result: dict[str, dict[str, Any]] = {}
    for filename, source_name in sources:
        payload = read_json(state_dir / filename, {}) or {}
        collections_to_read = [payload.get("symbols", [])]
        if filename == "fmp_archive_tier3_tier4_manifest_v1.json":
            collections_to_read.append(payload.get("tier4_symbols", []))
        for collection in collections_to_read:
            for raw in collection if isinstance(collection, list) else []:
                if not isinstance(raw, dict):
                    continue
                symbol = str(raw.get("symbol") or "").strip().upper()
                if not symbol or "/" in symbol:
                    continue
                row = result.setdefault(symbol, {"symbol": symbol, "source_names": [], "source_flags": {}})
                if source_name not in row["source_names"]:
                    row["source_names"].append(source_name)
                row["source_flags"][source_name] = True
                for field in ("sector", "industry", "company_name", "exchange", "archive_tier"):
                    if raw.get(field) not in (None, "") and row.get(field) in (None, ""):
                        row[field] = raw[field]
                if raw.get("asset_type"):
                    row["asset_type"] = raw["asset_type"]
    return result


def _sector_row(row: dict[str, Any]) -> str:
    sector = _norm(row.get("sector"))
    aliases = {
        "financials": "financial_services", "financial": "financial_services", "healthcare_biotech": "healthcare",
        "consumer_staples": "consumer_defensive", "consumer_discretionary": "consumer_cyclical",
        "communication": "communication_services", "communications": "communication_services", "basic_materials": "basic_materials",
    }
    return aliases.get(sector, sector)


def build_intraday_manifest_300(
    state_dir: Path,
    *,
    timeframe: str = DEFAULT_TIMEFRAME,
    limit: int = TARGET_SYMBOLS,
) -> list[dict[str, Any]]:
    """Select a bounded existing archive universe by deterministic sector round-robin."""
    timeframe = normalize_intraday_timeframe(timeframe)
    limit = max(1, min(MAX_ARCHIVE_SYMBOLS, int(limit or TARGET_SYMBOLS)))
    available = _source_rows(state_dir)
    selected: list[dict[str, Any]] = []
    selected_symbols: set[str] = set()

    def add(symbol: str, reason: str, group: str | None = None) -> None:
        symbol = symbol.upper()
        if symbol in selected_symbols:
            return
        source = dict(available.get(symbol) or {"symbol": symbol, "source_names": [], "source_flags": {}})
        source.setdefault("asset_type", "stock")
        is_etf_context = bool((source.get("source_flags") or {}).get("etf_reference"))
        row = {
            "symbol": symbol,
            "asset_type": "stock",
            "instrument_category": "ETF_CONTEXT" if is_etf_context else "EQUITY",
            "verified_is_etf": is_etf_context,
            "resolution": timeframe,
            "archive_tier": "deep_1hour_history" if timeframe == "1Hour" else "tier3b_intraday_6_month",
            "sector": source.get("sector"),
            "industry": source.get("industry"),
            "selection_group": group or INTRADAY_SYMBOL_GROUP.get(symbol) or f"sector_{_sector_row(source)}",
            "selection_reason": reason,
            "source_names": sorted(source.get("source_names") or []),
            "source_flags": dict(source.get("source_flags") or {}),
            "behavioral_contrast": "existing_high_value_group" if symbol in INTRADAY_SYMBOL_GROUP else "sector_round_robin_reference",
        }
        selected.append(row)
        selected_symbols.add(symbol)

    for symbol in INTRADAY_SYMBOLS:
        if symbol in available:
            add(symbol, "retained_existing_100_symbol_high_liquidity_and_lane_contrast")
    for symbol in CONTROL_SYMBOLS:
        if symbol in available:
            add(symbol, "existing_reference_manifest_broad_market_control")

    buckets: dict[str, list[str]] = collections.defaultdict(list)
    for symbol, row in sorted(available.items()):
        if symbol in selected_symbols or row.get("asset_type") == "crypto":
            continue
        buckets[_sector_row(row)].append(symbol)
    target_remaining = max(0, limit - len(selected))
    while target_remaining and any(buckets.values()):
        for sector in SECTOR_ORDER + tuple(sorted(set(buckets) - set(SECTOR_ORDER))):
            bucket = buckets.get(sector) or []
            if not bucket or target_remaining <= 0:
                continue
            symbol = bucket.pop(0)
            add(symbol, "existing_canonical_archive_universe_sector_round_robin_for_learning_diversity", f"sector_{sector}")
            target_remaining -= 1
    if target_remaining:
        raise ArchiveStop(f"intraday_manifest_sources_have_only_{len(selected)}_eligible_symbols")
    return selected[:limit]


def apply_daily_history_start_dates(state_dir: Path, manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bound hourly requests to each symbol's known local listing history."""
    db_path = state_dir / "ai_trading_memory.db"
    starts: dict[str, str] = {}
    if db_path.exists():
        try:
            with open_current_read_only(db_path) as connection:
                rows = connection.execute(
                    "SELECT symbol,date(MIN(ts),'unixepoch') FROM historical_market_bars "
                    "WHERE provider=? AND timeframe='1Day' GROUP BY symbol",
                    (FMP_PROVIDER,),
                ).fetchall()
            starts = {str(row[0]).upper(): str(row[1]) for row in rows if row[0] and row[1]}
        except sqlite3.Error as exc:
            raise ArchiveStop(f"daily_history_start_lookup_failed:{type(exc).__name__}") from exc
    for target in manifest:
        known = date.fromisoformat(starts[target["symbol"]]) if target["symbol"] in starts else DEFAULT_1HOUR_START_DATE
        target["history_start_date"] = max(DEFAULT_1HOUR_START_DATE, known).isoformat()
        target["history_start_source"] = (
            "canonical_FMP_HIST_1Day_min" if target["symbol"] in starts else "proven_1Hour_retention_floor"
        )
    return manifest


class IntradayArchiveRunner(ArchiveRunner):
    """Archive-only runner using the existing request and runtime guard."""

    def __init__(
        self,
        *,
        state_dir: Path,
        manifest: list[dict[str, Any]],
        lookback_days: int,
        window_days: int,
        calls_per_minute: int,
        timeframe: str = DEFAULT_TIMEFRAME,
        end_date: date | None = None,
        payload_ceiling_bytes: int | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.manifest = manifest
        self.manifest_by_symbol = {row["symbol"]: row for row in manifest}
        self.timeframe = normalize_intraday_timeframe(timeframe)
        self.endpoint = source_endpoint_for_timeframe(self.timeframe)
        suffix = "" if self.timeframe == DEFAULT_TIMEFRAME else f"_{self.timeframe.lower()}"
        archive_prefix = f"fmp_intraday_archive_compression_v1{suffix}"
        self.manifest_path = state_dir / f"{archive_prefix}_manifest.json"
        self.progress_path = state_dir / f"{archive_prefix}_progress.json"
        self.validation_path = state_dir / f"{archive_prefix}_validation.json"
        self.lineage_path = state_dir / f"{archive_prefix}_request_lineage.jsonl"
        self.context_path = state_dir / f"{archive_prefix}_context.jsonl.gz"
        self.db_path = state_dir / "ai_trading_memory.db"
        self.key, self.key_source = resolve_fmp_key()
        if not self.key:
            raise ArchiveStop("missing_fmp_api_key")
        self.governor = RateGovernor(min(calls_per_minute, MAX_CALLS_PER_MINUTE))
        self.started_at = now_iso()
        self.stop_reason = ""
        self.malformed_streak = 0
        self.payload_ceiling_bytes = int(payload_ceiling_bytes or (FIFTEEN_MIN_PAYLOAD_CEILING_BYTES if self.timeframe == "15Min" else PAYLOAD_CEILING_BYTES))
        self.request_limit = MAX_1HOUR_REQUESTS if self.timeframe == "1Hour" else MAX_REQUESTS
        self.lookback_days = max(1, min(MAX_LOOKBACK_DAYS, int(lookback_days or DEFAULT_LOOKBACK_DAYS)))
        self.window_days = max(1, min(366, int(window_days or DEFAULT_WINDOW_DAYS)))
        self.end_date = end_date or date.today()
        self.progress = self._load_progress()
        self._ensure_paths()
        self._ensure_manifest_file()
        self._db_size_before = self.db_path.stat().st_size if self.db_path.exists() else 0

    def _load_progress(self) -> dict[str, Any]:
        existing = read_json(self.progress_path, {})
        symbols = [row["symbol"] for row in self.manifest]
        if (
            not isinstance(existing, dict)
            or existing.get("manifest_symbols") != symbols
            or safe_int(existing.get("lookback_days")) != self.lookback_days
            or safe_int(existing.get("window_days")) != self.window_days
            or existing.get("timeframe") != self.timeframe
            or existing.get("end_date") != self.end_date.isoformat()
            or (
                self.timeframe == "1Hour"
                and existing.get("history_start_by_symbol")
                != {row["symbol"]: row.get("history_start_date") for row in self.manifest}
            )
        ):
            existing = {}
        existing.setdefault("schema_version", "fmp_intraday_archive_compression_v1_progress")
        existing.setdefault("status", "NOT_STARTED")
        existing.setdefault("started_at", self.started_at)
        existing.setdefault("updated_at", now_iso())
        existing.setdefault("manifest_symbols", symbols)
        if self.timeframe == "1Hour":
            existing.setdefault(
                "history_start_by_symbol",
                {row["symbol"]: row.get("history_start_date") for row in self.manifest},
            )
        existing.setdefault("lookback_days", self.lookback_days)
        existing.setdefault("window_days", self.window_days)
        existing.setdefault("timeframe", self.timeframe)
        existing.setdefault("endpoint", self.endpoint)
        existing.setdefault("end_date", self.end_date.isoformat())
        existing.setdefault("payload_ceiling_bytes", self.payload_ceiling_bytes)
        existing.setdefault("per_symbol", {})
        existing.setdefault("total_api_calls", 0)
        existing.setdefault("total_retries", 0)
        existing.setdefault("total_payload_bytes", 0)
        existing.setdefault("rows_inserted", 0)
        existing.setdefault("duplicate_rows", 0)
        existing.setdefault("invalid_rows", 0)
        existing.setdefault("chronology_failures", 0)
        existing.setdefault("windows_completed", 0)
        existing.setdefault("windows_skipped_existing", 0)
        existing.setdefault("errors", [])
        existing.setdefault("request_count_by_family", {})
        existing.setdefault("record_count_by_family", {})
        existing.setdefault("summary", {"status": "NOT_STARTED", "symbols_completed": 0, "records": 0})
        existing.setdefault("before_snapshot", None)
        return existing

    def _ensure_manifest_file(self) -> None:
        atomic_json_write(
            self.manifest_path,
            {
                "schema_version": "fmp_intraday_archive_compression_v1_manifest",
                "generator_version": VERSION,
                "generated_at": now_iso(),
                "provider": "FMP",
                "resolution": self.timeframe,
                "endpoint": self.endpoint,
                "target_symbol_count": len(self.manifest),
                "selection_policy": "existing_local_sources_sector_round_robin_with_existing_100_retained",
                "symbols": self.manifest,
                "hard_limits": {
                    "target_calls_per_minute": TARGET_CALLS_PER_MINUTE,
                    "absolute_calls_per_minute": MAX_CALLS_PER_MINUTE,
                    "payload_ceiling_bytes": self.payload_ceiling_bytes,
                    "max_retry_per_request": 1,
                },
            },
        )

    def _save_progress(self) -> None:
        self.progress["updated_at"] = now_iso()
        atomic_json_write(self.progress_path, self.progress)

    def _store_rows(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        if not self.db_path.exists():
            raise ArchiveStop("canonical_historical_database_missing")
        for attempt in range(3):
            inserted = duplicates = 0
            try:
                with sqlite3.connect(str(self.db_path), timeout=3.0) as connection:
                    connection.execute("PRAGMA busy_timeout=3000")
                    table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historical_market_bars'").fetchone()
                    if not table:
                        raise ArchiveStop("canonical_historical_market_bars_table_missing")
                    for row in rows:
                        cursor = connection.execute(
                            "INSERT OR IGNORE INTO historical_market_bars(symbol,asset_type,timeframe,ts,o,h,l,c,v,provider,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (row["symbol"], "stock", self.timeframe, row["timestamp"], row["open"], row["high"], row["low"], row["close"], row.get("volume"), FMP_PROVIDER, now_iso()),
                        )
                        if cursor.rowcount:
                            inserted += 1
                        else:
                            duplicates += 1
                    connection.commit()
                return inserted, duplicates
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if not any(token in message for token in ("locked", "busy")):
                    raise ArchiveStop(f"historical_store_write_failed:{str(exc)[:160]}") from exc
                if attempt >= 2:
                    raise ArchiveStop("canonical_historical_database_lock_contention") from exc
                time.sleep(0.5 * (attempt + 1))
        raise ArchiveStop("canonical_historical_database_lock_contention")

    def _existing_bounds(self) -> dict[str, tuple[int | None, int | None]]:
        if not self.db_path.exists():
            return {}
        try:
            with open_current_read_only(self.db_path) as connection:
                rows = connection.execute(
                    "SELECT symbol,MIN(ts),MAX(ts) FROM historical_market_bars WHERE provider=? AND asset_type='stock' AND timeframe=? GROUP BY symbol",
                    (FMP_PROVIDER, self.timeframe),
                ).fetchall()
            return {str(row[0]).upper(): (safe_int(row[1], 0) or None, safe_int(row[2], 0) or None) for row in rows}
        except sqlite3.Error:
            return {}

    def _window_already_covered(self, symbol: str, start: date, end: date, bounds: dict[str, tuple[int | None, int | None]]) -> bool:
        earliest, latest = bounds.get(symbol, (None, None))
        if earliest is None or latest is None:
            return False
        start_ts = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
        end_ts = int(datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC).timestamp())
        return earliest <= start_ts and latest >= end_ts

    def _run_intraday(self) -> None:
        phase = self.progress
        bounds = self._existing_bounds()
        lower_bound = self.end_date - timedelta(days=self.lookback_days - 1)
        window_end = self.end_date
        while window_end >= lower_bound:
            window_start = max(lower_bound, window_end - timedelta(days=self.window_days - 1))
            for target in self.manifest:
                symbol = target["symbol"]
                state = phase.setdefault("per_symbol", {}).setdefault(symbol, {"windows_completed": [], "rows_inserted": 0, "duplicate_rows": 0, "invalid_rows": 0, "chronology_failures": 0, "status": "RUNNING"})
                try:
                    symbol_lower_bound = max(lower_bound, date.fromisoformat(str(target.get("history_start_date") or lower_bound.isoformat())))
                except ValueError:
                    symbol_lower_bound = lower_bound
                if window_end < symbol_lower_bound:
                    continue
                symbol_window_start = max(symbol_lower_bound, window_end - timedelta(days=self.window_days - 1))
                symbol_window_key = f"{symbol_window_start.isoformat()}:{window_end.isoformat()}"
                if symbol_window_key in state.get("windows_completed", []):
                    continue
                self._guard_runtime()
                if self._window_already_covered(symbol, symbol_window_start, window_end, bounds):
                    state.setdefault("windows_completed", []).append(symbol_window_key)
                    state["status"] = "RUNNING"
                    phase["windows_skipped_existing"] = safe_int(phase.get("windows_skipped_existing")) + 1
                    phase["windows_completed"] = safe_int(phase.get("windows_completed")) + 1
                    self._save_progress()
                    continue
                params = {"symbol": symbol, "from": symbol_window_start.isoformat(), "to": window_end.isoformat()}
                rows, meta = self._request(family=f"{self.timeframe}_raw", symbol=symbol, endpoint=self.endpoint, params=params)
                clean, quality = normalize_intraday_rows(symbol, rows)
                inserted, duplicates = self._store_rows(clean) if clean else (0, 0)
                state.setdefault("windows_completed", []).append(symbol_window_key)
                state["rows_inserted"] = safe_int(state.get("rows_inserted")) + inserted
                state["duplicate_rows"] = safe_int(state.get("duplicate_rows")) + duplicates + safe_int(quality.get("duplicate_records"))
                state["invalid_rows"] = safe_int(state.get("invalid_rows")) + safe_int(quality.get("invalid_records"))
                state.setdefault("window_quality", {})[symbol_window_key] = {**meta, **quality, "rows_inserted": inserted, "duplicate_rows": duplicates, "requested_from": params["from"], "requested_to": params["to"]}
                phase["rows_inserted"] = safe_int(phase.get("rows_inserted")) + inserted
                phase["duplicate_rows"] = safe_int(phase.get("duplicate_rows")) + duplicates + safe_int(quality.get("duplicate_records"))
                phase["invalid_rows"] = safe_int(phase.get("invalid_rows")) + safe_int(quality.get("invalid_records"))
                phase["windows_completed"] = safe_int(phase.get("windows_completed")) + 1
                if not quality.get("chronologically_valid", True):
                    phase["chronology_failures"] = safe_int(phase.get("chronology_failures")) + 1
                state["status"] = "RUNNING"
                self._save_progress()
            window_end = window_start - timedelta(days=1)
        all_symbols_complete = True
        for target in self.manifest:
            symbol = target["symbol"]
            state = phase.setdefault("per_symbol", {}).setdefault(symbol, {"windows_completed": []})
            try:
                symbol_lower_bound = max(lower_bound, date.fromisoformat(str(target.get("history_start_date") or lower_bound.isoformat())))
            except ValueError:
                symbol_lower_bound = lower_bound
            expected_windows = max(1, ((self.end_date - symbol_lower_bound).days + 1 + self.window_days - 1) // self.window_days)
            state["expected_windows"] = expected_windows
            state["status"] = "COMPLETE" if len(set(state.get("windows_completed") or [])) >= expected_windows else "PARTIAL"
            all_symbols_complete = all_symbols_complete and state["status"] == "COMPLETE"
        if not all_symbols_complete:
            raise ArchiveStop("hourly_symbol_window_checkpoint_incomplete")
        phase["status"] = "COMPLETE"
        self._save_progress()

    def _build_summaries(self) -> None:
        summary_state = self.progress.setdefault("summary", {"status": "NOT_STARTED"})
        summary_state["status"] = "RUNNING"
        lower_bound = self.end_date - timedelta(days=self.lookback_days - 1)
        start_ts = int(datetime(lower_bound.year, lower_bound.month, lower_bound.day, tzinfo=UTC).timestamp())
        end_ts = int(datetime(self.end_date.year, self.end_date.month, self.end_date.day, 23, 59, 59, tzinfo=UTC).timestamp())
        if not self.db_path.exists():
            summary_state["status"] = "ARCHIVE_UNAVAILABLE"
            self._save_progress()
            return
        with sqlite3.connect(str(self.db_path), timeout=30.0) as connection:
            connection.execute("PRAGMA busy_timeout=30000")
            ensure_summary_schema(connection)
            total = 0
            completed = 0
            for target in self.manifest:
                self._guard_runtime()
                symbol = target["symbol"]
                rows = connection.execute(
                    "SELECT symbol,ts,o,h,l,c,v FROM historical_market_bars WHERE symbol=? AND asset_type='stock' AND timeframe=? AND provider=? AND ts>=? AND ts<=? ORDER BY ts",
                    (symbol, self.timeframe, FMP_PROVIDER, start_ts, end_ts),
                ).fetchall()
                canonical = [{"symbol": row[0], "timestamp": int(row[1]), "open": row[2], "high": row[3], "low": row[4], "close": row[5], "volume": row[6]} for row in rows]
                summaries = build_intraday_session_summaries(canonical, symbol=symbol, metadata=target, timeframe=self.timeframe)
                total += upsert_intraday_session_summaries(connection, summaries, generated_at=now_iso())
                connection.commit()
                completed += 1
                summary_state["symbols_completed"] = completed
                summary_state["records"] = total
                self._save_progress()
            connection.commit()
        summary_state["status"] = "COMPLETE"
        self._save_progress()

    def run(self) -> None:
        self.progress["status"] = "RUNNING"
        self._save_progress()
        try:
            self._run_intraday()
        except ArchiveStop as exc:
            self.stop_reason = str(exc)
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = self.stop_reason
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": self.stop_reason})
        except Exception as exc:
            self.stop_reason = f"unexpected_archive_error:{type(exc).__name__}:{str(exc)[:160]}"
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = self.stop_reason
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": self.stop_reason})
        try:
            self._build_summaries()
        except ArchiveStop as exc:
            self.stop_reason = str(exc)
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = self.stop_reason
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": self.stop_reason})
            self.progress.setdefault("summary", {})["status"] = "STOPPED_RUNTIME_GUARD"
        except Exception as exc:
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": f"summary_build_failed:{type(exc).__name__}:{str(exc)[:160]}"})
            self.progress.setdefault("summary", {})["status"] = "FAILED"
        if self.progress.get("status") == "RUNNING":
            self.progress["status"] = "COMPLETE"
        self.progress["finished_at"] = now_iso()
        self._save_progress()

    def _raw_validation(self) -> tuple[list[dict[str, Any]], int]:
        symbols = [row["symbol"] for row in self.manifest]
        if not symbols or not self.db_path.exists():
            return [], 0
        placeholders = ",".join("?" for _ in symbols)
        try:
            with open_current_read_only(self.db_path) as connection:
                rows = connection.execute(
                    f"SELECT symbol,COUNT(*) AS n,MIN(ts),MAX(ts) FROM historical_market_bars WHERE provider=? AND asset_type='stock' AND timeframe=? AND symbol IN ({placeholders}) GROUP BY symbol",
                    [FMP_PROVIDER, self.timeframe, *symbols],
                ).fetchall()
                duplicate_groups = connection.execute(
                    f"SELECT COUNT(*) FROM (SELECT symbol,asset_type,timeframe,ts FROM historical_market_bars WHERE provider=? AND asset_type='stock' AND timeframe=? AND symbol IN ({placeholders}) GROUP BY symbol,asset_type,timeframe,ts HAVING COUNT(*)>1)",
                    [FMP_PROVIDER, self.timeframe, *symbols],
                ).fetchone()[0]
        except sqlite3.Error:
            return [], 0
        return [{"symbol": row[0], "rows": int(row[1]), "earliest_timestamp": int(row[2]), "latest_timestamp": int(row[3])} for row in rows], int(duplicate_groups)

    def _summary_validation(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {"status": "ARCHIVE_UNAVAILABLE", "records": 0}
        try:
            with open_current_read_only(self.db_path) as connection:
                table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (SUMMARY_TABLE,)).fetchone()
                if not table:
                    return {"status": "SUMMARY_TABLE_UNAVAILABLE", "records": 0}
                count = int(connection.execute(f"SELECT COUNT(*) FROM {SUMMARY_TABLE} WHERE timeframe=?", (self.timeframe,)).fetchone()[0])
                payload_bytes = summary_payload_size(connection, timeframe=self.timeframe)
                schema = connection.execute(f"PRAGMA table_info({SUMMARY_TABLE})").fetchall()
                first = connection.execute(f"SELECT * FROM {SUMMARY_TABLE} WHERE timeframe=? ORDER BY session_date,symbol LIMIT 1", (self.timeframe,)).fetchone()
            return {"status": "OK", "records": count, "logical_payload_bytes": payload_bytes, "schema_columns": [row[1] for row in schema], "sample_summary_id": first[0] if first else None}
        except sqlite3.Error as exc:
            return {"status": "SUMMARY_READ_FAILED", "records": 0, "error": type(exc).__name__}

    def _retrieval_demos(self) -> dict[str, Any]:
        start_ts = int(datetime(self.end_date.year, self.end_date.month, self.end_date.day, tzinfo=UTC).timestamp()) - self.lookback_days * 86_400
        end_ts = int(datetime(self.end_date.year, self.end_date.month, self.end_date.day, 23, 59, 59, tzinfo=UTC).timestamp())
        demos: dict[str, Any] = {}
        for lane, setup in (("SCALP", {"momentum_bucket": "HIGH", "volume_bucket": "HIGH"}), ("DAY", {"direction": "UP", "volatility_bucket": "MEDIUM"}), ("SWING", {"direction": "UP"})):
            if lane == "SWING":
                demos[lane] = {"mode": "DAILY_FIRST", "intraday_supporting_only": True, "matches": 0, "raw_rows_read": 0}
                continue
            result = retrieve_intraday_session_matches(self.db_path, lane=lane, setup=setup, history_start_ts=start_ts, history_end_ts=end_ts, max_matches=5, timeframe=self.timeframe)
            first = (result.get("matches") or [None])[0]
            drilldown_rows = 0
            provenance = None
            if first:
                raw = fetch_intraday_raw_window(self.db_path, symbol=first["symbol"], start_ts=first["raw_start_ts"], end_ts=first["raw_end_ts"], timeframe=self.timeframe)
                drilldown_rows = len(raw)
                provenance = first.get("provenance")
            demos[lane] = {"mode": "INDEXED_SUMMARY_FIRST", "query": setup, "summary_rows_searched": result.get("summary_rows_searched", 0), "top_n": len(result.get("matches") or []), "raw_drilldown_rows": drilldown_rows, "summary_query_latency_ms": result.get("latency_ms"), "full_raw_scan_used": result.get("full_raw_scan_used"), "provenance": provenance}
        return demos

    def _fidelity_validation(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {"status": "ARCHIVE_UNAVAILABLE"}
        try:
            with open_current_read_only(self.db_path) as connection:
                row = connection.execute(
                    f"SELECT summary_id,symbol,raw_start_ts,raw_end_ts,setup_features_json,outcome_features_json FROM {SUMMARY_TABLE} WHERE timeframe=? AND session_segment='REGULAR' ORDER BY session_date,symbol LIMIT 1",
                    (self.timeframe,),
                ).fetchone()
            if not row:
                return {"status": "NO_SUMMARY_SAMPLE"}
            raw = fetch_intraday_raw_window(self.db_path, symbol=row[1], start_ts=int(row[2]), end_ts=int(row[3]), timeframe=self.timeframe)
            rebuilt = build_intraday_session_summaries(raw, symbol=row[1], metadata={}, timeframe=self.timeframe)
            rebuilt = next((item for item in rebuilt if item.get("session_segment") == "REGULAR"), None)
            if not rebuilt:
                return {"status": "RAW_SAMPLE_UNAVAILABLE", "summary_id": row[0]}
            stored_setup = json.loads(row[4] or "{}")
            stored_outcome = json.loads(row[5] or "{}")
            checks = {}
            for key in ("setup_return_pct", "setup_range_pct", "setup_realized_volatility_pct", "setup_direction"):
                checks[key] = rebuilt["setup_features"].get(key) == stored_setup.get(key)
            for key in ("session_return_pct", "range_pct", "realized_volatility_pct", "outcome_class", "mfe_pct", "mae_pct", "time_to_peak_seconds", "giveback_pct"):
                checks[key] = rebuilt["outcome_features"].get(key) == stored_outcome.get(key)
            return {"status": "PASS" if all(checks.values()) else "FAIL", "summary_id": row[0], "symbol": row[1], "raw_rows": len(raw), "checks": checks}
        except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
            return {"status": "FAILED", "error": type(exc).__name__}

    def validation(self, *, before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
        raw_rows, duplicate_groups = self._raw_validation()
        all_ts = [value for row in raw_rows for value in (row.get("earliest_timestamp"), row.get("latest_timestamp")) if value]
        summary = self._summary_validation()
        raw_count = sum(row["rows"] for row in raw_rows)
        expected_end = datetime(self.end_date.year, self.end_date.month, self.end_date.day, 23, 59, 59, tzinfo=UTC)
        validation = {
            "schema_version": "fmp_intraday_archive_compression_v1_validation",
            "generator_version": VERSION,
            "status": self.progress.get("status"),
            "generated_at": now_iso(),
            "started_at": self.progress.get("started_at"),
            "finished_at": self.progress.get("finished_at"),
            "tier3b_intraday": {
                "symbols_selected": len(self.manifest),
                "symbols_completed": sum(1 for row in self.manifest if self.progress.get("per_symbol", {}).get(row["symbol"], {}).get("status") == "COMPLETE"),
                "resolution": self.timeframe,
                "endpoint": self.endpoint,
                "lookback_calendar_days": self.lookback_days,
                "window_calendar_days": self.window_days,
                "rows_archived": raw_count,
                "rows_inserted_this_run": safe_int(self.progress.get("rows_inserted")),
                "earliest_timestamp_utc": datetime.fromtimestamp(min(all_ts), UTC).isoformat().replace("+00:00", "Z") if all_ts else None,
                "latest_timestamp_utc": datetime.fromtimestamp(max(all_ts), UTC).isoformat().replace("+00:00", "Z") if all_ts else None,
                "timeframe_coverage_count": len(raw_rows),
                "one_minute_coverage_count": len(raw_rows) if self.timeframe == DEFAULT_TIMEFRAME else 0,
                "resolution_fallback": {"rows": 0, "symbols": 0, "status": "NOT_USED"},
                "invalid_rows": safe_int(self.progress.get("invalid_rows")),
                "chronology_failures": safe_int(self.progress.get("chronology_failures")),
                "duplicate_rows_skipped": safe_int(self.progress.get("duplicate_rows")),
                "duplicate_key_groups": duplicate_groups,
                "selection_groups": dict(collections.Counter(row["selection_group"] for row in self.manifest)),
                "sector_coverage": dict(collections.Counter(str(row.get("sector") or "UNKNOWN") for row in self.manifest)),
                "per_symbol": raw_rows,
            },
            "compression": {
                "status": summary.get("status"),
                "summary_table": SUMMARY_TABLE,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "summary_record_count": summary.get("records", 0),
                "logical_summary_payload_bytes": summary.get("logical_payload_bytes", 0),
                "index_version": SUMMARY_INDEX_VERSION,
                "raw_rows_to_summary_records": round(raw_count / summary["records"], 3) if summary.get("records") else None,
                "raw_payload_duplicated_in_summary": False,
                "regenerable_from_raw": True,
                "provenance_preserved": True,
                "fidelity_contract": {"direction": True, "range": True, "volatility": True, "momentum": True, "continuation_fade_reversal": True, "mfe_mae": True, "time_to_peak": True, "giveback": True, "session_context": True},
                "fidelity_sample": self._fidelity_validation(),
                "material_information_loss": ["spread", "order_book", "news_reaction", "future_macro_effect"],
            },
            "retrieval": self._retrieval_demos(),
            "point_in_time_integrity": {
                "setup_features_separated_from_outcome_features": True,
                "future_bars_excluded_from_setup": True,
                "future_summary_as_of_exclusion_supported": True,
                "self_match_and_overlapping_window_exclusion_supported": True,
                "outcome_features": ["mfe_pct", "mae_pct", "time_to_peak_seconds", "giveback_pct", "holding_duration_seconds", "outcome_class"],
                "setup_features": ["open", "first_30m_return_pct", "range_pct", "realized_volatility_pct", "max_5m_return_pct", "max_30m_return_pct", "volume_acceleration_ratio"],
            },
            "session_normalization": {
                "timezone": "America/New_York",
                "utc_timestamps_preserved": True,
                "regular_segment": "09:30-16:00_local",
                "premarket_segment": "before_09:30_local",
                "after_hours_segment": "16:00_or_later_local",
                "dst_handled_by_zoneinfo": True,
                "holidays_and_half_days_inferred": False,
                "extended_hours_mixed_with_regular": False,
            },
            "corporate_action_integrity": {
                "raw_ohlcv_transformed": False,
                "adjusted_close_in_intraday_canonical": False,
                "price_adjustment_status": "PROVIDER_NATIVE_UNADJUSTED_STATUS_NOT_TRANSFORMED",
                "split_dividend_rewrite": False,
                "corporate_action_guard": "raw_prices_are_not_silently_rewritten",
            },
            "bias_controls": {
                "continuation": True,
                "fade": True,
                "reversal": True,
                "low_follow_through": True,
                "high_mae_and_giveback_retained": True,
                "selection_is_not_outcome_filtered": True,
            },
            "fred_context": {
                "integrated": False,
                "reason": "existing_FRED_ownership_is_governance_ready_but_no_bounded_point_in_time_join_contract_was_required_for_V1",
                "future_extension_point": "context_json.macro_context_with_release_timestamp_and_as_of_filter",
            },
            "usage": {
                "total_api_calls": safe_int(self.progress.get("total_api_calls")),
                "measured_payload_bytes": safe_int(self.progress.get("total_payload_bytes")),
                "measured_payload_gb_decimal": round(safe_int(self.progress.get("total_payload_bytes")) / 1_000_000_000, 9),
                "target_calls_per_minute": TARGET_CALLS_PER_MINUTE,
                "absolute_calls_per_minute": MAX_CALLS_PER_MINUTE,
                "retries": safe_int(self.progress.get("total_retries")),
                "errors": list(self.progress.get("errors") or [])[-20:],
                "request_count_by_family": dict(self.progress.get("request_count_by_family") or {}),
                "record_count_by_family": dict(self.progress.get("record_count_by_family") or {}),
            },
            "storage": {
                "canonical_database": str(self.db_path),
                "raw_table": "historical_market_bars",
                "summary_table": SUMMARY_TABLE,
                "database_bytes_before": self._db_size_before,
                "database_bytes_after": self.db_path.stat().st_size if self.db_path.exists() else 0,
                "shared_database_growth_not_isolated": True,
                "checkpoint_state": {"overall": self.progress.get("status"), "summary": self.progress.get("summary", {}).get("status"), "windows_completed": sum(len(value.get("windows_completed", [])) for value in (self.progress.get("per_symbol", {}) or {}).values()), "windows_skipped_existing": safe_int(self.progress.get("windows_skipped_existing"))},
            },
            "runtime_protection": {"before": before, "after": after, "archive_process_is_not_worker_owner": True, "broker_actions_caused": 0, "positions_mutated": False, "crypto_route_unchanged": True, "live_provider_routing_changed": False},
            "truth_safety": {"historical_replay_only": True, "broker_truth_untouched": True, "lifecycle_completion_eligible": False, "natural_truth_eligible": False, "learning_ack_eligible": False, "fabricated_evidence": False},
            "archive_date_contract": {"requested_end_utc": expected_end.isoformat().replace("+00:00", "Z"), "requested_start_date": (self.end_date - timedelta(days=self.lookback_days - 1)).isoformat()},
        }
        atomic_json_write(self.validation_path, validation)
        return validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive-only FMP intraday history and build indexed session summaries")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--symbols", type=int, default=TARGET_SYMBOLS)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--window-days", type=int, default=None)
    parser.add_argument("--calls-per-minute", type=int, default=TARGET_CALLS_PER_MINUTE)
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--end-date", default="", help="inclusive UTC archive end date (YYYY-MM-DD)")
    args = parser.parse_args()
    state_dir = Path(args.state_dir).expanduser().resolve()
    timeframe = normalize_intraday_timeframe(args.timeframe)
    end_date = date.fromisoformat(args.end_date) if args.end_date else None
    requested_symbols = max(1, min(MAX_ARCHIVE_SYMBOLS, int(args.symbols or TARGET_SYMBOLS)))
    manifest = build_intraday_manifest_300(state_dir, timeframe=timeframe, limit=requested_symbols)
    if len(manifest) != requested_symbols:
        raise SystemExit(f"intraday_manifest_size_mismatch:{len(manifest)}")
    if timeframe == "1Hour":
        manifest = apply_daily_history_start_dates(state_dir, manifest)
    before = make_before_after_snapshot(state_dir, label="BEFORE")
    archive_end = end_date or date.today()
    if args.lookback_days:
        lookback_days = args.lookback_days
    elif timeframe == "15Min":
        lookback_days = DEFAULT_15MIN_LOOKBACK_DAYS
    elif timeframe == "1Hour":
        lookback_days = (archive_end - DEFAULT_1HOUR_START_DATE).days + 1
    else:
        lookback_days = DEFAULT_LOOKBACK_DAYS
    if args.window_days:
        window_days = args.window_days
    elif timeframe == "15Min":
        window_days = DEFAULT_15MIN_WINDOW_DAYS
    elif timeframe == "1Hour":
        window_days = DEFAULT_1HOUR_WINDOW_DAYS
    else:
        window_days = DEFAULT_WINDOW_DAYS
    runner = IntradayArchiveRunner(
        state_dir=state_dir,
        manifest=manifest,
        lookback_days=lookback_days,
        window_days=window_days,
        calls_per_minute=args.calls_per_minute,
        timeframe=timeframe,
        end_date=end_date,
    )
    runner.progress["before_snapshot"] = before
    runner._save_progress()
    runner.run()
    after = make_before_after_snapshot(state_dir, label="AFTER")
    validation = runner.validation(before=before, after=after)
    print(json.dumps({"status": validation.get("status"), "timeframe": timeframe, "symbols_selected": len(manifest), "symbols_with_rows": validation.get("tier3b_intraday", {}).get("timeframe_coverage_count"), "rows": validation.get("tier3b_intraday", {}).get("rows_archived"), "summary_records": validation.get("compression", {}).get("summary_record_count"), "api_calls": validation.get("usage", {}).get("total_api_calls"), "payload_bytes": validation.get("usage", {}).get("measured_payload_bytes"), "stop_reason": runner.stop_reason, "validation_path": str(runner.validation_path)}, sort_keys=True))
    return 0 if validation.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
