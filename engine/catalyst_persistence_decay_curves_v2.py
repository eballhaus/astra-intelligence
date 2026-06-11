from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "2.0.0"
CACHE_TTL_SECONDS = 20.0

DEFAULT_CATALYSTS = (
    "earnings",
    "FDA_or_regulatory",
    "analyst_upgrade",
    "AI_theme",
    "semiconductor_theme",
    "contract_award",
    "short_squeeze",
    "sector_rotation",
    "macro_catalyst",
    "market_wide_momentum",
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


def _normalize_catalyst(value: Any) -> str:
    raw = _text(value, "unknown_catalyst").lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "ai": "AI_theme",
        "ai_theme": "AI_theme",
        "artificial_intelligence": "AI_theme",
        "semiconductor": "semiconductor_theme",
        "semiconductors": "semiconductor_theme",
        "fda": "FDA_or_regulatory",
        "regulatory": "FDA_or_regulatory",
        "analyst": "analyst_upgrade",
        "upgrade": "analyst_upgrade",
        "macro": "macro_catalyst",
        "macro_event": "macro_catalyst",
        "momentum": "market_wide_momentum",
        "sector_sympathy": "sector_rotation",
        "sector_rotation": "sector_rotation",
        "short_interest": "short_squeeze",
        "squeeze": "short_squeeze",
    }
    return aliases.get(raw, raw)


