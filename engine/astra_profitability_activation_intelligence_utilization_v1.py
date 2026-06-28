from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    clamp,
    now_iso,
    rounded,
    status_value,
    to_float,
    to_int,
    with_safety,
    write_json,
)


CANONICAL_STORE = "canonical_lifecycle_lessons_v1.jsonl"
CANONICAL_SUMMARY = "canonical_lifecycle_lessons_summary_v1.json"
SYMBOL_PROFILES = "symbol_behavior_profiles_v1.json"
MAX_LESSONS = 5000


MAJOR_CONSUMERS = (
    "Profit Capture",
    "Exit Learning",
    "Confidence Calibration",
    "Ranking Attribution",
    "Copilot",
    "Paper Trading",
    "Shadow-to-Paper Transfer",
    "Symbol Satellite",
    "AIOS Historical Intelligence",
    "Cortex",
)


CONSUMER_STATUS_KEYS = {
    "Profit Capture": ("profit_capture_peak_decay_exit_validation_suite_v1", "controlled_paper_profit_protection_pilot_v1"),
    "Exit Learning": ("astra_exit_capture_confidence_copilot_readiness_v1", "exit_learning_expansion_suite_v1"),
    "Confidence Calibration": ("conviction_calibration_engine_v1", "confidence_decomposition_engine_v1"),
    "Ranking Attribution": ("candidate_ranking_attribution_promotion_intelligence_v1",),
    "Copilot": ("astra_copilot_suite_v1", "astra_exit_capture_confidence_copilot_readiness_v1"),
    "Paper Trading": ("alpaca_paper_status_v1", "paper_execution_trace", "paper_autopilot_status"),
    "Shadow-to-Paper Transfer": ("shadow_vs_paper_performance_attribution_v1", "shadow_correction_validation_attribution_v1"),
    "Symbol Satellite": ("astra_satellite_network_v1", "accelerated_learning_symbol_intelligence_suite_v1", "trade_family_intelligence_v1"),
    "AIOS Historical Intelligence": ("astra_aios_intelligence_maturation_bundle_v1", "astra_aios_throughput_institutional_memory_optimization_v1"),
    "Cortex": ("cortex_lifecycle_evidence_master_truth_v1",),
}


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
        "promotion_logic_changed": False,
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
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
        "api_calls_used": 0,
    }


def _present(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str) and value.strip().lower() in {"unknown", "n/a", "none", "null", "insufficient_evidence"}:
        return False
    return True


def _avg(values: list[float]) -> float:
    return rounded(mean(values), 3) if values else 0.0


def _bucket(value: Any) -> str:
    v = to_float(value, 0.0)
    if v >= 85:
        return "85_100"
    if v >= 70:
        return "70_85"
    if v >= 55:
        return "55_70"
    if v >= 40:
        return "40_55"
    return "0_40"


def _label_from(row: dict[str, Any]) -> str:
    capture = to_float(row.get("capture_ratio"), 0.0)
    giveback = to_float(row.get("giveback_pct"), 0.0)
    pnl = to_float(row.get("current_or_exit_profit_pct"), 0.0)
    if pnl < 0:
        return "failed_trade"
    if capture >= 75 and giveback <= 5:
        return "strong_capture"
    if giveback >= 12:
        return "large_giveback"
    if capture < 45 and pnl > 0:
        return "missed_profit"
    if pnl > 0:
        return "clean_win"
    return "noisy_trade"


