from __future__ import annotations

import math
import time
from collections import Counter
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


HORIZONS = ("scalp", "day_trade", "swing_trade")


def _safe_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
        "human_review_required": True,
        "cache_first": True,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "paper_execution_changed": False,
        "forced_trades_enabled": False,
        "forced_exits_enabled": False,
        "learned_exits_enabled": False,
        "fixed_horizon_caps_enabled": False,
        "forced_horizon_quotas_enabled": False,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
        "dashboard_endpoint_storm_created": False,
        "api_calls_used": 0,
    }


def _normalize_horizon(value: Any) -> str:
    raw = text(value, "unknown").lower().replace("-", "_").replace(" ", "_")
    if "scalp" in raw or raw in {"15m", "30m", "45m", "60m"}:
        return "scalp"
    if "day" in raw or "intraday" in raw or "eod" in raw or raw in {"2h", "4h"}:
        return "day_trade"
    if "swing" in raw or "overnight" in raw or "multi_day" in raw or raw.endswith("d"):
        return "swing_trade"
    return "unknown"


def _entropy_score(counts: dict[str, int]) -> float:
    total = sum(max(0, int(counts.get(key, 0))) for key in HORIZONS)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for key in HORIZONS:
        share = max(0, int(counts.get(key, 0))) / total
        if share > 0:
            entropy -= share * math.log(share)
    return rounded(entropy / math.log(len(HORIZONS)) * 100.0, 3)


