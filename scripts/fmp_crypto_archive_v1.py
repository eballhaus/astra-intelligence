#!/usr/bin/env python3
"""Checkpointed FMP crypto history archive using Astra's existing archive contracts."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.astra_intraday_evidence_index_v1 import (  # noqa: E402
    SUMMARY_TABLE,
    build_intraday_session_summaries,
    ensure_summary_schema,
    upsert_intraday_session_summaries,
)
from scripts.fmp_archive_tier3_tier4_v1 import normalize_intraday_rows  # noqa: E402
from scripts.fmp_weekend_archive_v1 import (  # noqa: E402
    ArchiveRunner,
    ArchiveStop,
    FMP_PROVIDER,
    MAX_CALLS_PER_MINUTE,
    MAX_PAYLOAD_BYTES,
    RateGovernor,
    atomic_json_write,
    now_iso,
    open_current_read_only,
    read_json,
    safe_int,
)


VERSION = "1.0.0"
STATE_DIR = Path("/Users/Shared/AstraRuntime/state")
END_DATE = date(2026, 9, 11)
TARGET_CALLS_PER_MINUTE = 25
PAYLOAD_CEILING_BYTES = 10_000_000_000
WINDOWS = {
    "1Day": {"lookback_days": 6095, "window_days": 365, "limit": None},
    "1Hour": {"lookback_days": 6095, "window_days": 90, "limit": None},
    "5Min": {"lookback_days": 365, "window_days": 45, "limit": 8},
    "1Min": {"lookback_days": 90, "window_days": 7, "limit": 4},
}
REQUIRED_PAIRS = ("ETH/USD", "SHIB/USD")


def _pair(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "/")
    if "/" not in text and text.endswith("USD"):
        text = f"{text[:-3]}/USD"
    return text


def _capability_pairs(state_dir: Path) -> tuple[set[str], set[str], list[dict[str, Any]]]:
    capability = read_json(state_dir / "alpaca_crypto_capability_v2.json", {}) or {}
    matrix = read_json(state_dir / "astra_crypto_market_data_capability_matrix_v1.json", {}) or {}
    supported = {_pair(value) for value in capability.get("supported_pairs") or []}
    tradable = {_pair(value) for value in capability.get("tradable_pairs") or []}
    matrix_rows = [row for row in matrix.get("pairs") or [] if isinstance(row, dict)]
    return supported, tradable, matrix_rows


def build_crypto_manifest(state_dir: Path, timeframe: str) -> list[dict[str, Any]]:
    supported, tradable, matrix_rows = _capability_pairs(state_dir)
    if not supported or not tradable:
        raise ArchiveStop("STAGE_4_PAIR_UNIVERSE_UNRESOLVED:capability_pairs_missing")
    eligible = supported & tradable
    usd_matrix = []
    for row in matrix_rows:
        pair = _pair(row.get("symbol") or row.get("request_symbol"))
        if pair.endswith("/USD") and pair in eligible and pair not in usd_matrix:
            usd_matrix.append(pair)
    broad = sorted(pair for pair in eligible if pair.endswith("/USD"))
    ordered = usd_matrix + [pair for pair in broad if pair not in usd_matrix]
    for pair in REQUIRED_PAIRS:
        if pair not in eligible:
            raise ArchiveStop(f"STAGE_4_PAIR_UNIVERSE_UNRESOLVED:{pair}_not_supported_and_tradable")
        if pair not in ordered:
            ordered.append(pair)
    limit = WINDOWS[timeframe]["limit"]
    if limit:
        required = [pair for pair in REQUIRED_PAIRS if pair in ordered]
        ordered = required + [pair for pair in ordered if pair not in required]
        ordered = ordered[: max(int(limit), len(required))]
    rows = []
    for pair in ordered:
        base, quote = pair.split("/", 1)
        rows.append({
            "symbol": pair,
            "canonical_pair": pair,
            "asset_type": "crypto",
            "timeframe": timeframe,
            "provider": FMP_PROVIDER,
            "provider_alias_candidates": [f"{base}{quote}", pair, f"{base}-{quote}"],
            "selection_reason": "existing_crypto_capability_matrix_and_supported_tradable_universe",
            "horizon_attribution": "UNRESOLVED_HISTORICAL_CRYPTO",
            "historical_replay_only": True,
            "natural_truth_eligible": False,
        })
    return rows


class CryptoArchiveRunner(ArchiveRunner):
    """Reuse the existing request, rate, and live-worker guard implementation."""

    def __init__(self, *, state_dir: Path, manifest: list[dict[str, Any]], timeframe: str,
                 lookback_days: int, window_days: int, calls_per_minute: int,
                 end_date: date) -> None:
        self.state_dir = state_dir
        self.manifest = manifest
        self.manifest_by_symbol = {row["symbol"]: row for row in manifest}
        suffix = timeframe.lower()
        self.manifest_path = state_dir / f"fmp_crypto_archive_v1_{suffix}_manifest.json"
        self.progress_path = state_dir / f"fmp_crypto_archive_v1_{suffix}_progress.json"
        self.validation_path = state_dir / f"fmp_crypto_archive_v1_{suffix}_validation.json"
        self.lineage_path = state_dir / f"fmp_crypto_archive_v1_{suffix}_request_lineage.jsonl"
        self.context_path = state_dir / f"fmp_crypto_archive_v1_{suffix}_context.jsonl.gz"
        self.db_path = state_dir / "ai_trading_memory.db"
        self.key, self.key_source = __import__("engine.runtime_environment", fromlist=["resolve_fmp_key"]).resolve_fmp_key()
        if not self.key:
            raise ArchiveStop("missing_fmp_api_key")
        self.governor = RateGovernor(min(int(calls_per_minute), MAX_CALLS_PER_MINUTE))
        self.started_at = now_iso()
        self.stop_reason = ""
        self.malformed_streak = 0
        self.timeframe = timeframe
        self.endpoint = f"/stable/historical-chart/{timeframe.lower()}"
        self.lookback_days = int(lookback_days)
        self.window_days = int(window_days)
        self.end_date = end_date
        self.payload_ceiling_bytes = PAYLOAD_CEILING_BYTES
        self.request_limit = 40_000 if timeframe == "1Hour" else 24_000
        self.progress = self._load_crypto_progress()
        self._ensure_paths()
        self._ensure_manifest_file()

    def _load_crypto_progress(self) -> dict[str, Any]:
        existing = read_json(self.progress_path, {})
        symbols = [row["symbol"] for row in self.manifest]
        if not isinstance(existing, dict) or existing.get("manifest_symbols") != symbols or existing.get("timeframe") != self.timeframe or existing.get("end_date") != self.end_date.isoformat():
            existing = {}
        defaults = {
            "schema_version": "fmp_crypto_archive_v1_progress",
            "status": "NOT_STARTED",
            "manifest_symbols": symbols,
            "timeframe": self.timeframe,
            "endpoint": self.endpoint,
            "end_date": self.end_date.isoformat(),
            "lookback_days": self.lookback_days,
            "window_days": self.window_days,
            "provider": FMP_PROVIDER,
            "asset_type": "crypto",
            "historical_replay_only": True,
            "natural_truth_eligible": False,
            "per_symbol": {},
            "total_api_calls": 0,
            "total_retries": 0,
            "total_payload_bytes": 0,
            "rows_inserted": 0,
            "duplicate_rows": 0,
            "invalid_rows": 0,
            "chronology_failures": 0,
            "windows_completed": 0,
            "errors": [],
            "supported_gap_windows": [],
            "summary": {"status": "NOT_STARTED", "records": 0},
        }
        for key, value in defaults.items():
            existing.setdefault(key, value)
        return existing

    def _ensure_manifest_file(self) -> None:
        atomic_json_write(self.manifest_path, {
            "schema_version": "fmp_crypto_archive_v1_manifest",
            "generator_version": VERSION,
            "generated_at": now_iso(),
            "provider": FMP_PROVIDER,
            "asset_type": "crypto",
            "timeframe": self.timeframe,
            "symbols": self.manifest,
            "historical_replay_only": True,
            "natural_truth_eligible": False,
            "hard_limits": {"target_calls_per_minute": TARGET_CALLS_PER_MINUTE, "absolute_calls_per_minute": MAX_CALLS_PER_MINUTE, "payload_ceiling_bytes": self.payload_ceiling_bytes},
        })

    def _store_rows(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        inserted = duplicates = 0
        for attempt in range(3):
            try:
                with sqlite3.connect(str(self.db_path), timeout=3.0) as conn:
                    conn.execute("PRAGMA busy_timeout=3000")
                    for row in rows:
                        cursor = conn.execute(
                            "INSERT OR IGNORE INTO historical_market_bars(symbol,asset_type,timeframe,ts,o,h,l,c,v,provider,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (row["symbol"], "crypto", self.timeframe, row["timestamp"], row["open"], row["high"], row["low"], row["close"], row.get("volume"), FMP_PROVIDER, now_iso()),
                        )
                        if cursor.rowcount:
                            inserted += 1
                        else:
                            duplicates += 1
                    conn.commit()
                return inserted, duplicates
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise ArchiveStop(f"historical_store_write_failed:{str(exc)[:160]}") from exc
                if attempt == 2:
                    raise ArchiveStop("canonical_historical_database_lock_contention") from exc
                import time
                time.sleep(0.5 * (attempt + 1))
        return inserted, duplicates

    def _request_alias(self, target: dict[str, Any], start: date, end: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        last_meta: dict[str, Any] = {"status": 0, "records": 0, "error": "empty_provider_window"}
        for alias in target["provider_alias_candidates"]:
            rows, meta = self._request(family=f"{self.timeframe}_crypto_raw", symbol=target["canonical_pair"], endpoint=self.endpoint, params={"symbol": alias, "from": start.isoformat(), "to": end.isoformat()})
            clean, quality = normalize_intraday_rows(alias, rows)
            if clean and not quality.get("invalid_records") and quality.get("chronologically_valid", True):
                for row in clean:
                    row["symbol"] = target["canonical_pair"]
                return clean, {**meta, **quality, "provider_symbol": alias, "canonical_pair": target["canonical_pair"], "alias_resolution_status": "DETERMINISTIC_PRECEDENCE"}
            last_meta = {**meta, **quality, "provider_symbol": alias, "canonical_pair": target["canonical_pair"]}
        return [], {**last_meta, "supported_gap": True}

    def _run_archive(self) -> None:
        lower_bound = self.end_date - timedelta(days=self.lookback_days - 1)
        window_end = self.end_date
        while window_end >= lower_bound:
            window_start = max(lower_bound, window_end - timedelta(days=self.window_days - 1))
            for target in self.manifest:
                key = f"{window_start.isoformat()}:{window_end.isoformat()}"
                state = self.progress.setdefault("per_symbol", {}).setdefault(target["canonical_pair"], {"windows_completed": [], "status": "RUNNING"})
                if key in state.get("windows_completed", []):
                    continue
                rows, meta = self._request_alias(target, window_start, window_end)
                inserted, duplicates = self._store_rows(rows) if rows else (0, 0)
                state.setdefault("windows_completed", []).append(key)
                state.setdefault("window_quality", {})[key] = {**meta, "rows_inserted": inserted, "duplicate_rows": duplicates, "requested_from": window_start.isoformat(), "requested_to": window_end.isoformat(), "provenance": {"canonical_pair": target["canonical_pair"], "provider_symbol": meta.get("provider_symbol"), "provider": FMP_PROVIDER}}
                if meta.get("supported_gap"):
                    self.progress.setdefault("supported_gap_windows", []).append({"canonical_pair": target["canonical_pair"], "window": key, "provider_aliases_tried": target["provider_alias_candidates"], "reason": meta.get("error") or "empty_provider_window"})
                self.progress["rows_inserted"] = safe_int(self.progress.get("rows_inserted")) + inserted
                self.progress["duplicate_rows"] = safe_int(self.progress.get("duplicate_rows")) + duplicates + safe_int(meta.get("duplicate_records"))
                self.progress["invalid_rows"] = safe_int(self.progress.get("invalid_rows")) + safe_int(meta.get("invalid_records"))
                self.progress["chronology_failures"] = safe_int(self.progress.get("chronology_failures")) + (0 if meta.get("chronologically_valid", True) else 1)
                self.progress["windows_completed"] = safe_int(self.progress.get("windows_completed")) + 1
                self.progress.setdefault("last_successful_window", {})[target["canonical_pair"]] = {"window": key, "provider_symbol": meta.get("provider_symbol"), "actual_earliest": meta.get("earliest_timestamp"), "actual_latest": meta.get("latest_timestamp")}
                self._save_progress()
            window_end = window_start - timedelta(days=1)
        for target in self.manifest:
            state = self.progress.setdefault("per_symbol", {}).setdefault(target["canonical_pair"], {})
            state["status"] = "COMPLETE"
        self.progress["status"] = "COMPLETE_WITH_SUPPORTED_GAPS" if self.progress.get("supported_gap_windows") else "COMPLETE"
        self._save_progress()

    def _build_summaries(self) -> None:
        if self.timeframe == "1Day" or not self.db_path.exists():
            self.progress.setdefault("summary", {})["status"] = "COMPLETE_NO_SUMMARY_REQUIRED" if self.timeframe == "1Day" else "ARCHIVE_UNAVAILABLE"
            self._save_progress()
            return
        lower_bound = self.end_date - timedelta(days=self.lookback_days - 1)
        start_ts = int(datetime(lower_bound.year, lower_bound.month, lower_bound.day, tzinfo=UTC).timestamp())
        end_ts = int(datetime(self.end_date.year, self.end_date.month, self.end_date.day, 23, 59, 59, tzinfo=UTC).timestamp())
        total = 0
        with sqlite3.connect(str(self.db_path), timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            ensure_summary_schema(conn)
            for target in self.manifest:
                self._guard_runtime()
                rows = conn.execute("SELECT symbol,ts,o,h,l,c,v FROM historical_market_bars WHERE symbol=? AND asset_type='crypto' AND timeframe=? AND provider=? AND ts BETWEEN ? AND ? ORDER BY ts", (target["canonical_pair"], self.timeframe, FMP_PROVIDER, start_ts, end_ts)).fetchall()
                canonical = [{"symbol": row[0], "timestamp": int(row[1]), "open": row[2], "high": row[3], "low": row[4], "close": row[5], "volume": row[6]} for row in rows]
                summaries = build_intraday_session_summaries(canonical, symbol=target["canonical_pair"], metadata={**target, "lane_relevance": ["CRYPTO_HORIZON_UNRESOLVED"]}, timeframe=self.timeframe, asset_type="crypto")
                total += upsert_intraday_session_summaries(conn, summaries, generated_at=now_iso())
                conn.commit()
                self.progress.setdefault("summary", {})["records"] = total
                self._save_progress()
        self.progress.setdefault("summary", {})["status"] = "COMPLETE"
        self._save_progress()

    def run(self) -> dict[str, Any]:
        self.progress["status"] = "RUNNING"
        self._save_progress()
        try:
            self._run_archive()
            self._build_summaries()
        except ArchiveStop as exc:
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = str(exc)
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": str(exc)})
        except Exception as exc:
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = f"unexpected_archive_error:{type(exc).__name__}:{str(exc)[:160]}"
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": self.progress["stop_reason"]})
        self.progress["finished_at"] = now_iso()
        self._save_progress()
        return self.progress


def run(args: argparse.Namespace) -> int:
    timeframe = args.timeframe
    if timeframe not in WINDOWS:
        raise SystemExit(f"unsupported timeframe: {timeframe}")
    manifest = build_crypto_manifest(args.state_dir, timeframe)
    config = WINDOWS[timeframe]
    runner = CryptoArchiveRunner(state_dir=args.state_dir, manifest=manifest, timeframe=timeframe, lookback_days=config["lookback_days"], window_days=config["window_days"], calls_per_minute=args.calls_per_minute, end_date=args.end_date)
    result = runner.run()
    print(json.dumps({"status": result.get("status"), "timeframe": timeframe, "symbols": len(manifest), "rows_inserted": result.get("rows_inserted"), "api_calls": result.get("total_api_calls"), "payload_bytes": result.get("total_payload_bytes"), "supported_gap_windows": len(result.get("supported_gap_windows") or []), "checkpoint": str(runner.progress_path)}, sort_keys=True))
    return 0 if result.get("status") in {"COMPLETE", "COMPLETE_WITH_SUPPORTED_GAPS"} else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--timeframe", required=True, choices=tuple(WINDOWS))
    parser.add_argument("--calls-per-minute", type=int, default=TARGET_CALLS_PER_MINUTE)
    parser.add_argument("--end-date", type=lambda value: date.fromisoformat(value), default=END_DATE)
    raise SystemExit(run(parser.parse_args()))
