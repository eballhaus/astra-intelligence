from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 1_800_000
MAX_ROWS = 1800
CACHE_TTL_SECONDS = 8.0


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


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or str(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


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


def _values(rows: list[dict[str, Any]], *keys: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        for key in keys:
            if row.get(key) not in (None, ""):
                out.append(_to_float(row.get(key)))
                break
    return out


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def _group_average(rows: list[dict[str, Any]], group_key: str, value_keys: tuple[str, ...], limit: int = 10) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        group = _text(row.get(group_key), "unknown")
        if not group or group == "unknown":
            continue
        vals = _values([row], *value_keys)
        if vals:
            grouped[group].append(vals[0])
    averaged = {key: round(mean(vals), 4) for key, vals in grouped.items() if vals}
    return dict(sorted(averaged.items(), key=lambda item: item[1], reverse=True)[:limit])


def _issue(status: str, cause: str, severity: str, evidence_count: int, action: str, shadow: str) -> dict[str, Any]:
    return {
        "issue_status": status,
        "likely_cause": cause,
        "severity": severity,
        "evidence_count": int(evidence_count),
        "recommended_action": action,
        "safe_to_change_behavior": False,
        "shadow_only_recommendation": shadow,
    }


class LearningIssueAuditV1:
    """Fast, shadow-only reconciliation for confusing Learning Tab diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _rows(self, name: str, max_rows: int = MAX_ROWS) -> list[dict[str, Any]]:
        return _tail_jsonl(os.path.join(self.state_dir, name), max_rows=max_rows)

    def _opportunity_cost(self, rows: list[dict[str, Any]], status_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        selected_vals = _values(rows, "selected_return_pct")
        rejected_vals = _values(rows, "rejected_return_pct")
        costs = _values(rows, "opportunity_cost_pct")
        med_cost = _median(costs)
        avg_cost = _avg(costs)
        positive = max(costs) if costs else None
        negative = min(costs) if costs else None
        outlier_symbols: list[str] = []
        if costs and med_cost is not None:
            threshold = max(50.0, abs(med_cost) * 2.0)
            ranked = sorted(rows, key=lambda r: abs(_to_float(r.get("opportunity_cost_pct")) - med_cost), reverse=True)
            for row in ranked[:8]:
                gap = _to_float(row.get("opportunity_cost_pct"))
                if abs(gap - med_cost) >= threshold or abs(gap) >= 100.0:
                    outlier_symbols.append(_text(row.get("rejected_symbol") or row.get("selected_symbol"), "unknown"))
        cause = "insufficient_opportunity_cost_evidence"
        status = "expected_warmup"
        severity = "low"
        action = "Continue collecting selected-vs-rejected evidence."
        shadow = "Do not alter selection behavior until rejected candidate returns use realized same-cycle outcomes."
        if costs:
            mean_median_gap = abs((avg_cost or 0.0) - (med_cost or 0.0))
            if negative is not None and negative <= -100.0:
                cause = "outlier_or_best_selected_baseline_distortion"
                status = "calculation_display_ambiguity"
                severity = "medium"
                action = "Use median, gap bounds, and method label next to average opportunity cost."
                shadow = "Treat the large negative value as proxy/matching distortion unless realized rejected returns confirm it."
            elif mean_median_gap >= 30.0:
                cause = "mean_distorted_by_outliers"
                status = "calculation_display_ambiguity"
                severity = "medium"
                action = "Prefer median opportunity cost for headline interpretation."
                shadow = "Keep recommendation shadow-only and avoid ranking changes."
            elif (avg_cost or 0.0) > 0.35:
                cause = "true_missed_opportunity_pressure_possible"
                status = "real_learning_weakness_possible"
                severity = "medium"
                action = "Review missed symbols and require realized follow-through before behavior changes."
                shadow = "Track missed winners by archetype/regime, no auto-weight changes."
            else:
                cause = "current_selection_outperformed_rejected_proxy_set"
                status = "not_a_trading_weakness"
                severity = "low"
                action = "Display as favorable selection differential, not as missed opportunity pressure."
                shadow = "Continue monitoring with realized rejected outcomes when available."
        diagnostics = {
            "avg_selected_return": _avg(selected_vals),
            "avg_rejected_return": _avg(rejected_vals),
            "average_opportunity_cost": avg_cost if avg_cost is not None else status_payload.get("average_opportunity_cost"),
            "median_opportunity_cost": med_cost,
            "largest_positive_gap": round(positive, 4) if positive is not None else None,
            "largest_negative_gap": round(negative, 4) if negative is not None else None,
            "outlier_symbols": outlier_symbols,
            "calculation_method": "opportunity_cost_pct = rejected_return_pct - selected_return_pct; rejected_return_pct uses realized_return_pct when available, otherwise a quality/live-quality proxy with suppression/session penalties; selected_return_pct uses same-symbol lifecycle when available, otherwise the best selected lifecycle baseline.",
        }
        return diagnostics, _issue(status, cause, severity, len(rows), action, shadow)

    def _execution_participation(self, rows: list[dict[str, Any]], status_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        symbols = [_text(r.get("symbol")).upper() for r in rows if _text(r.get("symbol"))]
        reasons = [_text(r.get("rejection_reason") or r.get("suppression_reason"), "none").lower() for r in rows]
        unique_count = len(set(symbols))
        reviewed = len(rows)
        duplicate_blocks = sum(1 for reason in reasons if "duplicate_active_position" in reason or "duplicate" in reason)
        active_blocks = sum(1 for reason in reasons if "active_position" in reason or "already_open" in reason)
        confirmation_blocks = sum(1 for reason in reasons if "confirmation" in reason or "open_confirmation" in reason)
        quality_blocks = sum(1 for reason in reasons if "quality" in reason or "commitment" in reason or "entry" in reason)
        risk_blocks = sum(1 for reason in reasons if "risk" in reason or "heat" in reason or "survivability" in reason)
        liquidity_blocks = sum(1 for reason in reasons if "liquidity" in reason or "spread" in reason)
        portfolio_blocks = sum(1 for reason in reasons if "portfolio_fit" in reason or "portfolio" in reason)
        regime_blocks = sum(1 for reason in reasons if "regime" in reason or "context" in reason or "market_structure" in reason)
        submitted = sum(1 for row in rows if bool(row.get("order_submitted")))
        eligible = sum(1 for row in rows if bool(row.get("eligible")))
        submission_rate_unique = round((submitted / unique_count * 100.0), 4) if unique_count else 0.0
        eligible_not_submitted = "none"
        if eligible > submitted:
            top_reason = Counter(reason for reason in reasons if reason != "none").most_common(1)
            eligible_not_submitted = top_reason[0][0] if top_reason else "selected_or_eligible_without_submission_trace"
        if reviewed and duplicate_blocks / max(1, reviewed) >= 0.65 and unique_count < reviewed * 0.25:
            status = "expected_active_position_repeat_blocks"
            cause = "repeat_reviews_of_symbols_already_held_or_active"
            severity = "low"
            action = "Keep duplicate-active-position gate; display unique candidate rate so the funnel does not look self-blocking."
            shadow = "Audit unique candidates separately from repeated active-position rows."
        elif eligible > submitted:
            status = "possible_final_submission_suppression"
            cause = "eligible_candidates_not_reaching_submission"
            severity = "medium"
            action = "Inspect final submission preflight, but do not loosen gates without symbol-level proof."
            shadow = "Track eligible-not-submitted reasons per cycle."
        elif reviewed and submitted == 0:
            status = "underparticipation_needs_context"
            cause = "no_submission_in_recent_audit_window"
            severity = "medium"
            action = "Check market/session/broker state and capacity before changing strategy gates."
            shadow = "Continue participation bridge diagnostics only."
        else:
            status = "participation_audit_explained"
            cause = "suppression_reasons_are_classified"
            severity = "low"
            action = "No behavior change indicated by audit decomposition."
            shadow = "Continue monitoring unique candidate conversion."
        diagnostics = {
            "unique_candidates_reviewed": unique_count,
            "duplicate_symbol_blocks": duplicate_blocks,
            "active_position_blocks": active_blocks,
            "confirmation_required_blocks": confirmation_blocks,
            "quality_rejections": quality_blocks,
            "risk_rejections": risk_blocks,
            "liquidity_rejections": liquidity_blocks,
            "portfolio_fit_rejections": portfolio_blocks,
            "regime_rejections": regime_blocks,
            "eligible_not_submitted_reason": eligible_not_submitted,
            "submitted_count": submitted,
            "submission_rate_unique_candidates": submission_rate_unique,
            "top_rejection_reasons": dict(Counter(reason for reason in reasons if reason != "none").most_common(8)),
            "status_payload_label": _text(status_payload.get("participation_label"), "unknown"),
        }
        return diagnostics, _issue(status, cause, severity, reviewed, action, shadow)

    def _profit_capture(self, lifecycle_rows: list[dict[str, Any]], profit_rows: list[dict[str, Any]], replay_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        rows = profit_rows or lifecycle_rows
        peak_vals = _values(rows, "peak_unrealized_profit_pct", "max_favorable_excursion_pct", "MFE")
        exit_vals = _values(rows, "current_or_exit_profit_pct", "actual_return_pct", "current_return_pct")
        giveback_vals = _values(rows, "profit_giveback_pct", "giveback_from_peak_pct")
        capture_vals = _values(rows, "profit_capture_ratio")
        worst = sorted(rows, key=lambda r: _to_float(r.get("profit_giveback_pct") or r.get("giveback_from_peak_pct")), reverse=True)[:6]
        best = sorted(rows, key=lambda r: _to_float(r.get("profit_capture_ratio")), reverse=True)[:6]
        replay_improvement = _avg(_values(replay_rows, "improvement_vs_actual", "average_counterfactual_improvement"))
        avg_capture = _avg(capture_vals)
        avg_giveback = _avg(giveback_vals)
        if capture_vals and (avg_capture or 0.0) < 0.6 and (avg_giveback or 0.0) >= 5.0:
            status = "supported_learning_weakness"
            cause = "meaningful_mfe_with_partial_profit_retention"
            severity = "medium"
            action = "Keep exit behavior unchanged; use shadow profit-capture review by archetype/regime/horizon."
            shadow = "Prioritize profit giveback diagnostics and future human-reviewed exit policy tests."
        elif not capture_vals:
            status = "insufficient_profit_capture_evidence"
            cause = "missing_profit_capture_rows_or_open_trades_not_yet_resolved"
            severity = "low"
            action = "Wait for more lifecycle/profit-capture telemetry."
            shadow = "No behavior change."
        else:
            status = "profit_capture_within_current_learning_band"
            cause = "capture_ratio_not_showing_severe_systemic_weakness"
            severity = "low"
            action = "Continue monitoring giveback distribution."
            shadow = "No exit changes."
        diagnostics = {
            "avg_peak_gain": _avg(peak_vals),
            "avg_exit_gain": _avg(exit_vals),
            "avg_giveback": avg_giveback,
            "median_giveback": _median(giveback_vals),
            "average_profit_capture_ratio": avg_capture,
            "worst_giveback_symbols": [_text(r.get("symbol"), "unknown") for r in worst if _text(r.get("symbol"))],
            "best_capture_symbols": [_text(r.get("symbol"), "unknown") for r in best if _text(r.get("symbol"))],
            "sample_size": len(rows),
            "by_archetype_capture": _group_average(rows, "trade_archetype", ("profit_capture_ratio",)),
            "by_regime_capture": _group_average(rows, "market_regime", ("profit_capture_ratio",)),
            "by_horizon_capture": _group_average(rows, "horizon_style", ("profit_capture_ratio",)),
            "replay_missed_improvement": replay_improvement,
        }
        return diagnostics, _issue(status, cause, severity, len(rows), action, shadow)

    def _follow_through(self, lifecycle_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        labels = [_text(r.get("follow_through_label") or r.get("continuation_pattern_label"), "unknown").lower() for r in lifecycle_rows]
        continued = sum(1 for label in labels if any(x in label for x in ("strong", "moderate", "healthy", "clean")))
        stalled = sum(1 for label in labels if "stalled" in label)
        reversed_count = sum(1 for label in labels if "reversed" in label or "weakening" in label)
        failed = sum(1 for label in labels if "failed" in label or "breakout_failure" in label)
        scores = _values(lifecycle_rows, "follow_through_quality_score", "continuation_strength_score", "follow_through_score")
        avg_score = _avg(scores)
        if scores and (avg_score or 0.0) < 60.0:
            status = "supported_learning_weakness"
            cause = "follow_through_scores_cluster_in_weak_to_decent_band"
            severity = "medium"
            action = "Report by archetype/regime/horizon before entry threshold changes."
            shadow = "Use continuation evidence for human-reviewed future calibration only."
        elif not scores:
            status = "insufficient_continuation_evidence"
            cause = "missing_follow_through_scores"
            severity = "low"
            action = "Continue lifecycle tracking."
            shadow = "No entry changes."
        else:
            status = "not_currently_primary_weakness"
            cause = "continuation_scores_are_not_systemically_weak"
            severity = "low"
            action = "Monitor trend only."
            shadow = "No entry changes."
        diagnostics = {
            "continued_as_expected_count": continued,
            "stalled_count": stalled,
            "reversed_count": reversed_count,
            "failed_breakout_count": failed,
            "average_follow_through_score": avg_score,
            "continuation_score_by_archetype": _group_average(lifecycle_rows, "trade_archetype", ("follow_through_quality_score", "continuation_strength_score", "follow_through_score")),
            "continuation_score_by_regime": _group_average(lifecycle_rows, "market_regime", ("follow_through_quality_score", "continuation_strength_score", "follow_through_score")),
            "continuation_score_by_horizon": _group_average(lifecycle_rows, "horizon_style", ("follow_through_quality_score", "continuation_strength_score", "follow_through_score")),
            "entry_timing_vs_continuation_relationship": "entry timing relationship is diagnostic-only; current evidence should be reviewed by archetype/regime before threshold changes.",
        }
        return diagnostics, _issue(status, cause, severity, len(scores), action, shadow)

    def _buy_purity(self, candidate_rows: list[dict[str, Any]], advanced_status: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        evidence = len(candidate_rows) or _to_int((advanced_status.get("evidence_counts") or {}).get("return_evidence"), 0)
        quality_vals = _values(candidate_rows, "buy_list_purity", "buy_list_purity_score", "buy_ranking_quality_score", "grade_percent", "confidence")
        if evidence >= 50 and not quality_vals:
            status = "mapping_or_source_gap"
            cause = "candidate_evidence_exists_but_buy_purity_source_field_is_missing"
            severity = "medium"
            action = "Use available buy purity aliases in unified diagnostics; avoid showing false insufficient evidence."
            shadow = "Display/source fix only; no selection behavior change."
        elif quality_vals:
            status = "display_source_available"
            cause = "buy_purity_alias_fields_available"
            severity = "low"
            action = "Display mapped buy purity with source label."
            shadow = "No behavior change."
        else:
            status = "expected_insufficient_evidence"
            cause = "no_candidate_quality_source_available"
            severity = "low"
            action = "Continue collecting candidate evidence."
            shadow = "No behavior change."
        diagnostics = {
            "evidence_count": evidence,
            "mapped_buy_purity": _avg(quality_vals),
            "source_fields_checked": ["buy_list_purity", "buy_list_purity_score", "buy_ranking_quality_score", "grade_percent", "confidence"],
        }
        return diagnostics, _issue(status, cause, severity, evidence, action, shadow)

    def _exit_quality(self, lifecycle_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        closed = [r for r in lifecycle_rows if r.get("exit_timestamp") or r.get("exit_price") or _text(r.get("exit_label") or r.get("exit_classification"), "unknown") not in {"unknown", "insufficient_exit_data", ""}]
        exit_vals = _values(closed, "exit_quality_score", "exit_efficiency_score", "average_exit_quality")
        if not closed:
            status = "expected_insufficient_natural_exit_evidence"
            cause = "few_or_no_naturally_closed_lifecycles"
            severity = "low"
            action = "Keep Learning Tab maturity label; do not treat as a real exit weakness yet."
            shadow = "Wait for natural closes before exit policy review."
        elif closed and not exit_vals:
            status = "mapping_or_source_gap"
            cause = "closed_lifecycles_exist_without_mapped_exit_quality_field"
            severity = "medium"
            action = "Map lifecycle exit_quality_score into unified diagnostics."
            shadow = "Display/source fix only."
        elif (mean(exit_vals) if exit_vals else 100.0) < 60.0:
            status = "supported_learning_weakness"
            cause = "closed_lifecycle_exit_quality_is_below_target"
            severity = "medium"
            action = "Study exit labels; no forced exits or threshold changes."
            shadow = "Shadow-only exit review recommendations."
        else:
            status = "exit_quality_evidence_acceptable"
            cause = "mapped_exit_evidence_not_showing_systemic_failure"
            severity = "low"
            action = "Continue tracking natural exits."
            shadow = "No behavior change."
        diagnostics = {
            "closed_lifecycle_count": len(closed),
            "exit_quality_sample_size": len(exit_vals),
            "average_exit_quality": _avg(exit_vals),
            "exit_label_distribution": dict(Counter(_text(r.get("exit_label") or r.get("exit_classification"), "unknown") for r in closed).most_common(8)),
        }
        return diagnostics, _issue(status, cause, severity, max(len(closed), len(exit_vals)), action, shadow)

    def status(self, *, sources: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        sources = dict(sources or {})
        opportunity_rows = self._rows("opportunity_cost_learning_v1.jsonl")
        audit_rows = self._rows("execution_suppression_audit_v1.jsonl")
        lifecycle_rows = self._rows("trade_lifecycle_excursion_v2.jsonl")
        profit_rows = self._rows("adaptive_profit_capture_intelligence_v1.jsonl")
        replay_rows = self._rows("replay_counterfactual_learning_v2.jsonl")
        candidate_rows = self._rows("candidate_decision_ledger_v1.jsonl", max_rows=900)
        statuses = dict(sources.get("statuses") or {})
        opp_diag, opp_issue = self._opportunity_cost(opportunity_rows, statuses.get("opportunity_cost_learning") or {})
        exec_diag, exec_issue = self._execution_participation(audit_rows, statuses.get("execution_participation_audit") or {})
        profit_diag, profit_issue = self._profit_capture(lifecycle_rows, profit_rows, replay_rows)
        follow_diag, follow_issue = self._follow_through(lifecycle_rows)
        buy_diag, buy_issue = self._buy_purity(candidate_rows, statuses.get("advanced_learning_intelligence") or {})
        exit_diag, exit_issue = self._exit_quality(lifecycle_rows)
        issue_status = {
            "opportunity_cost": opp_issue,
            "execution_participation": exec_issue,
            "profit_capture": profit_issue,
            "follow_through_continuation": follow_issue,
            "buy_purity": buy_issue,
            "exit_quality": exit_issue,
        }
        medium_or_higher = [name for name, issue in issue_status.items() if issue.get("severity") in {"medium", "high"}]
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_learning_issue_audit",
            "generated_at": _now_iso(),
            "issue_status": issue_status,
            "opportunity_cost_diagnostics": opp_diag,
            "execution_participation_diagnostics": exec_diag,
            "profit_capture_diagnostics": profit_diag,
            "follow_through_diagnostics": follow_diag,
            "buy_purity_diagnostics": buy_diag,
            "exit_quality_diagnostics": exit_diag,
            "likely_cause_summary": ", ".join(medium_or_higher) if medium_or_higher else "no_behavior_change_indicated",
            "recommended_action": "Apply display/source reconciliation and keep behavior changes shadow-only.",
            "safe_to_change_behavior": False,
            "shadow_only_recommendation": "Use these diagnostics to decide future human-reviewed tuning; do not auto-loosen gates or exits.",
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "auto_apply_allowed": False,
            "human_review_required": True,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
