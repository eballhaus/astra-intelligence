"""Bounded, secret-free provider-consumption telemetry for worker snapshots."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "astra_provider_consumption_telemetry_v1"
FMP_EVENT_LEDGER_NAME = "fmp_efficiency_ledger_v1.jsonl"
MAX_FMP_EVENT_ROWS = 2_000
MAX_FMP_EVENT_BYTES = 2 * 1024 * 1024

# Generic router quotes are transport/cache observations. They have no
# attributable position or candidate assignment contract by themselves.
_GENERIC_ROUTER_QUOTE_CONTEXTS = frozenset({"provider_router_fmp_quote"})
_GENERIC_DIAGNOSTIC_CONTEXTS = frozenset({
    "provider_router_deliberate_fmp_probe",
    "fmp_rest_controlled_test",
    "fmp_url_builder",
})
_POSITION_TARGETED_CONTEXTS = frozenset({
    "paper_autopilot_legacy_swing_worker",
    "paper_autopilot_open_position_worker",
})
_CANDIDATE_TARGETED_CONTEXTS = frozenset({"top_buys_fmp_enrichment_v1"})


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


def _read_tail_lines(path: Path, limit: int, read_bytes: int = MAX_FMP_EVENT_BYTES) -> list[str]:
    """Read a bounded JSONL tail without loading historical provider traffic."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max(1024, int(read_bytes))))
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="ignore").splitlines()
    # The first row can be partial after seeking into a large JSONL file.
    if size > read_bytes and lines:
        lines = lines[1:]
    return lines[-max(1, int(limit)):]


