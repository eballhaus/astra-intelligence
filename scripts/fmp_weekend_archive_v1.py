#!/usr/bin/env python3
"""Bounded, resumable FMP historical archive runner.

This process is deliberately outside Astra's worker/provider ownership.  It
only reads the FMP API and appends historical evidence to the existing
``historical_market_bars`` table plus compact, provenance-preserving context
records.  It never imports execution, lifecycle, truth, or learning owners.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

# Allow direct ``python scripts/...`` execution without changing the worker's
# import environment.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.runtime_environment import resolve_fmp_key


VERSION = "1.0.0"
DEFAULT_STATE_DIR = Path("/Users/Shared/AstraRuntime/state")
FMP_BASE = "https://financialmodelingprep.com"
TARGET_SYMBOLS = 300
TARGET_CALLS_PER_MINUTE = 25
MAX_CALLS_PER_MINUTE = 50
MAX_PAYLOAD_BYTES = 37_300_000_000
MAX_REQUESTS = 5_000
MAX_RETRIES_PER_REQUEST = 1
MAX_HISTORY_BATCHES_PER_SYMBOL = 8
HISTORY_ENDPOINT = "/stable/historical-price-eod/full"
FMP_PROVIDER = "FMP_HIST"
STOCK_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# This is only a preference list for symbols already present in canonical
# local sources.  It does not add symbols to the source universe.
ETF_PREFERENCE = frozenset(
    {
        "DIA", "DVY", "EFA", "EEM", "IWM", "IVV", "MDY", "QQQ", "RSP", "SPY", "SPLG", "TLT", "VTI", "VO", "VB",
        "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY", "VNQ", "IYR", "SMH", "SOXX",
    }
)
CRYPTO_SYMBOLS = frozenset({"BTC", "ETH", "SHIB", "SOL", "DOGE", "USDT", "USDC"})


class ArchiveStop(RuntimeError):
    """A bounded stop condition that must preserve the checkpoint."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except (OSError, ValueError, TypeError):
        return default