class CatalystPersistenceDecayCurvesV2:
    """Shadow-only catalyst persistence and decay curve diagnostics.

    This suite reads cached summaries only. It does not call providers, brokers,
    LLMs, or execution/ranking code.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "catalyst_persistence_decay_curves_v2.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _catalyst_names(self, statuses: dict[str, dict[str, Any]]) -> list[str]:
        names = set(DEFAULT_CATALYSTS)
        catalyst = _status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        context = _status(statuses, "context_evidence_expansion_suite_v1")
        maturation = _status(statuses, "catalyst_classification_historical_exit_maturation_suite_v1")
        for value in (
            catalyst.get("dominant_catalyst"),
            catalyst.get("strongest_catalyst_type"),
            catalyst.get("weakest_catalyst_type"),
            context.get("dominant_catalyst_type"),
            context.get("strongest_catalyst_type"),
            context.get("weakest_catalyst_type"),
            maturation.get("dominant_catalyst"),
        ):
            if value:
                names.add(_normalize_catalyst(value))
        for mapping_key in ("best_horizon_by_catalyst", "catalyst_reliability_by_symbol"):
            for source in (catalyst, context):
                mapping = source.get(mapping_key) or {}
                if isinstance(mapping, dict):
                    names.update(_normalize_catalyst(k) for k in mapping.keys())
        for item in maturation.get("inferred_catalyst_categories") or []:
            names.add(_normalize_catalyst(item))
        return sorted(x for x in names if x and x not in {"unknown", "unknown_catalyst", "no_detected_catalyst"})[:18]

    def _build_curves(self, statuses: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        catalyst = _status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        context = _status(statuses, "context_evidence_expansion_suite_v1")
        historical = _status(statuses, "historical_intelligence_market_memory_suite_v1")
        maturation = _status(statuses, "catalyst_classification_historical_exit_maturation_suite_v1")
        profit = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        multi = _status(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        lifecycle = _status(statuses, "trade_lifecycle_excursion_v2")
        shadow = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")

        total_records = max(
            _to_int(catalyst.get("catalyst_records"), 0),
            _to_int(context.get("catalyst_records"), 0),
            _to_int(historical.get("catalyst_records_created"), 0),
            _to_int(maturation.get("classified_catalyst_count"), 0),
            1,
        )
        coverage = _clamp(_first(
            maturation.get("catalyst_coverage_score"),
            catalyst.get("catalyst_coverage_score"),
            context.get("catalyst_coverage_score"),
            historical.get("catalyst_coverage_score"),
            default=0.0,
        ))
        memory_quality = _clamp(
            _to_float(maturation.get("catalyst_memory_quality"), 0.0) * 0.40
            + _to_float(catalyst.get("catalyst_truth_score"), 0.0) * 0.25
            + _to_float(historical.get("historical_lesson_quality_score"), 0.0) * 0.20
            + coverage * 0.15
        )
        base_continuation = _clamp(
            _to_float(profit.get("continuation_failure_probability"), 0.0)
        )
        if base_continuation <= 0:
            base_continuation = _clamp(_to_float(shadow.get("consensus_confidence_score"), 45.0))
        decay_pressure = _clamp(
            _to_float(catalyst.get("catalyst_decay_learning_score"), 0.0) * 0.30
            + _to_float(maturation.get("catalyst_decay_learning_score"), 0.0) * 0.30
            + _to_float(multi.get("horizon_mismatch_risk_score"), 0.0) * 0.15
            + _to_float(profit.get("average_giveback_pct"), 0.0) * 2.5
        )
        hold_quality = _clamp(_to_float(profit.get("hold_duration_quality_score"), _to_float(maturation.get("hold_duration_learning_score"), 0.0)))
        avg_hold = _to_float(lifecycle.get("average_hold_duration_minutes"), 90.0)
        if avg_hold <= 0:
            avg_hold = 90.0

        best_by_catalyst = {}
        for source in (catalyst, context):
            mapping = source.get("best_horizon_by_catalyst") or {}
            if isinstance(mapping, dict):
                best_by_catalyst.update({_normalize_catalyst(k): v for k, v in mapping.items()})

        curves: list[dict[str, Any]] = []
        names = self._catalyst_names(statuses)
        per_count = max(1, int(total_records / max(1, len(names))))
        for idx, name in enumerate(names):
            horizon = _text(best_by_catalyst.get(name), "day_trade").lower()
            horizon_mult = 0.45 if "scalp" in horizon else (1.0 if "day" in horizon else 3.0)
            theme_bonus = 8.0 if any(token in name.lower() for token in ("ai", "semiconductor", "quantum", "market_wide")) else 0.0
            event_penalty = 10.0 if any(token in name.lower() for token in ("short_squeeze", "macro", "fda")) else 0.0
            continuation = _clamp(base_continuation * 0.45 + memory_quality * 0.35 + coverage * 0.20 + theme_bonus - event_penalty)
            exhaustion = _clamp(decay_pressure * 0.55 + max(0.0, 100.0 - continuation) * 0.35 + idx * 0.6)
            persistence = _clamp(continuation * 0.50 + hold_quality * 0.22 + memory_quality * 0.28 - exhaustion * 0.18)
            decay = _clamp(exhaustion * 0.70 + max(0.0, 100.0 - persistence) * 0.30)
            avg_cont_minutes = max(5.0, avg_hold * horizon_mult * (0.55 + persistence / 160.0))
            avg_decay_minutes = max(5.0, avg_cont_minutes * (0.45 + decay / 170.0))
            peak_minutes = max(3.0, avg_cont_minutes * 0.42)
            giveback_minutes = max(5.0, peak_minutes + avg_decay_minutes * 0.55)
            half_life = max(5.0, avg_cont_minutes * (0.42 + (100.0 - decay) / 260.0))
            confidence = _clamp(memory_quality * 0.50 + min(100.0, per_count * 3.0) * 0.25 + coverage * 0.25)
            curves.append({
                "catalyst_type": name,
                "occurrence_count": int(per_count),
                "average_continuation_duration_minutes": _round(avg_cont_minutes, 2),
                "average_decay_duration_minutes": _round(avg_decay_minutes, 2),
                "average_peak_timing_minutes": _round(peak_minutes, 2),
                "average_giveback_timing_minutes": _round(giveback_minutes, 2),
                "average_persistence_score": _round(persistence, 3),
                "confidence_score": _round(confidence, 3),
                "catalyst_persistence_score": _round(persistence, 3),
                "catalyst_decay_score": _round(decay, 3),
                "catalyst_half_life_estimate_minutes": _round(half_life, 2),
                "catalyst_continuation_probability": _round(continuation, 3),
                "catalyst_exhaustion_probability": _round(exhaustion, 3),
                "best_horizon_hint": horizon,
            })
        strongest = max(curves, key=lambda row: row["catalyst_persistence_score"], default={})
        weakest = max(curves, key=lambda row: row["catalyst_decay_score"], default={})
        aggregate = {
            "catalyst_persistence_score": _round(sum(r["catalyst_persistence_score"] for r in curves) / max(1, len(curves)), 3),
            "catalyst_decay_score": _round(sum(r["catalyst_decay_score"] for r in curves) / max(1, len(curves)), 3),
            "catalyst_half_life_estimate": _round(sum(r["catalyst_half_life_estimate_minutes"] for r in curves) / max(1, len(curves)), 2),
            "catalyst_continuation_probability": _round(sum(r["catalyst_continuation_probability"] for r in curves) / max(1, len(curves)), 3),
            "catalyst_exhaustion_probability": _round(sum(r["catalyst_exhaustion_probability"] for r in curves) / max(1, len(curves)), 3),
            "catalyst_memory_quality": _round(memory_quality, 3),
            "strongest_persistence_catalyst": _text(strongest.get("catalyst_type")),
            "fastest_decay_catalyst": _text(weakest.get("catalyst_type")),
        }
        return curves, aggregate

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        curves, aggregate = self._build_curves(statuses)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_catalyst_persistence_decay_curves",
            "generated_at": _now_iso(),
            "catalyst_curves": curves[:18],
            "catalysts_tracked": len(curves),
            **aggregate,
            "cache_freshness": "fresh",
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "behavior_safe_to_apply": False,
            "shadow_recommendation": "Use catalyst persistence curves as advisory memory only; do not apply hold or exit changes without human-reviewed validation.",
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
                "mode": "shadow_only_catalyst_persistence_decay_curves",
                "degraded_reason": f"catalyst_persistence_decay_curves_unavailable:{str(exc)[:140]}",
                "catalyst_persistence_score": 0.0,
                "catalyst_decay_score": 0.0,
                "catalyst_half_life_estimate": 0.0,
                "catalyst_continuation_probability": 0.0,
                "catalyst_exhaustion_probability": 0.0,
                "catalyst_memory_quality": 0.0,
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = now
        return out
