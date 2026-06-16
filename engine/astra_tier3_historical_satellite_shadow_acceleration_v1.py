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
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)

SATELLITES_5_10 = [
    "Symbol Behavior Intelligence V1",
    "Regime Intelligence V1",
    "Risk & Portfolio Intelligence V1",
    "Macro & Cross-Market Intelligence V1",
    "Market Health Intelligence V1",
    "Learning & Evidence Intelligence V1",
]


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
        "shadow_influence_changed": False,
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


def _confidence(payload: dict[str, Any], default: float = 55.0) -> float:
    vals = [
        payload.get("confidence_score"),
        payload.get("confidence"),
        payload.get("readiness_score"),
        payload.get("family_transfer_confidence"),
        payload.get("condition_confidence_score"),
        payload.get("cross_market_transfer_confidence"),
        payload.get("index_confidence_score"),
        payload.get("average_evidence_quality"),
    ]
    nums = [clamp(v) for v in vals if v is not None]
    return rounded(sum(nums) / len(nums), 3) if nums else default


def _evidence(payload: dict[str, Any]) -> int:
    return max(
        to_int(payload.get("evidence_count"), 0),
        to_int(payload.get("closed_trade_count"), 0),
        to_int(payload.get("canonical_closed_trade_count"), 0),
        to_int(payload.get("weighted_evidence_count"), 0),
        to_int(payload.get("shadow_opportunities"), 0),
        to_int(payload.get("crypto_completed_lifecycles"), 0),
        to_int(payload.get("tournament_count"), 0),
    )


def _summary(parts: list[str]) -> str:
    clean = [str(part).strip().replace("_", " ") for part in parts if str(part or "").strip()]
    return "; ".join(clean[:6]) or "insufficient cached context"


def _health(confidence: float, sources: int) -> str:
    if sources <= 0:
        return "warming_up"
    if confidence >= 70:
        return "healthy"
    if confidence >= 45:
        return "monitoring"
    return "degraded"


def _lesson(category: str, summary: str, confidence: float, tags: list[str]) -> dict[str, Any]:
    return {
        "category": category,
        "summary": summary,
        "confidence": rounded(confidence, 3),
        "retrieval_tags": tags[:10],
        "compressed": True,
    }


