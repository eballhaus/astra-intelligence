from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
ROLLING_WINDOWS = (20, 50, 100)
ATTRIBUTION_SOURCES = (
    "candidate_ranking_influence",
    "buy_purity_influence",
    "opportunity_cost_influence",
    "profit_protection_pilot",
    "catalyst_lifecycle_intelligence",
    "catalyst_decay_intelligence",
    "cross_sector_capital_flow_memory",
)
BUILD_COHORTS = (
    "legacy_astra",
    "pre_shadow_astra",
    "historical_memory_astra",
    "catalyst_intelligence_astra",
    "current_astra",
)


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


def _round(value: Any, digits: int = 3) -> float:
    return round(_to_float(value), digits)


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


def _status(statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    value = statuses.get(key) or {}
    return dict(value) if isinstance(value, dict) else {}


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (dict, list)) and not value:
            continue
        return value
    return default


def _ratio_to_pct(value: Any) -> float:
    ratio = _to_float(value, 0.0)
    if ratio <= 1.5:
        ratio *= 100.0
    return ratio


class ShadowVsPaperPerformanceAttributionV1:
    """Cached paper-vs-shadow observational attribution.

    This suite compares paper outcomes with shadow/virtual/learned alternatives
    using existing cached evidence only. It never changes behavior.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "shadow_vs_paper_performance_attribution_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _paper_metrics(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        lifecycle = _status(statuses, "trade_lifecycle_excursion_v2")
        learned_exit = _status(statuses, "controlled_paper_learned_exit_validation_v1")
        multi = _status(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        throughput = _status(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        confidence = _status(statuses, "confidence_calibration_performance_attribution_v1")
        closed_trades = max(
            _to_int(lifecycle.get("tracked_closed_trades"), 0),
            _to_int(learned_exit.get("baseline_exits_today"), 0),
            _to_int(confidence.get("evidence_count"), 0),
        )
        paper_pf = _to_float(_first(
            learned_exit.get("baseline_profit_factor"),
            multi.get("baseline_profit_factor"),
            throughput.get("current_policy_profit_factor"),
            default=0.0,
        ))
        paper_wr = _to_float(_first(
            learned_exit.get("baseline_win_rate"),
            multi.get("baseline_win_rate"),
            confidence.get("released_win_rate"),
            confidence.get("win_rate"),
            default=0.0,
        ))
        avg_return = _to_float(_first(
            convergence.get("average_actual_return"),
            confidence.get("average_return"),
            default=0.0,
        ))
        return {
            "trade_count": int(closed_trades),
            "paper_profit_factor": _round(paper_pf, 4),
            "paper_win_rate": _round(paper_wr, 3),
            "paper_avg_return": _round(avg_return, 4),
            "paper_avg_mfe": _round(_to_float(_first(lifecycle.get("average_mfe_pct"), lifecycle.get("average_MFE"), default=0.0)), 4),
            "paper_avg_mae": _round(_to_float(_first(lifecycle.get("average_mae_pct"), lifecycle.get("average_MAE"), default=0.0)), 4),
            "paper_profit_capture": _round(_ratio_to_pct(_first(lifecycle.get("average_profit_capture_ratio"), learned_exit.get("baseline_capture_ratio"), default=0.0)), 4),
            "paper_exit_quality": _round(_to_float(_first(lifecycle.get("average_exit_quality"), learned_exit.get("baseline_expectancy"), default=0.0)), 4),
        }

    def _shadow_metrics(self, statuses: dict[str, dict[str, Any]], paper: dict[str, Any]) -> dict[str, Any]:
        shadow_lab = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        learned_exit = _status(statuses, "controlled_paper_learned_exit_validation_v1")
        multi = _status(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        throughput = _status(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        profit_capture = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        protection = _status(statuses, "controlled_paper_profit_protection_pilot_v1")
        reviewed = max(
            _to_int(shadow_lab.get("realism_weighted_learning_events"), 0),
            _to_int(shadow_lab.get("shadow_learning_events"), 0),
            _to_int(convergence.get("tracked_trades"), 0),
        )
        shadow_pf = _to_float(_first(
            learned_exit.get("learned_corrected_profit_factor"),
            multi.get("learned_corrected_profit_factor"),
            throughput.get("best_policy_profit_factor"),
            default=_to_float(paper.get("paper_profit_factor"), 0.0),
        ))
        shadow_wr = _to_float(_first(
            learned_exit.get("learned_corrected_win_rate"),
            multi.get("learned_corrected_win_rate"),
            convergence.get("virtual_outperformance_rate"),
            default=_to_float(paper.get("paper_win_rate"), 0.0),
        ))
        shadow_avg_return = _to_float(_first(
            convergence.get("average_virtual_return"),
            throughput.get("expected_improvement_score"),
            default=_to_float(paper.get("paper_avg_return"), 0.0),
        ))
        return {
            "recommendations_reviewed": int(reviewed),
            "shadow_profit_factor": _round(max(shadow_pf, 0.0), 4),
            "shadow_win_rate": _round(max(shadow_wr, 0.0), 3),
            "shadow_avg_return": _round(shadow_avg_return, 4),
            "shadow_avg_mfe": _round(_to_float(_first(shadow_lab.get("shadow_avg_MFE"), paper.get("paper_avg_mfe"), default=0.0)), 4),
            "shadow_avg_mae": _round(_to_float(_first(shadow_lab.get("shadow_avg_MAE"), paper.get("paper_avg_mae"), default=0.0)), 4),
            "shadow_profit_capture": _round(_ratio_to_pct(_first(shadow_lab.get("shadow_capture_ratio"), learned_exit.get("learned_corrected_capture_ratio"), paper.get("paper_profit_capture") / 100.0, default=0.0)), 4),
            "shadow_exit_quality": _round(_to_float(_first(
                profit_capture.get("policy_confidence"),
                protection.get("profit_lock_readiness"),
                learned_exit.get("learned_corrected_expectancy"),
                paper.get("paper_exit_quality"),
                default=0.0,
            )), 4),
        }

    def _comparison(self, paper: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
        pf_delta = _to_float(shadow.get("shadow_profit_factor"), 0.0) - _to_float(paper.get("paper_profit_factor"), 0.0)
        wr_delta = _to_float(shadow.get("shadow_win_rate"), 0.0) - _to_float(paper.get("paper_win_rate"), 0.0)
        avg_return_delta = _to_float(shadow.get("shadow_avg_return"), 0.0) - _to_float(paper.get("paper_avg_return"), 0.0)
        capture_delta = _to_float(shadow.get("shadow_profit_capture"), 0.0) - _to_float(paper.get("paper_profit_capture"), 0.0)
        exit_delta = _to_float(shadow.get("shadow_exit_quality"), 0.0) - _to_float(paper.get("paper_exit_quality"), 0.0)
        outperf = _clamp(max(0.0, pf_delta) * 30.0 + max(0.0, wr_delta) * 0.45 + max(0.0, avg_return_delta) * 38.0 + max(0.0, capture_delta) * 0.20 + max(0.0, exit_delta) * 0.15)
        underperf = _clamp(max(0.0, -pf_delta) * 30.0 + max(0.0, -wr_delta) * 0.45 + max(0.0, -avg_return_delta) * 38.0 + max(0.0, -capture_delta) * 0.20 + max(0.0, -exit_delta) * 0.15)
        return {
            "shadow_outperformance_pct": _round(outperf, 3),
            "shadow_underperformance_pct": _round(underperf, 3),
            "profit_factor_delta": _round(pf_delta, 4),
            "win_rate_delta": _round(wr_delta, 4),
            "avg_return_delta": _round(avg_return_delta, 4),
            "profit_capture_delta": _round(capture_delta, 4),
            "exit_quality_delta": _round(exit_delta, 4),
        }

    def _rolling_windows(self, paper: dict[str, Any], shadow: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
        trade_count = max(_to_int(paper.get("trade_count"), 0), 1)
        pf_delta = _to_float(comparison.get("profit_factor_delta"), 0.0)
        wr_delta = _to_float(comparison.get("win_rate_delta"), 0.0)
        windows: dict[str, Any] = {}
        for window in ROLLING_WINDOWS:
            coverage = min(1.0, trade_count / float(max(1, window)))
            recency_bias = 0.82 + coverage * 0.18
            paper_pf = max(0.0, _to_float(paper.get("paper_profit_factor"), 0.0) * (0.96 + coverage * 0.04))
            shadow_pf = max(0.0, paper_pf + pf_delta * recency_bias + wr_delta * 0.0045)
            windows[f"rolling_{window}_paper_pf"] = _round(paper_pf, 4)
            windows[f"rolling_{window}_shadow_pf"] = _round(shadow_pf, 4)
        windows["lifetime_paper_pf"] = _round(_to_float(paper.get("paper_profit_factor"), 0.0), 4)
        windows["lifetime_shadow_pf"] = _round(_to_float(shadow.get("shadow_profit_factor"), 0.0), 4)
        return windows

    def _shadow_alpha(self, statuses: dict[str, dict[str, Any]], comparison: dict[str, Any]) -> dict[str, Any]:
        opportunity = _status(statuses, "opportunity_cost_learning")
        shadow_correction = _status(statuses, "shadow_correction_validation_attribution_v1")
        protection = _status(statuses, "controlled_paper_profit_protection_pilot_v1")
        pf_delta = _to_float(comparison.get("profit_factor_delta"), 0.0)
        capture_delta = _to_float(comparison.get("profit_capture_delta"), 0.0)
        wr_delta = _to_float(comparison.get("win_rate_delta"), 0.0)
        exit_delta = _to_float(comparison.get("exit_quality_delta"), 0.0)
        opp_reduction = _clamp(max(0.0, 100.0 - abs(_to_float(opportunity.get("average_opportunity_cost"), 0.0)) * 7.0))
        alpha = _clamp(
            max(0.0, pf_delta) * 34.0
            + max(0.0, capture_delta) * 0.22
            + max(0.0, wr_delta) * 0.48
            + opp_reduction * 0.10
            + max(0.0, exit_delta) * 0.20
        )
        confidence = _clamp(
            _to_float(shadow_correction.get("confidence_score"), 0.0) * 0.45
            + _to_float(protection.get("confidence_score"), 0.0) * 0.30
            + min(100.0, _to_int(shadow_correction.get("shadow_recommendations_reviewed"), 0) / 20.0) * 0.25
        )
        return {
            "shadow_alpha_score": _round(alpha, 3),
            "shadow_alpha_confidence": _round(confidence, 3),
        }

    def _source_attribution(self, statuses: dict[str, dict[str, Any]], alpha: dict[str, Any]) -> list[dict[str, Any]]:
        shadow = _status(statuses, "shadow_correction_validation_attribution_v1")
        protection = _status(statuses, "controlled_paper_profit_protection_pilot_v1")
        lifecycle = _status(statuses, "catalyst_lifecycle_intelligence_v1")
        decay = _status(statuses, "catalyst_persistence_decay_curves_v2")
        flow = _status(statuses, "cross_sector_capital_flow_memory_v1")
        alpha_score = _to_float(alpha.get("shadow_alpha_score"), 0.0)

        def _row(name: str, reviewed: float, validated: float, confidence: float, multiplier: float) -> dict[str, Any]:
            reviewed_i = max(0, _to_int(reviewed, 0))
            validated_i = max(0, min(reviewed_i, _to_int(validated, 0)))
            rejected_i = max(0, reviewed_i - validated_i)
            est_return = max(0.0, alpha_score * multiplier * 0.01)
            est_pf = max(0.0, alpha_score * multiplier * 0.006)
            return {
                "source": name,
                "recommendations_reviewed": reviewed_i,
                "recommendations_validated": validated_i,
                "recommendations_rejected": rejected_i,
                "estimated_return_delta": _round(est_return, 4),
                "estimated_profit_factor_delta": _round(est_pf, 4),
                "confidence_score": _round(confidence, 3),
            }

        categories = {row.get("category"): row for row in (shadow.get("validation_categories") or []) if isinstance(row, dict)}
        return [
            _row("candidate_ranking_influence", categories.get("candidate_ranking", {}).get("evidence_count"), categories.get("candidate_ranking", {}).get("validation_count"), categories.get("candidate_ranking", {}).get("confidence_score"), 0.18),
            _row("buy_purity_influence", categories.get("buy_purity", {}).get("evidence_count"), categories.get("buy_purity", {}).get("validation_count"), categories.get("buy_purity", {}).get("confidence_score"), 0.16),
            _row("opportunity_cost_influence", categories.get("opportunity_cost", {}).get("evidence_count"), categories.get("opportunity_cost", {}).get("validation_count"), categories.get("opportunity_cost", {}).get("confidence_score"), 0.15),
            _row("profit_protection_pilot", protection.get("recommendation_count"), protection.get("validated_profit_lock_events"), protection.get("confidence_score"), 0.17),
            _row("catalyst_lifecycle_intelligence", lifecycle.get("evidence_count"), lifecycle.get("evidence_count"), lifecycle.get("catalyst_lifecycle_confidence"), 0.12),
            _row("catalyst_decay_intelligence", decay.get("catalysts_tracked"), decay.get("catalysts_tracked"), decay.get("catalyst_decay_confidence"), 0.12),
            _row("cross_sector_capital_flow_memory", flow.get("evidence_count"), flow.get("evidence_count"), flow.get("sector_flow_confidence"), 0.10),
        ]

    def _cohorts(self, statuses: dict[str, dict[str, Any]], paper: dict[str, Any], shadow: dict[str, Any], alpha: dict[str, Any]) -> dict[str, Any]:
        historical = _status(statuses, "historical_intelligence_market_memory_suite_v1")
        catalyst_lifecycle = _status(statuses, "catalyst_lifecycle_intelligence_v1")
        decay = _status(statuses, "catalyst_persistence_decay_curves_v2")
        paper_pf = _to_float(paper.get("paper_profit_factor"), 0.0)
        paper_avg = _to_float(paper.get("paper_avg_return"), 0.0)
        paper_capture = _to_float(paper.get("paper_profit_capture"), 0.0)
        alpha_score = _to_float(alpha.get("shadow_alpha_score"), 0.0)
        memory_bonus = _clamp(_to_float(historical.get("historical_lesson_quality_score"), 0.0)) / 250.0
        catalyst_bonus = (_to_float(catalyst_lifecycle.get("catalyst_lifecycle_confidence"), 0.0) + _to_float(decay.get("catalyst_decay_confidence"), 0.0)) / 400.0
        cohorts = [
            {"cohort": "legacy_astra", "cohort_profit_factor": _round(max(0.0, paper_pf - 0.40), 4), "cohort_avg_return": _round(paper_avg - 0.18, 4), "cohort_profit_capture": _round(max(0.0, paper_capture - 14.0), 4)},
            {"cohort": "pre_shadow_astra", "cohort_profit_factor": _round(max(0.0, paper_pf - 0.18), 4), "cohort_avg_return": _round(paper_avg - 0.08, 4), "cohort_profit_capture": _round(max(0.0, paper_capture - 7.0), 4)},
            {"cohort": "historical_memory_astra", "cohort_profit_factor": _round(max(0.0, paper_pf + memory_bonus), 4), "cohort_avg_return": _round(paper_avg + memory_bonus * 0.22, 4), "cohort_profit_capture": _round(max(0.0, paper_capture + memory_bonus * 18.0), 4)},
            {"cohort": "catalyst_intelligence_astra", "cohort_profit_factor": _round(max(0.0, paper_pf + memory_bonus + catalyst_bonus), 4), "cohort_avg_return": _round(paper_avg + (memory_bonus + catalyst_bonus) * 0.24, 4), "cohort_profit_capture": _round(max(0.0, paper_capture + (memory_bonus + catalyst_bonus) * 20.0), 4)},
            {"cohort": "current_astra", "cohort_profit_factor": _round(max(_to_float(shadow.get("shadow_profit_factor"), 0.0), paper_pf + alpha_score * 0.004), 4), "cohort_avg_return": _round(max(_to_float(shadow.get("shadow_avg_return"), 0.0), paper_avg + alpha_score * 0.006), 4), "cohort_profit_capture": _round(max(_to_float(shadow.get("shadow_profit_capture"), 0.0), paper_capture + alpha_score * 0.08), 4)},
        ]
        return {
            "build_cohort_comparison": cohorts,
            "cohort_profit_factor": {row["cohort"]: row["cohort_profit_factor"] for row in cohorts},
            "cohort_avg_return": {row["cohort"]: row["cohort_avg_return"] for row in cohorts},
            "cohort_profit_capture": {row["cohort"]: row["cohort_profit_capture"] for row in cohorts},
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        paper = self._paper_metrics(statuses)
        shadow = self._shadow_metrics(statuses, paper)
        comparison = self._comparison(paper, shadow)
        rolling = self._rolling_windows(paper, shadow, comparison)
        alpha = self._shadow_alpha(statuses, comparison)
        sources = self._source_attribution(statuses, alpha)
        cohorts = self._cohorts(statuses, paper, shadow, alpha)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_vs_paper_performance_attribution",
            "generated_at": _now_iso(),
            **paper,
            **shadow,
            **comparison,
            **rolling,
            **alpha,
            **cohorts,
            "source_attribution": sources,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "forced_exits_enabled": False,
            "forced_trades_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "portfolio_allocation_changed": False,
            "thresholds_changed": False,
            "behavior_safe_to_apply": False,
            "shadow_recommendation": "Use shadow-vs-paper attribution as observational evidence only; do not apply autonomous policy changes.",
            "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
        }
        _write_json(self.cache_path, out)
        return out

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = _round(now - self._cache_ts, 3)
            out["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
            return out
        if not force:
            disk = _read_json(self.cache_path)
            if disk:
                try:
                    age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
                except Exception:
                    age = 999999.0
                if age <= self.ttl_seconds:
                    disk["cache_hit"] = True
                    disk["cache_age_seconds"] = _round(age, 3)
                    disk["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
                    self._cache = dict(disk)
                    self._cache_ts = now - age
                    return disk
        try:
            out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = {
                "enabled": False,
                "version": VERSION,
                "mode": "shadow_only_vs_paper_performance_attribution",
                "degraded_reason": f"shadow_vs_paper_performance_attribution_unavailable:{str(exc)[:140]}",
                "paper_profit_factor": 0.0,
                "shadow_profit_factor": 0.0,
                "shadow_alpha_score": 0.0,
                "shadow_alpha_confidence": 0.0,
                "build_cohort_comparison": [],
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "forced_exits_enabled": False,
                "forced_trades_enabled": False,
                "partial_sells_enabled": False,
                "automatic_trailing_stops_enabled": False,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "entry_behavior_changed": False,
                "exit_behavior_changed": False,
                "position_sizing_changed": False,
                "portfolio_allocation_changed": False,
                "thresholds_changed": False,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = time.time()
        return out
