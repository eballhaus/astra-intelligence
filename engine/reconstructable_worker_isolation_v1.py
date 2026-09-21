"""Short-lived isolation for bounded, non-authoritative worker workloads.

This module intentionally exposes one task.  The child receives only bounded
observation rows and may return evaluation-only data; it cannot write the
canonical worker state or access broker/truth/execution authority.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

MAX_INPUT_ROWS = 300
MAX_OUTPUT_ROWS = 300
MAX_IPC_BYTES = 4_000_000
DEFAULT_TIMEOUT_SECONDS = 20.0
TASK_BROAD_OBSERVATION_EVALUATION = "broad_observation_evaluation_v1"
_BLOCKED_RESOURCE_STATES = {
    "RESOURCE_MEMORY_PAUSE",
    "RESOURCE_HIGH_PAUSE",
    "RESOURCE_API_LATENCY_PAUSE",
    "RESOURCE_UNKNOWN_FAIL_CLOSED",
    "RESOURCE_RECOVERY_COOLDOWN",
}


def _rss_mb() -> float | None:
    try:
        import psutil  # type: ignore

        return round(float(psutil.Process(os.getpid()).memory_info().rss) / (1024.0 * 1024.0), 2)
    except Exception:
        return None


def _resource_gate(resource_state: str) -> tuple[bool, str, str]:
    state = str(resource_state or "RESOURCE_UNKNOWN_FAIL_CLOSED").upper()
    if state == "RESOURCE_NORMAL":
        return True, "NORMAL", ""
    if state == "RESOURCE_ELEVATED":
        return True, "REDUCED", "RESOURCE_ELEVATED_REDUCED_BATCH"
    if state in _BLOCKED_RESOURCE_STATES:
        return False, "BLOCKED", state
    return False, "BLOCKED", "RESOURCE_UNKNOWN_FAIL_CLOSED"


def _safe_failure(*, status: str, reason: str, resource_state: str, mode: str = "BLOCKED") -> dict[str, Any]:
    return {
        "schema_version": "astra_reconstructable_worker_isolation_v1",
        "task": TASK_BROAD_OBSERVATION_EVALUATION,
        "status": status,
        "failure_reason": str(reason or "failed_safe")[:180],
        "resource_state": str(resource_state or ""),
        "mode": mode,
        "promoted_rows": [],
        "observations_considered": 0,
        "evaluation_only": True,
        "observation_authority": False,
        "executable_evidence": False,
        "candidate_evidence_fabricated": False,
        "execution_authority": False,
        "broker_authority": False,
        "truth_authority": False,
        "policy_authority": False,
        "learning_ack_authority": False,
        "paper_only": True,
        "isolated_subprocess": True,
    }


def _validate_result(result: Any, *, resource_state: str, mode: str, input_rows: int, input_bytes: int) -> dict[str, Any]:
    if not isinstance(result, dict):
        return _safe_failure(status="FAILED_SAFE", reason="invalid_child_result", resource_state=resource_state, mode=mode)
    promoted = result.get("promoted_rows")
    if not isinstance(promoted, list) or len(promoted) > MAX_OUTPUT_ROWS or not all(isinstance(row, dict) for row in promoted):
        return _safe_failure(status="FAILED_SAFE", reason="invalid_or_unbounded_child_output", resource_state=resource_state, mode=mode)
    result = dict(result)
    result["promoted_rows"] = promoted
    result.update(
        {
            "schema_version": "astra_reconstructable_worker_isolation_v1",
            "status": "SUCCESS",
            "resource_state": resource_state,
            "mode": mode,
            "evaluation_only": True,
            "observation_authority": False,
            "executable_evidence": False,
            "candidate_evidence_fabricated": False,
            "execution_authority": False,
            "broker_authority": False,
            "truth_authority": False,
            "policy_authority": False,
            "learning_ack_authority": False,
            "paper_only": True,
            "isolated_subprocess": True,
            "ipc_input_rows": input_rows,
            "ipc_input_bytes": input_bytes,
            "ipc_output_rows": len(promoted),
        }
    )
    return result


def run_broad_observation_evaluation_v1(
    rows: list[dict[str, Any]] | None,
    *,
    state_dir: str,
    resource_state: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the observation-only allocator in one bounded child process."""
    allowed, mode, gate_reason = _resource_gate(resource_state)
    if not allowed:
        return _safe_failure(status="BLOCKED", reason=gate_reason, resource_state=resource_state, mode=mode)

    bounded_rows = [row for row in (rows or []) if isinstance(row, dict)][:MAX_INPUT_ROWS]
    try:
        request_bytes = json.dumps(
            {
                "schema_version": "astra_reconstructable_worker_isolation_request_v1",
                "task": TASK_BROAD_OBSERVATION_EVALUATION,
                "rows": bounded_rows,
                "state_dir": str(Path(state_dir).resolve()),
                "max_observations": len(bounded_rows),
                "authority": {
                    "execution": False,
                    "broker": False,
                    "truth": False,
                    "policy": False,
                    "learning_ack": False,
                },
            },
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    except Exception as exc:
        return _safe_failure(status="FAILED_SAFE", reason=f"request_serialization:{exc}", resource_state=resource_state, mode=mode)
    if len(request_bytes) > MAX_IPC_BYTES:
        return _safe_failure(status="FAILED_SAFE", reason="ipc_request_too_large", resource_state=resource_state, mode=mode)

    started = time.monotonic()
    parent_rss_before = _rss_mb()
    command = [sys.executable, "-m", "engine.reconstructable_worker_isolation_v1", "--child"]
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "ASTRA_PROCESS_ROLE": "reconstructable_subprocess"},
        )
        stdout, stderr = proc.communicate(input=request_bytes, timeout=max(1.0, float(timeout_seconds)))
        duration = round(time.monotonic() - started, 4)
        if proc.returncode != 0:
            return {
                **_safe_failure(status="FAILED_SAFE", reason=f"child_exit:{proc.returncode}", resource_state=resource_state, mode=mode),
                "subprocess_pid": proc.pid,
                "subprocess_exit_code": proc.returncode,
                "subprocess_stderr": stderr.decode("utf-8", errors="replace")[-180:],
                "duration_seconds": duration,
                "main_worker_rss_before_mb": parent_rss_before,
                "main_worker_rss_after_mb": _rss_mb(),
            }
        if len(stdout) > MAX_IPC_BYTES:
            return {
                **_safe_failure(status="FAILED_SAFE", reason="ipc_response_too_large", resource_state=resource_state, mode=mode),
                "subprocess_pid": proc.pid,
                "subprocess_exit_code": proc.returncode,
                "duration_seconds": duration,
            }
        payload = json.loads(stdout.decode("utf-8"))
        result = _validate_result(payload, resource_state=resource_state, mode=mode, input_rows=len(bounded_rows), input_bytes=len(request_bytes))
        result.update(
            {
                "subprocess_pid": proc.pid,
                "subprocess_exit_code": proc.returncode,
                "duration_seconds": duration,
                "main_worker_rss_before_mb": parent_rss_before,
                "main_worker_rss_after_mb": _rss_mb(),
            }
        )
        return result
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
            try:
                proc.communicate()
            except Exception:
                pass
        return {
            **_safe_failure(status="FAILED_SAFE", reason="subprocess_timeout", resource_state=resource_state, mode=mode),
            "subprocess_pid": proc.pid if proc is not None else None,
            "subprocess_exit_code": None,
            "duration_seconds": round(time.monotonic() - started, 4),
            "main_worker_rss_before_mb": parent_rss_before,
            "main_worker_rss_after_mb": _rss_mb(),
        }
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()
        return {
            **_safe_failure(status="FAILED_SAFE", reason=f"subprocess_error:{exc}", resource_state=resource_state, mode=mode),
            "subprocess_pid": proc.pid if proc is not None else None,
            "subprocess_exit_code": proc.returncode if proc is not None else None,
            "duration_seconds": round(time.monotonic() - started, 4),
            "main_worker_rss_before_mb": parent_rss_before,
            "main_worker_rss_after_mb": _rss_mb(),
        }