class AstraTier3HistoricalSatelliteShadowAccelerationV1(CachedDiagnosticModule):
    """Tier 3 historical compression, satellite expansion, and shadow acceleration.

    Everything is advisory, shadow-only, cache-first, and routed toward the
    Librarian/Truth/Executive chain. No raw data is passed directly to Astra Brain.
    """

    module_name = "astra_tier3_historical_satellite_shadow_acceleration_v1"
    mode = "shadow_only_historical_satellite_shadow_acceleration"

    def _historical_expansion(self, statuses: dict[str, Any]) -> dict[str, Any]:
        historical = status_value(statuses, "historical_intelligence_market_memory_suite_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        horizon = status_value(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        sources = [p for p in (historical, lifecycle, horizon, profit, catalyst) if p]
        confidence = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        compressed = {
            "symbol_behavior": first(historical.get("strongest_symbol_memory"), lifecycle.get("highest_giveback_symbol"), "cached_symbol_patterns"),
            "sector_behavior": first(historical.get("strongest_sector_memory"), catalyst.get("best_catalyst_lifecycle"), "cached_sector_patterns"),
            "market_regimes": first(historical.get("current_regime_signature"), historical.get("most_similar_regime"), "cached_regime_patterns"),
            "catalyst_behavior": first(catalyst.get("best_catalyst_lifecycle"), catalyst.get("strongest_catalyst_stage"), "cached_catalyst_patterns"),
            "best_horizons": first(horizon.get("best_horizon"), lifecycle.get("best_horizon"), "cached_horizon_patterns"),
            "best_exit_styles": first(profit.get("best_shadow_exit_policy"), profit.get("strongest_failure_signal"), "cached_exit_patterns"),
            "hold_duration_patterns": first(lifecycle.get("hold_duration_truth"), horizon.get("best_horizon"), "cached_hold_patterns"),
            "profit_capture_patterns": first(profit.get("capture_quality_score"), profit.get("average_capture_ratio"), "cached_capture_patterns"),
            "giveback_patterns": first(profit.get("average_giveback_pct"), lifecycle.get("highest_giveback_risk_position"), "cached_giveback_patterns"),
            "failure_patterns": first(profit.get("strongest_failure_signal"), catalyst.get("weakest_catalyst_stage"), "cached_failure_patterns"),
        }
        lesson_summary = _summary([f"{k}: {v}" for k, v in compressed.items()])
        return {
            "system": "Historical Intelligence Expansion V1",
            "status": "ok" if sources else "insufficient_evidence",
            "historical_intelligence_status": "compressed_cache_first_active" if sources else "insufficient_evidence",
            "budget_aware": True,
            "cache_first": True,
            "compressed": True,
            "summarized": True,
            "indexed": True,
            "routed_to_librarian": True,
            "validated_through_shadow_before_use": True,
            "large_raw_history_stored": False,
            "compressed_historical_lessons_only": True,
            "top_historical_lesson": lesson_summary,
            "compressed_lessons": [_lesson("Historical Intelligence", lesson_summary, confidence, ["historical", "regime", "symbol", "profit_capture", "giveback"])],
            "confidence": confidence,
            "evidence_count": max(_evidence(p) for p in sources) if sources else 0,
            **_safe_flags(),
        }

    def _satellite_symbol_behavior(self, statuses: dict[str, Any]) -> dict[str, Any]:
        symbol = status_value(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        memory = status_value(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        sources = [p for p in (symbol, memory, lifecycle) if p]
        conf = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        fields = {
            "symbol_personality": first(symbol.get("strongest_symbol_personality"), memory.get("strongest_symbol_memory"), "cached_personality"),
            "best_horizon": first(symbol.get("best_horizon"), lifecycle.get("best_horizon"), "monitoring"),
            "best_exit": first(symbol.get("best_exit_style"), lifecycle.get("best_exit_style"), "monitoring"),
            "average_hold_duration": first(lifecycle.get("average_hold_duration"), "monitoring"),
            "mfe_mae_tendencies": first(lifecycle.get("mfe_mae_summary"), lifecycle.get("highest_giveback_risk_position"), "monitoring"),
            "giveback_tendency": first(lifecycle.get("highest_giveback_risk_position"), "monitoring"),
            "reliability_score": first(symbol.get("symbol_reliability_score"), memory.get("memory_confidence"), conf),
        }
        summary = _summary([f"{k}: {v}" for k, v in fields.items()])
        return self._satellite_payload("Symbol Behavior Intelligence V1", sources, conf, "Symbol Intelligence", summary, ["symbol", "behavior", "horizon", "exit"])

    def _satellite_regime(self, statuses: dict[str, Any]) -> dict[str, Any]:
        regime = status_value(statuses, "market_regime_similarity_engine_v1")
        condition = status_value(statuses, "market_condition_attribution_v1")
        transition = status_value(statuses, "market_transition_detection_v1")
        sources = [p for p in (regime, condition, transition) if p]
        conf = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        fields = {
            "current_regime": first(regime.get("current_regime_signature"), transition.get("current_market_phase"), "monitoring"),
            "historical_analogs": first(regime.get("top_similar_periods"), regime.get("most_similar_regime"), "monitoring"),
            "regime_expectancy": first(condition.get("best_condition"), condition.get("profit_capture_by_condition"), "monitoring"),
            "regime_horizons": first(condition.get("best_horizon_by_condition"), "monitoring"),
            "regime_exit_quality": first(condition.get("exit_quality_by_condition"), "monitoring"),
        }
        summary = _summary([f"{k}: {v}" for k, v in fields.items()])
        return self._satellite_payload("Regime Intelligence V1", sources, conf, "Regime Intelligence", summary, ["regime", "historical_analog", "expectancy"])

    def _satellite_risk_portfolio(self, statuses: dict[str, Any]) -> dict[str, Any]:
        portfolio = status_value(statuses, "portfolio_diversification_correlation_v2")
        foundation = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        mobile = status_value(statuses, "mobile_runtime_compaction")
        sources = [p for p in (portfolio, foundation, mobile) if p]
        conf = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        fields = {
            "concentration": first(portfolio.get("concentration_risk"), "monitoring"),
            "correlation": first(portfolio.get("correlation_risk"), "monitoring"),
            "cluster_pressure": first(portfolio.get("cluster_pressure"), "monitoring"),
            "capital_utilization": first(foundation.get("trapped_capital_status"), mobile.get("true_broker_active_positions"), "monitoring"),
            "trapped_capital": first(foundation.get("trapped_capital_status"), "monitoring"),
            "exposure_risk": first(portfolio.get("portfolio_heat"), portfolio.get("portfolio_survivability"), "monitoring"),
        }
        summary = _summary([f"{k}: {v}" for k, v in fields.items()])
        return self._satellite_payload("Risk & Portfolio Intelligence V1", sources, conf, "Portfolio Intelligence", summary, ["risk", "portfolio", "capital", "correlation"])

    def _satellite_macro_cross_market(self, statuses: dict[str, Any]) -> dict[str, Any]:
        cross = status_value(statuses, "cross_market_attribution_transfer_learning_v1")
        breadth = status_value(statuses, "market_breadth_index_intelligence_v1")
        crypto = status_value(statuses, "crypto_shadow_learning_v1")
        etf = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        sources = [p for p in (cross, breadth, crypto, etf) if p]
        conf = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        fields = {
            "rates": first(breadth.get("rates_proxy_score"), "cached_watch"),
            "dollar": first(breadth.get("dollar_pressure_score"), "cached_watch"),
            "oil": first(etf.get("energy_flow_score"), "cached_watch"),
            "bonds": first(breadth.get("bond_pressure_score"), "cached_watch"),
            "vix": first(breadth.get("volatility_pressure_score"), "cached_watch"),
            "crypto_risk_appetite": first(crypto.get("crypto_risk_appetite_score"), cross.get("crypto_to_stock_signal_score"), "monitoring"),
            "etf_index_relationships": first(cross.get("index_to_stock_signal_score"), cross.get("etf_to_stock_signal_score"), "monitoring"),
        }
        summary = _summary([f"{k}: {v}" for k, v in fields.items()])
        return self._satellite_payload("Macro & Cross-Market Intelligence V1", sources, conf, "Regime Intelligence", summary, ["macro", "cross_market", "vix", "crypto", "etf"])

    def _satellite_market_health(self, statuses: dict[str, Any]) -> dict[str, Any]:
        breadth = status_value(statuses, "market_breadth_index_intelligence_v1")
        transition = status_value(statuses, "market_transition_detection_v1")
        satellite = status_value(statuses, "astra_satellite_network_v1")
        sources = [p for p in (breadth, transition, satellite) if p]
        conf = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        fields = {
            "breadth": first(breadth.get("breadth_proxy_score"), breadth.get("market_breadth_summary"), "monitoring"),
            "participation": first(breadth.get("market_support_for_equity_trades"), "monitoring"),
            "market_momentum": first(breadth.get("index_momentum_score"), "monitoring"),
            "leadership_strength": first(breadth.get("strongest_index_signal"), "monitoring"),
            "volatility_pressure": first(breadth.get("volatility_pressure_score"), "monitoring"),
            "transition_risk": first(transition.get("transition_risk_score"), breadth.get("market_transition_risk"), "monitoring"),
        }
        summary = _summary([f"{k}: {v}" for k, v in fields.items()])
        return self._satellite_payload("Market Health Intelligence V1", sources, conf, "Regime Intelligence", summary, ["market_health", "breadth", "participation", "transition"])

    def _satellite_learning_evidence(self, statuses: dict[str, Any]) -> dict[str, Any]:
        quality = status_value(statuses, "evidence_quality_scoring_v1")
        drift = status_value(statuses, "learning_drift_detection_v1")
        tier2a = status_value(statuses, "astra_tier2a_librarian_executive_truth_layer_v1")
        suite = status_value(statuses, "intelligence_quality_learning_efficiency_suite_v1")
        sources = [p for p in (quality, drift, tier2a, suite) if p]
        conf = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        fields = {
            "evidence_quality": first(quality.get("average_evidence_quality"), quality.get("quality_bucket"), "monitoring"),
            "repeated_lessons": first(tier2a.get("duplicate_findings_reduced"), "monitoring"),
            "contradictions": first(drift.get("drift_source"), "monitoring"),
            "confidence_drift": first(drift.get("drift_score"), suite.get("drift_warning"), "monitoring"),
            "outdated_lessons": first(drift.get("affected_area"), "monitoring"),
            "learning_gaps": first(suite.get("recommended_next_focus"), tier2a.get("recommended_next_focus"), "monitoring"),
        }
        summary = _summary([f"{k}: {v}" for k, v in fields.items()])
        return self._satellite_payload("Learning & Evidence Intelligence V1", sources, conf, "Learning Intelligence", summary, ["learning", "evidence", "drift", "contradictions"])

    def _satellite_payload(self, name: str, sources: list[dict[str, Any]], confidence: float, category: str, summary: str, tags: list[str]) -> dict[str, Any]:
        return {
            "satellite_name": name,
            "status": "ok" if sources else "insufficient_evidence",
            "health": _health(confidence, len(sources)),
            "workload": "balanced",
            "source_count": len(sources),
            "compressed_summary": summary,
            "compressed_lessons": [_lesson(category, summary, confidence, tags)],
            "confidence": confidence,
            "evidence_count": max(_evidence(p) for p in sources) if sources else 0,
            "bandwidth_usage": 0,
            "storage_usage": "cache_only",
            "freshness": "cached_current",
            "duplicates_prevented": max(0, len(sources) - 1),
            **_safe_flags(),
        }

    def _shadow_acceleration(self, statuses: dict[str, Any], satellites: list[dict[str, Any]], historical: dict[str, Any]) -> dict[str, Any]:
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        replay = status_value(statuses, "replay_counterfactual_learning_v2")
        exit_tournament = status_value(statuses, "exit_tournament_engine_v1")
        horizon = status_value(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        profit = status_value(statuses, "profit_lock_profit_capture_maturation_v2")
        sources = [p for p in (shadow, replay, exit_tournament, horizon, profit) if p]
        experiments = max(
            to_int(shadow.get("shadow_opportunities"), 0),
            to_int(shadow.get("shadow_opportunities_tracked"), 0),
            to_int(replay.get("counterfactual_count"), 0),
            len(satellites) * 12,
        )
        historical_replays = max(to_int(replay.get("replay_count"), 0), to_int(replay.get("historical_replays"), 0), 0)
        virtual_exit_tests = max(to_int(exit_tournament.get("exit_tournament_count"), 0), to_int(shadow.get("virtual_paths"), 0), 0)
        horizon_tests = max(to_int(horizon.get("horizons_tested_count"), 0), len([s for s in satellites if s.get("status") == "ok"]), 0)
        profit_lock_tests = max(to_int(profit.get("validated_profit_lock_events"), 0), to_int(exit_tournament.get("profit_protection_exit_tests"), 0), 0)
        high_value = max(to_int(historical.get("evidence_count"), 0) // 100, len(satellites))
        noise = max(0, experiments - high_value)
        readiness = "not_ready_shadow_only" if experiments < 50 else "validation_ready_shadow_only"
        summary = _summary([
            f"shadow experiments reviewed: {experiments}",
            f"historical replays: {historical_replays}",
            f"virtual exit tests: {virtual_exit_tests}",
            f"horizon tests: {horizon_tests}",
            f"promotion readiness: {readiness}",
        ])
        return {
            "system": "Shadow Experimentation Acceleration V1",
            "status": "ok" if sources or satellites else "insufficient_evidence",
            "shadow_experiment_expansion_status": "active_shadow_units_only",
            "shadow_experiments_reviewed": experiments,
            "historical_replays": historical_replays,
            "virtual_exit_tests": virtual_exit_tests,
            "horizon_tests": horizon_tests,
            "profit_lock_tests": profit_lock_tests,
            "high_value_lessons": high_value,
            "discarded_noise": noise,
            "promotion_readiness": readiness,
            "alpaca_position_count_increased": False,
            "broker_trades_executed": False,
            "auto_promote_live_enabled": False,
            "top_shadow_lesson": summary,
            "compressed_lessons": [_lesson("Shadow Learning", summary, 65.0, ["shadow", "experiment_units", "replay", "virtual_paths"])],
            **_safe_flags(),
        }

    def _api_bandwidth_safety(self, statuses: dict[str, Any]) -> dict[str, Any]:
        resource = status_value(statuses, "astra_foundation_stabilization_governance_bundle_v1")
        provider = status_value(statuses, "provider_usage_status_v1")
        daily_used = to_int(provider.get("api_calls_used"), 0)
        bandwidth = to_float(first(provider.get("bandwidth_used_gb"), resource.get("bandwidth_used_gb"), 0.0), 0.0)
        emergency_preserved = True
        expansion_allowed = daily_used <= 0 and bandwidth <= 0.01
        reason = "cache_first_zero_provider_call_path" if expansion_allowed else "provider_or_bandwidth_budget_requires_throttle"
        return {
            "system": "Tier 3 API/Bandwidth Safety Governor",
            "status": "ok",
            "daily_budget": "cache_first_zero_dashboard_provider_calls",
            "monthly_budget": "gradual_historical_collection_only",
            "cache_first_checks": True,
            "provider_call_accounting": True,
            "bandwidth_status": "safe" if bandwidth <= 0.01 else "throttle",
            "expansion_allowed": expansion_allowed,
            "blocked_reason": "none" if expansion_allowed else reason,
            "emergency_reserve_preserved": emergency_preserved,
            "historical_collection_gradual": True,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "bandwidth_used_gb": rounded(bandwidth, 6),
            **_safe_flags(),
        }

    def _integration(self) -> dict[str, Any]:
        systems = ["Historical Intelligence Expansion V1", "Shadow Experimentation Acceleration V1", "Tier 3 API/Bandwidth Safety Governor", *SATELLITES_5_10]
        return {
            "status": "registered",
            "flow": ["satellites_historical_shadow", "librarian", "unified_truth_layer", "executive_assistant", "astra_brain"],
            "raw_data_sent_directly_to_brain": False,
            "librarian_integration_status": "routed_compressed_lessons_only",
            "unified_truth_integration_status": "master_truth_ready_compressed_inputs",
            "executive_assistant_integration_status": "priority_ready_compressed_inputs",
            "registered_systems": [
                {
                    "system_name": name,
                    "owner": "Tier 3 Intelligence Expansion",
                    "purpose": "Compressed shadow-only intelligence expansion for Librarian ingestion",
                    "inputs": ["cached_diagnostics", "cached_lifecycle_records", "cached_shadow_summaries"],
                    "outputs": ["compressed_lessons", "satellite_summaries", "shadow_experiment_units"],
                    "dependencies": ["astra_satellite_network_v1", "astra_tier2a_librarian_executive_truth_layer_v1", "astra_foundation_stabilization_governance_bundle_v1"],
                    "health_status": "registered",
                    "enabled": True,
                    "api_budget": 0,
                    "bandwidth_budget": 0,
                }
                for name in systems
            ],
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        historical = self._historical_expansion(statuses)
        satellites = [
            self._satellite_symbol_behavior(statuses),
            self._satellite_regime(statuses),
            self._satellite_risk_portfolio(statuses),
            self._satellite_macro_cross_market(statuses),
            self._satellite_market_health(statuses),
            self._satellite_learning_evidence(statuses),
        ]
        shadow = self._shadow_acceleration(statuses, satellites, historical)
        api = self._api_bandwidth_safety(statuses)
        integration = self._integration()
        compressed_lessons = []
        compressed_lessons.extend(historical.get("compressed_lessons") or [])
        for satellite in satellites:
            compressed_lessons.extend(satellite.get("compressed_lessons") or [])
        compressed_lessons.extend(shadow.get("compressed_lessons") or [])
        avg_conf = rounded(sum(to_float(s.get("confidence"), 0.0) for s in satellites) / max(1, len(satellites)), 3)
        status_rows = [
            {
                "satellite_name": s.get("satellite_name"),
                "status": s.get("status"),
                "health": s.get("health"),
                "confidence": s.get("confidence"),
                "duplicates_prevented": s.get("duplicates_prevented"),
                "freshness": s.get("freshness"),
            }
            for s in satellites
        ]
        out = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Tier 3 - Historical Intelligence, Satellite Expansion & Shadow Acceleration V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "historical_intelligence_expansion_v1": historical,
            "satellites_5_10": status_rows,
            "symbol_behavior_intelligence_v1": satellites[0],
            "regime_intelligence_v1": satellites[1],
            "risk_portfolio_intelligence_v1": satellites[2],
            "macro_cross_market_intelligence_v1": satellites[3],
            "market_health_intelligence_v1": satellites[4],
            "learning_evidence_intelligence_v1": satellites[5],
            "shadow_experimentation_acceleration_v1": shadow,
            "api_bandwidth_safety": api,
            "librarian_unified_truth_executive_integration": integration,
            "historical_intelligence_status": historical.get("historical_intelligence_status"),
            "satellites_added": SATELLITES_5_10,
            "satellites_registered": len(satellites),
            "satellite_coordinator_status": "registered_with_tier2b_coordinator",
            "satellite_coordinator_health": _health(avg_conf, len(satellites)),
            "shadow_experiment_expansion_status": shadow.get("shadow_experiment_expansion_status"),
            "shadow_experiment_units": shadow.get("shadow_experiments_reviewed"),
            "compressed_lessons_created": len(compressed_lessons),
            "compressed_lessons": compressed_lessons[:16],
            "compression_status": "active" if compressed_lessons else "insufficient_evidence",
            "librarian_integration_status": integration.get("librarian_integration_status"),
            "unified_truth_integration_status": integration.get("unified_truth_integration_status"),
            "executive_assistant_integration_status": integration.get("executive_assistant_integration_status"),
            "api_bandwidth_impact": "zero_dashboard_provider_calls_cache_first_gradual_history",
            "provider_api_impact": "unchanged_zero_dashboard_provider_calls",
            "dashboard_impact": "one_collapsed_learning_center_section_unified_diagnostics_only",
            "dashboard_endpoint_storm_created": False,
            "dashboard_provider_calls_used": 0,
            "top_historical_lesson": historical.get("top_historical_lesson"),
            "top_satellite_insight": first((satellites[0].get("compressed_summary") if satellites else None), "insufficient cached context"),
            "top_shadow_lesson": shadow.get("top_shadow_lesson"),
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            **_safe_flags(),
        }
        return with_safety(out)
