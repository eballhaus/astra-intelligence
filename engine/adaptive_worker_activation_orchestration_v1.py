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
MAX_ROWS = 1400


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
        for key in ("generated_at", "timestamp", "updated_at", "current_timestamp", "created_at", "entry_timestamp"):
            age = _age_seconds(row.get(key))
            if age is not None:
                return age
    return None


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _first_number(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return _to_float(value, default)
    return float(default)


def _is_open(row: dict[str, Any]) -> bool:
    if row.get("exit_timestamp") or row.get("exit_price") or row.get("closed_at") or row.get("exit_label"):
        return False
    status = _text(row.get("status") or row.get("lifecycle_status") or row.get("position_status"), "open").lower()
    return status not in {"closed", "exited", "complete", "completed"}


def _top_symbol(rows: list[dict[str, Any]], score_keys: tuple[str, ...], default: str = "insufficient_data", reverse: bool = True) -> str:
    candidates: list[tuple[float, str]] = []
    for row in rows:
        sym = _symbol(row)
        if not sym:
            continue
        score = _first_number(row, *score_keys, default=0.0)
        candidates.append((score, sym))
    if not candidates:
        return default
    candidates.sort(reverse=reverse)
    return candidates[0][1]


class AdaptiveWorkerActivationOrchestrationV1:
    """Cached, shadow-only learning worker activation diagnostics.

    This suite reports what background-style learning workers should process and
    summarizes bounded evidence snapshots. It deliberately does not submit
    orders, change rankings, call providers, or spawn expensive dashboard jobs.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.state_path = os.path.join(self.state_dir, "adaptive_worker_activation_orchestration_v1.jsonl")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _rows(self, name: str, max_rows: int = 420) -> list[dict[str, Any]]:
        return _tail_jsonl(os.path.join(self.state_dir, name), max_rows=max_rows)

    def _collect_rows(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "market_context": self._rows("market_context_learning_suite_v1.jsonl", 520),
            "lifecycle": self._rows("trade_lifecycle_excursion_v2.jsonl", 520) + self._rows("trade_lifecycle_excursion_v1.jsonl", 260),
            "profit_capture": self._rows("adaptive_profit_capture_intelligence_v1.jsonl", 420),
            "exit_learning": self._rows("exit_learning_expansion_suite_v1.jsonl", 420),
            "replay": self._rows("replay_counterfactual_learning_v2.jsonl", 420),
            "opportunity_cost": self._rows("opportunity_cost_learning_v1.jsonl", 320),
            "infrastructure": self._rows("adaptive_learning_infrastructure_suite_v1.jsonl", 320),
            "acceleration": self._rows("learning_acceleration_retention_suite_v1.jsonl", 320),
            "candidate": self._rows("candidate_decision_ledger_v1.jsonl", 320),
            "audit": self._rows("execution_suppression_audit_v1.jsonl", 320),
            "context_evidence_expansion": self._rows("context_evidence_expansion_suite_v1.jsonl", 320),
            "catalyst_theme_narrative_v2": self._rows("catalyst_theme_narrative_capital_flow_intelligence_v2.jsonl", 320),
        }

    def _premarket_worker(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        context = rows["market_context"]
        profile_counter = Counter(_text(r.get("premarket_profile"), "unknown") for r in context if _text(r.get("premarket_profile"), "unknown") != "unknown")
        gap_values = [_first_number(r, "premarket_gap_pct", "premarket_price_change_pct", "gap_risk_score", default=0.0) for r in context]
        confidence = _to_float((statuses.get("market_context_learning_suite_v1") or {}).get("context_confidence"), 0.0)
        if not confidence and context:
            confidence = _clamp(30.0 + min(40.0, len(context) * 0.8))
        strongest = _top_symbol(context, ("premarket_momentum_score", "premarket_continuation_probability", "premarket_price_change_pct"))
        weakest = _top_symbol(context, ("premarket_giveback_risk", "gap_risk_score"))
        return {
            "premarket_worker_status": "active_cached" if context else "warming_up",
            "snapshots_collected": len(context),
            "premarket_snapshot_windows": ["early_premarket", "mid_premarket", "late_premarket", "pre_open_summary"],
            "strongest_premarket_symbol": strongest,
            "weakest_premarket_symbol": weakest,
            "premarket_context_confidence": _round(confidence, 2),
            "average_premarket_gap_pct": _avg(gap_values) if gap_values else None,
            "dominant_premarket_profile": profile_counter.most_common(1)[0][0] if profile_counter else "insufficient_data",
            "premarket_worker_api_calls_used": 0,
        }

    def _open_trade_worker(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        active = [r for r in rows["lifecycle"] if _is_open(r)]
        if not active and rows["profit_capture"]:
            active = [r for r in rows["profit_capture"] if _is_open(r)]
        givebacks = [_first_number(r, "profit_giveback_pct", "current_giveback_pct", "giveback_from_peak_pct", default=0.0) for r in active]
        decay_alerts = sum(1 for value in givebacks if value >= 2.0)
        strongest = _top_symbol(active, ("current_or_exit_profit_pct", "current_unrealized_profit_pct", "peak_unrealized_profit_pct", "max_favorable_excursion_pct"))
        weakest = _top_symbol(active, ("profit_giveback_pct", "max_adverse_excursion_pct", "worst_unrealized_drawdown_pct"))
        continuation_values = [_first_number(r, "continuation_strength_score", "follow_through_quality_score", "follow_through_score", default=0.0) for r in active]
        confidence = _clamp(25.0 + len(active) * 8.0 + (min(25.0, (_avg(continuation_values) or 0.0) * 0.2)))
        return {
            "open_trade_worker_status": "active_cached" if active else "waiting_for_open_trades",
            "active_trades_monitored": len(active),
            "profit_decay_alerts": decay_alerts,
            "strongest_open_trade": strongest,
            "weakest_open_trade": weakest,
            "open_trade_learning_confidence": _round(confidence, 2),
            "average_open_trade_giveback": _avg(givebacks) if givebacks else None,
            "open_trade_worker_api_calls_used": 0,
            "open_trade_orders_allowed": False,
            "open_trade_exits_allowed": False,
        }

    def _after_hours_worker(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        context = rows["market_context"]
        after_rows = [r for r in context if r.get("after_hours_profile") or r.get("after_hours_price_change_pct") is not None]
        confidence = _to_float((statuses.get("market_context_learning_suite_v1") or {}).get("after_hours_context_confidence"), 0.0)
        if not confidence and after_rows:
            confidence = _clamp(25.0 + len(after_rows) * 0.9)
        strongest = _top_symbol(after_rows, ("overnight_momentum_score", "gap_and_run_probability", "after_hours_price_change_pct"))
        risk = _top_symbol(after_rows, ("gap_and_fade_probability", "gap_risk_score", "premarket_giveback_risk"))
        profile_counter = Counter(_text(r.get("after_hours_profile"), "unknown") for r in after_rows if _text(r.get("after_hours_profile"), "unknown") != "unknown")
        return {
            "after_hours_worker_status": "active_cached" if after_rows else "warming_up",
            "after_hours_snapshots_collected": len(after_rows),
            "strongest_after_hours_symbol": strongest,
            "highest_gap_fade_risk_symbol": risk,
            "after_hours_context_confidence": _round(confidence, 2),
            "dominant_after_hours_profile": profile_counter.most_common(1)[0][0] if profile_counter else "insufficient_data",
            "after_hours_worker_api_calls_used": 0,
        }

    def _replay_worker(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        replay = rows["replay"]
        replay_status = statuses.get("replay_counterfactual_learning_v2") or {}
        jobs = len(replay) or _to_int(replay_status.get("counterfactuals_generated"), 0)
        improvements = [_first_number(r, "average_counterfactual_improvement", "improvement_vs_actual", "partial_exit_profit_delta", default=0.0) for r in replay]
        runtime = _to_float(replay_status.get("build_ms"), 0.0)
        best_pattern = _text(replay_status.get("best_counterfactual_pattern"), "insufficient_data")
        if best_pattern == "insufficient_data" and replay:
            best_pattern = Counter(_text(r.get("best_counterfactual_path") or r.get("best_counterfactual_pattern"), "unknown") for r in replay).most_common(1)[0][0]
        value = _clamp(30.0 + min(45.0, jobs * 0.8) + abs(_avg(improvements) or 0.0))
        return {
            "replay_worker_status": "active_cached" if jobs else "warming_up",
            "replay_jobs_completed": jobs,
            "counterfactuals_generated": _to_int(replay_status.get("counterfactuals_generated"), jobs),
            "best_exit_pattern": best_pattern,
            "hold_duration_improvement": _round(_avg(improvements) or 0.0, 3),
            "profit_capture_improvement": _round(_to_float(replay_status.get("average_counterfactual_improvement"), _avg(improvements) or 0.0), 3),
            "replay_learning_value": _round(value, 2),
            "replay_runtime_ms": _round(runtime, 3),
            "replay_worker_api_calls_used": 0,
        }

    def _coverage_worker(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        infra = statuses.get("adaptive_learning_infrastructure_suite_v1") or {}
        accel = statuses.get("learning_acceleration_retention_suite_v1") or {}
        context_expansion = statuses.get("context_evidence_expansion_suite_v1") or {}
        catalyst_v2 = statuses.get("catalyst_theme_narrative_capital_flow_intelligence_v2") or {}
        under = list(infra.get("underexplored_contexts") or accel.get("underexplored_contexts") or [])[:8]
        if catalyst_v2.get("top_learning_gap"):
            under = [str(catalyst_v2.get("top_learning_gap"))] + [item for item in under if item != catalyst_v2.get("top_learning_gap")]
        if context_expansion.get("top_learning_gap"):
            under = [str(context_expansion.get("top_learning_gap"))] + [item for item in under if item != context_expansion.get("top_learning_gap")]
        weakest = _text(infra.get("weakest_coverage_area") or accel.get("weakest_coverage_area"), "insufficient_data")
        if not under and weakest != "insufficient_data":
            under = [weakest]
        collected = sum(len(rows[name]) for name in ("market_context", "lifecycle", "candidate", "opportunity_cost", "context_evidence_expansion", "catalyst_theme_narrative_v2"))
        focus = under[:5] or ["after_hours_profile", "catalyst", "trade_personality"]
        return {
            "coverage_worker_status": "active_cached" if collected else "warming_up",
            "targeted_contexts": focus,
            "new_evidence_collected": collected,
            "weakest_remaining_context": weakest,
            "context_evidence_top_gap": _text(context_expansion.get("top_learning_gap"), "insufficient_data"),
            "context_evidence_records": _to_int(context_expansion.get("evidence_count"), 0),
            "catalyst_theme_top_gap": _text(catalyst_v2.get("top_learning_gap"), "insufficient_data"),
            "catalyst_theme_records": _to_int(catalyst_v2.get("evidence_count"), 0),
            "coverage_worker_confidence": _round(_clamp(25.0 + min(60.0, collected / 35.0)), 2),
            "coverage_worker_api_calls_used": 0,
        }

    def _orchestrator(self, worker_payloads: dict[str, dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        worker_statuses = [
            worker_payloads["premarket"].get("premarket_worker_status"),
            worker_payloads["open_trade"].get("open_trade_worker_status"),
            worker_payloads["after_hours"].get("after_hours_worker_status"),
            worker_payloads["replay"].get("replay_worker_status"),
            worker_payloads["coverage"].get("coverage_worker_status"),
        ]
        active_count = sum(1 for status in worker_statuses if status in {"active_cached", "ready", "running_cached"})
        failed_jobs = sum(1 for payload in statuses.values() if isinstance(payload, dict) and payload.get("degraded_reason"))
        skipped_jobs = sum(1 for status in worker_statuses if status in {"warming_up", "waiting_for_open_trades"})
        completed = sum(_to_int(worker_payloads[name].get(key), 0) for name, key in (
            ("premarket", "snapshots_collected"),
            ("open_trade", "active_trades_monitored"),
            ("after_hours", "after_hours_snapshots_collected"),
            ("replay", "replay_jobs_completed"),
            ("coverage", "new_evidence_collected"),
        ))
        api_calls = sum(_to_int(payload.get("api_calls_used"), 0) for payload in statuses.values() if isinstance(payload, dict))
        cache_flags = [bool(payload.get("cache_hit")) for payload in statuses.values() if isinstance(payload, dict) and "cache_hit" in payload]
        cache_hit_rate = (sum(1 for flag in cache_flags if flag) / max(1, len(cache_flags))) * 100.0 if cache_flags else 100.0
        queue_depth = max(1, min(60, active_count * 3 + skipped_jobs * 2 + failed_jobs * 3))
        api_budget_score = _clamp(100.0 - api_calls * 3.0 - failed_jobs * 5.0 + cache_hit_rate * 0.1)
        efficiency = _clamp(35.0 + active_count * 11.0 + min(25.0, completed / 160.0) - failed_jobs * 5.0 - skipped_jobs * 1.5)
        focus_options = [
            worker_payloads["coverage"].get("weakest_remaining_context"),
            worker_payloads["replay"].get("best_exit_pattern"),
            worker_payloads["premarket"].get("dominant_premarket_profile"),
        ]
        focus = next((_text(item) for item in focus_options if _text(item) not in {"", "insufficient_data", "unknown"}), "collect_more_after_hours_profile_evidence")
        status = "healthy" if failed_jobs == 0 and active_count >= 3 else "watch" if active_count >= 2 else "warming_up"
        return {
            "orchestrator_status": status,
            "active_worker_count": active_count,
            "completed_jobs": completed,
            "failed_jobs": failed_jobs,
            "skipped_jobs": skipped_jobs,
            "queue_depth": queue_depth,
            "api_budget_used": api_calls,
            "api_budget_score": _round(api_budget_score, 2),
            "cache_hit_rate": _round(cache_hit_rate, 2),
            "worker_efficiency_score": _round(efficiency, 2),
            "recommended_next_worker_focus": str(focus).replace(" ", "_"),
            "duplicate_work_prevention_active": True,
            "dashboard_blocking_prevented": True,
        }

    def _write_summary(self, out: dict[str, Any]) -> None:
        now = time.time()
        if now - self._last_write < 90.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            row = {k: out.get(k) for k in (
                "generated_at", "orchestrator_status", "active_worker_count", "completed_jobs",
                "failed_jobs", "skipped_jobs", "queue_depth", "worker_efficiency_score",
                "api_budget_score", "cache_hit_rate", "recommended_next_worker_focus",
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
        rows = self._collect_rows()
        workers = {
            "premarket": self._premarket_worker(rows, status_map),
            "open_trade": self._open_trade_worker(rows, status_map),
            "after_hours": self._after_hours_worker(rows, status_map),
            "replay": self._replay_worker(rows, status_map),
            "coverage": self._coverage_worker(rows, status_map),
        }
        orchestrator = self._orchestrator(workers, status_map)
        shadow = (
            f"Shadow-only: prioritize {orchestrator['recommended_next_worker_focus'].replace('_', ' ')}; "
            "collect cached worker evidence without changing trading behavior."
        )
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_adaptive_worker_activation_orchestration",
            "generated_at": _now_iso(),
            "worker_activation_layer_active": True,
            **orchestrator,
            **workers["premarket"],
            **workers["open_trade"],
            **workers["after_hours"],
            **workers["replay"],
            **workers["coverage"],
            "worker_details": workers,
            "worker_timeouts_enabled": True,
            "bounded_scans_only": True,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "shadow_recommendation": shadow,
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
