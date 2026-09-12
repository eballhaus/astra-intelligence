#!/usr/bin/env python3
"""Bounded FMP intraday and selective-universe archive extension.

This is archive-only tooling.  It reuses the existing FMP archive request,
runtime guard, rate governor, historical table, and context sidecar.  It does
not import execution, lifecycle, truth, learning, or provider-routing owners.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.runtime_environment import resolve_fmp_key
from scripts.fmp_weekend_archive_v1 import (
    ArchiveRunner,
    ArchiveStop,
    FMP_PROVIDER,
    HISTORY_ENDPOINT,
    MAX_CALLS_PER_MINUTE,
    MAX_HISTORY_BATCHES_PER_SYMBOL,
    MAX_PAYLOAD_BYTES,
    MAX_REQUESTS,
    RateGovernor,
    atomic_json_write,
    make_before_after_snapshot,
    normalize_symbol,
    now_iso,
    open_current_read_only,
    parse_date,
    read_json,
    safe_float,
    safe_int,
)


VERSION = "1.0.0"
DEFAULT_STATE_DIR = Path("/Users/Shared/AstraRuntime/state")
TARGET_CALLS_PER_MINUTE = 25
TIER3_PAYLOAD_CEILING_BYTES = 10_000_000_000
TIER4_PAYLOAD_CEILING_BYTES = 5_000_000_000
INTRADAY_LOOKBACK_CALENDAR_DAYS = 30
INTRADAY_WINDOW_CALENDAR_DAYS = 3
INTRADAY_ENDPOINT = "/stable/historical-chart/1min"
INTRADAY_TIMEFRAME = "1Min"
INTRADAY_FAMILY = "tier3_intraday_1min"
TIER4_FAMILY_PREFIX = "tier4_"
TIER3_MAX_SYMBOLS = 100
TIER4_MAX_SYMBOLS = 300
NY_TZ = ZoneInfo("America/New_York")


INTRADAY_GROUPS: dict[str, tuple[str, ...]] = {
    "technology_semiconductors": (
        "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "ORCL", "CRM", "ADBE", "CSCO", "INTC", "QCOM",
        "TXN", "MU", "AMAT", "LRCX", "KLAC", "IBM", "NOW", "PANW", "CRWD", "PLTR", "TSM",
    ),
    "communication_media": ("GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ", "SPOT"),
    "consumer_discretionary": ("AMZN", "TSLA", "HD", "LOW", "MCD", "NKE", "SBUX", "TJX", "UBER", "BKNG"),
    "consumer_staples": ("WMT", "COST", "PG", "KO", "PEP", "MDLZ", "MO"),
    "financials": ("JPM", "BAC", "WFC", "GS", "MS", "C", "AFL", "SCHW", "COF", "AXP", "V", "MA"),
    "healthcare_biotech": ("JNJ", "UNH", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "ISRG", "AMGN", "GILD", "MRNA", "BMY"),
    "industrials": ("CAT", "DE", "GE", "HON", "UPS", "LMT", "RTX", "BA", "NOC", "ETN"),
    "energy_materials": ("XOM", "CVX", "COP", "SLB", "OXY", "EOG", "NEM", "FCX"),
    "utilities_real_estate": ("NEE", "DUK", "SO", "CCI"),
    "high_beta_momentum": ("MSTR", "SMCI", "ARM", "COIN", "HOOD", "BX"),
}
INTRADAY_SYMBOL_GROUP = {symbol: group for group, symbols in INTRADAY_GROUPS.items() for symbol in symbols}
INTRADAY_SYMBOLS = tuple(symbol for symbols in INTRADAY_GROUPS.values() for symbol in symbols)


def build_intraday_manifest(state_dir: Path) -> list[dict[str, Any]]:
    """Return the fixed 100-symbol comparison set with local-source proof."""
    core_manifest = read_json(state_dir / "fmp_archive_manifest_v1.json", {})
    core_symbols = {normalize_symbol(row.get("symbol")) for row in core_manifest.get("symbols", []) if isinstance(row, dict)}
    broad = {normalize_symbol(symbol) for symbol in (read_json(state_dir / "broad_universe_intake_promotion_v1.json", {}) or {}).get("symbols", [])}
    rows = []
    for symbol in INTRADAY_SYMBOLS:
        source_flags = {
            "existing_core_archive": symbol in core_symbols,
            "existing_canonical_liquid_universe": symbol in broad,
        }
        rows.append(
            {
                "symbol": symbol,
                "asset_type": "stock",
                "resolution": INTRADAY_TIMEFRAME,
                "archive_tier": "tier3_intraday",
                "selection_group": INTRADAY_SYMBOL_GROUP[symbol],
                "selection_reason": "high_liquidity_sector_volatility_and_regime_contrast_from_existing_universe",
                "source_flags": source_flags,
            }
        )
    return rows


def build_tier4_manifest(state_dir: Path, limit: int = TIER4_MAX_SYMBOLS) -> list[dict[str, Any]]:
    """Select the unarchived portion of the existing liquid canonical universe."""
    broad_payload = read_json(state_dir / "broad_universe_intake_promotion_v1.json", {}) or {}
    broad_symbols = sorted({normalize_symbol(symbol) for symbol in broad_payload.get("symbols", []) if normalize_symbol(symbol)})
    core_payload = read_json(state_dir / "fmp_archive_manifest_v1.json", {}) or {}
    core_symbols = {normalize_symbol(row.get("symbol")) for row in core_payload.get("symbols", []) if isinstance(row, dict)}
    etf_payload = read_json(state_dir / "fmp_archive_enrichment_manifest_v1.json", {}) or {}
    etf_symbols = {normalize_symbol(row.get("symbol")) for row in etf_payload.get("symbols", []) if isinstance(row, dict)}
    candidates = [symbol for symbol in broad_symbols if symbol not in core_symbols and symbol not in etf_symbols and "/" not in symbol]
    candidates = candidates[: max(0, min(TIER4_MAX_SYMBOLS, int(limit or TIER4_MAX_SYMBOLS)))]
    return [
        {
            "symbol": symbol,
            "asset_type": "stock",
            "archive_tier": "tier4_selective_expansion",
            "selection_reason": "existing_canonical_liquid_universe_outside_core_and_etf_archives",
            "source_artifact": "broad_universe_intake_promotion_v1",
            "liquidity_filter": broad_payload.get("liquid_filter", {}),
            "status": "PENDING",
        }
        for symbol in candidates
    ]


def parse_intraday_timestamp(value: Any) -> tuple[int | None, str]:
    """Convert provider time to canonical UTC seconds without losing raw text."""
    raw = str(value or "").strip()
    if not raw:
        return None, ""
    try:
        if raw.isdigit():
            numeric = int(raw)
            if numeric > 10_000_000_000:
                numeric //= 1000
            return numeric, raw
        text = raw.replace("Z", "+00:00").replace(" ", "T", 1)
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=NY_TZ)
        return int(parsed.astimezone(UTC).timestamp()), raw
    except (TypeError, ValueError, OverflowError):
        return None, raw


def normalize_intraday_rows(symbol: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    duplicate_count = 0
    invalid_count = 0
    useful_fields: set[str] = set()
    for raw in rows:
        useful_fields.update(str(key) for key in raw.keys())
        returned_symbol = normalize_symbol(raw.get("symbol"))
        if returned_symbol and returned_symbol != symbol:
            invalid_count += 1
            continue
        timestamp, native_timestamp = parse_intraday_timestamp(raw.get("date") or raw.get("datetime") or raw.get("timestamp"))
        open_value = safe_float(raw.get("open"))
        high_value = safe_float(raw.get("high"))
        low_value = safe_float(raw.get("low"))
        close_value = safe_float(raw.get("close"))
        volume_value = safe_float(raw.get("volume"))
        if timestamp is None or any(value is None or value <= 0 for value in (open_value, high_value, low_value, close_value)):
            invalid_count += 1
            continue
        if volume_value is not None and volume_value < 0:
            invalid_count += 1
            continue
        if high_value < max(open_value, close_value) or low_value > min(open_value, close_value) or high_value < low_value:
            invalid_count += 1
            continue
        if timestamp in seen:
            duplicate_count += 1
            continue
        seen.add(timestamp)
        normalized.append(
            {
                "symbol": symbol,
                "timestamp": timestamp,
                "provider_native_timestamp": native_timestamp,
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": close_value,
                "volume": volume_value,
            }
        )
    normalized.sort(key=lambda row: row["timestamp"])
    timestamps = [row["timestamp"] for row in normalized]
    return normalized, {
        "records_received": len(rows),
        "records_valid": len(normalized),
        "unique_records": len(normalized),
        "duplicate_records": duplicate_count,
        "invalid_records": invalid_count,
        "earliest_timestamp": timestamps[0] if timestamps else None,
        "latest_timestamp": timestamps[-1] if timestamps else None,
        "chronologically_valid": all(left < right for left, right in zip(timestamps, timestamps[1:])),
        "useful_fields": sorted(useful_fields),
    }


class Tier34Runner(ArchiveRunner):
    """One archive-only owner for Tier 3 and Tier 4 with phase budgets."""

    def __init__(
        self,
        *,
        state_dir: Path,
        intraday_manifest: list[dict[str, Any]],
        tier4_manifest: list[dict[str, Any]],
        calls_per_minute: int = TARGET_CALLS_PER_MINUTE,
        intraday_days: int = INTRADAY_LOOKBACK_CALENDAR_DAYS,
        intraday_window_days: int = INTRADAY_WINDOW_CALENDAR_DAYS,
    ) -> None:
        self.state_dir = state_dir
        self.intraday_manifest = intraday_manifest
        self.tier4_manifest = tier4_manifest
        self.manifest = tier4_manifest
        self.manifest_by_symbol = {row["symbol"]: row for row in tier4_manifest}
        self.manifest_path = state_dir / "fmp_archive_tier3_tier4_manifest_v1.json"
        self.progress_path = state_dir / "fmp_archive_tier3_tier4_progress_v1.json"
        self.validation_path = state_dir / "fmp_archive_tier3_tier4_validation_v1.json"
        self.lineage_path = state_dir / "fmp_archive_tier3_tier4_request_lineage_v1.jsonl"
        self.context_path = state_dir / "fmp_archive_tier3_tier4_context_v1.jsonl.gz"
        self.db_path = state_dir / "ai_trading_memory.db"
        self.key, self.key_source = resolve_fmp_key()
        if not self.key:
            raise ArchiveStop("missing_fmp_api_key")
        self.governor = RateGovernor(calls_per_minute)
        self.payload_ceiling_bytes = TIER3_PAYLOAD_CEILING_BYTES
        self.request_limit = MAX_REQUESTS
        self.started_at = now_iso()
        self.stop_reason = ""
        self.malformed_streak = 0
        self.intraday_days = max(1, int(intraday_days or INTRADAY_LOOKBACK_CALENDAR_DAYS))
        self.intraday_window_days = max(1, min(3, int(intraday_window_days or INTRADAY_WINDOW_CALENDAR_DAYS)))
        self.progress = self._load_progress()
        self._ensure_paths()
        self._preserve_existing_profile_metadata()
        self._ensure_manifest_file()
        self._db_size_before = self.db_path.stat().st_size if self.db_path.exists() else 0

    def _load_progress(self) -> dict[str, Any]:
        existing = read_json(self.progress_path, {})
        intraday_symbols = [row["symbol"] for row in self.intraday_manifest]
        tier4_symbols = [row["symbol"] for row in self.tier4_manifest]
        if not isinstance(existing, dict) or existing.get("intraday_manifest_symbols") != intraday_symbols or existing.get("tier4_manifest_symbols") != tier4_symbols:
            existing = {}
        existing.setdefault("schema_version", "fmp_archive_tier3_tier4_progress_v1")
        existing.setdefault("status", "NOT_STARTED")
        existing.setdefault("started_at", self.started_at)
        existing.setdefault("updated_at", now_iso())
        existing.setdefault("intraday_manifest_symbols", intraday_symbols)
        existing.setdefault("tier4_manifest_symbols", tier4_symbols)
        existing.setdefault("intraday_days", self.intraday_days)
        existing.setdefault("intraday_window_days", self.intraday_window_days)
        existing.setdefault("tier3", {"status": "NOT_STARTED", "per_symbol": {}, "rows_inserted": 0, "duplicate_rows": 0, "invalid_rows": 0, "chronology_failures": 0, "windows_completed": 0})
        existing.setdefault("tier4", {"status": "NOT_STARTED", "per_symbol": {}, "rows_inserted": 0, "duplicate_rows": 0})
        existing.setdefault("total_api_calls", 0)
        existing.setdefault("total_retries", 0)
        existing.setdefault("total_payload_bytes", 0)
        existing.setdefault("errors", [])
        existing.setdefault("request_count_by_family", {})
        existing.setdefault("record_count_by_family", {})
        existing.setdefault("before_snapshot", None)
        return existing

    def _ensure_paths(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.lineage_path.exists():
            self.lineage_path.touch()

    def _ensure_manifest_file(self) -> None:
        atomic_json_write(
            self.manifest_path,
            {
                "schema_version": "fmp_archive_tier3_tier4_manifest_v1",
                "generated_at": now_iso(),
                "provider": "FMP",
                "intraday_target_count": len(self.intraday_manifest),
                "tier4_target_count": len(self.tier4_manifest),
                "intraday_symbols": self.intraday_manifest,
                "tier4_symbols": self.tier4_manifest,
                "selection_policy": "existing_local_canonical_universe_with_deterministic_intraday_contrast_set",
                "hard_limits": {
                    "target_calls_per_minute": TARGET_CALLS_PER_MINUTE,
                    "absolute_calls_per_minute": MAX_CALLS_PER_MINUTE,
                    "tier3_additional_payload_bytes": TIER3_PAYLOAD_CEILING_BYTES,
                    "tier4_additional_payload_bytes": TIER4_PAYLOAD_CEILING_BYTES,
                    "max_retry_per_request": 1,
                },
            },
        )

    def _preserve_existing_profile_metadata(self) -> None:
        """Keep completed profile enrichment across resume/validation runs."""
        existing = read_json(self.manifest_path, {}) or {}
        existing_rows = existing.get("tier4_symbols") if isinstance(existing, dict) else None
        current_symbols = [row["symbol"] for row in self.tier4_manifest]
        if not isinstance(existing_rows, list) or [row.get("symbol") for row in existing_rows if isinstance(row, dict)] != current_symbols:
            return
        prior_by_symbol = {row["symbol"]: row for row in existing_rows if isinstance(row, dict) and row.get("symbol")}
        for target in self.tier4_manifest:
            prior = prior_by_symbol.get(target["symbol"], {})
            for field in ("company_name", "exchange", "sector", "industry", "profile_fields", "profile_status"):
                if field in prior:
                    target[field] = prior[field]

    def _save_progress(self) -> None:
        self.progress["updated_at"] = now_iso()
        atomic_json_write(self.progress_path, self.progress)

    def _update_profile_metadata(self, symbol: str, rows: list[dict[str, Any]]) -> None:
        if not rows or symbol not in self.manifest_by_symbol:
            return
        row = rows[0]
        target = self.manifest_by_symbol[symbol]
        target.update(
            {
                "company_name": str(row.get("companyName") or row.get("name") or "") or None,
                "exchange": str(row.get("exchange") or row.get("exchangeShortName") or "") or None,
                "sector": str(row.get("sector") or "") or None,
                "industry": str(row.get("industry") or "") or None,
                "profile_fields": sorted(str(key) for key in row.keys()),
                "profile_status": "RECEIVED",
            }
        )
        self._ensure_manifest_file()

    def _store_intraday(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        if not self.db_path.exists():
            raise ArchiveStop("canonical_historical_database_missing")
        inserted = 0
        duplicates = 0
        with sqlite3.connect(str(self.db_path), timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historical_market_bars'").fetchone()
            if not table:
                raise ArchiveStop("canonical_historical_market_bars_table_missing")
            for row in rows:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO historical_market_bars(symbol,asset_type,timeframe,ts,o,h,l,c,v,provider,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (row["symbol"], "stock", INTRADAY_TIMEFRAME, row["timestamp"], row["open"], row["high"], row["low"], row["close"], row.get("volume"), FMP_PROVIDER, now_iso()),
                )
                if cursor.rowcount:
                    inserted += 1
                else:
                    duplicates += 1
            conn.commit()
        return inserted, duplicates

    def _tier3_window_key(self, start: date, end: date) -> str:
        return f"{start.isoformat()}:{end.isoformat()}"

    def _run_tier3(self) -> None:
        phase = self.progress["tier3"]
        if phase.get("status") == "COMPLETE":
            return
        phase["status"] = "RUNNING"
        phase["lookback_calendar_days"] = self.intraday_days
        phase["window_calendar_days"] = self.intraday_window_days
        lower_bound = date.today() - timedelta(days=self.intraday_days - 1)
        window_end = date.today()
        while window_end >= lower_bound:
            window_start = max(lower_bound, window_end - timedelta(days=self.intraday_window_days - 1))
            window_key = self._tier3_window_key(window_start, window_end)
            for target in self.intraday_manifest:
                symbol = target["symbol"]
                state = phase.setdefault("per_symbol", {}).setdefault(symbol, {"windows_completed": [], "rows_inserted": 0, "duplicate_rows": 0, "invalid_rows": 0, "earliest_timestamp": None, "latest_timestamp": None, "status": "RUNNING"})
                if window_key in state.get("windows_completed", []):
                    continue
                self._guard_runtime()
                params = {"symbol": symbol, "from": window_start.isoformat(), "to": window_end.isoformat()}
                rows, meta = self._request(family=INTRADAY_FAMILY, symbol=symbol, endpoint=INTRADAY_ENDPOINT, params=params)
                clean, quality = normalize_intraday_rows(symbol, rows)
                if clean:
                    self._append_context(INTRADAY_FAMILY, symbol, clean, endpoint=INTRADAY_ENDPOINT, params=params, retrieved_at=now_iso())
                inserted, duplicates = self._store_intraday(clean) if clean else (0, 0)
                state["windows_completed"].append(window_key)
                state["rows_inserted"] = safe_int(state.get("rows_inserted")) + inserted
                state["duplicate_rows"] = safe_int(state.get("duplicate_rows")) + duplicates + safe_int(quality.get("duplicate_records"))
                state["invalid_rows"] = safe_int(state.get("invalid_rows")) + safe_int(quality.get("invalid_records"))
                if quality.get("earliest_timestamp") is not None:
                    state["earliest_timestamp"] = min(x for x in (state.get("earliest_timestamp"), quality["earliest_timestamp"]) if x is not None)
                    state["latest_timestamp"] = max(x for x in (state.get("latest_timestamp"), quality["latest_timestamp"]) if x is not None)
                state.setdefault("window_quality", {})[window_key] = {**meta, **quality, "rows_inserted": inserted, "duplicate_rows": duplicates}
                phase["rows_inserted"] = safe_int(phase.get("rows_inserted")) + inserted
                phase["duplicate_rows"] = safe_int(phase.get("duplicate_rows")) + duplicates + safe_int(quality.get("duplicate_records"))
                phase["invalid_rows"] = safe_int(phase.get("invalid_rows")) + safe_int(quality.get("invalid_records"))
                if not quality.get("chronologically_valid", True):
                    phase["chronology_failures"] = safe_int(phase.get("chronology_failures")) + 1
                state["status"] = "COMPLETE"
                self._save_progress()
            phase["windows_completed"] = safe_int(phase.get("windows_completed")) + 1
            self._save_progress()
            window_end = window_start - timedelta(days=1)
        phase["status"] = "COMPLETE"
        self._save_progress()

    def _run_tier4(self) -> None:
        phase = self.progress["tier4"]
        if phase.get("status") == "COMPLETE":
            return
        phase["status"] = "RUNNING"
        self.payload_ceiling_bytes = safe_int(self.progress.get("total_payload_bytes")) + TIER4_PAYLOAD_CEILING_BYTES
        for target in self.tier4_manifest:
            symbol = target["symbol"]
            if phase.setdefault("per_symbol", {}).get(symbol, {}).get("status") == "COMPLETE":
                continue
            self._guard_runtime()
            phase["per_symbol"][symbol] = {"status": "RUNNING", "started_at": now_iso()}
            families = self._families_for_symbol(symbol)
            phase["per_symbol"][symbol]["families"] = families
            phase["per_symbol"][symbol]["status"] = "COMPLETE"
            phase["per_symbol"][symbol]["completed_at"] = now_iso()
            phase["rows_inserted"] = safe_int(phase.get("rows_inserted")) + safe_int(families.get("daily_history", {}).get("rows_inserted"))
            phase["duplicate_rows"] = safe_int(phase.get("duplicate_rows")) + safe_int(families.get("daily_history", {}).get("duplicate_rows"))
            self._save_progress()
        phase["status"] = "COMPLETE"
        self._save_progress()

    def run(self) -> None:
        self.progress["status"] = "RUNNING"
        self._save_progress()
        try:
            self._run_tier3()
            if self.progress["tier3"].get("status") != "COMPLETE":
                return
            self._run_tier4()
            self.progress["status"] = "COMPLETE" if self.progress["tier4"].get("status") == "COMPLETE" else "PARTIAL_STOPPED"
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
        self.progress["finished_at"] = now_iso()
        self._save_progress()

    def _intraday_validation(self) -> tuple[list[dict[str, Any]], int]:
        symbols = [row["symbol"] for row in self.intraday_manifest]
        if not symbols or not self.db_path.exists():
            return [], 0
        placeholders = ",".join("?" for _ in symbols)
        with open_current_read_only(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT symbol,COUNT(*) AS rows,MIN(ts) AS min_ts,MAX(ts) AS max_ts FROM historical_market_bars WHERE provider=? AND asset_type='stock' AND timeframe=? AND symbol IN ({placeholders}) GROUP BY symbol",
                [FMP_PROVIDER, INTRADAY_TIMEFRAME, *symbols],
            ).fetchall()
            duplicate_groups = conn.execute(
                f"SELECT COUNT(*) FROM (SELECT symbol,asset_type,timeframe,ts FROM historical_market_bars WHERE provider=? AND asset_type='stock' AND timeframe=? AND symbol IN ({placeholders}) GROUP BY symbol,asset_type,timeframe,ts HAVING COUNT(*)>1)",
                [FMP_PROVIDER, INTRADAY_TIMEFRAME, *symbols],
            ).fetchone()[0]
        result = []
        for row in rows:
            result.append(
                {
                    "symbol": row[0],
                    "rows": int(row[1]),
                    "earliest_timestamp": int(row[2]) if row[2] is not None else None,
                    "latest_timestamp": int(row[3]) if row[3] is not None else None,
                    "selection_group": INTRADAY_SYMBOL_GROUP.get(row[0]),
                }
            )
        return result, int(duplicate_groups)

    def _tier4_validation(self) -> dict[str, Any]:
        symbols = [row["symbol"] for row in self.tier4_manifest]
        by_symbol: list[dict[str, Any]] = []
        if symbols and self.db_path.exists():
            placeholders = ",".join("?" for _ in symbols)
            with open_current_read_only(self.db_path) as conn:
                rows = conn.execute(
                    f"SELECT symbol,COUNT(*) AS rows,MIN(ts) AS min_ts,MAX(ts) AS max_ts FROM historical_market_bars WHERE provider=? AND asset_type='stock' AND timeframe='1Day' AND symbol IN ({placeholders}) GROUP BY symbol",
                    [FMP_PROVIDER, *symbols],
                ).fetchall()
            for row in rows:
                by_symbol.append({"symbol": row[0], "rows": int(row[1]), "earliest_date": datetime.fromtimestamp(int(row[2]), UTC).date().isoformat() if row[2] is not None else None, "latest_date": datetime.fromtimestamp(int(row[3]), UTC).date().isoformat() if row[3] is not None else None})
        today = date.today()
        ages = {row["symbol"]: (today - parse_date(row["earliest_date"])).days if parse_date(row.get("earliest_date")) else 0 for row in by_symbol}
        profile_rows = [row for row in self.tier4_manifest if row.get("profile_status") == "RECEIVED"]
        family_counts = self.progress.get("record_count_by_family", {}) or {}
        return {
            "symbols_evaluated": len(self.tier4_manifest),
            "symbols_accepted": len(self.tier4_manifest),
            "rejected_count": 0,
            "rejection_reasons": {},
            "daily_rows_added": safe_int(self.progress["tier4"].get("rows_inserted")),
            "daily_duplicate_rows": safe_int(self.progress["tier4"].get("duplicate_rows")),
            "symbols_with_daily_rows": len(by_symbol),
            "earliest_date": min((row["earliest_date"] for row in by_symbol if row.get("earliest_date")), default=None),
            "latest_date": max((row["latest_date"] for row in by_symbol if row.get("latest_date")), default=None),
            "over_10_years": sum(1 for value in ages.values() if value > 3650),
            "over_20_years": sum(1 for value in ages.values() if value > 7300),
            "over_30_years": sum(1 for value in ages.values() if value > 10950),
            "metadata_coverage": len(profile_rows),
            "sector_coverage": dict(collections.Counter(row.get("sector") for row in profile_rows if row.get("sector"))),
            "industry_coverage": dict(collections.Counter(row.get("industry") for row in profile_rows if row.get("industry"))),
            "context_records_by_family": {key: safe_int(value) for key, value in family_counts.items() if key.startswith(TIER4_FAMILY_PREFIX) or key in {"profile", "corporate_actions_dividends", "corporate_actions_splits", "earnings"}},
            "corporate_actions": {
                "dividends": safe_int(family_counts.get("corporate_actions_dividends")),
                "splits": safe_int(family_counts.get("corporate_actions_splits")),
            },
            "earnings_records": safe_int(family_counts.get("earnings")),
            "fundamentals_records": sum(safe_int(value) for key, value in family_counts.items() if str(key).startswith("fundamentals_")),
            "per_symbol_depth": sorted(by_symbol, key=lambda row: (row.get("earliest_date") or "9999-12-31", row["symbol"])),
        }

    def validation(self, *, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> dict[str, Any]:
        intraday_rows, duplicate_groups = self._intraday_validation()
        intraday_state = self.progress.get("tier3", {})
        intraday_per_symbol = intraday_state.get("per_symbol", {}) or {}
        all_intraday_timestamps = [timestamp for row in intraday_rows for timestamp in (row.get("earliest_timestamp"), row.get("latest_timestamp")) if timestamp is not None]
        context_bytes = self.context_path.stat().st_size if self.context_path.exists() else 0
        lineage_bytes = self.lineage_path.stat().st_size if self.lineage_path.exists() else 0
        before_db = (before or self.progress.get("before_snapshot") or {}).get("database_bytes")
        after_db = (after or {}).get("database_bytes") if after else (self.db_path.stat().st_size if self.db_path.exists() else 0)
        expected_intraday_windows = (self.intraday_days + self.intraday_window_days - 1) // self.intraday_window_days
        earliest_timestamp = min(all_intraday_timestamps, default=None)
        latest_timestamp = max(all_intraday_timestamps, default=None)

        def timestamp_iso(value: int | None) -> str | None:
            return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z") if value is not None else None

        previous_payload = 0
        for name in ("fmp_archive_validation_v1.json", "fmp_archive_enrichment_validation_v1.json"):
            prior = read_json(self.state_dir / name, {}) or {}
            previous_payload += safe_int(prior.get("measured_payload_bytes"))
        runtime_duration_seconds = None
        started_at = self.progress.get("started_at")
        finished_at = self.progress.get("finished_at")
        if started_at and finished_at:
            try:
                started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                finished = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
                runtime_duration_seconds = max(0.0, (finished - started).total_seconds())
            except (TypeError, ValueError):
                runtime_duration_seconds = None
        validation = {
            "schema_version": "fmp_archive_tier3_tier4_validation_v1",
            "status": self.progress.get("status"),
            "scope_status": "COMPLETE" if self.progress.get("status") == "COMPLETE" else "PARTIAL_STOPPED",
            "generated_at": now_iso(),
            "started_at": self.progress.get("started_at"),
            "finished_at": self.progress.get("finished_at"),
            "runtime_duration_seconds": runtime_duration_seconds,
            "tier3_intraday": {
                "symbols_selected": len(self.intraday_manifest),
                "symbols_completed": sum(1 for row in self.intraday_manifest if len(intraday_per_symbol.get(row["symbol"], {}).get("windows_completed", [])) >= expected_intraday_windows and intraday_per_symbol.get(row["symbol"], {}).get("status") == "COMPLETE"),
                "resolution": INTRADAY_TIMEFRAME,
                "endpoint": INTRADAY_ENDPOINT,
                "lookback_calendar_days": self.intraday_days,
                "window_calendar_days": self.intraday_window_days,
                "rows_archived": sum(safe_int(row.get("rows")) for row in intraday_rows),
                "rows_inserted_this_run": safe_int(intraday_state.get("rows_inserted")),
                "earliest_timestamp": earliest_timestamp,
                "latest_timestamp": latest_timestamp,
                "earliest_timestamp_utc": timestamp_iso(earliest_timestamp),
                "latest_timestamp_utc": timestamp_iso(latest_timestamp),
                "one_minute_coverage_count": len(intraday_rows),
                "five_minute_fallback": {"rows": 0, "symbols": 0, "status": "NOT_USED"},
                "invalid_rows": safe_int(intraday_state.get("invalid_rows")),
                "chronology_failures": safe_int(intraday_state.get("chronology_failures")),
                "duplicate_rows_skipped": safe_int(intraday_state.get("duplicate_rows")),
                "duplicate_key_groups": duplicate_groups,
                "selection_groups": dict(collections.Counter(row["selection_group"] for row in self.intraday_manifest)),
                "symbols_with_no_rows": [row["symbol"] for row in self.intraday_manifest if row["symbol"] not in {item["symbol"] for item in intraday_rows}],
                "per_symbol": intraday_rows,
            },
            "tier4_expansion": self._tier4_validation(),
            "usage": {
                "total_api_calls": safe_int(self.progress.get("total_api_calls")),
                "measured_payload_bytes": safe_int(self.progress.get("total_payload_bytes")),
                "measured_payload_gb_decimal": round(safe_int(self.progress.get("total_payload_bytes")) / 1_000_000_000, 9),
                "previous_local_archive_payload_bytes": previous_payload,
                "cumulative_local_archive_payload_bytes_including_this_run": previous_payload + safe_int(self.progress.get("total_payload_bytes")),
                "retries": safe_int(self.progress.get("total_retries")),
                "errors": list(self.progress.get("errors") or [])[-20:],
                "request_count_by_family": dict(self.progress.get("request_count_by_family") or {}),
                "record_count_by_family": dict(self.progress.get("record_count_by_family") or {}),
                "target_calls_per_minute": TARGET_CALLS_PER_MINUTE,
                "absolute_calls_per_minute": MAX_CALLS_PER_MINUTE,
            },
            "storage": {
                "canonical_database": str(self.db_path),
                "historical_table": "historical_market_bars",
                "database_bytes_before": before_db,
                "database_bytes_after": after_db,
                "observed_shared_database_growth_bytes": (after_db - before_db) if before_db is not None and after_db is not None else None,
                "database_growth_attribution": "shared canonical database; concurrent worker writes cannot be isolated from archive writes",
                "context_path": str(self.context_path),
                "context_bytes": context_bytes,
                "lineage_path": str(self.lineage_path),
                "lineage_bytes": lineage_bytes,
                "historical_evidence_separate_from_broker_truth": True,
                "checkpoint_state": {
                    "overall": self.progress.get("status"),
                    "tier3": intraday_state.get("status"),
                    "tier4": self.progress.get("tier4", {}).get("status"),
                },
            },
            "runtime_protection": {
                "before": before or self.progress.get("before_snapshot"),
                "after": after,
                "worker_restart_requested": False,
                "backend_restart_requested": False,
                "broker_actions_caused": 0,
                "crypto_route_unchanged": True,
            },
            "truth_safety": {
                "broker_truth_untouched": True,
                "positions_mutated": False,
                "fabricated_lifecycle_or_truth": False,
                "fabricated_learning": False,
                "historical_replay_evidence_only": True,
                "symbol_rewrites": False,
                "provenance_preserved": True,
            },
        }
        atomic_json_write(self.validation_path, validation)
        return validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded FMP Tier 3 intraday and Tier 4 selective archive")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--calls-per-minute", type=int, default=TARGET_CALLS_PER_MINUTE)
    parser.add_argument("--intraday-days", type=int, default=INTRADAY_LOOKBACK_CALENDAR_DAYS)
    parser.add_argument("--intraday-window-days", type=int, default=INTRADAY_WINDOW_CALENDAR_DAYS)
    parser.add_argument("--tier4-symbols", type=int, default=TIER4_MAX_SYMBOLS)
    args = parser.parse_args()
    state_dir = Path(args.state_dir).expanduser().resolve()
    intraday_manifest = build_intraday_manifest(state_dir)
    if len(intraday_manifest) != TIER3_MAX_SYMBOLS:
        raise SystemExit(f"intraday_manifest_must_be_{TIER3_MAX_SYMBOLS}_symbols:{len(intraday_manifest)}")
    tier4_manifest = build_tier4_manifest(state_dir, limit=args.tier4_symbols)
    before = make_before_after_snapshot(state_dir, label="BEFORE")
    runner = Tier34Runner(
        state_dir=state_dir,
        intraday_manifest=intraday_manifest,
        tier4_manifest=tier4_manifest,
        calls_per_minute=min(args.calls_per_minute, MAX_CALLS_PER_MINUTE),
        intraday_days=args.intraday_days,
        intraday_window_days=args.intraday_window_days,
    )
    runner.progress.setdefault("before_snapshot", before)
    runner._save_progress()
    runner.run()
    after = make_before_after_snapshot(state_dir, label="AFTER")
    validation = runner.validation(before=before, after=after)
    print(json.dumps({
        "status": validation.get("status"),
        "tier3_symbols": validation.get("tier3_intraday", {}).get("symbols_selected"),
        "tier3_rows": validation.get("tier3_intraday", {}).get("rows_archived"),
        "tier4_symbols": validation.get("tier4_expansion", {}).get("symbols_accepted"),
        "tier4_daily_rows": validation.get("tier4_expansion", {}).get("daily_rows_added"),
        "api_calls": validation.get("usage", {}).get("total_api_calls"),
        "payload_bytes": validation.get("usage", {}).get("measured_payload_bytes"),
        "stop_reason": runner.stop_reason,
        "validation_path": str(runner.validation_path),
    }, sort_keys=True))
    return 0 if validation.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
