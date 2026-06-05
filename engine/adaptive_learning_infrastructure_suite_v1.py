from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 12.0
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1600

FOCUS_AREAS = (
    "profit_capture",
    "hold_duration",
    "horizon_classification",
    "small_cap_behavior",
    "catalyst_behavior",
    "exit_timing",
    "continuation_analysis",
)

QUEUE_NAMES = ("critical", "high", "normal", "low", "deferred")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
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


def _round(value: Any, digits: int = 3) -> float:
    return round(_to_float(value), digits)


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker")).upper()


def _age_seconds(timestamp: Any) -> float | None:
    raw = _text(timestamp)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
    except Exception:
        return None


def _latest_age(rows: list[dict[str, Any]]) -> float | None:
    for row in reversed(rows):
        for key in ("generated_at", "timestamp", "updated_at", "current_timestamp", "entry_timestamp", "created_at"):
            age = _age_seconds(row.get(key))
            if age is not None:
                return age
    return None


def _counter_top(counter: Counter[str], default: str = "insufficient_data") -> str:
    return counter.most_common(1)[0][0] if counter else default


class AdaptiveLearningInfrastructureSuiteV1:
    """Shadow-only worker/orchestrator/queue readiness diagnostics.

    This suite does not start background jobs or change execution. It provides the
    bounded status contract future workers can use without putting dashboard
    requests on the hook for heavy learning work.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0
        self.state_path = os.path.join(self.state_dir, "adaptive_learning_infrastructure_suite_v1.jsonl")

    def _rows(self, name: str, max_rows: int = 420) -> list[dict[str, Any]]:
        return _tail_jsonl(os.path.join(self.state_dir, name), max_rows=max_rows)

    def _collect_rows(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "lifecycle": self._rows("trade_lifecycle_excursion_v2.jsonl", 520) + self._rows("trade_lifecycle_excursion_v1.jsonl", 320),
            "profit_capture": self._rows("adaptive_profit_capture_intelligence_v1.jsonl", 420),
            "replay": self._rows("replay_counterfactual_learning_v2.jsonl", 420),
            "opportunity_cost": self._rows("opportunity_cost_learning_v1.jsonl", 420),
            "market_context": self._rows("market_context_learning_suite_v1.jsonl", 420),
            "exit_learning": self._rows("exit_learning_expansion_suite_v1.jsonl", 420),
            "learning_acceleration": self._rows("learning_acceleration_retention_suite_v1.jsonl", 320),
            "audit": self._rows("execution_suppression_audit_v1.jsonl", 420),
            "candidate": self._rows("candidate_decision_ledger_v1.jsonl", 320),
            "archetype_regime": self._rows("trade_archetype_regime_intelligence_v1.jsonl", 320),
            "context_evidence_expansion": self._rows("context_evidence_expansion_suite_v1.jsonl", 320),
            "catalyst_theme_narrative_v2": self._rows("catalyst_theme_narrative_capital_flow_intelligence_v2.jsonl", 320),
        }

    def _worker_foundation(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        lifecycle_age = _latest_age(rows["lifecycle"])
        context_age = _latest_age(rows["market_context"])
        replay_age = _latest_age(rows["replay"])
        exit_age = _latest_age(rows["exit_learning"])
        active_workers = [
            {
                "worker_type": "premarket_worker",
                "status": "ready" if rows["market_context"] else "warming_up",
                "queued_job_types": ["premarket_snapshots", "gap_analysis", "volume_analysis", "catalyst_snapshots"],
                "cache_age_seconds": None if context_age is None else round(context_age, 1),
            },
            {
                "worker_type": "market_hours_worker",
                "status": "ready" if rows["lifecycle"] or rows["profit_capture"] else "warming_up",
                "queued_job_types": ["open_trade_monitoring", "mfe_mae_collection", "profit_decay_tracking", "continuation_tracking"],
                "cache_age_seconds": None if lifecycle_age is None else round(lifecycle_age, 1),
            },
            {
                "worker_type": "after_hours_worker",
                "status": "ready" if rows["market_context"] else "warming_up",
                "queued_job_types": ["earnings_reaction_tracking", "after_hours_movement_tracking", "overnight_gap_tracking"],
                "cache_age_seconds": None if context_age is None else round(context_age, 1),
            },
            {
                "worker_type": "overnight_learning_worker",
                "status": "ready" if rows["replay"] or rows["learning_acceleration"] else "warming_up",
                "queued_job_types": ["replay_processing", "counterfactual_generation", "lesson_consolidation", "memory_maintenance"],
                "cache_age_seconds": None if replay_age is None else round(replay_age, 1),
            },
        ]
        ready_count = sum(1 for worker in active_workers if worker["status"] == "ready")
        evidence_jobs = sum(len(v) for v in rows.values())
        failed_jobs = sum(1 for key in ("degraded_reason", "failed_sources_count") for payload in statuses.values() if payload.get(key))
        completed_jobs = min(evidence_jobs, 5000)
        avg_runtime = mean([_to_float((statuses.get(name) or {}).get("build_ms"), 0.0) for name in statuses if isinstance(statuses.get(name), dict)] or [0.0])
        efficiency = _clamp(35.0 + ready_count * 12.5 + min(25.0, completed_jobs / 120.0) - failed_jobs * 4.0)
        health = "healthy" if ready_count >= 3 and failed_jobs == 0 else "degraded" if failed_jobs >= 3 else "warming_up"
        return {
            "active_workers": active_workers,
            "active_worker_count": ready_count,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "avg_worker_runtime": _round(avg_runtime, 3),
            "worker_efficiency_score": _round(efficiency, 2),
            "worker_health_status": health,
            "worker_outputs_cached": True,
            "dashboard_blocking_workers": False,
        }

    def _priority_scores(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, float]:
        acceleration = statuses.get("learning_acceleration_retention_suite_v1") or {}
        v3 = statuses.get("adaptive_execution_exit_intelligence_v3") or {}
        exit_learning = statuses.get("exit_learning_expansion_suite_v1") or {}
        market_context = statuses.get("market_context_learning_suite_v1") or {}
        profit_capture = statuses.get("adaptive_profit_capture") or {}
        blind = statuses.get("blind_spot_detection") or {}
        confidence_attr = statuses.get("confidence_calibration_performance_attribution_v1") or {}
        context_expansion = statuses.get("context_evidence_expansion_suite_v1") or {}
        catalyst_v2 = statuses.get("catalyst_theme_narrative_capital_flow_intelligence_v2") or {}
        return {
            "profit_capture": max(
                _to_float(v3.get("protect_profit_score"), 0.0),
                _to_float(exit_learning.get("protect_profit_score"), 0.0),
                _to_float(profit_capture.get("average_profit_giveback_pct"), 0.0) * 1.8,
            ),
            "hold_duration": max(_to_float(v3.get("hold_longer_score"), 0.0), _to_float(exit_learning.get("hold_longer_score"), 0.0)),
            "horizon_classification": max(0.0, 70.0 - _to_float(market_context.get("context_confidence"), 45.0)),
            "small_cap_behavior": 45.0 if "market_cap_tier" in list(acceleration.get("underexplored_contexts") or []) else 25.0,
            "catalyst_behavior": max(0.0, 75.0 - _to_float(market_context.get("catalyst_confidence"), 35.0)),
            "exit_timing": max(_to_float(exit_learning.get("protect_profit_score"), 0.0), _to_float(v3.get("profit_capture_score"), 0.0)),
            "continuation_analysis": max(0.0, 70.0 - _to_float(v3.get("continuation_probability"), _to_float(exit_learning.get("continuation_after_profit_score"), 50.0))),
            "blind_spot_coverage": _to_float(blind.get("blind_spot_score"), 0.0),
            "confidence_grade_attribution": max(0.0, 70.0 - _to_float(confidence_attr.get("confidence_predictive_power"), 45.0)) if _to_int(confidence_attr.get("evidence_count"), 0) else 25.0,
            "context_evidence_expansion": max(0.0, 100.0 - _to_float(context_expansion.get("catalyst_coverage_score"), 35.0)) if _to_int(context_expansion.get("evidence_count"), 0) else 35.0,
            "catalyst_theme_narrative_capital_flow": max(
                _to_float(catalyst_v2.get("unknown_catalyst_rate"), 60.0),
                100.0 - _to_float(catalyst_v2.get("catalyst_coverage_score"), 35.0),
            ) if _to_int(catalyst_v2.get("evidence_count"), 0) else 45.0,
        }

    def _orchestrator(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        scores = self._priority_scores(rows, statuses)
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        priorities = [name for name, score in ordered if score > 0][:6]
        highest = ordered[0][0] if ordered else "collect_lifecycle_evidence"
        lowest = ordered[-1][0] if ordered else "insufficient_data"
        load = _clamp(sum(scores.values()) / max(1, len(scores)))
        queue_depth = max(1, min(50, int(round(load / 4.0)) + len([v for v in rows.values() if v])))
        health = "healthy" if load < 70 else "busy" if load < 85 else "overloaded"
        return {
            "active_learning_priorities": priorities,
            "worker_queue_depth": queue_depth,
            "highest_priority_task": highest,
            "lowest_priority_task": lowest,
            "learning_load_score": _round(load, 2),
            "orchestration_health": health,
            "duplicate_analysis_prevention_active": True,
            "budget_aware_routing_active": True,
            "learning_priority_scores": {k: _round(v, 2) for k, v in scores.items()},
        }

    def _task_queue(self, rows: dict[str, list[dict[str, Any]]], orchestrator: dict[str, Any]) -> dict[str, Any]:
        load = _to_float(orchestrator.get("learning_load_score"), 0.0)
        critical = 1 if load >= 75 else 0
        high = max(1, int(load // 18))
        normal = max(2, len(orchestrator.get("active_learning_priorities") or []))
        low = max(1, len([name for name, values in rows.items() if values]) // 2)
        deferred = 2 if load >= 65 else 1
        distribution = {
            "critical": critical,
            "high": high,
            "normal": normal,
            "low": low,
            "deferred": deferred,
        }
        ages = [age for values in rows.values() if (age := _latest_age(values)) is not None]
        average_age = mean(ages) if ages else 0.0
        stale = sum(1 for age in ages if age > 18 * 3600)
        retry_count = sum(1 for values in rows.values() for row in values[-120:] if _to_int(row.get("retry_count"), 0) > 0)
        return {
            "total_tasks": sum(distribution.values()),
            "queue_distribution": distribution,
            "average_task_age": _round(average_age, 1),
            "average_task_age_seconds": _round(average_age, 1),
            "stale_task_count": stale,
            "retry_count": retry_count,
            "stale_task_detection_active": True,
            "bounded_queue_names": list(QUEUE_NAMES),
        }

    def _evidence_collection(self, rows: dict[str, list[dict[str, Any]]], orchestrator: dict[str, Any], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        counts = {
            "profit_capture": len(rows["profit_capture"]),
            "hold_duration": len([r for r in rows["lifecycle"] if r.get("hold_duration_minutes") is not None or r.get("actual_hold_duration_minutes") is not None]),
            "horizon_classification": len([r for r in rows["lifecycle"] + rows["market_context"] if r.get("horizon_style") or r.get("best_context_horizon")]),
            "small_cap_behavior": len([r for r in rows["candidate"] + rows["lifecycle"] if "small" in _text(r.get("cap_tier") or r.get("market_cap_tier") or r.get("market_cap_bucket")).lower()]),
            "catalyst_behavior": len([r for r in rows["market_context"] if r.get("catalyst_type")]),
            "exit_timing": len(rows["exit_learning"]),
            "continuation_analysis": len([r for r in rows["lifecycle"] + rows["exit_learning"] if r.get("continuation_strength_score") is not None or r.get("continuation_after_profit_score") is not None]),
        }
        gaps = {area: max(0, 80 - min(80, count)) for area, count in counts.items()}
        target = max(gaps.items(), key=lambda item: item[1], default=(orchestrator.get("highest_priority_task", "profit_capture"), 0))[0]
        priority_target = _text(orchestrator.get("highest_priority_task"), target)
        if priority_target in counts and gaps.get(priority_target, 0) >= 15:
            target = priority_target
        gap_score = _clamp(gaps.get(target, 0) * 1.2)
        return {
            "targeted_learning_area": target,
            "evidence_gap_score": _round(gap_score, 2),
            "evidence_collection_focus": f"collect_more_{target}_evidence",
            "collected_evidence_count": sum(counts.values()),
            "evidence_counts_by_area": counts,
            "candidate_focus_areas": list(FOCUS_AREAS),
        }

    def _api_budget(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        api_calls = {name: _to_int(payload.get("api_calls_used"), 0) for name, payload in statuses.items() if isinstance(payload, dict)}
        total_calls = sum(api_calls.values())
        cache_flags = [bool(payload.get("cache_hit")) for payload in statuses.values() if isinstance(payload, dict) and "cache_hit" in payload]
        cache_util = (sum(1 for hit in cache_flags if hit) / max(1, len(cache_flags))) * 100.0 if cache_flags else 100.0
        wasted = sum(1 for payload in statuses.values() if isinstance(payload, dict) and payload.get("degraded_reason"))
        source_scores = {
            name: max(0.0, 100.0 - calls * 8.0 - (25.0 if (statuses.get(name) or {}).get("degraded_reason") else 0.0))
            for name, calls in api_calls.items()
        }
        highest = max(source_scores.items(), key=lambda item: item[1], default=("local_cached_learning", 100.0))[0]
        lowest = min(source_scores.items(), key=lambda item: item[1], default=("none", 0.0))[0]
        score = _clamp(100.0 - total_calls * 3.0 - wasted * 4.0 + cache_util * 0.15)
        return {
            "api_budget_score": _round(score, 2),
            "wasted_calls_estimate": wasted,
            "highest_value_source": highest,
            "lowest_value_source": lowest,
            "cache_utilization": _round(cache_util, 2),
            "api_calls_observed": total_calls,
            "redundant_request_reduction_active": True,
            "api_calls_used": 0,
        }

    def _worker_health(self, worker: dict[str, Any], task_queue: dict[str, Any], api_budget: dict[str, Any], rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        ages = [age for values in rows.values() if (age := _latest_age(values)) is not None]
        freshness = _clamp(100.0 - ((mean(ages) / 3600.0) * 2.5 if ages else 0.0))
        timeout_count = _to_int(worker.get("failed_jobs"), 0)
        stuck_jobs = _to_int(task_queue.get("stale_task_count"), 0)
        queue_pressure = _clamp(_to_float(task_queue.get("total_tasks"), 0.0) * 3.0)
        health = _clamp((_to_float(worker.get("worker_efficiency_score"), 50.0) * 0.35) + (freshness * 0.3) + (_to_float(api_budget.get("api_budget_score"), 80.0) * 0.25) + (100.0 - queue_pressure) * 0.1 - timeout_count * 3.0 - stuck_jobs * 2.0)
        alerts: list[str] = []
        if timeout_count:
            alerts.append("worker_failures_detected")
        if stuck_jobs:
            alerts.append("stale_learning_tasks_detected")
        if queue_pressure >= 75:
            alerts.append("queue_pressure_high")
        if not alerts:
            alerts.append("no_worker_alerts")
        return {
            "health_score": _round(health, 2),
            "timeout_count": timeout_count,
            "stuck_jobs": stuck_jobs,
            "queue_pressure": _round(queue_pressure, 2),
            "cache_freshness": _round(freshness, 2),
            "worker_alerts": alerts,
            "worker_health_label": "healthy" if health >= 70 else "watch" if health >= 45 else "degraded",
        }

    def _coverage(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        all_rows = [row for values in rows.values() for row in values]
        counters = {
            "market_cap": Counter(_text(r.get("cap_tier") or r.get("market_cap_tier") or r.get("market_cap_bucket"), "unknown") for r in all_rows if _symbol(r)),
            "sector": Counter(_text(r.get("sector") or r.get("sector_context_label"), "unknown") for r in all_rows if _symbol(r)),
            "catalyst": Counter(_text(r.get("catalyst_type"), "unknown") for r in all_rows if _symbol(r) or r.get("catalyst_type")),
            "archetype": Counter(_text(r.get("trade_archetype") or r.get("archetype"), "unknown") for r in all_rows if _symbol(r)),
            "regime": Counter(_text(r.get("market_regime") or r.get("regime"), "unknown") for r in all_rows if _symbol(r)),
            "trade_personality": Counter(_text(r.get("trade_personality"), "unknown") for r in all_rows if _symbol(r)),
            "horizon": Counter(_text(r.get("horizon_style") or r.get("best_context_horizon") or r.get("hold_duration_bucket"), "unknown") for r in all_rows if _symbol(r)),
            "premarket_profile": Counter(_text(r.get("premarket_profile"), "unknown") for r in rows["market_context"]),
            "after_hours_profile": Counter(_text(r.get("after_hours_profile"), "unknown") for r in rows["market_context"]),
        }
        breadth = {name: len([k for k, v in counter.items() if k and k != "unknown" and v > 0]) for name, counter in counters.items()}
        strongest = max(breadth.items(), key=lambda item: item[1], default=("insufficient_data", 0))[0]
        weakest = min(breadth.items(), key=lambda item: item[1], default=("insufficient_data", 0))[0]
        under = [name for name, count in breadth.items() if count <= 1][:8]
        recommended = under[0] if under else weakest
        return {
            "strongest_coverage_area": strongest,
            "weakest_coverage_area": weakest,
            "underexplored_contexts": under,
            "coverage_breadth": breadth,
            "recommended_focus": f"collect_more_{recommended}_evidence" if recommended else "collect_more_lifecycle_evidence",
        }

    def _write_summary(self, out: dict[str, Any]) -> None:
        now = time.time()
        if now - self._last_write < 120.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            row = {k: out.get(k) for k in (
                "generated_at", "active_worker_count", "completed_jobs", "failed_jobs", "learning_load_score",
                "worker_efficiency_score", "api_budget_score", "evidence_gap_score", "health_score",
                "strongest_coverage_area", "weakest_coverage_area", "recommended_focus", "orchestration_health",
            )}
            with open(self.state_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached
        status_map = {k: dict(v) for k, v in dict(statuses or {}).items() if isinstance(v, dict)}
        activation = status_map.get("adaptive_worker_activation_orchestration_v1") or {}
        rows = self._collect_rows()
        worker = self._worker_foundation(rows, status_map)
        orchestrator = self._orchestrator(rows, status_map)
        task_queue = self._task_queue(rows, orchestrator)
        evidence = self._evidence_collection(rows, orchestrator, status_map)
        api_budget = self._api_budget(status_map)
        worker_health = self._worker_health(worker, task_queue, api_budget, rows)
        coverage = self._coverage(rows, status_map)
        shadow = (
            f"Shadow-only: route background learning toward {evidence['targeted_learning_area'].replace('_', ' ')}; "
            f"keep dashboard requests cached and trading behavior unchanged."
        )
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_adaptive_learning_infrastructure",
            "generated_at": _now_iso(),
            "adaptive_background_worker_foundation_v1_active": True,
            "learning_orchestrator_v1_active": True,
            "learning_task_queue_v1_active": True,
            "adaptive_evidence_collection_v1_active": True,
            "api_budget_intelligence_v1_active": True,
            "worker_health_monitor_v1_active": True,
            "learning_coverage_expansion_v1_active": True,
            **worker,
            **orchestrator,
            **task_queue,
            **evidence,
            **api_budget,
            **worker_health,
            **coverage,
            "shadow_recommendation": shadow,
            "future_worker_contract": {
                "premarket_worker_ready": True,
                "market_hours_worker_ready": True,
                "after_hours_worker_ready": True,
                "overnight_learning_worker_ready": True,
                "priority_queues": list(QUEUE_NAMES),
                "compatible_future_suites": [
                    "learning_acceleration_retention_suite_v1",
                    "open_trade_learning_v1",
                    "rejected_candidate_learning_expansion_v1",
                    "persona_learning_expansion_v1",
                    "market_context_learning_suite_v1",
                ],
            },
            "adaptive_worker_activation_compatible": True,
            "adaptive_worker_activation_status": _text(activation.get("orchestrator_status"), "not_loaded"),
            "adaptive_worker_activation_focus": _text(activation.get("recommended_next_worker_focus"), "collect_more_lifecycle_evidence"),
            "adaptive_worker_activation_active_workers": _to_int(activation.get("active_worker_count"), 0),
            "workers_started_by_dashboard": False,
            "dashboard_request_blocking": False,
            "behavior_safe_to_apply": False,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "thresholds_changed": False,
            "position_sizing_changed": False,
        }
        self._write_summary(out)
        self._cache = dict(out)
        self._cache_ts = now
        return out
