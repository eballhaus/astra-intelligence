"""V10.1 bounded profiling and packet handoffs for canonical learning owners."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Mapping

from engine.astra_aios_intelligence_maturation_bundle_v1 import build_teacher_handoff_from_compressed_lessons_v1
from engine.astra_knowledge_warehouse_v1 import AstraKnowledgeWarehouseV1
from engine.astra_storage_cache_attribution_learning_efficiency_v1 import _outcome_tier, _outcome_value, outcome_dimensions_for_row
from engine.astra_tier2a_librarian_executive_truth_layer_v1 import compress_historical_packet_handoffs_v1


VERSION = "1.0.0"
MAX_PACKET_PROVENANCE_REFS = 16
MAX_PACKETS_PER_PARTITION = 64
THROUGHPUT = {
    "PAUSED": {"rows": 0, "bytes": 0, "partitions": 0},
    "CONSERVATIVE": {"rows": 240, "bytes": 64 * 1024, "partitions": 1},
    "NORMAL": {"rows": 480, "bytes": 128 * 1024, "partitions": 1},
    "ACCELERATED": {"rows": 960, "bytes": 256 * 1024, "partitions": 1},
}
SAFETY = {
    "provider_calls_added": 0, "broker_calls_added": 0, "broker_actions_added": 0, "llm_calls_added": 0,
    "execution_behavior_changed": False, "automatic_adaptation_authority": False,
    "frozen_lifecycle_modified": False, "full_history_scan_count": 0,
}


def warehouse_partition_references_v1(state_dir: str, allowed_paths: set[str]) -> list[dict[str, Any]]:
    """Ask the Warehouse Manager for manifest-first source references."""
    return AstraKnowledgeWarehouseV1(state_dir=state_dir).source_references(allowed_paths=allowed_paths, max_sources=8)


def _identity(row: Mapping[str, Any], source: str) -> tuple[str, str]:
    stable = next((row.get(key) for key in ("stable_key", "lifecycle_id", "candidate_id", "event_id", "id") if row.get(key) not in (None, "")), None)
    outcome = _outcome_value(dict(row))
    if stable is not None:
        return f"identity:{source}:{_outcome_tier(dict(row), source)}:{stable}", str(stable)
    dimensions = outcome_dimensions_for_row(dict(row), source)
    material = {"source": source, "dimensions": dimensions, "outcome": outcome, "tier": _outcome_tier(dict(row), source), "label": row.get("outcome_label") or row.get("outcome") or row.get("result"), "timestamp": row.get("timestamp") or row.get("created_at")}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return f"equivalent:{hashlib.sha256(encoded.encode()).hexdigest()[:20]}", "UNAVAILABLE"


def profile_and_compress_partition_v1(source_ref: Mapping[str, Any], partition_id: str, rows: list[dict[str, Any]], registry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Profile a supplied bounded partition and hand deduplicated packets onward.

    This does not locate or read source files; Warehouse Manager/V10 retain those
    responsibilities.  Packet grouping is exact-equivalence only.
    """
    source = str(source_ref.get("path") or source_ref.get("source_identity") or "unknown_source")
    groups: dict[str, list[dict[str, Any]]] = {}
    pending, tier_counts, linked = {}, Counter(), 0
    for row in rows:
        key, identity = _identity(row, source)
        groups.setdefault(key, []).append(dict(row))
        value = _outcome_value(row)
        if value is None and identity != "UNAVAILABLE":
            pending[identity] = {"source": source, "partition_id": partition_id}
        else:
            linked += 1
            pending.pop(identity, None)
            tier_counts[_outcome_tier(row, source)] += 1
    packets = []
    for key, grouped in sorted(groups.items())[:MAX_PACKETS_PER_PARTITION]:
        first = grouped[0]
        dimensions = outcome_dimensions_for_row(first, source)
        values = [_outcome_value(row) for row in grouped if _outcome_value(row) is not None]
        tiered = Counter(_outcome_tier(row, source) for row in grouped)
        source_ids = [next((str(row.get(field)) for field in ("stable_key", "lifecycle_id", "candidate_id", "event_id", "id") if row.get(field) not in (None, "")), None) for row in grouped]
        # A stable packet identity lets a later outcome update its pending
        # observation rather than creating a second learning packet.
        packet_id = "packet:" + hashlib.sha256(f"{source}|{key}".encode()).hexdigest()[:20]
        packets.append({
            "packet_id": packet_id, "schema_version": VERSION, "source_partition_ids": [partition_id],
            "warehouse_source_identity": source_ref.get("source_identity"), "warehouse_source_path": source,
            "source_snapshot": source_ref.get("source_snapshot"), "raw_equivalent_count": len(grouped),
            "deduplicated_observation_count": 1, "evidence_tier_counts": dict(tiered),
            "dimensions": dimensions, "outcome_linked_count": len(values), "wins": sum(value > 0 for value in values),
            "losses": sum(value < 0 for value in values), "unknown_outcomes": len(grouped) - len(values),
            "average_return_pct": round(sum(values) / len(values), 5) if values else None,
            "provenance_references": [value for value in source_ids if value][:MAX_PACKET_PROVENANCE_REFS],
            "provenance_hash": hashlib.sha256((source + "|" + key).encode()).hexdigest()[:20],
            "evidence_tier_not_promoted": True,
        })
    raw_count, packet_count = len(rows), len(packets)
    duplicate_density = round((raw_count - packet_count) / raw_count, 5) if raw_count else 0.0
    link_density = round(linked / raw_count, 5) if raw_count else 0.0
    profile_state = "NO_OUTCOME_SIGNAL" if not linked else "REDUNDANT_HEAVY" if duplicate_density >= 0.5 else "HIGH_YIELD" if link_density >= 0.5 else "MEDIUM_YIELD" if link_density >= 0.1 else "LOW_YIELD"
    compression = compress_historical_packet_handoffs_v1(packets)
    teacher = build_teacher_handoff_from_compressed_lessons_v1(compression.get("compressed_lessons") or [])
    previous = dict(registry or {})
    stored_packets = dict(previous.get("packets") or {})
    for packet in packets:
        existing = dict(stored_packets.get(packet["packet_id"]) or {})
        if existing:
            packet["source_partition_ids"] = sorted(set((existing.get("source_partition_ids") or []) + packet["source_partition_ids"]))
            packet["raw_equivalent_count"] = max(int(existing.get("raw_equivalent_count") or 0), int(packet["raw_equivalent_count"] or 0))
        stored_packets[packet["packet_id"]] = packet
    pending_registry = dict(previous.get("pending_outcomes") or {})
    pending_registry.update(pending)
    for packet in packets:
        for reference in packet.get("provenance_references") or []:
            if packet.get("outcome_linked_count"):
                pending_registry.pop(str(reference), None)
    updated_registry = {"version": VERSION, "packets": stored_packets, "pending_outcomes": pending_registry}
    return {
        "partition_profile": {"partition_id": partition_id, "source": source, "profile_state": profile_state, "rows_sampled": raw_count, "outcome_link_density": link_density, "duplicate_density": duplicate_density, "tier_counts": dict(tier_counts), "packet_count": packet_count},
        "packets": packets,
        "representative_rows": [{**grouped[0], "_v10_compression_weight": len(grouped)} for _, grouped in sorted(groups.items())[:MAX_PACKETS_PER_PARTITION]],
        "compression_ratio": round(raw_count / packet_count, 5) if packet_count else None,
        "canonical_compression_handoff": compression, "canonical_teacher_handoff": teacher,
        "updated_registry": updated_registry, "full_history_scan_count": 0, **SAFETY,
    }


def adaptive_throughput_v1(history: Mapping[str, Any] | None, resource_facts: Mapping[str, Any] | None) -> dict[str, Any]:
    """Recommend a bounded serial budget; pressure always wins immediately."""
    history, facts = dict(history or {}), dict(resource_facts or {})
    unhealthy = bool(facts.get("worker_cycle_error") or facts.get("suppressed_execution_exception") or facts.get("trading_priority_active"))
    pressure = str(facts.get("resource_state") or "RESOURCE_NORMAL").upper()
    if unhealthy or pressure not in {"RESOURCE_NORMAL", "RESOURCE_ELEVATED", ""}:
        mode = "PAUSED"
    else:
        successes = int(history.get("healthy_successful_cycles") or 0)
        mode = "ACCELERATED" if successes >= 6 else "NORMAL" if successes >= 3 else "CONSERVATIVE"
    return {"mode": mode, "budget": dict(THROUGHPUT[mode]), "parallelism_enabled": False, "maximum_parallelism": 1, "reason": "RESOURCE_OR_TRADING_PRIORITY" if mode == "PAUSED" else "GRADUAL_HEALTHY_CHECKPOINTS", **SAFETY}
