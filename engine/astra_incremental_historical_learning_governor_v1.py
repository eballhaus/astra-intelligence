"""V10 checkpointed, resource-aware historical outcome-linkage governor.

The governor is intentionally outside the trading worker.  GET/status calls are
read-only; an explicit caller may run one bounded partition when runtime facts
say that background learning is safe.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.astra_evidence_utilization_information_value_v1 import (
    build_evidence_utilization_information_value_v1,
)
from engine.astra_historical_evidence_mining_knowledge_distillation_v1 import (
    build_historical_evidence_mining_knowledge_distillation_v1,
)
from engine.astra_historical_learning_compression_helpers_v1 import (
    THROUGHPUT,
    adaptive_throughput_v1,
    profile_and_compress_partition_v1,
    warehouse_partition_references_v1,
)
from engine.astra_storage_cache_attribution_learning_efficiency_v1 import (
    INDEX_DIMENSIONS,
    OUTCOME_INTERACTION_PAIRS,
    TARGET_COLD_FILES,
    _outcome_tier,
    _outcome_value,
    _outcome_timestamp,
    outcome_dimensions_for_row,
)


VERSION = "1.0.0"
CHECKPOINT_FILE = "astra_incremental_historical_learning_governor_v1.json"
DELTA_INDEX_FILE = "incremental_historical_learning_governor_v1.summary_index.json"
PACKET_REGISTRY_FILE = "historical_learning_compressed_packets_v1.json"
MAX_PARTITIONS_PER_CYCLE = 1
MAX_ROWS_PER_PARTITION = 240
MAX_BYTES_PER_PARTITION = 64 * 1024
MAX_ROWS_PER_PARTITION_HARD = int(THROUGHPUT["ACCELERATED"]["rows"])
MAX_BYTES_PER_PARTITION_HARD = int(THROUGHPUT["ACCELERATED"]["bytes"])
MAX_AGGREGATE_UPDATES_PER_PARTITION = 3_840
MAX_BUCKETS_PER_DIMENSION = 40
MAX_V8_PATTERNS_PER_UPDATE = 64
MAX_V8_INTERACTIONS_PER_UPDATE = 24
SOURCE_PRIORITY = {
    "candidate_decision_ledger_v1.jsonl": 100,
    "canonical_lifecycle_lessons_v1.jsonl": 98,
    "outcome_labels_v1.jsonl": 95,
    "replay_counterfactual_learning_v2.jsonl": 90,
    "trade_archetype_regime_intelligence_v1.jsonl": 85,
    "adaptive_execution_exit_intelligence_v3.jsonl": 80,
    "exit_learning_expansion_suite_v1.jsonl": 75,
    "trade_lifecycle_excursion_v2.jsonl": 70,
}
SAFETY = {
    "get_route_read_only": True,
    "background_worker_integration": False,
    "full_history_scan_count": 0,
    "provider_calls_added": 0,
    "broker_calls_added": 0,
    "broker_actions_added": 0,
    "llm_calls_added": 0,
    "execution_behavior_changed": False,
    "ranking_behavior_changed": False,
    "sizing_behavior_changed": False,
    "capital_behavior_changed": False,
    "automatic_adaptation_authority": False,
    "frozen_lifecycle_modified": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict(data) if isinstance(data, Mapping) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _snapshot(path: Path) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size_bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "version": f"{int(stat.st_size)}:{int(stat.st_mtime_ns)}"}


def _resource_decision(state: Path, facts: Mapping[str, Any] | None = None) -> dict[str, str]:
    facts = dict(facts or {})
    if not facts:
        facts = _read(state / "astra_worker_runtime_state_v1.json")
    if not facts:
        return {"decision": "DEFER", "reason": "WORKER_STATE_UNAVAILABLE"}
    liveness = facts.get("worker_liveness") if isinstance(facts.get("worker_liveness"), Mapping) else {}
    health = str(facts.get("worker_health") or facts.get("liveness_state") or facts.get("worker_liveness_state") or liveness.get("liveness_state") or "").upper()
    if facts.get("active_worker_present") is False:
        return {"decision": "DEFER", "reason": "WORKER_NOT_HEALTHY:PROCESS_MISSING"}
    if health and health not in {"HEALTHY", "ACTIVE_HEALTHY", "ACTIVE_RESOURCE_ELEVATED"}:
        return {"decision": "DEFER", "reason": f"WORKER_NOT_HEALTHY:{health}"}
    if facts.get("worker_cycle_error") or facts.get("suppressed_execution_exception"):
        return {"decision": "DEFER", "reason": "WORKER_EXECUTION_ERROR_PRESENT"}
    resource = str(facts.get("resource_state") or "RESOURCE_NORMAL").upper()
    if resource in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE", "RESOURCE_UNKNOWN_FAIL_CLOSED"}:
        return {"decision": "DEFER", "reason": f"RESOURCE_PRESSURE:{resource}"}
    if bool(facts.get("trading_priority_active") or facts.get("active_order_submission") or facts.get("active_position_exit")):
        return {"decision": "DEFER", "reason": "TRADING_PRIORITY_ACTIVE"}
    return {"decision": "RUN", "reason": "BOUNDED_BACKGROUND_WINDOW"}


def _warehouse_sources(state: Path) -> dict[str, dict[str, Any]]:
    """Use the Warehouse Manager manifest, never a V10 filesystem discovery pass."""
    references = warehouse_partition_references_v1(str(state), set(TARGET_COLD_FILES))
    return {str(item.get("path")): dict(item) for item in references if item.get("path")}


def _work_budget(checkpoint: Mapping[str, Any], resource_facts: Mapping[str, Any] | None) -> dict[str, Any]:
    return adaptive_throughput_v1((checkpoint.get("throughput") or {}), resource_facts)


def _source_state(checkpoint: dict[str, Any], name: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    sources = checkpoint.setdefault("sources", {})
    previous = dict(sources.get(name) or {})
    if previous.get("snapshot_version") == snapshot.get("version"):
        return previous
    previous_size = int(previous.get("source_size_bytes") or 0)
    if previous and int(snapshot.get("size_bytes") or 0) > previous_size and int(previous.get("next_offset") or 0) >= previous_size:
        # JSONL producers append in normal operation; retain the completed prefix.
        previous["next_offset"] = min(int(previous.get("next_offset") or 0), previous_size)
    elif previous:
        # Rewritten history needs an explicit source rebuild; silently adding it
        # would duplicate or mix outcome aggregates from two revisions.
        previous["rewrite_detected"] = True
        previous["last_status"] = "ERROR"
        previous["last_error"] = "SOURCE_REVISION_REQUIRES_SAFE_REBUILD"
        previous["next_offset"] = int(snapshot.get("size_bytes") or 0)
    else:
        previous["next_offset"] = 0
        previous["partitions_completed"] = 0
    previous.update({"snapshot_version": snapshot.get("version"), "source_size_bytes": snapshot.get("size_bytes"), "source_mtime_ns": snapshot.get("mtime_ns")})
    sources[name] = previous
    return previous


def _priority(name: str, summary: Mapping[str, Any]) -> int:
    base = SOURCE_PRIORITY.get(name, 40)
    linked = int(summary.get("outcome_linked_observations") or 0)
    if linked:
        base += 15
    if "shadow" in name or "replay" in name:
        base += 5
    return base


def _candidates(
    state: Path, checkpoint: dict[str, Any], allowed_sources: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates, counts = [], Counter()
    index_dir = state / "storage_summary_indexes"
    for name in TARGET_COLD_FILES:
        if allowed_sources is not None and name not in allowed_sources:
            counts["warehouse_unavailable"] += 1
            continue
        snapshot = _snapshot(state / name)
        if not snapshot:
            continue
        source = _source_state(checkpoint, name, snapshot)
        if source.get("rewrite_detected"):
            counts["error"] += 1
            continue
        offset = int(source.get("next_offset") or 0)
        size = int(snapshot["size_bytes"])
        if offset >= size:
            counts["complete"] += 1
            continue
        summary = _read(index_dir / f"{name}.summary_index.json")
        candidates.append({
            "partition_id": f"{name}:{snapshot['version']}:{offset}", "source": name,
            "source_snapshot": snapshot["version"], "cursor_start": offset,
            "priority": _priority(name, summary), "evidence_domain": name.removesuffix(".jsonl"),
        })
    return sorted(candidates, key=lambda item: (-item["priority"], item["source"], item["cursor_start"])), dict(counts)


def _read_partition(path: Path, offset: int, *, max_bytes: int, max_rows: int) -> tuple[list[dict[str, Any]], int, int, str | None]:
    """Read at most one aligned JSONL partition, never a whole source."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(offset)
            if offset:
                handle.readline()  # discard an incomplete row from a byte cursor
            start = handle.tell()
            data = handle.read(max_bytes)
    except OSError:
        return [], offset, 0, "SOURCE_UNAVAILABLE"
    if not data:
        return [], size, 0, None
    if start + len(data) < size:
        cut = data.rfind(b"\n")
        if cut < 0:
            return [], offset, len(data), "ROW_EXCEEDS_PARTITION_BYTE_BUDGET"
        complete, consumed = data[:cut + 1], cut + 1
    else:
        complete, consumed = data, len(data)
    rows, processed_bytes = [], 0
    for raw in complete.splitlines(keepends=True):
        processed_bytes += len(raw)
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, Mapping):
            rows.append(dict(parsed))
            if len(rows) >= max_rows:
                break
    # The cursor advances only through parsed/ignored rows before the row cap.
    return rows, min(size, start + processed_bytes), processed_bytes, None


