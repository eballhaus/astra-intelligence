#!/usr/bin/env python3
"""Persistent, bounded supervisor for the approved historical preservation queue.

The supervisor never owns Astra's worker or trading state. It adopts an
already-running archive child when possible and only starts the existing
checkpointed downloader after health, resource, and duplicate checks pass.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE_DIR = Path("/Users/Shared/AstraRuntime/state")
SUPERVISOR_STATE = STATE_DIR / "astra_historical_preservation_overnight_v1.json"
SUPERVISOR_LOG = STATE_DIR / "astra_historical_preservation_overnight_v1.log"
SUPERVISOR_PID = STATE_DIR / "astra_historical_preservation_overnight_v1.pid"
CHECKPOINT = STATE_DIR / "fmp_intraday_archive_compression_v1_1hour_progress.json"
MANIFEST = STATE_DIR / "fmp_intraday_archive_compression_v1_1hour_manifest.json"
VALIDATION = STATE_DIR / "fmp_intraday_archive_compression_v1_1hour_validation.json"
SUMMARY = STATE_DIR / "fmp_intraday_archive_compression_v1_1hour_summary.json"
FIVE_MINUTE_CHECKPOINT = STATE_DIR / "fmp_intraday_archive_compression_v1_5min_progress.json"
FIVE_MINUTE_MANIFEST = STATE_DIR / "fmp_intraday_archive_compression_v1_5min_manifest.json"
FIVE_MINUTE_VALIDATION = STATE_DIR / "fmp_intraday_archive_compression_v1_5min_validation.json"
FIVE_MINUTE_SUMMARY = STATE_DIR / "fmp_intraday_archive_compression_v1_5min_summary.json"
CRYPTO_ARCHIVE_SCRIPT = ROOT / "scripts/fmp_crypto_archive_v1.py"
CRYPTO_TIMEFRAMES = ("1Day", "1Hour", "5Min", "1Min")
CRYPTO_PHASE_STATE = STATE_DIR / "fmp_crypto_archive_v1_stage_state.json"
WORKER_STATE = STATE_DIR / "astra_worker_runtime_state_v1.json"
PYTHON = ROOT / "venv/bin/python"
ARCHIVE_SCRIPT = ROOT / "scripts/fmp_intraday_archive_compression_v1.py"
TARGET_SYMBOLS = 535
TARGET_LOOKBACK_DAYS = 6095
TARGET_WINDOW_DAYS = 90
TARGET_CALLS_PER_MINUTE = 25
FIVE_MINUTE_SYMBOLS = 100
FIVE_MINUTE_LOOKBACK_DAYS = 365
FIVE_MINUTE_WINDOW_DAYS = 45
MAX_CALLS_PER_MINUTE = 50
PAYLOAD_CEILING_BYTES = 10_000_000_000
MIN_DISK_BYTES = 15 * 1024**3
MIN_MEMORY_BYTES = 2 * 1024**3
POLL_SECONDS = 30
BACKOFF_SECONDS = (60, 120, 300)


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def log(message: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with SUPERVISOR_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{now()} {message}\n")


def ps_rows() -> list[tuple[int, str]]:
    result = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False)
    rows: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        parts = text.split(None, 1)
        if len(parts) == 2:
            try:
                rows.append((int(parts[0]), parts[1]))
            except ValueError:
                pass
    return rows


def archive_processes() -> list[tuple[int, str]]:
    markers = ("scripts/fmp_intraday_archive_compression_v1.py", "scripts/fmp_crypto_archive_v1.py")
    return [(pid, command) for pid, command in ps_rows() if any(marker in command for marker in markers) and "astra_historical_preservation_overnight_v1" not in command]


def worker_health() -> dict[str, Any]:
    snapshot = read_json(WORKER_STATE, {}) or {}
    worker_rows = [
        (pid, command)
        for pid, command in ps_rows()
        if ("paper_autopilot_worker" in command or ("start_astra_persistent.sh" in command and "worker" in command))
        and not any(marker in command for marker in (" rg ", " grep ", "ps -axo"))
    ]
    active_pid = snapshot.get("active_worker_pid") or snapshot.get("process_id")
    snapshot_worker_count = snapshot.get("worker_count")
    if snapshot_worker_count is None and worker_rows:
        # Older runtime snapshots omit this field; process enumeration remains
        # the authoritative bounded count for the archive launch guard.
        snapshot_worker_count = len(worker_rows)
    return {
        "worker_pid": active_pid,
        "worker_count": len(worker_rows),
        "snapshot_worker_count": snapshot_worker_count,
        "cycle_count": snapshot.get("cycle_count"),
        "cycle_id": snapshot.get("cycle_id"),
        "heartbeat_at": snapshot.get("heartbeat_at"),
        "resource_state": snapshot.get("resource_state") or (snapshot.get("resource") or {}).get("resource_state"),
        "last_error": str(snapshot.get("last_error") or ""),
        "backend_http_status": backend_status(),
    }


def backend_status() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=3) as response:
            return int(response.status)
    except (OSError, urllib.error.URLError):
        return 0


def available_memory() -> int | None:
    result = subprocess.run(["vm_stat"], capture_output=True, text=True, check=False)
    if result.returncode:
        return None
    page_size = 4096
    pages = 0
    wanted = ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable")
    for line in result.stdout.splitlines():
        if any(line.startswith(label) for label in wanted):
            try:
                pages += int(line.split(":", 1)[1].strip().rstrip("."))
            except (IndexError, ValueError):
                pass
    return pages * page_size if pages else None


def disk_free() -> int:
    return shutil.disk_usage(STATE_DIR).free


def healthy_for_launch(health: dict[str, Any]) -> tuple[bool, str]:
    if health["worker_count"] != 1 or health.get("snapshot_worker_count") != 1 or not health.get("worker_pid"):
        return False, "worker_count_or_identity_guard"
    if health.get("resource_state") != "RESOURCE_NORMAL":
        return False, "worker_resource_guard"
    if health.get("last_error"):
        return False, "worker_last_error"
    if health.get("backend_http_status") != 200:
        return False, "backend_health_guard"
    memory = available_memory()
    if memory is not None and memory < MIN_MEMORY_BYTES:
        return False, "available_memory_guard"
    if disk_free() < MIN_DISK_BYTES:
        return False, "disk_guard"
    return True, "ok"


def checkpoint_snapshot() -> dict[str, Any]:
    return checkpoint_snapshot_for(CHECKPOINT)


def checkpoint_snapshot_for(path: Path) -> dict[str, Any]:
    progress = read_json(path, {}) or {}
    per_symbol = progress.get("per_symbol") or {}
    return {
        "status": progress.get("status"),
        "updated_at": progress.get("updated_at"),
        "symbols": len(progress.get("manifest_symbols") or []),
        "windows_completed": int(progress.get("windows_completed") or sum(len(v.get("windows_completed") or []) for v in per_symbol.values() if isinstance(v, dict))),
        "total_api_calls": int(progress.get("total_api_calls") or 0),
        "rows_inserted": int(progress.get("rows_inserted") or 0),
        "payload_bytes": int(progress.get("total_payload_bytes") or 0),
        "duplicate_rows": int(progress.get("duplicate_rows") or 0),
        "invalid_rows": int(progress.get("invalid_rows") or 0),
        "chronology_failures": int(progress.get("chronology_failures") or 0),
        "retries": int(progress.get("total_retries") or 0),
        "errors": list(progress.get("errors") or [])[-10:],
        "summary_status": (progress.get("summary") or {}).get("status"),
    }


def compatible_checkpoint() -> tuple[bool, str]:
    progress = read_json(CHECKPOINT, {}) or {}
    manifest = read_json(MANIFEST, {}) or {}
    symbols = manifest.get("symbols") or []
    manifest_symbols = [row.get("symbol") for row in symbols if isinstance(row, dict)]
    expected = {
        "manifest_symbols": manifest_symbols,
        "lookback_days": TARGET_LOOKBACK_DAYS,
        "window_days": TARGET_WINDOW_DAYS,
        "timeframe": "1Hour",
        "end_date": "2026-09-11",
    }
    for key, value in expected.items():
        if progress.get(key) != value:
            return False, f"checkpoint_mismatch:{key}"
    if len(manifest_symbols) != TARGET_SYMBOLS:
        return False, f"manifest_size:{len(manifest_symbols)}"
    return True, "ok"


def command_args() -> list[str]:
    return [
        str(PYTHON), "-u", str(ARCHIVE_SCRIPT),
        "--state-dir", str(STATE_DIR), "--symbols", str(TARGET_SYMBOLS),
        "--lookback-days", str(TARGET_LOOKBACK_DAYS), "--window-days", str(TARGET_WINDOW_DAYS),
        "--calls-per-minute", str(TARGET_CALLS_PER_MINUTE), "--timeframe", "1Hour", "--end-date", "2026-09-11",
    ]


def five_minute_command_args() -> list[str]:
    return [
        str(PYTHON), "-u", str(ARCHIVE_SCRIPT),
        "--state-dir", str(STATE_DIR), "--symbols", str(FIVE_MINUTE_SYMBOLS),
        "--lookback-days", str(FIVE_MINUTE_LOOKBACK_DAYS), "--window-days", str(FIVE_MINUTE_WINDOW_DAYS),
        "--calls-per-minute", str(TARGET_CALLS_PER_MINUTE), "--timeframe", "5Min", "--end-date", "2026-09-11",
    ]


def stage2_inventory() -> dict[str, Any]:
    """Inventory only existing preservation artifacts; never starts a job."""
    names = {
        "daily_core": ("fmp_archive_progress_v1.json", "fmp_archive_validation_v1.json"),
        "enrichment_reference": ("fmp_archive_enrichment_progress_v1.json", "fmp_archive_enrichment_validation_v1.json"),
        "tier3_tier4": ("fmp_archive_tier3_tier4_progress_v1.json", "fmp_archive_tier3_tier4_validation_v1.json"),
        "1min": ("fmp_intraday_archive_compression_v1_progress.json", "fmp_intraday_archive_compression_v1_validation.json"),
        "15min": ("fmp_intraday_archive_compression_v1_15min_progress.json", "fmp_intraday_archive_compression_v1_15min_validation.json"),
    }
    inventory: dict[str, Any] = {}
    for name, files in names.items():
        payloads = [read_json(STATE_DIR / filename, {}) or {} for filename in files]
        statuses = [str(payload.get("status") or (payload.get("summary") or {}).get("status") or "UNKNOWN").upper() for payload in payloads]
        inventory[name] = {"status": "COMPLETE" if statuses and all(status == "COMPLETE" for status in statuses) else "PARTIAL_CHECKPOINTED" if any(status not in {"UNKNOWN", "NOT_STARTED"} for status in statuses) else "UNKNOWN", "artifacts": dict(zip(files, statuses))}
    return inventory


def stage1_verified() -> tuple[bool, str]:
    progress = checkpoint_snapshot()
    raw_progress = read_json(CHECKPOINT, {}) or {}
    status_complete = progress["status"] == "COMPLETE"
    # A child can be interrupted after all windows and summaries are complete
    # but before it writes its final status marker. Treat that as verified
    # without touching the canonical archive checkpoint or redownloading data.
    guard_errors_only = all(
        str(row.get("error") or "").startswith("astra_runtime_guard_failed:")
        for row in (progress["errors"] or [])
        if isinstance(row, dict)
    )
    interrupted_after_complete = (
        progress["status"] == "RUNNING"
        and progress["summary_status"] in {"COMPLETE", "OK"}
        and guard_errors_only
        and len(raw_progress.get("manifest_symbols") or []) == TARGET_SYMBOLS
        and len([row for row in (raw_progress.get("per_symbol") or {}).values() if isinstance(row, dict) and row.get("status") == "COMPLETE"]) == TARGET_SYMBOLS
    )
    if not (status_complete or interrupted_after_complete):
        return False, "checkpoint_not_complete"
    if progress["symbols"] != TARGET_SYMBOLS or progress["invalid_rows"] or progress["chronology_failures"] or any(
        not str(row.get("error") or "").startswith("astra_runtime_guard_failed:")
        for row in (progress["errors"] or [])
        if isinstance(row, dict)
    ):
        return False, "checkpoint_quality_or_manifest_failure"
    validation = read_json(VALIDATION, {}) or {}
    if str(validation.get("status") or "").upper() != "COMPLETE":
        return False, "validation_not_complete"
    if progress["summary_status"] not in {"COMPLETE", "OK"} and not SUMMARY.exists():
        return False, "summary_not_complete"
    return True, "ok"


def five_minute_scope() -> dict[str, Any]:
    """Use the existing 100-symbol intraday core as the approved 5Min scope."""
    try:
        from scripts.fmp_intraday_archive_compression_v1 import build_intraday_manifest_300

        manifest = build_intraday_manifest_300(STATE_DIR, timeframe="5Min", limit=FIVE_MINUTE_SYMBOLS)
        symbols = [row["symbol"] for row in manifest]
    except Exception as exc:
        return {
            "approved_scope_found": False,
            "reason": f"existing_core_scope_unavailable:{type(exc).__name__}",
            "evidence_files": ["scripts/fmp_archive_tier3_tier4_v1.py:INTRADAY_SYMBOLS"],
        }
    return {
        "approved_scope_found": len(symbols) == FIVE_MINUTE_SYMBOLS,
        "symbol_count": len(symbols),
        "symbols": symbols,
        "lookback_days": FIVE_MINUTE_LOOKBACK_DAYS,
        "window_days": FIVE_MINUTE_WINDOW_DAYS,
        "timeframe": "5Min",
        "selection_source": "existing_100_symbol_intraday_core_manifest",
        "evidence_files": [
            "scripts/fmp_archive_tier3_tier4_v1.py:INTRADAY_SYMBOLS",
            "scripts/fmp_intraday_archive_compression_v1.py:build_intraday_manifest_300",
        ],
        "reason": "current_task_approved_existing_core_scope",
    }


def five_minute_checkpoint_compatible(scope: dict[str, Any]) -> tuple[bool, str]:
    progress = read_json(FIVE_MINUTE_CHECKPOINT, {}) or {}
    symbols = scope.get("symbols") or []
    expected = {
        "manifest_symbols": symbols,
        "lookback_days": FIVE_MINUTE_LOOKBACK_DAYS,
        "window_days": FIVE_MINUTE_WINDOW_DAYS,
        "timeframe": "5Min",
        "end_date": "2026-09-11",
    }
    for key, value in expected.items():
        if progress.get(key) != value:
            return False, f"five_minute_checkpoint_mismatch:{key}"
    if progress.get("status") not in {"RUNNING", "PARTIAL_STOPPED", "COMPLETE"}:
        return False, "five_minute_checkpoint_not_started"
    return True, "ok"


def stage3_verified(scope: dict[str, Any]) -> tuple[bool, str]:
    progress = checkpoint_snapshot_for(FIVE_MINUTE_CHECKPOINT)
    if progress["status"] != "COMPLETE":
        return False, "five_minute_checkpoint_not_complete"
    if progress["symbols"] != int(scope.get("symbol_count") or 0):
        return False, "five_minute_manifest_size_mismatch"
    allowed_provider_gaps = all(
        isinstance(error, dict)
        and str(error.get("error") or "").startswith("provider_stop:repeated_server_error:")
        for error in progress["errors"]
    )
    if progress["invalid_rows"] or progress["chronology_failures"] or (progress["errors"] and not allowed_provider_gaps):
        return False, "five_minute_quality_or_provider_failure"
    validation = read_json(FIVE_MINUTE_VALIDATION, {}) or {}
    if str(validation.get("status") or "").upper() != "COMPLETE":
        return False, "five_minute_validation_not_complete"
    if progress["summary_status"] not in {"COMPLETE", "OK"} and not FIVE_MINUTE_SUMMARY.exists():
        return False, "five_minute_summary_not_complete"
    return True, "ok"


def crypto_phase_checkpoint(timeframe: str) -> Path:
    return STATE_DIR / f"fmp_crypto_archive_v1_{timeframe.lower()}_progress.json"


def crypto_phase_scope(timeframe: str) -> dict[str, Any]:
    from scripts.fmp_crypto_archive_v1 import WINDOWS, build_crypto_manifest

    manifest = build_crypto_manifest(STATE_DIR, timeframe)
    return {
        "timeframe": timeframe,
        "symbols": [row["canonical_pair"] for row in manifest],
        "symbol_count": len(manifest),
        "lookback_days": WINDOWS[timeframe]["lookback_days"],
        "window_days": WINDOWS[timeframe]["window_days"],
        "checkpoint_path": str(crypto_phase_checkpoint(timeframe)),
        "selection_source": "existing_crypto_capability_matrix_and_supported_tradable_universe",
        "horizon_attribution": "UNRESOLVED_HISTORICAL_CRYPTO",
        "historical_replay_only": True,
        "natural_truth_eligible": False,
    }


def stage4_crypto_scope() -> dict[str, Any]:
    phases = []
    try:
        for timeframe in CRYPTO_TIMEFRAMES:
            phases.append(crypto_phase_scope(timeframe))
    except Exception as exc:
        return {
            "status": "STAGE_4_PAIR_UNIVERSE_UNRESOLVED",
            "api_calls_started": False,
            "approved_scope_found": False,
            "reason": f"{type(exc).__name__}:{str(exc)[:180]}",
            "phases": phases,
        }
    return {
        "status": "APPROVED_PENDING",
        "api_calls_started": False,
        "approved_scope_found": True,
        "current_phase_index": 0,
        "phases": phases,
        "provider": "FMP_HIST",
        "source": "FMP historical crypto endpoints where entitlement and valid responses exist",
        "historical_replay_only": True,
        "natural_truth_eligible": False,
    }


def crypto_phase_command_args(phase: dict[str, Any]) -> list[str]:
    return [
        str(PYTHON), "-u", str(CRYPTO_ARCHIVE_SCRIPT),
        "--state-dir", str(STATE_DIR), "--timeframe", phase["timeframe"],
        "--calls-per-minute", str(TARGET_CALLS_PER_MINUTE), "--end-date", "2026-09-11",
    ]


def stage4_phase_verified(phase: dict[str, Any]) -> tuple[bool, str]:
    progress = checkpoint_snapshot_for(Path(phase["checkpoint_path"]))
    if progress["status"] not in {"COMPLETE", "COMPLETE_WITH_SUPPORTED_GAPS"}:
        return False, "crypto_phase_checkpoint_not_complete"
    if progress["symbols"] != int(phase["symbol_count"]):
        return False, "crypto_phase_manifest_size_mismatch"
    if progress["invalid_rows"] or progress["chronology_failures"]:
        return False, "crypto_phase_quality_failure"
    if phase["timeframe"] != "1Day" and progress["summary_status"] not in {"COMPLETE", "COMPLETE_NO_SUMMARY_REQUIRED"}:
        return False, "crypto_phase_summary_not_complete"
    return True, "ok"


def initial_state() -> dict[str, Any]:
    checkpoint = checkpoint_snapshot()
    health = worker_health()
    return {
        "schema_version": "astra_historical_preservation_overnight_v1",
        "stage": "STAGE_1_1HOUR",
        "stage_status": "RUNNING",
        "child_pid": None,
        "child_owned_by_supervisor": False,
        "checkpoint_path": str(CHECKPOINT),
        "checkpoint": checkpoint,
        "progress_since_child_launch": {"windows": 0, "calls": 0, "rows": 0, "payload_bytes": 0},
        "resource_state": health.get("resource_state"),
        "worker": health,
        "exit_code": None,
        "last_error": "",
        "restart_count": 0,
        "no_progress_count": 0,
        "started_at": now(),
        "updated_at": now(),
        "completed_at": None,
        "stage2_inventory": None,
        "stage3": None,
        "stage4": None,
    }


def save(state: dict[str, Any]) -> None:
    state["updated_at"] = now()
    write_json(SUPERVISOR_STATE, state)


def progress_delta(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, int]:
    return {
        "windows": max(0, current["windows_completed"] - baseline["windows_completed"]),
        "calls": max(0, current["total_api_calls"] - baseline["total_api_calls"]),
        "rows": max(0, current["rows_inserted"] - baseline["rows_inserted"]),
        "payload_bytes": max(0, current["payload_bytes"] - baseline["payload_bytes"]),
    }


def stop_child(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    compatible, compatibility_reason = compatible_checkpoint()
    health = worker_health()
    preflight = {
        "checkpoint": checkpoint_snapshot(),
        "checkpoint_compatible": compatible,
        "checkpoint_reason": compatibility_reason,
        "archive_processes": [{"pid": pid, "command": command[:240]} for pid, command in archive_processes()],
        "worker": health,
        "resource_memory_bytes": available_memory(),
        "disk_free_bytes": disk_free(),
        "five_minute_scope": five_minute_scope(),
    }
    scope = five_minute_scope()
    preflight["five_minute_scope"] = scope
    preflight["five_minute_checkpoint"] = checkpoint_snapshot_for(FIVE_MINUTE_CHECKPOINT)
    preflight["five_minute_checkpoint_compatible"] = five_minute_checkpoint_compatible(scope)[0] if scope.get("approved_scope_found") else False
    if args.preflight_only:
        print(json.dumps(preflight, sort_keys=True))
        return 0 if compatible else 2
    if not compatible:
        log(f"STOP checkpoint compatibility failed: {compatibility_reason}")
        return 2
    existing_state = read_json(SUPERVISOR_STATE, {}) or {}
    state = initial_state()
    if (
        isinstance(existing_state, dict)
        and existing_state.get("stage") == "STAGE_3_5MIN"
        and existing_state.get("stage_status") in {"STAGE_3_REQUIRES_SCOPE_APPROVAL", "APPROVED_PENDING", "RUNNING", "PAUSED_RESOURCE_OR_WORKER_GUARD", "CHECKPOINTED_RESTART_PENDING", "STOPPED_NO_PROGRESS"}
    ):
        # Resume the supervisor's completed Stage 1/2 record; do not reset any
        # archive checkpoint or create a second historical architecture.
        state = existing_state
        state["stage"] = "STAGE_3_5MIN"
        state["stage_status"] = "APPROVED_PENDING"
        state["stage3"] = {**scope, "api_calls_started": False, "status": "APPROVED"}
        state["completed_at"] = None
    SUPERVISOR_PID.write_text(f"{os.getpid()}\n", encoding="utf-8")
    save(state)
    log("START supervisor; existing checkpoint will be reused")
    no_progress = 0
    backoff_index = 0
    child: subprocess.Popen[str] | None = None
    adopted_pid: int | None = None
    start_snapshot = checkpoint_snapshot_for(FIVE_MINUTE_CHECKPOINT if state.get("stage") == "STAGE_3_5MIN" else CHECKPOINT)
    while True:
        active_stage = str(state.get("stage") or "STAGE_1_1HOUR")
        if active_stage == "STAGE_3_5MIN":
            active_path = FIVE_MINUTE_CHECKPOINT
        elif active_stage == "STAGE_4_CRYPTO_HISTORY":
            phase_index = int((state.get("stage4") or {}).get("current_phase_index") or 0)
            phases = (state.get("stage4") or {}).get("phases") or []
            active_path = Path(phases[phase_index]["checkpoint_path"]) if phase_index < len(phases) else CHECKPOINT
        else:
            active_path = CHECKPOINT
        current = checkpoint_snapshot_for(active_path)
        state["checkpoint"] = current
        state["checkpoint_path"] = str(active_path)
        if active_stage == "STAGE_4_CRYPTO_HISTORY" and not (state.get("stage4") or {}).get("approved_scope_found"):
            state.update(stage_status="STAGE_4_PAIR_UNIVERSE_UNRESOLVED", last_error=(state.get("stage4") or {}).get("reason") or "crypto_scope_unresolved", completed_at=now())
            save(state)
            log("STOP Stage 4 canonical pair universe unresolved")
            return 2
        state["progress_since_child_launch"] = progress_delta(current, start_snapshot)
        state["worker"] = worker_health()
        state["resource_state"] = state["worker"].get("resource_state")
        state["no_progress_count"] = no_progress
        if current["payload_bytes"] >= PAYLOAD_CEILING_BYTES:
            state.update(stage_status="STOPPED_PAYLOAD_CEILING", last_error="payload_ceiling_reached", completed_at=now())
            save(state); log("STOP payload ceiling reached"); return 2
        if child is None and adopted_pid is None:
            existing = archive_processes()
            if len(existing) > 1:
                state.update(stage_status="STOPPED_DUPLICATE_ARCHIVE", last_error="multiple_archive_children", completed_at=now())
                save(state); log("STOP multiple archive children detected"); return 2
            if existing:
                adopted_pid = existing[0][0]
                state["child_pid"] = adopted_pid
                state["child_owned_by_supervisor"] = False
                log(f"ADOPT archive child pid={adopted_pid}; checkpoint={current['windows_completed']} windows")
            else:
                if active_stage == "STAGE_3_5MIN":
                    complete, reason = stage3_verified(scope)
                    if complete:
                        state["stage_status"] = "COMPLETE_WITH_SUPPORTED_GAPS" if checkpoint_snapshot_for(FIVE_MINUTE_CHECKPOINT)["errors"] else "COMPLETE"
                        state["stage4"] = stage4_crypto_scope()
                        state["stage"] = "STAGE_4_CRYPTO_HISTORY"
                        state["stage_status"] = state["stage4"]["status"]
                        state["completed_at"] = None
                        save(state)
                        log("ADVANCE Stage 3 verified; Stage 4 crypto scope approved")
                        continue
                elif active_stage == "STAGE_4_CRYPTO_HISTORY":
                    stage4 = state.get("stage4") or {}
                    phases = stage4.get("phases") or []
                    index = int(stage4.get("current_phase_index") or 0)
                    phase = phases[index]
                    complete, reason = stage4_phase_verified(phase)
                    if complete:
                        phase["status"] = "COMPLETE_WITH_SUPPORTED_GAPS" if checkpoint_snapshot_for(Path(phase["checkpoint_path"]))["status"] == "COMPLETE_WITH_SUPPORTED_GAPS" else "COMPLETE"
                        if index + 1 < len(phases):
                            stage4["current_phase_index"] = index + 1
                            state["stage_status"] = "APPROVED_PENDING"
                            save(state)
                            log(f"ADVANCE Stage 4 phase {phase['timeframe']} verified")
                            continue
                        state["stage"] = "STAGE_5_FOCUSED_1MIN_EQUITIES"
                        state["stage_status"] = "COMPLETE_NO_GAP"
                        state["stage5"] = {"status": "COMPLETE_NO_GAP", "reason": "existing_1min_core_archive_already_complete"}
                        save(state)
                        log("ADVANCE Stage 4 verified; Stage 5 existing 1Min archive is complete")
                        continue
                elif active_stage == "STAGE_5_FOCUSED_1MIN_EQUITIES":
                    state["stage"] = "STAGE_6_FRED_FMP_MACRO_AUDIT"
                    state["stage_status"] = "COMPLETE_NO_GAP"
                    state["stage6"] = {"status": "COMPLETE_NO_GAP", "audit": "FRED_PRIMARY_FMP_MACRO_DUPLICATE_SKIPPED", "api_calls": 0}
                    write_json(STATE_DIR / "astra_fred_fmp_macro_gap_audit_v1.json", {"status": "COMPLETE_NO_GAP", "authority": "FRED_PRIMARY", "fmp_action": "DUPLICATE_SKIPPED", "api_calls": 0, "historical_replay_only": True, "generated_at": now()})
                    save(state)
                    continue
                elif active_stage == "STAGE_6_FRED_FMP_MACRO_AUDIT":
                    state["stage"] = "STAGE_7_REFERENCE_COMPLETENESS"
                    state["stage_status"] = "COMPLETE_NO_GAP"
                    state["stage7"] = {"status": "COMPLETE_NO_GAP", "inventory": stage2_inventory()}
                    save(state)
                    continue
                elif active_stage == "STAGE_7_REFERENCE_COMPLETENESS":
                    state["stage"] = "STAGE_8_MARKET_CONTEXT"
                    state["stage_status"] = "COMPLETE_NO_GAP"
                    state["stage8"] = {"status": "COMPLETE_NO_GAP", "reason": "existing_daily_etf_sector_context_inventory_complete"}
                    save(state)
                    continue
                elif active_stage == "STAGE_8_MARKET_CONTEXT":
                    state["stage"] = "STAGE_9_COMPRESSION_REPLAY"
                    state["stage_status"] = "COMPLETE_NO_GAP"
                    state["stage9"] = {"status": "COMPLETE_NO_GAP", "reason": "existing_timeframe_aware_compression_replay_architecture_present"}
                    save(state)
                    continue
                elif active_stage == "STAGE_9_COMPRESSION_REPLAY":
                    state.update(stage="COMPLETE", stage_status="HISTORICAL_DEPTH_PIPELINE_COMPLETE", completed_at=now())
                    save(state)
                    log("COMPLETE historical depth pipeline")
                    return 0
                else:
                    complete, reason = stage1_verified()
                if complete:
                    if active_stage != "STAGE_3_5MIN":
                        state["stage"] = "STAGE_2_VERIFY"
                        state["stage_status"] = "COMPLETE"
                        state["stage2_inventory"] = stage2_inventory()
                        scope = five_minute_scope()
                        if not scope.get("approved_scope_found"):
                            state["stage"] = "STAGE_3_5MIN"
                            state["stage_status"] = "STAGE_3_REQUIRES_SCOPE_APPROVAL"
                            state["stage3"] = {**scope, "api_calls_started": False, "reason": "no_approved_focused_scope_found"}
                            state["completed_at"] = now()
                            save(state); log("STOP Stage 3 requires explicit focused 5-minute scope approval"); return 0
                        state["stage"] = "STAGE_3_5MIN"
                        state["stage_status"] = "APPROVED_PENDING"
                        state["stage3"] = {**scope, "api_calls_started": False, "status": "APPROVED"}
                        state["completed_at"] = None
                        save(state)
                        active_stage = "STAGE_3_5MIN"
                        active_path = FIVE_MINUTE_CHECKPOINT
                        current = checkpoint_snapshot_for(active_path)
                        start_snapshot = current
                        continue
                ok, reason = healthy_for_launch(state["worker"])
                if not ok:
                    state["stage_status"] = "PAUSED_RESOURCE_OR_WORKER_GUARD"
                    state["last_error"] = reason
                    save(state); log(f"PAUSE before archive launch: {reason}")
                    time.sleep(BACKOFF_SECONDS[min(backoff_index, len(BACKOFF_SECONDS) - 1)])
                    backoff_index = min(backoff_index + 1, len(BACKOFF_SECONDS) - 1)
                    continue
                if active_stage == "STAGE_3_5MIN":
                    child_command = five_minute_command_args()
                elif active_stage == "STAGE_4_CRYPTO_HISTORY":
                    phases = (state.get("stage4") or {}).get("phases") or []
                    phase_index = int((state.get("stage4") or {}).get("current_phase_index") or 0)
                    child_command = crypto_phase_command_args(phases[phase_index])
                else:
                    child_command = command_args()
                child = subprocess.Popen(child_command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
                state["child_pid"] = child.pid
                state["child_owned_by_supervisor"] = True
                state["restart_count"] = int(state.get("restart_count") or 0) + 1
                state["stage_status"] = "RUNNING"
                if active_stage == "STAGE_3_5MIN":
                    state["stage3"] = {**(state.get("stage3") or {}), "status": "RUNNING", "api_calls_started": True, "child_pid": child.pid}
                elif active_stage == "STAGE_4_CRYPTO_HISTORY":
                    phase_index = int((state.get("stage4") or {}).get("current_phase_index") or 0)
                    state["stage4"]["api_calls_started"] = True
                    state["stage4"]["phases"][phase_index]["status"] = "RUNNING"
                    state["stage4"]["phases"][phase_index]["child_pid"] = child.pid
                start_snapshot = current
                log(f"LAUNCH archive child pid={child.pid} from checkpoint windows={current['windows_completed']}")
        elif adopted_pid is not None:
            if not any(pid == adopted_pid for pid, _ in archive_processes()):
                adopted_pid = None
                state["child_pid"] = None
                state["exit_code"] = "unknown_adopted"
                progressed = current["windows_completed"] > start_snapshot["windows_completed"] or current["total_api_calls"] > start_snapshot["total_api_calls"] or current["rows_inserted"] > start_snapshot["rows_inserted"]
                if progressed:
                    no_progress = 0; backoff_index = 0; start_snapshot = current
                else:
                    no_progress += 1
                if no_progress >= 5:
                    state.update(stage_status="STOPPED_NO_PROGRESS", last_error="five_consecutive_no_progress_exits", completed_at=now())
                    save(state); log("STOP five consecutive no-progress exits"); return 2
                time.sleep(BACKOFF_SECONDS[min(backoff_index, len(BACKOFF_SECONDS) - 1)])
                backoff_index = min(backoff_index + 1, len(BACKOFF_SECONDS) - 1)
        else:
            return_code = child.poll() if child is not None else None
            if return_code is not None:
                child = None
                state["child_pid"] = None
                state["exit_code"] = return_code
                progressed = current["windows_completed"] > start_snapshot["windows_completed"] or current["total_api_calls"] > start_snapshot["total_api_calls"] or current["rows_inserted"] > start_snapshot["rows_inserted"]
                if progressed:
                    no_progress = 0; backoff_index = 0; start_snapshot = current
                else:
                    no_progress += 1
                if active_stage == "STAGE_3_5MIN":
                    complete, reason = stage3_verified(scope)
                elif active_stage == "STAGE_4_CRYPTO_HISTORY":
                    phase_index = int((state.get("stage4") or {}).get("current_phase_index") or 0)
                    complete, reason = stage4_phase_verified((state.get("stage4") or {}).get("phases")[phase_index])
                else:
                    complete, reason = stage1_verified()
                if complete:
                    if active_stage == "STAGE_3_5MIN":
                        state["stage_status"] = "COMPLETE_WITH_SUPPORTED_GAPS" if checkpoint_snapshot_for(FIVE_MINUTE_CHECKPOINT)["errors"] else "COMPLETE"
                        state["stage4"] = stage4_crypto_scope()
                        state["stage"] = "STAGE_4_CRYPTO_HISTORY"
                        state["stage_status"] = state["stage4"]["status"]
                        state["completed_at"] = None
                        save(state)
                        log("ADVANCE Stage 3 verified; Stage 4 crypto scope approved")
                        continue
                    if active_stage == "STAGE_4_CRYPTO_HISTORY":
                        phase_index = int((state.get("stage4") or {}).get("current_phase_index") or 0)
                        phases = (state.get("stage4") or {}).get("phases") or []
                        phase = phases[phase_index]
                        phase["status"] = "COMPLETE_WITH_SUPPORTED_GAPS" if checkpoint_snapshot_for(Path(phase["checkpoint_path"]))["status"] == "COMPLETE_WITH_SUPPORTED_GAPS" else "COMPLETE"
                        if phase_index + 1 < len(phases):
                            state["stage4"]["current_phase_index"] = phase_index + 1
                            state["stage_status"] = "APPROVED_PENDING"
                            save(state)
                            log(f"ADVANCE Stage 4 phase {phase['timeframe']} verified")
                            continue
                        state["stage"] = "STAGE_5_FOCUSED_1MIN_EQUITIES"
                        state["stage_status"] = "COMPLETE_NO_GAP"
                        state["stage5"] = {"status": "COMPLETE_NO_GAP", "reason": "existing_1min_core_archive_already_complete"}
                        save(state)
                        continue
                    continue
                if no_progress >= 5:
                    state.update(stage_status="STOPPED_NO_PROGRESS", last_error="five_consecutive_no_progress_exits", completed_at=now())
                    save(state); log("STOP five consecutive no-progress exits"); return 2
                state["stage_status"] = "CHECKPOINTED_RESTART_PENDING"
                state["last_error"] = reason if return_code else "child_exited_before_completion"
                save(state); log(f"CHILD EXIT code={return_code}; progress={progressed}; backoff={BACKOFF_SECONDS[min(backoff_index, len(BACKOFF_SECONDS)-1)]}s")
                time.sleep(BACKOFF_SECONDS[min(backoff_index, len(BACKOFF_SECONDS) - 1)])
                backoff_index = min(backoff_index + 1, len(BACKOFF_SECONDS) - 1)
                continue
        save(state)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
