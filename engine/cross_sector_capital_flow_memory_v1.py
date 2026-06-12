from __future__ import annotations

import json, math, os, time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
SECTORS = ("Technology", "Industrials", "Healthcare", "Consumer", "Energy", "Financials", "Materials", "Utilities", "Real Estate", "Communications")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "": return float(default)
        if isinstance(value, str): value = value.strip().replace("%", "")
        out = float(value); return out if math.isfinite(out) else float(default)
    except Exception: return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try: return int(_to_float(value, default))
    except Exception: return int(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _round(value: Any, digits: int = 3) -> float:
    return round(_to_float(value), digits)


def _text(value: Any, default: str = "insufficient_data") -> str:
    out = str(value if value is not None else default).strip(); return out or str(default)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle: parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception: return {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True); tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle: json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception: return


def _status(statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    value = statuses.get(key) or {}; return dict(value) if isinstance(value, dict) else {}


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None: continue
        if isinstance(value, str) and not value.strip(): continue
        if isinstance(value, (dict, list)) and not value: continue
        return value
    return default


class CrossSectorCapitalFlowMemoryV1:
    """Shadow-only cross-sector/theme/leadership rotation memory."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state"); self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "cross_sector_capital_flow_memory_v1.json")
        self._cache: dict[str, Any] | None = None; self._cache_ts = 0.0

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        capital = _status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        market = _status(statuses, "market_context_learning_suite_v1")
        context = _status(statuses, "context_evidence_expansion_suite_v1")
        historical = _status(statuses, "historical_intelligence_market_memory_suite_v1")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        lifecycle = _status(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        shadow = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")

        evidence = max(_to_int(capital.get("capital_flow_records"), 0), _to_int(context.get("sector_records"), 0), _to_int(historical.get("sector_memory_records"), 0), _to_int(accelerated.get("symbol_profiles_tracked"), 0), _to_int(lifecycle.get("opportunities_tracked"), 0) // 3)
        base_conf = _clamp(_first(capital.get("capital_flow_confidence"), capital.get("narrative_confidence"), market.get("market_context_confidence"), context.get("context_confidence_score"), default=0.0))
        memory_quality = _clamp(_first(historical.get("market_memory_quality_score"), accelerated.get("cluster_learning_score"), convergence.get("symbol_behavior_confidence"), default=0.0))
        flow_pressure = _clamp(_first(capital.get("capital_flow_score"), market.get("sector_leadership_score"), shadow.get("consensus_confidence_score"), default=45.0))
        dominant_sector = _text(_first(capital.get("strongest_sector"), market.get("strongest_sector"), context.get("dominant_sector"), default="Technology"))
        weak_sector = _text(_first(capital.get("weakest_sector"), market.get("weakest_sector"), default="Utilities"))
        sector_rows = []
        for idx, sector in enumerate(SECTORS):
            leadership_bonus = 14.0 if sector.lower() in dominant_sector.lower() else 0.0
            outflow_bonus = 16.0 if sector.lower() in weak_sector.lower() else 0.0
            defensive = 8.0 if sector in {"Utilities", "Consumer", "Healthcare"} else 0.0
            growth = 8.0 if sector in {"Technology", "Communications", "Consumer"} else 0.0
            inflow = _clamp(flow_pressure * 0.55 + memory_quality * 0.20 + base_conf * 0.15 + leadership_bonus + growth - idx * 0.5)
            outflow = _clamp((100.0 - inflow) * 0.48 + outflow_bonus + defensive * 0.25)
            continuation_in = _clamp(inflow * 0.55 + base_conf * 0.25 + memory_quality * 0.20)
            continuation_out = _clamp(max(0.0, 100.0 - outflow) * 0.50 + base_conf * 0.20)
            sector_rows.append({"sector": sector, "inflow_score": _round(inflow, 3), "outflow_score": _round(outflow, 3), "flow_persistence": _round(_clamp((inflow - outflow) * 0.45 + memory_quality * 0.45 + base_conf * 0.10), 3), "rotation_speed": _round(_clamp(abs(inflow - outflow) * 0.62 + (100.0 - memory_quality) * 0.18), 3), "continuation_after_inflow": _round(continuation_in, 3), "continuation_after_outflow": _round(continuation_out, 3), "evidence_count": max(1, int(evidence / max(1, len(SECTORS))))})
        strongest_in = max(sector_rows, key=lambda r: r["inflow_score"], default={})
        strongest_out = max(sector_rows, key=lambda r: r["outflow_score"], default={})
        strongest_rotation = max(sector_rows, key=lambda r: r["rotation_speed"], default={})
        theme_rotation = _text(_first(capital.get("dominant_theme"), accelerated.get("strongest_symbol_cluster"), "AI_to_broad_growth"))
        confidence = _clamp(base_conf * 0.35 + memory_quality * 0.35 + min(100.0, evidence * 1.2) * 0.20 + flow_pressure * 0.10)
        rotation_confidence = _clamp(confidence * 0.70 + _to_float(strongest_rotation.get("rotation_speed"), 0.0) * 0.30)
        transition_memory = [{"from_sector": _text(strongest_out.get("sector")), "to_sector": _text(strongest_in.get("sector")), "transition_confidence": _round(rotation_confidence, 3), "continuation_probability": _round(strongest_in.get("continuation_after_inflow"), 3)}]
        out = {"enabled": True, "version": VERSION, "mode": "shadow_only_cross_sector_capital_flow_memory", "generated_at": _now_iso(), "evidence_count": int(evidence), "sector_flow_rows": sector_rows, "sector_transition_memory": transition_memory, "theme_transition_memory": [{"theme_rotation": theme_rotation, "confidence": _round(confidence, 3)}], "leadership_transition_memory": transition_memory, "strongest_inflow_sector": _text(strongest_in.get("sector")), "strongest_outflow_sector": _text(strongest_out.get("sector")), "flow_persistence": _round(strongest_in.get("flow_persistence"), 3), "rotation_speed": _round(strongest_rotation.get("rotation_speed"), 3), "continuation_after_inflow": _round(strongest_in.get("continuation_after_inflow"), 3), "continuation_after_outflow": _round(strongest_out.get("continuation_after_outflow"), 3), "strongest_capital_flow": f"{_text(strongest_in.get('sector'))}_inflow", "weakest_capital_flow": f"{_text(strongest_out.get('sector'))}_outflow", "strongest_sector_rotation": f"{_text(strongest_out.get('sector'))}_to_{_text(strongest_in.get('sector'))}", "strongest_theme_rotation": theme_rotation, "sector_flow_confidence": _round(confidence, 3), "rotation_confidence": _round(rotation_confidence, 3), "cache_freshness": "fresh", "dashboard_scan_rows": 0, "raw_archive_scanned": False, "raw_history_scanned": False, "api_calls_used": 0, "provider_calls_used": 0, "llm_calls_used": 0, "paper_only_preserved": True, "alpaca_paper_only_preserved": True, "forced_exits_enabled": False, "forced_trades_enabled": False, "partial_sells_enabled": False, "automatic_trailing_stops_enabled": False, "live_trading_changed": False, "broker_behavior_changed": False, "entry_behavior_changed": False, "exit_behavior_changed": False, "position_sizing_changed": False, "portfolio_allocation_changed": False, "thresholds_changed": False, "behavior_safe_to_apply": False, "shadow_recommendation": "Use cross-sector flow memory as advisory context only; do not change trades, sizing, thresholds, or broker behavior.", "build_ms": _round((time.perf_counter() - start) * 1000.0, 3)}
        _write_json(self.cache_path, out); return out

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
        try: out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = {"enabled": False, "version": VERSION, "mode": "shadow_only_cross_sector_capital_flow_memory", "degraded_reason": f"cross_sector_capital_flow_memory_unavailable:{str(exc)[:140]}", "evidence_count": 0, "strongest_capital_flow": "insufficient_data", "weakest_capital_flow": "insufficient_data", "strongest_sector_rotation": "insufficient_data", "strongest_theme_rotation": "insufficient_data", "sector_flow_confidence": 0.0, "rotation_confidence": 0.0, "api_calls_used": 0, "provider_calls_used": 0, "llm_calls_used": 0, "paper_only_preserved": True, "alpaca_paper_only_preserved": True, "forced_exits_enabled": False, "forced_trades_enabled": False, "partial_sells_enabled": False, "automatic_trailing_stops_enabled": False, "live_trading_changed": False, "broker_behavior_changed": False, "entry_behavior_changed": False, "exit_behavior_changed": False, "position_sizing_changed": False, "portfolio_allocation_changed": False, "thresholds_changed": False, "behavior_safe_to_apply": False, "build_ms": _round((time.perf_counter() - start) * 1000.0, 3)}
        self._cache = dict(out); self._cache_ts = time.time(); return out
