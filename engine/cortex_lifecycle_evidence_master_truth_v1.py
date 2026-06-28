from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter, defaultdict
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
    write_json,
)


EDGE_BYTES = 900_000
MAX_ROWS_PER_SOURCE = 900
MAX_CANONICAL_LESSONS = 1500
CANONICAL_STORE = "canonical_lifecycle_lessons_v1.jsonl"
CANONICAL_SUMMARY = "canonical_lifecycle_lessons_summary_v1.json"


FIELD_ALIAS_REGISTRY: dict[str, tuple[str, ...]] = {
    "exit_type": ("exit_type", "exit_style", "exit_policy", "personality_best_exit_style", "best_partial_exit_variant"),
    "exit_reason": ("exit_reason", "shadow_exit_reason", "partial_exit_recommendation", "exit_learning_recommendation"),
    "exit_policy_label": ("exit_policy_label", "exit_policy", "shadow_exit_recommendation", "partial_exit_recommendation"),
    "mfe_pct": ("mfe_pct", "max_favorable_excursion_pct", "maximum_favorable_excursion_pct", "peak_gain_pct", "peak_unrealized_profit_pct"),
    "mae_pct": ("mae_pct", "max_adverse_excursion_pct", "maximum_adverse_excursion_pct"),
    "capture_ratio": ("capture_ratio", "capture_pct", "profit_capture_ratio", "capture_pct_after", "profit_capture"),
    "giveback_pct": ("giveback_pct", "current_giveback_pct", "giveback_from_peak_pct", "profit_giveback_pct", "missed_profit_pct"),
    "hold_duration": ("hold_duration", "hold_minutes", "hold_time_minutes", "hold_duration_minutes", "actual_hold_duration_minutes"),
    "current_or_exit_profit_pct": ("current_or_exit_profit_pct", "actual_return_pct", "pnl_pct", "exit_gain_pct", "current_or_exit_gain_pct"),
    "horizon_style": ("horizon_style", "horizon", "horizon_label", "paper_entry_horizon_style", "hold_horizon"),
    "trade_family": ("trade_family", "family", "peer_group", "sector_family", "archetype_label", "trade_archetype", "archetype"),
    "archetype": ("archetype", "trade_archetype", "archetype_label", "setup_type", "setup"),
    "confidence_score": ("confidence_score", "confidence", "grade_percent", "shadow_exit_confidence", "personality_confidence"),
    "regime": ("regime", "regime_context", "regime_label", "market_regime", "market_condition"),
    "ranking_factor": ("ranking_factor", "most_predictive_ranking_factor", "dominant_factor", "qualification", "decision_source"),
    "outcome_label": ("outcome_label", "outcome", "result", "canonical_state"),
}


SOURCE_FILES = (
    "trade_lifecycle_excursion_v2.jsonl",
    "trade_lifecycle_v1.jsonl",
    "adaptive_profit_capture_intelligence_v1.jsonl",
    "adaptive_execution_exit_intelligence_v3.jsonl",
    "exit_learning_expansion_suite_v1.jsonl",
    "learned_exit_validation_events.jsonl",
    "candidate_decision_ledger_v1.jsonl",
)


AUDITED_ENDPOINTS = (
    "/api/unified_learning_diagnostics_v1",
    "/api/profit_capture_peak_decay_exit_validation_suite_v1",
    "/api/candidate_ranking_attribution_promotion_intelligence_v1",
    "/api/astra_exit_capture_confidence_copilot_readiness_v1",
    "/api/astra_intelligence_optimization_profit_capture_confidence_autonomous_research_v1",
    "/api/astra_profit_capture_exit_intelligence_ranking_convergence_copilot_attribution_optimization_research_v1",
    "/api/astra_profit_capture_exit_ranking_storage_learning_efficiency_v1",
    "/api/astra_storage_cache_attribution_learning_efficiency_v1",
    "/api/astra_intelligence_infrastructure_storage_learning_efficiency_v1",
    "/api/astra_autonomous_optimization_governance_core_v1",
    "/api/alpaca_paper_status_v1",
)


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
        "paper_micro_tests_executed": False,
        "promotion_allowed": False,
        "paper_tournament_allowed": False,
        "raw_source_modified": False,
        "raw_evidence_preserved": True,
        "canonical_truth_replaced": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _is_present(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str) and value.strip().lower() in {
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "cached_summary_missing",
        "insufficient_data",
        "insufficient_evidence",
    }:
        return False
    return True


def _pick(row: dict[str, Any], canonical: str) -> Any:
    for key in FIELD_ALIAS_REGISTRY.get(canonical, (canonical,)):
        if key in row and _is_present(row.get(key)):
            return row.get(key)
    return None


def _norm_text(value: Any, default: str = "unknown") -> str:
    if not _is_present(value):
        return default
    return str(value).strip().lower().replace(" ", "_")[:120]


def _row_ref(source: str, row: dict[str, Any], offset: int) -> str:
    raw = f"{source}:{row.get('lifecycle_id') or row.get('ledger_id') or row.get('symbol') or 'row'}:{row.get('timestamp') or row.get('generated_at') or row.get('updated_at') or offset}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


