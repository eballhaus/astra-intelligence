from __future__ import annotations

import os
import time
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
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

STATE_SCAN_LIMIT = 160
CACHE_SCAN_LIMIT = 220
OVERSIZED_BYTES = 250_000_000
SUMMARY_CANDIDATE_BYTES = 50_000_000

HOT_KEYWORDS = (
    "alpaca", "broker", "paper_position", "positions", "portfolio", "top_buys", "copilot", "alerts", "exit_review", "sell", "session", "health"
)
WARM_KEYWORDS = (
    "ranking", "profit_capture", "shadow", "regime", "market_context", "symbol", "catalyst", "learning", "attribution", "horizon"
)
CANONICAL_KEYWORDS = (
    "truth", "canonical", "closed", "lifecycle", "shadow_vs_paper", "broker", "trade_outcomes", "promotion_evidence"
)

TTL_CLASSES = {
    "real_time_short": 90,
    "medium": 900,
    "long": 7200,
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
        "automatic_learned_exits_enabled": False,
        "data_deleted": False,
        "data_archived_automatically": False,
        "canonical_truth_replaced": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _ttl_class(name: str) -> tuple[str, int]:
    low = str(name or "").lower()
    if any(k in low for k in HOT_KEYWORDS):
        return "real_time_short", TTL_CLASSES["real_time_short"]
    if any(k in low for k in WARM_KEYWORDS):
        return "medium", TTL_CLASSES["medium"]
    return "long", TTL_CLASSES["long"]


def _storage_tier(name: str, size: int = 0) -> str:
    low = str(name or "").lower()
    if any(k in low for k in CANONICAL_KEYWORDS):
        return "canonical_truth"
    if any(k in low for k in HOT_KEYWORDS):
        return "hot"
    if any(k in low for k in WARM_KEYWORDS) and size < OVERSIZED_BYTES:
        return "warm"
    if size >= SUMMARY_CANDIDATE_BYTES or low.endswith(".jsonl") or low.endswith(".db"):
        return "cold"
    return "warm"


def _freshness(age: float, ttl: int) -> tuple[str, float, bool]:
    ratio = age / max(1.0, float(ttl))
    if ratio <= 1.0:
        return "fresh", rounded(clamp(100.0 - ratio * 20.0), 3), False
    if ratio <= 3.0:
        return "aging", rounded(clamp(80.0 - (ratio - 1.0) * 20.0), 3), False
    return "stale", rounded(clamp(40.0 - (ratio - 3.0) * 6.0), 3), True


def _field(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    return default


class AstraStorageCacheAttributionLearningEfficiencyV1(CachedDiagnosticModule):
    module_name = "astra_storage_cache_attribution_learning_efficiency_v1"
    mode = "storage_cache_attribution_learning_efficiency_advisory"

    def _state_inventory(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        try:
            names = sorted(os.listdir(self.state_dir))[:STATE_SCAN_LIMIT]
        except Exception:
            names = []
        for name in names:
            path = os.path.join(self.state_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except Exception:
                continue
            size = int(stat.st_size)
            tier = _storage_tier(name, size)
            row = {
                "name": name,
                "path": f"state/{name}",
                "tier": tier,
                "size_bytes": size,
                "size_mb": rounded(size / 1_000_000.0, 3),
                "mtime": float(stat.st_mtime),
                "safe_for_ui_raw_scan": False if size >= SUMMARY_CANDIDATE_BYTES else tier in {"hot", "warm"},
                "recommendation": "preserve_canonical_truth" if tier == "canonical_truth" else "create_summary_or_index" if size >= SUMMARY_CANDIDATE_BYTES else "retain_current_access_pattern",
            }
            rows.append(row)
        rows.sort(key=lambda row: to_int(row.get("size_bytes"), 0), reverse=True)
        total = sum(to_int(row.get("size_bytes"), 0) for row in rows)
        oversized = [row for row in rows if to_int(row.get("size_bytes"), 0) >= OVERSIZED_BYTES]
        summary_candidates = [row for row in rows if to_int(row.get("size_bytes"), 0) >= SUMMARY_CANDIDATE_BYTES]
        return {
            "storage_tier_inventory": rows,
            "hot_storage_items": [row for row in rows if row.get("tier") == "hot"][:20],
            "warm_storage_items": [row for row in rows if row.get("tier") == "warm"][:20],
            "cold_storage_items": [row for row in rows if row.get("tier") == "cold"][:25],
            "canonical_truth_items": [row for row in rows if row.get("tier") == "canonical_truth"][:25],
            "oversized_state_items": oversized[:20],
            "safe_compaction_candidates": [],
            "archive_candidates": [row for row in summary_candidates if row.get("tier") == "cold"][:20],
            "index_candidates": [row for row in summary_candidates if str(row.get("name", "")).endswith(".jsonl")][:20],
            "summary_candidates": summary_candidates[:25],
            "total_learning_files": len(rows),
            "total_storage_footprint_bytes": total,
            "total_storage_footprint_mb": rounded(total / 1_000_000.0, 3),
            "storage_pressure_score": rounded(clamp((sum(to_int(row.get("size_bytes"), 0) for row in oversized) / 3_000_000_000.0) * 100.0 + len(summary_candidates) * 2.0), 3),
        }

    def _cache_inventory(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        cache_dir = os.path.join(self.state_dir, "dashboard_cache")
        now = time.time()
        try:
            names = sorted(os.listdir(cache_dir))[:CACHE_SCAN_LIMIT]
        except Exception:
            names = []
        for name in names:
            path = os.path.join(cache_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except Exception:
                continue
            base = name[:-5] if name.endswith(".json") else name
            ttl_class, ttl = _ttl_class(base)
            age = max(0.0, now - float(stat.st_mtime))
            status, trust, stale = _freshness(age, ttl)
            rows.append({
                "cache_name": base,
                "path": f"state/dashboard_cache/{name}",
                "cache_hit": True,
                "cache_age_seconds": rounded(age, 3),
                "cache_ttl_seconds": ttl,
                "cache_ttl_class": ttl_class,
                "cache_freshness_status": status,
                "cache_trust_score": trust,
                "stale_for_decision_making": bool(stale and ttl_class == "real_time_short"),
                "safe_for_dashboard_display": bool(status in {"fresh", "aging"} or ttl_class == "long"),
                "force_refresh_available": True,
            })
        stale_decision = [row for row in rows if row.get("stale_for_decision_making")]
        trust = rounded(sum(to_float(row.get("cache_trust_score"), 0) for row in rows) / max(1, len(rows)), 3)
        return {
            "cache_inventory": rows,
            "cache_trust_score": trust,
            "stale_decision_critical_cache_count": len(stale_decision),
            "stale_decision_critical_cache_items": stale_decision[:20],
            "smart_cache_status": "watch_stale_decision_caches" if stale_decision else "ok",
            "cache_freshness_recommendations": [
                "refresh_decision_critical_short_ttl_caches_in_background" if stale_decision else "retain_current_cache_policy",
                "serve_heavy_learning_diagnostics_from_long_ttl_summaries",
                "force_refresh_only_on_explicit_user_or_background_jobs",
            ],
        }

    def _profit_capture_summary(self, statuses: dict[str, Any]) -> dict[str, Any]:
        raw = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        summary = dict(raw.get("summary") or {})
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        confidence = _field(summary, "policy_confidence", default=_field(raw, "policy_confidence", default=learned.get("policy_confidence")))
        readiness = _field(summary, "readiness_score", default=_field(raw, "readiness_score", default=learned.get("policy_confidence")))
        blockers = []
        for item in (summary.get("readiness_blocker"), raw.get("readiness_blocker"), learned.get("baseline_vs_learned_status")):
            if item:
                blockers.append(item)
        ready = bool(to_float(confidence, 0) >= 65 and to_float(readiness, 0) >= 50 and not blockers)
        return {
            "profit_capture_confidence": rounded(confidence, 3),
            "profit_capture_score": rounded(_field(summary, "capture_quality_score", default=raw.get("capture_quality_score")), 3),
            "capture_quality_score": rounded(_field(summary, "capture_quality_score", default=raw.get("capture_quality_score")), 3),
            "average_capture_ratio": rounded(_field(summary, "average_capture_ratio", default=raw.get("average_capture_ratio")), 3),
            "average_giveback_pct": rounded(_field(summary, "average_giveback_pct", default=raw.get("average_giveback_pct")), 3),
            "profit_capture_readiness_score": rounded(readiness, 3),
            "profit_capture_blockers": blockers or ["profit_capture_validation_still_building"],
            "highest_giveback_trade": summary.get("highest_giveback_trade") or raw.get("highest_giveback_trade"),
            "best_capture_trade": summary.get("best_capture_trade") or raw.get("best_capture_trade"),
            "best_exit_policy": text(_field(summary, "best_exit_policy", "closest_exit_policy_to_readiness", default=raw.get("best_exit_policy"))),
            "closest_exit_policy_to_readiness": text(_field(summary, "closest_exit_policy_to_readiness", default=raw.get("closest_exit_policy_to_readiness"))),
            "weakest_horizon": summary.get("weakest_horizon") or raw.get("weakest_horizon"),
            "strongest_horizon": summary.get("strongest_horizon") or raw.get("strongest_horizon"),
            "shadow_recommendation": summary.get("shadow_recommendation") or raw.get("shadow_recommendation"),
            "profit_capture_next_action": "validate_profit_capture_policy_persistence_before_micro_test" if not ready else "human_review_for_tiny_paper_micro_test_candidate",
            "profit_capture_ready_for_micro_test": ready,
            "wiring_status": "wired_from_profit_capture_summary",
        }

    def _ranking_summary(self, statuses: dict[str, Any]) -> dict[str, Any]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        confidence = first(ranking.get("ranking_confidence_score"), ranking.get("confidence_score"), 0)
        ready = bool(to_float(ranking.get("ranking_quality_score"), 0) >= 75 and to_float(confidence, 0) >= 70 and to_float(ranking.get("evidence_count"), 0) >= 500)
        return {
            "ranking_attribution_score": rounded(first(ranking.get("ranking_quality_score"), ranking.get("attribution_quality"), 0), 3),
            "ranking_confidence_score": rounded(confidence, 3),
            "ranking_predictive_power": rounded(ranking.get("ranking_predictive_power"), 3),
            "ranking_reliability": rounded(ranking.get("ranking_reliability"), 3),
            "ranking_truth_score": rounded(ranking.get("ranking_truth_score"), 3),
            "ranking_accuracy": rounded(ranking.get("ranking_accuracy"), 3),
            "promotion_accuracy": rounded(ranking.get("promotion_accuracy"), 3),
            "rejection_accuracy": rounded(ranking.get("rejection_accuracy"), 3),
            "ranking_consistency": rounded(ranking.get("ranking_consistency"), 3),
            "strongest_positive_ranking_factor": ranking.get("strongest_positive_ranking_factor"),
            "strongest_negative_ranking_factor": ranking.get("strongest_negative_ranking_factor"),
            "most_predictive_ranking_factor": ranking.get("most_predictive_ranking_factor"),
            "least_predictive_ranking_factor": ranking.get("least_predictive_ranking_factor"),
            "most_overvalued_factor": ranking.get("most_overvalued_factor"),
            "most_undervalued_factor": ranking.get("most_undervalued_factor"),
            "dominant_ranking_blind_spot": ranking.get("dominant_ranking_blind_spot"),
            "next_ranking_focus": ranking.get("next_ranking_focus"),
            "highest_expected_ranking_improvement": ranking.get("highest_expected_ranking_improvement"),
            "candidate_ranking_influence_readiness": ranking.get("candidate_ranking_influence_readiness"),
            "strongest_ranking_lesson": ranking.get("strongest_ranking_lesson"),
            "strongest_promotion_lesson": ranking.get("strongest_promotion_lesson"),
            "strongest_rejection_lesson": ranking.get("strongest_rejection_lesson"),
            "evidence_count": to_int(ranking.get("evidence_count"), 0),
            "ranking_ready_for_micro_test": ready,
            "wiring_status": "wired_from_candidate_ranking_attribution",
        }

    def _learning_efficiency(self, storage: dict[str, Any], cache: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        rows = storage.get("storage_tier_inventory") or []
        summary_candidates = storage.get("summary_candidates") or []
        duplicates = to_int((status_value(statuses, "astra_autonomous_optimization_governance_core_v1").get("information_compression_summary") or {}).get("duplicate_observations"), 0)
        stale = to_int(cache.get("stale_decision_critical_cache_count"), 0)
        high_value = len(storage.get("canonical_truth_items") or []) + len(storage.get("hot_storage_items") or [])
        low_value = len(storage.get("cold_storage_items") or [])
        density = rounded((high_value / max(1, len(rows))) * 100.0, 3)
        signal = rounded(clamp(density - duplicates * 1.5 - stale * 2.0), 3)
        pressure = to_float(storage.get("storage_pressure_score"), 0)
        evidence_roi = rounded(clamp(signal * 0.6 + (100.0 - min(100.0, pressure)) * 0.4), 3)
        return {
            "learning_efficiency_score": signal,
            "evidence_roi_score": evidence_roi,
            "signal_to_noise_score": signal,
            "storage_pressure_score": rounded(pressure, 3),
            "high_value_evidence_count": high_value,
            "low_value_evidence_count": low_value,
            "duplicate_evidence": duplicates,
            "stale_evidence": stale,
            "evidence_density": density,
            "memory_usefulness": rounded((high_value / max(1, high_value + low_value)) * 100.0, 3),
            "retrieval_usefulness": rounded(cache.get("cache_trust_score"), 3),
            "is_collecting_too_much": bool(pressure >= 50 or len(summary_candidates) >= 8),
            "is_collecting_too_little": False,
            "most_useful_learning_source": (storage.get("canonical_truth_items") or storage.get("hot_storage_items") or [{}])[0].get("name", "canonical_truth_summaries"),
            "least_useful_learning_source": (storage.get("cold_storage_items") or [{}])[0].get("name", "none"),
            "compression_candidates": storage.get("safe_compaction_candidates") or [],
            "archive_candidates": storage.get("archive_candidates") or [],
            "summary_candidates": storage.get("summary_candidates") or [],
            "index_candidates": storage.get("index_candidates") or [],
            "learning_efficiency_recommendations": [
                "create_summary_indexes_for_large_jsonl_learning_files",
                "keep_canonical_truth_hot_or_protected",
                "serve_ui_from_cache_and_summary_layers_only",
                "refresh_decision_critical_caches_in_background",
            ],
        }

    def _fast_load(self, storage: dict[str, Any], cache: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        optimization = status_value(statuses, "astra_autonomous_optimization_governance_core_v1")
        slow = (optimization.get("resource_allocation_summary") or {}).get("slowest_endpoint") or {}
        return {
            "dashboard_fast_load_safe": True,
            "learning_tab_fast_load_safe": True,
            "unified_diagnostics_fast_load_safe": True,
            "heavy_scan_blocked_from_ui": True,
            "raw_scan_guard_active": True,
            "endpoint_latency_summary": {
                "slowest_endpoint": slow.get("system_name"),
                "slowest_latency_ms": slow.get("latency_ms"),
                "unified_cache_fallback_available": True,
            },
            "slow_endpoint_recommendations": [
                "keep_unified_diagnostics_cache_first",
                "return_persisted_cache_for_heavy_validation_endpoints",
                "run_raw_large_file_refreshes_only_in_bounded_background_or_force_paths",
            ],
            "initial_learning_tab_endpoint_count": 1,
            "dashboard_provider_calls_used": 0,
            "dashboard_llm_calls_used": 0,
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        storage = self._state_inventory()
        cache = self._cache_inventory()
        profit = self._profit_capture_summary(statuses)
        ranking = self._ranking_summary(statuses)
        learning = self._learning_efficiency(storage, cache, statuses)
        fast = self._fast_load(storage, cache, statuses)
        risk = rounded(clamp(to_float(storage.get("storage_pressure_score"), 0) * 0.7 + cache.get("stale_decision_critical_cache_count", 0) * 5.0), 3)
        recommendations = [
            "create_summary_indexes_for_large_cold_jsonl_files" if storage.get("summary_candidates") else "retain_current_storage_layout",
            "refresh_stale_decision_critical_caches_in_background" if cache.get("stale_decision_critical_cache_count") else "cache_freshness_ok",
            profit.get("profit_capture_next_action"),
            ranking.get("highest_expected_ranking_improvement") or "continue_ranking_attribution_validation",
            "preserve_canonical_truth_before_any_future_compaction",
        ]
        payload = {
            "enabled": True,
            "version": "1.0.0",
            "suite": "Astra Storage Architecture, Smart Cache, Attribution & Learning Efficiency Suite V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "storage_architecture_governance_v1": storage,
            "smart_cache_freshness_trust_v1": cache,
            "profit_capture_summary_validation_wiring_v1": profit,
            "ranking_attribution_summary_validation_wiring_v1": ranking,
            "learning_efficiency_evidence_roi_v1": learning,
            "fast_load_protection_v1": fast,
            "storage_tier_inventory": storage.get("storage_tier_inventory"),
            "hot_storage_items": storage.get("hot_storage_items"),
            "warm_storage_items": storage.get("warm_storage_items"),
            "cold_storage_items": storage.get("cold_storage_items"),
            "canonical_truth_items": storage.get("canonical_truth_items"),
            "oversized_state_items": storage.get("oversized_state_items"),
            "safe_compaction_candidates": storage.get("safe_compaction_candidates"),
            "archive_candidates": storage.get("archive_candidates"),
            "index_candidates": storage.get("index_candidates"),
            "summary_candidates": storage.get("summary_candidates"),
            "storage_risk_score": risk,
            "storage_pressure_score": storage.get("storage_pressure_score"),
            "storage_recommendations": recommendations,
            "cache_trust_score": cache.get("cache_trust_score"),
            "stale_decision_critical_cache_count": cache.get("stale_decision_critical_cache_count"),
            "profit_capture_confidence": profit.get("profit_capture_confidence"),
            "profit_capture_score": profit.get("profit_capture_score"),
            "ranking_attribution_score": ranking.get("ranking_attribution_score"),
            "ranking_confidence_score": ranking.get("ranking_confidence_score"),
            "learning_efficiency_score": learning.get("learning_efficiency_score"),
            "evidence_roi_score": learning.get("evidence_roi_score"),
            "dashboard_fast_load_safe": fast.get("dashboard_fast_load_safe"),
            "learning_tab_fast_load_safe": fast.get("learning_tab_fast_load_safe"),
            "unified_diagnostics_fast_load_safe": fast.get("unified_diagnostics_fast_load_safe"),
            "top_remaining_weaknesses": [
                "large_cold_storage_requires_summary_indexes" if storage.get("summary_candidates") else "none",
                "profit_capture_confidence_low" if to_float(profit.get("profit_capture_confidence"), 0) < 65 else "profit_capture_validating",
                "ranking_attribution_not_micro_test_ready" if not ranking.get("ranking_ready_for_micro_test") else "ranking_attribution_ready_for_review",
                "stale_decision_critical_cache" if cache.get("stale_decision_critical_cache_count") else "cache_trust_ok",
            ],
            "top_remaining_bottlenecks": [
                (storage.get("oversized_state_items") or [{}])[0].get("name", "none"),
                (cache.get("stale_decision_critical_cache_items") or [{}])[0].get("cache_name", "none"),
                fast.get("endpoint_latency_summary", {}).get("slowest_endpoint") or "none",
            ],
            "highest_roi_next_improvement": "create_summary_indexes_for_large_cold_storage_and_wire_profit_capture_validation",
            "recommended_next_roadmap_item": "storage_summary_indexing_profit_capture_validation_and_cache_refresh_governance",
            "learning_center_summary": {
                "storage_risk_score": risk,
                "storage_pressure_score": storage.get("storage_pressure_score"),
                "largest_state_files": storage.get("oversized_state_items", [])[:5],
                "hot_warm_cold_status": "tiered_inventory_ready",
                "cache_trust_score": cache.get("cache_trust_score"),
                "stale_decision_critical_cache_count": cache.get("stale_decision_critical_cache_count"),
                "profit_capture_confidence": profit.get("profit_capture_confidence"),
                "ranking_attribution_score": ranking.get("ranking_attribution_score"),
                "learning_efficiency_score": learning.get("learning_efficiency_score"),
                "dashboard_fast_load_status": "safe" if fast.get("dashboard_fast_load_safe") else "watch",
                "highest_roi_next_improvement": "create_summary_indexes_for_large_cold_storage_and_wire_profit_capture_validation",
                "top_recommendations": recommendations[:5],
            },
            "safety_confirmations": _safe_flags(),
            **_safe_flags(),
        }
        return with_safety(payload)
