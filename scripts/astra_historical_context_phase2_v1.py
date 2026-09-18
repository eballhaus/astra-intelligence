#!/usr/bin/env python3
"""Resumable, historical-only context pipeline for Astra Phase 2.

This supervisor deliberately owns no trading, lifecycle, broker, truth, or
live-learning authority.  It either reads existing local archives or records a
bounded provider gap.  One child and one stage are active at a time.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERSION = "1.0.0"
DEFAULT_STATE_DIR = Path("/Users/Shared/AstraRuntime/state")
PIPELINE_NAME = "ASTRA_HISTORICAL_CONTEXT_PHASE2_V1"
OUTPUT_DIRNAME = "historical_context_phase2_v1"
LOG_FILENAME = "astra_historical_context_phase2_v1.log"
PID_FILENAME = "astra_historical_context_phase2_v1.pid"
MAX_LOCAL_SYMBOLS_PER_CHILD = 50
MARKET_HOURS_LOCAL_SYMBOLS_PER_CHILD = 10
POLL_SECONDS = 2.0
RELAUNCH_DELAY_SECONDS = 15.0
TERMINAL = {"COMPLETE", "COMPLETE_WITH_SUPPORTED_GAPS", "COMPLETE_NO_GAP", "PROVIDER_REQUIRED", "FAILED_INTEGRITY"}

STAGES: tuple[tuple[int, str, str], ...] = (
    (1, "SEC_POINT_IN_TIME_FILINGS", "sec_filings_context_v1.jsonl"),
    (2, "HISTORICAL_NEWS_CATALYSTS", "catalyst_timeline_v1.jsonl"),
    (3, "ANALYST_EXPECTATIONS_REVISIONS", "analyst_expectations_v1.jsonl"),
    (4, "OPTIONS_VOLATILITY_HISTORY", "volatility_context_v1.jsonl"),
    (5, "MARKET_MICROSTRUCTURE_HISTORY", "microstructure_context_v1.jsonl"),
    (6, "EXECUTION_REALISM_COST_MODEL", "execution_realism_v1.jsonl"),
    (7, "SHORT_OWNERSHIP_POSITIONING", "ownership_context_v1.jsonl"),
    (8, "CROSS_ASSET_REGIME_CONTEXT", "cross_asset_context_v1.jsonl"),
    (9, "CRYPTO_INSTITUTIONAL_CONTEXT", "crypto_context_v1.jsonl"),
    (10, "HISTORICAL_REGIME_INTELLIGENCE", "regime_features_v1.jsonl"),
    (11, "CROSS_LANE_FEATURE_STORE", "historical_feature_store_v1.jsonl"),
    (12, "INSTITUTIONAL_REPLAY_WALK_FORWARD", "replay_validation_v1.jsonl"),
    (13, "HISTORICAL_STRATEGY_ATTRIBUTION", "strategy_attribution_v1.jsonl"),
    (14, "HISTORICAL_LEARNING_COMPRESSION_V2", "learning_compression_v2.jsonl"),
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def market_hours_now() -> bool:
    local = datetime.now(ZoneInfo("America/New_York"))
    return local.weekday() < 5 and (local.hour, local.minute) >= (9, 30) and (local.hour, local.minute) < (16, 0)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def state_path(state_dir: Path) -> Path:
    return state_dir / "astra_historical_context_phase2_v1.json"


def log_path(state_dir: Path) -> Path:
    return state_dir / LOG_FILENAME


def pid_path(state_dir: Path) -> Path:
    return state_dir / PID_FILENAME


def checkpoint_path(state_dir: Path, stage: int) -> Path:
    return state_dir / f"astra_historical_context_phase2_v1_stage_{stage:02d}_progress.json"


def output_path(state_dir: Path, stage: int) -> Path:
    filename = dict((number, output) for number, _name, output in STAGES)[stage]
    return state_dir / OUTPUT_DIRNAME / filename


def stage_name(stage: int) -> str:
    return dict((number, name) for number, name, _output in STAGES)[stage]


def manifest_symbols(state_dir: Path) -> list[str]:
    """Use only established local universes; never invent a symbol list."""
    candidates: set[str] = set()
    for filename in (
        "fmp_intraday_archive_compression_v1_1hour_manifest.json",
        "fmp_archive_tier3_tier4_manifest_v1.json",
        "broad_universe_intake_promotion_v1.json",
    ):
        payload = read_json(state_dir / filename, {})
        rows = payload.get("symbols") if isinstance(payload, dict) else []
        if not rows and isinstance(payload, dict):
            rows = payload.get("eligible_rows") or payload.get("alpaca_symbols") or []
        for row in rows or []:
            symbol = str(row.get("symbol") if isinstance(row, dict) else row or "").strip().upper()
            if symbol and "/" not in symbol and len(symbol) <= 10:
                candidates.add(symbol)
    return sorted(candidates)


def worker_health(state_dir: Path) -> dict[str, Any]:
    runtime = read_json(state_dir / "astra_worker_runtime_state_v1.json", {})
    resource = runtime.get("resource") if isinstance(runtime.get("resource"), dict) else {}
    pid = runtime.get("active_worker_pid") or runtime.get("process_id")
    return {
        "worker_pid": pid,
        "worker_present": bool(runtime.get("active_worker_present")) and bool(pid),
        "worker_count": 1 if runtime.get("active_worker_present") and pid else 0,
        "resource_state": runtime.get("resource_state") or resource.get("resource_state") or "UNKNOWN",
        "last_error": runtime.get("last_error") or "",
        "cycle_count": runtime.get("cycle_count"),
        "cycle_elapsed_seconds": runtime.get("cycle_elapsed_seconds"),
        "source_identity": runtime.get("source_identity") or runtime.get("runtime_source_identity"),
        "updated_at": runtime.get("updated_at") or runtime.get("heartbeat_at"),
    }


def worker_safe(state_dir: Path) -> bool:
    health = worker_health(state_dir)
    return (
        health["worker_count"] == 1
        and health["resource_state"] not in {"RESOURCE_ELEVATED", "RESOURCE_CRITICAL", "RESOURCE_HIGH"}
        and not health["last_error"]
    )


def safety_fields() -> dict[str, Any]:
    return {
        "historical_replay_only": True,
        "execution_authority": "DISABLED",
        "broker_actions_added": 0,
        "truth_records_added": 0,
        "learning_acknowledgements_added": 0,
        "capacity_mutations": 0,
        "live_trading_changed": False,
        "source_provenance_required": True,
        "lookahead_rejected": True,
    }


def initial_stage_checkpoint(state_dir: Path, stage: int) -> dict[str, Any]:
    path = checkpoint_path(state_dir, stage)
    existing = read_json(path, {})
    if isinstance(existing, dict) and existing.get("stage") == stage:
        if stage in {4, 5, 6, 8} and existing.get("status") == "COMPLETE" and not existing.get("provider_required"):
            existing["status"] = "COMPLETE_WITH_SUPPORTED_GAPS"
            existing["provider_required"] = {
                4: ["historical implied-volatility, skew, term-structure and options open-interest provider"],
                5: ["historical true quote/trade microstructure provider; OHLCV proxy only"],
                6: ["historical quote-level transaction-cost observations; modelled replay-only proxy used"],
                8: ["additional point-in-time cross-asset event context beyond existing local archive"],
            }[stage]
            existing["updated_at"] = now_iso()
            atomic_json(path, existing)
        return existing
    payload = {
        "schema_version": "astra_historical_context_phase2_stage_v1",
        "pipeline": PIPELINE_NAME,
        "stage": stage,
        "stage_name": stage_name(stage),
        "status": "PENDING",
        "started_at": None,
        "updated_at": now_iso(),
        "symbols_targeted": 0,
        "symbols_completed": 0,
        "next_index": 0,
        "records_written": 0,
        "duplicates": 0,
        "invalid_records": 0,
        "chronology_failures": 0,
        "lookahead_violations": 0,
        "api_calls": 0,
        "retries": 0,
        "payload_bytes": 0,
        "provider_required": [],
        "errors": [],
        "last_successful_key": None,
        "output_path": str(output_path(state_dir, stage)),
        **safety_fields(),
    }
    atomic_json(path, payload)
    return payload


def base_state(state_dir: Path) -> dict[str, Any]:
    existing = read_json(state_path(state_dir), {})
    if isinstance(existing, dict) and existing.get("pipeline") == PIPELINE_NAME:
        return existing
    statuses = {str(number): "PENDING" for number, _name, _output in STAGES}
    return {
        "schema_version": "astra_historical_context_phase2_v1",
        "pipeline": PIPELINE_NAME,
        "version": VERSION,
        "status": "STARTING",
        "current_stage": 1,
        "current_stage_name": stage_name(1),
        "stage_statuses": statuses,
        "stage_checkpoints": {str(number): str(checkpoint_path(state_dir, number)) for number, _name, _output in STAGES},
        "child_pid": None,
        "restart_count": 0,
        "last_error": "",
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "completed_at": None,
        "resource_state": "UNKNOWN",
        "worker_health": {},
        **safety_fields(),
    }


def update_state(state_dir: Path, payload: Mapping[str, Any]) -> None:
    value = dict(payload)
    value["updated_at"] = now_iso()
    atomic_json(state_path(state_dir), value)


def log_event(state_dir: Path, event: str, **fields: Any) -> None:
    record = {"at": now_iso(), "event": event, **fields}
    path = log_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")


def append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
            count += 1
    return count


def sec_stage(state_dir: Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Fetch only the existing bounded SEC adapter contract when identified."""
    user_agent = os.getenv("ASTRA_SEC_USER_AGENT") or os.getenv("SEC_USER_AGENT")
    symbols = manifest_symbols(state_dir)
    checkpoint["symbols_targeted"] = len(symbols)
    if not user_agent:
        checkpoint["status"] = "PROVIDER_REQUIRED"
        checkpoint["provider_required"] = ["ASTRA_SEC_USER_AGENT for SEC EDGAR identification and submissions"]
        checkpoint["errors"] = ["SEC provider identification is not configured in this environment"]
        checkpoint["updated_at"] = now_iso()
        atomic_json(checkpoint_path(state_dir, 1), checkpoint)
        return checkpoint
    from engine.provider_router import ProviderRouter

    router = ProviderRouter()
    index = int(checkpoint.get("next_index") or 0)
    completed = set(checkpoint.get("completed_keys") or [])
    rows: list[dict[str, Any]] = []
    for symbol in symbols[index : index + MAX_LOCAL_SYMBOLS_PER_CHILD]:
        try:
            result = router.fetch_sec_company_context(symbol)
            compact = {
                "schema_version": "astra_sec_pit_context_v1",
                "symbol": symbol,
                "source": "SEC_EDGAR",
                "retrieved_at": result.get("retrieved_at") or now_iso(),
                "response_state": result.get("response_state"),
                "record_id": result.get("record_id"),
                "cik": result.get("cik"),
                "normalized_fields": result.get("normalized_fields") or {},
                "filing_provenance": result.get("filing_provenance") or {},
                **safety_fields(),
            }
            rows.append(compact)
            completed.add(symbol)
            checkpoint["last_successful_key"] = symbol
        except Exception as exc:  # bounded provider gap, never a trading error
            checkpoint.setdefault("errors", []).append(f"{symbol}:{type(exc).__name__}")
        checkpoint["api_calls"] = int(checkpoint.get("api_calls") or 0) + 1
    append_jsonl(output_path(state_dir, 1), rows)
    checkpoint["completed_keys"] = sorted(completed)
    checkpoint["symbols_completed"] = len(completed)
    checkpoint["next_index"] = min(len(symbols), index + MAX_LOCAL_SYMBOLS_PER_CHILD)
    checkpoint["records_written"] = int(checkpoint.get("records_written") or 0) + len(rows)
    checkpoint["status"] = "COMPLETE" if checkpoint["next_index"] >= len(symbols) else "RUNNING"
    checkpoint["updated_at"] = now_iso()
    atomic_json(checkpoint_path(state_dir, 1), checkpoint)
    return checkpoint


