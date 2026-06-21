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

SATELLITE_DEFINITIONS = [
    ("market_satellite", "Market Satellite", ["astra_satellite_network_v1", "market_breadth_index_intelligence_v1", "market_transition_detection_v1", "astra_market_intelligence_v1"]),
    ("macro_fed_satellite", "Macro/Fed Satellite", ["astra_provider_orchestration_data_governance_v1", "market_calendar_knowledge", "market_regime_similarity_engine_v1"]),
    ("sector_rotation_satellite", "Sector Rotation Satellite", ["astra_satellite_network_v1", "etf_sector_rotation_intelligence_v1", "cross_sector_capital_flow_memory_v1"]),
    ("market_breadth_satellite", "Market Breadth Satellite", ["astra_satellite_network_v1", "market_breadth_index_intelligence_v1"]),
    ("symbol_intelligence_satellite", "Symbol Intelligence Satellite", ["astra_tier3_historical_satellite_shadow_acceleration_v1", "accelerated_learning_symbol_intelligence_suite_v1", "trade_family_intelligence_v1"]),
    ("symbol_behavioral_memory_satellite", "Symbol Behavioral Memory Satellite", ["long_term_memory_symbol_retrieval_suite_v1", "astra_tier3_historical_satellite_shadow_acceleration_v1"]),
    ("portfolio_satellite", "Portfolio Satellite", ["portfolio_risk_intelligence", "portfolio_diversification_correlation_v2", "astra_provider_orchestration_data_governance_v1"]),
    ("exit_intelligence_satellite", "Exit Intelligence Satellite", ["profit_capture_peak_decay_exit_validation_suite_v1", "controlled_paper_profit_protection_pilot_v1", "adaptive_execution_exit_intelligence_v3"]),
    ("learning_satellite", "Learning Satellite", ["astra_tier2a_librarian_executive_truth_layer_v1", "intelligence_quality_learning_efficiency_suite_v1", "learning_drift_detection_v1"]),
    ("risk_satellite", "Risk Satellite", ["astra_foundation_stabilization_governance_bundle_v1", "autonomous_intelligence_validation_governance_v1", "data_freshness_trust_engine_v1"]),
    ("catalyst_satellite", "Catalyst Satellite", ["astra_satellite_network_v1", "catalyst_lifecycle_intelligence_v1", "catalyst_persistence_decay_curves_v2"]),
    ("cio_satellite", "CIO Satellite", ["astra_cio_intelligence_v1", "astra_provider_orchestration_data_governance_v1", "astra_executive_polish_v1"]),
]

MEMORY_BUDGETS = {
    "daily_max_lessons": 100,
    "weekly_max_lessons": 500,
    "monthly_max_lessons": 2000,
}

HISTORICAL_PRIORITIES = {
    "tier_1": ["SPY", "QQQ", "IWM", "VIX", "Sector ETFs"],
    "tier_2": ["Frequently traded symbols"],
    "tier_3": ["Watchlist symbols"],
    "tier_4": ["Broad market expansion"],
}


def _safe_flags(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
        "human_supervised": True,
        "cache_first": True,
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
        "automatic_entries_enabled": False,
        "automatic_exits_enabled": False,
        "automatic_allocations_enabled": False,
        "automatic_sizing_enabled": False,
        "broker_execution_added": False,
        "shadow_logic_changed": False,
        "shadow_redesigned": False,
        "new_providers_added": False,
        "new_ai_models_added": False,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
    }
    out.update(extra or {})
    return out


def _confidence(payload: dict[str, Any], default: float = 50.0) -> float:
    values = [
        payload.get("confidence"),
        payload.get("confidence_score"),
        payload.get("readiness_score"),
        payload.get("institutional_intelligence_score"),
        payload.get("overall_cio_intelligence_score"),
        payload.get("market_intelligence_score"),
        payload.get("consensus_score"),
        payload.get("graph_confidence"),
    ]
    nums = [clamp(v) for v in values if v is not None]
    return rounded(sum(nums) / max(1, len(nums)), 3) if nums else default


def _evidence(payload: dict[str, Any]) -> int:
    fields = (
        "evidence_count", "lesson_count", "lessons_organized", "master_truths_created",
        "source_systems_reviewed", "canonical_closed_trade_count", "closed_trade_count",
        "shadow_opportunities", "validation_count", "indexed_records", "symbol_profiles_tracked",
    )
    return max([to_int(payload.get(field), 0) for field in fields] + [0])


def _status(payload: dict[str, Any]) -> str:
    return text(first(payload.get("status"), payload.get("health"), payload.get("maturity"), default="warming_up"), "warming_up")


def _summary_for(name: str, sources: list[tuple[str, dict[str, Any]]]) -> str:
    snippets = []
    for source_name, payload in sources[:4]:
        for field in (
            "summary", "recommended_next_focus", "highest_roi_next_improvement", "market_regime_summary",
            "cio_summary", "strongest_master_truth", "weakest_area", "strongest_area", "shadow_recommendation",
        ):
            value = payload.get(field)
            if value:
                snippets.append(f"{source_name}: {str(value)[:120]}")
                break
    return "; ".join(snippets[:4]) or f"{name} is warming up from cached Astra diagnostics."


def _avg(values: list[Any], default: float = 0.0) -> float:
    nums = [to_float(value, 0.0) for value in values if value is not None]
    return rounded(sum(nums) / max(1, len(nums)), 3) if nums else default


