from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 12.0
DASHBOARD_CACHE_MAX_AGE_SECONDS = 180.0

HORIZON_BUCKETS = ["15m", "30m", "45m", "60m", "2h", "4h", "eod", "1d", "2d", "3d", "5d", "10d", "10d_plus"]
PEER_GROUPS: dict[str, list[str]] = {
    "semiconductor_ai_leaders": ["NVDA", "AMD", "AVGO", "TSM", "ARM"],
    "quantum_momentum": ["QBTS", "RGTI", "IONQ", "QUBT"],
    "retail_momentum": ["AMC", "GME"],
    "biotech_catalyst_movers": ["MRNA", "BNTX", "REGN", "VRTX"],
    "airline_rotation": ["DAL", "UAL", "AAL"],
    "sector_proxy_etfs": ["QQQ", "SPY", "IWM", "SMH", "XLE", "XLV"],
}


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


def _text(value: Any, default: str = "insufficient_data") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        return


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _compact_map(value: Any, limit: int = 8) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in list(value.items())[:limit]}


def _first_key(value: Any, default: str = "insufficient_data") -> str:
    if isinstance(value, dict) and value:
        return _text(next(iter(value.keys())), default)
    return default


def _first_value(value: Any, default: str = "insufficient_data") -> str:
    if isinstance(value, dict) and value:
        return _text(next(iter(value.values())), default)
    return default


