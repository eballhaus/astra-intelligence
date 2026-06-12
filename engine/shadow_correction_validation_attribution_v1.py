from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
SHADOW_INFLUENCE_CAP_PCT = 3.0
MIN_VALIDATION_EVIDENCE = 25
MIN_CONFIDENCE_SCORE = 60.0

VALIDATION_CATEGORIES = (
    "candidate_ranking",
    "buy_purity",
    "opportunity_cost",
    "symbol_preference",
    "catalyst_confidence",
    "hold_duration",
    "profit_capture",
    "exit_review",
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


class ShadowCorrectionValidationAttributionV1:
    """Validate shadow recommendations and expose capped Phase 1 influence.

    This suite is intentionally advisory. It consumes cached learning summaries,
    performs no provider/broker calls, and does not mutate rankings directly.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "shadow_correction_validation_attribution_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _category_inputs(self, statuses: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
        shadow = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        opportunity = _status(statuses, "opportunity_cost_learning")
        decision = _status(statuses, "decision_optimization_trade_management_suite_v1")
        confidence = _status(statuses, "confidence_calibration_performance_attribution_v1")
        catalyst = _status(statuses, "catalyst_classification_historical_exit_maturation_suite_v1")
        catalyst_decay = _status(statuses, "catalyst_persistence_decay_curves_v2")
        profit_lock = _status(statuses, "profit_lock_profit_capture_maturation_v2")
        profit_capture = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        full = _status(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        issue = _status(statuses, "learning_issue_audit")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        multi_horizon = _status(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")

        buy_diag = dict(issue.get("buy_purity_diagnostics") or {})
        exit_diag = dict(issue.get("exit_quality_diagnostics") or {})
        opportunity_diag = dict(issue.get("opportunity_cost_diagnostics") or {})

        shadow_events = max(
            _to_int(shadow.get("realism_weighted_learning_events"), 0),
            _to_int(shadow.get("shadow_learning_events"), 0),
            _to_int(shadow.get("high_value_lessons"), 0),
        )
        full_evidence = max(_to_int(full.get("opportunities_tracked"), 0), shadow_events)
        opportunity_count = max(
            _to_int(opportunity.get("rejected_candidates_reviewed"), 0),
            _to_int(opportunity.get("opportunity_rows_reviewed"), 0),
            _to_int(decision.get("opportunity_rows_reviewed"), 0),
        )
        profit_count = max(_to_int(profit_capture.get("tracked_trades"), 0), _to_int(profit_lock.get("tracked_trades"), 0))
        catalyst_count = max(_to_int(catalyst.get("classified_catalyst_count"), 0), _to_int(catalyst_decay.get("catalysts_tracked"), 0))
        symbol_count = max(_to_int(accelerated.get("symbol_profiles_tracked"), 0), _to_int(convergence.get("symbol_profiles_reviewed"), 0))

        ranking_quality = _clamp(_first(
            confidence.get("feature_attribution_confidence"),
            decision.get("decision_quality_score"),
            full.get("learning_completeness_score"),
            default=50.0,
        ))
        buy_quality = _clamp(_first(
            buy_diag.get("mapped_buy_purity"),
            confidence.get("confidence_predictive_power"),
            decision.get("buy_purity_score"),
            default=50.0,
        ))
        opp_cost = abs(_to_float(_first(opportunity.get("average_opportunity_cost"), opportunity_diag.get("average_opportunity_cost"), decision.get("highest_opportunity_cost"), default=0.0)))
        opp_quality = _clamp(100.0 - min(100.0, opp_cost * 8.0))
        symbol_quality = _clamp(_first(accelerated.get("symbol_personality_quality_score"), convergence.get("symbol_behavior_confidence"), default=50.0))
        catalyst_quality = _clamp(_first(catalyst.get("catalyst_confidence_score"), catalyst_decay.get("catalyst_memory_quality"), default=50.0))
        hold_quality = _clamp(_first(profit_lock.get("hold_duration_learning_score"), profit_capture.get("hold_duration_quality_score"), multi_horizon.get("horizon_exit_quality_score"), default=50.0))
        profit_quality = _clamp(_first(profit_lock.get("profit_capture_maturity_score"), profit_capture.get("capture_quality_score"), default=50.0))
        exit_quality = _clamp(_first(exit_diag.get("exit_quality_confidence"), profit_capture.get("policy_confidence"), profit_lock.get("profit_lock_readiness_score"), default=50.0))

        return {
            "candidate_ranking": {"evidence": full_evidence, "quality": ranking_quality, "delta": ranking_quality - 50.0},
            "buy_purity": {"evidence": max(full_evidence, _to_int(confidence.get("evidence_count"), 0)), "quality": buy_quality, "delta": buy_quality - 50.0},
            "opportunity_cost": {"evidence": opportunity_count, "quality": opp_quality, "delta": max(-50.0, min(50.0, -opp_cost * 2.0))},
            "symbol_preference": {"evidence": symbol_count, "quality": symbol_quality, "delta": symbol_quality - 50.0},
            "catalyst_confidence": {"evidence": catalyst_count, "quality": catalyst_quality, "delta": catalyst_quality - 50.0},
            "hold_duration": {"evidence": profit_count, "quality": hold_quality, "delta": hold_quality - 50.0},
            "profit_capture": {"evidence": profit_count, "quality": profit_quality, "delta": profit_quality - 50.0},
            "exit_review": {"evidence": profit_count, "quality": exit_quality, "delta": exit_quality - 50.0},
        }

    def _category_rows(self, statuses: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        inputs = self._category_inputs(statuses)
        rows: list[dict[str, Any]] = []
        for category in VALIDATION_CATEGORIES:
            item = inputs.get(category) or {}
            evidence = _to_int(item.get("evidence"), 0)
            quality = _clamp(item.get("quality"), 0.0, 100.0)
            delta = _to_float(item.get("delta"), 0.0)
            validation_count = min(evidence, max(0, int(round(evidence * quality / 100.0))))
            degradation_count = max(0, min(evidence, int(round(evidence * max(0.0, 100.0 - quality) / 160.0))))
            improvement_rate = _round((validation_count / max(1, evidence)) * 100.0, 3)
            degradation_rate = _round((degradation_count / max(1, evidence)) * 100.0, 3)
            expectancy_delta = _round(delta / 12.0, 4)
            profit_factor_delta = _round(delta / 100.0, 4)
            confidence = _clamp(quality * 0.60 + min(100.0, evidence * 2.0) * 0.30 + max(0.0, improvement_rate - degradation_rate) * 0.10)
            readiness = _clamp(confidence * 0.55 + min(100.0, evidence * 2.0) * 0.30 + max(0.0, improvement_rate - degradation_rate) * 0.15)
            validated = bool(evidence >= MIN_VALIDATION_EVIDENCE and confidence >= MIN_CONFIDENCE_SCORE and improvement_rate > degradation_rate)
            if validated:
                status = "validated_phase1_shadow_influence_eligible"
            elif evidence < MIN_VALIDATION_EVIDENCE:
                status = "insufficient_evidence"
            elif confidence < MIN_CONFIDENCE_SCORE:
                status = "insufficient_confidence"
            else:
                status = "observation_only_degradation_not_beaten"
            rows.append({
                "category": category,
                "evidence_count": int(evidence),
                "validation_count": int(validation_count),
                "improvement_rate": improvement_rate,
                "degradation_rate": degradation_rate,
                "expectancy_delta": expectancy_delta,
                "profit_factor_delta": profit_factor_delta,
                "confidence_score": _round(confidence, 3),
                "readiness_score": _round(readiness, 3),
                "validated_status": status,
                "phase1_eligible": validated,
                "recommendation_category": category,
                "recommendation_confidence": _round(confidence, 3),
                "recommendation_timestamp": _now_iso(),
            })
        return rows

    def _influence(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        allowed = {"candidate_ranking", "buy_purity", "opportunity_cost"}
        row_map = {row["category"]: row for row in rows}

        def pct(category: str) -> float:
            row = row_map.get(category) or {}
            if not row.get("phase1_eligible"):
                return 0.0
            readiness = _to_float(row.get("readiness_score"), 0.0)
            spread = max(0.0, _to_float(row.get("improvement_rate"), 0.0) - _to_float(row.get("degradation_rate"), 0.0))
            raw = min(SHADOW_INFLUENCE_CAP_PCT, SHADOW_INFLUENCE_CAP_PCT * (readiness / 100.0) * (0.55 + min(0.45, spread / 100.0)))
            return _round(raw, 3)

        candidate = pct("candidate_ranking")
        buy = pct("buy_purity")
        opportunity = pct("opportunity_cost")
        return {
            "shadow_influence_enabled": bool(any(p > 0 for p in (candidate, buy, opportunity))),
            "shadow_influence_cap_pct": SHADOW_INFLUENCE_CAP_PCT,
            "candidate_ranking_influence_pct": candidate,
            "buy_purity_influence_pct": buy,
            "opportunity_cost_influence_pct": opportunity,
            "phase1_allowed_categories": sorted(allowed),
            "phase1_blocked_actions": [
                "create_trades",
                "block_trades",
                "broker_behavior",
                "position_sizing",
                "risk_limits",
                "exits",
                "capital_allocation",
            ],
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        rows = self._category_rows(statuses)
        influence = self._influence(rows)
        total_validated = sum(_to_int(row.get("validation_count"), 0) for row in rows)
        total_failed = sum(max(0, _to_int(row.get("evidence_count"), 0) - _to_int(row.get("validation_count"), 0)) for row in rows)
        reviewed = sum(_to_int(row.get("evidence_count"), 0) for row in rows)
        validated_rows = [row for row in rows if row.get("phase1_eligible")]
        phase1_rows = [row for row in rows if row.get("category") in {"candidate_ranking", "buy_purity", "opportunity_cost"}]
        strongest = max(rows, key=lambda row: _to_float(row.get("readiness_score"), 0.0), default={})
        weakest = min(rows, key=lambda row: _to_float(row.get("readiness_score"), 0.0), default={})
        avg_improvement = sum(_to_float(row.get("improvement_rate"), 0.0) - _to_float(row.get("degradation_rate"), 0.0) for row in rows) / max(1, len(rows))
        confidence = sum(_to_float(row.get("confidence_score"), 0.0) for row in phase1_rows) / max(1, len(phase1_rows))
        readiness = sum(_to_float(row.get("readiness_score"), 0.0) for row in phase1_rows) / max(1, len(phase1_rows))
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_correction_validation_attribution",
            "generated_at": _now_iso(),
            "validation_categories": rows,
            "strongest_validated_improvement": _text(strongest.get("category")),
            "weakest_validated_improvement": _text(weakest.get("category")),
            "total_validated_recommendations": int(total_validated),
            "total_failed_recommendations": int(total_failed),
            "average_improvement_score": _round(avg_improvement, 3),
            "validated_improvement_score": _round(max(0.0, avg_improvement), 3),
            "shadow_recommendations_reviewed": int(reviewed),
            "validated_recommendations": int(sum(1 for row in validated_rows)),
            "rejected_recommendations": int(len(rows) - len(validated_rows)),
            "confidence_score": _round(confidence, 3),
            "readiness_score": _round(readiness, 3),
            "minimum_validation_evidence": MIN_VALIDATION_EVIDENCE,
            **influence,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "portfolio_allocation_changed": False,
            "autonomous_entry_exit_control_enabled": False,
            "behavior_safe_to_apply": False,
            "shadow_recommendation": "Phase 1 shadow influence is capped, validation-gated, and advisory; continue paper-only validation before any broader policy deployment.",
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
                "mode": "shadow_only_correction_validation_attribution",
                "degraded_reason": f"shadow_correction_validation_unavailable:{str(exc)[:140]}",
                "shadow_influence_enabled": False,
                "shadow_influence_cap_pct": SHADOW_INFLUENCE_CAP_PCT,
                "candidate_ranking_influence_pct": 0.0,
                "buy_purity_influence_pct": 0.0,
                "opportunity_cost_influence_pct": 0.0,
                "validated_improvement_score": 0.0,
                "shadow_recommendations_reviewed": 0,
                "validated_recommendations": 0,
                "rejected_recommendations": 0,
                "confidence_score": 0.0,
                "readiness_score": 0.0,
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = now
        return out
