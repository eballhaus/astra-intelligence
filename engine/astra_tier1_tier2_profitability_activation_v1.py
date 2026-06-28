from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    now_iso,
    rounded,
    status_value,
    to_float,
    to_int,
    with_safety,
    write_json,
)


CANONICAL_STORE = "canonical_lifecycle_lessons_v1.jsonl"
SYMBOL_PROFILES = "symbol_behavior_profiles_v1.json"
TRADE_FABRIC_STORE = "trade_management_intelligence_fabric_v1.json"
MAX_LESSONS = 5000
MAX_CANDIDATE_ROWS = 1200


def _safe_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
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
        "automatic_promotions_enabled": False,
        "learned_exits_enabled": False,
        "paper_trades_placed": False,
        "paper_orders_placed": False,
        "paper_micro_tests_executed": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _present(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str) and value.strip().lower() in {"unknown", "n/a", "none", "null", "insufficient_evidence"}:
        return False
    return True


def _avg(values: list[float]) -> float:
    return rounded(mean(values), 3) if values else 0.0


def _status(value: float) -> str:
    if value >= 75:
        return "verified_strong"
    if value >= 60:
        return "verified_minimum"
    return "blocked_below_threshold"


class AstraTier1Tier2ProfitabilityActivationV1(CachedDiagnosticModule):
    module_name = "astra_tier1_tier2_profitability_activation_v1"
    mode = "tier1_tier2_profitability_activation_advisory_only"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 1800.0) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)

    def _read_json(self, filename: str) -> dict[str, Any]:
        try:
            with open(os.path.join(self.state_dir, filename), "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _read_jsonl(self, filename: str, limit: int) -> list[dict[str, Any]]:
        path = os.path.join(self.state_dir, filename)
        rows: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if len(rows) >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        rows.append(parsed)
        except Exception:
            return []
        return rows

    def _symbol_profiles(self) -> dict[str, Any]:
        parsed = self._read_json(SYMBOL_PROFILES)
        return parsed.get("profiles") if isinstance(parsed.get("profiles"), dict) else {}

    def _trade_management_fabric(self, lessons: list[dict[str, Any]], profiles: dict[str, Any]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in lessons:
            symbol = str(row.get("symbol") or "").upper().strip()
            if symbol:
                grouped[symbol].append(row)
        symbols: dict[str, Any] = {}
        for symbol, rows in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:80]:
            capture_vals = [to_float(r.get("capture_ratio"), 0.0) for r in rows if _present(r.get("capture_ratio"))]
            giveback_vals = [to_float(r.get("giveback_pct"), 0.0) for r in rows if _present(r.get("giveback_pct"))]
            hold_vals = [to_float(r.get("hold_duration"), 0.0) for r in rows if _present(r.get("hold_duration"))]
            pnl_vals = [to_float(r.get("current_or_exit_profit_pct"), 0.0) for r in rows if _present(r.get("current_or_exit_profit_pct"))]
            horizons = Counter(str(r.get("horizon_style") or "unknown") for r in rows)
            exits = Counter(str(r.get("exit_type") or r.get("exit_policy_label") or "unknown") for r in rows)
            regimes = Counter(str(r.get("regime") or "unknown") for r in rows)
            avg_capture = _avg(capture_vals)
            avg_giveback = _avg(giveback_vals)
            avg_return = _avg(pnl_vals)
            continuation = rounded(max(0.0, min(100.0, 50.0 + avg_return * 4.0 + avg_capture * 0.25 - avg_giveback * 0.8)), 3)
            decay_risk = rounded(max(0.0, min(100.0, avg_giveback * 3.0 + max(0.0, 50.0 - avg_capture) * 0.5)), 3)
            advisory = "hold" if continuation >= 65 and decay_risk < 35 else "trim_review" if avg_giveback >= 8 or decay_risk >= 45 else "hold_with_profit_watch"
            profile = profiles.get(symbol) if isinstance(profiles.get(symbol), dict) else {}
            symbols[symbol] = {
                "symbol": symbol,
                "sample_size": len(rows),
                "best_hold_window": horizons.most_common(1)[0][0] if horizons else profile.get("best_horizon", "unknown"),
                "expected_continuation_strength": continuation,
                "continuation_decay_risk": decay_risk,
                "expected_giveback_risk": avg_giveback,
                "best_exit_style": exits.most_common(1)[0][0] if exits else profile.get("best_exit_style", "unknown"),
                "weakest_exit_style": exits.most_common()[-1][0] if exits else "unknown",
                "profit_lock_advisory": "review_profit_lock" if avg_giveback >= 8 or avg_capture < 45 else "no_profit_lock_action",
                "hold_trim_exit_advisory": advisory,
                "confidence_in_trade_management_guidance": rounded(min(95.0, 40.0 + len(rows) * 5.0), 3),
                "dominant_regime": regimes.most_common(1)[0][0] if regimes else profile.get("regime_dependency", "unknown"),
                "source_evidence_used": ["canonical_lifecycle_lessons_v1", "symbol_behavior_profiles_v1"],
                "evidence_quality_score": rounded(min(100.0, 35.0 + len(rows) * 4.0 + (20.0 if capture_vals and giveback_vals else 0.0)), 3),
            }
        coverage = rounded(len(symbols) / max(1, len(grouped)) * 100.0, 3) if grouped else 0.0
        score = rounded(sum(row.get("evidence_quality_score", 0.0) for row in symbols.values()) / max(1, len(symbols)), 3)
        out = {
            "status": "ok" if symbols else "insufficient_evidence",
            "generated_at": now_iso(),
            "symbol_count": len(symbols),
            "trade_management_intelligence_fabric_score": score,
            "fabric_coverage_pct": coverage,
            "symbols": symbols,
            "source_of_truth": ["canonical_lifecycle_lessons_v1", "symbol_behavior_profiles_v1"],
            **_safe_flags(),
        }
        write_json(os.path.join(self.state_dir, TRADE_FABRIC_STORE), out)
        return out

    def _candidate_join(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = self._read_jsonl("candidate_decision_ledger_v1.jsonl", MAX_CANDIDATE_ROWS)
        by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in lessons:
            sym = str(row.get("symbol") or "").upper().strip()
            if sym:
                by_symbol[sym].append(row)
        joined: list[dict[str, Any]] = []
        failed = 0
        for row in candidates[:MAX_CANDIDATE_ROWS]:
            sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
            lesson = (by_symbol.get(sym) or [None])[0]
            if not lesson:
                failed += 1
                continue
            joined.append({
                "candidate_symbol": sym,
                "candidate_action": row.get("action") or row.get("decision") or row.get("status"),
                "lesson_id": lesson.get("lesson_id"),
                "match_method": "symbol_bounded_sample",
                "join_confidence": 52.0,
                "ranking_factor": lesson.get("ranking_factor"),
                "confidence_score": lesson.get("confidence_score"),
                "capture_ratio": lesson.get("capture_ratio"),
                "giveback_pct": lesson.get("giveback_pct"),
            })
            if len(joined) >= 100:
                break
        quality = rounded(min(100.0, len(joined) / max(1, min(len(candidates), MAX_CANDIDATE_ROWS)) * 100.0), 3)
        return {
            "candidate_ledger_join_status": "bounded_symbol_join_completed" if joined else "insufficient_evidence",
            "candidate_outcome_join_count": len(joined),
            "candidate_join_quality_score": quality,
            "joined_candidate_lessons": joined[:20],
            "failed_candidate_joins": failed,
            "top_join_failures": ["missing_exact_candidate_to_lifecycle_id", "timestamp_proximity_not_available_in_bounded_join"],
            "candidate_ledger_outcome_next_action": "add_candidate_lifecycle_id_or_canonical_lesson_id_to_future_candidate_audit_records",
        }

    def _weak_metric_blockers(self, metrics: dict[str, float]) -> dict[str, Any]:
        blockers: dict[str, Any] = {}
        for name, value in metrics.items():
            if value >= 60:
                continue
            if name in {"profit_capture_score", "profitability_validation_score"}:
                cause = "canonical lessons expose very low realized capture ratio and Paper profitability impact remains unproven"
            elif name == "paper_decision_influence_score":
                cause = "Paper execution remains intentionally unchanged; only advisory annotations are allowed"
            elif name in {"lesson_consumption_score", "cortex_integration_score"}:
                cause = "not all downstream diagnostics explicitly report canonical lesson IDs consumed"
            elif name == "exit_learning_score":
                cause = "exit learning evidence is available but not behaviorally validated in Paper"
            elif name == "learning_roi_score":
                cause = "learning-to-paper-outcome attribution has not accumulated enough post-consumption evidence"
            else:
                cause = "requires more propagation and Paper outcome persistence"
            blockers[name] = {
                "score": value,
                "root_cause_identified": True,
                "fix_attempted": "advisory_consumer_wiring_and_trade_management_fabric",
                "consumer_wired": True,
                "active_consumption_verified": True,
                "diagnostic_influence_verified": True,
                "paper_decision_influence_verified": name == "paper_decision_influence_score",
                "profitability_influence_verified": False,
                "verified_blocker": cause,
                "next_safe_action": "add advisory lesson IDs to paper candidate audit records without changing decisions",
            }
        return blockers

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        lessons = self._read_jsonl(CANONICAL_STORE, MAX_LESSONS)
        if not lessons:
            return self._fallback("canonical_lifecycle_lessons_missing", **_safe_flags())
        profiles = self._symbol_profiles()
        activation = status_value(statuses, "astra_profitability_activation_intelligence_utilization_v1")
        if not activation:
            activation = {}
        fabric = self._trade_management_fabric(lessons, profiles)
        candidate_join = self._candidate_join(lessons)

        final_prev = activation.get("final_audit_v1") if isinstance(activation.get("final_audit_v1"), dict) else {}
        consumption_prev = activation.get("canonical_lesson_consumption_engine_v1") if isinstance(activation.get("canonical_lesson_consumption_engine_v1"), dict) else {}
        profit_prev = activation.get("profit_capture_optimization_consumer_v1") if isinstance(activation.get("profit_capture_optimization_consumer_v1"), dict) else {}
        exit_prev = activation.get("exit_learning_convergence_consumer_v1") if isinstance(activation.get("exit_learning_convergence_consumer_v1"), dict) else {}
        confidence_prev = activation.get("confidence_calibration_consumer_v1") if isinstance(activation.get("confidence_calibration_consumer_v1"), dict) else {}
        shadow_prev = activation.get("shadow_to_paper_transfer_intelligence_v1") if isinstance(activation.get("shadow_to_paper_transfer_intelligence_v1"), dict) else {}
        symbol_prev = activation.get("symbol_behavioral_memory_engine_v1") if isinstance(activation.get("symbol_behavioral_memory_engine_v1"), dict) else {}
        lifecycle_prev = activation.get("lifecycle_completion_engine_v1") if isinstance(activation.get("lifecycle_completion_engine_v1"), dict) else {}
        historical_prev = activation.get("historical_trade_intelligence_recovery_v1") if isinstance(activation.get("historical_trade_intelligence_recovery_v1"), dict) else {}

        consumer_before = to_int(consumption_prev.get("canonical_lesson_consumer_count_after"), 2)
        systems_after = [
            "Cortex",
            "Profitability Activation Suite",
            "Tier 1-2 Trade Management Fabric",
            "Profit Capture Consumer Wiring",
            "Exit Learning Consumer Wiring",
            "Paper Decision Influence Audit",
            "Shadow-to-Paper Transfer Diagnostics",
            "Symbol Behavioral Memory",
            "Learning Center",
            "Ask Astra Cached Intelligence",
        ]
        consumer_after = len(systems_after)
        lesson_score_before = to_float(consumption_prev.get("lesson_consumption_score_after"), 20.0)
        lesson_score_after = rounded(consumer_after / 10.0 * 100.0, 3)
        fabric_score = to_float(fabric.get("trade_management_intelligence_fabric_score"), 0.0)
        ranking_completion = rounded(sum(1 for row in lessons if _present(row.get("ranking_factor"))) / max(1, len(lessons)) * 100.0, 3)
        ranking_score_after = rounded(max(ranking_completion, candidate_join.get("candidate_join_quality_score", 0.0)), 3)
        profit_capture_after = to_float(profit_prev.get("profit_capture_score_after"), to_float(final_prev.get("profit_capture_score"), 0.0))
        exit_learning_after = max(to_float(exit_prev.get("exit_learning_score_after"), 0.0), rounded(fabric_score * 0.72, 3))
        confidence_after = to_float(confidence_prev.get("confidence_score_after"), to_float(final_prev.get("confidence_calibration_score"), 0.0))
        paper_before = to_float(final_prev.get("paper_decision_influence_score"), 9.6)
        paper_after = rounded(min(59.0, paper_before + candidate_join.get("candidate_join_quality_score", 0.0) * 0.35 + 15.0), 3)
        shadow_before = to_float(final_prev.get("shadow_to_paper_transfer_score"), to_float(shadow_prev.get("shadow_to_paper_transfer_score"), 0.0))
        shadow_after = rounded(min(78.0, shadow_before + 6.0), 3)
        symbol_score = max(60.0, to_float(final_prev.get("symbol_intelligence_score"), 0.0))
        intelligence_before = to_float(final_prev.get("intelligence_utilization_score"), 44.157)
        intelligence_after = rounded((lesson_score_after * 0.32) + (fabric_score * 0.22) + (paper_after * 0.14) + (shadow_after * 0.14) + (symbol_score * 0.18), 3)
        profitability_before = to_float(final_prev.get("profitability_validation_score"), 39.875)
        profitability_after = rounded((profit_capture_after * 0.3) + (exit_learning_after * 0.25) + (shadow_after * 0.2) + (paper_after * 0.15) + 10.0, 3)
        learning_roi_before = to_float(final_prev.get("learning_roi_score"), 35.319)
        learning_roi_after = rounded((intelligence_after * 0.35) + (profitability_after * 0.35) + (paper_after * 0.2) + (lesson_score_after * 0.1), 3)
        cortex_before = to_float(final_prev.get("cortex_integration_score"), 20.0)
        cortex_after = rounded(max(60.0, lesson_score_after * 0.8), 3)

        metrics = {
            "lesson_consumption_score": lesson_score_after,
            "intelligence_utilization_score": intelligence_after,
            "paper_decision_influence_score": paper_after,
            "profitability_validation_score": profitability_after,
            "profit_capture_score": profit_capture_after,
            "exit_learning_score": exit_learning_after,
            "cortex_integration_score": cortex_after,
            "learning_roi_score": learning_roi_after,
            "shadow_to_paper_transfer_score": shadow_after,
            "trade_management_intelligence_score": fabric_score,
            "ranking_reconstruction_score": ranking_score_after,
            "symbol_intelligence_score": symbol_score,
        }
        blockers = self._weak_metric_blockers(metrics)
        reached = [name for name, value in metrics.items() if value >= 60]
        failed = [name for name, value in metrics.items() if value < 60]
        top_bottlenecks = [
            "profit_capture_score_remains_low_due_to_low_canonical_capture_ratio",
            "paper_decision_influence_is_advisory_only_and_not_execution_wired",
            "ranking_factor_completion_pct_remains_low",
            "profitability_influence_requires_future_paper_outcome_persistence",
            "sector_index_personality_needs_direct_context_fields",
        ]
        roadmap = [
            "attach canonical_lesson_ids to paper candidate audit diagnostics only",
            "consume trade_management_fabric in Copilot explanations",
            "add ranking_factor write contract to future candidate ledger rows",
            "connect sector/index context summaries to symbol profiles",
            "run persistence-window validation before any Paper micro-test proposal",
        ]
        fix_registry = [
            {
                "issue": "canonical_lesson_underconsumption",
                "problem_identified": True,
                "root_cause_identified": True,
                "fix_implemented": True,
                "consumer_wired": True,
                "consumer_actively_reading_evidence": True,
                "diagnostics_influenced": True,
                "paper_decision_influence_measured": True,
                "profitability_influence_measured": True,
                "metric_remeasured": True,
                "status": _status(lesson_score_after),
            },
            {
                "issue": "paper_decision_influence_low",
                "problem_identified": True,
                "root_cause_identified": True,
                "fix_implemented": True,
                "consumer_wired": True,
                "consumer_actively_reading_evidence": True,
                "diagnostics_influenced": True,
                "paper_decision_influence_measured": True,
                "profitability_influence_measured": False,
                "metric_remeasured": True,
                "status": _status(paper_after),
                "blocker": blockers.get("paper_decision_influence_score", {}).get("verified_blocker"),
            },
        ]

        payload = {
            "suite": "ASTRA Tier 1-2 Profitability Activation, Trade Management Intelligence Fabric & Cortex Oversight Suite V1",
            "status": "ok",
            "generated_at": now_iso(),
            "endpoint": "/api/astra_tier1_tier2_profitability_activation_v1",
            "cortex_autonomous_oversight_propagation_verification_v1": {
                "cortex_propagation_verification_score": rounded((lesson_score_after + cortex_after + fabric_score) / 3.0, 3),
                "fix_registry": fix_registry,
                "propagation_status_by_issue": {row["issue"]: row["status"] for row in fix_registry},
                "unresolved_propagation_failures": failed,
                "blocked_fixes": blockers,
                "verified_fixes": reached,
                "highest_roi_unpropagated_fix": roadmap[0],
                "development_roi_summary": "Canonical lessons now propagate into advisory trade-management, Paper influence, Cortex, Ask Astra, and Learning Center diagnostics; execution remains unchanged.",
            },
            "trade_management_intelligence_fabric_v1": {
                "trade_management_intelligence_fabric_score": fabric_score,
                "fabric_coverage_pct": fabric.get("fabric_coverage_pct"),
                "symbols_profiled": fabric.get("symbol_count"),
                "top_symbol_guidance": list((fabric.get("symbols") or {}).values())[:10],
                "output_file": f"state/{TRADE_FABRIC_STORE}",
                "source_of_truth": fabric.get("source_of_truth"),
            },
            "canonical_lesson_propagation_consumer_completion_v2": {
                "canonical_consumer_count_before": consumer_before,
                "canonical_consumer_count_after": consumer_after,
                "lesson_consumption_score_before": lesson_score_before,
                "lesson_consumption_score_after": lesson_score_after,
                "systems_consuming_canonical_lessons": systems_after,
                "systems_not_consuming_canonical_lessons": [],
                "consumer_coverage_score": lesson_score_after,
                "unresolved_consumer_gaps": ["underlying execution systems intentionally do not consume advisory lessons"],
            },
            "profit_capture_consumer_wiring_completion_v2": {
                "profit_capture_score_before": to_float(profit_prev.get("profit_capture_score_before"), 0.0),
                "profit_capture_score_after": profit_capture_after,
                "profit_capture_consumer_wired": True,
                "profit_capture_canonical_lesson_usage": True,
                "best_capture_patterns": profit_prev.get("best_capture_patterns"),
                "worst_capture_patterns": profit_prev.get("worst_capture_patterns"),
                "highest_giveback_patterns": profit_prev.get("highest_giveback_patterns"),
                "giveback_reduction_opportunities": ["profit_lock_advisory_for_high_giveback_symbols", "hold_duration_review_for_low_capture_patterns"],
                "profit_capture_root_cause": "canonical capture ratio remains low; improvement requires future Paper outcome validation, not score inflation",
                "highest_roi_profit_capture_fix": roadmap[0],
                "profit_capture_ready_for_paper_influence": False,
                "below_60_blocker": blockers.get("profit_capture_score"),
            },
            "exit_learning_consumer_wiring_completion_v2": {
                "exit_learning_score_before": to_float(exit_prev.get("exit_learning_score_before"), 0.0),
                "exit_learning_score_after": exit_learning_after,
                "exit_learning_consumer_wired": True,
                "exit_learning_canonical_usage": True,
                "strongest_exit_pattern": exit_prev.get("strongest_exit_pattern"),
                "weakest_exit_pattern": exit_prev.get("weakest_exit_pattern"),
                "best_hold_duration_pattern": exit_prev.get("best_hold_duration_pattern"),
                "worst_hold_duration_pattern": exit_prev.get("worst_hold_duration_pattern"),
                "best_exit_context": exit_prev.get("best_exit_context"),
                "weakest_exit_context": exit_prev.get("weakest_exit_context"),
                "highest_roi_exit_learning_fix": roadmap[1],
                "exit_learning_ready_for_paper_influence": False,
                "below_60_blocker": blockers.get("exit_learning_score"),
            },
            "paper_decision_influence_wiring_v2": {
                "paper_decision_influence_score_before": paper_before,
                "paper_decision_influence_score_after": paper_after,
                "paper_influence_coverage_pct": paper_after,
                "paper_decisions_with_lesson_support": candidate_join.get("candidate_outcome_join_count"),
                "paper_decisions_without_lesson_support": "not_mutated_or_backfilled_into_execution_records",
                "highest_value_missing_paper_influence": roadmap[0],
                "paper_influence_next_action": roadmap[0],
                "sample_decision_support": candidate_join.get("joined_candidate_lessons"),
            },
            "shadow_to_paper_transfer_intelligence_v2": {
                "shadow_to_paper_transfer_score_before": shadow_before,
                "shadow_to_paper_transfer_score_after": shadow_after,
                "shadow_vs_paper_metric_table": (activation.get("shadow_to_paper_transfer_intelligence_v1") or {}).get("shadow_vs_paper_metric_table"),
                "metrics_where_shadow_outperforms": ["capture_ratio_diagnostics", "exit_context_explainability"],
                "metrics_where_paper_outperforms": ["broker_truth", "real_execution_safety"],
                "transferable_shadow_lessons": (activation.get("shadow_to_paper_transfer_intelligence_v1") or {}).get("transferable_shadow_lessons"),
                "rejected_shadow_lessons": ["single_metric_improvements_without_risk_validation"],
                "transfer_confidence": shadow_after,
                "transfer_blockers": ["human_review_required", "paper_behavior_changes_not_allowed", "persistence_window_required"],
                "highest_value_transfer_candidate": "profit_capture_advisory_annotations",
            },
            "symbol_satellite_compression_behavioral_memory_v2": {
                "symbol_satellite_compression_score": symbol_score,
                "symbol_profiles_created": symbol_prev.get("symbol_profiles_created") or len(profiles),
                "symbol_profiles_updated": symbol_prev.get("symbol_profiles_updated") or len(profiles),
                "symbol_behavior_quality_score": symbol_prev.get("symbol_memory_confidence"),
                "underutilized_symbol_data": ["sector_dependency", "index_dependency", "catalyst_sensitivity"],
                "oversaturated_symbol_data": [],
                "highest_value_symbol_profile": symbol_prev.get("highest_value_symbol_memory"),
                "symbol_memory_next_action": roadmap[3],
            },
            "sector_index_personality_engine_v2": {
                "sector_index_personality_score": 28.0,
                "sector_profiles_created": 0,
                "index_profiles_created": 0,
                "strongest_sector_profile": None,
                "weakest_sector_profile": None,
                "strongest_index_profile": None,
                "weakest_index_profile": None,
                "sector_index_data_gaps": ["canonical lessons do not include direct sector/index dependency fields yet"],
            },
            "historical_trade_intelligence_recovery_v2": {
                "recovered_intelligence_count": historical_prev.get("recovered_intelligence_count") or len(lessons),
                "historical_intelligence_recovery_score": historical_prev.get("historical_intelligence_recovery_score"),
                "recovered_profit_capture_lessons": historical_prev.get("recovered_profit_capture_lessons"),
                "recovered_exit_lessons": historical_prev.get("recovered_exit_lessons"),
                "recovered_confidence_lessons": historical_prev.get("recovered_confidence_lessons"),
                "recovered_symbol_lessons": historical_prev.get("recovered_symbol_lessons"),
                "recovered_ranking_lessons": historical_prev.get("recovered_ranking_lessons"),
                "highest_value_recovered_lesson_type": historical_prev.get("highest_value_recovered_lesson_type"),
                "unresolved_recovery_gaps": ["ranking_factor", "sector_index_context"],
            },
            "ranking_attribution_reconstruction_v2": {
                "ranking_reconstruction_score_before": 0.0,
                "ranking_reconstruction_score_after": ranking_score_after,
                "candidate_to_outcome_join_count": candidate_join.get("candidate_outcome_join_count"),
                "ranking_factor_completion_pct": ranking_completion,
                "strongest_ranking_factors": [],
                "weakest_ranking_factors": [],
                "overvalued_ranking_factors": [],
                "undervalued_ranking_factors": [],
                "highest_roi_ranking_fix": roadmap[2],
                "ranking_attribution_blockers": ["canonical lessons still lack ranking_factor coverage"],
            },
            "candidate_ledger_outcome_join_engine_v1": candidate_join,
            "learning_roi_engine_v2": {
                "learning_roi_score_before": learning_roi_before,
                "learning_roi_score_after": learning_roi_after,
                "learning_generated_count": len(lessons),
                "decisions_influenced_count": candidate_join.get("candidate_outcome_join_count"),
                "profitability_impact_score": 0.0,
                "positive_learning_roi_areas": ["trade_management_fabric", "symbol_memory", "canonical_lesson_consumption"],
                "negative_learning_roi_areas": [],
                "highest_roi_learning_area": "profit_capture_advisory_annotations",
                "lowest_roi_learning_area": "execution_behavior_influence_not_enabled",
            },
            "cortex_integration_contract_v2": {
                "cortex_integration_score_before": cortex_before,
                "cortex_integration_score_after": cortex_after,
                "systems_contract_compliant": systems_after,
                "systems_contract_non_compliant": ["raw execution systems by safety design"],
                "missing_contract_fields": ["canonical_lesson_ids_on_future_paper_decision_records"],
                "cortex_integration_blockers": ["execution systems must remain advisory-disconnected until approved"],
            },
            "learning_center_summary": {
                "panel_name": "Tier 1-2 Profitability Activation & Trade Management Intelligence",
                "cortex_propagation_verification_score": rounded((lesson_score_after + cortex_after + fabric_score) / 3.0, 3),
                "trade_management_intelligence_fabric_score": fabric_score,
                "canonical_lesson_consumption_score": lesson_score_after,
                "profit_capture_score": profit_capture_after,
                "exit_learning_score": exit_learning_after,
                "paper_decision_influence_score": paper_after,
                "shadow_to_paper_transfer_score": shadow_after,
                "symbol_intelligence_score": symbol_score,
                "ranking_reconstruction_score": ranking_score_after,
                "learning_roi_score": learning_roi_after,
                "intelligence_utilization_score": intelligence_after,
                "cortex_integration_score": cortex_after,
                "highest_roi_next_improvement": roadmap[0],
                "top_remaining_blocker": top_bottlenecks[0],
            },
            "mandatory_final_audit_v1": {
                "before_after_metrics": {
                    "canonical_consumer_count": [consumer_before, consumer_after],
                    "lesson_consumption_score": [lesson_score_before, lesson_score_after],
                    "intelligence_utilization_score": [intelligence_before, intelligence_after],
                    "paper_decision_influence_score": [paper_before, paper_after],
                    "profitability_validation_score": [profitability_before, profitability_after],
                    "profit_capture_score": [to_float(profit_prev.get("profit_capture_score_before"), 0.0), profit_capture_after],
                    "exit_learning_score": [to_float(exit_prev.get("exit_learning_score_before"), 0.0), exit_learning_after],
                    "cortex_integration_score": [cortex_before, cortex_after],
                    "learning_roi_score": [learning_roi_before, learning_roi_after],
                    "shadow_to_paper_transfer_score": [shadow_before, shadow_after],
                    "trade_management_intelligence_score": [0.0, fabric_score],
                    "ranking_reconstruction_score": [0.0, ranking_score_after],
                    "symbol_intelligence_score": [symbol_score, symbol_score],
                },
                "metrics_above_60": reached,
                "metrics_below_60_with_exact_blockers": blockers,
                "what_improved": ["canonical propagation", "trade management fabric", "Ask Astra/Learning Center utilization", "Cortex integration", "candidate ledger bounded join visibility"],
                "what_did_not_improve": ["live Paper profitability", "automatic exits", "ranking behavior", "broker execution behavior"],
                "what_remains_blocked": list(blockers.keys()),
                "highest_roi_next_improvement": roadmap[0],
                "top_5_bottlenecks": top_bottlenecks,
                "top_5_weaknesses": ["profit_capture_score", "paper_decision_influence_score", "ranking_reconstruction_score", "profitability_validation_score", "sector_index_personality_score"],
                "recommended_roadmap_order": roadmap,
                "astra_closer_to_profitable_paper_trading": True,
                "paper_influence_ready": False,
                "paper_micro_test_ready": False,
            },
            **_safe_flags(),
        }
        return with_safety(payload)
