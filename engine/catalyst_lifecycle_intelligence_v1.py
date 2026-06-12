from __future__ import annotations

import json, math, os, time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
STAGES = ("emerging", "accelerating", "mature", "peaking", "decaying", "exhausted")
CATALYSTS = (
    "earnings", "AI", "quantum", "crypto", "FDA", "analyst_upgrade", "analyst_downgrade",
    "sector_rotation", "M&A", "macro", "market_wide_risk", "short_squeeze", "momentum_continuation",
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


class CatalystLifecycleIntelligenceV1:
    """Shadow-only catalyst lifecycle diagnostics from cached evidence."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "catalyst_lifecycle_intelligence_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        curves = _status(statuses, "catalyst_persistence_decay_curves_v2")
        catalyst_hist = _status(statuses, "catalyst_classification_historical_exit_maturation_suite_v1")
        capital = _status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        profit = _status(statuses, "profit_lock_profit_capture_maturation_v2")
        protection = _status(statuses, "controlled_paper_profit_protection_pilot_v1")
        shadow = _status(statuses, "shadow_correction_validation_attribution_v1")
        historical = _status(statuses, "historical_intelligence_market_memory_suite_v1")
        replay = _status(statuses, "replay_counterfactual_learning_v2")
        symbol = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")

        evidence = max(
            _to_int(catalyst_hist.get("classified_catalyst_count"), 0),
            _to_int(capital.get("catalyst_records"), 0),
            _to_int(historical.get("catalyst_records_created"), 0),
            _to_int(replay.get("counterfactual_count"), 0),
            _to_int(curves.get("catalysts_tracked"), 0) * 8,
        )
        memory_quality = _clamp(_first(catalyst_hist.get("catalyst_memory_quality"), curves.get("catalyst_memory_quality"), capital.get("catalyst_truth_score"), default=0.0))
        persistence = _clamp(curves.get("catalyst_persistence_score"), 0.0, 100.0)
        decay = _clamp(curves.get("catalyst_decay_score"), 0.0, 100.0)
        continuation = _clamp(curves.get("catalyst_continuation_probability"), 0.0, 100.0)
        giveback = max(0.0, _to_float(_first(profit.get("average_giveback_pct"), protection.get("giveback_rate"), default=0.0)))
        hold_quality = _clamp(_first(profit.get("hold_duration_learning_score"), protection.get("hold_duration_efficiency"), default=0.0))
        exit_quality = _clamp(_first(profit.get("profit_lock_readiness_score"), protection.get("profit_lock_readiness"), default=0.0))
        half_life = max(5.0, _to_float(curves.get("catalyst_half_life_estimate"), 45.0))
        confidence = _clamp(memory_quality * 0.45 + min(100.0, evidence * 1.4) * 0.25 + _clamp(shadow.get("confidence_score"), 0, 100) * 0.15 + persistence * 0.15)

        stage_rows: list[dict[str, Any]] = []
        stage_weights = {
            "emerging": (0.65, 0.35, 0.30),
            "accelerating": (0.95, 0.20, 0.55),
            "mature": (0.85, 0.35, 0.70),
            "peaking": (0.62, 0.62, 0.86),
            "decaying": (0.35, 0.88, 0.55),
            "exhausted": (0.12, 0.98, 0.25),
        }
        for stage in STAGES:
            cont_mult, decay_mult, profit_mult = stage_weights[stage]
            cont = _clamp(continuation * cont_mult + persistence * 0.18)
            dec = _clamp(decay * decay_mult + max(0.0, 100.0 - cont) * 0.20)
            prof = _clamp((cont * 0.42 + exit_quality * 0.22 + memory_quality * 0.18 + profit_mult * 30.0) - giveback * decay_mult)
            stage_giveback = max(0.0, giveback * (0.55 + decay_mult))
            stage_rows.append({
                "stage": stage,
                "persistence_score": _round(persistence * cont_mult + memory_quality * 0.15, 3),
                "continuation_probability": _round(cont, 3),
                "decay_probability": _round(dec, 3),
                "average_lifespan_minutes": _round(half_life * (0.55 + cont_mult), 2),
                "profitability_score": _round(prof, 3),
                "average_giveback_pct": _round(stage_giveback, 4),
                "exit_quality_score": _round(_clamp(exit_quality * (1.0 - decay_mult * 0.25) + cont * 0.20), 3),
                "hold_duration_quality_score": _round(_clamp(hold_quality * (1.0 - decay_mult * 0.22) + cont * 0.18), 3),
            })
        strongest_stage = max(stage_rows, key=lambda r: r["profitability_score"], default={})
        weakest_stage = max(stage_rows, key=lambda r: r["decay_probability"], default={})

        catalyst_rows: list[dict[str, Any]] = []
        curve_map = {str(r.get("catalyst_type", "")).lower(): r for r in (curves.get("catalyst_curves") or []) if isinstance(r, dict)}
        for idx, catalyst in enumerate(CATALYSTS):
            key = catalyst.lower().replace(" ", "_")
            curve = curve_map.get(key) or curve_map.get(key + "_theme") or {}
            c_persistence = _clamp(_first(curve.get("catalyst_persistence_score"), persistence - idx * 0.8, default=persistence))
            c_decay = _clamp(_first(curve.get("catalyst_decay_score"), decay + idx * 0.6, default=decay))
            best_stage = "accelerating" if c_persistence >= c_decay else "peaking"
            if c_decay > 70:
                best_stage = "mature"
            catalyst_rows.append({
                "catalyst_type": catalyst,
                "best_lifecycle_stage": best_stage,
                "persistence_score": _round(c_persistence, 3),
                "continuation_probability": _round(_clamp(_first(curve.get("catalyst_continuation_probability"), continuation, default=continuation)), 3),
                "decay_probability": _round(c_decay, 3),
                "average_lifespan_minutes": _round(_to_float(_first(curve.get("catalyst_half_life_estimate_minutes"), half_life, default=half_life)), 2),
                "profitability_score": _round(_clamp(c_persistence * 0.45 + memory_quality * 0.25 + exit_quality * 0.18 - c_decay * 0.12), 3),
                "evidence_count": max(1, int(evidence / max(1, len(CATALYSTS)))),
            })
        best_lifecycle = max(catalyst_rows, key=lambda r: r["profitability_score"], default={})
        worst_lifecycle = max(catalyst_rows, key=lambda r: r["decay_probability"], default={})
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_catalyst_lifecycle_intelligence",
            "generated_at": _now_iso(),
            "evidence_count": int(evidence),
            "lifecycle_stages": stage_rows,
            "catalyst_lifecycle_rows": catalyst_rows,
            "strongest_catalyst_stage": _text(strongest_stage.get("stage")),
            "weakest_catalyst_stage": _text(weakest_stage.get("stage")),
            "best_catalyst_lifecycle": _text(best_lifecycle.get("catalyst_type")),
            "worst_catalyst_lifecycle": _text(worst_lifecycle.get("catalyst_type")),
            "catalyst_lifecycle_confidence": _round(confidence, 3),
            "average_persistence_score": _round(persistence, 3),
            "average_decay_probability": _round(decay, 3),
            "average_continuation_probability": _round(continuation, 3),
            "average_lifespan_minutes": _round(half_life, 2),
            "best_stage_profitability_score": _round(strongest_stage.get("profitability_score"), 3),
            "worst_stage_giveback_pct": _round(weakest_stage.get("average_giveback_pct"), 4),
            "symbol_memory_support": _round(_clamp(symbol.get("symbol_personality_quality_score"), 0, 100), 3),
            "cache_freshness": "fresh",
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
            "shadow_recommendation": "Use catalyst lifecycle stages for advisory learning only; do not change entries, exits, sizing, or broker behavior.",
            "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
        }
        _write_json(self.cache_path, out)
        return out

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter(); now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache); out["cache_hit"] = True; out["cache_age_seconds"] = _round(now - self._cache_ts, 3); out["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3); return out
        if not force:
            disk = _read_json(self.cache_path)
            if disk:
                try: age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
                except Exception: age = 999999.0
                if age <= self.ttl_seconds:
                    disk["cache_hit"] = True; disk["cache_age_seconds"] = _round(age, 3); disk["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3); self._cache = dict(disk); self._cache_ts = now - age; return disk
        try:
            out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = {"enabled": False, "version": VERSION, "mode": "shadow_only_catalyst_lifecycle_intelligence", "degraded_reason": f"catalyst_lifecycle_intelligence_unavailable:{str(exc)[:140]}", "evidence_count": 0, "strongest_catalyst_stage": "insufficient_data", "weakest_catalyst_stage": "insufficient_data", "best_catalyst_lifecycle": "insufficient_data", "worst_catalyst_lifecycle": "insufficient_data", "catalyst_lifecycle_confidence": 0.0, "api_calls_used": 0, "provider_calls_used": 0, "llm_calls_used": 0, "paper_only_preserved": True, "alpaca_paper_only_preserved": True, "forced_exits_enabled": False, "forced_trades_enabled": False, "partial_sells_enabled": False, "automatic_trailing_stops_enabled": False, "live_trading_changed": False, "broker_behavior_changed": False, "entry_behavior_changed": False, "exit_behavior_changed": False, "position_sizing_changed": False, "portfolio_allocation_changed": False, "thresholds_changed": False, "behavior_safe_to_apply": False, "build_ms": _round((time.perf_counter() - start) * 1000.0, 3)}
        self._cache = dict(out); self._cache_ts = time.time(); return out
