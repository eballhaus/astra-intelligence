"""Canonical, bounded retrieval contract for existing Astra knowledge stores.

The warehouse is an orchestration facade, not a second storage system.  It
selects existing summary indexes and bounded tails, returns source lineage,
and refuses to turn a query into a full-history scan.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from engine.astra_build_h_ownership_v1 import STORE_CATALOG
from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    clamp,
    now_iso,
    read_json,
    rounded,
    tail_jsonl,
    text,
    to_int,
    with_safety,
)

VERSION = "1.0.0"
MAX_RESULTS = 100
MAX_FILES = 8
MAX_RAW_ROWS = 240
MAX_RAW_BYTES = 1_000_000
DISTILLED_LESSONS_REGISTRY = "historical_evidence_distilled_lessons_v1.json"
SUPPORTED_DIMENSIONS = (
    "symbol", "asset_class", "sector", "theme", "catalyst", "regime",
    "archetype", "trade_style", "horizon", "recommendation_state",
    "lifecycle_status", "evidence_class", "outcome_label", "confidence_bucket",
)


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if expected in (None, "", [], {}):
            continue
        value = row.get(key)
        if value in (None, ""):
            aliases = {
                "symbol": ("ticker", "asset_symbol", "selected_symbol"),
                "horizon": ("horizon_style", "selected_horizon"),
                "asset_class": ("asset_type",),
                "outcome_label": ("outcome", "label"),
            }
            for alias in aliases.get(key, ()):
                if row.get(alias) not in (None, ""):
                    value = row.get(alias)
                    break
        if _norm(value) != _norm(expected):
            return False
    return True


class AstraKnowledgeWarehouseV1(CachedDiagnosticModule):
    module_name = "astra_knowledge_warehouse_v1"
    mode = "shadow_only_bounded_existing_store_orchestration"

    def _catalog(self) -> list[dict[str, Any]]:
        catalog = []
        for definition in STORE_CATALOG:
            row = dict(definition)
            path = os.path.join(self.state_dir, str(row.get("path") or "").rstrip("/"))
            row["exists"] = os.path.exists(path)
            row["size_bytes"] = os.path.getsize(path) if os.path.isfile(path) else 0
            index_path = row.get("index")
            index_payload = {}
            if index_path and not str(index_path).startswith("state/"):
                index_payload = read_json(os.path.join(self.state_dir, str(index_path)))
            row["index_available"] = bool(index_payload) if index_path else False
            row["index_generation"] = index_payload.get("index_generation") if index_payload else None
            row["record_count_estimate"] = next(
                (int(index_payload[key]) for key in ("record_count", "records", "rows", "count", "indexed_records") if isinstance(index_payload.get(key), (int, float))),
                None,
            )
            catalog.append(row)
        return catalog

    def _select_sources(self, filters: dict[str, Any], max_files: int) -> list[dict[str, Any]]:
        haystack = " ".join(_norm(value) for value in filters.values())
        ranked: list[tuple[int, dict[str, Any]]] = []
        for row in self._catalog():
            if not row.get("exists"):
                continue
            name = _norm(row.get("store")) + " " + _norm(row.get("evidence_class"))
            score = 1
            if any(token in name for token in ("broker", "canonical", "outcome")):
                score += 5
            if haystack and any(token in name for token in haystack.split()):
                score += 2
            if row.get("index_available"):
                score += 3
            ranked.append((score, row))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("store"))))
        return [row for _, row in ranked[: max(1, min(MAX_FILES, int(max_files or MAX_FILES)))]]

    def source_references(self, allowed_paths: set[str] | None = None, max_sources: int = MAX_FILES) -> list[dict[str, Any]]:
        """Return bounded manifest references without opening raw evidence."""
        allowed = {str(path) for path in (allowed_paths or set())}
        rows = []
        for source in self._catalog():
            path = str(source.get("path") or "")
            if allowed and path not in allowed:
                continue
            if not source.get("exists") or not path.endswith(".jsonl"):
                continue
            rows.append({
                "source_identity": source.get("store"), "path": path, "index": source.get("index"),
                "owner": source.get("owner"), "evidence_class": source.get("evidence_class"),
                "authority": source.get("authority"), "size_bytes": source.get("size_bytes", 0),
                "record_count_estimate": source.get("record_count_estimate"),
                "index_generation": source.get("index_generation"), "index_available": source.get("index_available", False),
            })
        return sorted(rows, key=lambda row: str(row["path"]))[:max(1, min(MAX_FILES, int(max_sources or MAX_FILES)))]

    def query(self, query: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        requested = dict(query or {})
        invalid = sorted(set(requested) - set(SUPPORTED_DIMENSIONS) - {"date_from", "date_to", "freshness_requirement", "max_results", "max_files", "detail_level", "page"})
        filters = {key: requested.get(key) for key in SUPPORTED_DIMENSIONS if requested.get(key) not in (None, "")}
        max_results = max(1, min(MAX_RESULTS, to_int(requested.get("max_results"), 25)))
        max_files = max(1, min(MAX_FILES, to_int(requested.get("max_files"), MAX_FILES)))
        page = max(1, to_int(requested.get("page"), 1))
        sources = self._select_sources(filters, max_files)
        rows: list[dict[str, Any]] = []
        raw_records_read = 0
        files_opened = 0
        used_indexes: list[str] = []
        partitions: list[str] = []
        detail = _norm(requested.get("detail_level") or "summary")
        if not invalid:
            for source in sources:
                path = os.path.join(self.state_dir, str(source.get("path") or "").rstrip("/"))
                index_path = source.get("index")
                index_payload = read_json(os.path.join(self.state_dir, str(index_path))) if index_path and not str(index_path).startswith("state/") else {}
                if index_payload:
                    used_indexes.append(str(index_path))
                    partitions.append(str(source.get("path")))
                    summary = {
                        "source_store": source.get("store"),
                        "evidence_class": source.get("evidence_class"),
                        "record_count_estimate": source.get("record_count_estimate"),
                        "index_generation": source.get("index_generation"),
                        "summary_only": True,
                    }
                    if detail != "raw":
                        rows.append(summary)
                        continue
                if detail == "raw" and os.path.isfile(path) and path.endswith(".jsonl"):
                    bounded = tail_jsonl(path, max_rows=MAX_RAW_ROWS, max_bytes=MAX_RAW_BYTES)
                    files_opened += 1
                    raw_records_read += len(bounded)
                    rows.extend([{**row, "source_store": source.get("store"), "evidence_class": source.get("evidence_class"), "summary_only": False} for row in bounded if _matches(row, filters)])
                elif detail == "raw" and os.path.isfile(path) and path.endswith(".json"):
                    payload = read_json(path)
                    files_opened += 1
                    raw_records_read += 1
                    if payload and _matches(payload, filters):
                        rows.append({**payload, "source_store": source.get("store"), "evidence_class": source.get("evidence_class"), "summary_only": False})
        start = (page - 1) * max_results
        page_rows = rows[start : start + max_results]
        query_id = "whq_" + hashlib.sha1(repr(sorted(requested.items())).encode("utf-8", errors="ignore")).hexdigest()[:12]
        return with_safety({
            "endpoint": "/api/astra_knowledge_warehouse_v1",
            "version": VERSION,
            "status": "invalid_query" if invalid else "ok",
            "query_id": query_id,
            "query": requested,
            "source_catalog_entry": [row.get("store") for row in sources],
            "authoritative_source": "broker_truth_records_v1",
            "index_used": used_indexes,
            "partitions_or_stores_used": partitions,
            "evidence_class": filters.get("evidence_class") or "mixed_or_source_declared",
            "freshness": "cache_or_index_declared",
            "retrieved_count": len(page_rows),
            "total_matching_estimate": len(rows),
            "latency_ms": rounded((time.perf_counter() - started) * 1000.0, 3),
            "cache_status": "bounded_local_index_or_tail",
            "raw_records_read": raw_records_read,
            "files_opened": files_opened,
            "full_history_scan_used": False,
            "fallback_reason": "unsupported_dimension" if invalid else None,
            "truncated": len(rows) > start + max_results,
            "page": page,
            "page_size": max_results,
            "rows": page_rows,
            "invalid_dimensions": invalid,
        })

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        catalog = self._catalog()
        existing = [row for row in catalog if row.get("exists")]
        indexes = [row for row in existing if row.get("index_available")]
        distilled = read_json(os.path.join(self.state_dir, DISTILLED_LESSONS_REGISTRY))
        distilled_lessons = list(distilled.get("lessons") or []) if isinstance(distilled, dict) else []
        distilled_lesson_reuse = {
            "owner": "historical_evidence_mining_knowledge_distillation_v1",
            "retention": "bounded_registry_rebuild_with_v8",
            "lessons_available": len(distilled_lessons),
            "deduplicated": bool(distilled.get("deduplicated", True)),
            "registry_generated_at": distilled.get("updated_at"),
            "advisory_only": True,
            "automatic_adaptation": False,
            "evidence_class": "distilled_lesson",
            "bounded_read": True,
        }
        storage_status = statuses.get("astra_storage_cache_attribution_learning_efficiency_v1") or {}
        total_storage = storage_status.get("total_storage_bytes") or storage_status.get("storage_total_bytes")
        daily_growth = storage_status.get("daily_growth_bytes") or storage_status.get("estimated_daily_growth_bytes")
        total_storage_value = int(total_storage) if isinstance(total_storage, (int, float)) else None
        daily_growth_value = int(daily_growth) if isinstance(daily_growth, (int, float)) else None
        projections = {}
        if total_storage_value is not None and daily_growth_value is not None and daily_growth_value >= 0:
            projections = {
                "one_year_bytes": total_storage_value + daily_growth_value * 365,
                "three_year_bytes": total_storage_value + daily_growth_value * 365 * 3,
                "five_year_bytes": total_storage_value + daily_growth_value * 365 * 5,
                "projection_basis": "current measured daily growth where available",
            }
        return with_safety({
            "endpoint": "/api/astra_knowledge_warehouse_v1",
            "version": VERSION,
            "status": "ok" if existing else "insufficient_evidence",
            "generated_at": now_iso(),
            "canonical_layer": True,
            "warehouse_role": "orchestrate_existing_stores_not_replace_them",
            "source_catalog": catalog,
            "canonical_authoritative_sources": ["broker_truth_records_v1"],
            "derived_sources": [row.get("store") for row in existing if row.get("authority") == "DERIVED"],
            "cache_sources": [row.get("store") for row in existing if row.get("authority") == "CACHE"],
            "index_sources": [row.get("store") for row in existing if row.get("authority") == "INDEX"],
            "query_contract_dimensions": list(SUPPORTED_DIMENSIONS) + ["date_from", "date_to", "freshness_requirement", "max_results", "max_files", "detail_level", "page"],
            "bounded_read_policy": {"max_results": MAX_RESULTS, "max_files": MAX_FILES, "max_raw_rows": MAX_RAW_ROWS, "max_raw_bytes": MAX_RAW_BYTES, "timeout_ms": 5000},
            "hot_warm_cold_policy": {"hot": "current broker and recommendation summaries", "warm": "recent lessons and outcomes", "cold": "older raw and replay detail"},
            "source_lineage_supported": True,
            "manifest_first": True,
            "full_history_fallback": False,
            "consumer_migration": {
                "copilot": "compatible_summary_contract",
                "cortex": "existing_librarian_and_truth_preserved",
                "governance": "existing_storage_and_runtime_audits_preserved",
                "learning_center": "unified_cached_summary",
                "ask_astra": "contract_ready_no_new_llm_calls",
            },
            "catalog_entries": len(catalog),
            "existing_stores": len(existing),
            "indexed_stores": len(indexes),
            "index_coverage_pct": rounded(len(indexes) * 100.0 / max(1, len(existing)), 3),
            "status_summary": "bounded_index_first_retrieval_with_tail_fallback",
            "storage_profile": {
                "hot": [row.get("store") for row in existing if row.get("authority") == "AUTHORITATIVE" or row.get("authority") == "CACHE"],
                "warm": [row.get("store") for row in existing if row.get("authority") == "DERIVED" and row.get("evidence_class") not in {"historical_similarity", "replay_counterfactual"}],
                "cold": [row.get("store") for row in existing if row.get("evidence_class") in {"historical_similarity", "replay_counterfactual"}],
                "tier_move_policy": "metadata_only_until_governed_compaction_worker_is_available",
            },
            "manifest_status": {
                "manifest_first": True,
                "manifest_entries": len(existing),
                "valid_entries": sum(1 for row in existing if row.get("index_available") or row.get("authority") == "AUTHORITATIVE"),
                "checksum_validation": "not_run_on_render",
                "schema_mismatch_detected": False,
                "orphaned_partitions": [],
            },
            "partitioning_status": "existing_partition_metadata_reused; new partition migration deferred",
            "rotation_status": "not_started_non_destructive",
            "compression_status": "existing_summary_indexes_and_lesson_compression_reused",
            "distilled_lesson_reuse": distilled_lesson_reuse,
            "incremental_index_status": {
                "index_generation_observed": any(row.get("index_generation") for row in indexes),
                "index_lag_measured": False,
                "pending_updates": None,
                "full_rebuild_on_render": False,
            },
            "compaction_status": "diagnostic_only_resumable_worker_not_started",
            "retention_status": "authoritative_preserved_derived_policy_declared",
            "sqlite_health": "not_mutated_by_build_h",
            "growth_projection": projections or {"status": "insufficient_evidence", "reason": "daily_growth_not_exposed_by_existing_storage_status"},
            "storage_total_bytes": total_storage_value,
            "daily_growth_bytes": daily_growth_value,
            "provider_calls_used": 0,
            "broker_calls_used": 0,
            "llm_calls_used": 0,
        })
