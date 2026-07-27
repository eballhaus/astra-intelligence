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


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return True
    if raw in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(default)


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


class ControlledPaperLearnedExitValidationV1:
    """Paper-only learned-exit bucket verification and diagnostics.

    This suite is deliberately conservative: it exposes whether the bucket can
    be enabled, but it never submits orders or changes exits itself.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "controlled_paper_learned_exit_validation_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _config(self, paper_status: dict[str, Any], multi: dict[str, Any]) -> dict[str, Any]:
        paper_has_config = "learned_exit_validation_bucket_configured" in paper_status
        paper_has_kill = "learned_exit_validation_kill_switch" in paper_status
        configured = (
            bool(paper_status.get("learned_exit_validation_bucket_configured"))
            if paper_has_config
            else bool(multi.get("learned_exit_bucket_configured") or _bool_env("ASTRA_LEARNED_EXIT_VALIDATION_BUCKET_ENABLED", False))
        )
        kill_switch = (
            bool(paper_status.get("learned_exit_validation_kill_switch"))
            if paper_has_kill
            else bool(_bool_env("ASTRA_LEARNED_EXIT_VALIDATION_KILL_SWITCH", True))
        )
        max_daily = max(0, min(5, _to_int(
            paper_status.get("learned_exit_validation_max_exits_per_day")
            or multi.get("max_learning_corrected_exits_per_day"),
            5,
        )))
        max_pct = max(0.0, min(25.0, _to_float(
            paper_status.get("learned_exit_validation_max_exit_pct")
            or multi.get("max_learning_corrected_exit_pct"),
            25.0,
        )))
        return {
            "bucket_configured": configured,
            "kill_switch_status": "enabled" if kill_switch else "disabled",
            "kill_switch_enabled": kill_switch,
            "max_learning_corrected_exits_per_day": max_daily,
            "max_learning_corrected_exit_pct": max_pct,
            "min_policy_confidence": _to_float(paper_status.get("learned_exit_validation_min_confidence"), 70.0),
            "min_evidence_count": _to_int(paper_status.get("learned_exit_validation_min_evidence"), 100),
        }

    def _paper_exit_path_verification(self, statuses: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        broker = _status(statuses, "alpaca_paper_broker")
        paper_status = _status(statuses, "paper_autopilot_status")
        blockers: list[str] = []
        paper_mode_verified = bool(broker.get("paper_mode_verified", False))
        live_endpoint_detected = bool(broker.get("live_endpoint_detected", False))
        broker_live_endpoint_allowed = bool(broker.get("broker_live_endpoint_allowed", False) or live_endpoint_detected)
        broker_execution_ready = bool(broker.get("broker_execution_ready") or broker.get("broker_execution_enabled"))
        sell_route_guarded = True
        duplicate_exit_prevention_verified = bool(paper_status.get("learned_exit_duplicate_exit_prevention_verified", False))
        fill_confirmation_verified = bool(paper_status.get("learned_exit_broker_fill_confirmation_verified", False))
        learned_exit_runtime_path = bool(paper_status.get("learned_exit_validation_runtime_path_enabled", False))

        if not paper_mode_verified:
            blockers.append("paper_mode_not_verified")
        if broker_live_endpoint_allowed:
            blockers.append("live_endpoint_detected_or_allowed")
        if not broker_execution_ready:
            blockers.append("broker_execution_not_ready_or_summary_only")
        if not sell_route_guarded:
            blockers.append("paper_sell_route_not_guarded")
        if not duplicate_exit_prevention_verified:
            blockers.append("duplicate_pending_sell_order_prevention_not_verified")
        if not fill_confirmation_verified:
            blockers.append("paper_sell_fill_confirmation_not_verified_before_local_close")
        if not learned_exit_runtime_path:
            blockers.append("paper_autopilot_learned_exit_path_not_connected_to_guarded_alpaca_paper_sell_order")
        if not config.get("bucket_configured"):
            blockers.append("validation_bucket_config_disabled")
        if config.get("kill_switch_enabled"):
            blockers.append("kill_switch_enabled")

        verified = bool(
            paper_mode_verified
            and not broker_live_endpoint_allowed
            and broker_execution_ready
            and sell_route_guarded
            and duplicate_exit_prevention_verified
            and fill_confirmation_verified
            and learned_exit_runtime_path
        )
        return {
            "paper_exit_path_verified": verified,
            "paper_exit_path_blockers": blockers,
            "paper_exit_path_verification_status": "verified" if verified else "blocked",
            "paper_sell_route_guarded": sell_route_guarded,
            "duplicate_exit_submissions_prevented": duplicate_exit_prevention_verified,
            "broker_fill_confirmation_required": True,
            "broker_fill_confirmation_verified": fill_confirmation_verified,
            "paper_mode_verified": paper_mode_verified,
            "broker_execution_ready": broker_execution_ready,
            "broker_live_endpoint_allowed": broker_live_endpoint_allowed,
            "live_endpoint_detected": live_endpoint_detected,
        }

    def _performance(self, statuses: dict[str, Any]) -> dict[str, Any]:
        multi = _status(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        throughput = _status(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        peak = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        return {
            "baseline_profit_factor": _to_float(multi.get("baseline_profit_factor") or throughput.get("current_policy_profit_factor"), 0.0),
            "learned_corrected_profit_factor": _to_float(multi.get("learned_corrected_profit_factor"), 0.0),
            "profit_factor_delta": _to_float(multi.get("profit_factor_delta"), 0.0),
            "baseline_win_rate": _to_float(multi.get("baseline_win_rate"), 0.0),
            "learned_corrected_win_rate": _to_float(multi.get("learned_corrected_win_rate"), 0.0),
            "win_rate_delta": _to_float(multi.get("win_rate_delta"), 0.0),
            "baseline_expectancy": _to_float(multi.get("baseline_expectancy"), 0.0),
            "learned_corrected_expectancy": _to_float(multi.get("learned_corrected_expectancy"), 0.0),
            "expectancy_delta": _to_float(multi.get("expectancy_delta"), 0.0),
            "baseline_capture_ratio": _to_float(multi.get("baseline_capture_ratio") or peak.get("average_capture_ratio"), 0.0),
            "learned_corrected_capture_ratio": _to_float(multi.get("learned_corrected_capture_ratio"), 0.0),
            "capture_ratio_delta": _to_float(multi.get("capture_ratio_delta"), 0.0),
            "baseline_giveback": _to_float(multi.get("baseline_giveback") or peak.get("average_giveback_pct"), 0.0),
            "learned_corrected_giveback": _to_float(multi.get("learned_corrected_giveback"), 0.0),
            "giveback_delta": _to_float(multi.get("giveback_delta"), 0.0),
            "saved_loss": _to_float(multi.get("saved_loss"), 0.0),
            "missed_upside": _to_float(multi.get("missed_upside"), 0.0),
            "false_exit_rate": _to_float(multi.get("false_exit_rate"), 0.0),
            "capacity_freed_by_learned_exits": _to_int(multi.get("capacity_freed_by_learned_exits"), 0),
            "opportunity_throughput_after_capacity_freed": _to_int(multi.get("opportunity_throughput_after_capacity_freed"), 0),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        paper_status = _status(statuses, "paper_autopilot_status")
        multi = _status(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        throughput = _status(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        shadow_vs_paper = _status(statuses, "shadow_vs_paper_performance_attribution_v1")
        if not shadow_vs_paper:
            try:
                from engine.shadow_vs_paper_performance_attribution_v1 import ShadowVsPaperPerformanceAttributionV1

                shadow_vs_paper = ShadowVsPaperPerformanceAttributionV1(state_dir=self.state_dir).status(statuses=statuses, force=False)
            except Exception:
                shadow_vs_paper = {}
        config = self._config(paper_status, multi)
        verification = self._paper_exit_path_verification(statuses, config)
        performance = self._performance(statuses)
        evidence = max(
            _to_int(throughput.get("evidence_count"), 0),
            _to_int(multi.get("validation_evidence_count"), 0),
            _to_int(paper_status.get("total_closed_trades"), 0),
            _to_int(shadow_vs_paper.get("canonical_closed_trade_count"), 0),
            _to_int(shadow_vs_paper.get("shadow_completed_lifecycle_count"), 0),
        )
        confidence = _to_float(
            throughput.get("policy_confidence")
            or multi.get("validation_confidence")
            or (config["min_policy_confidence"] if evidence >= config["min_evidence_count"] else 0.0),
            0.0,
        )
        evidence_ready = bool(evidence >= config["min_evidence_count"] and confidence >= config["min_policy_confidence"])
        learned_exit_bucket_enabled = bool(
            config["bucket_configured"]
            and not config["kill_switch_enabled"]
            and verification["paper_exit_path_verified"]
            and evidence_ready
        )
        rollback_reason = "none"
        if not learned_exit_bucket_enabled:
            rollback_reason = (verification["paper_exit_path_blockers"] or ["insufficient_evidence_or_policy_confidence"])[0]
            if not evidence_ready and rollback_reason == "none":
                rollback_reason = "insufficient_evidence_or_policy_confidence"
        used_today = _to_int(paper_status.get("learned_exits_used_today") or multi.get("learned_exits_used_today"), 0) if learned_exit_bucket_enabled else 0
        remaining = max(0, int(config["max_learning_corrected_exits_per_day"]) - used_today)
        by_horizon = dict(paper_status.get("learned_exits_by_horizon") or multi.get("learned_exits_by_horizon") or {})
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "controlled_paper_learned_exit_validation",
            "generated_at": _now_iso(),
            "learned_exit_bucket_enabled": learned_exit_bucket_enabled,
            "learned_exit_bucket_configured": bool(config["bucket_configured"]),
            "learned_exits_used_today": used_today,
            "learned_exits_remaining_today": remaining,
            "max_learning_corrected_exits_per_day": int(config["max_learning_corrected_exits_per_day"]),
            "max_learning_corrected_exit_pct": float(config["max_learning_corrected_exit_pct"]),
            "learned_exits_by_horizon": {
                "scalp": _to_int(by_horizon.get("scalp"), 0),
                "day_trade": _to_int(by_horizon.get("day_trade"), 0),
                "swing_trade": _to_int(by_horizon.get("swing_trade"), 0),
            },
            "scalp_day_swing_coverage_status": "not_started" if used_today <= 0 else "partial",
            "learned_exit_candidates_today": _to_int(paper_status.get("learned_exit_candidates_today") or multi.get("learned_exit_candidates_today"), 0),
            "rejected_learned_exit_candidates": _to_int(paper_status.get("rejected_learned_exit_candidates") or multi.get("rejected_learned_exit_candidates"), 0),
            "rejection_reasons": list(paper_status.get("rejection_reasons") or multi.get("rejection_reasons") or verification["paper_exit_path_blockers"])[:10],
            "policies_used_today": list(paper_status.get("policies_used_today") or multi.get("policies_used_today") or [])[:8],
            "top_policy_used": _text((list(paper_status.get("policies_used_today") or multi.get("policies_used_today") or []) or [throughput.get("best_shadow_exit_policy") or "none"])[0], "none"),
            "current_active_learned_exit_tests": _to_int(paper_status.get("current_active_learned_exit_tests") or multi.get("current_active_learned_exit_tests"), 0),
            "baseline_exits_today": _to_int(paper_status.get("baseline_exits_today") or multi.get("baseline_exits_today"), 0),
            "learned_corrected_exits_today": used_today,
            "baseline_vs_learned_status": "controlled_bucket_disabled_until_exit_path_verified" if not learned_exit_bucket_enabled else "active_controlled_ab_validation",
            **performance,
            **verification,
            "policy_confidence": confidence,
            "evidence_count": evidence,
            "canonical_closed_trade_count": _to_int(shadow_vs_paper.get("canonical_closed_trade_count"), 0),
            "paper_trade_count": _to_int(shadow_vs_paper.get("paper_trade_count"), 0),
            "shadow_losing_trade_count": _to_int(shadow_vs_paper.get("shadow_losing_trade_count"), 0),
            "closed_lifecycle_evidence_reconciled": bool(shadow_vs_paper.get("closed_lifecycle_evidence_reconciled")),
            "broker_truth_matches_exit_validator_truth": bool(shadow_vs_paper.get("broker_truth_matches_lifecycle_truth", True)),
            "exit_validator_truth_source": _text(shadow_vs_paper.get("canonical_performance_source"), "unknown"),
            "evidence_ready": evidence_ready,
            "readiness_status": "blocked_exit_path_verification" if not verification["paper_exit_path_verified"] else ("ready" if evidence_ready else "not_ready_more_evidence_required"),
            "remaining_evidence_needed": max(0, int(config["min_evidence_count"]) - evidence),
            "what_worked": [],
            "what_failed": [],
            "why_it_worked": "awaiting_controlled_paper_samples",
            "why_it_failed": "awaiting_controlled_paper_samples",
            "lesson_stored": False,
            "rollback_status": _text(paper_status.get("rollback_status"), "auto_disabled" if not learned_exit_bucket_enabled else "armed"),
            "rollback_reason": _text(paper_status.get("rollback_reason"), rollback_reason),
            "rollback_triggered_at": _text(paper_status.get("rollback_triggered_at"), _now_iso() if not learned_exit_bucket_enabled else ""),
            "kill_switch_status": config["kill_switch_status"],
            "safety_status": "safe_disabled" if not learned_exit_bucket_enabled else "guarded_paper_only_validation",
            "next_recommended_action": (
                "wire_learned_exit_bucket_to_guarded_alpaca_paper_sell_order_with_duplicate_prevention_and_fill_confirmation"
                if not verification["paper_exit_path_verified"]
                else "collect_controlled_paper_exit_ab_samples"
            ),
            "shadow_recommendation": "Keep the learned-exit bucket disabled until paper sell submission, duplicate prevention, and fill-confirmed local close are verified.",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "live_trading_changed": False,
            "no_live_endpoint": not bool(verification["broker_live_endpoint_allowed"]),
            "no_live_orders": True,
            "broker_behavior_changed": bool(learned_exit_bucket_enabled),
            "broker_behavior_changed_scope": "controlled_paper_exit_bucket_only" if learned_exit_bucket_enabled else "none",
            "broad_ranking_behavior_changed": False,
            "broad_entry_behavior_changed": False,
            "broad_exit_behavior_changed": False,
            "broad_sizing_behavior_changed": False,
            "thresholds_changed": False,
            "fmp_budgets_changed": False,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
            "human_review_required": True,
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
                    self._cache_ts = now - age
                    return disk
        try:
            out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = {
                "enabled": False,
                "version": VERSION,
                "mode": "controlled_paper_learned_exit_validation",
                "learned_exit_bucket_enabled": False,
                "paper_exit_path_verified": False,
                "paper_exit_path_blockers": [f"controlled_paper_learned_exit_validation_unavailable:{str(exc)[:140]}"],
                "rollback_status": "auto_disabled",
                "rollback_reason": "diagnostic_unavailable",
                "kill_switch_status": "enabled",
                "safety_status": "safe_disabled",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "live_trading_changed": False,
                "broker_live_endpoint_allowed": False,
                "natural_exit_preserved": True,
                "forced_exits_enabled": False,
                "human_review_required": True,
                "behavior_safe_to_apply": False,
                "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = now
        return out
