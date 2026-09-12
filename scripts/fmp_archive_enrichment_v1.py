#!/usr/bin/env python3
"""Bounded FMP ETF and historical identity enrichment for the archive.

This extends the existing archive owner without importing execution, lifecycle,
truth, or learning authorities.  ETF bars use the existing historical table;
identity events use a compact reference table and never rewrite price symbols.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.runtime_environment import resolve_fmp_key
from scripts.fmp_weekend_archive_v1 import (
    ArchiveRunner,
    ArchiveStop,
    MAX_CALLS_PER_MINUTE,
    MAX_RETRIES_PER_REQUEST,
    MAX_PAYLOAD_BYTES,
    RateGovernor,
    atomic_json_write,
    make_before_after_snapshot,
    normalize_rows,
    now_iso,
    open_current_read_only,
    parse_date,
    read_json,
    safe_int,
)


VERSION = "1.0.0"
DEFAULT_STATE_DIR = Path("/Users/Shared/AstraRuntime/state")
TARGET_CALLS_PER_MINUTE = 25
ENRICHMENT_PAYLOAD_CEILING_BYTES = 5_000_000_000
ENRICHMENT_REQUEST_LIMIT = 1_000
IDENTITY_TABLE = "historical_symbol_continuity"
IDENTITY_PROVIDER = "FMP"
SYMBOL_CHANGE_ENDPOINT = "/stable/symbol-change"
DELISTED_ENDPOINT = "/stable/delisted-companies"

ETF_GROUPS: dict[str, tuple[str, ...]] = {
    "broad_market": ("SPY", "QQQ", "DIA", "IWM"),
    "sector": ("XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC", "VNQ"),
    "style": ("VOO", "VUG", "VTV", "RSP", "MDY", "VBK", "VBR", "IVV"),
    "rates": ("TLT", "IEF", "SHY", "AGG", "BND"),
    "commodity": ("GLD", "SLV", "DBC"),
    "volatility": ("VIXY",),
    "other": ("EFA", "EEM", "ARKK", "SMH", "SOXX"),
}
ETF_CATEGORIES = {symbol: category for category, symbols in ETF_GROUPS.items() for symbol in symbols}
ETF_SYMBOLS = tuple(ETF_CATEGORIES)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def verified_etf_profile(row: dict[str, Any]) -> bool:
    """Require an explicit provider ETF flag; names alone are insufficient."""
    return _bool(_first(row, "isEtf", "isETF", "is_etf")) is True


def build_enrichment_manifest() -> list[dict[str, Any]]:
    return [
        {
            "symbol": symbol,
            "asset_type": "stock",
            "instrument_type": "ETF",
            "category": ETF_CATEGORIES[symbol],
            "status": "PENDING",
            "verified_is_etf": False,
            "source": "existing_canonical_etf_registry_plus_bounded_regime_set",
        }
        for symbol in ETF_SYMBOLS
    ]


def restore_manifest_verification(manifest: list[dict[str, Any]], context_path: Path) -> None:
    """Restore ETF verification flags when a completed run is resumed."""
    if not context_path.exists():
        return
    by_symbol = {row["symbol"]: row for row in manifest}
    try:
        with gzip.open(context_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if item.get("family") != "etf_profile":
                    continue
                row = by_symbol.get(_text(item.get("symbol")).upper())
                profile = item.get("record") if isinstance(item.get("record"), dict) else {}
                if row is None:
                    continue
                verified = verified_etf_profile(profile)
                row.update(
                    {
                        "verified_is_etf": verified,
                        "profile_fields": sorted(profile.keys()),
                        "profile_status": "VERIFIED_ETF" if verified else "NOT_VERIFIED",
                        "status": "COMPLETE" if verified else "NOT_VERIFIED",
                    }
                )
    except OSError:
        return


def normalize_identity_record(raw: dict[str, Any], event_type: str, retrieved_at: str) -> dict[str, Any]:
    if event_type == "SYMBOL_CHANGE":
        old_symbol = _text(_first(raw, "oldSymbol", "old_symbol", "previousSymbol", "fromSymbol")).upper()
        new_symbol = _text(_first(raw, "newSymbol", "new_symbol", "toSymbol", "symbol")).upper()
        effective_date = parse_date(_first(raw, "date", "effectiveDate", "changeDate"))
        active_status = "ACTIVE_OR_UNKNOWN"
    else:
        old_symbol = _text(_first(raw, "symbol", "ticker")).upper()
        new_symbol = ""
        effective_date = parse_date(_first(raw, "delistedDate", "delistingDate", "date"))
        active_status = "INACTIVE"
    valid_mapping = event_type == "DELISTING" and bool(old_symbol) or (
        event_type == "SYMBOL_CHANGE" and bool(old_symbol and new_symbol and old_symbol != new_symbol)
    )
    normalized = {
        "old_symbol": old_symbol,
        "new_symbol": new_symbol,
        "company_name": _text(_first(raw, "companyName", "name")) or None,
        "effective_date": effective_date.isoformat() if effective_date else None,
        "event_type": event_type,
        "exchange": _text(_first(raw, "exchange", "exchangeShortName")) or None,
        "active_status": active_status,
        "reason": _text(_first(raw, "reason", "delistingReason")) or None,
        "cik": _text(raw.get("cik")) or None,
        "isin": _text(raw.get("isin")) or None,
        "cusip": _text(raw.get("cusip")) or None,
        "source": IDENTITY_PROVIDER,
        "retrieved_at": retrieved_at,
        "confidence": "HIGH" if valid_mapping else "LOW",
        "ambiguity_state": "VALIDATED" if valid_mapping else "AMBIGUOUS",
    }
    normalized["continuity_id"] = hashlib.sha256(
        json.dumps(
            {
                key: normalized[key]
                for key in (
                    "old_symbol",
                    "new_symbol",
                    "company_name",
                    "effective_date",
                    "event_type",
                    "exchange",
                    "active_status",
                    "reason",
                    "cik",
                    "isin",
                    "cusip",
                    "confidence",
                    "ambiguity_state",
                )
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return normalized


class EnrichmentRunner(ArchiveRunner):
    """Reuse the existing request, rate, runtime guard, and daily storage path."""

    def __init__(self, *, state_dir: Path, manifest: list[dict[str, Any]], calls_per_minute: int = TARGET_CALLS_PER_MINUTE) -> None:
        self.state_dir = state_dir
        self.manifest = manifest
        self.manifest_by_symbol = {row["symbol"]: row for row in manifest}
        self.manifest_path = state_dir / "fmp_archive_enrichment_manifest_v1.json"
        self.progress_path = state_dir / "fmp_archive_enrichment_progress_v1.json"
        self.validation_path = state_dir / "fmp_archive_enrichment_validation_v1.json"
        self.lineage_path = state_dir / "fmp_archive_enrichment_request_lineage_v1.jsonl"
        self.context_path = state_dir / "fmp_archive_enrichment_context_v1.jsonl.gz"
        self.db_path = state_dir / "ai_trading_memory.db"
        self.key, self.key_source = resolve_fmp_key()
        if not self.key:
            raise ArchiveStop("missing_fmp_api_key")
        self.governor = RateGovernor(calls_per_minute)
        self.payload_ceiling_bytes = ENRICHMENT_PAYLOAD_CEILING_BYTES
        self.request_limit = ENRICHMENT_REQUEST_LIMIT
        self.started_at = now_iso()
        self.stop_reason = ""
        self.malformed_streak = 0
        self.progress = self._load_progress()
        self._ensure_paths()
        restore_manifest_verification(self.manifest, self.context_path)
        self._ensure_manifest_file()
        self._ensure_identity_table()
        self._db_size_before = self.db_path.stat().st_size if self.db_path.exists() else 0

    def _ensure_paths(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.lineage_path.exists():
            self.lineage_path.touch()

    def _load_progress(self) -> dict[str, Any]:
        existing = read_json(self.progress_path, {})
        symbols = [row["symbol"] for row in self.manifest]
        if not isinstance(existing, dict) or existing.get("manifest_symbols") != symbols:
            existing = {}
        existing.setdefault("schema_version", "fmp_archive_enrichment_progress_v1")
        existing.setdefault("status", "NOT_STARTED")
        existing.setdefault("started_at", self.started_at)
        existing.setdefault("updated_at", now_iso())
        existing.setdefault("manifest_symbols", symbols)
        existing.setdefault("completed_symbols", [])
        existing.setdefault("per_symbol", {})
        existing.setdefault("continuity_families", {})
        existing.setdefault("endpoint_gaps", [])
        existing.setdefault("total_api_calls", 0)
        existing.setdefault("total_retries", 0)
        existing.setdefault("total_payload_bytes", 0)
        existing.setdefault("errors", [])
        existing.setdefault("request_count_by_family", {})
        existing.setdefault("record_count_by_family", {})
        existing.setdefault("rows_inserted", 0)
        existing.setdefault("duplicate_rows", 0)
        return existing

    def _save_progress(self) -> None:
        self.progress["updated_at"] = now_iso()
        atomic_json_write(self.progress_path, self.progress)

    def _ensure_manifest_file(self) -> None:
        atomic_json_write(
            self.manifest_path,
            {
                "schema_version": "fmp_archive_enrichment_manifest_v1",
                "generated_at": now_iso(),
                "provider": IDENTITY_PROVIDER,
                "target_symbol_count": len(self.manifest),
                "source_policy": "bounded_verified_etf_regime_set",
                "symbols": self.manifest,
                "hard_limits": {
                    "target_calls_per_minute": TARGET_CALLS_PER_MINUTE,
                    "absolute_calls_per_minute": MAX_CALLS_PER_MINUTE,
                    "max_additional_payload_bytes": ENRICHMENT_PAYLOAD_CEILING_BYTES,
                    "max_retry_per_request": MAX_RETRIES_PER_REQUEST,
                },
            },
        )

    def _ensure_identity_table(self) -> None:
        if not self.db_path.exists():
            raise ArchiveStop("canonical_historical_database_missing")
        with sqlite3.connect(str(self.db_path), timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {IDENTITY_TABLE} (
                    continuity_id TEXT PRIMARY KEY,
                    old_symbol TEXT NOT NULL DEFAULT '',
                    new_symbol TEXT NOT NULL DEFAULT '',
                    company_name TEXT,
                    effective_date TEXT,
                    event_type TEXT NOT NULL,
                    exchange TEXT,
                    active_status TEXT,
                    reason TEXT,
                    cik TEXT,
                    isin TEXT,
                    cusip TEXT,
                    source TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    confidence TEXT,
                    ambiguity_state TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _persist_manifest_status(self, symbol: str, **changes: Any) -> None:
        row = self.manifest_by_symbol[symbol]
        row.update(changes)
        self._ensure_manifest_file()

    def _family_context(self, family: str, symbol: str, endpoint: str, params: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        if rows:
            self._append_context(family, symbol, rows, endpoint=endpoint, params=params, retrieved_at=now_iso())

    def _store_identity_records(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        inserted = 0
        with sqlite3.connect(str(self.db_path), timeout=30.0) as conn:
            conn.execute("PRAGMA busy_timeout=30000")
            for row in records:
                existing = conn.execute(
                    f"""
                    SELECT 1 FROM {IDENTITY_TABLE}
                    WHERE old_symbol=? AND new_symbol=? AND event_type=?
                      AND COALESCE(effective_date, '')=COALESCE(?, '')
                    LIMIT 1
                    """,
                    (row["old_symbol"], row["new_symbol"], row["event_type"], row["effective_date"]),
                ).fetchone()
                if existing:
                    continue
                cursor = conn.execute(
                    f"""
                    INSERT OR IGNORE INTO {IDENTITY_TABLE}
                    (continuity_id,old_symbol,new_symbol,company_name,effective_date,event_type,exchange,active_status,reason,cik,isin,cusip,source,retrieved_at,confidence,ambiguity_state)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    tuple(row.get(key) for key in (
                        "continuity_id", "old_symbol", "new_symbol", "company_name", "effective_date",
                        "event_type", "exchange", "active_status", "reason", "cik", "isin", "cusip",
                        "source", "retrieved_at", "confidence", "ambiguity_state",
                    )),
                )
                inserted += int(bool(cursor.rowcount))
            conn.commit()
        return inserted

    def _collect_continuity_family(self, family: str, endpoint: str, event_type: str, params: dict[str, Any]) -> None:
        if self.progress.get("continuity_families", {}).get(family):
            return
        rows, meta = self._request(family=family, symbol="", endpoint=endpoint, params=params)
        self._family_context(family, "", endpoint, params, rows)
        normalized = [normalize_identity_record(row, event_type, now_iso()) for row in rows]
        self._store_identity_records(normalized)
        if meta.get("error"):
            self.progress.setdefault("endpoint_gaps", []).append({"family": family, "endpoint": endpoint, "error": meta["error"]})
        self.progress.setdefault("continuity_families", {})[family] = True
        self._save_progress()

    def _process_etf(self, symbol: str) -> None:
        profile_rows, profile_meta = self._request(family="etf_profile", symbol=symbol, endpoint="/stable/profile", params={"symbol": symbol})
        self._family_context("etf_profile", symbol, "/stable/profile", {"symbol": symbol}, profile_rows)
        profile = profile_rows[0] if profile_rows else {}
        verified = verified_etf_profile(profile)
        self._persist_manifest_status(
            symbol,
            verified_is_etf=verified,
            profile_fields=sorted(profile.keys()),
            profile_status="VERIFIED_ETF" if verified else "NOT_VERIFIED",
        )
        if not verified:
            self._persist_manifest_status(symbol, status="NOT_VERIFIED")
            return
        daily = self._daily_for_symbol(symbol)
        self._family_context("etf_dividends", symbol, "/stable/dividends", {"symbol": symbol}, self._request(family="etf_dividends", symbol=symbol, endpoint="/stable/dividends", params={"symbol": symbol})[0])
        self._family_context("etf_splits", symbol, "/stable/splits", {"symbol": symbol}, self._request(family="etf_splits", symbol=symbol, endpoint="/stable/splits", params={"symbol": symbol})[0])
        self._persist_manifest_status(
            symbol,
            status="COMPLETE" if daily.get("status") == "SUCCESS" else "HISTORY_UNAVAILABLE",
            daily_status=daily.get("status"),
            daily_earliest_date=daily.get("earliest_date"),
            daily_latest_date=daily.get("latest_date"),
        )

    def run(self) -> dict[str, Any]:
        self.progress["status"] = "RUNNING"
        self._save_progress()
        try:
            completed = set(self.progress.get("completed_symbols") or [])
            for row in self.manifest:
                symbol = row["symbol"]
                if symbol in completed:
                    continue
                self._guard_runtime()
                self.progress.setdefault("per_symbol", {})[symbol] = {"started_at": now_iso(), "status": "RUNNING"}
                self._process_etf(symbol)
                self.progress["per_symbol"][symbol].update({"status": "COMPLETE", "completed_at": now_iso()})
                self.progress.setdefault("completed_symbols", []).append(symbol)
                self._save_progress()
            self._collect_continuity_family("symbol_changes", SYMBOL_CHANGE_ENDPOINT, "SYMBOL_CHANGE", {})
            self._collect_continuity_family("delistings", DELISTED_ENDPOINT, "DELISTING", {"limit": 5000})
            self.progress["status"] = "COMPLETE"
        except ArchiveStop as exc:
            self.stop_reason = str(exc)
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = self.stop_reason
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": self.stop_reason})
        except Exception as exc:  # Preserve checkpoint even on an unexpected archive-only failure.
            self.stop_reason = f"unexpected_archive_error:{type(exc).__name__}:{str(exc)[:160]}"
            self.progress["status"] = "PARTIAL_STOPPED"
            self.progress["stop_reason"] = self.stop_reason
            self.progress.setdefault("errors", []).append({"timestamp": now_iso(), "error": self.stop_reason})
        self.progress["finished_at"] = now_iso()
        self._save_progress()
        return self.validation()

    def validation(self, *, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> dict[str, Any]:
        verified_symbols = [row["symbol"] for row in self.manifest if row.get("verified_is_etf")]
        by_symbol: list[dict[str, Any]] = []
        if verified_symbols and self.db_path.exists():
            placeholders = ",".join("?" for _ in verified_symbols)
            with open_current_read_only(self.db_path) as conn:
                rows = conn.execute(
                    f"SELECT symbol,COUNT(*) n,MIN(ts),MAX(ts) FROM historical_market_bars WHERE provider='FMP_HIST' AND asset_type='stock' AND timeframe='1Day' AND symbol IN ({placeholders}) GROUP BY symbol",
                    verified_symbols,
                ).fetchall()
            for symbol, count, minimum, maximum in rows:
                by_symbol.append({
                    "symbol": symbol,
                    "rows": int(count),
                    "earliest_date": datetime.fromtimestamp(int(minimum), UTC).date().isoformat() if minimum is not None else None,
                    "latest_date": datetime.fromtimestamp(int(maximum), UTC).date().isoformat() if maximum is not None else None,
                })
        context_counts: dict[str, int] = {}
        if self.context_path.exists():
            with gzip.open(self.context_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        family = str((json.loads(line) or {}).get("family") or "unknown")
                        context_counts[family] = context_counts.get(family, 0) + 1
                    except (ValueError, TypeError):
                        continue
        identity_summary = {"symbol_changes": 0, "delistings": 0, "inactive": 0, "mappings_with_effective_dates": 0, "ambiguous": 0}
        examples: list[dict[str, Any]] = []
        if self.db_path.exists():
            with open_current_read_only(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                for event_type, key in (("SYMBOL_CHANGE", "symbol_changes"), ("DELISTING", "delistings")):
                    identity_summary[key] = int(conn.execute(f"SELECT COUNT(*) FROM {IDENTITY_TABLE} WHERE event_type=?", (event_type,)).fetchone()[0])
                identity_summary["inactive"] = int(conn.execute(f"SELECT COUNT(*) FROM {IDENTITY_TABLE} WHERE active_status='INACTIVE'").fetchone()[0])
                identity_summary["mappings_with_effective_dates"] = int(conn.execute(f"SELECT COUNT(*) FROM {IDENTITY_TABLE} WHERE event_type='SYMBOL_CHANGE' AND ambiguity_state='VALIDATED' AND effective_date IS NOT NULL").fetchone()[0])
                identity_summary["ambiguous"] = int(conn.execute(f"SELECT COUNT(*) FROM {IDENTITY_TABLE} WHERE ambiguity_state='AMBIGUOUS'").fetchone()[0])
                examples = [dict(row) for row in conn.execute(f"SELECT old_symbol,new_symbol,company_name,effective_date,event_type FROM {IDENTITY_TABLE} WHERE ambiguity_state='VALIDATED' ORDER BY effective_date LIMIT 5")]
        parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        duration = None
        if self.progress.get("started_at") and self.progress.get("finished_at"):
            duration = round(parse(self.progress["finished_at"]) - parse(self.progress["started_at"]), 3)
        validation = {
            "schema_version": "fmp_archive_enrichment_validation_v1",
            "status": self.progress.get("status"),
            "scope_status": "COMPLETE_WITH_ENDPOINT_GAPS" if self.progress.get("endpoint_gaps") else "COMPLETE",
            "generated_at": now_iso(),
            "started_at": self.progress.get("started_at"),
            "finished_at": self.progress.get("finished_at"),
            "runtime_duration_seconds": duration,
            "etf": {
                "symbols_targeted": len(self.manifest),
                "symbols_processed": len(self.progress.get("completed_symbols") or []),
                "verified_etfs": len(verified_symbols),
                "daily_rows": sum(row["rows"] for row in by_symbol),
                "earliest_history": min((row["earliest_date"] for row in by_symbol if row.get("earliest_date")), default=None),
                "latest_history": max((row["latest_date"] for row in by_symbol if row.get("latest_date")), default=None),
                "over_10_years": sum(1 for row in by_symbol if row.get("earliest_date") and (datetime.now(UTC).date() - datetime.fromisoformat(row["earliest_date"]).date()).days > 3650),
                "over_20_years": sum(1 for row in by_symbol if row.get("earliest_date") and (datetime.now(UTC).date() - datetime.fromisoformat(row["earliest_date"]).date()).days > 7300),
                "category_coverage": dict(collections.Counter(row["category"] for row in self.manifest if row.get("verified_is_etf"))),
                "metadata_coverage": sum(1 for row in self.manifest if row.get("profile_status") == "VERIFIED_ETF"),
                "corporate_actions": {"dividends": context_counts.get("etf_dividends", 0), "splits": context_counts.get("etf_splits", 0)},
                "top_by_depth": sorted(by_symbol, key=lambda row: (row.get("earliest_date") or "9999-12-31", -row["rows"]))[:20],
                "unsupported_or_not_verified": [row["symbol"] for row in self.manifest if not row.get("verified_is_etf")],
            },
            "symbol_continuity": {
                **identity_summary,
                "record_counts_from_provider": {
                    "symbol_changes": self.progress.get("record_count_by_family", {}).get("symbol_changes", 0),
                    "delistings": self.progress.get("record_count_by_family", {}).get("delistings", 0),
                },
                "continuity_examples": examples,
                "unsupported_or_missing_endpoints": list(self.progress.get("endpoint_gaps") or []),
            },
            "api_calls": safe_int(self.progress.get("total_api_calls")),
            "measured_payload_bytes": safe_int(self.progress.get("total_payload_bytes")),
            "measured_payload_gb_decimal": round(safe_int(self.progress.get("total_payload_bytes")) / 1_000_000_000, 9),
            "retries": safe_int(self.progress.get("total_retries")),
            "errors": list(self.progress.get("errors") or [])[-20:],
            "request_count_by_family": dict(self.progress.get("request_count_by_family") or {}),
            "duplicate_rows_skipped": safe_int(self.progress.get("duplicate_rows")),
            "checkpoint_state": {
                "status": self.progress.get("status"),
                "completed_symbols": len(self.progress.get("completed_symbols") or []),
                "continuity_families": dict(self.progress.get("continuity_families") or {}),
            },
            "archive_storage": {
                "canonical_database": str(self.db_path),
                "historical_table": "historical_market_bars",
                "identity_table": IDENTITY_TABLE,
                "database_bytes_before": self._db_size_before,
                "database_bytes_after": self.db_path.stat().st_size if self.db_path.exists() else 0,
                "context_path": str(self.context_path),
                "lineage_path": str(self.lineage_path),
                "historical_evidence_separate_from_broker_truth": True,
            },
            "runtime_protection": {
                "before": before,
                "after": after,
                "worker_restart_requested": False,
                "backend_restart_requested": False,
                "broker_actions_caused": 0,
                "crypto_route_unchanged": True,
            },
            "truth_safety": {
                "broker_truth_untouched": True,
                "fabricated_identity": False,
                "fabricated_lifecycle_or_truth": False,
                "historical_evidence_separate": True,
            },
        }
        atomic_json_write(self.validation_path, validation)
        return validation


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded FMP ETF and identity enrichment")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--calls-per-minute", type=int, default=TARGET_CALLS_PER_MINUTE)
    args = parser.parse_args()
    state_dir = Path(args.state_dir).expanduser().resolve()
    manifest = build_enrichment_manifest()
    before = make_before_after_snapshot(state_dir, label="BEFORE")
    runner = EnrichmentRunner(state_dir=state_dir, manifest=manifest, calls_per_minute=min(args.calls_per_minute, MAX_CALLS_PER_MINUTE))
    runner.progress.setdefault("before_snapshot", before)
    validation = runner.run()
    after = make_before_after_snapshot(state_dir, label="AFTER")
    validation["runtime_protection"] = {
        "before": before,
        "after": after,
        "worker_pid_same": before.get("worker_pid") == after.get("worker_pid"),
        "worker_count_before": before.get("worker_count"),
        "worker_count_after": after.get("worker_count"),
        "resource_before": before.get("resource_state"),
        "resource_after": after.get("resource_state"),
        "last_error_before": before.get("last_error"),
        "last_error_after": after.get("last_error"),
        "worker_restart_requested": False,
        "backend_restart_requested": False,
        "broker_actions_caused": 0,
        "crypto_route_unchanged": True,
    }
    atomic_json_write(runner.validation_path, validation)
    print(json.dumps({
        "status": validation.get("status"),
        "scope_status": validation.get("scope_status"),
        "etfs_targeted": validation.get("etf", {}).get("symbols_targeted"),
        "etfs_verified": validation.get("etf", {}).get("verified_etfs"),
        "daily_rows": validation.get("etf", {}).get("daily_rows"),
        "api_calls": validation.get("api_calls"),
        "payload_bytes": validation.get("measured_payload_bytes"),
        "symbol_changes": validation.get("symbol_continuity", {}).get("symbol_changes"),
        "delistings": validation.get("symbol_continuity", {}).get("delistings"),
        "stop_reason": runner.stop_reason,
        "validation_path": str(runner.validation_path),
    }, sort_keys=True))
    return 0 if validation.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