class AstraLearningPreservationCapacityV1(CachedDiagnosticModule):
    """Advisory learning-throughput, horizon-diversity, and lifecycle integrity suite."""

    module_name = "astra_learning_preservation_capacity_v1"
    mode = "paper_only_cache_first_learning_preservation_advisory"

    @staticmethod
    def _horizon_payload(statuses: dict[str, Any]) -> dict[str, Any]:
        return status_value(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")

    @staticmethod
    def _lifecycle_payload(statuses: dict[str, Any]) -> dict[str, Any]:
        return status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")

    def _learning_throughput(self, statuses: dict[str, Any], horizon: dict[str, Any]) -> dict[str, Any]:
        adaptive = status_value(statuses, "astra_adaptive_learning_v1")
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        throughput = status_value(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        recovery = status_value(statuses, "astra_recovery_center_v1")
        protection = dict(recovery.get("learning_protection") or {})
        accelerator = dict(adaptive.get("learning_accelerator_v2") or {})
        reviewed = max(
            to_int(throughput.get("reviewed_today"), 0),
            to_int(shadow.get("shadow_recommendations_reviewed"), 0),
            to_int(shadow.get("shadow_opportunities"), 0),
        )
        eligible = max(to_int(throughput.get("eligible_today"), 0), to_int(horizon.get("practice_candidate_count"), 0))
        executed = max(to_int(throughput.get("submitted_today"), 0), to_int(horizon.get("selected_horizon_count"), 0))
        closed = max(to_int(throughput.get("closed_trades_today"), 0), to_int(horizon.get("freed_slots_today"), 0))
        evidence = max(
            to_int(shadow.get("evidence_count"), 0),
            to_int(accelerator.get("evidence_count"), 0),
            to_int(dict(adaptive.get("replay_expansion_v1") or {}).get("replay_count"), 0),
            sum(
                to_int(horizon.get(key), 0)
                for key in ("scalp_learning_events", "day_learning_events", "swing_learning_events")
            ),
            to_int(status_value(statuses, "unified_learning_diagnostics_v1").get("evidence_count"), 0),
        )
        age_hours = max(0.0, to_float(protection.get("estimated_hours_offline"), 0.0))
        utilization = rounded(executed / max(1, eligible, executed) * 100.0, 3)
        participation = rounded(max(eligible, executed) / max(1, reviewed) * 100.0, 3)
        turnover = rounded(closed / max(1, to_int(horizon.get("broker_confirmed_count"), 0)) * 100.0, 3)
        health = clamp(
            100.0
            - min(45.0, age_hours * 12.0)
            - max(0.0, 25.0 - participation) * 0.7
            - max(0.0, 15.0 - utilization) * 0.5
        )
        return {
            "module": "Learning Throughput Preservation Engine V1",
            "status": "ok" if evidence or reviewed else "insufficient_evidence",
            "learning_throughput_score": rounded(health, 3),
            "evidence_count": evidence,
            "evidence_age_hours": rounded(age_hours, 3),
            "evidence_freshness": "fresh" if age_hours <= 2 else "aging" if age_hours <= 6 else "stale",
            "opportunities_reviewed": reviewed,
            "opportunities_eligible": eligible,
            "opportunities_executed": executed,
            "trades_closed_today": closed,
            "trade_turnover_pct": turnover,
            "opportunity_utilization_pct": utilization,
            "learning_participation_pct": participation,
            "fresh_evidence_flow_preserved": bool(age_hours <= 3 and (evidence > 0 or reviewed > 0)),
            "primary_throughput_blocker": text(
                first(throughput.get("top_blocker"), horizon.get("horizon_participation_blocker"), "insufficient_fresh_candidate_participation")
            ),
            "recommended_action": "review_underused_existing_candidate_flow_without_changing_gates",
            **_safe_flags(),
        }

    def _horizon_diversity(self, horizon: dict[str, Any]) -> dict[str, Any]:
        distribution = dict(
            horizon.get("horizon_distribution")
            or horizon.get("paper_horizon_distribution")
            or horizon.get("current_horizon_distribution")
            or {}
        )
        total = max(0, to_int(horizon.get("total_used"), to_int(horizon.get("broker_confirmed_count"), 0)))
        slot_keys = {
            "scalp": "scalp_slots_used",
            "day_trade": "day_trade_slots_used",
            "swing_trade": "swing_slots_used",
        }
        if any(key in horizon for key in slot_keys.values()):
            counts = {name: to_int(horizon.get(key), 0) for name, key in slot_keys.items()}
        else:
            counts = {
                name: int(round(to_float(distribution.get(name), 0.0) * total / 100.0))
                for name in HORIZONS
            }
            if total > 0 and sum(counts.values()) != total:
                dominant_name = max(distribution, key=lambda key: to_float(distribution.get(key), 0.0), default="swing_trade")
                if dominant_name in counts:
                    counts[dominant_name] += total - sum(counts.values())
        total = max(sum(counts.values()), total)
        if total > 0 and sum(counts.values()) == 0:
            counts["swing_trade"] = total
        shares = {key: rounded(value / max(1, sum(counts.values())) * 100.0, 3) for key, value in counts.items()}
        dominant = max(shares, key=shares.get) if sum(counts.values()) else "unknown"
        ordered = sorted(shares.items(), key=lambda item: item[1], reverse=True)
        dominance_gap = rounded(ordered[0][1] - ordered[1][1], 3) if len(ordered) > 1 else 0.0
        monopolized = bool(dominant in HORIZONS and shares[dominant] >= 60.0 and dominance_gap >= 25.0)
        swing_saturated = bool(monopolized and dominant == "swing_trade")
        exposure = dict((horizon.get("modules") or {}).get("horizon_exposure_balancer_v1") or {})
        learning_events = {
            "scalp": to_int(first(horizon.get("scalp_learning_events"), exposure.get("scalp_learning_events"), 0), 0),
            "day_trade": to_int(first(horizon.get("day_learning_events"), exposure.get("day_learning_events"), 0), 0),
            "swing_trade": to_int(first(horizon.get("swing_learning_events"), exposure.get("swing_learning_events"), 0), 0),
        }
        weakest = min(learning_events, key=learning_events.get) if any(learning_events.values()) else min(shares, key=shares.get)
        return {
            "module": "Dynamic Horizon Allocation & Diversity Engine V1",
            "status": "ok" if total > 0 else "insufficient_evidence",
            "broker_confirmed_positions": to_int(horizon.get("broker_confirmed_count"), total),
            "horizon_counts": counts,
            "horizon_distribution_pct": shares,
            "horizon_diversity_score": _entropy_score(counts),
            "dominant_horizon": dominant,
            "dominance_gap_pct": dominance_gap,
            "horizon_monopolization_detected": monopolized,
            "swing_saturation_detected": swing_saturated,
            "underdeveloped_horizon": weakest,
            "learning_events_by_horizon": learning_events,
            "protected_learning_focus": weakest if weakest in {"scalp", "day_trade"} else "maintain_adaptive_mix",
            "allocation_method": "relative_dominance_and_evidence_participation_not_fixed_caps",
            "recommended_action": (
                f"prefer_{weakest}_evidence_when_candidates_already_pass_existing_gates"
                if weakest in HORIZONS
                else "maintain_adaptive_horizon_learning"
            ),
            **_safe_flags(),
        }

    def _position_lifecycle_audit(self, statuses: dict[str, Any], horizon: dict[str, Any]) -> dict[str, Any]:
        lifecycle = self._lifecycle_payload(statuses)
        rows = list(lifecycle.get("position_audit_rows") or lifecycle.get("truth_validation_rows") or [])
        if not rows:
            rotation = dict((horizon.get("modules") or {}).get("adaptive_portfolio_rotation_engine_v1") or {})
            rows = list(rotation.get("rotation_review_positions") or rotation.get("top_stale_positions") or [])
        audited: list[dict[str, Any]] = []
        counts = Counter()
        for raw in rows[:40]:
            if not isinstance(raw, dict):
                continue
            continuation = to_float(raw.get("continuation_probability"), 50.0)
            decay = to_float(first(raw.get("catalyst_decay_risk"), raw.get("catalyst_decay"), 45.0), 45.0)
            thesis = to_float(raw.get("thesis_health"), max(0.0, 100.0 - decay))
            giveback = to_float(first(raw.get("giveback_risk"), raw.get("stale_score"), 0.0), 0.0)
            if raw.get("should_have_sold") or (thesis < 30 and continuation < 35):
                state = "thesis_broken"
            elif raw.get("should_have_converted_horizon") or to_float(raw.get("stale_score"), 0.0) >= 65:
                state = "overheld"
            elif raw.get("should_have_profit_protected") or giveback >= 60 or thesis < 55:
                state = "watch"
            else:
                state = "healthy"
            counts[state] += 1
            audited.append(
                {
                    "symbol": text(raw.get("symbol"), "UNKNOWN").upper(),
                    "horizon": _normalize_horizon(first(raw.get("normalized_horizon"), raw.get("horizon"), "unknown")),
                    "position_age_hours": rounded(first(raw.get("elapsed_hold_hours"), to_float(raw.get("position_age"), 0.0) * 24.0, 0.0), 3),
                    "lifecycle_status": state,
                    "thesis_health": rounded(thesis, 3),
                    "continuation_probability": rounded(continuation, 3),
                    "catalyst_decay_risk": rounded(decay, 3),
                    "giveback_risk": rounded(giveback, 3),
                    "review_reason": text(first(raw.get("truth_explanation"), raw.get("rotation_reason"), raw.get("exit_blocker"), "monitor")),
                }
            )
        most_urgent = next(
            (row for row in audited if row["lifecycle_status"] == "thesis_broken"),
            next((row for row in audited if row["lifecycle_status"] == "overheld"), audited[0] if audited else {}),
        )
        broker_count = to_int(horizon.get("broker_confirmed_count"), to_int(lifecycle.get("total_active_positions"), len(audited)))
        detail_gap = max(0, broker_count - len(audited))
        if detail_gap:
            counts["watch"] += detail_gap
        return {
            "module": "Position Lifecycle Auditor V1",
            "status": "ok" if audited or broker_count else "insufficient_evidence",
            "active_position_source": text(horizon.get("active_position_source"), "broker_confirmed_alpaca_paper"),
            "broker_confirmed_count": broker_count,
            "lifecycle_rows_audited": max(len(audited), to_int(horizon.get("lifecycle_rows_audited"), 0)),
            "classification_counts": {key: int(counts.get(key, 0)) for key in ("healthy", "watch", "overheld", "thesis_broken")},
            "position_detail_rows": len(audited),
            "position_detail_coverage_pct": rounded(len(audited) / max(1, broker_count) * 100.0, 3),
            "broker_positions_pending_detail": detail_gap,
            "pending_detail_classification": "watch",
            "position_rows": audited,
            "most_urgent_position": most_urgent,
            "biggest_exit_blocker": text(lifecycle.get("biggest_exit_blocker"), "insufficient_position_detail"),
            "broker_truth_wins": True,
            **_safe_flags(),
        }

    def _capacity_recovery(self, horizon: dict[str, Any]) -> dict[str, Any]:
        compaction = dict(horizon.get("stale_workflow_compaction_v1") or {})
        stale_hidden = max(
            to_int(horizon.get("stale_internal_rows_hidden"), 0),
            to_int(horizon.get("stale_rows_hidden"), 0),
            to_int(compaction.get("stale_rows_hidden"), 0),
        )
        archived = max(to_int(horizon.get("archived_workflow_rows"), 0), to_int(compaction.get("archived_workflow_rows"), 0))
        unmatched_internal = list(horizon.get("unmatched_internal_symbols") or [])
        duplicates = max(0, to_int(compaction.get("stale_rows_compacted"), 0) - len(unmatched_internal))
        quarantined = max(stale_hidden, archived, len(unmatched_internal))
        return {
            "module": "Capacity Recovery & Stale Workflow Cleanup V1",
            "status": "ok",
            "active_workflow_rows": to_int(first(horizon.get("active_workflow_rows"), compaction.get("active_workflow_rows"), 0), 0),
            "stale_workflow_rows_detected": quarantined,
            "stale_workflow_rows_hidden": stale_hidden,
            "orphaned_workflow_rows": len(unmatched_internal),
            "duplicate_workflow_rows": duplicates,
            "quarantined_workflow_rows": quarantined,
            "archived_workflow_rows": archived,
            "quarantine_effective": bool(quarantined == 0 or stale_hidden >= quarantined or archived >= quarantined),
            "stale_rows_affect_capacity": False,
            "stale_rows_affect_diagnostics": False,
            "stale_rows_affect_learning": False,
            "stale_rows_affect_horizon_balancing": False,
            "full_history_preserved": bool(compaction.get("archive_integrity", True)),
            "archive_retrieval_health": text(compaction.get("archive_retrieval_health"), "healthy"),
            "capacity_recovered_slots": stale_hidden,
            "cleanup_method": "existing_broker_truth_filter_and_workflow_compaction",
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        horizon = self._horizon_payload(statuses)
        throughput = self._learning_throughput(statuses, horizon)
        diversity = self._horizon_diversity(horizon)
        lifecycle = self._position_lifecycle_audit(statuses, horizon)
        cleanup = self._capacity_recovery(horizon)
        status = "ok" if any(module.get("status") == "ok" for module in (throughput, diversity, lifecycle, cleanup)) else "insufficient_evidence"
        out = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Tier 1A - Learning Preservation, Horizon Intelligence & Capacity Stabilization Suite V1",
            "status": status,
            "mode": self.mode,
            "generated_at": now_iso(),
            "learning_throughput_preservation_engine_v1": throughput,
            "dynamic_horizon_allocation_diversity_engine_v1": diversity,
            "position_lifecycle_auditor_v1": lifecycle,
            "capacity_recovery_stale_workflow_cleanup_v1": cleanup,
            "summary": {
                "learning_throughput_score": throughput.get("learning_throughput_score"),
                "fresh_evidence_flow_preserved": throughput.get("fresh_evidence_flow_preserved"),
                "horizon_diversity_score": diversity.get("horizon_diversity_score"),
                "swing_saturation_detected": diversity.get("swing_saturation_detected"),
                "underdeveloped_horizon": diversity.get("underdeveloped_horizon"),
                "broker_confirmed_count": lifecycle.get("broker_confirmed_count"),
                "lifecycle_rows_audited": lifecycle.get("lifecycle_rows_audited"),
                "lifecycle_classification_counts": lifecycle.get("classification_counts"),
                "stale_workflow_rows_hidden": cleanup.get("stale_workflow_rows_hidden"),
                "quarantine_effective": cleanup.get("quarantine_effective"),
                "next_recommended_action": diversity.get("recommended_action"),
            },
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(out)
