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


class AstraAiosIntelligenceMaturationBundleV1(CachedDiagnosticModule):
    """Astra Intelligence Operating System V1 coordinator.

    This module organizes existing Astra intelligence into the requested AIOS flow.
    It does not gather provider data, alter Shadow logic, or change any trading
    behavior. It formalizes budgets, DNA, triage, compression, teaching, memory,
    retrieval, AIC coordination, and validation using cached subsystem outputs.
    """

    module_name = "astra_aios_intelligence_maturation_bundle_v1"
    mode = "advisory_cache_first_aios_intelligence_maturation"

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
            "supports_retrieval_by": ["symbol", "sector", "regime", "catalyst", "exit_pattern", "horizon", "confidence", "outcome", "similarity"],
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
            "shadow_observes": ["satellite_outputs", "market_regimes", "portfolio_exposures", "macro_environments", "exit_intelligence", "symbol_behavioral_memory"],
            "shadow_executes": False,
            "shadow_overrides_paper": False,
            "shadow_submits_orders": False,
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
        maturity_score = rounded(sum([
            to_float(request_manager.get("average_satellite_confidence"), 0.0),
            to_float(ihie.get("confidence"), 0.0),
            to_float(aic.get("aic_coordination_score"), 0.0),
            70.0 if triage.get("status") == "ok" else 45.0,
            70.0 if memory.get("status") == "ok" else 45.0,
        ]) / 5.0, 3)
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
            "aios_maturity_score": maturity_score,
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
                "Long-Term Memory Symbol Retrieval",
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