def local_bar_rows(state_dir: Path, symbols: list[str], *, timeframe: str = "1Day") -> dict[str, list[tuple[Any, ...]]]:
    db_path = state_dir / "ai_trading_memory.db"
    if not db_path.exists() or not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    query = (
        "SELECT symbol,ts,o,h,l,c,v FROM historical_market_bars "
        "WHERE asset_type='stock' AND timeframe=? AND symbol IN (" + placeholders + ") "
        "ORDER BY symbol,ts"
    )
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0) as conn:
            result: dict[str, list[tuple[Any, ...]]] = {symbol: [] for symbol in symbols}
            for row in conn.execute(query, (timeframe, *symbols)):
                result.setdefault(str(row[0]), []).append(tuple(row[1:]))
            return result
    except sqlite3.Error:
        return {}


def derived_local_stage(state_dir: Path, stage: int, checkpoint: dict[str, Any]) -> dict[str, Any]:
    symbols = manifest_symbols(state_dir)
    checkpoint["symbols_targeted"] = len(symbols)
    index = int(checkpoint.get("next_index") or 0)
    batch_size = MARKET_HOURS_LOCAL_SYMBOLS_PER_CHILD if market_hours_now() else MAX_LOCAL_SYMBOLS_PER_CHILD
    batch = symbols[index : index + batch_size]
    bars = local_bar_rows(state_dir, batch)
    if not bars and batch:
        checkpoint["status"] = "COMPLETE_WITH_SUPPORTED_GAPS"
        checkpoint["provider_required"] = ["readable local historical_market_bars snapshot for derived local context"]
        checkpoint["errors"] = ["local archive unavailable or locked; no synthetic records created"]
        checkpoint["next_index"] = len(symbols)
        checkpoint["updated_at"] = now_iso()
        atomic_json(checkpoint_path(state_dir, stage), checkpoint)
        return checkpoint

    output_rows: list[dict[str, Any]] = []
    completed = int(checkpoint.get("symbols_completed") or 0)
    for symbol in batch:
        rows = bars.get(symbol) or []
        closes = [float(row[4]) for row in rows if row[4] is not None and float(row[4]) > 0]
        highs = [float(row[2]) for row in rows if row[2] is not None and float(row[2]) > 0]
        lows = [float(row[3]) for row in rows if row[3] is not None and float(row[3]) > 0]
        volumes = [float(row[5]) for row in rows if row[5] is not None and float(row[5]) >= 0]
        returns = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1] > 0]
        realized = math.sqrt(sum(value * value for value in returns[-20:])) * 100.0 if returns else None
        range_pct = ((max(highs) / min(lows)) - 1.0) * 100.0 if highs and lows and min(lows) > 0 else None
        common = {
            "schema_version": "astra_historical_context_feature_v1",
            "symbol": symbol,
            "source_timestamp": rows[-1][0] if rows else None,
            "calculation_version": VERSION,
            "lane_applicability": ["SCALP", "DAY", "SWING"],
            "quality": "DERIVED_LOCALLY" if rows else "NO_LOCAL_DATA",
            "provenance": {"provider": "FMP_HIST_LOCAL_ARCHIVE", "table": "historical_market_bars", "timeframe": "1Day"},
            **safety_fields(),
        }
        if stage == 4:
            output_rows.append({**common, "feature": "realized_volatility_20d_pct", "value": realized, "method": "RMS_COMPLETED_DAILY_RETURNS"})
        elif stage == 5:
            output_rows.append({**common, "feature": "intraday_liquidity_proxy", "value": (sum(volumes[-20:]) / len(volumes[-20:])) if volumes else None, "method": "DERIVED_OHLCV_PROXY", "quote_data": "NOT_AVAILABLE"})
            output_rows.append({**common, "feature": "range_behavior_20d_pct", "value": range_pct, "method": "DERIVED_OHLCV_PROXY", "quote_data": "NOT_AVAILABLE"})
        elif stage == 6:
            spread_proxy = max(0.0, (range_pct or 0.0) * 0.10)
            output_rows.append({**common, "feature": "modelled_execution_cost_pct", "value": spread_proxy, "method": "MODELLED_OHLCV_VOLATILITY_LIQUIDITY_PROXY", "execution_authority": "REPLAY_ONLY"})
        elif stage == 8:
            output_rows.append({**common, "feature": "cross_asset_context_available", "value": bool(rows), "method": "LOCAL_ARCHIVE_INVENTORY_ONLY"})
        elif stage == 10:
            trend = (closes[-1] / closes[0] - 1.0) * 100.0 if len(closes) >= 2 and closes[0] > 0 else None
            label = "TRENDING" if trend is not None and abs(trend) >= 5.0 else "RANGE_OR_INSUFFICIENT_CONTEXT"
            output_rows.append({**common, "feature": "deterministic_regime_label", "value": label, "method": "BOUNDED_20D_DAILY_RETURN_AND_RANGE", "numeric_context": {"trend_pct": trend, "realized_volatility_pct": realized}})
        completed += 1

    append_jsonl(output_path(state_dir, stage), output_rows)
    checkpoint["symbols_completed"] = completed
    checkpoint["next_index"] = min(len(symbols), index + len(batch))
    checkpoint["records_written"] = int(checkpoint.get("records_written") or 0) + len(output_rows)
    checkpoint["last_successful_key"] = batch[-1] if batch else checkpoint.get("last_successful_key")
    checkpoint["status"] = "COMPLETE" if checkpoint["next_index"] >= len(symbols) else "RUNNING"
    if stage in {4, 5, 6, 8} and checkpoint["status"] == "COMPLETE":
        checkpoint["status"] = "COMPLETE_WITH_SUPPORTED_GAPS"
        checkpoint["provider_required"] = {
            4: ["historical implied-volatility, skew, term-structure and options open-interest provider"],
            5: ["historical true quote/trade microstructure provider; OHLCV proxy only"],
            6: ["historical quote-level transaction-cost observations; modelled replay-only proxy used"],
            8: ["additional point-in-time cross-asset event context beyond existing local archive"],
        }[stage]
    checkpoint["updated_at"] = now_iso()
    atomic_json(checkpoint_path(state_dir, stage), checkpoint)
    return checkpoint


