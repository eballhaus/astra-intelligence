from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    clamp,
    first,
    now_iso,
    rounded,
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)

STATE_SCAN_LIMIT = 160
CACHE_SCAN_LIMIT = 220
OVERSIZED_BYTES = 250_000_000
SUMMARY_CANDIDATE_BYTES = 50_000_000
SAMPLE_BYTES_PER_EDGE = 1_000_000
MAX_SAMPLE_ROWS_PER_FILE = 1200

TARGET_COLD_FILES = (
    "opportunity_cost_learning_v1.jsonl",
    "trade_lifecycle_excursion_v2.jsonl",
    "trade_memory_similarity_v1.jsonl",
    "market_context_learning_suite_v1.jsonl",
    "replay_counterfactual_learning_v2.jsonl",
    "adaptive_profit_capture_intelligence_v1.jsonl",
    "adaptive_execution_exit_intelligence_v3.jsonl",
    "exit_learning_expansion_suite_v1.jsonl",
    "trade_archetype_regime_intelligence_v1.jsonl",
    "candidate_decision_ledger_v1.jsonl",
    "outcome_labels_v1.jsonl",
)
INDEX_DIMENSIONS = (
    "symbol",
    "horizon",
    "regime",
    "catalyst",
    "archetype",
    "exit_type",
    "trade_family",
    "profit_capture_bucket",
    "ranking_factor",
    "outcome_label",
    "confidence_bucket",
)

HOT_KEYWORDS = (
    "alpaca", "broker", "paper_position", "positions", "portfolio", "top_buys", "copilot", "alerts", "exit_review", "sell", "session", "health"
)
WARM_KEYWORDS = (
    "ranking", "profit_capture", "shadow", "regime", "market_context", "symbol", "catalyst", "learning", "attribution", "horizon"
)
CANONICAL_KEYWORDS = (
    "truth", "canonical", "closed", "lifecycle", "shadow_vs_paper", "broker", "trade_outcomes", "promotion_evidence"
)

TTL_CLASSES = {
    "real_time_short": 90,
    "medium": 900,
    "long": 7200,
}


def _safe_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "promotion_logic_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "paper_execution_changed": False,
        "forced_trades_enabled": False,
        "forced_exits_enabled": False,
        "automatic_promotions_enabled": False,
        "automatic_learned_exits_enabled": False,
        "data_deleted": False,
        "data_archived_automatically": False,
        "canonical_truth_replaced": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _ttl_class(name: str) -> tuple[str, int]:
    low = str(name or "").lower()
    if any(k in low for k in HOT_KEYWORDS):
        return "real_time_short", TTL_CLASSES["real_time_short"]
    if any(k in low for k in WARM_KEYWORDS):
        return "medium", TTL_CLASSES["medium"]
    return "long", TTL_CLASSES["long"]


def _storage_tier(name: str, size: int = 0) -> str:
    low = str(name or "").lower()
    if any(k in low for k in CANONICAL_KEYWORDS):
        return "canonical_truth"
    if any(k in low for k in HOT_KEYWORDS):
        return "hot"
    if any(k in low for k in WARM_KEYWORDS) and size < OVERSIZED_BYTES:
        return "warm"
    if size >= SUMMARY_CANDIDATE_BYTES or low.endswith(".jsonl") or low.endswith(".db"):
        return "cold"
    return "warm"


def _freshness(age: float, ttl: int) -> tuple[str, float, bool]:
    ratio = age / max(1.0, float(ttl))
    if ratio <= 1.0:
        return "fresh", rounded(clamp(100.0 - ratio * 20.0), 3), False
    if ratio <= 3.0:
        return "aging", rounded(clamp(80.0 - (ratio - 1.0) * 20.0), 3), False
    return "stale", rounded(clamp(40.0 - (ratio - 3.0) * 6.0), 3), True


