"""Bounded, secret-free provider-consumption telemetry for worker snapshots."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "astra_provider_consumption_telemetry_v1"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_tail(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-max(1, limit):]
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def build_provider_consumption_telemetry_v1(
    *,
    state_dir: str | Path = "state",
    configured: bool,
    key_fingerprint: str,
    consumer_events: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Summarize existing router ledger events without issuing provider calls."""
    root = Path(state_dir)
    events = _read_tail(root / "fmp_efficiency_ledger_v1.jsonl")
    attempts = len(events)
    successes = [row for row in events if bool(row.get("ok"))]
    failures = [row for row in events if not bool(row.get("ok")) and not bool(row.get("cache_hit"))]
    accepted = [row for row in successes if _number(row.get("useful_fields_count")) > 0]
    bytes_received = int(sum(max(0.0, _number(row.get("bytes_actual_if_available") or row.get("bandwidth_delta"))) for row in events))
    cache_hits = len([row for row in events if bool(row.get("cache_hit"))])
    consumer_rows = [dict(row) for row in consumer_events if isinstance(row, Mapping) and row.get("consumer")]
    consumed = [row for row in consumer_rows if bool(row.get("accepted"))]
    last_event = dict(events[-1]) if events else {}
    last_consumer = str(consumed[-1].get("consumer") or "") if consumed else ""
    provider = {
        "provider": "FMP",
        "configured": bool(configured),
        "key_fingerprint": str(key_fingerprint or ""),
        "eligible": bool(configured),
        "attempted_calls": attempts,
        "successful_calls": len(successes),
        "failed_calls": len(failures),
        "cache_hits": cache_hits,
        "cache_misses": max(0, attempts - cache_hits),
        "responses_accepted": len(accepted),
        "responses_rejected": max(0, len(successes) - len(accepted)),
        "bytes_received": bytes_received,
        "last_attempt_at": str(last_event.get("timestamp") or ""),
        "last_success_at": str(successes[-1].get("timestamp") or "") if successes else "",
        "last_failure_at": str(failures[-1].get("timestamp") or "") if failures else "",
        "last_http_status": int(_number(last_event.get("status_code"))),
        "last_latency_ms": _number(last_event.get("latency_ms")),
        "last_consumer": last_consumer,
        "last_accepted_symbol": str(consumed[-1].get("symbol") or "") if consumed else "",
        "first_causal_blocker": str(last_event.get("blocked_reason") or ""),
        "budget_limit_per_minute": 750,
        "bounded_usage_status": (
            "CONFIGURED_UNUSED" if configured and not attempts else
            "SUCCESS_NOT_CONSUMED" if accepted and not consumed else
            "ACTIVE" if consumed else "FAIL_CLOSED"
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "window_start": str(events[0].get("timestamp") or "") if events else "",
        "provider_count": 1,
        "providers": [provider],
        "configured_but_unused_count": int(bool(configured and not attempts)),
        "successful_but_unconsumed_count": int(bool(accepted and not consumed)),
        "provider_starvation_count": int(bool(configured and not attempts)),
        "budget_warning_count": int(any(str(row.get("blocked_reason") or "") in {"call_limit", "bandwidth_budget"} for row in events)),
        "stale_evidence_count": 0,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
        "state_mutations_from_get": 0,
        "paper_only_preserved": True,
    }


def save_provider_consumption_telemetry_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    _atomic_write(Path(state_dir) / "astra_provider_consumption_telemetry_v1.json", payload)


def load_provider_consumption_telemetry_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try:
        payload = json.loads((Path(state_dir) / "astra_provider_consumption_telemetry_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def save_fmp_production_verification_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    _atomic_write(Path(state_dir) / "astra_fmp_production_verification_v1.json", payload)


def load_fmp_production_verification_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try:
        payload = json.loads((Path(state_dir) / "astra_fmp_production_verification_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}