def feature_store_stage(state_dir: Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    """Consolidate Phase 2 feature outputs into one provenance-backed view."""
    source_stages = (4, 5, 6, 8, 10)
    output = output_path(state_dir, 11)
    seen: set[str] = set()
    if output.exists():
        for line in output.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
                seen.add(str(row.get("feature_id") or ""))
            except ValueError:
                continue
    rows: list[dict[str, Any]] = []
    for source_stage in source_stages:
        source = output_path(state_dir, source_stage)
        if not source.exists():
            continue
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    source_row = json.loads(line)
                except ValueError:
                    continue
                feature = str(source_row.get("feature") or "")
                symbol = str(source_row.get("symbol") or "")
                if not feature or not symbol:
                    continue
                feature_id = hashlib.sha256(f"{symbol}|{feature}|{source_row.get('source_timestamp')}|{source_stage}".encode()).hexdigest()
                if feature_id in seen:
                    continue
                seen.add(feature_id)
                rows.append({
                    "schema_version": "astra_historical_feature_store_v1",
                    "feature_id": feature_id,
                    "symbol": symbol,
                    "timestamp": source_row.get("source_timestamp"),
                    "feature": feature,
                    "value": source_row.get("value"),
                    "provenance": source_row.get("provenance") or {},
                    "source_timestamp": source_row.get("source_timestamp"),
                    "calculation_version": source_row.get("calculation_version") or VERSION,
                    "lane_applicability": source_row.get("lane_applicability") or [],
                    "quality": source_row.get("quality"),
                    **safety_fields(),
                })
    written = append_jsonl(output, rows)
    checkpoint["records_written"] = int(checkpoint.get("records_written") or 0) + written
    checkpoint["status"] = "COMPLETE_WITH_SUPPORTED_GAPS"
    checkpoint["provider_required"] = ["feature availability is limited to supported local Phase 2 outputs"]
    checkpoint["updated_at"] = now_iso()
    atomic_json(checkpoint_path(state_dir, 11), checkpoint)
    return checkpoint


def rearm_stage(state_dir: Path, stage: int) -> dict[str, Any]:
    """Re-arm only an explicitly requested provider-gap stage."""
    if stage != 1:
        raise ValueError("only SEC Stage 1 may be explicitly re-armed")
    if not (os.getenv("ASTRA_SEC_USER_AGENT") or os.getenv("SEC_USER_AGENT")):
        raise ValueError("ASTRA_SEC_USER_AGENT is required before Stage 1 can be re-armed")
    checkpoint = initial_stage_checkpoint(state_dir, stage)
    checkpoint["status"] = "PENDING"
    checkpoint["provider_required"] = []
    checkpoint["errors"] = []
    checkpoint["updated_at"] = now_iso()
    atomic_json(checkpoint_path(state_dir, stage), checkpoint)
    return checkpoint


def provider_gap_stage(state_dir: Path, stage: int, checkpoint: dict[str, Any]) -> dict[str, Any]:
    gaps = {
        2: "authorized historical news/catalyst provider contract is not present; current Finnhub adapter is bounded live context",
        3: "point-in-time analyst revision history adapter is not present",
        7: "historical short/ownership time series beyond existing SEC/local subsets is not present",
        9: "crypto funding/open-interest/liquidation history adapter is not present",
    }
    checkpoint["status"] = "PROVIDER_REQUIRED"
    checkpoint["provider_required"] = [gaps[stage]]
    checkpoint["updated_at"] = now_iso()
    atomic_json(checkpoint_path(state_dir, stage), checkpoint)
    return checkpoint


def delegated_stage(state_dir: Path, stage: int, checkpoint: dict[str, Any]) -> dict[str, Any]:
    existing = {
        11: "existing historical evidence/compression interfaces remain canonical; Phase 2 outputs are additive and provenance-backed",
        12: "existing replay/counterfactual architecture remains the execution-free consumer; no duplicate replay engine created",
        13: "existing historical learning/attribution owners remain canonical; no live-policy mutation permitted",
        14: "existing Librarian/Teacher/compression owners remain canonical; raw Phase 2 outputs remain drill-down sources",
    }
    checkpoint["status"] = "COMPLETE_WITH_SUPPORTED_GAPS"
    checkpoint["delegated_to_existing_owner"] = existing[stage]
    checkpoint["updated_at"] = now_iso()
    atomic_json(checkpoint_path(state_dir, stage), checkpoint)
    return checkpoint


def run_child(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = initial_stage_checkpoint(state_dir, args.stage)
    if checkpoint.get("status") in TERMINAL:
        return 0
    if not checkpoint.get("started_at"):
        checkpoint["started_at"] = now_iso()
    checkpoint["status"] = "RUNNING"
    atomic_json(checkpoint_path(state_dir, args.stage), checkpoint)
    if args.stage == 1:
        result = sec_stage(state_dir, checkpoint)
    elif args.stage in {2, 3, 7, 9}:
        result = provider_gap_stage(state_dir, args.stage, checkpoint)
    elif args.stage in {4, 5, 6, 8, 10}:
        result = derived_local_stage(state_dir, args.stage, checkpoint)
    elif args.stage == 11:
        result = feature_store_stage(state_dir, checkpoint)
    else:
        result = delegated_stage(state_dir, args.stage, checkpoint)
    print(json.dumps({"stage": args.stage, "status": result.get("status"), "next_index": result.get("next_index"), "records_written": result.get("records_written")}, sort_keys=True))
    return 0


def supervisor(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "astra_historical_context_phase2_v1.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 2
        pid_path(state_dir).write_text(str(os.getpid()), encoding="ascii")
        log_event(state_dir, "SUPERVISOR_STARTED", pid=os.getpid(), checkpoint_root=str(state_dir))
        state = base_state(state_dir)
        state["supervisor_pid"] = os.getpid()
        state["log_path"] = str(log_path(state_dir))
        state["pid_path"] = str(pid_path(state_dir))
        # Normalize older terminal checkpoints before selecting the next stage;
        # this changes only status metadata, never historical records.
        for number, _name, _output in STAGES:
            normalized = initial_stage_checkpoint(state_dir, number)
            state["stage_statuses"][str(number)] = normalized.get("status") or "PENDING"
        if args.resume_stage is not None:
            try:
                rearm_stage(state_dir, args.resume_stage)
            except ValueError as exc:
                state["status"] = "PROVIDER_REQUIRED"
                state["last_error"] = str(exc)
                update_state(state_dir, state)
                log_event(state_dir, "RESUME_REFUSED", stage=args.resume_stage, reason=str(exc))
                return 3
            state["stage_statuses"][str(args.resume_stage)] = "PENDING"
            state["current_stage"] = args.resume_stage
            state["current_stage_name"] = stage_name(args.resume_stage)
            state["status"] = "RUNNING"
            log_event(state_dir, "STAGE_REARMED", stage=args.resume_stage)
        update_state(state_dir, state)
        stopped = False

        def stop(_signum: int, _frame: object) -> None:
            nonlocal stopped
            stopped = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while not stopped:
            health = worker_health(state_dir)
            state["worker_health"] = health
            state["resource_state"] = health["resource_state"]
            state["market_hours_mode"] = market_hours_now()
            if not worker_safe(state_dir):
                state["status"] = "RESOURCE_PAUSED_SAFE"
                state["last_error"] = "worker health/resource guard did not permit historical child"
                state["child_pid"] = None
                update_state(state_dir, state)
                log_event(state_dir, "PAUSED_RESOURCE_GUARD", worker_health=health)
                time.sleep(30.0)
                continue
            stage = next((number for number, _name, _output in STAGES if state["stage_statuses"].get(str(number)) not in TERMINAL), None)
            if stage is None:
                state["status"] = "PHASE2_COMPLETE"
                state["completed_at"] = state.get("completed_at") or now_iso()
                state["child_pid"] = None
                update_state(state_dir, state)
                log_event(state_dir, "PIPELINE_COMPLETE")
                break
            state["status"] = "RUNNING"
            state["current_stage"] = stage
            state["current_stage_name"] = stage_name(stage)
            checkpoint = initial_stage_checkpoint(state_dir, stage)
            state["stage_statuses"][str(stage)] = checkpoint.get("status") or "PENDING"
            update_state(state_dir, state)
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", "--stage", str(stage), "--state-dir", str(state_dir)], cwd=str(ROOT))
            state["child_pid"] = child.pid
            update_state(state_dir, state)
            log_event(state_dir, "CHILD_STARTED", stage=stage, child_pid=child.pid, checkpoint=str(checkpoint_path(state_dir, stage)))
            while child.poll() is None and not stopped:
                time.sleep(POLL_SECONDS)
                health = worker_health(state_dir)
                if health["resource_state"] in {"RESOURCE_ELEVATED", "RESOURCE_CRITICAL", "RESOURCE_HIGH"} or health["last_error"]:
                    child.terminate()
                    state["status"] = "RESOURCE_PAUSED_SAFE"
                    state["last_error"] = "worker health changed while phase2 child was running"
                    break
                state["worker_health"] = health
                update_state(state_dir, state)
            if child.poll() is None:
                child.wait(timeout=10)
            cp = read_json(checkpoint_path(state_dir, stage), {})
            stage_status = str(cp.get("status") or "FAILED_INTEGRITY")
            state["stage_statuses"][str(stage)] = stage_status
            state["child_pid"] = None
            if child.returncode not in (0, None):
                state["last_error"] = f"stage_{stage}_child_exit_{child.returncode}"
                state["status"] = "INTEGRITY_FAILURE"
                update_state(state_dir, state)
                log_event(state_dir, "CHILD_FAILED", stage=stage, exit_code=child.returncode)
                break
            state["last_error"] = ""
            log_event(state_dir, "CHILD_CHECKPOINTED", stage=stage, status=stage_status, records_written=cp.get("records_written", 0))
            update_state(state_dir, state)
            if not stopped:
                time.sleep(RELAUNCH_DELAY_SECONDS)
        state["child_pid"] = None
        update_state(state_dir, state)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Astra historical/context Phase 2 supervisor")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--stage", type=int, choices=range(1, 15))
    parser.add_argument("--resume-stage", type=int, choices=(1,), default=None)
    args = parser.parse_args(argv)
    if args.child:
        if args.stage is None:
            parser.error("--child requires --stage")
        return run_child(args)
    return supervisor(args)


if __name__ == "__main__":
    raise SystemExit(main())