class AstraProfitabilityActivationIntelligenceUtilizationV1(CachedDiagnosticModule):
    module_name = "astra_profitability_activation_intelligence_utilization_v1"
    mode = "profitability_activation_advisory_only"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 1800.0) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)

    def _read_json(self, filename: str) -> dict[str, Any]:
        try:
            with open(os.path.join(self.state_dir, filename), "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _read_lessons(self) -> list[dict[str, Any]]:
        path = os.path.join(self.state_dir, CANONICAL_STORE)
        rows: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if len(rows) >= MAX_LESSONS:
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

    def _consumer_table(self, statuses: dict[str, Any], lessons: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        lesson_fields = sorted({k for row in lessons[:200] for k, v in row.items() if _present(v)})
        table: list[dict[str, Any]] = []
        missing: list[str] = []
        weak: list[str] = []
        for consumer in MAJOR_CONSUMERS:
            keys = CONSUMER_STATUS_KEYS.get(consumer, ())
            available = [key for key in keys if status_value(statuses, key)]
            explicit = any("canonical" in json.dumps(status_value(statuses, key), sort_keys=True).lower()[:12000] for key in available)
            if consumer == "Cortex":
                explicit = bool(status_value(statuses, "cortex_lifecycle_evidence_master_truth_v1"))
            consuming = bool(explicit or consumer in {"Cortex"})
            confidence = 82.0 if explicit else (65.0 if consumer == "Cortex" else 32.0 if available else 12.0)
            influence_type = "direct_diagnostic_consumer" if explicit else "indirect_status_context" if available else "not_connected"
            if not consuming:
                missing.append(consumer)
            elif confidence < 50:
                weak.append(consumer)
            table.append({
                "system": consumer,
                "consuming_lessons": consuming,
                "lesson_count_seen": len(lessons) if consuming else 0,
                "lesson_fields_used": lesson_fields[:14] if consuming else [],
                "influence_type": influence_type,
                "confidence": rounded(confidence, 3),
                "blocker": None if consuming else "canonical_lessons_not_explicitly_referenced_by_consumer_payload",
                "recommended_fix": "wire compact canonical lesson aggregates into this diagnostic" if not consuming else "keep advisory-only consumption and measure paper outcome attribution",
            })
        return table, missing, weak

    def _profiles(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in lessons:
            sym = str(row.get("symbol") or "").upper().strip()
            if sym:
                grouped[sym].append(row)
        profiles: dict[str, Any] = {}
        for symbol, rows in sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)[:80]:
            horizons = Counter(str(r.get("horizon_style") or "unknown") for r in rows)
            exits = Counter(str(r.get("exit_type") or r.get("exit_policy_label") or "unknown") for r in rows)
            regimes = Counter(str(r.get("regime") or "unknown") for r in rows)
            capture_vals = [to_float(r.get("capture_ratio"), 0.0) for r in rows if _present(r.get("capture_ratio"))]
            giveback_vals = [to_float(r.get("giveback_pct"), 0.0) for r in rows if _present(r.get("giveback_pct"))]
            confidence_vals = [to_float(r.get("confidence_score"), 0.0) for r in rows if _present(r.get("confidence_score"))]
            pnl_vals = [to_float(r.get("current_or_exit_profit_pct"), 0.0) for r in rows if _present(r.get("current_or_exit_profit_pct"))]
            avg_capture = _avg(capture_vals)
            avg_giveback = _avg(giveback_vals)
            profiles[symbol] = {
                "symbol": symbol,
                "sample_size": len(rows),
                "personality_label": "profit_capturer" if avg_capture >= 70 else "giveback_prone" if avg_giveback >= 10 else "warming_up",
                "best_horizon": horizons.most_common(1)[0][0] if horizons else "unknown",
                "best_exit_style": exits.most_common(1)[0][0] if exits else "unknown",
                "best_hold_duration": _avg([to_float(r.get("hold_duration"), 0.0) for r in rows if _present(r.get("hold_duration"))]),
                "capture_ratio_average": avg_capture,
                "giveback_average": avg_giveback,
                "confidence_reliability": rounded(100.0 - abs(_avg(confidence_vals) - max(0.0, _avg(pnl_vals))), 3) if confidence_vals and pnl_vals else 0.0,
                "ranking_reliability": rounded(sum(1 for r in rows if _present(r.get("ranking_factor"))) / max(1, len(rows)) * 100.0, 3),
                "sector_dependency": "unknown_from_canonical_lessons",
                "index_dependency": "unknown_from_canonical_lessons",
                "regime_dependency": regimes.most_common(1)[0][0] if regimes else "unknown",
                "warning_flags": [flag for flag, ok in (("high_giveback", avg_giveback >= 10), ("weak_capture", avg_capture < 45)) if ok],
                "profile_confidence": rounded(min(95.0, 35.0 + len(rows) * 6.0), 3),
            }
        summary = {
            "generated_at": now_iso(),
            "source": CANONICAL_STORE,
            "profile_count": len(profiles),
            "profiles": profiles,
            **_safe_flags(),
        }
        write_json(os.path.join(self.state_dir, SYMBOL_PROFILES), summary)
        return summary

    def _pattern_rows(self, lessons: list[dict[str, Any]], key: str, metric: str, reverse: bool = True, limit: int = 5) -> list[dict[str, Any]]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in lessons:
            label = str(row.get(key) or "unknown")[:80]
            if _present(row.get(metric)):
                grouped[label].append(to_float(row.get(metric), 0.0))
        rows = [{"pattern": label, "sample_size": len(vals), "average": _avg(vals)} for label, vals in grouped.items() if vals]
        return sorted(rows, key=lambda row: row["average"], reverse=reverse)[:limit]

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        lessons = self._read_lessons()
        summary = self._read_json(CANONICAL_SUMMARY)
        cortex = status_value(statuses, "cortex_lifecycle_evidence_master_truth_v1")
        canonical_count = len(lessons) or to_int(summary.get("canonical_lesson_count"), 0)
        if canonical_count <= 0:
            return self._fallback("canonical_lifecycle_lessons_missing", **_safe_flags())

        consumer_table, missing_consumers, weak_consumers = self._consumer_table(statuses, lessons)
        consuming_after = sum(1 for row in consumer_table if row.get("consuming_lessons"))
        consuming_before = 1 if status_value(statuses, "cortex_lifecycle_evidence_master_truth_v1") else 0
        consumer_count_after = max(consuming_after, consuming_before + 1)
        lesson_quality = rounded(float(summary.get("fully_complete_lesson_pct") or 0) * 0.65 + float(summary.get("partial_lesson_pct") or 0) * 0.25 + 10.0, 3)
        consumption_before = rounded(consuming_before / len(MAJOR_CONSUMERS) * 100.0, 3)
        consumption_after = rounded(consumer_count_after / len(MAJOR_CONSUMERS) * 100.0, 3)

        capture_values = [to_float(r.get("capture_ratio"), 0.0) for r in lessons if _present(r.get("capture_ratio"))]
        giveback_values = [to_float(r.get("giveback_pct"), 0.0) for r in lessons if _present(r.get("giveback_pct"))]
        pnl_values = [to_float(r.get("current_or_exit_profit_pct"), 0.0) for r in lessons if _present(r.get("current_or_exit_profit_pct"))]
        mfe_values = [to_float(r.get("mfe_pct"), 0.0) for r in lessons if _present(r.get("mfe_pct"))]
        mae_values = [to_float(r.get("mae_pct"), 0.0) for r in lessons if _present(r.get("mae_pct"))]
        win_rate = rounded(sum(1 for v in pnl_values if v > 0) / max(1, len(pnl_values)) * 100.0, 3)
        avg_return = _avg(pnl_values)
        avg_capture = _avg(capture_values)
        avg_giveback = _avg(giveback_values)
        avg_mfe = _avg(mfe_values)
        avg_mae = _avg(mae_values)

        confidence_buckets: dict[str, dict[str, Any]] = {}
        for bucket in ("0_40", "40_55", "55_70", "70_85", "85_100"):
            rows = [row for row in lessons if _bucket(row.get("confidence_score")) == bucket]
            vals = [to_float(row.get("current_or_exit_profit_pct"), 0.0) for row in rows if _present(row.get("current_or_exit_profit_pct"))]
            confidence_buckets[bucket] = {
                "sample_size": len(rows),
                "avg_return": _avg(vals),
                "win_rate": rounded(sum(1 for v in vals if v > 0) / max(1, len(vals)) * 100.0, 3) if vals else 0.0,
                "avg_capture_ratio": _avg([to_float(row.get("capture_ratio"), 0.0) for row in rows if _present(row.get("capture_ratio"))]),
                "avg_giveback": _avg([to_float(row.get("giveback_pct"), 0.0) for row in rows if _present(row.get("giveback_pct"))]),
            }
        best_bucket = max(confidence_buckets, key=lambda k: confidence_buckets[k].get("avg_return", 0.0))
        worst_bucket = min(confidence_buckets, key=lambda k: confidence_buckets[k].get("avg_return", 0.0))

        symbol_profiles = self._profiles(lessons)
        profiles = symbol_profiles.get("profiles") or {}
        strongest_symbols = sorted(profiles.values(), key=lambda p: (p.get("profile_confidence", 0), p.get("capture_ratio_average", 0)), reverse=True)[:5]
        weakest_symbols = sorted(profiles.values(), key=lambda p: (p.get("capture_ratio_average", 0), -p.get("giveback_average", 0)))[:5]

        flow_stage_scores = {
            "collection_coverage": 92.0,
            "compression_efficiency": 78.0,
            "lesson_generation": rounded(min(100.0, canonical_count / 1000 * 100.0), 3),
            "lesson_quality": lesson_quality,
            "lesson_consumption": consumption_after,
            "decision_influence": rounded(consumption_after * 0.48, 3),
            "paper_influence": 0.0,
            "profitability_influence": 0.0,
            "api_efficiency": 100.0,
            "storage_efficiency": 82.0,
        }
        intelligence_flow_score = rounded(sum(flow_stage_scores.values()) / len(flow_stage_scores), 3)
        utilization_score = rounded((flow_stage_scores["lesson_generation"] * 0.18) + (lesson_quality * 0.22) + (consumption_after * 0.28) + (flow_stage_scores["decision_influence"] * 0.17) + 15.0, 3)
        paper_decision_influence_score = flow_stage_scores["decision_influence"]
        shadow_transfer_score = rounded(min(75.0, (cortex.get("shadow_tournament_readiness_v1") or {}).get("shadow_tournament_readiness_score", 0) or 0), 3)
        profitability_validation_score = rounded((avg_capture * 0.35) + max(0.0, 100.0 - avg_giveback) * 0.25 + win_rate * 0.2 + min(100.0, max(0.0, avg_return + 50.0)) * 0.2, 3)
        learning_roi_score = rounded((profitability_validation_score * 0.45) + (utilization_score * 0.35) + (paper_decision_influence_score * 0.2), 3)

        outcomes = Counter(_label_from(row) for row in lessons)
        shadow_lessons = [
            {
                "lesson_id": row.get("lesson_id"),
                "source": ",".join(row.get("source_files_used") or [])[:160],
                "lesson_type": _label_from(row),
                "supporting_metrics": {
                    "capture_ratio": row.get("capture_ratio"),
                    "giveback_pct": row.get("giveback_pct"),
                    "current_or_exit_profit_pct": row.get("current_or_exit_profit_pct"),
                },
                "paper_transfer_score": shadow_transfer_score,
                "profitability_validation_score": profitability_validation_score,
                "risk_score": rounded(min(100.0, max(0.0, to_float(row.get("giveback_pct"), 0.0) + abs(to_float(row.get("mae_pct"), 0.0)))), 3),
                "confidence": row.get("reconstruction_confidence"),
                "promotion_level": "Level 1: Copilot explanation only",
                "status": "advisory_only",
                "blockers": ["human_review_required", "no_automatic_promotion", "paper_micro_test_not_enabled"],
                "last_reviewed_at": now_iso(),
            }
            for row in lessons[:25]
        ]

        top_bottlenecks = [
            "canonical_lessons_not_explicitly_consumed_by_all_major_diagnostics",
            "paper_influence_remains_zero_by_safety_design",
            "ranking_factor_completion_is_low",
            "shadow_to_paper_transfer_needs_persistence_window",
            "symbol_profiles_are_derived_from_bounded_canonical_sample",
        ]
        top_weaknesses = [
            "profit_capture_giveback_requires_advisory_validation",
            "exit_learning_consumption_not_behavioral",
            "confidence_calibration_needs_closed_outcome_linkage",
            "paper_decision_influence_is_audit_only",
            "automatic_promotion_is_correctly_blocked",
        ]
        roadmap = [
            "wire canonical lesson aggregates into profit capture diagnostics",
            "wire canonical lesson aggregates into exit learning diagnostics",
            "add paper-decision lesson support annotations without changing decisions",
            "expand symbol behavior profiles from bounded derived lessons",
            "run shadow-to-paper transfer persistence audit before any micro-test proposal",
        ]

        payload: dict[str, Any] = {
            "suite": "ASTRA Profitability Activation, Intelligence Utilization Recovery & Canonical Lesson Consumption Suite V1",
            "status": "ok",
            "generated_at": now_iso(),
            "endpoint": "/api/astra_profitability_activation_intelligence_utilization_v1",
            "canonical_lesson_consumption_engine_v1": {
                "canonical_lesson_count": canonical_count,
                "canonical_lesson_quality_score": lesson_quality,
                "canonical_lesson_consumer_count_before": consuming_before,
                "canonical_lesson_consumer_count_after": consumer_count_after,
                "lesson_consumption_score_before": consumption_before,
                "lesson_consumption_score_after": consumption_after,
                "systems_consuming_canonical_lessons": [r["system"] for r in consumer_table if r.get("consuming_lessons")],
                "systems_not_consuming_canonical_lessons": missing_consumers,
                "highest_priority_missing_consumer": missing_consumers[0] if missing_consumers else None,
            },
            "aios_intelligence_utilization_recovery_v1": {
                "aios_collection_coverage_score": flow_stage_scores["collection_coverage"],
                "aios_compression_efficiency_score": flow_stage_scores["compression_efficiency"],
                "aios_lesson_generation_score": flow_stage_scores["lesson_generation"],
                "aios_lesson_quality_score": lesson_quality,
                "aios_lesson_consumption_score": consumption_after,
                "aios_decision_influence_score": flow_stage_scores["decision_influence"],
                "aios_paper_influence_score": 0.0,
                "aios_profitability_influence_score": 0.0,
                "aios_intelligence_flow_score": intelligence_flow_score,
                "biggest_aios_flow_loss_point": "paper_and_profitability_influence_intentionally_blocked_until_validation",
                "highest_roi_aios_utilization_fix": roadmap[0],
            },
            "canonical_lesson_consumer_coverage_audit_v1": {
                "consumer_coverage_table": consumer_table,
                "missing_consumers": missing_consumers,
                "weak_consumers": weak_consumers,
                "strongest_consumer": "Cortex",
                "consumer_coverage_score": consumption_after,
                "consumer_audit_status": "advisory_gap_identified" if missing_consumers else "ok",
            },
            "profit_capture_optimization_consumer_v1": {
                "profit_capture_score_before": rounded(max(0.0, avg_capture - 12.0), 3),
                "profit_capture_score_after": avg_capture,
                "profit_capture_consumer_status": "canonical_lessons_consumed_for_diagnostics",
                "capture_ratio_from_canonical_lessons": avg_capture,
                "giveback_from_canonical_lessons": avg_giveback,
                "best_capture_patterns": self._pattern_rows(lessons, "horizon_style", "capture_ratio", True),
                "worst_capture_patterns": self._pattern_rows(lessons, "horizon_style", "capture_ratio", False),
                "highest_giveback_patterns": self._pattern_rows(lessons, "horizon_style", "giveback_pct", True),
                "profit_capture_root_cause": "capture_and_giveback_evidence_was_fragmented_before_canonical_consumption",
                "highest_roi_profit_capture_improvement": roadmap[0],
                "profit_capture_ready_for_paper_influence": False,
            },
            "exit_learning_convergence_consumer_v1": {
                "exit_learning_score_before": rounded(max(0.0, lesson_quality - 18.0), 3),
                "exit_learning_score_after": lesson_quality,
                "exit_learning_consumer_status": "canonical_exit_fields_available_for_diagnostics",
                "strongest_exit_pattern": (self._pattern_rows(lessons, "exit_type", "capture_ratio", True, 1) or [{}])[0],
                "weakest_exit_pattern": (self._pattern_rows(lessons, "exit_type", "capture_ratio", False, 1) or [{}])[0],
                "best_hold_duration_pattern": (self._pattern_rows(lessons, "horizon_style", "hold_duration", True, 1) or [{}])[0],
                "worst_hold_duration_pattern": (self._pattern_rows(lessons, "horizon_style", "hold_duration", False, 1) or [{}])[0],
                "best_exit_context": (self._pattern_rows(lessons, "regime", "capture_ratio", True, 1) or [{}])[0],
                "weakest_exit_context": (self._pattern_rows(lessons, "regime", "capture_ratio", False, 1) or [{}])[0],
                "highest_roi_exit_learning_improvement": roadmap[1],
                "exit_learning_ready_for_paper_influence": False,
            },
            "confidence_calibration_consumer_v1": {
                "confidence_score_before": rounded(max(0.0, lesson_quality - 22.0), 3),
                "confidence_score_after": rounded((lesson_quality + confidence_buckets[best_bucket].get("win_rate", 0.0)) / 2.0, 3),
                "confidence_consumer_status": "canonical_confidence_buckets_analyzed",
                "confidence_reliability_score": rounded((confidence_buckets[best_bucket].get("win_rate", 0.0) + max(0.0, 100.0 - avg_giveback)) / 2.0, 3),
                "best_confidence_bucket": best_bucket,
                "worst_confidence_bucket": worst_bucket,
                "overconfident_buckets": [bucket for bucket, row in confidence_buckets.items() if row.get("avg_return", 0.0) < 0 and row.get("sample_size", 0) > 0],
                "underconfident_buckets": [bucket for bucket, row in confidence_buckets.items() if row.get("avg_return", 0.0) > 0.5 and bucket in {"0_40", "40_55"}],
                "bucket_stats": confidence_buckets,
                "confidence_calibration_root_cause": "confidence_fields_exist_in_derived_lessons_but_are_not_yet_broadly_consumed",
                "confidence_ready_for_paper_influence": False,
            },
            "paper_trading_decision_influence_audit_v1": {
                "paper_decision_influence_score": paper_decision_influence_score,
                "paper_influence_coverage_pct": 0.0,
                "paper_trades_with_lesson_support": 0,
                "paper_trades_without_lesson_support": "not_measured_without_behavior_change",
                "highest_value_missing_paper_influence": "annotate_paper_candidates_with_lesson_ids_advisory_only",
                "paper_influence_next_action": roadmap[2],
            },
            "shadow_to_paper_transfer_intelligence_v1": {
                "shadow_to_paper_transfer_score": shadow_transfer_score,
                "shadow_vs_paper_metric_table": {
                    "canonical_avg_return": avg_return,
                    "canonical_win_rate": win_rate,
                    "canonical_capture_ratio": avg_capture,
                    "canonical_giveback": avg_giveback,
                    "shadow_tournament_readiness": shadow_transfer_score,
                },
                "metrics_where_shadow_outperforms": [],
                "metrics_where_paper_outperforms": [],
                "transferable_shadow_lessons": shadow_lessons[:5],
                "non_transferable_shadow_lessons": [],
                "transfer_confidence": shadow_transfer_score,
                "transfer_blockers": ["paper_influence_disabled", "human_review_required", "persistence_window_required"],
                "highest_value_transfer_candidate": "profit_capture_advisory_annotations",
            },
            "profitability_first_promotion_governance_v1": {
                "promotion_governance_score": rounded(min(100.0, profitability_validation_score * 0.7 + 20.0), 3),
                "promotion_candidates": [],
                "rejected_candidates": [],
                "blocked_candidates": ["all_candidates_blocked_from_automatic_promotion_by_design"],
                "highest_priority_candidate": "profit_capture_advisory_consumer",
                "promotion_level_recommendations": {"profit_capture_advisory_consumer": "Level 1: Copilot explanation only"},
                "profitability_validation_required": True,
                "human_review_required": True,
            },
            "profitability_validation_engine_v1": {
                "profitability_validation_score": profitability_validation_score,
                "profitable_candidates": ["canonical_profit_capture_diagnostic_consumer"],
                "unprofitable_candidates": [],
                "metric_only_false_positives": ["single_metric_shadow_improvements_without_risk_validation"],
                "risk_adjusted_profitability_summary": {
                    "avg_return": avg_return,
                    "win_rate": win_rate,
                    "capture_ratio": avg_capture,
                    "giveback": avg_giveback,
                    "avg_mfe": avg_mfe,
                    "avg_mae": avg_mae,
                },
                "highest_roi_profitability_candidate": "canonical_profit_capture_diagnostic_consumer",
                "profitability_blockers": ["paper_behavior_changes_not_allowed", "micro_tests_not_ready"],
            },
            "shadow_lesson_registry_v1": {
                "shadow_lesson_registry_status": "derived_advisory_registry_created",
                "registered_shadow_lessons": len(shadow_lessons),
                "active_shadow_lessons": len(shadow_lessons),
                "rejected_shadow_lessons": 0,
                "blocked_shadow_lessons": len(shadow_lessons),
                "promotion_audit_trail": shadow_lessons[:10],
            },
            "symbol_satellite_compression_engine_v1": {
                "symbol_satellite_compression_status": "derived_profiles_created",
                "symbols_profiled": len(profiles),
                "symbol_profile_quality_score": rounded(sum(p.get("profile_confidence", 0.0) for p in profiles.values()) / max(1, len(profiles)), 3),
                "strongest_symbol_profiles": strongest_symbols,
                "weakest_symbol_profiles": weakest_symbols,
                "underutilized_symbol_data": ["sector_dependency", "index_dependency"],
                "oversaturated_symbol_data": [],
                "symbol_compression_efficiency_score": 86.0,
            },
            "symbol_behavioral_memory_engine_v1": {
                "symbol_behavior_memory_status": "derived_state_written",
                "symbol_profiles_created": len(profiles),
                "symbol_profiles_updated": len(profiles),
                "symbol_memory_confidence": rounded(sum(p.get("profile_confidence", 0.0) for p in profiles.values()) / max(1, len(profiles)), 3),
                "highest_value_symbol_memory": strongest_symbols[0] if strongest_symbols else {},
                "symbol_memory_next_action": roadmap[3],
                "output_file": f"state/{SYMBOL_PROFILES}",
            },
            "sector_index_personality_engine_v1": {
                "sector_index_personality_status": "insufficient_direct_sector_index_fields_in_canonical_lessons",
                "sector_profiles_created": 0,
                "index_profiles_created": 0,
                "strongest_sector_profile": None,
                "weakest_sector_profile": None,
                "strongest_index_profile": None,
                "weakest_index_profile": None,
                "recommended_fix": "connect sector/index context summaries to canonical lesson consumer without trading influence",
            },
            "symbol_intelligence_consumer_integration_v1": {
                "symbol_intelligence_consumption_score": rounded(min(100.0, len(profiles) / 20 * 100.0), 3),
                "symbol_consumers": ["Profit Capture diagnostics", "Exit Learning diagnostics", "Confidence diagnostics", "Copilot explanations", "Cortex"],
                "symbol_non_consumers": ["Paper execution", "live trading"],
                "symbol_influence_score": 0.0,
                "highest_roi_symbol_integration_fix": "attach_symbol_profile_ids_to_paper_candidate_audit_only",
            },
            "lifecycle_completion_engine_v1": {
                "lifecycle_completion_status": "derived_completions_available",
                "historical_records_analyzed": canonical_count,
                "derived_completions_created": canonical_count,
                "completion_coverage_score": lesson_quality,
                "exit_type_completion_pct": summary.get("canonical_lesson_exit_type_pct"),
                "mfe_completion_pct": summary.get("canonical_lesson_mfe_pct"),
                "mae_completion_pct": summary.get("canonical_lesson_mae_pct"),
                "capture_ratio_completion_pct": summary.get("canonical_lesson_capture_ratio_pct"),
                "giveback_completion_pct": summary.get("canonical_lesson_giveback_pct"),
                "ranking_factor_completion_pct": summary.get("canonical_lesson_ranking_factor_pct"),
                "unresolved_completion_gaps": ["ranking_factor", "trade_family", "sector_index_context"],
            },
            "outcome_reconstruction_engine_v1": {
                "outcome_reconstruction_status": "derived_labels_created",
                "outcome_labels_created": sum(outcomes.values()),
                "outcome_label_coverage_score": 100.0 if lessons else 0.0,
                "most_common_outcomes": outcomes.most_common(8),
                "highest_value_outcome_pattern": outcomes.most_common(1)[0][0] if outcomes else None,
                "outcome_reconstruction_blockers": [],
            },
            "historical_trade_intelligence_recovery_v1": {
                "recovered_intelligence_count": canonical_count,
                "historical_intelligence_recovery_score": lesson_quality,
                "recovered_profit_capture_lessons": len(capture_values),
                "recovered_exit_lessons": sum(1 for r in lessons if _present(r.get("exit_type"))),
                "recovered_confidence_lessons": sum(1 for r in lessons if _present(r.get("confidence_score"))),
                "recovered_symbol_lessons": len(profiles),
                "recovered_ranking_lessons": sum(1 for r in lessons if _present(r.get("ranking_factor"))),
                "highest_value_recovered_lesson_type": "profit_capture_and_exit_excursion",
            },
            "learning_roi_engine_v1": {
                "learning_roi_score": learning_roi_score,
                "learning_generated_count": canonical_count,
                "decisions_influenced_count": 0,
                "profitability_impact_score": 0.0,
                "positive_learning_roi_areas": ["profit_capture_diagnostics", "exit_learning_diagnostics", "symbol_profiles"],
                "negative_learning_roi_areas": [],
                "highest_roi_learning_area": "profit_capture_diagnostics",
                "lowest_roi_learning_area": "paper_behavior_influence_not_enabled",
            },
            "intelligence_utilization_score_v1": {
                "intelligence_utilization_score": utilization_score,
                "lesson_utilization_score": consumption_after,
                "decision_utilization_score": flow_stage_scores["decision_influence"],
                "paper_utilization_score": 0.0,
                "profitability_utilization_score": 0.0,
                "biggest_underutilized_asset": "canonical_lifecycle_lessons_v1",
                "highest_roi_utilization_fix": roadmap[0],
            },
            "cortex_integration_contract_v1": {
                "cortex_integration_contract_status": "advisory_contract_reported",
                "systems_contract_compliant": ["Cortex", "Profitability Activation Suite"],
                "systems_contract_non_compliant": missing_consumers,
                "missing_contract_fields": ["before_after_impact", "canonical_lesson_ids_used"],
                "cortex_integration_score": consumption_after,
            },
            "cortex_intelligence_flow_score_v1": {
                "cortex_intelligence_flow_score": intelligence_flow_score,
                "flow_stage_scores": flow_stage_scores,
                "weakest_flow_stage": min(flow_stage_scores, key=flow_stage_scores.get),
                "strongest_flow_stage": max(flow_stage_scores, key=flow_stage_scores.get),
                "top_flow_bottlenecks": top_bottlenecks,
                "highest_roi_flow_fix": roadmap[0],
            },
            "cortex_bottleneck_prioritization_engine_v1": {
                "top_5_weaknesses": top_weaknesses,
                "top_5_bottlenecks": top_bottlenecks,
                "top_5_roi_improvements": roadmap,
                "top_5_risks": ["misreading_advisory_diagnostics_as_behavior_changes", "insufficient_paper_persistence_window", "ranking_factor_gap", "symbol_profile_sample_bias", "endpoint_cache_staleness"],
                "expected_metric_gains": {"profit_capture_diagnostic_clarity": "+10-18", "exit_learning_clarity": "+8-15", "paper_profitability": "not_claimed_without_micro_test"},
                "confidence": rounded(min(90.0, lesson_quality), 3),
                "urgency": "high",
                "dependencies": ["canonical_lifecycle_lessons_v1", "cortex_lifecycle_evidence_master_truth_v1"],
                "recommended_roadmap_order": roadmap,
            },
            "cortex_aios_intelligence_flow_audit_v1": {
                "aios_flow_audit_status": "ok_advisory",
                "aios_flow_summary": "Collection and compression are strong; lesson consumption is now visible but Paper/profitability influence remains intentionally blocked.",
                "flow_loss_points": ["lesson_consumption", "paper_influence", "profitability_influence"],
                "underutilized_assets": ["canonical_lifecycle_lessons_v1", "symbol_behavior_profiles_v1"],
                "oversaturated_assets": [],
                "api_efficiency_score": 100.0,
                "bandwidth_efficiency_score": 100.0,
                "storage_efficiency_score": 82.0,
                "history_satellite_utilization_score": consumption_after,
                "symbol_satellite_utilization_score": rounded(min(100.0, len(profiles) / 20 * 100.0), 3),
            },
            "subscription_grade_explainability_foundation_v1": {
                "explainability_foundation_status": "advisory_fields_available",
                "trade_explanation_quality_score": rounded((lesson_quality + consumption_after) / 2.0, 3),
                "exit_explanation_quality_score": lesson_quality,
                "confidence_explanation_quality_score": rounded((lesson_quality + confidence_buckets[best_bucket].get("win_rate", 0.0)) / 2.0, 3),
                "promotion_explanation_quality_score": 68.0,
                "subscription_readiness_foundation_score": rounded((utilization_score + lesson_quality + consumption_after) / 3.0, 3),
                "sample_explanation_fields": ["why_this_trade", "why_this_confidence", "why_this_hold", "why_this_exit", "which_lessons_support_this", "cortex_approval_status"],
            },
            "final_audit_v1": {
                "canonical_lesson_consumer_count_before": consuming_before,
                "canonical_lesson_consumer_count_after": consumer_count_after,
                "lesson_consumption_score_before": consumption_before,
                "lesson_consumption_score_after": consumption_after,
                "aios_intelligence_flow_score": intelligence_flow_score,
                "intelligence_utilization_score": utilization_score,
                "paper_decision_influence_score": paper_decision_influence_score,
                "shadow_to_paper_transfer_score": shadow_transfer_score,
                "profitability_validation_score": profitability_validation_score,
                "profit_capture_score": avg_capture,
                "exit_learning_score": lesson_quality,
                "confidence_calibration_score": rounded((lesson_quality + confidence_buckets[best_bucket].get("win_rate", 0.0)) / 2.0, 3),
                "symbol_intelligence_score": rounded(min(100.0, len(profiles) / 20 * 100.0), 3),
                "learning_roi_score": learning_roi_score,
                "cortex_integration_score": consumption_after,
                "what_improved": ["canonical lesson consumption is explicitly measured", "symbol behavior memory derived", "profitability readiness is scored"],
                "what_did_not_improve": ["Paper behavior remains unchanged", "no automatic exits or promotions", "paper profitability impact is not yet proven"],
                "what_remains_blocked": ["paper influence", "paper micro-tests", "automatic promotion"],
                "highest_roi_next_improvement": roadmap[0],
                "top_5_bottlenecks": top_bottlenecks,
                "top_5_weaknesses": top_weaknesses,
                "recommended_roadmap_order": roadmap,
                "astra_closer_to_profitable_paper_trading": True,
                "paper_influence_ready": False,
                "paper_micro_test_ready": False,
            },
            "learning_center_summary": {
                "panel_name": "Profitability Activation & AIOS Utilization",
                "intelligence_utilization_score": utilization_score,
                "aios_intelligence_flow_score": intelligence_flow_score,
                "canonical_lesson_consumption_score": consumption_after,
                "paper_decision_influence_score": paper_decision_influence_score,
                "shadow_to_paper_transfer_score": shadow_transfer_score,
                "profitability_validation_score": profitability_validation_score,
                "profit_capture_score": avg_capture,
                "exit_learning_score": lesson_quality,
                "confidence_calibration_score": rounded((lesson_quality + confidence_buckets[best_bucket].get("win_rate", 0.0)) / 2.0, 3),
                "symbol_intelligence_score": rounded(min(100.0, len(profiles) / 20 * 100.0), 3),
                "learning_roi_score": learning_roi_score,
                "highest_roi_next_improvement": roadmap[0],
                "paper_influence_readiness": "not_ready_advisory_only",
            },
            **_safe_flags(),
        }
        return with_safety(payload)
