from __future__ import annotations

import os
import re
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


SYSTEM_CATEGORIES = (
    "trading",
    "learning",
    "shadow",
    "portfolio",
    "market_intelligence",
    "infrastructure",
    "recovery",
    "governance",
    "provider",
    "dashboard",
)
CRITICAL_SYSTEMS = (
    "alpaca_paper_broker",
    "shadow_vs_paper_performance_attribution_v1",
    "controlled_paper_learned_exit_validation_v1",
    "astra_autonomous_governance_core_v1",
    "astra_autonomous_research_planning_ranking_intelligence_v1",
    "astra_controlled_ranking_evolution_executive_layer_v1",
    "astra_recovery_center_v1",
    "astra_provider_orchestration_data_governance_v1",
    "astra_adaptive_occupancy_evolution_suite_v1",
    "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1",
    "astra_tier2a_librarian_executive_truth_layer_v1",
    "astra_satellite_network_v1",
    "unified_learning_diagnostics_v1",
)
STATE_SCAN_LIMIT = 80
ENGINE_SCAN_LIMIT = 320


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
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _category_for(name: str) -> str:
    n = str(name or "").lower()
    if "broker" in n or "paper" in n or "trade" in n or "execution" in n:
        return "trading"
    if "learning" in n or "lifecycle" in n or "memory" in n:
        return "learning"
    if "shadow" in n or "replay" in n or "counterfactual" in n:
        return "shadow"
    if "portfolio" in n or "risk" in n or "allocation" in n:
        return "portfolio"
    if "market" in n or "sector" in n or "catalyst" in n or "macro" in n or "crypto" in n:
        return "market_intelligence"
    if "recover" in n or "runtime" in n or "health" in n or "infrastructure" in n:
        return "infrastructure"
    if "governance" in n or "truth" in n or "audit" in n or "registry" in n:
        return "governance"
    if "provider" in n or "api" in n or "fmp" in n or "alpaca" in n:
        return "provider"
    if "dashboard" in n or "copilot" in n or "ask_astra" in n:
        return "dashboard"
    return "learning"


def _status_label(row: dict[str, Any], cache_exists: bool) -> str:
    if not row:
        return "missing"
    raw = text(first(row.get("status"), row.get("health"), row.get("safety_status"), row.get("mode"), default="healthy"), "healthy").lower()
    if row.get("enabled") is False:
        return "inactive"
    if row.get("degraded_reason") or row.get("error"):
        return "warning"
    if "critical" in raw or "red" in raw or "failed" in raw:
        return "critical"
    if "stale" in raw:
        return "stale"
    if "disconnected" in raw:
        return "disconnected"
    if not cache_exists and "v1" in raw:
        return "warning"
    if "warning" in raw or "partial" in raw or "blocked" in raw or "insufficient" in raw:
        return "warning"
    return "healthy"


def _metric_count(row: dict[str, Any]) -> int:
    keys = (
        "evidence_count",
        "canonical_closed_trade_count",
        "paper_trade_count",
        "shadow_trade_count",
        "recommendations_reviewed",
        "candidate_decision_record_count",
        "lifecycle_rows_audited",
        "tournament_count",
        "trade_count",
    )
    return max(to_int(row.get(key), 0) for key in keys)


