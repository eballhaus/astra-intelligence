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
CACHE_TTL_SECONDS = 12.0
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 900
CHART_POINTS = 80


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        if not math.isfinite(out):
            return float(default)
        return out
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _score(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if out <= 1.0:
        out *= 100.0
    return _clamp(out)


def _text(value: Any, default: str = "") -> str:
    s = str(value if value is not None else default).strip()
    return s or str(default)


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def _first_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        try:
            if value is None or value == "":
                continue
            out = float(value)
            if math.isfinite(out):
                return out
        except Exception:
            continue
    return float(default)


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def _timestamp(row: dict[str, Any], index: int) -> str:
    for key in ("closed_at", "exit_timestamp", "exit_time", "updated_at", "timestamp", "ts", "created_at", "entry_timestamp"):
        value = row.get(key)
        if value:
            return _text(value)[:32]
    return f"sample_{index + 1}"


def _return_pct(row: dict[str, Any]) -> float:
    return _first_float(
        row.get("realized_return_pct"),
        row.get("return_pct"),
        row.get("return_percent"),
        row.get("pnl_pct"),
        row.get("profit_pct"),
        default=0.0,
    )


def _hold_minutes(row: dict[str, Any]) -> float:
    minutes = _first_float(
        row.get("hold_duration_minutes"),
        row.get("actual_hold_duration_minutes"),
        row.get("hold_time_minutes"),
        default=0.0,
    )
    if minutes > 0:
        return minutes
    seconds = _first_float(row.get("hold_seconds"), row.get("duration_seconds"), default=0.0)
    if seconds > 0:
        return seconds / 60.0
    return 0.0


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return rows
    for pack_key in ("stocks", "crypto"):
        pack = payload.get(pack_key)
        if not isinstance(pack, dict):
            continue
        for section in ("final", "qualified", "watchlist", "fill"):
            values = pack.get(section)
            if isinstance(values, list):
                rows.extend([dict(v) for v in values if isinstance(v, dict)])
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _text(row.get("symbol") or row.get("ticker")).upper()
        if symbol and symbol not in dedup:
            dedup[symbol] = row
    return list(dedup.values())


def _metric(value: Any, *, label: str | None = None, evidence_count: int = 0, maturity: str | None = None, explanation: str = "") -> dict[str, Any]:
    has_value = value is not None and value != ""
    numeric = None
    if has_value:
        try:
            numeric = float(value)
            if not math.isfinite(numeric):
                numeric = None
        except Exception:
            numeric = None
    mature = maturity or ("healthy" if evidence_count > 0 and numeric is not None else "insufficient_evidence")
    if numeric is None and mature in {"healthy", "degraded"}:
        mature = "insufficient_evidence"
    return {
        "value": round(numeric, 4) if numeric is not None else None,
        "label": label or mature,
        "evidence_count": int(max(0, evidence_count)),
        "maturity": mature,
        "explanation": explanation or _maturity_explanation(mature),
    }


def _maturity_explanation(maturity: str) -> str:
    mapping = {
        "warming_up": "Astra is collecting enough observations for this metric.",
        "insufficient_closed_trades": "Waiting for enough naturally closed paper trades.",
        "awaiting_replay_data": "Waiting for enough replay-reviewed trades.",
        "awaiting_lifecycle_outcomes": "Waiting for complete lifecycle outcomes.",
        "insufficient_evidence": "Not enough evidence for a truthful numeric claim yet.",
        "stale_last_known_good": "Using last-known-good data while fresh diagnostics rebuild.",
        "healthy": "Evidence is sufficient and the metric is current.",
        "degraded": "Metric is available but source quality is degraded.",
    }
    return mapping.get(str(maturity), "Metric is being monitored.")


def _profit_factor(returns: list[float]) -> float | None:
    wins = [v for v in returns if v > 0]
    losses = [abs(v) for v in returns if v < 0]
    if not returns or not losses:
        return None if not wins else round(sum(wins), 4)
    return round(sum(wins) / max(1e-9, sum(losses)), 4)


def _rolling(values: list[float], window: int = 20) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1): i + 1]
        out.append(round(mean(chunk), 4) if chunk else 0.0)
    return out


class UnifiedLearningDiagnosticsV1:
    """Fast, cached, maturity-aware Learning tab control-tower snapshot."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def build(self, sources: dict[str, Any] | None = None, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached
        sources = dict(sources or {})
        failed_sources: list[str] = []
        try:
            payload = self._build_uncached(sources, failed_sources)
        except Exception as exc:
            if self._cache:
                payload = dict(self._cache)
                payload["stale_cache"] = True
                payload["degraded_reason"] = f"unified_rebuild_failed_last_known_good_used: {str(exc)[:140]}"
            else:
                payload = self._fallback(str(exc))
        payload["cache_hit"] = False
        payload["cache_age_seconds"] = 0.0
        payload["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        payload["api_calls_used"] = 0
        payload["failed_sources"] = failed_sources
        payload["failed_sources_count"] = len(failed_sources)
        self._cache = dict(payload)
        self._cache_ts = now
        return payload

    def _rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name, limit in (
            ("opportunity_cost_learning_v1.jsonl", 360),
            ("replay_counterfactual_learning_v2.jsonl", 360),
            ("trade_memory_similarity_v1.jsonl", 320),
            ("learning_knowledge_graph_v1.jsonl", 320),
            ("explanation_intelligence_v1.jsonl", 240),
            ("trade_archetype_regime_intelligence_v1.jsonl", 360),
            ("adaptive_profit_capture_intelligence_v1.jsonl", 360),
            ("trade_lifecycle_excursion_v2.jsonl", 360),
            ("trade_lifecycle_excursion_v1.jsonl", 360),
            ("trade_lifecycle_v1.jsonl", 320),
            ("outcome_labels_v1.jsonl", 280),
            ("candidate_decision_ledger_v1.jsonl", 220),
            ("paper_trade_journal.jsonl", 180),
        ):
            rows.extend(_tail_jsonl(os.path.join(self.state_dir, name), max_rows=limit))
        return rows[-MAX_ROWS:]

    def _build_uncached(self, sources: dict[str, Any], failed_sources: list[str]) -> dict[str, Any]:
        top_payload = dict(sources.get("top_buys") or {})
        learning_fast = dict(sources.get("learning_snapshot_fast") or {})
        paper = dict(sources.get("paper_performance") or {})
        statuses = {k: v for k, v in dict(sources.get("statuses") or {}).items() if isinstance(v, dict)}
        candidate_rows = _candidate_rows(top_payload)
        history_rows = self._rows()
        closed_rows = [r for r in history_rows if _return_pct(r) != 0 or r.get("closed_at") or r.get("exit_timestamp")]
        returns = [_return_pct(r) for r in closed_rows]
        evidence_count = len(closed_rows)
        maturity = self._evidence_maturity(evidence_count, statuses)
        perf = self._performance_summary(learning_fast, paper, statuses, returns, evidence_count, maturity)
        execution = self._execution_quality_summary(learning_fast, statuses, candidate_rows, evidence_count, maturity)
        portfolio = self._portfolio_health_summary(statuses, candidate_rows, maturity)
        learning = self._learning_maturity_summary(statuses, paper, evidence_count, maturity)
        regime = self._regime_context_summary(statuses, candidate_rows, history_rows, maturity)
        system = self._system_health_summary(sources, statuses, learning_fast)
        executive = self._executive_snapshot(perf, execution, portfolio, learning, regime, system, candidate_rows, evidence_count)
        charts = self._master_charts(history_rows, candidate_rows, statuses)
        advanced = self._advanced_statuses(statuses, sources)
        adaptive_v2 = self._adaptive_execution_exit_summary(statuses.get("adaptive_execution_exit_intelligence_v2") or {})
        diversification_v2 = self._portfolio_diversification_summary(statuses.get("portfolio_diversification_correlation_v2") or {})
        mobile_compaction = self._mobile_runtime_compaction_summary(statuses.get("mobile_runtime_compaction") or {})
        profit_exploration = self._profit_seeking_exploration_summary(statuses.get("profit_seeking_adaptive_exploration") or {})
        market_calendar_knowledge = self._market_calendar_knowledge_summary(statuses.get("market_calendar_knowledge") or {})
        broad_universe = self._broad_universe_intake_summary(statuses.get("broad_universe_intake_promotion") or {})
        trade_lifecycle_excursion = self._trade_lifecycle_excursion_summary(statuses.get("trade_lifecycle_excursion") or {})
        trade_lifecycle_excursion_v2 = self._trade_lifecycle_excursion_v2_summary(statuses.get("trade_lifecycle_excursion_v2") or {})
        adaptive_profit_capture = self._adaptive_profit_capture_summary(statuses.get("adaptive_profit_capture") or {})
        profit_capture_peak_decay_exit_validation = self._profit_capture_peak_decay_exit_validation_summary(statuses.get("profit_capture_peak_decay_exit_validation_suite_v1") or {})
        adaptive_execution_exit_v3 = self._adaptive_execution_exit_v3_summary(statuses.get("adaptive_execution_exit_intelligence_v3") or {})
        exit_learning_expansion = self._exit_learning_expansion_summary(statuses.get("exit_learning_expansion_suite_v1") or {})
        market_context_learning = self._market_context_learning_summary(statuses.get("market_context_learning_suite_v1") or {})
        learning_acceleration_retention = self._learning_acceleration_retention_summary(statuses.get("learning_acceleration_retention_suite_v1") or {})
        adaptive_learning_infrastructure_suite = self._adaptive_learning_infrastructure_suite_summary(statuses.get("adaptive_learning_infrastructure_suite_v1") or {})
        adaptive_worker_activation_orchestration = self._adaptive_worker_activation_orchestration_summary(statuses.get("adaptive_worker_activation_orchestration_v1") or {})
        confidence_calibration_performance_attribution = self._confidence_calibration_performance_attribution_summary(statuses.get("confidence_calibration_performance_attribution_v1") or {})
        context_evidence_expansion = self._context_evidence_expansion_summary(statuses.get("context_evidence_expansion_suite_v1") or {})
        catalyst_theme_narrative_capital_flow_v2 = self._catalyst_theme_narrative_capital_flow_v2_summary(statuses.get("catalyst_theme_narrative_capital_flow_intelligence_v2") or {})
        decision_optimization_trade_management = self._decision_optimization_trade_management_summary(statuses.get("decision_optimization_trade_management_suite_v1") or {})
        full_opportunity_lifecycle_learning = self._full_opportunity_lifecycle_learning_summary(statuses.get("full_opportunity_lifecycle_learning_suite_v1") or {})
        long_term_memory_symbol_retrieval = self._long_term_memory_symbol_retrieval_summary(statuses.get("long_term_memory_symbol_retrieval_suite_v1") or {})
        virtual_paper_convergence_symbol_attribution = self._virtual_paper_convergence_symbol_attribution_summary(statuses.get("virtual_paper_convergence_symbol_attribution_v1") or {})
        accelerated_learning_symbol_intelligence = self._accelerated_learning_symbol_intelligence_summary(statuses.get("accelerated_learning_symbol_intelligence_suite_v1") or {})
        realistic_shadow_evidence_learning_lab = self._realistic_shadow_evidence_learning_lab_summary(statuses.get("realistic_shadow_evidence_learning_lab_v1") or {})
        historical_intelligence_market_memory = self._historical_intelligence_market_memory_summary(statuses.get("historical_intelligence_market_memory_suite_v1") or {})
        catalyst_classification_historical_exit_maturation = self._catalyst_classification_historical_exit_maturation_summary(statuses.get("catalyst_classification_historical_exit_maturation_suite_v1") or {})
        catalyst_persistence_decay_curves = self._catalyst_persistence_decay_curves_v2_summary(statuses.get("catalyst_persistence_decay_curves_v2") or {})
        catalyst_lifecycle_intelligence = self._catalyst_lifecycle_intelligence_v1_summary(statuses.get("catalyst_lifecycle_intelligence_v1") or {})
        cross_sector_capital_flow_memory = self._cross_sector_capital_flow_memory_v1_summary(statuses.get("cross_sector_capital_flow_memory_v1") or {})
        shadow_vs_paper_performance_attribution = self._shadow_vs_paper_performance_attribution_v1_summary(statuses.get("shadow_vs_paper_performance_attribution_v1") or {})
        candidate_ranking_attribution_promotion_intelligence = self._candidate_ranking_attribution_promotion_intelligence_v1_summary(statuses.get("candidate_ranking_attribution_promotion_intelligence_v1") or {})
        intelligence_quality_learning_efficiency = self._intelligence_quality_learning_efficiency_suite_v1_summary(statuses.get("intelligence_quality_learning_efficiency_suite_v1") or {})
        advanced_attribution_controlled_exit_learning_roi = self._advanced_attribution_controlled_exit_learning_roi_suite_v1_summary(statuses.get("advanced_attribution_controlled_exit_learning_roi_suite_v1") or {})
        profit_optimization_context_intelligence = self._profit_optimization_context_intelligence_suite_v1_summary(statuses.get("profit_optimization_context_intelligence_suite_v1") or {})
        trade_lifecycle_audit_truth_horizon_integrity = self._trade_lifecycle_audit_truth_horizon_integrity_suite_v1_summary(statuses.get("trade_lifecycle_audit_truth_horizon_integrity_suite_v1") or {})
        astra_foundation_stabilization_governance = self._astra_foundation_stabilization_governance_bundle_v1_summary(statuses.get("astra_foundation_stabilization_governance_bundle_v1") or {})
        astra_tier2a_librarian_executive_truth_layer = self._astra_tier2a_librarian_executive_truth_layer_v1_summary(statuses.get("astra_tier2a_librarian_executive_truth_layer_v1") or {})
        astra_satellite_network = self._astra_satellite_network_v1_summary(statuses.get("astra_satellite_network_v1") or {})
        astra_tier3_historical_satellite_shadow_acceleration = self._astra_tier3_historical_satellite_shadow_acceleration_v1_summary(statuses.get("astra_tier3_historical_satellite_shadow_acceleration_v1") or {})
        astra_final_intelligence_maturation = self._astra_final_intelligence_maturation_bundle_v1_summary(statuses.get("astra_final_intelligence_maturation_bundle_v1") or {})
        astra_targeted_maturity_profit_capture_optimization = self._astra_targeted_maturity_profit_capture_optimization_bundle_v1_summary(statuses.get("astra_targeted_maturity_profit_capture_optimization_bundle_v1") or {})
        astra_horizon_lifecycle_capacity_promotion_readiness = self._astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1_summary(statuses.get("astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1") or {})
        trade_thesis_validation = self._trade_thesis_validation_v1_summary(statuses.get("trade_thesis_validation_v1") or {})
        market_transition_detection = self._market_transition_detection_v1_summary(statuses.get("market_transition_detection_v1") or {})
        trade_family_intelligence = self._trade_family_intelligence_v1_summary(statuses.get("trade_family_intelligence_v1") or {})
        market_condition_attribution = self._market_condition_attribution_v1_summary(statuses.get("market_condition_attribution_v1") or {})
        market_breadth_index_intelligence = self._market_breadth_index_intelligence_v1_summary(statuses.get("market_breadth_index_intelligence_v1") or {})
        etf_sector_rotation_intelligence = self._etf_sector_rotation_intelligence_v1_summary(statuses.get("etf_sector_rotation_intelligence_v1") or {})
        crypto_shadow_learning = self._crypto_shadow_learning_v1_summary(statuses.get("crypto_shadow_learning_v1") or {})
        cross_market_attribution_transfer_learning = self._cross_market_attribution_transfer_learning_v1_summary(statuses.get("cross_market_attribution_transfer_learning_v1") or {})
        profit_lock_profit_capture_maturation = self._profit_lock_profit_capture_maturation_v2_summary(statuses.get("profit_lock_profit_capture_maturation_v2") or {})
        shadow_correction_validation_attribution = self._shadow_correction_validation_attribution_v1_summary(statuses.get("shadow_correction_validation_attribution_v1") or {})
        controlled_paper_profit_protection_pilot = self._controlled_paper_profit_protection_pilot_v1_summary(statuses.get("controlled_paper_profit_protection_pilot_v1") or {})
        adaptive_learning_prioritization_resource_allocation = self._adaptive_learning_prioritization_resource_allocation_summary(statuses.get("adaptive_learning_prioritization_resource_allocation_v1") or {})
        autonomous_intelligence_validation_governance = self._autonomous_intelligence_validation_governance_summary(statuses.get("autonomous_intelligence_validation_governance_v1") or {})
        paper_throughput_exit_validation_catalyst = self._paper_throughput_exit_validation_catalyst_summary(statuses.get("paper_throughput_exit_validation_catalyst_intelligence_v1") or {})
        multi_horizon_capacity_exit_validation = self._multi_horizon_capacity_exit_validation_summary(statuses.get("multi_horizon_paper_capacity_exit_validation_v1") or {})
        controlled_paper_learned_exit_validation = self._controlled_paper_learned_exit_validation_summary(statuses.get("controlled_paper_learned_exit_validation_v1") or {})
        if adaptive_worker_activation_orchestration.get("enabled"):
            adaptive_learning_infrastructure_suite["adaptive_worker_activation_compatible"] = True
            adaptive_learning_infrastructure_suite["adaptive_worker_activation_status"] = adaptive_worker_activation_orchestration.get("orchestrator_status")
            adaptive_learning_infrastructure_suite["adaptive_worker_activation_focus"] = adaptive_worker_activation_orchestration.get("recommended_next_worker_focus")
            adaptive_learning_infrastructure_suite["adaptive_worker_activation_active_workers"] = adaptive_worker_activation_orchestration.get("active_worker_count")
        trade_archetype_regime = self._trade_archetype_regime_summary(statuses.get("trade_archetype_regime") or {})
        replay_counterfactual_learning_v2 = self._replay_counterfactual_learning_v2_summary(statuses.get("replay_counterfactual_learning_v2") or {})
        opportunity_cost_learning = self._opportunity_cost_learning_summary(statuses.get("opportunity_cost_learning") or {})
        advanced_learning_intelligence = self._advanced_learning_intelligence_summary(statuses.get("advanced_learning_intelligence") or {})
        blind_spot_detection = self._blind_spot_detection_summary(statuses.get("blind_spot_detection") or {})
        learning_issue_audit = self._learning_issue_audit_summary(statuses.get("learning_issue_audit") or {})
        remote_runtime_consistency = self._remote_runtime_consistency_summary(statuses.get("remote_runtime_consistency") or {})
        capacity_expansion_status = self._capacity_expansion_summary(statuses)
        paper_path_gating_status = self._paper_path_gating_summary(statuses)
        horizon_coverage = self._horizon_coverage_summary(statuses, history_rows, paper_path_gating_status)
        multi_horizon_raw = dict(statuses.get("multi_horizon_intelligence_adaptive_lifecycle_suite_v1") or {})
        if horizon_coverage:
            multi_horizon_raw["horizon_mismatch_risk_score"] = max(
                _to_float(multi_horizon_raw.get("horizon_mismatch_risk_score"), 0.0),
                _to_float(horizon_coverage.get("horizon_mismatch_risk_score"), 0.0),
            )
            multi_horizon_raw.setdefault("missing_horizons", horizon_coverage.get("missing_horizons"))
            multi_horizon_raw.setdefault("horizons_tested", horizon_coverage.get("tested_horizons"))
            multi_horizon_raw.setdefault("dominant_paper_horizon", horizon_coverage.get("dominant_horizon"))
            multi_horizon_raw.setdefault("best_horizon", horizon_coverage.get("best_horizon"))
            multi_horizon_raw.setdefault("weakest_horizon", horizon_coverage.get("weakest_horizon"))
            multi_horizon_raw.setdefault("learned_exits_applied", horizon_coverage.get("learned_exits_applied"))
            multi_horizon_raw.setdefault("natural_exit_preserved", horizon_coverage.get("natural_exit_preserved"))
            multi_horizon_raw.setdefault("next_recommended_test", horizon_coverage.get("next_recommended_horizon_test"))
        multi_horizon_intelligence_adaptive_lifecycle = self._multi_horizon_intelligence_adaptive_lifecycle_summary(multi_horizon_raw)
        execution_participation_audit = self._execution_participation_audit_summary(statuses.get("execution_participation_audit") or {})
        stale = self._stale_status(sources, system)
        return {
            "ok": True,
            "enabled": True,
            "version": VERSION,
            "mode": "unified_learning_snapshot",
            "generated_at": _now_iso(),
            "executive_snapshot": executive,
            "master_charts": charts,
            "performance_summary": perf,
            "execution_quality_summary": execution,
            "portfolio_health_summary": portfolio,
            "portfolio_diversification_correlation_v2": diversification_v2,
            "mobile_runtime_compaction": mobile_compaction,
            "profit_seeking_adaptive_exploration": profit_exploration,
            "market_calendar_knowledge": market_calendar_knowledge,
            "broad_universe_intake_promotion": broad_universe,
            "trade_lifecycle_excursion": trade_lifecycle_excursion,
            "trade_lifecycle_excursion_v2": trade_lifecycle_excursion_v2,
            "adaptive_profit_capture_intelligence": adaptive_profit_capture,
            "profit_capture_peak_decay_exit_validation_suite_v1": profit_capture_peak_decay_exit_validation,
            "adaptive_execution_exit_intelligence_v3": adaptive_execution_exit_v3,
            "exit_learning_expansion_suite_v1": exit_learning_expansion,
            "market_context_learning_suite_v1": market_context_learning,
            "learning_acceleration_retention_suite_v1": learning_acceleration_retention,
            "adaptive_learning_infrastructure_suite_v1": adaptive_learning_infrastructure_suite,
            "adaptive_worker_activation_orchestration_v1": adaptive_worker_activation_orchestration,
            "confidence_calibration_performance_attribution_v1": confidence_calibration_performance_attribution,
            "context_evidence_expansion_suite_v1": context_evidence_expansion,
            "catalyst_theme_narrative_capital_flow_intelligence_v2": catalyst_theme_narrative_capital_flow_v2,
            "decision_optimization_trade_management_suite_v1": decision_optimization_trade_management,
            "full_opportunity_lifecycle_learning_suite_v1": full_opportunity_lifecycle_learning,
            "long_term_memory_symbol_retrieval_suite_v1": long_term_memory_symbol_retrieval,
            "virtual_paper_convergence_symbol_attribution_v1": virtual_paper_convergence_symbol_attribution,
            "accelerated_learning_symbol_intelligence_suite_v1": accelerated_learning_symbol_intelligence,
            "realistic_shadow_evidence_learning_lab_v1": realistic_shadow_evidence_learning_lab,
            "historical_intelligence_market_memory_suite_v1": historical_intelligence_market_memory,
            "catalyst_classification_historical_exit_maturation_suite_v1": catalyst_classification_historical_exit_maturation,
            "catalyst_persistence_decay_curves_v2": catalyst_persistence_decay_curves,
            "catalyst_lifecycle_intelligence_v1": catalyst_lifecycle_intelligence,
            "cross_sector_capital_flow_memory_v1": cross_sector_capital_flow_memory,
            "shadow_vs_paper_performance_attribution_v1": shadow_vs_paper_performance_attribution,
            "candidate_ranking_attribution_promotion_intelligence_v1": candidate_ranking_attribution_promotion_intelligence,
            "intelligence_quality_learning_efficiency_suite_v1": intelligence_quality_learning_efficiency,
            "advanced_attribution_controlled_exit_learning_roi_suite_v1": advanced_attribution_controlled_exit_learning_roi,
            "profit_optimization_context_intelligence_suite_v1": profit_optimization_context_intelligence,
            "trade_lifecycle_audit_truth_horizon_integrity_suite_v1": trade_lifecycle_audit_truth_horizon_integrity,
            "astra_foundation_stabilization_governance_bundle_v1": astra_foundation_stabilization_governance,
            "astra_tier2a_librarian_executive_truth_layer_v1": astra_tier2a_librarian_executive_truth_layer,
            "astra_satellite_network_v1": astra_satellite_network,
            "astra_tier3_historical_satellite_shadow_acceleration_v1": astra_tier3_historical_satellite_shadow_acceleration,
            "astra_final_intelligence_maturation_bundle_v1": astra_final_intelligence_maturation,
            "astra_targeted_maturity_profit_capture_optimization_bundle_v1": astra_targeted_maturity_profit_capture_optimization,
            "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1": astra_horizon_lifecycle_capacity_promotion_readiness,
            "trade_thesis_validation_v1": trade_thesis_validation,
            "market_transition_detection_v1": market_transition_detection,
            "trade_family_intelligence_v1": trade_family_intelligence,
            "market_condition_attribution_v1": market_condition_attribution,
            "market_breadth_index_intelligence_v1": market_breadth_index_intelligence,
            "etf_sector_rotation_intelligence_v1": etf_sector_rotation_intelligence,
            "crypto_shadow_learning_v1": crypto_shadow_learning,
            "cross_market_attribution_transfer_learning_v1": cross_market_attribution_transfer_learning,
            "profit_lock_profit_capture_maturation_v2": profit_lock_profit_capture_maturation,
            "shadow_correction_validation_attribution_v1": shadow_correction_validation_attribution,
            "controlled_paper_profit_protection_pilot_v1": controlled_paper_profit_protection_pilot,
            "multi_horizon_intelligence_adaptive_lifecycle_suite_v1": multi_horizon_intelligence_adaptive_lifecycle,
            "paper_throughput_exit_validation_catalyst_intelligence_v1": paper_throughput_exit_validation_catalyst,
            "multi_horizon_paper_capacity_exit_validation_v1": multi_horizon_capacity_exit_validation,
            "controlled_paper_learned_exit_validation_v1": controlled_paper_learned_exit_validation,
            "adaptive_learning_prioritization_resource_allocation_v1": adaptive_learning_prioritization_resource_allocation,
            "autonomous_intelligence_validation_governance_v1": autonomous_intelligence_validation_governance,
            "trade_archetype_regime_intelligence": trade_archetype_regime,
            "replay_counterfactual_learning_v2": replay_counterfactual_learning_v2,
            "opportunity_cost_learning": opportunity_cost_learning,
            "advanced_learning_intelligence": advanced_learning_intelligence,
            "blind_spot_detection": blind_spot_detection,
            "learning_issue_audit": learning_issue_audit,
            "remote_runtime_consistency": remote_runtime_consistency,
            "capacity_expansion_status": capacity_expansion_status,
            "paper_path_gating_summary": paper_path_gating_status,
            "horizon_coverage_summary": horizon_coverage,
            "execution_participation_audit": execution_participation_audit,
            "learning_maturity_summary": learning,
            "regime_context_summary": regime,
            "adaptive_execution_exit_intelligence_v2": adaptive_v2,
            "adaptive_execution_intelligence": adaptive_v2.get("adaptive_execution_intelligence", {}),
            "exit_intelligence_v2": adaptive_v2.get("exit_intelligence_v2", {}),
            "regime_adaptive_trading": adaptive_v2.get("regime_adaptive_trading", {}),
            "lifecycle_adaptation": adaptive_v2.get("lifecycle_adaptation", {}),
            "profitability_improvement_diagnostics": adaptive_v2.get("profitability_improvement_diagnostics", {}),
            "system_health_summary": system,
            "advanced_panel_links": advanced,
            "advanced_panel_statuses": advanced,
            "stale_data_status": stale,
            "evidence_maturity_status": maturity,
            "future_suite_integration_contract": self._integration_contract(),
            "frontend_endpoint_policy": {
                "initial_learning_tab_endpoint_count": 1,
                "initial_endpoint": "/api/unified_learning_diagnostics_v1",
                "advanced_diagnostics_lazy_load": True,
                "legacy_initial_endpoint_storm_removed": True,
            },
            "stale_cache": False,
            "degraded_reason": system.get("degraded_reason") or "",
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "behavior_safe_to_apply": False,
        }

    def _evidence_maturity(self, evidence_count: int, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        replay = statuses.get("replay_lifecycle_expectancy") or {}
        replay_ready = bool(replay.get("replay_learning_ready"))
        lifecycle_ready = bool(replay.get("lifecycle_tracking_ready"))
        expectancy_ready = bool(replay.get("expectancy_learning_ready"))
        if evidence_count <= 0:
            label = "insufficient_closed_trades"
        elif evidence_count < 20:
            label = "warming_up"
        elif not replay_ready:
            label = "awaiting_replay_data"
        elif not lifecycle_ready:
            label = "awaiting_lifecycle_outcomes"
        else:
            label = "healthy" if expectancy_ready or evidence_count >= 50 else "warming_up"
        return {
            "label": label,
            "evidence_count": evidence_count,
            "closed_trade_count": evidence_count,
            "replay_ready": replay_ready,
            "lifecycle_ready": lifecycle_ready,
            "expectancy_ready": expectancy_ready,
            "explanation": _maturity_explanation(label),
        }

    def _performance_summary(self, learning_fast: dict[str, Any], paper: dict[str, Any], statuses: dict[str, dict[str, Any]], returns: list[float], evidence_count: int, maturity: dict[str, Any]) -> dict[str, Any]:
        paper_combined = dict(paper.get("combined") or paper.get("paper_outcome_summary", {}).get("combined") or {})
        replay = statuses.get("replay_lifecycle_expectancy") or {}
        replay_cf = statuses.get("replay_counterfactual_learning_v2") or {}
        lifecycle_v2 = statuses.get("trade_lifecycle_excursion_v2") or {}
        edge = statuses.get("edge_development") or {}
        advanced = statuses.get("advanced_learning_intelligence") or {}
        issue_audit = statuses.get("learning_issue_audit") or {}
        buy_purity_diag = dict(issue_audit.get("buy_purity_diagnostics") or {})
        closed = max(evidence_count, _to_int(paper_combined.get("valid_closed"), 0), _to_int(paper.get("closed_trades_count"), 0))
        advanced_count = _to_int((advanced.get("evidence_counts") or {}).get("return_evidence"), 0)
        advanced_core_values_available = all(advanced.get(key) not in (None, "") for key in ("released_win_rate", "profit_factor", "average_return"))
        advanced_available = bool(
            advanced_count > 0
            and advanced_core_values_available
            and (advanced.get("source_validation_passed") or _to_float(advanced.get("metric_confidence_score"), 0.0) >= 45.0)
        )
        if advanced_available:
            closed = max(closed, advanced_count)
        metric_maturity = "healthy" if closed >= 20 else ("warming_up" if closed > 0 else "insufficient_closed_trades")
        if advanced_available:
            released_wr = _first_float(advanced.get("released_win_rate"), advanced.get("win_rate"), default=0.0)
            pf_value = _first_float(advanced.get("profit_factor"), default=0.0)
            avg_return = _first_float(advanced.get("average_return"), default=0.0)
        else:
            released_wr = _first_float(learning_fast.get("current_engine_released_wr"), paper_combined.get("win_rate"), paper.get("win_rate"), default=0.0)
            pf = _first_float(replay.get("expectancy_profit_factor"), default=0.0)
            pf_value = pf if pf > 0 else (_profit_factor(returns) or 0.0)
            avg_return = _first_float(replay.get("expectancy_avg_return"), paper_combined.get("avg_return"), paper.get("avg_return"), default=0.0)
        expectancy = _first_float(replay.get("expectancy_score"), edge.get("average_expected_value_score"), default=0.0)
        if expectancy <= 0 and advanced.get("expectancy") not in (None, ""):
            expectancy = _first_float(advanced.get("expectancy"), default=0.0)
        buy_purity = _first_float(
            buy_purity_diag.get("mapped_buy_purity"),
            learning_fast.get("buy_list_purity"),
            learning_fast.get("buy_list_purity_score"),
            learning_fast.get("buy_ranking_quality_score"),
            edge.get("buy_list_purity_score"),
            edge.get("buy_ranking_quality_score"),
            edge.get("average_expected_value_score"),
            default=0.0,
        )
        mature = metric_maturity if closed > 0 else maturity.get("label", "insufficient_evidence")
        source = "advanced_learning_intelligence_v1" if advanced_available else "legacy_learning_sources"
        available_metric_sources = {
            "advanced_learning_intelligence_v1": {
                "available": bool(advanced_core_values_available and advanced_count > 0),
                "source_validation_passed": bool(advanced.get("source_validation_passed")),
                "metric_confidence_score": _to_float(advanced.get("metric_confidence_score"), 0.0),
                "sample_size": advanced_count,
                "dataset_scope_label": _text(advanced.get("dataset_scope_label"), "unknown"),
                "dataset_scope_mismatch_detected": bool(advanced.get("dataset_scope_mismatch_detected", False)),
            },
            "replay_lifecycle_expectancy": {
                "available": bool(replay),
                "sample_size": _to_int(replay.get("expectancy_sample_size"), 0),
            },
            "lifecycle_rows": {
                "available": bool(returns),
                "sample_size": len(returns),
            },
            "legacy_learning_sources": {
                "available": bool(learning_fast or paper_combined or paper),
                "sample_size": _to_int(paper_combined.get("valid_closed"), _to_int(paper.get("closed_trades_count"), 0)),
            },
        }
        rejected_metric_sources: dict[str, str] = {}
        if not advanced_available:
            if not advanced_core_values_available:
                rejected_metric_sources["advanced_learning_intelligence_v1"] = "missing_core_reconciled_metric_values"
            elif advanced_count <= 0:
                rejected_metric_sources["advanced_learning_intelligence_v1"] = "no_return_evidence"
            elif not advanced.get("source_validation_passed") and _to_float(advanced.get("metric_confidence_score"), 0.0) < 45.0:
                rejected_metric_sources["advanced_learning_intelligence_v1"] = "low_metric_confidence"
        source_selection_reason = (
            "using_reconciled_advanced_learning_metrics_with_scope_labels"
            if advanced_available
            else "advanced_reconciled_metrics_unavailable_using_legacy_fallback"
        )
        legacy_fallback_used = source == "legacy_learning_sources"
        return {
            "released_win_rate": {**_metric(released_wr if closed > 0 else None, evidence_count=closed, maturity=mature, explanation=f"Win rate for released/current-engine paper outcomes. Source: {source}."), "source": source},
            "profit_factor": {**_metric(pf_value, evidence_count=closed, maturity=mature if pf_value is not None else "insufficient_closed_trades", explanation=f"Gross winners divided by gross losers. Source: {source}."), "source": source},
            "expectancy_score": {**_metric(expectancy if closed > 0 or expectancy > 0 else None, evidence_count=closed, maturity=mature, explanation=f"Outcome-weighted expectancy quality score. Source: {source}."), "source": source},
            "average_return": {**_metric(avg_return if closed > 0 else None, evidence_count=closed, maturity=mature, explanation=f"Average paper return from reconciled available outcomes. Source: {source}."), "source": source},
            "buy_list_purity": {**_metric(buy_purity if buy_purity > 0 else None, evidence_count=max(closed, 0), maturity="healthy" if buy_purity > 0 else maturity.get("label", "insufficient_evidence"), explanation="Cleanliness of the promoted buy list from mapped buy-purity/ranking-quality sources."), "source": "buy_purity_alias_mapping" if buy_purity > 0 else "unavailable"},
            "closed_trade_count": closed,
            "metric_source": source,
            "selected_metric_source": source,
            "available_metric_sources": available_metric_sources,
            "rejected_metric_sources": rejected_metric_sources,
            "source_selection_reason": source_selection_reason,
            "reconciled_metrics_available": bool(advanced_available),
            "legacy_fallback_used": bool(legacy_fallback_used),
            "fallback_reason": "" if not legacy_fallback_used else _text(next(iter(rejected_metric_sources.values()), "advanced_metrics_unavailable")),
            "core_performance_sample_size": int(closed),
            "replay_sample_size": _to_int(replay_cf.get("tracked_lifecycles"), _to_int(replay.get("expectancy_sample_size"), 0)),
            "lifecycle_sample_size": _to_int(lifecycle_v2.get("tracked_active_trades"), 0) + _to_int(lifecycle_v2.get("tracked_closed_trades"), 0),
            "advanced_learning_sample_size": int(advanced_count),
            "broker_confirmed_sample_size": _to_int(paper.get("closed_trades_count"), _to_int(paper_combined.get("valid_closed"), 0)),
            "open_trade_inclusion": _text(advanced.get("open_trade_inclusion"), "included_when_current_return_available" if advanced_available else "source_dependent"),
            "closed_trade_inclusion": _text(advanced.get("closed_trade_inclusion"), "included_when_exit_or_return_available" if advanced_available else "source_dependent"),
            "dataset_scope_label": _text(advanced.get("dataset_scope_label"), "legacy_or_mixed_scope" if legacy_fallback_used else "advanced_learning_scope"),
            "dataset_scope_mismatch_detected": bool(advanced.get("dataset_scope_mismatch_detected", False)),
        }

    def _execution_quality_summary(self, learning_fast: dict[str, Any], statuses: dict[str, dict[str, Any]], rows: list[dict[str, Any]], evidence_count: int, maturity: dict[str, Any]) -> dict[str, Any]:
        regime = statuses.get("regime_execution_survivability") or {}
        tm = statuses.get("trade_management_portfolio") or {}
        edge = statuses.get("edge_development") or {}
        lifecycle_v2 = statuses.get("trade_lifecycle_excursion_v2") or {}
        adaptive_exit_v2 = statuses.get("adaptive_execution_exit_intelligence_v2") or {}
        issue_audit = statuses.get("learning_issue_audit") or {}
        exit_diag = dict(issue_audit.get("exit_quality_diagnostics") or {})
        mature = "healthy" if evidence_count > 0 or rows else maturity.get("label", "insufficient_evidence")
        entry = _first_float(learning_fast.get("entry_quality"), regime.get("entry_timing_quality"), tm.get("average_entry_quality_shadow"), default=0.0)
        exit_q = _first_float(
            exit_diag.get("average_exit_quality"),
            learning_fast.get("exit_quality"),
            regime.get("exit_timing_quality"),
            tm.get("average_exit_quality_score"),
            lifecycle_v2.get("average_exit_quality"),
            adaptive_exit_v2.get("exit_quality"),
            adaptive_exit_v2.get("exit_efficiency_score"),
            default=0.0,
        )
        follow = _first_float(learning_fast.get("follow_through_quality"), regime.get("follow_through_probability"), edge.get("average_expected_follow_through_score"), default=0.0)
        truth = _first_float(edge.get("average_expected_win_probability"), default=0.0)
        return {
            "entry_quality": _metric(entry if entry > 0 else None, evidence_count=evidence_count, maturity=mature, explanation="Entry timing and quality from current learning summaries."),
            "exit_quality": {
                **_metric(exit_q if exit_q > 0 else None, evidence_count=evidence_count, maturity=mature, explanation="Exit timing quality without forcing exits."),
                "exit_quality_source": _text(exit_diag.get("exit_quality_source"), "mixed_learning_sources"),
                "exit_quality_sample_size": _to_int(exit_diag.get("exit_quality_sample_size"), 0),
                "natural_exit_count": _to_int(exit_diag.get("natural_exit_count"), 0),
                "simulated_exit_count": _to_int(exit_diag.get("simulated_exit_count"), 0),
                "open_position_count_used": _to_int(exit_diag.get("open_position_count_used"), 0),
                "closed_position_count_used": _to_int(exit_diag.get("closed_position_count_used"), 0),
                "exit_quality_confidence": _to_float(exit_diag.get("exit_quality_confidence"), 0.0),
                "exit_quality_scope_label": _text(exit_diag.get("exit_quality_scope_label"), "source_dependent"),
            },
            "follow_through_quality": _metric(follow if follow > 0 else None, evidence_count=max(evidence_count, len(rows)), maturity=mature, explanation="Likelihood that entries continue after trigger."),
            "confidence_truthfulness": _metric(truth if truth > 0 else None, evidence_count=evidence_count, maturity=mature if truth > 0 else "insufficient_evidence", explanation="How calibrated confidence appears versus observed outcomes."),
            "execution_quality_score": _metric(_first_float(regime.get("execution_quality_score"), default=0.0) or None, evidence_count=max(evidence_count, len(rows)), maturity=mature),
        }

    def _portfolio_health_summary(self, statuses: dict[str, dict[str, Any]], rows: list[dict[str, Any]], maturity: dict[str, Any]) -> dict[str, Any]:
        regime = statuses.get("regime_execution_survivability") or {}
        tm = statuses.get("trade_management_portfolio") or {}
        risk = statuses.get("portfolio_risk_intelligence") or {}
        div = statuses.get("portfolio_diversification_correlation_v2") or {}
        mature = "healthy" if rows else maturity.get("label", "insufficient_evidence")
        survivability = _first_float(div.get("portfolio_survivability"), regime.get("portfolio_survivability_score"), tm.get("portfolio_stability_score"), risk.get("average_portfolio_risk_score"), default=0.0)
        concentration = _first_float(div.get("concentration_risk"), regime.get("portfolio_concentration_risk"), tm.get("sector_concentration_score"), risk.get("highest_concentration_risk"), default=0.0)
        correlation = _first_float(div.get("correlation_risk"), regime.get("portfolio_correlation_risk"), tm.get("portfolio_correlation_risk"), risk.get("highest_correlation_risk"), default=0.0)
        heat = _first_float(tm.get("portfolio_heat_score"), risk.get("average_portfolio_risk_score"), default=0.0)
        return {
            "portfolio_survivability": _metric(survivability if survivability > 0 else None, evidence_count=len(rows), maturity=mature, explanation="Portfolio-level durability and survivability score."),
            "concentration_risk": _metric(concentration if concentration > 0 else None, evidence_count=len(rows), maturity=mature, explanation="Risk from clustered symbols/sectors/archetypes."),
            "correlation_risk": _metric(correlation if correlation > 0 else None, evidence_count=len(rows), maturity=mature, explanation="Risk from correlated candidates or positions."),
            "portfolio_heat": _metric(heat if heat > 0 else None, evidence_count=len(rows), maturity=mature, explanation="Aggregate pressure from open/selected risk."),
            "diversification_quality": _metric(div.get("diversification_quality"), evidence_count=len(rows), maturity=_text(div.get("maturity"), mature), explanation="Quality of current sector/cap/archetype/horizon balance."),
            "portfolio_fit_quality": _metric(div.get("portfolio_fit_quality"), evidence_count=len(rows), maturity=_text(div.get("maturity"), mature), explanation="Average paper candidate fit after concentration/correlation pressure."),
            "largest_cluster": _text(div.get("largest_cluster"), "unknown_cluster"),
            "top_duplicate_theme": _text(div.get("top_duplicate_theme"), "unknown"),
            "current_portfolio_balance_label": _text(div.get("current_portfolio_balance_label"), "warming_up"),
            "portfolio_balance_summary": _text(regime.get("portfolio_balance_summary") or tm.get("portfolio_risk_summary"), "Waiting for portfolio diagnostics."),
        }

    def _learning_maturity_summary(self, statuses: dict[str, dict[str, Any]], paper: dict[str, Any], evidence_count: int, maturity: dict[str, Any]) -> dict[str, Any]:
        replay = statuses.get("replay_lifecycle_expectancy") or {}
        adaptive = statuses.get("adaptive_learning_infrastructure") or {}
        coverage = _first_float(replay.get("lifecycle_tracking_quality_score"), paper.get("completed_trade_coverage_pct"), default=0.0)
        return {
            "replay_maturity": _metric(replay.get("replay_learning_maturity_score"), evidence_count=evidence_count, maturity="healthy" if replay.get("replay_learning_ready") else "awaiting_replay_data"),
            "lifecycle_maturity": _metric(replay.get("lifecycle_tracking_quality_score"), evidence_count=evidence_count, maturity="healthy" if replay.get("lifecycle_tracking_ready") else "awaiting_lifecycle_outcomes"),
            "expectancy_maturity": _metric(replay.get("expectancy_learning_maturity_score"), evidence_count=evidence_count, maturity="healthy" if replay.get("expectancy_learning_ready") else maturity.get("label", "insufficient_evidence")),
            "closed_trade_coverage": _metric(coverage if coverage > 0 else None, evidence_count=evidence_count, maturity=maturity.get("label", "insufficient_evidence")),
            "adaptive_confidence": _metric(adaptive.get("learning_readiness_score"), evidence_count=evidence_count, maturity=maturity.get("label", "insufficient_evidence")),
            "learning_loop_summary": _text(replay.get("learning_loop_summary") or adaptive.get("adaptive_learning_summary"), maturity.get("explanation")),
        }

    def _regime_context_summary(self, statuses: dict[str, dict[str, Any]], rows: list[dict[str, Any]], history: list[dict[str, Any]], maturity: dict[str, Any]) -> dict[str, Any]:
        regime = statuses.get("regime_execution_survivability") or {}
        edge = statuses.get("edge_development") or {}
        current = _text(regime.get("current_market_regime"), "uncertain_regime")
        best_arch = _text(edge.get("best_current_archetype") or regime.get("strongest_survivability_archetype"), "insufficient_data")
        posture = _text((statuses.get("market_session_execution_timing") or {}).get("open_confirmation_label"), "guarded")
        return {
            "current_regime": current,
            "regime_alignment": _metric(regime.get("regime_trade_alignment_score"), evidence_count=max(len(rows), len(history)), maturity="healthy" if rows else maturity.get("label", "insufficient_evidence")),
            "best_archetype": best_arch,
            "operating_posture": posture,
            "strongest_regime": _text(regime.get("strongest_regime"), "insufficient_data"),
            "weakest_regime": _text(regime.get("weakest_regime"), "insufficient_data"),
            "regime_behavior_summary": _text(regime.get("regime_behavior_summary"), "Waiting for regime evidence."),
        }

    def _horizon_coverage_summary(
        self,
        statuses: dict[str, dict[str, Any]],
        history_rows: list[dict[str, Any]],
        paper_path_gating_status: dict[str, Any],
    ) -> dict[str, Any]:
        horizon_dashboard = dict(statuses.get("horizon_performance_dashboard") or {})
        multi_horizon = dict(statuses.get("multi_horizon_paper_trading") or {})
        profit_capture_validation = dict(statuses.get("profit_capture_peak_decay_exit_validation_suite_v1") or {})
        shadow_lab = dict(statuses.get("realistic_shadow_evidence_learning_lab_v1") or {})
        paper_trace = dict(statuses.get("paper_execution_trace") or {})
        paper_autopilot = dict(statuses.get("paper_autopilot_throughput") or {})

        closed_rows = [
            row for row in history_rows
            if _return_pct(row) != 0 or _text(row.get("closed_at") or row.get("exit_timestamp") or row.get("exit_timestamp_utc"), "") != ""
        ]
        bucket_defs: list[tuple[str, float, float | None]] = [
            ("15m", 0.0, 15.0),
            ("30m", 15.0, 30.0),
            ("45m", 30.0, 45.0),
            ("60m", 45.0, 60.0),
            ("2h", 60.0, 120.0),
            ("4h", 120.0, 240.0),
            ("eod", 240.0, 390.0),
            ("1d", 390.0, 1440.0),
            ("2d", 1440.0, 2880.0),
            ("3d", 2880.0, 4320.0),
            ("5d", 4320.0, 7200.0),
            ("10d", 7200.0, 14400.0),
            ("10d_plus", 14400.0, None),
        ]
        bucket_counts = {label: 0 for label, *_ in bucket_defs}
        minute_values: list[float] = []
        for row in closed_rows:
            minutes = _hold_minutes(row)
            if minutes <= 0:
                continue
            minute_values.append(minutes)
            for label, lower, upper in bucket_defs:
                if minutes > lower and (upper is None or minutes <= upper):
                    bucket_counts[label] += 1
                    break

        total_bucketed = sum(bucket_counts.values())
        scalp_count = sum(bucket_counts[label] for label in ("15m", "30m", "45m", "60m"))
        day_count = sum(bucket_counts[label] for label in ("2h", "4h", "eod"))
        swing_count = sum(bucket_counts[label] for label in ("1d", "2d", "3d", "5d", "10d", "10d_plus"))
        scalp_pct = round((scalp_count / total_bucketed) * 100.0, 2) if total_bucketed else 0.0
        day_pct = round((day_count / total_bucketed) * 100.0, 2) if total_bucketed else 0.0
        swing_pct = round((swing_count / total_bucketed) * 100.0, 2) if total_bucketed else 0.0
        coarse_counts = {
            "scalp": _to_int((horizon_dashboard.get("scalp") or {}).get("closed_sample_size"), _to_int((horizon_dashboard.get("scalp") or {}).get("sample_size"), _to_int((horizon_dashboard.get("scalp") or {}).get("natural_exit_count"), _to_int((multi_horizon.get("scalp_closures_today") or multi_horizon.get("scalp_entries_today")), 0)))),
            "day_trade": _to_int((horizon_dashboard.get("day_trade") or {}).get("closed_sample_size"), _to_int((horizon_dashboard.get("day_trade") or {}).get("sample_size"), _to_int((horizon_dashboard.get("day_trade") or {}).get("natural_exit_count"), _to_int((multi_horizon.get("day_trade_closures_today") or multi_horizon.get("day_trade_entries_today")), 0)))),
            "swing_trade": _to_int((horizon_dashboard.get("swing_trade") or {}).get("closed_sample_size"), _to_int((horizon_dashboard.get("swing_trade") or {}).get("sample_size"), _to_int((horizon_dashboard.get("swing_trade") or {}).get("natural_exit_count"), _to_int((multi_horizon.get("swing_trade_closures_today") or multi_horizon.get("swing_trade_entries_today")), 0)))),
        }
        coarse_tested_horizons = [label for label, count in coarse_counts.items() if count > 0]
        coarse_missing_horizons = [label for label, count in coarse_counts.items() if count <= 0]
        fine_tested_horizons = [label for label, count in bucket_counts.items() if count > 0]
        fine_missing_horizons = [label for label, count in bucket_counts.items() if count <= 0]
        tested_horizons = coarse_tested_horizons + [label for label in fine_tested_horizons if label not in coarse_tested_horizons]
        missing_horizons = {
            "coarse": coarse_missing_horizons,
            "fine": fine_missing_horizons,
        }
        dominant_horizon = max(coarse_counts.items(), key=lambda kv: kv[1])[0] if any(v > 0 for v in coarse_counts.values()) else _text(multi_horizon.get("best_current_horizon"), _text(horizon_dashboard.get("best_current_horizon"), "insufficient_data"))
        best_horizon = _text(horizon_dashboard.get("best_current_horizon"), _text(multi_horizon.get("best_current_horizon"), dominant_horizon))
        weakest_horizon = _text(horizon_dashboard.get("weakest_current_horizon"), _text(multi_horizon.get("weakest_current_horizon"), "insufficient_data"))

        support_map = {
            "scalp": bool((profit_capture_validation.get("best_hold_duration_by_horizon") or {}).get("scalp") or (profit_capture_validation.get("best_exit_policy_by_horizon") or {}).get("scalp")),
            "day_trade": bool((profit_capture_validation.get("best_hold_duration_by_horizon") or {}).get("day_trade") or (profit_capture_validation.get("best_exit_policy_by_horizon") or {}).get("day_trade")),
            "swing_trade": bool((profit_capture_validation.get("best_hold_duration_by_horizon") or {}).get("swing") or (profit_capture_validation.get("best_hold_duration_by_horizon") or {}).get("swing_trade") or (profit_capture_validation.get("best_exit_policy_by_horizon") or {}).get("swing") or (profit_capture_validation.get("best_exit_policy_by_horizon") or {}).get("swing_trade")),
        }
        shadow_horizon_balance = _to_float(multi_horizon.get("multi_horizon_learning_score"), _to_float(horizon_dashboard.get("multi_horizon_learning_score"), 0.0))
        shadow_support_score = _clamp((shadow_horizon_balance * 0.6) + (100.0 if any(support_map.values()) else 35.0) * 0.4)

        paper_horizon_bias = "balanced_mix"
        if coarse_counts.get("swing_trade", 0) >= max(coarse_counts.get("scalp", 0), coarse_counts.get("day_trade", 0)) and coarse_counts.get("swing_trade", 0) > 0:
            paper_horizon_bias = "swing_trade_bias"
        elif coarse_counts.get("day_trade", 0) >= max(coarse_counts.get("scalp", 0), coarse_counts.get("swing_trade", 0)) and coarse_counts.get("day_trade", 0) > 0:
            paper_horizon_bias = "day_trade_bias"
        elif coarse_counts.get("scalp", 0) > 0:
            paper_horizon_bias = "scalp_bias"

        learned_exits_applied = bool(paper_path_gating_status.get("learned_exits_applied", False))
        natural_exit_preserved = bool(
            paper_path_gating_status.get("natural_exit_preserved", True)
            and bool((statuses.get("alpaca_paper_broker") or {}).get("natural_exit_preserved", True))
        )
        horizon_mismatch_risk = 0.0
        if paper_horizon_bias == "swing_trade_bias":
            horizon_mismatch_risk += 20.0
        if weakest_horizon == "day_trade":
            horizon_mismatch_risk += 15.0
        if scalp_pct < 10.0:
            horizon_mismatch_risk += 10.0
        if day_pct < 10.0:
            horizon_mismatch_risk += 10.0
        if swing_pct >= 60.0:
            horizon_mismatch_risk += 10.0
        if not learned_exits_applied and natural_exit_preserved:
            horizon_mismatch_risk += 15.0
        if _to_float(profit_capture_validation.get("hold_duration_quality_score"), 0.0) < 45.0:
            horizon_mismatch_risk += 10.0
        if _text(shadow_lab.get("best_horizon"), "") == "hold_duration":
            horizon_mismatch_risk += 5.0
        horizon_mismatch_risk = _clamp(horizon_mismatch_risk)

        if paper_horizon_bias == "swing_trade_bias":
            why_positions_hold_long = "Paper horizons are biased toward swing/long-hold observations, and learned exits remain shadow-only under natural_exit_preserved=true."
        elif not learned_exits_applied:
            why_positions_hold_long = "Learned exits are still shadow-only, so paper positions continue to follow natural exits rather than horizon-specific exit recommendations."
        else:
            why_positions_hold_long = "Paper exits are using the current natural-exit path; horizon-specific recommendations are not yet behavior-applied."

        if scalp_pct < day_pct and scalp_pct < swing_pct:
            next_test = "Expand 15m-60m scalp coverage and compare against current natural-exit holds."
        elif day_pct < swing_pct:
            next_test = "Expand 2h-EOD day-trade coverage and compare against the current swing bias."
        else:
            next_test = "Increase 1d-10d swing coverage and keep learned exits shadow-only."

        return {
            "enabled": True,
            "horizon_coverage_status": "observed_and_shadow_compared",
            "tested_horizons": tested_horizons,
            "missing_horizons": missing_horizons,
            "observed_hold_bucket_counts": bucket_counts,
            "scalp_coverage_count": scalp_count,
            "day_coverage_count": day_count,
            "swing_coverage_count": swing_count,
            "scalp_coverage_pct": scalp_pct,
            "day_coverage_pct": day_pct,
            "swing_coverage_pct": swing_pct,
            "horizon_bucket_total": int(total_bucketed),
            "median_hold_minutes": round(_to_float(sorted(minute_values)[len(minute_values) // 2] if minute_values else 0.0), 2) if minute_values else 0.0,
            "mean_hold_minutes": round(_to_float(sum(minute_values) / len(minute_values) if minute_values else 0.0), 2) if minute_values else 0.0,
            "coarse_horizon_counts": coarse_counts,
            "coarse_tested_horizons": coarse_tested_horizons,
            "coarse_missing_horizons": coarse_missing_horizons,
            "fine_hold_buckets_tested": fine_tested_horizons,
            "fine_hold_buckets_missing": fine_missing_horizons,
            "paper_entries_today_by_horizon": {
                "scalp": _to_int((multi_horizon.get("scalp_entries_today")), 0),
                "day_trade": _to_int((multi_horizon.get("day_trade_entries_today")), 0),
                "swing_trade": _to_int((multi_horizon.get("swing_trade_entries_today")), 0),
            },
            "paper_closures_today_by_horizon": {
                "scalp": _to_int((multi_horizon.get("scalp_closures_today")), 0),
                "day_trade": _to_int((multi_horizon.get("day_trade_closures_today")), 0),
                "swing_trade": _to_int((multi_horizon.get("swing_trade_closures_today")), 0),
            },
            "shadow_horizon_support": support_map,
            "shadow_horizon_balance": round(shadow_horizon_balance, 3),
            "shadow_support_score": round(shadow_support_score, 2),
            "paper_horizon_bias": paper_horizon_bias,
            "dominant_horizon": dominant_horizon,
            "best_horizon": best_horizon,
            "weakest_horizon": weakest_horizon,
            "horizon_mismatch_risk_score": round(horizon_mismatch_risk, 2),
            "horizon_mismatch_risk_label": "high" if horizon_mismatch_risk >= 65 else "moderate" if horizon_mismatch_risk >= 35 else "low",
            "learned_exits_applied": learned_exits_applied,
            "learned_horizon_status": "shadow_only_not_applied" if not learned_exits_applied else "paper_ready_candidate",
            "natural_exit_preserved": natural_exit_preserved,
            "why_positions_hold_long": why_positions_hold_long,
            "next_recommended_horizon_test": next_test,
            "shadow_recommendation": "Keep horizon learning shadow-only while expanding missing minute buckets and comparing against the current swing bias.",
        }

    def _adaptive_execution_exit_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_learning"),
            "maturity": _text(data.get("maturity"), "insufficient_lifecycle_data"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "execution_posture": _text(data.get("execution_posture"), "confirmation_required"),
            "exit_quality": data.get("exit_quality"),
            "continuation_quality": data.get("continuation_quality"),
            "chase_risk": data.get("chase_risk"),
            "adaptive_profitability": data.get("adaptive_profitability"),
            "lifecycle_stability": data.get("lifecycle_stability"),
            "strongest_adaptive_behavior": _text(data.get("strongest_adaptive_behavior"), "insufficient_data"),
            "biggest_weakness": _text(data.get("biggest_weakness"), "insufficient_lifecycle_data"),
            "summary": _text(data.get("summary"), "Adaptive execution and exit diagnostics are warming up."),
            "adaptive_execution_intelligence": dict(data.get("execution_timing_diagnostics") or {}),
            "exit_intelligence_v2": dict(data.get("adaptive_exit_diagnostics") or {}),
            "regime_adaptive_trading": dict(data.get("regime_adaptation_diagnostics") or {}),
            "lifecycle_adaptation": dict(data.get("lifecycle_adaptation_diagnostics") or {}),
            "profitability_improvement_diagnostics": dict(data.get("profitability_improvement_diagnostics") or {}),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "stale": bool(data.get("stale") or data.get("stale_cache")),
            "degraded_reason": _text(data.get("degraded_reason"), ""),
            "live_trading_changed": False,
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _mobile_runtime_compaction_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_display_compaction"),
            "mobile_runtime_compaction_active": bool(data.get("mobile_runtime_compaction_active", False)),
            "true_broker_active_positions": data.get("true_broker_active_positions"),
            "internal_open_workflow_rows": _to_int(data.get("internal_open_workflow_rows"), 0),
            "stale_internal_positions": _to_int(data.get("stale_internal_positions"), 0),
            "display_active_positions_count": _to_int(data.get("display_active_positions_count"), 0),
            "active_positions_preview_limit": _to_int(data.get("active_positions_preview_limit"), 5),
            "recent_orders_preview_limit": _to_int(data.get("recent_orders_preview_limit"), 5),
            "canceled_orders_compacted_count": _to_int(data.get("canceled_orders_compacted_count"), 0),
            "stale_rows_hidden_count": _to_int(data.get("stale_rows_hidden_count"), 0),
            "learning_fast_path_active": bool(data.get("learning_fast_path_active", False)),
            "canceled_order_scan_skipped": bool(data.get("canceled_order_scan_skipped", True)),
            "learning_payload_compacted": bool(data.get("learning_payload_compacted", False)),
            "mobile_payload_compacted": bool(data.get("mobile_payload_compacted", False)),
            "full_history_preserved": bool(data.get("full_history_preserved", True)),
            "replay_learning_preserved": bool(data.get("replay_learning_preserved", True)),
            "summary": _text(data.get("summary"), "Mobile runtime compaction diagnostics are warming up."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
        }

    def _profit_seeking_exploration_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_calibration"),
            "controlled_exploration_enabled": bool(data.get("controlled_exploration_enabled", True)),
            "exploration_mode": _text(data.get("exploration_mode"), "profit_seeking"),
            "exploration_randomness_allowed": bool(data.get("exploration_randomness_allowed", False)),
            "participation_quality_score": data.get("participation_quality_score"),
            "caution_aggression_balance_score": data.get("caution_aggression_balance_score"),
            "caution_aggression_label": _text(data.get("caution_aggression_label"), "insufficient_evidence"),
            "over_cautious_risk": data.get("over_cautious_risk"),
            "under_cautious_risk": data.get("under_cautious_risk"),
            "missed_opportunity_pressure": data.get("missed_opportunity_pressure"),
            "learning_diversity_score": data.get("learning_diversity_score"),
            "exploration_trades_allowed_today": _to_int(data.get("exploration_trades_allowed_today"), _to_int(data.get("exploration_max_new_trades_per_day"), 0)),
            "exploration_trades_used_today": _to_int(data.get("exploration_trades_used_today"), 0),
            "underexplored_contexts": list(data.get("underexplored_contexts") or [])[:8],
            "overexplored_contexts": list(data.get("overexplored_contexts") or [])[:8],
            "exploration_allocation_pct": _to_float(data.get("exploration_allocation_pct"), 0.0),
            "exploitation_allocation_pct": _to_float(data.get("exploitation_allocation_pct"), 100.0),
            "exploration_decay_active": bool(data.get("exploration_decay_active", True)),
            "exploration_decay_reason": _text(data.get("exploration_decay_reason"), "warming_up"),
            "adaptive_exploration_recommendation": _text(data.get("adaptive_exploration_recommendation"), "maintain_bounded_profit_seeking_exploration"),
            "summary": _text(data.get("summary"), "Profit-seeking exploration diagnostics are warming up."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _market_calendar_knowledge_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "market_calendar_available": bool(data.get("market_calendar_available", False)),
            "market_calendar_source": _text(data.get("market_calendar_source"), "local_estimate"),
            "market_calendar_cache_hit": bool(data.get("market_calendar_cache_hit", False)),
            "market_calendar_stale": bool(data.get("market_calendar_stale", False)),
            "current_session_type": _text(data.get("current_session_type") or data.get("market_session_mode"), "unknown_closed"),
            "session_tradable": bool(data.get("session_tradable") or data.get("market_is_tradable")),
            "broker_order_submission_allowed": bool(data.get("broker_order_submission_allowed") or data.get("paper_order_submission_allowed")),
            "next_market_open": _text(data.get("next_market_open")),
            "next_market_close": _text(data.get("next_market_close")),
            "holiday_name": _text(data.get("holiday_name")),
            "is_market_holiday": bool(data.get("is_market_holiday", False)),
            "is_early_close": bool(data.get("is_early_close", False)),
            "early_close_time": _text(data.get("early_close_time")),
            "minutes_until_open": data.get("minutes_until_open"),
            "minutes_until_close": data.get("minutes_until_close"),
            "session_risk_label": _text(data.get("session_risk_label"), "unknown"),
            "session_risk_score": data.get("session_risk_score"),
            "session_execution_posture": _text(data.get("session_execution_posture"), "observe_only_execution_intent"),
            "session_confirmation_requirement": _text(data.get("session_confirmation_requirement"), "market_open_confirmation_required"),
            "market_structure_label": _text(data.get("market_structure_label"), "unknown"),
            "trade_style_environment": _text(data.get("trade_style_environment"), "unknown"),
            "behavioral_market_state": _text(data.get("behavioral_market_state"), "unknown"),
            "market_context_summary": _text(data.get("market_context_summary"), "Market context diagnostics are warming up."),
            "market_knowledge_confidence": data.get("market_knowledge_confidence"),
            "market_context_supports_exploration": bool(data.get("market_context_supports_exploration", False)),
            "exploration_context_quality": data.get("exploration_context_quality"),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
        }

    def _broad_universe_intake_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_candidate_promotion"),
            "broad_universe_pipeline_active": bool(data.get("broad_universe_pipeline_active", False)),
            "broad_universe_size": _to_int(data.get("broad_universe_size"), 0),
            "tradable_universe_size": _to_int(data.get("tradable_universe_size"), 0),
            "universe_source": _text(data.get("universe_source"), "local_cache"),
            "universe_cache_hit": bool(data.get("universe_cache_hit", False)),
            "universe_stale": bool(data.get("universe_stale", False)),
            "scan_slice_size": _to_int(data.get("scan_slice_size"), 0),
            "scan_slice_index": _to_int(data.get("scan_slice_index"), 0),
            "scan_slice_total": _to_int(data.get("scan_slice_total"), 0),
            "symbols_scanned_this_cycle": _to_int(data.get("symbols_scanned_this_cycle"), 0),
            "symbols_scanned_today": _to_int(data.get("symbols_scanned_today"), 0),
            "universe_coverage_today_pct": _to_float(data.get("universe_coverage_today_pct"), 0.0),
            "candidates_detected": _to_int(data.get("candidates_detected"), 0),
            "lightweight_scored_count": _to_int(data.get("lightweight_scored_count"), 0),
            "shortlist_count": _to_int(data.get("shortlist_count"), 0),
            "deep_scored_count": _to_int(data.get("deep_scored_count"), 0),
            "promoted_to_top_buys_count": _to_int(data.get("promoted_to_top_buys_count"), 0),
            "promoted_symbols": list(data.get("promoted_symbols") or [])[:20],
            "promoted_cap_distribution": dict(data.get("promoted_cap_distribution") or {}),
            "promoted_sector_distribution": dict(data.get("promoted_sector_distribution") or {}),
            "fmp_usage_pct": _to_float(data.get("fmp_usage_pct"), 0.0),
            "fmp_bandwidth_used_gb": _to_float(data.get("fmp_bandwidth_used_gb"), 0.0),
            "fmp_bandwidth_limit_gb": _to_float(data.get("fmp_bandwidth_limit_gb"), 50.0),
            "fmp_budget_state": _text(data.get("fmp_budget_state"), "degraded_unknown_usage"),
            "current_learning_bias": _text(data.get("current_learning_bias"), "warming_up"),
            "next_scan_focus": _text(data.get("next_scan_focus"), "quality_rotation"),
            "learning_diversity_improved": bool(data.get("learning_diversity_improved", False)),
            "summary": _text(
                data.get("summary"),
                f"Broad universe scanned {_to_int(data.get('symbols_scanned_this_cycle'), 0)} symbols and promoted {_to_int(data.get('promoted_to_top_buys_count'), 0)} bounded candidates.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
        }

    def _trade_lifecycle_excursion_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        tracked_total = _to_int(data.get("total_tracked_lifecycles"), 0)
        maturity = _text(data.get("maturity"), "warming_up" if tracked_total else "awaiting_lifecycle_outcomes")
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_lifecycle_observability"),
            "maturity": maturity,
            "tracked_active_trades": _to_int(data.get("tracked_active_trades"), 0),
            "tracked_closed_trades": _to_int(data.get("tracked_closed_trades"), 0),
            "total_tracked_lifecycles": tracked_total,
            "average_mfe_pct": data.get("average_mfe_pct"),
            "average_mae_pct": data.get("average_mae_pct"),
            "average_profit_giveback_pct": data.get("average_profit_giveback_pct"),
            "average_hold_duration_minutes": data.get("average_hold_duration_minutes"),
            "follow_through_quality_score": data.get("follow_through_quality_score"),
            "exit_quality_score": data.get("exit_quality_score"),
            "profit_capture_quality": data.get("profit_capture_quality"),
            "exit_label_distribution": dict(data.get("exit_label_distribution") or {}),
            "follow_through_distribution": dict(data.get("follow_through_distribution") or {}),
            "strongest_follow_through_context": _text(data.get("strongest_follow_through_context"), "insufficient_evidence"),
            "weakest_follow_through_context": _text(data.get("weakest_follow_through_context"), "insufficient_evidence"),
            "premature_exit_count": _to_int(data.get("premature_exit_count"), 0),
            "overstayed_exit_count": _to_int(data.get("overstayed_exit_count"), 0),
            "learning_ready": bool(data.get("learning_ready", False)),
            "summary": _text(
                data.get("summary"),
                "Trade lifecycle excursion telemetry is waiting for active or naturally closed paper trades.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
        }

    def _trade_lifecycle_excursion_v2_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        tracked_total = _to_int(data.get("total_tracked_lifecycles"), 0)
        maturity = _text(data.get("maturity"), "warming_up" if tracked_total else "awaiting_lifecycle_outcomes")
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "mode": _text(data.get("mode"), "paper_only_lifecycle_learning_v2"),
            "maturity": maturity,
            "tracked_active_trades": _to_int(data.get("tracked_active_trades"), 0),
            "tracked_closed_trades": _to_int(data.get("tracked_closed_trades"), 0),
            "total_tracked_lifecycles": tracked_total,
            "average_mfe_pct": data.get("average_mfe_pct"),
            "average_mae_pct": data.get("average_mae_pct"),
            "average_profit_giveback_pct": data.get("average_profit_giveback_pct"),
            "average_profit_capture_ratio": data.get("average_profit_capture_ratio"),
            "average_giveback_after_mfe": data.get("average_giveback_after_mfe"),
            "average_hold_duration_minutes": data.get("average_hold_duration_minutes"),
            "average_hold_duration_quality": data.get("average_hold_duration_quality"),
            "average_exit_quality": data.get("average_exit_quality"),
            "average_exit_efficiency": data.get("average_exit_efficiency"),
            "average_follow_through_quality": data.get("average_follow_through_quality"),
            "high_giveback_trade_count": _to_int(data.get("high_giveback_trade_count"), 0),
            "premature_exit_count": _to_int(data.get("premature_exit_count"), 0),
            "overstayed_exit_count": _to_int(data.get("overstayed_exit_count"), 0),
            "stop_loss_exit_count": _to_int(data.get("stop_loss_exit_count"), 0),
            "profit_protection_exit_count": _to_int(data.get("profit_protection_exit_count"), 0),
            "exit_label_distribution": dict(data.get("exit_label_distribution") or {}),
            "follow_through_distribution": dict(data.get("follow_through_distribution") or {}),
            "best_follow_through_context": _text(data.get("best_follow_through_context"), "insufficient_evidence"),
            "weakest_follow_through_context": _text(data.get("weakest_follow_through_context"), "insufficient_evidence"),
            "best_hold_duration_context": _text(data.get("best_hold_duration_context"), "insufficient_evidence"),
            "weakest_hold_duration_context": _text(data.get("weakest_hold_duration_context"), "insufficient_evidence"),
            "best_profit_capture_context": _text(data.get("best_profit_capture_context"), "insufficient_evidence"),
            "weakest_profit_capture_context": _text(data.get("weakest_profit_capture_context"), "insufficient_evidence"),
            "strongest_continuation_archetype": _text(data.get("strongest_continuation_archetype"), "insufficient_evidence"),
            "weakest_continuation_archetype": _text(data.get("weakest_continuation_archetype"), "insufficient_evidence"),
            "symbols_with_best_continuation": list(data.get("symbols_with_best_continuation") or [])[:5],
            "symbols_with_worst_giveback": list(data.get("symbols_with_worst_giveback") or [])[:5],
            "best_profit_capture_symbol": _text(data.get("best_profit_capture_symbol"), "insufficient_evidence"),
            "worst_giveback_symbol": _text(data.get("worst_giveback_symbol"), "insufficient_evidence"),
            "learning_readiness": _text(data.get("learning_readiness"), "warming_up"),
            "learning_ready": bool(data.get("learning_ready", False)),
            "summary": _text(
                data.get("summary"),
                "Trade lifecycle V2 is waiting for active or naturally closed paper lifecycle evidence.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
        }

    def _adaptive_profit_capture_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_profit_capture_learning"),
            "tracked_lifecycles": _to_int(data.get("tracked_lifecycles"), 0),
            "active_trades_reviewed": _to_int(data.get("active_trades_reviewed"), 0),
            "closed_trades_reviewed": _to_int(data.get("closed_trades_reviewed"), 0),
            "average_profit_capture_ratio": data.get("average_profit_capture_ratio"),
            "average_profit_giveback_pct": data.get("average_profit_giveback_pct"),
            "average_missed_profit_pct": data.get("average_missed_profit_pct"),
            "average_profit_retention_score": data.get("average_profit_retention_score"),
            "profit_capture_quality_score": data.get("profit_capture_quality_score"),
            "high_giveback_trade_count": _to_int(data.get("high_giveback_trade_count"), 0),
            "excellent_capture_count": _to_int(data.get("excellent_capture_count"), 0),
            "weak_capture_count": _to_int(data.get("weak_capture_count"), 0),
            "severe_giveback_count": _to_int(data.get("severe_giveback_count"), 0),
            "best_profit_capture_context": _text(data.get("best_profit_capture_context"), "insufficient_data"),
            "weakest_profit_capture_context": _text(data.get("weakest_profit_capture_context"), "insufficient_data"),
            "best_profit_capture_symbol": _text(data.get("best_profit_capture_symbol"), "insufficient_data"),
            "worst_profit_capture_symbol": _text(data.get("worst_profit_capture_symbol"), "insufficient_data"),
            "worst_giveback_symbol": _text(data.get("worst_giveback_symbol"), "insufficient_data"),
            "top_giveback_patterns": dict(data.get("top_giveback_patterns") or {}),
            "most_common_giveback_pattern": _text(data.get("most_common_giveback_pattern"), "insufficient_data"),
            "open_position_watchlist": list(data.get("open_position_watchlist") or [])[:12],
            "open_position_watchlist_count": _to_int(data.get("open_position_watchlist_count"), len(data.get("open_position_watchlist") or [])),
            "profit_capture_recommendation": _text(data.get("profit_capture_recommendation"), "insufficient_data"),
            "profit_capture_reason": _text(data.get("profit_capture_reason"), "Waiting for profit-capture evidence."),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "summary": _text(data.get("summary"), "Adaptive profit capture intelligence is collecting lifecycle evidence."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
        }

    def _adaptive_execution_exit_v3_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "3.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_exit_learning"),
            "tracked_trades": _to_int(data.get("tracked_trades"), 0),
            "closed_trades_reviewed": _to_int(data.get("closed_trades_reviewed"), 0),
            "open_trades_reviewed": _to_int(data.get("open_trades_reviewed"), 0),
            "profit_capture_score": data.get("profit_capture_score"),
            "avg_peak_gain": data.get("avg_peak_gain"),
            "avg_exit_gain": data.get("avg_exit_gain"),
            "avg_current_gain": data.get("avg_current_gain"),
            "avg_giveback": data.get("avg_giveback"),
            "median_giveback": data.get("median_giveback"),
            "avg_capture_ratio": data.get("avg_capture_ratio"),
            "capture_ratio": data.get("capture_ratio"),
            "capture_ratio_by_horizon": dict(data.get("capture_ratio_by_horizon") or {}),
            "capture_ratio_by_archetype": dict(data.get("capture_ratio_by_archetype") or {}),
            "capture_ratio_by_regime": dict(data.get("capture_ratio_by_regime") or {}),
            "worst_giveback_symbols": list(data.get("worst_giveback_symbols") or [])[:8],
            "best_capture_symbols": list(data.get("best_capture_symbols") or [])[:8],
            "open_vs_closed_capture": dict(data.get("open_vs_closed_capture") or {}),
            "strongest_exit_context": _text(data.get("strongest_exit_context"), "insufficient_data"),
            "weakest_exit_context": _text(data.get("weakest_exit_context"), "insufficient_data"),
            "biggest_giveback_context": _text(data.get("biggest_giveback_context"), "insufficient_data"),
            "best_profit_retention_context": _text(data.get("best_profit_retention_context"), "insufficient_data"),
            "protect_gains_sooner_context": _text(data.get("protect_gains_sooner_context"), "insufficient_data"),
            "hold_longer_context": _text(data.get("hold_longer_context"), "insufficient_data"),
            "horizon_profitability": dict(data.get("horizon_profitability") or {}),
            "most_profitable_horizon": _text(data.get("most_profitable_horizon"), "insufficient_data"),
            "safest_horizon": _text(data.get("safest_horizon"), "insufficient_data"),
            "highest_frequency_horizon": _text(data.get("highest_frequency_horizon"), "insufficient_data"),
            "highest_giveback_horizon": _text(data.get("highest_giveback_horizon"), "insufficient_data"),
            "best_risk_adjusted_horizon": _text(data.get("best_risk_adjusted_horizon"), "insufficient_data"),
            "horizon_allocation_recommendation": _text(data.get("horizon_allocation_recommendation"), "insufficient_data"),
            "continued_after_profit_count": _to_int(data.get("continued_after_profit_count"), 0),
            "faded_after_profit_count": _to_int(data.get("faded_after_profit_count"), 0),
            "reversed_after_profit_count": _to_int(data.get("reversed_after_profit_count"), 0),
            "average_time_to_peak": data.get("average_time_to_peak"),
            "average_time_from_peak_to_exit": data.get("average_time_from_peak_to_exit"),
            "peak_decay_rate": data.get("peak_decay_rate"),
            "continuation_probability": data.get("continuation_probability"),
            "peak_decay_risk": data.get("peak_decay_risk"),
            "hold_longer_score": data.get("hold_longer_score"),
            "protect_profit_score": data.get("protect_profit_score"),
            "shadow_exit_bias": _text(data.get("shadow_exit_bias"), "insufficient_data"),
            "shadow_exit_recommendations": list(data.get("shadow_exit_recommendations") or [])[:12],
            "shadow_only_recommendation": _text(data.get("shadow_only_recommendation"), "insufficient_data"),
            "summary": _text(data.get("summary"), "Adaptive Execution & Exit Intelligence V3 is collecting profit-capture evidence."),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "automatic_profit_taking_enabled": bool(data.get("automatic_profit_taking_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _exit_learning_expansion_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_exit_learning_expansion"),
            "tracked_trades": _to_int(data.get("tracked_trades"), 0),
            "best_partial_exit_variant": _text(data.get("best_partial_exit_variant"), "insufficient_data"),
            "partial_exit_profit_delta": data.get("partial_exit_profit_delta"),
            "partial_exit_capture_improvement": data.get("partial_exit_capture_improvement"),
            "partial_exit_confidence": data.get("partial_exit_confidence"),
            "partial_exit_recommendation": _text(data.get("partial_exit_recommendation"), "shadow_review_only"),
            "first_15_min_return": data.get("first_15_min_return"),
            "first_30_min_return": data.get("first_30_min_return"),
            "first_60_min_return": data.get("first_60_min_return"),
            "lunch_period_return": data.get("lunch_period_return"),
            "power_hour_return": data.get("power_hour_return"),
            "overnight_return": data.get("overnight_return"),
            "time_to_peak": data.get("time_to_peak"),
            "time_of_peak": _text(data.get("time_of_peak"), "insufficient_data"),
            "best_time_window": _text(data.get("best_time_window"), "insufficient_data"),
            "weakest_time_window": _text(data.get("weakest_time_window"), "insufficient_data"),
            "time_window_by_horizon": dict(data.get("time_window_by_horizon") or {}),
            "time_window_by_archetype": dict(data.get("time_window_by_archetype") or {}),
            "time_window_by_regime": dict(data.get("time_window_by_regime") or {}),
            "best_profit_window": _text(data.get("best_profit_window"), "insufficient_data"),
            "highest_giveback_window": _text(data.get("highest_giveback_window"), "insufficient_data"),
            "best_entry_to_exit_window": _text(data.get("best_entry_to_exit_window"), "insufficient_data"),
            "time_of_day_exit_bias": _text(data.get("time_of_day_exit_bias"), "insufficient_data"),
            "dominant_trade_personality": _text(data.get("dominant_trade_personality"), "insufficient_evidence"),
            "weakest_trade_personality": _text(data.get("weakest_trade_personality"), "insufficient_evidence"),
            "trade_personality_distribution": dict(data.get("trade_personality_distribution") or {}),
            "personality_best_exit_style": dict(data.get("personality_best_exit_style") or {}),
            "personality_giveback_risk": dict(data.get("personality_giveback_risk") or {}),
            "personality_hold_score": dict(data.get("personality_hold_score") or {}),
            "personality_profit_protection_score": dict(data.get("personality_profit_protection_score") or {}),
            "avg_profitable_hold_time": data.get("avg_profitable_hold_time"),
            "median_profitable_hold_time": data.get("median_profitable_hold_time"),
            "best_hold_duration": data.get("best_hold_duration"),
            "worst_hold_duration": data.get("worst_hold_duration"),
            "time_after_peak_before_decay": data.get("time_after_peak_before_decay"),
            "optimal_hold_window": _text(data.get("optimal_hold_window"), "insufficient_data"),
            "best_hold_window": _text(data.get("best_hold_window"), "insufficient_data"),
            "hold_too_short_count": _to_int(data.get("hold_too_short_count"), 0),
            "hold_too_long_count": _to_int(data.get("hold_too_long_count"), 0),
            "hold_longer_supported": bool(data.get("hold_longer_supported", False)),
            "exit_sooner_supported": bool(data.get("exit_sooner_supported", False)),
            "holding_time_confidence": data.get("holding_time_confidence"),
            "milestone_stats": dict(data.get("milestone_stats") or {}),
            "highest_decay_milestone": _text(data.get("highest_decay_milestone"), "insufficient_data"),
            "profit_decay_risk": data.get("profit_decay_risk"),
            "continuation_after_profit_score": data.get("continuation_after_profit_score"),
            "protect_profit_score": data.get("protect_profit_score"),
            "hold_longer_score": data.get("hold_longer_score"),
            "milestone_exit_bias": _text(data.get("milestone_exit_bias"), "insufficient_data"),
            "shadow_exit_learning_recommendation": _text(data.get("shadow_exit_learning_recommendation"), "insufficient_data"),
            "summary": _text(
                data.get("summary"),
                "Astra is studying partial exits, time-of-day behavior, trade personality, holding time, and profit decay without changing trading behavior.",
            ),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _market_context_learning_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_market_context_learning"),
            "tracked_symbols": _to_int(data.get("tracked_symbols"), 0),
            "tracked_trades": _to_int(data.get("tracked_trades"), 0),
            "context_records": _to_int(data.get("context_records"), 0),
            "premarket_profile_distribution": dict(data.get("premarket_profile_distribution") or {}),
            "catalyst_type_distribution": dict(data.get("catalyst_type_distribution") or {}),
            "after_hours_profile_distribution": dict(data.get("after_hours_profile_distribution") or {}),
            "strongest_premarket_profile": _text(data.get("strongest_premarket_profile"), "insufficient_data"),
            "weakest_premarket_profile": _text(data.get("weakest_premarket_profile"), "insufficient_data"),
            "dominant_catalyst_type": _text(data.get("dominant_catalyst_type"), "insufficient_data"),
            "strongest_catalyst_type": _text(data.get("strongest_catalyst_type"), "insufficient_data"),
            "weakest_catalyst_type": _text(data.get("weakest_catalyst_type"), "insufficient_data"),
            "strongest_after_hours_profile": _text(data.get("strongest_after_hours_profile"), "insufficient_data"),
            "highest_gap_fade_risk_profile": _text(data.get("highest_gap_fade_risk_profile"), "insufficient_data"),
            "best_context_horizon": _text(data.get("best_context_horizon"), "insufficient_data"),
            "highest_giveback_context": _text(data.get("highest_giveback_context"), "insufficient_data"),
            "context_confidence": _to_float(data.get("context_confidence"), 0.0),
            "premarket_momentum_score": data.get("premarket_momentum_score"),
            "gap_risk_score": data.get("gap_risk_score"),
            "premarket_continuation_probability": data.get("premarket_continuation_probability"),
            "premarket_giveback_risk": data.get("premarket_giveback_risk"),
            "overnight_momentum_score": data.get("overnight_momentum_score"),
            "gap_and_run_probability": data.get("gap_and_run_probability"),
            "gap_and_fade_probability": data.get("gap_and_fade_probability"),
            "historical_expectancy_by_catalyst": dict(data.get("historical_expectancy_by_catalyst") or {}),
            "average_hold_duration_by_catalyst": dict(data.get("average_hold_duration_by_catalyst") or {}),
            "giveback_risk_by_catalyst": dict(data.get("giveback_risk_by_catalyst") or {}),
            "best_horizon_by_catalyst": dict(data.get("best_horizon_by_catalyst") or {}),
            "profile_samples": list(data.get("profile_samples") or [])[:8],
            "shadow_context_recommendation": _text(data.get("shadow_context_recommendation"), "insufficient_data"),
            "summary": _text(
                data.get("summary"),
                "Astra is studying premarket, catalyst, and after-hours context without changing trading behavior.",
            ),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
        }

    def _profit_capture_peak_decay_exit_validation_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_profit_capture_peak_decay_exit_validation"),
            "tracked_trades": _to_int(data.get("tracked_trades"), 0),
            "average_capture_ratio": data.get("average_capture_ratio"),
            "average_giveback_pct": data.get("average_giveback_pct"),
            "capture_quality_score": _to_float(data.get("capture_quality_score"), 0.0),
            "highest_giveback_trade": _text(data.get("highest_giveback_trade"), "insufficient_data"),
            "best_capture_trade": _text(data.get("best_capture_trade"), "insufficient_data"),
            "strongest_profit_milestone": _text(data.get("strongest_profit_milestone"), "insufficient_data"),
            "weakest_profit_milestone": _text(data.get("weakest_profit_milestone"), "insufficient_data"),
            "continuation_failure_probability": _to_float(data.get("continuation_failure_probability"), 0.0),
            "strongest_failure_signal": _text(data.get("strongest_failure_signal"), "insufficient_data"),
            "best_hold_duration_by_horizon": dict(data.get("best_hold_duration_by_horizon") or {}),
            "capture_ratio_by_horizon": dict(data.get("capture_ratio_by_horizon") or {}),
            "giveback_by_horizon": dict(data.get("giveback_by_horizon") or {}),
            "continuation_by_horizon": dict(data.get("continuation_by_horizon") or {}),
            "horizon_exit_quality_score": _to_float(data.get("horizon_exit_quality_score"), 0.0),
            "strongest_horizon": _text(data.get("strongest_horizon"), "insufficient_data"),
            "weakest_horizon": _text(data.get("weakest_horizon"), "insufficient_data"),
            "hold_duration_quality_score": _to_float(data.get("hold_duration_quality_score"), 0.0),
            "best_exit_policy": _text(data.get("best_exit_policy"), "insufficient_data"),
            "second_best_exit_policy": _text(data.get("second_best_exit_policy"), "insufficient_data"),
            "highest_improvement_policy": _text(data.get("highest_improvement_policy"), "insufficient_data"),
            "most_consistent_policy": _text(data.get("most_consistent_policy"), "insufficient_data"),
            "weakest_policy": _text(data.get("weakest_policy"), "insufficient_data"),
            "best_exit_policy_by_horizon": dict(data.get("best_exit_policy_by_horizon") or {}),
            "closest_exit_policy_to_readiness": _text(data.get("closest_exit_policy_to_readiness"), "insufficient_data"),
            "readiness_score": _to_float(data.get("readiness_score"), 0.0),
            "readiness_blocker": _text(data.get("readiness_blocker"), "insufficient_data"),
            "policy_confidence": _to_float(data.get("policy_confidence"), 0.0),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Keep profit capture and exit validation shadow-only."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "cache_age_seconds": data.get("cache_age_seconds"),
            "cache_freshness": _text(data.get("cache_freshness"), "stale"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "bandwidth_saving_mode": bool(data.get("bandwidth_saving_mode", True)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _learning_acceleration_retention_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_learning_acceleration_retention"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "top_learning_priority": _text(data.get("top_learning_priority"), "insufficient_data"),
            "secondary_learning_priority": _text(data.get("secondary_learning_priority"), "insufficient_data"),
            "lowest_learning_priority": _text(data.get("lowest_learning_priority"), "insufficient_data"),
            "priority_reason": _text(data.get("priority_reason"), "Learning priority evidence is warming up."),
            "priority_confidence": _to_float(data.get("priority_confidence"), 0.0),
            "recommended_worker_focus": _text(data.get("recommended_worker_focus"), "collect_more_lifecycle_evidence"),
            "priority_scores": dict(data.get("priority_scores") or {}),
            "weighted_confidence_score": _to_float(data.get("weighted_confidence_score"), 0.0),
            "strongest_evidence_source": _text(data.get("strongest_evidence_source"), "insufficient_data"),
            "weakest_evidence_source": _text(data.get("weakest_evidence_source"), "insufficient_data"),
            "evidence_mix": dict(data.get("evidence_mix") or {}),
            "evidence_quality_label": _text(data.get("evidence_quality_label"), "warming_up"),
            "evidence_weighting_reason": _text(data.get("evidence_weighting_reason"), "Evidence weighting is warming up."),
            "consolidated_lessons_count": _to_int(data.get("consolidated_lessons_count"), 0),
            "promoted_lessons": list(data.get("promoted_lessons") or [])[:8],
            "tentative_lessons": list(data.get("tentative_lessons") or [])[:8],
            "retired_or_deprioritized_lessons": list(data.get("retired_or_deprioritized_lessons") or [])[:8],
            "strongest_new_lesson": _text(data.get("strongest_new_lesson"), "insufficient_data"),
            "overnight_consolidation_status": _text(data.get("overnight_consolidation_status"), "warming_up"),
            "knowledge_retention_score": _to_float(data.get("knowledge_retention_score"), 0.0),
            "strongest_coverage_area": _text(data.get("strongest_coverage_area"), "insufficient_data"),
            "weakest_coverage_area": _text(data.get("weakest_coverage_area"), "insufficient_data"),
            "underexplored_contexts": list(data.get("underexplored_contexts") or [])[:10],
            "overrepresented_contexts": list(data.get("overrepresented_contexts") or [])[:10],
            "coverage_score": _to_float(data.get("coverage_score"), 0.0),
            "recommended_evidence_collection_focus": _text(data.get("recommended_evidence_collection_focus"), "collect_more_lifecycle_evidence"),
            "strongest_cross_system_agreement": _text(data.get("strongest_cross_system_agreement"), "insufficient_data"),
            "agreement_score": _to_float(data.get("agreement_score"), 0.0),
            "agreeing_systems": list(data.get("agreeing_systems") or [])[:10],
            "disagreement_systems": list(data.get("disagreement_systems") or [])[:10],
            "confidence_boost_reason": _text(data.get("confidence_boost_reason"), "No strong cross-system agreement yet."),
            "cross_learning_summary": _text(data.get("cross_learning_summary"), "Cross-learning agreement is warming up."),
            "conflict_detected": bool(data.get("conflict_detected", False)),
            "conflict_type": _text(data.get("conflict_type"), "none"),
            "conflicting_systems": list(data.get("conflicting_systems") or [])[:10],
            "conflict_severity": _text(data.get("conflict_severity"), "none"),
            "likely_resolution": _text(data.get("likely_resolution"), "no_resolution_needed"),
            "recommended_human_review": bool(data.get("recommended_human_review", False)),
            "most_predictive_learning_system": _text(data.get("most_predictive_learning_system"), "insufficient_data"),
            "least_predictive_learning_system": _text(data.get("least_predictive_learning_system"), "insufficient_data"),
            "meta_learning_score": _to_float(data.get("meta_learning_score"), 0.0),
            "system_reliability_map": dict(data.get("system_reliability_map") or {}),
            "recommended_learning_weight_adjustments": dict(data.get("recommended_learning_weight_adjustments") or {}),
            "meta_learning_confidence": _to_float(data.get("meta_learning_confidence"), 0.0),
            "future_worker_contract": dict(data.get("future_worker_contract") or {}),
            "shadow_learning_recommendation": _text(data.get("shadow_learning_recommendation"), "keep_learning_changes_shadow_only"),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
        }

    def _adaptive_learning_infrastructure_suite_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_adaptive_learning_infrastructure"),
            "active_workers": list(data.get("active_workers") or [])[:8],
            "active_worker_count": _to_int(data.get("active_worker_count"), 0),
            "completed_jobs": _to_int(data.get("completed_jobs"), 0),
            "failed_jobs": _to_int(data.get("failed_jobs"), 0),
            "avg_worker_runtime": _to_float(data.get("avg_worker_runtime"), 0.0),
            "worker_efficiency_score": _to_float(data.get("worker_efficiency_score"), 0.0),
            "worker_health_status": _text(data.get("worker_health_status"), "warming_up"),
            "active_learning_priorities": list(data.get("active_learning_priorities") or [])[:8],
            "worker_queue_depth": _to_int(data.get("worker_queue_depth"), 0),
            "highest_priority_task": _text(data.get("highest_priority_task"), "collect_lifecycle_evidence"),
            "lowest_priority_task": _text(data.get("lowest_priority_task"), "insufficient_data"),
            "learning_load_score": _to_float(data.get("learning_load_score"), 0.0),
            "orchestration_health": _text(data.get("orchestration_health"), "warming_up"),
            "total_tasks": _to_int(data.get("total_tasks"), 0),
            "queue_distribution": dict(data.get("queue_distribution") or {}),
            "average_task_age": _to_float(data.get("average_task_age"), 0.0),
            "stale_task_count": _to_int(data.get("stale_task_count"), 0),
            "retry_count": _to_int(data.get("retry_count"), 0),
            "targeted_learning_area": _text(data.get("targeted_learning_area"), "profit_capture"),
            "evidence_gap_score": _to_float(data.get("evidence_gap_score"), 0.0),
            "evidence_collection_focus": _text(data.get("evidence_collection_focus"), "collect_more_lifecycle_evidence"),
            "collected_evidence_count": _to_int(data.get("collected_evidence_count"), 0),
            "evidence_counts_by_area": dict(data.get("evidence_counts_by_area") or {}),
            "api_budget_score": _to_float(data.get("api_budget_score"), 0.0),
            "wasted_calls_estimate": _to_int(data.get("wasted_calls_estimate"), 0),
            "highest_value_source": _text(data.get("highest_value_source"), "local_cached_learning"),
            "lowest_value_source": _text(data.get("lowest_value_source"), "none"),
            "cache_utilization": _to_float(data.get("cache_utilization"), 0.0),
            "health_score": _to_float(data.get("health_score"), 0.0),
            "timeout_count": _to_int(data.get("timeout_count"), 0),
            "stuck_jobs": _to_int(data.get("stuck_jobs"), 0),
            "cache_freshness": _to_float(data.get("cache_freshness"), 0.0),
            "worker_alerts": list(data.get("worker_alerts") or [])[:8],
            "strongest_coverage_area": _text(data.get("strongest_coverage_area"), "insufficient_data"),
            "weakest_coverage_area": _text(data.get("weakest_coverage_area"), "insufficient_data"),
            "underexplored_contexts": list(data.get("underexplored_contexts") or [])[:10],
            "recommended_focus": _text(data.get("recommended_focus"), "collect_more_lifecycle_evidence"),
            "coverage_breadth": dict(data.get("coverage_breadth") or {}),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "keep_learning_infrastructure_shadow_only"),
            "future_worker_contract": dict(data.get("future_worker_contract") or {}),
            "adaptive_worker_activation_compatible": bool(data.get("adaptive_worker_activation_compatible", True)),
            "adaptive_worker_activation_status": _text(data.get("adaptive_worker_activation_status"), "not_loaded"),
            "adaptive_worker_activation_focus": _text(data.get("adaptive_worker_activation_focus"), "collect_more_lifecycle_evidence"),
            "adaptive_worker_activation_active_workers": _to_int(data.get("adaptive_worker_activation_active_workers"), 0),
            "workers_started_by_dashboard": bool(data.get("workers_started_by_dashboard", False)),
            "dashboard_request_blocking": bool(data.get("dashboard_request_blocking", False)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
        }

    def _adaptive_worker_activation_orchestration_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_adaptive_worker_activation_orchestration"),
            "orchestrator_status": _text(data.get("orchestrator_status"), "warming_up"),
            "active_worker_count": _to_int(data.get("active_worker_count"), 0),
            "completed_jobs": _to_int(data.get("completed_jobs"), 0),
            "failed_jobs": _to_int(data.get("failed_jobs"), 0),
            "skipped_jobs": _to_int(data.get("skipped_jobs"), 0),
            "queue_depth": _to_int(data.get("queue_depth"), 0),
            "worker_efficiency_score": _to_float(data.get("worker_efficiency_score"), 0.0),
            "api_budget_score": _to_float(data.get("api_budget_score"), 0.0),
            "api_budget_used": _to_int(data.get("api_budget_used"), 0),
            "cache_hit_rate": _to_float(data.get("cache_hit_rate"), 0.0),
            "premarket_worker_status": _text(data.get("premarket_worker_status"), "warming_up"),
            "snapshots_collected": _to_int(data.get("snapshots_collected"), 0),
            "strongest_premarket_symbol": _text(data.get("strongest_premarket_symbol"), "insufficient_data"),
            "weakest_premarket_symbol": _text(data.get("weakest_premarket_symbol"), "insufficient_data"),
            "premarket_context_confidence": _to_float(data.get("premarket_context_confidence"), 0.0),
            "open_trade_worker_status": _text(data.get("open_trade_worker_status"), "waiting_for_open_trades"),
            "active_trades_monitored": _to_int(data.get("active_trades_monitored"), 0),
            "profit_decay_alerts": _to_int(data.get("profit_decay_alerts"), 0),
            "strongest_open_trade": _text(data.get("strongest_open_trade"), "insufficient_data"),
            "weakest_open_trade": _text(data.get("weakest_open_trade"), "insufficient_data"),
            "open_trade_learning_confidence": _to_float(data.get("open_trade_learning_confidence"), 0.0),
            "after_hours_worker_status": _text(data.get("after_hours_worker_status"), "warming_up"),
            "after_hours_snapshots_collected": _to_int(data.get("after_hours_snapshots_collected"), 0),
            "strongest_after_hours_symbol": _text(data.get("strongest_after_hours_symbol"), "insufficient_data"),
            "highest_gap_fade_risk_symbol": _text(data.get("highest_gap_fade_risk_symbol"), "insufficient_data"),
            "after_hours_context_confidence": _to_float(data.get("after_hours_context_confidence"), 0.0),
            "replay_worker_status": _text(data.get("replay_worker_status"), "warming_up"),
            "replay_jobs_completed": _to_int(data.get("replay_jobs_completed"), 0),
            "replay_learning_value": _to_float(data.get("replay_learning_value"), 0.0),
            "replay_runtime_ms": _to_float(data.get("replay_runtime_ms"), 0.0),
            "coverage_worker_status": _text(data.get("coverage_worker_status"), "warming_up"),
            "targeted_contexts": list(data.get("targeted_contexts") or [])[:8],
            "new_evidence_collected": _to_int(data.get("new_evidence_collected"), 0),
            "weakest_remaining_context": _text(data.get("weakest_remaining_context"), "insufficient_data"),
            "recommended_next_worker_focus": _text(data.get("recommended_next_worker_focus"), "collect_more_lifecycle_evidence"),
            "worker_details": dict(data.get("worker_details") or {}),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "keep_worker_activation_shadow_only"),
            "worker_timeouts_enabled": bool(data.get("worker_timeouts_enabled", True)),
            "bounded_scans_only": bool(data.get("bounded_scans_only", True)),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
        }

    def _confidence_calibration_performance_attribution_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_confidence_calibration_performance_attribution"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "best_confidence_bucket": _text(data.get("best_confidence_bucket"), "insufficient_data"),
            "worst_confidence_bucket": _text(data.get("worst_confidence_bucket"), "insufficient_data"),
            "confidence_calibration_score": _to_float(data.get("confidence_calibration_score"), 0.0),
            "confidence_predictive_power": _to_float(data.get("confidence_predictive_power"), 0.0),
            "confidence_sizing_readiness": _to_float(data.get("confidence_sizing_readiness"), _to_float(data.get("sizing_readiness_score"), 0.0)),
            "confidence_bucket_stats": dict(data.get("confidence_bucket_stats") or {}),
            "sample_size_by_bucket": dict(data.get("sample_size_by_bucket") or {}),
            "return_monotonicity": _to_float(data.get("return_monotonicity"), 0.0),
            "risk_adjusted_monotonicity": _to_float(data.get("risk_adjusted_monotonicity"), 0.0),
            "bucket_consistency": _to_float(data.get("bucket_consistency"), 0.0),
            "best_grade": _text(data.get("best_grade"), "insufficient_data"),
            "weakest_grade": _text(data.get("weakest_grade"), "insufficient_data"),
            "grade_predictive_power": _to_float(data.get("grade_predictive_power"), 0.0),
            "grade_calibration_score": _to_float(data.get("grade_calibration_score"), _to_float(data.get("grade_predictive_power"), 0.0)),
            "grade_bucket_stats": dict(data.get("grade_bucket_stats") or {}),
            "best_confidence_horizon_pair": _text(data.get("best_confidence_horizon_pair"), "insufficient_data"),
            "worst_confidence_horizon_pair": _text(data.get("worst_confidence_horizon_pair"), "insufficient_data"),
            "confidence_bucket_by_horizon": dict(data.get("confidence_bucket_by_horizon") or {}),
            "sizing_readiness_score": _to_float(data.get("sizing_readiness_score"), 0.0),
            "ready_for_confidence_weighted_sizing": bool(data.get("ready_for_confidence_weighted_sizing", False)),
            "recommended_future_sizing_policy_shadow_only": _text(data.get("recommended_future_sizing_policy_shadow_only"), "insufficient_data"),
            "reason_not_ready": _text(data.get("reason_not_ready"), "minimum_evidence_needed"),
            "minimum_evidence_needed": _text(data.get("minimum_evidence_needed"), "more_broker_confirmed_bucket_evidence"),
            "profit_by_symbol": dict(data.get("profit_by_symbol") or {}),
            "profit_by_horizon": dict(data.get("profit_by_horizon") or {}),
            "profit_by_archetype": dict(data.get("profit_by_archetype") or {}),
            "profit_by_regime": dict(data.get("profit_by_regime") or {}),
            "profit_by_confidence_bucket": dict(data.get("profit_by_confidence_bucket") or {}),
            "profit_by_grade": dict(data.get("profit_by_grade") or {}),
            "profit_by_market_cap_tier": dict(data.get("profit_by_market_cap_tier") or {}),
            "profit_by_sector": dict(data.get("profit_by_sector") or {}),
            "largest_winner_contribution": _to_float(data.get("largest_winner_contribution"), 0.0),
            "largest_loser_contribution": _to_float(data.get("largest_loser_contribution"), 0.0),
            "concentration_of_profit": _to_float(data.get("concentration_of_profit"), 0.0),
            "top_profit_driver": _text(data.get("top_profit_driver"), "insufficient_data"),
            "top_loss_driver": _text(data.get("top_loss_driver"), "insufficient_data"),
            "healthiest_profit_source": _text(data.get("healthiest_profit_source"), "insufficient_data"),
            "most_fragile_profit_source": _text(data.get("most_fragile_profit_source"), "insufficient_data"),
            "concentration_warning": _text(data.get("concentration_warning"), "insufficient_data"),
            "daily_positive_rate": _to_float(data.get("daily_positive_rate"), 0.0),
            "current_day_return": _to_float(data.get("current_day_return"), 0.0),
            "current_day_pnl": _to_float(data.get("current_day_pnl"), 0.0),
            "current_day_status": _text(data.get("current_day_status"), "unavailable"),
            "daily_profitability_score": _to_float(data.get("daily_profitability_score"), 0.0),
            "positive_days": _to_int(data.get("positive_days"), 0),
            "negative_days": _to_int(data.get("negative_days"), 0),
            "flat_days": _to_int(data.get("flat_days"), 0),
            "rolling_5_day_return": _to_float(data.get("rolling_5_day_return"), 0.0),
            "rolling_20_day_return": _to_float(data.get("rolling_20_day_return"), 0.0),
            "rolling_performance_summary": _text(data.get("rolling_performance_summary"), "Daily portfolio snapshots are warming up."),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "keep_confidence_and_sizing_shadow_only"),
            "summary": _text(
                data.get("summary"),
                "Astra is studying whether confidence, grades, horizons, and attribution explain returns without changing sizing or execution.",
            ),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
        }

    def _context_evidence_expansion_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_context_evidence_expansion"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "active_trades_tracked": _to_int(data.get("active_trades_tracked"), 0),
            "active_trade_symbols": list(data.get("active_trade_symbols") or [])[:12],
            "strongest_open_trade": _text(data.get("strongest_open_trade"), "insufficient_data"),
            "weakest_open_trade": _text(data.get("weakest_open_trade"), "insufficient_data"),
            "highest_profit_decay_symbol": _text(data.get("highest_profit_decay_symbol"), "insufficient_data"),
            "highest_giveback_symbol": _text(data.get("highest_giveback_symbol"), "insufficient_data"),
            "best_open_trade_horizon": _text(data.get("best_open_trade_horizon"), "insufficient_data"),
            "open_trade_continuation_score": _to_float(data.get("open_trade_continuation_score"), 0.0),
            "open_trade_profit_capture_score": _to_float(data.get("open_trade_profit_capture_score"), 0.0),
            "open_trade_learning_confidence": _to_float(data.get("open_trade_learning_confidence"), 0.0),
            "open_trade_shadow_recommendation": _text(data.get("open_trade_shadow_recommendation"), "collect_open_trade_evidence"),
            "rejected_candidates_reviewed": _to_int(data.get("rejected_candidates_reviewed"), 0),
            "correct_rejections": _to_int(data.get("correct_rejections"), 0),
            "missed_winners": _to_int(data.get("missed_winners"), 0),
            "avoided_losers": _to_int(data.get("avoided_losers"), 0),
            "rejection_accuracy": _to_float(data.get("rejection_accuracy"), 0.0),
            "biggest_missed_symbol": _text(data.get("biggest_missed_symbol"), "insufficient_data"),
            "best_correct_rejection": _text(data.get("best_correct_rejection"), "insufficient_data"),
            "worst_rejection_reason": _text(data.get("worst_rejection_reason"), "insufficient_data"),
            "rejection_reason_distribution": dict(data.get("rejection_reason_distribution") or {}),
            "rejection_learning_score": _to_float(data.get("rejection_learning_score"), 0.0),
            "rejected_candidate_learning_confidence": _to_float(data.get("rejected_candidate_learning_confidence"), 0.0),
            "rejected_candidate_shadow_recommendation": _text(data.get("rejected_candidate_shadow_recommendation"), "study_rejections_shadow_only"),
            "catalyst_records": _to_int(data.get("catalyst_records"), 0),
            "dominant_catalyst_type": _text(data.get("dominant_catalyst_type"), "insufficient_data"),
            "strongest_catalyst_type": _text(data.get("strongest_catalyst_type"), "insufficient_data"),
            "weakest_catalyst_type": _text(data.get("weakest_catalyst_type"), "insufficient_data"),
            "unknown_catalyst_rate": _to_float(data.get("unknown_catalyst_rate"), 100.0),
            "catalyst_coverage_score": _to_float(data.get("catalyst_coverage_score"), 0.0),
            "best_catalyst_horizon": _text(data.get("best_catalyst_horizon"), "insufficient_data"),
            "highest_giveback_catalyst": _text(data.get("highest_giveback_catalyst"), "insufficient_data"),
            "catalyst_distribution": dict(data.get("catalyst_distribution") or {}),
            "best_horizon_by_catalyst": dict(data.get("best_horizon_by_catalyst") or {}),
            "avg_giveback_by_catalyst": dict(data.get("avg_giveback_by_catalyst") or {}),
            "continuation_probability_by_catalyst": dict(data.get("continuation_probability_by_catalyst") or {}),
            "catalyst_learning_confidence": _to_float(data.get("catalyst_learning_confidence"), 0.0),
            "catalyst_shadow_recommendation": _text(data.get("catalyst_shadow_recommendation"), "continue_catalyst_tracking_shadow_only"),
            "top_learning_gap": _text(data.get("top_learning_gap"), "insufficient_data"),
            "learning_gap_scores": dict(data.get("learning_gap_scores") or {}),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_context_evidence_collection_shadow_only"),
            "summary": _text(
                data.get("summary"),
                "Astra is learning from open trades, rejected candidates, and catalysts without changing trading behavior.",
            ),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
        }

    def _catalyst_theme_narrative_capital_flow_v2_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "mode": _text(data.get("mode"), "paper_only_catalyst_theme_narrative_capital_flow_intelligence"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "catalyst_records": _to_int(data.get("catalyst_records"), 0),
            "dominant_catalyst": _text(data.get("dominant_catalyst"), "insufficient_data"),
            "secondary_catalyst": _text(data.get("secondary_catalyst"), "none"),
            "supporting_catalysts": list(data.get("supporting_catalysts") or [])[:8],
            "catalyst_count": _to_int(data.get("catalyst_count"), 0),
            "catalyst_confidence": _to_float(data.get("catalyst_confidence"), 0.0),
            "catalyst_agreement_score": _to_float(data.get("catalyst_agreement_score"), 0.0),
            "multi_catalyst_score": _to_float(data.get("multi_catalyst_score"), 0.0),
            "catalyst_strength_score": _to_float(data.get("catalyst_strength_score"), 0.0),
            "average_strength_score": _to_float(data.get("average_strength_score"), 0.0),
            "strongest_catalyst_type": _text(data.get("strongest_catalyst_type"), "insufficient_data"),
            "weakest_catalyst_type": _text(data.get("weakest_catalyst_type"), "insufficient_data"),
            "catalyst_coverage_score": _to_float(data.get("catalyst_coverage_score"), 0.0),
            "unknown_catalyst_rate": _to_float(data.get("unknown_catalyst_rate"), 100.0),
            "catalyst_strength_reliability": _to_float(data.get("catalyst_strength_reliability"), 0.0),
            "catalyst_reliability": dict(data.get("catalyst_reliability") or {}),
            "highest_winrate_catalyst": _text(data.get("highest_winrate_catalyst"), "insufficient_data"),
            "highest_return_catalyst": _text(data.get("highest_return_catalyst"), "insufficient_data"),
            "highest_giveback_catalyst": _text(data.get("highest_giveback_catalyst"), "insufficient_data"),
            "most_reliable_catalyst": _text(data.get("most_reliable_catalyst"), "insufficient_data"),
            "catalyst_decay_learning_score": _to_float(data.get("catalyst_decay_learning_score"), 0.0),
            "longest_lasting_catalyst": _text(data.get("longest_lasting_catalyst"), "insufficient_data"),
            "fastest_decay_catalyst": _text(data.get("fastest_decay_catalyst"), "insufficient_data"),
            "catalyst_half_life": dict(data.get("catalyst_half_life") or {}),
            "catalyst_decay_curve": dict(data.get("catalyst_decay_curve") or {}),
            "best_horizon_by_catalyst": dict(data.get("best_horizon_by_catalyst") or {}),
            "worst_horizon_by_catalyst": dict(data.get("worst_horizon_by_catalyst") or {}),
            "catalyst_horizon_confidence": _to_float(data.get("catalyst_horizon_confidence"), 0.0),
            "best_catalyst_archetype_pair": _text(data.get("best_catalyst_archetype_pair"), "insufficient_data"),
            "weakest_catalyst_archetype_pair": _text(data.get("weakest_catalyst_archetype_pair"), "insufficient_data"),
            "archetype_catalyst_score": dict(data.get("archetype_catalyst_score") or {}),
            "dominant_theme": _text(data.get("dominant_theme"), "insufficient_data"),
            "strongest_theme": _text(data.get("strongest_theme"), "insufficient_data"),
            "weakest_theme": _text(data.get("weakest_theme"), "insufficient_data"),
            "emerging_theme": _text(data.get("emerging_theme"), "insufficient_data"),
            "weakening_theme": _text(data.get("weakening_theme"), "insufficient_data"),
            "fading_theme": _text(data.get("fading_theme"), "insufficient_data"),
            "theme_persistence_score": _to_float(data.get("theme_persistence_score"), 0.0),
            "theme_confidence": _to_float(data.get("theme_confidence"), 0.0),
            "theme_relative_strength": dict(data.get("theme_relative_strength") or {}),
            "theme_relative_momentum": dict(data.get("theme_relative_momentum") or {}),
            "theme_rotation_score": _to_float(data.get("theme_rotation_score"), 0.0),
            "dominant_sector": _text(data.get("dominant_sector"), "insufficient_data"),
            "current_leading_sector": _text(data.get("current_leading_sector"), "insufficient_data"),
            "strongest_sector": _text(data.get("strongest_sector"), "insufficient_data"),
            "weakest_sector": _text(data.get("weakest_sector"), "insufficient_data"),
            "improving_sector": _text(data.get("improving_sector"), "insufficient_data"),
            "weakening_sector": _text(data.get("weakening_sector"), "insufficient_data"),
            "sector_rotation_score": _to_float(data.get("sector_rotation_score"), 0.0),
            "sector_rotation_velocity": _to_float(data.get("sector_rotation_velocity"), 0.0),
            "sector_rotation_confidence": _to_float(data.get("sector_rotation_confidence"), 0.0),
            "dominant_industry": _text(data.get("dominant_industry"), "insufficient_data"),
            "leading_industry": _text(data.get("leading_industry"), "insufficient_data"),
            "strongest_industry": _text(data.get("strongest_industry"), "insufficient_data"),
            "weakest_industry": _text(data.get("weakest_industry"), "insufficient_data"),
            "industry_rotation_score": _to_float(data.get("industry_rotation_score"), 0.0),
            "industry_rotation_strength": _to_float(data.get("industry_rotation_strength"), 0.0),
            "strongest_capital_flow": _text(data.get("strongest_capital_flow"), "insufficient_data"),
            "weakest_capital_flow": _text(data.get("weakest_capital_flow"), "insufficient_data"),
            "capital_flow_confidence": _to_float(data.get("capital_flow_confidence"), 0.0),
            "institutional_rotation_signal": _text(data.get("institutional_rotation_signal"), "insufficient_data"),
            "market_leader": _text(data.get("market_leader"), "insufficient_data"),
            "strongest_leadership_group": _text(data.get("strongest_leadership_group"), "insufficient_data"),
            "leadership_strength_score": _to_float(data.get("leadership_strength_score"), 0.0),
            "strongest_narrative_chain": _text(data.get("strongest_narrative_chain"), "insufficient_data"),
            "longest_narrative_chain": _text(data.get("longest_narrative_chain"), "insufficient_data"),
            "narrative_learning_score": _to_float(data.get("narrative_learning_score"), 0.0),
            "catalyst_truth_score": _to_float(data.get("catalyst_truth_score"), 0.0),
            "catalyst_prediction_accuracy": _to_float(data.get("catalyst_prediction_accuracy"), 0.0),
            "catalyst_confidence_truth": _to_float(data.get("catalyst_confidence_truth"), 0.0),
            "top_learning_gap": _text(data.get("top_learning_gap"), "insufficient_data"),
            "learning_gap_scores": dict(data.get("learning_gap_scores") or {}),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_catalyst_theme_narrative_learning_shadow_only"),
            "summary": _text(data.get("summary"), "Astra is learning why stocks move without changing trading behavior."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
        }

    def _decision_optimization_trade_management_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_decision_optimization_trade_management"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "tracked_trades": _to_int(data.get("tracked_trades"), 0),
            "opportunity_rows_reviewed": _to_int(data.get("opportunity_rows_reviewed"), 0),
            "completed_lifecycles_reviewed": _to_int(data.get("completed_lifecycles_reviewed"), 0),
            "actual_average_result": data.get("actual_average_result"),
            "virtual_exit_policy_stats": dict(data.get("virtual_exit_policy_stats") or {}),
            "best_virtual_exit_policy": _text(data.get("best_virtual_exit_policy"), "insufficient_data"),
            "worst_virtual_exit_policy": _text(data.get("worst_virtual_exit_policy"), "insufficient_data"),
            "highest_improvement_policy": _text(data.get("highest_improvement_policy"), "insufficient_data"),
            "most_reliable_policy": _text(data.get("most_reliable_policy"), "insufficient_data"),
            "continuation_failure_probability": _to_float(data.get("continuation_failure_probability"), 0.0),
            "strongest_failure_signal": _text(data.get("strongest_failure_signal"), "insufficient_data"),
            "weakest_failure_signal": _text(data.get("weakest_failure_signal"), "insufficient_data"),
            "failure_signal_scores": dict(data.get("failure_signal_scores") or {}),
            "average_failure_lead_time": _text(data.get("average_failure_lead_time"), "insufficient_data"),
            "average_failure_lead_time_minutes": _to_float(data.get("average_failure_lead_time_minutes"), 0.0),
            "continuation_quality_score": _to_float(data.get("continuation_quality_score"), 0.0),
            "rejection_accuracy": _to_float(data.get("rejection_accuracy"), 0.0),
            "missed_winner_rate": _to_float(data.get("missed_winner_rate"), 0.0),
            "avoided_loser_rate": _to_float(data.get("avoided_loser_rate"), 0.0),
            "decision_quality_score": _to_float(data.get("decision_quality_score"), 0.0),
            "strongest_rejection_reason": _text(data.get("strongest_rejection_reason"), "insufficient_data"),
            "weakest_rejection_reason": _text(data.get("weakest_rejection_reason"), "insufficient_data"),
            "top_missed_opportunities": list(data.get("top_missed_opportunities") or [])[:8],
            "recurring_rejection_mistakes": list(data.get("recurring_rejection_mistakes") or [])[:8],
            "recurring_rejection_successes": list(data.get("recurring_rejection_successes") or [])[:8],
            "average_opportunity_cost": data.get("average_opportunity_cost"),
            "highest_opportunity_cost": data.get("highest_opportunity_cost"),
            "confidence_truth_score": _to_float(data.get("confidence_truth_score"), 0.0),
            "predictive_power": _to_float(data.get("predictive_power"), 0.0),
            "sizing_readiness_score": _to_float(data.get("sizing_readiness_score"), 0.0),
            "confidence_reliability": _text(data.get("confidence_reliability"), "insufficient_data"),
            "best_confidence_bucket": _text(data.get("best_confidence_bucket"), "insufficient_data"),
            "worst_confidence_bucket": _text(data.get("worst_confidence_bucket"), "insufficient_data"),
            "confidence_bucket_outcomes": dict(data.get("confidence_bucket_outcomes") or {}),
            "confidence_monotonicity": _to_float(data.get("confidence_monotonicity"), 0.0),
            "higher_confidence_produces_better_outcomes": bool(data.get("higher_confidence_produces_better_outcomes", False)),
            "confidence_weighted_sizing_may_eventually_be_justified": bool(data.get("confidence_weighted_sizing_may_eventually_be_justified", False)),
            "biggest_decision_gap": _text(data.get("biggest_decision_gap"), "insufficient_data"),
            "strongest_improvement_area": _text(data.get("strongest_improvement_area"), "insufficient_data"),
            "top_exit_learning_focus": _text(data.get("top_exit_learning_focus"), "insufficient_data"),
            "confidence_calibration_status": _text(data.get("confidence_calibration_status"), "insufficient_data"),
            "decision_gap_scores": dict(data.get("decision_gap_scores") or {}),
            "trade_management_intelligence_score": _to_float(data.get("trade_management_intelligence_score"), 0.0),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_decision_optimization_shadow_only"),
            "summary": _text(
                data.get("summary"),
                "Astra is simulating trade-management decisions and confidence truth without changing execution.",
            ),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _full_opportunity_lifecycle_learning_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_full_opportunity_lifecycle_learning"),
            "opportunities_tracked": _to_int(data.get("opportunities_tracked"), 0),
            "paper_trades_tracked": _to_int(data.get("paper_trades_tracked"), 0),
            "virtual_trades_tracked": _to_int(data.get("virtual_trades_tracked"), 0),
            "rejected_tracked": _to_int(data.get("rejected_tracked"), 0),
            "skipped_tracked": _to_int(data.get("skipped_tracked"), 0),
            "ignored_tracked": _to_int(data.get("ignored_tracked"), 0),
            "blocked_tracked": _to_int(data.get("blocked_tracked"), 0),
            "missed_winners": _to_int(data.get("missed_winners"), 0),
            "avoided_losers": _to_int(data.get("avoided_losers"), 0),
            "learning_completeness_score": _to_float(data.get("learning_completeness_score"), 0.0),
            "decision_distribution": dict(data.get("decision_distribution") or {}),
            "outcome_distribution": dict(data.get("outcome_distribution") or {}),
            "graph_nodes": _to_int(data.get("graph_nodes"), 0),
            "graph_edges": _to_int(data.get("graph_edges"), 0),
            "strongest_learning_connection": _text(data.get("strongest_learning_connection"), "insufficient_data"),
            "weakest_learning_connection": _text(data.get("weakest_learning_connection"), "insufficient_data"),
            "systems_receiving_evidence": dict(data.get("systems_receiving_evidence") or {}),
            "cross_system_learning_score": _to_float(data.get("cross_system_learning_score"), 0.0),
            "most_predictive_feature": _text(data.get("most_predictive_feature"), "insufficient_data"),
            "least_predictive_feature": _text(data.get("least_predictive_feature"), "insufficient_data"),
            "feature_predictive_score": dict(data.get("feature_predictive_score") or {}),
            "top_profit_features": list(data.get("top_profit_features") or [])[:8],
            "top_loss_features": list(data.get("top_loss_features") or [])[:8],
            "feature_attribution_confidence": _to_float(data.get("feature_attribution_confidence"), 0.0),
            "highest_value_learning_focus": _text(data.get("highest_value_learning_focus"), "insufficient_data"),
            "lowest_value_learning_focus": _text(data.get("lowest_value_learning_focus"), "insufficient_data"),
            "recommended_worker_focus": _text(data.get("recommended_worker_focus"), "insufficient_data"),
            "learning_roi_score": _to_float(data.get("learning_roi_score"), 0.0),
            "priority_confidence": _to_float(data.get("priority_confidence"), 0.0),
            "reinforced_lessons": _to_int(data.get("reinforced_lessons"), 0),
            "stale_lessons": _to_int(data.get("stale_lessons"), 0),
            "retired_lessons": _to_int(data.get("retired_lessons"), 0),
            "memory_quality_score": _to_float(data.get("memory_quality_score"), 0.0),
            "retention_efficiency_score": _to_float(data.get("retention_efficiency_score"), 0.0),
            "raw_event_count": _to_int(data.get("raw_event_count"), 0),
            "compact_summary_count": _to_int(data.get("compact_summary_count"), 0),
            "archive_count": _to_int(data.get("archive_count"), 0),
            "cache_freshness": _text(data.get("cache_freshness") or data.get("freshness_status"), "stale"),
            "cache_status": _text(data.get("cache_status"), "unknown"),
            "cache_age_seconds": data.get("cache_age_seconds"),
            "last_updated": _text(data.get("last_updated") or data.get("generated_at"), ""),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "max_raw_rows_scanned_per_build": _to_int(data.get("max_raw_rows_scanned_per_build"), 0),
            "max_file_size_before_rotation": _to_int(data.get("max_file_size_before_rotation"), 0),
            "max_hot_lookback_days": _to_int(data.get("max_hot_lookback_days"), 0),
            "memory_pressure_score": _to_float(data.get("memory_pressure_score"), 0.0),
            "storage_health_score": _to_float(data.get("storage_health_score"), 0.0),
            "compaction_status": _text(data.get("compaction_status"), "unknown"),
            "estimated_load_ms": _to_float(data.get("estimated_load_ms"), 0.0),
            "data_source_label": _text(data.get("data_source_label"), "compact_cached_summary"),
            "hot_storage_path": _text(data.get("hot_storage_path"), "state/opportunities/raw/YYYY-MM-DD.jsonl"),
            "warm_storage_path": _text(data.get("warm_storage_path"), "state/opportunities/summaries/YYYY-MM-DD.summary.json"),
            "cold_storage_adapter": _text(data.get("cold_storage_adapter"), "optional_sqlite_or_gzip_archive_prepared"),
            "dashboard_cache_path": _text(data.get("dashboard_cache_path"), "state/dashboard_cache/full_opportunity_lifecycle_summary.json"),
            "index_fields": list(data.get("index_fields") or []),
            "bandwidth_saving_mode": bool(data.get("bandwidth_saving_mode", True)),
            "api_budget_status": _text(data.get("api_budget_status"), "cached_local_only"),
            "bandwidth_pressure_score": _to_float(data.get("bandwidth_pressure_score"), 0.0),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_full_opportunity_lifecycle_learning_shadow_only"),
            "summary": _text(
                data.get("summary"),
                "Astra is learning from every observed opportunity while keeping dashboard summaries compact and cached.",
            ),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
        }

    def _long_term_memory_symbol_retrieval_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_long_term_memory_symbol_retrieval"),
            "storage_health_score": _to_float(data.get("storage_health_score"), 0.0),
            "memory_pressure_score": _to_float(data.get("memory_pressure_score"), 0.0),
            "cleanup_status": _text(data.get("cleanup_status"), "unavailable"),
            "estimated_days_until_storage_pressure": _to_float(data.get("estimated_days_until_storage_pressure"), 0.0),
            "storage_bytes_total": _to_int(data.get("storage_bytes_total"), 0),
            "raw_event_size_bytes": _to_int(data.get("raw_event_size_bytes"), 0),
            "summary_size_bytes": _to_int(data.get("summary_size_bytes"), 0),
            "cache_size_bytes": _to_int(data.get("cache_size_bytes"), 0),
            "archive_size_bytes": _to_int(data.get("archive_size_bytes"), 0),
            "symbol_profiles_tracked": _to_int(data.get("symbol_profiles_tracked"), 0),
            "strongest_symbol_profile": _text(data.get("strongest_symbol_profile"), "insufficient_data"),
            "weakest_symbol_profile": _text(data.get("weakest_symbol_profile"), "insufficient_data"),
            "best_behavioral_edge_symbol": _text(data.get("best_behavioral_edge_symbol"), "insufficient_data"),
            "highest_giveback_symbol": _text(data.get("highest_giveback_symbol"), "insufficient_data"),
            "most_reliable_symbol": _text(data.get("most_reliable_symbol"), "insufficient_data"),
            "symbol_memory_quality_score": _to_float(data.get("symbol_memory_quality_score"), 0.0),
            "symbol_profile_sample": list(data.get("symbol_profile_sample") or [])[:8],
            "indexed_records": _to_int(data.get("indexed_records"), 0),
            "retrieval_latency_ms": _to_float(data.get("retrieval_latency_ms"), 0.0),
            "retrieval_health_score": _to_float(data.get("retrieval_health_score"), 0.0),
            "strongest_index": _text(data.get("strongest_index"), "insufficient_data"),
            "weakest_index": _text(data.get("weakest_index"), "insufficient_data"),
            "recent_lookup_success_rate": _to_float(data.get("recent_lookup_success_rate"), 0.0),
            "full_scan_avoided_count": _to_int(data.get("full_scan_avoided_count"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "hot_rows_scanned_for_rebuild": _to_int(data.get("hot_rows_scanned_for_rebuild"), 0),
            "cache_freshness": _text(data.get("cache_freshness"), "stale"),
            "cache_status": _text(data.get("cache_status"), "unknown"),
            "cache_age_seconds": data.get("cache_age_seconds"),
            "last_updated": _text(data.get("last_updated") or data.get("generated_at"), ""),
            "dashboard_fast_path": _text(data.get("dashboard_fast_path"), "cached_summary_only"),
            "raw_archive_scan_during_render": bool(data.get("raw_archive_scan_during_render", False)),
            "sqlite_archive_adapter_status": _text(data.get("sqlite_archive_adapter_status"), "prepared_optional_not_required"),
            "cleanup_action_taken": _text(data.get("cleanup_action_taken"), "none_diagnostics_only"),
            "retention_policy": dict(data.get("retention_policy") or {}),
            "index_fields": list(data.get("index_fields") or []),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_long_term_memory_symbol_retrieval_shadow_only"),
            "summary": _text(
                data.get("summary"),
                "Astra is organizing long-term memory, symbol behavior profiles, and indexed retrieval without changing trading behavior.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "bandwidth_saving_mode": bool(data.get("bandwidth_saving_mode", True)),
            "api_budget_status": _text(data.get("api_budget_status"), "cached_local_only"),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
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

    def _virtual_paper_convergence_symbol_attribution_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_virtual_paper_convergence_symbol_attribution"),
            "tracked_trades": _to_int(data.get("tracked_trades"), 0),
            "symbol_profiles_reviewed": _to_int(data.get("symbol_profiles_reviewed"), 0),
            "average_actual_return": data.get("average_actual_return"),
            "average_virtual_return": data.get("average_virtual_return"),
            "average_convergence_gap": data.get("average_convergence_gap"),
            "missed_profit_pct": data.get("missed_profit_pct"),
            "missed_profit_dollars": data.get("missed_profit_dollars"),
            "gap_severity": _text(data.get("gap_severity"), "insufficient_data"),
            "convergence_quality_score": _to_float(data.get("convergence_quality_score"), 0.0),
            "virtual_outperformance_rate": _to_float(data.get("virtual_outperformance_rate"), 0.0),
            "largest_convergence_gap_symbol": _text(data.get("largest_convergence_gap_symbol"), "insufficient_data"),
            "smallest_convergence_gap_symbol": _text(data.get("smallest_convergence_gap_symbol"), "insufficient_data"),
            "dominant_gap_cause": _text(data.get("dominant_gap_cause"), "insufficient_data"),
            "primary_gap_cause": _text(data.get("primary_gap_cause"), "insufficient_data"),
            "secondary_gap_cause": _text(data.get("secondary_gap_cause"), "insufficient_data"),
            "gap_cause_confidence": _to_float(data.get("gap_cause_confidence"), 0.0),
            "repeated_gap_pattern": _text(data.get("repeated_gap_pattern"), "insufficient_data"),
            "gap_attribution_score": _to_float(data.get("gap_attribution_score"), 0.0),
            "strongest_gap_pattern": _text(data.get("strongest_gap_pattern"), "insufficient_data"),
            "weakest_gap_pattern": _text(data.get("weakest_gap_pattern"), "insufficient_data"),
            "gap_attribution_confidence": _to_float(data.get("gap_attribution_confidence"), 0.0),
            "highest_value_gap_to_reduce": _text(data.get("highest_value_gap_to_reduce"), "insufficient_data"),
            "strongest_symbol_behavior_edge": _text(data.get("strongest_symbol_behavior_edge"), "insufficient_data"),
            "weakest_symbol_behavior_edge": _text(data.get("weakest_symbol_behavior_edge"), "insufficient_data"),
            "highest_gap_symbol": _text(data.get("highest_gap_symbol"), "insufficient_data"),
            "most_reliable_symbol": _text(data.get("most_reliable_symbol"), "insufficient_data"),
            "least_reliable_symbol": _text(data.get("least_reliable_symbol"), "insufficient_data"),
            "symbol_behavior_confidence": _to_float(data.get("symbol_behavior_confidence"), 0.0),
            "best_symbol_horizon_pair": _text(data.get("best_symbol_horizon_pair"), "insufficient_data"),
            "worst_symbol_horizon_pair": _text(data.get("worst_symbol_horizon_pair"), "insufficient_data"),
            "best_horizon_by_symbol": dict(data.get("best_horizon_by_symbol") or {}),
            "worst_horizon_by_symbol": dict(data.get("worst_horizon_by_symbol") or {}),
            "horizon_gap_score": _to_float(data.get("horizon_gap_score"), 0.0),
            "horizon_fit_confidence": _to_float(data.get("horizon_fit_confidence"), 0.0),
            "best_exit_style_by_symbol": dict(data.get("best_exit_style_by_symbol") or {}),
            "worst_exit_style_by_symbol": dict(data.get("worst_exit_style_by_symbol") or {}),
            "exit_style_improvement_by_symbol": dict(data.get("exit_style_improvement_by_symbol") or {}),
            "symbol_exit_confidence": _to_float(data.get("symbol_exit_confidence"), 0.0),
            "symbols_needing_profit_lock": list(data.get("symbols_needing_profit_lock") or [])[:8],
            "symbols_needing_continuation_exit": list(data.get("symbols_needing_continuation_exit") or [])[:8],
            "symbols_needing_longer_hold": list(data.get("symbols_needing_longer_hold") or [])[:8],
            "best_regime_by_symbol": dict(data.get("best_regime_by_symbol") or {}),
            "worst_regime_by_symbol": dict(data.get("worst_regime_by_symbol") or {}),
            "best_catalyst_by_symbol": dict(data.get("best_catalyst_by_symbol") or {}),
            "worst_catalyst_by_symbol": dict(data.get("worst_catalyst_by_symbol") or {}),
            "best_theme_by_symbol": dict(data.get("best_theme_by_symbol") or {}),
            "catalyst_symbol_fit_score": _to_float(data.get("catalyst_symbol_fit_score"), 0.0),
            "regime_symbol_fit_score": _to_float(data.get("regime_symbol_fit_score"), 0.0),
            "top_profit_driver": _text(data.get("top_profit_driver"), "insufficient_data"),
            "top_loss_driver": _text(data.get("top_loss_driver"), "insufficient_data"),
            "top_missed_profit_driver": _text(data.get("top_missed_profit_driver"), "insufficient_data"),
            "profitability_attribution_score": _to_float(data.get("profitability_attribution_score"), 0.0),
            "highest_value_profitability_lever": _text(data.get("highest_value_profitability_lever"), "insufficient_data"),
            "strongest_virtual_policy": _text(data.get("strongest_virtual_policy"), "insufficient_data"),
            "weakest_virtual_policy": _text(data.get("weakest_virtual_policy"), "insufficient_data"),
            "policy_improvement_confidence": _to_float(data.get("policy_improvement_confidence"), 0.0),
            "policy_attribution_score": _to_float(data.get("policy_attribution_score"), 0.0),
            "closest_policy_to_future_review": _text(data.get("closest_policy_to_future_review"), "insufficient_data"),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_virtual_to_paper_convergence_shadow_only"),
            "summary": _text(
                data.get("summary"),
                "Astra is comparing actual paper outcomes with virtual alternatives without changing trading behavior.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "bandwidth_saving_mode": bool(data.get("bandwidth_saving_mode", True)),
            "cache_hit": bool(data.get("cache_hit", False)),
            "cache_freshness": _text(data.get("cache_freshness"), "stale"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "order_logic_changed": bool(data.get("order_logic_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _accelerated_learning_symbol_intelligence_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_accelerated_learning_symbol_intelligence"),
            "historical_records_reviewed": _to_int(data.get("historical_records_reviewed"), 0),
            "accelerated_learning_events": _to_int(data.get("accelerated_learning_events"), 0),
            "replay_acceleration_score": _to_float(data.get("replay_acceleration_score"), 0.0),
            "most_common_historical_mistake": _text(data.get("most_common_historical_mistake"), "insufficient_data"),
            "highest_value_historical_lesson": _text(data.get("highest_value_historical_lesson"), "insufficient_data"),
            "average_actual_return": data.get("average_actual_return"),
            "average_virtual_return": data.get("average_virtual_return"),
            "average_convergence_gap": data.get("average_convergence_gap"),
            "dominant_gap_cause": _text(data.get("dominant_gap_cause"), "insufficient_data"),
            "highest_value_gap_to_reduce": _text(data.get("highest_value_gap_to_reduce"), "insufficient_data"),
            "symbol_profiles_tracked": _to_int(data.get("symbol_profiles_tracked"), 0),
            "strongest_symbol_profile": _text(data.get("strongest_symbol_profile"), "insufficient_data"),
            "weakest_symbol_profile": _text(data.get("weakest_symbol_profile"), "insufficient_data"),
            "most_reliable_symbol": _text(data.get("most_reliable_symbol"), "insufficient_data"),
            "highest_giveback_symbol": _text(data.get("highest_giveback_symbol"), "insufficient_data"),
            "best_behavioral_edge_symbol": _text(data.get("best_behavioral_edge_symbol"), "insufficient_data"),
            "symbol_personality_quality_score": _to_float(data.get("symbol_personality_quality_score"), 0.0),
            "best_horizon_by_symbol": dict(data.get("best_horizon_by_symbol") or {}),
            "worst_horizon_by_symbol": dict(data.get("worst_horizon_by_symbol") or {}),
            "best_symbol_horizon_pair": _text(data.get("best_symbol_horizon_pair"), "insufficient_data"),
            "worst_symbol_horizon_pair": _text(data.get("worst_symbol_horizon_pair"), "insufficient_data"),
            "horizon_confidence": _to_float(data.get("horizon_confidence"), 0.0),
            "horizon_fit_score": _to_float(data.get("horizon_fit_score"), 0.0),
            "best_exit_style_by_symbol": dict(data.get("best_exit_style_by_symbol") or {}),
            "worst_exit_style_by_symbol": dict(data.get("worst_exit_style_by_symbol") or {}),
            "exit_style_improvement_by_symbol": dict(data.get("exit_style_improvement_by_symbol") or {}),
            "symbols_needing_profit_lock": list(data.get("symbols_needing_profit_lock") or [])[:8],
            "symbols_needing_continuation_exit": list(data.get("symbols_needing_continuation_exit") or [])[:8],
            "symbols_needing_longer_hold": list(data.get("symbols_needing_longer_hold") or [])[:8],
            "symbol_exit_confidence": _to_float(data.get("symbol_exit_confidence"), 0.0),
            "best_catalyst_by_symbol": dict(data.get("best_catalyst_by_symbol") or {}),
            "worst_catalyst_by_symbol": dict(data.get("worst_catalyst_by_symbol") or {}),
            "catalyst_reliability_by_symbol": dict(data.get("catalyst_reliability_by_symbol") or {}),
            "best_theme_by_symbol": dict(data.get("best_theme_by_symbol") or {}),
            "weakest_theme_by_symbol": dict(data.get("weakest_theme_by_symbol") or {}),
            "theme_symbol_fit_score": _to_float(data.get("theme_symbol_fit_score"), 0.0),
            "best_regime_by_symbol": dict(data.get("best_regime_by_symbol") or {}),
            "worst_regime_by_symbol": dict(data.get("worst_regime_by_symbol") or {}),
            "regime_fit_score": _to_float(data.get("regime_fit_score"), 0.0),
            "regime_symbol_confidence": _to_float(data.get("regime_symbol_confidence"), 0.0),
            "symbol_clusters": dict(data.get("symbol_clusters") or {}),
            "strongest_symbol_cluster": _text(data.get("strongest_symbol_cluster"), "insufficient_data"),
            "weakest_symbol_cluster": _text(data.get("weakest_symbol_cluster"), "insufficient_data"),
            "transferable_lessons": list(data.get("transferable_lessons") or [])[:8],
            "cluster_learning_score": _to_float(data.get("cluster_learning_score"), 0.0),
            "strongest_cross_symbol_pattern": _text(data.get("strongest_cross_symbol_pattern"), "insufficient_data"),
            "weakest_cross_symbol_pattern": _text(data.get("weakest_cross_symbol_pattern"), "insufficient_data"),
            "cross_symbol_learning_score": _to_float(data.get("cross_symbol_learning_score"), 0.0),
            "transferable_pattern_confidence": _to_float(data.get("transferable_pattern_confidence"), 0.0),
            "top_profit_driver": _text(data.get("top_profit_driver"), "insufficient_data"),
            "top_loss_driver": _text(data.get("top_loss_driver"), "insufficient_data"),
            "top_missed_profit_driver": _text(data.get("top_missed_profit_driver"), "insufficient_data"),
            "highest_value_profitability_lever": _text(data.get("highest_value_profitability_lever"), "insufficient_data"),
            "profitability_attribution_score": _to_float(data.get("profitability_attribution_score"), 0.0),
            "highest_roi_learning_area": _text(data.get("highest_roi_learning_area"), "insufficient_data"),
            "lowest_roi_learning_area": _text(data.get("lowest_roi_learning_area"), "insufficient_data"),
            "expected_learning_gain": _to_float(data.get("expected_learning_gain"), 0.0),
            "recommended_accelerated_focus": _text(data.get("recommended_accelerated_focus"), "insufficient_data"),
            "symbols_with_behavior_drift": list(data.get("symbols_with_behavior_drift") or [])[:8],
            "highest_drift_symbol": _text(data.get("highest_drift_symbol"), "insufficient_data"),
            "most_stable_symbol": _text(data.get("most_stable_symbol"), "insufficient_data"),
            "regime_override_count": _to_int(data.get("regime_override_count"), 0),
            "symbol_drift_warning": _text(data.get("symbol_drift_warning"), "insufficient_data"),
            "drift_score": _to_float(data.get("drift_score"), 0.0),
            "symbol_stability_score": _to_float(data.get("symbol_stability_score"), 0.0),
            "compressed_lessons": _to_int(data.get("compressed_lessons"), 0),
            "raw_records_summarized": _to_int(data.get("raw_records_summarized"), 0),
            "storage_savings_estimate": _to_float(data.get("storage_savings_estimate"), 0.0),
            "compression_quality_score": _to_float(data.get("compression_quality_score"), 0.0),
            "indexed_learning_records": _to_int(data.get("indexed_learning_records"), 0),
            "retrieval_latency_ms": _to_float(data.get("retrieval_latency_ms"), 0.0),
            "indexing_health_score": _to_float(data.get("indexing_health_score"), 0.0),
            "full_scan_avoided_count": _to_int(data.get("full_scan_avoided_count"), 0),
            "best_sector_horizon": dict(data.get("best_sector_horizon") or {}),
            "best_industry_horizon": dict(data.get("best_industry_horizon") or {}),
            "best_theme_horizon": dict(data.get("best_theme_horizon") or {}),
            "best_peer_group_horizon": dict(data.get("best_peer_group_horizon") or {}),
            "best_sector_exit_style": dict(data.get("best_sector_exit_style") or {}),
            "best_industry_exit_style": dict(data.get("best_industry_exit_style") or {}),
            "best_theme_exit_style": dict(data.get("best_theme_exit_style") or {}),
            "best_peer_group_exit_style": dict(data.get("best_peer_group_exit_style") or {}),
            "strongest_sector_behavior": _text(data.get("strongest_sector_behavior"), "insufficient_data"),
            "weakest_sector_behavior": _text(data.get("weakest_sector_behavior"), "insufficient_data"),
            "strongest_industry_behavior": _text(data.get("strongest_industry_behavior"), "insufficient_data"),
            "strongest_theme_behavior": _text(data.get("strongest_theme_behavior"), "insufficient_data"),
            "strongest_peer_group_behavior": _text(data.get("strongest_peer_group_behavior"), "insufficient_data"),
            "highest_giveback_sector": _text(data.get("highest_giveback_sector"), "insufficient_data"),
            "highest_giveback_industry": _text(data.get("highest_giveback_industry"), "insufficient_data"),
            "highest_giveback_theme": _text(data.get("highest_giveback_theme"), "insufficient_data"),
            "highest_giveback_peer_group": _text(data.get("highest_giveback_peer_group"), "insufficient_data"),
            "transferable_learning_confidence": _to_float(data.get("transferable_learning_confidence"), 0.0),
            "peer_group_learning_score": _to_float(data.get("peer_group_learning_score"), 0.0),
            "sector_drift_score": _to_float(data.get("sector_drift_score"), 0.0),
            "industry_drift_score": _to_float(data.get("industry_drift_score"), 0.0),
            "theme_drift_score": _to_float(data.get("theme_drift_score"), 0.0),
            "peer_group_drift_score": _to_float(data.get("peer_group_drift_score"), 0.0),
            "top_learning_gap": _text(data.get("top_learning_gap"), "insufficient_data"),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_accelerated_symbol_learning_shadow_only"),
            "summary": _text(data.get("summary"), "Astra is accelerating learning from cached historical summaries without changing trading behavior."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "scan_rows_used": _to_int(data.get("scan_rows_used"), 0),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "bandwidth_saving_mode": bool(data.get("bandwidth_saving_mode", True)),
            "cache_hit": bool(data.get("cache_hit", False)),
            "cache_freshness": _text(data.get("cache_freshness"), "stale"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "order_logic_changed": bool(data.get("order_logic_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _multi_horizon_intelligence_adaptive_lifecycle_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_multi_horizon_adaptive_lifecycle"),
            "suite_status": _text(data.get("suite_status"), "unavailable"),
            "horizons_tested": list(data.get("horizons_tested") or [])[:16],
            "missing_horizons": dict(data.get("missing_horizons") or {}),
            "horizon_outcomes": dict(data.get("horizon_outcomes") or {}),
            "virtual_paths_per_horizon": dict(data.get("virtual_paths_per_horizon") or {}),
            "learning_events_per_horizon": dict(data.get("learning_events_per_horizon") or {}),
            "closed_trades_per_horizon": dict(data.get("closed_trades_per_horizon") or {}),
            "paper_trades_per_horizon": dict(data.get("paper_trades_per_horizon") or {}),
            "shadow_trades_per_horizon": dict(data.get("shadow_trades_per_horizon") or {}),
            "dominant_paper_horizon": _text(data.get("dominant_paper_horizon"), "insufficient_data"),
            "dominant_shadow_horizon": _text(data.get("dominant_shadow_horizon"), "insufficient_data"),
            "best_horizon": _text(data.get("best_horizon"), "insufficient_data"),
            "weakest_horizon": _text(data.get("weakest_horizon"), "insufficient_data"),
            "predicted_horizon": _text(data.get("predicted_horizon"), "insufficient_data"),
            "actual_best_horizon": _text(data.get("actual_best_horizon"), "insufficient_data"),
            "horizon_mismatch_detected": bool(data.get("horizon_mismatch_detected", False)),
            "horizon_mismatch_risk_score": _to_float(data.get("horizon_mismatch_risk_score"), 0.0),
            "symbols_most_affected": list(data.get("symbols_most_affected") or [])[:8],
            "setups_most_affected": list(data.get("setups_most_affected") or [])[:8],
            "estimated_profit_lost_to_horizon_mismatch": _to_float(data.get("estimated_profit_lost_to_horizon_mismatch"), 0.0),
            "estimated_giveback_from_wrong_horizon": _to_float(data.get("estimated_giveback_from_wrong_horizon"), 0.0),
            "symbol_horizon_dna": dict(data.get("symbol_horizon_dna") or {}),
            "best_symbol_horizon": _text(data.get("best_symbol_horizon"), "insufficient_data"),
            "worst_symbol_horizon": _text(data.get("worst_symbol_horizon"), "insufficient_data"),
            "strongest_setup_horizon": _text(data.get("strongest_setup_horizon"), "insufficient_data"),
            "strongest_catalyst_horizon": _text(data.get("strongest_catalyst_horizon"), "insufficient_data"),
            "strongest_regime_horizon": _text(data.get("strongest_regime_horizon"), "insufficient_data"),
            "strongest_peer_group_pattern": _text(data.get("strongest_peer_group_pattern"), "insufficient_data"),
            "peer_best_horizon": _text(data.get("peer_best_horizon"), "insufficient_data"),
            "peer_exit_style": _text(data.get("peer_exit_style"), "insufficient_data"),
            "transfer_confidence": _to_float(data.get("transfer_confidence"), 0.0),
            "horizon_readiness": dict(data.get("horizon_readiness") or {}),
            "lifecycle_flags": dict(data.get("lifecycle_flags") or {}),
            "entry_timing": _text(data.get("entry_timing"), "tracked_shadow_only"),
            "first_profit_milestone": _text(data.get("first_profit_milestone"), "insufficient_data"),
            "peak_profit": _to_float(data.get("peak_profit"), 0.0),
            "profit_decay": _to_float(data.get("profit_decay"), 0.0),
            "hold_quality": _to_float(data.get("hold_quality"), 0.0),
            "opportunity_cost": _to_float(data.get("opportunity_cost"), 0.0),
            "learned_exits_applied": bool(data.get("learned_exits_applied", False)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "next_recommended_test": _text(data.get("next_recommended_test"), "continue_shadow_horizon_validation"),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_multi_horizon_lifecycle_learning_shadow_only"),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _paper_throughput_exit_validation_catalyst_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_throughput_exit_validation_catalyst_intelligence"),
            "paper_throughput_status": _text(data.get("paper_throughput_status"), "unavailable"),
            "reviewed_today": _to_int(data.get("reviewed_today"), 0),
            "eligible_today": _to_int(data.get("eligible_today"), 0),
            "submitted_today": _to_int(data.get("submitted_today"), 0),
            "blocked_today": _to_int(data.get("blocked_today"), 0),
            "suppression_rate": _to_float(data.get("suppression_rate"), 0.0),
            "top_blocker": _text(data.get("top_blocker"), "unknown_blocker"),
            "top_blockers": dict(data.get("top_blockers") or {}),
            "duplicate_blocks": _to_int(data.get("duplicate_blocks"), 0),
            "confirmation_blocks": _to_int(data.get("confirmation_blocks"), 0),
            "stale_row_blocks": _to_int(data.get("stale_row_blocks"), 0),
            "broker_confirmed_positions": _to_int(data.get("broker_confirmed_positions"), 0),
            "internal_active_rows": _to_int(data.get("internal_active_rows"), 0),
            "stale_internal_rows": _to_int(data.get("stale_internal_rows"), 0),
            "true_capacity_available": _to_int(data.get("true_capacity_available"), 0),
            "safe_capacity_available": _to_int(data.get("safe_capacity_available"), 0),
            "high_confidence_candidates_blocked": _to_int(data.get("high_confidence_candidates_blocked"), 0),
            "missed_evidence_estimate": _to_int(data.get("missed_evidence_estimate"), 0),
            "missed_profit_learning_estimate": _to_float(data.get("missed_profit_learning_estimate"), 0.0),
            "recommended_safe_throughput_action": _text(data.get("recommended_safe_throughput_action"), "continue_current_paper_safety_gates"),
            "learned_exit_outperforms_current": bool(data.get("learned_exit_outperforms_current", False)),
            "best_shadow_exit_policy": _text(data.get("best_shadow_exit_policy"), "insufficient_data"),
            "best_policy_profit_factor": _to_float(data.get("best_policy_profit_factor"), 0.0),
            "current_policy_profit_factor": _to_float(data.get("current_policy_profit_factor"), 0.0),
            "improvement_delta": _to_float(data.get("improvement_delta"), 0.0),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "policy_confidence": _to_float(data.get("policy_confidence"), 0.0),
            "readiness_status": _text(data.get("readiness_status"), "not_ready_more_evidence_required"),
            "minimum_evidence_remaining": _to_int(data.get("minimum_evidence_remaining"), 0),
            "symbols_where_learned_exit_helps": list(data.get("symbols_where_learned_exit_helps") or [])[:8],
            "symbols_where_learned_exit_hurts": list(data.get("symbols_where_learned_exit_hurts") or [])[:8],
            "horizons_where_learned_exit_helps": dict(data.get("horizons_where_learned_exit_helps") or {}),
            "catalyst_decay_exit_value": _to_float(data.get("catalyst_decay_exit_value"), 0.0),
            "learned_exit_validation_bucket_enabled": bool(data.get("learned_exit_validation_bucket_enabled", False)),
            "learned_exit_validation_bucket_reason": _text(data.get("learned_exit_validation_bucket_reason"), "disabled_pending_human_review_and_policy_governance"),
            "catalyst_coverage": _to_float(data.get("catalyst_coverage"), 0.0),
            "unknown_catalyst_rate": _to_float(data.get("unknown_catalyst_rate"), 100.0),
            "dominant_catalyst": _text(data.get("dominant_catalyst"), "unknown_catalyst"),
            "catalyst_decay_score": _to_float(data.get("catalyst_decay_score"), 0.0),
            "best_horizon_by_catalyst": dict(data.get("best_horizon_by_catalyst") or {}),
            "best_exit_by_catalyst": dict(data.get("best_exit_by_catalyst") or {}),
            "symbols_with_unknown_catalyst": list(data.get("symbols_with_unknown_catalyst") or [])[:10],
            "cached_context_available": bool(data.get("cached_context_available", False)),
            "recommended_safe_context_fix": _text(data.get("recommended_safe_context_fix"), "continue_cached_catalyst_learning"),
            "recommended_next_action": _text(data.get("recommended_next_action"), "continue_collecting_paper_and_shadow_evidence"),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_collecting_paper_and_shadow_evidence"),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_live_endpoint_allowed": bool(data.get("broker_live_endpoint_allowed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "fmp_budgets_changed": bool(data.get("fmp_budgets_changed", False)),
            "paper_mode_verified": bool(data.get("paper_mode_verified", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "learned_exits_applied": bool(data.get("learned_exits_applied", False)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _multi_horizon_capacity_exit_validation_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_multi_horizon_capacity_controlled_exit_validation"),
            "total_capacity": _to_int(data.get("total_capacity"), 20),
            "total_used": _to_int(data.get("total_used"), 0),
            "total_available": _to_int(data.get("total_available"), 0),
            "swing_capacity": _to_int(data.get("swing_capacity"), 8),
            "swing_used": _to_int(data.get("swing_used"), 0),
            "swing_available": _to_int(data.get("swing_available"), 0),
            "day_capacity": _to_int(data.get("day_capacity"), 8),
            "day_used": _to_int(data.get("day_used"), 0),
            "day_available": _to_int(data.get("day_available"), 0),
            "scalp_capacity": _to_int(data.get("scalp_capacity"), 4),
            "scalp_used": _to_int(data.get("scalp_used"), 0),
            "scalp_available": _to_int(data.get("scalp_available"), 0),
            "unknown_horizon_positions": _to_int(data.get("unknown_horizon_positions"), 0),
            "broker_confirmed_positions": _to_int(data.get("broker_confirmed_positions"), 0),
            "stale_internal_rows": _to_int(data.get("stale_internal_rows"), 0),
            "horizon_capacity_blockers": list(data.get("horizon_capacity_blockers") or [])[:10],
            "top_capacity_blocker": _text(data.get("top_capacity_blocker"), "none"),
            "capacity_freed_today": _to_int(data.get("capacity_freed_today"), 0),
            "candidates_blocked_by_horizon_capacity": _to_int(data.get("candidates_blocked_by_horizon_capacity"), 0),
            "high_confidence_candidates_blocked_by_capacity": _to_int(data.get("high_confidence_candidates_blocked_by_capacity"), 0),
            "missed_evidence_due_to_capacity": _to_int(data.get("missed_evidence_due_to_capacity"), 0),
            "recommended_capacity_action": _text(data.get("recommended_capacity_action"), "horizon_capacity_monitoring"),
            "learned_exit_bucket_enabled": bool(data.get("learned_exit_bucket_enabled", False)),
            "learned_exit_bucket_configured": bool(data.get("learned_exit_bucket_configured", False)),
            "learned_exit_bucket_auto_disabled": bool(data.get("learned_exit_bucket_auto_disabled", True)),
            "rollback_reason": _text(data.get("rollback_reason"), "validation_bucket_config_disabled"),
            "rollback_triggered_at": _text(data.get("rollback_triggered_at"), ""),
            "baseline_vs_learned_status": _text(data.get("baseline_vs_learned_status"), "learning_bucket_disabled_collecting_baseline"),
            "safety_status": _text(data.get("safety_status"), "safe_disabled"),
            "learned_exits_used_today": _to_int(data.get("learned_exits_used_today"), 0),
            "best_learned_exit_policy": _text(data.get("best_learned_exit_policy"), "insufficient_data"),
            "baseline_profit_factor": _to_float(data.get("baseline_profit_factor"), 0.0),
            "learned_corrected_profit_factor": _to_float(data.get("learned_corrected_profit_factor"), 0.0),
            "profit_factor_delta": _to_float(data.get("profit_factor_delta"), 0.0),
            "baseline_expectancy": _to_float(data.get("baseline_expectancy"), 0.0),
            "learned_corrected_expectancy": _to_float(data.get("learned_corrected_expectancy"), 0.0),
            "expectancy_delta": _to_float(data.get("expectancy_delta"), 0.0),
            "baseline_capture_ratio": _to_float(data.get("baseline_capture_ratio"), 0.0),
            "learned_corrected_capture_ratio": _to_float(data.get("learned_corrected_capture_ratio"), 0.0),
            "capture_ratio_delta": _to_float(data.get("capture_ratio_delta"), 0.0),
            "baseline_giveback": _to_float(data.get("baseline_giveback"), 0.0),
            "learned_corrected_giveback": _to_float(data.get("learned_corrected_giveback"), 0.0),
            "giveback_delta": _to_float(data.get("giveback_delta"), 0.0),
            "learned_exit_bucket_outperforming": bool(data.get("learned_exit_bucket_outperforming", False)),
            "learned_exit_bucket_underperforming": bool(data.get("learned_exit_bucket_underperforming", False)),
            "validation_confidence": _to_float(data.get("validation_confidence"), 0.0),
            "remaining_evidence_needed": _to_int(data.get("remaining_evidence_needed"), 0),
            "next_recommended_action": _text(data.get("next_recommended_action"), "continue_horizon_capacity_monitoring"),
            "lesson_routing": list(data.get("lesson_routing") or [])[:10],
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "paper_mode_verified": bool(data.get("paper_mode_verified", True)),
            "broker_live_endpoint_allowed": bool(data.get("broker_live_endpoint_allowed", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "broad_entry_behavior_changed": bool(data.get("broad_entry_behavior_changed", False)),
            "broad_exit_behavior_changed": bool(data.get("broad_exit_behavior_changed", False)),
            "broad_sizing_behavior_changed": bool(data.get("broad_sizing_behavior_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "fmp_budgets_changed": bool(data.get("fmp_budgets_changed", False)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "kill_switch_exists": bool(data.get("kill_switch_exists", True)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _historical_intelligence_market_memory_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_historical_intelligence_market_memory"),
            "historical_phase": _text(data.get("historical_phase"), "phase_0_diagnostics_only"),
            "symbols_selected": _to_int(data.get("symbols_selected"), 0),
            "symbols_completed": _to_int(data.get("symbols_completed"), 0),
            "symbols_deferred": _to_int(data.get("symbols_deferred"), 0),
            "compressed_market_memory_records": _to_int(data.get("compressed_market_memory_records"), 0),
            "symbol_profiles_created": _to_int(data.get("symbol_profiles_created"), 0),
            "symbol_profiles_updated": _to_int(data.get("symbol_profiles_updated"), 0),
            "peer_groups_created": _to_int(data.get("peer_groups_created"), 0),
            "regimes_detected": _to_int(data.get("regimes_detected"), 0),
            "catalyst_records_created": _to_int(data.get("catalyst_records_created"), 0),
            "catalyst_coverage_score": _to_float(data.get("catalyst_coverage_score"), 0.0),
            "unknown_catalyst_rate": _to_float(data.get("unknown_catalyst_rate"), 100.0),
            "historical_replays_completed": _to_int(data.get("historical_replays_completed"), 0),
            "historical_replay_score": _to_float(data.get("historical_replay_score"), 0.0),
            "market_memory_quality_score": _to_float(data.get("market_memory_quality_score"), 0.0),
            "historical_lesson_quality_score": _to_float(data.get("historical_lesson_quality_score"), 0.0),
            "historical_memory_growth_score": _to_float(data.get("historical_memory_growth_score"), 0.0),
            "symbol_memory_growth_score": _to_float(data.get("symbol_memory_growth_score"), 0.0),
            "sector_memory_growth_score": _to_float(data.get("sector_memory_growth_score"), 0.0),
            "regime_memory_growth_score": _to_float(data.get("regime_memory_growth_score"), 0.0),
            "historical_transfer_learning_score": _to_float(data.get("historical_transfer_learning_score"), 0.0),
            "rotating_universe_size": _to_int(data.get("rotating_universe_size"), 0),
            "symbols_scanned_today": _to_int(data.get("symbols_scanned_today"), 0),
            "candidate_diversity_score": _to_float(data.get("candidate_diversity_score"), 0.0),
            "sector_coverage_score": _to_float(data.get("sector_coverage_score"), 0.0),
            "fmp_monthly_bandwidth_limit_gb": _to_float(data.get("fmp_monthly_bandwidth_limit_gb"), 50.0),
            "fmp_monthly_bandwidth_used_gb": _to_float(data.get("fmp_monthly_bandwidth_used_gb"), 0.0),
            "fmp_remaining_bandwidth_gb": _to_float(data.get("fmp_remaining_bandwidth_gb"), 50.0),
            "fmp_daily_safe_budget_gb": _to_float(data.get("fmp_daily_safe_budget_gb"), 0.0),
            "fmp_usage_pct": _to_float(data.get("fmp_usage_pct"), 0.0),
            "fmp_warning_level_active": bool(data.get("fmp_warning_level_active", False)),
            "fmp_hard_stop_active": bool(data.get("fmp_hard_stop_active", False)),
            "fmp_expansion_allowed": bool(data.get("fmp_expansion_allowed", False)),
            "fmp_expansion_block_reason": _text(data.get("fmp_expansion_block_reason"), "none"),
            "projected_month_end_usage_gb": _to_float(data.get("projected_month_end_usage_gb"), 0.0),
            "actual_bandwidth_used_gb": _to_float(data.get("actual_bandwidth_used_gb"), 0.0),
            "estimated_bandwidth_cost_gb": _to_float(data.get("estimated_bandwidth_cost_gb"), 0.0),
            "storage_pressure_score": _to_float(data.get("storage_pressure_score"), 0.0),
            "memory_pressure_score": _to_float(data.get("memory_pressure_score"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue cache-only historical diagnostics."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _catalyst_classification_historical_exit_maturation_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_catalyst_historical_exit_maturation"),
            "catalyst_coverage_score": _to_float(data.get("catalyst_coverage_score"), 0.0),
            "unknown_catalyst_rate": _to_float(data.get("unknown_catalyst_rate"), 100.0),
            "direct_unknown_catalyst_rate": _to_float(data.get("direct_unknown_catalyst_rate"), 100.0),
            "classified_catalyst_count": _to_int(data.get("classified_catalyst_count"), 0),
            "catalyst_memory_quality": _to_float(data.get("catalyst_memory_quality"), 0.0),
            "catalyst_confidence_score": _to_float(data.get("catalyst_confidence_score"), 0.0),
            "inferred_catalyst_categories": list(data.get("inferred_catalyst_categories") or [])[:12],
            "dominant_catalyst": _text(data.get("dominant_catalyst"), "other_known_catalyst"),
            "catalyst_classification_source": _text(data.get("catalyst_classification_source"), "cached_memory_theme_sector_context"),
            "historical_memory_growth_score": _to_float(data.get("historical_memory_growth_score"), 0.0),
            "symbol_memory_growth_score": _to_float(data.get("symbol_memory_growth_score"), 0.0),
            "sector_memory_growth_score": _to_float(data.get("sector_memory_growth_score"), 0.0),
            "regime_memory_growth_score": _to_float(data.get("regime_memory_growth_score"), 0.0),
            "historical_transfer_learning_score": _to_float(data.get("historical_transfer_learning_score"), 0.0),
            "profit_lock_readiness_score": _to_float(data.get("profit_lock_readiness_score"), 0.0),
            "catalyst_decay_learning_score": _to_float(data.get("catalyst_decay_learning_score"), 0.0),
            "continuation_failure_learning_score": _to_float(data.get("continuation_failure_learning_score"), 0.0),
            "hold_duration_learning_score": _to_float(data.get("hold_duration_learning_score"), 0.0),
            "giveback_reduction_score": _to_float(data.get("giveback_reduction_score"), 0.0),
            "exit_learning_maturity_score": _to_float(data.get("exit_learning_maturity_score"), 0.0),
            "exit_learning_sample_size": _to_int(data.get("exit_learning_sample_size"), 0),
            "fmp_smart_budget_preserved": bool(data.get("fmp_smart_budget_preserved", True)),
            "hard_safety_ceiling_controls_preserved": bool(data.get("hard_safety_ceiling_controls_preserved", True)),
            "bandwidth_impact_estimate": _text(data.get("bandwidth_impact_estimate"), "zero_dashboard_provider_calls_cache_only"),
            "api_impact_estimate": _text(data.get("api_impact_estimate"), "zero_additional_dashboard_api_provider_llm_calls"),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_provider_calls": _to_int(data.get("dashboard_provider_calls"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue catalyst, memory, and exit maturation shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _catalyst_persistence_decay_curves_v2_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        curves = list(data.get("catalyst_curves") or [])[:18]
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_catalyst_persistence_decay_curves"),
            "catalysts_tracked": _to_int(data.get("catalysts_tracked"), len(curves)),
            "catalyst_curves": curves,
            "catalyst_persistence_score": _to_float(data.get("catalyst_persistence_score"), 0.0),
            "catalyst_decay_score": _to_float(data.get("catalyst_decay_score"), 0.0),
            "catalyst_half_life_estimate": _to_float(data.get("catalyst_half_life_estimate"), 0.0),
            "catalyst_continuation_probability": _to_float(data.get("catalyst_continuation_probability"), 0.0),
            "catalyst_exhaustion_probability": _to_float(data.get("catalyst_exhaustion_probability"), 0.0),
            "catalyst_memory_quality": _to_float(data.get("catalyst_memory_quality"), 0.0),
            "strongest_persistence_catalyst": _text(data.get("strongest_persistence_catalyst"), "insufficient_data"),
            "fastest_decay_catalyst": _text(data.get("fastest_decay_catalyst"), "insufficient_data"),
            "strongest_persistence_pattern": _text(data.get("strongest_persistence_pattern"), "insufficient_data"),
            "strongest_decay_pattern": _text(data.get("strongest_decay_pattern"), "insufficient_data"),
            "best_catalyst_half_life": _to_float(data.get("best_catalyst_half_life"), 0.0),
            "worst_catalyst_half_life": _to_float(data.get("worst_catalyst_half_life"), 0.0),
            "best_catalyst_half_life_type": _text(data.get("best_catalyst_half_life_type"), "insufficient_data"),
            "worst_catalyst_half_life_type": _text(data.get("worst_catalyst_half_life_type"), "insufficient_data"),
            "catalyst_decay_readiness": _to_float(data.get("catalyst_decay_readiness"), 0.0),
            "catalyst_decay_confidence": _to_float(data.get("catalyst_decay_confidence"), 0.0),
            "profit_capture_before_decay": _to_float(data.get("profit_capture_before_decay"), 0.0),
            "profit_capture_after_decay": _to_float(data.get("profit_capture_after_decay"), 0.0),
            "continuation_after_catalyst_weakening": _to_float(data.get("continuation_after_catalyst_weakening"), 0.0),
            "giveback_after_catalyst_weakening": _to_float(data.get("giveback_after_catalyst_weakening"), 0.0),
            "cache_freshness": _text(data.get("cache_freshness"), "fresh"),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue catalyst persistence learning shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _catalyst_lifecycle_intelligence_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_catalyst_lifecycle_intelligence"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "lifecycle_stages": list(data.get("lifecycle_stages") or [])[:6],
            "catalyst_lifecycle_rows": list(data.get("catalyst_lifecycle_rows") or [])[:13],
            "strongest_catalyst_stage": _text(data.get("strongest_catalyst_stage"), "insufficient_data"),
            "weakest_catalyst_stage": _text(data.get("weakest_catalyst_stage"), "insufficient_data"),
            "best_catalyst_lifecycle": _text(data.get("best_catalyst_lifecycle"), "insufficient_data"),
            "worst_catalyst_lifecycle": _text(data.get("worst_catalyst_lifecycle"), "insufficient_data"),
            "catalyst_lifecycle_confidence": _to_float(data.get("catalyst_lifecycle_confidence"), 0.0),
            "average_persistence_score": _to_float(data.get("average_persistence_score"), 0.0),
            "average_decay_probability": _to_float(data.get("average_decay_probability"), 0.0),
            "average_continuation_probability": _to_float(data.get("average_continuation_probability"), 0.0),
            "average_lifespan_minutes": _to_float(data.get("average_lifespan_minutes"), 0.0),
            "best_stage_profitability_score": _to_float(data.get("best_stage_profitability_score"), 0.0),
            "worst_stage_giveback_pct": _to_float(data.get("worst_stage_giveback_pct"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue catalyst lifecycle learning shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _cross_sector_capital_flow_memory_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_cross_sector_capital_flow_memory"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "sector_flow_rows": list(data.get("sector_flow_rows") or [])[:10],
            "sector_transition_memory": list(data.get("sector_transition_memory") or [])[:5],
            "theme_transition_memory": list(data.get("theme_transition_memory") or [])[:5],
            "strongest_inflow_sector": _text(data.get("strongest_inflow_sector"), "insufficient_data"),
            "strongest_outflow_sector": _text(data.get("strongest_outflow_sector"), "insufficient_data"),
            "flow_persistence": _to_float(data.get("flow_persistence"), 0.0),
            "rotation_speed": _to_float(data.get("rotation_speed"), 0.0),
            "continuation_after_inflow": _to_float(data.get("continuation_after_inflow"), 0.0),
            "continuation_after_outflow": _to_float(data.get("continuation_after_outflow"), 0.0),
            "strongest_capital_flow": _text(data.get("strongest_capital_flow"), "insufficient_data"),
            "weakest_capital_flow": _text(data.get("weakest_capital_flow"), "insufficient_data"),
            "strongest_sector_rotation": _text(data.get("strongest_sector_rotation"), "insufficient_data"),
            "strongest_theme_rotation": _text(data.get("strongest_theme_rotation"), "insufficient_data"),
            "sector_flow_confidence": _to_float(data.get("sector_flow_confidence"), 0.0),
            "rotation_confidence": _to_float(data.get("rotation_confidence"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue cross-sector capital-flow learning shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _candidate_ranking_attribution_promotion_intelligence_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_candidate_ranking_audit"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "promoted_candidates": _to_int(data.get("promoted_candidates"), 0),
            "rejected_candidates": _to_int(data.get("rejected_candidates"), 0),
            "selected_candidates": _to_int(data.get("selected_candidates"), 0),
            "missed_candidates": _to_int(data.get("missed_candidates"), 0),
            "top_ranked_candidates": _to_int(data.get("top_ranked_candidates"), 0),
            "actual_winners": _to_int(data.get("actual_winners"), 0),
            "actual_losers": _to_int(data.get("actual_losers"), 0),
            "ranking_accuracy": _to_float(data.get("ranking_accuracy"), 0.0),
            "promotion_accuracy": _to_float(data.get("promotion_accuracy"), 0.0),
            "rejection_accuracy": _to_float(data.get("rejection_accuracy"), 0.0),
            "ranking_miss_rate": _to_float(data.get("ranking_miss_rate"), 0.0),
            "ranking_overconfidence": _to_float(data.get("ranking_overconfidence"), 0.0),
            "ranking_underconfidence": _to_float(data.get("ranking_underconfidence"), 0.0),
            "ranking_consistency": _to_float(data.get("ranking_consistency"), 0.0),
            "ranking_factor_rows": list(data.get("ranking_factor_rows") or [])[:14],
            "strongest_positive_ranking_factor": _text(data.get("strongest_positive_ranking_factor"), "insufficient_data"),
            "strongest_negative_ranking_factor": _text(data.get("strongest_negative_ranking_factor"), "insufficient_data"),
            "most_predictive_ranking_factor": _text(data.get("most_predictive_ranking_factor"), "insufficient_data"),
            "least_predictive_ranking_factor": _text(data.get("least_predictive_ranking_factor"), "insufficient_data"),
            "most_overvalued_factor": _text(data.get("most_overvalued_factor"), "insufficient_data"),
            "most_undervalued_factor": _text(data.get("most_undervalued_factor"), "insufficient_data"),
            "promotion_success_rate": _to_float(data.get("promotion_success_rate"), 0.0),
            "promotion_failure_rate": _to_float(data.get("promotion_failure_rate"), 0.0),
            "promotion_alpha_score": _to_float(data.get("promotion_alpha_score"), 0.0),
            "promotion_confidence_score": _to_float(data.get("promotion_confidence_score"), 0.0),
            "best_promoted_candidate": _text(data.get("best_promoted_candidate"), "insufficient_data"),
            "worst_promoted_candidate": _text(data.get("worst_promoted_candidate"), "insufficient_data"),
            "biggest_missed_promotion": _text(data.get("biggest_missed_promotion"), "insufficient_data"),
            "biggest_false_promotion": _text(data.get("biggest_false_promotion"), "insufficient_data"),
            "missed_winners": _to_int(data.get("missed_winners"), 0),
            "missed_alpha": _to_float(data.get("missed_alpha"), 0.0),
            "opportunity_ranking_gap": _to_float(data.get("opportunity_ranking_gap"), 0.0),
            "dominant_missed_winner_pattern": _text(data.get("dominant_missed_winner_pattern"), "insufficient_data"),
            "dominant_ranking_mistake": _text(data.get("dominant_ranking_mistake"), "insufficient_data"),
            "dominant_rejection_mistake": _text(data.get("dominant_rejection_mistake"), "insufficient_data"),
            "most_common_missed_catalyst": _text(data.get("most_common_missed_catalyst"), "insufficient_data"),
            "most_common_missed_sector_rotation": _text(data.get("most_common_missed_sector_rotation"), "insufficient_data"),
            "most_common_missed_regime_signal": _text(data.get("most_common_missed_regime_signal"), "insufficient_data"),
            "ranking_quality_score": _to_float(data.get("ranking_quality_score"), 0.0),
            "ranking_confidence_score": _to_float(data.get("ranking_confidence_score"), 0.0),
            "ranking_predictive_power": _to_float(data.get("ranking_predictive_power"), 0.0),
            "ranking_reliability": _to_float(data.get("ranking_reliability"), 0.0),
            "ranking_maturity": _text(data.get("ranking_maturity"), "warming_up"),
            "strongest_promotion_archetype": _text(data.get("strongest_promotion_archetype"), "insufficient_data"),
            "strongest_promotion_regime": _text(data.get("strongest_promotion_regime"), "insufficient_data"),
            "strongest_promotion_sector": _text(data.get("strongest_promotion_sector"), "insufficient_data"),
            "strongest_promotion_catalyst": _text(data.get("strongest_promotion_catalyst"), "insufficient_data"),
            "weakest_promotion_archetype": _text(data.get("weakest_promotion_archetype"), "insufficient_data"),
            "weakest_promotion_regime": _text(data.get("weakest_promotion_regime"), "insufficient_data"),
            "weakest_promotion_sector": _text(data.get("weakest_promotion_sector"), "insufficient_data"),
            "weakest_promotion_catalyst": _text(data.get("weakest_promotion_catalyst"), "insufficient_data"),
            "strongest_ranking_lesson": _text(data.get("strongest_ranking_lesson"), "Continue ranking audit shadow-only."),
            "strongest_promotion_lesson": _text(data.get("strongest_promotion_lesson"), "Continue promotion audit shadow-only."),
            "strongest_rejection_lesson": _text(data.get("strongest_rejection_lesson"), "Continue rejection audit shadow-only."),
            "dominant_ranking_blind_spot": _text(data.get("dominant_ranking_blind_spot"), "insufficient_data"),
            "next_ranking_focus": _text(data.get("next_ranking_focus"), "insufficient_data"),
            "highest_expected_ranking_improvement": _text(data.get("highest_expected_ranking_improvement"), "insufficient_data"),
            "candidate_ranking_influence_readiness": _text(data.get("candidate_ranking_influence_readiness"), "insufficient_evidence"),
            "confidence_score": _to_float(data.get("confidence_score"), 0.0),
            "consistency_score": _to_float(data.get("consistency_score"), 0.0),
            "attribution_quality": _to_float(data.get("attribution_quality"), 0.0),
            "ranking_truth_score": _to_float(data.get("ranking_truth_score"), 0.0),
            "influence_ready": bool(data.get("influence_ready", False)),
            "influence_confidence": _to_float(data.get("influence_confidence"), 0.0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue candidate ranking audit before any ranking influence."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _intelligence_quality_learning_efficiency_suite_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        modules = dict(data.get("modules") or {})
        summary = dict(data.get("summary") or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Intelligence Quality & Learning Efficiency Suite V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "shadow_analysis_intelligence_quality_learning_efficiency"),
            "shadow_only": bool(data.get("shadow_only", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "highest_value_learning_system": _text(data.get("highest_value_learning_system") or summary.get("highest_value_learning_system"), "insufficient_data"),
            "weighted_evidence_count": _to_float(data.get("weighted_evidence_count"), 0.0),
            "weakest_confidence_component": _text(data.get("weakest_confidence_component") or summary.get("weakest_confidence_component"), "insufficient_data"),
            "drift_warning": _text(data.get("drift_warning") or summary.get("drift_warning"), "insufficient_data"),
            "most_similar_regime": _text(data.get("most_similar_regime"), "insufficient_data"),
            "ranking_tournament_regret": _to_float(data.get("ranking_tournament_regret") or summary.get("largest_ranking_regret"), 0.0),
            "exit_tournament_capture_gap": _to_float(data.get("exit_tournament_capture_gap"), 0.0),
            "largest_exit_regret": _to_float(summary.get("largest_exit_regret"), 0.0),
            "conviction_calibration_score": _to_float(data.get("conviction_calibration_score"), 0.0),
            "recommended_next_focus": _text(data.get("recommended_next_focus") or summary.get("recommended_next_focus"), "continue_shadow_diagnostics"),
            "modules_reporting_insufficient_evidence": list(data.get("modules_reporting_insufficient_evidence") or [])[:8],
            "learning_roi_status": _text((modules.get("learning_roi_engine_v1") or {}).get("status"), "not_loaded"),
            "ranking_tournament_count": _to_int((modules.get("ranking_tournament_engine_v1") or {}).get("tournament_count"), 0),
            "exit_tournament_count": _to_int((modules.get("exit_tournament_engine_v1") or {}).get("exit_tournament_count"), 0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "promotion_logic_changed": bool(data.get("promotion_logic_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
        }

    def _advanced_attribution_controlled_exit_learning_roi_suite_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        summary = dict(data.get("summary") or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Advanced Attribution, Controlled Exit Validation & Learning ROI Suite V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "shadow_only_advanced_attribution_controlled_exit_learning_roi"),
            "shadow_only": bool(data.get("shadow_only", True)),
            "learning_only": bool(data.get("learning_only", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "top_win_drivers": list(data.get("top_win_drivers") or [])[:5],
            "top_loss_drivers": list(data.get("top_loss_drivers") or [])[:5],
            "most_predictive_factors": list(data.get("most_predictive_factors") or [])[:5],
            "buy_purity_leakage_sources": list(data.get("buy_purity_leakage_sources") or [])[:6],
            "highest_roi_improvement_areas": list(data.get("highest_roi_improvement_areas") or [])[:6],
            "highest_roi_improvement_area": _text(data.get("highest_roi_improvement_area") or summary.get("highest_expected_pf_impact"), "insufficient_data"),
            "estimated_pf_gain": _to_float(data.get("estimated_pf_gain"), 0.0),
            "best_exit_candidate": _text(data.get("best_exit_candidate") or summary.get("best_exit_candidate"), "insufficient_data"),
            "highest_improvement_candidate": _text(data.get("highest_improvement_candidate"), "insufficient_data"),
            "exit_validation_score": _to_float(data.get("exit_validation_score"), 0.0),
            "policy_readiness_score": _to_float(data.get("policy_readiness_score"), 0.0),
            "exit_candidate_rows": list(data.get("exit_candidate_rows") or [])[:7],
            "policy_readiness": list(data.get("policy_readiness") or [])[:6],
            "profit_lost_estimate": _to_float(data.get("profit_lost_estimate"), 0.0),
            "giveback_attribution": _text(data.get("giveback_attribution"), "insufficient_data"),
            "capture_attribution": _text(data.get("capture_attribution"), "insufficient_data"),
            "lifecycle_quality_score": _to_float(data.get("lifecycle_quality_score"), 0.0),
            "best_hold_window": _text(data.get("best_hold_window"), "insufficient_data"),
            "best_capture_window": _text(data.get("best_capture_window"), "insufficient_data"),
            "highest_giveback_window": _text(data.get("highest_giveback_window"), "insufficient_data"),
            "best_profit_retention_window": _text(data.get("best_profit_retention_window"), "insufficient_data"),
            "continuation_failure_patterns": _text(data.get("continuation_failure_patterns"), "insufficient_data"),
            "catalyst_coverage": _to_float(data.get("catalyst_coverage"), 0.0),
            "unknown_catalyst_rate": _to_float(data.get("unknown_catalyst_rate"), 0.0),
            "strongest_sector": _text(data.get("strongest_sector"), "insufficient_data"),
            "weakest_sector": _text(data.get("weakest_sector"), "insufficient_data"),
            "strongest_catalyst": _text(data.get("strongest_catalyst"), "insufficient_data"),
            "weakest_catalyst": _text(data.get("weakest_catalyst"), "insufficient_data"),
            "best_regime": _text(data.get("best_regime"), "insufficient_data"),
            "best_sector_regime_pair": _text(data.get("best_sector_regime_pair"), "insufficient_data"),
            "unknown_catalyst_trend": _text(data.get("unknown_catalyst_trend"), "insufficient_data"),
            "strongest_symbol_family": _text(data.get("strongest_symbol_family"), "insufficient_data"),
            "weakest_symbol_family": _text(data.get("weakest_symbol_family"), "insufficient_data"),
            "why_profits_are_being_lost": _text(data.get("why_profits_are_being_lost") or summary.get("top_profit_loss_driver"), "insufficient_data"),
            "why_buy_purity_is_below_target": _text(data.get("why_buy_purity_is_below_target"), "insufficient_data"),
            "why_exits_underperform": _text(data.get("why_exits_underperform"), "insufficient_data"),
            "future_policy_candidate_closest_to_readiness": _text(data.get("future_policy_candidate_closest_to_readiness"), "insufficient_data"),
            "recommended_next_focus": _text(summary.get("recommended_next_focus") or data.get("highest_roi_improvement_area"), "continue_shadow_attribution"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "promotion_logic_changed": bool(data.get("promotion_logic_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _profit_optimization_context_intelligence_suite_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Profit Optimization, Interaction Intelligence & Decision Engine V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "shadow_only_profit_optimization_context_intelligence"),
            "shadow_only": bool(data.get("shadow_only", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "learning_only": bool(data.get("learning_only", True)),
            "auto_apply": bool(data.get("auto_apply", False)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "exit_candidate_rows": list(data.get("exit_candidate_rows") or [])[:9],
            "best_exit_candidate": _text(data.get("best_exit_candidate"), "insufficient_data"),
            "highest_improvement_candidate": _text(data.get("highest_improvement_candidate"), "insufficient_data"),
            "expected_pf_improvement": _to_float(data.get("expected_pf_improvement"), 0.0),
            "expected_avg_return_improvement": _to_float(data.get("expected_avg_return_improvement"), 0.0),
            "expected_giveback_reduction": _to_float(data.get("expected_giveback_reduction"), 0.0),
            "exit_validation_confidence": _to_float(data.get("exit_validation_confidence"), 0.0),
            "exit_policy_readiness": _text(data.get("exit_policy_readiness"), "shadow_validation_only"),
            "catalyst_coverage_pct": _to_float(data.get("catalyst_coverage_pct"), 0.0),
            "unknown_catalyst_pct": _to_float(data.get("unknown_catalyst_pct"), 0.0),
            "catalyst_persistence": _to_float(data.get("catalyst_persistence"), 0.0),
            "catalyst_half_life": _text(data.get("catalyst_half_life"), "insufficient_data"),
            "catalyst_decay": _to_float(data.get("catalyst_decay"), 0.0),
            "catalyst_failure_patterns": _text(data.get("catalyst_failure_patterns"), "insufficient_data"),
            "best_catalyst_horizon": _text(data.get("best_catalyst_horizon"), "insufficient_data"),
            "best_catalyst_exit": _text(data.get("best_catalyst_exit"), "insufficient_data"),
            "catalyst_reliability_score": _to_float(data.get("catalyst_reliability_score"), 0.0),
            "strongest_catalyst": _text(data.get("strongest_catalyst"), "insufficient_data"),
            "weakest_catalyst": _text(data.get("weakest_catalyst"), "insufficient_data"),
            "dominant_catalyst": _text(data.get("dominant_catalyst"), "insufficient_data"),
            "unknown_catalyst_trend": _text(data.get("unknown_catalyst_trend"), "insufficient_data"),
            "catalyst_decay_risk": _to_float(data.get("catalyst_decay_risk"), 0.0),
            "buy_purity_score": _to_float(data.get("buy_purity_score"), 0.0),
            "buy_purity_target_gap": _to_float(data.get("buy_purity_target_gap"), 0.0),
            "purity_leakage_ranking": list(data.get("purity_leakage_ranking") or [])[:8],
            "highest_roi_purity_fix": _text(data.get("highest_roi_purity_fix"), "insufficient_data"),
            "expected_purity_improvement": _to_float(data.get("expected_purity_improvement"), 0.0),
            "buy_purity_confidence": _to_float(data.get("confidence"), 0.0),
            "symbol_profiles": list(data.get("symbol_profiles") or [])[:8],
            "sector_profiles": list(data.get("sector_profiles") or [])[:10],
            "regime_profiles": list(data.get("regime_profiles") or [])[:8],
            "best_symbol_exit": _text(data.get("best_symbol_exit"), "insufficient_data"),
            "worst_symbol_exit": _text(data.get("worst_symbol_exit"), "insufficient_data"),
            "strongest_sector": _text(data.get("strongest_sector"), "insufficient_data"),
            "weakest_sector": _text(data.get("weakest_sector"), "insufficient_data"),
            "best_sector_exit": _text(data.get("best_sector_exit"), "insufficient_data"),
            "best_regime_exit": _text(data.get("best_regime_exit"), "insufficient_data"),
            "highest_giveback_symbol": _text(data.get("highest_giveback_symbol"), "insufficient_data"),
            "highest_giveback_sector": _text(data.get("highest_giveback_sector"), "insufficient_data"),
            "highest_giveback_regime": _text(data.get("highest_giveback_regime"), "insufficient_data"),
            "top_opportunity_cost_drivers": list(data.get("top_opportunity_cost_drivers") or [])[:6],
            "missed_winner_count": _to_int(data.get("missed_winner_count"), 0),
            "avoided_loser_count": _to_int(data.get("avoided_loser_count"), 0),
            "selection_quality": _to_float(data.get("selection_quality"), 0.0),
            "opportunity_cost_confidence": _to_float(data.get("opportunity_cost_confidence"), 0.0),
            "highest_roi_selection_fix": _text(data.get("highest_roi_selection_fix"), "insufficient_data"),
            "interaction_rows": list(data.get("interaction_rows") or [])[:8],
            "best_interaction_combo": _text(data.get("best_interaction_combo"), "insufficient_data"),
            "worst_interaction_combo": _text(data.get("worst_interaction_combo"), "insufficient_data"),
            "best_exit_by_context": _text(data.get("best_exit_by_context"), "insufficient_data"),
            "context_where_profit_lock_works": _text(data.get("context_where_profit_lock_works"), "insufficient_data"),
            "context_where_catalyst_exit_works": _text(data.get("context_where_catalyst_exit_works"), "insufficient_data"),
            "context_where_horizon_exit_works": _text(data.get("context_where_horizon_exit_works"), "insufficient_data"),
            "context_where_current_exit_underperforms": _text(data.get("context_where_current_exit_underperforms"), "insufficient_data"),
            "highest_roi_improvement_area": _text(data.get("highest_roi_improvement_area"), "insufficient_data"),
            "improvement_priority_ranking": list(data.get("improvement_priority_ranking") or [])[:10],
            "expected_pf_gain_ranking": list(data.get("expected_pf_gain_ranking") or [])[:10],
            "expected_avg_return_gain_ranking": list(data.get("expected_avg_return_gain_ranking") or [])[:10],
            "lowest_confidence_area": _text(data.get("lowest_confidence_area"), "insufficient_data"),
            "most_ready_improvement": _text(data.get("most_ready_improvement"), "insufficient_data"),
            "best_improvement_to_validate_next": _text(data.get("best_improvement_to_validate_next"), "insufficient_data"),
            "best_context_where_it_works": _text(data.get("best_context_where_it_works"), "insufficient_data"),
            "contexts_where_it_fails": list(data.get("contexts_where_it_fails") or [])[:6],
            "expected_pf_impact": _to_float(data.get("expected_pf_impact"), 0.0),
            "expected_avg_return_impact": _to_float(data.get("expected_avg_return_impact"), 0.0),
            "confidence": _to_float(data.get("confidence"), 0.0),
            "evidence_level": _text(data.get("evidence_level"), "cached_summary"),
            "readiness_level": _text(data.get("readiness_level"), "shadow_validation_only"),
            "reasoning_summary": _text(data.get("reasoning_summary"), "Continue shadow-only profit optimization diagnostics."),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "promotion_logic_changed": bool(data.get("promotion_logic_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _trade_lifecycle_audit_truth_horizon_integrity_suite_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        audit = dict(data.get("trade_lifecycle_audit_suite_v1") or {})
        truth = dict(data.get("trade_lifecycle_truth_audit_v1") or {})
        horizon = dict(data.get("horizon_integrity_conversion_intelligence_v1") or {})
        answers = dict(data.get("final_report_answers") or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Trade Lifecycle Audit, Truth Validation & Conditional Horizon Integrity Suite V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "paper_only_lifecycle_truth_validation_advisory"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "total_active_positions": _to_int(data.get("total_active_positions") or audit.get("total_active_positions"), 0),
            "position_rows_audited": _to_int(audit.get("position_rows_audited"), 0),
            "broker_confirmed_positions": _to_int(audit.get("broker_confirmed_positions"), 0),
            "stale_internal_rows": _to_int(audit.get("stale_internal_rows"), 0),
            "active_position_source": _text(audit.get("active_position_source"), "none"),
            "average_hold_duration_hours": _to_float(data.get("average_hold_duration_hours") or audit.get("average_hold_hours"), 0.0),
            "average_hold_duration_days": _to_float(audit.get("average_hold_days"), 0.0),
            "oldest_position": _text(data.get("oldest_position") or audit.get("oldest_position"), "insufficient_data"),
            "oldest_position_hold_hours": _to_float(audit.get("oldest_position_hold_hours"), 0.0),
            "most_overdue_position": _text(data.get("most_overdue_position") or audit.get("most_overdue_position"), "insufficient_data"),
            "most_profitable_position": _text(data.get("most_profitable_position") or audit.get("most_profitable_position"), "insufficient_data"),
            "most_profitable_position_pct": _to_float(audit.get("most_profitable_position_pct"), 0.0),
            "highest_giveback_risk_position": _text(data.get("highest_giveback_risk_position") or audit.get("highest_giveback_risk_position"), "insufficient_data"),
            "highest_giveback_risk": _to_float(audit.get("highest_giveback_risk"), 0.0),
            "biggest_exit_blocker": _text(data.get("biggest_exit_blocker") or audit.get("biggest_exit_blocker"), "insufficient_data"),
            "dominant_hold_reason": _text(data.get("dominant_hold_reason") or audit.get("dominant_hold_reason"), "insufficient_data"),
            "dominant_active_horizon": _text(audit.get("dominant_active_horizon"), "unknown"),
            "horizon_distribution": dict(audit.get("horizon_distribution") or {}),
            "active_overdue_pct": _to_float(audit.get("active_overdue_pct"), 0.0),
            "would_repurchase_today_pct": _to_float(audit.get("would_repurchase_today_pct"), 0.0),
            "same_decision_if_replayed_today_count": _to_int(audit.get("same_decision_if_replayed_today_count"), 0),
            "correctly_holding_count": _to_int(truth.get("correctly_holding_count"), 0),
            "should_have_sold_count": _to_int(truth.get("should_have_sold_count"), 0),
            "should_have_converted_horizon_count": _to_int(truth.get("should_have_converted_horizon_count"), 0),
            "should_have_profit_protected_count": _to_int(truth.get("should_have_profit_protected_count"), 0),
            "average_truth_confidence": _to_float(truth.get("average_truth_confidence"), 0.0),
            "horizon_integrity_needed": bool(data.get("horizon_integrity_needed") or audit.get("horizon_integrity_needed")),
            "horizon_integrity_status": _text(horizon.get("status"), "not_needed"),
            "horizon_integrity_reason": _text(horizon.get("reason") or audit.get("horizon_integrity_reason"), "insufficient_data"),
            "review_convert_sell_only": bool(horizon.get("review_convert_sell_only", True)),
            "scalp_to_swing_direct_conversion_allowed": bool(horizon.get("scalp_to_swing_direct_conversion_allowed", False)),
            "position_audit_rows": list(data.get("position_audit_rows") or [])[:12],
            "truth_validation_rows": list(data.get("truth_validation_rows") or [])[:12],
            "horizon_conversion_rows": list(horizon.get("conversion_rows") or [])[:12],
            "final_report_answers": answers,
            "is_astra_holding_everything_too_long": _text(answers.get("is_astra_holding_everything_too_long"), "insufficient_data"),
            "intentionally_holding_or_drifting": _text(answers.get("intentionally_holding_or_drifting"), "insufficient_data"),
            "unintentionally_swing_system": bool(answers.get("unintentionally_swing_system", False)),
            "pf_contribution_by_horizon_pct": dict(answers.get("pf_contribution_by_horizon_pct") or {}),
            "single_highest_roi_fix": _text(answers.get("single_highest_roi_fix"), "insufficient_data"),
            "safest_next_implementation": _text(answers.get("safest_next_implementation"), "review_only_diagnostics"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "sell_behavior_changed": bool(data.get("sell_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _astra_foundation_stabilization_governance_bundle_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        integrity = dict(data.get("trading_integrity_stabilization") or {})
        horizon_exit = dict(data.get("horizon_exit_candidate_engine_v1") or {})
        exit_pipeline = dict(data.get("exit_pipeline_integrity_v1") or {})
        profit_truth = dict(data.get("profit_capture_truth_engine_v1") or {})
        capital = dict(data.get("capital_efficiency_engine_v1") or {})
        audit = dict(data.get("astra_internal_audit_department_v1") or {})
        operations = dict(data.get("astra_operations_department_v1") or {})
        resource = dict(data.get("astra_resource_manager_v1") or {})
        registry = dict(data.get("astra_system_registry_v1") or {})
        preservation = dict(data.get("astra_knowledge_preservation_framework_v1") or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Tier 1 Foundation Stabilization & Governance Bundle V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "foundation_stabilization_governance_advisory"),
            "unknown_horizon_positions": _to_int(data.get("unknown_horizon_positions") or integrity.get("unknown_horizon_positions"), 0),
            "infer_horizon_style_reads_paper_entry_horizon_style": bool(integrity.get("infer_horizon_style_reads_paper_entry_horizon_style", False)),
            "broker_confirmed_positions_source_of_truth": bool(integrity.get("broker_confirmed_positions_source_of_truth", False)),
            "stale_internal_rows_distort_active_positions": bool(integrity.get("stale_internal_rows_distort_active_positions", False)),
            "horizon_reconciliation_persistent": bool(integrity.get("horizon_reconciliation_persistent", False)),
            "learned_exit_candidates_today": _to_int(integrity.get("learned_exit_candidates_today"), 0),
            "learned_exit_candidates_today_diagnosis": _text(data.get("learned_exit_candidates_today_diagnosis") or integrity.get("learned_exit_candidates_today_diagnosis"), "insufficient_data"),
            "horizon_exit_candidate_count": _to_int(horizon_exit.get("candidate_count"), 0),
            "horizon_exit_due_count": _to_int(horizon_exit.get("exit_due_count"), 0),
            "horizon_conversion_candidate_count": _to_int(horizon_exit.get("conversion_candidate_count"), 0),
            "horizon_exit_candidate_rows": list(horizon_exit.get("rows") or [])[:12],
            "generated_exits": _to_int(exit_pipeline.get("generated_exits"), 0),
            "suppressed_exits": _to_int(exit_pipeline.get("suppressed_exits"), 0),
            "blocked_exits": _to_int(exit_pipeline.get("blocked_exits"), 0),
            "rejected_exits": _to_int(exit_pipeline.get("rejected_exits"), 0),
            "biggest_exit_blocker": _text(data.get("biggest_exit_blocker") or exit_pipeline.get("biggest_exit_blocker"), "insufficient_data"),
            "exit_blockers": list(exit_pipeline.get("exit_blockers") or [])[:8],
            "mfe_average": _to_float(profit_truth.get("mfe_average"), 0.0),
            "current_profit_average": _to_float(profit_truth.get("current_profit_average"), 0.0),
            "giveback": _to_float(profit_truth.get("giveback"), 0.0),
            "capture_ratio": _to_float(profit_truth.get("capture_ratio"), 0.0),
            "peak_decay": _to_float(profit_truth.get("peak_decay"), 0.0),
            "profit_protection_opportunity": bool(profit_truth.get("profit_protection_opportunity", False)),
            "biggest_profit_capture_leak": _text(data.get("biggest_profit_capture_leak") or profit_truth.get("biggest_profit_capture_leak"), "insufficient_data"),
            "trapped_capital_status": _text(data.get("trapped_capital_status") or capital.get("trapped_capital_status"), "insufficient_data"),
            "trapped_capital": bool(capital.get("trapped_capital", False)),
            "total_capacity": _to_int(capital.get("total_capacity"), 0),
            "total_used": _to_int(capital.get("total_used"), 0),
            "total_available": _to_int(capital.get("total_available"), 0),
            "missed_opportunity_pressure": _to_int(capital.get("missed_opportunity_pressure"), 0),
            "internal_audit_status": _text(audit.get("department"), "Astra Internal Audit Department V1"),
            "oversight_governor_status": _text(data.get("oversight_governor_status") or operations.get("endpoint_health"), "monitoring"),
            "pause_unsafe_optional_workers_recommended": bool(operations.get("pause_unsafe_optional_workers_recommended", False)),
            "api_governor_status": _text(data.get("api_governor_status"), "active_cache_first_zero_dashboard_provider_calls"),
            "dashboard_provider_calls_used": _to_int(resource.get("dashboard_provider_calls_used"), 0),
            "api_calls_tracked": _to_int(resource.get("api_calls_tracked"), 0),
            "bandwidth_used_gb": _to_float(resource.get("bandwidth_used_gb"), 0.0),
            "registry_status": _text(data.get("registry_status") or registry.get("registry_status"), "insufficient_data"),
            "registered_system_count": _to_int(registry.get("registered_system_count"), 0),
            "registered_systems": list(registry.get("systems") or [])[:12],
            "knowledge_preservation_status": _text(preservation.get("preservation_status"), "insufficient_data"),
            "existing_intelligence_preserved": bool(preservation.get("existing_intelligence_preserved", True)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _astra_tier2a_librarian_executive_truth_layer_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        librarian = dict(data.get("astra_librarian_v1") or {})
        executive = dict(data.get("executive_assistant_orchestrator_v1") or {})
        truth = dict(data.get("unified_truth_layer_v1") or {})
        compression = dict(data.get("knowledge_compression_engine_v1") or {})
        retrieval = dict(data.get("retrieval_engine_integration_v1") or {})
        tier1 = dict(data.get("tier1_integration") or {})
        shadow = dict(data.get("shadow_lab_integration") or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Tier 2A - Librarian, Executive Assistant & Unified Truth Layer V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "shadow_only_intelligence_organization"),
            "source_systems_reviewed": _to_int(data.get("source_systems_reviewed"), 0),
            "lessons_organized": _to_int(data.get("lessons_organized") or librarian.get("lessons_organized"), 0),
            "duplicate_findings_reduced": _to_int(data.get("duplicate_findings_reduced") or truth.get("duplicate_findings_reduced"), 0),
            "master_truths_created": _to_int(data.get("master_truths_created") or truth.get("master_truths_created"), 0),
            "retrieval_indexes_created": bool(data.get("retrieval_indexes_created") or librarian.get("retrieval_indexes_created")),
            "retrieval_index_count": _to_int(retrieval.get("index_count"), 0),
            "compression_status": _text(data.get("compression_status") or compression.get("compression_status"), "insufficient_evidence"),
            "executive_assistant_status": _text(data.get("executive_assistant_status") or executive.get("executive_assistant_status"), "insufficient_evidence"),
            "unified_truth_status": _text(data.get("unified_truth_status") or truth.get("unified_truth_status"), "insufficient_evidence"),
            "strongest_master_truth": _text(data.get("strongest_master_truth") or truth.get("strongest_master_truth"), "insufficient_evidence"),
            "recommended_next_focus": _text(data.get("recommended_next_focus"), "continue_cache_first_intelligence_organization"),
            "top_5_insights": list(data.get("top_5_insights") or executive.get("top_5") or [])[:5],
            "top_10_insights": list(data.get("top_10_insights") or executive.get("top_10") or [])[:10],
            "top_25_insights": list(data.get("top_25_insights") or executive.get("top_25") or [])[:25],
            "master_issues": list(truth.get("master_issues") or [])[:12],
            "retrieval_indexes": dict(librarian.get("retrieval_indexes") or retrieval.get("indexes") or {}),
            "registered_systems": list(tier1.get("registered_systems") or [])[:8],
            "tier1_integration_status": _text(tier1.get("status"), "insufficient_evidence"),
            "shadow_lab_integration_status": _text(shadow.get("status"), "shadow_only"),
            "policy_promotion_enabled": bool(shadow.get("policy_promotion_enabled", False)),
            "trade_influence_enabled": bool(shadow.get("trade_influence_enabled", False)),
            "ranking_influence_enabled": bool(shadow.get("ranking_influence_enabled", False)),
            "broker_influence_enabled": bool(shadow.get("broker_influence_enabled", False)),
            "paper_execution_influence_enabled": bool(shadow.get("paper_execution_influence_enabled", False)),
            "dashboard_performance_impact": _text(data.get("dashboard_performance_impact"), "single_unified_diagnostics_panel_cache_first"),
            "dashboard_provider_calls_used": _to_int(data.get("dashboard_provider_calls_used"), 0),
            "dashboard_api_calls_added": _to_int(data.get("dashboard_api_calls_added"), 0),
            "dashboard_endpoint_storm_created": bool(data.get("dashboard_endpoint_storm_created", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
        }

    def _astra_satellite_network_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        coordinator = dict(data.get("satellite_coordinator_v1") or {})
        market = dict(data.get("market_structure_intelligence_v1") or {})
        sector = dict(data.get("sector_rotation_intelligence_v1") or {})
        catalyst = dict(data.get("catalyst_intelligence_v1") or {})
        family = dict(data.get("trade_family_intelligence_satellite_v1") or {})
        compression = dict(data.get("satellite_compression_layer") or {})
        integration = dict(data.get("tier1_tier2a_integration") or {})
        shadow = dict(data.get("shadow_lab_integration") or {})
        satellites = [market, sector, catalyst, family]
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Tier 2B - Satellites 1-4 & Satellite Coordinator V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "shadow_only_satellite_information_gathering"),
            "coordinator_status": _text(data.get("coordinator_status") or coordinator.get("status"), "insufficient_evidence"),
            "coordinator_health": _text(data.get("coordinator_health") or coordinator.get("health"), "warming_up"),
            "satellites_registered": _to_int(data.get("satellites_registered") or coordinator.get("satellites_registered"), 0),
            "satellites_created": list(data.get("satellites_created") or [])[:8],
            "satellite_statuses": list(coordinator.get("satellite_statuses") or [])[:8],
            "market_structure_status": _text(market.get("status"), "insufficient_evidence"),
            "market_structure_summary": _text(market.get("compressed_market_summary"), "insufficient cached context"),
            "sector_rotation_status": _text(sector.get("status"), "insufficient_evidence"),
            "sector_rotation_summary": _text(sector.get("compressed_sector_summary"), "insufficient cached context"),
            "catalyst_status": _text(catalyst.get("status"), "insufficient_evidence"),
            "catalyst_summary": _text(catalyst.get("compressed_catalyst_summary"), "insufficient cached context"),
            "trade_family_status": _text(family.get("status"), "insufficient_evidence"),
            "trade_family_summary": _text(family.get("compressed_trade_family_summary"), "insufficient cached context"),
            "compressed_lessons_count": _to_int(compression.get("compressed_lessons_count"), 0),
            "compression_status": _text(data.get("compression_status") or compression.get("status"), "insufficient_evidence"),
            "raw_data_passed_directly": bool(compression.get("raw_data_passed_directly", False)),
            "duplicates_prevented": _to_int(data.get("duplicates_prevented") or coordinator.get("duplicates_prevented"), 0),
            "bandwidth_usage": _to_float(data.get("bandwidth_usage") or coordinator.get("bandwidth_usage"), 0.0),
            "bandwidth_impact": _text(data.get("bandwidth_impact"), "zero_provider_bandwidth_cache_only"),
            "provider_api_impact": _text(data.get("provider_api_impact"), "unchanged_zero_dashboard_provider_calls"),
            "dashboard_impact": _text(data.get("dashboard_impact"), "one_collapsed_learning_center_section_unified_diagnostics_only"),
            "dashboard_endpoint_storm_created": bool(data.get("dashboard_endpoint_storm_created", False)),
            "dashboard_provider_calls_used": _to_int(data.get("dashboard_provider_calls_used"), 0),
            "registered_systems": list(integration.get("registered_systems") or [])[:8],
            "tier1_tier2a_integration_status": _text(integration.get("status"), "insufficient_evidence"),
            "shadow_lab_integration_status": _text(shadow.get("status"), "shadow_only"),
            "policy_influence_enabled": bool(shadow.get("policy_influence_enabled", False)),
            "trade_influence_enabled": bool(shadow.get("trade_influence_enabled", False)),
            "broker_influence_enabled": bool(shadow.get("broker_influence_enabled", False)),
            "ranking_influence_enabled": bool(shadow.get("ranking_influence_enabled", False)),
            "paper_execution_influence_enabled": bool(shadow.get("paper_execution_influence_enabled", False)),
            "shadow_influence_percentages_changed": bool(data.get("shadow_influence_changed", False) or shadow.get("shadow_influence_percentages_changed", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "satellite_health_rows": [
                {
                    "satellite_name": _text(row.get("satellite_name"), "satellite"),
                    "status": _text(row.get("status"), "insufficient_evidence"),
                    "health": _text(row.get("health"), "warming_up"),
                    "confidence": _to_float(row.get("confidence"), 0.0),
                    "duplicates_prevented": _to_int(row.get("duplicates_prevented"), 0),
                }
                for row in satellites
            ],
        }

    def _astra_tier3_historical_satellite_shadow_acceleration_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        historical = dict(data.get("historical_intelligence_expansion_v1") or {})
        shadow = dict(data.get("shadow_experimentation_acceleration_v1") or {})
        api = dict(data.get("api_bandwidth_safety") or {})
        integration = dict(data.get("librarian_unified_truth_executive_integration") or {})
        satellites = list(data.get("satellites_5_10") or [])
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Tier 3 - Historical Intelligence, Satellite Expansion & Shadow Acceleration V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "shadow_only_historical_satellite_shadow_acceleration"),
            "historical_intelligence_status": _text(data.get("historical_intelligence_status") or historical.get("historical_intelligence_status"), "insufficient_evidence"),
            "top_historical_lesson": _text(data.get("top_historical_lesson") or historical.get("top_historical_lesson"), "insufficient cached context"),
            "satellites_added": list(data.get("satellites_added") or [])[:8],
            "satellites_registered": _to_int(data.get("satellites_registered"), 0),
            "satellite_coordinator_status": _text(data.get("satellite_coordinator_status"), "insufficient_evidence"),
            "satellite_coordinator_health": _text(data.get("satellite_coordinator_health"), "warming_up"),
            "satellites_5_10": satellites[:8],
            "shadow_experiment_expansion_status": _text(data.get("shadow_experiment_expansion_status") or shadow.get("shadow_experiment_expansion_status"), "insufficient_evidence"),
            "shadow_experiment_units": _to_int(data.get("shadow_experiment_units") or shadow.get("shadow_experiments_reviewed"), 0),
            "historical_replays": _to_int(shadow.get("historical_replays"), 0),
            "virtual_exit_tests": _to_int(shadow.get("virtual_exit_tests"), 0),
            "horizon_tests": _to_int(shadow.get("horizon_tests"), 0),
            "profit_lock_tests": _to_int(shadow.get("profit_lock_tests"), 0),
            "promotion_readiness": _text(shadow.get("promotion_readiness"), "not_ready_shadow_only"),
            "top_shadow_lesson": _text(data.get("top_shadow_lesson") or shadow.get("top_shadow_lesson"), "insufficient cached context"),
            "compressed_lessons_created": _to_int(data.get("compressed_lessons_created"), 0),
            "compressed_lessons": list(data.get("compressed_lessons") or [])[:12],
            "compression_status": _text(data.get("compression_status"), "insufficient_evidence"),
            "top_satellite_insight": _text(data.get("top_satellite_insight"), "insufficient cached context"),
            "librarian_integration_status": _text(data.get("librarian_integration_status") or integration.get("librarian_integration_status"), "insufficient_evidence"),
            "unified_truth_integration_status": _text(data.get("unified_truth_integration_status") or integration.get("unified_truth_integration_status"), "insufficient_evidence"),
            "executive_assistant_integration_status": _text(data.get("executive_assistant_integration_status") or integration.get("executive_assistant_integration_status"), "insufficient_evidence"),
            "registered_systems": list(integration.get("registered_systems") or [])[:10],
            "api_bandwidth_impact": _text(data.get("api_bandwidth_impact"), "zero_dashboard_provider_calls_cache_first_gradual_history"),
            "provider_api_impact": _text(data.get("provider_api_impact"), "unchanged_zero_dashboard_provider_calls"),
            "dashboard_impact": _text(data.get("dashboard_impact"), "one_collapsed_learning_center_section_unified_diagnostics_only"),
            "dashboard_endpoint_storm_created": bool(data.get("dashboard_endpoint_storm_created", False)),
            "dashboard_provider_calls_used": _to_int(data.get("dashboard_provider_calls_used"), 0),
            "bandwidth_status": _text(api.get("bandwidth_status"), "safe"),
            "expansion_allowed": bool(api.get("expansion_allowed", False)),
            "blocked_reason": _text(api.get("blocked_reason"), "none"),
            "emergency_reserve_preserved": bool(api.get("emergency_reserve_preserved", True)),
            "historical_collection_gradual": bool(api.get("historical_collection_gradual", True)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "shadow_influence_changed": bool(data.get("shadow_influence_changed", False)),
        }

    def _astra_final_intelligence_maturation_bundle_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        modules = dict(data.get("modules") or {})
        compression = dict(modules.get("dynamic_knowledge_compression_v2") or {})
        historical = dict(modules.get("historical_intelligence_maturation_v2") or {})
        prioritization = dict(modules.get("adaptive_learning_prioritization_v2") or {})
        research = dict(modules.get("autonomous_research_department_lite") or {})
        portfolio = dict(modules.get("portfolio_construction_lite") or {})
        self_optimization = dict(modules.get("self_optimization_engine_v1") or {})
        health = dict(modules.get("autonomous_health_monitoring_v2") or {})
        profit_focus = dict(modules.get("unified_profit_improvement_focus") or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Final Intelligence Maturation Bundle V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "shadow_only_final_intelligence_maturation"),
            "final_major_architecture_bundle": bool(data.get("final_major_architecture_bundle", True)),
            "future_major_tiers_allowed": bool(data.get("future_major_tiers_allowed", False)),
            "future_work_scope": _text(data.get("future_work_scope"), "small_targeted_improvements_only_after_human_approval"),
            "modules_created": list(data.get("modules_created") or [])[:12],
            "compression_status": _text(data.get("compression_status") or compression.get("compression_status"), "insufficient_evidence"),
            "compressed_lessons": _to_int(compression.get("compressed_lessons"), 0),
            "archived_lessons": _to_int(compression.get("archived_lessons"), 0),
            "stale_lessons": _to_int(compression.get("stale_lessons"), 0),
            "duplicate_lessons_removed": _to_int(compression.get("duplicate_lessons_removed"), 0),
            "active_high_value_lessons": _to_int(compression.get("active_high_value_lessons"), 0),
            "compression_efficiency": _to_float(compression.get("compression_efficiency"), 0.0),
            "historical_maturity_status": _text(data.get("historical_maturity_status") or historical.get("historical_maturity_status"), "insufficient_evidence"),
            "memory_quality": _to_float(historical.get("memory_quality"), 0.0),
            "memory_maturity": _to_float(historical.get("memory_maturity"), 0.0),
            "retrieval_accuracy": _to_float(historical.get("retrieval_accuracy"), 0.0),
            "transfer_learning_quality": _to_float(historical.get("transfer_learning_quality"), 0.0),
            "historical_confidence": _to_float(historical.get("historical_confidence"), 0.0),
            "learning_prioritization_status": _text(data.get("learning_prioritization_status") or prioritization.get("learning_prioritization_status"), "insufficient_evidence"),
            "attention_allocation_pct": dict(prioritization.get("attention_allocation_pct") or {}),
            "research_department_status": _text(data.get("research_department_status") or research.get("research_department_status"), "insufficient_evidence"),
            "research_studies": _to_int(research.get("research_studies"), 0),
            "completed_research_studies": _to_int(research.get("completed_research_studies"), 0),
            "validated_research_studies": _to_int(research.get("validated_research_studies"), 0),
            "portfolio_intelligence_status": _text(data.get("portfolio_intelligence_status") or portfolio.get("portfolio_intelligence_status"), "insufficient_evidence"),
            "concentration_status": _text(portfolio.get("concentration_status"), "monitoring"),
            "correlation_status": _text(portfolio.get("correlation_status"), "monitoring"),
            "trapped_capital_status": _text(portfolio.get("trapped_capital_status"), "monitoring"),
            "capital_efficiency_score": _to_float(portfolio.get("capital_efficiency_score"), 0.0),
            "portfolio_utilization_score": _to_float(portfolio.get("portfolio_utilization_score"), 0.0),
            "self_optimization_status": _text(data.get("self_optimization_status") or self_optimization.get("self_optimization_status"), "insufficient_evidence"),
            "top_weakness": _text(data.get("top_weakness") or self_optimization.get("top_weakness"), "profit_capture_exit_quality"),
            "top_opportunity": _text(data.get("top_opportunity") or self_optimization.get("top_opportunity"), "profit_capture_and_exit_quality"),
            "top_bottleneck": _text(data.get("top_bottleneck") or self_optimization.get("top_bottleneck"), "profit_capture_giveback"),
            "highest_roi_improvement": _text(data.get("highest_roi_improvement") or self_optimization.get("highest_roi_improvement"), "profit_capture_and_exit_quality"),
            "highest_confidence_improvement": _text(data.get("highest_confidence_improvement") or self_optimization.get("highest_confidence_improvement"), "profit_protection_validation"),
            "recommended_next_focus": _text(data.get("recommended_next_focus") or self_optimization.get("recommended_next_focus"), "continue advisory-only profit improvement focus"),
            "health_monitoring_status": _text(data.get("health_monitoring_status") or health.get("health_monitoring_status"), "insufficient_evidence"),
            "broker_health": _text(health.get("broker_health"), "monitoring"),
            "api_health": _text(health.get("api_health"), "monitoring"),
            "bandwidth_health": _text(health.get("bandwidth_health"), "safe"),
            "efficiency_score": _to_float(health.get("efficiency_score"), 0.0),
            "profit_improvement_status": _text(data.get("profit_improvement_status") or profit_focus.get("profit_improvement_status"), "insufficient_evidence"),
            "focus_areas": list(profit_focus.get("focus_areas") or [])[:8],
            "expected_pf_improvement": _to_float(data.get("expected_pf_improvement") or profit_focus.get("expected_pf_improvement"), 0.0),
            "expected_capture_improvement_pct": _to_float(data.get("expected_capture_improvement_pct") or profit_focus.get("expected_capture_improvement_pct"), 0.0),
            "expected_giveback_reduction_pct": _to_float(data.get("expected_giveback_reduction_pct") or profit_focus.get("expected_giveback_reduction_pct"), 0.0),
            "expected_exit_improvement_pct": _to_float(data.get("expected_exit_improvement_pct") or profit_focus.get("expected_exit_improvement_pct"), 0.0),
            "intelligence_summary": _text(data.get("intelligence_summary"), "insufficient cached context"),
            "dashboard_impact": _text(data.get("dashboard_impact"), "one_collapsed_learning_center_section_unified_diagnostics_only"),
            "api_bandwidth_impact": _text(data.get("api_bandwidth_impact"), "unchanged_zero_dashboard_provider_calls_cache_first_no_endpoint_storm"),
            "provider_api_impact": _text(data.get("provider_api_impact"), "unchanged_zero_dashboard_provider_calls"),
            "librarian_integration_status": _text(data.get("librarian_integration_status"), "routed_compressed_outputs_only"),
            "unified_truth_integration_status": _text(data.get("unified_truth_integration_status"), "summary_truths_only"),
            "executive_assistant_integration_status": _text(data.get("executive_assistant_integration_status"), "prioritized_advisory_focus_only"),
            "astra_brain_integration_status": _text(data.get("astra_brain_integration_status"), "advisory_context_only_no_behavior_change"),
            "shadow_lab_route": _text(data.get("shadow_lab_route"), "Research -> Shadow Lab -> Human Approval"),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "raw_data_direct_to_brain": bool(data.get("raw_data_direct_to_brain", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_endpoint_storm_created": bool(data.get("dashboard_endpoint_storm_created", False)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "human_approval_required": bool(data.get("human_approval_required", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "promotion_logic_changed": bool(data.get("promotion_logic_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "shadow_influence_changed": bool(data.get("shadow_influence_changed", False)),
        }

    def _astra_targeted_maturity_profit_capture_optimization_bundle_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        modules = dict(data.get("modules") or {})
        horizon = dict(modules.get("horizon_intelligence_maturation_suite_v1") or {})
        exit_quality = dict(modules.get("exit_quality_optimization_v1") or {})
        profit_capture = dict(modules.get("profit_capture_giveback_reduction_v1") or {})
        executive = dict(modules.get("executive_summary_engine_v1") or {})
        consolidation = dict(modules.get("learning_center_consolidation_v1") or {})
        duplicate = dict(modules.get("duplicate_intelligence_detection_v1") or {})
        root = dict(modules.get("root_cause_engine_v1") or {})
        throughput = dict(modules.get("intelligence_throughput_meter_v1") or {})
        saturation = dict(modules.get("intelligence_saturation_meter_v1") or {})
        universe = dict(modules.get("dynamic_universe_manager_v1") or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Targeted Maturity & Profit-Capture Optimization Bundle V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "shadow_only_targeted_maturity_profit_capture_optimization"),
            "modules_created": list(data.get("modules_created") or [])[:12],
            "horizon_status": _text(data.get("horizon_status") or horizon.get("horizon_status"), "insufficient_evidence"),
            "positions_reviewed": _to_int(horizon.get("positions_reviewed"), 0),
            "unknown_horizon_positions": _to_int(horizon.get("unknown_horizon_positions"), 0),
            "horizon_drift_count": _to_int(horizon.get("horizon_drift_count"), 0),
            "recommended_horizon_action": _text(horizon.get("recommended_horizon_action"), "continue_collecting_evidence"),
            "allowed_horizon_actions": list(horizon.get("allowed_horizon_actions") or [])[:8],
            "pf_delta_estimate": _to_float(horizon.get("pf_delta_estimate"), 0.0),
            "capture_improvement_estimate": _to_float(horizon.get("capture_improvement_estimate"), 0.0),
            "giveback_reduction_estimate": _to_float(horizon.get("giveback_reduction_estimate"), 0.0),
            "exit_quality_improvement_estimate": _to_float(horizon.get("exit_quality_improvement_estimate"), 0.0),
            "sample_positions": list(horizon.get("sample_positions") or [])[:8],
            "exit_quality_status": _text(data.get("exit_quality_status") or exit_quality.get("exit_quality_status"), "insufficient_evidence"),
            "best_virtual_exit": _text(exit_quality.get("best_virtual_exit"), "monitoring"),
            "natural_exit": _text(exit_quality.get("natural_exit"), "preserved_default"),
            "missed_exit": bool(exit_quality.get("missed_exit", False)),
            "late_exit": bool(exit_quality.get("late_exit", False)),
            "continuation_failure": _text(exit_quality.get("continuation_failure"), "monitoring"),
            "profit_decay": _text(exit_quality.get("profit_decay"), "monitoring"),
            "exit_confidence": _to_float(exit_quality.get("exit_confidence"), 0.0),
            "exit_review_candidate": bool(exit_quality.get("exit_review_candidate", False)),
            "review_only_exit_candidates": _to_int(exit_quality.get("review_only_exit_candidates"), 0),
            "profit_capture_status": _text(data.get("profit_capture_status") or profit_capture.get("profit_capture_status"), "insufficient_evidence"),
            "mfe": profit_capture.get("mfe"),
            "mae": profit_capture.get("mae"),
            "current_profit": profit_capture.get("current_profit"),
            "realized_profit": profit_capture.get("realized_profit"),
            "giveback": _to_float(profit_capture.get("giveback"), 0.0),
            "capture_ratio": _to_float(profit_capture.get("capture_ratio"), 0.0),
            "peak_decay": _text(profit_capture.get("peak_decay"), "monitoring"),
            "profit_lock_candidate": bool(profit_capture.get("profit_lock_candidate", False)),
            "protect_profit_confidence": _to_float(profit_capture.get("protect_profit_confidence"), 0.0),
            "biggest_giveback_symbol": _text(data.get("biggest_giveback_symbol") or profit_capture.get("biggest_giveback_symbol"), "unknown"),
            "biggest_capture_leak": _text(data.get("biggest_capture_leak") or profit_capture.get("biggest_capture_leak"), "exit_intelligence_profit_capture"),
            "best_profit_protection_candidate": _text(data.get("best_profit_protection_candidate") or profit_capture.get("best_profit_protection_candidate"), "monitoring"),
            "estimated_pf_gain": _to_float(profit_capture.get("estimated_pf_gain"), 0.0),
            "executive_summary_status": _text(data.get("executive_summary_status") or executive.get("executive_summary_status"), "insufficient_evidence"),
            "executive_summary": _text(data.get("executive_summary") or executive.get("summary"), "insufficient cached context"),
            "pf": executive.get("pf"),
            "win_rate": executive.get("win_rate"),
            "buy_purity": executive.get("buy_purity"),
            "top_weakness": _text(executive.get("top_weakness"), "profit_capture_exit_quality"),
            "top_opportunity": _text(executive.get("top_opportunity"), "reduce giveback and improve exit review quality"),
            "recommended_next_focus": _text(data.get("recommended_next_focus") or executive.get("recommended_next_focus"), "mature horizon and profit capture diagnostics"),
            "learning_center_consolidation_status": _text(data.get("learning_center_consolidation_status") or consolidation.get("learning_center_consolidation_status"), "insufficient_evidence"),
            "departments": list(consolidation.get("departments") or [])[:12],
            "duplicate_detection_status": _text(data.get("duplicate_detection_status") or duplicate.get("duplicate_detection_status"), "insufficient_evidence"),
            "duplicate_findings_detected": _to_int(data.get("duplicate_findings_detected") or duplicate.get("duplicate_findings_detected"), 0),
            "merged_findings": _to_int(data.get("merged_findings") or duplicate.get("merged_findings"), 0),
            "master_issue": _text(duplicate.get("master_issue"), "monitoring"),
            "systems_contributing": list(duplicate.get("systems_contributing") or [])[:10],
            "root_cause_status": _text(data.get("root_cause_status") or root.get("root_cause_status"), "insufficient_evidence"),
            "top_root_cause": _text(data.get("top_root_cause") or root.get("top_root_cause"), "exit_intelligence_profit_capture"),
            "affected_metrics": list(root.get("affected_metrics") or [])[:10],
            "highest_roi_fix": _text(root.get("highest_roi_fix"), "review-only profit protection and dynamic horizon diagnostics"),
            "throughput_meter_status": _text(data.get("throughput_meter_status") or throughput.get("throughput_meter_status"), "insufficient_evidence"),
            "symbols_observed": _to_int(throughput.get("symbols_observed"), 0),
            "symbols_deeply_analyzed": _to_int(throughput.get("symbols_deeply_analyzed"), 0),
            "satellites_active": _to_int(throughput.get("satellites_active"), 0),
            "satellite_intelligence_packets": _to_int(throughput.get("satellite_intelligence_packets"), 0),
            "historical_memories_used": _to_int(throughput.get("historical_memories_used"), 0),
            "historical_memories_created": _to_int(throughput.get("historical_memories_created"), 0),
            "catalysts_analyzed": _to_int(throughput.get("catalysts_analyzed"), 0),
            "shadow_experiments": _to_int(throughput.get("shadow_experiments"), 0),
            "virtual_simulations": _to_int(throughput.get("virtual_simulations"), 0),
            "compressed_lessons": _to_int(throughput.get("compressed_lessons"), 0),
            "master_truths_created": _to_int(throughput.get("master_truths_created"), 0),
            "executive_insights_delivered": _to_int(throughput.get("executive_insights_delivered"), 0),
            "brain_packets_delivered": _to_int(throughput.get("brain_packets_delivered"), 0),
            "intelligence_efficiency_ratio": _to_float(data.get("intelligence_efficiency_ratio") or throughput.get("intelligence_efficiency_ratio"), 0.0),
            "saturation_meter_status": _text(data.get("saturation_meter_status") or saturation.get("saturation_meter_status"), "insufficient_evidence"),
            "saturation_percentage": _to_float(data.get("saturation_percentage") or saturation.get("saturation_percentage"), 0.0),
            "safe_expansion_capacity": _to_float(data.get("safe_expansion_capacity") or saturation.get("safe_expansion_capacity"), 0.0),
            "expand_data_yes_no": _text(saturation.get("expand_data_yes_no"), "monitor"),
            "improve_quality_yes_no": _text(saturation.get("improve_quality_yes_no"), "monitor"),
            "recommended_next_capacity": _text(saturation.get("recommended_next_capacity"), "monitor"),
            "dynamic_universe_status": _text(data.get("dynamic_universe_status") or universe.get("dynamic_universe_status"), "insufficient_evidence"),
            "categories_tracked": list(universe.get("categories_tracked") or [])[:12],
            "current_universe": _to_int(data.get("current_universe") or universe.get("current_universe"), 0),
            "next_safe_universe_target": _to_int(data.get("next_safe_universe_target") or universe.get("next_safe_target"), 0),
            "mature_universe_target": _text(data.get("mature_universe_target") or universe.get("mature_target"), "750-1000 curated assets"),
            "dynamic_universe_recommendation": _text(data.get("dynamic_universe_recommendation") or universe.get("recommendation"), "recommendation only"),
            "expected_pf_improvement": _to_float(data.get("expected_pf_improvement") or executive.get("expected_pf_improvement"), 0.0),
            "integration_flow": _text(data.get("integration_flow"), "Satellites/Historical/Shadow -> Librarian -> Unified Truth -> Executive Assistant -> Astra Brain"),
            "raw_data_direct_to_brain": bool(data.get("raw_data_direct_to_brain", False)),
            "dashboard_impact": _text(data.get("dashboard_impact"), "one_collapsed_learning_center_section_unified_diagnostics_only"),
            "api_bandwidth_impact": _text(data.get("api_bandwidth_impact"), "unchanged_zero_dashboard_provider_calls_cache_first_no_endpoint_storm"),
            "provider_api_impact": _text(data.get("provider_api_impact"), "unchanged_zero_dashboard_provider_calls"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_endpoint_storm_created": bool(data.get("dashboard_endpoint_storm_created", False)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "shadow_influence_changed": bool(data.get("shadow_influence_changed", False)),
        }

    def _astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        modules = dict(data.get("modules") or {})
        repair = dict(modules.get("trade_lifecycle_audit_auto_repair_v1") or {})
        readiness = dict(modules.get("horizon_shadow_to_paper_promotion_readiness_v1") or {})
        capacity = dict(modules.get("horizon_capacity_manager_v1") or {})
        recycling = dict(modules.get("dynamic_capacity_recycling_v1") or {})
        exposure = dict(modules.get("horizon_exposure_balancer_v1") or {})
        optimizer = dict(modules.get("learning_exposure_optimizer_v1") or {})
        dashboard = dict(modules.get("horizon_lifecycle_dashboard_summary") or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "suite": _text(data.get("suite"), "ASTRA Horizon Lifecycle, Capacity Recycling & Promotion Readiness Bundle V1"),
            "version": _text(data.get("version"), "1.0.0"),
            "status": _text(data.get("status"), "insufficient_evidence"),
            "mode": _text(data.get("mode"), "paper_safe_shadow_horizon_lifecycle_capacity_promotion_readiness"),
            "modules_created": list(data.get("modules_created") or [])[:10],
            "repair_status": _text(data.get("repair_status") or repair.get("repair_status"), "insufficient_evidence"),
            "active_position_source": _text(data.get("active_position_source") or repair.get("active_position_source"), "unknown"),
            "broker_confirmed_count": _to_int(data.get("broker_confirmed_count") or repair.get("broker_confirmed_count"), 0),
            "internal_active_count": _to_int(data.get("internal_active_count") or repair.get("internal_active_count"), 0),
            "stale_internal_rows_hidden": _to_int(data.get("stale_internal_rows_hidden") or repair.get("stale_internal_rows_hidden"), 0),
            "lifecycle_rows_audited": _to_int(data.get("lifecycle_rows_audited") or repair.get("lifecycle_rows_audited"), 0),
            "unmatched_broker_symbols": list(data.get("unmatched_broker_symbols") or repair.get("unmatched_broker_symbols") or [])[:20],
            "unmatched_internal_symbols": list(data.get("unmatched_internal_symbols") or repair.get("unmatched_internal_symbols") or [])[:20],
            "broker_confirmed_positions_source_of_truth": bool(repair.get("broker_confirmed_positions_source_of_truth", False)),
            "stale_internal_rows_distort_active_status": bool(repair.get("stale_internal_rows_distort_active_status", False)),
            "full_history_preserved": bool(repair.get("full_history_preserved", True)),
            "unknown_horizon_positions": _to_int(data.get("unknown_horizon_positions") or capacity.get("unknown_horizon_slots"), 0),
            "horizon_distribution": dict(data.get("horizon_distribution") or capacity.get("horizon_distribution_pct") or {}),
            "current_horizon_distribution": dict(data.get("current_horizon_distribution") or capacity.get("horizon_distribution_pct") or {}),
            "assigned_horizons_today": dict(data.get("assigned_horizons_today") or {}),
            "selected_horizons_today": dict(data.get("selected_horizons_today") or {}),
            "assigned_horizon_rows": list(data.get("assigned_horizon_rows") or [])[:12],
            "assigned_horizon_count": _to_int(data.get("assigned_horizon_count"), 0),
            "assigned_horizon_source": _text(data.get("assigned_horizon_source"), "paper_execution_trace.per_candidate_decision_trace"),
            "horizon_assignment_version": _text(data.get("horizon_assignment_version"), "paper_autopilot_horizon_inference_v1"),
            "capacity_mode": _text(data.get("capacity_mode"), "advisory_rebalance_only"),
            "capacity_rebalance_status": _text(data.get("capacity_rebalance_status"), _text(exposure.get("horizon_exposure_balance"), "insufficient_evidence")),
            "capacity_rebalance_recommendation": _text(data.get("capacity_rebalance_recommendation"), _text(capacity.get("recommended_capacity_shift"), "maintain_current_learning_mix")),
            "rebalance_action_taken": bool(data.get("rebalance_action_taken", False)),
            "rebalance_action_reason": _text(data.get("rebalance_action_reason"), "diagnostic_only_no_behavior_change"),
            "preferred_next_horizon": _text(data.get("preferred_next_horizon"), _text(capacity.get("underexposed_horizon"), "scalp")),
            "overconcentration_warning": bool(data.get("overconcentration_warning", False)),
            "practice_bucket_status": _text(data.get("practice_bucket_status"), "advisory_only_disabled_pending_human_review"),
            "bucket_enabled": bool(data.get("bucket_enabled", False)),
            "bucket_size": _to_int(data.get("bucket_size"), 3),
            "bucket_used_today": _to_int(data.get("bucket_used_today"), 0),
            "scalp_practice_count": _to_int(data.get("scalp_practice_count"), 0),
            "day_trade_practice_count": _to_int(data.get("day_trade_practice_count"), 0),
            "swing_practice_count": _to_int(data.get("swing_practice_count"), 0),
            "practice_candidate_count": _to_int(data.get("practice_candidate_count"), 0),
            "blocked_candidate_count": _to_int(data.get("blocked_candidate_count"), 0),
            "practice_bucket_block_reasons": dict(data.get("practice_bucket_block_reasons") or {}),
            "exit_readiness_status": _text(data.get("exit_readiness_status") or readiness.get("highest_readiness"), "collect_more_evidence"),
            "exit_readiness_by_horizon": dict(data.get("exit_readiness_by_horizon") or readiness.get("readiness_by_horizon") or {}),
            "scalp_exit_readiness": _text(data.get("scalp_exit_readiness"), _text((readiness.get("readiness_by_horizon") or {}).get("scalp"), "collect_more_evidence")),
            "day_trade_exit_readiness": _text(data.get("day_trade_exit_readiness"), _text((readiness.get("readiness_by_horizon") or {}).get("day_trade"), "collect_more_evidence")),
            "swing_exit_readiness": _text(data.get("swing_exit_readiness"), _text((readiness.get("readiness_by_horizon") or {}).get("swing_trade"), "collect_more_evidence")),
            "highest_roi_exit_focus": _text(data.get("highest_roi_exit_focus") or optimizer.get("highest_roi_learning_focus"), "horizon_exposure"),
            "promotion_readiness": _text(data.get("promotion_readiness") or readiness.get("highest_readiness"), "collect_more_evidence"),
            "reason_not_ready": _text(data.get("reason_not_ready"), "more_horizon_evidence_required"),
            "readiness_by_horizon": dict(data.get("readiness_by_horizon") or readiness.get("readiness_by_horizon") or {}),
            "horizon_readiness_rows": list(readiness.get("horizon_rows") or [])[:6],
            "highest_readiness": _text(readiness.get("highest_readiness"), "collect_more_evidence"),
            "horizon_capacity_status": _text(data.get("horizon_capacity_status") or capacity.get("capacity_status"), "insufficient_evidence"),
            "total_capacity": _to_int(capacity.get("total_capacity"), 20),
            "total_used": _to_int(capacity.get("total_used"), 0),
            "scalp_slots_used": _to_int(capacity.get("scalp_slots_used"), 0),
            "day_trade_slots_used": _to_int(capacity.get("day_trade_slots_used"), 0),
            "swing_slots_used": _to_int(capacity.get("swing_slots_used"), 0),
            "unknown_horizon_slots": _to_int(capacity.get("unknown_horizon_slots"), 0),
            "conservatively_classified_unknown_broker_rows": _to_int(capacity.get("conservatively_classified_unknown_broker_rows"), 0),
            "conservative_classification_basis": _text(capacity.get("conservative_classification_basis"), "none"),
            "overexposed_horizon": _text(data.get("overexposed_horizon") or capacity.get("overexposed_horizon"), "none"),
            "underexposed_horizon": _text(data.get("underexposed_horizon") or capacity.get("underexposed_horizon"), "none"),
            "recommended_capacity_shift": _text(capacity.get("recommended_capacity_shift"), "maintain_current_learning_mix"),
            "capacity_health": _text(capacity.get("capacity_health"), "monitoring"),
            "dynamic_recycling_status": _text(data.get("dynamic_recycling_status") or recycling.get("dynamic_recycling_status"), "insufficient_evidence"),
            "recently_closed_positions": _to_int(recycling.get("recently_closed_positions"), 0),
            "freed_slots_today": _to_int(recycling.get("freed_slots_today"), 0),
            "recycled_slots_available": _to_int(recycling.get("recycled_slots_available"), 0),
            "replacement_scan_recommended": bool(recycling.get("replacement_scan_recommended", False)),
            "replacement_eligibility_count": _to_int(recycling.get("replacement_eligibility_count"), 0),
            "cooldown_status": _text(recycling.get("cooldown_status"), "respect_existing_cooldowns"),
            "market_session_status": _text(recycling.get("market_session_status"), "unknown_or_closed"),
            "recycle_block_reason": _text(recycling.get("recycle_block_reason"), "none"),
            "horizon_exposure_balance": _text(data.get("horizon_exposure_balance") or exposure.get("horizon_exposure_balance"), "insufficient_evidence"),
            "scalp_exposure_pct": _to_float(exposure.get("scalp_exposure_pct"), 0.0),
            "day_trade_exposure_pct": _to_float(exposure.get("day_trade_exposure_pct"), 0.0),
            "swing_exposure_pct": _to_float(exposure.get("swing_exposure_pct"), 0.0),
            "scalp_learning_events": _to_int(exposure.get("scalp_learning_events"), 0),
            "day_learning_events": _to_int(exposure.get("day_learning_events"), 0),
            "swing_learning_events": _to_int(exposure.get("swing_learning_events"), 0),
            "horizon_exposure_gap": _to_float(exposure.get("horizon_exposure_gap"), 0.0),
            "horizon_learning_balance_score": _to_float(exposure.get("horizon_learning_balance_score"), 0.0),
            "recommended_learning_focus": _text(exposure.get("recommended_learning_focus"), "maintain_balanced_horizon_learning"),
            "top_learning_exposure_gap": _text(data.get("top_learning_exposure_gap") or optimizer.get("top_learning_gap"), "horizon_exposure"),
            "highest_roi_learning_focus": _text(optimizer.get("highest_roi_learning_focus"), "horizon_exit_profit_capture"),
            "recommended_shadow_focus": _text(optimizer.get("recommended_shadow_focus"), "increase_shadow_validation_for_horizon_exposure"),
            "recommended_paper_learning_focus": _text(optimizer.get("recommended_paper_learning_focus"), "use_existing_ranking_and_entry_gates_to_collect_underexposed_horizon_evidence"),
            "active_broker_positions": _to_int(data.get("active_broker_positions") or dashboard.get("active_broker_positions"), 0),
            "rows_audited": _to_int(data.get("rows_audited") or dashboard.get("rows_audited"), 0),
            "shadow_horizon_readiness": dict(dashboard.get("shadow_horizon_readiness") or {}),
            "recycling_recommendation": _text(data.get("recycling_recommendation") or dashboard.get("recycling_recommendation"), "monitor_capacity_until_slot_reopens"),
            "top_horizon_problem": _text(data.get("top_horizon_problem") or dashboard.get("top_horizon_problem"), "monitoring"),
            "next_recommended_action": _text(data.get("next_recommended_action") or dashboard.get("next_recommended_action"), "continue advisory horizon learning"),
            "integration_flow": _text(data.get("integration_flow"), "Trade lifecycle / Shadow / Horizon systems -> Librarian -> Unified Truth -> Executive Assistant -> Learning Center"),
            "raw_data_direct_to_brain": bool(data.get("raw_data_direct_to_brain", False)),
            "dashboard_impact": _text(data.get("dashboard_impact"), "one_collapsed_learning_center_section_unified_diagnostics_only"),
            "api_bandwidth_impact": _text(data.get("api_bandwidth_impact"), "unchanged_zero_dashboard_provider_calls_cache_first_no_endpoint_storm"),
            "provider_api_impact": _text(data.get("provider_api_impact"), "unchanged_zero_dashboard_provider_calls"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_endpoint_storm_created": bool(data.get("dashboard_endpoint_storm_created", False)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
            "shadow_analysis_mode": bool(data.get("shadow_analysis_mode", True)),
            "advisory_only": bool(data.get("advisory_only", True)),
            "paper_safe": bool(data.get("paper_safe", True)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "paper_execution_changed": bool(data.get("paper_execution_changed", False)),
            "paper_sell_behavior_enabled": bool(data.get("paper_sell_behavior_enabled", False)),
            "learned_exits_enabled": bool(data.get("learned_exits_enabled", False)),
            "shadow_influence_changed": bool(data.get("shadow_influence_changed", False)),
        }

    def _trade_thesis_validation_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_trade_thesis_validation"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "thesis_rows": list(data.get("thesis_rows") or [])[:8],
            "thesis_accuracy_score": _to_float(data.get("thesis_accuracy_score"), 0.0),
            "thesis_failure_rate": _to_float(data.get("thesis_failure_rate"), 0.0),
            "strongest_thesis_type": _text(data.get("strongest_thesis_type"), "insufficient_data"),
            "weakest_thesis_type": _text(data.get("weakest_thesis_type"), "insufficient_data"),
            "thesis_confidence": _to_float(data.get("thesis_confidence"), 0.0),
            "top_failed_thesis_reason": _text(data.get("top_failed_thesis_reason"), "insufficient_data"),
            "top_successful_thesis_reason": _text(data.get("top_successful_thesis_reason"), "insufficient_data"),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue trade thesis validation shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _market_transition_detection_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_market_transition_detection"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "regime_stability_score": _to_float(data.get("regime_stability_score"), 0.0),
            "transition_risk_score": _to_float(data.get("transition_risk_score"), 0.0),
            "transition_confidence": _to_float(data.get("transition_confidence"), 0.0),
            "strongest_transition_warning": _text(data.get("strongest_transition_warning"), "insufficient_data"),
            "current_market_phase": _text(data.get("current_market_phase"), "insufficient_data"),
            "likely_next_market_phase": _text(data.get("likely_next_market_phase"), "insufficient_data"),
            "transition_warning_rows": list(data.get("transition_warning_rows") or [])[:8],
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue market transition detection shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _trade_family_intelligence_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_trade_family_intelligence"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "family_rows": list(data.get("family_rows") or [])[:8],
            "strongest_trade_family": _text(data.get("strongest_trade_family"), "insufficient_data"),
            "weakest_trade_family": _text(data.get("weakest_trade_family"), "insufficient_data"),
            "best_family_horizon": _text(data.get("best_family_horizon"), "insufficient_data"),
            "best_family_exit_style": _text(data.get("best_family_exit_style"), "insufficient_data"),
            "family_transfer_confidence": _to_float(data.get("family_transfer_confidence"), 0.0),
            "family_learning_score": _to_float(data.get("family_learning_score"), 0.0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue trade-family intelligence shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _market_condition_attribution_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_market_condition_attribution"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "condition_rows": list(data.get("condition_rows") or [])[:9],
            "best_condition": _text(data.get("best_condition"), "insufficient_data"),
            "weakest_condition": _text(data.get("weakest_condition"), "insufficient_data"),
            "best_horizon_by_condition": dict(data.get("best_horizon_by_condition") or {}),
            "weakest_horizon_by_condition": dict(data.get("weakest_horizon_by_condition") or {}),
            "profit_capture_by_condition": dict(data.get("profit_capture_by_condition") or {}),
            "exit_quality_by_condition": dict(data.get("exit_quality_by_condition") or {}),
            "condition_confidence_score": _to_float(data.get("condition_confidence_score"), 0.0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue market-condition attribution shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _market_breadth_index_intelligence_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "context_only_market_breadth_index_intelligence"),
            "index_symbols_tracked": list(data.get("index_symbols_tracked") or [])[:12],
            "index_signal_rows": list(data.get("index_signal_rows") or [])[:8],
            "overall_market_health": _to_float(data.get("overall_market_health"), 0.0),
            "risk_on_score": _to_float(data.get("risk_on_score"), 0.0),
            "risk_off_score": _to_float(data.get("risk_off_score"), 0.0),
            "index_trend_strength": _to_float(data.get("index_trend_strength"), 0.0),
            "index_momentum_score": _to_float(data.get("index_momentum_score"), 0.0),
            "breadth_proxy_score": _to_float(data.get("breadth_proxy_score"), 0.0),
            "volatility_pressure_score": _to_float(data.get("volatility_pressure_score"), 0.0),
            "market_transition_risk": _to_float(data.get("market_transition_risk"), 0.0),
            "market_support_for_equity_trades": _to_float(data.get("market_support_for_equity_trades"), 0.0),
            "market_support_for_momentum_trades": _to_float(data.get("market_support_for_momentum_trades"), 0.0),
            "market_support_for_small_caps": _to_float(data.get("market_support_for_small_caps"), 0.0),
            "market_support_for_growth_trades": _to_float(data.get("market_support_for_growth_trades"), 0.0),
            "strongest_index_signal": _text(data.get("strongest_index_signal"), "insufficient_data"),
            "weakest_index_signal": _text(data.get("weakest_index_signal"), "insufficient_data"),
            "current_index_regime": _text(data.get("current_index_regime"), "insufficient_data"),
            "index_confidence_score": _to_float(data.get("index_confidence_score"), 0.0),
            "market_breadth_summary": _text(data.get("market_breadth_summary"), "warming up"),
            **self._context_only_market_safety_summary(data),
        }

    def _etf_sector_rotation_intelligence_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "context_only_etf_sector_rotation_intelligence"),
            "etf_symbols_tracked": list(data.get("etf_symbols_tracked") or [])[:24],
            "sector_rows": list(data.get("sector_rows") or [])[:10],
            "strongest_sector": _text(data.get("strongest_sector"), "insufficient_data"),
            "weakest_sector": _text(data.get("weakest_sector"), "insufficient_data"),
            "sector_inflow_score": _to_float(data.get("sector_inflow_score"), 0.0),
            "sector_outflow_score": _to_float(data.get("sector_outflow_score"), 0.0),
            "rotation_speed": _to_float(data.get("rotation_speed"), 0.0),
            "sector_momentum_persistence": _to_float(data.get("sector_momentum_persistence"), 0.0),
            "sector_decay_risk": _to_float(data.get("sector_decay_risk"), 0.0),
            "sector_support_for_current_positions": _to_float(data.get("sector_support_for_current_positions"), 0.0),
            "etf_leadership_score": _to_float(data.get("etf_leadership_score"), 0.0),
            "sector_rotation_confidence": _to_float(data.get("sector_rotation_confidence"), 0.0),
            "strongest_sector_rotation": _text(data.get("strongest_sector_rotation"), "insufficient_data"),
            "weakest_sector_rotation": _text(data.get("weakest_sector_rotation"), "insufficient_data"),
            "sector_leadership_map": dict(data.get("sector_leadership_map") or {}),
            "sector_rotation_summary": _text(data.get("sector_rotation_summary"), "warming up"),
            "sector_context_for_stock_selection": _text(data.get("sector_context_for_stock_selection"), "observation_only"),
            "sector_context_for_profit_capture": _text(data.get("sector_context_for_profit_capture"), "observation_only"),
            **self._context_only_market_safety_summary(data),
        }

    def _crypto_shadow_learning_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "separate_crypto_shadow_learning_no_trading"),
            "crypto_core_symbols_tracked": list(data.get("crypto_core_symbols_tracked") or [])[:16],
            "crypto_rotating_symbols_today": list(data.get("crypto_rotating_symbols_today") or [])[:20],
            "crypto_scan_symbols_today": _to_int(data.get("crypto_scan_symbols_today"), 0),
            "crypto_families": list(data.get("crypto_families") or [])[:12],
            "crypto_horizons": list(data.get("crypto_horizons") or [])[:8],
            "crypto_shadow_opportunities": _to_int(data.get("crypto_shadow_opportunities"), 0),
            "crypto_virtual_paths": _to_int(data.get("crypto_virtual_paths"), 0),
            "crypto_completed_lifecycles": _to_int(data.get("crypto_completed_lifecycles"), 0),
            "crypto_replay_score": _to_float(data.get("crypto_replay_score"), 0.0),
            "crypto_profit_factor": data.get("crypto_profit_factor"),
            "crypto_profit_factor_status": _text(data.get("crypto_profit_factor_status"), "INSUFFICIENT_EVIDENCE"),
            "crypto_win_rate": _to_float(data.get("crypto_win_rate"), 0.0),
            "crypto_avg_return": _to_float(data.get("crypto_avg_return"), 0.0),
            "crypto_avg_mfe": _to_float(data.get("crypto_avg_mfe"), 0.0),
            "crypto_avg_mae": _to_float(data.get("crypto_avg_mae"), 0.0),
            "crypto_profit_capture": _to_float(data.get("crypto_profit_capture"), 0.0),
            "crypto_giveback": _to_float(data.get("crypto_giveback"), 0.0),
            "crypto_best_horizon": _text(data.get("crypto_best_horizon"), "insufficient_data"),
            "crypto_weakest_horizon": _text(data.get("crypto_weakest_horizon"), "insufficient_data"),
            "crypto_best_family": _text(data.get("crypto_best_family"), "insufficient_data"),
            "crypto_weakest_family": _text(data.get("crypto_weakest_family"), "insufficient_data"),
            "crypto_best_regime": _text(data.get("crypto_best_regime"), "insufficient_data"),
            "crypto_transition_score": _to_float(data.get("crypto_transition_score"), 0.0),
            "crypto_volatility_learning_score": _to_float(data.get("crypto_volatility_learning_score"), 0.0),
            "crypto_momentum_learning_score": _to_float(data.get("crypto_momentum_learning_score"), 0.0),
            "crypto_risk_appetite_score": _to_float(data.get("crypto_risk_appetite_score"), 0.0),
            **self._context_only_market_safety_summary(data),
        }

    def _cross_market_attribution_transfer_learning_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_cross_market_attribution_transfer_learning"),
            "relationship_rows": list(data.get("relationship_rows") or [])[:8],
            "cross_market_transfer_confidence": _to_float(data.get("cross_market_transfer_confidence"), 0.0),
            "crypto_to_stock_signal_score": _to_float(data.get("crypto_to_stock_signal_score"), 0.0),
            "index_to_stock_signal_score": _to_float(data.get("index_to_stock_signal_score"), 0.0),
            "etf_to_stock_signal_score": _to_float(data.get("etf_to_stock_signal_score"), 0.0),
            "risk_appetite_transfer_score": _to_float(data.get("risk_appetite_transfer_score"), 0.0),
            "market_psychology_score": _to_float(data.get("market_psychology_score"), 0.0),
            "speculation_score": _to_float(data.get("speculation_score"), 0.0),
            "cross_market_alpha_available": bool(data.get("cross_market_alpha_available", False)),
            "cross_market_alpha_confidence": _to_float(data.get("cross_market_alpha_confidence"), 0.0),
            "strongest_cross_market_relationship": _text(data.get("strongest_cross_market_relationship"), "insufficient_data"),
            "weakest_cross_market_relationship": _text(data.get("weakest_cross_market_relationship"), "insufficient_data"),
            "recommended_cross_market_use": _text(data.get("recommended_cross_market_use"), "attribution_only"),
            **self._context_only_market_safety_summary(data),
        }

    def _context_only_market_safety_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "bandwidth_used_gb": _to_float(data.get("bandwidth_used_gb"), 0.0),
            "bandwidth_budget_status": _text(data.get("bandwidth_budget_status"), "cache_only_safe"),
            "crypto_scan_symbols_today": _to_int(data.get("crypto_scan_symbols_today"), 0),
            "crypto_rotating_symbols_today": list(data.get("crypto_rotating_symbols_today") or [])[:20],
            "etf_symbols_tracked": list(data.get("etf_symbols_tracked") or [])[:24],
            "index_symbols_tracked": list(data.get("index_symbols_tracked") or [])[:12],
            "cache_hit_rate": _to_float(data.get("cache_hit_rate"), 100.0),
            "provider_budget_safe": bool(data.get("provider_budget_safe", True)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "crypto_paper_trading_enabled": bool(data.get("crypto_paper_trading_enabled", False)),
            "crypto_live_trading_enabled": bool(data.get("crypto_live_trading_enabled", False)),
            "etf_trading_enabled": bool(data.get("etf_trading_enabled", False)),
            "index_trading_enabled": bool(data.get("index_trading_enabled", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Keep context learning shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _profit_lock_profit_capture_maturation_v2_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        scenarios = list(data.get("virtual_profit_lock_scenarios") or [])[:5]
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_profit_lock_profit_capture_maturation"),
            "tracked_trades": _to_int(data.get("tracked_trades"), 0),
            "average_capture_ratio": _to_float(data.get("average_capture_ratio"), 0.0),
            "average_giveback_pct": _to_float(data.get("average_giveback_pct"), 0.0),
            "average_MFE": _to_float(data.get("average_MFE"), 0.0),
            "average_MAE": _to_float(data.get("average_MAE"), 0.0),
            "virtual_profit_lock_scenarios": scenarios,
            "profit_lock_readiness_score": _to_float(data.get("profit_lock_readiness_score"), 0.0),
            "profit_capture_maturity_score": _to_float(data.get("profit_capture_maturity_score"), 0.0),
            "giveback_reduction_score": _to_float(data.get("giveback_reduction_score"), 0.0),
            "continuation_failure_learning_score": _to_float(data.get("continuation_failure_learning_score"), 0.0),
            "hold_duration_learning_score": _to_float(data.get("hold_duration_learning_score"), 0.0),
            "profit_capture_improvement_potential": _to_float(data.get("profit_capture_improvement_potential"), 0.0),
            "best_virtual_profit_lock_model": _text(data.get("best_virtual_profit_lock_model"), "insufficient_data"),
            "best_virtual_profit_capture_model": _text(data.get("best_virtual_profit_capture_model"), "insufficient_data"),
            "cache_freshness": _text(data.get("cache_freshness"), "fresh"),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue virtual profit-lock maturation shadow-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _shadow_correction_validation_attribution_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        categories = list(data.get("validation_categories") or [])[:8]
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_correction_validation_attribution"),
            "validation_categories": categories,
            "strongest_validated_improvement": _text(data.get("strongest_validated_improvement"), "insufficient_data"),
            "weakest_validated_improvement": _text(data.get("weakest_validated_improvement"), "insufficient_data"),
            "total_validated_recommendations": _to_int(data.get("total_validated_recommendations"), 0),
            "total_failed_recommendations": _to_int(data.get("total_failed_recommendations"), 0),
            "average_improvement_score": _to_float(data.get("average_improvement_score"), 0.0),
            "shadow_influence_enabled": bool(data.get("shadow_influence_enabled", False)),
            "shadow_influence_cap_pct": _to_float(data.get("shadow_influence_cap_pct"), 3.0),
            "candidate_ranking_influence_pct": _to_float(data.get("candidate_ranking_influence_pct"), 0.0),
            "buy_purity_influence_pct": _to_float(data.get("buy_purity_influence_pct"), 0.0),
            "opportunity_cost_influence_pct": _to_float(data.get("opportunity_cost_influence_pct"), 0.0),
            "validated_improvement_score": _to_float(data.get("validated_improvement_score"), 0.0),
            "shadow_recommendations_reviewed": _to_int(data.get("shadow_recommendations_reviewed"), 0),
            "validated_recommendations": _to_int(data.get("validated_recommendations"), 0),
            "rejected_recommendations": _to_int(data.get("rejected_recommendations"), 0),
            "confidence_score": _to_float(data.get("confidence_score"), 0.0),
            "readiness_score": _to_float(data.get("readiness_score"), 0.0),
            "minimum_validation_evidence": _to_int(data.get("minimum_validation_evidence"), 25),
            "phase1_allowed_categories": list(data.get("phase1_allowed_categories") or [])[:3],
            "phase1_blocked_actions": list(data.get("phase1_blocked_actions") or [])[:10],
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "autonomous_entry_exit_control_enabled": bool(data.get("autonomous_entry_exit_control_enabled", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue shadow correction validation before broader influence."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _controlled_paper_profit_protection_pilot_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_profit_protection_pilot_shadow_validated"),
            "profit_protection_active": bool(data.get("profit_protection_active", False)),
            "activation_blockers": list(data.get("activation_blockers") or [])[:8],
            "minimum_closed_trade_evidence": _to_int(data.get("minimum_closed_trade_evidence"), 50),
            "closed_trade_evidence": _to_int(data.get("closed_trade_evidence"), 0),
            "profit_capture_score": _to_float(data.get("profit_capture_score"), 0.0),
            "giveback_rate": _to_float(data.get("giveback_rate"), 0.0),
            "shadow_validation_confidence": _to_float(data.get("shadow_validation_confidence"), 0.0),
            "policy_readiness": _to_float(data.get("policy_readiness"), 0.0),
            "profit_protection_influence_cap_pct": _to_float(data.get("profit_protection_influence_cap_pct"), 3.0),
            "profit_lock_guidance_influence_pct": _to_float(data.get("profit_lock_guidance_influence_pct"), 0.0),
            "exit_review_influence_pct": _to_float(data.get("exit_review_influence_pct"), 0.0),
            "hold_review_influence_pct": _to_float(data.get("hold_review_influence_pct"), 0.0),
            "continuation_review_influence_pct": _to_float(data.get("continuation_review_influence_pct"), 0.0),
            "profit_lock_readiness": _to_float(data.get("profit_lock_readiness"), 0.0),
            "giveback_risk_score": _to_float(data.get("giveback_risk_score"), 0.0),
            "catalyst_decay_risk": _to_float(data.get("catalyst_decay_risk"), 0.0),
            "continuation_failure_probability": _to_float(data.get("continuation_failure_probability"), 0.0),
            "peak_decay_risk": _to_float(data.get("peak_decay_risk"), 0.0),
            "hold_duration_efficiency": _to_float(data.get("hold_duration_efficiency"), 0.0),
            "estimated_giveback_reduction": _to_float(data.get("estimated_giveback_reduction"), 0.0),
            "estimated_profit_capture_improvement": _to_float(data.get("estimated_profit_capture_improvement"), 0.0),
            "estimated_expectancy_improvement": _to_float(data.get("estimated_expectancy_improvement"), 0.0),
            "recommendation_count": _to_int(data.get("recommendation_count"), 0),
            "validated_profit_lock_events": _to_int(data.get("validated_profit_lock_events"), 0),
            "validated_hold_improvements": _to_int(data.get("validated_hold_improvements"), 0),
            "validated_continuation_failures": _to_int(data.get("validated_continuation_failures"), 0),
            "strongest_profit_protection_pattern": _text(data.get("strongest_profit_protection_pattern"), "insufficient_data"),
            "weakest_profit_protection_pattern": _text(data.get("weakest_profit_protection_pattern"), "insufficient_data"),
            "most_improved_symbol": _text(data.get("most_improved_symbol"), "insufficient_data"),
            "most_improved_archetype": _text(data.get("most_improved_archetype"), "insufficient_data"),
            "confidence_score": _to_float(data.get("confidence_score"), 0.0),
            "readiness_score": _to_float(data.get("readiness_score"), 0.0),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Keep profit-protection pilot advisory and paper-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _shadow_vs_paper_performance_attribution_v1_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "shadow_only_vs_paper_performance_attribution"),
            "canonical_performance_source": _text(data.get("canonical_performance_source"), "unavailable"),
            "canonical_closed_trade_count": _to_int(data.get("canonical_closed_trade_count"), 0),
            "minimum_pf_sample_size": _to_int(data.get("minimum_pf_sample_size"), 0),
            "minimum_shadow_sample_size": _to_int(data.get("minimum_shadow_sample_size"), 0),
            "minimum_lifecycle_count": _to_int(data.get("minimum_lifecycle_count"), 0),
            "paper_profit_factor_available": bool(data.get("paper_profit_factor_available", False)),
            "shadow_profit_factor_available": bool(data.get("shadow_profit_factor_available", False)),
            "paper_profit_factor_status": _text(data.get("paper_profit_factor_status"), "INSUFFICIENT_EVIDENCE"),
            "shadow_profit_factor_status": _text(data.get("shadow_profit_factor_status"), "INSUFFICIENT_EVIDENCE"),
            "shadow_pf_blocker": _text(data.get("shadow_pf_blocker"), "none"),
            "reconciliation_status": _text(data.get("reconciliation_status") or data.get("overall_reconciliation_status"), "WARNING"),
            "overall_reconciliation_status": _text(data.get("overall_reconciliation_status"), "WARNING"),
            "paper_reconciliation_status": _text(data.get("paper_reconciliation_status"), "WARNING"),
            "shadow_reconciliation_status": _text(data.get("shadow_reconciliation_status"), "INSUFFICIENT_EVIDENCE"),
            "paper_pf_matches_unified": bool(data.get("paper_pf_matches_unified", False)),
            "paper_returns_match_unified": bool(data.get("paper_returns_match_unified", False)),
            "evidence_matches_unified": bool(data.get("evidence_matches_unified", False)),
            "cohort_matches_unified": bool(data.get("cohort_matches_unified", False)),
            "insufficient_evidence": bool(data.get("insufficient_evidence", False)),
            "trade_count": _to_int(data.get("trade_count"), 0),
            "paper_trade_count": _to_int(data.get("paper_trade_count"), 0),
            "recommendations_reviewed": _to_int(data.get("recommendations_reviewed"), 0),
            "paper_gross_profit": _to_float(data.get("paper_gross_profit"), 0.0),
            "paper_gross_loss": _to_float(data.get("paper_gross_loss"), 0.0),
            "winning_trade_count": _to_int(data.get("winning_trade_count"), 0),
            "losing_trade_count": _to_int(data.get("losing_trade_count"), 0),
            "breakeven_trade_count": _to_int(data.get("breakeven_trade_count"), 0),
            "paper_profit_factor_raw": data.get("paper_profit_factor_raw"),
            "paper_profit_factor_verified": data.get("paper_profit_factor_verified"),
            "paper_profit_factor": _to_float(data.get("paper_profit_factor"), 0.0),
            "paper_win_rate": _to_float(data.get("paper_win_rate"), 0.0),
            "paper_avg_return": _to_float(data.get("paper_avg_return"), 0.0),
            "paper_avg_mfe": _to_float(data.get("paper_avg_mfe"), 0.0),
            "paper_avg_mae": _to_float(data.get("paper_avg_mae"), 0.0),
            "paper_profit_capture": _to_float(data.get("paper_profit_capture"), 0.0),
            "paper_exit_quality": _to_float(data.get("paper_exit_quality"), 0.0),
            "shadow_trade_count": _to_int(data.get("shadow_trade_count"), 0),
            "shadow_completed_lifecycle_count": _to_int(data.get("shadow_completed_lifecycle_count"), 0),
            "shadow_winning_trade_count": _to_int(data.get("shadow_winning_trade_count"), 0),
            "shadow_losing_trade_count": _to_int(data.get("shadow_losing_trade_count"), 0),
            "shadow_breakeven_trade_count": _to_int(data.get("shadow_breakeven_trade_count"), 0),
            "shadow_gross_profit": _to_float(data.get("shadow_gross_profit"), 0.0),
            "shadow_gross_loss": _to_float(data.get("shadow_gross_loss"), 0.0),
            "shadow_profit_factor_raw": data.get("shadow_profit_factor_raw"),
            "shadow_profit_factor_verified": data.get("shadow_profit_factor_verified"),
            "shadow_profit_factor": _to_float(data.get("shadow_profit_factor"), 0.0),
            "shadow_win_rate": _to_float(data.get("shadow_win_rate"), 0.0),
            "shadow_avg_return": _to_float(data.get("shadow_avg_return"), 0.0),
            "shadow_avg_mfe": _to_float(data.get("shadow_avg_mfe"), 0.0),
            "shadow_avg_mae": _to_float(data.get("shadow_avg_mae"), 0.0),
            "shadow_profit_capture": _to_float(data.get("shadow_profit_capture"), 0.0),
            "shadow_exit_quality": _to_float(data.get("shadow_exit_quality"), 0.0),
            "shadow_outperformance_pct": _to_float(data.get("shadow_outperformance_pct"), 0.0),
            "shadow_underperformance_pct": _to_float(data.get("shadow_underperformance_pct"), 0.0),
            "profit_factor_delta": _to_float(data.get("profit_factor_delta"), 0.0),
            "win_rate_delta": _to_float(data.get("win_rate_delta"), 0.0),
            "avg_return_delta": _to_float(data.get("avg_return_delta"), 0.0),
            "profit_capture_delta": _to_float(data.get("profit_capture_delta"), 0.0),
            "exit_quality_delta": _to_float(data.get("exit_quality_delta"), 0.0),
            "rolling_20_shadow_pf": _to_float(data.get("rolling_20_shadow_pf"), 0.0),
            "rolling_20_paper_pf": _to_float(data.get("rolling_20_paper_pf"), 0.0),
            "rolling_50_shadow_pf": _to_float(data.get("rolling_50_shadow_pf"), 0.0),
            "rolling_50_paper_pf": _to_float(data.get("rolling_50_paper_pf"), 0.0),
            "rolling_100_shadow_pf": _to_float(data.get("rolling_100_shadow_pf"), 0.0),
            "rolling_100_paper_pf": _to_float(data.get("rolling_100_paper_pf"), 0.0),
            "lifetime_shadow_pf": _to_float(data.get("lifetime_shadow_pf"), 0.0),
            "lifetime_paper_pf": _to_float(data.get("lifetime_paper_pf"), 0.0),
            "rolling_20_paper_pf_status": _text(data.get("rolling_20_paper_pf_status"), "INSUFFICIENT_EVIDENCE"),
            "rolling_20_shadow_pf_status": _text(data.get("rolling_20_shadow_pf_status"), "INSUFFICIENT_EVIDENCE"),
            "rolling_50_paper_pf_status": _text(data.get("rolling_50_paper_pf_status"), "INSUFFICIENT_EVIDENCE"),
            "rolling_50_shadow_pf_status": _text(data.get("rolling_50_shadow_pf_status"), "INSUFFICIENT_EVIDENCE"),
            "rolling_100_paper_pf_status": _text(data.get("rolling_100_paper_pf_status"), "INSUFFICIENT_EVIDENCE"),
            "rolling_100_shadow_pf_status": _text(data.get("rolling_100_shadow_pf_status"), "INSUFFICIENT_EVIDENCE"),
            "lifetime_paper_pf_status": _text(data.get("lifetime_paper_pf_status"), "INSUFFICIENT_EVIDENCE"),
            "lifetime_shadow_pf_status": _text(data.get("lifetime_shadow_pf_status"), "INSUFFICIENT_EVIDENCE"),
            "shadow_alpha_available": bool(data.get("shadow_alpha_available", False)),
            "shadow_alpha_score": _to_float(data.get("shadow_alpha_score"), 0.0),
            "shadow_alpha_confidence": _to_float(data.get("shadow_alpha_confidence"), 0.0),
            "shadow_alpha_status": _text(data.get("shadow_alpha_status"), "INSUFFICIENT_EVIDENCE"),
            "source_attribution": list(data.get("source_attribution") or [])[:7],
            "build_cohort_comparison": list(data.get("build_cohort_comparison") or [])[:5],
            "cohort_profit_factor": dict(data.get("cohort_profit_factor") or {}),
            "cohort_avg_return": dict(data.get("cohort_avg_return") or {}),
            "cohort_profit_capture": dict(data.get("cohort_profit_capture") or {}),
            "cohort_trade_count": dict(data.get("cohort_trade_count") or {}),
            "cohort_profit_factor_verified": dict(data.get("cohort_profit_factor_verified") or {}),
            "cohort_confidence": dict(data.get("cohort_confidence") or {}),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "partial_sells_enabled": bool(data.get("partial_sells_enabled", False)),
            "automatic_trailing_stops_enabled": bool(data.get("automatic_trailing_stops_enabled", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "entry_behavior_changed": bool(data.get("entry_behavior_changed", False)),
            "exit_behavior_changed": bool(data.get("exit_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "Continue shadow-vs-paper attribution observation-only."),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _controlled_paper_learned_exit_validation_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "controlled_paper_learned_exit_validation"),
            "learned_exit_bucket_enabled": bool(data.get("learned_exit_bucket_enabled", False)),
            "learned_exit_bucket_configured": bool(data.get("learned_exit_bucket_configured", False)),
            "paper_exit_path_verified": bool(data.get("paper_exit_path_verified", False)),
            "paper_exit_path_verification_status": _text(data.get("paper_exit_path_verification_status"), "blocked"),
            "paper_exit_path_blockers": list(data.get("paper_exit_path_blockers") or [])[:10],
            "learned_exits_used_today": _to_int(data.get("learned_exits_used_today"), 0),
            "learned_exits_remaining_today": _to_int(data.get("learned_exits_remaining_today"), 5),
            "max_learning_corrected_exits_per_day": _to_int(data.get("max_learning_corrected_exits_per_day"), 5),
            "max_learning_corrected_exit_pct": _to_float(data.get("max_learning_corrected_exit_pct"), 25.0),
            "learned_exits_by_horizon": dict(data.get("learned_exits_by_horizon") or {}),
            "scalp_day_swing_coverage_status": _text(data.get("scalp_day_swing_coverage_status"), "not_started"),
            "top_policy_used": _text(data.get("top_policy_used"), "none"),
            "learned_exit_candidates_today": _to_int(data.get("learned_exit_candidates_today"), 0),
            "rejected_learned_exit_candidates": _to_int(data.get("rejected_learned_exit_candidates"), 0),
            "rejection_reasons": list(data.get("rejection_reasons") or [])[:10],
            "current_active_learned_exit_tests": _to_int(data.get("current_active_learned_exit_tests"), 0),
            "baseline_exits_today": _to_int(data.get("baseline_exits_today"), 0),
            "learned_corrected_exits_today": _to_int(data.get("learned_corrected_exits_today"), 0),
            "baseline_vs_learned_status": _text(data.get("baseline_vs_learned_status"), "controlled_bucket_disabled_until_exit_path_verified"),
            "baseline_profit_factor": _to_float(data.get("baseline_profit_factor"), 0.0),
            "learned_corrected_profit_factor": _to_float(data.get("learned_corrected_profit_factor"), 0.0),
            "profit_factor_delta": _to_float(data.get("profit_factor_delta"), 0.0),
            "baseline_win_rate": _to_float(data.get("baseline_win_rate"), 0.0),
            "learned_corrected_win_rate": _to_float(data.get("learned_corrected_win_rate"), 0.0),
            "win_rate_delta": _to_float(data.get("win_rate_delta"), 0.0),
            "baseline_expectancy": _to_float(data.get("baseline_expectancy"), 0.0),
            "learned_corrected_expectancy": _to_float(data.get("learned_corrected_expectancy"), 0.0),
            "expectancy_delta": _to_float(data.get("expectancy_delta"), 0.0),
            "baseline_capture_ratio": _to_float(data.get("baseline_capture_ratio"), 0.0),
            "learned_corrected_capture_ratio": _to_float(data.get("learned_corrected_capture_ratio"), 0.0),
            "capture_ratio_delta": _to_float(data.get("capture_ratio_delta"), 0.0),
            "baseline_giveback": _to_float(data.get("baseline_giveback"), 0.0),
            "learned_corrected_giveback": _to_float(data.get("learned_corrected_giveback"), 0.0),
            "giveback_delta": _to_float(data.get("giveback_delta"), 0.0),
            "capacity_freed_by_learned_exits": _to_int(data.get("capacity_freed_by_learned_exits"), 0),
            "saved_loss": _to_float(data.get("saved_loss"), 0.0),
            "missed_upside": _to_float(data.get("missed_upside"), 0.0),
            "false_exit_rate": _to_float(data.get("false_exit_rate"), 0.0),
            "rollback_status": _text(data.get("rollback_status"), "auto_disabled"),
            "rollback_reason": _text(data.get("rollback_reason"), "validation_bucket_config_disabled"),
            "rollback_triggered_at": _text(data.get("rollback_triggered_at"), ""),
            "kill_switch_status": _text(data.get("kill_switch_status"), "enabled"),
            "safety_status": _text(data.get("safety_status"), "safe_disabled"),
            "next_recommended_action": _text(data.get("next_recommended_action"), "keep_bucket_disabled_until_verified"),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "No behavior change."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "paper_mode_verified": bool(data.get("paper_mode_verified", False)),
            "broker_live_endpoint_allowed": bool(data.get("broker_live_endpoint_allowed", False)),
            "live_trading_changed": bool(data.get("live_trading_changed", False)),
            "no_live_endpoint": bool(data.get("no_live_endpoint", True)),
            "no_live_orders": bool(data.get("no_live_orders", True)),
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "broker_behavior_changed_scope": _text(data.get("broker_behavior_changed_scope"), "none"),
            "broad_ranking_behavior_changed": bool(data.get("broad_ranking_behavior_changed", False)),
            "broad_entry_behavior_changed": bool(data.get("broad_entry_behavior_changed", False)),
            "broad_exit_behavior_changed": bool(data.get("broad_exit_behavior_changed", False)),
            "broad_sizing_behavior_changed": bool(data.get("broad_sizing_behavior_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "fmp_budgets_changed": bool(data.get("fmp_budgets_changed", False)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _realistic_shadow_evidence_learning_lab_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_realistic_shadow_evidence_learning_lab"),
            "shadow_opportunities_tracked": _to_int(data.get("shadow_opportunities_tracked"), 0),
            "virtual_paths_created": _to_int(data.get("virtual_paths_created"), 0),
            "shadow_learning_events": _to_int(data.get("shadow_learning_events"), 0),
            "shadow_capacity_used": _to_float(data.get("shadow_capacity_used"), 0.0),
            "shadow_capacity_remaining": _to_int(data.get("shadow_capacity_remaining"), 0),
            "previous_shadow_target": _to_int(data.get("previous_shadow_target"), 125),
            "target_shadow_opportunities_per_day": _to_int(data.get("target_shadow_opportunities_per_day"), 175),
            "hard_max_shadow_opportunities_per_day": _to_int(data.get("hard_max_shadow_opportunities_per_day"), 200),
            "shadow_capacity_increase": _to_int(data.get("shadow_capacity_increase"), 50),
            "estimated_learning_acceleration_pct": _to_float(data.get("estimated_learning_acceleration_pct"), 40.0),
            "shadow_capacity_safe": bool(data.get("shadow_capacity_safe", True)),
            "price_path_realism_score": _to_float(data.get("price_path_realism_score"), 0.0),
            "price_path_source": _text(data.get("price_path_source"), "cached_lifecycle_replay_counterfactual_summaries"),
            "price_path_data_quality": _text(data.get("price_path_data_quality"), "insufficient_data"),
            "price_path_limitation": _text(data.get("price_path_limitation"), "insufficient_data"),
            "eligible_shadow_trades": _to_int(data.get("eligible_shadow_trades"), 0),
            "near_miss_shadow_trades": _to_int(data.get("near_miss_shadow_trades"), 0),
            "discarded_unrealistic_trades": _to_int(data.get("discarded_unrealistic_trades"), 0),
            "eligibility_pass_rate": _to_float(data.get("eligibility_pass_rate"), 0.0),
            "paper_engine_mirror_score": _to_float(data.get("paper_engine_mirror_score"), 0.0),
            "mirrored_candidate_count": _to_int(data.get("mirrored_candidate_count"), 0),
            "shadow_context_completeness": _to_float(data.get("shadow_context_completeness"), 0.0),
            "shadow_portfolio_value": _to_float(data.get("shadow_portfolio_value"), 0.0),
            "shadow_virtual_positions": _to_int(data.get("shadow_virtual_positions"), 0),
            "shadow_concentration": _to_float(data.get("shadow_concentration"), 0.0),
            "shadow_correlation": _to_float(data.get("shadow_correlation"), 0.0),
            "shadow_heat": _to_float(data.get("shadow_heat"), 0.0),
            "shadow_portfolio_realism_score": _to_float(data.get("shadow_portfolio_realism_score"), 0.0),
            "estimated_slippage_pct": _to_float(data.get("estimated_slippage_pct"), 0.0),
            "execution_realism_score": _to_float(data.get("execution_realism_score"), 0.0),
            "adjusted_shadow_return": data.get("adjusted_shadow_return"),
            "raw_shadow_return": data.get("raw_shadow_return"),
            "completed_shadow_lifecycles": _to_int(data.get("completed_shadow_lifecycles"), 0),
            "active_shadow_lifecycles": _to_int(data.get("active_shadow_lifecycles"), 0),
            "shadow_avg_MFE": data.get("shadow_avg_MFE"),
            "shadow_avg_MAE": data.get("shadow_avg_MAE"),
            "shadow_capture_ratio": data.get("shadow_capture_ratio"),
            "shadow_giveback_pct": data.get("shadow_giveback_pct"),
            "average_shadow_realism_score": _to_float(data.get("average_shadow_realism_score"), 0.0),
            "high_realism_shadow_trades": _to_int(data.get("high_realism_shadow_trades"), 0),
            "low_realism_shadow_trades": _to_int(data.get("low_realism_shadow_trades"), 0),
            "realism_weighted_learning_events": _to_int(data.get("realism_weighted_learning_events"), 0),
            "best_virtual_path": _text(data.get("best_virtual_path"), "insufficient_data"),
            "worst_virtual_path": _text(data.get("worst_virtual_path"), "insufficient_data"),
            "best_horizon": _text(data.get("best_horizon"), "insufficient_data"),
            "best_exit_style": _text(data.get("best_exit_style"), "insufficient_data"),
            "virtual_path_quality_score": _to_float(data.get("virtual_path_quality_score"), 0.0),
            "evidence_quality_score": _to_float(data.get("evidence_quality_score"), 0.0),
            "high_value_lessons": _to_int(data.get("high_value_lessons"), 0),
            "compressed_lessons": _to_int(data.get("compressed_lessons"), 0),
            "discarded_noise_count": _to_int(data.get("discarded_noise_count"), 0),
            "quality_retention_rate": _to_float(data.get("quality_retention_rate"), 0.0),
            "consensus_lesson_count": _to_int(data.get("consensus_lesson_count"), 0),
            "strongest_consensus_lesson": _text(data.get("strongest_consensus_lesson"), "insufficient_data"),
            "conflicting_lesson_count": _to_int(data.get("conflicting_lesson_count"), 0),
            "consensus_confidence_score": _to_float(data.get("consensus_confidence_score"), 0.0),
            "raw_observations": _to_int(data.get("raw_observations"), 0),
            "candidate_lessons": _to_int(data.get("candidate_lessons"), 0),
            "validated_lessons": _to_int(data.get("validated_lessons"), 0),
            "high_confidence_lessons": _to_int(data.get("high_confidence_lessons"), 0),
            "future_policy_candidates": _to_int(data.get("future_policy_candidates"), 0),
            "duplicate_lessons_compressed": _to_int(data.get("duplicate_lessons_compressed"), 0),
            "storage_saved_estimate": _to_float(data.get("storage_saved_estimate"), 0.0),
            "compression_quality_score": _to_float(data.get("compression_quality_score"), 0.0),
            "active_weakness_focus": _text(data.get("active_weakness_focus"), "insufficient_data"),
            "weakness_shadow_events": _to_int(data.get("weakness_shadow_events"), 0),
            "weakness_learning_score": _to_float(data.get("weakness_learning_score"), 0.0),
            "weakness_improvement_signal": _text(data.get("weakness_improvement_signal"), "insufficient_data"),
            "top_failure_pattern": _text(data.get("top_failure_pattern"), "insufficient_data"),
            "repeated_failure_count": _to_int(data.get("repeated_failure_count"), 0),
            "failure_pattern_confidence": _to_float(data.get("failure_pattern_confidence"), 0.0),
            "affected_symbols": list(data.get("affected_symbols") or [])[:8],
            "winning_policy": _text(data.get("winning_policy"), "insufficient_data"),
            "second_best_policy": _text(data.get("second_best_policy"), "insufficient_data"),
            "weakest_policy": _text(data.get("weakest_policy"), "insufficient_data"),
            "policy_tournament_score": _to_float(data.get("policy_tournament_score"), 0.0),
            "policy_confidence": _to_float(data.get("policy_confidence"), 0.0),
            "policy_readiness_candidate": _text(data.get("policy_readiness_candidate"), "insufficient_data"),
            "raw_shadow_records": _to_int(data.get("raw_shadow_records"), 0),
            "compact_shadow_summaries": _to_int(data.get("compact_shadow_summaries"), 0),
            "compressed_lesson_count": _to_int(data.get("compressed_lesson_count"), 0),
            "storage_pressure_score": _to_float(data.get("storage_pressure_score"), 0.0),
            "memory_pressure_score": _to_float(data.get("memory_pressure_score"), 0.0),
            "cleanup_recommendation": _text(data.get("cleanup_recommendation"), "insufficient_data"),
            "stale_lessons": list(data.get("stale_lessons") or [])[:8],
            "decayed_lessons": list(data.get("decayed_lessons") or [])[:8],
            "reinforced_lessons": list(data.get("reinforced_lessons") or [])[:8],
            "recency_quality_score": _to_float(data.get("recency_quality_score"), 0.0),
            "fmp_status": _text(data.get("fmp_status"), "insufficient_data"),
            "fmp_smart_budget_enabled": bool(data.get("fmp_smart_budget_enabled", False)),
            "fmp_rest_conserve_mode": bool(data.get("fmp_rest_conserve_mode", data.get("fmp_cache_only_mode", True))),
            "fmp_refresh_allowed_now": bool(data.get("fmp_refresh_allowed_now", False)),
            "fmp_refresh_block_reason": _text(data.get("fmp_refresh_block_reason"), "insufficient_data"),
            "fmp_zero_usage_reason": _text(data.get("fmp_zero_usage_reason"), "unknown_zero_usage"),
            "fmp_last_successful_call": _text(data.get("fmp_last_successful_call"), "insufficient_data"),
            "fmp_last_failed_call": _text(data.get("fmp_last_failed_call"), "insufficient_data"),
            "fmp_last_fresh_data_timestamp": _text(data.get("fmp_last_fresh_data_timestamp"), "insufficient_data"),
            "fmp_cache_hit_rate": _to_float(data.get("fmp_cache_hit_rate"), 0.0),
            "fmp_cache_only_mode": bool(data.get("fmp_cache_only_mode", True)),
            "fmp_provider_enabled": bool(data.get("fmp_provider_enabled", False)),
            "fmp_provider_available": bool(data.get("fmp_provider_available", False)),
            "fmp_zero_usage_detected": bool(data.get("fmp_zero_usage_detected", False)),
            "fmp_calls_used_today": _to_int(data.get("fmp_calls_used_today"), 0),
            "fmp_bandwidth_used_today": _to_float(data.get("fmp_bandwidth_used_today"), 0.0),
            "fmp_daily_call_limit": data.get("fmp_daily_call_limit", "call_limit_unknown"),
            "fmp_daily_bandwidth_limit": data.get("fmp_daily_bandwidth_limit", "bandwidth_limit_unknown"),
            "fmp_remaining_calls_estimate": data.get("fmp_remaining_calls_estimate", "call_limit_unknown"),
            "fmp_remaining_bandwidth_estimate": data.get("fmp_remaining_bandwidth_estimate", "bandwidth_limit_unknown"),
            "fmp_budget_status": _text(data.get("fmp_budget_status"), "insufficient_data"),
            "provider_fallback_status": _text(data.get("provider_fallback_status"), "insufficient_data"),
            "provider_budget_status": _text(data.get("provider_budget_status"), "insufficient_data"),
            "bandwidth_pressure_score": _to_float(data.get("bandwidth_pressure_score"), 0.0),
            "data_freshness_score": _to_float(data.get("data_freshness_score"), 0.0),
            "live_data_confidence_score": _to_float(data.get("live_data_confidence_score"), 0.0),
            "provider_warning": _text(data.get("provider_warning"), "none"),
            "recommended_safe_fix": _text(data.get("recommended_safe_fix"), "none"),
            "safe_fix_applied": bool(data.get("safe_fix_applied", False)),
            "safe_fix_reason": _text(data.get("safe_fix_reason"), "no_safe_fix_needed"),
            "governance_status": _text(data.get("governance_status"), "shadow_only"),
            "shadow_lab_safe": bool(data.get("shadow_lab_safe", True)),
            "blocked_behavior_changes": list(data.get("blocked_behavior_changes") or [])[:12],
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_realistic_shadow_lab_shadow_only"),
            "summary": _text(data.get("summary"), "Astra is generating realistic shadow evidence without broker orders."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "full_history_scanned": bool(data.get("full_history_scanned", False)),
            "bandwidth_saving_mode": bool(data.get("bandwidth_saving_mode", True)),
            "cache_hit": bool(data.get("cache_hit", False)),
            "cache_freshness": _text(data.get("cache_freshness"), "stale"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "paper_orders_placed": bool(data.get("paper_orders_placed", False)),
            "alpaca_orders_placed": bool(data.get("alpaca_orders_placed", False)),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "ranking_behavior_changed": bool(data.get("ranking_behavior_changed", False)),
            "paper_execution_behavior_changed": bool(data.get("paper_execution_behavior_changed", False)),
            "position_sizing_changed": bool(data.get("position_sizing_changed", False)),
            "thresholds_changed": bool(data.get("thresholds_changed", False)),
            "portfolio_allocation_changed": bool(data.get("portfolio_allocation_changed", False)),
            "order_logic_changed": bool(data.get("order_logic_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "behavior_safe_to_apply": bool(data.get("behavior_safe_to_apply", False)),
        }

    def _adaptive_learning_prioritization_resource_allocation_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_adaptive_learning_prioritization_resource_allocation"),
            "top_weakness": _text(data.get("top_weakness"), "insufficient_data"),
            "secondary_weakness": _text(data.get("secondary_weakness"), "insufficient_data"),
            "weakness_rankings": list(data.get("weakness_rankings") or [])[:10],
            "weakness_confidence": _to_float(data.get("weakness_confidence"), 0.0),
            "weakness_trend": _text(data.get("weakness_trend"), "unknown"),
            "weakness_persistence": _to_float(data.get("weakness_persistence"), 0.0),
            "weakness_is_real_vs_noise": _text(data.get("weakness_is_real_vs_noise"), "observation_only_possible_noise"),
            "highest_value_learning_focus": _text(data.get("highest_value_learning_focus"), "insufficient_data"),
            "lowest_value_learning_focus": _text(data.get("lowest_value_learning_focus"), "insufficient_data"),
            "expected_improvement_score": _to_float(data.get("expected_improvement_score"), 0.0),
            "learning_roi_score": _to_float(data.get("learning_roi_score"), 0.0),
            "focus_reason": _text(data.get("focus_reason"), "insufficient_data"),
            "weakness_focus_allocation": _to_float(data.get("weakness_focus_allocation"), 0.0),
            "balanced_learning_allocation": _to_float(data.get("balanced_learning_allocation"), 0.0),
            "strength_validation_allocation": _to_float(data.get("strength_validation_allocation"), 10.0),
            "system_health_allocation": _to_float(data.get("system_health_allocation"), 5.0),
            "active_focus_distribution": dict(data.get("active_focus_distribution") or {}),
            "allocation_confidence": _to_float(data.get("allocation_confidence"), 0.0),
            "allocation_guardrail_status": _text(data.get("allocation_guardrail_status"), "unknown"),
            "allocation_reason": _text(data.get("allocation_reason"), "insufficient_data"),
            "recommended_worker_focus": _text(data.get("recommended_worker_focus"), "insufficient_data"),
            "worker_focus_reason": _text(data.get("worker_focus_reason"), "insufficient_data"),
            "worker_focus_change": _text(data.get("worker_focus_change"), "recommendation_only_no_new_jobs_spawned"),
            "worker_focus_safety_status": _text(data.get("worker_focus_safety_status"), "safe_shadow_only_existing_orchestrator"),
            "recommended_replay_focus": _text(data.get("recommended_replay_focus"), "insufficient_data"),
            "replay_priority_reason": _text(data.get("replay_priority_reason"), "insufficient_data"),
            "counterfactual_focus": _text(data.get("counterfactual_focus"), "insufficient_data"),
            "replay_learning_value_score": _to_float(data.get("replay_learning_value_score"), 0.0),
            "memory_focus": _text(data.get("memory_focus"), "insufficient_data"),
            "retained_weakness_lessons": list(data.get("retained_weakness_lessons") or [])[:8],
            "deprioritized_lessons": list(data.get("deprioritized_lessons") or [])[:8],
            "memory_weighting_score": _to_float(data.get("memory_weighting_score"), 0.0),
            "retention_priority_reason": _text(data.get("retention_priority_reason"), "insufficient_data"),
            "improving_weakness": _text(data.get("improving_weakness"), "none_detected"),
            "worsening_weakness": _text(data.get("worsening_weakness"), "none_detected"),
            "emerging_weakness": _text(data.get("emerging_weakness"), "none_detected"),
            "resolved_weakness": _text(data.get("resolved_weakness"), "none_detected"),
            "weakness_drift_score": _to_float(data.get("weakness_drift_score"), 0.0),
            "governance_status": _text(data.get("governance_status"), "unavailable"),
            "allocation_safe": bool(data.get("allocation_safe", False)),
            "blocked_allocation_reason": _text(data.get("blocked_allocation_reason"), "none"),
            "policy_readiness_status": _text(data.get("policy_readiness_status"), "not_ready_shadow_only_no_behavior_changes"),
            "governance_guardrails": dict(data.get("governance_guardrails") or {}),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_adaptive_learning_prioritization_shadow_only"),
            "summary": _text(
                data.get("summary"),
                "Astra is ranking learning weaknesses and allocating learning focus without changing trading behavior.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "bandwidth_saving_mode": bool(data.get("bandwidth_saving_mode", True)),
            "api_budget_status": _text(data.get("api_budget_status"), "cached_summaries_only"),
            "cache_hit": bool(data.get("cache_hit", False)),
            "cache_status": _text(data.get("cache_status"), "unknown"),
            "cache_freshness": _text(data.get("cache_freshness"), "stale"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
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

    def _autonomous_intelligence_validation_governance_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_autonomous_intelligence_validation_governance"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "sample_size_quality": _to_float(data.get("sample_size_quality"), 0.0),
            "evidence_consistency": _to_float(data.get("evidence_consistency"), 0.0),
            "conflicting_evidence_score": _to_float(data.get("conflicting_evidence_score"), 0.0),
            "outlier_risk_score": _to_float(data.get("outlier_risk_score"), 0.0),
            "regime_contamination_score": _to_float(data.get("regime_contamination_score"), 0.0),
            "recency_relevance_score": _to_float(data.get("recency_relevance_score"), 0.0),
            "lesson_reliability_score": _to_float(data.get("lesson_reliability_score"), 0.0),
            "truth_validation_score": _to_float(data.get("truth_validation_score"), 0.0),
            "trusted_lessons": list(data.get("trusted_lessons") or [])[:8],
            "questionable_lessons": list(data.get("questionable_lessons") or [])[:8],
            "strongest_validated_lesson": _text(data.get("strongest_validated_lesson"), "insufficient_data"),
            "weakest_validated_lesson": _text(data.get("weakest_validated_lesson"), "insufficient_data"),
            "truth_validation_status": _text(data.get("truth_validation_status"), "insufficient_data"),
            "top_root_cause": _text(data.get("top_root_cause"), "insufficient_data"),
            "likely_contributing_systems": list(data.get("likely_contributing_systems") or [])[:10],
            "improvement_hypothesis": _text(data.get("improvement_hypothesis"), "insufficient_data"),
            "highest_value_hypothesis": _text(data.get("highest_value_hypothesis"), "insufficient_data"),
            "expected_gain": _to_float(data.get("expected_gain"), 0.0),
            "confidence": _to_float(data.get("confidence"), 0.0),
            "virtual_test_recommended": bool(data.get("virtual_test_recommended", False)),
            "recommended_virtual_test": _text(data.get("recommended_virtual_test"), "insufficient_data"),
            "self_healing_status": _text(data.get("self_healing_status"), "diagnostic_only"),
            "autonomous_repair_readiness": _text(data.get("autonomous_repair_readiness"), "not_ready_shadow_only"),
            "governance_score": _to_float(data.get("governance_score"), 0.0),
            "warning_level": _text(data.get("warning_level"), "red"),
            "primary_risk": _text(data.get("primary_risk"), "insufficient_data"),
            "secondary_risk": _text(data.get("secondary_risk"), "insufficient_data"),
            "trading_safety_status": _text(data.get("trading_safety_status"), "green"),
            "learning_safety_status": _text(data.get("learning_safety_status"), "unknown"),
            "storage_safety_status": _text(data.get("storage_safety_status"), "unknown"),
            "performance_safety_status": _text(data.get("performance_safety_status"), "unknown"),
            "api_safety_status": _text(data.get("api_safety_status"), "unknown"),
            "infrastructure_safety_status": _text(data.get("infrastructure_safety_status"), "unknown"),
            "knowledge_safety_status": _text(data.get("knowledge_safety_status"), "unknown"),
            "governance_recommendation": _text(data.get("governance_recommendation"), "continue_shadow_only_learning_validation"),
            "ready_policies": list(data.get("ready_policies") or []),
            "not_ready_policies": list(data.get("not_ready_policies") or []),
            "closest_policy_to_readiness": _text(data.get("closest_policy_to_readiness"), "insufficient_data"),
            "readiness_blocker": _text(data.get("readiness_blocker"), "insufficient_data"),
            "policy_readiness_score": _to_float(data.get("policy_readiness_score"), 0.0),
            "policy_readiness_scores": dict(data.get("policy_readiness_scores") or {}),
            "policies_applied": list(data.get("policies_applied") or []),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "continue_autonomous_intelligence_validation_shadow_only"),
            "summary": _text(
                data.get("summary"),
                "Astra is validating lesson truth, diagnosing weaknesses, proposing virtual tests, and monitoring governance without changing trading behavior.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "provider_calls_used": _to_int(data.get("provider_calls_used"), 0),
            "llm_calls_used": _to_int(data.get("llm_calls_used"), 0),
            "dashboard_scan_rows": _to_int(data.get("dashboard_scan_rows"), 0),
            "raw_history_scanned": bool(data.get("raw_history_scanned", False)),
            "raw_archive_scanned": bool(data.get("raw_archive_scanned", False)),
            "bandwidth_saving_mode": bool(data.get("bandwidth_saving_mode", True)),
            "cache_hit": bool(data.get("cache_hit", False)),
            "cache_status": _text(data.get("cache_status"), "unknown"),
            "cache_freshness": _text(data.get("cache_freshness"), "stale"),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
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

    def _trade_archetype_regime_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_archetype_regime_learning"),
            "tracked_trades": _to_int(data.get("tracked_trades"), 0),
            "archetype_distribution": dict(data.get("archetype_distribution") or {}),
            "regime_distribution": dict(data.get("regime_distribution") or {}),
            "best_archetype": _text(data.get("best_archetype"), "insufficient_data"),
            "weakest_archetype": _text(data.get("weakest_archetype"), "insufficient_data"),
            "most_consistent_archetype": _text(data.get("most_consistent_archetype"), "insufficient_data"),
            "highest_giveback_archetype": _text(data.get("highest_giveback_archetype"), "insufficient_data"),
            "best_follow_through_archetype": _text(data.get("best_follow_through_archetype"), "insufficient_data"),
            "worst_follow_through_archetype": _text(data.get("worst_follow_through_archetype"), "insufficient_data"),
            "best_regime": _text(data.get("best_regime"), "insufficient_data"),
            "weakest_regime": _text(data.get("weakest_regime"), "insufficient_data"),
            "current_regime": _text(data.get("current_regime"), "uncertain_regime"),
            "current_regime_quality": _to_float(data.get("current_regime_quality"), 0.0),
            "current_regime_trade_support": _text(data.get("current_regime_trade_support"), "selective_or_uncertain"),
            "best_archetype_regime_pair": _text(data.get("best_archetype_regime_pair"), "insufficient_data"),
            "weakest_archetype_regime_pair": _text(data.get("weakest_archetype_regime_pair"), "insufficient_data"),
            "current_best_supported_archetype": _text(data.get("current_best_supported_archetype"), "insufficient_data"),
            "current_archetype_regime_alignment_score": _to_float(data.get("current_archetype_regime_alignment_score"), 0.0),
            "poor_fit_archetype_warning": bool(data.get("poor_fit_archetype_warning", False)),
            "archetype_quality_scores": dict(data.get("archetype_quality_scores") or {}),
            "regime_quality_scores": dict(data.get("regime_quality_scores") or {}),
            "archetype_regime_matrix_summary": dict(data.get("archetype_regime_matrix_summary") or {}),
            "shadow_recommendation": _text(data.get("shadow_recommendation"), "insufficient_data"),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "summary": _text(data.get("summary"), "Trade archetype and regime intelligence is collecting lifecycle evidence."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
        }

    def _replay_counterfactual_learning_v2_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "tracked_lifecycles": _to_int(data.get("tracked_lifecycles"), 0),
            "counterfactuals_generated": _to_int(data.get("counterfactuals_generated"), 0),
            "average_actual_return": data.get("average_actual_return"),
            "average_best_counterfactual_return": data.get("average_best_counterfactual_return"),
            "average_counterfactual_improvement": data.get("average_counterfactual_improvement"),
            "average_actual_vs_best_possible": data.get("average_actual_vs_best_possible"),
            "best_counterfactual_pattern": _text(data.get("best_counterfactual_pattern"), "insufficient_data"),
            "most_common_missed_improvement": _text(data.get("most_common_missed_improvement"), "insufficient_data"),
            "replay_learning_score": data.get("replay_learning_score"),
            "replay_learning_recommendation": _text(data.get("replay_learning_recommendation"), "insufficient_data"),
            "replay_actual_avg_source": _text(data.get("replay_actual_avg_source"), "unknown"),
            "replay_best_virtual_source": _text(data.get("replay_best_virtual_source"), "unknown"),
            "replay_scope_label": _text(data.get("replay_scope_label"), "unknown"),
            "replay_closed_only": bool(data.get("replay_closed_only", False)),
            "replay_open_included": bool(data.get("replay_open_included", False)),
            "replay_outlier_symbols": list(data.get("replay_outlier_symbols") or [])[:8],
            "replay_negative_return_drivers": dict(data.get("replay_negative_return_drivers") or {}),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
        }

    def _opportunity_cost_learning_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "selected_candidates_reviewed": _to_int(data.get("selected_candidates_reviewed"), 0),
            "rejected_candidates_reviewed": _to_int(data.get("rejected_candidates_reviewed"), 0),
            "average_opportunity_cost": data.get("average_opportunity_cost"),
            "avg_selected_return": data.get("avg_selected_return"),
            "avg_rejected_return": data.get("avg_rejected_return"),
            "median_opportunity_cost": data.get("median_opportunity_cost"),
            "largest_positive_gap": data.get("largest_positive_gap"),
            "largest_negative_gap": data.get("largest_negative_gap"),
            "largest_positive_gap_symbol": _text(data.get("largest_positive_gap_symbol"), "insufficient_data"),
            "largest_negative_gap_symbol": _text(data.get("largest_negative_gap_symbol"), "insufficient_data"),
            "outlier_symbols": list(data.get("outlier_symbols") or [])[:8],
            "calculation_method": _text(data.get("calculation_method"), "opportunity_cost_pct = rejected_return_pct - selected_return_pct"),
            "missed_opportunity_count": _to_int(data.get("missed_opportunity_count"), 0),
            "correct_selection_count": _to_int(data.get("correct_selection_count"), 0),
            "selection_quality_score": data.get("selection_quality_score"),
            "ranking_quality_score": data.get("ranking_quality_score"),
            "best_selected_symbol": _text(data.get("best_selected_symbol"), "insufficient_data"),
            "worst_selected_symbol": _text(data.get("worst_selected_symbol"), "insufficient_data"),
            "best_rejected_symbol": _text(data.get("best_rejected_symbol"), "insufficient_data"),
            "missed_best_symbol": _text(data.get("missed_best_symbol"), "insufficient_data"),
            "ranking_improvement_recommendation": _text(data.get("ranking_improvement_recommendation"), "insufficient_data"),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
        }

    def _advanced_learning_intelligence_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_advanced_learning_diagnostics"),
            "metrics_reconciled": bool(data.get("metrics_reconciled", False)),
            "source_validation_passed": bool(data.get("source_validation_passed", False)),
            "evidence_consistency_score": _to_float(data.get("evidence_consistency_score"), 0.0),
            "metric_confidence_score": _to_float(data.get("metric_confidence_score"), 0.0),
            "memory_quality_score": _to_float(data.get("memory_quality_score"), 0.0),
            "graph_maturity": _text(data.get("graph_maturity"), "warming_up"),
            "graph_confidence": _to_float(data.get("graph_confidence"), 0.0),
            "explanation_quality_score": _to_float(data.get("explanation_quality_score"), 0.0),
            "explanation_confidence": _to_float(data.get("explanation_confidence"), 0.0),
            "supporting_evidence_count": _to_int(data.get("supporting_evidence_count"), 0),
            "strongest_learning_connection": _text(data.get("strongest_learning_connection"), "insufficient_data"),
            "weakest_learning_connection": _text(data.get("weakest_learning_connection"), "insufficient_data"),
            "similar_trade_count": _to_int(data.get("similar_trade_count"), 0),
            "closest_trade_matches": list(data.get("closest_trade_matches") or [])[:8],
            "average_similar_return": data.get("average_similar_return"),
            "average_similar_follow_through": data.get("average_similar_follow_through"),
            "average_similar_profit_capture": data.get("average_similar_profit_capture"),
            "best_similar_context": _text(data.get("best_similar_context"), "insufficient_data"),
            "worst_similar_context": _text(data.get("worst_similar_context"), "insufficient_data"),
            "graph_insights": list(data.get("graph_insights") or [])[:6],
            "released_win_rate": data.get("released_win_rate"),
            "win_rate": data.get("win_rate"),
            "profit_factor": data.get("profit_factor"),
            "average_return": data.get("average_return"),
            "expectancy": data.get("expectancy"),
            "evidence_counts": dict(data.get("evidence_counts") or {}),
            "mismatches": list(data.get("mismatches") or [])[:8],
            "reconciliation_summary": _text(data.get("reconciliation_summary"), "Waiting for performance metric reconciliation evidence."),
            "candidate_explanation_template": _text(data.get("candidate_explanation_template"), "Waiting for evidence-backed explanation templates."),
            "recommendation": _text(data.get("recommendation"), "insufficient_data"),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
        }

    def _blind_spot_detection_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "blind_spot_score": _to_float(data.get("blind_spot_score"), 0.0),
            "missed_opportunity_count": _to_int(data.get("missed_opportunity_count"), 0),
            "top_missed_symbols": list(data.get("top_missed_symbols") or [])[:10],
            "underselected_sectors": list(data.get("underselected_sectors") or [])[:8],
            "overselected_sectors": list(data.get("overselected_sectors") or [])[:8],
            "underselected_archetypes": list(data.get("underselected_archetypes") or [])[:8],
            "cap_tier_bias": _text(data.get("cap_tier_bias"), "insufficient_evidence"),
            "horizon_bias": _text(data.get("horizon_bias"), "insufficient_evidence"),
            "regime_blind_spots": list(data.get("regime_blind_spots") or [])[:8],
            "strongest_blind_spot": _text(data.get("strongest_blind_spot"), "insufficient_evidence"),
            "recommendation": _text(data.get("recommendation"), "continue_shadow_monitoring"),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "human_review_required": bool(data.get("human_review_required", True)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
        }

    def _learning_issue_audit_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_learning_issue_audit"),
            "issue_status": dict(data.get("issue_status") or {}),
            "core_metric_source_regression_status": dict(data.get("core_metric_source_regression_status") or {}),
            "dataset_scope_mismatch_status": dict(data.get("dataset_scope_mismatch_status") or {}),
            "profit_capture_issue_status": dict(data.get("profit_capture_issue_status") or {}),
            "exit_quality_issue_status": dict(data.get("exit_quality_issue_status") or {}),
            "replay_conflict_status": dict(data.get("replay_conflict_status") or {}),
            "adaptive_execution_exit_v3_status": dict(data.get("adaptive_execution_exit_v3_status") or {}),
            "execution_participation_display_status": dict(data.get("execution_participation_display_status") or {}),
            "core_metric_source_diagnostics": dict(data.get("core_metric_source_diagnostics") or {}),
            "dataset_scope_diagnostics": dict(data.get("dataset_scope_diagnostics") or {}),
            "opportunity_cost_diagnostics": dict(data.get("opportunity_cost_diagnostics") or {}),
            "execution_participation_diagnostics": dict(data.get("execution_participation_diagnostics") or {}),
            "profit_capture_diagnostics": dict(data.get("profit_capture_diagnostics") or {}),
            "follow_through_diagnostics": dict(data.get("follow_through_diagnostics") or {}),
            "buy_purity_diagnostics": dict(data.get("buy_purity_diagnostics") or {}),
            "exit_quality_diagnostics": dict(data.get("exit_quality_diagnostics") or {}),
            "replay_conflict_diagnostics": dict(data.get("replay_conflict_diagnostics") or {}),
            "adaptive_execution_exit_v3_diagnostics": dict(data.get("adaptive_execution_exit_v3_diagnostics") or {}),
            "likely_cause_summary": _text(data.get("likely_cause_summary"), "collecting_issue_evidence"),
            "recommended_action": _text(data.get("recommended_action"), "keep_behavior_changes_shadow_only"),
            "safe_to_change_behavior": bool(data.get("safe_to_change_behavior", False)),
            "shadow_only_recommendation": _text(data.get("shadow_only_recommendation"), "no_behavior_change"),
            "human_review_required": bool(data.get("human_review_required", True)),
            "auto_apply_allowed": bool(data.get("auto_apply_allowed", False)),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": bool(data.get("broker_behavior_changed", False)),
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
        }

    def _remote_runtime_consistency_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "local_backend_ok": bool(data.get("local_backend_ok", False)),
            "frontend_ok": bool(data.get("frontend_ok", False)),
            "backend_url": _text(data.get("backend_url"), "http://127.0.0.1:8000"),
            "frontend_url": _text(data.get("frontend_url"), "http://127.0.0.1:5173"),
            "unified_timestamp": _text(data.get("unified_timestamp"), ""),
            "learning_tab_endpoint_count": _to_int(data.get("learning_tab_endpoint_count"), 1),
            "cache_age_seconds": _to_float(data.get("cache_age_seconds"), 0.0),
            "advanced_learning_metrics_visible": bool(data.get("advanced_learning_metrics_visible", False)),
            "remote_consistency_status": _text(data.get("remote_consistency_status"), "unknown"),
            "stale_ui_detected": bool(data.get("stale_ui_detected", False)),
            "recommended_action": _text(data.get("recommended_action"), "refresh_remote_browser_if_values_look_stale"),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
        }

    def _capacity_expansion_summary(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        trace = dict(statuses.get("paper_execution_trace") or {})
        throughput = dict(statuses.get("paper_autopilot_throughput") or {})
        stock_limit = _to_int(trace.get("stock_capacity_limit"), _to_int(throughput.get("max_stocks"), 12))
        total_limit = _to_int(trace.get("max_open_positions_total"), _to_int(throughput.get("current_max_concurrent_positions"), 15))
        return {
            "enabled": True,
            "version": "1.0.0",
            "mode": "paper_only_cautious_capacity_expansion",
            "paper_learning_capacity_expansion_active": bool(stock_limit >= 12 or total_limit >= 12),
            "target_stock_positions_default": 12,
            "target_stock_positions_upper_bound": 15,
            "current_stock_capacity_limit": stock_limit,
            "current_total_capacity_limit": total_limit,
            "suggested_horizon_mix": {"scalp": 3, "day_trade": 5, "swing_short_swing_max": 7},
            "capacity_expansion_reason": "increase_learning_evidence_without_forcing_trades",
            "quality_candidates_required": True,
            "duplicate_active_symbol_block_preserved": True,
            "market_session_gate_preserved": True,
            "broker_safeguards_preserved": True,
            "live_trading_changed": False,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _paper_path_gating_summary(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        trace = dict(statuses.get("paper_execution_trace") or {})
        throughput = dict(statuses.get("paper_autopilot_throughput") or {})
        broker = dict(statuses.get("alpaca_paper_broker") or {})
        decision_opt = dict(statuses.get("decision_optimization_trade_management_suite_v1") or {})
        exit_learning = dict(statuses.get("exit_learning_expansion_suite_v1") or {})
        candidates_seen = _to_int(trace.get("candidates_seen"), 0)
        eligible = _to_int(trace.get("eligible_candidates"), 0)
        submitted = _to_int(trace.get("orders_submitted"), 0)
        open_positions = _to_int(trace.get("broker_open_positions_count"), _to_int(trace.get("internal_open_positions_count"), 0))
        raw_rows = _to_int(trace.get("open_position_rows_count"), _to_int(throughput.get("open_position_rows_count"), open_positions))
        unique_positions = _to_int(trace.get("open_positions_unique_count"), open_positions)
        capacity_available = _to_int(trace.get("capacity_available"), 0)
        capacity_blocked = bool(trace.get("capacity_blocked", False))
        blocker = _text(trace.get("final_blocker_reason") or trace.get("why_no_trade_today"), "unknown_blocker")
        learned_exit_evidence = _to_int(decision_opt.get("evidence_count"), 0) + _to_int(exit_learning.get("tracked_trades"), 0)
        return {
            "paper_path_status": blocker if blocker not in {"", "awaiting_next_worker_cycle", "orders_submitted"} else "paper_path_open",
            "top_blocker": blocker,
            "candidates_reviewed_today": candidates_seen,
            "candidates_passed_ranking": eligible,
            "candidates_passed_risk": eligible,
            "candidates_blocked": max(0, candidates_seen - eligible),
            "high_confidence_candidates_blocked": max(0, candidates_seen - eligible),
            "missed_evidence_estimate": max(0, candidates_seen - submitted),
            "missed_opportunity_estimate": max(0, candidates_seen - submitted),
            "available_buying_power_at_block": _to_float(broker.get("buying_power"), _to_float(broker.get("available_buying_power"), 0.0)),
            "current_open_positions": unique_positions,
            "broker_confirmed_open_positions": _to_int(trace.get("broker_open_positions_count"), 0),
            "stale_internal_position_rows": max(0, raw_rows - unique_positions),
            "open_position_rows_count": raw_rows,
            "capacity_available": capacity_available,
            "capacity_blocked": capacity_blocked,
            "recommended_safe_action": (
                "Keep market-session safety intact; count unique open positions for capacity, expose raw-row overhang, and leave learned exits shadow-only."
            ),
            "learned_exit_status": "shadow_only_not_applied",
            "learned_hold_duration_status": "shadow_only_not_applied",
            "best_shadow_exit_policy": _text(decision_opt.get("best_virtual_exit_policy"), "insufficient_data"),
            "best_shadow_hold_window": _text(exit_learning.get("optimal_hold_window") or exit_learning.get("best_hold_window"), "insufficient_data"),
            "evidence_supporting_learned_exits": learned_exit_evidence,
            "readiness_status": "validation_ready_shadow_only" if learned_exit_evidence >= 40 else "not_ready",
            "remaining_evidence_needed": (
                "human_review_required_before_any_paper_exit_changes"
                if not bool(decision_opt.get("behavior_safe_to_apply", False))
                else "policy_governance_review_required"
            ),
            "learned_exits_applied": False,
            "learned_exits_ready": False,
            "behavior_safe_to_apply": False,
        }

    def _execution_participation_audit_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_audit"),
            "participation_label": _text(data.get("participation_label"), "insufficient_evidence"),
            "candidates_seen": _to_int(data.get("candidates_seen"), 0),
            "reviewed_total": _to_int(data.get("reviewed_total"), _to_int(data.get("candidates_execution_reviewed"), 0)),
            "unique_candidates_reviewed": _to_int(data.get("unique_candidates_reviewed"), 0),
            "eligible_unique": _to_int(data.get("eligible_unique"), 0),
            "submitted_unique": _to_int(data.get("submitted_unique"), 0),
            "candidates_promoted": _to_int(data.get("candidates_promoted"), 0),
            "candidates_deep_scored": _to_int(data.get("candidates_deep_scored"), 0),
            "candidates_execution_reviewed": _to_int(data.get("candidates_execution_reviewed"), 0),
            "candidates_portfolio_rejected": _to_int(data.get("candidates_portfolio_rejected"), 0),
            "candidates_timing_rejected": _to_int(data.get("candidates_timing_rejected"), 0),
            "candidates_correlation_rejected": _to_int(data.get("candidates_correlation_rejected"), 0),
            "candidates_confirmation_rejected": _to_int(data.get("candidates_confirmation_rejected"), 0),
            "candidates_exploration_rejected": _to_int(data.get("candidates_exploration_rejected"), 0),
            "candidates_position_limit_rejected": _to_int(data.get("candidates_position_limit_rejected"), 0),
            "candidates_submitted": _to_int(data.get("candidates_submitted"), 0),
            "candidates_filled": _to_int(data.get("candidates_filled"), 0),
            "eligible_candidates": _to_int(data.get("eligible_candidates"), 0),
            "orders_attempted": _to_int(data.get("orders_attempted"), 0),
            "orders_rejected": _to_int(data.get("orders_rejected"), 0),
            "duplicate_symbol_blocks": _to_int(data.get("duplicate_symbol_blocks"), 0),
            "duplicate_review_count": _to_int(data.get("duplicate_review_count"), _to_int(data.get("duplicate_symbol_blocks"), 0)),
            "active_position_blocks": _to_int(data.get("active_position_blocks"), 0),
            "active_position_block_count": _to_int(data.get("active_position_block_count"), _to_int(data.get("active_position_blocks"), 0)),
            "confirmation_required_blocks": _to_int(data.get("confirmation_required_blocks"), 0),
            "confirmation_required_count": _to_int(data.get("confirmation_required_count"), _to_int(data.get("confirmation_required_blocks"), 0)),
            "quality_rejections": _to_int(data.get("quality_rejections"), 0),
            "risk_rejections": _to_int(data.get("risk_rejections"), 0),
            "liquidity_rejections": _to_int(data.get("liquidity_rejections"), 0),
            "portfolio_fit_rejections": _to_int(data.get("portfolio_fit_rejections"), 0),
            "regime_rejections": _to_int(data.get("regime_rejections"), 0),
            "eligible_not_submitted_reason": _text(data.get("eligible_not_submitted_reason"), "none"),
            "final_submission_suppression_detected": bool(data.get("final_submission_suppression_detected", False)),
            "submitted_count": _to_int(data.get("submitted_count"), _to_int(data.get("candidates_submitted"), 0)),
            "submission_rate_total_reviews": _to_float(data.get("submission_rate_total_reviews"), _to_float(data.get("execution_conversion_rate"), 0.0)),
            "submission_rate_unique_candidates": _to_float(data.get("submission_rate_unique_candidates"), 0.0),
            "display_explanation": _text(data.get("display_explanation"), "Total reviews and unique candidates are separate participation views."),
            "participation_efficiency_score": _to_float(data.get("participation_efficiency_score"), 0.0),
            "participation_suppression_score": _to_float(data.get("participation_suppression_score"), 0.0),
            "missed_opportunity_pressure": _to_float(data.get("missed_opportunity_pressure"), 0.0),
            "overprotection_risk": _to_float(data.get("overprotection_risk"), 0.0),
            "underparticipation_risk": _to_float(data.get("underparticipation_risk"), 0.0),
            "execution_conversion_rate": _to_float(data.get("execution_conversion_rate"), 0.0),
            "eligible_to_submitted_rate": _to_float(data.get("eligible_to_submitted_rate"), 0.0),
            "submitted_to_filled_rate": _to_float(data.get("submitted_to_filled_rate"), 0.0),
            "market_opportunity_capture_rate": _to_float(data.get("market_opportunity_capture_rate"), 0.0),
            "missed_follow_through_pct": _to_float(data.get("missed_follow_through_pct"), 0.0),
            "missed_profit_capture_pct": _to_float(data.get("missed_profit_capture_pct"), 0.0),
            "missed_breakout_count": _to_int(data.get("missed_breakout_count"), 0),
            "missed_continuation_count": _to_int(data.get("missed_continuation_count"), 0),
            "missed_high_expectancy_candidates": _to_int(data.get("missed_high_expectancy_candidates"), 0),
            "top_rejection_reasons": dict(data.get("top_rejection_reasons") or {}),
            "rejection_stage_counts": dict(data.get("rejection_stage_counts") or {}),
            "final_blocker_reason": _text(data.get("final_blocker_reason"), "none"),
            "summary": _text(data.get("summary"), "Execution participation audit is collecting suppression evidence."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
        }

    def _portfolio_diversification_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_diversification"),
            "maturity": _text(data.get("maturity"), "warming_up"),
            "portfolio_diversification_v2_active": bool(data.get("portfolio_diversification_v2_active", True)),
            "average_portfolio_fit_score": data.get("average_portfolio_fit_score"),
            "average_diversification_quality_score": data.get("average_diversification_quality_score"),
            "average_correlation_pressure_score": data.get("average_correlation_pressure_score"),
            "average_concentration_pressure_score": data.get("average_concentration_pressure_score"),
            "largest_cluster": _text(data.get("largest_cluster"), "unknown_cluster"),
            "largest_cluster_count": _to_int(data.get("largest_cluster_count"), 0),
            "top_duplicate_theme": _text(data.get("top_duplicate_theme"), "unknown"),
            "mega_cap_concentration_pct": _to_float(data.get("mega_cap_concentration_pct"), 0.0),
            "non_mega_quality_candidates": _to_int(data.get("non_mega_quality_candidates"), 0),
            "candidates_penalized_for_correlation": _to_int(data.get("candidates_penalized_for_correlation"), 0),
            "candidates_boosted_for_diversification": _to_int(data.get("candidates_boosted_for_diversification"), 0),
            "elite_candidates_survived_penalty": _to_int(data.get("elite_candidates_survived_penalty"), 0),
            "current_portfolio_balance_label": _text(data.get("current_portfolio_balance_label"), "warming_up"),
            "candidate_cluster_summary": dict(data.get("candidate_cluster_summary") or {}),
            "summary": _text(data.get("summary"), "Portfolio diversification diagnostics are warming up."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "stale": bool(data.get("stale") or data.get("stale_cache")),
            "degraded_reason": _text(data.get("degraded_reason"), ""),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _system_health_summary(self, sources: dict[str, Any], statuses: dict[str, dict[str, Any]], learning_fast: dict[str, Any]) -> dict[str, Any]:
        failed = [k for k, v in statuses.items() if isinstance(v, dict) and v.get("enabled") is False and v.get("degraded_reason")]
        runtime = _first_float(learning_fast.get("runtime_learning_stability"), (statuses.get("adaptive_learning_infrastructure") or {}).get("trading_day_health_score"), default=0.0)
        provider_health = 100.0
        data_quality = _first_float((statuses.get("adaptive_learning_infrastructure") or {}).get("learning_readiness_score"), default=0.0)
        integrity = _first_float((statuses.get("adaptive_learning_infrastructure") or {}).get("infrastructure_maturity_score"), runtime, default=0.0)
        refresh = 100.0 if not failed else max(0.0, 100.0 - len(failed) * 12.0)
        degraded_reason = ""
        if failed:
            degraded_reason = f"{len(failed)} advanced diagnostics degraded"
        return {
            "runtime_integrity": _metric(integrity if integrity > 0 else None, evidence_count=1, maturity="healthy" if not failed else "degraded"),
            "data_quality": _metric(data_quality if data_quality > 0 else None, evidence_count=1, maturity="healthy" if data_quality > 0 else "warming_up"),
            "provider_health": _metric(provider_health, evidence_count=1, maturity="healthy", explanation="Unified diagnostics used cached/local data only."),
            "learning_refresh_integrity": _metric(refresh, evidence_count=1, maturity="healthy" if not failed else "degraded"),
            "degraded_reason": degraded_reason,
        }

    def _executive_snapshot(self, perf: dict[str, Any], execution: dict[str, Any], portfolio: dict[str, Any], learning: dict[str, Any], regime: dict[str, Any], system: dict[str, Any], rows: list[dict[str, Any]], evidence_count: int) -> dict[str, Any]:
        weakness_candidates = []
        for name, summary, key in (
            ("entry_quality", execution, "entry_quality"),
            ("exit_quality", execution, "exit_quality"),
            ("follow_through", execution, "follow_through_quality"),
            ("portfolio_survivability", portfolio, "portfolio_survivability"),
            ("replay_maturity", learning, "replay_maturity"),
        ):
            metric = summary.get(key) or {}
            value = metric.get("value")
            if value is not None:
                weakness_candidates.append((float(value), name))
        main_weakness = min(weakness_candidates)[1] if weakness_candidates else "insufficient_evidence"
        strongest = max(weakness_candidates)[1] if weakness_candidates else "warming_up"
        if main_weakness == "portfolio_survivability":
            next_focus = "reduce concentration and correlation before expanding exposure"
        elif main_weakness in {"entry_quality", "follow_through"}:
            next_focus = "tighten entry confirmation and follow-through validation"
        elif main_weakness == "exit_quality":
            next_focus = "review natural exit timing and profit giveback patterns"
        else:
            next_focus = "collect more naturally closed and replay-reviewed paper outcomes"
        evidence_label = "healthy" if evidence_count >= 50 else ("warming_up" if evidence_count > 0 else "insufficient_closed_trades")
        confidence_label = "high" if evidence_count >= 100 else ("medium" if evidence_count >= 30 else "low")
        primary_blocker = "none"
        if evidence_label != "healthy":
            primary_blocker = evidence_label
        elif (portfolio.get("concentration_risk") or {}).get("value", 0) and (portfolio.get("concentration_risk") or {}).get("value", 0) >= 75:
            primary_blocker = "portfolio_concentration_risk"
        return {
            "core_performance": {k: perf[k] for k in ("released_win_rate", "profit_factor", "expectancy_score", "average_return", "buy_list_purity")},
            "execution_quality": {k: execution[k] for k in ("entry_quality", "exit_quality", "follow_through_quality", "confidence_truthfulness")},
            "market_intelligence": {
                "current_regime": regime.get("current_regime"),
                "regime_alignment": regime.get("regime_alignment"),
                "best_archetype": regime.get("best_archetype"),
                "operating_posture": regime.get("operating_posture"),
            },
            "portfolio_health": {k: portfolio[k] for k in ("portfolio_survivability", "concentration_risk", "correlation_risk", "portfolio_heat")},
            "learning_status": {k: learning[k] for k in ("replay_maturity", "lifecycle_maturity", "expectancy_maturity", "closed_trade_coverage", "adaptive_confidence")},
            "system_health": {k: system[k] for k in ("runtime_integrity", "data_quality", "provider_health", "learning_refresh_integrity")},
            "main_current_weakness": main_weakness,
            "strongest_current_area": strongest,
            "next_best_focus": next_focus,
            "primary_blocker_reason": primary_blocker,
            "confidence_label": confidence_label,
            "evidence_label": evidence_label,
            "candidate_count": len(rows),
            "closed_trade_count": evidence_count,
        }

    def _master_charts(self, history_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        rows = history_rows[-CHART_POINTS:]
        returns = [_return_pct(r) for r in rows]
        timestamps = [_timestamp(r, i) for i, r in enumerate(rows)]
        equity: list[float] = []
        eq = 100.0
        peak = 100.0
        drawdown: list[float] = []
        for ret in returns:
            eq *= 1.0 + (ret / 100.0)
            peak = max(peak, eq)
            equity.append(round(eq, 4))
            drawdown.append(round(((eq - peak) / peak) * 100.0, 4) if peak else 0.0)
        rolling_exp = _rolling(returns, 20)
        rolling_wr: list[float] = []
        rolling_pf: list[float] = []
        for i in range(len(returns)):
            chunk = returns[max(0, i - 19): i + 1]
            rolling_wr.append(round(sum(1 for v in chunk if v > 0) / max(1, len(chunk)) * 100.0, 2))
            rolling_pf.append(_profit_factor(chunk) or 0.0)
        entry = [_score(r.get("entry_quality") or r.get("entry_timing_quality"), 50.0) for r in rows]
        follow = [_score(r.get("follow_through_quality_score") or r.get("follow_through_probability"), 50.0) for r in rows]
        exit_q = [_score(r.get("exit_quality_score") or r.get("exit_timing_quality"), 50.0) for r in rows]
        giveback = [_clamp(_to_float(r.get("profit_giveback") or r.get("profit_giveback_pct") or r.get("missed_profit_pct"), 0.0), 0.0, 100.0) for r in rows]
        weak_follow = [100.0 - v for v in follow]
        regime = statuses.get("regime_execution_survivability") or {}
        portfolio = statuses.get("trade_management_portfolio") or {}
        div = statuses.get("portfolio_diversification_correlation_v2") or {}
        replay = statuses.get("replay_lifecycle_expectancy") or {}
        adaptive_v2 = statuses.get("adaptive_execution_exit_intelligence_v2") or {}
        adaptive_exit = dict(adaptive_v2.get("adaptive_exit_diagnostics") or {})
        adaptive_exec = dict(adaptive_v2.get("execution_timing_diagnostics") or {})
        adaptive_lifecycle = dict(adaptive_v2.get("lifecycle_adaptation_diagnostics") or {})
        adaptive_profit = dict(adaptive_v2.get("profitability_improvement_diagnostics") or {})
        heat = _score(portfolio.get("portfolio_heat_score"), 50.0)
        concentration = _score(div.get("concentration_risk"), _score(regime.get("portfolio_concentration_risk"), 50.0))
        correlation = _score(div.get("correlation_risk"), _score(regime.get("portfolio_correlation_risk"), 50.0))
        survivability = _score(div.get("portfolio_survivability"), _score(regime.get("portfolio_survivability_score"), 50.0))
        diversification = _score(div.get("diversification_quality"), max(0.0, 100.0 - concentration))
        portfolio_fit = _score(div.get("portfolio_fit_quality"), 50.0)
        cluster_pressure = _score(div.get("average_correlation_pressure_score"), correlation)
        timeline_len = max(1, len(timestamps))
        heat_series = [round(heat, 2)] * timeline_len
        concentration_series = [round(concentration, 2)] * timeline_len
        correlation_series = [round(correlation, 2)] * timeline_len
        survivability_series = [round(survivability, 2)] * timeline_len
        diversification_series = [round(diversification, 2)] * timeline_len
        portfolio_fit_series = [round(portfolio_fit, 2)] * timeline_len
        cluster_pressure_series = [round(cluster_pressure, 2)] * timeline_len
        maturity_series = [round(_score(replay.get("replay_learning_maturity_score"), 0.0), 2)] * timeline_len
        lifecycle_series = [round(_score(replay.get("lifecycle_tracking_quality_score"), 0.0), 2)] * timeline_len
        expectancy_series = [round(_score(replay.get("expectancy_learning_maturity_score"), 0.0), 2)] * timeline_len
        coverage_series = [round(_score(replay.get("lifecycle_tracking_quality_score"), 0.0), 2)] * timeline_len
        adaptive_series = [round(_score((statuses.get("adaptive_learning_infrastructure") or {}).get("learning_readiness_score"), 0.0), 2)] * timeline_len
        adaptive_giveback_series = [round(_score((adaptive_exit.get("profit_giveback_pressure") or {}).get("value"), 0.0), 2)] * timeline_len
        adaptive_continuation_series = [round(_score(adaptive_v2.get("continuation_quality"), _score((adaptive_exit.get("continuation_strength") or {}).get("value"), 50.0)), 2)] * timeline_len
        adaptive_hold_series = [round(_score((adaptive_exit.get("adaptive_hold_quality") or {}).get("value"), _score((adaptive_lifecycle.get("hold_quality") or {}).get("value"), 50.0)), 2)] * timeline_len
        regime_expectancy_series = [round(_score((adaptive_profit.get("regime_adjusted_expectancy") or {}).get("value"), 50.0), 2)] * timeline_len
        execution_timing_series = [round(_score((adaptive_exec.get("execution_timing_quality") or {}).get("value"), 50.0), 2)] * timeline_len
        matrix: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for r in history_rows[-MAX_ROWS:]:
            reg = _text(r.get("current_market_regime") or r.get("market_regime") or r.get("regime_context"), "unknown")
            arch = _text(r.get("trade_archetype") or r.get("setup_type"), "unknown")
            bucket = matrix[reg].setdefault(arch, {"sample_size": 0, "returns": []})
            bucket["sample_size"] += 1
            bucket["returns"].append(_return_pct(r))
        heatmap = {}
        for reg, arches in matrix.items():
            heatmap[reg] = {}
            for arch, vals in arches.items():
                rets = vals.get("returns") or []
                heatmap[reg][arch] = {
                    "sample_size": len(rets),
                    "expectancy": round(mean(rets), 4) if rets else None,
                    "win_rate": round(sum(1 for v in rets if v > 0) / max(1, len(rets)) * 100.0, 2) if rets else None,
                    "profit_factor": _profit_factor(rets),
                }
        return {
            "equity_curve_drawdown_upgrade_timeline": {
                "timestamps": timestamps,
                "equity_values": equity,
                "drawdown_values": drawdown,
                "upgrade_markers": [],
                "regime_markers": [_text(regime.get("current_market_regime"), "uncertain_regime")],
                "portfolio_heat_markers": heat_series,
            },
            "rolling_expectancy_profit_factor_win_rate": {
                "timestamps": timestamps,
                "rolling_expectancy": rolling_exp,
                "rolling_profit_factor": rolling_pf,
                "rolling_win_rate": rolling_wr,
                "regime_markers": [_text(regime.get("current_market_regime"), "uncertain_regime")],
            },
            "entry_followthrough_exit_quality": {
                "timestamps": timestamps,
                "entry_quality": entry,
                "follow_through_quality": follow,
                "exit_quality": exit_q,
                "profit_giveback": giveback,
                "weak_follow_through_rate": weak_follow,
            },
            "portfolio_survivability": {
                "timestamps": timestamps,
                "portfolio_survivability": survivability_series,
                "concentration_risk": concentration_series,
                "correlation_risk": correlation_series,
                "portfolio_heat": heat_series,
                "diversification_quality": diversification_series,
                "portfolio_fit_quality": portfolio_fit_series,
                "cluster_pressure": cluster_pressure_series,
            },
            "portfolio_diversification_correlation_v2_trends": {
                "timestamps": timestamps,
                "diversification_quality_trend": diversification_series,
                "correlation_risk_trend": correlation_series,
                "concentration_risk_trend": concentration_series,
                "portfolio_fit_trend": portfolio_fit_series,
                "cluster_pressure_trend": cluster_pressure_series,
            },
            "learning_maturity_timeline": {
                "timestamps": timestamps,
                "replay_maturity": maturity_series,
                "lifecycle_maturity": lifecycle_series,
                "expectancy_maturity": expectancy_series,
                "closed_trade_coverage": coverage_series,
                "adaptive_confidence": adaptive_series,
            },
            "adaptive_execution_exit_v2_trends": {
                "timestamps": timestamps,
                "profit_giveback_trend": adaptive_giveback_series,
                "continuation_quality_trend": adaptive_continuation_series,
                "adaptive_hold_quality_trend": adaptive_hold_series,
                "regime_adjusted_expectancy_trend": regime_expectancy_series,
                "execution_timing_trend": execution_timing_series,
            },
            "regime_archetype_performance_heatmap": {
                "regime_archetype_matrix": heatmap,
                "expectancy_by_regime": {k: round(mean([cell.get("expectancy") or 0 for cell in v.values()]), 4) for k, v in heatmap.items()},
                "win_rate_by_archetype": self._aggregate_heatmap(heatmap, "win_rate"),
                "profit_factor_by_archetype": self._aggregate_heatmap(heatmap, "profit_factor"),
                "sample_size_by_cell": {reg: {arch: cell.get("sample_size", 0) for arch, cell in arches.items()} for reg, arches in heatmap.items()},
            },
        }

    @staticmethod
    def _aggregate_heatmap(heatmap: dict[str, dict[str, dict[str, Any]]], key: str) -> dict[str, float]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for arches in heatmap.values():
            for arch, cell in arches.items():
                value = cell.get(key)
                if value is not None:
                    grouped[arch].append(float(value))
        return {arch: round(mean(values), 4) for arch, values in grouped.items() if values}

    def _advanced_statuses(self, statuses: dict[str, dict[str, Any]], sources: dict[str, Any]) -> dict[str, Any]:
        names = [
            "learning_snapshot", "paper_performance", "top_buys", "edge_development", "trade_management_portfolio",
            "adaptive_learning_infrastructure", "replay_lifecycle_expectancy", "regime_execution_survivability",
            "adaptive_execution_exit_intelligence_v2", "market_session_execution_timing", "paper_opportunity_allocation",
            "portfolio_diversification_correlation_v2", "profit_seeking_adaptive_exploration", "mobile_runtime_compaction",
            "market_calendar_knowledge", "broad_universe_intake_promotion", "trade_lifecycle_excursion",
            "trade_lifecycle_excursion_v2", "adaptive_profit_capture", "profit_capture_peak_decay_exit_validation_suite_v1", "adaptive_execution_exit_intelligence_v3", "trade_archetype_regime",
            "exit_learning_expansion_suite_v1", "market_context_learning_suite_v1", "learning_acceleration_retention_suite_v1", "adaptive_learning_infrastructure_suite_v1", "adaptive_worker_activation_orchestration_v1", "confidence_calibration_performance_attribution_v1", "context_evidence_expansion_suite_v1", "catalyst_theme_narrative_capital_flow_intelligence_v2", "decision_optimization_trade_management_suite_v1", "full_opportunity_lifecycle_learning_suite_v1", "long_term_memory_symbol_retrieval_suite_v1", "virtual_paper_convergence_symbol_attribution_v1", "accelerated_learning_symbol_intelligence_suite_v1", "realistic_shadow_evidence_learning_lab_v1", "historical_intelligence_market_memory_suite_v1", "catalyst_persistence_decay_curves_v2", "catalyst_lifecycle_intelligence_v1", "cross_sector_capital_flow_memory_v1", "shadow_vs_paper_performance_attribution_v1", "candidate_ranking_attribution_promotion_intelligence_v1", "learning_roi_engine_v1", "evidence_quality_scoring_v1", "confidence_decomposition_engine_v1", "learning_drift_detection_v1", "market_regime_similarity_engine_v1", "ranking_tournament_engine_v1", "exit_tournament_engine_v1", "conviction_calibration_engine_v1", "intelligence_quality_learning_efficiency_suite_v1", "advanced_attribution_controlled_exit_learning_roi_suite_v1", "profit_optimization_context_intelligence_suite_v1", "trade_lifecycle_audit_truth_horizon_integrity_suite_v1", "astra_foundation_stabilization_governance_bundle_v1", "astra_tier2a_librarian_executive_truth_layer_v1", "astra_satellite_network_v1", "astra_tier3_historical_satellite_shadow_acceleration_v1", "astra_final_intelligence_maturation_bundle_v1", "astra_targeted_maturity_profit_capture_optimization_bundle_v1", "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1", "trade_thesis_validation_v1", "market_transition_detection_v1", "trade_family_intelligence_v1", "market_condition_attribution_v1", "market_breadth_index_intelligence_v1", "etf_sector_rotation_intelligence_v1", "crypto_shadow_learning_v1", "cross_market_attribution_transfer_learning_v1", "profit_lock_profit_capture_maturation_v2", "shadow_correction_validation_attribution_v1", "controlled_paper_profit_protection_pilot_v1", "adaptive_learning_prioritization_resource_allocation_v1", "autonomous_intelligence_validation_governance_v1", "replay_counterfactual_learning_v2", "opportunity_cost_learning",
            "advanced_learning_intelligence",
            "blind_spot_detection", "learning_issue_audit", "remote_runtime_consistency", "capacity_expansion_status",
            "paper_throughput_exit_validation_catalyst_intelligence_v1", "multi_horizon_paper_capacity_exit_validation_v1", "controlled_paper_learned_exit_validation_v1",
            "execution_participation_audit",
            "alpaca_paper_broker", "horizon_performance_dashboard",
        ]
        out = {}
        for name in names:
            payload = statuses.get(name) or sources.get(name) or {}
            out[name] = {
                "status": "available" if isinstance(payload, dict) and payload else "not_loaded",
                "maturity": _text((payload or {}).get("maturity") or (payload or {}).get("mode"), "summary_only"),
                "primary_metric": _first((payload or {}).get("primary_metric"), (payload or {}).get("score"), (payload or {}).get("enabled"), default=None),
                "blocker": _text((payload or {}).get("degraded_reason") or (payload or {}).get("final_blocker_reason"), "none"),
                "api_calls_used": _to_int((payload or {}).get("api_calls_used"), 0),
                "stale": bool((payload or {}).get("stale") or (payload or {}).get("stale_cache")),
                "endpoint": self._endpoint_for(name),
            }
        return out

    @staticmethod
    def _endpoint_for(name: str) -> str:
        mapping = {
            "learning_snapshot": "/api/learning_snapshot_fast_v1",
            "paper_performance": "/api/paper_performance",
            "top_buys": "/api/top_buys?buy_mode=balanced",
            "edge_development": "/api/edge_development_status_v1",
            "trade_management_portfolio": "/api/trade_management_portfolio_status_v1",
            "adaptive_learning_infrastructure": "/api/adaptive_learning_infrastructure_status_v1",
            "replay_lifecycle_expectancy": "/api/replay_lifecycle_expectancy_status_v1",
            "regime_execution_survivability": "/api/regime_execution_survivability_status_v1",
            "adaptive_execution_exit_intelligence_v2": "/api/adaptive_execution_exit_intelligence_status_v2",
            "portfolio_diversification_correlation_v2": "/api/portfolio_diversification_correlation_status_v2",
            "profit_seeking_adaptive_exploration": "/api/profit_seeking_adaptive_exploration_status_v1",
            "market_calendar_knowledge": "/api/market_calendar_knowledge_status_v1",
            "broad_universe_intake_promotion": "/api/broad_universe_intake_status_v1",
            "trade_lifecycle_excursion": "/api/trade_lifecycle_excursion_status_v1",
            "trade_lifecycle_excursion_v2": "/api/trade_lifecycle_excursion_v2_status",
            "adaptive_profit_capture": "/api/adaptive_profit_capture_status_v1",
            "profit_capture_peak_decay_exit_validation_suite_v1": "/api/profit_capture_peak_decay_exit_validation_suite_v1",
            "adaptive_execution_exit_intelligence_v3": "/api/adaptive_execution_exit_intelligence_v3",
            "exit_learning_expansion_suite_v1": "/api/exit_learning_expansion_suite_v1",
            "market_context_learning_suite_v1": "/api/market_context_learning_suite_v1",
            "learning_acceleration_retention_suite_v1": "/api/learning_acceleration_retention_suite_v1",
            "adaptive_learning_infrastructure_suite_v1": "/api/adaptive_learning_infrastructure_suite_v1",
            "adaptive_worker_activation_orchestration_v1": "/api/adaptive_worker_activation_orchestration_v1",
            "confidence_calibration_performance_attribution_v1": "/api/confidence_calibration_performance_attribution_v1",
            "context_evidence_expansion_suite_v1": "/api/context_evidence_expansion_suite_v1",
            "catalyst_theme_narrative_capital_flow_intelligence_v2": "/api/catalyst_theme_narrative_capital_flow_intelligence_v2",
            "decision_optimization_trade_management_suite_v1": "/api/decision_optimization_trade_management_suite_v1",
            "full_opportunity_lifecycle_learning_suite_v1": "/api/full_opportunity_lifecycle_learning_suite_v1",
            "long_term_memory_symbol_retrieval_suite_v1": "/api/long_term_memory_symbol_retrieval_suite_v1",
            "virtual_paper_convergence_symbol_attribution_v1": "/api/virtual_paper_convergence_symbol_attribution_v1",
            "accelerated_learning_symbol_intelligence_suite_v1": "/api/accelerated_learning_symbol_intelligence_suite_v1",
            "realistic_shadow_evidence_learning_lab_v1": "/api/realistic_shadow_evidence_learning_lab_v1",
            "historical_intelligence_market_memory_suite_v1": "/api/historical_intelligence_market_memory_suite_v1",
            "catalyst_persistence_decay_curves_v2": "/api/catalyst_persistence_decay_curves_v2",
            "catalyst_lifecycle_intelligence_v1": "/api/catalyst_lifecycle_intelligence_v1",
            "cross_sector_capital_flow_memory_v1": "/api/cross_sector_capital_flow_memory_v1",
            "shadow_vs_paper_performance_attribution_v1": "/api/shadow_vs_paper_performance_attribution_v1",
            "candidate_ranking_attribution_promotion_intelligence_v1": "/api/candidate_ranking_attribution_promotion_intelligence_v1",
            "learning_roi_engine_v1": "/api/learning_roi_engine_v1",
            "evidence_quality_scoring_v1": "/api/evidence_quality_scoring_v1",
            "confidence_decomposition_engine_v1": "/api/confidence_decomposition_engine_v1",
            "learning_drift_detection_v1": "/api/learning_drift_detection_v1",
            "market_regime_similarity_engine_v1": "/api/market_regime_similarity_engine_v1",
            "ranking_tournament_engine_v1": "/api/ranking_tournament_engine_v1",
            "exit_tournament_engine_v1": "/api/exit_tournament_engine_v1",
            "conviction_calibration_engine_v1": "/api/conviction_calibration_engine_v1",
            "intelligence_quality_learning_efficiency_suite_v1": "/api/intelligence_quality_learning_efficiency_suite_v1",
            "advanced_attribution_controlled_exit_learning_roi_suite_v1": "/api/advanced_attribution_controlled_exit_learning_roi_suite_v1",
            "profit_optimization_context_intelligence_suite_v1": "/api/profit_optimization_context_intelligence_suite_v1",
            "trade_lifecycle_audit_truth_horizon_integrity_suite_v1": "/api/trade_lifecycle_audit_truth_horizon_integrity_suite_v1",
            "astra_foundation_stabilization_governance_bundle_v1": "/api/astra_foundation_stabilization_governance_bundle_v1",
            "astra_tier2a_librarian_executive_truth_layer_v1": "/api/astra_tier2a_librarian_executive_truth_layer_v1",
            "astra_satellite_network_v1": "/api/astra_satellite_network_v1",
            "astra_tier3_historical_satellite_shadow_acceleration_v1": "/api/astra_tier3_historical_satellite_shadow_acceleration_v1",
            "astra_final_intelligence_maturation_bundle_v1": "/api/astra_final_intelligence_maturation_bundle_v1",
            "astra_targeted_maturity_profit_capture_optimization_bundle_v1": "/api/astra_targeted_maturity_profit_capture_optimization_bundle_v1",
            "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1": "/api/astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1",
            "trade_thesis_validation_v1": "/api/trade_thesis_validation_v1",
            "market_transition_detection_v1": "/api/market_transition_detection_v1",
            "trade_family_intelligence_v1": "/api/trade_family_intelligence_v1",
            "market_condition_attribution_v1": "/api/market_condition_attribution_v1",
            "market_breadth_index_intelligence_v1": "/api/market_breadth_index_intelligence_v1",
            "etf_sector_rotation_intelligence_v1": "/api/etf_sector_rotation_intelligence_v1",
            "crypto_shadow_learning_v1": "/api/crypto_shadow_learning_v1",
            "cross_market_attribution_transfer_learning_v1": "/api/cross_market_attribution_transfer_learning_v1",
            "profit_lock_profit_capture_maturation_v2": "/api/profit_lock_profit_capture_maturation_v2",
            "shadow_correction_validation_attribution_v1": "/api/shadow_correction_validation_attribution_v1",
            "controlled_paper_profit_protection_pilot_v1": "/api/controlled_paper_profit_protection_pilot_v1",
            "adaptive_learning_prioritization_resource_allocation_v1": "/api/adaptive_learning_prioritization_resource_allocation_v1",
            "autonomous_intelligence_validation_governance_v1": "/api/autonomous_intelligence_validation_governance_v1",
            "trade_archetype_regime": "/api/trade_archetype_regime_status_v1",
            "replay_counterfactual_learning_v2": "/api/replay_counterfactual_learning_v2_status",
            "opportunity_cost_learning": "/api/opportunity_cost_learning_status_v1",
            "advanced_learning_intelligence": "/api/advanced_learning_intelligence_status_v1",
            "blind_spot_detection": "/api/blind_spot_detection_status_v1",
            "learning_issue_audit": "/api/learning_issue_audit_status_v1",
            "remote_runtime_consistency": "/api/remote_runtime_consistency_status_v1",
            "execution_participation_audit": "/api/execution_participation_audit_status_v1",
            "paper_throughput_exit_validation_catalyst_intelligence_v1": "/api/paper_throughput_exit_validation_catalyst_intelligence_v1",
            "multi_horizon_paper_capacity_exit_validation_v1": "/api/multi_horizon_paper_capacity_exit_validation_v1",
            "controlled_paper_learned_exit_validation_v1": "/api/controlled_paper_learned_exit_validation_v1",
            "mobile_runtime_compaction": "/api/mobile_runtime_compaction_status_v1",
            "market_session_execution_timing": "/api/market_session_execution_timing_status_v1",
            "paper_opportunity_allocation": "/api/paper_opportunity_allocation_status_v1",
            "alpaca_paper_broker": "/api/alpaca_paper_status_v1",
            "horizon_performance_dashboard": "/api/horizon_performance_dashboard_v1",
        }
        return mapping.get(name, "")

    def _stale_status(self, sources: dict[str, Any], system: dict[str, Any]) -> dict[str, Any]:
        stale_sources = []
        for name, payload in sources.items():
            if isinstance(payload, dict) and (payload.get("stale") or payload.get("stale_cache") or payload.get("learning_payload_stale")):
                stale_sources.append(name)
        return {
            "stale": bool(stale_sources),
            "stale_sources": stale_sources,
            "last_known_good_used": bool(stale_sources),
            "stale_age_seconds": _to_float(sources.get("stale_age_seconds"), 0.0),
            "message": "Learning snapshot is using last-known-good data because some advanced diagnostics timed out." if stale_sources else "Unified learning snapshot is current enough for display.",
            "degraded_reason": system.get("degraded_reason") or "",
        }

    @staticmethod
    def _integration_contract() -> dict[str, Any]:
        return {
            "use_unified_learning_adapter": True,
            "avoid_frontend_endpoint_spam": True,
            "advanced_panels_lazy_load": True,
            "required_summary_fields": ["status", "maturity", "primary_metric", "blocker", "api_calls_used", "stale"],
            "endpoint_policy": "new endpoints allowed for debugging, but Learning tab should prefer unified snapshot",
            "future_roadmap_later_stage_only": [
                "Options Intelligence & Learning Suite",
                "Futures Intelligence & Learning Suite",
                "News LLM Engine",
                "Real-Time Sentiment Engine",
                "Massive Headline Ingestion Engine",
            ],
        }

    def _fallback(self, reason: str) -> dict[str, Any]:
        maturity = {"label": "degraded", "evidence_count": 0, "explanation": f"Unified diagnostics fallback: {reason[:140]}"}
        empty_metric = _metric(None, evidence_count=0, maturity="insufficient_evidence")
        return {
            "ok": False,
            "enabled": True,
            "version": VERSION,
            "generated_at": _now_iso(),
            "executive_snapshot": {
                "core_performance": {k: empty_metric for k in ("released_win_rate", "profit_factor", "expectancy_score", "average_return", "buy_list_purity")},
                "execution_quality": {k: empty_metric for k in ("entry_quality", "exit_quality", "follow_through_quality", "confidence_truthfulness")},
                "market_intelligence": {"current_regime": "uncertain_regime", "regime_alignment": empty_metric, "best_archetype": "insufficient_data", "operating_posture": "guarded"},
                "portfolio_health": {k: empty_metric for k in ("portfolio_survivability", "concentration_risk", "correlation_risk", "portfolio_heat")},
                "learning_status": {k: empty_metric for k in ("replay_maturity", "lifecycle_maturity", "expectancy_maturity", "closed_trade_coverage", "adaptive_confidence")},
                "system_health": {k: empty_metric for k in ("runtime_integrity", "data_quality", "provider_health", "learning_refresh_integrity")},
                "main_current_weakness": "degraded",
                "strongest_current_area": "unknown",
                "next_best_focus": "restore unified diagnostics",
                "primary_blocker_reason": reason[:140],
                "confidence_label": "low",
                "evidence_label": "degraded",
            },
            "master_charts": self._empty_charts(),
            "performance_summary": {},
            "execution_quality_summary": {},
            "portfolio_health_summary": {},
            "learning_maturity_summary": {},
            "regime_context_summary": {},
            "system_health_summary": {},
            "advanced_panel_links": {},
            "stale_data_status": {"stale": True, "message": "Unified diagnostics fallback is active.", "degraded_reason": reason[:160]},
            "evidence_maturity_status": maturity,
            "future_suite_integration_contract": self._integration_contract(),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
        }

    @staticmethod
    def _empty_charts() -> dict[str, Any]:
        base = {"timestamps": [], "insufficient_data": True}
        return {
            "equity_curve_drawdown_upgrade_timeline": {**base, "equity_values": [], "drawdown_values": [], "upgrade_markers": [], "regime_markers": [], "portfolio_heat_markers": []},
            "rolling_expectancy_profit_factor_win_rate": {**base, "rolling_expectancy": [], "rolling_profit_factor": [], "rolling_win_rate": [], "regime_markers": []},
            "entry_followthrough_exit_quality": {**base, "entry_quality": [], "follow_through_quality": [], "exit_quality": [], "profit_giveback": [], "weak_follow_through_rate": []},
            "portfolio_survivability": {**base, "portfolio_survivability": [], "concentration_risk": [], "correlation_risk": [], "portfolio_heat": [], "diversification_quality": []},
            "learning_maturity_timeline": {**base, "replay_maturity": [], "lifecycle_maturity": [], "expectancy_maturity": [], "closed_trade_coverage": [], "adaptive_confidence": []},
            "regime_archetype_performance_heatmap": {"regime_archetype_matrix": {}, "expectancy_by_regime": {}, "win_rate_by_archetype": {}, "profit_factor_by_archetype": {}, "sample_size_by_cell": {}},
        }
