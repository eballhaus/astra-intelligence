from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
DASHBOARD_CACHE_MAX_AGE_SECONDS = 180.0

WEAKNESSES = (
    "profit_capture", "giveback", "hold_duration", "continuation_quality", "opportunity_cost",
    "missed_winners", "confidence_truth", "catalyst_decay", "after_hours_profile", "premarket_profile",
    "symbol_memory", "rejection_accuracy", "horizon_classification", "entry_quality", "exit_quality",
    "profit_capture_peak_decay_validation", "virtual_paper_convergence", "accelerated_symbol_intelligence", "realistic_shadow_lab", "portfolio_concentration", "correlation_risk", "storage_health", "retrieval_health", "worker_health",
    "API_budget", "evidence_quality", "evidence_gap",
)

WEAKNESS_TO_WORKER = {
    "profit_capture": "open_trade_profit_capture_worker",
    "giveback": "open_trade_profit_decay_worker",
    "hold_duration": "replay_hold_duration_worker",
    "continuation_quality": "continuation_failure_worker",
    "opportunity_cost": "rejected_candidate_replay_worker",
    "missed_winners": "rejected_candidate_learning_worker",
    "confidence_truth": "confidence_calibration_worker",
    "catalyst_decay": "market_context_catalyst_decay_worker",
    "after_hours_profile": "after_hours_context_worker",
    "premarket_profile": "premarket_context_worker",
    "symbol_memory": "symbol_memory_index_worker",
    "rejection_accuracy": "rejected_candidate_learning_worker",
    "horizon_classification": "horizon_classification_worker",
    "entry_quality": "entry_quality_review_worker",
    "exit_quality": "exit_learning_worker",
    "profit_capture_peak_decay_validation": "profit_capture_peak_decay_exit_validation_worker",
    "virtual_paper_convergence": "virtual_to_paper_gap_attribution_worker",
    "accelerated_symbol_intelligence": "accelerated_symbol_peer_learning_worker",
    "realistic_shadow_lab": "realistic_shadow_evidence_lab_worker",
    "portfolio_concentration": "portfolio_risk_monitor_worker",
    "correlation_risk": "portfolio_correlation_monitor_worker",
    "storage_health": "memory_retention_worker",
    "retrieval_health": "knowledge_retrieval_index_worker",
    "worker_health": "worker_health_monitor",
    "API_budget": "api_budget_monitor",
    "evidence_quality": "evidence_quality_worker",
    "evidence_gap": "coverage_gap_worker",
}

WEAKNESS_TO_REPLAY = {
    "profit_capture": "profit_lock_and_peak_decay_counterfactuals",
    "giveback": "giveback_threshold_and_trailing_profit_counterfactuals",
    "hold_duration": "fixed_hold_duration_and_horizon_counterfactuals",
    "continuation_quality": "continuation_failure_exit_counterfactuals",
    "opportunity_cost": "rejected_candidate_and_missed_winner_replay",
    "missed_winners": "missed_winner_replay_and_selection_review",
    "confidence_truth": "confidence_bucket_outcome_replay",
    "catalyst_decay": "catalyst_hold_duration_decay_curves",
    "horizon_classification": "horizon_specific_return_replay",
    "exit_quality": "exit_timing_efficiency_counterfactuals",
    "profit_capture_peak_decay_validation": "profit_capture_peak_decay_exit_validation_counterfactuals",
    "virtual_paper_convergence": "virtual_to_paper_gap_replay_by_symbol_horizon_exit_style",
    "accelerated_symbol_intelligence": "symbol_peer_horizon_exit_drift_replay",
    "realistic_shadow_lab": "realistic_shadow_policy_tournament_replay",
}


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