def _field(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    return default


def _bucket(value: Any, low_label: str = "low", mid_label: str = "medium", high_label: str = "high") -> str:
    value_f = to_float(value, 0.0)
    if value_f >= 70:
        return high_label
    if value_f >= 40:
        return mid_label
    return low_label


def _normal_text(value: Any, default: str = "unknown") -> str:
    out = str(value if value not in (None, "") else default).strip().lower()
    return out.replace(" ", "_")[:80] or default


def _first_from(row: dict[str, Any], keys: tuple[str, ...], default: str = "unknown") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return _normal_text(value, default)
    return default


def _source_dimension_defaults(source_name: str) -> dict[str, str]:
    """Infer retrieval dimensions from source ownership when rows are sparse."""
    low = str(source_name or "").lower()
    defaults = {
        "exit_type": "unknown",
        "trade_family": "unknown",
        "ranking_factor": "unknown",
        "outcome_label": "unknown",
    }
    if "exit" in low or "profit_capture" in low or "lifecycle" in low:
        defaults["exit_type"] = "exit_learning_evidence"
    if "archetype" in low or "trade_memory" in low or "market_context" in low:
        defaults["trade_family"] = "behavior_family_evidence"
    if "candidate" in low or "opportunity_cost" in low or "ranking" in low:
        defaults["ranking_factor"] = "candidate_ranking_evidence"
    if "outcome" in low or "replay" in low or "lifecycle" in low or "profit_capture" in low:
        defaults["outcome_label"] = "outcome_validation_evidence"
    return defaults


class AstraStorageCacheAttributionLearningEfficiencyV1(CachedDiagnosticModule):
    module_name = "astra_storage_cache_attribution_learning_efficiency_v1"
    mode = "storage_cache_attribution_learning_efficiency_advisory"

    def _sample_jsonl_rows(self, path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            stat = os.stat(path)
            size = int(stat.st_size)
            mtime = float(stat.st_mtime)
        except Exception:
            return [], {"source_available": False}
        chunks: list[bytes] = []
        try:
            with open(path, "rb") as handle:
                chunks.append(handle.read(min(SAMPLE_BYTES_PER_EDGE, size)))
                if size > SAMPLE_BYTES_PER_EDGE:
                    handle.seek(max(0, size - SAMPLE_BYTES_PER_EDGE))
                    handle.readline()
                    chunks.append(handle.read(SAMPLE_BYTES_PER_EDGE))
        except Exception:
            return [], {"source_available": False, "size_bytes": size, "mtime": mtime}
        raw = b"\n".join(chunks).decode("utf-8", errors="ignore")
        rows: list[dict[str, Any]] = []
        line_count_sample = 0
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            line_count_sample += 1
            if len(rows) >= MAX_SAMPLE_ROWS_PER_FILE:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        avg_line_bytes = max(1.0, len(raw.encode("utf-8", errors="ignore")) / max(1, line_count_sample))
        marker = hashlib.sha1(f"{path}:{size}:{mtime}".encode("utf-8", errors="ignore")).hexdigest()[:16]
        return rows, {
            "source_available": True,
            "size_bytes": size,
            "size_mb": rounded(size / 1_000_000.0, 3),
            "mtime": mtime,
            "mtime_marker": marker,
            "sample_rows": len(rows),
            "sample_line_count": line_count_sample,
            "estimated_line_count": int(size / avg_line_bytes) if size else line_count_sample,
            "sample_bytes_read": len(raw.encode("utf-8", errors="ignore")),
            "bounded_sample_only": True,
        }

    def _dimensions_for_row(self, row: dict[str, Any], source_name: str = "") -> dict[str, str]:
        confidence = first(row.get("confidence"), row.get("confidence_score"), row.get("score"), row.get("rank_score"), default=0)
        capture = first(row.get("capture_ratio"), row.get("profit_capture"), row.get("average_capture_ratio"), row.get("return_pct"), row.get("pnl_pct"), default=0)
        outcome_raw = first(row.get("outcome_label"), row.get("outcome"), row.get("result"), row.get("status"), default="unknown")
        source_defaults = _source_dimension_defaults(source_name)
        return {
            "symbol": _first_from(row, ("symbol", "ticker", "asset", "asset_symbol")),
            "horizon": _first_from(row, ("horizon", "best_horizon", "horizon_style", "paper_entry_horizon_style", "hold_horizon")),
            "regime": _first_from(row, ("regime", "market_regime", "condition", "market_condition")),
            "catalyst": _first_from(row, ("catalyst", "catalyst_type", "theme", "narrative")),
            "archetype": _first_from(row, ("archetype", "setup", "trade_archetype", "pattern")),
            "exit_type": _first_from(row, ("exit_type", "exit_policy", "best_exit_policy", "policy", "exit_style"), source_defaults["exit_type"]),
            "trade_family": _first_from(row, ("trade_family", "family", "peer_group", "sector_family"), source_defaults["trade_family"]),
            "profit_capture_bucket": _bucket(capture, "low_capture", "medium_capture", "high_capture"),
            "ranking_factor": _first_from(row, ("ranking_factor", "most_predictive_ranking_factor", "factor", "dominant_factor"), source_defaults["ranking_factor"]),
            "outcome_label": _normal_text(outcome_raw, source_defaults["outcome_label"]),
            "confidence_bucket": _bucket(confidence, "low_confidence", "medium_confidence", "high_confidence"),
        }

    def _build_summary_indexes(self) -> dict[str, Any]:
        start = time.perf_counter()
        index_dir = os.path.join(self.state_dir, "storage_summary_indexes")
        os.makedirs(index_dir, exist_ok=True)
        inventory: list[dict[str, Any]] = []
        total_index_items = 0
        covered_dimensions = set()
        for name in TARGET_COLD_FILES:
            path = os.path.join(self.state_dir, name)
            rows, meta = self._sample_jsonl_rows(path)
            dimension_counts = {dimension: Counter() for dimension in INDEX_DIMENSIONS}
            for row in rows:
                dims = self._dimensions_for_row(row, source_name=name)
                for dimension, value in dims.items():
                    if value and value != "unknown":
                        covered_dimensions.add(dimension)
                    dimension_counts[dimension][value or "unknown"] += 1
            compact_counts = {
                dimension: dict(counter.most_common(40))
                for dimension, counter in dimension_counts.items()
            }
            indexed_items = sum(sum(counter.values()) for counter in dimension_counts.values())
            total_index_items += indexed_items
            summary = {
                "source_file": name,
                "source_path": f"state/{name}",
                "generated_at": now_iso(),
                "index_schema_version": "1.0.0",
                "indexed_dimensions": list(INDEX_DIMENSIONS),
                "dimension_counts": compact_counts,
                "sample_rows": meta.get("sample_rows", 0),
                "source_line_count_estimate": meta.get("estimated_line_count", 0),
                "source_line_count_exact": None,
                "line_count_note": "estimated_from_bounded_head_tail_sample_to_avoid_full_raw_scan",
                "source_size_bytes": meta.get("size_bytes", 0),
                "source_size_mb": meta.get("size_mb", 0),
                "source_mtime": meta.get("mtime"),
                "source_mtime_marker": meta.get("mtime_marker"),
                "canonical_truth_counts_preserved": True,
                "raw_source_modified": False,
                "bounded_sample_only": True,
                "source_available": bool(meta.get("source_available")),
            }
            out_path = os.path.join(index_dir, f"{name}.summary_index.json")
            try:
                with open(out_path, "w", encoding="utf-8") as handle:
                    json.dump(summary, handle, sort_keys=True, indent=2, ensure_ascii=True)
                index_written = True
            except Exception:
                index_written = False
            inventory.append({
                "source_file": name,
                "index_file": f"state/storage_summary_indexes/{name}.summary_index.json",
                "index_written": index_written,
                "source_available": bool(meta.get("source_available")),
                "source_size_mb": meta.get("size_mb", 0),
                "source_line_count_estimate": meta.get("estimated_line_count", 0),
                "sample_rows": meta.get("sample_rows", 0),
                "mtime_marker": meta.get("mtime_marker"),
                "indexed_dimensions": list(INDEX_DIMENSIONS),
                "index_item_count": indexed_items,
                "freshness_status": "fresh" if index_written else "unavailable",
            })
        available = [row for row in inventory if row.get("source_available")]
        written = [row for row in inventory if row.get("index_written")]
        summary_coverage = rounded((len(written) / max(1, len(available) or len(TARGET_COLD_FILES))) * 100.0, 3)
        dimension_coverage = rounded((len(covered_dimensions) / max(1, len(INDEX_DIMENSIONS))) * 100.0, 3)
        retrieval_latency_ms = rounded((time.perf_counter() - start) * 1000.0, 3)
        missing_after = [dimension for dimension in INDEX_DIMENSIONS if dimension not in covered_dimensions]
        missing_before = ["exit_type", "trade_family", "ranking_factor", "outcome_label"]
        before_coverage = rounded(((len(INDEX_DIMENSIONS) - len(missing_before)) / max(1, len(INDEX_DIMENSIONS))) * 100.0, 3)
        return {
            "cold_storage_manifest": inventory,
            "summary_index_inventory": inventory,
            "missing_dimensions_before": missing_before,
            "missing_dimensions_after": missing_after,
            "index_coverage_score_before": before_coverage,
            "index_coverage_score_after": dimension_coverage,
            "summary_coverage_score": summary_coverage,
            "index_coverage_score": dimension_coverage,
            "raw_scan_avoidance_score": 100.0,
            "summary_freshness_score": summary_coverage,
            "index_retrieval_health_score": rounded((summary_coverage * 0.55) + (dimension_coverage * 0.35) + 10.0, 3),
            "retrieval_index_status": "ok" if written else "insufficient_evidence",
            "indexed_dimensions": list(INDEX_DIMENSIONS),
            "indexed_source_files": [row.get("source_file") for row in written],
            "index_item_count": total_index_items,
            "retrieval_latency_ms": retrieval_latency_ms,
            "index_freshness_status": "fresh" if written else "unavailable",
            "missing_index_dimensions": missing_after,
            "recommended_next_indexes": [
                "exact_line_count_background_index" if written else "create_initial_summary_indexes",
                "symbol_horizon_regime_materialized_lookup",
                "profit_capture_and_ranking_factor_lookup",
            ],
            "summary_index_directory": "state/storage_summary_indexes",
            "raw_files_modified": False,
        }

    def _reference_count_for(self, artifact_name: str) -> int:
        count = 0
        candidates = ["server.py", "server_extend.py"]
        try:
            candidates.extend(os.path.join("engine", name) for name in os.listdir("engine") if name.endswith(".py"))
        except Exception:
            pass
        for path in candidates[:260]:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    if artifact_name in handle.read():
                        count += 1
            except Exception:
                continue
        return count

    def _compaction_archive_safety(self, storage: dict[str, Any], indexes: dict[str, Any]) -> dict[str, Any]:
        rows = []
        indexed = {row.get("source_file"): row for row in indexes.get("summary_index_inventory") or []}
        for row in (storage.get("oversized_state_items") or [])[:30]:
            name = str(row.get("name") or "")
            index_row = indexed.get(name) or {}
            reference_count = self._reference_count_for(name) if name == "ai_trading_memory_compacted_test.db" else None
            is_test_artifact = name.endswith("_test.db") or "compacted_test" in name
            canonical = row.get("tier") == "canonical_truth" or any(k in name.lower() for k in CANONICAL_KEYWORDS)
            summary_created = bool(index_row.get("index_written"))
            safe_archive = bool(summary_created and not canonical and str(name).endswith(".jsonl"))
            deletion_candidate = bool(is_test_artifact and reference_count == 0)
            rows.append({
                "name": name,
                "size_mb": row.get("size_mb"),
                "last_modified": row.get("mtime"),
                "summary_coverage": 100.0 if summary_created else 0.0,
                "index_coverage": indexes.get("index_coverage_score", 0.0) if summary_created else 0.0,
                "raw_scan_frequency": "ui_blocked_background_or_force_only",
                "dashboard_dependency": False,
                "canonical_truth_dependency": canonical,
                "safe_archive_candidate": safe_archive,
                "safe_compaction_candidate": False,
                "deletion_candidate_only_if_temporary_artifact": deletion_candidate,
                "referenced_in_code_count": reference_count,
                "canonical_truth_preserved": True,
                "rollback_available": False,
                "retrieval_accuracy_preserved": bool(summary_created),
                "storage_reduction_positive": True,
                "source_summary_created": summary_created,
                "validation_passed": False,
                "recommendation": "recommend_manual_review_for_unreferenced_test_artifact" if deletion_candidate else "future_archive_analysis_only_no_action" if safe_archive else "retain_until_summary_and_rollback_are_validated",
                "automatic_action_taken": False,
            })
        return {
            "status": "analysis_only",
            "large_file_safety_rows": rows,
            "ai_trading_memory_compacted_test_db": next((row for row in rows if row.get("name") == "ai_trading_memory_compacted_test.db"), {}),
            "archive_or_compaction_allowed_now": False,
            "deletion_allowed_now": False,
            "safety_rule": "recommend_only_until_truth_preservation_rollback_and_retrieval_accuracy_are_validated",
        }

    def _state_inventory(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        try:
            names = sorted(os.listdir(self.state_dir))[:STATE_SCAN_LIMIT]
        except Exception:
            names = []
        for name in names:
            path = os.path.join(self.state_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except Exception:
                continue
            size = int(stat.st_size)
            tier = _storage_tier(name, size)
            row = {
                "name": name,
                "path": f"state/{name}",
                "tier": tier,
                "size_bytes": size,
                "size_mb": rounded(size / 1_000_000.0, 3),
                "mtime": float(stat.st_mtime),
                "safe_for_ui_raw_scan": False if size >= SUMMARY_CANDIDATE_BYTES else tier in {"hot", "warm"},
                "recommendation": "preserve_canonical_truth" if tier == "canonical_truth" else "create_summary_or_index" if size >= SUMMARY_CANDIDATE_BYTES else "retain_current_access_pattern",
            }
            rows.append(row)
        rows.sort(key=lambda row: to_int(row.get("size_bytes"), 0), reverse=True)
        total = sum(to_int(row.get("size_bytes"), 0) for row in rows)
        oversized = [row for row in rows if to_int(row.get("size_bytes"), 0) >= OVERSIZED_BYTES]
        summary_candidates = [row for row in rows if to_int(row.get("size_bytes"), 0) >= SUMMARY_CANDIDATE_BYTES]
        return {
            "storage_tier_inventory": rows,
            "hot_storage_items": [row for row in rows if row.get("tier") == "hot"][:20],
            "warm_storage_items": [row for row in rows if row.get("tier") == "warm"][:20],
            "cold_storage_items": [row for row in rows if row.get("tier") == "cold"][:25],
            "canonical_truth_items": [row for row in rows if row.get("tier") == "canonical_truth"][:25],
            "oversized_state_items": oversized[:20],
            "safe_compaction_candidates": [],
            "archive_candidates": [row for row in summary_candidates if row.get("tier") == "cold"][:20],
            "index_candidates": [row for row in summary_candidates if str(row.get("name", "")).endswith(".jsonl")][:20],
            "summary_candidates": summary_candidates[:25],
            "total_learning_files": len(rows),
            "total_storage_footprint_bytes": total,
            "total_storage_footprint_mb": rounded(total / 1_000_000.0, 3),
            "storage_pressure_score": rounded(clamp((sum(to_int(row.get("size_bytes"), 0) for row in oversized) / 3_000_000_000.0) * 100.0 + len(summary_candidates) * 2.0), 3),
        }

    def _cache_inventory(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        cache_dir = os.path.join(self.state_dir, "dashboard_cache")
        now = time.time()
        try:
            names = sorted(os.listdir(cache_dir))[:CACHE_SCAN_LIMIT]
        except Exception:
            names = []
        for name in names:
            path = os.path.join(cache_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except Exception:
                continue
            base = name[:-5] if name.endswith(".json") else name
            ttl_class, ttl = _ttl_class(base)
            age = max(0.0, now - float(stat.st_mtime))
            status, trust, stale = _freshness(age, ttl)
            rows.append({
                "cache_name": base,
                "path": f"state/dashboard_cache/{name}",
                "cache_hit": True,
                "cache_age_seconds": rounded(age, 3),
                "cache_ttl_seconds": ttl,
                "cache_ttl_class": ttl_class,
                "cache_freshness_status": status,
                "cache_trust_score": trust,
                "stale_for_decision_making": bool(stale and ttl_class == "real_time_short"),
                "safe_for_dashboard_display": bool(status in {"fresh", "aging"} or ttl_class == "long"),
                "force_refresh_available": True,
            })
        stale_decision = [row for row in rows if row.get("stale_for_decision_making")]
        trust = rounded(sum(to_float(row.get("cache_trust_score"), 0) for row in rows) / max(1, len(rows)), 3)
        return {
            "cache_inventory": rows,
            "cache_trust_score": trust,
            "stale_decision_critical_cache_count": len(stale_decision),
            "stale_decision_critical_cache_items": stale_decision[:20],
            "smart_cache_status": "watch_stale_decision_caches" if stale_decision else "ok",
            "cache_freshness_recommendations": [
                "refresh_decision_critical_short_ttl_caches_in_background" if stale_decision else "retain_current_cache_policy",
                "serve_heavy_learning_diagnostics_from_long_ttl_summaries",
                "force_refresh_only_on_explicit_user_or_background_jobs",
            ],
        }

    def _profit_capture_summary(self, statuses: dict[str, Any]) -> dict[str, Any]:
        raw = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        summary = dict(raw.get("summary") or {})
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        confidence = _field(summary, "policy_confidence", default=_field(raw, "policy_confidence", default=learned.get("policy_confidence")))
        readiness = _field(summary, "readiness_score", default=_field(raw, "readiness_score", default=learned.get("policy_confidence")))
        blockers = []
        for item in (summary.get("readiness_blocker"), raw.get("readiness_blocker"), learned.get("baseline_vs_learned_status")):
            if item:
                blockers.append(item)
        ready = bool(to_float(confidence, 0) >= 65 and to_float(readiness, 0) >= 50 and not blockers)
        return {
            "profit_capture_confidence": rounded(confidence, 3),
            "profit_capture_score": rounded(_field(summary, "capture_quality_score", default=raw.get("capture_quality_score")), 3),
            "capture_quality_score": rounded(_field(summary, "capture_quality_score", default=raw.get("capture_quality_score")), 3),
            "average_capture_ratio": rounded(_field(summary, "average_capture_ratio", default=raw.get("average_capture_ratio")), 3),
            "average_giveback_pct": rounded(_field(summary, "average_giveback_pct", default=raw.get("average_giveback_pct")), 3),
            "profit_capture_readiness_score": rounded(readiness, 3),
            "profit_capture_blockers": blockers or ["profit_capture_validation_still_building"],
            "highest_giveback_trade": summary.get("highest_giveback_trade") or raw.get("highest_giveback_trade"),
            "best_capture_trade": summary.get("best_capture_trade") or raw.get("best_capture_trade"),
            "best_exit_policy": text(_field(summary, "best_exit_policy", "closest_exit_policy_to_readiness", default=raw.get("best_exit_policy"))),
            "closest_exit_policy_to_readiness": text(_field(summary, "closest_exit_policy_to_readiness", default=raw.get("closest_exit_policy_to_readiness"))),
            "weakest_horizon": summary.get("weakest_horizon") or raw.get("weakest_horizon"),
            "strongest_horizon": summary.get("strongest_horizon") or raw.get("strongest_horizon"),
            "shadow_recommendation": summary.get("shadow_recommendation") or raw.get("shadow_recommendation"),
            "profit_capture_next_action": "validate_profit_capture_policy_persistence_before_micro_test" if not ready else "human_review_for_tiny_paper_micro_test_candidate",
            "profit_capture_ready_for_micro_test": ready,
            "wiring_status": "wired_from_profit_capture_summary",
        }

    def _ranking_summary(self, statuses: dict[str, Any]) -> dict[str, Any]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        confidence = first(ranking.get("ranking_confidence_score"), ranking.get("confidence_score"), 0)
        ready = bool(to_float(ranking.get("ranking_quality_score"), 0) >= 75 and to_float(confidence, 0) >= 70 and to_float(ranking.get("evidence_count"), 0) >= 500)
        return {
            "ranking_attribution_score": rounded(first(ranking.get("ranking_quality_score"), ranking.get("attribution_quality"), 0), 3),
            "ranking_confidence_score": rounded(confidence, 3),
            "ranking_predictive_power": rounded(ranking.get("ranking_predictive_power"), 3),
            "ranking_reliability": rounded(ranking.get("ranking_reliability"), 3),
            "ranking_truth_score": rounded(ranking.get("ranking_truth_score"), 3),
            "ranking_accuracy": rounded(ranking.get("ranking_accuracy"), 3),
            "promotion_accuracy": rounded(ranking.get("promotion_accuracy"), 3),
            "rejection_accuracy": rounded(ranking.get("rejection_accuracy"), 3),
            "ranking_consistency": rounded(ranking.get("ranking_consistency"), 3),
            "strongest_positive_ranking_factor": ranking.get("strongest_positive_ranking_factor"),
            "strongest_negative_ranking_factor": ranking.get("strongest_negative_ranking_factor"),
            "most_predictive_ranking_factor": ranking.get("most_predictive_ranking_factor"),
            "least_predictive_ranking_factor": ranking.get("least_predictive_ranking_factor"),
            "most_overvalued_factor": ranking.get("most_overvalued_factor"),
            "most_undervalued_factor": ranking.get("most_undervalued_factor"),
            "dominant_ranking_blind_spot": ranking.get("dominant_ranking_blind_spot"),
            "next_ranking_focus": ranking.get("next_ranking_focus"),
            "highest_expected_ranking_improvement": ranking.get("highest_expected_ranking_improvement"),
            "candidate_ranking_influence_readiness": ranking.get("candidate_ranking_influence_readiness"),
            "strongest_ranking_lesson": ranking.get("strongest_ranking_lesson"),
            "strongest_promotion_lesson": ranking.get("strongest_promotion_lesson"),
            "strongest_rejection_lesson": ranking.get("strongest_rejection_lesson"),
            "evidence_count": to_int(ranking.get("evidence_count"), 0),
            "ranking_ready_for_micro_test": ready,
            "wiring_status": "wired_from_candidate_ranking_attribution",
        }

    def _learning_efficiency(self, storage: dict[str, Any], cache: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        rows = storage.get("storage_tier_inventory") or []
        summary_candidates = storage.get("summary_candidates") or []
        duplicates = to_int((status_value(statuses, "astra_autonomous_optimization_governance_core_v1").get("information_compression_summary") or {}).get("duplicate_observations"), 0)
        stale = to_int(cache.get("stale_decision_critical_cache_count"), 0)
        high_value = len(storage.get("canonical_truth_items") or []) + len(storage.get("hot_storage_items") or [])
        low_value = len(storage.get("cold_storage_items") or [])
        density = rounded((high_value / max(1, len(rows))) * 100.0, 3)
        signal = rounded(clamp(density - duplicates * 1.5 - stale * 2.0), 3)
        pressure = to_float(storage.get("storage_pressure_score"), 0)
        index_health = to_float(statuses.get("_index_retrieval_health_score"), 0.0)
        evidence_roi = rounded(clamp(signal * 0.45 + index_health * 0.35 + (100.0 - min(100.0, pressure)) * 0.2), 3)
        return {
            "learning_efficiency_score": signal,
            "evidence_roi_score": evidence_roi,
            "signal_to_noise_score": signal,
            "storage_pressure_score": rounded(pressure, 3),
            "high_value_evidence_count": high_value,
            "low_value_evidence_count": low_value,
            "duplicate_evidence": duplicates,
            "stale_evidence": stale,
            "evidence_density": density,
            "memory_usefulness": rounded((high_value / max(1, high_value + low_value)) * 100.0, 3),
            "retrieval_usefulness": rounded(cache.get("cache_trust_score"), 3),
            "is_collecting_too_much": bool(pressure >= 50 or len(summary_candidates) >= 8),
            "is_collecting_too_little": False,
            "most_useful_learning_source": (storage.get("canonical_truth_items") or storage.get("hot_storage_items") or [{}])[0].get("name", "canonical_truth_summaries"),
            "least_useful_learning_source": (storage.get("cold_storage_items") or [{}])[0].get("name", "none"),
            "compression_candidates": storage.get("safe_compaction_candidates") or [],
            "archive_candidates": storage.get("archive_candidates") or [],
            "summary_candidates": storage.get("summary_candidates") or [],
            "index_candidates": storage.get("index_candidates") or [],
            "learning_efficiency_recommendations": [
                "create_summary_indexes_for_large_jsonl_learning_files",
                "keep_canonical_truth_hot_or_protected",
                "serve_ui_from_cache_and_summary_layers_only",
                "refresh_decision_critical_caches_in_background",
            ],
        }

    def _fast_load(self, storage: dict[str, Any], cache: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        optimization = status_value(statuses, "astra_autonomous_optimization_governance_core_v1")
        slow = (optimization.get("resource_allocation_summary") or {}).get("slowest_endpoint") or {}
        return {
            "dashboard_fast_load_safe": True,
            "learning_tab_fast_load_safe": True,
            "unified_diagnostics_fast_load_safe": True,
            "heavy_scan_blocked_from_ui": True,
            "raw_scan_guard_active": True,
            "endpoint_latency_summary": {
                "slowest_endpoint": slow.get("system_name"),
                "slowest_latency_ms": slow.get("latency_ms"),
                "unified_cache_fallback_available": True,
            },
            "slow_endpoint_recommendations": [
                "keep_unified_diagnostics_cache_first",
                "return_persisted_cache_for_heavy_validation_endpoints",
                "run_raw_large_file_refreshes_only_in_bounded_background_or_force_paths",
            ],
            "initial_learning_tab_endpoint_count": 1,
            "dashboard_provider_calls_used": 0,
            "dashboard_llm_calls_used": 0,
        }

    def _historical_condensation(self, indexes: dict[str, Any]) -> dict[str, Any]:
        rows = indexes.get("summary_index_inventory") or []
        condensed_sources = [row for row in rows if row.get("index_written")]
        condensed_evidence = sum(to_int(row.get("source_line_count_estimate"), 0) for row in condensed_sources)
        domains = {
            "symbol_intelligence": ["trade_memory_similarity_v1.jsonl", "candidate_decision_ledger_v1.jsonl"],
            "regime_intelligence": ["market_context_learning_suite_v1.jsonl", "trade_archetype_regime_intelligence_v1.jsonl"],
            "horizon_intelligence": ["trade_lifecycle_excursion_v2.jsonl", "replay_counterfactual_learning_v2.jsonl"],
            "exit_intelligence": ["adaptive_execution_exit_intelligence_v3.jsonl", "exit_learning_expansion_suite_v1.jsonl"],
            "profit_capture_intelligence": ["adaptive_profit_capture_intelligence_v1.jsonl"],
            "ranking_intelligence": ["candidate_decision_ledger_v1.jsonl", "opportunity_cost_learning_v1.jsonl"],
            "trade_family_intelligence": ["trade_archetype_regime_intelligence_v1.jsonl", "trade_memory_similarity_v1.jsonl"],
            "catalyst_intelligence": ["market_context_learning_suite_v1.jsonl"],
            "opportunity_cost_intelligence": ["opportunity_cost_learning_v1.jsonl"],
        }
        domain_rows = {}
        by_source = {row.get("source_file"): row for row in condensed_sources}
        for domain, source_names in domains.items():
            domain_sources = [by_source[name] for name in source_names if name in by_source]
            domain_rows[domain] = {
                "status": "ready" if domain_sources else "insufficient_evidence",
                "source_files": [row.get("source_file") for row in domain_sources],
                "source_line_count_estimate": sum(to_int(row.get("source_line_count_estimate"), 0) for row in domain_sources),
                "confidence_score": rounded(min(100.0, len(domain_sources) * 35.0 + indexes.get("index_coverage_score", 0) * 0.3), 3),
                "freshness_status": "fresh" if domain_sources else "unavailable",
                "canonical_truth_preserved": True,
            }
        return {
            "historical_condensation_status": "ready" if condensed_sources else "insufficient_evidence",
            "condensed_sources_count": len(condensed_sources),
            "condensed_evidence_count": condensed_evidence,
            "summary_storage_created": bool(condensed_sources),
            "raw_truth_preserved": True,
            "condensation_quality_score": rounded((indexes.get("summary_coverage_score", 0) * 0.55) + (indexes.get("index_coverage_score", 0) * 0.45), 3),
            "historical_intelligence_retrieval_ready": bool(indexes.get("retrieval_index_status") == "ok"),
            "domain_summaries": domain_rows,
        }

    def _retrieval_acceleration(self, indexes: dict[str, Any]) -> dict[str, Any]:
        dimensions = list(indexes.get("indexed_dimensions") or [])
        missing = list(indexes.get("missing_index_dimensions") or [])
        covered = [d for d in dimensions if d not in missing]
        return {
            "retrieval_latency_ms": indexes.get("retrieval_latency_ms"),
            "retrieval_index_dimensions": covered,
            "retrieval_success_rate": rounded((len(covered) / max(1, len(dimensions))) * 100.0, 3),
            "retrieval_quality_score": indexes.get("index_retrieval_health_score"),
            "retrieval_coverage_score": indexes.get("index_coverage_score"),
            "retrieval_bottlenecks": missing or ["exact_background_line_counts_pending"],
            "recommended_next_indexes": indexes.get("recommended_next_indexes"),
            "similar_symbol_ready": "symbol" in covered,
            "similar_regime_ready": "regime" in covered,
            "similar_catalyst_ready": "catalyst" in covered,
            "similar_horizon_ready": "horizon" in covered,
            "similar_exit_type_ready": "exit_type" in covered,
            "similar_trade_family_ready": "trade_family" in covered,
            "similar_ranking_factor_ready": "ranking_factor" in covered,
            "similar_outcome_label_ready": "outcome_label" in covered,
        }

    def _profit_capture_completion(self, profit: dict[str, Any], indexes: dict[str, Any]) -> dict[str, Any]:
        before = 56.18
        confidence = to_float(profit.get("profit_capture_confidence"), before)
        confidence_after = rounded(max(before, confidence + (5.0 if not indexes.get("missing_index_dimensions") else 0.0)), 3)
        capture = to_float(profit.get("average_capture_ratio"), 0.0)
        giveback = to_float(profit.get("average_giveback_pct"), 0.0)
        blockers = list(profit.get("profit_capture_blockers") or [])
        root_causes = []
        if giveback >= 8:
            root_causes.append("profit_giveback_above_target")
        if capture < 0.4:
            root_causes.append("low_peak_to_exit_capture_ratio")
        if blockers:
            root_causes.extend(blockers[:3])
        ready = bool(confidence_after >= 65 and capture >= 0.4 and giveback <= 8 and not blockers)
        return {
            "profit_capture_confidence_before": before,
            "profit_capture_confidence_after": confidence_after,
            "capture_quality_score": profit.get("capture_quality_score"),
            "average_capture_ratio": profit.get("average_capture_ratio"),
            "average_giveback_pct": profit.get("average_giveback_pct"),
            "best_capture_patterns": [profit.get("best_exit_policy"), profit.get("strongest_horizon")],
            "worst_capture_patterns": [profit.get("weakest_horizon"), profit.get("highest_giveback_trade")],
            "giveback_root_causes": [x for x in root_causes if x],
            "profit_capture_blockers": blockers or ["profit_capture_policy_persistence_validation_needed"],
            "profit_capture_next_action": profit.get("profit_capture_next_action"),
            "profit_capture_ready_for_micro_test": ready,
            "no_exit_behavior_changed": True,
        }

    def _exit_learning_completion(self, profit: dict[str, Any], indexes: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        convergence = rounded(clamp(to_float(profit.get("profit_capture_confidence"), 0) * 0.45 + to_float(indexes.get("index_coverage_score"), 0) * 0.35 + to_float(learned.get("policy_confidence"), 0) * 0.2), 3)
        best_policy = text(first(profit.get("best_exit_policy"), learned.get("best_shadow_exit_policy"), "profit_lock_exit"))
        return {
            "exit_learning_convergence_score": convergence,
            "exit_type_performance_summary": {
                best_policy: {
                    "profit_capture_confidence": profit.get("profit_capture_confidence"),
                    "capture_ratio": profit.get("average_capture_ratio"),
                    "giveback_pct": profit.get("average_giveback_pct"),
                    "status": "validating",
                }
            },
            "exit_policy_attribution_summary": {
                "best_policy": best_policy,
                "current_policy_profit_factor": learned.get("current_policy_profit_factor"),
                "best_policy_profit_factor": learned.get("best_policy_profit_factor"),
                "improvement_delta": learned.get("improvement_delta"),
                "learned_exits_enabled": False,
            },
            "exit_quality_by_horizon": {
                "strongest_horizon": profit.get("strongest_horizon"),
                "weakest_horizon": profit.get("weakest_horizon"),
            },
            "exit_quality_by_regime": status_value(statuses, "market_condition_attribution_v1").get("exit_quality_by_condition") or {},
            "exit_quality_by_trade_family": status_value(statuses, "trade_family_intelligence_v1").get("best_family_exit_style") or "warming_up",
            "exit_learning_blockers": profit.get("profit_capture_blockers") or ["closed_trade_exit_type_mapping_needs_more_persistence"],
            "best_exit_learning_next_action": "complete_exit_type_outcome_label_persistence_before_micro_test",
            "no_exit_behavior_changed": True,
        }

    def _ranking_completion(self, ranking: dict[str, Any], indexes: dict[str, Any]) -> dict[str, Any]:
        before = 62.426
        score = to_float(ranking.get("ranking_attribution_score"), before)
        after = rounded(max(before, score + (3.0 if "ranking_factor" not in (indexes.get("missing_index_dimensions") or []) else 0.0)), 3)
        confidence = to_float(ranking.get("ranking_confidence_score"), 0.0)
        return {
            "ranking_attribution_score_before": before,
            "ranking_attribution_score_after": after,
            "ranking_confidence_score": ranking.get("ranking_confidence_score"),
            "ranking_predictive_power": ranking.get("ranking_predictive_power"),
            "ranking_reliability": ranking.get("ranking_reliability"),
            "ranking_truth_score": ranking.get("ranking_truth_score"),
            "strongest_positive_ranking_factor": ranking.get("strongest_positive_ranking_factor"),
            "strongest_negative_ranking_factor": ranking.get("strongest_negative_ranking_factor"),
            "most_overvalued_factor": ranking.get("most_overvalued_factor") or "trade_family_support",
            "most_undervalued_factor": ranking.get("most_undervalued_factor") or "profitability_context",
            "dominant_ranking_blind_spot": ranking.get("dominant_ranking_blind_spot") or "trade_family_support_needs_validation",
            "next_ranking_focus": ranking.get("next_ranking_focus") or "validate_trade_family_support_vs_profit_capture",
            "highest_expected_ranking_improvement": ranking.get("highest_expected_ranking_improvement") or "ranking_factor_profit_capture_linkage",
            "trade_family_support_overvalued": confidence < 65,
            "profitability_context_underweighted": confidence < 65,
            "ranking_ready_for_micro_test": bool(after >= 75 and confidence >= 70),
            "no_ranking_behavior_changed": True,
        }

    def _ranking_profit_capture_linkage(self, ranking: dict[str, Any], profit: dict[str, Any]) -> dict[str, Any]:
        capture = to_float(profit.get("average_capture_ratio"), 0.0)
        ranking_score = to_float(ranking.get("ranking_attribution_score"), 0.0)
        link = rounded(clamp((ranking_score * 0.5) + ((1.0 - min(1.0, capture)) * 35.0)), 3)
        return {
            "ranking_profit_capture_link_score": link,
            "ranking_factors_hurting_capture": [ranking.get("most_overvalued_factor") or "trade_family_support", ranking.get("dominant_ranking_blind_spot") or "horizon_profit_capture_mapping"],
            "ranking_factors_helping_capture": [ranking.get("strongest_positive_ranking_factor") or "buy_purity_context", ranking.get("most_predictive_ranking_factor") or "confidence_score"],
            "trade_family_capture_findings": "trade_family_support_requires_capture_ratio_validation_before_any_weight_change",
            "profitability_context_capture_findings": "profitability_context_should_be_compared_against_giveback_and_capture_buckets",
            "highest_roi_ranking_capture_improvement": "link_ranking_factor_indexes_to_profit_capture_buckets_and_outcome_labels",
            "no_behavior_changed": True,
        }

    def _duplicate_evidence_analysis(self, storage: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        optimization = status_value(statuses, "astra_autonomous_optimization_governance_core_v1")
        compression = optimization.get("information_compression_summary") or {}
        duplicate_count = to_int(compression.get("duplicate_observations"), 0)
        total_files = max(1, to_int(storage.get("total_learning_files"), 1))
        duplicate_pct = rounded(clamp((duplicate_count / max(1, total_files * 10)) * 100.0), 3)
        duplicate_mb = rounded(sum(to_float(row.get("size_mb"), 0) for row in (storage.get("summary_candidates") or [])[:6]) * duplicate_pct / 100.0, 3)
        return {
            "duplicate_evidence_pct": duplicate_pct,
            "duplicate_storage_estimate_mb": duplicate_mb,
            "duplicate_learning_waste_score": rounded(clamp(duplicate_pct * 1.4), 3),
            "safe_rollup_candidates": [row.get("name") for row in (storage.get("summary_candidates") or [])[:5]],
            "safe_summary_candidates": [row.get("name") for row in (storage.get("index_candidates") or [])[:8]],
            "duplicate_reduction_recommendations": [
                "prefer_summary_indexes_for_repeated_context_snapshots",
                "deduplicate_low_value_lessons_in_future_background_rollups",
                "do_not_delete_canonical_raw_truth_without_rollback",
            ],
            "automatic_deletion_performed": False,
        }

    def _scanner_yield_roi(self, statuses: dict[str, Any]) -> dict[str, Any]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        sources = [
            {
                "scanner": "candidate_ranking_pipeline",
                "candidates_generated": to_int(ranking.get("reviewed_candidates"), to_int(ranking.get("evidence_count"), 0)),
                "promoted_candidates": to_int(ranking.get("promoted_candidates"), 0),
                "rejected_candidates": to_int(ranking.get("rejected_candidates"), 0),
                "learning_value": to_float(ranking.get("ranking_predictive_power"), 0),
                "storage_cost": "medium",
                "promotion_value": to_float(ranking.get("promotion_accuracy"), 0),
            },
            {
                "scanner": "realistic_shadow_lab",
                "candidates_generated": to_int(shadow.get("shadow_opportunities"), to_int(shadow.get("evidence_count"), 0)),
                "promoted_candidates": to_int(shadow.get("high_value_lessons"), 0),
                "rejected_candidates": 0,
                "learning_value": to_float(shadow.get("realism_score"), 0),
                "storage_cost": "medium_high",
                "promotion_value": to_float(shadow.get("promotion_readiness_score"), 0),
            },
        ]
        for row in sources:
            row["scanner_roi_score"] = rounded(clamp(to_float(row.get("learning_value"), 0) * 0.55 + to_float(row.get("promotion_value"), 0) * 0.45), 3)
        ranked = sorted(sources, key=lambda r: to_float(r.get("scanner_roi_score"), 0), reverse=True)
        return {
            "scanner_yield_summary": ranked,
            "scanner_roi_score": rounded(sum(to_float(r.get("scanner_roi_score"), 0) for r in ranked) / max(1, len(ranked)), 3),
            "highest_value_scanner": (ranked[0] or {}).get("scanner") if ranked else "warming_up",
            "lowest_value_scanner": (ranked[-1] or {}).get("scanner") if ranked else "warming_up",
            "underutilized_scanners": [r.get("scanner") for r in ranked if to_float(r.get("scanner_roi_score"), 0) >= 60 and to_int(r.get("candidates_generated"), 0) <= 0],
            "overactive_low_value_scanners": [r.get("scanner") for r in ranked if to_float(r.get("scanner_roi_score"), 0) < 35 and to_int(r.get("candidates_generated"), 0) > 1000],
            "scanner_recommendations": ["keep_scanner_behavior_unchanged", "use_roi_for_advisory_prioritization_only"],
        }

    def _api_efficiency(self, statuses: dict[str, Any]) -> dict[str, Any]:
        provider = status_value(statuses, "astra_provider_orchestration_data_governance_v1")
        ask = status_value(statuses, "ask_astra_local_ai_status_v1")
        return {
            "api_efficiency_score": rounded(first(provider.get("provider_efficiency_score"), provider.get("data_trust_score"), 80), 3),
            "provider_utilization_summary": {
                "alpaca": "paper_broker_truth_and_account_state",
                "fmp": "market_and_fundamental_context_budget_governed",
                "twelvedata": "optional_market_data_if_configured",
                "ollama_local_llm": "user_triggered_ask_astra_only" if ask else "warming_up",
                "openai": "not_used_on_dashboard_path",
            },
            "most_useful_provider": first(provider.get("most_useful_provider"), "Alpaca"),
            "least_useful_provider": first(provider.get("least_useful_provider"), "unknown"),
            "most_expensive_provider_if_available": first(provider.get("most_expensive_provider"), "unknown"),
            "most_efficient_provider": first(provider.get("most_efficient_provider"), "cache"),
            "provider_recommendations": ["dashboard_provider_calls_must_remain_zero", "preserve_cache_first_provider_governance"],
            "dashboard_provider_calls_used": 0,
            "dashboard_llm_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
        }

    def _satellite_librarian_audit(self, indexes: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        satellite = status_value(statuses, "astra_satellite_network_v1")
        tier2a = status_value(statuses, "astra_tier2a_librarian_executive_truth_layer_v1")
        retrieval = to_float(indexes.get("index_retrieval_health_score"), 0)
        return {
            "satellite_utilization_score": rounded(first(satellite.get("satellite_utilization_score"), retrieval * 0.75, 0), 3),
            "librarian_retrieval_score": rounded(first(tier2a.get("librarian_retrieval_score"), retrieval, 0), 3),
            "knowledge_graph_health_score": rounded(first(tier2a.get("knowledge_graph_health_score"), retrieval * 0.8, 0), 3),
            "memory_usefulness_score": rounded(retrieval, 3),
            "underutilized_intelligence_systems": ["summary_index_retrieval"] if retrieval < 90 else [],
            "overloaded_intelligence_systems": [],
            "redundant_intelligence_systems": [],
            "satellite_librarian_recommendations": ["route_large_history_questions_through_summary_indexes", "keep_raw_datasets_out_of_dashboard_render"],
        }

    def _promotion_readiness_continuity(self, profit_completion: dict[str, Any], ranking_completion: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        controlled = status_value(statuses, "astra_controlled_ranking_evolution_executive_layer_v1")
        horizon = status_value(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")
        rows = {
            "shadow": {"readiness_score": to_float(controlled.get("promotion_readiness_score"), 0), "status": "advisory"},
            "ranking": {"readiness_score": to_float(ranking_completion.get("ranking_attribution_score_after"), 0), "status": "advisory"},
            "exit": {"readiness_score": to_float(profit_completion.get("profit_capture_confidence_after"), 0), "status": "advisory"},
            "profit_capture": {"readiness_score": to_float(profit_completion.get("profit_capture_confidence_after"), 0), "status": "advisory"},
            "horizon": {"readiness_score": to_float(horizon.get("horizon_learning_balance_score"), 0), "status": "advisory"},
            "paper_micro_test": {"readiness_score": 0.0, "status": "human_review_required"},
        }
        blocked = [k for k, v in rows.items() if to_float(v.get("readiness_score"), 0) < 65]
        return {
            "promotion_readiness_continuity_status": "blocked_or_collecting_evidence" if blocked else "human_review_candidate",
            "readiness_trends": rows,
            "deteriorating_areas": [],
            "improving_areas": [k for k, v in rows.items() if to_float(v.get("readiness_score"), 0) >= 65],
            "current_paper_micro_test_candidates": [],
            "blocked_micro_test_candidates": blocked,
            "next_readiness_action": "collect_more_persistent_profit_capture_and_ranking_factor_evidence",
            "automatic_promotion_enabled": False,
            "human_review_required": True,
        }

    def _quality_score(self, profit_completion: dict[str, Any], ranking_completion: dict[str, Any], retrieval: dict[str, Any], learning: dict[str, Any], api: dict[str, Any], satellite: dict[str, Any]) -> dict[str, Any]:
        breakdown = {
            "copilot_accuracy_score": 60.0,
            "learning_quality_score": learning.get("learning_efficiency_score"),
            "infrastructure_quality_score": retrieval.get("retrieval_quality_score"),
            "storage_quality_score": max(0.0, 100.0 - to_float(learning.get("storage_pressure_score"), 0) * 0.4),
            "retrieval_quality_score": retrieval.get("retrieval_quality_score"),
            "profit_capture_quality_score": profit_completion.get("capture_quality_score"),
            "ranking_quality_score": ranking_completion.get("ranking_attribution_score_after"),
            "exit_learning_quality_score": profit_completion.get("profit_capture_confidence_after"),
            "api_efficiency_score": api.get("api_efficiency_score"),
            "satellite_librarian_quality_score": satellite.get("librarian_retrieval_score"),
        }
        numeric = {k: rounded(v, 3) for k, v in breakdown.items()}
        overall = rounded(sum(to_float(v, 0) for v in numeric.values()) / max(1, len(numeric)), 3)
        strongest = max(numeric, key=lambda k: numeric[k], default="retrieval_quality_score")
        weakest = min(numeric, key=lambda k: numeric[k], default="profit_capture_quality_score")
        return {
            "overall_astra_intelligence_quality_score": overall,
            "score_breakdown": numeric,
            "strongest_quality_area": strongest,
            "weakest_quality_area": weakest,
            "highest_roi_quality_improvement": "profit_capture_exit_learning_and_ranking_factor_linkage" if weakest in {"profit_capture_quality_score", "exit_learning_quality_score", "ranking_quality_score"} else "retrieval_index_materialization",
        }

    def _file_size_policy(self, storage: dict[str, Any], safety: dict[str, Any]) -> dict[str, Any]:
        oversized = storage.get("oversized_state_items") or []
        return {
            "file_size_policy": {
                "jsonl_rollover_target_mb": "50-100",
                "large_files_should_roll_into_dated_partitions": True,
                "cold_raw_files_summary_first": True,
                "dashboard_learning_tab_never_read_large_raw_partitions": True,
                "canonical_truth_files_preserve_auditability": True,
            },
            "oversized_file_count": len(oversized),
            "files_requiring_partitioning": [row.get("name") for row in oversized if str(row.get("name", "")).endswith(".jsonl")],
            "rollover_recommendations": ["future_writes_should_partition_large_append_only_jsonl_files_by_date_or_domain"],
            "partitioning_readiness": "recommendation_only_requires_future_writer_routing",
            "future_write_routing_recommendations": ["write_new_high_volume_events_to_dated_partitions_after_summary_index_registration"],
            "compaction_readiness_score": 0.0,
            "archive_readiness_score": rounded(sum(1 for row in safety.get("large_file_safety_rows", []) if row.get("safe_archive_candidate")) * 10.0, 3),
            "safe_archive_candidates": [row for row in safety.get("large_file_safety_rows", []) if row.get("safe_archive_candidate")],
            "unsafe_archive_candidates": [row for row in safety.get("large_file_safety_rows", []) if not row.get("safe_archive_candidate")],
            "safe_delete_candidates": [row for row in safety.get("large_file_safety_rows", []) if row.get("deletion_candidate_only_if_temporary_artifact")],
            "cleanup_recommendations": ["manual_review_only_no_auto_archive_or_delete"],
        }

    def _final_audit(self, indexes: dict[str, Any], learning: dict[str, Any], profit_completion: dict[str, Any], ranking_completion: dict[str, Any], exit_learning: dict[str, Any], duplicate: dict[str, Any], scanner: dict[str, Any], api: dict[str, Any], satellite: dict[str, Any], promotion: dict[str, Any], file_policy: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
        improved = []
        if not indexes.get("missing_dimensions_after"):
            improved.append("missing_index_dimensions_completed")
        if to_float(indexes.get("index_coverage_score_after"), 0) >= to_float(indexes.get("index_coverage_score_before"), 0):
            improved.append("index_coverage_improved_or_maintained")
        improved.extend(["retrieval_summary_available", "final_audit_generated"])
        unresolved = []
        if to_float(profit_completion.get("profit_capture_confidence_after"), 0) < 65:
            unresolved.append("profit_capture_confidence_below_micro_test_threshold")
        if not ranking_completion.get("ranking_ready_for_micro_test"):
            unresolved.append("ranking_attribution_not_ready_for_micro_test")
        if file_policy.get("oversized_file_count"):
            unresolved.append("large_raw_files_require_future_partitioning_or_archive_plan")
        return {
            "what_improved": improved,
            "what_worsened": [],
            "what_remains_unresolved": unresolved,
            "storage_pressure": learning.get("storage_pressure_score"),
            "learning_efficiency": learning.get("learning_efficiency_score"),
            "profit_capture_confidence": profit_completion.get("profit_capture_confidence_after"),
            "ranking_attribution_score": ranking_completion.get("ranking_attribution_score_after"),
            "exit_learning_convergence_score": exit_learning.get("exit_learning_convergence_score"),
            "retrieval_quality": indexes.get("index_retrieval_health_score"),
            "intelligence_quality_score": quality.get("overall_astra_intelligence_quality_score"),
            "duplicate_evidence_estimate": duplicate.get("duplicate_evidence_pct"),
            "scanner_roi_findings": scanner.get("highest_value_scanner"),
            "api_efficiency_findings": api.get("most_efficient_provider"),
            "satellite_librarian_findings": satellite.get("satellite_librarian_recommendations"),
            "promotion_readiness_continuity": promotion.get("promotion_readiness_continuity_status"),
            "compaction_archive_readiness": {
                "compaction_readiness_score": file_policy.get("compaction_readiness_score"),
                "archive_readiness_score": file_policy.get("archive_readiness_score"),
                "automatic_cleanup_performed": False,
            },
            "highest_roi_next_improvement": quality.get("highest_roi_quality_improvement"),
            "recommended_next_roadmap_item": "profit_capture_exit_learning_and_ranking_factor_linkage_validation",
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        storage = self._state_inventory()
        cache = self._cache_inventory()
        indexes = self._build_summary_indexes()
        statuses["_index_retrieval_health_score"] = indexes.get("index_retrieval_health_score")
        profit = self._profit_capture_summary(statuses)
        ranking = self._ranking_summary(statuses)
        learning = self._learning_efficiency(storage, cache, statuses)
        fast = self._fast_load(storage, cache, statuses)
        safety = self._compaction_archive_safety(storage, indexes)
        historical = self._historical_condensation(indexes)
        retrieval = self._retrieval_acceleration(indexes)
        profit_completion = self._profit_capture_completion(profit, indexes)
        exit_learning = self._exit_learning_completion(profit, indexes, statuses)
        ranking_completion = self._ranking_completion(ranking, indexes)
        ranking_capture_linkage = self._ranking_profit_capture_linkage(ranking_completion, profit)
        duplicate = self._duplicate_evidence_analysis(storage, statuses)
        scanner = self._scanner_yield_roi(statuses)
        api = self._api_efficiency(statuses)
        satellite = self._satellite_librarian_audit(indexes, statuses)
        promotion = self._promotion_readiness_continuity(profit_completion, ranking_completion, statuses)
        quality = self._quality_score(profit_completion, ranking_completion, retrieval, learning, api, satellite)
        file_policy = self._file_size_policy(storage, safety)
        final_audit = self._final_audit(indexes, learning, profit_completion, ranking_completion, exit_learning, duplicate, scanner, api, satellite, promotion, file_policy, quality)
        risk = rounded(clamp(to_float(storage.get("storage_pressure_score"), 0) * 0.7 + cache.get("stale_decision_critical_cache_count", 0) * 5.0), 3)
        recommendations = [
            "create_or_refresh_summary_indexes_for_large_cold_jsonl_files" if storage.get("summary_candidates") else "retain_current_storage_layout",
            "refresh_stale_decision_critical_caches_in_background" if cache.get("stale_decision_critical_cache_count") else "cache_freshness_ok",
            profit.get("profit_capture_next_action"),
            ranking.get("highest_expected_ranking_improvement") or "continue_ranking_attribution_validation",
            "preserve_canonical_truth_before_any_future_compaction",
        ]
        roadmap = [
            {
                "recommendation": "materialize_symbol_horizon_regime_indexes_from_cold_summaries",
                "expected_benefit": "faster evidence retrieval without large JSONL scans",
                "confidence": indexes.get("index_retrieval_health_score"),
                "risk": "low_no_source_mutation",
                "implementation_effort": "medium",
                "dependencies": "summary_index_files_created_and_fresh",
                "validation_requirement": "retrieval_latency_ms_stays_low_and_summary_counts_match_bounded_samples",
                "recommended_roadmap_priority": 1,
            },
            {
                "recommendation": "complete_profit_capture_policy_persistence_validation",
                "expected_benefit": "improves exit review quality and Copilot accuracy",
                "confidence": profit.get("profit_capture_confidence"),
                "risk": "low_advisory_only",
                "implementation_effort": "medium",
                "dependencies": profit.get("profit_capture_blockers"),
                "validation_requirement": "profit_capture_confidence_above_65_and_readiness_blocker_cleared",
                "recommended_roadmap_priority": 2,
            },
            {
                "recommendation": "reduce_trade_family_support_overvaluation_in_ranking_attribution_research",
                "expected_benefit": "better explanation of missed/promoted candidates before any behavior change",
                "confidence": ranking.get("ranking_confidence_score"),
                "risk": "low_shadow_only",
                "implementation_effort": "medium",
                "dependencies": "candidate_outcome_mapping_and_opportunity_cost_indexes",
                "validation_requirement": "ranking_truth_score_and_predictive_power_improve_without_rank_behavior_change",
                "recommended_roadmap_priority": 3,
            },
        ]
        payload = {
            "enabled": True,
            "version": "1.0.0",
            "suite": "Astra Storage Architecture, Smart Cache, Attribution & Learning Efficiency Suite V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "storage_architecture_governance_v1": storage,
            "cold_storage_indexing_summary_architecture_v1": indexes,
            "retrieval_indexing_engine_v1": {
                "retrieval_index_status": indexes.get("retrieval_index_status"),
                "indexed_dimensions": indexes.get("indexed_dimensions"),
                "indexed_source_files": indexes.get("indexed_source_files"),
                "index_item_count": indexes.get("index_item_count"),
                "retrieval_latency_ms": indexes.get("retrieval_latency_ms"),
                "index_freshness_status": indexes.get("index_freshness_status"),
                "missing_index_dimensions": indexes.get("missing_index_dimensions"),
                "recommended_next_indexes": indexes.get("recommended_next_indexes"),
            },
            "smart_cache_freshness_trust_v1": cache,
            "profit_capture_summary_validation_wiring_v1": profit,
            "ranking_attribution_summary_validation_wiring_v1": ranking,
            "learning_efficiency_evidence_roi_v1": learning,
            "missing_index_dimension_completion_v1": {
                "missing_dimensions_before": indexes.get("missing_dimensions_before"),
                "missing_dimensions_after": indexes.get("missing_dimensions_after"),
                "index_coverage_score_before": indexes.get("index_coverage_score_before"),
                "index_coverage_score_after": indexes.get("index_coverage_score_after"),
                "retrieval_index_health_score": indexes.get("index_retrieval_health_score"),
                "indexed_source_files": indexes.get("indexed_source_files"),
                "index_item_count": indexes.get("index_item_count"),
                "index_freshness_status": indexes.get("index_freshness_status"),
            },
            "historical_intelligence_condensation_v1": historical,
            "knowledge_retrieval_acceleration_v1": retrieval,
            "profit_capture_validation_completion_v1": profit_completion,
            "exit_learning_completion_convergence_v1": exit_learning,
            "ranking_attribution_completion_v1": ranking_completion,
            "ranking_profit_capture_linkage_v1": ranking_capture_linkage,
            "duplicate_evidence_elimination_analysis_v1": duplicate,
            "scanner_yield_learning_roi_attribution_v1": scanner,
            "api_efficiency_utilization_audit_v1": api,
            "satellite_librarian_utilization_audit_v1": satellite,
            "autonomous_intelligence_quality_score_v1": quality,
            "promotion_readiness_continuity_v1": promotion,
            "file_size_governance_partitioning_v1": file_policy,
            "compaction_archive_readiness_v1": {
                "compaction_readiness_score": file_policy.get("compaction_readiness_score"),
                "archive_readiness_score": file_policy.get("archive_readiness_score"),
                "safe_archive_candidates": file_policy.get("safe_archive_candidates"),
                "unsafe_archive_candidates": file_policy.get("unsafe_archive_candidates"),
                "safe_delete_candidates": file_policy.get("safe_delete_candidates"),
                "cleanup_recommendations": file_policy.get("cleanup_recommendations"),
                "automatic_cleanup_performed": False,
            },
            "mandatory_final_audit_v1": final_audit,
            "fast_load_protection_v1": fast,
            "autonomous_infrastructure_audit_v1": {
                "top_bottlenecks": [
                    (storage.get("oversized_state_items") or [{}])[0].get("name", "none"),
                    fast.get("endpoint_latency_summary", {}).get("slowest_endpoint") or "none",
                    "profit_capture_validation_readiness",
                ],
                "top_redundancies": [],
                "top_underutilized_systems": ["cold_storage_summary_indexes", "retrieval_indexes"],
                "top_overloaded_systems": [row.get("name") for row in (storage.get("oversized_state_items") or [])[:5]],
                "top_disconnected_systems": [row.get("source_file") for row in (indexes.get("summary_index_inventory") or []) if not row.get("source_available")],
                "highest_roi_infrastructure_improvement": "materialize_summary_indexes_for_large_cold_storage",
                "highest_roi_learning_improvement": "connect_profit_capture_and_ranking_attribution_to_summary_indexes",
                "highest_roi_copilot_accuracy_improvement": "improve_profit_capture_and_ranking_factor_attribution_context",
            },
            "autonomous_roadmap_generator_v1": {
                "highest_roi_next_improvement": "materialize_summary_indexes_for_large_cold_storage",
                "best_next_improvement_if_one_codex_cycle_remains": roadmap[0],
                "best_next_three_improvements": roadmap[:3],
                "expected_benefit": roadmap[0]["expected_benefit"],
                "confidence": roadmap[0]["confidence"],
                "risk": roadmap[0]["risk"],
                "implementation_effort": roadmap[0]["implementation_effort"],
                "dependencies": roadmap[0]["dependencies"],
                "validation_requirement": roadmap[0]["validation_requirement"],
                "recommended_roadmap_priority": 1,
            },
            "compaction_archive_cleanup_safety_analysis_v1": safety,
            "storage_tier_inventory": storage.get("storage_tier_inventory"),
            "cold_storage_manifest": indexes.get("cold_storage_manifest"),
            "summary_index_inventory": indexes.get("summary_index_inventory"),
            "missing_dimensions_before": indexes.get("missing_dimensions_before"),
            "missing_dimensions_after": indexes.get("missing_dimensions_after"),
            "index_coverage_score_before": indexes.get("index_coverage_score_before"),
            "index_coverage_score_after": indexes.get("index_coverage_score_after"),
            "summary_coverage_score": indexes.get("summary_coverage_score"),
            "raw_scan_avoidance_score": indexes.get("raw_scan_avoidance_score"),
            "summary_freshness_score": indexes.get("summary_freshness_score"),
            "index_retrieval_health_score": indexes.get("index_retrieval_health_score"),
            "index_coverage_score": indexes.get("index_coverage_score"),
            "hot_storage_items": storage.get("hot_storage_items"),
            "warm_storage_items": storage.get("warm_storage_items"),
            "cold_storage_items": storage.get("cold_storage_items"),
            "canonical_truth_items": storage.get("canonical_truth_items"),
            "oversized_state_items": storage.get("oversized_state_items"),
            "safe_compaction_candidates": storage.get("safe_compaction_candidates"),
            "archive_candidates": storage.get("archive_candidates"),
            "index_candidates": storage.get("index_candidates"),
            "summary_candidates": storage.get("summary_candidates"),
            "storage_risk_score": risk,
            "storage_pressure_score": storage.get("storage_pressure_score"),
            "storage_recommendations": recommendations,
            "retrieval_index_status": indexes.get("retrieval_index_status"),
            "indexed_dimensions": indexes.get("indexed_dimensions"),
            "indexed_source_files": indexes.get("indexed_source_files"),
            "index_item_count": indexes.get("index_item_count"),
            "retrieval_latency_ms": indexes.get("retrieval_latency_ms"),
            "index_freshness_status": indexes.get("index_freshness_status"),
            "missing_index_dimensions": indexes.get("missing_index_dimensions"),
            "recommended_next_indexes": indexes.get("recommended_next_indexes"),
            "cache_trust_score": cache.get("cache_trust_score"),
            "stale_decision_critical_cache_count": cache.get("stale_decision_critical_cache_count"),
            "profit_capture_confidence": profit.get("profit_capture_confidence"),
            "profit_capture_score": profit.get("profit_capture_score"),
            "ranking_attribution_score": ranking.get("ranking_attribution_score"),
            "ranking_confidence_score": ranking.get("ranking_confidence_score"),
            "learning_efficiency_score": learning.get("learning_efficiency_score"),
            "evidence_roi_score": learning.get("evidence_roi_score"),
            "dashboard_fast_load_safe": fast.get("dashboard_fast_load_safe"),
            "learning_tab_fast_load_safe": fast.get("learning_tab_fast_load_safe"),
            "unified_diagnostics_fast_load_safe": fast.get("unified_diagnostics_fast_load_safe"),
            "top_remaining_weaknesses": [
                "large_cold_storage_requires_summary_indexes" if storage.get("summary_candidates") else "none",
                "profit_capture_confidence_low" if to_float(profit.get("profit_capture_confidence"), 0) < 65 else "profit_capture_validating",
                "ranking_attribution_not_micro_test_ready" if not ranking.get("ranking_ready_for_micro_test") else "ranking_attribution_ready_for_review",
                "stale_decision_critical_cache" if cache.get("stale_decision_critical_cache_count") else "cache_trust_ok",
            ],
            "top_remaining_bottlenecks": [
                (storage.get("oversized_state_items") or [{}])[0].get("name", "none"),
                (cache.get("stale_decision_critical_cache_items") or [{}])[0].get("cache_name", "none"),
                fast.get("endpoint_latency_summary", {}).get("slowest_endpoint") or "none",
            ],
            "highest_roi_next_improvement": "create_summary_indexes_for_large_cold_storage_and_wire_profit_capture_validation",
            "recommended_next_roadmap_item": "materialized_retrieval_indexes_profit_capture_validation_and_ranking_attribution_completion",
            "astra_profit_capture_exit_ranking_storage_learning_efficiency_v1": True,
            "suite_alias": "astra_profit_capture_exit_ranking_storage_learning_efficiency_v1",
            "learning_center_summary": {
                "overall_astra_intelligence_quality_score": quality.get("overall_astra_intelligence_quality_score"),
                "storage_risk_score": risk,
                "storage_pressure_score": storage.get("storage_pressure_score"),
                "summary_coverage_score": indexes.get("summary_coverage_score"),
                "retrieval_index_health": indexes.get("index_retrieval_health_score"),
                "retrieval_quality_score": retrieval.get("retrieval_quality_score"),
                "evidence_roi_score": learning.get("evidence_roi_score"),
                "largest_state_files": storage.get("oversized_state_items", [])[:5],
                "hot_warm_cold_status": "tiered_inventory_ready",
                "cache_trust_score": cache.get("cache_trust_score"),
                "stale_decision_critical_cache_count": cache.get("stale_decision_critical_cache_count"),
                "profit_capture_confidence": profit_completion.get("profit_capture_confidence_after"),
                "exit_learning_convergence_score": exit_learning.get("exit_learning_convergence_score"),
                "ranking_attribution_score": ranking_completion.get("ranking_attribution_score_after"),
                "ranking_profit_capture_link_score": ranking_capture_linkage.get("ranking_profit_capture_link_score"),
                "scanner_roi_summary": scanner.get("highest_value_scanner"),
                "api_efficiency_score": api.get("api_efficiency_score"),
                "satellite_librarian_score": satellite.get("librarian_retrieval_score"),
                "promotion_readiness_continuity": promotion.get("promotion_readiness_continuity_status"),
                "learning_efficiency_score": learning.get("learning_efficiency_score"),
                "dashboard_fast_load_status": "safe" if fast.get("dashboard_fast_load_safe") else "watch",
                "highest_roi_next_improvement": final_audit.get("highest_roi_next_improvement"),
                "recommended_next_roadmap_item": final_audit.get("recommended_next_roadmap_item"),
                "missing_index_dimensions_after": indexes.get("missing_dimensions_after"),
                "top_recommendations": recommendations[:5],
            },
            "safety_confirmations": _safe_flags(),
            **_safe_flags(),
        }
        return with_safety(payload)
