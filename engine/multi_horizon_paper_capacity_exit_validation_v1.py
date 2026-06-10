from __future__ import annotations

import json
import math
import os
import time
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


class MultiHorizonPaperCapacityExitValidationV1:
    """Paper-only horizon capacity and controlled exit-validation diagnostics.

    The suite reports capacity pools and A/B readiness. It does not place orders,
    fetch providers, or apply learned exits.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "multi_horizon_paper_capacity_exit_validation_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _capacity(self, paper_trace: dict[str, Any], paper_status: dict[str, Any], throughput: dict[str, Any]) -> dict[str, Any]:
        summary = dict(
            paper_trace.get("horizon_capacity_summary")
            or paper_status.get("horizon_capacity_summary")
            or (paper_status.get("last_execution_trace") or {}).get("horizon_capacity_summary")
            or {}
        )
        total_capacity = _to_int(summary.get("total_capacity"), _to_int(throughput.get("current_max_concurrent_positions"), 20))
        total_used = _to_int(summary.get("total_used"), _to_int(paper_trace.get("broker_open_positions_count"), _to_int(paper_status.get("open_positions_count"), 0)))
        total_available = _to_int(summary.get("total_available"), max(0, total_capacity - total_used))
        has_bucket_detail = any(k in summary for k in ("swing_used", "day_used", "scalp_used", "unknown_horizon_positions"))
        if not has_bucket_detail and total_used > 0:
            unknown = total_used
            swing_used = min(_to_int(summary.get("swing_capacity"), 8), unknown)
            day_used = 0
            scalp_used = 0
            swing_available = max(0, min(_to_int(summary.get("swing_capacity"), 8) - swing_used, total_available))
            day_available = max(0, min(_to_int(summary.get("day_capacity"), 8), total_available))
            scalp_available = max(0, min(_to_int(summary.get("scalp_capacity"), 4), total_available))
        else:
            unknown = _to_int(summary.get("unknown_horizon_positions"), 0)
            swing_used = _to_int(summary.get("swing_used"), 0)
            day_used = _to_int(summary.get("day_used"), 0)
            scalp_used = _to_int(summary.get("scalp_used"), 0)
            swing_available = _to_int(summary.get("swing_available"), max(0, min(_to_int(summary.get("swing_capacity"), 8) - swing_used, total_available)))
            day_available = _to_int(summary.get("day_available"), max(0, min(_to_int(summary.get("day_capacity"), 8) - day_used, total_available)))
            scalp_available = _to_int(summary.get("scalp_available"), max(0, min(_to_int(summary.get("scalp_capacity"), 4) - scalp_used, total_available)))
        return {
            "total_capacity": total_capacity,
            "total_used": total_used,
            "total_available": total_available,
            "swing_capacity": _to_int(summary.get("swing_capacity"), 8),
            "swing_used": swing_used,
            "swing_available": swing_available,
            "day_capacity": _to_int(summary.get("day_capacity"), 8),
            "day_used": day_used,
            "day_available": day_available,
            "scalp_capacity": _to_int(summary.get("scalp_capacity"), 4),
            "scalp_used": scalp_used,
            "scalp_available": scalp_available,
            "unknown_horizon_positions": unknown,
            "broker_confirmed_positions": _to_int(paper_trace.get("broker_open_positions_count"), total_used),
            "stale_internal_rows": _to_int(paper_trace.get("stale_internal_positions_count"), _to_int(throughput.get("stale_internal_workflow_row_overhang"), 0)),
            "horizon_capacity_blockers": list(summary.get("horizon_capacity_blockers") or [])[:10],
            "capacity_freed_today": _to_int(summary.get("capacity_freed_today"), _to_int(paper_trace.get("positions_closed"), 0)),
            "candidates_blocked_by_horizon_capacity": _to_int(summary.get("candidates_blocked_by_horizon_capacity"), _to_int(paper_trace.get("candidates_blocked_by_horizon_capacity"), 0)),
            "high_confidence_candidates_blocked_by_capacity": _to_int(summary.get("high_confidence_candidates_blocked_by_capacity"), _to_int(paper_trace.get("high_confidence_candidates_blocked_by_capacity"), 0)),
            "missed_evidence_due_to_capacity": _to_int(summary.get("missed_evidence_due_to_capacity"), _to_int(paper_trace.get("missed_evidence_due_to_capacity"), 0)),
            "recommended_capacity_action": _text(summary.get("recommended_capacity_action"), "horizon_capacity_available_for_qualified_candidates" if total_available > 0 else "wait_for_capacity"),
        }

    def _exit_validation(self, statuses: dict[str, Any]) -> dict[str, Any]:
        peak = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        throughput_exit = _status(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        paper_status = _status(statuses, "paper_autopilot_status")
        baseline_pf = _to_float(throughput_exit.get("current_policy_profit_factor"), 0.0)
        learned_pf = _to_float(throughput_exit.get("best_policy_profit_factor"), 0.0)
        baseline_expectancy = _to_float(peak.get("baseline_expectancy"), 0.0)
        learned_expectancy = _to_float(peak.get("learned_corrected_expectancy"), 0.0)
        baseline_capture = _to_float(peak.get("average_capture_ratio"), 0.0)
        learned_capture = _to_float(peak.get("learned_corrected_capture_ratio"), 0.0)
        baseline_giveback = _to_float(peak.get("average_giveback_pct"), 0.0)
        learned_giveback = _to_float(peak.get("learned_corrected_giveback"), 0.0)
        configured = bool(paper_status.get("learned_exit_validation_bucket_configured", False))
        kill_switch = bool(paper_status.get("learned_exit_validation_kill_switch", True))
        evidence = _to_int(throughput_exit.get("evidence_count"), _to_int(peak.get("tracked_trades"), 0))
        confidence = _to_float(throughput_exit.get("policy_confidence"), _to_float(peak.get("policy_confidence"), 0.0))
        paper_ready = bool(evidence >= _to_int(paper_status.get("learned_exit_validation_min_evidence"), 100) and confidence >= _to_float(paper_status.get("learned_exit_validation_min_confidence"), 70.0))
        enabled = bool(configured and not kill_switch and paper_ready)
        if kill_switch:
            rollback_reason = "kill_switch_enabled"
        elif not configured:
            rollback_reason = "validation_bucket_config_disabled"
        elif not paper_ready:
            rollback_reason = "insufficient_evidence_or_policy_confidence"
        else:
            rollback_reason = "ready_but_no_runtime_exit_application_in_this_diagnostic"
        return {
            "learned_exit_bucket_enabled": enabled,
            "learned_exit_bucket_configured": configured,
            "learned_exit_bucket_auto_disabled": not enabled,
            "rollback_reason": rollback_reason,
            "rollback_triggered_at": _now_iso() if not enabled else "",
            "baseline_vs_learned_status": "learning_bucket_disabled_collecting_baseline" if not enabled else "active_controlled_ab_validation",
            "safety_status": "safe_disabled" if not enabled else "guarded_paper_only_validation",
            "learned_exits_used_today": 0,
            "max_learning_corrected_exits_per_day": _to_int(paper_status.get("learned_exit_validation_max_exits_per_day"), 5),
            "max_learning_corrected_exit_pct": _to_float(paper_status.get("learned_exit_validation_max_exit_pct"), 25.0),
            "best_learned_exit_policy": _text(throughput_exit.get("best_shadow_exit_policy") or peak.get("best_exit_policy"), "insufficient_data"),
            "baseline_profit_factor": baseline_pf,
            "learned_corrected_profit_factor": learned_pf if enabled else 0.0,
            "profit_factor_delta": (learned_pf - baseline_pf) if enabled else 0.0,
            "baseline_expectancy": baseline_expectancy,
            "learned_corrected_expectancy": learned_expectancy if enabled else 0.0,
            "expectancy_delta": (learned_expectancy - baseline_expectancy) if enabled else 0.0,
            "baseline_capture_ratio": baseline_capture,
            "learned_corrected_capture_ratio": learned_capture if enabled else 0.0,
            "capture_ratio_delta": (learned_capture - baseline_capture) if enabled else 0.0,
            "baseline_giveback": baseline_giveback,
            "learned_corrected_giveback": learned_giveback if enabled else 0.0,
            "giveback_delta": (baseline_giveback - learned_giveback) if enabled else 0.0,
            "learned_exit_bucket_outperforming": False,
            "learned_exit_bucket_underperforming": False,
            "validation_confidence": confidence,
            "remaining_evidence_needed": max(0, _to_int(paper_status.get("learned_exit_validation_min_evidence"), 100) - evidence),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        paper_trace = _status(statuses, "paper_execution_trace")
        paper_status = _status(statuses, "paper_autopilot_status")
        throughput = _status(statuses, "paper_autopilot_throughput")
        capacity = self._capacity(paper_trace, paper_status, throughput)
        exit_validation = self._exit_validation(statuses)
        next_action = (
            "use_available_horizon_capacity_for_qualified_scalp_day_candidates"
            if capacity["total_available"] > 0
            else "wait_for_capacity_or_review_valid_paper_exits"
        )
        if not exit_validation["learned_exit_bucket_enabled"]:
            next_action = f"{next_action}; keep_learned_exit_bucket_disabled:{exit_validation['rollback_reason']}"
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_multi_horizon_capacity_controlled_exit_validation",
            "generated_at": _now_iso(),
            **capacity,
            **exit_validation,
            "top_capacity_blocker": (capacity.get("horizon_capacity_blockers") or ["none"])[0],
            "next_recommended_action": next_action,
            "lesson_routing": [
                "baseline_vs_corrected_exit_outcome",
                "horizon_capacity_throughput",
                "profit_capture_giveback",
                "symbol_catalyst_regime_policy_context",
            ],
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "paper_mode_verified": True,
            "broker_live_endpoint_allowed": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "broad_entry_behavior_changed": False,
            "broad_exit_behavior_changed": False,
            "broad_sizing_behavior_changed": False,
            "thresholds_changed": False,
            "fmp_budgets_changed": False,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
            "human_review_required": True,
            "kill_switch_exists": True,
            "behavior_safe_to_apply": False,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
        }
        _write_json(self.cache_path, out)
        return out

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
            out = _read_json(self.cache_path) or {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_multi_horizon_capacity_controlled_exit_validation",
                "total_capacity": 20,
                "total_used": 0,
                "total_available": 0,
                "learned_exit_bucket_enabled": False,
                "rollback_reason": "diagnostics_unavailable",
                "degraded_reason": f"multi_horizon_capacity_exit_validation_unavailable:{str(exc)[:140]}",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "behavior_safe_to_apply": False,
            }
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        self._cache = dict(out)
        self._cache_ts = now
        return out