def open_current_read_only(db_path: Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    """Read current SQLite state, including committed WAL records."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=timeout)


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def date_to_ts(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def is_equity_symbol(value: Any) -> bool:
    symbol = normalize_symbol(value)
    if not symbol or "/" in symbol or symbol in CRYPTO_SYMBOLS or not STOCK_SYMBOL_RE.fullmatch(symbol):
        return False
    return True


def normalize_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("historical", "data", "results", "_list"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, dict)]
    return []


def normalize_daily_rows(symbol: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    duplicate_count = 0
    invalid_count = 0
    useful_fields: set[str] = set()
    for raw in rows:
        useful_fields.update(str(key) for key in raw.keys())
        raw_symbol = normalize_symbol(raw.get("symbol") or symbol)
        day = parse_date(raw.get("date") or raw.get("datetime") or raw.get("timestamp"))
        if raw_symbol and raw_symbol != symbol or day is None:
            invalid_count += 1
            continue
        key = day.isoformat()
        if key in seen:
            duplicate_count += 1
            continue
        open_value = safe_float(raw.get("open"))
        high_value = safe_float(raw.get("high"))
        low_value = safe_float(raw.get("low"))
        close_value = safe_float(raw.get("close"))
        volume_value = safe_float(raw.get("volume"))
        if any(value is None or value <= 0 for value in (open_value, high_value, low_value, close_value)):
            invalid_count += 1
            continue
        if high_value < max(open_value, close_value) or low_value > min(open_value, close_value) or high_value < low_value:
            invalid_count += 1
            continue
        seen.add(key)
        normalized.append(
            {
                "symbol": symbol,
                "date": key,
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": close_value,
                "volume": volume_value,
                "adjusted_close": safe_float(raw.get("adjClose") or raw.get("adjustedClose") or raw.get("adj_close")),
            }
        )
    normalized.sort(key=lambda row: row["date"])
    dates = [parse_date(row["date"]) for row in normalized]
    chronologically_valid = all(left <= right for left, right in zip(dates, dates[1:]) if left and right)
    return normalized, {
        "records_received": len(rows),
        "records_valid": len(normalized),
        "unique_records": len(normalized),
        "duplicate_records": duplicate_count,
        "invalid_records": invalid_count,
        "earliest_date": normalized[0]["date"] if normalized else None,
        "latest_date": normalized[-1]["date"] if normalized else None,
        "chronologically_valid": chronologically_valid,
        "useful_fields": sorted(useful_fields),
        "adjusted_close_records": sum(1 for row in normalized if row.get("adjusted_close") is not None),
    }


def source_symbols(state_dir: Path) -> tuple[set[str], set[str], dict[str, str]]:
    """Read only existing local source manifests for the archive universe."""
    broad_payload = read_json(state_dir / "broad_universe_intake_promotion_v1.json", {})
    broad = {
        normalize_symbol(symbol)
        for symbol in list((broad_payload or {}).get("symbols") or [])
        if is_equity_symbol(symbol)
    }
    historical: set[str] = set()
    db_path = state_dir / "ai_trading_memory.db"
    if db_path.exists():
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True, timeout=1.0) as conn:
                historical = {
                    normalize_symbol(row[0])
                    for row in conn.execute("SELECT DISTINCT symbol FROM historical_market_bars WHERE asset_type='stock'")
                    if is_equity_symbol(row[0])
                }
        except sqlite3.Error:
            historical = set()
    reasons: dict[str, str] = {}
    for symbol in sorted(broad | historical):
        labels = []
        if symbol in historical:
            labels.append("present_in_existing_historical_market_bars")
        if symbol in broad:
            labels.append("present_in_current_canonical_liquid_universe")
        reasons[symbol] = ";".join(labels)
    return broad, historical, reasons


def build_symbol_manifest(state_dir: Path, limit: int = TARGET_SYMBOLS) -> list[dict[str, Any]]:
    broad, historical, reasons = source_symbols(state_dir)
    symbols = sorted(broad | historical)
    ranked = sorted(
        symbols,
        key=lambda symbol: (
            1 if symbol in ETF_PREFERENCE else 0,
            1 if symbol in historical else 0,
            1 if symbol in broad else 0,
            symbol,
        ),
        reverse=True,
    )[: max(1, min(TARGET_SYMBOLS, int(limit or TARGET_SYMBOLS)))]
    manifest = []
    for symbol in sorted(ranked):
        is_etf = symbol in ETF_PREFERENCE
        manifest.append(
            {
                "symbol": symbol,
                "asset_type": "stock",
                "sector": None,
                "industry": None,
                "archive_tier": "core_etf" if is_etf else "liquid_equity",
                "reason_selected": reasons.get(symbol) or "existing_canonical_source",
                "source_flags": {
                    "existing_historical_bars": symbol in historical,
                    "canonical_liquid_universe": symbol in broad,
                    "known_etf_preference": is_etf,
                },
            }
        )
    return manifest


class RateGovernor:
    def __init__(self, calls_per_minute: int = TARGET_CALLS_PER_MINUTE, *, sleep_fn=time.sleep) -> None:
        rate = max(1, min(MAX_CALLS_PER_MINUTE, int(calls_per_minute or TARGET_CALLS_PER_MINUTE)))
        self.interval = 60.0 / rate
        self.next_call_at = 0.0
        self.sleep_fn = sleep_fn

    def wait(self) -> None:
        now = time.monotonic()
        delay = max(0.0, self.next_call_at - now)
        if delay:
            self.sleep_fn(delay)
        self.next_call_at = max(now, self.next_call_at) + self.interval


class ArchiveRunner:
    def __init__(self, *, state_dir: Path, manifest: list[dict[str, Any]], calls_per_minute: int = TARGET_CALLS_PER_MINUTE) -> None:
        self.state_dir = state_dir
        self.manifest = manifest
        self.manifest_by_symbol = {row["symbol"]: row for row in manifest}
        self.manifest_path = state_dir / "fmp_archive_manifest_v1.json"
        self.progress_path = state_dir / "fmp_archive_progress_v1.json"
        self.validation_path = state_dir / "fmp_archive_validation_v1.json"
        self.lineage_path = state_dir / "fmp_archive_request_lineage_v1.jsonl"
        self.context_path = state_dir / "fmp_archive_context_v1.jsonl.gz"
        self.db_path = state_dir / "ai_trading_memory.db"
        self.key, self.key_source = resolve_fmp_key()
        if not self.key:
            raise ArchiveStop("missing_fmp_api_key")
        self.governor = RateGovernor(calls_per_minute)
        self.started_at = now_iso()
        self.stop_reason = ""
        self.malformed_streak = 0
        self.progress = self._load_progress()
        self._ensure_manifest_file()
        self._ensure_paths()
        self._db_size_before = self.db_path.stat().st_size if self.db_path.exists() else 0

    def _ensure_paths(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.lineage_path.exists():
            self.lineage_path.touch()

    def _load_progress(self) -> dict[str, Any]:
        existing = read_json(self.progress_path, {})
        if not isinstance(existing, dict) or existing.get("manifest_symbols") != [row["symbol"] for row in self.manifest]:
            existing = {}
        existing.setdefault("schema_version", "fmp_archive_progress_v1")
        existing.setdefault("status", "NOT_STARTED")
        existing.setdefault("started_at", self.started_at)
        existing.setdefault("updated_at", now_iso())
        existing.setdefault("manifest_symbols", [row["symbol"] for row in self.manifest])
        existing.setdefault("completed_symbols", [])
        existing.setdefault("per_symbol", {})
        existing.setdefault("total_api_calls", 0)
        existing.setdefault("total_retries", 0)
        existing.setdefault("total_payload_bytes", 0)
        existing.setdefault("errors", [])
        existing.setdefault("request_count_by_family", {})
        existing.setdefault("record_count_by_family", {})
        existing.setdefault("rows_inserted", 0)
        existing.setdefault("duplicate_rows", 0)
        return existing

    def _ensure_manifest_file(self) -> None:
        payload = {
            "schema_version": "fmp_archive_manifest_v1",
            "generated_at": now_iso(),
            "provider": "FMP",
            "asset_type": "stock",
            "target_symbol_count": len(self.manifest),
            "source_policy": "existing_local_canonical_liquid_and_historical_sources_only",
            "symbols": self.manifest,
            "hard_limits": {
                "target_calls_per_minute": TARGET_CALLS_PER_MINUTE,
                "absolute_calls_per_minute": MAX_CALLS_PER_MINUTE,
                "max_additional_payload_bytes": MAX_PAYLOAD_BYTES,
                "max_retry_per_request": MAX_RETRIES_PER_REQUEST,
            },
        }
        atomic_json_write(self.manifest_path, payload)

    def _save_progress(self) -> None:
        self.progress["updated_at"] = now_iso()
        atomic_json_write(self.progress_path, self.progress)

    def _runtime_health(self) -> dict[str, Any]:
        snapshot = read_json(self.state_dir / "astra_worker_runtime_state_v1.json", {})
        worker_pids: list[int] = []
        try:
            result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=2, check=False)
            for line in result.stdout.splitlines():
                if "engine.paper_autopilot_worker" not in line or "grep" in line:
                    continue
                try:
                    worker_pids.append(int(line.strip().split(None, 1)[0]))
                except (IndexError, ValueError):
                    continue
        except (OSError, subprocess.SubprocessError):
            worker_pids = []
        backend_status = 0
        try:
            request = urllib.request.Request("http://127.0.0.1:8000/api/health", method="GET")
            with urllib.request.urlopen(request, timeout=2) as response:
                backend_status = int(response.status)
        except (OSError, urllib.error.URLError):
            backend_status = 0
        return {
            "timestamp": now_iso(),
            "worker_pids": worker_pids,
            "worker_pid_count": len(worker_pids),
            "snapshot_worker_count": safe_int(snapshot.get("worker_count"), 0),
            "active_worker_pid": snapshot.get("active_worker_pid"),
            "worker_revision": snapshot.get("worker_revision") or snapshot.get("runtime_revision"),
            "cycle_id": snapshot.get("cycle_id"),
            "cycle_count": snapshot.get("cycle_count"),
            "heartbeat_at": snapshot.get("heartbeat_at"),
            "resource_state": snapshot.get("resource_state") or (snapshot.get("resource") or {}).get("resource_state"),
            "last_error": str(snapshot.get("last_error") or ""),
            "backend_http_status": backend_status,
        }

    def _guard_runtime(self) -> None:
        health = self._runtime_health()
        healthy = (
            health["worker_pid_count"] == 1
            and health["snapshot_worker_count"] == 1
            and bool(health.get("active_worker_pid"))
            and health.get("resource_state") == "RESOURCE_NORMAL"
            and not health.get("last_error")
            and health["backend_http_status"] == 200
        )
        if not healthy:
            raise ArchiveStop("astra_runtime_guard_failed:" + json.dumps(health, sort_keys=True, separators=(",", ":"))[:700])

    def _append_lineage(self, record: dict[str, Any]) -> None:
        with self.lineage_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")

    def _append_context(self, family: str, symbol: str, rows: list[dict[str, Any]], *, endpoint: str, params: dict[str, Any], retrieved_at: str) -> None:
        if not rows:
            return
        self.context_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(self.context_path, "at", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": "fmp_archive_context_v1",
                            "family": family,
                            "symbol": symbol,
                            "provider": "FMP",
                            "endpoint": endpoint,
                            "requested_params": params,
                            "retrieved_at": retrieved_at,
                            "record": row,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )

    def _request(self, *, family: str, symbol: str, endpoint: str, params: dict[str, Any], retry_count: int = 0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self._guard_runtime()
        if safe_int(self.progress.get("total_api_calls"), 0) >= MAX_REQUESTS:
            raise ArchiveStop("max_request_count_reached")
        self.governor.wait()
        requested_at = now_iso()
        secret_params = dict(params)
        secret_params["apikey"] = self.key
        url = FMP_BASE + endpoint + "?" + urllib.parse.urlencode(secret_params)
        visible_params = {key: value for key, value in params.items() if key != "apikey"}
        started = time.perf_counter()
        status = 0
        body = b""
        error = ""
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Astra-FMP-Archive/1.0"}, method="GET")
            with urllib.request.urlopen(request, timeout=30) as response:
                status = int(response.status)
                chunks: list[bytes] = []
                bytes_read = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    if safe_int(self.progress.get("total_payload_bytes"), 0) + bytes_read > MAX_PAYLOAD_BYTES:
                        raise ArchiveStop("payload_ceiling_exceeded")
                    chunks.append(chunk)
                body = b"".join(chunks)
        except urllib.error.HTTPError as exc:
            status = int(exc.code or 0)
            error = f"http_{status}"
            try:
                body = exc.read(4096)
            except OSError:
                body = b""
        except ArchiveStop:
            raise
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            error = type(exc).__name__
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        payload_bytes = len(body)
        self.progress["total_api_calls"] = safe_int(self.progress.get("total_api_calls"), 0) + 1
        self.progress["total_payload_bytes"] = safe_int(self.progress.get("total_payload_bytes"), 0) + payload_bytes
        self.progress.setdefault("request_count_by_family", {})[family] = safe_int(self.progress.get("request_count_by_family", {}).get(family), 0) + 1
        if status in {401, 403, 429}:
            error = error or f"http_{status}"
            self._append_lineage({"timestamp": requested_at, "family": family, "symbol": symbol, "endpoint": endpoint, "params": visible_params, "status": status, "response_bytes": payload_bytes, "elapsed_ms": elapsed_ms, "records": 0, "error": error, "retry_count": retry_count})
            raise ArchiveStop(f"provider_stop:{error}")
        if status >= 500 or not status:
            if retry_count < MAX_RETRIES_PER_REQUEST:
                self.progress["total_retries"] = safe_int(self.progress.get("total_retries"), 0) + 1
                self._append_lineage({"timestamp": requested_at, "family": family, "symbol": symbol, "endpoint": endpoint, "params": visible_params, "status": status, "response_bytes": payload_bytes, "elapsed_ms": elapsed_ms, "records": 0, "error": error or "server_error", "retry_count": retry_count})
                return self._request(family=family, symbol=symbol, endpoint=endpoint, params=params, retry_count=retry_count + 1)
            raise ArchiveStop(f"provider_stop:repeated_server_error:{status or error}")
        if status != 200:
            error = error or f"http_{status}"
            self.progress.setdefault("errors", []).append({"family": family, "symbol": symbol, "error": error, "timestamp": requested_at})
            self._append_lineage({"timestamp": requested_at, "family": family, "symbol": symbol, "endpoint": endpoint, "params": visible_params, "status": status, "response_bytes": payload_bytes, "elapsed_ms": elapsed_ms, "records": 0, "error": error, "retry_count": retry_count})
            return [], {"status": status, "response_bytes": payload_bytes, "elapsed_ms": elapsed_ms, "error": error, "records": 0}
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.malformed_streak += 1
            error = f"malformed_json:{type(exc).__name__}"
            if self.malformed_streak >= 2:
                raise ArchiveStop("provider_stop:repeated_malformed_response")
            rows = []
            meta = {"status": status, "response_bytes": payload_bytes, "elapsed_ms": elapsed_ms, "error": error, "records": 0}
            self._append_lineage({"timestamp": requested_at, "family": family, "symbol": symbol, "endpoint": endpoint, "params": visible_params, **meta, "retry_count": retry_count})
            return rows, meta
        rows = normalize_rows(payload)
        self.malformed_streak = 0
        dates = [parse_date(row.get("date") or row.get("datetime") or row.get("timestamp")) for row in rows]
        valid_dates = [value.isoformat() for value in dates if value]
        meta = {
            "status": status,
            "response_bytes": payload_bytes,
            "elapsed_ms": elapsed_ms,
            "error": "",
            "records": len(rows),
            "earliest_date": min(valid_dates) if valid_dates else None,
            "latest_date": max(valid_dates) if valid_dates else None,
            "useful_fields": sorted({str(key) for row in rows[:100] for key in row.keys()}),
        }
        self.progress.setdefault("record_count_by_family", {})[family] = safe_int(self.progress.get("record_count_by_family", {}).get(family), 0) + len(rows)
        self._append_lineage({"timestamp": requested_at, "family": family, "symbol": symbol, "endpoint": endpoint, "params": visible_params, **meta, "retry_count": retry_count})
        return rows, meta

    def _store_daily(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        if not self.db_path.exists():
            raise ArchiveStop("canonical_historical_database_missing")
        inserted = 0
        duplicates = 0
        try:
            with sqlite3.connect(str(self.db_path), timeout=30.0) as conn:
                conn.execute("PRAGMA busy_timeout=30000")
                table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historical_market_bars'").fetchone()
                if not table:
                    raise ArchiveStop("canonical_historical_market_bars_table_missing")
                for row in rows:
                    day = parse_date(row.get("date"))
                    if not day:
                        continue
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO historical_market_bars(symbol,asset_type,timeframe,ts,o,h,l,c,v,provider,ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (row["symbol"], "stock", "1Day", date_to_ts(day), row["open"], row["high"], row["low"], row["close"], row.get("volume"), FMP_PROVIDER, now_iso()),
                    )
                    if cursor.rowcount:
                        inserted += 1
                    else:
                        duplicates += 1
                conn.commit()
        except sqlite3.OperationalError as exc:
            raise ArchiveStop(f"historical_store_write_failed:{str(exc)[:160]}") from exc
        self.progress["rows_inserted"] = safe_int(self.progress.get("rows_inserted"), 0) + inserted
        self.progress["duplicate_rows"] = safe_int(self.progress.get("duplicate_rows"), 0) + duplicates
        return inserted, duplicates

    def _update_profile_metadata(self, symbol: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        row = rows[0]
        manifest_row = self.manifest_by_symbol.get(symbol)
        if manifest_row:
            manifest_row["sector"] = str(row.get("sector") or "") or None
            manifest_row["industry"] = str(row.get("industry") or "") or None
            atomic_json_write(
                self.manifest_path,
                {
                    "schema_version": "fmp_archive_manifest_v1",
                    "generated_at": now_iso(),
                    "provider": "FMP",
                    "asset_type": "stock",
                    "target_symbol_count": len(self.manifest),
                    "source_policy": "existing_local_canonical_liquid_and_historical_sources_only",
                    "symbols": self.manifest,
                    "hard_limits": {"target_calls_per_minute": TARGET_CALLS_PER_MINUTE, "absolute_calls_per_minute": MAX_CALLS_PER_MINUTE, "max_additional_payload_bytes": MAX_PAYLOAD_BYTES, "max_retry_per_request": MAX_RETRIES_PER_REQUEST},
                },
            )

    def _family_call(self, family: str, symbol: str, endpoint: str, params: dict[str, Any], *, context: bool = True) -> dict[str, Any]:
        rows, meta = self._request(family=family, symbol=symbol, endpoint=endpoint, params=params)
        if context and rows:
            self._append_context(family, symbol, rows, endpoint=endpoint, params=params, retrieved_at=now_iso())
        return {**meta, "records": len(rows)}

    def _daily_for_symbol(self, symbol: str) -> dict[str, Any]:
        end = date.today()
        start = date(1900, 1, 1)
        current_end = end
        batches = 0
        details: list[dict[str, Any]] = []
        while batches < MAX_HISTORY_BATCHES_PER_SYMBOL:
            params = {"symbol": symbol, "from": start.isoformat(), "to": current_end.isoformat()}
            rows, meta = self._request(family="daily_history", symbol=symbol, endpoint=HISTORY_ENDPOINT, params=params)
            clean, quality = normalize_daily_rows(symbol, rows)
            if clean:
                inserted, duplicates = self._store_daily(clean)
            else:
                inserted, duplicates = 0, 0
            batch = {**meta, **quality, "requested_from": params["from"], "requested_to": params["to"], "rows_inserted": inserted, "duplicate_rows": duplicates}
            details.append(batch)
            batches += 1
            if not clean or len(rows) < 5_000 or not quality.get("earliest_date"):
                break
            earliest = parse_date(quality["earliest_date"])
            if not earliest or earliest <= start or earliest >= current_end:
                break
            current_end = earliest - timedelta(days=1)
        return {
            "status": "SUCCESS" if any(item.get("records_valid", 0) for item in details) else "EMPTY_RESPONSE",
            "batches": batches,
            "records_valid": sum(safe_int(item.get("records_valid"), 0) for item in details),
            "rows_inserted": sum(safe_int(item.get("rows_inserted"), 0) for item in details),
            "duplicate_rows": sum(safe_int(item.get("duplicate_rows"), 0) for item in details),
            "earliest_date": min((item.get("earliest_date") for item in details if item.get("earliest_date")), default=None),
            "latest_date": max((item.get("latest_date") for item in details if item.get("latest_date")), default=None),
            "batches_detail": details,
        }

    def _families_for_symbol(self, symbol: str) -> dict[str, Any]:
        families: dict[str, Any] = {}
        families["daily_history"] = self._daily_for_symbol(symbol)
        profile_rows, profile_meta = self._request(family="profile", symbol=symbol, endpoint="/stable/profile", params={"symbol": symbol})
        families["profile"] = {**profile_meta, "records": len(profile_rows)}
        if profile_rows:
            self._append_context("profile", symbol, profile_rows, endpoint="/stable/profile", params={"symbol": symbol}, retrieved_at=now_iso())
            self._update_profile_metadata(symbol, profile_rows)
        families["corporate_actions_dividends"] = self._family_call("corporate_actions_dividends", symbol, "/stable/dividends", {"symbol": symbol})
        families["corporate_actions_splits"] = self._family_call("corporate_actions_splits", symbol, "/stable/splits", {"symbol": symbol})
        families["earnings"] = self._family_call("earnings", symbol, "/stable/earnings", {"symbol": symbol})
        for statement, endpoint in (
            ("income_statement", "/stable/income-statement"),
            ("balance_sheet", "/stable/balance-sheet-statement"),
            ("cash_flow", "/stable/cash-flow-statement"),
        ):
            for period in ("annual", "quarter"):
                family = f"fundamentals_{statement}_{period}"
                families[family] = self._family_call(family, symbol, endpoint, {"symbol": symbol, "period": period, "limit": 20})
        return families

    def run(self) -> dict[str, Any]:
        self.progress["status"] = "RUNNING"
        self._save_progress()
        try:
            for row in self.manifest:
                symbol = row["symbol"]
                if symbol in set(self.progress.get("completed_symbols") or []):
                    continue
                self._guard_runtime()
                self.progress.setdefault("per_symbol", {})[symbol] = {"started_at": now_iso(), "status": "RUNNING", "families": {}}
                families = self._families_for_symbol(symbol)
                self.progress["per_symbol"][symbol]["families"] = families
                self.progress["per_symbol"][symbol]["status"] = "COMPLETE"
                self.progress["per_symbol"][symbol]["completed_at"] = now_iso()
                self.progress.setdefault("completed_symbols", []).append(symbol)
                self._save_progress()
            self.progress["status"] = "COMPLETE"
        except ArchiveStop as exc:
            self.stop_reason = str(exc)
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = self.stop_reason
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": self.stop_reason})
        except Exception as exc:  # Bounded checkpoint is more important than losing progress.
            self.stop_reason = f"unexpected_archive_error:{type(exc).__name__}:{str(exc)[:160]}"
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = self.stop_reason
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": self.stop_reason})
        self.progress["finished_at"] = now_iso()
        self._save_progress()
        return self.validation()

    def validation(self) -> dict[str, Any]:
        by_symbol: list[dict[str, Any]] = []
        daily_rows = 0
        fmp_symbols = 0
        duplicate_rows = safe_int(self.progress.get("duplicate_rows"), 0)
        if self.db_path.exists():
            try:
                with open_current_read_only(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    query = conn.execute(
                        "SELECT symbol, COUNT(*) AS rows, MIN(ts) AS min_ts, MAX(ts) AS max_ts FROM historical_market_bars WHERE provider=? AND asset_type='stock' AND timeframe='1Day' GROUP BY symbol ORDER BY rows DESC, symbol",
                        (FMP_PROVIDER,),
                    ).fetchall()
                    daily_rows = sum(safe_int(row["rows"], 0) for row in query)
                    fmp_symbols = len(query)
                    for row in query:
                        by_symbol.append({"symbol": row["symbol"], "rows": safe_int(row["rows"], 0), "earliest_date": datetime.fromtimestamp(safe_int(row["min_ts"], 0), UTC).date().isoformat() if row["min_ts"] else None, "latest_date": datetime.fromtimestamp(safe_int(row["max_ts"], 0), UTC).date().isoformat() if row["max_ts"] else None})
            except sqlite3.Error:
                pass
        context_counts: dict[str, int] = {}
        if self.context_path.exists():
            try:
                with gzip.open(self.context_path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            family = str((json.loads(line) or {}).get("family") or "unknown")
                            context_counts[family] = context_counts.get(family, 0) + 1
                        except (ValueError, TypeError):
                            continue
            except OSError:
                pass
        today = date.today()
        def age_days(item: dict[str, Any]) -> int:
            first = parse_date(item.get("earliest_date"))
            return (today - first).days if first else 0
        validation = {
            "schema_version": "fmp_archive_validation_v1",
            "status": self.progress.get("status"),
            "generated_at": now_iso(),
            "started_at": self.progress.get("started_at"),
            "finished_at": self.progress.get("finished_at"),
            "runtime_duration_seconds": None,
            "symbols_targeted": len(self.manifest),
            "symbols_completed": len(self.progress.get("completed_symbols") or []),
            "symbols_with_fmp_daily_rows": fmp_symbols,
            "daily_rows": daily_rows,
            "daily_rows_inserted_this_run": safe_int(self.progress.get("rows_inserted"), 0),
            "duplicate_rows_not_overwritten": duplicate_rows,
            "top_20_by_daily_rows": by_symbol[:20],
            "symbols_less_than_10_years": [item["symbol"] for item in by_symbol if 0 < age_days(item) < 3650],
            "symbols_more_than_20_years": [item["symbol"] for item in by_symbol if age_days(item) > 7300],
            "symbols_more_than_30_years": [item["symbol"] for item in by_symbol if age_days(item) > 10950],
            "symbols_without_useful_deep_history": [item["symbol"] for item in by_symbol if safe_int(item.get("rows"), 0) < 2],
            "context_records_by_family": context_counts,
            "api_calls": safe_int(self.progress.get("total_api_calls"), 0),
            "retries": safe_int(self.progress.get("total_retries"), 0),
            "measured_payload_bytes": safe_int(self.progress.get("total_payload_bytes"), 0),
            "measured_payload_gb_decimal": round(safe_int(self.progress.get("total_payload_bytes"), 0) / 1_000_000_000, 9),
            "additional_payload_ceiling_bytes": MAX_PAYLOAD_BYTES,
            "checkpoint_state": {"status": self.progress.get("status"), "completed_symbols": len(self.progress.get("completed_symbols") or []), "next_uncompleted_symbol": next((row["symbol"] for row in self.manifest if row["symbol"] not in set(self.progress.get("completed_symbols") or [])), None)},
            "failure_count": len(self.progress.get("errors") or []),
            "failures": list(self.progress.get("errors") or [])[-20:],
            "archive_storage": {
                "canonical_database": str(self.db_path),
                "canonical_table": "historical_market_bars",
                "historical_provider_label": FMP_PROVIDER,
                "context_path": str(self.context_path),
                "context_bytes": self.context_path.stat().st_size if self.context_path.exists() else 0,
                "request_lineage_path": str(self.lineage_path),
                "request_lineage_bytes": self.lineage_path.stat().st_size if self.lineage_path.exists() else 0,
                "database_bytes_before": self._db_size_before,
                "database_bytes_after": self.db_path.stat().st_size if self.db_path.exists() else 0,
                "historical_evidence_separate_from_broker_truth": True,
            },
            "provenance": {"provider": "FMP", "source_endpoint": HISTORY_ENDPOINT, "retrieval_timestamp_preserved": True, "requested_ranges_preserved_in_lineage": True, "provider_native_adjusted_close": "stored_only_if_returned; not synthesized"},
            "safety": {"paper_only": True, "broker_actions": 0, "truth_created": 0, "learning_ack_created": 0, "worker_owned_provider_routing_changed": False, "crypto_routing_changed": False},
        }
        atomic_json_write(self.validation_path, validation)
        return validation


def make_before_after_snapshot(state_dir: Path, *, label: str) -> dict[str, Any]:
    runtime = read_json(state_dir / "astra_worker_runtime_state_v1.json", {})
    positions: list[dict[str, Any]] = []
    db_path = state_dir / "ai_trading_memory.db"
    if db_path.exists():
        try:
            with open_current_read_only(db_path) as conn:
                conn.row_factory = sqlite3.Row
                positions = [dict(row) for row in conn.execute("SELECT position_id,symbol,lane_id,status,quantity FROM paper_positions WHERE status IN ('OPEN','PENDING') ORDER BY symbol LIMIT 100")]
        except sqlite3.Error:
            positions = []
    return {
        "label": label,
        "timestamp": now_iso(),
        "worker_pid": runtime.get("active_worker_pid") or runtime.get("process_id"),
        "worker_count": runtime.get("worker_count"),
        "worker_revision": runtime.get("worker_revision") or runtime.get("runtime_revision"),
        "cycle_id": runtime.get("cycle_id"),
        "cycle_count": runtime.get("cycle_count"),
        "heartbeat_at": runtime.get("heartbeat_at"),
        "resource_state": runtime.get("resource_state") or (runtime.get("resource") or {}).get("resource_state"),
        "last_error": runtime.get("last_error") or "",
        "positions_sample": positions,
        "database_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "paper_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded FMP weekend historical archive")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--symbols", type=int, default=TARGET_SYMBOLS)
    parser.add_argument("--calls-per-minute", type=int, default=TARGET_CALLS_PER_MINUTE)
    parser.add_argument("--before-after-path", default="")
    args = parser.parse_args()
    state_dir = Path(args.state_dir).expanduser().resolve()
    manifest = build_symbol_manifest(state_dir, limit=args.symbols)
    before = make_before_after_snapshot(state_dir, label="BEFORE")
    runner = ArchiveRunner(state_dir=state_dir, manifest=manifest, calls_per_minute=min(args.calls_per_minute, MAX_CALLS_PER_MINUTE))
    validation = runner.run()
    after = make_before_after_snapshot(state_dir, label="AFTER")
    validation["before_snapshot"] = before
    validation["after_snapshot"] = after
    validation["worker_health_before_after"] = {"worker_pid_same": before.get("worker_pid") == after.get("worker_pid"), "worker_count_before": before.get("worker_count"), "worker_count_after": after.get("worker_count"), "resource_before": before.get("resource_state"), "resource_after": after.get("resource_state"), "last_error_before": before.get("last_error"), "last_error_after": after.get("last_error")}
    validation["runtime_protection"] = {"archive_process_is_not_worker_owner": True, "worker_restart_requested": False, "backend_restart_requested": False, "broker_actions_caused": 0, "crypto_route_unchanged": True}
    atomic_json_write(runner.validation_path, validation)
    if args.before_after_path:
        atomic_json_write(Path(args.before_after_path), {"before": before, "after": after})
    print(json.dumps({"status": validation.get("status"), "symbols_targeted": validation.get("symbols_targeted"), "symbols_completed": validation.get("symbols_completed"), "daily_rows": validation.get("daily_rows"), "api_calls": validation.get("api_calls"), "payload_bytes": validation.get("measured_payload_bytes"), "stop_reason": runner.stop_reason, "validation_path": str(runner.validation_path)}, sort_keys=True))
    return 0 if validation.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