def _empty_delta() -> dict[str, Any]:
    return {"version": VERSION, "sources": {}, "outcome_by_dimension": {}, "outcome_by_interaction": {}, "evidence_tier_counts": {}}


def _bucket(summary: dict[str, Any], kind: str, key: str, value: str, tier: str) -> dict[str, Any]:
    container = summary.setdefault(kind, {}).setdefault(key, {})
    if value not in container and len(container) >= MAX_BUCKETS_PER_DIMENSION:
        value = "__other_bounded_values__"
    return container.setdefault(value, {}).setdefault(tier, {
        "observation_count": 0, "outcome_count": 0, "wins": 0, "losses": 0, "neutral_count": 0,
        "unknown_outcome_count": 0, "return_sum": 0.0, "positive_return_sum": 0.0, "negative_return_abs_sum": 0.0,
        "first_observation_timestamp": "UNAVAILABLE", "last_observation_timestamp": "UNAVAILABLE",
    })


def _accumulate(bucket: dict[str, Any], row: Mapping[str, Any]) -> None:
    weight = max(1, int(row.get("_v10_compression_weight") or 1))
    value = _outcome_value(dict(row))
    bucket["observation_count"] += weight
    timestamp = _outcome_timestamp(dict(row))
    if timestamp:
        first, last = bucket.get("first_observation_timestamp"), bucket.get("last_observation_timestamp")
        bucket["first_observation_timestamp"] = timestamp if first in (None, "UNAVAILABLE") or timestamp < first else first
        bucket["last_observation_timestamp"] = timestamp if last in (None, "UNAVAILABLE") or timestamp > last else last
    if value is None:
        bucket["unknown_outcome_count"] += weight
        return
    bucket["outcome_count"] += weight
    bucket["return_sum"] += value * weight
    if value > 0:
        bucket["wins"] += weight
        bucket["positive_return_sum"] += value * weight
    elif value < 0:
        bucket["losses"] += weight
        bucket["negative_return_abs_sum"] += abs(value) * weight
    else:
        bucket["neutral_count"] += weight


