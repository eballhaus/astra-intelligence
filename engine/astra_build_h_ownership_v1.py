"""Bounded ownership catalog for Astra Build H.

This module is diagnostic-only.  It inventories known stores by metadata and
existing summary indexes; it never walks the runtime tree or mutates data.
"""

from __future__ import annotations

import os
from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, now_iso, read_json, with_safety

VERSION = "1.0.0"

STORE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "store": "broker_truth_records_v1",
        "path": "broker_truth_records_v1.json",
        "owner": "closed_trade_truth_registry_v1",
        "writer": "broker truth reconciliation",
        "readers": ["canonical outcomes", "paper performance", "governance"],
        "evidence_class": "broker_confirmed_truth",
        "authority": "AUTHORITATIVE",
        "rebuildable": False,
        "index": None,
        "retention": "preserve_authoritative_history",
    },
    {
        "store": "canonical_outcomes",
        "path": "canonical_outcomes_v1.jsonl",
        "owner": "canonical_outcome_builder_v1",
        "writer": "canonical outcome reconciliation",
        "readers": ["performance attribution", "learning", "governance"],
        "evidence_class": "canonical_derived_from_broker_truth",
        "authority": "DERIVED",
        "rebuildable": True,
        "index": "storage_summary_indexes/outcome_labels_v1.jsonl.summary_index.json",
        "retention": "preserve_lineage",
    },
    {
        "store": "lifecycle_lessons",
        "path": "canonical_lifecycle_lessons_v1.jsonl",
        "owner": "cortex_lifecycle_evidence_master_truth_v1",
        "writer": "lifecycle lesson consolidation",
        "readers": ["librarian", "cortex", "exit diagnostics"],
        "evidence_class": "validated_lesson",
        "authority": "DERIVED",
        "rebuildable": True,
        "index": "canonical_lifecycle_lessons_summary_v1.json",
        "retention": "review_and_expire_non_authoritative_lessons",
    },
    {
        "store": "recommendation_history",
        "path": "recommendation_history_v1.jsonl",
        "owner": "recommendation_history_and_attribution",
        "writer": "copilot recommendation attribution",
        "readers": ["copilot", "effectiveness", "decision trace"],
        "evidence_class": "recommendation_event",
        "authority": "DERIVED",
        "rebuildable": False,
        "index": "state/knowledge_retrieval_index_v1.json",
        "retention": "append_only_audit",
    },
    {
        "store": "opportunity_cost",
        "path": "opportunity_cost_learning_v1.jsonl",
        "owner": "opportunity_cost_learning_v1",
        "writer": "opportunity cost learning",
        "readers": ["ranking diagnostics", "learning velocity", "shadow"],
        "evidence_class": "diagnostic_learning",
        "authority": "DERIVED",
        "rebuildable": True,
        "index": "storage_summary_indexes/opportunity_cost_learning_v1.jsonl.summary_index.json",
        "retention": "bounded_derived_history",
    },
    {
        "store": "trade_memory_similarity",
        "path": "trade_memory_similarity_v1.jsonl",
        "owner": "long_term_memory_symbol_retrieval_suite_v1",
        "writer": "symbol memory retrieval",
        "readers": ["symbol intelligence", "historical similarity", "copilot"],
        "evidence_class": "historical_similarity",
        "authority": "DERIVED",
        "rebuildable": True,
        "index": "storage_summary_indexes/trade_memory_similarity_v1.jsonl.summary_index.json",
        "retention": "warm_then_cold",
    },
    {
        "store": "replay_counterfactual",
        "path": "replay_counterfactual_learning_v2.jsonl",
        "owner": "replay_counterfactual_learning_v2",
        "writer": "replay and counterfactual learning",
        "readers": ["shadow governance", "effectiveness", "learning"],
        "evidence_class": "replay_counterfactual",
        "authority": "DERIVED",
        "rebuildable": True,
        "index": "storage_summary_indexes/replay_counterfactual_learning_v2.jsonl.summary_index.json",
        "retention": "warm_then_cold",
    },
    {
        "store": "market_context",
        "path": "market_context_learning_suite_v1.jsonl",
        "owner": "market_context_learning_suite_v1",
        "writer": "market context learning",
        "readers": ["regime", "catalyst", "copilot", "shadow"],
        "evidence_class": "provider_context_cached",
        "authority": "DERIVED",
        "rebuildable": True,
        "index": "storage_summary_indexes/market_context_learning_suite_v1.jsonl.summary_index.json",
        "retention": "warm_then_cold",
    },
    {
        "store": "candidate_decision_ledger",
        "path": "candidate_decision_ledger_v1.jsonl",
        "owner": "candidate_ranking_attribution_promotion_intelligence_v1",
        "writer": "candidate decision attribution",
        "readers": ["ranking", "promotion diagnostics", "effectiveness"],
        "evidence_class": "ranking_diagnostic",
        "authority": "DERIVED",
        "rebuildable": True,
        "index": "storage_summary_indexes/candidate_decision_ledger_v1.jsonl.summary_index.json",
        "retention": "bounded_derived_history",
    },
    {
        "store": "ai_trading_memory",
        "path": "ai_trading_memory.db",
        "owner": "trade_intelligence_and_memory",
        "writer": "trade intelligence relational persistence",
        "readers": ["trade intelligence", "portfolio", "performance"],
        "evidence_class": "relational_trade_memory",
        "authority": "DERIVED_WITH_RELATIONAL_AUTHORITY_BY_TABLE",
        "rebuildable": False,
        "index": "sqlite_internal_indexes",
        "retention": "preserve_until_table_authority_audited",
    },
    {
        "store": "knowledge_retrieval_index",
        "path": "knowledge_retrieval_index_v1.json",
        "owner": "knowledge_retrieval_indexing_v1",
        "writer": "retrieval index builder",
        "readers": ["learning", "librarian", "warehouse manager"],
        "evidence_class": "index_metadata",
        "authority": "INDEX",
        "rebuildable": True,
        "index": "self",
        "retention": "rebuildable_with_manifest",
    },
    {
        "store": "storage_summary_indexes",
        "path": "storage_summary_indexes/",
        "owner": "astra_storage_cache_attribution_learning_efficiency_v1",
        "writer": "storage/cache analyzer",
        "readers": ["bounded diagnostics", "retrieval health", "warehouse manager"],
        "evidence_class": "summary_index",
        "authority": "INDEX",
        "rebuildable": True,
        "index": "self",
        "retention": "incremental_rebuild",
    },
    {
        "store": "dashboard_cache",
        "path": "dashboard_cache/",
        "owner": "unified diagnostics cache",
        "writer": "dashboard and diagnostic adapters",
        "readers": ["dashboard", "Learning Center", "Copilot"],
        "evidence_class": "cached_summary",
        "authority": "CACHE",
        "rebuildable": True,
        "index": None,
        "retention": "ttl_and_rebuildable",
    },
)


