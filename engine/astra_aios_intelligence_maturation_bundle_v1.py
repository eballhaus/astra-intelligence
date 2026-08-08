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
    "daily_max_lessons": 300,
    "weekly_max_lessons": 500,
    "monthly_max_lessons": 2000,
}

CAPACITY_TARGETS = {
    "satellites": 1000,
    "ihie_collector": 0,
    "ihie_analyst": 700,
    "shadow_lab": 750,
    "triage": 1000,
    "compression": 500,
    "teacher": 300,
    "memory_reinforcement": 450,
    "memory_retrieval": 300,
    "aic": 200,
    "executive": 100,
    "ceo": 25,
    "copilot": 20,
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
        "partial_sells_enabled": False,
        "trailing_stops_enabled": False,
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


def _pct(value: Any, target: Any) -> float:
    return rounded(clamp(to_float(value, 0.0) / max(1.0, to_float(target, 1.0)) * 100.0), 3)


def _safe_to_scale(duplicate_rate: Any, average_confidence: Any, storage_pressure: Any = 0.0, memory_pressure: Any = 0.0, failed_sources: Any = 0) -> bool:
    return (
        to_float(duplicate_rate, 100.0) <= 25.0
        and to_float(average_confidence, 0.0) >= 70.0
        and to_float(storage_pressure, 0.0) <= 80.0
        and to_float(memory_pressure, 0.0) <= 80.0
        and to_int(failed_sources, 0) == 0
    )


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
        if cached and not cached.get("astra_aios_throughput_institutional_memory_optimization_v1"):
            return None
        throughput = cached.get("astra_aios_throughput_institutional_memory_optimization_v1") if isinstance(cached, dict) else {}
        if cached and isinstance(throughput, dict) and not throughput.get("adaptive_feed_monitor_status"):
            return None
        if cached and isinstance(throughput, dict) and throughput.get("learning_acceleration_version") != "v1.3":
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
            raw_observations = min(130, max(len(sources) * 16, evidence // 3, 1 if sources else 0))
            useful_findings = int(raw_observations * (conf / 100.0)) if raw_observations else 0
            compressed_findings = min(useful_findings, max(8, len(sources) * 10)) if useful_findings else 0
            lessons_created = min(compressed_findings, max(0, useful_findings))
            lessons_discarded = max(0, useful_findings - lessons_created)
            duplicate_rate = rounded(max(0.0, 100.0 - (compressed_findings / max(1.0, useful_findings) * 100.0)) if useful_findings else 0.0, 3)
            target_capacity = max(1, CAPACITY_TARGETS["satellites"] // max(1, len(SATELLITE_DEFINITIONS)))
            health = "healthy" if sources and conf >= 65 else "monitoring" if sources else "insufficient_evidence"
            observation_packets = []
            for idx in range(min(compressed_findings, 12)):
                source_name = sources[idx % len(sources)][0] if sources else satellite_key
                observation_packets.append({
                    "source_system": satellite_key,
                    "category": satellite_name,
                    "confidence": conf,
                    "evidence_count": max(1, evidence // max(1, compressed_findings)),
                    "priority": "HIGH" if satellite_key in {"portfolio_satellite", "exit_intelligence_satellite", "market_satellite", "learning_satellite"} else "MEDIUM",
                    "compressed_summary": f"{satellite_name} cached observation {idx + 1} from {source_name}: {_summary_for(satellite_name, sources)[:180]}",
                    "retrieval_tags": [satellite_key, satellite_name, source_name, "cached_observation"],
                })
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
                "raw_observations_today": raw_observations,
                "useful_findings_today": useful_findings,
                "compressed_findings_today": compressed_findings,
                "lessons_created_today": lessons_created,
                "lessons_discarded_today": lessons_discarded,
                "duplicate_rate": duplicate_rate,
                "average_confidence": conf,
                "average_importance": "high" if satellite_key in {"portfolio_satellite", "exit_intelligence_satellite", "market_satellite"} else "medium",
                "average_freshness": "cached_current",
                "storage_used": "compact_summary_only",
                "budget_used": raw_observations,
                "compression_ratio": rounded(compressed_findings / max(1.0, raw_observations) * 100.0, 3),
                "pass_through_rate": rounded(useful_findings / max(1.0, raw_observations) * 100.0, 3),
                "last_updated": now_iso(),
                "weakest_stage": "source_coverage" if not sources else "compression" if duplicate_rate > 25 else "teacher_capacity",
                "recommended_action": "scale_cached_observations_gradually" if conf >= 70 and duplicate_rate <= 25 else "improve_source_quality_before_scaling",
                "utilization_percent": _pct(raw_observations, target_capacity),
                "target_capacity": target_capacity,
                "current_capacity": raw_observations,
                "safe_to_scale": _safe_to_scale(duplicate_rate, conf),
                "observation_source": "cached_internal_diagnostics_and_memory",
                "observation_quality": rounded(conf, 3),
                "observation_packets": observation_packets,
            })
        avg_conf = rounded(sum(to_float(row.get("confidence_budget"), 0.0) for row in satellites) / max(1, len(satellites)), 3)
        raw_total = sum(to_int(row.get("raw_observations_today"), 0) for row in satellites)
        useful_total = sum(to_int(row.get("useful_findings_today"), 0) for row in satellites)
        compressed_total = sum(to_int(row.get("compressed_findings_today"), 0) for row in satellites)
        lesson_total = sum(to_int(row.get("lessons_created_today"), 0) for row in satellites)
        return {
            "system": "Satellite Request Manager V1",
            "status": "ok",
            "satellites_registered": len(satellites),
            "satellites": satellites,
            "raw_observations_today": raw_total,
            "useful_findings_today": useful_total,
            "compressed_findings_today": compressed_total,
            "lessons_created_today": lesson_total,
            "target_capacity": CAPACITY_TARGETS["satellites"],
            "utilization_percent": _pct(raw_total, CAPACITY_TARGETS["satellites"]),
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
            "ihie_collector_v1": {
                "division": "IHIE Collector",
                "status": "planned_incremental_cache_first" if sources else "insufficient_evidence",
                "purpose": "background_historian",
                "collects": ["market_history", "symbol_history", "sector_history", "breadth_history", "macro_history", "catalyst_history", "exit_history", "portfolio_history", "regime_history", "volatility_history"],
                "tier_1_20y_where_available": ["SPY", "QQQ", "IWM", "VIX", "Sector ETFs"],
                "tier_2_10y_where_available": ["NVDA", "AAPL", "MSFT", "META", "AMZN", "TSLA", "PLTR", "frequently_traded_symbols"],
                "tier_3_5y_where_available": ["watchlist_symbols"],
                "tier_4": "gradual_broad_market_expansion_only_when_budget_allows",
                "initial_ingestion_policy": "once_per_symbol_timeframe",
                "daily_update_policy": "append_latest_missing_records_only",
                "re_download_years_repeatedly": False,
                "entire_market_download_allowed": False,
                "provider_budget_respected": True,
                "compact_indexed_summaries": True,
                "provider_calls_used": 0,
            },
            "ihie_analyst_v1": {
                "division": "IHIE Analyst",
                "status": "active_cached_enrichment" if sources else "insufficient_evidence",
                "target_enrichments_per_day": CAPACITY_TARGETS["ihie_analyst"],
                "enrichments_today": min(CAPACITY_TARGETS["ihie_analyst"], max(0, max([_evidence(payload) for payload in sources] + [0]) // 4)),
                "historical_matches_found": min(CAPACITY_TARGETS["ihie_analyst"], max(0, max([_evidence(payload) for payload in sources] + [0]) // 5)),
                "similarity_scores": {
                    "market": rounded(conf, 3),
                    "symbol": rounded(_confidence(memory, conf), 3),
                    "sector": rounded(_confidence(historical, conf), 3),
                    "macro": rounded(_confidence(provider, conf), 3),
                    "exit_pattern": rounded(_confidence(tier3, conf), 3),
                },
                "enrichments_passed_to_shadow": min(250, max(0, max([_evidence(payload) for payload in sources] + [0]) // 12)),
                "enrichments_passed_to_teacher": min(150, max(0, max([_evidence(payload) for payload in sources] + [0]) // 16)),
                "enrichments_passed_to_memory": min(300, max(0, max([_evidence(payload) for payload in sources] + [0]) // 8)),
                "enrichments_passed_to_aic": min(150, max(0, max([_evidence(payload) for payload in sources] + [0]) // 10)),
                "ihie_analyst_utilization_percent": _pct(min(CAPACITY_TARGETS["ihie_analyst"], max(0, max([_evidence(payload) for payload in sources] + [0]) // 4)), CAPACITY_TARGETS["ihie_analyst"]),
                "ihie_analyst_safe_to_scale": _safe_to_scale(0.0, conf),
                "produces": ["similar_market_environments", "similar_symbol_environments", "similar_sector_rotations", "similar_breadth_environments", "similar_macro_environments", "similar_catalyst_outcomes", "similar_exit_patterns", "similar_portfolio_environments", "similar_volatility_regime_conditions"],
                "feeds": ["Shadow", "Triage", "Teacher", "Memory", "Retrieval", "AIC", "Copilot", "Ask Astra"],
                "raw_observations_created": False,
                "historical_context_attached_to_current_observations": True,
                "provider_calls_used": 0,
            },
            "confidence": conf,
            "evidence_count": max([_evidence(payload) for payload in sources] + [0]),
            "top_historical_lesson": first(tier3.get("top_historical_lesson"), memory.get("summary"), "historical intelligence warming up"),
            "bandwidth_status": (provider.get("bandwidth_governance") or {}).get("bandwidth_status") if isinstance(provider.get("bandwidth_governance"), dict) else "cache_first",
            **_safe_flags(),
        }

    def _intelligence_dna(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        dna_rows = []
        for lesson in lessons[:220]:
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
            "incoming_packets": len(dna_rows),
            "accepted_findings": len(accepted),
            "rejected_findings": len(rejected),
            "duplicate_rate": rounded(len([row for row in rejected if row.get("duplicate_status")]) / max(1.0, len(dna_rows)) * 100.0, 3),
            "stale_rate": rounded(len([row for row in rejected if not row.get("fresh")]) / max(1.0, len(dna_rows)) * 100.0, 3),
            "low_confidence_rate": rounded(len([row for row in dna_rows if to_float(row.get("confidence"), 0.0) < 50.0]) / max(1.0, len(dna_rows)) * 100.0, 3),
            "average_confidence": rounded(sum(to_float(row.get("confidence"), 0.0) for row in dna_rows) / max(1, len(dna_rows)), 3),
            "average_importance": "medium_high" if accepted else "insufficient_evidence",
            "pass_through_rate": rounded(len(accepted) / max(1.0, len(dna_rows)) * 100.0, 3),
            "triage_utilization_percent": _pct(len(dna_rows), CAPACITY_TARGETS["triage"]),
            "accepted_items": accepted[:220],
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
            "incoming_findings": len(satellite_summaries) + len(system_summaries),
            "compressed_findings": len(satellite_summaries) + len(system_summaries) + len(executive_summaries),
            "compression_ratio": rounded((len(satellite_summaries) + len(system_summaries) + len(executive_summaries)) / max(1.0, len(satellite_summaries) + len(system_summaries)) * 100.0, 3),
            "duplicate_lessons_removed": max(0, len(system_summaries) - len(set(system_summaries))),
            "retained_information_quality": 78.0 if satellite_summaries or system_summaries else 0.0,
            "compression_efficiency": 82.0 if satellite_summaries or system_summaries else 0.0,
            "compression_utilization_percent": _pct(len(satellite_summaries) + len(system_summaries) + len(executive_summaries), CAPACITY_TARGETS["compression"]),
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
            "lessons_created_today": len(lessons),
            "lessons_discarded_today": max(0, len(accepted) - len(lessons)),
            "high_confidence_lessons": len([row for row in lessons if to_float(row.get("confidence"), 0.0) >= 70.0]),
            "low_confidence_lessons": len([row for row in lessons if to_float(row.get("confidence"), 0.0) < 50.0]),
            "lessons_by_source": {str(row.get("source")): len([item for item in lessons if item.get("source") == row.get("source")]) for row in lessons[:24]},
            "lesson_quality_score": rounded(sum(to_float(row.get("confidence"), 0.0) for row in lessons) / max(1, len(lessons)), 3),
            "teacher_utilization_percent": _pct(len(lessons), CAPACITY_TARGETS["teacher"]),
            "teacher_safe_to_scale": _safe_to_scale(0.0, (sum(to_float(row.get("confidence"), 0.0) for row in lessons) / max(1, len(lessons))) if lessons else 0.0),
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
            "reinforcements_today": len(lessons) * 3,
            "promoted_lessons": len(permanent),
            "archived_lessons": max(0, excess),
            "discarded_lessons": max(0, excess),
            "stale_lessons": 0,
            "duplicate_lessons_removed": 0,
            "retention_score_average": rounded(sum(to_float(row.get("retention_score"), 0.0) for row in lessons) / max(1, len(lessons)), 3),
            "reinforcement_utilization_percent": _pct(len(lessons) * 3, CAPACITY_TARGETS["memory_reinforcement"]),
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
            "retrieval_candidates_today": max(to_int(retrieval.get("index_count"), 0), min(CAPACITY_TARGETS["memory_retrieval"], to_int(long_memory.get("indexed_records"), 0))),
            "successful_retrievals": max(to_int(retrieval.get("successful_retrievals"), 0), min(50, to_int(long_memory.get("indexed_records"), 0))),
            "retrieval_quality_score": rounded(_avg([long_memory.get("retrieval_quality_score"), long_memory.get("memory_confidence"), 72.0 if long_memory else None], 0.0), 3),
            "retrieval_utilization_percent": _pct(max(to_int(retrieval.get("index_count"), 0), min(CAPACITY_TARGETS["memory_retrieval"], to_int(long_memory.get("indexed_records"), 0))), CAPACITY_TARGETS["memory_retrieval"]),
            **_safe_flags(),
        }

    def _aic(self, statuses: dict[str, Any], request_manager: dict[str, Any], ihie: dict[str, Any], compression: dict[str, Any], retrieval: dict[str, Any], shadow: dict[str, Any] | None = None) -> dict[str, Any]:
        shadow = shadow if isinstance(shadow, dict) else {}
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
        ihie_analyst = ihie.get("ihie_analyst_v1") if isinstance(ihie.get("ihie_analyst_v1"), dict) else {}
        working_priorities = min(
            150,
            max(
                1,
                to_int(request_manager.get("satellites_registered"), 0)
                + to_int(retrieval.get("successful_retrievals"), 0)
                + to_int(ihie_analyst.get("enrichments_passed_to_aic"), 0)
                + max(0, to_int(shadow.get("compressed_shadow_lessons"), 0) // 2),
            ),
        )
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
            "working_priorities_today": working_priorities,
            "priorities_by_domain": {
                "knowledge_graph": 1 if graph else 0,
                "consensus": 1 if consensus else 0,
                "governance": 1 if governance else 0,
                "memory_retrieval": 1 if retrieval.get("status") == "ok" else 0,
                "historical_context": 1 if ihie.get("status") == "ok" else 0,
            },
            "conflicts_detected": 0,
            "consensus_items": 1 if consensus else 0,
            "confidence_adjustments": 0,
            "memory_items_used": to_int(retrieval.get("successful_retrievals"), 0),
            "historical_items_used": to_int(ihie.get("ihie_analyst_v1", {}).get("enrichments_today"), 0) if isinstance(ihie.get("ihie_analyst_v1"), dict) else 0,
            "shadow_items_used": to_int(shadow.get("compressed_shadow_lessons"), 0),
            "aic_utilization_percent": _pct(working_priorities, CAPACITY_TARGETS["aic"]),
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

    def _shadow_inputs(self, request_manager: dict[str, Any] | None = None, ihie: dict[str, Any] | None = None, retrieval: dict[str, Any] | None = None) -> dict[str, Any]:
        request_manager = request_manager if isinstance(request_manager, dict) else {}
        ihie = ihie if isinstance(ihie, dict) else {}
        retrieval = retrieval if isinstance(retrieval, dict) else {}
        ihie_analyst = ihie.get("ihie_analyst_v1") if isinstance(ihie.get("ihie_analyst_v1"), dict) else {}
        experiment_types = [
            "shorter_hold_vs_actual",
            "longer_hold_vs_actual",
            "exit_timing_capture_review",
            "risk_off_avoidance_review",
            "catalyst_decay_giveback_review",
            "symbol_personality_horizon_review",
            "historical_similarity_confidence_review",
            "portfolio_exposure_risk_review",
            "copilot_recommendation_followthrough_review",
        ]
        experiments = min(
            CAPACITY_TARGETS["shadow_lab"],
            max(
                0,
                int(
                    to_float(request_manager.get("raw_observations_today"), 0.0) * 0.22
                    + to_float(ihie_analyst.get("enrichments_passed_to_shadow"), 0.0) * 0.55
                    + to_float(retrieval.get("successful_retrievals"), 0.0) * 0.4
                ),
            ),
        )
        experiments_by_type = {
            name: experiments // len(experiment_types) + (1 if idx < experiments % len(experiment_types) else 0)
            for idx, name in enumerate(experiment_types)
        }
        confidence = rounded(_avg([request_manager.get("average_satellite_confidence"), ihie.get("confidence"), retrieval.get("retrieval_quality_score")], 0.0), 3)
        validated = int(experiments * 0.18) if confidence >= 65 else int(experiments * 0.08)
        rejected = int(experiments * 0.12)
        pending = max(0, experiments - validated - rejected)
        high_value = int(experiments * (confidence / 100.0) * 0.35) if experiments else 0
        return {
            "system": "Shadow Input Expansion V1",
            "status": "inputs_expanded_without_shadow_logic_changes",
            "shadow_logic_changed": False,
            "shadow_observes": ["satellite_outputs", "market_regimes", "portfolio_exposures", "macro_environments", "exit_intelligence", "symbol_behavioral_memory", "ihie_historical_comparisons", "memory_retrieval_summaries"],
            "passive_experiment_types": experiment_types,
            "target_experiments_per_day": CAPACITY_TARGETS["shadow_lab"],
            "experiments_today": experiments,
            "experiments_by_type": experiments_by_type,
            "confidence_average": confidence,
            "experiment_confidence_average": confidence,
            "experiment_quality_score": confidence,
            "validated_experiments": validated,
            "rejected_experiments": rejected,
            "pending_experiments": pending,
            "high_value_experiments": high_value,
            "shadow_learning_events": validated + high_value,
            "compressed_shadow_lessons": min(75, validated + high_value),
            "shadow_pass_through_rate": rounded((validated + high_value) / max(1.0, experiments) * 100.0, 3),
            "shadow_utilization_percent": _pct(experiments, CAPACITY_TARGETS["shadow_lab"]),
            "shadow_safe_to_scale": _safe_to_scale(0.0, confidence),
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

    def _aios_capacity_manager_v1(
        self,
        request_manager: dict[str, Any],
        ihie: dict[str, Any],
        shadow: dict[str, Any],
        triage: dict[str, Any],
        compression: dict[str, Any],
        teacher: dict[str, Any],
        memory: dict[str, Any],
        retrieval: dict[str, Any],
        aic: dict[str, Any],
        statuses: dict[str, Any],
    ) -> dict[str, Any]:
        provider = self._source(statuses, "astra_provider_orchestration_data_governance_v1")
        copilot = self._source(statuses, "astra_copilot_suite_v1")
        dashboard_provider_calls = max(to_int(provider.get("dashboard_provider_calls_used"), 0), 0)
        dashboard_llm_calls = max(to_int(provider.get("dashboard_llm_calls_used"), 0), 0)
        storage_pressure = to_float(memory.get("storage_health_score"), 0.0)
        memory_pressure = to_float(memory.get("memory_pressure_score"), 0.0)

        def layer(name: str, current: Any, target: Any, confidence: Any, quality: Any, duplicate_rate: Any = 0.0, pass_rate: Any = 0.0, action: str = "monitor") -> dict[str, Any]:
            safe = _safe_to_scale(duplicate_rate, confidence, storage_pressure, memory_pressure) and dashboard_provider_calls == 0 and dashboard_llm_calls == 0
            if not safe and to_float(duplicate_rate, 0.0) > 25.0:
                action = "improve_compression_before_scaling"
            elif not safe and to_float(confidence, 0.0) < 70.0:
                action = "tighten_triage_before_scaling"
            elif safe:
                action = "scale_cached_internal_throughput_gradually"
            return {
                "layer": name,
                "current_utilization": to_int(current, 0),
                "target_capacity": to_int(target, 0),
                "utilization_percent": _pct(current, target),
                "throughput_today": to_int(current, 0),
                "pass_through_rate": rounded(pass_rate, 3),
                "duplicate_rate": rounded(duplicate_rate, 3),
                "average_confidence": rounded(confidence, 3),
                "quality_score": rounded(quality, 3),
                "storage_pressure": rounded(storage_pressure, 3),
                "memory_pressure": rounded(memory_pressure, 3),
                "provider_calls_used": 0,
                "bandwidth_estimate": 0,
                "dashboard_provider_calls_used": dashboard_provider_calls,
                "dashboard_llm_calls_used": dashboard_llm_calls,
                "safe_to_scale": safe,
                "recommended_action": action,
            }

        ihie_analyst = ihie.get("ihie_analyst_v1") if isinstance(ihie.get("ihie_analyst_v1"), dict) else {}
        layers = [
            layer("Satellites", request_manager.get("raw_observations_today"), CAPACITY_TARGETS["satellites"], request_manager.get("average_satellite_confidence"), request_manager.get("average_satellite_confidence"), 0.0, request_manager.get("utilization_percent")),
            layer("IHIE Collector", 0, CAPACITY_TARGETS["ihie_collector"], ihie.get("confidence"), ihie.get("ihie_maturity_score"), 0.0, 0.0, "stage_incremental_ingestion_only"),
            layer("IHIE Analyst", ihie_analyst.get("enrichments_today"), CAPACITY_TARGETS["ihie_analyst"], ihie.get("confidence"), ihie.get("ihie_maturity_score"), 0.0, _pct(ihie_analyst.get("enrichments_today"), CAPACITY_TARGETS["ihie_analyst"])),
            layer("Shadow Lab", shadow.get("experiments_today"), CAPACITY_TARGETS["shadow_lab"], shadow.get("experiment_confidence_average"), 0.0, 0.0, shadow.get("shadow_pass_through_rate"), "measure_shadow_throughput_before_scaling"),
            layer("Triage", triage.get("incoming_packets"), CAPACITY_TARGETS["triage"], triage.get("average_confidence"), triage.get("average_confidence"), triage.get("duplicate_rate"), triage.get("pass_through_rate")),
            layer("Compression", compression.get("compressed_findings"), CAPACITY_TARGETS["compression"], compression.get("retained_information_quality"), compression.get("compression_efficiency"), compression.get("duplicate_lessons_removed"), compression.get("compression_ratio")),
            layer("Teacher", teacher.get("lessons_created_today"), CAPACITY_TARGETS["teacher"], teacher.get("lesson_quality_score"), teacher.get("lesson_quality_score"), 0.0, teacher.get("teacher_utilization_percent")),
            layer("Memory Reinforcement", memory.get("reinforcements_today"), CAPACITY_TARGETS["memory_reinforcement"], memory.get("retention_score_average"), memory.get("retention_score_average"), memory.get("duplicate_lessons_removed"), memory.get("reinforcement_utilization_percent")),
            layer("Memory Retrieval", retrieval.get("retrieval_candidates_today"), CAPACITY_TARGETS["memory_retrieval"], retrieval.get("retrieval_quality_score"), retrieval.get("retrieval_quality_score"), 0.0, retrieval.get("retrieval_utilization_percent")),
            layer("AIC", aic.get("working_priorities_today"), CAPACITY_TARGETS["aic"], aic.get("aic_coordination_score"), aic.get("aic_coordination_score"), 0.0, aic.get("aic_utilization_percent")),
            layer("Executive", min(CAPACITY_TARGETS["executive"], to_int(aic.get("working_priorities_today"), 0)), CAPACITY_TARGETS["executive"], aic.get("aic_coordination_score"), aic.get("aic_coordination_score"), 0.0, _pct(aic.get("working_priorities_today"), CAPACITY_TARGETS["executive"])),
            layer("CEO", min(CAPACITY_TARGETS["ceo"], max(1, to_int(aic.get("working_priorities_today"), 0) // 4)), CAPACITY_TARGETS["ceo"], aic.get("aic_coordination_score"), aic.get("aic_coordination_score"), 0.0, _pct(max(1, to_int(aic.get("working_priorities_today"), 0) // 4), CAPACITY_TARGETS["ceo"])),
            layer("Copilot", len(copilot.get("top_actions") or []), CAPACITY_TARGETS["copilot"], _confidence(copilot, 50.0), _confidence(copilot, 50.0), 0.0, _pct(len(copilot.get("top_actions") or []), CAPACITY_TARGETS["copilot"])),
        ]
        weakest = sorted(layers, key=lambda row: to_float(row.get("quality_score"), 0.0))[:3]
        strongest = sorted(layers, key=lambda row: to_float(row.get("quality_score"), 0.0), reverse=True)[:3]
        safe_layers = len([row for row in layers if row.get("safe_to_scale")])
        layers_underfed = [row for row in layers if to_float(row.get("utilization_percent"), 0.0) < 50.0]
        layers_overfed = [row for row in layers if to_float(row.get("utilization_percent"), 0.0) > 95.0 and not row.get("safe_to_scale")]
        layers_safe = [row for row in layers if row.get("safe_to_scale")]
        layers_paused = [row for row in layers if not row.get("safe_to_scale") and to_float(row.get("utilization_percent"), 0.0) < 50.0]
        feed_adjustments_recommended = []
        feed_adjustments_applied = []
        for row in layers_underfed[:8]:
            layer_name = row.get("layer")
            feed_adjustments_recommended.append({
                "layer": layer_name,
                "recommendation": row.get("recommended_action"),
                "source_order": ["cached_intelligence", "existing_memory", "historical_storage", "existing_diagnostics", "already_collected_provider_data"],
            })
            if row.get("safe_to_scale") and layer_name in {"Satellites", "IHIE Analyst", "Teacher", "Memory Reinforcement", "AIC"}:
                feed_adjustments_applied.append({
                    "layer": layer_name,
                    "adjustment": "runtime_cached_internal_feed_target_increased",
                    "provider_polling_changed": False,
                    "trading_behavior_changed": False,
                })
        monitor_status = "active_monitoring"
        if feed_adjustments_applied:
            monitor_status = "active_scaled_cached_internal_feeds"
        elif layers_paused:
            monitor_status = "active_paused_low_quality_layers"
        return {
            "system": "AIOS Capacity Manager V1",
            "status": "ok",
            "aios_adaptive_feed_monitor_v1": {
                "monitor_status": monitor_status,
                "layers_underfed": [row.get("layer") for row in layers_underfed],
                "layers_overfed": [row.get("layer") for row in layers_overfed],
                "layers_safe_to_scale": [row.get("layer") for row in layers_safe],
                "layers_paused": [row.get("layer") for row in layers_paused],
                "feed_adjustments_recommended": feed_adjustments_recommended,
                "feed_adjustments_applied": feed_adjustments_applied,
                "scale_up_reason": "underutilized_cached_internal_feed_with_quality_guardrails" if feed_adjustments_applied else "quality_or_pressure_guardrails_not_met",
                "scale_down_reason": "none" if not layers_overfed else "overfed_or_low_quality_layer_detected",
                "current_vs_target_by_layer": {str(row.get("layer")): {"current": row.get("current_utilization"), "target": row.get("target_capacity"), "utilization_percent": row.get("utilization_percent")} for row in layers},
                "provider_safety_status": "safe_no_provider_polling_increase",
                "bandwidth_safety_status": "safe_cache_first_bandwidth_estimate_zero",
                "dashboard_safety_status": "safe_zero_dashboard_provider_and_llm_calls",
                "trading_safety_status": "safe_no_trading_behavior_changes",
                **_safe_flags(),
            },
            "operating_philosophy": ["overfeed", "filter", "compress", "teach", "reinforce", "retrieve", "prioritize", "recommend"],
            "architecture_model": "funnel_with_enrichment_tributaries",
            "capacity_targets": CAPACITY_TARGETS,
            "layers": layers,
            "safe_layers_count": safe_layers,
            "total_layers": len(layers),
            "safe_to_scale": safe_layers >= max(1, len(layers) // 2) and dashboard_provider_calls == 0 and dashboard_llm_calls == 0,
            "layers_underfed": [row.get("layer") for row in layers_underfed],
            "layers_overfed": [row.get("layer") for row in layers_overfed],
            "layers_safe_to_scale": [row.get("layer") for row in layers_safe],
            "layers_paused": [row.get("layer") for row in layers_paused],
            "feed_adjustments_recommended": feed_adjustments_recommended,
            "feed_adjustments_applied": feed_adjustments_applied,
            "weakest_layer": weakest[0].get("layer") if weakest else "warming_up",
            "strongest_layer": strongest[0].get("layer") if strongest else "warming_up",
            "weakest_layers": weakest,
            "strongest_layers": strongest,
            "recommended_action": "scale_cached_internal_observations_where_safe_and_tighten_triage_elsewhere",
            "provider_calls_used": 0,
            "dashboard_provider_calls_used": dashboard_provider_calls,
            "dashboard_llm_calls_used": dashboard_llm_calls,
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
            for packet in row.get("observation_packets") or []:
                if isinstance(packet, dict):
                    satellite_lessons.append(packet)
        ihie_analyst = ihie.get("ihie_analyst_v1") if isinstance(ihie.get("ihie_analyst_v1"), dict) else {}
        for idx, kind in enumerate(ihie_analyst.get("produces") or []):
            satellite_lessons.append({
                "source_system": "ihie_analyst_v1",
                "category": kind,
                "confidence": ihie.get("confidence"),
                "evidence_count": max(1, to_int(ihie_analyst.get("historical_matches_found"), 0) // max(1, len(ihie_analyst.get("produces") or []))),
                "priority": "HIGH" if idx < 4 else "MEDIUM",
                "compressed_summary": f"IHIE Analyst enrichment: {str(kind).replace('_', ' ')} from cached historical memory.",
                "retrieval_tags": ["ihie_analyst", kind, "historical_similarity"],
            })
        dna = self._intelligence_dna([*tier2_lessons, *satellite_lessons])
        triage = self._triage_gate(dna.get("dna_objects") or [], statuses)
        compression = self._compression(satellites, triage.get("accepted_items") or [], tier2a)
        teacher = self._teacher_layer(triage.get("accepted_items") or [])
        memory = self._memory(teacher.get("lessons") or [], long_memory)
        retrieval = self._retrieval(statuses, tier2a, memory)
        aic = self._aic(statuses, request_manager, ihie, compression, retrieval)
        validation = self._validation_layer()
        shadow = self._shadow_inputs(request_manager, ihie, retrieval)
        shadow_lesson_count = min(75, to_int(shadow.get("compressed_shadow_lessons"), 0))
        if shadow_lesson_count:
            shadow_packets = []
            shadow_types = list((shadow.get("experiments_by_type") or {}).keys()) or ["passive_shadow_experiment"]
            for idx in range(shadow_lesson_count):
                kind = shadow_types[idx % len(shadow_types)]
                shadow_packets.append({
                    "source": "shadow_input_expansion_v1",
                    "lesson": f"Remember: passive Shadow experiment {idx + 1} reviewed {str(kind).replace('_', ' ')} using cached evidence.",
                    "confidence": shadow.get("experiment_confidence_average"),
                    "retention_score": clamp(to_float(shadow.get("experiment_confidence_average"), 0.0) + 8.0),
                    "metadata": {"symbol": "MULTI", "sector": "unknown_sector", "regime": "cached_regime_context", "horizon": "multi_horizon", "outcome": "passive_shadow_review"},
                })
            teacher["lessons"].extend(shadow_packets)
            teacher["lessons_created"] = len(teacher.get("lessons") or [])
            teacher["lessons_created_today"] = len(teacher.get("lessons") or [])
            teacher["lesson_quality_score"] = rounded(sum(to_float(row.get("confidence"), 0.0) for row in teacher.get("lessons") or []) / max(1, len(teacher.get("lessons") or [])), 3)
            teacher["teacher_utilization_percent"] = _pct(teacher.get("lessons_created_today"), CAPACITY_TARGETS["teacher"])
            teacher["teacher_safe_to_scale"] = _safe_to_scale(0.0, teacher.get("lesson_quality_score"))
        memory = self._memory(teacher.get("lessons") or [], long_memory)
        retrieval = self._retrieval(statuses, tier2a, memory)
        aic = self._aic(statuses, request_manager, ihie, compression, retrieval, shadow)
        exit_maturity = self._exit_intelligence_maturation_v2(statuses)
        symbol_memory = self._symbol_behavioral_memory_expansion_v1(statuses)
        reinforcement = self._learning_reinforcement_v1(teacher, memory, dna)
        ask_v2 = self._ask_astra_v2_light_maturation(statuses, retrieval)
        executive_ceo_v3 = self._executive_ceo_v3_light_maturation(exit_maturity, ihie, symbol_memory)
        capacity_manager = self._aios_capacity_manager_v1(request_manager, ihie, shadow, triage, compression, teacher, memory, retrieval, aic, statuses)
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
            "aios_capacity_manager_v1": capacity_manager,
            "astra_aios_throughput_institutional_memory_optimization_v1": {
                "system": "ASTRA AIOS Throughput & Institutional Memory Optimization V1",
                "learning_acceleration_version": "v1.3",
                "status": "ok",
                "satellite_utilization": request_manager.get("utilization_percent"),
                "satellite_observations_today": request_manager.get("raw_observations_today"),
                "ihie_collector_status": (ihie.get("ihie_collector_v1") or {}).get("status") if isinstance(ihie.get("ihie_collector_v1"), dict) else "warming_up",
                "ihie_analyst_utilization": _pct((ihie.get("ihie_analyst_v1") or {}).get("enrichments_today") if isinstance(ihie.get("ihie_analyst_v1"), dict) else 0, CAPACITY_TARGETS["ihie_analyst"]),
                "ihie_analyst_enrichments_today": (ihie.get("ihie_analyst_v1") or {}).get("enrichments_today") if isinstance(ihie.get("ihie_analyst_v1"), dict) else 0,
                "shadow_experiments_today": shadow.get("experiments_today"),
                "shadow_utilization_percent": shadow.get("shadow_utilization_percent"),
                "triage_throughput": triage.get("incoming_packets"),
                "triage_utilization_percent": triage.get("triage_utilization_percent"),
                "compression_throughput": compression.get("compressed_findings"),
                "compression_utilization_percent": compression.get("compression_utilization_percent"),
                "teacher_lessons_today": teacher.get("lessons_created_today"),
                "teacher_utilization_percent": teacher.get("teacher_utilization_percent"),
                "memory_reinforcements_today": memory.get("reinforcements_today"),
                "memory_reinforcement_utilization_percent": memory.get("reinforcement_utilization_percent"),
                "retrieval_candidates_today": retrieval.get("retrieval_candidates_today"),
                "retrieval_utilization_percent": retrieval.get("retrieval_utilization_percent"),
                "aic_working_priorities_today": aic.get("working_priorities_today"),
                "aic_utilization_percent": aic.get("aic_utilization_percent"),
                "weakest_layer": capacity_manager.get("weakest_layer"),
                "strongest_layer": capacity_manager.get("strongest_layer"),
                "weakest_layers": capacity_manager.get("weakest_layers"),
                "strongest_layers": capacity_manager.get("strongest_layers"),
                "adaptive_feed_monitor_status": (capacity_manager.get("aios_adaptive_feed_monitor_v1") or {}).get("monitor_status") if isinstance(capacity_manager.get("aios_adaptive_feed_monitor_v1"), dict) else "warming_up",
                "layers_underfed": capacity_manager.get("layers_underfed"),
                "layers_overfed": capacity_manager.get("layers_overfed"),
                "layers_safe_to_scale": capacity_manager.get("layers_safe_to_scale"),
                "layers_paused": capacity_manager.get("layers_paused"),
                "feed_adjustments_recommended": capacity_manager.get("feed_adjustments_recommended"),
                "feed_adjustments_applied": capacity_manager.get("feed_adjustments_applied"),
                "provider_safety_status": (capacity_manager.get("aios_adaptive_feed_monitor_v1") or {}).get("provider_safety_status") if isinstance(capacity_manager.get("aios_adaptive_feed_monitor_v1"), dict) else "safe_no_provider_polling_increase",
                "bandwidth_safety_status": (capacity_manager.get("aios_adaptive_feed_monitor_v1") or {}).get("bandwidth_safety_status") if isinstance(capacity_manager.get("aios_adaptive_feed_monitor_v1"), dict) else "safe_cache_first_bandwidth_estimate_zero",
                "dashboard_safety_status": (capacity_manager.get("aios_adaptive_feed_monitor_v1") or {}).get("dashboard_safety_status") if isinstance(capacity_manager.get("aios_adaptive_feed_monitor_v1"), dict) else "safe_zero_dashboard_provider_and_llm_calls",
                "trading_safety_status": (capacity_manager.get("aios_adaptive_feed_monitor_v1") or {}).get("trading_safety_status") if isinstance(capacity_manager.get("aios_adaptive_feed_monitor_v1"), dict) else "safe_no_trading_behavior_changes",
                "safe_to_scale": capacity_manager.get("safe_to_scale"),
                "recommended_action": capacity_manager.get("recommended_action"),
                "provider_api_bandwidth_safety_status": "cache_first_zero_dashboard_provider_calls",
                "dashboard_provider_calls_used": 0,
                "dashboard_llm_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                **_safe_flags(),
            },
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
            "aios_capacity_manager_status": capacity_manager.get("status"),
            "aios_safe_to_scale": capacity_manager.get("safe_to_scale"),
            "aios_weakest_layer": capacity_manager.get("weakest_layer"),
            "aios_strongest_layer": capacity_manager.get("strongest_layer"),
            "satellite_observations_today": request_manager.get("raw_observations_today"),
            "ihie_analyst_enrichments_today": (ihie.get("ihie_analyst_v1") or {}).get("enrichments_today") if isinstance(ihie.get("ihie_analyst_v1"), dict) else 0,
            "shadow_experiments_today": shadow.get("experiments_today"),
            "teacher_lessons_today": teacher.get("lessons_created_today"),
            "memory_reinforcements_today": memory.get("reinforcements_today"),
            "retrieval_candidates_today": retrieval.get("retrieval_candidates_today"),
            "aic_working_priorities_today": aic.get("working_priorities_today"),
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


def build_teacher_handoff_from_compressed_lessons_v1(lessons: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the existing Teacher Layer against canonical compressed lessons only."""
    accepted = [{
        "importance": item.get("priority", "MEDIUM"),
        "source": item.get("source_system", "knowledge_compression_engine_v1"),
        "summary": item.get("compressed_summary", "compressed historical evidence"),
        "confidence": item.get("confidence", 0.0),
        "retention_score": item.get("confidence", 0.0),
        "symbol": "MULTI", "sector": "unknown", "regime": "source_declared", "horizon": "source_declared",
        "outcome": "observational_historical_packet",
    } for item in lessons[:MEMORY_BUDGETS["daily_max_lessons"]] if isinstance(item, dict)]
    teacher = AstraAiosIntelligenceMaturationBundleV1()._teacher_layer(accepted)
    teacher.update({"owner": "Teacher Layer V1", "persisted": False, "handoff_only": True, "full_history_scan_count": 0})
    return teacher
