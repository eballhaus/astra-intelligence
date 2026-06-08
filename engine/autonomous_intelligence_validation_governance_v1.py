from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
DASHBOARD_CACHE_MAX_AGE_SECONDS = 180.0

POLICIES = (
    "confidence_weighted_sizing",
    "horizon_specific_exits",
    "continuation_failure_exits",
    "profit_lock_exits",
    "catalyst_aware_holding",
    "opportunity_cost_threshold_adjustments",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        return


def _freshness_label(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "stale"
    if age_seconds <= 120:
        return "live"
    if age_seconds <= 900:
        return "fresh"
    if age_seconds <= 3600:
        return "warm"
    return "stale"


class AutonomousIntelligenceValidationGovernanceV1:
    """Shadow-only truth validation, self-healing diagnostics, and governance oversight."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "autonomous_intelligence_validation_governance_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _s(self, statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        return dict(statuses.get(key) or {})

    def _evidence_quality(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        lifecycle = self._s(statuses, "trade_lifecycle_excursion_v2")
        replay = self._s(statuses, "replay_counterfactual_learning_v2")
        opportunity = self._s(statuses, "opportunity_cost_learning")
        confidence = self._s(statuses, "confidence_calibration_performance_attribution_v1")
        catalyst = self._s(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        memory = self._s(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        full = self._s(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        decision = self._s(statuses, "decision_optimization_trade_management_suite_v1")
        peak_decay = self._s(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        convergence = self._s(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        accelerated_symbol = self._s(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        shadow_lab = self._s(statuses, "realistic_shadow_evidence_learning_lab_v1")
        allocator = self._s(statuses, "adaptive_learning_prioritization_resource_allocation_v1")
        accel = self._s(statuses, "learning_acceleration_retention_suite_v1")

        counts = [
            _to_float(lifecycle.get("tracked_active_trades"), 0) + _to_float(lifecycle.get("tracked_closed_trades"), 0),
            _to_float(replay.get("tracked_lifecycles"), 0),
            _to_float(opportunity.get("rejected_candidates_reviewed"), 0) + _to_float(opportunity.get("selected_candidates_reviewed"), 0),
            _to_float(confidence.get("evidence_count"), 0),
            _to_float(catalyst.get("evidence_count"), 0),
            _to_float(memory.get("indexed_records"), 0),
            _to_float(full.get("opportunities_tracked"), 0),
            _to_float(decision.get("evidence_count"), 0),
            _to_float(peak_decay.get("tracked_trades"), 0),
            _to_float(convergence.get("tracked_trades"), 0),
            _to_float(accelerated_symbol.get("accelerated_learning_events"), 0),
            _to_float(shadow_lab.get("shadow_learning_events"), 0),
        ]
        evidence_count = int(sum(counts))
        sample_quality = _clamp(evidence_count / 1200.0 * 100.0)
        consistency_inputs = [
            _to_float(accel.get("agreement_score"), 55),
            _to_float(full.get("cross_system_learning_score"), 50),
            _to_float(peak_decay.get("capture_quality_score"), 55),
            _to_float(convergence.get("convergence_quality_score"), 55),
            _to_float(accelerated_symbol.get("symbol_personality_quality_score"), 55),
            _to_float(accelerated_symbol.get("peer_group_learning_score"), 55),
            _to_float(shadow_lab.get("average_shadow_realism_score"), 55),
            _to_float(shadow_lab.get("consensus_confidence_score"), 55),
            100 - _to_float(allocator.get("weakness_confidence"), 0) * 0.15,
        ]
        evidence_consistency = _clamp(_avg(consistency_inputs) or 50.0)
        conflict = _clamp(_to_float(accel.get("conflict_severity"), 0) or (100 - evidence_consistency) * 0.55)
        outlier = _clamp(abs(_to_float(opportunity.get("average_opportunity_cost"), 0)) * 0.35 + _to_float(decision.get("highest_opportunity_cost"), 0) * 0.25)
        regime_contamination = _clamp(100 - _to_float(self._s(statuses, "trade_archetype_regime").get("current_archetype_regime_alignment_score"), 55))
        recency = _clamp(100 - (25 if _text(memory.get("cache_freshness"), "fresh") == "stale" else 0) - (15 if _text(full.get("cache_freshness"), "fresh") == "stale" else 0))
        reliability = _clamp(sample_quality * 0.28 + evidence_consistency * 0.30 + recency * 0.20 + (100 - conflict) * 0.12 + (100 - outlier) * 0.10)
        truth = _clamp(reliability * 0.72 + (100 - regime_contamination) * 0.13 + (100 - outlier) * 0.15)
        lessons = [
            ("profit_capture_is_current_high_value_learning_focus", _to_float(allocator.get("learning_roi_score"), 0)),
            ("symbol_memory_indexes_are_healthy", _to_float(memory.get("retrieval_health_score"), 0)),
            ("full_opportunity_lifecycle_has_high_completeness", _to_float(full.get("learning_completeness_score"), 0)),
            ("confidence_truth_requires_more_validation", 100 - _to_float(decision.get("confidence_truth_score"), 50)),
            ("catalyst_decay_needs_context_validation", 100 - _to_float(catalyst.get("catalyst_decay_learning_score"), 50)),
            ("profit_capture_peak_decay_exit_validation_is_shadow_validated", _to_float(peak_decay.get("capture_quality_score"), 0)),
            ("virtual_to_paper_convergence_gap_is_explained", _to_float(convergence.get("gap_attribution_score"), 0)),
            ("accelerated_symbol_peer_learning_is_available", _to_float(accelerated_symbol.get("replay_acceleration_score"), 0)),
            ("realistic_shadow_lab_is_budget_safe", 100 - _to_float(shadow_lab.get("bandwidth_pressure_score"), 0)),
        ]
        trusted = [name for name, score in lessons if score >= 65]
        questionable = [name for name, score in lessons if score < 50]
        strongest = max(lessons, key=lambda x: x[1], default=("insufficient_data", 0))[0]
        weakest = min(lessons, key=lambda x: x[1], default=("insufficient_data", 0))[0]
        return {
            "evidence_count": evidence_count,
            "sample_size_quality": _round(sample_quality, 2),
            "evidence_consistency": _round(evidence_consistency, 2),
            "conflicting_evidence_score": _round(conflict, 2),
            "outlier_risk_score": _round(outlier, 2),
            "regime_contamination_score": _round(regime_contamination, 2),
            "recency_relevance_score": _round(recency, 2),
            "lesson_reliability_score": _round(reliability, 2),
            "truth_validation_score": _round(truth, 2),
            "trusted_lessons": trusted,
            "questionable_lessons": questionable,
            "strongest_validated_lesson": strongest,
            "weakest_validated_lesson": weakest,
            "truth_validation_status": "validated_shadow_learning" if truth >= 70 else "needs_more_evidence" if truth >= 45 else "weak_or_noisy_evidence",
        }

    def _self_healing(self, statuses: dict[str, dict[str, Any]], truth: dict[str, Any]) -> dict[str, Any]:
        allocator = self._s(statuses, "adaptive_learning_prioritization_resource_allocation_v1")
        decision = self._s(statuses, "decision_optimization_trade_management_suite_v1")
        memory = self._s(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        top = _text(allocator.get("top_weakness"), "profit_capture")
        root_map = {
            "profit_capture": "winners_give_back_peak_profit_before_natural_exit",
            "giveback": "profit_decay_after_mfe_not_yet_policy_actionable",
            "hold_duration": "horizon_hold_windows_need_more_counterfactual_validation",
            "continuation_quality": "continuation_failure_signals_are_incomplete_or_late",
            "profit_capture_peak_decay_exit_validation": "profit_capture_peak_decay_and_exit_policies_need_horizon_validation",
            "virtual_paper_convergence": "paper_results_lag_best_virtual_paths_due_to_attributed_gap_drivers",
            "accelerated_symbol_intelligence": "symbol_peer_horizon_exit_and_drift_patterns_need_more_cached_validation",
            "realistic_shadow_lab": "shadow_evidence_realism_provider_freshness_or_consensus_quality_needs_validation",
            "catalyst_decay": "catalyst_half_life_and_context_persistence_need_more_evidence",
            "opportunity_cost": "rejected_candidate_outcomes_outperform_selected_candidates_in_some_contexts",
            "confidence_truth": "confidence_scores_not_yet_monotonic_enough_for_policy_use",
            "horizon_classification": "horizon_labels_have_insufficient_truth_backtesting",
            "symbol_memory": "symbol_profiles_need_more_repeated_behavior_samples",
            "storage_health": "memory_pressure_or_cache_retention_needs_attention",
            "retrieval_health": "knowledge_indexes_need_more_complete_key_coverage",
            "worker_health": "worker_queue_or_runtime_efficiency_requires monitoring",
            "API_budget": "budget_guardrails_require_preserving_cached_only_paths",
        }
        hypothesis_map = {
            "profit_capture": "shadow_test_profit_lock_and_peak_decay_exits_by_horizon",
            "giveback": "shadow_test_giveback_thresholds_without_order_actions",
            "hold_duration": "shadow_test_fixed_hold_windows_by_archetype_and_horizon",
            "continuation_quality": "shadow_test_continuation_failure_exit_timing",
            "catalyst_decay": "shadow_test_catalyst_decay_hold_duration_curves",
            "opportunity_cost": "shadow_test_rejected_candidate_replay_and_selection_threshold_explanations",
            "confidence_truth": "shadow_test_confidence_bucket_monotonicity_before_sizing",
            "horizon_classification": "shadow_test_horizon_label_truth_by_symbol_and_context",
            "symbol_memory": "shadow_prioritize_symbol_profiles_for_repeatedly_seen_symbols",
            "profit_capture_peak_decay_exit_validation": "shadow_test_profit_capture_peak_decay_exit_validation_by_horizon",
            "virtual_paper_convergence": "shadow_test_virtual_to_paper_gap_reduction_by_symbol_horizon_and_exit_style",
            "accelerated_symbol_intelligence": "shadow_test_symbol_peer_group_transfer_learning_and_drift_validation",
            "realistic_shadow_lab": "shadow_test_realistic_virtual_paths_with_no_broker_orders",
        }
        systems = ["adaptive_learning_prioritization", "decision_optimization", "replay_counterfactual", "full_opportunity_lifecycle", "profit_capture_peak_decay_exit_validation", "virtual_paper_convergence_symbol_attribution", "accelerated_learning_symbol_intelligence", "realistic_shadow_evidence_learning_lab"]
        if top in {"symbol_memory", "retrieval_health", "storage_health"}:
            systems.append("long_term_memory_symbol_retrieval")
        expected_gain = _clamp(_to_float(allocator.get("expected_improvement_score"), 0) * 0.75 + _to_float(decision.get("trade_management_intelligence_score"), 0) * 0.15)
        confidence = _clamp((_to_float(truth.get("truth_validation_score"), 0) * 0.55) + (_to_float(allocator.get("weakness_confidence"), 0) * 0.45))
        return {
            "root_cause_map": {top: root_map.get(top, "insufficient_cross_system_evidence")},
            "top_root_cause": root_map.get(top, "insufficient_cross_system_evidence"),
            "likely_contributing_systems": systems,
            "improvement_hypothesis": hypothesis_map.get(top, f"shadow_test_more_evidence_for_{top}"),
            "highest_value_hypothesis": hypothesis_map.get(top, f"shadow_test_more_evidence_for_{top}"),
            "expected_gain": _round(expected_gain, 2),
            "confidence": _round(confidence, 2),
            "virtual_test_recommended": True,
            "recommended_virtual_test": hypothesis_map.get(top, f"shadow_test_more_evidence_for_{top}"),
            "human_review_required": True,
            "self_healing_status": "diagnostic_ready_no_autonomous_repair",
            "autonomous_repair_readiness": "not_ready_shadow_only",
            "memory_context": _text(memory.get("strongest_symbol_profile"), "insufficient_data"),
        }

    def _governance(self, statuses: dict[str, dict[str, Any]], truth: dict[str, Any]) -> dict[str, Any]:
        memory = self._s(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        worker = self._s(statuses, "adaptive_worker_activation_orchestration_v1")
        allocator = self._s(statuses, "adaptive_learning_prioritization_resource_allocation_v1")
        full = self._s(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        risks = {
            "trading_safety": 0.0,
            "learning_safety": max(0.0, 100 - _to_float(truth.get("truth_validation_score"), 50)),
            "storage_safety": max(0.0, 100 - _to_float(memory.get("storage_health_score"), 100)),
            "performance_safety": _to_float(full.get("dashboard_scan_rows"), 0) * 2.0 + _to_float(memory.get("dashboard_scan_rows"), 0) * 2.0,
            "api_safety": _to_float(allocator.get("api_calls_used"), 0) + _to_float(worker.get("api_calls_used"), 0),
            "infrastructure_safety": max(0.0, 100 - _to_float(worker.get("worker_efficiency_score"), 75)),
            "knowledge_safety": max(0.0, 100 - _to_float(memory.get("retrieval_health_score"), 80)),
        }
        primary = max(risks.items(), key=lambda kv: kv[1], default=("none", 0))[0]
        secondary = sorted(risks.items(), key=lambda kv: kv[1], reverse=True)[1][0] if len(risks) > 1 else "none"
        risk_score = _clamp(max(risks.values()) if risks else 0.0)
        governance_score = _clamp(100 - risk_score * 0.62 - _to_float(truth.get("conflicting_evidence_score"), 0) * 0.18)
        warning = "green" if governance_score >= 80 else "yellow" if governance_score >= 65 else "orange" if governance_score >= 45 else "red"
        def status(key: str) -> str:
            val = risks.get(key, 0.0)
            return "green" if val < 20 else "yellow" if val < 40 else "orange" if val < 65 else "red"
        return {
            "governance_score": _round(governance_score, 2),
            "warning_level": warning,
            "primary_risk": primary,
            "secondary_risk": secondary,
            "trading_safety_status": "green",
            "learning_safety_status": status("learning_safety"),
            "storage_safety_status": status("storage_safety"),
            "performance_safety_status": status("performance_safety"),
            "api_safety_status": status("api_safety"),
            "infrastructure_safety_status": status("infrastructure_safety"),
            "knowledge_safety_status": status("knowledge_safety"),
            "governance_recommendation": "continue_shadow_only_learning_validation" if warning in {"green", "yellow"} else "pause_policy_consideration_and_review_governance_risks",
        }

    def _policy_readiness(self, statuses: dict[str, dict[str, Any]], truth: dict[str, Any], gov: dict[str, Any]) -> dict[str, Any]:
        decision = self._s(statuses, "decision_optimization_trade_management_suite_v1")
        confidence = self._s(statuses, "confidence_calibration_performance_attribution_v1")
        allocator = self._s(statuses, "adaptive_learning_prioritization_resource_allocation_v1")
        replay = self._s(statuses, "replay_counterfactual_learning_v2")
        base = _to_float(truth.get("truth_validation_score"), 0)
        gov_ok = 1.0 if _text(gov.get("warning_level"), "red") in {"green", "yellow"} else 0.55
        scores = {
            "confidence_weighted_sizing": min(base, _to_float(confidence.get("sizing_readiness_score"), 0)) * gov_ok,
            "horizon_specific_exits": min(base, _to_float(decision.get("sizing_readiness_score"), 0) + 5) * gov_ok,
            "continuation_failure_exits": min(base, 100 - _to_float(decision.get("continuation_failure_probability"), 100) + 20) * gov_ok,
            "profit_lock_exits": min(base, _to_float(allocator.get("expected_improvement_score"), 0)) * gov_ok,
            "catalyst_aware_holding": min(base, 100 - _to_float(self._s(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2").get("unknown_catalyst_rate"), 100)) * gov_ok,
            "opportunity_cost_threshold_adjustments": min(base, _to_float(replay.get("replay_learning_score"), 0) + 10) * gov_ok,
        }
        ready = [k for k, v in scores.items() if v >= 85 and base >= 80 and gov.get("warning_level") == "green"]
        not_ready = [k for k in POLICIES if k not in ready]
        closest = max(scores.items(), key=lambda kv: kv[1], default=("insufficient_data", 0))[0]
        blocker = "human_review_required_and_shadow_only" if scores.get(closest, 0) >= 70 else "insufficient_truth_validation_or_consistency"
        return {
            "ready_policies": ready,
            "not_ready_policies": not_ready,
            "closest_policy_to_readiness": closest,
            "readiness_blocker": blocker,
            "policy_readiness_score": _round(max(scores.values()) if scores else 0, 2),
            "policy_readiness_scores": {k: _round(v, 2) for k, v in scores.items()},
            "policies_applied": [],
        }

    def _cached(self) -> dict[str, Any] | None:
        payload = _read_json(self.cache_path)
        if not payload:
            return None
        try:
            age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
        except Exception:
            age = None
        payload["cache_hit"] = True
        payload["cache_age_seconds"] = round(age, 3) if age is not None else None
        payload["cache_freshness"] = _freshness_label(age)
        payload["api_calls_used"] = 0
        payload["provider_calls_used"] = 0
        payload["llm_calls_used"] = 0
        payload["behavior_safe_to_apply"] = False
        return payload

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        truth = self._evidence_quality(statuses)
        healing = self._self_healing(statuses, truth)
        gov = self._governance(statuses, truth)
        policy = self._policy_readiness(statuses, truth, gov)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_autonomous_intelligence_validation_governance",
            "generated_at": _now_iso(),
            **truth,
            **healing,
            **gov,
            **policy,
            "shadow_recommendation": f"shadow_only_run_{healing.get('recommended_virtual_test')}_and_keep_all_policies_not_applied",
            "summary": "Astra is validating lesson truth, diagnosing weaknesses, proposing virtual tests, and monitoring governance without changing trading behavior.",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "bandwidth_saving_mode": True,
            "cache_status": "rebuilt",
            "cache_freshness": "live",
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "portfolio_allocation_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "auto_apply_allowed": False,
            "human_review_required": True,
            "behavior_safe_to_apply": False,
        }
        out["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
        _write_json(self.cache_path, out)
        return out

    def status(self, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache and now - self._cache_ts < self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["behavior_safe_to_apply"] = False
            return out
        if not force:
            cached = self._cached()
            if cached and _to_float(cached.get("cache_age_seconds"), 999999.0) <= DASHBOARD_CACHE_MAX_AGE_SECONDS:
                self._cache = cached
                self._cache_ts = now
                return cached
        try:
            out = self._build(statuses or {})
            out["cache_hit"] = False
            self._cache = out
            self._cache_ts = now
            return out
        except Exception as exc:
            cached = self._cached()
            if cached:
                cached["stale_cache"] = True
                cached["degraded_reason"] = f"autonomous_intelligence_validation_governance_rebuild_failed_using_cache:{str(exc)[:140]}"
                cached["behavior_safe_to_apply"] = False
                return cached
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_autonomous_intelligence_validation_governance",
                "evidence_count": 0,
                "truth_validation_score": 0.0,
                "lesson_reliability_score": 0.0,
                "strongest_validated_lesson": "unavailable",
                "weakest_validated_lesson": "unavailable",
                "top_root_cause": "unavailable",
                "highest_value_hypothesis": "unavailable",
                "recommended_virtual_test": "unavailable",
                "governance_score": 0.0,
                "warning_level": "red",
                "primary_risk": "unavailable",
                "secondary_risk": "unavailable",
                "policy_readiness_score": 0.0,
                "closest_policy_to_readiness": "unavailable",
                "readiness_blocker": "unavailable",
                "trading_safety_status": "green",
                "learning_safety_status": "red",
                "storage_safety_status": "red",
                "performance_safety_status": "red",
                "api_safety_status": "green",
                "infrastructure_safety_status": "red",
                "knowledge_safety_status": "red",
                "degraded_reason": f"autonomous_intelligence_validation_governance_v1_unavailable:{str(exc)[:140]}",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "build_ms": 0.0,
                "shadow_recommendation": "unavailable",
                "behavior_safe_to_apply": False,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "ranking_behavior_changed": False,
                "paper_execution_behavior_changed": False,
                "position_sizing_changed": False,
                "thresholds_changed": False,
                "portfolio_allocation_changed": False,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
                "auto_apply_allowed": False,
                "human_review_required": True,
            }