class AdaptiveLearningPrioritizationResourceAllocationV1:
    """Shadow-only learning priority, resource allocation, and governance diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "adaptive_learning_prioritization_resource_allocation_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _status(self, statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        return dict(statuses.get(key) or {})

    def _collect_weakness_signals(self, statuses: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        signals: dict[str, list[tuple[float, str, float]]] = defaultdict(list)

        def add(name: str, score: Any, source: str, evidence: Any = 0) -> None:
            val = _clamp(score)
            signals[name].append((val, source, _to_float(evidence, 0.0)))

        profit = self._status(statuses, "adaptive_profit_capture")
        v3 = self._status(statuses, "adaptive_execution_exit_intelligence_v3")
        exit_expansion = self._status(statuses, "exit_learning_expansion_suite_v1")
        decision = self._status(statuses, "decision_optimization_trade_management_suite_v1")
        full = self._status(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        confidence = self._status(statuses, "confidence_calibration_performance_attribution_v1")
        context = self._status(statuses, "context_evidence_expansion_suite_v1")
        catalyst = self._status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        memory = self._status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        worker = self._status(statuses, "adaptive_worker_activation_orchestration_v1")
        acceleration = self._status(statuses, "learning_acceleration_retention_suite_v1")
        lifecycle_v2 = self._status(statuses, "trade_lifecycle_excursion_v2")
        opportunity = self._status(statuses, "opportunity_cost_learning")
        replay = self._status(statuses, "replay_counterfactual_learning_v2")
        peak_decay = self._status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        convergence = self._status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        accelerated_symbol = self._status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        shadow_lab = self._status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        portfolio = self._status(statuses, "portfolio_diversification_correlation_v2")
        issue = self._status(statuses, "learning_issue_audit")

        add("profit_capture", 100 - _to_float(profit.get("average_profit_capture_ratio"), 50.0), "adaptive_profit_capture", profit.get("tracked_lifecycles"))
        add("profit_capture", _to_float(v3.get("protect_profit_score"), 0.0), "adaptive_execution_exit_v3", v3.get("tracked_trades"))
        add("giveback", _to_float(profit.get("average_profit_giveback_pct"), 0.0) * 2.4, "adaptive_profit_capture", profit.get("tracked_lifecycles"))
        add("giveback", _to_float(exit_expansion.get("protect_profit_score"), 0.0), "exit_learning_expansion", exit_expansion.get("tracked_trades"))
        add("hold_duration", 100 - _to_float(exit_expansion.get("hold_longer_score"), 50.0), "exit_learning_expansion", exit_expansion.get("tracked_trades"))
        add("profit_capture_peak_decay_validation", 100 - _to_float(peak_decay.get("capture_quality_score"), 50.0), "profit_capture_peak_decay_exit_validation", peak_decay.get("tracked_trades"))
        add("profit_capture_peak_decay_validation", 100 - _to_float(peak_decay.get("hold_duration_quality_score"), 50.0), "profit_capture_peak_decay_exit_validation", peak_decay.get("tracked_trades"))
        add("profit_capture_peak_decay_validation", _to_float(peak_decay.get("continuation_failure_probability"), 0.0), "profit_capture_peak_decay_exit_validation", peak_decay.get("tracked_trades"))
        add("virtual_paper_convergence", abs(_to_float(convergence.get("average_convergence_gap"), 0.0)) * 4.0, "virtual_paper_convergence_symbol_attribution", convergence.get("tracked_trades"))
        add("virtual_paper_convergence", 100 - _to_float(convergence.get("convergence_quality_score"), 50.0), "virtual_paper_convergence_symbol_attribution", convergence.get("tracked_trades"))
        add("virtual_paper_convergence", 100 - _to_float(convergence.get("gap_attribution_score"), 50.0), "virtual_paper_convergence_symbol_attribution", convergence.get("tracked_trades"))
        add("accelerated_symbol_intelligence", 100 - _to_float(accelerated_symbol.get("replay_acceleration_score"), 50.0), "accelerated_symbol_intelligence", accelerated_symbol.get("accelerated_learning_events"))
        add("accelerated_symbol_intelligence", 100 - _to_float(accelerated_symbol.get("symbol_personality_quality_score"), 50.0), "accelerated_symbol_intelligence", accelerated_symbol.get("symbol_profiles_tracked"))
        add("accelerated_symbol_intelligence", _to_float(accelerated_symbol.get("drift_score"), 0.0), "accelerated_symbol_intelligence", accelerated_symbol.get("indexed_learning_records"))
        add("realistic_shadow_lab", 100 - _to_float(shadow_lab.get("average_shadow_realism_score"), 55.0), "realistic_shadow_lab", shadow_lab.get("shadow_learning_events"))
        add("realistic_shadow_lab", 100 - _to_float(shadow_lab.get("evidence_quality_score"), 55.0), "realistic_shadow_lab", shadow_lab.get("shadow_learning_events"))
        add("realistic_shadow_lab", _to_float(shadow_lab.get("bandwidth_pressure_score"), 0.0), "realistic_shadow_lab", shadow_lab.get("shadow_learning_events"))
        if _text(shadow_lab.get("provider_warning"), "none") not in {"none", ""}:
            add("realistic_shadow_lab", 65.0, "realistic_shadow_lab_provider_warning", shadow_lab.get("shadow_learning_events"))
        add("continuation_quality", 100 - _to_float(decision.get("continuation_quality_score"), 50.0), "decision_optimization", decision.get("tracked_trades"))
        add("opportunity_cost", _to_float(decision.get("highest_opportunity_cost"), 0.0), "decision_optimization", decision.get("opportunity_rows_reviewed"))
        add("opportunity_cost", abs(_to_float(opportunity.get("average_opportunity_cost"), 0.0)), "opportunity_cost_learning", opportunity.get("rejected_candidates_reviewed"))
        add("missed_winners", _to_float(decision.get("missed_winner_rate"), 0.0), "decision_optimization", decision.get("opportunity_rows_reviewed"))
        add("missed_winners", min(100.0, _to_float(full.get("missed_winners"), 0.0) / max(1, _to_float(full.get("opportunities_tracked"), 1)) * 100.0), "full_opportunity_lifecycle", full.get("opportunities_tracked"))
        add("confidence_truth", 100 - _to_float(decision.get("confidence_truth_score"), 50.0), "decision_optimization", decision.get("tracked_trades"))
        add("confidence_truth", 100 - _to_float(confidence.get("confidence_predictive_power"), 50.0), "confidence_attribution", confidence.get("evidence_count"))
        add("catalyst_decay", 100 - _to_float(catalyst.get("catalyst_decay_learning_score"), 50.0), "catalyst_theme_v2", catalyst.get("evidence_count"))
        add("after_hours_profile", 100 - _to_float(context.get("after_hours_context_confidence"), 35.0), "context_evidence", context.get("evidence_count"))
        add("premarket_profile", 100 - _to_float(context.get("premarket_context_confidence"), 35.0), "context_evidence", context.get("evidence_count"))
        add("symbol_memory", 100 - _to_float(memory.get("symbol_memory_quality_score"), 50.0), "long_term_memory", memory.get("symbol_profiles_tracked"))
        add("rejection_accuracy", 100 - _to_float(decision.get("rejection_accuracy"), 50.0), "decision_optimization", decision.get("opportunity_rows_reviewed"))
        add("horizon_classification", 100 - _to_float(confidence.get("confidence_sizing_readiness"), 50.0), "confidence_attribution", confidence.get("evidence_count"))
        add("entry_quality", 100 - _to_float((issue.get("entry_quality_diagnostics") or {}).get("entry_quality_score"), 55.0), "learning_issue_audit", 1)
        add("exit_quality", 100 - _to_float((issue.get("exit_quality_diagnostics") or {}).get("exit_quality_score"), _to_float(lifecycle_v2.get("average_exit_quality"), 50.0)), "learning_issue_audit", lifecycle_v2.get("tracked_closed_trades"))
        add("portfolio_concentration", _to_float(portfolio.get("concentration_risk_score"), 40.0), "portfolio_diversification", 1)
        add("correlation_risk", _to_float(portfolio.get("correlation_risk_score"), 35.0), "portfolio_diversification", 1)
        add("storage_health", 100 - _to_float(memory.get("storage_health_score"), 100.0), "long_term_memory", memory.get("indexed_records"))
        add("retrieval_health", 100 - _to_float(memory.get("retrieval_health_score"), 100.0), "long_term_memory", memory.get("indexed_records"))
        add("worker_health", 100 - _to_float(worker.get("worker_efficiency_score"), 75.0), "worker_activation", worker.get("completed_jobs"))
        add("API_budget", 100 - _to_float(worker.get("api_budget_score"), 80.0), "worker_activation", worker.get("completed_jobs"))
        add("evidence_quality", 100 - _to_float(acceleration.get("weighted_confidence_score"), 60.0), "learning_acceleration", acceleration.get("evidence_count"))
        add("evidence_gap", _to_float(acceleration.get("evidence_gap_score"), 35.0), "learning_acceleration", acceleration.get("evidence_count"))
        add("evidence_gap", 100 - _to_float(full.get("learning_completeness_score"), 70.0), "full_opportunity_lifecycle", full.get("opportunities_tracked"))
        add("profit_capture", _to_float(replay.get("average_counterfactual_improvement"), 0.0) * 6.0, "replay_counterfactual", replay.get("tracked_lifecycles"))

        out: dict[str, dict[str, Any]] = {}
        for weakness in WEAKNESSES:
            rows = signals.get(weakness, [])
            if not rows:
                out[weakness] = {"weakness_score": 0.0, "sources": [], "evidence_count": 0.0, "source_count": 0}
                continue
            scores = [r[0] for r in rows]
            evidence = sum(r[2] for r in rows)
            out[weakness] = {
                "weakness_score": _round(_avg(scores) or 0.0, 2),
                "sources": [r[1] for r in rows],
                "evidence_count": _round(evidence, 2),
                "source_count": len(set(r[1] for r in rows)),
                "max_signal": _round(max(scores), 2),
                "min_signal": _round(min(scores), 2),
            }
        return out

    def _value_scores(self, weakness_signals: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        impact_weights = {
            "profit_capture": 1.0, "giveback": 0.95, "opportunity_cost": 0.95, "missed_winners": 0.9,
            "continuation_quality": 0.85, "confidence_truth": 0.75, "exit_quality": 0.82,
            "hold_duration": 0.78, "rejection_accuracy": 0.76, "catalyst_decay": 0.68,
            "profit_capture_peak_decay_validation": 0.98,
            "virtual_paper_convergence": 0.96,
            "accelerated_symbol_intelligence": 0.72,
            "realistic_shadow_lab": 0.70,
            "symbol_memory": 0.55, "horizon_classification": 0.62, "worker_health": 0.72,
            "storage_health": 0.88, "retrieval_health": 0.74, "API_budget": 0.82,
        }
        out: dict[str, dict[str, Any]] = {}
        for weakness, data in weakness_signals.items():
            weakness_score = _to_float(data.get("weakness_score"), 0.0)
            evidence = _to_float(data.get("evidence_count"), 0.0)
            source_count = _to_float(data.get("source_count"), 0.0)
            sample_conf = _clamp(min(70.0, evidence / 12.0) + min(30.0, source_count * 12.0))
            persistence = _clamp(source_count / 4.0 * 100.0)
            impact = _clamp(weakness_score * impact_weights.get(weakness, 0.55))
            evidence_gap = _clamp(100.0 - sample_conf)
            improvement = _clamp(impact * 0.55 + weakness_score * 0.30 + persistence * 0.15)
            urgency = _clamp(impact * 0.75 + max(0.0, weakness_score - 65.0) * 0.8)
            noise = _clamp((100.0 - sample_conf) * 0.65 + (100.0 - persistence) * 0.20)
            expected = _clamp((improvement * 0.45) + (impact * 0.28) + (urgency * 0.17) + (sample_conf * 0.10) - noise * 0.18)
            out[weakness] = {
                **data,
                "performance_impact_score": _round(impact, 2),
                "evidence_gap_score": _round(evidence_gap, 2),
                "improvement_potential_score": _round(improvement, 2),
                "urgency_score": _round(urgency, 2),
                "expected_learning_value": _round(expected, 2),
                "sample_size_confidence": _round(sample_conf, 2),
                "noise_risk_score": _round(noise, 2),
            }
        return out

    def _rankings(self, scored: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [{"weakness": k, **v} for k, v in scored.items()]
        rows.sort(key=lambda r: (_to_float(r.get("expected_learning_value")), _to_float(r.get("weakness_score"))), reverse=True)
        return rows

    def _allocation(self, rankings: list[dict[str, Any]]) -> dict[str, Any]:
        top = rankings[0] if rankings else {}
        confidence = _to_float(top.get("sample_size_confidence"), 0.0)
        noise = _to_float(top.get("noise_risk_score"), 100.0)
        top_weakness = _text(top.get("weakness"), "insufficient_data")
        if confidence < 40 or noise > 70:
            weakness_focus = 45.0
            balanced = 40.0
            reason = "low_confidence_or_noisy_top_weakness_kept_observation_only"
        else:
            weakness_focus = 60.0
            balanced = 25.0
            reason = "default_guardrailed_learning_allocation"
        strength = 10.0
        health = 5.0
        single_cap = min(40.0, weakness_focus)
        active_distribution = {top_weakness: single_cap} if top_weakness != "insufficient_data" else {}
        if weakness_focus > single_cap:
            active_distribution["other_ranked_weaknesses"] = _round(weakness_focus - single_cap, 2)
        allocation_conf = _round(max(0.0, min(confidence, 100.0 - noise * 0.35)), 2)
        guardrail_status = "passed"
        if weakness_focus > 70 or strength < 10 or health < 5 or max(active_distribution.values() or [0]) > 40:
            guardrail_status = "blocked_by_guardrails"
        return {
            "weakness_focus_allocation": weakness_focus,
            "balanced_learning_allocation": balanced,
            "strength_validation_allocation": strength,
            "system_health_allocation": health,
            "active_focus_distribution": active_distribution,
            "allocation_confidence": allocation_conf,
            "allocation_guardrail_status": guardrail_status,
            "allocation_reason": reason,
        }

    def _drift(self, rankings: list[dict[str, Any]]) -> dict[str, Any]:
        # V1 intentionally uses current cached summary only. Persistent drift history can be layered later.
        top = rankings[0] if rankings else {}
        second = rankings[1] if len(rankings) > 1 else {}
        top_name = _text(top.get("weakness"), "insufficient_data")
        second_name = _text(second.get("weakness"), "insufficient_data")
        top_score = _to_float(top.get("expected_learning_value"), 0.0)
        second_score = _to_float(second.get("expected_learning_value"), 0.0)
        emerging = top_name if top_score >= 55 else "none_detected"
        worsening = top_name if _to_float(top.get("weakness_score"), 0.0) >= 65 else "none_detected"
        improving = second_name if second_score < top_score * 0.55 and second_name != "insufficient_data" else "none_detected"
        resolved = "evidence_gap" if any(r.get("weakness") == "evidence_gap" and _to_float(r.get("weakness_score"), 0.0) < 25 for r in rankings) else "none_detected"
        return {
            "improving_weakness": improving,
            "worsening_weakness": worsening,
            "emerging_weakness": emerging,
            "resolved_weakness": resolved,
            "weakness_drift_score": _round(_clamp(abs(top_score - second_score)), 2),
            "weakness_trend": "current_snapshot_only_v1",
            "weakness_persistence": _round(_to_float(top.get("source_count"), 0.0) / 4.0 * 100.0, 2) if top else 0.0,
        }

    def _governance(self, allocation: dict[str, Any], rankings: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        top = rankings[0] if rankings else {}
        health_weaknesses = {"storage_health", "retrieval_health", "worker_health", "API_budget"}
        severe_health = [r for r in rankings if r.get("weakness") in health_weaknesses and _to_float(r.get("weakness_score"), 0.0) >= 75.0]
        confidence = _to_float(allocation.get("allocation_confidence"), 0.0)
        top_noise = _to_float(top.get("noise_risk_score"), 100.0)
        blocked = []
        if allocation.get("allocation_guardrail_status") != "passed":
            blocked.append("allocation_guardrail_violation")
        if confidence < 35:
            blocked.append("low_allocation_confidence")
        if top_noise > 70:
            blocked.append("top_weakness_noise_risk_high")
        if severe_health:
            blocked.append("system_health_weakness_overrides_trading_learning")
        governance_status = "passed_shadow_only" if not blocked else "guardrailed_observation_only"
        return {
            "governance_status": governance_status,
            "allocation_safe": bool(not blocked),
            "blocked_allocation_reason": ",".join(blocked) if blocked else "none",
            "policy_readiness_status": "not_ready_shadow_only_no_behavior_changes",
            "behavior_safe_to_apply": False,
            "governance_guardrails": {
                "no_behavior_changes_allowed": True,
                "no_policy_application_allowed": True,
                "no_broker_or_paper_execution_changes": True,
                "no_ranking_entry_exit_sizing_threshold_changes": True,
                "no_dashboard_endpoint_increase": True,
                "no_provider_api_llm_call_increase": True,
                "no_full_history_or_raw_archive_scans": True,
                "allocation_changes_explainable": True,
            },
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
        signals = self._collect_weakness_signals(statuses)
        scored = self._value_scores(signals)
        rankings = self._rankings(scored)
        top = rankings[0] if rankings else {}
        secondary = rankings[1] if len(rankings) > 1 else {}
        allocation = self._allocation(rankings)
        drift = self._drift(rankings)
        governance = self._governance(allocation, rankings, statuses)
        top_weakness = _text(top.get("weakness"), "insufficient_data")
        worker_focus = WEAKNESS_TO_WORKER.get(top_weakness, "coverage_gap_worker")
        replay_focus = WEAKNESS_TO_REPLAY.get(top_weakness, "highest_value_weakness_replay")
        memory_focus = f"retain_high_confidence_{top_weakness}_lessons"
        weakness_confidence = _round(_to_float(top.get("sample_size_confidence"), 0.0), 2)
        weakness_real = "real_supported" if weakness_confidence >= 55 and _to_float(top.get("noise_risk_score"), 100.0) < 60 else "observation_only_possible_noise"
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_adaptive_learning_prioritization_resource_allocation",
            "generated_at": _now_iso(),
            "top_weakness": top_weakness,
            "secondary_weakness": _text(secondary.get("weakness"), "insufficient_data"),
            "weakness_rankings": rankings[:10],
            "weakness_confidence": weakness_confidence,
            "weakness_trend": drift.get("weakness_trend"),
            "weakness_persistence": drift.get("weakness_persistence"),
            "weakness_is_real_vs_noise": weakness_real,
            "highest_value_learning_focus": top_weakness,
            "lowest_value_learning_focus": _text((rankings[-1] if rankings else {}).get("weakness"), "insufficient_data"),
            "learning_roi_score": _round(_to_float(top.get("expected_learning_value"), 0.0), 2),
            "expected_improvement_score": _round(_to_float(top.get("improvement_potential_score"), 0.0), 2),
            "focus_reason": f"{top_weakness}_ranked_highest_by_expected_learning_value_with_{weakness_confidence:.1f}_confidence",
            **allocation,
            "recommended_worker_focus": worker_focus,
            "worker_focus_reason": f"route_existing_workers_to_{top_weakness}_without_new_provider_calls",
            "worker_focus_change": "recommendation_only_no_new_jobs_spawned",
            "worker_focus_safety_status": "safe_shadow_only_existing_orchestrator",
            "recommended_replay_focus": replay_focus,
            "replay_priority_reason": f"counterfactuals_prioritize_{top_weakness}_because_it_has_highest_expected_learning_value",
            "counterfactual_focus": replay_focus,
            "replay_learning_value_score": _round(_to_float(top.get("expected_learning_value"), 0.0), 2),
            "memory_focus": memory_focus,
            "retained_weakness_lessons": [r.get("weakness") for r in rankings[:4]],
            "deprioritized_lessons": [r.get("weakness") for r in rankings[-4:]],
            "memory_weighting_score": _round(_to_float(top.get("expected_learning_value"), 0.0) * 0.7 + weakness_confidence * 0.3, 2),
            "retention_priority_reason": f"retain_repeated_high_value_{top_weakness}_patterns_and_deprioritize_low_value_noise",
            **drift,
            **governance,
            "shadow_recommendation": f"shadow_only_allocate_learning_attention_to_{top_weakness}_while_preserving_guardrails",
            "summary": "Astra is ranking learning weaknesses and allocating learning focus without changing trading behavior.",
            "cache_status": "rebuilt",
            "cache_freshness": "live",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "bandwidth_saving_mode": True,
            "api_budget_status": "cached_summaries_only",
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
                cached["degraded_reason"] = f"adaptive_learning_prioritization_rebuild_failed_using_cache:{str(exc)[:140]}"
                cached["behavior_safe_to_apply"] = False
                return cached
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_adaptive_learning_prioritization_resource_allocation",
                "top_weakness": "unavailable",
                "secondary_weakness": "unavailable",
                "weakness_rankings": [],
                "weakness_confidence": 0.0,
                "highest_value_learning_focus": "unavailable",
                "expected_improvement_score": 0.0,
                "learning_roi_score": 0.0,
                "weakness_focus_allocation": 0.0,
                "balanced_learning_allocation": 0.0,
                "strength_validation_allocation": 10.0,
                "system_health_allocation": 5.0,
                "recommended_worker_focus": "unavailable",
                "recommended_replay_focus": "unavailable",
                "memory_focus": "unavailable",
                "improving_weakness": "unavailable",
                "worsening_weakness": "unavailable",
                "emerging_weakness": "unavailable",
                "resolved_weakness": "unavailable",
                "governance_status": "unavailable",
                "allocation_safe": False,
                "policy_readiness_status": "not_ready_shadow_only_no_behavior_changes",
                "shadow_recommendation": "unavailable",
                "degraded_reason": f"adaptive_learning_prioritization_resource_allocation_v1_unavailable:{str(exc)[:140]}",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "build_ms": 0.0,
                "behavior_safe_to_apply": False,
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
                "auto_apply_allowed": False,
                "human_review_required": True,
            }
