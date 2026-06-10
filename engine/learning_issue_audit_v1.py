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
        eligible_unique = len({_text(r.get("symbol")).upper() for r in rows if bool(r.get("eligible")) and _text(r.get("symbol"))})
        submitted_unique = len({_text(r.get("symbol")).upper() for r in rows if bool(r.get("order_submitted")) and _text(r.get("symbol"))})
        submission_rate_total = round((submitted / reviewed * 100.0), 4) if reviewed else 0.0
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
        elif eligible > submitted and submitted_unique <= 0:
            status = "possible_final_submission_suppression"
            cause = "eligible_candidates_not_reaching_submission"
            severity = "medium"
            action = "Inspect final submission preflight, but do not loosen gates without symbol-level proof."
            shadow = "Track eligible-not-submitted reasons per cycle."
        elif submitted_unique > 0 and duplicate_blocks / max(1, reviewed) >= 0.50:
            status = "participation_math_display_clarified"
            cause = "unique_symbol_submissions_exist_but_total_reviews_are_dominated_by_duplicate_active_rows"
            severity = "low"
            action = "Show total-review and unique-symbol rates separately."
            shadow = "No participation gate changes."
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
            "reviewed_total": reviewed,
            "unique_candidates_reviewed": unique_count,
            "eligible_unique": eligible_unique,
            "submitted_unique": submitted_unique,
            "duplicate_symbol_blocks": duplicate_blocks,
            "duplicate_review_count": duplicate_blocks,
            "active_position_blocks": active_blocks,
            "active_position_block_count": active_blocks,
            "confirmation_required_blocks": confirmation_blocks,
            "confirmation_required_count": confirmation_blocks,
            "quality_rejections": quality_blocks,
            "risk_rejections": risk_blocks,
            "liquidity_rejections": liquidity_blocks,
            "portfolio_fit_rejections": portfolio_blocks,
            "regime_rejections": regime_blocks,
            "eligible_not_submitted_reason": eligible_not_submitted,
            "submitted_count": submitted,
            "final_submission_suppression_detected": bool(eligible > submitted),
            "submission_rate_total_reviews": submission_rate_total,
            "submission_rate_unique_candidates": submission_rate_unique,
            "display_explanation": "Reviewed total counts repeated checks; unique reviewed counts distinct symbols. Duplicate-active-position blocks are expected when Astra keeps re-evaluating symbols already held.",
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
            "avg_current_or_exit_gain": _avg(exit_vals),
            "avg_giveback": avg_giveback,
            "median_giveback": _median(giveback_vals),
            "average_profit_capture_ratio": avg_capture,
            "capture_ratio": avg_capture,
            "worst_giveback_symbols": [_text(r.get("symbol"), "unknown") for r in worst if _text(r.get("symbol"))],
            "best_capture_symbols": [_text(r.get("symbol"), "unknown") for r in best if _text(r.get("symbol"))],
            "sample_size": len(rows),
            "by_archetype_capture": _group_average(rows, "trade_archetype", ("profit_capture_ratio",)),
            "by_regime_capture": _group_average(rows, "market_regime", ("profit_capture_ratio",)),
            "by_horizon_capture": _group_average(rows, "horizon_style", ("profit_capture_ratio",)),
            "capture_ratio_by_archetype": _group_average(rows, "trade_archetype", ("profit_capture_ratio",)),
            "capture_ratio_by_regime": _group_average(rows, "market_regime", ("profit_capture_ratio",)),
            "capture_ratio_by_horizon": _group_average(rows, "horizon_style", ("profit_capture_ratio",)),
            "open_vs_closed_capture": {
                "open": _avg(_values([r for r in rows if not (r.get("exit_timestamp") or r.get("exit_price") or r.get("closed"))], "profit_capture_ratio")),
                "closed": _avg(_values([r for r in rows if r.get("exit_timestamp") or r.get("exit_price") or r.get("closed")], "profit_capture_ratio")),
            },
            "replay_missed_improvement": replay_improvement,
            "recommendation": shadow,
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
            "exit_quality_source": "natural_lifecycle_exit_quality_score",
            "natural_exit_count": len([r for r in closed if _text(r.get("exit_label") or r.get("exit_classification"), "").lower() not in {"simulated_exit", "counterfactual_exit"}]),
            "simulated_exit_count": len([r for r in closed if _text(r.get("exit_label") or r.get("exit_classification"), "").lower() in {"simulated_exit", "counterfactual_exit"}]),
            "open_position_count_used": 0,
            "closed_position_count_used": len(closed),
            "exit_quality_confidence": round(min(100.0, len(exit_vals) * 2.5), 4),
            "exit_quality_scope_label": "closed_natural_lifecycle_rows",
        }
        return diagnostics, _issue(status, cause, severity, max(len(closed), len(exit_vals)), action, shadow)

    def _core_metric_source(self, statuses: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        advanced = dict(statuses.get("advanced_learning_intelligence") or {})
        advanced_count = _to_int((advanced.get("evidence_counts") or {}).get("return_evidence"), 0)
        advanced_values = {
            "released_win_rate": advanced.get("released_win_rate") or advanced.get("win_rate"),
            "profit_factor": advanced.get("profit_factor"),
            "average_return": advanced.get("average_return"),
        }
        reconciled_available = bool(advanced_count > 0 and all(v not in (None, "") for v in advanced_values.values()))
        validation = bool(advanced.get("source_validation_passed"))
        scope_mismatch = bool(advanced.get("dataset_scope_mismatch_detected")) or "replay_actual_return_differs_from_lifecycle_average" in list(advanced.get("mismatches") or [])
        if reconciled_available and not validation and scope_mismatch:
            issue = _issue(
                "display_source_fix",
                "advanced_metrics_available_but_demoted_by_replay_scope_mismatch",
                "medium",
                advanced_count,
                "Use advanced reconciled lifecycle metrics for Core Performance and label replay scope separately.",
                "No strategy behavior change; this is source-priority/display reconciliation.",
            )
        elif reconciled_available:
            issue = _issue(
                "advanced_source_available",
                "advanced_reconciled_metrics_available",
                "low",
                advanced_count,
                "Use advanced_learning_intelligence_v1 as preferred Core Performance source.",
                "No behavior change.",
            )
        else:
            issue = _issue(
                "legacy_fallback_expected",
                "advanced_reconciled_metrics_missing",
                "low",
                advanced_count,
                "Use audited lifecycle/replay/legacy fallback until advanced metrics return.",
                "No behavior change.",
            )
        diagnostics = {
            "selected_metric_source": "advanced_learning_intelligence_v1" if reconciled_available else "legacy_learning_sources",
            "available_metric_sources": {
                "advanced_learning_intelligence_v1": {
                    "available": reconciled_available,
                    "sample_size": advanced_count,
                    "source_validation_passed": validation,
                    "metric_confidence_score": advanced.get("metric_confidence_score"),
                    "dataset_scope_label": advanced.get("dataset_scope_label"),
                },
                "legacy_learning_sources": {"available": True},
            },
            "rejected_metric_sources": {} if reconciled_available else {"advanced_learning_intelligence_v1": "missing_reconciled_core_values"},
            "source_selection_reason": issue["likely_cause"],
            "reconciled_metrics_available": reconciled_available,
            "legacy_fallback_used": not reconciled_available,
            "fallback_reason": "" if reconciled_available else "advanced_reconciled_metrics_missing",
            **advanced_values,
        }
        return diagnostics, issue

    def _dataset_scope(self, lifecycle_rows: list[dict[str, Any]], profit_rows: list[dict[str, Any]], replay_rows: list[dict[str, Any]], statuses: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        advanced = dict(statuses.get("advanced_learning_intelligence") or {})
        advanced_counts = dict(advanced.get("evidence_counts") or {})
        closed_lifecycle = [r for r in lifecycle_rows if r.get("exit_timestamp") or r.get("exit_price") or r.get("closed")]
        open_lifecycle = [r for r in lifecycle_rows if r not in closed_lifecycle]
        mismatch = bool(advanced.get("dataset_scope_mismatch_detected")) or bool(replay_rows and lifecycle_rows)
        diagnostics = {
            "core_performance_sample_size": _to_int(advanced_counts.get("return_evidence"), len([r for r in lifecycle_rows if _values([r], "current_or_exit_profit_pct", "current_return_pct", "actual_return_pct")])),
            "replay_sample_size": len(replay_rows),
            "lifecycle_sample_size": len(lifecycle_rows),
            "advanced_learning_sample_size": _to_int(advanced_counts.get("return_evidence"), 0),
            "broker_confirmed_sample_size": _to_int(advanced_counts.get("broker_confirmed_closes_proxy"), len(closed_lifecycle)),
            "open_trade_inclusion": advanced.get("open_trade_inclusion") or ("included" if open_lifecycle else "not_present"),
            "closed_trade_inclusion": advanced.get("closed_trade_inclusion") or ("included" if closed_lifecycle else "not_present"),
            "dataset_scope_label": advanced.get("dataset_scope_label") or "mixed_lifecycle_replay_profit_capture_scope",
            "dataset_scope_mismatch_detected": mismatch,
        }
        issue = _issue(
            "scope_mismatch_labeled" if mismatch else "scope_consistent",
            "systems_use_different_open_closed_and_counterfactual_scopes" if mismatch else "learning_systems_share_compatible_scope",
            "medium" if mismatch else "low",
            max(diagnostics["core_performance_sample_size"], diagnostics["replay_sample_size"], diagnostics["lifecycle_sample_size"]),
            "Label scope differences instead of comparing headline metrics as if they share one dataset.",
            "No behavior change; scope labeling only.",
        )
        return diagnostics, issue

    def _replay_conflict(self, replay_rows: list[dict[str, Any]], statuses: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        replay = dict(statuses.get("replay_counterfactual_learning_v2") or {})
        actual_vals = _values(replay_rows, "actual_return_pct")
        best_vals = _values(replay_rows, "best_counterfactual_return", "average_best_counterfactual_return")
        improvement_vals = _values(replay_rows, "improvement_vs_actual", "average_counterfactual_improvement")
        negative = [r for r in replay_rows if _to_float(r.get("actual_return_pct")) < 0]
        outliers = sorted(replay_rows, key=lambda r: abs(_to_float(r.get("actual_return_pct")) - (_avg(actual_vals) or 0.0)), reverse=True)[:8]
        avg_actual = replay.get("average_actual_return") if replay.get("average_actual_return") not in (None, "") else _avg(actual_vals)
        avg_best = replay.get("average_best_counterfactual_return") if replay.get("average_best_counterfactual_return") not in (None, "") else _avg(best_vals)
        avg_improvement = replay.get("average_counterfactual_improvement") if replay.get("average_counterfactual_improvement") not in (None, "") else _avg(improvement_vals)
        conflict = bool(avg_actual is not None and avg_best is not None and abs(_to_float(avg_best) - _to_float(avg_actual)) >= 5.0)
        diagnostics = {
            "average_actual_return": avg_actual,
            "average_best_counterfactual_return": avg_best,
            "average_counterfactual_improvement": avg_improvement,
            "replay_actual_avg_source": replay.get("replay_actual_avg_source") or "trade_lifecycle_current_or_exit_profit_pct",
            "replay_best_virtual_source": replay.get("replay_best_virtual_source") or "shadow_counterfactual_paths_from_mfe_mae_giveback",
            "replay_scope_label": replay.get("replay_scope_label") or "active_and_closed_lifecycle_rows_shadow_counterfactual",
            "replay_closed_only": bool(replay.get("replay_closed_only", False)),
            "replay_open_included": bool(replay.get("replay_open_included", True)),
            "replay_outlier_symbols": [_text(r.get("symbol"), "unknown") for r in outliers if _text(r.get("symbol"))],
            "replay_negative_return_drivers": dict(Counter(_text(r.get("symbol"), "unknown") for r in negative).most_common(8)),
        }
        issue = _issue(
            "scope_conflict_not_core_metric_failure" if conflict else "no_material_replay_conflict",
            "replay_compares_actual_to_best_virtual_paths_not_core_closed_performance" if conflict else "replay_and_core_difference_within_current_band",
            "medium" if conflict else "low",
            len(replay_rows),
            "Show replay as counterfactual profit-capture learning, not as the Core Performance source.",
            "Use for shadow-only exit/profit-capture review.",
        )
        return diagnostics, issue

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
        core_diag, core_issue = self._core_metric_source(statuses)
        dataset_diag, dataset_issue = self._dataset_scope(lifecycle_rows, profit_rows, replay_rows, statuses)
        replay_diag, replay_issue = self._replay_conflict(replay_rows, statuses)
        v3 = dict(statuses.get("adaptive_execution_exit_intelligence_v3") or {})
        exit_learning = dict(statuses.get("exit_learning_expansion_suite_v1") or {})
        market_context = dict(statuses.get("market_context_learning_suite_v1") or {})
        acceleration = dict(statuses.get("learning_acceleration_retention_suite_v1") or {})
        infrastructure = dict(statuses.get("adaptive_learning_infrastructure_suite_v1") or {})
        worker_activation = dict(statuses.get("adaptive_worker_activation_orchestration_v1") or {})
        confidence_attr = dict(statuses.get("confidence_calibration_performance_attribution_v1") or {})
        context_expansion = dict(statuses.get("context_evidence_expansion_suite_v1") or {})
        catalyst_v2 = dict(statuses.get("catalyst_theme_narrative_capital_flow_intelligence_v2") or {})
        decision_opt = dict(statuses.get("decision_optimization_trade_management_suite_v1") or {})
        profit_capture_validation = dict(statuses.get("profit_capture_peak_decay_exit_validation_suite_v1") or {})
        full_lifecycle = dict(statuses.get("full_opportunity_lifecycle_learning_suite_v1") or {})
        long_memory = dict(statuses.get("long_term_memory_symbol_retrieval_suite_v1") or {})
        virtual_convergence = dict(statuses.get("virtual_paper_convergence_symbol_attribution_v1") or {})
        accelerated_symbol = dict(statuses.get("accelerated_learning_symbol_intelligence_suite_v1") or {})
        shadow_lab = dict(statuses.get("realistic_shadow_evidence_learning_lab_v1") or {})
        multi_horizon_intelligence = dict(statuses.get("multi_horizon_intelligence_adaptive_lifecycle_suite_v1") or {})
        paper_throughput_exit_catalyst = dict(statuses.get("paper_throughput_exit_validation_catalyst_intelligence_v1") or {})
        multi_horizon_capacity_exit = dict(statuses.get("multi_horizon_paper_capacity_exit_validation_v1") or {})
        learning_allocator = dict(statuses.get("adaptive_learning_prioritization_resource_allocation_v1") or {})
        autonomous_governance = dict(statuses.get("autonomous_intelligence_validation_governance_v1") or {})
        paper_trace = dict(statuses.get("paper_execution_trace") or {})
        paper_autopilot = dict(statuses.get("paper_autopilot_throughput") or {})
        paper_broker = dict(statuses.get("alpaca_paper_broker") or {})
        paper_path_summary = dict(paper_broker.get("paper_path_gating_summary") or paper_broker.get("paper_path_gating_diagnostics") or {})
        paper_session = dict(paper_autopilot.get("market_session_execution_timing") or paper_trace.get("market_session_execution_timing") or {})
        v3_issue = _issue(
            "shadow_exit_learning_active" if v3.get("enabled") else "shadow_exit_learning_unavailable",
            "adaptive_execution_exit_v3_tracks_profit_capture_horizon_and_peak_decay" if v3.get("enabled") else "adaptive_execution_exit_v3_not_available",
            "medium" if v3.get("enabled") and _to_float(v3.get("protect_profit_score"), 0.0) >= 45.0 else "low",
            _to_int(v3.get("tracked_trades"), 0),
            "Use V3 for shadow-only profit capture and horizon diagnostics; do not auto-apply exits.",
            _text(v3.get("shadow_only_recommendation"), "No behavior change."),
        )
        exit_learning_issue = _issue(
            "exit_learning_expansion_active" if exit_learning.get("enabled") else "exit_learning_expansion_unavailable",
            "partial_exit_time_of_day_personality_hold_and_profit_decay_learning_active" if exit_learning.get("enabled") else "exit_learning_expansion_not_available",
            "medium" if exit_learning.get("enabled") and _to_float(exit_learning.get("protect_profit_score"), 0.0) >= 45.0 else "low",
            _to_int(exit_learning.get("tracked_trades"), 0),
            "Use the expansion suite for shadow-only partial-exit, time-window, personality, holding-time, and decay review.",
            _text(exit_learning.get("shadow_exit_learning_recommendation"), "No behavior change."),
        )
        market_context_issue = _issue(
            "market_context_learning_active" if market_context.get("enabled") else "market_context_learning_unavailable",
            "premarket_catalyst_after_hours_context_learning_active" if market_context.get("enabled") else "market_context_learning_not_available",
            "medium" if market_context.get("enabled") and _to_float(market_context.get("context_confidence"), 0.0) < 45.0 else "low",
            _to_int(market_context.get("context_records"), 0),
            "Use market context as shadow-only evidence for horizon and exit-learning interpretation.",
            _text(market_context.get("shadow_context_recommendation"), "No behavior change."),
        )
        acceleration_issue = _issue(
            "learning_acceleration_active" if acceleration.get("enabled") else "learning_acceleration_unavailable",
            "priority_weighting_retention_coverage_agreement_conflict_meta_learning_active" if acceleration.get("enabled") else "learning_acceleration_not_available",
            "medium" if acceleration.get("conflict_detected") else "low",
            _to_int(acceleration.get("evidence_count"), 0),
            "Use acceleration diagnostics to focus learning workers while preserving all execution behavior.",
            _text(acceleration.get("shadow_learning_recommendation"), "No behavior change."),
        )
        infrastructure_issue = _issue(
            "adaptive_learning_infrastructure_active" if infrastructure.get("enabled") else "adaptive_learning_infrastructure_unavailable",
            "worker_orchestration_queue_budget_health_and_coverage_diagnostics_active" if infrastructure.get("enabled") else "adaptive_learning_infrastructure_not_available",
            "medium" if infrastructure.get("enabled") and _to_float(infrastructure.get("health_score"), 0.0) < 45.0 else "low",
            _to_int(infrastructure.get("collected_evidence_count"), 0),
            "Use adaptive learning infrastructure diagnostics to route future background learning work; keep trading behavior unchanged.",
            _text(infrastructure.get("shadow_recommendation"), "No behavior change."),
        )
        worker_activation_issue = _issue(
            "adaptive_worker_activation_active" if worker_activation.get("enabled") else "adaptive_worker_activation_unavailable",
            "premarket_open_trade_after_hours_replay_and_coverage_workers_cached_and_shadow_only" if worker_activation.get("enabled") else "adaptive_worker_activation_not_available",
            "medium" if worker_activation.get("enabled") and _to_int(worker_activation.get("failed_jobs"), 0) > 0 else "low",
            _to_int(worker_activation.get("completed_jobs"), 0),
            "Use worker activation diagnostics to collect cached evidence without dashboard blocking or trading behavior changes.",
            _text(worker_activation.get("shadow_recommendation"), "No behavior change."),
        )
        confidence_issue = _issue(
            "confidence_calibration_active" if confidence_attr.get("enabled") else "confidence_calibration_unavailable",
            "confidence_grade_horizon_attribution_and_daily_performance_tracking_active" if confidence_attr.get("enabled") else "confidence_calibration_not_available",
            "medium"
            if confidence_attr.get("enabled")
            and _to_int(confidence_attr.get("evidence_count"), 0) >= 20
            and _to_float(confidence_attr.get("confidence_predictive_power"), 0.0) < 45.0
            else "low",
            _to_int(confidence_attr.get("evidence_count"), 0),
            "Use calibration diagnostics to decide whether confidence and grades predict outcomes; keep sizing changes disabled.",
            _text(confidence_attr.get("shadow_recommendation"), "No behavior change."),
        )
        context_expansion_issue = _issue(
            "context_evidence_expansion_active" if context_expansion.get("enabled") else "context_evidence_expansion_unavailable",
            "open_trade_rejected_candidate_and_catalyst_evidence_expansion_active" if context_expansion.get("enabled") else "context_evidence_expansion_not_available",
            "medium"
            if context_expansion.get("enabled")
            and (
                _to_float(context_expansion.get("unknown_catalyst_rate"), 0.0) >= 60.0
                or _to_float(context_expansion.get("open_trade_learning_confidence"), 0.0) < 35.0
            )
            else "low",
            _to_int(context_expansion.get("evidence_count"), 0),
            "Use context expansion diagnostics to improve evidence coverage without changing rankings, gates, or exits.",
            _text(context_expansion.get("shadow_recommendation"), "No behavior change."),
        )
        catalyst_v2_issue = _issue(
            "catalyst_theme_narrative_capital_flow_v2_active" if catalyst_v2.get("enabled") else "catalyst_theme_narrative_capital_flow_v2_unavailable",
            "multi_catalyst_theme_narrative_sector_industry_capital_flow_learning_active" if catalyst_v2.get("enabled") else "catalyst_theme_narrative_capital_flow_v2_not_available",
            "medium"
            if catalyst_v2.get("enabled")
            and (
                _to_float(catalyst_v2.get("unknown_catalyst_rate"), 100.0) >= 60.0
                or _to_float(catalyst_v2.get("catalyst_coverage_score"), 0.0) < 35.0
                or _to_float(catalyst_v2.get("capital_flow_confidence"), 0.0) < 35.0
            )
            else "low",
            _to_int(catalyst_v2.get("evidence_count"), 0),
            "Use V2 context intelligence to classify catalyst/theme/narrative/capital-flow gaps; keep ranking and execution unchanged.",
            _text(catalyst_v2.get("shadow_recommendation"), "No behavior change."),
        )
        decision_opt_issue = _issue(
            "decision_optimization_trade_management_active" if decision_opt.get("enabled") else "decision_optimization_trade_management_unavailable",
            "shadow_exit_policy_continuation_opportunity_cost_confidence_truth_diagnostics_active" if decision_opt.get("enabled") else "decision_optimization_trade_management_not_available",
            "medium"
            if decision_opt.get("enabled")
            and (
                _to_float(decision_opt.get("continuation_failure_probability"), 0.0) >= 55.0
                or _to_float(decision_opt.get("missed_winner_rate"), 0.0) >= 35.0
                or _to_float(decision_opt.get("confidence_truth_score"), 100.0) < 50.0
            )
            else "low",
            _to_int(decision_opt.get("evidence_count"), 0),
            "Use decision optimization diagnostics for human-reviewed learning only; do not auto-apply exit, ranking, sizing, or threshold changes.",
            _text(decision_opt.get("shadow_recommendation"), "No behavior change."),
        )
        peak_decay_exit_validation_issue = _issue(
            "profit_capture_peak_decay_exit_validation_active" if profit_capture_validation.get("enabled") else "profit_capture_peak_decay_exit_validation_unavailable",
            "profit_capture_peak_decay_exit_validation_shadow_analysis_active" if profit_capture_validation.get("enabled") else "profit_capture_peak_decay_exit_validation_not_available",
            "medium"
            if profit_capture_validation.get("enabled")
            and (
                _to_float(profit_capture_validation.get("capture_quality_score"), 0.0) < 55.0
                or _to_float(profit_capture_validation.get("hold_duration_quality_score"), 0.0) < 45.0
                or _to_float(profit_capture_validation.get("continuation_failure_probability"), 0.0) >= 60.0
            )
            else "low",
            _to_int(profit_capture_validation.get("tracked_trades"), 0),
            "Use profit capture and peak-decay exit validation only for shadow learning; keep exits, thresholds, and sizing unchanged.",
            _text(profit_capture_validation.get("shadow_recommendation"), "No behavior change."),
        )
        full_lifecycle_issue = _issue(
            "full_opportunity_lifecycle_learning_active" if full_lifecycle.get("enabled") else "full_opportunity_lifecycle_learning_unavailable",
            "opportunity_lifecycle_graph_feature_attribution_and_memory_storage_diagnostics_active" if full_lifecycle.get("enabled") else "full_opportunity_lifecycle_learning_not_available",
            "medium"
            if full_lifecycle.get("enabled")
            and (
                _to_float(full_lifecycle.get("learning_completeness_score"), 0.0) < 45.0
                or _to_float(full_lifecycle.get("memory_pressure_score"), 0.0) >= 65.0
                or _text(full_lifecycle.get("cache_freshness"), "stale") == "stale"
            )
            else "low",
            _to_int(full_lifecycle.get("opportunities_tracked"), 0),
            "Use full opportunity lifecycle diagnostics to route evidence and monitor storage health; keep dashboard on compact cache and trading behavior unchanged.",
            _text(full_lifecycle.get("shadow_recommendation"), "No behavior change."),
        )
        long_memory_issue = _issue(
            "long_term_memory_symbol_retrieval_active" if long_memory.get("enabled") else "long_term_memory_symbol_retrieval_unavailable",
            "storage_retention_symbol_behavior_profiles_and_indexed_retrieval_active" if long_memory.get("enabled") else "long_term_memory_symbol_retrieval_not_available",
            "medium"
            if long_memory.get("enabled")
            and (
                _to_float(long_memory.get("memory_pressure_score"), 0.0) >= 65.0
                or _to_float(long_memory.get("retrieval_health_score"), 100.0) < 45.0
                or _text(long_memory.get("cache_freshness"), "stale") == "stale"
            )
            else "low",
            _to_int(long_memory.get("indexed_records"), 0),
            "Use long-term memory diagnostics to preserve valuable summaries, monitor storage pressure, and retrieve symbol lessons quickly; keep trading behavior unchanged.",
            _text(long_memory.get("shadow_recommendation"), "No behavior change."),
        )
        virtual_convergence_issue = _issue(
            "virtual_paper_convergence_symbol_attribution_active" if virtual_convergence.get("enabled") else "virtual_paper_convergence_symbol_attribution_unavailable",
            "virtual_to_paper_gap_symbol_horizon_exit_policy_attribution_active" if virtual_convergence.get("enabled") else "virtual_paper_convergence_symbol_attribution_not_available",
            "medium"
            if virtual_convergence.get("enabled")
            and (
                _to_float(virtual_convergence.get("average_convergence_gap"), 0.0) >= 3.0
                or _to_float(virtual_convergence.get("convergence_quality_score"), 100.0) < 55.0
            )
            else "low",
            _to_int(virtual_convergence.get("tracked_trades"), 0),
            "Use virtual-to-paper convergence diagnostics to explain missed virtual performance; keep all policies and trading behavior unchanged.",
            _text(virtual_convergence.get("shadow_recommendation"), "No behavior change."),
        )
        accelerated_symbol_issue = _issue(
            "accelerated_learning_symbol_intelligence_active" if accelerated_symbol.get("enabled") else "accelerated_learning_symbol_intelligence_unavailable",
            "cached_history_symbol_peer_cluster_and_drift_learning_active" if accelerated_symbol.get("enabled") else "accelerated_learning_symbol_intelligence_not_available",
            "medium"
            if accelerated_symbol.get("enabled")
            and (
                _to_float(accelerated_symbol.get("average_convergence_gap"), 0.0) >= 3.0
                or _to_float(accelerated_symbol.get("drift_score"), 0.0) >= 45.0
            )
            else "low",
            _to_int(accelerated_symbol.get("accelerated_learning_events"), 0),
            "Use accelerated symbol intelligence to mine cached history and peer evidence; keep all behavior unchanged.",
            _text(accelerated_symbol.get("shadow_recommendation"), "No behavior change."),
        )
        shadow_lab_issue = _issue(
            "realistic_shadow_evidence_learning_lab_active" if shadow_lab.get("enabled") else "realistic_shadow_evidence_learning_lab_unavailable",
            "shadow_only_realistic_paper_like_evidence_generation_active" if shadow_lab.get("enabled") else "realistic_shadow_evidence_learning_lab_not_available",
            "medium"
            if shadow_lab.get("enabled")
            and (
                _to_float(shadow_lab.get("average_shadow_realism_score"), 100.0) < 45.0
                or _text(shadow_lab.get("provider_warning"), "none") not in {"none", ""}
                or bool(shadow_lab.get("paper_orders_placed", False))
                or bool(shadow_lab.get("alpaca_orders_placed", False))
            )
            else "low",
            _to_int(shadow_lab.get("shadow_learning_events"), 0),
            "Use realistic shadow lab evidence only for compressed shadow learning; keep broker and paper execution unchanged.",
            _text(shadow_lab.get("shadow_recommendation"), "No behavior change."),
        )
        multi_horizon_intelligence_issue = _issue(
            "multi_horizon_intelligence_adaptive_lifecycle_active" if multi_horizon_intelligence.get("enabled") else "multi_horizon_intelligence_adaptive_lifecycle_unavailable",
            "horizon_lifecycle_symbol_peer_pattern_diagnostics_active" if multi_horizon_intelligence.get("enabled") else "multi_horizon_intelligence_adaptive_lifecycle_not_available",
            "medium"
            if multi_horizon_intelligence.get("enabled")
            and _to_float(multi_horizon_intelligence.get("horizon_mismatch_risk_score"), 0.0) >= 65.0
            else "low",
            sum(_to_int(v, 0) for v in (multi_horizon_intelligence.get("closed_trades_per_horizon") or {}).values())
            if isinstance(multi_horizon_intelligence.get("closed_trades_per_horizon"), dict)
            else 0,
            "Use multi-horizon lifecycle diagnostics to target shadow validation; do not apply learned exits without human review.",
            _text(multi_horizon_intelligence.get("shadow_recommendation"), "No behavior change."),
        )
        paper_throughput_exit_catalyst_issue = _issue(
            "paper_throughput_exit_validation_catalyst_active" if paper_throughput_exit_catalyst.get("enabled") else "paper_throughput_exit_validation_catalyst_unavailable",
            "paper_throughput_blockers_learned_exit_validation_and_catalyst_coverage_visible" if paper_throughput_exit_catalyst.get("enabled") else "paper_throughput_exit_validation_catalyst_not_available",
            "medium" if _to_float(paper_throughput_exit_catalyst.get("suppression_rate"), 0.0) >= 95.0 or _to_float(paper_throughput_exit_catalyst.get("unknown_catalyst_rate"), 100.0) >= 60.0 else "low",
            _to_int(paper_throughput_exit_catalyst.get("reviewed_today"), 0),
            "Use this summary to inspect paper evidence bottlenecks, learned-exit readiness, and catalyst coverage without changing execution.",
            _text(paper_throughput_exit_catalyst.get("recommended_next_action"), "No behavior change."),
        )
        multi_horizon_capacity_exit_issue = _issue(
            "multi_horizon_capacity_exit_validation_active" if multi_horizon_capacity_exit.get("enabled") else "multi_horizon_capacity_exit_validation_unavailable",
            "horizon_capacity_pools_and_controlled_exit_bucket_diagnostics_active" if multi_horizon_capacity_exit.get("enabled") else "multi_horizon_capacity_exit_validation_not_available",
            "medium" if _to_int(multi_horizon_capacity_exit.get("total_available"), 0) <= 0 or bool(multi_horizon_capacity_exit.get("learned_exit_bucket_auto_disabled", True)) else "low",
            _to_int(multi_horizon_capacity_exit.get("total_used"), 0),
            "Use horizon capacity pools to preserve scalp/day learning capacity; learned-exit bucket remains guarded and reversible.",
            _text(multi_horizon_capacity_exit.get("next_recommended_action"), "No behavior change."),
        )
        learning_allocator_issue = _issue(
            "adaptive_learning_prioritization_active" if learning_allocator.get("enabled") else "adaptive_learning_prioritization_unavailable",
            "weakness_detection_learning_value_resource_allocation_worker_replay_memory_and_governance_diagnostics_active" if learning_allocator.get("enabled") else "adaptive_learning_prioritization_not_available",
            "medium"
            if learning_allocator.get("enabled")
            and (
                not bool(learning_allocator.get("allocation_safe", False))
                or _text(learning_allocator.get("governance_status"), "") == "guardrailed_observation_only"
            )
            else "low",
            len(learning_allocator.get("weakness_rankings") or []),
            "Use prioritization diagnostics to focus learning resources only; keep policy application and trading behavior disabled.",
            _text(learning_allocator.get("shadow_recommendation"), "No behavior change."),
        )
        autonomous_governance_issue = _issue(
            "autonomous_intelligence_validation_governance_active" if autonomous_governance.get("enabled") else "autonomous_intelligence_validation_governance_unavailable",
            "truth_validation_self_healing_governance_and_policy_readiness_diagnostics_active" if autonomous_governance.get("enabled") else "autonomous_intelligence_validation_governance_not_available",
            "medium"
            if autonomous_governance.get("enabled")
            and _text(autonomous_governance.get("warning_level"), "green") in {"orange", "red"}
            else "low",
            _to_int(autonomous_governance.get("evidence_count"), 0),
            "Use autonomous governance diagnostics for truth validation and virtual-test planning only; keep all policies unapplied.",
            _text(autonomous_governance.get("shadow_recommendation"), "No behavior change."),
        )
        paper_path_candidates_seen = _to_int(paper_trace.get("candidates_seen"), 0)
        paper_path_eligible = _to_int(paper_trace.get("eligible_candidates"), 0)
        paper_path_submitted = _to_int(paper_trace.get("orders_submitted"), 0)
        paper_path_unique_open = _to_int(paper_trace.get("open_positions_unique_count"), _to_int(paper_trace.get("broker_open_positions_count"), 0))
        paper_path_raw_rows = _to_int(paper_trace.get("open_position_rows_count"), paper_path_unique_open)
        paper_path_evidence = _to_int(decision_opt.get("evidence_count"), 0) + _to_int(exit_learning.get("tracked_trades"), 0)
        paper_path_diag = {
            "paper_path_status": _text(
                paper_path_summary.get("paper_path_status")
                or paper_session.get("session_block_reason")
                or paper_trace.get("final_blocker_reason")
                or paper_trace.get("why_no_trade_today"),
                "unknown_blocker",
            ),
            "top_blocker": _text(
                paper_path_summary.get("top_blocker")
                or paper_trace.get("final_blocker_reason")
                or paper_session.get("session_block_reason")
                or paper_trace.get("why_no_trade_today"),
                "unknown_blocker",
            ),
            "candidates_reviewed_today": _to_int(paper_path_summary.get("candidates_reviewed_today"), paper_path_candidates_seen),
            "candidates_passed_ranking": _to_int(paper_path_summary.get("candidates_passed_ranking"), paper_path_eligible),
            "candidates_passed_risk": _to_int(paper_path_summary.get("candidates_passed_risk"), paper_path_eligible),
            "candidates_blocked": _to_int(paper_path_summary.get("candidates_blocked"), max(0, paper_path_candidates_seen - paper_path_eligible)),
            "high_confidence_candidates_blocked": _to_int(paper_path_summary.get("high_confidence_candidates_blocked"), max(0, paper_path_candidates_seen - paper_path_eligible)),
            "missed_evidence_estimate": _to_int(paper_path_summary.get("missed_evidence_estimate"), max(0, paper_path_candidates_seen - paper_path_submitted)),
            "missed_opportunity_estimate": _to_int(paper_path_summary.get("missed_opportunity_estimate"), max(0, paper_path_candidates_seen - paper_path_submitted)),
            "available_buying_power_at_block": _to_float(paper_path_summary.get("available_buying_power_at_block"), _to_float(paper_broker.get("buying_power"), _to_float(paper_broker.get("available_buying_power"), 0.0))),
            "current_open_positions": _to_int(paper_path_summary.get("current_open_positions"), paper_path_unique_open),
            "broker_confirmed_open_positions": _to_int(paper_path_summary.get("broker_confirmed_open_positions"), _to_int(paper_trace.get("broker_open_positions_count"), 0)),
            "stale_internal_position_rows": _to_int(paper_path_summary.get("stale_internal_position_rows"), max(0, paper_path_raw_rows - paper_path_unique_open)),
            "open_position_rows_count": _to_int(paper_path_summary.get("open_position_rows_count"), paper_path_raw_rows),
            "capacity_available": _to_int(paper_path_summary.get("capacity_available"), _to_int(paper_trace.get("capacity_available"), 0)),
            "capacity_blocked": bool(paper_path_summary.get("capacity_blocked", paper_trace.get("capacity_blocked", False))),
            "session_now_utc": _text(paper_path_summary.get("session_now_utc"), _text(paper_session.get("session_now_utc"), "")),
            "session_now_et": _text(paper_path_summary.get("session_now_et") or paper_path_summary.get("session_timestamp_et"), _text(paper_session.get("session_now_et") or paper_session.get("session_timestamp_et"), "")),
            "session_source": _text(paper_path_summary.get("session_source"), _text(paper_session.get("session_source"), "market_calendar_knowledge")),
            "session_cache_age_seconds": round(_to_float(paper_path_summary.get("session_cache_age_seconds"), _to_float(paper_session.get("session_cache_age_seconds"), 0.0)), 2),
            "session_is_stale": bool(paper_path_summary.get("session_is_stale", paper_session.get("session_is_stale", False))),
            "market_should_be_open_now": bool(paper_path_summary.get("market_should_be_open_now", paper_session.get("market_should_be_open_now", False))),
            "session_block_reason": _text(paper_path_summary.get("session_block_reason"), _text(paper_session.get("session_block_reason"), "none")),
            "session_block_validated": bool(paper_path_summary.get("session_block_validated", paper_session.get("session_block_validated", False))),
            "candidates_blocked_by_session_gate_today": int(
                max(
                    0,
                    _to_int(paper_path_summary.get("candidates_blocked_by_session_gate_today"), paper_path_candidates_seen)
                    if _text(paper_path_summary.get("paper_path_status"), _text(paper_session.get("session_block_reason"), "")) == "session_order_submission_blocked"
                    else 0,
                )
            ),
            "likely_missed_evidence_from_session_bug": int(
                max(
                    0,
                    _to_int(paper_path_summary.get("likely_missed_evidence_from_session_bug"), paper_path_candidates_seen)
                    if bool(paper_path_summary.get("session_is_stale", paper_session.get("session_is_stale", False)))
                    and bool(paper_path_summary.get("market_should_be_open_now", paper_session.get("market_should_be_open_now", False)))
                    and not bool(paper_session.get("paper_order_submission_allowed", False))
                    else 0,
                )
            ),
            "recommended_safe_action": "Keep market-session safety intact; count unique open positions for capacity and keep learned exits shadow-only.",
            "learned_exit_status": "shadow_only_not_applied",
            "learned_hold_duration_status": "shadow_only_not_applied",
            "best_shadow_exit_policy": _text(decision_opt.get("best_virtual_exit_policy"), "insufficient_data"),
            "best_shadow_hold_window": _text(exit_learning.get("optimal_hold_window") or exit_learning.get("best_hold_window"), "insufficient_data"),
            "evidence_supporting_learned_exits": paper_path_evidence,
            "readiness_status": "validation_ready_shadow_only" if paper_path_evidence >= 40 else "not_ready",
            "remaining_evidence_needed": "human_review_required_before_any_paper_exit_changes",
            "learned_exits_applied": False,
            "learned_exits_ready": False,
            "behavior_safe_to_apply": False,
        }
        horizon_dashboard = dict(statuses.get("horizon_performance_dashboard") or {})
        multi_horizon = dict(statuses.get("multi_horizon_paper_trading") or {})
        shadow_lab = dict(statuses.get("realistic_shadow_evidence_learning_lab_v1") or {})
        profit_capture_validation = dict(statuses.get("profit_capture_peak_decay_exit_validation_suite_v1") or {})
        def _coarse_count(name: str) -> int:
            horizon = dict(horizon_dashboard.get(name) or {})
            return _to_int(
                horizon.get("closed_sample_size"),
                _to_int(
                    horizon.get("sample_size"),
                    _to_int(
                        horizon.get("natural_exit_count"),
                        _to_int(
                            horizon.get("sample_count"),
                            _to_int(
                                horizon.get("closed_count"),
                                _to_int(multi_horizon.get(f"{name}_closures_today") or multi_horizon.get(f"{name}_entries_today"), 0),
                            ),
                        ),
                    ),
                ),
            )

        coarse_counts = {
            "scalp": _coarse_count("scalp"),
            "day_trade": _coarse_count("day_trade"),
            "swing_trade": _coarse_count("swing_trade"),
        }
        paper_horizon_bias = "balanced_mix"
        if coarse_counts["swing_trade"] >= max(coarse_counts["scalp"], coarse_counts["day_trade"]) and coarse_counts["swing_trade"] > 0:
            paper_horizon_bias = "swing_trade_bias"
        elif coarse_counts["day_trade"] >= max(coarse_counts["scalp"], coarse_counts["swing_trade"]) and coarse_counts["day_trade"] > 0:
            paper_horizon_bias = "day_trade_bias"
        elif coarse_counts["scalp"] > 0:
            paper_horizon_bias = "scalp_bias"
        horizon_mismatch_risk = 0.0
        if paper_horizon_bias == "swing_trade_bias":
            horizon_mismatch_risk += 20.0
        if _text(horizon_dashboard.get("weakest_current_horizon"), "") == "day_trade":
            horizon_mismatch_risk += 15.0
        if not bool(paper_path_diag.get("learned_exits_applied", False)) and bool(paper_path_diag.get("natural_exit_preserved", True)):
            horizon_mismatch_risk += 15.0
        if _to_float(profit_capture_validation.get("hold_duration_quality_score"), 0.0) < 45.0:
            horizon_mismatch_risk += 10.0
        if _text(shadow_lab.get("best_horizon"), "") == "hold_duration":
            horizon_mismatch_risk += 10.0
        horizon_coverage_diag = {
            "enabled": True,
            "tested_horizons": ["scalp", "day_trade", "swing_trade"],
            "missing_horizons": [],
            "closed_trades_by_horizon": coarse_counts,
            "paper_entries_today_by_horizon": {
                "scalp": _to_int(multi_horizon.get("scalp_entries_today"), 0),
                "day_trade": _to_int(multi_horizon.get("day_trade_entries_today"), 0),
                "swing_trade": _to_int(multi_horizon.get("swing_trade_entries_today"), 0),
            },
            "paper_closures_today_by_horizon": {
                "scalp": _to_int(multi_horizon.get("scalp_closures_today"), 0),
                "day_trade": _to_int(multi_horizon.get("day_trade_closures_today"), 0),
                "swing_trade": _to_int(multi_horizon.get("swing_trade_closures_today"), 0),
            },
            "best_horizon": _text(horizon_dashboard.get("best_current_horizon"), _text(multi_horizon.get("best_current_horizon"), "insufficient_data")),
            "weakest_horizon": _text(horizon_dashboard.get("weakest_current_horizon"), _text(multi_horizon.get("weakest_current_horizon"), "insufficient_data")),
            "dominant_horizon": paper_horizon_bias.replace("_bias", ""),
            "paper_horizon_bias": paper_horizon_bias,
            "shadow_horizon_balance": _to_float(multi_horizon.get("multi_horizon_learning_score"), 0.0),
            "learned_exits_applied": False,
            "learned_horizon_status": "shadow_only_not_applied",
            "why_positions_hold_long": (
                "Natural exits remain preserved and learned exits are still shadow-only, so paper positions can continue to hold longer than the learned shadow windows."
            ),
            "horizon_mismatch_risk_score": round(min(100.0, horizon_mismatch_risk), 2),
            "next_recommended_horizon_test": (
                "Expand 15m-60m scalp coverage before changing any paper exit behavior."
                if coarse_counts["scalp"] <= coarse_counts["day_trade"] and coarse_counts["scalp"] <= coarse_counts["swing_trade"]
                else "Compare 2h-EOD day-trade coverage against the current swing bias."
            ),
        }
        paper_path_diag["horizon_coverage_summary"] = horizon_coverage_diag
        paper_path_issue = _issue(
            "paper_path_gating_transparent" if paper_path_candidates_seen > 0 else "paper_path_gating_warming_up",
            "session_gate_and_unique_position_capacity_diagnostics_active" if paper_path_candidates_seen > 0 else "insufficient_session_trace",
            "medium" if _text(paper_path_diag.get("top_blocker"), "") in {"session_order_submission_blocked", "open_confirmation_required", "max_new_positions_per_cycle_reached"} else "low",
            paper_path_candidates_seen,
            "Use the new paper-path gating summary to explain blockers and capacity without changing strategy gates.",
            "Keep learned exits shadow-only and fix stale-row overcounting only for diagnostics/capacity truth.",
        )
        issue_status = {
            "core_metric_source_regression": core_issue,
            "dataset_scope_mismatch": dataset_issue,
            "opportunity_cost": opp_issue,
            "execution_participation": exec_issue,
            "profit_capture": profit_issue,
            "follow_through_continuation": follow_issue,
            "buy_purity": buy_issue,
            "exit_quality": exit_issue,
            "replay_conflict": replay_issue,
            "adaptive_execution_exit_v3": v3_issue,
            "exit_learning_expansion_suite_v1": exit_learning_issue,
            "market_context_learning_suite_v1": market_context_issue,
            "learning_acceleration_retention_suite_v1": acceleration_issue,
            "adaptive_learning_infrastructure_suite_v1": infrastructure_issue,
            "adaptive_worker_activation_orchestration_v1": worker_activation_issue,
            "confidence_calibration_performance_attribution_v1": confidence_issue,
            "context_evidence_expansion_suite_v1": context_expansion_issue,
            "catalyst_theme_narrative_capital_flow_intelligence_v2": catalyst_v2_issue,
            "decision_optimization_trade_management_suite_v1": decision_opt_issue,
            "profit_capture_peak_decay_exit_validation_suite_v1": peak_decay_exit_validation_issue,
            "full_opportunity_lifecycle_learning_suite_v1": full_lifecycle_issue,
            "long_term_memory_symbol_retrieval_suite_v1": long_memory_issue,
            "virtual_paper_convergence_symbol_attribution_v1": virtual_convergence_issue,
            "accelerated_learning_symbol_intelligence_suite_v1": accelerated_symbol_issue,
            "realistic_shadow_evidence_learning_lab_v1": shadow_lab_issue,
            "multi_horizon_intelligence_adaptive_lifecycle_suite_v1": multi_horizon_intelligence_issue,
            "paper_throughput_exit_validation_catalyst_intelligence_v1": paper_throughput_exit_catalyst_issue,
            "multi_horizon_paper_capacity_exit_validation_v1": multi_horizon_capacity_exit_issue,
            "adaptive_learning_prioritization_resource_allocation_v1": learning_allocator_issue,
            "autonomous_intelligence_validation_governance_v1": autonomous_governance_issue,
            "paper_path_gating": paper_path_issue,
        }
        medium_or_higher = [name for name, issue in issue_status.items() if issue.get("severity") in {"medium", "high"}]
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_learning_issue_audit",
            "generated_at": _now_iso(),
            "issue_status": issue_status,
            "core_metric_source_regression_status": core_issue,
            "dataset_scope_mismatch_status": dataset_issue,
            "profit_capture_issue_status": profit_issue,
            "exit_quality_issue_status": exit_issue,
            "replay_conflict_status": replay_issue,
            "adaptive_execution_exit_v3_status": v3_issue,
            "exit_learning_expansion_status": exit_learning_issue,
            "market_context_learning_status": market_context_issue,
            "learning_acceleration_retention_status": acceleration_issue,
            "adaptive_learning_infrastructure_status": infrastructure_issue,
            "adaptive_worker_activation_status": worker_activation_issue,
            "confidence_calibration_performance_attribution_status": confidence_issue,
            "context_evidence_expansion_status": context_expansion_issue,
            "catalyst_theme_narrative_capital_flow_v2_status": catalyst_v2_issue,
            "decision_optimization_trade_management_status": decision_opt_issue,
            "profit_capture_peak_decay_exit_validation_status": peak_decay_exit_validation_issue,
            "full_opportunity_lifecycle_learning_status": full_lifecycle_issue,
            "long_term_memory_symbol_retrieval_status": long_memory_issue,
            "virtual_paper_convergence_symbol_attribution_status": virtual_convergence_issue,
            "accelerated_learning_symbol_intelligence_status": accelerated_symbol_issue,
            "realistic_shadow_evidence_learning_lab_status": shadow_lab_issue,
            "multi_horizon_intelligence_adaptive_lifecycle_status": multi_horizon_intelligence_issue,
            "paper_throughput_exit_validation_catalyst_status": paper_throughput_exit_catalyst_issue,
            "multi_horizon_paper_capacity_exit_validation_status": multi_horizon_capacity_exit_issue,
            "adaptive_learning_prioritization_resource_allocation_status": learning_allocator_issue,
            "autonomous_intelligence_validation_governance_status": autonomous_governance_issue,
            "paper_path_gating_status": paper_path_issue,
            "execution_participation_display_status": exec_issue,
            "core_metric_source_diagnostics": core_diag,
            "dataset_scope_diagnostics": dataset_diag,
            "opportunity_cost_diagnostics": opp_diag,
            "execution_participation_diagnostics": exec_diag,
            "profit_capture_diagnostics": profit_diag,
            "follow_through_diagnostics": follow_diag,
            "buy_purity_diagnostics": buy_diag,
            "exit_quality_diagnostics": exit_diag,
            "replay_conflict_diagnostics": replay_diag,
            "adaptive_execution_exit_v3_diagnostics": {
                "profit_capture_score": v3.get("profit_capture_score"),
                "avg_giveback": v3.get("avg_giveback"),
                "avg_capture_ratio": v3.get("avg_capture_ratio"),
                "most_profitable_horizon": v3.get("most_profitable_horizon"),
                "highest_giveback_horizon": v3.get("highest_giveback_horizon"),
                "protect_profit_score": v3.get("protect_profit_score"),
                "hold_longer_score": v3.get("hold_longer_score"),
                "continuation_probability": v3.get("continuation_probability"),
                "shadow_exit_bias": v3.get("shadow_exit_bias"),
                "shadow_only_recommendation": v3.get("shadow_only_recommendation"),
                "behavior_safe_to_apply": bool(v3.get("behavior_safe_to_apply", False)),
            },
            "exit_learning_expansion_diagnostics": {
                "tracked_trades": exit_learning.get("tracked_trades"),
                "best_partial_exit_variant": exit_learning.get("best_partial_exit_variant"),
                "partial_exit_profit_delta": exit_learning.get("partial_exit_profit_delta"),
                "partial_exit_capture_improvement": exit_learning.get("partial_exit_capture_improvement"),
                "best_profit_window": exit_learning.get("best_profit_window"),
                "highest_giveback_window": exit_learning.get("highest_giveback_window"),
                "dominant_trade_personality": exit_learning.get("dominant_trade_personality"),
                "weakest_trade_personality": exit_learning.get("weakest_trade_personality"),
                "best_hold_window": exit_learning.get("best_hold_window"),
                "highest_decay_milestone": exit_learning.get("highest_decay_milestone"),
                "protect_profit_score": exit_learning.get("protect_profit_score"),
                "hold_longer_score": exit_learning.get("hold_longer_score"),
                "continuation_after_profit_score": exit_learning.get("continuation_after_profit_score"),
                "shadow_exit_learning_recommendation": exit_learning.get("shadow_exit_learning_recommendation"),
                "behavior_safe_to_apply": bool(exit_learning.get("behavior_safe_to_apply", False)),
            },
            "market_context_learning_diagnostics": {
                "tracked_symbols": market_context.get("tracked_symbols"),
                "tracked_trades": market_context.get("tracked_trades"),
                "context_records": market_context.get("context_records"),
                "strongest_premarket_profile": market_context.get("strongest_premarket_profile"),
                "weakest_premarket_profile": market_context.get("weakest_premarket_profile"),
                "dominant_catalyst_type": market_context.get("dominant_catalyst_type"),
                "strongest_catalyst_type": market_context.get("strongest_catalyst_type"),
                "weakest_catalyst_type": market_context.get("weakest_catalyst_type"),
                "strongest_after_hours_profile": market_context.get("strongest_after_hours_profile"),
                "highest_gap_fade_risk_profile": market_context.get("highest_gap_fade_risk_profile"),
                "best_context_horizon": market_context.get("best_context_horizon"),
                "highest_giveback_context": market_context.get("highest_giveback_context"),
                "context_confidence": market_context.get("context_confidence"),
                "gap_risk_score": market_context.get("gap_risk_score"),
                "premarket_continuation_probability": market_context.get("premarket_continuation_probability"),
                "gap_and_fade_probability": market_context.get("gap_and_fade_probability"),
                "shadow_context_recommendation": market_context.get("shadow_context_recommendation"),
                "behavior_safe_to_apply": bool(market_context.get("behavior_safe_to_apply", False)),
            },
            "learning_acceleration_retention_diagnostics": {
                "top_learning_priority": acceleration.get("top_learning_priority"),
                "secondary_learning_priority": acceleration.get("secondary_learning_priority"),
                "weighted_confidence_score": acceleration.get("weighted_confidence_score"),
                "knowledge_retention_score": acceleration.get("knowledge_retention_score"),
                "coverage_score": acceleration.get("coverage_score"),
                "agreement_score": acceleration.get("agreement_score"),
                "conflict_detected": bool(acceleration.get("conflict_detected", False)),
                "conflict_type": acceleration.get("conflict_type"),
                "meta_learning_score": acceleration.get("meta_learning_score"),
                "strongest_new_lesson": acceleration.get("strongest_new_lesson"),
                "weakest_coverage_area": acceleration.get("weakest_coverage_area"),
                "most_predictive_learning_system": acceleration.get("most_predictive_learning_system"),
                "recommended_worker_focus": acceleration.get("recommended_worker_focus"),
                "shadow_learning_recommendation": acceleration.get("shadow_learning_recommendation"),
                "behavior_safe_to_apply": bool(acceleration.get("behavior_safe_to_apply", False)),
            },
            "adaptive_learning_infrastructure_diagnostics": {
                "active_worker_count": infrastructure.get("active_worker_count"),
                "completed_jobs": infrastructure.get("completed_jobs"),
                "failed_jobs": infrastructure.get("failed_jobs"),
                "learning_load_score": infrastructure.get("learning_load_score"),
                "worker_efficiency_score": infrastructure.get("worker_efficiency_score"),
                "api_budget_score": infrastructure.get("api_budget_score"),
                "evidence_gap_score": infrastructure.get("evidence_gap_score"),
                "health_score": infrastructure.get("health_score"),
                "targeted_learning_area": infrastructure.get("targeted_learning_area"),
                "highest_priority_task": infrastructure.get("highest_priority_task"),
                "orchestration_health": infrastructure.get("orchestration_health"),
                "worker_queue_depth": infrastructure.get("worker_queue_depth"),
                "stale_task_count": infrastructure.get("stale_task_count"),
                "strongest_coverage_area": infrastructure.get("strongest_coverage_area"),
                "weakest_coverage_area": infrastructure.get("weakest_coverage_area"),
                "recommended_focus": infrastructure.get("recommended_focus"),
                "shadow_recommendation": infrastructure.get("shadow_recommendation"),
                "workers_started_by_dashboard": bool(infrastructure.get("workers_started_by_dashboard", False)),
                "dashboard_request_blocking": bool(infrastructure.get("dashboard_request_blocking", False)),
                "behavior_safe_to_apply": bool(infrastructure.get("behavior_safe_to_apply", False)),
            },
            "adaptive_worker_activation_diagnostics": {
                "orchestrator_status": worker_activation.get("orchestrator_status"),
                "active_worker_count": worker_activation.get("active_worker_count"),
                "completed_jobs": worker_activation.get("completed_jobs"),
                "failed_jobs": worker_activation.get("failed_jobs"),
                "skipped_jobs": worker_activation.get("skipped_jobs"),
                "queue_depth": worker_activation.get("queue_depth"),
                "worker_efficiency_score": worker_activation.get("worker_efficiency_score"),
                "api_budget_score": worker_activation.get("api_budget_score"),
                "cache_hit_rate": worker_activation.get("cache_hit_rate"),
                "premarket_worker_status": worker_activation.get("premarket_worker_status"),
                "open_trade_worker_status": worker_activation.get("open_trade_worker_status"),
                "after_hours_worker_status": worker_activation.get("after_hours_worker_status"),
                "replay_worker_status": worker_activation.get("replay_worker_status"),
                "coverage_worker_status": worker_activation.get("coverage_worker_status"),
                "recommended_next_worker_focus": worker_activation.get("recommended_next_worker_focus"),
                "provider_calls_used": worker_activation.get("provider_calls_used"),
                "llm_calls_used": worker_activation.get("llm_calls_used"),
                "shadow_recommendation": worker_activation.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(worker_activation.get("behavior_safe_to_apply", False)),
            },
            "confidence_calibration_performance_attribution_diagnostics": {
                "evidence_count": confidence_attr.get("evidence_count"),
                "best_confidence_bucket": confidence_attr.get("best_confidence_bucket"),
                "worst_confidence_bucket": confidence_attr.get("worst_confidence_bucket"),
                "confidence_calibration_score": confidence_attr.get("confidence_calibration_score"),
                "confidence_predictive_power": confidence_attr.get("confidence_predictive_power"),
                "confidence_sizing_readiness": confidence_attr.get("confidence_sizing_readiness"),
                "best_grade": confidence_attr.get("best_grade"),
                "grade_predictive_power": confidence_attr.get("grade_predictive_power"),
                "best_confidence_horizon_pair": confidence_attr.get("best_confidence_horizon_pair"),
                "worst_confidence_horizon_pair": confidence_attr.get("worst_confidence_horizon_pair"),
                "sizing_readiness_score": confidence_attr.get("sizing_readiness_score"),
                "ready_for_confidence_weighted_sizing": bool(confidence_attr.get("ready_for_confidence_weighted_sizing", False)),
                "reason_not_ready": confidence_attr.get("reason_not_ready"),
                "top_profit_driver": confidence_attr.get("top_profit_driver"),
                "top_loss_driver": confidence_attr.get("top_loss_driver"),
                "daily_positive_rate": confidence_attr.get("daily_positive_rate"),
                "current_day_return": confidence_attr.get("current_day_return"),
                "current_day_status": confidence_attr.get("current_day_status"),
                "shadow_recommendation": confidence_attr.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(confidence_attr.get("behavior_safe_to_apply", False)),
                "position_sizing_changed": bool(confidence_attr.get("position_sizing_changed", False)),
            },
            "context_evidence_expansion_diagnostics": {
                "evidence_count": context_expansion.get("evidence_count"),
                "active_trades_tracked": context_expansion.get("active_trades_tracked"),
                "strongest_open_trade": context_expansion.get("strongest_open_trade"),
                "weakest_open_trade": context_expansion.get("weakest_open_trade"),
                "highest_profit_decay_symbol": context_expansion.get("highest_profit_decay_symbol"),
                "highest_giveback_symbol": context_expansion.get("highest_giveback_symbol"),
                "open_trade_learning_confidence": context_expansion.get("open_trade_learning_confidence"),
                "rejected_candidates_reviewed": context_expansion.get("rejected_candidates_reviewed"),
                "rejection_accuracy": context_expansion.get("rejection_accuracy"),
                "missed_winners": context_expansion.get("missed_winners"),
                "avoided_losers": context_expansion.get("avoided_losers"),
                "biggest_missed_symbol": context_expansion.get("biggest_missed_symbol"),
                "rejected_candidate_learning_confidence": context_expansion.get("rejected_candidate_learning_confidence"),
                "catalyst_records": context_expansion.get("catalyst_records"),
                "dominant_catalyst_type": context_expansion.get("dominant_catalyst_type"),
                "unknown_catalyst_rate": context_expansion.get("unknown_catalyst_rate"),
                "catalyst_coverage_score": context_expansion.get("catalyst_coverage_score"),
                "best_catalyst_horizon": context_expansion.get("best_catalyst_horizon"),
                "catalyst_learning_confidence": context_expansion.get("catalyst_learning_confidence"),
                "top_learning_gap": context_expansion.get("top_learning_gap"),
                "shadow_recommendation": context_expansion.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(context_expansion.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(context_expansion.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(context_expansion.get("paper_execution_behavior_changed", False)),
            },
            "catalyst_theme_narrative_capital_flow_v2_diagnostics": {
                "evidence_count": catalyst_v2.get("evidence_count"),
                "catalyst_records": catalyst_v2.get("catalyst_records"),
                "dominant_catalyst": catalyst_v2.get("dominant_catalyst"),
                "strongest_catalyst_type": catalyst_v2.get("strongest_catalyst_type"),
                "weakest_catalyst_type": catalyst_v2.get("weakest_catalyst_type"),
                "catalyst_coverage_score": catalyst_v2.get("catalyst_coverage_score"),
                "unknown_catalyst_rate": catalyst_v2.get("unknown_catalyst_rate"),
                "catalyst_truth_score": catalyst_v2.get("catalyst_truth_score"),
                "catalyst_prediction_accuracy": catalyst_v2.get("catalyst_prediction_accuracy"),
                "strongest_theme": catalyst_v2.get("strongest_theme"),
                "weakest_theme": catalyst_v2.get("weakest_theme"),
                "dominant_theme": catalyst_v2.get("dominant_theme"),
                "strongest_sector": catalyst_v2.get("strongest_sector"),
                "weakest_sector": catalyst_v2.get("weakest_sector"),
                "dominant_industry": catalyst_v2.get("dominant_industry"),
                "strongest_capital_flow": catalyst_v2.get("strongest_capital_flow"),
                "market_leader": catalyst_v2.get("market_leader"),
                "strongest_narrative_chain": catalyst_v2.get("strongest_narrative_chain"),
                "catalyst_decay_learning_score": catalyst_v2.get("catalyst_decay_learning_score"),
                "most_reliable_catalyst": catalyst_v2.get("most_reliable_catalyst"),
                "top_learning_gap": catalyst_v2.get("top_learning_gap"),
                "shadow_recommendation": catalyst_v2.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(catalyst_v2.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(catalyst_v2.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(catalyst_v2.get("paper_execution_behavior_changed", False)),
            },
            "decision_optimization_trade_management_diagnostics": {
                "evidence_count": decision_opt.get("evidence_count"),
                "tracked_trades": decision_opt.get("tracked_trades"),
                "best_virtual_exit_policy": decision_opt.get("best_virtual_exit_policy"),
                "worst_virtual_exit_policy": decision_opt.get("worst_virtual_exit_policy"),
                "highest_improvement_policy": decision_opt.get("highest_improvement_policy"),
                "most_reliable_policy": decision_opt.get("most_reliable_policy"),
                "continuation_failure_probability": decision_opt.get("continuation_failure_probability"),
                "strongest_failure_signal": decision_opt.get("strongest_failure_signal"),
                "continuation_quality_score": decision_opt.get("continuation_quality_score"),
                "rejection_accuracy": decision_opt.get("rejection_accuracy"),
                "missed_winner_rate": decision_opt.get("missed_winner_rate"),
                "avoided_loser_rate": decision_opt.get("avoided_loser_rate"),
                "decision_quality_score": decision_opt.get("decision_quality_score"),
                "confidence_truth_score": decision_opt.get("confidence_truth_score"),
                "predictive_power": decision_opt.get("predictive_power"),
                "sizing_readiness_score": decision_opt.get("sizing_readiness_score"),
                "confidence_reliability": decision_opt.get("confidence_reliability"),
                "biggest_decision_gap": decision_opt.get("biggest_decision_gap"),
                "strongest_improvement_area": decision_opt.get("strongest_improvement_area"),
                "highest_opportunity_cost": decision_opt.get("highest_opportunity_cost"),
                "top_exit_learning_focus": decision_opt.get("top_exit_learning_focus"),
                "confidence_calibration_status": decision_opt.get("confidence_calibration_status"),
                "shadow_recommendation": decision_opt.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(decision_opt.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(decision_opt.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(decision_opt.get("paper_execution_behavior_changed", False)),
                "position_sizing_changed": bool(decision_opt.get("position_sizing_changed", False)),
                "thresholds_changed": bool(decision_opt.get("thresholds_changed", False)),
            },
            "profit_capture_peak_decay_exit_validation_diagnostics": {
                "tracked_trades": profit_capture_validation.get("tracked_trades"),
                "average_capture_ratio": profit_capture_validation.get("average_capture_ratio"),
                "average_giveback_pct": profit_capture_validation.get("average_giveback_pct"),
                "capture_quality_score": profit_capture_validation.get("capture_quality_score"),
                "highest_giveback_trade": profit_capture_validation.get("highest_giveback_trade"),
                "best_capture_trade": profit_capture_validation.get("best_capture_trade"),
                "strongest_profit_milestone": profit_capture_validation.get("strongest_profit_milestone"),
                "weakest_profit_milestone": profit_capture_validation.get("weakest_profit_milestone"),
                "continuation_failure_probability": profit_capture_validation.get("continuation_failure_probability"),
                "strongest_failure_signal": profit_capture_validation.get("strongest_failure_signal"),
                "best_hold_duration_by_horizon": profit_capture_validation.get("best_hold_duration_by_horizon"),
                "hold_duration_quality_score": profit_capture_validation.get("hold_duration_quality_score"),
                "best_exit_policy": profit_capture_validation.get("best_exit_policy"),
                "second_best_exit_policy": profit_capture_validation.get("second_best_exit_policy"),
                "highest_improvement_policy": profit_capture_validation.get("highest_improvement_policy"),
                "most_consistent_policy": profit_capture_validation.get("most_consistent_policy"),
                "weakest_policy": profit_capture_validation.get("weakest_policy"),
                "best_exit_policy_by_horizon": profit_capture_validation.get("best_exit_policy_by_horizon"),
                "closest_exit_policy_to_readiness": profit_capture_validation.get("closest_exit_policy_to_readiness"),
                "readiness_score": profit_capture_validation.get("readiness_score"),
                "readiness_blocker": profit_capture_validation.get("readiness_blocker"),
                "policy_confidence": profit_capture_validation.get("policy_confidence"),
                "shadow_recommendation": profit_capture_validation.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(profit_capture_validation.get("behavior_safe_to_apply", False)),
            },
            "full_opportunity_lifecycle_learning_diagnostics": {
                "opportunities_tracked": full_lifecycle.get("opportunities_tracked"),
                "paper_trades_tracked": full_lifecycle.get("paper_trades_tracked"),
                "virtual_trades_tracked": full_lifecycle.get("virtual_trades_tracked"),
                "rejected_tracked": full_lifecycle.get("rejected_tracked"),
                "skipped_tracked": full_lifecycle.get("skipped_tracked"),
                "ignored_tracked": full_lifecycle.get("ignored_tracked"),
                "blocked_tracked": full_lifecycle.get("blocked_tracked"),
                "missed_winners": full_lifecycle.get("missed_winners"),
                "avoided_losers": full_lifecycle.get("avoided_losers"),
                "learning_completeness_score": full_lifecycle.get("learning_completeness_score"),
                "strongest_learning_connection": full_lifecycle.get("strongest_learning_connection"),
                "weakest_learning_connection": full_lifecycle.get("weakest_learning_connection"),
                "cross_system_learning_score": full_lifecycle.get("cross_system_learning_score"),
                "most_predictive_feature": full_lifecycle.get("most_predictive_feature"),
                "least_predictive_feature": full_lifecycle.get("least_predictive_feature"),
                "highest_value_learning_focus": full_lifecycle.get("highest_value_learning_focus"),
                "recommended_worker_focus": full_lifecycle.get("recommended_worker_focus"),
                "memory_quality_score": full_lifecycle.get("memory_quality_score"),
                "storage_health_score": full_lifecycle.get("storage_health_score"),
                "memory_pressure_score": full_lifecycle.get("memory_pressure_score"),
                "cache_freshness": full_lifecycle.get("cache_freshness"),
                "cache_status": full_lifecycle.get("cache_status"),
                "dashboard_scan_rows": full_lifecycle.get("dashboard_scan_rows"),
                "api_calls_used": full_lifecycle.get("api_calls_used"),
                "provider_calls_used": full_lifecycle.get("provider_calls_used"),
                "llm_calls_used": full_lifecycle.get("llm_calls_used"),
                "bandwidth_saving_mode": bool(full_lifecycle.get("bandwidth_saving_mode", True)),
                "api_budget_status": full_lifecycle.get("api_budget_status"),
                "shadow_recommendation": full_lifecycle.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(full_lifecycle.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(full_lifecycle.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(full_lifecycle.get("paper_execution_behavior_changed", False)),
                "position_sizing_changed": bool(full_lifecycle.get("position_sizing_changed", False)),
                "thresholds_changed": bool(full_lifecycle.get("thresholds_changed", False)),
            },
            "long_term_memory_symbol_retrieval_diagnostics": {
                "storage_health_score": long_memory.get("storage_health_score"),
                "memory_pressure_score": long_memory.get("memory_pressure_score"),
                "cleanup_status": long_memory.get("cleanup_status"),
                "estimated_days_until_storage_pressure": long_memory.get("estimated_days_until_storage_pressure"),
                "symbol_profiles_tracked": long_memory.get("symbol_profiles_tracked"),
                "strongest_symbol_profile": long_memory.get("strongest_symbol_profile"),
                "weakest_symbol_profile": long_memory.get("weakest_symbol_profile"),
                "best_behavioral_edge_symbol": long_memory.get("best_behavioral_edge_symbol"),
                "highest_giveback_symbol": long_memory.get("highest_giveback_symbol"),
                "most_reliable_symbol": long_memory.get("most_reliable_symbol"),
                "symbol_memory_quality_score": long_memory.get("symbol_memory_quality_score"),
                "indexed_records": long_memory.get("indexed_records"),
                "retrieval_latency_ms": long_memory.get("retrieval_latency_ms"),
                "retrieval_health_score": long_memory.get("retrieval_health_score"),
                "strongest_index": long_memory.get("strongest_index"),
                "weakest_index": long_memory.get("weakest_index"),
                "recent_lookup_success_rate": long_memory.get("recent_lookup_success_rate"),
                "full_scan_avoided_count": long_memory.get("full_scan_avoided_count"),
                "dashboard_scan_rows": long_memory.get("dashboard_scan_rows"),
                "cache_freshness": long_memory.get("cache_freshness"),
                "cleanup_action_taken": long_memory.get("cleanup_action_taken"),
                "raw_archive_scan_during_render": bool(long_memory.get("raw_archive_scan_during_render", False)),
                "api_calls_used": long_memory.get("api_calls_used"),
                "provider_calls_used": long_memory.get("provider_calls_used"),
                "llm_calls_used": long_memory.get("llm_calls_used"),
                "shadow_recommendation": long_memory.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(long_memory.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(long_memory.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(long_memory.get("paper_execution_behavior_changed", False)),
                "position_sizing_changed": bool(long_memory.get("position_sizing_changed", False)),
                "thresholds_changed": bool(long_memory.get("thresholds_changed", False)),
            },
            "virtual_paper_convergence_symbol_attribution_diagnostics": {
                "tracked_trades": virtual_convergence.get("tracked_trades"),
                "symbol_profiles_reviewed": virtual_convergence.get("symbol_profiles_reviewed"),
                "average_actual_return": virtual_convergence.get("average_actual_return"),
                "average_virtual_return": virtual_convergence.get("average_virtual_return"),
                "average_convergence_gap": virtual_convergence.get("average_convergence_gap"),
                "convergence_quality_score": virtual_convergence.get("convergence_quality_score"),
                "virtual_outperformance_rate": virtual_convergence.get("virtual_outperformance_rate"),
                "dominant_gap_cause": virtual_convergence.get("dominant_gap_cause"),
                "highest_value_gap_to_reduce": virtual_convergence.get("highest_value_gap_to_reduce"),
                "largest_convergence_gap_symbol": virtual_convergence.get("largest_convergence_gap_symbol"),
                "strongest_symbol_behavior_edge": virtual_convergence.get("strongest_symbol_behavior_edge"),
                "weakest_symbol_behavior_edge": virtual_convergence.get("weakest_symbol_behavior_edge"),
                "highest_gap_symbol": virtual_convergence.get("highest_gap_symbol"),
                "most_reliable_symbol": virtual_convergence.get("most_reliable_symbol"),
                "best_symbol_horizon_pair": virtual_convergence.get("best_symbol_horizon_pair"),
                "worst_symbol_horizon_pair": virtual_convergence.get("worst_symbol_horizon_pair"),
                "best_exit_style_by_symbol": dict(virtual_convergence.get("best_exit_style_by_symbol") or {}),
                "symbols_needing_profit_lock": list(virtual_convergence.get("symbols_needing_profit_lock") or [])[:8],
                "symbols_needing_continuation_exit": list(virtual_convergence.get("symbols_needing_continuation_exit") or [])[:8],
                "best_regime_by_symbol": dict(virtual_convergence.get("best_regime_by_symbol") or {}),
                "best_catalyst_by_symbol": dict(virtual_convergence.get("best_catalyst_by_symbol") or {}),
                "top_missed_profit_driver": virtual_convergence.get("top_missed_profit_driver"),
                "highest_value_profitability_lever": virtual_convergence.get("highest_value_profitability_lever"),
                "strongest_virtual_policy": virtual_convergence.get("strongest_virtual_policy"),
                "closest_policy_to_future_review": virtual_convergence.get("closest_policy_to_future_review"),
                "policy_improvement_confidence": virtual_convergence.get("policy_improvement_confidence"),
                "api_calls_used": virtual_convergence.get("api_calls_used"),
                "provider_calls_used": virtual_convergence.get("provider_calls_used"),
                "llm_calls_used": virtual_convergence.get("llm_calls_used"),
                "shadow_recommendation": virtual_convergence.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(virtual_convergence.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(virtual_convergence.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(virtual_convergence.get("paper_execution_behavior_changed", False)),
                "position_sizing_changed": bool(virtual_convergence.get("position_sizing_changed", False)),
                "thresholds_changed": bool(virtual_convergence.get("thresholds_changed", False)),
            },
            "accelerated_learning_symbol_intelligence_diagnostics": {
                "historical_records_reviewed": accelerated_symbol.get("historical_records_reviewed"),
                "accelerated_learning_events": accelerated_symbol.get("accelerated_learning_events"),
                "replay_acceleration_score": accelerated_symbol.get("replay_acceleration_score"),
                "average_convergence_gap": accelerated_symbol.get("average_convergence_gap"),
                "dominant_gap_cause": accelerated_symbol.get("dominant_gap_cause"),
                "symbol_profiles_tracked": accelerated_symbol.get("symbol_profiles_tracked"),
                "strongest_symbol_profile": accelerated_symbol.get("strongest_symbol_profile"),
                "highest_giveback_symbol": accelerated_symbol.get("highest_giveback_symbol"),
                "most_reliable_symbol": accelerated_symbol.get("most_reliable_symbol"),
                "best_horizon_by_symbol": dict(accelerated_symbol.get("best_horizon_by_symbol") or {}),
                "best_exit_style_by_symbol": dict(accelerated_symbol.get("best_exit_style_by_symbol") or {}),
                "best_catalyst_by_symbol": dict(accelerated_symbol.get("best_catalyst_by_symbol") or {}),
                "best_regime_by_symbol": dict(accelerated_symbol.get("best_regime_by_symbol") or {}),
                "strongest_symbol_cluster": accelerated_symbol.get("strongest_symbol_cluster"),
                "strongest_cross_symbol_pattern": accelerated_symbol.get("strongest_cross_symbol_pattern"),
                "top_missed_profit_driver": accelerated_symbol.get("top_missed_profit_driver"),
                "highest_value_profitability_lever": accelerated_symbol.get("highest_value_profitability_lever"),
                "highest_roi_learning_area": accelerated_symbol.get("highest_roi_learning_area"),
                "symbols_with_behavior_drift": list(accelerated_symbol.get("symbols_with_behavior_drift") or [])[:8],
                "highest_drift_symbol": accelerated_symbol.get("highest_drift_symbol"),
                "most_stable_symbol": accelerated_symbol.get("most_stable_symbol"),
                "regime_override_count": accelerated_symbol.get("regime_override_count"),
                "compressed_lessons": accelerated_symbol.get("compressed_lessons"),
                "indexed_learning_records": accelerated_symbol.get("indexed_learning_records"),
                "retrieval_latency_ms": accelerated_symbol.get("retrieval_latency_ms"),
                "strongest_sector_behavior": accelerated_symbol.get("strongest_sector_behavior"),
                "strongest_industry_behavior": accelerated_symbol.get("strongest_industry_behavior"),
                "strongest_theme_behavior": accelerated_symbol.get("strongest_theme_behavior"),
                "strongest_peer_group_behavior": accelerated_symbol.get("strongest_peer_group_behavior"),
                "best_peer_group_horizon": dict(accelerated_symbol.get("best_peer_group_horizon") or {}),
                "best_peer_group_exit_style": dict(accelerated_symbol.get("best_peer_group_exit_style") or {}),
                "highest_giveback_peer_group": accelerated_symbol.get("highest_giveback_peer_group"),
                "transferable_learning_confidence": accelerated_symbol.get("transferable_learning_confidence"),
                "peer_group_learning_score": accelerated_symbol.get("peer_group_learning_score"),
                "sector_drift_score": accelerated_symbol.get("sector_drift_score"),
                "industry_drift_score": accelerated_symbol.get("industry_drift_score"),
                "theme_drift_score": accelerated_symbol.get("theme_drift_score"),
                "peer_group_drift_score": accelerated_symbol.get("peer_group_drift_score"),
                "api_calls_used": accelerated_symbol.get("api_calls_used"),
                "provider_calls_used": accelerated_symbol.get("provider_calls_used"),
                "llm_calls_used": accelerated_symbol.get("llm_calls_used"),
                "dashboard_scan_rows": accelerated_symbol.get("dashboard_scan_rows"),
                "raw_history_scanned": bool(accelerated_symbol.get("raw_history_scanned", False)),
                "raw_archive_scanned": bool(accelerated_symbol.get("raw_archive_scanned", False)),
                "shadow_recommendation": accelerated_symbol.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(accelerated_symbol.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(accelerated_symbol.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(accelerated_symbol.get("paper_execution_behavior_changed", False)),
                "position_sizing_changed": bool(accelerated_symbol.get("position_sizing_changed", False)),
                "thresholds_changed": bool(accelerated_symbol.get("thresholds_changed", False)),
            },
            "realistic_shadow_evidence_learning_lab_diagnostics": {
                "shadow_opportunities_tracked": shadow_lab.get("shadow_opportunities_tracked"),
                "eligible_shadow_trades": shadow_lab.get("eligible_shadow_trades"),
                "near_miss_shadow_trades": shadow_lab.get("near_miss_shadow_trades"),
                "discarded_unrealistic_trades": shadow_lab.get("discarded_unrealistic_trades"),
                "virtual_paths_created": shadow_lab.get("virtual_paths_created"),
                "shadow_learning_events": shadow_lab.get("shadow_learning_events"),
                "completed_shadow_lifecycles": shadow_lab.get("completed_shadow_lifecycles"),
                "average_shadow_realism_score": shadow_lab.get("average_shadow_realism_score"),
                "high_realism_shadow_trades": shadow_lab.get("high_realism_shadow_trades"),
                "paper_engine_mirror_score": shadow_lab.get("paper_engine_mirror_score"),
                "shadow_portfolio_realism_score": shadow_lab.get("shadow_portfolio_realism_score"),
                "execution_realism_score": shadow_lab.get("execution_realism_score"),
                "evidence_quality_score": shadow_lab.get("evidence_quality_score"),
                "high_value_lessons": shadow_lab.get("high_value_lessons"),
                "compressed_lessons": shadow_lab.get("compressed_lessons"),
                "discarded_noise_count": shadow_lab.get("discarded_noise_count"),
                "consensus_lesson_count": shadow_lab.get("consensus_lesson_count"),
                "strongest_consensus_lesson": shadow_lab.get("strongest_consensus_lesson"),
                "active_weakness_focus": shadow_lab.get("active_weakness_focus"),
                "top_failure_pattern": shadow_lab.get("top_failure_pattern"),
                "winning_policy": shadow_lab.get("winning_policy"),
                "policy_tournament_score": shadow_lab.get("policy_tournament_score"),
                "policy_confidence": shadow_lab.get("policy_confidence"),
                "storage_pressure_score": shadow_lab.get("storage_pressure_score"),
                "memory_pressure_score": shadow_lab.get("memory_pressure_score"),
                "fmp_status": shadow_lab.get("fmp_status"),
                "fmp_smart_budget_enabled": bool(shadow_lab.get("fmp_smart_budget_enabled", False)),
                "fmp_rest_conserve_mode": bool(shadow_lab.get("fmp_rest_conserve_mode", False)),
                "fmp_refresh_allowed_now": bool(shadow_lab.get("fmp_refresh_allowed_now", False)),
                "fmp_refresh_block_reason": shadow_lab.get("fmp_refresh_block_reason"),
                "fmp_zero_usage_reason": shadow_lab.get("fmp_zero_usage_reason"),
                "fmp_last_successful_call": shadow_lab.get("fmp_last_successful_call"),
                "fmp_last_fresh_data_timestamp": shadow_lab.get("fmp_last_fresh_data_timestamp"),
                "fmp_cache_hit_rate": shadow_lab.get("fmp_cache_hit_rate"),
                "fmp_calls_used_today": shadow_lab.get("fmp_calls_used_today"),
                "fmp_bandwidth_used_today": shadow_lab.get("fmp_bandwidth_used_today"),
                "fmp_daily_call_limit": shadow_lab.get("fmp_daily_call_limit"),
                "fmp_daily_bandwidth_limit": shadow_lab.get("fmp_daily_bandwidth_limit"),
                "fmp_remaining_calls_estimate": shadow_lab.get("fmp_remaining_calls_estimate"),
                "fmp_remaining_bandwidth_estimate": shadow_lab.get("fmp_remaining_bandwidth_estimate"),
                "fmp_budget_status": shadow_lab.get("fmp_budget_status"),
                "bandwidth_pressure_score": shadow_lab.get("bandwidth_pressure_score"),
                "data_freshness_score": shadow_lab.get("data_freshness_score"),
                "live_data_confidence_score": shadow_lab.get("live_data_confidence_score"),
                "provider_warning": shadow_lab.get("provider_warning"),
                "recommended_safe_fix": shadow_lab.get("recommended_safe_fix"),
                "safe_fix_applied": bool(shadow_lab.get("safe_fix_applied", False)),
                "paper_orders_placed": bool(shadow_lab.get("paper_orders_placed", False)),
                "alpaca_orders_placed": bool(shadow_lab.get("alpaca_orders_placed", False)),
                "api_calls_used": shadow_lab.get("api_calls_used"),
                "provider_calls_used": shadow_lab.get("provider_calls_used"),
                "llm_calls_used": shadow_lab.get("llm_calls_used"),
                "dashboard_scan_rows": shadow_lab.get("dashboard_scan_rows"),
                "raw_history_scanned": bool(shadow_lab.get("raw_history_scanned", False)),
                "raw_archive_scanned": bool(shadow_lab.get("raw_archive_scanned", False)),
                "shadow_recommendation": shadow_lab.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(shadow_lab.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(shadow_lab.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(shadow_lab.get("paper_execution_behavior_changed", False)),
                "position_sizing_changed": bool(shadow_lab.get("position_sizing_changed", False)),
                "thresholds_changed": bool(shadow_lab.get("thresholds_changed", False)),
            },
            "multi_horizon_intelligence_adaptive_lifecycle_diagnostics": {
                "suite_status": multi_horizon_intelligence.get("suite_status"),
                "horizons_tested": list(multi_horizon_intelligence.get("horizons_tested") or [])[:16],
                "missing_horizons": dict(multi_horizon_intelligence.get("missing_horizons") or {}),
                "dominant_paper_horizon": multi_horizon_intelligence.get("dominant_paper_horizon"),
                "dominant_shadow_horizon": multi_horizon_intelligence.get("dominant_shadow_horizon"),
                "best_horizon": multi_horizon_intelligence.get("best_horizon"),
                "weakest_horizon": multi_horizon_intelligence.get("weakest_horizon"),
                "horizon_mismatch_risk_score": multi_horizon_intelligence.get("horizon_mismatch_risk_score"),
                "best_symbol_horizon": multi_horizon_intelligence.get("best_symbol_horizon"),
                "worst_symbol_horizon": multi_horizon_intelligence.get("worst_symbol_horizon"),
                "strongest_setup_horizon": multi_horizon_intelligence.get("strongest_setup_horizon"),
                "strongest_catalyst_horizon": multi_horizon_intelligence.get("strongest_catalyst_horizon"),
                "strongest_peer_group_pattern": multi_horizon_intelligence.get("strongest_peer_group_pattern"),
                "estimated_profit_lost_to_horizon_mismatch": multi_horizon_intelligence.get("estimated_profit_lost_to_horizon_mismatch"),
                "learned_exits_applied": bool(multi_horizon_intelligence.get("learned_exits_applied", False)),
                "natural_exit_preserved": bool(multi_horizon_intelligence.get("natural_exit_preserved", True)),
                "forced_exits_enabled": bool(multi_horizon_intelligence.get("forced_exits_enabled", False)),
                "next_recommended_test": multi_horizon_intelligence.get("next_recommended_test"),
                "api_calls_used": multi_horizon_intelligence.get("api_calls_used"),
                "provider_calls_used": multi_horizon_intelligence.get("provider_calls_used"),
                "llm_calls_used": multi_horizon_intelligence.get("llm_calls_used"),
                "shadow_recommendation": multi_horizon_intelligence.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(multi_horizon_intelligence.get("behavior_safe_to_apply", False)),
            },
            "paper_throughput_exit_validation_catalyst_diagnostics": {
                "paper_throughput_status": paper_throughput_exit_catalyst.get("paper_throughput_status"),
                "reviewed_today": paper_throughput_exit_catalyst.get("reviewed_today"),
                "eligible_today": paper_throughput_exit_catalyst.get("eligible_today"),
                "submitted_today": paper_throughput_exit_catalyst.get("submitted_today"),
                "blocked_today": paper_throughput_exit_catalyst.get("blocked_today"),
                "suppression_rate": paper_throughput_exit_catalyst.get("suppression_rate"),
                "top_blocker": paper_throughput_exit_catalyst.get("top_blocker"),
                "duplicate_blocks": paper_throughput_exit_catalyst.get("duplicate_blocks"),
                "confirmation_blocks": paper_throughput_exit_catalyst.get("confirmation_blocks"),
                "stale_row_blocks": paper_throughput_exit_catalyst.get("stale_row_blocks"),
                "broker_confirmed_positions": paper_throughput_exit_catalyst.get("broker_confirmed_positions"),
                "internal_active_rows": paper_throughput_exit_catalyst.get("internal_active_rows"),
                "stale_internal_rows": paper_throughput_exit_catalyst.get("stale_internal_rows"),
                "true_capacity_available": paper_throughput_exit_catalyst.get("true_capacity_available"),
                "safe_capacity_available": paper_throughput_exit_catalyst.get("safe_capacity_available"),
                "missed_evidence_estimate": paper_throughput_exit_catalyst.get("missed_evidence_estimate"),
                "recommended_safe_throughput_action": paper_throughput_exit_catalyst.get("recommended_safe_throughput_action"),
                "learned_exit_outperforms_current": bool(paper_throughput_exit_catalyst.get("learned_exit_outperforms_current", False)),
                "best_shadow_exit_policy": paper_throughput_exit_catalyst.get("best_shadow_exit_policy"),
                "current_policy_profit_factor": paper_throughput_exit_catalyst.get("current_policy_profit_factor"),
                "best_policy_profit_factor": paper_throughput_exit_catalyst.get("best_policy_profit_factor"),
                "improvement_delta": paper_throughput_exit_catalyst.get("improvement_delta"),
                "readiness_status": paper_throughput_exit_catalyst.get("readiness_status"),
                "learned_exit_validation_bucket_enabled": bool(paper_throughput_exit_catalyst.get("learned_exit_validation_bucket_enabled", False)),
                "catalyst_coverage": paper_throughput_exit_catalyst.get("catalyst_coverage"),
                "unknown_catalyst_rate": paper_throughput_exit_catalyst.get("unknown_catalyst_rate"),
                "dominant_catalyst": paper_throughput_exit_catalyst.get("dominant_catalyst"),
                "best_horizon_by_catalyst": paper_throughput_exit_catalyst.get("best_horizon_by_catalyst"),
                "recommended_next_action": paper_throughput_exit_catalyst.get("recommended_next_action"),
                "api_calls_used": paper_throughput_exit_catalyst.get("api_calls_used"),
                "provider_calls_used": paper_throughput_exit_catalyst.get("provider_calls_used"),
                "llm_calls_used": paper_throughput_exit_catalyst.get("llm_calls_used"),
                "behavior_safe_to_apply": bool(paper_throughput_exit_catalyst.get("behavior_safe_to_apply", False)),
            },
            "multi_horizon_paper_capacity_exit_validation_diagnostics": {
                "total_capacity": multi_horizon_capacity_exit.get("total_capacity"),
                "total_used": multi_horizon_capacity_exit.get("total_used"),
                "total_available": multi_horizon_capacity_exit.get("total_available"),
                "swing_capacity": multi_horizon_capacity_exit.get("swing_capacity"),
                "swing_used": multi_horizon_capacity_exit.get("swing_used"),
                "swing_available": multi_horizon_capacity_exit.get("swing_available"),
                "day_capacity": multi_horizon_capacity_exit.get("day_capacity"),
                "day_used": multi_horizon_capacity_exit.get("day_used"),
                "day_available": multi_horizon_capacity_exit.get("day_available"),
                "scalp_capacity": multi_horizon_capacity_exit.get("scalp_capacity"),
                "scalp_used": multi_horizon_capacity_exit.get("scalp_used"),
                "scalp_available": multi_horizon_capacity_exit.get("scalp_available"),
                "unknown_horizon_positions": multi_horizon_capacity_exit.get("unknown_horizon_positions"),
                "broker_confirmed_positions": multi_horizon_capacity_exit.get("broker_confirmed_positions"),
                "stale_internal_rows": multi_horizon_capacity_exit.get("stale_internal_rows"),
                "top_capacity_blocker": multi_horizon_capacity_exit.get("top_capacity_blocker"),
                "candidates_blocked_by_horizon_capacity": multi_horizon_capacity_exit.get("candidates_blocked_by_horizon_capacity"),
                "missed_evidence_due_to_capacity": multi_horizon_capacity_exit.get("missed_evidence_due_to_capacity"),
                "learned_exit_bucket_enabled": bool(multi_horizon_capacity_exit.get("learned_exit_bucket_enabled", False)),
                "learned_exits_used_today": multi_horizon_capacity_exit.get("learned_exits_used_today"),
                "baseline_vs_learned_status": multi_horizon_capacity_exit.get("baseline_vs_learned_status"),
                "best_learned_exit_policy": multi_horizon_capacity_exit.get("best_learned_exit_policy"),
                "profit_factor_delta": multi_horizon_capacity_exit.get("profit_factor_delta"),
                "rollback_reason": multi_horizon_capacity_exit.get("rollback_reason"),
                "safety_status": multi_horizon_capacity_exit.get("safety_status"),
                "next_recommended_action": multi_horizon_capacity_exit.get("next_recommended_action"),
                "api_calls_used": multi_horizon_capacity_exit.get("api_calls_used"),
                "provider_calls_used": multi_horizon_capacity_exit.get("provider_calls_used"),
                "llm_calls_used": multi_horizon_capacity_exit.get("llm_calls_used"),
                "behavior_safe_to_apply": bool(multi_horizon_capacity_exit.get("behavior_safe_to_apply", False)),
            },
            "adaptive_learning_prioritization_resource_allocation_diagnostics": {
                "top_weakness": learning_allocator.get("top_weakness"),
                "secondary_weakness": learning_allocator.get("secondary_weakness"),
                "weakness_rankings": list(learning_allocator.get("weakness_rankings") or [])[:10],
                "weakness_confidence": learning_allocator.get("weakness_confidence"),
                "weakness_is_real_vs_noise": learning_allocator.get("weakness_is_real_vs_noise"),
                "highest_value_learning_focus": learning_allocator.get("highest_value_learning_focus"),
                "expected_improvement_score": learning_allocator.get("expected_improvement_score"),
                "learning_roi_score": learning_allocator.get("learning_roi_score"),
                "weakness_focus_allocation": learning_allocator.get("weakness_focus_allocation"),
                "balanced_learning_allocation": learning_allocator.get("balanced_learning_allocation"),
                "strength_validation_allocation": learning_allocator.get("strength_validation_allocation"),
                "system_health_allocation": learning_allocator.get("system_health_allocation"),
                "active_focus_distribution": learning_allocator.get("active_focus_distribution"),
                "recommended_worker_focus": learning_allocator.get("recommended_worker_focus"),
                "recommended_replay_focus": learning_allocator.get("recommended_replay_focus"),
                "memory_focus": learning_allocator.get("memory_focus"),
                "emerging_weakness": learning_allocator.get("emerging_weakness"),
                "resolved_weakness": learning_allocator.get("resolved_weakness"),
                "governance_status": learning_allocator.get("governance_status"),
                "allocation_safe": bool(learning_allocator.get("allocation_safe", False)),
                "blocked_allocation_reason": learning_allocator.get("blocked_allocation_reason"),
                "policy_readiness_status": learning_allocator.get("policy_readiness_status"),
                "api_calls_used": learning_allocator.get("api_calls_used"),
                "provider_calls_used": learning_allocator.get("provider_calls_used"),
                "llm_calls_used": learning_allocator.get("llm_calls_used"),
                "shadow_recommendation": learning_allocator.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(learning_allocator.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(learning_allocator.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(learning_allocator.get("paper_execution_behavior_changed", False)),
                "position_sizing_changed": bool(learning_allocator.get("position_sizing_changed", False)),
                "thresholds_changed": bool(learning_allocator.get("thresholds_changed", False)),
                "portfolio_allocation_changed": bool(learning_allocator.get("portfolio_allocation_changed", False)),
            },
            "autonomous_intelligence_validation_governance_diagnostics": {
                "evidence_count": autonomous_governance.get("evidence_count"),
                "truth_validation_score": autonomous_governance.get("truth_validation_score"),
                "lesson_reliability_score": autonomous_governance.get("lesson_reliability_score"),
                "strongest_validated_lesson": autonomous_governance.get("strongest_validated_lesson"),
                "weakest_validated_lesson": autonomous_governance.get("weakest_validated_lesson"),
                "truth_validation_status": autonomous_governance.get("truth_validation_status"),
                "top_root_cause": autonomous_governance.get("top_root_cause"),
                "highest_value_hypothesis": autonomous_governance.get("highest_value_hypothesis"),
                "recommended_virtual_test": autonomous_governance.get("recommended_virtual_test"),
                "self_healing_status": autonomous_governance.get("self_healing_status"),
                "autonomous_repair_readiness": autonomous_governance.get("autonomous_repair_readiness"),
                "governance_score": autonomous_governance.get("governance_score"),
                "warning_level": autonomous_governance.get("warning_level"),
                "primary_risk": autonomous_governance.get("primary_risk"),
                "secondary_risk": autonomous_governance.get("secondary_risk"),
                "policy_readiness_score": autonomous_governance.get("policy_readiness_score"),
                "closest_policy_to_readiness": autonomous_governance.get("closest_policy_to_readiness"),
                "readiness_blocker": autonomous_governance.get("readiness_blocker"),
                "trading_safety_status": autonomous_governance.get("trading_safety_status"),
                "learning_safety_status": autonomous_governance.get("learning_safety_status"),
                "storage_safety_status": autonomous_governance.get("storage_safety_status"),
                "performance_safety_status": autonomous_governance.get("performance_safety_status"),
                "api_safety_status": autonomous_governance.get("api_safety_status"),
                "infrastructure_safety_status": autonomous_governance.get("infrastructure_safety_status"),
                "knowledge_safety_status": autonomous_governance.get("knowledge_safety_status"),
                "api_calls_used": autonomous_governance.get("api_calls_used"),
                "provider_calls_used": autonomous_governance.get("provider_calls_used"),
                "llm_calls_used": autonomous_governance.get("llm_calls_used"),
                "shadow_recommendation": autonomous_governance.get("shadow_recommendation"),
                "behavior_safe_to_apply": bool(autonomous_governance.get("behavior_safe_to_apply", False)),
                "ranking_behavior_changed": bool(autonomous_governance.get("ranking_behavior_changed", False)),
                "paper_execution_behavior_changed": bool(autonomous_governance.get("paper_execution_behavior_changed", False)),
                "position_sizing_changed": bool(autonomous_governance.get("position_sizing_changed", False)),
                "thresholds_changed": bool(autonomous_governance.get("thresholds_changed", False)),
                "portfolio_allocation_changed": bool(autonomous_governance.get("portfolio_allocation_changed", False)),
            },
            "paper_path_gating_diagnostics": paper_path_diag,
            "horizon_coverage_summary": horizon_coverage_diag,
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
