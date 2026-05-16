"""Market Data Orchestration Engine V1.

Planning and governance only. This module never performs provider calls and never
starts broad collection workers. It centralizes provider roles, cache-first task
planning, quota/bandwidth budgets, and FMP optimizer-aware collection gates.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any


VERSION = "1.1.0"
BROAD_UNIVERSE_TARGET_COUNT = 7500
ACTIVE_UNIVERSE_TARGET_COUNT = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


class MarketDataOrchestrationEngine:
    """Builds cache-first market-data plans without executing heavy collection."""

    def __init__(self, state_dir: str = "state", fmp_optimizer: Any | None = None) -> None:
        self.state_dir = str(state_dir or "state")
        self.fmp_optimizer = fmp_optimizer
        self.cache_paths = {
            "fmp_enrichment": os.path.join(self.state_dir, "fmp_enrichment_cache_v1.json"),
            "fmp_efficiency_manifest": os.path.join(self.state_dir, "fmp_efficiency_manifest_v1.json"),
            "runtime_snapshot": os.path.join(self.state_dir, "runtime_top_buys_snapshot.json"),
            "trade_lifecycle": os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl"),
            "replay_results": os.path.join(self.state_dir, "replay_results_v2.json"),
            "candidate_ledger": os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl"),
        }
        self.provider_roles = {
            "alpaca_iex": {
                "primary_role": "live market scanning, open trade monitoring, watchlist updates, entered position tracking, websocket when available",
                "not_responsible_for": "broad whole-market historical or fundamental collection",
                "preferred_data": ["live_quotes", "open_trade_ticks", "watchlist_quotes", "position_state"],
            },
            "financial_modeling_prep": {
                "primary_role": "broad universe discovery, OHLCV history, fundamentals, statements, ratios, earnings, sectors, company profiles, replay enrichment",
                "governed_by": "FmpUtilizationOptimizer",
                "preferred_data": ["historical_ohlcv", "fundamentals", "financial_ratios", "earnings", "company_profiles", "sector_industry", "batch_market_enrichment"],
            },
            "finnhub": {"primary_role": "backup quote validation, earnings/news support, secondary enrichment"},
            "twelve_data": {"primary_role": "quote and intraday backup, secondary historical support"},
            "polygon": {"primary_role": "quote validation and intraday backup"},
            "alphavantage": {"primary_role": "low-frequency backup only"},
            "eodhd": {"primary_role": "supplemental historical and validation backup"},
        }
        self.priority_order = [
            "open_entered_trades",
            "current_top_buys",
            "current_rankings_candidates",
            "high_confidence_watchlist",
            "broad_market_scan_candidates",
            "historical_replay_counterfactual_candidates",
            "fundamentals_catalyst_enrichment",
            "low_priority_background_refresh",
        ]
        self.quota_targets = {
            "fmp_rolling_monthly_target_utilization_pct": 70.0,
            "fmp_normal_operating_band_pct": [55.0, 70.0],
            "fmp_soft_throttle_above_pct": 70.0,
            "fmp_hard_stop_above_pct": 80.0,
            "fmp_minimum_reserve_pct": 20.0,
            "heavy_collection_default_enabled": False,
            "controlled_broad_collection_enabled": True,
            "broad_universe_target_count": BROAD_UNIVERSE_TARGET_COUNT,
            "active_universe_target_count": ACTIVE_UNIVERSE_TARGET_COUNT,
        }
        self.ttls_seconds = {
            "live_quotes": 30,
            "open_trade_monitoring": 10,
            "top_buys_snapshot": 120,
            "rankings_candidates": 180,
            "intraday_backup": 300,
            "earnings_calendar": 21600,
            "fundamentals": 604800,
            "historical_ohlcv_daily": 86400,
            "company_profiles": 604800,
            "replay_inputs": 86400,
        }
        self.allowed_fmp_non_overlap_roles = [
            "historical_ohlcv",
            "fundamentals",
            "financial_statements",
            "financial_ratios",
            "earnings_calendar_and_history",
            "sector_industry_classification",
            "company_profile",
            "replay_counterfactual_enrichment",
            "market_wide_batch_enrichment",
            "validation_when_explicitly_marked_validation_needed",
        ]

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _count_jsonl(self, path: str, max_scan: int = 20000) -> int:
        if not os.path.exists(path):
            return 0
        count = 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for count, _line in enumerate(fh, start=1):
                    if count >= max_scan:
                        break
        except Exception:
            return 0
        return int(count)

    def _file_age_seconds(self, path: str) -> float | None:
        try:
            return max(0.0, time.time() - os.path.getmtime(path))
        except Exception:
            return None

    def _cache_summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, path in self.cache_paths.items():
            exists = os.path.exists(path)
            size = os.path.getsize(path) if exists else 0
            age = self._file_age_seconds(path) if exists else None
            out[name] = {
                "exists": bool(exists),
                "path": path,
                "bytes": int(size),
                "age_seconds": round(age, 3) if age is not None else None,
            }
        fmp_cache = self._read_json(self.cache_paths["fmp_enrichment"])
        out["fmp_enrichment"]["entries_estimated"] = len(fmp_cache) if isinstance(fmp_cache, dict) else 0
        out["trade_lifecycle"]["rows_estimated"] = self._count_jsonl(self.cache_paths["trade_lifecycle"])
        out["candidate_ledger"]["rows_estimated"] = self._count_jsonl(self.cache_paths["candidate_ledger"])
        return out

    def _fmp_status(self) -> dict[str, Any]:
        if self.fmp_optimizer is None:
            return {
                "enabled": False,
                "mode": "recommendation_plan_only",
                "current_usage_pct_estimated": 0.0,
                "target_usage_pct": 70.0,
                "safety_reserve_pct": 20.0,
                "soft_throttle_active": False,
                "hard_stop_active": False,
                "call_allowance_state": "optimizer_unavailable",
                "recommendation": "hold_usage",
            }
        try:
            status = self.fmp_optimizer.status()
            return status if isinstance(status, dict) else {}
        except Exception as exc:
            return {
                "enabled": False,
                "mode": "recommendation_plan_only",
                "current_usage_pct_estimated": 0.0,
                "target_usage_pct": 70.0,
                "safety_reserve_pct": 20.0,
                "soft_throttle_active": False,
                "hard_stop_active": False,
                "call_allowance_state": "optimizer_error",
                "recommendation": "hold_usage",
                "error": f"fmp_optimizer_unavailable: {exc}",
            }

    def _quota_state(self) -> dict[str, Any]:
        fmp = self._fmp_status()
        usage = _to_float(fmp.get("current_usage_pct_estimated"), 0.0)
        hard_stop = bool(fmp.get("hard_stop_active")) or usage >= 80.0 or bool(fmp.get("emergency_cutoff_active"))
        soft = bool(fmp.get("soft_throttle_active")) or usage >= 70.0
        allowed = not hard_stop and str(fmp.get("call_allowance_state") or "").lower() not in {"hard_stop", "optimizer_denied"}
        return {
            "fmp": fmp,
            "fmp_usage_pct": round(usage, 3),
            "fmp_soft_throttle_active": bool(soft),
            "fmp_hard_stop_active": bool(hard_stop),
            "fmp_optimizer_allows_planning": bool(allowed),
            "fmp_optimizer_recommendation": str(fmp.get("recommendation") or "unknown"),
        }

    def _overlap_policy(self) -> dict[str, Any]:
        return {
            "overlap_prevention_enabled": True,
            "fmp_duplicate_live_quote_blocked": True,
            "alpaca_iex_live_quote_ownership": True,
            "alpaca_iex_ownership_scope": [
                "iex_covered_active_trades",
                "iex_covered_watchlist_symbols",
                "iex_covered_top_candidates",
            ],
            "allowed_fmp_non_overlap_roles": list(self.allowed_fmp_non_overlap_roles),
            "fmp_validation_rule": "allow_only_when_validation_needed_true",
            "blocked_overlap_examples": [
                {
                    "example": "fmp_live_quote_for_active_trade_symbol",
                    "reason": "alpaca_iex_owns_live_quote_tracking_for_iex_covered_priority_symbols",
                },
                {
                    "example": "fmp_live_quote_for_top_buy_symbol_without_validation_needed",
                    "reason": "duplicate_basic_live_quote_collection_blocked",
                },
                {
                    "example": "fmp_intraday_quote_poll_for_watchlist_symbol_already_on_alpaca_iex",
                    "reason": "quote_overlap_prevention_policy",
                },
            ],
        }

    def _task_rows(self, top_buy_count: int = 0, rankings_count: int = 0) -> list[dict[str, Any]]:
        tasks = [
            {
                "id": "open_entered_trades",
                "priority": 1,
                "data_wanted_next": ["live quote", "position state", "exit trigger context", "volatility state"],
                "why_valuable": "Protects active capital and improves exit quality / candidate-to-position quality.",
                "provider": "alpaca_iex",
                "estimated_calls": 0,
                "estimated_bandwidth_kb": 32,
                "cache_key": "trade_lifecycle",
                "execution_allowed_now": True,
                "execution_mode": "websocket_preferred_gradual_polling_fallback",
            },
            {
                "id": "current_top_buys",
                "priority": 2,
                "data_wanted_next": ["fresh quotes", "quote validation", "near-term catalyst flags"],
                "why_valuable": "Keeps released candidates accurate without widening broad collection.",
                "provider": "alpaca_iex_primary_with_finnhub_polygon_validation_if_needed",
                "estimated_calls": max(0, min(3, top_buy_count)),
                "estimated_bandwidth_kb": 48,
                "cache_key": "runtime_snapshot",
                "execution_allowed_now": True,
                "execution_mode": "cache_first_small_batch_only",
                "validation_needed": False,
            },
            {
                "id": "current_rankings_candidates",
                "priority": 3,
                "data_wanted_next": ["quote freshness", "provider agreement", "sector context"],
                "why_valuable": "Improves entry quality and confidence truthfulness for already-visible candidates.",
                "provider": "alpaca_iex_primary_fmp_sector_context_if_optimizer_allows",
                "estimated_calls": max(0, min(4, rankings_count)),
                "estimated_bandwidth_kb": 72,
                "cache_key": "runtime_snapshot",
                "execution_allowed_now": True,
                "execution_mode": "cache_first_targeted_refresh",
                "validation_needed": False,
            },
            {
                "id": "high_confidence_watchlist",
                "priority": 4,
                "data_wanted_next": ["intraday quote", "volume confirmation", "event proximity"],
                "why_valuable": "Prepares watchlist names without broad-market sweep behavior.",
                "provider": "alpaca_iex_with_twelve_data_backup",
                "estimated_calls": 5,
                "estimated_bandwidth_kb": 96,
                "cache_key": "candidate_ledger",
                "execution_allowed_now": False,
                "execution_mode": "planned_only_until_explicit_worker_enable",
            },
            {
                "id": "broad_market_scan_candidates",
                "priority": 5,
                "data_wanted_next": ["universe discovery", "liquidity screens", "sector leaders", "high-volume movers"],
                "why_valuable": "Expands candidate diversity for better buy list purity and opportunity coverage.",
                "provider": "financial_modeling_prep_batch_endpoints",
                "estimated_calls": 8,
                "estimated_bandwidth_kb": 512,
                "cache_key": "fmp_enrichment",
                "execution_allowed_now": True,
                "execution_mode": "controlled_staged_collection_small_batch_only",
            },
            {
                "id": "historical_replay_counterfactual_candidates",
                "priority": 6,
                "data_wanted_next": ["daily OHLCV history", "split/dividend adjusted history", "replay windows"],
                "why_valuable": "Feeds replay and counterfactual learning without touching live rankings.",
                "provider": "financial_modeling_prep_when_optimizer_allows_else_eodhd_supplemental_plan",
                "estimated_calls": 10,
                "estimated_bandwidth_kb": 2048,
                "cache_key": "replay_results",
                "execution_allowed_now": True,
                "execution_mode": "controlled_staged_collection_small_batch_only",
            },
            {
                "id": "fundamentals_catalyst_enrichment",
                "priority": 7,
                "data_wanted_next": ["financial statements", "ratios", "earnings calendar", "company profile", "sector industry"],
                "why_valuable": "Improves confidence truthfulness, catalyst awareness, and entry quality.",
                "provider": "financial_modeling_prep_primary_finnhub_news_backup",
                "estimated_calls": 12,
                "estimated_bandwidth_kb": 1536,
                "cache_key": "fmp_enrichment",
                "execution_allowed_now": True,
                "execution_mode": "controlled_staged_collection_cache_first",
                "validation_needed": False,
            },
            {
                "id": "low_priority_background_refresh",
                "priority": 8,
                "data_wanted_next": ["aged cache refresh", "low-frequency validation", "stale fundamentals"],
                "why_valuable": "Maintains data completeness without competing with active trading needs.",
                "provider": "lowest_cost_available_provider_for_missing_field",
                "estimated_calls": 4,
                "estimated_bandwidth_kb": 384,
                "cache_key": "fmp_enrichment",
                "execution_allowed_now": False,
                "execution_mode": "disabled_until_explicit_background_collection_enable",
            },
        ]
        cache = self._cache_summary()
        quota = self._quota_state()
        fmp_hard_stop = bool(quota.get("fmp_hard_stop_active"))
        for task in tasks:
            cache_info = cache.get(str(task.get("cache_key")), {})
            task["cache_availability"] = {
                "exists": bool(cache_info.get("exists")),
                "age_seconds": cache_info.get("age_seconds"),
                "bytes": cache_info.get("bytes", 0),
            }
            if "financial_modeling_prep" in str(task.get("provider")) and fmp_hard_stop:
                task["execution_allowed_now"] = False
                task["blocked_reason"] = "fmp_optimizer_hard_stop_or_denial"
            elif task.get("execution_allowed_now") is False:
                task["blocked_reason"] = "heavy_or_background_collection_disabled_by_default"
        return tasks

    def _budget_summary(self, tasks: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        allowed = [t for t in tasks if bool(t.get("execution_allowed_now"))]
        planned_calls = sum(_to_int(t.get("estimated_calls"), 0) for t in tasks)
        allowed_calls = sum(_to_int(t.get("estimated_calls"), 0) for t in allowed)
        planned_kb = sum(_to_float(t.get("estimated_bandwidth_kb"), 0.0) for t in tasks)
        allowed_kb = sum(_to_float(t.get("estimated_bandwidth_kb"), 0.0) for t in allowed)
        return (
            {
                "estimated_planned_calls_all_tasks": int(planned_calls),
                "estimated_calls_allowed_now": int(allowed_calls),
                "heavy_collection_calls_enabled": int(allowed_calls),
                "duplicate_call_avoidance": "cache_key_and_provider_role_checked_before_request",
                "delta_only_refresh_required": True,
                "batch_endpoint_preferred": True,
            },
            {
                "estimated_planned_bandwidth_kb_all_tasks": round(planned_kb, 3),
                "estimated_bandwidth_kb_allowed_now": round(allowed_kb, 3),
                "bandwidth_pressure": "low" if allowed_kb < 512 else "moderate",
                "heavy_collection_bandwidth_enabled_kb": round(allowed_kb, 3),
            },
        )

    def status(self, top_buy_count: int = 0, rankings_count: int = 0) -> dict[str, Any]:
        tasks = self._task_rows(top_buy_count=top_buy_count, rankings_count=rankings_count)
        call_budget, bandwidth_budget = self._budget_summary(tasks)
        quota = self._quota_state()
        overlap_policy = self._overlap_policy()
        blocked = [t for t in tasks if not bool(t.get("execution_allowed_now"))]
        allowed = [t for t in tasks if bool(t.get("execution_allowed_now"))]
        fmp_status = quota.get("fmp", {}) if isinstance(quota.get("fmp"), dict) else {}
        usage = _to_float(fmp_status.get("current_usage_pct_estimated"), 0.0)
        return {
            "enabled": True,
            "version": VERSION,
            "market_data_orchestration_status_v1": True,
            "mode": "planning_governance_only",
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "provider_roles": self.provider_roles,
            "quota_targets": self.quota_targets,
            "current_quota_state": quota,
            "call_budget_summary": call_budget,
            "bandwidth_budget_summary": bandwidth_budget,
            "active_trade_monitoring_mode": "websocket_preferred_gradual_polling_fallback",
            "broad_collection_enabled": True,
            "collection_enabled": True,
            "collection_allowed_now": bool(allowed) and not bool(quota.get("fmp_hard_stop_active")),
            "broad_universe_target_count": BROAD_UNIVERSE_TARGET_COUNT,
            "broad_universe_collected_count": int(_to_float((self._cache_summary().get("fmp_enrichment") or {}).get("entries_estimated"), 0.0)),
            "active_universe_target_count": ACTIVE_UNIVERSE_TARGET_COUNT,
            "active_universe_current_count": min(ACTIVE_UNIVERSE_TARGET_COUNT, int(top_buy_count) + int(rankings_count)),
            "collection_progress_pct": round(
                min(100.0, (_to_float((self._cache_summary().get("fmp_enrichment") or {}).get("entries_estimated"), 0.0) / max(1, BROAD_UNIVERSE_TARGET_COUNT)) * 100.0),
                3,
            ),
            "overlap_prevention_enabled": bool(overlap_policy.get("overlap_prevention_enabled", False)),
            "fmp_duplicate_live_quote_blocked": bool(overlap_policy.get("fmp_duplicate_live_quote_blocked", False)),
            "alpaca_iex_live_quote_ownership": bool(overlap_policy.get("alpaca_iex_live_quote_ownership", False)),
            "allowed_fmp_non_overlap_roles": list(overlap_policy.get("allowed_fmp_non_overlap_roles") or []),
            "blocked_overlap_examples": list(overlap_policy.get("blocked_overlap_examples") or []),
            "overlap_policy": overlap_policy,
            "highest_priority_tasks": tasks[:4],
            "blocked_tasks": blocked,
            "reserve_levels": {
                "fmp_reserve_pct_estimated": round(max(0.0, 100.0 - usage), 3),
                "minimum_fmp_reserve_pct": 20.0,
                "broad_collection_reserve_protected": True,
            },
            "cache_hit_expectation": self._cache_summary(),
            "api_efficiency_policy": {
                "delta_only_refresh_planning_enabled": True,
                "batch_endpoint_optimizer_enabled": True,
                "smart_ttl_policy_enabled": True,
                "data_deduplication_hashing_enabled": True,
                "synthetic_replay_expansion_uses_local_data_only": True,
            },
            "expected_learning_benefits": [
                "entry_quality",
                "released_win_rate",
                "buy_list_purity",
                "confidence_truthfulness",
                "exit_quality",
                "candidate_to_position_quality",
                "overall_trade_expectancy",
            ],
        }

    def plan(self, top_buy_count: int = 0, rankings_count: int = 0) -> dict[str, Any]:
        tasks = self._task_rows(top_buy_count=top_buy_count, rankings_count=rankings_count)
        call_budget, bandwidth_budget = self._budget_summary(tasks)
        overlap_policy = self._overlap_policy()
        return {
            "enabled": True,
            "version": VERSION,
            "market_data_orchestration_plan_v1": True,
            "mode": "planning_governance_only",
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "what_data_astra_wants_next": tasks,
            "call_budget_summary": call_budget,
            "bandwidth_budget_summary": bandwidth_budget,
            "execution_allowed_now": [t for t in tasks if bool(t.get("execution_allowed_now"))],
            "execution_blocked_now": [t for t in tasks if not bool(t.get("execution_allowed_now"))],
            "broad_collection_enabled": True,
            "collection_enabled": True,
            "broad_universe_target_count": BROAD_UNIVERSE_TARGET_COUNT,
            "active_universe_target_count": ACTIVE_UNIVERSE_TARGET_COUNT,
            "overlap_prevention_enabled": bool(overlap_policy.get("overlap_prevention_enabled", False)),
            "fmp_duplicate_live_quote_blocked": bool(overlap_policy.get("fmp_duplicate_live_quote_blocked", False)),
            "alpaca_iex_live_quote_ownership": bool(overlap_policy.get("alpaca_iex_live_quote_ownership", False)),
            "allowed_fmp_non_overlap_roles": list(overlap_policy.get("allowed_fmp_non_overlap_roles") or []),
            "blocked_overlap_examples": list(overlap_policy.get("blocked_overlap_examples") or []),
            "overlap_policy": overlap_policy,
        }

    def active_trade_plan(self, open_trade_count: int = 0, watchlist_count: int = 0) -> dict[str, Any]:
        rapid_movement = max(0, int(open_trade_count)) > 0
        cadence = "10-30s polling fallback" if rapid_movement else "60-180s gradual polling fallback"
        return {
            "enabled": True,
            "version": VERSION,
            "active_trade_data_plan_v1": True,
            "mode": "planning_governance_only",
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "provider": "alpaca_iex",
            "preferred_transport": "websocket_streaming_when_available",
            "fallback_transport": cadence,
            "open_trade_count_estimated": int(max(0, open_trade_count)),
            "watchlist_count_estimated": int(max(0, watchlist_count)),
            "increase_frequency_when": ["rapid_movement", "earnings", "high_volatility", "exit_trigger_conditions"],
            "reduce_frequency_when": ["inactive_position", "stable_price_action", "no_exit_pressure"],
            "execution_allowed_now": True,
            "broad_collection_enabled": True,
            "estimated_calls": max(0, min(12, int(open_trade_count) + int(watchlist_count))),
            "estimated_bandwidth_kb": 64 + (max(0, int(open_trade_count)) * 16),
            "cache_policy": "reuse quote/position state inside TTL before any polling fallback",
        }

    def fmp_market_collection_plan(self, symbol_count: int = 0) -> dict[str, Any]:
        quota = self._quota_state()
        fmp_status = quota.get("fmp", {}) if isinstance(quota.get("fmp"), dict) else {}
        overlap_policy = self._overlap_policy()
        hard_stop = bool(quota.get("fmp_hard_stop_active"))
        soft = bool(quota.get("fmp_soft_throttle_active"))
        collection_allowed = not hard_stop and not soft
        reason = ""
        if hard_stop:
            reason = "fmp_optimizer_hard_stop_or_denial"
        elif soft:
            reason = "fmp_optimizer_soft_throttle_active"
        phases = [
            {"phase": "universe_discovery", "provider": "financial_modeling_prep", "estimated_calls": 1, "estimated_bandwidth_kb": 256, "batch_preferred": True},
            {"phase": "liquidity_and_sector_leaders", "provider": "financial_modeling_prep", "estimated_calls": 2, "estimated_bandwidth_kb": 384, "batch_preferred": True},
            {"phase": "daily_ohlcv_history", "provider": "financial_modeling_prep", "estimated_calls": max(1, min(20, int(symbol_count) or 6)), "estimated_bandwidth_kb": 2048, "batch_preferred": True},
            {"phase": "fundamentals_ratios_profiles", "provider": "financial_modeling_prep", "estimated_calls": max(1, min(20, int(symbol_count) or 6)), "estimated_bandwidth_kb": 1536, "batch_preferred": True},
            {"phase": "earnings_catalysts", "provider": "financial_modeling_prep", "estimated_calls": 2, "estimated_bandwidth_kb": 512, "batch_preferred": True},
            {
                "phase": "backup_validation",
                "provider": "finnhub_twelve_data_polygon_eodhd_as_needed",
                "estimated_calls": 0,
                "estimated_bandwidth_kb": 0,
                "batch_preferred": False,
                "validation_needed": True,
            },
        ]
        return {
            "enabled": True,
            "version": VERSION,
            "fmp_market_collection_plan_v1": True,
            "mode": "planning_governance_only",
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "authority": "FmpUtilizationOptimizer",
            "quota_targets": self.quota_targets,
            "current_quota_state": quota,
            "broad_collection_enabled": True,
            "collection_enabled": True,
            "execution_allowed_now": bool(collection_allowed),
            "blocked_reason": reason,
            "broad_universe_target_count": BROAD_UNIVERSE_TARGET_COUNT,
            "active_universe_target_count": ACTIVE_UNIVERSE_TARGET_COUNT,
            "collection_progress_pct": round(
                min(100.0, (_to_float((self._cache_summary().get("fmp_enrichment") or {}).get("entries_estimated"), 0.0) / max(1, BROAD_UNIVERSE_TARGET_COUNT)) * 100.0),
                3,
            ),
            "controlled_staged_collection_only": True,
            "uncontrolled_bulk_collection_enabled": False,
            "never_bypass_optimizer_denial": True,
            "overlap_prevention_enabled": bool(overlap_policy.get("overlap_prevention_enabled", False)),
            "fmp_duplicate_live_quote_blocked": bool(overlap_policy.get("fmp_duplicate_live_quote_blocked", False)),
            "alpaca_iex_live_quote_ownership": bool(overlap_policy.get("alpaca_iex_live_quote_ownership", False)),
            "allowed_fmp_non_overlap_roles": list(overlap_policy.get("allowed_fmp_non_overlap_roles") or []),
            "blocked_overlap_examples": list(overlap_policy.get("blocked_overlap_examples") or []),
            "overlap_policy": overlap_policy,
            "planned_phases": phases,
            "estimated_calls": int(sum(_to_int(p.get("estimated_calls"), 0) for p in phases)),
            "estimated_bandwidth_kb": round(sum(_to_float(p.get("estimated_bandwidth_kb"), 0.0) for p in phases), 3),
            "cache_first_checks": self._cache_summary(),
            "optimizer_snapshot": fmp_status,
        }
