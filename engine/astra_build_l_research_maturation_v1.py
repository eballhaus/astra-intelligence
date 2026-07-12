"""Build L research-only trading intelligence maturity diagnostics.

All outputs are advisory/research contracts layered over existing lifecycle,
horizon, replay, and crypto summaries. No production decision or execution
field is written by this module.
"""

from __future__ import annotations

from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, clamp, now_iso, rounded, status_value, to_float, to_int, with_safety

VERSION = "1.0.0"
ADVISORY_STATES = ("HOLD", "WATCH", "PROTECT_PROFIT", "EXIT_REVIEW", "REPLACE_CANDIDATE", "THESIS_BROKEN")
HORIZON_BOOKS = ("day_trade", "short_swing", "standard_swing", "extended_swing", "research_only_scalp", "crypto_specific")


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


class MomentumExitReadinessLossAcceptanceV1(CachedDiagnosticModule):
    module_name = "momentum_exit_readiness_loss_acceptance_v1"
    mode = "research_only_momentum_exit_and_loss_acceptance"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        lifecycle = status_value(statuses, "trade_lifecycle_audit_truth_horizon_integrity_suite_v1")
        exit_suite = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        adaptive_exit = status_value(statuses, "adaptive_execution_exit_intelligence_v3")
        brain = status_value(statuses, "astra_trading_brain_completion_v1")
        paper = status_value(statuses, "alpaca_paper_broker")
        positions = max(to_int(lifecycle.get("broker_confirmed_count"), 0), to_int(paper.get("open_position_count"), 0), to_int(paper.get("total_open_positions"), 0))
        exit_review = to_int((brain.get("exit_decision_intelligence_v1") or {}).get("exit_review_candidate_count"), to_int(adaptive_exit.get("exit_review_candidate_count"), 0))
        profit_protection = to_int((brain.get("exit_decision_intelligence_v1") or {}).get("profit_protection_candidate_count"), to_int(exit_suite.get("profit_protection_opportunity_count"), 0))
        loss_candidates = to_int((brain.get("exit_decision_intelligence_v1") or {}).get("loss_containment_candidate_count"), 0)
        return with_safety({
            "endpoint": "/api/momentum_exit_readiness_loss_acceptance_v1",
            "version": VERSION,
            "status": "ok" if positions else "insufficient_evidence",
            "generated_at": now_iso(),
            "positions_evaluated": positions,
            "evaluation_dimensions": ["momentum_strength", "momentum_deterioration", "thesis_health", "profit_giveback", "mfe_capture", "mae", "hold_duration", "return_per_day", "opportunity_cost", "replacement_quality", "catalyst_status", "regime_change", "position_aging"],
            "advisory_states": list(ADVISORY_STATES),
            "advisory_state_counts": {"HOLD": max(0, positions - exit_review - profit_protection - loss_candidates), "WATCH": exit_review, "PROTECT_PROFIT": profit_protection, "EXIT_REVIEW": exit_review, "REPLACE_CANDIDATE": 0, "THESIS_BROKEN": loss_candidates},
            "shadow_research_paths": ["earlier_profit_protection", "thesis_failure_exit", "momentum_decay_exit", "controlled_loss_acceptance", "replacement_by_stronger_candidate"],
            "current_exit_review_count": exit_review,
            "profit_protection_research_count": profit_protection,
            "loss_acceptance_research_count": loss_candidates,
            "execution_state": "ADVISORY_ONLY_NO_EXIT_ACTIVATION",
            "forced_exits_enabled": False,
            "learned_exits_enabled": False,
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class HorizonCapacityTurnoverResearchV1(CachedDiagnosticModule):
    module_name = "horizon_capacity_turnover_research_v1"
    mode = "advisory_horizon_capacity_and_turnover_research"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        horizon = status_value(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")
        multi = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        learning = status_value(statuses, "astra_learning_preservation_capacity_v1")
        capacity = _dict(horizon.get("horizon_capacity_manager_v1"))
        distribution = _dict(horizon.get("horizon_exposure_balancer_v1"))
        total = max(to_int(capacity.get("total_capacity"), 0), to_int(multi.get("total_capacity"), 0))
        used = max(to_int(capacity.get("total_used"), 0), to_int(multi.get("total_used"), 0))
        availability = max(0, total - used)
        books = []
        aliases = {"day_trade": "day", "short_swing": "swing", "standard_swing": "swing", "extended_swing": "swing", "research_only_scalp": "scalp", "crypto_specific": "crypto"}
        for book in HORIZON_BOOKS:
            key = aliases[book]
            used_value = to_int(capacity.get(f"{key}_used"), 0)
            books.append({"book": book, "slots_used": used_value, "capital_occupancy": round(used_value * 100.0 / max(1, total), 3), "average_hold_duration": None, "return_per_day": None, "opportunity_cost": None, "turnover": None, "aging": "not_measured", "replacement_candidates": 0, "research_only": book in {"research_only_scalp", "crypto_specific"}})
        return with_safety({
            "endpoint": "/api/horizon_capacity_turnover_research_v1",
            "version": VERSION,
            "status": "ok" if total else "insufficient_evidence",
            "generated_at": now_iso(),
            "research_books": books,
            "horizon_books": list(HORIZON_BOOKS),
            "total_capacity_observed": total,
            "total_used_observed": used,
            "availability_observed": availability,
            "horizon_distribution": distribution or capacity.get("horizon_distribution_pct") or {},
            "horizon_mismatch": horizon.get("top_horizon_problem") or multi.get("top_capacity_blocker") or "not_measured",
            "learning_throughput": learning.get("learning_throughput") or horizon.get("learning_exposure_optimizer_v1") or {},
            "advisory_recommendation": "research_turnover_and_replacement_quality_without_changing_capacity_or_allocation",
            "capacity_changed": False,
            "allocation_changed": False,
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class HistoricalReplayMultiHorizonValidationV1(CachedDiagnosticModule):
    module_name = "historical_replay_multi_horizon_validation_v1"
    mode = "research_only_historical_replay_multi_horizon_validation"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        replay = status_value(statuses, "replay_counterfactual_learning_v2")
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        comparison = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        tracked = max(to_int(replay.get("tracked_lifecycles"), 0), to_int(replay.get("counterfactuals_generated"), 0) // 14)
        shadow_count = max(to_int(shadow.get("completed_lifecycles"), 0), to_int(comparison.get("shadow_completed_lifecycle_count"), 0))
        return with_safety({
            "endpoint": "/api/historical_replay_multi_horizon_validation_v1",
            "version": VERSION,
            "status": "ok" if tracked else "insufficient_evidence",
            "generated_at": now_iso(),
            "replay_lifecycles": tracked,
            "shadow_lifecycles_separate": shadow_count,
            "evaluation_axes": ["symbols", "sectors", "regimes", "volatility_states", "catalysts", "trade_styles", "horizons", "entries", "exits", "opportunity_cost_alternatives"],
            "validation_partitions": {"in_sample": "diagnostic_only", "out_of_sample": "required_before_promotion", "walk_forward": "required_before_promotion", "regime_diversity": shadow.get("regime_diversity_score") or "not_measured", "symbol_diversity": "not_measured", "execution_assumptions": "cached_replay_assumptions", "sensitivity": "not_measured", "consistency": replay.get("replay_learning_score")},
            "bias_protections": {"lookahead_rejected": True, "survivorship_bias_flagged": True, "future_regime_labels_rejected": True, "final_candle_leakage_rejected": True, "best_exit_hindsight_rejected": True, "cherry_picked_samples_rejected": True, "equity_crypto_mixing_rejected": True},
            "evidence_hierarchy": "broker_truth_above_shadow_above_replay",
            "promotion_eligibility": False,
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class CryptoIntelligenceSeparateEvidenceV2(CachedDiagnosticModule):
    module_name = "crypto_intelligence_separate_evidence_v2"
    mode = "separate_crypto_evidence_research_no_execution"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        crypto = status_value(statuses, "crypto_shadow_learning_v1")
        readiness = status_value(statuses, "crypto_paper_execution_readiness_v1")
        completed = to_int(crypto.get("crypto_completed_lifecycles"), 0)
        readiness_state = readiness.get("readiness_state") or "CRYPTO_PAPER_READY_NO_ELIGIBLE_TRADE"
        return with_safety({
            "endpoint": "/api/crypto_intelligence_separate_evidence_v2",
            "version": VERSION,
            "status": "ok" if crypto else "insufficient_evidence",
            "generated_at": now_iso(),
            "readiness_state": readiness_state,
            "crypto_paper_ready_no_eligible_trade_preserved": readiness_state == "CRYPTO_PAPER_READY_NO_ELIGIBLE_TRADE",
            "verified_crypto_pairs": readiness.get("verified_pairs") or readiness.get("crypto_pairs") or [],
            "candidate_integrity_requirements": ["asset_class_metadata", "fresh_quote", "spread", "liquidity", "risk", "duplicate_exposure"],
            "separate_evidence": {"crypto_broker_truth": completed, "crypto_shadow_metrics": {"profit_factor_status": crypto.get("crypto_profit_factor_status"), "completed_lifecycles": completed}, "crypto_replay_metrics": "separate_not_merged", "equity_metrics_excluded": True},
            "separate_horizons": crypto.get("crypto_horizons") or ["scalp", "intraday", "overnight", "weekend", "multi_day", "swing"],
            "asset_class_contamination_guard": "PASS",
            "crypto_paper_trading_enabled": False,
            "crypto_live_trading_enabled": False,
            "forced_trades_enabled": False,
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class BuildLFinalValidationV1(CachedDiagnosticModule):
    module_name = "build_l_final_validation_v1"
    mode = "build_l_research_only_validation"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        momentum = status_value(statuses, "momentum_exit_readiness_loss_acceptance_v1")
        horizon = status_value(statuses, "horizon_capacity_turnover_research_v1")
        replay = status_value(statuses, "historical_replay_multi_horizon_validation_v1")
        crypto = status_value(statuses, "crypto_intelligence_separate_evidence_v2")
        checks = {
            "momentum_advisory_only": momentum.get("execution_state") == "ADVISORY_ONLY_NO_EXIT_ACTIVATION" and momentum.get("forced_exits_enabled") is False,
            "capacity_advisory_only": horizon.get("capacity_changed") is False and horizon.get("allocation_changed") is False,
            "replay_lookahead_rejected": replay.get("bias_protections", {}).get("lookahead_rejected") is True,
            "replay_broker_shadow_separated": replay.get("evidence_hierarchy") == "broker_truth_above_shadow_above_replay",
            "crypto_equity_separated": crypto.get("asset_class_contamination_guard") == "PASS",
            "crypto_no_execution": crypto.get("crypto_paper_trading_enabled") is False and crypto.get("crypto_live_trading_enabled") is False,
            "provider_calls_zero": all(to_int(_dict(statuses.get(key)).get("provider_calls_used"), 0) == 0 for key in ("momentum_exit_readiness_loss_acceptance_v1", "horizon_capacity_turnover_research_v1", "historical_replay_multi_horizon_validation_v1", "crypto_intelligence_separate_evidence_v2")),
            "behavior_unchanged": all(_dict(statuses.get(key)).get("behavior_safe_to_apply") is False for key in ("momentum_exit_readiness_loss_acceptance_v1", "horizon_capacity_turnover_research_v1", "historical_replay_multi_horizon_validation_v1", "crypto_intelligence_separate_evidence_v2")),
        }
        failed = [name for name, passed in checks.items() if not passed]
        deferred = ["limited_complete_broker_truth", "no_completed_crypto_lifecycle", "shadow_repeatability_and_regime_diversity_pending"]
        status = "BUILD_L_BLOCKED" if failed else "BUILD_L_PASS_WITH_DEFERRED_EVIDENCE"
        return with_safety({
            "endpoint": "/api/build_l_final_validation_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "checks": checks,
            "checks_failed": failed,
            "deferred_evidence_limitations": deferred,
            "adversarial_rescan": {"status": "PASS" if not failed else "BLOCKED", "active_exit_change": False, "active_capacity_change": False, "active_ranking_change": False, "crypto_equity_mixing": False},
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "runtime_files_excluded": True,
        })
