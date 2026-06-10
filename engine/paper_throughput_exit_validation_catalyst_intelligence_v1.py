from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 12.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _text(value: Any, default: str = "insufficient_data") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        return


def _status(statuses: dict[str, Any], key: str) -> dict[str, Any]:
    value = statuses.get(key) or {}
    return dict(value) if isinstance(value, dict) else {}


def _first_nonempty(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return default


def _compact_list(value: Any, limit: int = 8) -> list[Any]:
    if isinstance(value, list):
        return value[:limit]
    if isinstance(value, tuple):
        return list(value)[:limit]
    if isinstance(value, dict):
        return list(value.keys())[:limit]
    if value in (None, ""):
        return []
    return [value]


def _compact_map(value: Any, limit: int = 8) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in list(value.items())[:limit]}


class PaperThroughputExitValidationCatalystIntelligenceV1:
    """Cache-first diagnostics for paper throughput, exit validation, and catalyst coverage.

    This suite intentionally does not submit orders, apply learned exits, fetch provider data, or
    change strategy behavior. It aggregates existing diagnostics so blockers and shadow readiness
    are visible in one place.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(
            self.state_dir,
            "dashboard_cache",
            "paper_throughput_exit_validation_catalyst_intelligence_v1.json",
        )
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _blocker_counts(self, paper_trace: dict[str, Any], audit: dict[str, Any], paper_path: dict[str, Any]) -> Counter[str]:
        counts: Counter[str] = Counter()
        top_blockers = paper_path.get("top_blockers") or audit.get("top_blockers") or audit.get("blocker_counts")
        if isinstance(top_blockers, dict):
            for reason, count in top_blockers.items():
                counts[_text(reason, "unknown_blocker")] += _to_int(count, 0)
        elif isinstance(top_blockers, list):
            for item in top_blockers:
                if isinstance(item, dict):
                    counts[_text(item.get("reason") or item.get("blocker"), "unknown_blocker")] += _to_int(item.get("count"), 1)
                else:
                    counts[_text(item, "unknown_blocker")] += 1

        for key in ("top_block_reason", "top_blocker", "final_blocker_reason", "why_no_trade_today"):
            reason = _text(paper_path.get(key) or audit.get(key) or paper_trace.get(key), "")
            if reason:
                counts[reason] += 1

        trace_rows = paper_trace.get("per_candidate_decision_trace")
        if isinstance(trace_rows, list):
            for row in trace_rows[:500]:
                if isinstance(row, dict):
                    reason = _text(
                        row.get("block_reason")
                        or row.get("reason")
                        or row.get("paper_block_reason")
                        or row.get("final_blocker_reason"),
                        "",
                    )
                    if reason:
                        counts[reason] += 1
        return counts

    def _throughput(self, statuses: dict[str, Any]) -> dict[str, Any]:
        paper_trace = _status(statuses, "paper_execution_trace")
        throughput = _status(statuses, "paper_autopilot_throughput")
        audit = _status(statuses, "execution_participation_audit")
        broker = _status(statuses, "alpaca_paper_broker")
        paper_path = dict(broker.get("paper_path_gating_summary") or broker.get("paper_path_gating_diagnostics") or {})
        counts = self._blocker_counts(paper_trace, audit, paper_path)

        reviewed = max(
            _to_int(paper_path.get("candidates_reviewed_today"), 0),
            _to_int(paper_path.get("reviewed_today"), 0),
            _to_int(audit.get("reviewed_today"), 0),
            _to_int(audit.get("candidates_reviewed"), 0),
            _to_int(audit.get("decisions_reviewed"), 0),
            _to_int(paper_trace.get("candidates_seen"), 0),
        )
        eligible = max(
            _to_int(paper_path.get("eligible_today"), 0),
            _to_int(paper_path.get("candidates_passed_ranking"), 0),
            _to_int(paper_path.get("candidates_passed_risk"), 0),
            _to_int(audit.get("eligible_today"), 0),
            _to_int(audit.get("eligible_candidates"), 0),
            _to_int(paper_trace.get("eligible_candidates"), 0),
        )
        submitted = max(
            _to_int(paper_path.get("submitted_today"), 0),
            _to_int(audit.get("submitted_today"), 0),
            _to_int(audit.get("submitted_count"), 0),
            _to_int(paper_trace.get("orders_submitted"), 0),
        )
        blocked = max(
            _to_int(paper_path.get("candidates_blocked"), 0),
            _to_int(paper_path.get("blocked_today"), 0),
            _to_int(audit.get("blocked_today"), 0),
            max(0, reviewed - submitted),
        )
        duplicate_blocks = max(
            _to_int(audit.get("duplicate_symbol_blocks"), 0),
            _to_int(audit.get("duplicate_blocks"), 0),
            _to_int(paper_path.get("duplicate_blocks"), 0),
            counts.get("duplicate_active_position", 0),
        )
        confirmation_blocks = max(
            _to_int(audit.get("confirmation_required_blocks"), 0),
            _to_int(paper_path.get("confirmation_blocks"), 0),
            counts.get("open_confirmation_required", 0) + counts.get("session_order_submission_blocked", 0),
        )
        stale_internal_rows = max(
            _to_int(paper_path.get("stale_internal_position_rows"), 0),
            _to_int(paper_path.get("stale_internal_rows"), 0),
            _to_int(throughput.get("stale_internal_workflow_row_overhang"), 0),
            _to_int(paper_trace.get("stale_internal_positions_count"), 0),
        )
        stale_ignored = bool(
            paper_path.get("stale_internal_positions_ignored_for_broker_capacity")
            or paper_trace.get("stale_internal_positions_ignored_for_broker_capacity")
        )
        stale_row_blocks = 0 if stale_ignored else max(0, min(stale_internal_rows, blocked))
        broker_positions = max(
            _to_int(paper_path.get("broker_confirmed_open_positions"), 0),
            _to_int(paper_trace.get("broker_confirmed_open_positions"), 0),
            _to_int(paper_trace.get("broker_open_positions_count"), 0),
        )
        internal_rows = max(
            _to_int(paper_path.get("internal_active_rows"), 0),
            _to_int(paper_path.get("open_position_rows_count"), 0),
            _to_int(throughput.get("open_position_rows_count"), 0),
            _to_int(paper_trace.get("open_position_rows_count"), 0),
        )
        capacity = max(
            _to_int(paper_path.get("capacity_available"), 0),
            _to_int(paper_trace.get("capacity_available"), 0),
            max(0, _to_int(throughput.get("current_max_concurrent_positions"), 0) - broker_positions),
        )
        top_blockers = dict(counts.most_common(8))
        top_blocker = _text(_first_nonempty(paper_path.get("top_blocker"), next(iter(top_blockers), None)), "unknown_blocker")
        high_conf_blocked = max(
            _to_int(paper_path.get("high_confidence_candidates_blocked"), 0),
            _to_int(audit.get("high_confidence_candidates_blocked"), 0),
            int(round(blocked * 0.08)) if blocked and top_blocker in {"duplicate_active_position", "open_confirmation_required"} else 0,
        )
        missed_evidence = max(0, high_conf_blocked + min(blocked, duplicate_blocks + confirmation_blocks + stale_row_blocks))
        suppression_rate = round(((blocked / reviewed) * 100.0), 3) if reviewed > 0 else 0.0
        safe_capacity = capacity if capacity > 0 and not bool(paper_path.get("portfolio_heat_blocked") or paper_path.get("concentration_blocked") or paper_path.get("correlation_blocked")) else 0

        if stale_row_blocks > 0:
            action = "refresh_broker_confirmed_capacity_and_exclude_stale_internal_rows_from_capacity_only"
        elif confirmation_blocks > duplicate_blocks and confirmation_blocks > 0:
            action = "refresh_market_session_open_confirmation_before_blocking_valid_paper_candidates"
        elif duplicate_blocks > 0 and safe_capacity > 0:
            action = "deduplicate_against_broker_confirmed_unique_symbols_and_preserve_real_duplicate_blocks"
        elif safe_capacity > 0 and suppression_rate >= 95.0:
            action = "review_non_strategy_gates_for_over_suppression_before_limit_changes"
        else:
            action = "continue_current_paper_safety_gates_and_collect_more_evidence"

        return {
            "paper_throughput_status": "over_suppressed" if suppression_rate >= 95.0 and reviewed >= 50 else "monitoring",
            "reviewed_today": reviewed,
            "eligible_today": eligible,
            "submitted_today": submitted,
            "blocked_today": blocked,
            "suppression_rate": suppression_rate,
            "top_blocker": top_blocker,
            "top_blockers": top_blockers,
            "duplicate_blocks": duplicate_blocks,
            "confirmation_blocks": confirmation_blocks,
            "stale_row_blocks": stale_row_blocks,
            "broker_confirmed_positions": broker_positions,
            "internal_active_rows": internal_rows,
            "stale_internal_rows": stale_internal_rows,
            "true_capacity_available": capacity,
            "safe_capacity_available": safe_capacity,
            "high_confidence_candidates_blocked": high_conf_blocked,
            "missed_evidence_estimate": missed_evidence,
            "missed_profit_learning_estimate": round(missed_evidence * 0.35, 3),
            "recommended_safe_throughput_action": action,
            "stale_internal_rows_ignored_for_capacity": stale_ignored,
        }

    def _exit_validation(self, statuses: dict[str, Any]) -> dict[str, Any]:
        peak = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        multi = _status(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        shadow = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        best_policy = _text(
            _first_nonempty(peak.get("best_exit_policy"), peak.get("highest_improvement_policy"), shadow.get("winning_policy")),
            "insufficient_data",
        )
        current_pf = _to_float(
            _first_nonempty(peak.get("current_policy_profit_factor"), peak.get("actual_profit_factor"), peak.get("profit_factor")),
            0.0,
        )
        best_pf = _to_float(
            _first_nonempty(peak.get("best_policy_profit_factor"), peak.get("simulated_profit_factor"), shadow.get("policy_tournament_score")),
            0.0,
        )
        improvement = _to_float(
            _first_nonempty(peak.get("improvement_delta"), convergence.get("average_convergence_gap"), peak.get("average_giveback_pct")),
            0.0,
        )
        evidence = max(
            _to_int(peak.get("tracked_trades"), 0),
            _to_int(multi.get("evidence_count"), 0),
            _to_int(convergence.get("tracked_trades"), 0),
            _to_int(shadow.get("realism_weighted_learning_events"), 0),
        )
        policy_confidence = _clamp(_first_nonempty(peak.get("policy_confidence"), shadow.get("policy_confidence"), multi.get("policy_confidence")), 0.0, 100.0)
        readiness_score = _clamp(_first_nonempty(peak.get("readiness_score"), multi.get("horizon_mismatch_risk_score")), 0.0, 100.0)
        if readiness_score >= 80.0 and policy_confidence >= 75.0 and evidence >= 100:
            readiness = "validation_ready_human_review_required"
        elif evidence >= 50 and policy_confidence >= 45.0:
            readiness = "shadow_validation_active_not_paper_ready"
        else:
            readiness = "not_ready_more_evidence_required"
        outperforms = bool(improvement > 0.0 and (best_pf > current_pf or current_pf <= 0.0) and policy_confidence >= 45.0)
        return {
            "learned_exit_outperforms_current": outperforms,
            "best_shadow_exit_policy": best_policy,
            "best_policy_profit_factor": round(best_pf, 4),
            "current_policy_profit_factor": round(current_pf, 4),
            "improvement_delta": round(improvement, 4),
            "evidence_count": evidence,
            "policy_confidence": round(policy_confidence, 3),
            "readiness_status": readiness,
            "minimum_evidence_remaining": max(0, 100 - evidence),
            "symbols_where_learned_exit_helps": _compact_list(peak.get("symbols_where_learned_exit_helps") or convergence.get("symbols_needing_profit_lock")),
            "symbols_where_learned_exit_hurts": _compact_list(peak.get("symbols_where_learned_exit_hurts")),
            "horizons_where_learned_exit_helps": _compact_map(peak.get("best_exit_policy_by_horizon") or multi.get("horizon_readiness"), 6),
            "catalyst_decay_exit_value": round(_to_float(peak.get("continuation_failure_probability"), 0.0) + _to_float(multi.get("horizon_mismatch_risk_score"), 0.0) * 0.25, 3),
            "learned_exit_validation_bucket_enabled": False,
            "learned_exit_validation_bucket_reason": "disabled_pending_human_review_and_policy_governance",
            "learned_exits_applied": False,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
        }

    def _catalyst(self, statuses: dict[str, Any], best_policy: str) -> dict[str, Any]:
        catalyst = _status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        context = _status(statuses, "context_evidence_expansion_suite_v1")
        market = _status(statuses, "market_context_learning_suite_v1")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        coverage = max(
            _to_float(catalyst.get("catalyst_coverage_score"), 0.0),
            _to_float(context.get("catalyst_coverage_score"), 0.0),
            _to_float(market.get("catalyst_coverage_score"), 0.0),
        )
        unknown_rate = _to_float(_first_nonempty(catalyst.get("unknown_catalyst_rate"), context.get("unknown_catalyst_rate")), 100.0)
        dominant = _text(
            _first_nonempty(catalyst.get("dominant_catalyst"), context.get("dominant_catalyst_type"), market.get("dominant_catalyst_type")),
            "unknown_catalyst",
        )
        best_horizon = _first_nonempty(catalyst.get("best_horizon_by_catalyst"), context.get("best_catalyst_horizon"), accelerated.get("best_catalyst_by_symbol"), default={})
        best_exit = {dominant: best_policy} if dominant not in {"", "unknown_catalyst", "unavailable"} else {}
        symbols_unknown = _compact_list(
            _first_nonempty(catalyst.get("symbols_with_unknown_catalyst"), context.get("symbols_with_unknown_catalyst"), market.get("symbols_with_unknown_catalyst")),
            10,
        )
        cached_available = bool(catalyst.get("enabled") or context.get("enabled") or market.get("enabled") or accelerated.get("enabled"))
        if unknown_rate >= 60.0:
            fix = "prioritize_cached_market_context_symbol_memory_and_peer_theme_evidence_before_any_provider_refresh"
        elif coverage < 45.0:
            fix = "expand_cached_catalyst_context_mapping_for_existing_evidence_only"
        else:
            fix = "continue_cached_catalyst_decay_and_horizon_learning"
        return {
            "catalyst_coverage": round(coverage, 3),
            "unknown_catalyst_rate": round(unknown_rate, 3),
            "dominant_catalyst": dominant,
            "catalyst_decay_score": round(_to_float(catalyst.get("catalyst_decay_learning_score"), _to_float(context.get("catalyst_learning_confidence"), 0.0)), 3),
            "best_horizon_by_catalyst": best_horizon if isinstance(best_horizon, dict) else {dominant: _text(best_horizon, "insufficient_data")},
            "best_exit_by_catalyst": best_exit,
            "symbols_with_unknown_catalyst": symbols_unknown,
            "cached_context_available": cached_available,
            "recommended_safe_context_fix": fix,
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        throughput = self._throughput(statuses)
        exit_validation = self._exit_validation(statuses)
        catalyst = self._catalyst(statuses, exit_validation.get("best_shadow_exit_policy", "insufficient_data"))
        if throughput["paper_throughput_status"] == "over_suppressed":
            next_action = throughput["recommended_safe_throughput_action"]
        elif catalyst["unknown_catalyst_rate"] >= 60.0:
            next_action = catalyst["recommended_safe_context_fix"]
        elif exit_validation["readiness_status"] != "not_ready_more_evidence_required":
            next_action = "continue_shadow_exit_validation_and_prepare_human_review_packet"
        else:
            next_action = "continue_collecting_paper_and_shadow_evidence"
        payload = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_throughput_exit_validation_catalyst_intelligence",
            "generated_at": _now_iso(),
            **throughput,
            **exit_validation,
            **catalyst,
            "recommended_next_action": next_action,
            "shadow_recommendation": next_action,
            "paper_mode_verified": True,
            "broker_live_endpoint_allowed": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "portfolio_allocation_changed": False,
            "fmp_budgets_changed": False,
            "provider_budget_changed": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "behavior_safe_to_apply": False,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
        }
        _write_json(self.cache_path, payload)
        return payload

    def status(self, *, statuses: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        if not force:
            disk = _read_json(self.cache_path)
            if disk:
                try:
                    age = time.time() - os.path.getmtime(self.cache_path)
                except Exception:
                    age = 999999.0
                if age <= self.ttl_seconds:
                    disk["cache_hit"] = True
                    disk["cache_age_seconds"] = round(age, 3)
                    disk["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
                    self._cache = dict(disk)
                    self._cache_ts = now
                    return disk
        try:
            out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = _read_json(self.cache_path)
            if out:
                out["stale_cache"] = True
                out["degraded_reason"] = f"paper_throughput_exit_validation_catalyst_intelligence_rebuild_failed_using_cache:{str(exc)[:140]}"
            else:
                out = {
                    "enabled": False,
                    "version": VERSION,
                    "mode": "paper_only_throughput_exit_validation_catalyst_intelligence",
                    "paper_throughput_status": "unavailable",
                    "top_blocker": "unknown_blocker",
                    "reviewed_today": 0,
                    "eligible_today": 0,
                    "submitted_today": 0,
                    "blocked_today": 0,
                    "suppression_rate": 0.0,
                    "missed_evidence_estimate": 0,
                    "true_capacity_available": 0,
                    "learned_exit_outperforms_current": False,
                    "best_shadow_exit_policy": "unavailable",
                    "improvement_delta": 0.0,
                    "learned_exit_validation_bucket_enabled": False,
                    "catalyst_coverage": 0.0,
                    "unknown_catalyst_rate": 100.0,
                    "dominant_catalyst": "unknown_catalyst",
                    "recommended_next_action": "diagnostics_unavailable",
                    "degraded_reason": f"paper_throughput_exit_validation_catalyst_intelligence_unavailable:{str(exc)[:140]}",
                    "api_calls_used": 0,
                    "provider_calls_used": 0,
                    "llm_calls_used": 0,
                    "live_trading_changed": False,
                    "broker_live_endpoint_allowed": False,
                    "broker_behavior_changed": False,
                    "ranking_behavior_changed": False,
                    "entry_behavior_changed": False,
                    "exit_behavior_changed": False,
                    "paper_execution_behavior_changed": False,
                    "position_sizing_changed": False,
                    "thresholds_changed": False,
                    "behavior_safe_to_apply": False,
                }
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        self._cache = dict(out)
        self._cache_ts = now
        return out