class MultiHorizonIntelligenceAdaptiveLifecycleSuiteV1:
    """Shadow-only horizon, lifecycle, and cross-symbol pattern diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "multi_horizon_intelligence_adaptive_lifecycle_suite_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _status(self, statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        return dict(statuses.get(key) or {})

    def _horizon_stats(self, horizon_dashboard: dict[str, Any]) -> tuple[dict[str, Any], str, str, str]:
        stats: dict[str, Any] = {}
        for key in ("scalp", "day_trade", "swing_trade"):
            payload = dict(horizon_dashboard.get(key) or {})
            count = _to_int(payload.get("closed_sample_size"), _to_int(payload.get("sample_size"), _to_int(payload.get("natural_exit_count"), 0)))
            stats[key] = {
                "evidence_count": count,
                "win_rate": _to_float(payload.get("win_rate"), 0.0),
                "average_return": _to_float(payload.get("average_return_pct"), 0.0),
                "profit_factor": _to_float(payload.get("profit_factor"), 0.0),
                "expectancy": _to_float(payload.get("average_return_pct"), 0.0),
                "mfe": _to_float(payload.get("average_mfe"), 0.0),
                "mae": _to_float(payload.get("average_mae"), 0.0),
                "giveback": _to_float(payload.get("average_giveback"), 0.0),
                "capture_ratio": _to_float(payload.get("capture_ratio"), 0.0),
                "exit_quality": _to_float(payload.get("exit_quality"), 0.0),
                "follow_through": _to_float(payload.get("follow_through"), _to_float(payload.get("entry_quality"), 0.0)),
                "catalyst_decay": _to_float(payload.get("catalyst_decay"), 0.0),
                "continuation_failure": _to_float(payload.get("continuation_failure"), 0.0),
            }
        dominant = max(stats.items(), key=lambda item: _to_int(item[1].get("evidence_count"), 0), default=("insufficient_data", {}))[0]
        best = _text(horizon_dashboard.get("best_current_horizon"), dominant)
        weakest = _text(horizon_dashboard.get("weakest_current_horizon"), "insufficient_data")
        return stats, dominant, best, weakest

    def _symbol_dna(self, accelerated: dict[str, Any], convergence: dict[str, Any], memory: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        best_horizon = _compact_map(accelerated.get("best_horizon_by_symbol") or convergence.get("best_horizon_by_symbol"))
        best_exit = _compact_map(accelerated.get("best_exit_style_by_symbol") or convergence.get("best_exit_style_by_symbol"))
        best_catalyst = _compact_map(accelerated.get("best_catalyst_by_symbol") or convergence.get("best_catalyst_by_symbol"))
        best_regime = _compact_map(accelerated.get("best_regime_by_symbol") or convergence.get("best_regime_by_symbol"))
        worst_horizon = _compact_map(accelerated.get("worst_horizon_by_symbol") or convergence.get("worst_horizon_by_symbol"))
        symbols = list(dict.fromkeys(list(best_horizon.keys()) + list(best_exit.keys()) + [_text(memory.get("strongest_symbol_profile"), "")]))
        dna: dict[str, Any] = {}
        for symbol in [s for s in symbols if s][:10]:
            peer_group = self._peer_group_for_symbol(symbol)
            evidence = max(_to_int(memory.get("symbol_profiles_tracked"), 0), _to_int(convergence.get("symbol_profiles_reviewed"), 0))
            confidence = "high" if evidence >= 50 else "moderate" if evidence >= 15 else "low"
            dna[symbol] = {
                "best_horizon": _text(best_horizon.get(symbol), _first_value(best_horizon)),
                "worst_horizon": _text(worst_horizon.get(symbol), "insufficient_data"),
                "best_exit_style": _text(best_exit.get(symbol), _first_value(best_exit)),
                "best_setup": _text(convergence.get("best_symbol_horizon_pair") or accelerated.get("best_symbol_horizon_pair"), "insufficient_data"),
                "best_catalyst": _text(best_catalyst.get(symbol), _first_value(best_catalyst)),
                "best_regime": _text(best_regime.get(symbol), _first_value(best_regime)),
                "average_giveback": _to_float(memory.get("highest_giveback_symbol") == symbol and convergence.get("average_convergence_gap"), 0.0),
                "capture_ratio": _to_float(convergence.get("convergence_quality_score"), 0.0),
                "evidence_count": evidence,
                "confidence": confidence,
                "recent_drift": symbol in set(accelerated.get("symbols_with_behavior_drift") or []),
                "peer_group_support": peer_group,
            }
        strongest = _text(memory.get("strongest_symbol_profile") or accelerated.get("strongest_symbol_profile") or _first_key(dna), "insufficient_data")
        weakest = _text(memory.get("highest_giveback_symbol") or accelerated.get("highest_giveback_symbol") or _first_key(worst_horizon), "insufficient_data")
        return dna, strongest, weakest

    def _peer_group_for_symbol(self, symbol: str) -> str:
        upper = _text(symbol, "").upper()
        for group, members in PEER_GROUPS.items():
            if upper in members:
                return group
        return "direct_symbol_only"

    def _readiness(self, horizon_stats: dict[str, Any], horizon_coverage: dict[str, Any]) -> dict[str, Any]:
        readiness: dict[str, Any] = {}
        support_score = _to_float(horizon_coverage.get("shadow_support_score"), 0.0)
        for horizon, payload in horizon_stats.items():
            evidence = _to_int(payload.get("evidence_count"), 0)
            repeatability = _clamp(_to_float(payload.get("profit_factor"), 0.0) * 20.0)
            confidence = _clamp(min(40.0, evidence / 5.0) + repeatability * 0.35 + support_score * 0.25)
            if confidence >= 85 and evidence >= 120:
                status = "high_confidence_shadow_only"
                remaining = "human_review_required_before_any_paper_behavior_change"
            elif confidence >= 65 and evidence >= 50:
                status = "paper_ready_candidate"
                remaining = "policy_governance_and_human_review_required"
            elif confidence >= 35 and evidence >= 15:
                status = "validation_ready"
                remaining = "more_cross_regime_and_symbol_confirmation"
            else:
                status = "not_ready"
                remaining = "more_horizon_lifecycle_evidence_needed"
            readiness[horizon] = {
                "status": status,
                "evidence_count": evidence,
                "confidence": round(confidence, 2),
                "repeatability": round(repeatability, 2),
                "regime_support": _text(horizon_coverage.get("learned_horizon_status"), "shadow_only_not_applied"),
                "symbol_support": _text(horizon_coverage.get("paper_horizon_bias"), "insufficient_data"),
                "peer_support": "supportive_only",
                "remaining_evidence_needed": remaining,
            }
        return readiness

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        horizon_dashboard = self._status(statuses, "horizon_performance_dashboard")
        multi_horizon = self._status(statuses, "multi_horizon_paper_trading")
        horizon_coverage = self._status(statuses, "horizon_coverage_summary")
        profit_capture = self._status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        shadow_lab = self._status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        accelerated = self._status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        convergence = self._status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        memory = self._status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        catalyst = self._status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        lifecycle = self._status(statuses, "trade_lifecycle_excursion_v2")
        allocator = self._status(statuses, "adaptive_learning_prioritization_resource_allocation_v1")

        horizon_stats, dominant_paper_horizon, best_horizon, weakest_horizon = self._horizon_stats(horizon_dashboard)
        fine_missing = list((horizon_coverage.get("missing_horizons") or {}).get("fine") or horizon_coverage.get("fine_hold_buckets_missing") or [])
        horizons_tested = list(dict.fromkeys(list(horizon_coverage.get("tested_horizons") or []) + ["scalp", "day_trade", "swing_trade"]))
        symbol_dna, best_symbol_horizon, worst_symbol_horizon = self._symbol_dna(accelerated, convergence, memory)
        readiness = self._readiness(horizon_stats, horizon_coverage)

        strongest_setup_horizon = _text(profit_capture.get("best_exit_policy"), _text(convergence.get("best_symbol_horizon_pair"), "insufficient_data"))
        strongest_catalyst_horizon = _text(catalyst.get("best_horizon_by_catalyst") or catalyst.get("best_catalyst_horizon"), "insufficient_data")
        strongest_peer_group = _text(accelerated.get("strongest_peer_group_behavior") or accelerated.get("strongest_symbol_cluster"), "insufficient_data")
        dominant_shadow_horizon = _text(shadow_lab.get("best_horizon"), _text(multi_horizon.get("best_current_horizon"), "insufficient_data"))
        mismatch_risk = _clamp(
            _to_float(horizon_coverage.get("horizon_mismatch_risk_score"), 0.0)
            + (10.0 if _text(shadow_lab.get("best_horizon"), "") == "hold_duration" else 0.0)
            + (10.0 if not fine_missing else 0.0)
        )
        symbols_affected = [
            value for value in [
                _text(memory.get("highest_giveback_symbol"), ""),
                _text(convergence.get("highest_gap_symbol"), ""),
                _text(accelerated.get("highest_giveback_symbol"), ""),
            ] if value
        ][:6]
        setups_affected = [strongest_setup_horizon, _text(allocator.get("highest_value_learning_focus"), "hold_duration")]
        average_gap = abs(_to_float(convergence.get("average_convergence_gap"), 0.0))
        avg_giveback = _to_float(profit_capture.get("average_giveback_pct"), 0.0)
        estimated_profit_lost = round(average_gap * max(1, _to_int(convergence.get("tracked_trades"), _to_int(profit_capture.get("tracked_trades"), 0))), 4)
        estimated_giveback = round(avg_giveback * max(1, _to_int(profit_capture.get("tracked_trades"), 0)), 4)

        lifecycle_flags = {
            "should_have_scalped": bool(best_horizon == "scalp" or weakest_horizon == "swing_trade"),
            "should_have_day_traded": bool(best_horizon == "day_trade" or _text(allocator.get("highest_value_learning_focus"), "") in {"hold_duration", "profit_capture"}),
            "should_have_swung": bool(best_horizon == "swing_trade"),
            "held_too_long": bool(mismatch_risk >= 65 or _text(horizon_coverage.get("paper_horizon_bias"), "") == "swing_trade_bias"),
            "exited_too_early": bool(_to_float(profit_capture.get("average_capture_ratio"), 0.0) >= 0.75 and best_horizon == "swing_trade"),
            "profit_protection_needed": bool(_to_float(profit_capture.get("capture_quality_score"), 100.0) < 55.0 or avg_giveback > 10.0),
            "continuation_supported": bool(_to_float(profit_capture.get("continuation_failure_probability"), 0.0) < 45.0),
            "catalyst_decay_detected": bool(_text(allocator.get("top_weakness"), "") == "catalyst_decay" or _text(shadow_lab.get("top_failure_pattern"), "") == "catalyst_decay"),
        }
        next_test = _text(
            horizon_coverage.get("next_recommended_horizon_test"),
            "Expand 15m-60m and 2h-EOD shadow comparisons before changing paper behavior.",
        )
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_multi_horizon_adaptive_lifecycle",
            "generated_at": _now_iso(),
            "suite_status": "active_shadow_diagnostics",
            "horizons_tested": horizons_tested,
            "missing_horizons": {
                "fine": fine_missing,
                "coarse": list(horizon_coverage.get("coarse_missing_horizons") or []),
            },
            "horizon_outcomes": horizon_stats,
            "virtual_paths_per_horizon": {k: _to_int(v.get("evidence_count"), 0) for k, v in horizon_stats.items()},
            "learning_events_per_horizon": {k: _to_int(v.get("evidence_count"), 0) for k, v in horizon_stats.items()},
            "closed_trades_per_horizon": {k: _to_int(v.get("evidence_count"), 0) for k, v in horizon_stats.items()},
            "paper_trades_per_horizon": dict(horizon_coverage.get("paper_entries_today_by_horizon") or {}),
            "shadow_trades_per_horizon": {k: _to_int(v.get("evidence_count"), 0) for k, v in horizon_stats.items()},
            "dominant_paper_horizon": dominant_paper_horizon,
            "dominant_shadow_horizon": dominant_shadow_horizon,
            "best_horizon": best_horizon,
            "weakest_horizon": weakest_horizon,
            "horizon_mismatch_risk_score": round(mismatch_risk, 2),
            "predicted_horizon": dominant_paper_horizon,
            "actual_best_horizon": best_horizon,
            "horizon_mismatch_detected": bool(mismatch_risk >= 50.0),
            "symbols_most_affected": symbols_affected,
            "setups_most_affected": setups_affected,
            "estimated_profit_lost_to_horizon_mismatch": estimated_profit_lost,
            "estimated_giveback_from_wrong_horizon": estimated_giveback,
            "symbol_horizon_dna": symbol_dna,
            "best_symbol_horizon": best_symbol_horizon,
            "worst_symbol_horizon": worst_symbol_horizon,
            "strongest_setup_horizon": strongest_setup_horizon,
            "strongest_catalyst_horizon": strongest_catalyst_horizon,
            "strongest_regime_horizon": _text(convergence.get("best_regime_by_symbol") or accelerated.get("best_regime_by_symbol"), "insufficient_data"),
            "strongest_peer_group_pattern": strongest_peer_group,
            "peer_groups": PEER_GROUPS,
            "peer_best_horizon": _text(accelerated.get("best_peer_group_horizon"), _first_value(accelerated.get("best_horizon_by_symbol"))),
            "peer_exit_style": _text(accelerated.get("best_peer_group_exit_style"), _first_value(accelerated.get("best_exit_style_by_symbol"))),
            "peer_catalyst_decay": _text(shadow_lab.get("top_failure_pattern"), "insufficient_data"),
            "peer_profit_capture": _text(profit_capture.get("best_exit_policy"), "insufficient_data"),
            "transfer_confidence": _to_float(accelerated.get("transferable_learning_confidence"), _to_float(accelerated.get("peer_group_learning_score"), 0.0)),
            "horizon_readiness": readiness,
            "lifecycle_flags": lifecycle_flags,
            "entry_timing": _text(lifecycle.get("entry_timing_status"), "tracked_shadow_only"),
            "first_profit_milestone": _text(profit_capture.get("strongest_profit_milestone"), "insufficient_data"),
            "peak_profit": _to_float(lifecycle.get("average_peak_profit_pct"), 0.0),
            "profit_decay": _to_float(profit_capture.get("average_giveback_pct"), 0.0),
            "hold_quality": _to_float(profit_capture.get("hold_duration_quality_score"), 0.0),
            "opportunity_cost": _to_float(convergence.get("average_convergence_gap"), 0.0),
            "learned_exits_applied": False,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
            "behavior_safe_to_apply": False,
            "next_recommended_test": next_test,
            "shadow_recommendation": "Keep horizon intelligence shadow-only; expand missing fine buckets and require human review before any learned exits.",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "portfolio_allocation_changed": False,
            "order_logic_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "forced_trades_enabled": False,
            "auto_apply_allowed": False,
            "human_review_required": True,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
        }
        _write_json(self.cache_path, out)
        return out

    def _cached(self) -> dict[str, Any]:
        cached = _read_json(self.cache_path)
        if not cached:
            return {}
        try:
            age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
        except Exception:
            age = DASHBOARD_CACHE_MAX_AGE_SECONDS + 1
        cached["cache_hit"] = True
        cached["cache_age_seconds"] = round(age, 3)
        cached["behavior_safe_to_apply"] = False
        return cached

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["behavior_safe_to_apply"] = False
            return out
        if not force:
            cached = self._cached()
            if cached and _to_float(cached.get("cache_age_seconds"), 999999.0) <= DASHBOARD_CACHE_MAX_AGE_SECONDS:
                self._cache = cached
                self._cache_ts = now
                return cached
        try:
            out = self._build(statuses or {})
            out["cache_hit"] = False
            out["cache_age_seconds"] = 0.0
            self._cache = out
            self._cache_ts = now
            return out
        except Exception as exc:
            cached = self._cached()
            if cached:
                cached["stale_cache"] = True
                cached["degraded_reason"] = f"multi_horizon_intelligence_rebuild_failed_using_cache:{str(exc)[:140]}"
                cached["behavior_safe_to_apply"] = False
                return cached
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_shadow_multi_horizon_adaptive_lifecycle",
                "suite_status": "unavailable",
                "horizons_tested": [],
                "missing_horizons": {"fine": HORIZON_BUCKETS, "coarse": ["scalp", "day_trade", "swing_trade"]},
                "dominant_paper_horizon": "unavailable",
                "dominant_shadow_horizon": "unavailable",
                "best_horizon": "unavailable",
                "weakest_horizon": "unavailable",
                "horizon_mismatch_risk_score": 0.0,
                "best_symbol_horizon": "unavailable",
                "worst_symbol_horizon": "unavailable",
                "strongest_setup_horizon": "unavailable",
                "strongest_catalyst_horizon": "unavailable",
                "strongest_peer_group_pattern": "unavailable",
                "estimated_profit_lost_to_horizon_mismatch": 0.0,
                "learned_exits_applied": False,
                "behavior_safe_to_apply": False,
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "dashboard_scan_rows": 0,
                "raw_history_scanned": False,
                "raw_archive_scanned": False,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "ranking_behavior_changed": False,
                "paper_execution_behavior_changed": False,
                "position_sizing_changed": False,
                "thresholds_changed": False,
                "portfolio_allocation_changed": False,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_exits_enabled": False,
                "degraded_reason": f"multi_horizon_intelligence_adaptive_lifecycle_suite_v1_unavailable:{str(exc)[:140]}",
            }