def _materialize(summary: dict[str, Any]) -> None:
    def materialize(groups: Mapping[str, Any]) -> None:
        for buckets in groups.values():
            for tiers in buckets.values():
                for bucket in tiers.values():
                    outcomes = int(bucket.get("outcome_count") or 0)
                    total = float(bucket.get("return_sum") or 0.0)
                    bucket["sample_size"] = outcomes
                    bucket["average_return_pct"] = round(total / outcomes, 5) if outcomes else None
                    bucket["expectancy_pct"] = bucket["average_return_pct"]
                    positive, negative = float(bucket.get("positive_return_sum") or 0.0), float(bucket.get("negative_return_abs_sum") or 0.0)
                    bucket["profit_factor"] = round(positive / negative, 5) if positive and negative else None
                    bucket["win_rate_pct"] = round(int(bucket.get("wins") or 0) * 100 / outcomes, 3) if outcomes else None
    materialize(summary.get("outcome_by_dimension") or {})
    materialize(summary.get("outcome_by_interaction") or {})


def _merge_partition(delta: dict[str, Any], source: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    counters = Counter(rows_examined=sum(max(1, int(row.get("_v10_compression_weight") or 1)) for row in rows), outcome_linked=0, aggregate_updates=0)
    for row in rows:
        outcome = _outcome_value(row)
        label = str(row.get("outcome_label") or row.get("outcome") or row.get("result") or "unknown").strip().lower()
        if outcome is None and label in {"", "unknown", "none"}:
            continue
        dimensions = outcome_dimensions_for_row(row, source)
        eligible = {key: value for key, value in dimensions.items() if value and value != "unknown"}
        if not eligible:
            continue
        tier = _outcome_tier(row, source)
        weight = max(1, int(row.get("_v10_compression_weight") or 1))
        counters["outcome_linked"] += weight
        delta.setdefault("evidence_tier_counts", {})[tier] = int(delta.setdefault("evidence_tier_counts", {}).get(tier) or 0) + weight
        for key, value in eligible.items():
            _accumulate(_bucket(delta, "outcome_by_dimension", key, value, tier), row)
            counters["aggregate_updates"] += 1
        for left, right in OUTCOME_INTERACTION_PAIRS:
            if left in eligible and right in eligible:
                _accumulate(_bucket(delta, "outcome_by_interaction", f"{left}×{right}", f"{eligible[left]}×{eligible[right]}", tier), row)
                counters["aggregate_updates"] += 1
    delta.setdefault("sources", {}).setdefault(source, {"partitions": 0, "rows_examined": 0, "outcome_linked": 0})
    source_state = delta["sources"][source]
    source_state["partitions"] += 1
    source_state["rows_examined"] += counters["rows_examined"]
    source_state["outcome_linked"] += counters["outcome_linked"]
    _materialize(delta)
    return dict(counters)


def _delta_index(delta: Mapping[str, Any]) -> dict[str, Any]:
    sources = delta.get("sources") or {}
    dimensions = delta.get("outcome_by_dimension") or {}
    interactions = delta.get("outcome_by_interaction") or {}
    rows = sum(int(item.get("rows_examined") or 0) for item in sources.values() if isinstance(item, Mapping))
    linked = sum(int(item.get("outcome_linked") or 0) for item in sources.values() if isinstance(item, Mapping))
    return {
        "source_file": "incremental_historical_learning_governor_v1", "generated_at": _now(),
        "index_schema_version": VERSION, "incremental_partitioned": True, "raw_source_modified": False,
        "source_line_count_estimate": rows, "outcome_linkable_observations": linked,
        "outcome_linked_observations": linked, "outcome_linkage_coverage_pct": round(linked * 100 / rows, 5) if rows else 0.0,
        "evidence_tier_counts": dict(delta.get("evidence_tier_counts") or {}),
        "dimensions_linked": sorted(dimensions), "dimensions_without_outcomes": [key for key in INDEX_DIMENSIONS if key not in dimensions],
        "outcome_by_dimension": dimensions, "outcome_by_interaction": interactions,
        "aggregate_count": sum(len(buckets) for buckets in dimensions.values()),
        "interaction_aggregate_count": sum(len(buckets) for buckets in interactions.values()),
        "partition_sources": sources, "full_history_scan_count": 0,
    }


def _coverage(
    state: Path, checkpoint: Mapping[str, Any], allowed_sources: set[str] | None = None,
) -> dict[str, Any]:
    v8 = build_historical_evidence_mining_knowledge_distillation_v1(str(state))
    v9 = build_evidence_utilization_information_value_v1(str(state))
    candidates, complete = _candidates(state, dict(checkpoint), allowed_sources)
    sources = checkpoint.get("sources") or {}
    packets = _read(state / PACKET_REGISTRY_FILE)
    completed = sum(int(item.get("partitions_completed") or 0) for item in sources.values() if isinstance(item, Mapping))
    return {
        "indexed_record_equivalents": (v8.get("learning_coverage") or {}).get("indexed_historical_observations_available", 0),
        "outcome_linked_observations": (v8.get("learning_coverage") or {}).get("outcome_linked_observations", 0),
        "outcome_linkage_coverage_pct": (v8.get("learning_coverage") or {}).get("outcome_linkage_coverage_pct", 0.0),
        "partitions_discovered": len(candidates) + int(complete.get("complete") or 0),
        "partitions_complete": completed, "partitions_remaining": len(candidates),
        "partition_errors": int(complete.get("error") or 0),
        "partitions_deferred": int((checkpoint.get("velocity") or {}).get("deferred_cycles") or 0),
        "partitions_no_outcome_data": int((checkpoint.get("velocity") or {}).get("no_outcome_partitions") or 0),
        "compressed_packet_count": len(packets.get("packets") or {}),
        "pending_outcome_count": len(packets.get("pending_outcomes") or {}),
        "outcome_aggregates": (v8.get("learning_coverage") or {}).get("outcome_aggregate_count", 0),
        "v8_patterns": (v8.get("learning_coverage") or {}).get("pattern_count", 0),
        "v8_interactions": (v8.get("learning_coverage") or {}).get("interaction_count", 0),
        "v8_lessons": (v8.get("learning_coverage") or {}).get("distilled_lesson_count", 0),
        "shadow_supported_lessons": (v8.get("learning_coverage") or {}).get("shadow_supported_lesson_count", 0),
        "strict_supported_lessons": (v8.get("learning_coverage") or {}).get("strict_supported_lesson_count", 0),
        "v9_validation_priorities": sum(item.get("teaching_priority") == "VALIDATION_PRIORITY" for item in ((v9.get("learning_teaching_priority") or {}).get("items") or [])),
        "v7_cortex_ready_candidates": len((v9.get("v7_cortex_handoff") or {}).get("candidates") or []),
        "overlapping_index_note": "Indexed totals are record-equivalents, not asserted unique market events.",
    }


def build_incremental_historical_learning_governor_v1(
    state_dir: str = "state", resource_facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only V10 status.  It never starts a mining partition."""
    state = Path(state_dir)
    checkpoint = _read(state / CHECKPOINT_FILE)
    warehouse_sources = _warehouse_sources(state)
    candidates, partition_counts = _candidates(state, checkpoint, set(warehouse_sources))
    throughput = _work_budget(checkpoint, resource_facts)
    return {
        "suite": "ASTRA Incremental Historical Learning & Coverage Governor V10", "version": VERSION,
        "enabled": True, "current_status": "ERROR" if partition_counts.get("error") else "READY" if candidates else "IDLE_OR_COMPLETE",
        "resource_decision": _resource_decision(state, resource_facts),
        "current_priority_partition": candidates[0] if candidates else None,
        "partition_contract": {"states": ["PENDING", "READY", "PROCESSING", "COMPLETE", "DEFERRED_RESOURCE_PRESSURE", "NO_OUTCOME_DATA", "UNCHANGED", "ERROR"], "checkpoint_file": CHECKPOINT_FILE},
        "work_budget": {"default": {"max_partitions_per_cycle": MAX_PARTITIONS_PER_CYCLE, "max_rows_per_partition": MAX_ROWS_PER_PARTITION, "max_bytes_per_partition": MAX_BYTES_PER_PARTITION}, "recommended": throughput.get("budget"), "hard_max": {"max_rows_per_partition": MAX_ROWS_PER_PARTITION_HARD, "max_bytes_per_partition": MAX_BYTES_PER_PARTITION_HARD}, "max_aggregate_updates": MAX_AGGREGATE_UPDATES_PER_PARTITION, "max_v8_patterns_updated": MAX_V8_PATTERNS_PER_UPDATE, "max_v8_interactions_updated": MAX_V8_INTERACTIONS_PER_UPDATE},
        "warehouse_manager": {"owner": "AstraKnowledgeWarehouseV1", "source_references_available": len(warehouse_sources), "unavailable_target_sources": partition_counts.get("warehouse_unavailable", 0)},
        "canonical_ownership": {"warehouse_manager": "AstraKnowledgeWarehouseV1", "compression": "Knowledge Compression Engine V1", "teacher": "Teacher Layer V1", "v8": "Historical Evidence Mining & Knowledge Distillation V1", "v9": "Evidence Utilization & Information Value V1", "v10": "Incremental Historical Learning Governor V1", "v10_1": "Historical Learning Compression Helpers V1", "adaptation": "V7/Cortex"},
        "throughput": throughput, "coverage_funnel": _coverage(state, checkpoint, set(warehouse_sources)), "last_checkpoint": checkpoint.get("last_checkpoint"),
        "learning_velocity": dict(checkpoint.get("velocity") or {}), "explicit_cycle_required": True,
        **SAFETY,
    }


def run_incremental_historical_learning_cycle_v1(
    state_dir: str = "state", *, resource_facts: Mapping[str, Any] | None = None,
    max_partitions: int = MAX_PARTITIONS_PER_CYCLE, max_rows: int | None = None,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Run at most one safe bounded partition; callers must schedule explicitly."""
    state, started = Path(state_dir), time.monotonic()
    checkpoint_path = state / CHECKPOINT_FILE
    checkpoint = _read(checkpoint_path)
    throughput = _work_budget(checkpoint, resource_facts)
    recommended = dict(throughput.get("budget") or {})
    max_partitions = min(MAX_PARTITIONS_PER_CYCLE, max(0, int(max_partitions)))
    max_rows = min(MAX_ROWS_PER_PARTITION_HARD, max(1, int(max_rows if max_rows is not None else recommended.get("rows", MAX_ROWS_PER_PARTITION))))
    max_bytes = min(MAX_BYTES_PER_PARTITION_HARD, max(1, int(max_bytes if max_bytes is not None else recommended.get("bytes", MAX_BYTES_PER_PARTITION))))
    decision = _resource_decision(state, resource_facts)
    if decision["decision"] != "RUN":
        velocity = checkpoint.setdefault("velocity", {})
        velocity["deferred_cycles"] = int(velocity.get("deferred_cycles") or 0) + 1
        checkpoint["last_checkpoint"] = {"status": "DEFERRED_RESOURCE_PRESSURE", "reason": decision["reason"], "at": _now()}
        _atomic_write(checkpoint_path, checkpoint)
        return {"status": "DEFERRED_RESOURCE_PRESSURE", "resource_decision": decision, "partitions_processed": [], **SAFETY}
    warehouse_sources = _warehouse_sources(state)
    candidates, _ = _candidates(state, checkpoint, set(warehouse_sources))
    if not candidates or max_partitions <= 0:
        return {"status": "UNCHANGED", "resource_decision": decision, "partitions_processed": [], **SAFETY}
    candidate = candidates[0]
    rows, next_offset, bytes_read, error = _read_partition(state / candidate["source"], candidate["cursor_start"], max_bytes=max_bytes, max_rows=max_rows)
    source_state = checkpoint.setdefault("sources", {}).setdefault(candidate["source"], {})
    if error:
        source_state["last_status"] = "ERROR"
        source_state["last_error"] = error
        checkpoint["last_checkpoint"] = {"status": "ERROR", "partition_id": candidate["partition_id"], "reason": error, "at": _now()}
        _atomic_write(checkpoint_path, checkpoint)
        return {"status": "ERROR", "resource_decision": decision, "partitions_processed": [{**candidate, "status": "ERROR", "error": error}], **SAFETY}
    compression = profile_and_compress_partition_v1(
        {**warehouse_sources[candidate["source"]], "source_snapshot": candidate["source_snapshot"]}, candidate["partition_id"], rows,
        _read(state / PACKET_REGISTRY_FILE),
    )
    _atomic_write(state / PACKET_REGISTRY_FILE, compression["updated_registry"])
    representative_rows = list(compression.get("representative_rows") or rows)
    delta_path = state / "storage_summary_indexes" / DELTA_INDEX_FILE
    delta = _read(delta_path) or _empty_delta()
    counters = _merge_partition(delta, candidate["source"], representative_rows)
    if counters["aggregate_updates"] > MAX_AGGREGATE_UPDATES_PER_PARTITION:
        raise RuntimeError("bounded aggregate update contract exceeded")
    _atomic_write(delta_path, _delta_index(delta))
    source_size = int(source_state.get("source_size_bytes") or 0)
    partition_status = "NO_OUTCOME_DATA" if not counters["outcome_linked"] else "COMPLETE" if next_offset >= source_size else "READY"
    source_state.update({"next_offset": next_offset, "last_status": partition_status, "last_partition_id": candidate["partition_id"], "last_processed_at": _now()})
    source_state["partitions_completed"] = int(source_state.get("partitions_completed") or 0) + 1
    source_state["packets_compressed"] = int(source_state.get("packets_compressed") or 0) + len(compression.get("packets") or [])
    source_state["raw_records_represented"] = int(source_state.get("raw_records_represented") or 0) + len(rows)
    elapsed = round(time.monotonic() - started, 6)
    velocity = checkpoint.setdefault("velocity", {})
    throughput_state = checkpoint.setdefault("throughput", {})
    throughput_state["healthy_successful_cycles"] = int(throughput_state.get("healthy_successful_cycles") or 0) + 1
    throughput_state["last_mode"] = throughput.get("mode")
    velocity.update({"last_cycle_outcome_links_added": counters["outcome_linked"], "last_cycle_aggregate_updates": counters["aggregate_updates"], "last_cycle_rows_examined": len(rows), "last_cycle_representative_rows": counters["rows_examined"], "last_cycle_compression_ratio": compression.get("compression_ratio"), "last_cycle_learning_yield_per_1000_records": round(counters["outcome_linked"] * 1000 / len(rows), 3) if rows else 0.0, "last_cycle_duration_seconds": elapsed, "evidence_rows_per_second": round(len(rows) / elapsed, 3) if elapsed else None})
    if not counters["outcome_linked"]:
        velocity["no_outcome_partitions"] = int(velocity.get("no_outcome_partitions") or 0) + 1
    checkpoint["last_checkpoint"] = {"status": partition_status, "partition_id": candidate["partition_id"], "next_cursor": next_offset, "compression_profile": (compression.get("partition_profile") or {}).get("profile_state"), "at": _now()}
    _atomic_write(checkpoint_path, checkpoint)
    v8 = build_historical_evidence_mining_knowledge_distillation_v1(str(state), persist_lessons=True)
    v9 = build_evidence_utilization_information_value_v1(str(state))
    return {"status": partition_status, "resource_decision": decision, "throughput": throughput, "partitions_processed": [{**candidate, "status": partition_status, "next_cursor": next_offset, "rows_examined": len(rows), "representative_rows": counters["rows_examined"], "outcome_linked_count": counters["outcome_linked"], "aggregate_updates": counters["aggregate_updates"], "bytes_read": bytes_read, "duration_seconds": elapsed, "compression_profile": compression.get("partition_profile"), "compression_ratio": compression.get("compression_ratio")}], "canonical_handoffs": {"compression": compression.get("canonical_compression_handoff"), "teacher": compression.get("canonical_teacher_handoff")}, "v8_bounded_snapshot": {"patterns": (v8.get("learning_coverage") or {}).get("pattern_count"), "interactions": (v8.get("learning_coverage") or {}).get("interaction_count"), "lessons": (v8.get("learning_coverage") or {}).get("distilled_lesson_count")}, "v9_bounded_snapshot": {"validation_priorities": sum(item.get("teaching_priority") == "VALIDATION_PRIORITY" for item in ((v9.get("learning_teaching_priority") or {}).get("items") or [])), "v7_candidates": len((v9.get("v7_cortex_handoff") or {}).get("candidates") or [])}, **SAFETY}
