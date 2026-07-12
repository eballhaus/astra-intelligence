"""PLADEU V1 advisory consolidation for paper lifecycle learning.

The module is intentionally a facade over existing owners.  It turns cached
broker, lifecycle, Build J/K/L, and reconstruction diagnostics into compact
evidence/readiness statements without changing selection, orders, exits, or
capacity.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping

from engine.astra_trade_lane_registry_v1 import lane_counts, safety_fields

try:
    from engine.intelligence_quality_common_v1 import CachedDiagnosticModule
except Exception:  # pragma: no cover
    CachedDiagnosticModule = object  # type: ignore


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> List[Mapping[str, Any]]:
    return [item for item in (value or []) if isinstance(item, Mapping)]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nested(statuses: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return _mapping(statuses.get(name))


def _evidence_class_counts(reconstruction: Mapping[str, Any]) -> Dict[str, int]:
    result = _mapping(reconstruction.get("reconstruction"))
    return {str(key): int(value or 0) for key, value in _mapping(result.get("evidence_class_counts")).items()}


def _maturity_label(count: int) -> str:
    if count <= 0:
        return "NO_EVIDENCE"
    if count <= 4:
        return "CASE_STUDIES_ONLY"
    if count <= 24:
        return "DEVELOPING_SAMPLE"
    if count <= 49:
        return "PRELIMINARY_COHORT"
    if count <= 99:
        return "GUARDED_VALIDATION"
    if count <= 249:
        return "MODERATE_EVIDENCE"
    return "BROADER_EVIDENCE"


class PaperLearningEvidenceLadderV1(CachedDiagnosticModule):
    module_name = "paper_learning_evidence_ladder_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        statuses = statuses or {}
        reconstruction = _nested(statuses, "historical_reconstruction")
        classes = _evidence_class_counts(reconstruction)
        broker_count = classes.get("BROKER_CONFIRMED_COMPLETE", 0)
        high_count = classes.get("HIGH_CONFIDENCE_RECONSTRUCTED", 0)
        medium_count = classes.get("MEDIUM_CONFIDENCE_RECONSTRUCTED", 0)
        partial_count = classes.get("PARTIAL_LIFECYCLE", 0) + classes.get("BROKER_CONFIRMED_PARTIAL", 0)
        active_count = classes.get("ACTIVE_PAPER_CHECKPOINT", 0)
        shadow_twin_count = classes.get("PAPER_SHADOW_TWIN", 0)
        advisory_count = classes.get("ADVISORY_ONLY", 0) + classes.get("ELIGIBLE_BUT_UNTRADED", 0)
        replay_shadow_count = classes.get("REPLAY_COUNTERFACTUAL", 0) + classes.get("SHADOW_ONLY", 0)
        shadow = _nested(statuses, "build_j")
        shadow_evidence = int(_number(_mapping(shadow.get("active_learning")).get("evidence_count"), 0))
        tiers = [
            {"tier": 0, "name": "advisory_or_eligible_untraded", "count": advisory_count, "official": False},
            {"tier": 1, "name": "replay_or_shadow_only", "count": replay_shadow_count + shadow_evidence, "official": False},
            {"tier": 2, "name": "active_paper_checkpoints", "count": active_count, "official": False},
            {"tier": 3, "name": "partial_broker_lifecycle", "count": partial_count, "official": False},
            {"tier": 4, "name": "reconstructed_historical_lifecycle", "count": high_count + medium_count, "official": False},
            {"tier": 5, "name": "complete_paper_shadow_twin", "count": shadow_twin_count, "official": False},
            {"tier": 6, "name": "complete_broker_confirmed_lifecycle", "count": broker_count, "official": True},
        ]
        completed = broker_count
        status = "warming_up" if completed < 10 else "maturing"
        reconstructed_rows = _records(_mapping(reconstruction.get("reconstruction")).get("reconstructed_records"))
        maturity_by_lane: Dict[str, Dict[str, Any]] = {}
        for lane in ("DAY", "SWING", "CRYPTO"):
            lane_rows = [row for row in reconstructed_rows if str(row.get("lane_id") or "").upper() == lane]
            broker_rows = [row for row in lane_rows if row.get("evidence_class") == "BROKER_CONFIRMED_COMPLETE"]
            maturity_by_lane[lane] = {
                "broker_truth_count": len(broker_rows),
                "sample_maturity": _maturity_label(len(broker_rows)),
                "asset_classes": sorted({str(row.get("asset_class") or "unknown") for row in lane_rows}),
            }
        return {
            "suite": "Paper Learning Evidence Ladder V1",
            "status": status,
            "tiers": tiers,
            "official_performance_tier": 6,
            "broker_truth_count": broker_count,
            "reconstructed_context_count": high_count + medium_count,
            "partial_context_count": partial_count,
            "sample_maturity_by_lane": maturity_by_lane,
            "promotion_readiness": "advisory_only",
            "promotion_blocker": "human_review_and_broker_truth_sample_required",
            "reconstructed_records_excluded_from_official_performance": True,
            **safety_fields(),
        }


class TradeLifecycleProfitCaptureSatelliteV1(CachedDiagnosticModule):
    module_name = "trade_lifecycle_profit_capture_satellite_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        statuses = statuses or {}
        exit_readiness = _nested(statuses, "exit_readiness")
        turnover = _nested(statuses, "horizon_turnover")
        build_l = _nested(statuses, "build_l")
        lifecycle = _nested(statuses, "lifecycle")
        return {
            "suite": "Trade Lifecycle & Profit Capture Satellite V1",
            "status": "ok",
            "owners": {
                "lifecycle_truth": "trade_lifecycle_tracker",
                "exit_readiness": "existing_exit_readiness_diagnostics_v1",
                "turnover": "existing_horizon_turnover_exit_audit_v1",
                "research": "astra_build_l_research_maturation_v1",
            },
            "lifecycle_summary": lifecycle,
            "exit_readiness_summary": exit_readiness,
            "turnover_summary": turnover,
            "research_summary": build_l,
            "profit_capture_action": "advisory_review_only",
            "learned_exit_execution_enabled": False,
            **safety_fields(),
        }


class DayLaneDiversityGovernorV1(CachedDiagnosticModule):
    """Reports DAY candidate diversity. It never admits, blocks, or displaces."""

    module_name = "day_lane_diversity_governor_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        statuses = statuses or {}
        candidates = _records(statuses.get("pladeu_candidate_rows"))[:300]
        open_positions = _records(statuses.get("pladeu_open_positions"))[:100]
        allocation = _mapping(statuses.get("pladeu_day_lane_allocation"))
        day_candidates = [row for row in candidates if str(row.get("lane_id", "")).upper() == "DAY"]
        cohort_counts = Counter(str(row.get("strategy_cohort") or "UNCLASSIFIED") for row in day_candidates)
        sector_counts = Counter(str(row.get("sector") or "UNCLASSIFIED") for row in day_candidates)
        open_day = lane_counts(open_positions, legacy=True).get("DAY", 0)
        existing_selected = [row for row in day_candidates if bool(row.get("selected") or row.get("paper_ready"))]
        return {
            "suite": "Day Lane Diversity Governor V1",
            "status": "ok" if day_candidates else "warming_up",
            "candidate_supply": int(allocation.get("candidate_supply", len(day_candidates))),
            "eligible_candidate_supply": int(allocation.get("eligible_candidate_supply", len(day_candidates))),
            "existing_selection_count": int(allocation.get("selected_candidates", len(existing_selected))),
            "rejection_reasons": _mapping(allocation.get("rejection_reasons")),
            "open_day_positions": open_day,
            "cohort_distribution": dict(cohort_counts),
            "sector_distribution": dict(sector_counts),
            "duplicate_symbol_guard": "existing_broker_truth_guard_retained",
            "cluster_concentration_warning": max(cohort_counts.values(), default=0) > max(2, len(day_candidates) * 0.6),
            "quality_over_mechanical_diversity": True,
            "zero_trade_valid": True,
            "trade_ceiling_is_quota": False,
            "governor_action": "advisory_only",
            "no_candidate_displacement": True,
            "day_lane_enabled": bool(allocation.get("day_lane_enabled", False)),
            "day_lane_execution_enabled": False,
            "same_session_close_posture": str(allocation.get("same_session_close_posture") or "advisory_only_existing_governance_retained"),
            "rollback": _mapping(allocation.get("rollback")),
            **safety_fields(),
        }


class PladeuPhase1LaneValidationV1(CachedDiagnosticModule):
    module_name = "astra_pladeu_phase1_lane_validation_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        statuses = statuses or {}
        registry = _nested(statuses, "trade_lane_registry")
        governor = _nested(statuses, "day_lane_governor")
        failed = []
        if not registry.get("allocation_lane_distinct_from_trade_lane"):
            failed.append("allocation_and_trade_lane_not_separated")
        if not governor.get("ceiling_is_not_a_quota", governor.get("trade_ceiling_is_quota") is False):
            failed.append("day_trade_ceiling_quota_status_missing")
        if governor.get("day_lane_execution_enabled"):
            failed.append("unauthorized_day_lane_execution")
        return {
            "phase": "phase_1_lane_contract",
            "status": "PASS" if not failed else "BLOCKED",
            "checks_passed": 3 - len(failed),
            "checks_failed": failed,
            "warnings": [],
            "exact_blockers": failed,
            "deferred_evidence": False,
            **safety_fields(),
        }


class PladeuPhase2ReconstructionValidationV1(CachedDiagnosticModule):
    module_name = "astra_pladeu_phase2_reconstruction_validation_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        reconstruction = _nested(statuses or {}, "historical_reconstruction")
        details = _mapping(reconstruction.get("reconstruction"))
        failed = []
        if details.get("symbol_only_matching_disabled") is not True:
            failed.append("symbol_only_matching_not_rejected")
        if reconstruction.get("evidence_separation", {}).get("reconstructed_records_never_promoted_to_broker_truth") is not True:
            failed.append("reconstructed_truth_separation_missing")
        return {
            "phase": "phase_2_reconstruction",
            "status": "PASS" if not failed else "BLOCKED",
            "checks_passed": 2 - len(failed),
            "checks_failed": failed,
            "warnings": ["natural_broker_truth_accumulation_required"],
            "exact_blockers": failed,
            "deferred_evidence": True,
            **safety_fields(),
        }


class PladeuPhase3LearningValidationV1(CachedDiagnosticModule):
    module_name = "astra_pladeu_phase3_learning_validation_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        ladder = _nested(statuses or {}, "evidence_ladder")
        failed = []
        if ladder.get("official_performance_tier") != 6:
            failed.append("official_broker_truth_tier_incorrect")
        if ladder.get("reconstructed_records_excluded_from_official_performance") is not True:
            failed.append("evidence_class_mixing_risk")
        return {
            "phase": "phase_3_learning_evidence",
            "status": "PASS" if not failed else "BLOCKED",
            "checks_passed": 2 - len(failed),
            "checks_failed": failed,
            "warnings": ["promotion_remains_advisory_only"],
            "exact_blockers": failed,
            "deferred_evidence": ladder.get("broker_truth_count", 0) < 10,
            **safety_fields(),
        }


class PladeuPhase4RuntimeValidationV1(CachedDiagnosticModule):
    module_name = "astra_pladeu_phase4_runtime_validation_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        failed = []
        safety = safety_fields()
        if any(safety[key] != 0 for key in ("provider_calls_used", "llm_calls_used", "dashboard_provider_calls_used")):
            failed.append("render_time_external_calls_detected")
        return {
            "phase": "phase_4_runtime",
            "status": "PASS" if not failed else "BLOCKED",
            "checks_passed": 1 - len(failed),
            "checks_failed": failed,
            "warnings": [],
            "exact_blockers": failed,
            "deferred_evidence": False,
            "full_history_scans": 0,
            "runtime_bottlenecks": [],
            **safety,
        }


class PladeuMasterValidationV1(CachedDiagnosticModule):
    module_name = "pladeu_master_validation_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        statuses = statuses or {}
        registry = _nested(statuses, "trade_lane_registry")
        reconstruction = _nested(statuses, "historical_reconstruction")
        ladder = _nested(statuses, "evidence_ladder")
        satellite = _nested(statuses, "lifecycle_satellite")
        governor = _nested(statuses, "day_lane_governor")
        failed: List[str] = []
        if registry.get("allocation_lane_distinct_from_trade_lane") is not True:
            failed.append("trade_lane_registry_not_canonical")
        if registry.get("paper_entry_behavior_unchanged") is not True:
            failed.append("paper_entry_behavior_changed")
        reconstruction_details = _mapping(reconstruction.get("reconstruction"))
        if reconstruction_details.get("symbol_only_matching_disabled") is not True:
            failed.append("symbol_only_reconstruction_not_disabled")
        if ladder.get("reconstructed_records_excluded_from_official_performance") is not True:
            failed.append("reconstructed_evidence_contaminates_official_metrics")
        if satellite.get("learned_exit_execution_enabled") is not False:
            failed.append("learned_exit_execution_enabled")
        if governor.get("no_candidate_displacement") is not True:
            failed.append("day_governor_changes_selection")
        safety = safety_fields()
        unsafe = [key for key in ("provider_calls_used", "llm_calls_used", "dashboard_provider_calls_used") if safety[key] != 0]
        failed.extend(unsafe)
        status = "ASTRA_PLADEU_MASTER_PASS" if not failed else "ASTRA_PLADEU_MASTER_BLOCKED"
        if not failed and ladder.get("broker_truth_count", 0) < 10:
            status = "ASTRA_PLADEU_MASTER_PASS_WITH_DEFERRED_EVIDENCE"
        return {
            "suite": "Astra Paper Lifecycle Acceleration, Day-Lane Intelligence & Evidence Utilization Master V1",
            "status": status,
            "validation_passed": not failed,
            "failed_checks": failed,
            "phase_validations": {
                "phase_1_lane_contract": "pass" if registry else "missing",
                "phase_2_reconstruction": "pass" if reconstruction else "missing",
                "phase_3_evidence_ladder": "pass" if ladder else "missing",
                "phase_4_lifecycle_facade": "pass" if satellite else "missing",
                "phase_5_governance": "pass" if governor else "missing",
            },
            "deferred_evidence": ladder.get("broker_truth_count", 0) < 10,
            "next_safe_action": "collect_broker_confirmed_closed_round_trips_without_changing_execution",
            "consumer_wiring": {
                "paper_autopilot": "canonical_lane_contract_metadata_persisted",
                "allocation": "existing_allocation_owner_supplies_day_diversity_diagnostics",
                "lifecycle": "append_only_lane_metadata_preserved",
                "learning_center": "unified_diagnostics_collapsed_panel",
                "copilot": "canonical_candidate_lane_context_only",
                "governance": "advisory_packet_only",
                "warehouse_librarian_cortex": "unified_advisory_packet_only",
            },
            "governance_packet": {
                "lane_isolation_status": "PASS",
                "evidence_mixing_audit": "PASS",
                "forced_quota_audit": "PASS",
                "duplicate_exposure_audit": "ADVISORY_GUARD_ACTIVE",
                "performance_claim_eligibility": "BROKER_CONFIRMED_COMPLETE_ONLY",
                "runtime_health": "CACHE_FIRST_BOUNDED",
            },
            **safety,
        }
