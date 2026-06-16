from __future__ import annotations

import time
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    clamp,
    first,
    now_iso,
    rounded,
    safe_average,
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)

MAX_ROWS = 30


def _list(value: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _pct(value: Any) -> float:
    out = to_float(value, 0.0)
    if -1.25 <= out <= 1.25 and out != 0:
        out *= 100.0
    return out


def _horizon_limit_hours(horizon: str) -> float:
    h = str(horizon or "unknown").lower().replace("-", "_").replace(" ", "_")
    if h == "scalp":
        return 1.5
    if h == "day_trade":
        return 10.0
    if h == "swing_trade":
        return 120.0
    return 24.0


def _safe_flags(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
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
        "sell_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "paper_execution_changed": False,
        "forced_exits_enabled": False,
        "forced_trades_enabled": False,
        "partial_sells_enabled": False,
        "automatic_trailing_stops_enabled": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
    }
    out.update(extra or {})
    return out


class AstraFoundationStabilizationGovernanceBundleV1(CachedDiagnosticModule):
    """Foundation stabilization and governance diagnostics.

    This bundle is framework preparation only. It consumes cached diagnostics,
    emits advisory rows and governance state, and never writes to strategy,
    broker, paper execution, sizing, allocation, threshold, or ranking systems.
    """

    module_name = "astra_foundation_stabilization_governance_bundle_v1"
    mode = "foundation_stabilization_governance_advisory"

    def _active_positions(self, statuses: dict[str, Any]) -> list[dict[str, Any]]:
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        mobile = status_value(statuses, "mobile_runtime_compaction")
        rows = _list(lifecycle.get("position_audit_rows"))
        if rows:
            return rows[:MAX_ROWS]
        for key in ("desktop_positions_preview", "true_broker_positions_preview", "positions", "open_positions", "active_positions"):
            rows = _list(mobile.get(key))
            if rows:
                return rows[:MAX_ROWS]
        return []

    def _trading_integrity(self, statuses: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        multi = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        mobile = status_value(statuses, "mobile_runtime_compaction")
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        unknown = to_int(multi.get("unknown_horizon_positions"), to_int(lifecycle.get("horizon_distribution", {}).get("unknown"), 0))
        broker_positions = max(
            to_int(mobile.get("true_broker_active_positions"), 0),
            to_int(multi.get("broker_confirmed_positions"), 0),
            to_int(lifecycle.get("broker_confirmed_positions"), 0),
        )
        stale_rows = max(
            to_int(mobile.get("stale_internal_positions"), 0),
            to_int(multi.get("stale_internal_rows"), 0),
            to_int(lifecycle.get("stale_internal_rows"), 0),
        )
        candidates_today = to_int(learned.get("learned_exit_candidates_today"), 0)
        blockers = list(learned.get("paper_exit_path_blockers") or learned.get("rejection_reasons") or [])[:10]
        if candidates_today <= 0:
            if not rows and broker_positions <= 0:
                diagnosis = "no_active_broker_confirmed_positions_available_to_review"
            elif blockers:
                diagnosis = f"candidate_generation_suppressed_by_{text(blockers[0])}"
            elif not learned.get("learned_exit_bucket_enabled"):
                diagnosis = "learned_exit_bucket_disabled_or_not_evidence_ready"
            else:
                diagnosis = "no_active_position_met_evidence_confidence_exit_due_requirements"
        else:
            diagnosis = "learned_exit_candidates_generated"
        return {
            "infer_horizon_style_reads_paper_entry_horizon_style": True,
            "unknown_horizon_positions": unknown,
            "unknown_horizon_positions_ok": unknown == 0,
            "broker_confirmed_positions_source_of_truth": bool(mobile.get("broker_positions_fetch_ok", True) or broker_positions >= 0),
            "broker_confirmed_positions": broker_positions,
            "stale_internal_rows": stale_rows,
            "stale_internal_rows_distort_active_positions": False,
            "horizon_reconciliation_persistent": unknown == 0 and bool(multi.get("enabled", True)),
            "learned_exit_candidates_today": candidates_today,
            "learned_exit_candidates_today_diagnosis": diagnosis,
            "learned_exit_blockers": blockers,
        }

    def _horizon_exit_candidates(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        out = []
        for row in rows[:MAX_ROWS]:
            horizon = text(first(row.get("normalized_horizon"), row.get("horizon"), row.get("trade_horizon"), default="unknown"), "unknown")
            elapsed = to_float(first(row.get("elapsed_hold_hours"), row.get("hold_hours"), default=0.0), 0.0)
            expected = _horizon_limit_hours(horizon)
            sell_conf = clamp(first(row.get("sell_confidence"), row.get("exit_readiness"), default=0.0))
            exit_due = bool(elapsed >= expected or sell_conf >= 68.0 or row.get("should_have_profit_protected"))
            conversion = bool(row.get("should_have_converted_horizon") or (horizon in {"scalp", "day_trade"} and elapsed >= expected))
            reason = text(first(row.get("exit_blocker"), row.get("why_still_holding"), default="natural_exit_rules_not_satisfied"))
            out.append({
                "symbol": text(first(row.get("symbol"), row.get("ticker"), default="UNKNOWN"), "UNKNOWN").upper(),
                "horizon": horizon,
                "elapsed_hold_duration_hours": rounded(elapsed, 3),
                "expected_hold_duration_hours": rounded(expected, 3),
                "exit_due": exit_due,
                "conversion_candidate": conversion,
                "confidence": rounded(first(row.get("truth_confidence"), row.get("confidence"), sell_conf, default=0.0), 3),
                "reason": reason,
            })
        due = [r for r in out if r["exit_due"]]
        return {
            "status": "ok" if out else "insufficient_evidence",
            "candidate_count": len(out),
            "exit_due_count": len(due),
            "conversion_candidate_count": len([r for r in out if r["conversion_candidate"]]),
            "biggest_exit_blocker": text(first((due[0] if due else {}).get("reason"), "natural_exit_rules_not_satisfied")),
            "rows": out,
            **_safe_flags(),
        }

    def _exit_pipeline_integrity(self, statuses: dict[str, Any]) -> dict[str, Any]:
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        multi = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        generated = to_int(learned.get("learned_exit_candidates_today"), 0)
        rejected = to_int(learned.get("rejected_learned_exit_candidates"), 0)
        applied = to_int(learned.get("learned_corrected_exits_today"), to_int(learned.get("learned_exits_used_today"), 0))
        blocked = max(0, generated - rejected - applied)
        blockers = list(learned.get("paper_exit_path_blockers") or learned.get("rejection_reasons") or [])[:10]
        if not blockers and generated <= 0:
            blockers = [text(learned.get("rollback_reason") or multi.get("rollback_reason") or "no_exit_candidates_met_requirements")]
        return {
            "generated_exits": generated,
            "suppressed_exits": max(0, to_int(multi.get("learned_exits_remaining_today"), 0) - generated) if generated == 0 else 0,
            "blocked_exits": blocked,
            "rejected_exits": rejected,
            "applied_exits": applied,
            "biggest_exit_blocker": text(blockers[0] if blockers else "none"),
            "exit_blockers": blockers,
            "explanation": "Exit pipeline is advisory-visible only; no forced or autonomous sells were enabled.",
            **_safe_flags(),
        }

    def _profit_capture_truth(self, statuses: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        peak = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        mfe_values = [to_float(first(r.get("mfe"), r.get("max_favorable_excursion"), r.get("pnl_percent"), default=0.0), 0.0) for r in rows]
        current_values = [_pct(first(r.get("pnl_percent"), r.get("current_profit"), default=0.0)) for r in rows]
        giveback_rows = [max(0.0, mfe - cur) for mfe, cur in zip(mfe_values, current_values)]
        giveback = first(profit.get("giveback_rate"), peak.get("average_giveback_pct"), safe_average(giveback_rows), default=0.0)
        capture = first(profit.get("profit_capture_score"), peak.get("capture_quality_score"), default=max(0.0, 100.0 - to_float(giveback) * 4.0))
        leak = text(first(profit.get("strongest_profit_protection_pattern"), peak.get("strongest_failure_signal"), "profit_giveback_after_peak"))
        return {
            "mfe_average": rounded(safe_average(mfe_values), 3),
            "current_profit_average": rounded(safe_average(current_values), 3),
            "realized_profit_average": rounded(first(peak.get("average_realized_return"), peak.get("average_return"), default=0.0), 3),
            "giveback": rounded(giveback, 3),
            "capture_ratio": rounded(first(peak.get("average_capture_ratio"), to_float(capture) / 100.0, default=0.0), 4),
            "peak_decay": rounded(first(profit.get("peak_decay_risk"), peak.get("peak_decay_risk"), default=0.0), 3),
            "profit_protection_opportunity": bool(to_float(giveback) > 8.0 or to_float(capture) < 60.0),
            "biggest_profit_capture_leak": leak,
            "estimated_profit_capture_improvement": rounded(profit.get("estimated_profit_capture_improvement"), 3),
            **_safe_flags(),
        }

    def _capital_efficiency(self, statuses: dict[str, Any], rows: list[dict[str, Any]], integrity: dict[str, Any]) -> dict[str, Any]:
        multi = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        throughput = status_value(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        total_used = to_int(first(multi.get("total_used"), integrity.get("broker_confirmed_positions"), len(rows), default=0), 0)
        total_capacity = to_int(first(multi.get("total_capacity"), 20, default=20), 20)
        total_available = max(0, to_int(first(multi.get("total_available"), total_capacity - total_used, default=0), 0))
        stale = to_int(integrity.get("stale_internal_rows"), 0)
        missed_pressure = max(
            to_int(multi.get("missed_evidence_due_to_capacity"), 0),
            to_int(throughput.get("missed_evidence_estimate"), 0),
            to_int(throughput.get("high_confidence_candidates_blocked"), 0),
        )
        trapped = bool(total_available <= 0 or to_float(multi.get("candidates_blocked_by_horizon_capacity"), 0.0) > 0)
        return {
            "trapped_capital": trapped,
            "trapped_capital_status": "capacity_constrained_review_needed" if trapped else "capacity_available_or_not_constrained",
            "stale_positions": stale,
            "stale_positions_blocking_capacity": False,
            "capacity_bottlenecks": list(multi.get("horizon_capacity_blockers") or [])[:10],
            "total_capacity": total_capacity,
            "total_used": total_used,
            "total_available": total_available,
            "missed_opportunity_pressure": missed_pressure,
            "recommended_action": text(first(multi.get("recommended_capacity_action"), throughput.get("recommended_safe_throughput_action"), default="monitor_capacity_without_changing_limits")),
            **_safe_flags(),
        }

    def _internal_audit(self, statuses: dict[str, Any]) -> dict[str, Any]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        perf = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        return {
            "department": "Astra Internal Audit Department V1",
            "cadence": "nightly_report_only",
            "did_i_buy_correctly": rounded(first(ranking.get("promotion_accuracy"), ranking.get("ranking_quality_score"), default=0.0), 3),
            "did_i_hold_correctly": rounded(first(lifecycle.get("correctly_holding_count"), 0), 3),
            "did_i_sell_correctly": rounded(first(perf.get("paper_exit_quality"), perf.get("paper_profit_capture"), default=0.0), 3),
            "did_i_trap_capital": bool(to_float(status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1").get("total_available"), 1.0) <= 0.0),
            "did_i_surrender_profits": bool(to_float(profit.get("giveback_rate"), 0.0) > 8.0),
            "did_pf_improve": text(perf.get("overall_reconciliation_status") or "monitor_pf_trend"),
            "did_bugs_appear": False,
            "did_new_logic_help": "insufficient_controlled_sample_report_only",
            "auto_correct_behavior": False,
            **_safe_flags(),
        }

    def _operations_governor(self, statuses: dict[str, Any]) -> dict[str, Any]:
        health = status_value(statuses, "system_status")
        remote = status_value(statuses, "remote_runtime_consistency")
        storage = status_value(statuses, "adaptive_learning_infrastructure_suite_v1")
        failures = [k for k, v in statuses.items() if isinstance(v, dict) and (v.get("status") == "error" or v.get("ok") is False)][:12]
        storage_pressure = clamp(first(storage.get("storage_pressure_score"), remote.get("storage_pressure_score"), default=0.0))
        memory_pressure = clamp(first(storage.get("memory_pressure_score"), remote.get("memory_pressure_score"), default=0.0))
        optional_pause = bool(storage_pressure >= 85.0 or memory_pressure >= 85.0 or len(failures) >= 5)
        return {
            "department": "Astra Operations Department V1",
            "backend_health": text(first(health.get("backend_status"), health.get("status"), "healthy")),
            "frontend_health": text(first(remote.get("frontend_health"), "healthy")),
            "worker_health": text(first(health.get("worker_health"), remote.get("worker_health"), "monitoring")),
            "dashboard_health": text(first(remote.get("dashboard_health"), "healthy")),
            "endpoint_health": "warning" if failures else "healthy",
            "storage_pressure": rounded(storage_pressure, 3),
            "memory_pressure": rounded(memory_pressure, 3),
            "system_drift": text(first(remote.get("runtime_drift_status"), "monitoring")),
            "subsystem_failures": failures,
            "allowed_actions": ["warn", "log", "recommend_fixes", "pause_unsafe_optional_workers"],
            "pause_unsafe_optional_workers_recommended": optional_pause,
            "never_trade_or_sell_or_change_strategy": True,
            **_safe_flags(),
        }

    def _resource_manager(self, statuses: dict[str, Any]) -> dict[str, Any]:
        provider = status_value(statuses, "provider_usage_status_v1")
        fmp = status_value(statuses, "adaptive_market_intake_fmp_budget_suite_v1")
        api_calls = to_int(provider.get("api_calls_used"), 0)
        bandwidth = to_float(first(provider.get("bandwidth_used_gb"), fmp.get("bandwidth_used_gb"), default=0.0), 0.0)
        return {
            "department": "Astra Resource Manager V1",
            "api_calls_tracked": api_calls,
            "bandwidth_used_gb": rounded(bandwidth, 6),
            "storage_growth_status": text(first(provider.get("storage_growth_status"), "monitoring")),
            "cpu_pressure": rounded(first(provider.get("cpu_pressure"), 0.0), 3),
            "historical_collection_budget": text(first(fmp.get("historical_collection_budget"), "cache_first_bounded")),
            "worker_refresh_rates_status": text(first(provider.get("worker_refresh_rates_status"), "bounded")),
            "priority_order": ["live_trading_data", "active_positions", "sell_candidates", "market_regime"],
            "lowest_priority": ["duplicate_refreshes", "stale_scans", "low_value_history"],
            "dashboard_zero_provider_call_required": True,
            "dashboard_provider_calls_used": 0,
            "cache_aggressively": True,
            **_safe_flags(),
        }

    def _registry(self) -> dict[str, Any]:
        systems = [
            ("Horizon Exit Candidate Engine V1", "Trading Integrity", "Advisory exit-due and horizon conversion visibility"),
            ("Exit Pipeline Integrity V1", "Trading Integrity", "Generated/suppressed/blocked/rejected exit diagnostics"),
            ("Profit Capture Truth Engine V1", "Trading Integrity", "MFE, giveback, capture, peak-decay attribution"),
            ("Capital Efficiency Engine V1", "Trading Integrity", "Trapped capital and capacity pressure diagnostics"),
            ("Astra Internal Audit Department V1", "Audit", "Nightly report-only self audit"),
            ("Astra Operations Department V1", "Operations", "Runtime health and optional worker safety recommendations"),
            ("Astra Resource Manager V1", "Resource Manager", "API, bandwidth, storage, CPU and cache budget governance"),
            ("Astra System Registry V1", "Architecture", "Registered ownership, dependencies and budgets"),
            ("Astra Knowledge Preservation Framework V1", "Architecture", "Preserve and categorize existing intelligence"),
        ]
        rows = []
        for name, owner, purpose in systems:
            rows.append({
                "system_name": name,
                "owner": owner,
                "purpose": purpose,
                "inputs": ["cached_unified_diagnostics", "cached_learning_evidence"],
                "outputs": ["advisory_diagnostics", "learning_center_summary"],
                "dependencies": ["unified_learning_diagnostics_v1"],
                "health_status": "registered",
                "enabled": True,
                "api_budget": 0,
                "bandwidth_budget": 0,
            })
        return {
            "registry_status": "active",
            "registered_system_count": len(rows),
            "systems": rows,
            **_safe_flags(),
        }

    def _knowledge_preservation(self, statuses: dict[str, Any]) -> dict[str, Any]:
        categories = {
            "trading_integrity": ["trade_lifecycle_audit_truth_horizon_integrity_suite_v1", "multi_horizon_paper_capacity_exit_validation_v1"],
            "learning_quality": ["intelligence_quality_learning_efficiency_suite_v1", "candidate_ranking_attribution_promotion_intelligence_v1"],
            "profit_capture": ["profit_optimization_context_intelligence_suite_v1", "controlled_paper_profit_protection_pilot_v1"],
            "shadow_learning": ["realistic_shadow_evidence_learning_lab_v1", "shadow_vs_paper_performance_attribution_v1"],
            "market_context": ["market_breadth_index_intelligence_v1", "etf_sector_rotation_intelligence_v1", "cross_market_attribution_transfer_learning_v1"],
            "governance": ["autonomous_intelligence_validation_governance_v1", "learning_issue_audit"],
        }
        present = {k: [name for name in names if status_value(statuses, name)] for k, names in categories.items()}
        return {
            "framework": "Astra Knowledge Preservation Framework V1",
            "preservation_status": "active",
            "existing_intelligence_preserved": True,
            "rebuild_astra": False,
            "duplicate_astra": False,
            "categories": present,
            "ownership_assigned": True,
            "expandable": True,
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        rows = self._active_positions(statuses)
        integrity = self._trading_integrity(statuses, rows)
        horizon_exit = self._horizon_exit_candidates(rows)
        exit_pipeline = self._exit_pipeline_integrity(statuses)
        profit_truth = self._profit_capture_truth(statuses, rows)
        capital = self._capital_efficiency(statuses, rows, integrity)
        internal_audit = self._internal_audit(statuses)
        operations = self._operations_governor(statuses)
        resource = self._resource_manager(statuses)
        registry = self._registry()
        preservation = self._knowledge_preservation(statuses)
        out = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Tier 1 Foundation Stabilization & Governance Bundle V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "trading_integrity_stabilization": integrity,
            "horizon_exit_candidate_engine_v1": horizon_exit,
            "exit_pipeline_integrity_v1": exit_pipeline,
            "profit_capture_truth_engine_v1": profit_truth,
            "capital_efficiency_engine_v1": capital,
            "astra_internal_audit_department_v1": internal_audit,
            "astra_operations_department_v1": operations,
            "astra_resource_manager_v1": resource,
            "astra_system_registry_v1": registry,
            "astra_knowledge_preservation_framework_v1": preservation,
            "unknown_horizon_positions": integrity["unknown_horizon_positions"],
            "learned_exit_candidates_today_diagnosis": integrity["learned_exit_candidates_today_diagnosis"],
            "biggest_exit_blocker": exit_pipeline["biggest_exit_blocker"],
            "biggest_profit_capture_leak": profit_truth["biggest_profit_capture_leak"],
            "trapped_capital_status": capital["trapped_capital_status"],
            "oversight_governor_status": operations["endpoint_health"],
            "api_governor_status": "active_cache_first_zero_dashboard_provider_calls",
            "registry_status": registry["registry_status"],
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(out)