class AstraAutonomousOptimizationGovernanceCoreV1(CachedDiagnosticModule):
    """Systemwide oversight and optimization diagnostics.

    The core is observational only. It inventories existing Astra systems,
    reconciles cached status signals, finds conflicts/redundancy/resource
    pressure, and emits recommendations without changing any trading behavior.
    """

    module_name = "astra_autonomous_optimization_governance_core_v1"
    mode = "systemwide_autonomous_optimization_governance_advisory"

    def _engine_modules(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        engine_dir = os.path.join(os.getcwd(), "engine")
        try:
            names = sorted(name for name in os.listdir(engine_dir) if name.endswith(".py"))[:ENGINE_SCAN_LIMIT]
        except Exception:
            names = []
        for name in names:
            base = name[:-3]
            path = os.path.join(engine_dir, name)
            try:
                stat = os.stat(path)
                size = int(stat.st_size)
                mtime = float(stat.st_mtime)
            except Exception:
                size = 0
                mtime = 0.0
            rows.append({
                "system_name": base,
                "system_type": "engine_module",
                "category": _category_for(base),
                "present": True,
                "path": f"engine/{name}",
                "size_bytes": size,
                "mtime": mtime,
            })
        return rows

    def _endpoint_inventory(self) -> list[dict[str, Any]]:
        endpoints: list[dict[str, Any]] = []
        pattern = re.compile(r"@router\.(?:get|post)\(\"([^\"]+)\"\)")
        try:
            with open("server_extend.py", "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    match = pattern.search(line)
                    if match:
                        route = match.group(1)
                        endpoints.append({
                            "system_name": route.replace("/api/", "").replace("/", "_") or route,
                            "system_type": "endpoint",
                            "category": _category_for(route),
                            "endpoint": route,
                            "present": True,
                            "endpoint_available": True,
                        })
        except Exception:
            return []
        return endpoints[:260]

    def _state_inventory(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        state_dir = self.state_dir
        try:
            names = sorted(os.listdir(state_dir))
        except Exception:
            names = []
        for name in names:
            if len(rows) >= STATE_SCAN_LIMIT:
                break
            path = os.path.join(state_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except Exception:
                continue
            rows.append({
                "name": name,
                "path": f"state/{name}",
                "size_bytes": int(stat.st_size),
                "mtime": float(stat.st_mtime),
                "category": _category_for(name),
                "recommendation": "compress_or_archive_if_not_hot_path" if int(stat.st_size) > 100_000_000 else "retain_cached_summary",
            })
        rows.sort(key=lambda row: to_float(row.get("size_bytes"), 0.0), reverse=True)
        total = sum(to_int(row.get("size_bytes"), 0) for row in rows)
        largest = rows[0] if rows else {}
        return {
            "state_files_reviewed": len(rows),
            "state_bytes_reviewed": total,
            "largest_state_file": largest,
            "large_state_files": [row for row in rows if to_int(row.get("size_bytes"), 0) > 50_000_000][:10],
            "storage_pressure_score": rounded(clamp(total / 20_000_000.0), 3),
        }

    def _system_inventory(self, statuses: dict[str, Any], endpoint_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cache_dir = os.path.join(self.state_dir, "dashboard_cache")
        endpoint_names = {str(row.get("system_name")) for row in endpoint_rows}
        rows: list[dict[str, Any]] = []
        seen = set()
        for name, value in sorted((statuses or {}).items()):
            if not isinstance(value, dict):
                continue
            cache_path = os.path.join(cache_dir, f"{name}.json")
            cache_exists = os.path.exists(cache_path)
            endpoint_available = name in endpoint_names or f"/api/{name}" in {str(row.get("endpoint")) for row in endpoint_rows}
            status = _status_label(value, cache_exists)
            evidence = _metric_count(value)
            latency = to_float(first(value.get("build_ms"), value.get("latency_ms"), value.get("endpoint_latency_ms"), default=0.0), 0.0)
            usefulness = clamp(min(55.0, evidence / 1500.0) + (25.0 if status in {"healthy", "warning"} else 5.0) + (20.0 if endpoint_available or cache_exists else 0.0))
            risk = clamp((35.0 if status in {"critical", "warning", "stale", "disconnected"} else 5.0) + (latency / 150.0) + (15.0 if not cache_exists and endpoint_available else 0.0))
            contribution = clamp(usefulness - risk * 0.25)
            rows.append({
                "system_name": name,
                "category": _category_for(name),
                "present": True,
                "active": value.get("enabled", True) is not False,
                "status": status,
                "connected": bool(endpoint_available or cache_exists or evidence > 0),
                "endpoint_available": endpoint_available,
                "cache_available": cache_exists,
                "output_valid": bool(value),
                "latency_ms": rounded(latency, 3),
                "evidence_count": evidence,
                "usefulness_score": rounded(usefulness, 3),
                "risk_score": rounded(risk, 3),
                "redundancy_score": 0.0,
                "contribution_score": rounded(contribution, 3),
                "recommendation": "investigate_status_or_cache" if status in {"critical", "warning", "stale", "disconnected"} else "keep",
            })
            seen.add(name)
        for name in CRITICAL_SYSTEMS:
            if name not in seen:
                rows.append({
                    "system_name": name,
                    "category": _category_for(name),
                    "present": False,
                    "active": False,
                    "status": "missing",
                    "connected": False,
                    "endpoint_available": name in endpoint_names,
                    "cache_available": False,
                    "output_valid": False,
                    "latency_ms": 0.0,
                    "evidence_count": 0,
                    "usefulness_score": 0.0,
                    "risk_score": 75.0,
                    "redundancy_score": 0.0,
                    "contribution_score": 0.0,
                    "recommendation": "restore_or_wire_required_system",
                })
        prefix_counts = Counter(str(row["system_name"]).split("_v")[0].replace("astra_", "") for row in rows)
        for row in rows:
            redundancy = max(0, prefix_counts[str(row["system_name"]).split("_v")[0].replace("astra_", "")] - 1) * 12.5
            row["redundancy_score"] = rounded(clamp(redundancy), 3)
            if redundancy >= 25 and row["recommendation"] == "keep":
                row["recommendation"] = "check_overlap_and_consolidate_if_outputs_conflict"
        rows.sort(key=lambda row: (to_float(row.get("risk_score"), 0.0), to_float(row.get("redundancy_score"), 0.0)), reverse=True)
        return rows[:180]

    def _conflicts(self, statuses: dict[str, Any]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        shadow = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        controlled = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        alpaca = status_value(statuses, "alpaca_paper_broker")
        truth = status_value(statuses, "astra_truth_controlled_evolution_executive_v1")
        perf = status_value(statuses, "astra_performance_optimization_suite_v1")
        closed = to_int(shadow.get("canonical_closed_trade_count"), 0)
        if closed > 0 and to_int(controlled.get("canonical_closed_trade_count"), closed) == 0:
            conflicts.append({
                "conflict_type": "truth_mismatch",
                "systems_involved": ["shadow_vs_paper_performance_attribution_v1", "controlled_paper_learned_exit_validation_v1"],
                "severity": "high",
                "confidence": 90.0,
                "likely_cause": "exit_validator_not_consuming_canonical_lifecycle_truth",
                "recommended_correction": "reuse_shadow_vs_paper_canonical_truth_fields",
            })
        if bool(alpaca.get("paper_mode_verified")) and bool(alpaca.get("broker_live_endpoint_allowed")):
            conflicts.append({
                "conflict_type": "broker_safety_conflict",
                "systems_involved": ["alpaca_paper_broker"],
                "severity": "critical",
                "confidence": 95.0,
                "likely_cause": "paper_mode_and_live_endpoint_flags_disagree",
                "recommended_correction": "block_behavior_and_reconcile_broker_endpoint_config",
            })
        truth_status = text((truth.get("executive_snapshot_truth_reconciliation_v1") or {}).get("status"), "")
        if truth_status and truth_status not in {"PASS", "ok", "healthy"} and closed > 0:
            conflicts.append({
                "conflict_type": "executive_truth_status_mismatch",
                "systems_involved": ["astra_truth_controlled_evolution_executive_v1", "shadow_vs_paper_performance_attribution_v1"],
                "severity": "medium",
                "confidence": 70.0,
                "likely_cause": "executive_truth_layer_not_using_latest_canonical_closed_trade_cache",
                "recommended_correction": "refresh_truth_layer_from_shadow_vs_paper_canonical_metrics",
            })
        if perf.get("status") in {"critical", "warning"}:
            conflicts.append({
                "conflict_type": "performance_optimization_warning",
                "systems_involved": ["astra_performance_optimization_suite_v1"],
                "severity": "medium",
                "confidence": 65.0,
                "likely_cause": "optimization_suite_reported_warning_status",
                "recommended_correction": "inspect_performance_suite_top_bottleneck",
            })
        return conflicts[:12]

    def _improvement_attribution(self, statuses: dict[str, Any]) -> dict[str, Any]:
        controlled = status_value(statuses, "astra_controlled_ranking_evolution_executive_layer_v1")
        gov = status_value(statuses, "astra_autonomous_governance_core_v1")
        manager = status_value(controlled, "autonomous_improvement_program_manager_v1")
        rows = [dict(row) for row in (manager.get("correction_program_rows") or []) if isinstance(row, dict)]
        if not rows:
            correction = status_value(gov, "correction_validation")
            rows = [dict(row) for row in (correction.get("correction_validation_rows") or []) if isinstance(row, dict)]
        normalized = []
        for row in rows[:20]:
            benefit = first(row.get("actual_benefit"), row.get("actual_improvement"), row.get("confidence"), row.get("confidence_score"), default=0.0)
            confidence = first(row.get("confidence"), row.get("confidence_score"), default=0.0)
            roi = clamp(to_float(benefit, 0.0) * 0.7 + to_float(confidence, 0.0) * 0.3)
            normalized.append({
                "improvement": text(first(row.get("correction"), row.get("name"), default="unknown")),
                "why_built": text(first(row.get("goal"), row.get("expected_outcome"), default="improve_astra_reliability")),
                "expected_benefit": row.get("expected_benefit") or row.get("expected_outcome"),
                "actual_measured_benefit": benefit,
                "trading_impact": "advisory_only",
                "learning_impact": "measured_from_cached_governance_rows",
                "reliability_impact": "positive" if roi >= 50 else "uncertain",
                "performance_impact": row.get("status") or row.get("classification"),
                "confidence_score": rounded(confidence, 3),
                "roi_score": rounded(roi, 3),
                "recommendation": "expand" if roi >= 75 else "refine" if roi >= 40 else "investigate_or_retire",
            })
        most = max(normalized, key=lambda row: to_float(row.get("roi_score"), 0.0), default={})
        least = min(normalized, key=lambda row: to_float(row.get("roi_score"), 999.0), default={})
        return {
            "improvements_tracked": len(normalized),
            "improvement_rows": normalized,
            "upgrade_helped_most": most,
            "upgrade_helped_least": least,
            "upgrade_created_risk_or_overhead": [row for row in normalized if row.get("recommendation") == "investigate_or_retire"][:5],
            "next_improvement_to_refine": (least or {}).get("improvement", "profit_capture"),
        }

    def _resource_summary(self, inventory: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        slowest = max(inventory, key=lambda row: to_float(row.get("latency_ms"), 0.0), default={})
        highest_cost = max(inventory, key=lambda row: to_float(row.get("risk_score"), 0.0) + to_float(row.get("latency_ms"), 0.0) / 100.0, default={})
        low_value_high_cost = max(
            inventory,
            key=lambda row: max(0.0, to_float(row.get("risk_score"), 0.0) - to_float(row.get("usefulness_score"), 0.0)),
            default={},
        )
        high_value_low_cost = max(
            inventory,
            key=lambda row: to_float(row.get("usefulness_score"), 0.0) - to_float(row.get("risk_score"), 0.0),
            default={},
        )
        return {
            "highest_cost_system": highest_cost,
            "lowest_value_high_cost_system": low_value_high_cost,
            "highest_value_low_cost_system": high_value_low_cost,
            "slowest_endpoint": slowest,
            "largest_state_file": state.get("largest_state_file") or {},
            "most_important_performance_bottleneck": text(first((low_value_high_cost or {}).get("system_name"), (state.get("largest_state_file") or {}).get("name"), default="none")),
            "recommendations": [
                "cache_result" if to_float(slowest.get("latency_ms"), 0.0) > 500 else "keep_cached_fast_paths",
                "compress_or_archive_large_jsonl_files" if state.get("large_state_files") else "retain_current_state_file_policy",
                "delay_low_value_work" if to_float(low_value_high_cost.get("risk_score"), 0.0) > 60 else "continue_current_worker_budget",
            ],
            "storage_pressure_score": state.get("storage_pressure_score", 0.0),
        }

    def _api_governance(self, statuses: dict[str, Any]) -> dict[str, Any]:
        provider = status_value(statuses, "astra_provider_orchestration_data_governance_v1")
        alpaca = status_value(statuses, "alpaca_paper_broker")
        ask = status_value(statuses, "ask_astra_local_ai_status_v1")
        rows = [
            {
                "provider": "Alpaca",
                "healthy": bool(alpaca.get("paper_mode_verified", True)),
                "calls_used": to_int(alpaca.get("api_calls_used"), 0),
                "dashboard_calls_used": to_int(alpaca.get("dashboard_provider_calls_used"), 0),
                "best_use_case": "broker_truth_positions_orders_account_paper_only",
                "risk": "live_endpoint_blocked" if alpaca.get("broker_live_endpoint_allowed") else "paper_safe",
            },
            {
                "provider": "FMP/TwelveData",
                "healthy": provider.get("provider_budget_safe", True) is not False,
                "calls_used": to_int(provider.get("provider_calls_used"), 0),
                "dashboard_calls_used": to_int(provider.get("dashboard_provider_calls_used"), 0),
                "best_use_case": "cached_market_context_fundamentals_calendar_data",
                "risk": "budget_governed",
            },
            {
                "provider": "Ollama/local LLM",
                "healthy": bool(ask.get("ollama_reachable") or ask.get("selected_model")),
                "calls_used": to_int(ask.get("llm_calls_used"), 0),
                "dashboard_calls_used": to_int(ask.get("dashboard_llm_calls_used"), 0),
                "best_use_case": "user_triggered_ask_astra_explanations",
                "risk": "user_triggered_only",
            },
        ]
        wasted = [row for row in rows if to_int(row.get("dashboard_calls_used"), 0) > 0]
        return {
            "provider_rows": rows,
            "provider_calls_used": 0,
            "dashboard_provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_llm_calls_used": 0,
            "provider_budget_safe": not wasted,
            "api_provider_risks": wasted,
            "provider_recommendations": [
                "keep_dashboard_provider_calls_zero",
                "use_alpaca_only_for_broker_truth",
                "use_local_llm_only_after_user_submit",
                "prefer_cached_market_context_for_dashboard",
            ],
        }

    def _compression_summary(self, inventory: list[dict[str, Any]], state: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        learning = [row for row in inventory if row.get("category") in {"learning", "shadow", "market_intelligence"}]
        useful = [row for row in learning if to_float(row.get("contribution_score"), 0.0) >= 45]
        stale = [row for row in learning if row.get("status") in {"stale", "warning", "disconnected"}]
        duplicate_pressure = [row for row in inventory if to_float(row.get("redundancy_score"), 0.0) >= 25][:8]
        evidence_quality = status_value(statuses, "evidence_quality_scoring_v1")
        return {
            "signal_to_noise_score": rounded(clamp((len(useful) / max(1, len(learning))) * 100.0 - len(duplicate_pressure) * 2.0), 3),
            "duplicate_observations": len(duplicate_pressure),
            "stale_observations": len(stale),
            "high_value_learning_systems": useful[:8],
            "low_value_learning_systems": stale[:8],
            "memory_usefulness": rounded(first(evidence_quality.get("average_evidence_quality"), 62.0), 3),
            "learning_velocity": text(first(status_value(statuses, "learning_acceleration_retention_suite_v1").get("learning_velocity_status"), "warming_up")),
            "evidence_quality": evidence_quality.get("quality_bucket", "warming_up"),
            "recommendations": [
                "compress_repeated_diagnostics_into_executive_summaries",
                "archive_large_jsonl_files_after_cached_truth_is_preserved" if state.get("large_state_files") else "retain_current_cache_policy",
                "expand_collection_only_for_high_roi_gaps",
                "reduce_duplicate_overlap_before_adding_new_systems",
            ],
            "is_collecting_too_much": bool(len(duplicate_pressure) >= 5 or len(state.get("large_state_files") or []) >= 5),
            "is_collecting_too_little": bool(len(useful) < 5),
            "most_useful_information": (useful[0] if useful else {}).get("system_name", "canonical_lifecycle_truth"),
            "least_useful_information": (stale[0] if stale else {}).get("system_name", "none"),
        }

    def _promotion_oversight(self, statuses: dict[str, Any]) -> dict[str, Any]:
        controlled = status_value(statuses, "astra_controlled_ranking_evolution_executive_layer_v1")
        promotion = status_value(controlled, "controlled_self_promotion_readiness_engine_v1")
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        status = text(first(promotion.get("status"), learned.get("readiness_status"), "continue_collecting_evidence"))
        blocked = bool("block" in status.lower() or "collect" in status.lower() or not promotion.get("paper_micro_test_ready", False))
        return {
            "status": status,
            "ready_for_paper_micro_test": bool(promotion.get("paper_micro_test_ready", False)),
            "not_ready": blocked,
            "continue_collecting_evidence": "collect" in status.lower() or blocked,
            "blocked": blocked,
            "rejected": False,
            "needs_human_review": True,
            "promotion_readiness_score": rounded(first(promotion.get("promotion_readiness_score"), learned.get("policy_confidence"), default=0.0), 3),
            "promotion_blockers": list(promotion.get("promotion_blockers") or learned.get("paper_exit_path_blockers") or [])[:8],
            "automatic_promotions_enabled": False,
        }

    def _dependency_map(self, statuses: dict[str, Any], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
        controlled = status_value(statuses, "astra_controlled_ranking_evolution_executive_layer_v1")
        research = status_value(statuses, "astra_autonomous_research_planning_ranking_intelligence_v1")
        weakness = text(first(controlled.get("highest_roi_remaining_improvement"), research.get("highest_roi_remaining_improvement"), "profit_capture_and_ranking_bias"))
        dependency = {
            "weakness": weakness,
            "upstream_causes": [
                "ranking_attribution_confidence",
                "regime_attribution_quality",
                "profit_capture_persistence_window",
            ],
            "downstream_effects": [
                "promotion_readiness_delay",
                "paper_micro_test_blocked",
                "executive_confidence_warming_up",
            ],
            "dependent_systems": [
                "candidate_ranking_attribution_promotion_intelligence_v1",
                "shadow_vs_paper_performance_attribution_v1",
                "controlled_paper_learned_exit_validation_v1",
                "astra_controlled_ranking_evolution_executive_layer_v1",
            ],
            "prerequisite_repairs": [c.get("recommended_correction") for c in conflicts[:3]],
            "blocking_systems": [c.get("systems_involved") for c in conflicts[:3]],
            "highest_leverage_dependency": "ranking_attribution_plus_profit_capture_persistence",
            "recommended_next_action": "improve_ranking_attribution_and_profit_capture_validation_before_micro_test",
        }
        return dependency

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        endpoint_rows = self._endpoint_inventory()
        state = self._state_inventory()
        inventory = self._system_inventory(statuses, endpoint_rows)
        conflicts = self._conflicts(statuses)
        improvement = self._improvement_attribution(statuses)
        resource = self._resource_summary(inventory, state)
        api = self._api_governance(statuses)
        compression = self._compression_summary(inventory, state, statuses)
        promotion = self._promotion_oversight(statuses)
        dependency = self._dependency_map(statuses, conflicts)

        active = [row for row in inventory if row.get("active")]
        healthy = [row for row in inventory if row.get("status") == "healthy"]
        warning = [row for row in inventory if row.get("status") in {"warning", "critical", "stale", "disconnected", "missing"}]
        duplicate_rows = [row for row in inventory if to_float(row.get("redundancy_score"), 0.0) >= 25]
        truth_consistency = 100.0 - len([c for c in conflicts if c.get("conflict_type", "").endswith("mismatch")]) * 18.0
        system_health = clamp((len(healthy) / max(1, len(inventory))) * 100.0 - len([c for c in conflicts if c.get("severity") == "critical"]) * 12.0)
        reliability = clamp(system_health - len(warning) * 0.25)
        optimization = clamp(100.0 - to_float(resource.get("storage_pressure_score"), 0.0) * 0.35 - len(duplicate_rows) * 1.8)
        top_weaknesses = [
            text((resource.get("lowest_value_high_cost_system") or {}).get("system_name"), "none"),
            text((state.get("largest_state_file") or {}).get("name"), "none"),
            text(dependency.get("weakness"), "profit_capture_and_ranking_bias"),
            text((conflicts[0] if conflicts else {}).get("conflict_type"), "no_high_confidence_conflicts"),
            text(compression.get("least_useful_information"), "none"),
        ]
        top_strengths = [
            text((resource.get("highest_value_low_cost_system") or {}).get("system_name"), "cached_unified_diagnostics"),
            text((improvement.get("upgrade_helped_most") or {}).get("improvement"), "trading_brain_completion"),
            "paper_only_safety_controls",
            "dashboard_provider_calls_zero",
            "cache_first_diagnostics",
        ]
        recommendations = [
            dependency.get("recommended_next_action"),
            "compress_or_archive_large_state_files" if state.get("large_state_files") else "retain_state_policy",
            "consolidate_duplicate_diagnostics_before_new_engines" if duplicate_rows else "keep_current_diagnostic_boundaries",
            "preserve_dashboard_zero_provider_calls",
            "continue_collecting_evidence_before_paper_micro_tests",
        ]
        payload = {
            "enabled": True,
            "version": "1.0.0",
            "suite": "Astra Autonomous Optimization & Governance Core V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "system_inventory": inventory,
            "endpoint_inventory_count": len(endpoint_rows),
            "engine_inventory_count": len(self._engine_modules()),
            "system_health_score": rounded(system_health, 3),
            "reliability_score": rounded(reliability, 3),
            "optimization_score": rounded(optimization, 3),
            "truth_consistency_score": rounded(clamp(truth_consistency), 3),
            "redundancy_conflict_summary": {
                "conflict_count": len(conflicts),
                "redundant_system_count": len(duplicate_rows),
                "top_conflicts": conflicts[:5],
                "top_redundancy_findings": duplicate_rows[:5],
            },
            "resource_allocation_summary": resource,
            "api_governance_summary": api,
            "information_compression_summary": compression,
            "promotion_readiness_oversight": promotion,
            "improvement_attribution_summary": improvement,
            "dependency_map": dependency,
            "highest_roi_next_improvement": dependency.get("recommended_next_action"),
            "recommended_next_roadmap_item": "ranking_attribution_profit_capture_persistence_and_state_compaction",
            "top_findings": [
                {"finding": item, "category": "weakness", "recommendation": recommendations[min(i, len(recommendations) - 1)]}
                for i, item in enumerate(top_weaknesses)
            ],
            "top_recommendations": recommendations,
            "top_weaknesses": top_weaknesses,
            "top_strengths": top_strengths,
            "top_bottlenecks": [
                resource.get("most_important_performance_bottleneck"),
                (state.get("largest_state_file") or {}).get("name"),
                dependency.get("weakness"),
            ],
            "top_system_conflicts": conflicts[:5],
            "top_redundant_systems": duplicate_rows[:5],
            "top_performance_bottlenecks": [
                resource.get("slowest_endpoint"),
                resource.get("highest_cost_system"),
                resource.get("lowest_value_high_cost_system"),
            ],
            "api_provider_findings": api.get("provider_rows"),
            "information_overload_underutilization_findings": {
                "is_collecting_too_much": compression.get("is_collecting_too_much"),
                "is_collecting_too_little": compression.get("is_collecting_too_little"),
                "duplicate_observations": compression.get("duplicate_observations"),
                "stale_observations": compression.get("stale_observations"),
            },
            "safety_confirmations": _safe_flags(),
            **_safe_flags(),
        }
        return with_safety(payload)