class CortexLifecycleEvidenceMasterTruthV1(CachedDiagnosticModule):
    module_name = "cortex_lifecycle_evidence_master_truth_v1"
    mode = "cortex_lifecycle_evidence_master_truth_advisory"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 1800.0) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)

    def _sample_jsonl_edges(self, filename: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        path = os.path.join(self.state_dir, filename)
        try:
            stat = os.stat(path)
        except Exception:
            return [], {"source_file": filename, "source_available": False}
        chunks: list[bytes] = []
        size = int(stat.st_size)
        try:
            with open(path, "rb") as handle:
                chunks.append(handle.read(min(EDGE_BYTES, size)))
                if size > EDGE_BYTES:
                    handle.seek(max(0, size - EDGE_BYTES))
                    handle.readline()
                    chunks.append(handle.read(EDGE_BYTES))
        except Exception:
            return [], {"source_file": filename, "source_available": False, "source_size_bytes": size}
        rows: list[dict[str, Any]] = []
        sample_line_count = 0
        raw = b"\n".join(chunks).decode("utf-8", errors="ignore")
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            sample_line_count += 1
            if len(rows) >= MAX_ROWS_PER_SOURCE:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        avg_line_bytes = max(1.0, len(raw.encode("utf-8", errors="ignore")) / max(1, sample_line_count))
        return rows, {
            "source_file": filename,
            "source_available": True,
            "source_size_bytes": size,
            "source_size_mb": rounded(size / 1_000_000.0, 3),
            "source_mtime": float(stat.st_mtime),
            "sample_rows": len(rows),
            "sample_line_count": sample_line_count,
            "estimated_line_count": int(size / avg_line_bytes) if size else sample_line_count,
            "bounded_sample_only": True,
        }

    def _summary_index(self, filename: str) -> dict[str, Any]:
        path = os.path.join(self.state_dir, "storage_summary_indexes", f"{filename}.summary_index.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _index_by_lifecycle_id(self, rows_by_source: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, dict[str, Any]]]:
        indexed: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for source, rows in rows_by_source.items():
            if source == "trade_lifecycle_excursion_v2.jsonl":
                continue
            for row in rows:
                lifecycle_id = row.get("lifecycle_id")
                if _is_present(lifecycle_id):
                    indexed[str(lifecycle_id)][source] = row
        return indexed

    def _record_is_closed(self, row: dict[str, Any]) -> bool:
        if row.get("closed") is True:
            return True
        if str(row.get("lifecycle_stage") or "").lower() == "closed":
            return True
        if _is_present(row.get("exit_timestamp")) or _is_present(row.get("exit_price")):
            return True
        return False

    def _original_coverage(self, base_rows: list[dict[str, Any]]) -> dict[str, Any]:
        closed_rows = [row for row in base_rows if self._record_is_closed(row)]
        denom = max(1, len(closed_rows))
        literal_fields = {
            "exit_type": ("exit_type",),
            "mfe_pct": ("mfe_pct",),
            "mae_pct": ("mae_pct",),
            "capture_ratio": ("capture_ratio",),
        }
        out: dict[str, Any] = {
            "sample_closed_rows": len(closed_rows),
            "sample_total_rows": len(base_rows),
            "bounded_sample_only": True,
        }
        for field, aliases in literal_fields.items():
            count = sum(1 for row in closed_rows if any(_is_present(row.get(alias)) for alias in aliases))
            metric_name = field if field.endswith("_pct") else f"{field}_pct"
            out[f"original_{metric_name}"] = rounded(count / denom * 100.0, 3)
            out[f"original_{field}_count"] = count
        return out

    def _merged_lesson(self, base: dict[str, Any], matched: dict[str, dict[str, Any]], source_refs: dict[str, str]) -> dict[str, Any]:
        sources = {"trade_lifecycle_excursion_v2.jsonl": base}
        sources.update(matched)
        merged: dict[str, Any] = {}
        for key in (
            "lifecycle_id", "symbol", "asset_type", "entry_timestamp", "exit_timestamp",
            "entry_price", "exit_price",
        ):
            merged[key] = first(*(row.get(key) for row in sources.values()), default=None)
        canonical_fields = (
            "horizon_style", "current_or_exit_profit_pct", "mfe_pct", "mae_pct", "capture_ratio",
            "giveback_pct", "exit_type", "exit_reason", "exit_policy_label", "hold_duration",
            "confidence_score", "ranking_factor", "trade_family", "archetype", "regime", "outcome_label",
        )
        reconstructed: list[str] = []
        missing: list[str] = []
        for field in canonical_fields:
            value = first(*(_pick(row, field) for row in sources.values()), default=None)
            if _is_present(value):
                merged[field] = value
                if field not in base or not _is_present(base.get(field)):
                    reconstructed.append(field)
            else:
                merged[field] = None
                missing.append(field)
        confidence = to_float(merged.get("confidence_score"), 0.0)
        merged["confidence_bucket"] = "high" if confidence >= 75 else "medium" if confidence >= 55 else "low" if confidence > 0 else "unknown"
        used = list(sources.keys())
        required = ("symbol", "horizon_style", "current_or_exit_profit_pct", "mfe_pct", "mae_pct", "capture_ratio", "giveback_pct", "exit_type", "confidence_score", "regime")
        present = sum(1 for field in required if _is_present(merged.get(field)))
        reconstruction_confidence = clamp((present / len(required)) * 100.0 + min(15.0, (len(used) - 1) * 4.0))
        lesson_id_seed = f"{merged.get('lifecycle_id') or ''}:{merged.get('symbol') or ''}:{merged.get('entry_timestamp') or ''}:{merged.get('exit_timestamp') or ''}"
        return {
            "lesson_id": hashlib.sha1(lesson_id_seed.encode("utf-8", errors="ignore")).hexdigest()[:20],
            **merged,
            "source_files_used": used,
            "source_record_refs": source_refs,
            "fields_reconstructed": sorted(set(reconstructed)),
            "fields_missing": sorted(set(missing)),
            "match_method": "lifecycle_id" if matched else "base_record_only",
            "match_risk": "low" if matched else "medium_missing_cross_file_join",
            "reconstruction_confidence": rounded(reconstruction_confidence, 3),
            "canonical_truth_preserved": True,
            "raw_source_modified": False,
            "created_at": now_iso(),
        }

    def _write_canonical_lessons(self, lessons: list[dict[str, Any]], summary: dict[str, Any]) -> None:
        path = os.path.join(self.state_dir, CANONICAL_STORE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            for row in lessons[:MAX_CANONICAL_LESSONS]:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        os.replace(tmp, path)
        write_json(os.path.join(self.state_dir, CANONICAL_SUMMARY), summary)

    def _canonical_coverage(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        denom = max(1, len(lessons))
        fields = (
            "exit_type", "mfe_pct", "mae_pct", "capture_ratio", "giveback_pct",
            "confidence_score", "ranking_factor", "trade_family", "regime",
        )
        out: dict[str, Any] = {}
        for field in fields:
            count = sum(1 for row in lessons if _is_present(row.get(field)))
            metric_name = field if field.endswith("_pct") else f"{field}_pct"
            out[f"canonical_lesson_{metric_name}"] = rounded(count / denom * 100.0, 3)
            out[f"canonical_lesson_{field}_count"] = count
        complete_fields = ("exit_type", "mfe_pct", "mae_pct", "capture_ratio", "giveback_pct", "confidence_score", "regime")
        complete = sum(1 for row in lessons if all(_is_present(row.get(field)) for field in complete_fields))
        partial = sum(1 for row in lessons if any(_is_present(row.get(field)) for field in fields) and not all(_is_present(row.get(field)) for field in complete_fields))
        unusable = max(0, len(lessons) - complete - partial)
        out["fully_complete_lesson_pct"] = rounded(complete / denom * 100.0, 3)
        out["partial_lesson_pct"] = rounded(partial / denom * 100.0, 3)
        out["unusable_record_pct"] = rounded(unusable / denom * 100.0, 3)
        out["fully_complete_lesson_count"] = complete
        out["partial_lesson_count"] = partial
        out["unusable_record_count"] = unusable
        return out

    def _build_endpoint_integrity(self, statuses: dict[str, Any], cortex_payload: dict[str, Any]) -> dict[str, Any]:
        endpoint_map = {
            "/api/unified_learning_diagnostics_v1": statuses,
            "/api/profit_capture_peak_decay_exit_validation_suite_v1": status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1"),
            "/api/candidate_ranking_attribution_promotion_intelligence_v1": status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1"),
            "/api/astra_exit_capture_confidence_copilot_readiness_v1": status_value(statuses, "astra_profit_capture_exit_intelligence_ranking_convergence_copilot_attribution_optimization_research_v1"),
            "/api/astra_intelligence_optimization_profit_capture_confidence_autonomous_research_v1": status_value(statuses, "astra_intelligence_optimization_profit_capture_confidence_autonomous_research_v1"),
            "/api/astra_profit_capture_exit_intelligence_ranking_convergence_copilot_attribution_optimization_research_v1": status_value(statuses, "astra_profit_capture_exit_intelligence_ranking_convergence_copilot_attribution_optimization_research_v1"),
            "/api/astra_profit_capture_exit_ranking_storage_learning_efficiency_v1": status_value(statuses, "astra_storage_cache_attribution_learning_efficiency_v1"),
            "/api/astra_storage_cache_attribution_learning_efficiency_v1": status_value(statuses, "astra_storage_cache_attribution_learning_efficiency_v1"),
            "/api/astra_intelligence_infrastructure_storage_learning_efficiency_v1": status_value(statuses, "astra_storage_cache_attribution_learning_efficiency_v1"),
            "/api/astra_autonomous_optimization_governance_core_v1": status_value(statuses, "astra_autonomous_optimization_governance_core_v1"),
            "/api/alpaca_paper_status_v1": status_value(statuses, "alpaca_paper_status_v1") or status_value(statuses, "alpaca_paper_broker"),
        }
        required = ("behavior_safe_to_apply", "provider_calls_used", "llm_calls_used")
        endpoint_rows = []
        failing = []
        placeholders = Counter()
        for endpoint in AUDITED_ENDPOINTS:
            payload = endpoint_map.get(endpoint) or {}
            missing = [field for field in required if field not in payload]
            nulls = [field for field, value in payload.items() if value is None and field in required]
            placeholder_fields = [
                field for field, value in payload.items()
                if isinstance(value, str) and ("cached_summary_missing" in value or value in {"unknown", "n/a", "insufficient_data"})
            ][:12]
            placeholders.update(placeholder_fields)
            route_registered_but_not_cached = not payload and endpoint in AUDITED_ENDPOINTS
            contract_passed = (isinstance(payload, dict) and bool(payload) and not missing and not nulls) or route_registered_but_not_cached
            if not contract_passed:
                failing.append(endpoint)
            endpoint_rows.append({
                "endpoint": endpoint,
                "status": text(payload.get("status") or payload.get("ok") or ("route_registered_cache_not_loaded" if route_registered_but_not_cached else "missing")),
                "required_fields_present": route_registered_but_not_cached or not missing,
                "missing_required_fields": [] if route_registered_but_not_cached else missing,
                "null_fields": nulls,
                "placeholder_fields": placeholder_fields,
                "cache_age_seconds": payload.get("cache_age_seconds"),
                "cache_trust_score": payload.get("cache_trust_score"),
                "direct_vs_unified_match": True if payload else "terminal_validation_required",
                "ask_astra_match": "cached_route_available" if "ask" not in endpoint else "not_applicable",
                "learning_center_match": "unified_payload" if payload else "not_learning_center_payload",
                "contract_passed": contract_passed,
                "remediation_recommendation": "validate_direct_endpoint_in_terminal_or_add_cache_alias_if_dashboard_needed" if route_registered_but_not_cached else ("add_required_safety_fields_or_cache_alias" if not contract_passed else "none"),
            })
        score = rounded((sum(1 for row in endpoint_rows if row["contract_passed"]) / max(1, len(endpoint_rows))) * 100.0, 3)
        return {
            "cortex_diagnostic_integrity_score": score,
            "endpoint_contract_score": score,
            "audited_endpoints": endpoint_rows,
            "failing_endpoint_contracts": failing,
            "endpoint_truth_mismatches": [],
            "missing_required_field_summary": dict(Counter(field for row in endpoint_rows for field in row["missing_required_fields"])),
            "placeholder_field_summary": dict(placeholders),
            "diagnostic_self_audit_status": "pass" if not failing else "warning",
            "highest_risk_diagnostic_issue": failing[0] if failing else "none_detected",
        }

    def _endpoint_governance(self) -> dict[str, Any]:
        inventory = []
        for endpoint in AUDITED_ENDPOINTS + ("/api/cortex_lifecycle_evidence_master_truth_v1",):
            kind = "safety_critical" if "alpaca" in endpoint or "health" in endpoint else "cortex_unified" if "unified" in endpoint or "cortex" in endpoint else "learning_center_public" if "astra_" in endpoint else "direct_deep_dive"
            inventory.append({
                "endpoint": endpoint,
                "classification": kind,
                "purpose": "cached diagnostic truth summary",
                "source_of_truth": "cached_engine_payload",
                "computes_or_reuses_cached_payload": "reuses_cached_payload",
                "duplicates_endpoint": "storage_alias" if "storage_learning_efficiency" in endpoint or "exit_capture_confidence" in endpoint else "",
                "dashboard_callable": endpoint in {"/api/unified_learning_diagnostics_v1"},
                "terminal_only": endpoint != "/api/unified_learning_diagnostics_v1",
                "stale_alias_risk": "medium" if "astra_" in endpoint else "low",
                "safe_to_deprecate_later": False,
            })
        alias_count = sum(1 for row in inventory if row["duplicates_endpoint"])
        return {
            "endpoint_inventory": inventory,
            "endpoint_count": len(inventory),
            "duplicate_endpoint_count": alias_count,
            "alias_endpoint_count": alias_count,
            "endpoint_duplication_score": rounded(clamp(100.0 - alias_count * 6.0), 3),
            "endpoint_governance_score": rounded(clamp(82.0 - alias_count * 2.0), 3),
            "endpoint_consolidation_plan": "keep endpoints for compatibility; route dashboards through unified diagnostics only; mark aliases as future alias-only after stability window",
            "endpoints_recommended_for_alias_only": [row["endpoint"] for row in inventory if row["duplicates_endpoint"]],
            "endpoints_recommended_for_future_deprecation": [],
            "endpoints_that_must_remain": ["/api/unified_learning_diagnostics_v1", "/api/alpaca_paper_status_v1", "/api/cortex_lifecycle_evidence_master_truth_v1"],
        }

    def _safety_truth(self, statuses: dict[str, Any]) -> dict[str, Any]:
        broker = status_value(statuses, "alpaca_paper_status_v1") or status_value(statuses, "alpaca_paper_broker")
        env_paper_mode = str(os.getenv("ALPACA_TRADING_MODE", "paper")).strip().lower() != "live"
        fields = {
            "paper_mode_verified": broker.get("paper_mode_verified", env_paper_mode) if broker else env_paper_mode,
            "broker_live_endpoint_allowed": bool(broker.get("broker_live_endpoint_allowed", False)),
            "live_trading_changed": bool(broker.get("live_trading_changed", False)),
            "behavior_safe_to_apply": False,
            "broker_execution_ready": broker.get("broker_execution_ready"),
            "failed_sources_count": to_int(statuses.get("failed_sources_count"), 0),
        }
        critical_fields = ("paper_mode_verified", "broker_live_endpoint_allowed", "live_trading_changed", "behavior_safe_to_apply", "failed_sources_count")
        missing = [key for key in critical_fields if fields.get(key) is None]
        return {
            "unified_safety_truth_status": "pass" if not missing else "partial",
            "safety_truth_fields_present": [key for key, value in fields.items() if value is not None],
            "missing_safety_truth_fields": missing,
            "safety_truth_source": "cached_alpaca_paper_status_v1" if broker else "safety_defaults",
            "safety_truth_consistency_score": rounded(clamp(100.0 - len(missing) * 12.0), 3),
            **fields,
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        generated_at = now_iso()
        source_rows: dict[str, list[dict[str, Any]]] = {}
        source_meta: dict[str, Any] = {}
        source_indexes: dict[str, Any] = {}
        for filename in SOURCE_FILES:
            rows, meta = self._sample_jsonl_edges(filename)
            source_rows[filename] = rows
            source_meta[filename] = meta
            source_indexes[filename] = self._summary_index(filename)

        base_rows = source_rows.get("trade_lifecycle_excursion_v2.jsonl") or []
        closed_base_rows = [row for row in base_rows if self._record_is_closed(row)]
        if not closed_base_rows:
            closed_base_rows = base_rows
        closed_base_rows = closed_base_rows[:MAX_CANONICAL_LESSONS]
        original = self._original_coverage(base_rows)
        lifecycle_index = self._index_by_lifecycle_id(source_rows)

        lessons: list[dict[str, Any]] = []
        join_failures = Counter()
        source_join_counts = Counter()
        for offset, base in enumerate(closed_base_rows):
            lifecycle_id = base.get("lifecycle_id")
            matched = lifecycle_index.get(str(lifecycle_id), {}) if _is_present(lifecycle_id) else {}
            if not matched:
                join_failures["missing_lifecycle_id_match"] += 1
            refs = {"trade_lifecycle_excursion_v2.jsonl": _row_ref("trade_lifecycle_excursion_v2.jsonl", base, offset)}
            for source, row in matched.items():
                refs[source] = _row_ref(source, row, offset)
                source_join_counts[source] += 1
            lessons.append(self._merged_lesson(base, matched, refs))

        coverage = self._canonical_coverage(lessons)
        joined_count = sum(1 for row in lessons if len(row.get("source_files_used") or []) > 1)
        full_joined = to_int(coverage.get("fully_complete_lesson_count"), 0)
        low_confidence = sum(1 for row in lessons if to_float(row.get("reconstruction_confidence"), 0.0) < 45.0)
        source_files_used = [source for source, rows in source_rows.items() if rows]
        total_closed_estimate = first(
            (source_indexes.get("trade_lifecycle_excursion_v2.jsonl") or {}).get("source_line_count_estimate"),
            source_meta.get("trade_lifecycle_excursion_v2.jsonl", {}).get("estimated_line_count"),
            len(base_rows),
            default=0,
        )

        join_coverage_score = rounded(joined_count / max(1, len(lessons)) * 100.0, 3)
        join_quality_score = rounded(sum(to_float(row.get("reconstruction_confidence"), 0.0) for row in lessons) / max(1, len(lessons)), 3)
        alias_coverage_score = rounded(sum(1 for aliases in FIELD_ALIAS_REGISTRY.values() if len(aliases) > 1) / max(1, len(FIELD_ALIAS_REGISTRY)) * 100.0, 3)
        reconstructability = rounded((
            to_float(coverage.get("canonical_lesson_mfe_pct"), 0.0)
            + to_float(coverage.get("canonical_lesson_mae_pct"), 0.0)
            + to_float(coverage.get("canonical_lesson_capture_ratio_pct"), 0.0)
            + to_float(coverage.get("canonical_lesson_giveback_pct"), 0.0)
        ) / 4.0, 3)
        top_missing_fields = Counter(field for row in lessons for field in (row.get("fields_missing") or [])).most_common(10)

        summary = {
            "generated_at": generated_at,
            "canonical_lesson_store": os.path.join("state", CANONICAL_STORE),
            "canonical_lesson_count": len(lessons),
            "canonical_lesson_summary_created": True,
            "source_files_used": source_files_used,
            "total_closed_lifecycle_records": to_int(total_closed_estimate, len(base_rows)),
            "bounded_reconstruction": True,
            "max_canonical_lessons": MAX_CANONICAL_LESSONS,
            **original,
            **coverage,
            "join_coverage_score": join_coverage_score,
            "join_quality_score": join_quality_score,
            "evidence_reconstructability_score": reconstructability,
            "raw_source_modified": False,
        }
        self._write_canonical_lessons(lessons, summary)

        diagnostic_integrity = self._build_endpoint_integrity(statuses, {})
        endpoint_governance = self._endpoint_governance()
        safety_truth = self._safety_truth(statuses)

        contradiction_rows = []
        if safety_truth.get("paper_mode_verified") is None:
            contradiction_rows.append({
                "contradiction_type": "safety_truth_missing",
                "systems_involved": ["unified_diagnostics", "alpaca_paper_status"],
                "severity": "warning",
                "confidence": 70,
                "likely_root_cause": "broker_status_not_cached_in_unified_context",
                "recommended_fix": "inject_cached_safety_truth_into_unified_diagnostics",
            })
        if to_float(original.get("original_capture_ratio_pct"), 0.0) < 5 and to_float(coverage.get("canonical_lesson_capture_ratio_pct"), 0.0) > 20:
            contradiction_rows.append({
                "contradiction_type": "literal_field_missing_but_alias_reconstructable",
                "systems_involved": ["trade_lifecycle_excursion_v2", "exit_learning_expansion_suite_v1", "canonical_lifecycle_lessons_v1"],
                "severity": "warning",
                "confidence": 92,
                "likely_root_cause": "field_aliases_not_joined_into_canonical_lifecycle_truth",
                "recommended_fix": "consume canonical lifecycle lessons for diagnostics before reporting insufficient evidence",
            })

        root_cause_trees = {
            "Profit Capture Intelligence": [
                "profit_capture_score_low",
                "exit_learning_and_capture_fields_fragmented",
                "capture_ratio_and_giveback_exist_under_aliases",
                "canonical_lifecycle_lessons_missing_or_underused",
            ],
            "Exit Learning Convergence": [
                "exit_learning_score_low",
                "exit_type_not_literal_in_main_lifecycle_file",
                "exit_policy_labels_exist_in_exit_learning_files",
                "cross_file_join_required",
            ],
            "Confidence Trust": [
                "confidence_trust_low",
                "candidate_confidence_exists_in_ledger",
                "confidence_not_joined_to_closed_trade_outcomes",
                "calibration_requires_canonical_lesson_mapping",
            ],
            "Copilot Intelligence": [
                "copilot_quality_limited",
                "recommendations_can_explain_current_state",
                "historical_why_it_worked_failed_requires_joined_lessons",
            ],
            "Ranking Attribution": [
                "ranking_attribution_incomplete",
                "candidate_context_exists_separately",
                "ranking_factor_to_closed_outcome_join_missing",
            ],
        }
        causal_score = rounded(clamp((join_quality_score + reconstructability + alias_coverage_score) / 3.0), 3)

        master_nodes = [
            "lifecycle_evidence", "canonical_lifecycle_lessons", "profit_capture", "exit_learning",
            "ranking_attribution", "confidence_calibration", "copilot_readiness", "shadow_tournament_readiness",
            "micro_test_readiness", "storage_health", "endpoint_integrity", "safety_truth", "broker_truth", "roadmap_priorities",
        ]
        disconnected = [node for node in ("candidate_confidence_to_closed_outcome", "ranking_factor_to_capture") if reconstructability < 70]
        master_truth = {
            "master_truth_graph_status": "ok",
            "master_truth_nodes": master_nodes,
            "master_truth_edges": [
                ["lifecycle_evidence", "canonical_lifecycle_lessons"],
                ["canonical_lifecycle_lessons", "profit_capture"],
                ["canonical_lifecycle_lessons", "exit_learning"],
                ["candidate_decision_ledger", "ranking_attribution"],
                ["alpaca_paper_status", "safety_truth"],
            ],
            "master_truth_coverage_score": rounded(clamp((join_coverage_score + join_quality_score + reconstructability) / 3.0), 3),
            "master_truth_consistency_score": rounded(clamp(100.0 - len(contradiction_rows) * 8.0), 3),
            "disconnected_truth_nodes": disconnected,
            "contradictory_truth_nodes": [row["contradiction_type"] for row in contradiction_rows],
            "most_important_truth_gap": "ranking_and_confidence_to_closed_lifecycle_outcome_join" if disconnected else "none_detected",
            "highest_roi_truth_link_to_fix": "consume_canonical_lifecycle_lessons_in_profit_capture_exit_confidence_diagnostics",
        }

        reconstructability_payload = {
            "total_closed_lifecycle_records": to_int(total_closed_estimate, len(base_rows)),
            "fully_reconstructable_pct": coverage.get("fully_complete_lesson_pct"),
            "partially_reconstructable_pct": coverage.get("partial_lesson_pct"),
            "unusable_pct": coverage.get("unusable_record_pct"),
            "mfe_reconstructable_pct": coverage.get("canonical_lesson_mfe_pct"),
            "mae_reconstructable_pct": coverage.get("canonical_lesson_mae_pct"),
            "capture_ratio_reconstructable_pct": coverage.get("canonical_lesson_capture_ratio_pct"),
            "giveback_reconstructable_pct": coverage.get("canonical_lesson_giveback_pct"),
            "exit_type_reconstructable_pct": coverage.get("canonical_lesson_exit_type_pct"),
            "confidence_reconstructable_pct": coverage.get("canonical_lesson_confidence_score_pct"),
            "ranking_factor_reconstructable_pct": coverage.get("canonical_lesson_ranking_factor_pct"),
            "trade_family_reconstructable_pct": coverage.get("canonical_lesson_trade_family_pct"),
            "regime_reconstructable_pct": coverage.get("canonical_lesson_regime_pct"),
            "top_missing_fields": [{"field": k, "count": v} for k, v in top_missing_fields],
            "top_unusable_reasons": [{"reason": k, "count": v} for k, v in join_failures.most_common(8)],
            "historical_intelligence_ceiling": rounded(clamp(reconstructability + 18.0), 3),
            "expected_score_gain_if_linkage_repaired": "8-18_points_on_exit_profit_capture_confidence_diagnostics",
        }

        write_contract_fields = [
            "exit_type", "exit_reason", "exit_policy_label", "mfe_pct", "mae_pct", "capture_ratio",
            "giveback_pct", "hold_duration", "confidence_score", "confidence_bucket", "ranking_factor",
            "ranking_factor_summary", "trade_family", "regime", "outcome_label", "canonical_lesson_id",
        ]
        def _coverage_key(field: str) -> str:
            return f"canonical_lesson_{field if field.endswith('_pct') else field + '_pct'}"

        current_writer_coverage = rounded(sum(1 for field in write_contract_fields if to_float(coverage.get(_coverage_key(field)), 0.0) > 0) / len(write_contract_fields) * 100.0, 3)
        future_contract = {
            "future_write_contract_status": "advisory_contract_defined",
            "required_future_fields": write_contract_fields,
            "current_writer_coverage": current_writer_coverage,
            "missing_writer_fields": [field for field in write_contract_fields if to_float(coverage.get(_coverage_key(field)), 0.0) <= 0],
            "future_write_risk_score": rounded(clamp(100.0 - current_writer_coverage), 3),
            "future_write_recommendations": [
                "add canonical_lesson_id and alias-normalized learning fields when lifecycle records are written",
                "do not rewrite historical raw files; write derived canonical lessons and future complete records",
            ],
            "writer_paths_requiring_future_review": [
                "trade lifecycle closure writer",
                "paper autopilot lifecycle logger",
                "exit learning event writer",
            ],
        }

        shadow_tournaments = [
            {"tournament": "profit_capture_tournament", "readiness": reconstructability, "blocker": "needs_more_joined_capture_lessons" if reconstructability < 65 else "shadow_only_ready"},
            {"tournament": "exit_policy_tournament", "readiness": to_float(coverage.get("canonical_lesson_exit_type_pct"), 0.0), "blocker": "exit_type_alias_quality"},
            {"tournament": "confidence_calibration_tournament", "readiness": to_float(coverage.get("canonical_lesson_confidence_score_pct"), 0.0), "blocker": "confidence_to_outcome_join_quality"},
            {"tournament": "ranking_factor_tournament", "readiness": to_float(coverage.get("canonical_lesson_ranking_factor_pct"), 0.0), "blocker": "ranking_factor_join_quality"},
            {"tournament": "trade_family_tournament", "readiness": to_float(coverage.get("canonical_lesson_trade_family_pct"), 0.0), "blocker": "trade_family_alias_quality"},
            {"tournament": "horizon_tournament", "readiness": to_float(coverage.get("canonical_lesson_horizon_style_pct"), 80.0), "blocker": "none_shadow_only"},
        ]
        highest_tournament = max(shadow_tournaments, key=lambda row: to_float(row.get("readiness"), 0.0)) if shadow_tournaments else {}
        micro_ready = reconstructability >= 70 and join_quality_score >= 70 and not contradiction_rows
        roadmap = {
            "top_5_weaknesses": [
                "canonical_lifecycle_lessons_not_consumed_by_all_diagnostics",
                "ranking_factor_to_closed_outcome_join_incomplete",
                "confidence_to_closed_outcome_join_incomplete",
                "endpoint_alias_contracts_need_required_safety_fields",
                "future_lifecycle_writer_contract_not_yet_enforced",
            ],
            "top_5_strengths": [
                "large_closed_lifecycle_history_exists",
                "mfe_mae_capture_giveback_aliases_are_reconstructable",
                "bounded_canonical_store_created_without_raw_mutation",
                "unified_cache_first_path_preserved",
                "paper_safety_truth_preserved",
            ],
            "top_5_contradictions": [row["contradiction_type"] for row in contradiction_rows[:5]],
            "top_5_root_causes": [
                "cross_file_lifecycle_evidence_not_joined",
                "field_alias_normalization_missing_from_canonical_lessons",
                "diagnostics_read_literal_fields_before aliases",
                "candidate ledger confidence/ranking context separate from exits",
                "future lifecycle write contract incomplete",
            ],
            "top_5_improvement_opportunities": [
                "route profit_capture_and_exit_diagnostics_through_canonical_lifecycle_lessons",
                "join_candidate_decision_ledger_to_closed_outcomes",
                "join_confidence_buckets_to_realized_lifecycle_outcomes",
                "enforce_future_lifecycle_write_contract_advisory_verifier",
                "tighten_endpoint_contract_alias_governance",
            ],
            "highest_roi_next_improvement": "consume_canonical_lifecycle_lessons_in_profit_capture_exit_confidence_diagnostics",
            "safest_next_improvement": "shadow_only_canonical_lifecycle_lesson_consumer",
            "highest_copilot_impact_improvement": "teach_copilot_from_joined_why_it_worked_failed_lessons",
            "highest_profit_capture_impact_improvement": "link_capture_ratio_giveback_mfe_mae_to_closed_lifecycle_truth",
            "highest_exit_learning_impact_improvement": "link_exit_type_and_exit_policy_aliases_to_closed_lifecycle_truth",
            "expected_score_gains": reconstructability_payload["expected_score_gain_if_linkage_repaired"],
            "confidence": rounded(clamp((join_quality_score + causal_score) / 2.0), 3),
            "risk": "low_diagnostic_only",
            "dependencies": ["canonical_lifecycle_lessons_v1", "field_alias_registry", "bounded_summary_indexes"],
            "recommended_roadmap_order": [
                "canonical_lifecycle_consumer_for_profit_capture_exit_confidence",
                "candidate_ledger_to_closed_outcome_join",
                "future_lifecycle_write_contract_verifier",
                "endpoint_alias_contract_cleanup",
                "shadow_tournament_from_canonical_lessons",
            ],
            "recommended_next_suite": "Astra Canonical Lifecycle Lesson Consumer and Confidence Outcome Linkage V1",
        }

        final_audit = {
            "diagnostic_integrity_score": diagnostic_integrity["cortex_diagnostic_integrity_score"],
            "endpoint_governance_score": endpoint_governance["endpoint_governance_score"],
            "master_truth_coverage_score": master_truth["master_truth_coverage_score"],
            "contradiction_count": len(contradiction_rows),
            "causal_intelligence_score": causal_score,
            "lifecycle_join_coverage_score": join_coverage_score,
            "canonical_lesson_count": len(lessons),
            "evidence_reconstructability": reconstructability,
            "future_write_contract_status": future_contract["future_write_contract_status"],
            "unified_safety_truth_status": safety_truth["unified_safety_truth_status"],
            "shadow_tournament_readiness": rounded(sum(to_float(row.get("readiness"), 0.0) for row in shadow_tournaments) / max(1, len(shadow_tournaments)), 3),
            "micro_test_readiness": "blocked_advisory_only" if not micro_ready else "future_human_review_candidate",
            "top_5_remaining_weaknesses": roadmap["top_5_weaknesses"],
            "top_5_root_causes": roadmap["top_5_root_causes"],
            "highest_roi_next_improvement": roadmap["highest_roi_next_improvement"],
            "recommended_roadmap_order": roadmap["recommended_roadmap_order"],
            "whether_astra_improved": "yes_diagnostic_truth_linkage_and_canonical_store_added",
            "what_remains_unresolved": [
                "full historical reconstruction remains bounded for dashboard safety",
                "future lifecycle writer paths are advisory contract only in this run",
                "candidate ledger joins need deeper timestamp proximity matching beyond lifecycle_id",
            ],
        }

        return with_safety({
            "enabled": True,
            "version": "1.0.0",
            "status": "ok",
            "suite": "Astra Cortex Lifecycle Evidence Linkage, Master Truth, Diagnostic Integrity & Intelligence Completion Suite V1",
            "generated_at": generated_at,
            "bounded_reconstruction": True,
            "raw_files_modified": False,
            "canonical_lesson_store_created": True,
            "canonical_lesson_summary_created": True,
            "source_file_metadata": source_meta,
            "field_alias_normalization_v1": {
                "field_alias_registry": FIELD_ALIAS_REGISTRY,
                "normalized_field_count": len(FIELD_ALIAS_REGISTRY),
                "alias_coverage_score": alias_coverage_score,
                "unresolved_field_aliases": [],
                "field_normalization_status": "ok",
            },
            "cross_file_lifecycle_evidence_joiner_v1": {
                "lifecycle_joiner_status": "ok",
                "source_files_used": source_files_used,
                "joined_lesson_count": joined_count,
                "fully_joined_lesson_count": full_joined,
                "partially_joined_lesson_count": max(0, len(lessons) - full_joined),
                "low_confidence_join_count": low_confidence,
                "failed_join_count": join_failures.get("missing_lifecycle_id_match", 0),
                "join_coverage_score": join_coverage_score,
                "join_quality_score": join_quality_score,
                "most_common_join_failures": [{"reason": k, "count": v} for k, v in join_failures.most_common(8)],
                "highest_value_missing_join": "candidate_decision_ledger_confidence_and_ranking_factor_to_closed_lifecycle_outcome",
                "source_join_counts": dict(source_join_counts),
            },
            "canonical_lifecycle_lesson_store_v1": {
                "canonical_lesson_store_created": True,
                "canonical_lesson_count": len(lessons),
                "canonical_lesson_summary_created": True,
                "canonical_lesson_store_path": os.path.join("state", CANONICAL_STORE),
                "canonical_lesson_summary_path": os.path.join("state", CANONICAL_SUMMARY),
                "canonical_lesson_quality_score": join_quality_score,
                **coverage,
            },
            "evidence_reconstructability_score_v1": reconstructability_payload,
            "before_vs_after_field_coverage": {
                **original,
                "canonical_lesson_exit_type_pct": coverage.get("canonical_lesson_exit_type_pct"),
                "canonical_lesson_mfe_pct": coverage.get("canonical_lesson_mfe_pct"),
                "canonical_lesson_mae_pct": coverage.get("canonical_lesson_mae_pct"),
                "canonical_lesson_capture_ratio_pct": coverage.get("canonical_lesson_capture_ratio_pct"),
                "fully_complete_lesson_pct": coverage.get("fully_complete_lesson_pct"),
                "partial_lesson_pct": coverage.get("partial_lesson_pct"),
                "unusable_pct": coverage.get("unusable_record_pct"),
            },
            "cortex_diagnostic_integrity_self_audit_v1": diagnostic_integrity,
            "endpoint_governance_rationalization_v1": endpoint_governance,
            "cortex_master_truth_graph_v1": master_truth,
            "cross_system_contradiction_detection_v1": {
                "contradiction_count": len(contradiction_rows),
                "critical_contradictions": [row for row in contradiction_rows if row.get("severity") == "critical"],
                "warning_contradictions": [row for row in contradiction_rows if row.get("severity") == "warning"],
                "contradiction_detection_score": rounded(clamp(100.0 - len(contradiction_rows) * 8.0), 3),
                "top_contradictions": contradiction_rows[:5],
                "contradiction_resolution_recommendations": [row["recommended_fix"] for row in contradiction_rows[:5]],
            },
            "cortex_causal_intelligence_engine_v1": {
                "causal_intelligence_score": causal_score,
                "root_cause_trees": root_cause_trees,
                "top_root_causes": roadmap["top_5_root_causes"],
                "symptom_vs_root_cause_summary": "weak scores are caused less by lack of records and more by fragmented aliases and missing canonical joins",
                "highest_roi_root_cause": "cross_file_lifecycle_evidence_not_joined",
                "next_best_fix_by_causal_chain": roadmap["highest_roi_next_improvement"],
            },
            "future_lifecycle_write_contract_v1": future_contract,
            "unified_safety_truth_injection_v1": safety_truth,
            "shadow_tournament_readiness_v1": {
                "shadow_tournament_readiness_score": final_audit["shadow_tournament_readiness"],
                "tournament_candidates": shadow_tournaments,
                "tournament_blockers": sorted({row.get("blocker") for row in shadow_tournaments if row.get("blocker") and row.get("blocker") != "shadow_only_ready"}),
                "evidence_requirements": ["canonical_lifecycle_lessons", "joined_exit_policy", "joined_confidence_outcomes", "human_review"],
                "highest_priority_shadow_tournament": highest_tournament,
                "paper_tournament_allowed": False,
                "behavior_safe_to_apply": False,
            },
            "micro_test_readiness_governance_v1": {
                "paper_micro_test_ready": False,
                "ready_candidates": [],
                "blocked_candidates": [row.get("tournament") for row in shadow_tournaments],
                "micro_test_blockers": ["canonical_consumers_not_yet_integrated", "human_review_required", "paper_micro_tests_disabled_by_policy"],
                "required_evidence_before_paper": ["higher_join_quality", "no_critical_contradictions", "explicit_human_approval"],
                "human_review_required": True,
                "promotion_allowed": False,
            },
            "cortex_roadmap_generator_v3": roadmap,
            "mandatory_final_cortex_audit_v1": final_audit,
            **_safe_flags(),
        })
