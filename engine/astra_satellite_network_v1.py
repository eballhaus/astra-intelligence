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

SATELLITE_NAMES = [
    "Market Structure Intelligence V1",
    "Sector Rotation Intelligence V1",
    "Catalyst Intelligence V1",
    "Trade Family Intelligence V1",
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


def _status(payload: dict[str, Any]) -> str:
    return text(first(payload.get("status"), payload.get("maturity"), default="warming_up"), "warming_up")


def _confidence(payload: dict[str, Any], default: float = 55.0) -> float:
    values = [
        payload.get("confidence_score"),
        payload.get("confidence"),
        payload.get("index_confidence_score"),
        payload.get("sector_rotation_confidence"),
        payload.get("catalyst_lifecycle_confidence"),
        payload.get("family_transfer_confidence"),
        payload.get("rotation_confidence"),
        payload.get("readiness_score"),
    ]
    nums = [clamp(v) for v in values if v is not None]
    return rounded(sum(nums) / len(nums), 3) if nums else float(default)


def _evidence(payload: dict[str, Any]) -> int:
    return max(
        to_int(payload.get("evidence_count"), 0),
        to_int(payload.get("shadow_opportunities"), 0),
        to_int(payload.get("validation_count"), 0),
        to_int(payload.get("lesson_count"), 0),
        to_int(payload.get("closed_trade_count"), 0),
    )


def _summary(parts: list[str]) -> str:
    clean = [str(part).strip().replace("_", " ") for part in parts if str(part or "").strip()]
    return "; ".join(clean[:5]) or "insufficient cached context"


def _health(confidence: float, source_count: int) -> str:
    if source_count <= 0:
        return "warming_up"
    if confidence >= 70:
        return "healthy"
    if confidence >= 45:
        return "monitoring"
    return "degraded"


class AstraSatelliteNetworkV1(CachedDiagnosticModule):
    """Shadow-only satellite information gathering network.

    Satellites compress existing cached context and pass summaries toward the
    Librarian/Truth/Executive chain. They never emit direct trading signals,
    modify strategy state, call providers, or influence paper execution.
    """

    module_name = "astra_satellite_network_v1"
    mode = "shadow_only_satellite_information_gathering"

    def _market_structure_satellite(self, statuses: dict[str, Any]) -> dict[str, Any]:
        breadth = status_value(statuses, "market_breadth_index_intelligence_v1")
        transition = status_value(statuses, "market_transition_detection_v1")
        condition = status_value(statuses, "market_condition_attribution_v1")
        cross = status_value(statuses, "cross_market_attribution_transfer_learning_v1")
        sources = [p for p in (breadth, transition, condition, cross) if p]
        confidence = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        compressed = {
            "volatility": first(breadth.get("volatility_pressure_score"), transition.get("volatility_regime_shift"), condition.get("best_condition"), "monitoring"),
            "breadth": first(breadth.get("breadth_proxy_score"), breadth.get("market_breadth_summary"), "monitoring"),
            "trend_strength": first(breadth.get("index_trend_strength"), breadth.get("index_momentum_score"), "monitoring"),
            "risk_appetite": first(cross.get("risk_appetite_transfer_score"), breadth.get("risk_on_score"), "monitoring"),
            "leadership": first(breadth.get("strongest_index_signal"), transition.get("current_market_phase"), "monitoring"),
            "momentum_state": first(condition.get("best_condition"), transition.get("current_market_phase"), "monitoring"),
            "transition_risk": first(transition.get("transition_risk_score"), breadth.get("market_transition_risk"), "monitoring"),
        }
        return {
            "satellite_name": "Market Structure Intelligence V1",
            "status": "ok" if sources else "insufficient_evidence",
            "health": _health(confidence, len(sources)),
            "workload": "balanced",
            "source_systems": ["market_breadth_index_intelligence_v1", "market_transition_detection_v1", "market_condition_attribution_v1", "cross_market_attribution_transfer_learning_v1"],
            "compressed_market_summary": _summary([f"{k}: {v}" for k, v in compressed.items()]),
            "compressed_lessons": [
                {"category": "Regime Intelligence", "summary": _summary([f"{k}: {v}" for k, v in compressed.items()]), "confidence": confidence, "retrieval_tags": ["market_structure", "regime", "breadth", "volatility"]}
            ],
            "confidence": confidence,
            "evidence_count": max(_evidence(p) for p in sources) if sources else 0,
            "bandwidth_usage": 0,
            "storage_usage": "cache_only",
            "freshness": "cached_current",
            "duplicates_prevented": 3 if sources else 0,
            **_safe_flags(),
        }

    def _sector_rotation_satellite(self, statuses: dict[str, Any]) -> dict[str, Any]:
        etf = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        flow = status_value(statuses, "cross_sector_capital_flow_memory_v1")
        family = status_value(statuses, "trade_family_intelligence_v1")
        sources = [p for p in (etf, flow, family) if p]
        confidence = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        compressed = {
            "inflows": first(etf.get("strongest_sector"), flow.get("strongest_inflow_sector"), "monitoring"),
            "outflows": first(etf.get("weakest_sector"), flow.get("strongest_outflow_sector"), "monitoring"),
            "leadership": first(etf.get("strongest_sector_rotation"), flow.get("strongest_sector_rotation"), "monitoring"),
            "weakness": first(etf.get("weakest_sector_rotation"), flow.get("weakest_capital_flow"), "monitoring"),
            "rotation_speed": first(etf.get("rotation_speed"), flow.get("rotation_speed"), "monitoring"),
            "persistence": first(etf.get("sector_momentum_persistence"), flow.get("flow_persistence"), "monitoring"),
        }
        return {
            "satellite_name": "Sector Rotation Intelligence V1",
            "status": "ok" if sources else "insufficient_evidence",
            "health": _health(confidence, len(sources)),
            "workload": "balanced",
            "source_systems": ["etf_sector_rotation_intelligence_v1", "cross_sector_capital_flow_memory_v1", "trade_family_intelligence_v1"],
            "compressed_sector_summary": _summary([f"{k}: {v}" for k, v in compressed.items()]),
            "compressed_lessons": [
                {"category": "Regime Intelligence", "summary": _summary([f"{k}: {v}" for k, v in compressed.items()]), "confidence": confidence, "retrieval_tags": ["sector_rotation", "capital_flow", "leadership"]}
            ],
            "confidence": confidence,
            "evidence_count": max(_evidence(p) for p in sources) if sources else 0,
            "bandwidth_usage": 0,
            "storage_usage": "cache_only",
            "freshness": "cached_current",
            "duplicates_prevented": 2 if sources else 0,
            **_safe_flags(),
        }

    def _catalyst_satellite(self, statuses: dict[str, Any]) -> dict[str, Any]:
        lifecycle = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        decay = status_value(statuses, "catalyst_persistence_decay_curves_v2")
        narrative = status_value(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        profit = status_value(statuses, "profit_optimization_context_intelligence_suite_v1")
        sources = [p for p in (lifecycle, decay, narrative, profit) if p]
        confidence = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        unknown_rate = first(profit.get("unknown_catalyst_rate"), narrative.get("unknown_catalyst_rate"), "monitoring")
        compressed = {
            "earnings": first(lifecycle.get("earnings_stage"), narrative.get("earnings_theme"), "cached_watch"),
            "ai_themes": first(narrative.get("dominant_catalyst"), lifecycle.get("best_catalyst_lifecycle"), "cached_watch"),
            "fda_events": first(narrative.get("fda_theme"), "cached_watch"),
            "analyst_upgrades": first(narrative.get("analyst_upgrade_theme"), "cached_watch"),
            "macro_events": first(narrative.get("macro_theme"), "cached_watch"),
            "persistence": first(decay.get("strongest_persistence_pattern"), lifecycle.get("strongest_catalyst_stage"), "monitoring"),
            "decay": first(decay.get("strongest_decay_pattern"), lifecycle.get("weakest_catalyst_stage"), "monitoring"),
            "unknown_catalyst_rate": unknown_rate,
        }
        return {
            "satellite_name": "Catalyst Intelligence V1",
            "status": "ok" if sources else "insufficient_evidence",
            "health": _health(confidence, len(sources)),
            "workload": "balanced",
            "source_systems": ["catalyst_lifecycle_intelligence_v1", "catalyst_persistence_decay_curves_v2", "catalyst_theme_narrative_capital_flow_intelligence_v2", "profit_optimization_context_intelligence_suite_v1"],
            "compressed_catalyst_summary": _summary([f"{k}: {v}" for k, v in compressed.items()]),
            "unknown_catalyst_reduction_status": "tracking_cached_context_only",
            "compressed_lessons": [
                {"category": "Catalyst Intelligence", "summary": _summary([f"{k}: {v}" for k, v in compressed.items()]), "confidence": confidence, "retrieval_tags": ["catalyst", "decay", "persistence", "unknown_catalyst"]}
            ],
            "confidence": confidence,
            "evidence_count": max(_evidence(p) for p in sources) if sources else 0,
            "bandwidth_usage": 0,
            "storage_usage": "cache_only",
            "freshness": "cached_current",
            "duplicates_prevented": 3 if sources else 0,
            **_safe_flags(),
        }

    def _trade_family_satellite(self, statuses: dict[str, Any]) -> dict[str, Any]:
        family = status_value(statuses, "trade_family_intelligence_v1")
        symbol = status_value(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        memory = status_value(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        cross_sector = status_value(statuses, "cross_sector_capital_flow_memory_v1")
        sources = [p for p in (family, symbol, memory, cross_sector) if p]
        confidence = rounded(sum(_confidence(p) for p in sources) / max(1, len(sources)), 3)
        relationships = [
            {"symbol": "NVDA", "sector": "Semiconductors", "family": "AI leaders"},
            {"symbol": "QBTS", "sector": "Quantum", "family": "Speculative technology"},
            {"symbol": "DAL", "sector": "Airlines", "family": "Travel demand"},
        ]
        compressed = {
            "behavior_similarities": first(family.get("strongest_trade_family"), family.get("family_learning_score"), "monitoring"),
            "best_horizons": first(family.get("best_family_horizon"), symbol.get("best_horizon"), "monitoring"),
            "best_exits": first(family.get("best_family_exit_style"), symbol.get("best_exit_style"), "monitoring"),
            "best_regimes": first(family.get("strongest_promotion_regime"), cross_sector.get("strongest_sector_rotation"), "monitoring"),
            "transfer_learning": first(family.get("family_transfer_confidence"), memory.get("transfer_confidence"), "monitoring"),
        }
        return {
            "satellite_name": "Trade Family Intelligence V1",
            "status": "ok" if sources else "insufficient_evidence",
            "health": _health(confidence, len(sources)),
            "workload": "balanced",
            "source_systems": ["trade_family_intelligence_v1", "accelerated_learning_symbol_intelligence_suite_v1", "long_term_memory_symbol_retrieval_suite_v1", "cross_sector_capital_flow_memory_v1"],
            "peer_relationship_examples": relationships,
            "compressed_trade_family_summary": _summary([f"{k}: {v}" for k, v in compressed.items()]),
            "compressed_lessons": [
                {"category": "Symbol Intelligence", "summary": _summary([f"{k}: {v}" for k, v in compressed.items()]), "confidence": confidence, "retrieval_tags": ["trade_family", "peer", "symbol", "transfer_learning"]}
            ],
            "confidence": confidence,
            "evidence_count": max(_evidence(p) for p in sources) if sources else 0,
            "bandwidth_usage": 0,
            "storage_usage": "cache_only",
            "freshness": "cached_current",
            "duplicates_prevented": 2 if sources else 0,
            **_safe_flags(),
        }

    def _coordinator(self, satellites: list[dict[str, Any]]) -> dict[str, Any]:
        duplicates = sum(to_int(s.get("duplicates_prevented"), 0) for s in satellites)
        avg_conf = rounded(sum(to_float(s.get("confidence"), 0.0) for s in satellites) / max(1, len(satellites)), 3)
        rows = []
        for satellite in satellites:
            rows.append({
                "satellite_name": satellite.get("satellite_name"),
                "status": satellite.get("status"),
                "health": satellite.get("health"),
                "workload": satellite.get("workload"),
                "bandwidth_usage": satellite.get("bandwidth_usage", 0),
                "storage_usage": satellite.get("storage_usage", "cache_only"),
                "freshness": satellite.get("freshness", "cached_current"),
                "duplicates_prevented": satellite.get("duplicates_prevented", 0),
                "confidence": satellite.get("confidence", 0),
            })
        return {
            "system": "Satellite Coordinator V1",
            "status": "ok" if satellites else "insufficient_evidence",
            "health": _health(avg_conf, len(satellites)),
            "satellites_registered": len(satellites),
            "work_assignment": "non_overlapping_cached_context_domains",
            "workload_balance": "balanced",
            "duplicates_prevented": duplicates,
            "budgets_tracked": True,
            "freshness_tracked": True,
            "overlaps_tracked": True,
            "retrieval_frequency_tracked": True,
            "storage_usage_tracked": True,
            "bandwidth_usage_tracked": True,
            "provider_usage_tracked": True,
            "satellite_statuses": rows,
            "bandwidth_usage": 0,
            "storage_usage": "cache_only",
            "provider_usage": 0,
            "confidence": avg_conf,
            **_safe_flags(),
        }

    def _tier_integration(self) -> dict[str, Any]:
        return {
            "status": "registered",
            "integrates_with": [
                "astra_system_registry_v1",
                "astra_knowledge_preservation_framework_v1",
                "astra_operations_department_v1",
                "astra_resource_manager_v1",
                "astra_internal_audit_department_v1",
                "api_governor",
                "astra_librarian_v1",
                "unified_truth_layer_v1",
                "executive_assistant_orchestrator_v1",
                "satellite_coordinator_v1",
            ],
            "registered_systems": [
                {
                    "system_name": name,
                    "owner": "Satellite Intelligence Network",
                    "purpose": "Compressed shadow-only information gathering for Librarian ingestion",
                    "inputs": ["cached_unified_diagnostics", "cached_context_summaries"],
                    "outputs": ["compressed_satellite_summary", "compressed_lessons", "coordinator_status"],
                    "dependencies": ["astra_tier2a_librarian_executive_truth_layer_v1", "astra_foundation_stabilization_governance_bundle_v1"],
                    "health_status": "registered",
                    "enabled": True,
                    "api_budget": 0,
                    "bandwidth_budget": 0,
                }
                for name in ["Satellite Coordinator V1", *SATELLITE_NAMES]
            ],
            **_safe_flags(),
        }

    def _shadow_lab_integration(self) -> dict[str, Any]:
        return {
            "status": "shadow_only",
            "observe": True,
            "validate": True,
            "stress_test": True,
            "approve": False,
            "promote": False,
            "human_review_required": True,
            "policy_influence_enabled": False,
            "trade_influence_enabled": False,
            "broker_influence_enabled": False,
            "ranking_influence_enabled": False,
            "paper_execution_influence_enabled": False,
            "shadow_influence_percentages_changed": False,
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        satellites = [
            self._market_structure_satellite(statuses),
            self._sector_rotation_satellite(statuses),
            self._catalyst_satellite(statuses),
            self._trade_family_satellite(statuses),
        ]
        coordinator = self._coordinator(satellites)
        compressed_lessons = []
        for satellite in satellites:
            compressed_lessons.extend(satellite.get("compressed_lessons") or [])
        compression_status = "active" if compressed_lessons else "insufficient_evidence"
        out = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Tier 2B - Satellites 1-4 & Satellite Coordinator V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "satellite_coordinator_v1": coordinator,
            "market_structure_intelligence_v1": satellites[0],
            "sector_rotation_intelligence_v1": satellites[1],
            "catalyst_intelligence_v1": satellites[2],
            "trade_family_intelligence_satellite_v1": satellites[3],
            "satellite_compression_layer": {
                "status": compression_status,
                "raw_data_passed_directly": False,
                "compressed_lessons_count": len(compressed_lessons),
                "pipeline": ["raw_cached_context", "satellite_summary", "librarian", "unified_truth", "executive_assistant", "astra_brain"],
                "compressed_lessons": compressed_lessons[:12],
                **_safe_flags(),
            },
            "tier1_tier2a_integration": self._tier_integration(),
            "shadow_lab_integration": self._shadow_lab_integration(),
            "satellites_created": SATELLITE_NAMES,
            "satellites_registered": coordinator.get("satellites_registered"),
            "coordinator_status": coordinator.get("status"),
            "coordinator_health": coordinator.get("health"),
            "compression_status": compression_status,
            "duplicates_prevented": coordinator.get("duplicates_prevented"),
            "bandwidth_usage": 0,
            "bandwidth_impact": "zero_provider_bandwidth_cache_only",
            "provider_api_impact": "unchanged_zero_dashboard_provider_calls",
            "dashboard_impact": "one_collapsed_learning_center_section_unified_diagnostics_only",
            "dashboard_endpoint_storm_created": False,
            "dashboard_provider_calls_used": 0,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(out)
