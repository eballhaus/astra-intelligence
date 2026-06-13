from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
THESIS_TYPES = (
    "trade_thesis",
    "catalyst_thesis",
    "symbol_thesis",
    "sector_thesis",
    "regime_thesis",
    "horizon_thesis",
    "entry_thesis",
    "exit_thesis",
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


class TradeThesisValidationV1:
    """Shadow-only thesis validation from cached learning evidence."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "trade_thesis_validation_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        decision = _status(statuses, "decision_optimization_trade_management_suite_v1")
        catalyst = _status(statuses, "catalyst_lifecycle_intelligence_v1")
        symbol = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        market = _status(statuses, "market_context_learning_suite_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        profit = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        shadow = _status(statuses, "shadow_correction_validation_attribution_v1")
        confidence = _status(statuses, "confidence_calibration_performance_attribution_v1")
        full = _status(statuses, "full_opportunity_lifecycle_learning_suite_v1")

        evidence = max(
            _to_int(full.get("opportunities_tracked"), 0),
            _to_int(convergence.get("tracked_trades"), 0),
            _to_int(shadow.get("shadow_recommendations_reviewed"), 0),
            _to_int(confidence.get("evidence_count"), 0),
        )
        quality_map = {
            "trade_thesis": _clamp(_first(decision.get("decision_quality_score"), shadow.get("validated_improvement_score"), default=55.0)),
            "catalyst_thesis": _clamp(_first(catalyst.get("catalyst_lifecycle_confidence"), confidence.get("feature_attribution_confidence"), default=52.0)),
            "symbol_thesis": _clamp(_first(symbol.get("symbol_personality_quality_score"), convergence.get("symbol_behavior_confidence"), default=48.0)),
            "sector_thesis": _clamp(_first(symbol.get("peer_group_learning_score"), decision.get("market_context_quality"), default=46.0)),
            "regime_thesis": _clamp(_first(market.get("regime_fit_score"), decision.get("decision_quality_score"), default=54.0)),
            "horizon_thesis": _clamp(_first(profit.get("hold_duration_quality_score"), convergence.get("horizon_fit_confidence"), default=50.0)),
            "entry_thesis": _clamp(_first(decision.get("entry_quality_score"), confidence.get("confidence_predictive_power"), default=49.0)),
            "exit_thesis": _clamp(_first(profit.get("policy_confidence"), profit.get("capture_quality_score"), default=47.0)),
        }
        failed_reason_map = {
            "trade_thesis": "weak_follow_through_or_selection_noise",
            "catalyst_thesis": "catalyst_decay_or_unknown_catalyst",
            "symbol_thesis": "symbol_behavior_drift",
            "sector_thesis": "sector_rotation_or_peer_mismatch",
            "regime_thesis": "regime_shift_or_context_conflict",
            "horizon_thesis": "horizon_mismatch",
            "entry_thesis": "entry_timing_or_confirmation_miss",
            "exit_thesis": "profit_giveback_or_late_exit",
        }
        success_reason_map = {
            "trade_thesis": "setup_follow_through_confirmed",
            "catalyst_thesis": "catalyst_persistence_confirmed",
            "symbol_thesis": "symbol_behavior_match",
            "sector_thesis": "sector_peer_alignment",
            "regime_thesis": "regime_fit_confirmed",
            "horizon_thesis": "correct_hold_window",
            "entry_thesis": "entry_confirmation_quality",
            "exit_thesis": "profit_capture_alignment",
        }

        rows = []
        for idx, thesis_type in enumerate(THESIS_TYPES):
            score = quality_map[thesis_type]
            accuracy = _clamp(score * 0.88 + min(12.0, evidence / 25.0))
            failure_rate = _clamp(100.0 - accuracy)
            rows.append({
                "thesis_type": thesis_type,
                "accuracy_score": _round(accuracy, 3),
                "failure_rate": _round(failure_rate, 3),
                "confidence": _round(_clamp(score * 0.72 + min(20.0, evidence / 30.0) + max(0.0, 8.0 - idx)), 3),
                "top_failed_reason": failed_reason_map[thesis_type],
                "top_success_reason": success_reason_map[thesis_type],
                "evidence_count": max(1, int(evidence / max(1, len(THESIS_TYPES)))),
            })
        strongest = max(rows, key=lambda row: row["accuracy_score"], default={})
        weakest = max(rows, key=lambda row: row["failure_rate"], default={})
        thesis_confidence = _clamp(sum(row["confidence"] for row in rows) / max(1, len(rows)))
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_trade_thesis_validation",
            "generated_at": _now_iso(),
            "evidence_count": int(evidence),
            "thesis_rows": rows,
            "thesis_accuracy_score": _round(sum(row["accuracy_score"] for row in rows) / max(1, len(rows)), 3),
            "thesis_failure_rate": _round(sum(row["failure_rate"] for row in rows) / max(1, len(rows)), 3),
            "strongest_thesis_type": _text(strongest.get("thesis_type")),
            "weakest_thesis_type": _text(weakest.get("thesis_type")),
            "thesis_confidence": _round(thesis_confidence, 3),
            "top_failed_thesis_reason": _text(weakest.get("top_failed_reason")),
            "top_successful_thesis_reason": _text(strongest.get("top_success_reason")),
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
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
            "shadow_recommendation": "Validate trade theses as learning evidence only; do not change entries, exits, sizing, or broker behavior.",
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
                "mode": "shadow_only_trade_thesis_validation",
                "degraded_reason": f"trade_thesis_validation_unavailable:{str(exc)[:140]}",
                "evidence_count": 0,
                "thesis_accuracy_score": 0.0,
                "thesis_failure_rate": 0.0,
                "strongest_thesis_type": "insufficient_data",
                "weakest_thesis_type": "insufficient_data",
                "thesis_confidence": 0.0,
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