def _child_main() -> int:
    raw = sys.stdin.buffer.read(MAX_IPC_BYTES + 1)
    if len(raw) > MAX_IPC_BYTES:
        print(json.dumps(_safe_failure(status="FAILED_SAFE", reason="ipc_request_too_large", resource_state="RESOURCE_NORMAL"), separators=(",", ":")))
        return 0
    try:
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict) or request.get("task") != TASK_BROAD_OBSERVATION_EVALUATION:
            raise ValueError("unsupported_task")
        rows = request.get("rows")
        if not isinstance(rows, list) or len(rows) > MAX_INPUT_ROWS:
            raise ValueError("invalid_bounded_rows")
        from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1

        allocator = PaperOpportunityAllocationEngineV1(state_dir=str(request.get("state_dir") or "state"))
        # The child may read existing local evidence but cannot update the
        # durable rank ledger or any other worker-owned state.
        allocator._write_rank_state = lambda _payload: None  # type: ignore[method-assign]
        result = allocator.evaluate_broad_observations_v1(rows, max_observations=min(MAX_INPUT_ROWS, len(rows)))
        if not isinstance(result, dict):
            raise ValueError("invalid_allocator_result")
        result["subprocess_peak_rss_mb"] = _rss_mb()
        print(json.dumps(result, separators=(",", ":"), default=str))
        return 0
    except Exception as exc:
        print(json.dumps(_safe_failure(status="FAILED_SAFE", reason=f"child_exception:{exc}", resource_state="RESOURCE_NORMAL"), separators=(",", ":")))
        return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the parent contract
    raise SystemExit(_child_main())