def _first_count(payload: dict[str, Any]) -> int | None:
    for key in ("record_count", "records", "rows", "count", "indexed_records", "total_records"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


class AstraBuildHOwnershipMapV1(CachedDiagnosticModule):
    module_name = "astra_build_h_ownership_map_v1"
    mode = "shadow_only_bounded_storage_ownership_audit"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        storage_status = statuses.get("astra_storage_cache_attribution_learning_efficiency_v1") or {}
        stores: list[dict[str, Any]] = []
        for definition in STORE_CATALOG:
            row = dict(definition)
            relative = str(definition.get("path") or "")
            path = os.path.join(self.state_dir, relative.rstrip("/"))
            exists = os.path.exists(path)
            size = 0
            modified = None
            if exists and os.path.isfile(path):
                try:
                    stat = os.stat(path)
                    size = int(stat.st_size)
                    modified = stat.st_mtime
                except OSError:
                    exists = False
            index_path = definition.get("index")
            index_payload = {}
            if index_path and not str(index_path).startswith("state/"):
                index_payload = read_json(os.path.join(self.state_dir, str(index_path)))
            row.update({
                "exists": exists,
                "size_bytes": size,
                "modified_epoch": modified,
                "record_count_estimate": _first_count(index_payload),
                "index_available": bool(index_payload) if index_path else False,
                "schema_version": index_payload.get("schema_version") if index_payload else None,
                "metadata_only_scan": True,
            })
            stores.append(row)
        missing_owner = [row["store"] for row in stores if not row.get("owner")]
        conflicts = []
        authoritative = [row["store"] for row in stores if str(row.get("authority", "")).startswith("AUTHORITATIVE")]
        if len(authoritative) != 1:
            conflicts.append("authoritative_store_count_requires_review")
        largest = sorted(stores, key=lambda row: int(row.get("size_bytes") or 0), reverse=True)[:8]
        total_storage = storage_status.get("total_storage_bytes")
        if total_storage is None:
            total_storage = storage_status.get("storage_total_bytes")
        status = "OWNERSHIP_MAP_PASS"
        warnings: list[str] = []
        if missing_owner or conflicts:
            status = "OWNERSHIP_MAP_PASS_WITH_WARNINGS"
            warnings.extend(["missing_owner"] if missing_owner else [])
            warnings.extend(conflicts)
        return with_safety({
            "endpoint": "/api/astra_build_h_ownership_map_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "scan_policy": "bounded_known_store_metadata_and_existing_indexes_only",
            "stores_inventoried": len(stores),
            "canonical_owners_assigned": len(stores) - len(missing_owner),
            "unknown_owners": missing_owner,
            "duplicated_active_stores": [],
            "stale_or_unused_stores": [],
            "authoritative_data_conflicts": conflicts,
            "missing_schema_versions": [row["store"] for row in stores if row.get("exists") and not row.get("schema_version") and row.get("authority") in {"AUTHORITATIVE", "DERIVED"}],
            "missing_indexes": [row["store"] for row in stores if row.get("exists") and row.get("index") and not row.get("index_available")],
            "missing_retention_policy": [row["store"] for row in stores if not row.get("retention")],
            "missing_recovery_path": [],
            "total_storage_bytes": int(total_storage or 0),
            "largest_stores": largest,
            "warnings": warnings,
            "stores": stores,
            "no_destructive_migration": True,
            "provider_calls_used": 0,
            "broker_calls_used": 0,
            "llm_calls_used": 0,
        })