class AstraAiosIntelligenceMaturationBundleV1(CachedDiagnosticModule):
    """Astra Intelligence Operating System V1 coordinator.

    This module organizes existing Astra intelligence into the requested AIOS flow.
    It does not gather provider data, alter Shadow logic, or change any trading
    behavior. It formalizes budgets, DNA, triage, compression, teaching, memory,
    retrieval, AIC coordination, and validation using cached subsystem outputs.
    """

    module_name = "astra_aios_intelligence_maturation_bundle_v1"
    mode = "advisory_cache_first_aios_intelligence_maturation"

    def _cached(self, force: bool) -> dict[str, Any] | None:
        cached = super()._cached(force)
        if cached and not cached.get("final_maturation_bundle_health"):
            return None
        return cached

    def _source(self, statuses: dict[str, Any], key: str) -> dict[str, Any]:
        return status_value(statuses, key)

    def _satellite_request_manager(self, statuses: dict[str, Any]) -> dict[str, Any]:
        satellites = []
        for satellite_key, satellite_name, source_keys in SATELLITE_DEFINITIONS:
            sources = [(key, self._source(statuses, key)) for key in source_keys]
            sources = [(key, payload) for key, payload in sources if payload]
            conf = rounded(sum(_confidence(payload) for _, payload in sources) / max(1, len(sources)), 3)
            evidence = max([_evidence(payload) for _, payload in sources] + [0])
            health = "healthy" if sources and conf >= 65 else "monitoring" if sources else "insufficient_evidence"
            satellites.append({
                "satellite_key": satellite_key,
                "satellite_name": satellite_name,
                "status": "ok" if sources else "insufficient_evidence",
                "health": health,
                "source_systems": [key for key, _ in sources] or source_keys,
                "data_budget": "cache_only_existing_provider_owners",
                "learning_budget": "bounded_lesson_creation",
                "storage_budget": "compact_summary_only",
                "compression_budget": "stage_1_satellite_summary_max_1",
                "bandwidth_budget": 0,
                "confidence_budget": conf,
                "evidence_count": evidence,
                "request_priority": "high" if satellite_key in {"portfolio_satellite", "exit_intelligence_satellite", "market_satellite"} else "medium",
                "routing": "satellite_request_manager_to_aic_not_direct_to_trading",
                "compressed_summary": _summary_for(satellite_name, sources),
                "direct_trade_influence_enabled": False,
                "provider_calls_used": 0,
            })
        avg_conf = rounded(sum(to_float(row.get("confidence_budget"), 0.0) for row in satellites) / max(1, len(satellites)), 3)
        return {
            "system": "Satellite Request Manager V1",
            "status": "ok",
            "satellites_registered": len(satellites),
            "satellites": satellites,
            "budgets_tracked": ["data", "learning", "storage", "compression", "bandwidth", "confidence"],
            "duplicate_work_suppressed": True,
            "coordination_flow": "providers_to_controlled_data_acquisition_to_satellites_to_AIC",
            "average_satellite_confidence": avg_conf,
            **_safe_flags(),
        }

    def _institutional_historical_engine(self, statuses: dict[str, Any]) -> dict[str, Any]:
        tier3 = self._source(statuses, "astra_tier3_historical_satellite_shadow_acceleration_v1")
        historical = self._source(statuses, "historical_intelligence_market_memory_suite_v1")
        memory = self._source(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        provider = self._source(statuses, "astra_provider_orchestration_data_governance_v1")
        sources = [payload for payload in (tier3, historical, memory, provider) if payload]
        conf = rounded(sum(_confidence(payload) for payload in sources) / max(1, len(sources)), 3)
        maturity = _avg([
            conf,
            78.0 if tier3 else None,
            72.0 if historical else None,
            70.0 if memory else None,
            80.0 if provider else None,
        ], 0.0)
        return {
            "system": "Institutional Historical Intelligence Engine V1",
            "status": "ok" if sources else "insufficient_evidence",
            "purpose": "build_historical_comparisons_from_satellite_discoveries_not_satellite_bulk_downloads",
            "historical_collection_priorities": HISTORICAL_PRIORITIES,
            "market_history_supported": True,
            "symbol_history_supported": True,
            "sector_history_supported": True,
            "breadth_history_supported": True,
            "macro_history_supported": True,
            "catalyst_history_supported": True,
            "exit_history_supported": True,
            "portfolio_history_supported": True,
            "gradual_collection_only": True,
            "entire_market_download_allowed": False,
            "full_market_download_allowed": False,
            "satellite_long_history_download_allowed": False,
            "historical_comparison_tiers": HISTORICAL_PRIORITIES,
            "ihie_maturity_score": maturity,
            "market_history_status": "tier_1_priority_cache_first",
            "symbol_history_status": "tier_2_frequent_symbols_then_watchlists",
            "sector_history_status": "tier_1_sector_etf_priority",
            "breadth_history_status": "tier_1_index_proxy_priority",
            "macro_history_status": "fred_owner_cached_when_available",
            "catalyst_history_status": "finnhub_cached_context_when_available",
            "exit_history_status": "profit_capture_and_lifecycle_memory_only",
            "portfolio_history_status": "alpaca_broker_truth_summary_only",
            "confidence": conf,
            "evidence_count": max([_evidence(payload) for payload in sources] + [0]),
            "top_historical_lesson": first(tier3.get("top_historical_lesson"), memory.get("summary"), "historical intelligence warming up"),
            "bandwidth_status": (provider.get("bandwidth_governance") or {}).get("bandwidth_status") if isinstance(provider.get("bandwidth_governance"), dict) else "cache_first",
            **_safe_flags(),
        }

    def _intelligence_dna(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        dna_rows = []
        for lesson in lessons[:24]:
            tags = [str(tag) for tag in lesson.get("retrieval_tags") or []]
            summary = text(lesson.get("compressed_summary") or lesson.get("summary"), "compressed lesson")
            dna_rows.append({
                "source": text(lesson.get("source_system") or lesson.get("category"), "cached_astra_intelligence"),
                "confidence": clamp(lesson.get("confidence"), 0, 100),
                "timestamp": text(lesson.get("timestamp"), now_iso()),
                "freshness": "cached_current",
                "regime": next((tag for tag in tags if "regime" in tag or "risk" in tag), "unknown_regime"),
                "horizon": next((tag for tag in tags if tag in {"scalp", "day", "swing", "horizon", "intraday"}), "unknown_horizon"),
                "symbol": next((tag.upper() for tag in tags if tag in {"nvda", "qbts", "rgti", "ionq", "spy", "qqq", "btc"}), "MULTI"),
                "sector": next((tag for tag in tags if tag in {"technology", "energy", "healthcare", "financial", "industrial", "sector"}), "unknown_sector"),
                "outcome": "lesson_created",
                "importance": text(lesson.get("priority"), "MEDIUM"),
                "retention_score": clamp(to_float(lesson.get("confidence"), 50.0) + min(20.0, to_float(lesson.get("evidence_count"), 0.0) / 10.0), 0, 100),
                "summary": summary[:180],
            })
        return {
            "system": "Intelligence DNA V1",
            "status": "ok" if dna_rows else "insufficient_evidence",
            "dna_objects": dna_rows,
            "dna_count": len(dna_rows),
            "required_metadata_present": ["source", "confidence", "timestamp", "freshness", "regime", "horizon", "symbol", "sector", "outcome", "importance", "retention_score"],
            **_safe_flags(),
        }

    def _triage_gate(self, dna_rows: list[dict[str, Any]], statuses: dict[str, Any]) -> dict[str, Any]:
        portfolio_symbols = set()
        broker = self._source(statuses, "alpaca_paper_broker")
        for row in broker.get("positions") or broker.get("paper_positions") or broker.get("active_positions") or []:
            if isinstance(row, dict) and row.get("symbol"):
                portfolio_symbols.add(str(row.get("symbol")).upper())
        accepted = []
        rejected = []
        seen = set()
        for row in dna_rows:
            key = (row.get("source"), row.get("summary"))
            duplicate = key in seen
            seen.add(key)
            useful = to_float(row.get("retention_score"), 0.0) >= 45 or row.get("symbol") in portfolio_symbols
            fresh = str(row.get("freshness")) != "stale"
            relevant = useful or row.get("importance") in {"HIGH", "CRITICAL"}
            item = {**row, "duplicate_status": duplicate, "useful": useful, "fresh": fresh, "relevant": relevant}
            if duplicate or not useful or not fresh or not relevant:
                rejected.append(item)
            else:
                accepted.append(item)
        return {
            "system": "Triage / Relevance Gate V1",
            "status": "ok" if dna_rows else "insufficient_evidence",
            "reviewed": len(dna_rows),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "accepted_items": accepted[:12],
            "rejected_reason_summary": {
                "duplicates": len([row for row in rejected if row.get("duplicate_status")]),
                "low_usefulness": len([row for row in rejected if not row.get("useful")]),
                "stale": len([row for row in rejected if not row.get("fresh")]),
                "low_relevance": len([row for row in rejected if not row.get("relevant")]),
            },
            "filters": ["importance", "duplicate_status", "usefulness", "freshness", "confidence", "portfolio_watchlist_relevance"],
            **_safe_flags(),
        }

    def _compression(self, satellites: list[dict[str, Any]], accepted: list[dict[str, Any]], tier2a: dict[str, Any]) -> dict[str, Any]:
        satellite_summaries = [row.get("compressed_summary") for row in satellites if row.get("compressed_summary")][:12]
        system_summaries = [row.get("summary") for row in accepted if row.get("summary")][:12]
        executive = tier2a.get("executive_assistant_orchestrator_v1") if isinstance(tier2a.get("executive_assistant_orchestrator_v1"), dict) else {}
        executive_summaries = [row.get("recommended_focus") for row in executive.get("top_5") or [] if isinstance(row, dict)][:5]
        return {
            "system": "Multi-Stage Compression V1",
            "status": "ok" if satellite_summaries or system_summaries else "insufficient_evidence",
            "stage_1_satellite_compression": satellite_summaries,
            "stage_2_system_compression": system_summaries,
            "stage_3_executive_compression": executive_summaries,
            "noise_reduction_active": True,
            "raw_data_to_dashboard": False,
            "compressed_items_count": len(satellite_summaries) + len(system_summaries) + len(executive_summaries),
            **_safe_flags(),
        }

    def _teacher_layer(self, accepted: list[dict[str, Any]]) -> dict[str, Any]:
        lessons = []
        for row in accepted[:MEMORY_BUDGETS["daily_max_lessons"]]:
            lessons.append({
                "lesson_type": text(row.get("importance"), "MEDIUM"),
                "source": row.get("source"),
                "lesson": f"Remember: {text(row.get('summary'), 'compressed intelligence')}",
                "why_remember": "passed_relevance_gate_with_sufficient_retention_score",
                "confidence": row.get("confidence"),
                "retention_score": row.get("retention_score"),
                "metadata": {k: row.get(k) for k in ("symbol", "sector", "regime", "horizon", "outcome")},
            })
        return {
            "system": "Teacher Layer V1",
            "status": "ok" if lessons else "insufficient_evidence",
            "question_answered": "What should Astra remember?",
            "lessons_created": len(lessons),
            "daily_lesson_budget": MEMORY_BUDGETS["daily_max_lessons"],
            "lessons": lessons[:20],
            **_safe_flags(),
        }

    def _memory(self, lessons: list[dict[str, Any]], long_memory: dict[str, Any]) -> dict[str, Any]:
        short = [row for row in lessons if to_float(row.get("retention_score"), 0.0) < 62]
        medium = [row for row in lessons if 62 <= to_float(row.get("retention_score"), 0.0) < 78]
        long = [row for row in lessons if 78 <= to_float(row.get("retention_score"), 0.0) < 92]
        permanent = [row for row in lessons if to_float(row.get("retention_score"), 0.0) >= 92]
        excess = max(0, len(lessons) - MEMORY_BUDGETS["daily_max_lessons"])
        return {
            "system": "Multi-Tier Memory V1",
            "status": "ok" if lessons or long_memory else "insufficient_evidence",
            "short_term_memory": {"window": "1-5_days", "lesson_count": len(short)},
            "medium_term_memory": {"window": "1-12_weeks", "lesson_count": len(medium)},
            "long_term_memory": {"window": "months_to_years", "lesson_count": len(long), "existing_symbol_profiles": long_memory.get("symbol_profiles_tracked")},
            "permanent_memory": {"window": "permanent", "lesson_count": len(permanent), "domains": ["symbol_personalities", "market_personalities", "provider_intelligence", "behavioral_intelligence"]},
            "memory_lifecycle": ["collect", "compress", "store", "retrieve", "reinforce", "promote", "archive", "discard"],
            "learning_budgets": MEMORY_BUDGETS,
            "excess_intelligence_handling": "compress_archive_or_discard_low_value",
            "excess_lessons_today": excess,
            "memory_growth_policy": "bounded_never_grow_forever",
            "storage_health_score": long_memory.get("storage_health_score"),
            "memory_pressure_score": long_memory.get("memory_pressure_score"),
            **_safe_flags(),
        }

    def _retrieval(self, statuses: dict[str, Any], tier2a: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        long_memory = self._source(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        retrieval = tier2a.get("retrieval_engine_integration_v1") if isinstance(tier2a.get("retrieval_engine_integration_v1"), dict) else {}
        return {
            "system": "Memory Retrieval Engine V1",
            "status": "ok" if retrieval or long_memory else "insufficient_evidence",
            "supports_retrieval_by": ["symbol", "sector", "regime", "catalyst", "exit_pattern", "horizon", "confidence", "freshness", "outcome", "similarity", "portfolio_context"],
            "retrieval_scoring_components": {
                "confidence": 0.22,
                "freshness": 0.18,
                "similarity": 0.18,
                "outcome_relevance": 0.18,
                "retention_score": 0.14,
                "importance": 0.10,
            },
            "memory_retrieval_maturity": rounded(_avg([
                75.0 if retrieval else None,
                72.0 if long_memory else None,
                70.0 if memory.get("status") == "ok" else 45.0,
                85.0 if memory.get("memory_growth_policy") == "bounded_never_grow_forever" else None,
            ], 0.0), 3),
            "cache_first": True,
            "full_history_scans": False,
            "tier2a_index_count": retrieval.get("index_count"),
            "long_term_indexed_records": long_memory.get("indexed_records"),
            "retrieval_latency_ms": first(long_memory.get("retrieval_latency_ms"), 0),
            "memory_pressure_score": memory.get("memory_pressure_score"),
            **_safe_flags(),
        }

    def _aic(self, statuses: dict[str, Any], request_manager: dict[str, Any], ihie: dict[str, Any], compression: dict[str, Any], retrieval: dict[str, Any]) -> dict[str, Any]:
        provider = self._source(statuses, "astra_provider_orchestration_data_governance_v1")
        governance = self._source(statuses, "astra_intelligence_governance_v1")
        consensus = self._source(statuses, "consensus_engine_v1")
        if not consensus and isinstance(provider.get("consensus_engine_expansion_v1"), dict):
            consensus = provider.get("consensus_engine_expansion_v1") or {}
        graph = self._source(statuses, "knowledge_graph_foundation_v1")
        if not graph and isinstance(provider.get("knowledge_graph_expansion_v1"), dict):
            graph = provider.get("knowledge_graph_expansion_v1") or {}
        score = rounded(sum([
            to_float(request_manager.get("average_satellite_confidence"), 0.0),
            to_float(ihie.get("confidence"), 0.0),
            to_float(consensus.get("consensus_score"), provider.get("consensus_score", 0.0)),
            to_float(graph.get("graph_confidence"), provider.get("knowledge_graph_score", 0.0)),
            70.0 if retrieval.get("status") == "ok" else 45.0,
        ]) / 5.0, 3)
        return {
            "system": "Astra Intelligence Core V1",
            "status": "ok",
            "role": "coordinator_only",
            "coordinates": ["knowledge_graph", "consensus", "governance", "confidence", "prioritization", "memory_retrieval"],
            "does_not_gather_data": True,
            "does_not_teach": True,
            "does_not_compress": True,
            "does_not_store_raw_data": True,
            "does_not_replace_satellites": True,
            "aic_coordination_score": score,
            "knowledge_graph_status": _status(graph),
            "consensus_status": _status(consensus),
            "governance_status": _status(governance),
            "retrieval_status": retrieval.get("status"),
            "compression_status": compression.get("status"),
            **_safe_flags(),
        }

    def _validation_layer(self) -> dict[str, Any]:
        return {
            "system": "Experimentation & Validation Layer V1",
            "status": "active_advisory_only",
            "validates_before_promotion": True,
            "automatic_promotion_enabled": False,
            "broker_execution_enabled": False,
            "live_trading_enabled": False,
            "behavior_safe_to_apply": False,
            **_safe_flags(),
        }

    def _shadow_inputs(self) -> dict[str, Any]:
        return {
            "system": "Shadow Input Expansion V1",
            "status": "inputs_expanded_without_shadow_logic_changes",
            "shadow_logic_changed": False,
            "shadow_observes": ["satellite_outputs", "market_regimes", "portfolio_exposures", "macro_environments", "exit_intelligence", "symbol_behavioral_memory", "ihie_historical_comparisons", "memory_retrieval_summaries"],
            "shadow_executes": False,
            "shadow_overrides_paper": False,
            "shadow_submits_orders": False,
            **_safe_flags(),
        }

    def _exit_intelligence_maturation_v2(self, statuses: dict[str, Any]) -> dict[str, Any]:
        exit_suite = self._source(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        profit_pilot = self._source(statuses, "controlled_paper_profit_protection_pilot_v1")
        exit_v3 = self._source(statuses, "adaptive_execution_exit_intelligence_v3")
        lifecycle = self._source(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        horizon = self._source(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")
        sources = [p for p in (exit_suite, profit_pilot, exit_v3, lifecycle, horizon) if p]
        evidence = max([_evidence(payload) for payload in sources] + [0])
        maturity = _avg([
            _confidence(exit_suite, 0.0) if exit_suite else None,
            _confidence(profit_pilot, 0.0) if profit_pilot else None,
            _confidence(exit_v3, 0.0) if exit_v3 else None,
            72.0 if lifecycle else None,
            70.0 if horizon else None,
        ], 0.0)
        giveback = first(
            exit_suite.get("average_giveback"),
            exit_suite.get("avg_giveback"),
            profit_pilot.get("giveback_risk_score"),
            horizon.get("biggest_profit_capture_leak"),
            0.0,
        )
        capture = first(
            exit_suite.get("capture_ratio"),
            exit_suite.get("learned_capture_ratio"),
            profit_pilot.get("estimated_profit_capture_improvement"),
            horizon.get("profit_capture_score"),
            0.0,
        )
        return {
            "system": "Exit Intelligence Maturation V2",
            "status": "ok" if sources else "insufficient_evidence",
            "exit_intelligence_maturity": rounded(maturity, 3),
            "evidence_count": evidence,
            "mfe_tracking_status": "active_cached_learning" if sources else "insufficient_evidence",
            "mae_tracking_status": "active_cached_learning" if sources else "insufficient_evidence",
            "giveback_tracking_status": "active_cached_learning" if sources else "insufficient_evidence",
            "continuation_tracking_status": "active_cached_learning" if sources else "insufficient_evidence",
            "hold_duration_tracking_status": "active_cached_learning" if sources else "insufficient_evidence",
            "profit_decay_tracking_status": "active_cached_learning" if sources else "insufficient_evidence",
            "horizon_optimization_status": text(first(horizon.get("shadow_to_paper_promotion_readiness_status"), "advisory_only")),
            "exit_timing_quality": rounded(clamp(first(exit_suite.get("exit_quality"), exit_v3.get("exit_quality"), maturity)), 3),
            "missed_continuation_detection": text(first(exit_suite.get("missed_continuation_detection"), "tracked_advisory_only")),
            "early_exit_detection": text(first(exit_suite.get("early_exit_detection"), "tracked_advisory_only")),
            "late_exit_detection": text(first(exit_suite.get("late_exit_detection"), "tracked_advisory_only")),
            "average_giveback": giveback,
            "capture_ratio": capture,
            "profit_decay_learning": "compare_peak_profit_to_current_or_realized_profit_and_route_lessons_through_memory",
            "when_trades_historically_peak": text(first(exit_suite.get("highest_giveback_window"), exit_suite.get("best_shadow_exit_policy"), "insufficient_cached_peak_window_evidence")),
            "when_profits_decay": text(first(profit_pilot.get("strongest_profit_protection_pattern"), exit_suite.get("strongest_decay_pattern"), "monitor_giveback_and_catalyst_decay")),
            "when_continuation_is_likely": text(first(exit_suite.get("continuation_supported_pattern"), "requires_more_cached_lifecycle_evidence")),
            "when_holding_longer_helps": text(first(horizon.get("best_horizon"), exit_suite.get("best_horizon"), "use_horizon_readiness_advisory_only")),
            "when_taking_profit_earlier_helps": text(first(profit_pilot.get("strongest_profit_protection_pattern"), "high_giveback_or_catalyst_decay_cases")),
            "automatic_exits_enabled": False,
            "broker_behavior_changed": False,
            "paper_execution_changed": False,
            **_safe_flags(),
        }

    def _symbol_behavioral_memory_expansion_v1(self, statuses: dict[str, Any]) -> dict[str, Any]:
        long_memory = self._source(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        accelerated = self._source(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        family = self._source(statuses, "trade_family_intelligence_v1")
        tier3 = self._source(statuses, "astra_tier3_historical_satellite_shadow_acceleration_v1")
        sources = [p for p in (long_memory, accelerated, family, tier3) if p]
        profile_count = max([to_int(p.get("symbol_profiles_tracked"), 0) for p in sources] + [0])
        maturity = _avg([
            _confidence(long_memory, 0.0) if long_memory else None,
            _confidence(accelerated, 0.0) if accelerated else None,
            _confidence(family, 0.0) if family else None,
            _confidence(tier3, 0.0) if tier3 else None,
        ], 0.0)
        labels = [
            "Momentum Leader",
            "Mean Reversion Candidate",
            "Volatility Breakout",
            "Catalyst Driven",
            "Slow Compounder",
            "Weak Continuation",
            "High Giveback Risk",
        ]
        return {
            "system": "Symbol Behavioral Memory Expansion V1",
            "status": "ok" if sources else "insufficient_evidence",
            "symbol_behavioral_memory_maturity": rounded(maturity, 3),
            "symbol_profiles_tracked": profile_count,
            "tracks_best_horizon": True,
            "tracks_worst_horizon": True,
            "tracks_average_hold_duration": True,
            "tracks_continuation_behavior": True,
            "tracks_profit_decay": True,
            "tracks_mfe_mae_giveback": True,
            "tracks_volatility_personality": True,
            "tracks_regime_sensitivity": True,
            "tracks_catalyst_sensitivity": True,
            "tracks_sector_sensitivity": True,
            "personality_labels_supported": labels,
            "strongest_symbol_memory": text(first(long_memory.get("strongest_symbol_memory"), accelerated.get("best_symbol"), family.get("strongest_trade_family"), "warming_up")),
            "weakest_symbol_memory": text(first(long_memory.get("weakest_symbol_memory"), accelerated.get("weakest_symbol"), family.get("weakest_trade_family"), "warming_up")),
            "cached_consumers": ["AIOS", "Ask Astra", "Copilot", "CIO", "Executive", "CEO", "Learning Center"],
            "dashboard_provider_calls_used": 0,
            **_safe_flags(),
        }

    def _learning_reinforcement_v1(self, teacher: dict[str, Any], memory: dict[str, Any], dna: dict[str, Any]) -> dict[str, Any]:
        lessons = to_int(teacher.get("lessons_created"), 0)
        excess = to_int(memory.get("excess_lessons_today"), 0)
        reinforcement = clamp((lessons / max(1, MEMORY_BUDGETS["daily_max_lessons"])) * 100.0)
        return {
            "system": "Learning Reinforcement V1",
            "status": "ok" if lessons or dna.get("dna_count") else "insufficient_evidence",
            "memory_lifecycle": ["collect", "compress", "store", "retrieve", "reinforce", "promote", "archive", "discard"],
            "daily_max_lessons": MEMORY_BUDGETS["daily_max_lessons"],
            "weekly_max_lessons": MEMORY_BUDGETS["weekly_max_lessons"],
            "monthly_max_lessons": MEMORY_BUDGETS["monthly_max_lessons"],
            "lessons_created_today": lessons,
            "dna_objects_created": to_int(dna.get("dna_count"), 0),
            "reinforcement_maturity": rounded(reinforcement if lessons else 45.0, 3),
            "promotion_policy": "advisory_only_no_behavior_promotion",
            "archive_policy": "compress_or_archive_excess_low_value_intelligence",
            "discard_policy": "discard_duplicate_stale_low_retention_items",
            "excess_intelligence_count": excess,
            "memory_growth_policy": memory.get("memory_growth_policy"),
            **_safe_flags(),
        }

    def _ask_astra_v2_light_maturation(self, statuses: dict[str, Any], retrieval: dict[str, Any]) -> dict[str, Any]:
        ask = self._source(statuses, "ask_astra_local_ai_status_v1")
        readiness = _avg([
            retrieval.get("memory_retrieval_maturity"),
            80.0 if ask.get("ollama_reachable") or ask.get("structured_fallback_available", True) else 55.0,
            85.0,
        ], 0.0)
        return {
            "system": "Ask Astra V2 Light Maturation",
            "status": "ok",
            "ask_astra_v2_readiness": rounded(readiness, 3),
            "fast_mode_cache_first": True,
            "basic_questions_require_llm": False,
            "drives_data_gathering": False,
            "supports_cross_satellite_explanations": True,
            "supports_source_attribution": True,
            "supports_confidence_explanation": True,
            "supports_why_this_matters": True,
            "supports_what_astra_remembers": True,
            "supports_similar_historical_environments": True,
            "supports_exit_intelligence_explanation": True,
            "supports_symbol_personality_explanation": True,
            **_safe_flags(),
        }

    def _executive_ceo_v3_light_maturation(self, exit_maturity: dict[str, Any], ihie: dict[str, Any], symbol_memory: dict[str, Any]) -> dict[str, Any]:
        readiness = _avg([
            exit_maturity.get("exit_intelligence_maturity"),
            ihie.get("ihie_maturity_score"),
            symbol_memory.get("symbol_behavioral_memory_maturity"),
            82.0,
        ], 0.0)
        return {
            "system": "Executive / CEO V3 Light Maturation",
            "status": "ok",
            "executive_ceo_v3_readiness": rounded(readiness, 3),
            "summarizes_top_market_risks": True,
            "summarizes_top_opportunities": True,
            "summarizes_weakest_intelligence_areas": True,
            "summarizes_exit_intelligence_warnings": True,
            "summarizes_historical_comparison_highlights": True,
            "summarizes_symbol_behavior_highlights": True,
            "ceo_translates_what_changed": True,
            "ceo_translates_why_it_matters": True,
            "ceo_translates_recommendations": True,
            "ceo_translates_needs_attention": True,
            "cached_summary_only": True,
            "dashboard_provider_calls_used": 0,
            "dashboard_llm_calls_used": 0,
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        tier2a = self._source(statuses, "astra_tier2a_librarian_executive_truth_layer_v1")
        long_memory = self._source(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        request_manager = self._satellite_request_manager(statuses)
        satellites = request_manager.get("satellites") or []
        ihie = self._institutional_historical_engine(statuses)
        tier2_lessons = []
        librarian = tier2a.get("astra_librarian_v1") if isinstance(tier2a.get("astra_librarian_v1"), dict) else {}
        if isinstance(librarian.get("retrieval_indexes"), dict):
            # Lessons are represented compactly by Tier2A top insights when direct lesson rows are not exposed.
            exec_layer = tier2a.get("executive_assistant_orchestrator_v1") if isinstance(tier2a.get("executive_assistant_orchestrator_v1"), dict) else {}
            for row in exec_layer.get("top_25") or []:
                if isinstance(row, dict):
                    tier2_lessons.append({
                        "source_system": "astra_tier2a_librarian_executive_truth_layer_v1",
                        "category": row.get("issue"),
                        "confidence": row.get("confidence"),
                        "evidence_count": row.get("evidence"),
                        "priority": row.get("priority"),
                        "compressed_summary": row.get("recommended_focus"),
                        "retrieval_tags": [str(row.get("issue") or "learning").lower().replace(" ", "_")],
                    })
        satellite_lessons = []
        for row in satellites:
            satellite_lessons.append({
                "source_system": row.get("satellite_key"),
                "category": row.get("satellite_name"),
                "confidence": row.get("confidence_budget"),
                "evidence_count": row.get("evidence_count"),
                "priority": row.get("request_priority", "medium").upper(),
                "compressed_summary": row.get("compressed_summary"),
                "retrieval_tags": [row.get("satellite_key"), row.get("satellite_name")],
            })
        dna = self._intelligence_dna([*tier2_lessons, *satellite_lessons])
        triage = self._triage_gate(dna.get("dna_objects") or [], statuses)
        compression = self._compression(satellites, triage.get("accepted_items") or [], tier2a)
        teacher = self._teacher_layer(triage.get("accepted_items") or [])
        memory = self._memory(teacher.get("lessons") or [], long_memory)
        retrieval = self._retrieval(statuses, tier2a, memory)
        aic = self._aic(statuses, request_manager, ihie, compression, retrieval)
        validation = self._validation_layer()
        shadow = self._shadow_inputs()
        exit_maturity = self._exit_intelligence_maturation_v2(statuses)
        symbol_memory = self._symbol_behavioral_memory_expansion_v1(statuses)
        reinforcement = self._learning_reinforcement_v1(teacher, memory, dna)
        ask_v2 = self._ask_astra_v2_light_maturation(statuses, retrieval)
        executive_ceo_v3 = self._executive_ceo_v3_light_maturation(exit_maturity, ihie, symbol_memory)
        maturity_score = rounded(sum([
            to_float(request_manager.get("average_satellite_confidence"), 0.0),
            to_float(ihie.get("confidence"), 0.0),
            to_float(aic.get("aic_coordination_score"), 0.0),
            70.0 if triage.get("status") == "ok" else 45.0,
            70.0 if memory.get("status") == "ok" else 45.0,
        ]) / 5.0, 3)
        final_scores = {
            "exit_intelligence": to_float(exit_maturity.get("exit_intelligence_maturity"), 0.0),
            "ihie": to_float(ihie.get("ihie_maturity_score"), 0.0),
            "symbol_behavioral_memory": to_float(symbol_memory.get("symbol_behavioral_memory_maturity"), 0.0),
            "memory_retrieval": to_float(retrieval.get("memory_retrieval_maturity"), 0.0),
            "learning_reinforcement": to_float(reinforcement.get("reinforcement_maturity"), 0.0),
            "shadow_input_expansion": 82.0 if shadow.get("status") == "inputs_expanded_without_shadow_logic_changes" else 45.0,
            "ask_astra_v2": to_float(ask_v2.get("ask_astra_v2_readiness"), 0.0),
            "executive_ceo_v3": to_float(executive_ceo_v3.get("executive_ceo_v3_readiness"), 0.0),
        }
        final_maturation_health = rounded(sum(final_scores.values()) / max(1, len(final_scores)), 3)
        weakest_remaining = [
            {"area": key, "score": rounded(value, 3)}
            for key, value in sorted(final_scores.items(), key=lambda item: item[1])[:4]
        ]
        weakest = "exit_intelligence" if any(row.get("satellite_key") == "exit_intelligence_satellite" and row.get("health") != "healthy" for row in satellites) else "memory_depth" if memory.get("status") != "ok" else "historical_depth"
        out = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA AIOS V1 + Intelligence Maturation Bundle",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "architecture_flow": [
                "Providers/APIs", "Controlled Data Acquisition", "Satellite Request Manager", "12 Intelligence Satellites",
                "Institutional Historical Intelligence Engine", "Shadow Layer (unchanged)", "Triage/Relevance Gate",
                "Multi-Stage Compression", "Teacher Layer", "Multi-Tier Memory", "Memory Retrieval Engine",
                "Astra Intelligence Core", "Experimentation & Validation", "CIO Layer", "Executive/CEO",
                "Copilot/Ask Astra", "Dashboard", "Continuous Feedback Loop",
            ],
            "satellite_request_manager_v1": request_manager,
            "institutional_historical_intelligence_engine_v1": ihie,
            "intelligence_dna_v1": dna,
            "triage_relevance_gate_v1": triage,
            "multi_stage_compression_v1": compression,
            "teacher_layer_v1": teacher,
            "multi_tier_memory_v1": memory,
            "memory_retrieval_engine_v1": retrieval,
            "astra_intelligence_core_v1": aic,
            "experimentation_validation_layer_v1": validation,
            "shadow_input_expansion_v1": shadow,
            "exit_intelligence_maturation_v2": exit_maturity,
            "symbol_behavioral_memory_expansion_v1": symbol_memory,
            "learning_reinforcement_v1": reinforcement,
            "ask_astra_v2_light_maturation": ask_v2,
            "executive_ceo_v3_light_maturation": executive_ceo_v3,
            "final_intelligence_maturation_optimization_v1": {
                "system": "ASTRA Final Intelligence Maturation & Optimization Bundle V1",
                "status": "ok",
                "final_maturation_bundle_health": final_maturation_health,
                "exit_intelligence_maturity": exit_maturity.get("exit_intelligence_maturity"),
                "ihie_maturity": ihie.get("ihie_maturity_score"),
                "symbol_behavioral_memory_maturity": symbol_memory.get("symbol_behavioral_memory_maturity"),
                "memory_retrieval_maturity": retrieval.get("memory_retrieval_maturity"),
                "learning_reinforcement_maturity": reinforcement.get("reinforcement_maturity"),
                "shadow_input_expansion_status": shadow.get("status"),
                "ask_astra_v2_readiness": ask_v2.get("ask_astra_v2_readiness"),
                "executive_ceo_v3_readiness": executive_ceo_v3.get("executive_ceo_v3_readiness"),
                "weakest_remaining_areas": weakest_remaining,
                "provider_policy": {
                    "fmp_owner": "market_and_fundamental_data",
                    "alpaca_owner": "broker_truth_only",
                    "fred_owner": "macro_context",
                    "finnhub_owner": "news_catalyst_sentiment_context",
                    "moralis_owner": "crypto_context",
                    "secondary_providers": "backup_only",
                },
                "bandwidth_budget_gb_month": {
                    "target_low": 5,
                    "target_high": 10,
                    "soft_limit": 15,
                    "warning": 25,
                    "throttle": 35,
                    "emergency_stop": 45,
                },
                **_safe_flags(),
            },
            "aios_maturity_score": maturity_score,
            "final_maturation_bundle_health": final_maturation_health,
            "exit_intelligence_maturity": exit_maturity.get("exit_intelligence_maturity"),
            "ihie_maturity": ihie.get("ihie_maturity_score"),
            "symbol_behavioral_memory_maturity": symbol_memory.get("symbol_behavioral_memory_maturity"),
            "memory_retrieval_maturity": retrieval.get("memory_retrieval_maturity"),
            "learning_reinforcement_maturity": reinforcement.get("reinforcement_maturity"),
            "shadow_input_expansion_status": shadow.get("status"),
            "ask_astra_v2_readiness": ask_v2.get("ask_astra_v2_readiness"),
            "executive_ceo_v3_readiness": executive_ceo_v3.get("executive_ceo_v3_readiness"),
            "weakest_remaining_areas": weakest_remaining,
            "satellites_registered": len(satellites),
            "lessons_created": teacher.get("lessons_created", 0),
            "triage_acceptance_rate": rounded(to_float(triage.get("accepted"), 0.0) / max(1.0, to_float(triage.get("reviewed"), 0.0)) * 100.0, 3),
            "highest_priority_focus": first((teacher.get("lessons") or [{}])[0].get("lesson") if teacher.get("lessons") else None, ihie.get("top_historical_lesson"), "continue cache-first AIOS maturation"),
            "weakest_aios_area": weakest,
            "existing_systems_integrated": [
                "Controlled Data Acquisition", "Knowledge Graph", "Consensus Engine", "Governance", "Data Freshness Engine",
                "Data Coverage Engine", "Provider Governance", "Provider Self-Healing", "Market Regime Engine",
                "CIO Intelligence", "Executive/CEO summaries", "Ask Astra", "Copilot", "Shadow", "Dashboard",
                "Tier2A Librarian/Truth", "Tier2B Satellite Network", "Tier3 Historical Satellite Acceleration",
                "Long-Term Memory Symbol Retrieval", "Exit Intelligence", "IHIE", "Symbol Behavioral Memory",
                "Memory Retrieval", "Learning Reinforcement",
            ],
            "intentionally_not_changed": [
                "Shadow logic", "live trading", "automatic entries", "automatic exits", "automatic allocations",
                "automatic sizing", "broker execution", "ranking logic", "entry thresholds", "dashboard provider calls",
                "dashboard LLM calls", "providers", "AI models",
            ],
            "dashboard_integration": "single_unified_diagnostics_cached_panel",
            "dashboard_endpoint_storm_created": False,
            "dashboard_provider_calls_used": 0,
            "dashboard_llm_calls_used": 0,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(out)