def _read_tail(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    try:
        lines = _read_tail_lines(path, limit)
    except (OSError, ValueError):
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


def append_fmp_provider_event_v1(
    event: Mapping[str, Any],
    *,
    state_dir: str | Path = "state",
    max_rows: int = MAX_FMP_EVENT_ROWS,
    max_bytes: int = MAX_FMP_EVENT_BYTES,
) -> None:
    """Append one redacted event and compact the shared ledger atomically.

    The backend and worker are separate processes.  A lock file keeps their
    writes ordered, while compaction prevents old telemetry from becoming an
    active-window budget input or an unbounded runtime artifact.
    """
    root = Path(state_dir)
    path = root / FMP_EVENT_LEDGER_NAME
    root.mkdir(parents=True, exist_ok=True)
    row = dict(event)
    row["timestamp"] = str(row.get("timestamp") or _now())
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            tail_over_limit = len(_read_tail_lines(path, max(1, int(max_rows)) + 1)) > int(max_rows)
            if path.stat().st_size > max(1, int(max_bytes)) or tail_over_limit:
                rows = _read_tail(path, max(1, int(max_rows)))
                compacted = "".join(
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
                    for item in rows[-max(1, int(max_rows)):]
                )
                fd, temporary = tempfile.mkstemp(dir=str(root), suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(compacted)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                except Exception:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
                    raise
        finally:
            try:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass


def fmp_context_network_bytes_v1(
    caller_context: str,
    *,
    state_dir: str | Path = "state",
    window_start: str = "",
) -> int:
    """Return actual network bytes for one producer context only.

    A candidate-enrichment cap must never be charged for open-position router
    traffic.  Cache reads and deduplicated events have no network byte cost.
    """
    rows = _read_tail(Path(state_dir) / FMP_EVENT_LEDGER_NAME, MAX_FMP_EVENT_ROWS)
    total = 0
    for row in rows:
        if str(row.get("caller_context") or "") != str(caller_context):
            continue
        if window_start and not _within_window(row, window_start):
            continue
        if bool(row.get("cache_hit")) or bool(row.get("deduplicated")):
            continue
        if _number(row.get("api_calls_delta")) <= 0:
            continue
        total += max(0, int(_number(row.get("bytes_actual_if_available") or row.get("bandwidth_delta"))))
    return total


def _within_window(row: Mapping[str, Any], window_start: str) -> bool:
    if not window_start:
        return True
    try:
        observed = datetime.fromisoformat(str(row.get("timestamp") or "").replace("Z", "+00:00")).astimezone(UTC)
        start = datetime.fromisoformat(str(window_start).replace("Z", "+00:00")).astimezone(UTC)
        return observed >= start
    except (TypeError, ValueError):
        return False


def _consumer_event_within_window(row: Mapping[str, Any], window_start: str) -> bool:
    if not window_start:
        return True
    # Current-window consumption must be traceable to a response generated in
    # this worker generation.  Re-triaging persisted evidence after restart is
    # useful, but it must not make an older provider response look newly
    # assigned in the active-window accounting.
    return _within_window({"timestamp": row.get("producer_event_at") or row.get("evidence_at")}, window_start)


def _family(value: Mapping[str, Any]) -> str:
    """Normalize persisted FMP endpoint identities without changing router policy."""
    raw = str(value.get("endpoint_family") or "unknown").strip().lower()
    if raw in {"quote_profile", "quote"}:
        path = str(value.get("endpoint_path_template") or "").lower()
        if "profile" in path:
            return "company_profile"
        return "quote"
    if "historical" in raw:
        return "completed_bars"
    return raw.replace(" ", "_") or "unknown"


def _transport_succeeded(row: Mapping[str, Any]) -> bool:
    """Return HTTP transport success without confusing it with payload utility."""
    status = _number(row.get("status_code"))
    return 200 <= status < 400 or (status == 0 and bool(row.get("ok")))


def _assignment_scope(row: Mapping[str, Any]) -> str:
    """Classify assignment intent without inferring it from endpoint or symbol."""
    explicit = str(row.get("assignment_scope") or "").strip().lower()
    if explicit in {
        "generic_router_quote",
        "generic_diagnostic",
        "position_targeted_evidence",
        "candidate_targeted_evidence",
        "assignment_required_unclassified",
    }:
        return explicit
    caller = str(row.get("caller_context") or "").strip().lower()
    if caller in _GENERIC_ROUTER_QUOTE_CONTEXTS:
        return "generic_router_quote"
    if caller in _GENERIC_DIAGNOSTIC_CONTEXTS:
        return "generic_diagnostic"
    if caller in _POSITION_TARGETED_CONTEXTS:
        return "position_targeted_evidence"
    if caller in _CANDIDATE_TARGETED_CONTEXTS:
        return "candidate_targeted_evidence"
    # Preserve prior fail-closed accounting for unknown producers.
    return "assignment_required_unclassified"


def _requires_assignment(row: Mapping[str, Any]) -> bool:
    return _assignment_scope(row) not in {"generic_router_quote", "generic_diagnostic"}


def _event_counts(events: list[dict[str, Any]], consumer_events: list[dict[str, Any]], family: str) -> dict[str, Any]:
    scoped = [row for row in events if _family(row) == family]
    assigned = [row for row in consumer_events if str(row.get("endpoint_family") or "unknown") == family and bool(row.get("assigned"))]
    consumed = [row for row in consumer_events if str(row.get("endpoint_family") or "unknown") == family and bool(row.get("consumed"))]
    rejected_by_consumer = [row for row in consumer_events if str(row.get("endpoint_family") or "unknown") == family and bool(row.get("rejected"))]
    cache_hits = [row for row in scoped if bool(row.get("cache_hit"))]
    deduplicated = [row for row in scoped if bool(row.get("deduplicated"))]
    blocked = [row for row in scoped if str(row.get("blocked_reason") or "").lower() in {"call_limit", "bandwidth_budget", "governor_blocked", "provider_cooldown_or_budget"}]
    network = [row for row in scoped if row not in cache_hits and row not in deduplicated and row not in blocked]
    successful = [row for row in network if _transport_succeeded(row)]
    failures = [row for row in network if row not in successful]
    accepted = [row for row in successful if _number(row.get("useful_fields_count")) > 0]
    assignment_required = [row for row in accepted if _requires_assignment(row)]
    generic_router_quotes = [row for row in accepted if _assignment_scope(row) == "generic_router_quote"]
    position_targeted = [row for row in accepted if _assignment_scope(row) == "position_targeted_evidence"]
    candidate_targeted = [row for row in accepted if _assignment_scope(row) == "candidate_targeted_evidence"]
    byte_missing = [row for row in successful if _number(row.get("bytes_actual_if_available") or row.get("bandwidth_delta")) <= 0]
    last = dict(scoped[-1]) if scoped else {}
    return {
        "endpoint_family": family,
        "configured": True,
        "scheduled": len(scoped), "eligible": len(scoped), "attempted": len(scoped),
        "network_sent": len(network), "successful": len(successful),
        "HTTP_failed": sum(_number(row.get("status_code")) >= 400 for row in failures),
        "network_failed": sum(not _number(row.get("status_code")) for row in failures),
        "governor_blocked": len(blocked), "cache_hits": len(cache_hits),
        "cache_misses": max(0, len(scoped) - len(cache_hits)), "deduplicated": len(deduplicated),
        "not_eligible": 0, "responses_parsed": len(successful),
        "responses_accepted": len(accepted), "responses_rejected": max(0, len(successful) - len(accepted)) + len(rejected_by_consumer),
        "responses_assigned": len(assigned), "responses_consumed": len(consumed),
        "assignment_required_accepted": len(assignment_required),
        "generic_router_quote_accepted": len(generic_router_quotes),
        "position_targeted_accepted": len(position_targeted),
        "candidate_targeted_accepted": len(candidate_targeted),
        "unclassified_assignment_required_accepted": sum(
            1 for row in assignment_required if _assignment_scope(row) == "assignment_required_unclassified"
        ),
        "byte_telemetry_missing": len(byte_missing),
        "bytes_received": int(sum(max(0.0, _number(row.get("bytes_actual_if_available") or row.get("bandwidth_delta"))) for row in scoped)),
        "last_attempt_at": str(last.get("timestamp") or ""),
        "last_network_request_at": str(network[-1].get("timestamp") or "") if network else "",
        "last_success_at": str(successful[-1].get("timestamp") or "") if successful else "",
        "last_failure_at": str(failures[-1].get("timestamp") or "") if failures else "",
        "last_assigned_at": str(assigned[-1].get("assigned_at") or "") if assigned else "",
        "last_consumed_at": str(consumed[-1].get("consumed_at") or "") if consumed else "",
        "last_http_status": int(_number(last.get("status_code"))), "last_latency_ms": _number(last.get("latency_ms")),
        "last_evidence_timestamp": str((consumed or assigned or [{}])[-1].get("evidence_at") or ""),
        "last_symbol": str((consumed or assigned or [{}])[-1].get("symbol") or last.get("symbol") or ""),
        "last_consumer": str(consumed[-1].get("consumer") or "") if consumed else "",
        "consumer_record_id": str(consumed[-1].get("consumer_record_id") or "") if consumed else "",
        "first_causal_blocker": str((rejected_by_consumer[-1].get("rejection_reason") if rejected_by_consumer else "") or last.get("blocked_reason") or ""),
        "budget_limit": 750, "budget_used": len(network), "budget_remaining": max(0, 750 - len(network)),
    }


def build_provider_consumption_telemetry_v1(
    *,
    state_dir: str | Path = "state",
    configured: bool,
    key_fingerprint: str,
    consumer_events: Iterable[Mapping[str, Any]] = (),
    window_start: str = "",
) -> dict[str, Any]:
    """Summarize existing router ledger events without issuing provider calls."""
    root = Path(state_dir)
    raw_events = [row for row in _read_tail(root / FMP_EVENT_LEDGER_NAME) if _within_window(row, window_start)]
    # Consumption acknowledgements are ledgered beside their producer event so
    # a candidate-enrichment response is not mistaken for an unconsumed quote.
    ledger_consumers = [
        {
            "endpoint_family": _family(row), "symbol": row.get("symbol"),
            "assigned": bool(row.get("assigned")), "assigned_at": row.get("assigned_at") or row.get("timestamp"),
            "consumed": bool(row.get("consumed")), "consumed_at": row.get("consumed_at") or row.get("timestamp"),
            "rejected": bool(row.get("rejected")), "rejected_at": row.get("rejected_at") or row.get("timestamp"),
            "rejection_reason": row.get("rejection_reason") or "",
            "consumer": row.get("consumer") or "", "consumer_record_id": row.get("consumer_record_id") or "",
            "evidence_at": row.get("evidence_at") or row.get("timestamp"),
        }
        for row in raw_events if str(row.get("event_phase") or "").upper() == "CONSUMPTION"
    ]
    events = [row for row in raw_events if str(row.get("event_phase") or "").upper() != "CONSUMPTION"]
    attempts = len(events)
    cache_hits = [row for row in events if bool(row.get("cache_hit"))]
    governor_blocked = [row for row in events if str(row.get("blocked_reason") or "").lower() in {"call_limit", "bandwidth_budget", "governor_blocked", "provider_cooldown_or_budget"}]
    deduplicated = [row for row in events if bool(row.get("deduplicated"))]
    network_sent = [row for row in events if row not in cache_hits and row not in governor_blocked and row not in deduplicated]
    # HTTP success is transport success.  ``ok`` additionally represents a
    # usable normalized payload, which is accounted for by acceptance below.
    successes = [row for row in network_sent if _transport_succeeded(row)]
    failures = [row for row in network_sent if row not in successes]
    accepted = [row for row in successes if _number(row.get("useful_fields_count")) > 0]
    assignment_required = [row for row in accepted if _requires_assignment(row)]
    generic_router_quotes = [row for row in accepted if _assignment_scope(row) == "generic_router_quote"]
    position_targeted = [row for row in accepted if _assignment_scope(row) == "position_targeted_evidence"]
    candidate_targeted = [row for row in accepted if _assignment_scope(row) == "candidate_targeted_evidence"]
    byte_missing = [row for row in successes if _number(row.get("bytes_actual_if_available") or row.get("bandwidth_delta")) <= 0]
    bytes_received = int(sum(max(0.0, _number(row.get("bytes_actual_if_available") or row.get("bandwidth_delta"))) for row in events))
    consumer_rows = ledger_consumers + [
        dict(row) for row in consumer_events
        if isinstance(row, Mapping) and (row.get("consumer") or row.get("rejected")) and _consumer_event_within_window(row, window_start)
    ]
    consumed = [row for row in consumer_rows if bool(row.get("consumed"))]
    rejected = [row for row in consumer_rows if bool(row.get("rejected"))]
    last_event = dict(events[-1]) if events else {}
    last_consumer = str(consumed[-1].get("consumer") or "") if consumed else ""
    assigned_count = sum(bool(row.get("assigned")) for row in consumer_rows)
    consumed_count = sum(bool(row.get("consumed")) for row in consumer_rows)
    provider = {
        "provider": "FMP",
        "configured": bool(configured),
        "key_fingerprint": str(key_fingerprint or ""),
        "eligible": bool(configured),
        "scheduled": attempts,
        "attempted": attempts,
        "network_sent": len(network_sent),
        "attempted_calls": attempts,
        "successful_calls": len(successes),
        "failed_calls": len(failures),
        "HTTP_failed": len([row for row in failures if _number(row.get("status_code")) >= 400]),
        "network_failed": len([row for row in failures if not _number(row.get("status_code"))]),
        "governor_blocked": len(governor_blocked),
        "cache_hits": len(cache_hits),
        "cache_misses": max(0, attempts - len(cache_hits)),
        "deduplicated": len(deduplicated),
        "responses_parsed": len(successes),
        "responses_accepted": len(accepted),
        "responses_rejected": max(0, len(successes) - len(accepted)) + len(rejected),
        "responses_assigned": assigned_count,
        "responses_consumed": consumed_count,
        "assignment_required_accepted": len(assignment_required),
        "generic_router_quote_accepted": len(generic_router_quotes),
        "position_targeted_accepted": len(position_targeted),
        "candidate_targeted_accepted": len(candidate_targeted),
        "unclassified_assignment_required_accepted": sum(
            1 for row in assignment_required if _assignment_scope(row) == "assignment_required_unclassified"
        ),
        "byte_telemetry_missing": len(byte_missing),
        "bytes_received": bytes_received,
        "last_attempt_at": str(last_event.get("timestamp") or ""),
        "last_success_at": str(successes[-1].get("timestamp") or "") if successes else "",
        "last_failure_at": str(failures[-1].get("timestamp") or "") if failures else "",
        "last_http_status": int(_number(last_event.get("status_code"))),
        "last_latency_ms": _number(last_event.get("latency_ms")),
        "last_consumer": last_consumer,
        "last_accepted_symbol": str(consumed[-1].get("symbol") or "") if consumed else "",
        "first_causal_blocker": str((rejected[-1].get("rejection_reason") if rejected else "") or last_event.get("blocked_reason") or ""),
        "budget_limit_per_minute": 750,
        "budget_used": len(network_sent),
        "budget_remaining": max(0, 750 - len(network_sent)),
        "bounded_usage_status": (
            "CONFIGURED_UNUSED" if configured and not attempts else
            "SUCCESS_NOT_CONSUMED" if assignment_required and not consumed and not rejected else
            "GENERIC_ROUTER_QUOTE_ACTIVITY" if generic_router_quotes and not assignment_required else
            "ACTIVE" if consumed else "FAIL_CLOSED"
        ),
    }
    families = sorted({_family(row) for row in events} | {str(row.get("endpoint_family") or "unknown") for row in consumer_rows})
    family_rows = [_event_counts(events, consumer_rows, family) for family in families]
    complete = bool(family_rows) and not any(
        row["assignment_required_accepted"] > row["responses_assigned"] + row["responses_rejected"] or row["responses_assigned"] > row["responses_consumed"] or row["byte_telemetry_missing"] > 0
        for row in family_rows
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "window_start": str(window_start or (events[0].get("timestamp") if events else "") or ""),
        "provider_count": 1,
        "providers": [{**provider, "endpoint_families": family_rows, "telemetry_complete": complete}],
        "endpoint_families": family_rows,
        "telemetry_complete": complete,
        "configured_but_unused_count": int(bool(configured and not attempts)),
        "successful_but_unconsumed_count": int(bool(assignment_required and not consumed and not rejected)),
        "provider_starvation_count": int(bool(configured and not attempts)),
        "budget_warning_count": int(any(str(row.get("blocked_reason") or "") in {"call_limit", "bandwidth_budget"} for row in events)),
        "governor_blocked_count": len(governor_blocked),
        "expected_traffic_missing_count": int(bool(configured and not attempts)),
        "success_not_consumed_count": int(bool(assignment_required and not consumed and not rejected)),
        "stale_evidence_count": 0,
        "byte_telemetry_mismatch_count": len(byte_missing),
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
