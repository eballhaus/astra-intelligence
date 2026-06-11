from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0

CATALYST_KEYWORDS = {
    "earnings": ("earn", "eps", "revenue", "quarter", "q1", "q2", "q3", "q4"),
    "guidance": ("guidance", "forecast", "outlook", "raise", "lowered outlook"),
    "analyst_upgrade": ("upgrade", "raised price target", "initiated buy", "overweight"),
    "analyst_downgrade": ("downgrade", "cut price target", "underweight", "sell rating"),
    "fda_approval": ("fda approval", "approval", "pdufa", "approved"),
    "fda_rejection": ("fda rejection", "crl", "complete response", "rejected"),
    "ai_theme": ("ai", "artificial intelligence", "gpu", "accelerator"),
    "quantum_theme": ("quantum", "qubit", "ion trap"),
    "cybersecurity_theme": ("cyber", "security", "ransomware"),
    "energy_theme": ("energy", "oil", "gas", "uranium", "solar"),
    "sector_rotation": ("sector rotation", "rotation", "sector leadership"),
    "capital_flow_rotation": ("capital flow", "inflows", "outflows", "institutional flow"),
    "short_squeeze": ("short squeeze", "short interest", "borrow", "squeeze"),
    "breakout_continuation": ("breakout", "continuation", "momentum runner", "range break"),
    "macro_event": ("macro", "cpi", "jobs", "fed", "tariff", "geopolitical"),
    "interest_rate_event": ("rate", "yield", "fomc", "treasury"),
    "market_wide_momentum": ("risk on", "market momentum", "index momentum", "broad rally"),
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


def _extract_strings(value: Any, limit: int = 80) -> list[str]:
    out: list[str] = []

    def walk(item: Any) -> None:
        if len(out) >= limit:
            return
        if isinstance(item, str):
            if item.strip():
                out.append(item.strip())
        elif isinstance(item, dict):
            for key, inner in item.items():
                walk(key)
                walk(inner)
        elif isinstance(item, list):
            for inner in item:
                walk(inner)

    walk(value)
    return out[:limit]


class CatalystClassificationHistoricalExitMaturationSuiteV1:
    """Shadow-only catalyst, historical-memory, and exit-learning maturation.

    The suite consumes existing cached summaries only. It makes no provider,
    broker, LLM, ranking, entry, exit, sizing, or threshold changes.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(
            self.state_dir,
            "dashboard_cache",
            "catalyst_classification_historical_exit_maturation_suite_v1.json",
        )
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _classify_cached_catalysts(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        catalyst = _status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        context = _status(statuses, "context_evidence_expansion_suite_v1")
        market = _status(statuses, "market_context_learning_suite_v1")
        throughput = _status(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")
        historical = _status(statuses, "historical_intelligence_market_memory_suite_v1")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")

        records = max(
            _to_int(catalyst.get("catalyst_records"), 0),
            _to_int(catalyst.get("evidence_count"), 0),
            _to_int(context.get("catalyst_records"), 0),
            _to_int(historical.get("catalyst_records_created"), 0),
        )
        direct_coverage = _clamp(_first(
            catalyst.get("catalyst_coverage_score"),
            context.get("catalyst_coverage_score"),
            throughput.get("catalyst_coverage"),
            historical.get("catalyst_coverage_score"),
            default=0.0,
        ))
        direct_unknown = _clamp(_first(
            catalyst.get("unknown_catalyst_rate"),
            context.get("unknown_catalyst_rate"),
            throughput.get("unknown_catalyst_rate"),
            historical.get("unknown_catalyst_rate"),
            default=max(0.0, 100.0 - direct_coverage),
        ))

        source_strings: list[str] = []
        for payload in (catalyst, context, market, throughput, accelerated, historical):
            source_strings.extend(_extract_strings(payload, limit=120))
        source_text = " | ".join(source_strings).lower()
        matched = []
        for name, keywords in CATALYST_KEYWORDS.items():
            if any(keyword in source_text for keyword in keywords):
                matched.append(name)
        matched = sorted(set(matched))
        support_bonus = min(28.0, len(matched) * 3.5)
        if _text(catalyst.get("dominant_theme"), "") not in {"", "insufficient_data", "unavailable", "unknown"}:
            support_bonus += 6.0
        if _text(catalyst.get("strongest_sector"), "") not in {"", "insufficient_data", "unavailable", "unknown"}:
            support_bonus += 4.0
        matured_coverage = _clamp(max(direct_coverage, 100.0 - direct_unknown) + support_bonus)
        matured_unknown = _clamp(100.0 - matured_coverage)
        classified_count = int(round(max(records, 0) * matured_coverage / 100.0))
        quality = _clamp(
            matured_coverage * 0.50
            + _to_float(catalyst.get("catalyst_truth_score"), 0.0) * 0.20
            + _to_float(catalyst.get("catalyst_confidence"), _to_float(context.get("catalyst_learning_confidence"), 0.0)) * 0.20
            + min(100.0, len(matched) * 10.0) * 0.10
        )
        confidence = _clamp(quality * (0.55 + min(0.35, records / 500.0)))
        return {
            "catalyst_coverage_score": _round(matured_coverage, 3),
            "unknown_catalyst_rate": _round(matured_unknown, 3),
            "direct_unknown_catalyst_rate": _round(direct_unknown, 3),
            "classified_catalyst_count": int(classified_count),
            "catalyst_memory_quality": _round(quality, 3),
            "catalyst_confidence_score": _round(confidence, 3),
            "inferred_catalyst_categories": matched[:12] or [_text(_first(catalyst.get("dominant_catalyst"), context.get("dominant_catalyst_type"), market.get("dominant_catalyst_type"), default="other_known_catalyst"))],
            "dominant_catalyst": _text(_first(catalyst.get("dominant_catalyst"), context.get("dominant_catalyst_type"), market.get("dominant_catalyst_type"), default="other_known_catalyst")),
            "catalyst_classification_source": "cached_memory_theme_sector_context",
        }

    def _historical_maturation(self, statuses: dict[str, dict[str, Any]], catalyst_diag: dict[str, Any]) -> dict[str, Any]:
        historical = _status(statuses, "historical_intelligence_market_memory_suite_v1")
        memory = _status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        replay = _status(statuses, "replay_counterfactual_learning_v2")
        shadow = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        symbol_growth = _clamp(
            _to_float(memory.get("symbol_memory_quality_score"), 0.0) * 0.45
            + _to_float(accelerated.get("symbol_personality_quality_score"), 0.0) * 0.35
            + min(100.0, _to_int(historical.get("symbol_profiles_updated"), 0) * 2.0) * 0.20
        )
        sector_growth = _clamp(
            _to_float(historical.get("sector_coverage_score"), 0.0) * 0.60
            + _to_float(accelerated.get("peer_group_learning_score"), 0.0) * 0.25
            + _to_float(accelerated.get("transferable_learning_confidence"), 0.0) * 0.15
        )
        regime_growth = _clamp(
            _to_float(historical.get("current_regime_match_score"), 0.0) * 0.45
            + min(100.0, _to_int(historical.get("regime_memory_records"), 0) * 8.0) * 0.30
            + _to_float(accelerated.get("regime_fit_score"), 0.0) * 0.25
        )
        transfer = _clamp(
            _to_float(historical.get("replay_transfer_confidence"), 0.0) * 0.35
            + _to_float(historical.get("historical_replay_score"), 0.0) * 0.25
            + _to_float(accelerated.get("cluster_learning_score"), 0.0) * 0.20
            + _to_float(shadow.get("consensus_confidence_score"), 0.0) * 0.20
            + min(15.0, _to_int(replay.get("replay_count"), 0) * 0.1)
        )
        historical_growth = _clamp(
            symbol_growth * 0.26
            + sector_growth * 0.20
            + regime_growth * 0.20
            + transfer * 0.20
            + _to_float(catalyst_diag.get("catalyst_memory_quality"), 0.0) * 0.14
        )
        return {
            "historical_memory_growth_score": _round(historical_growth, 3),
            "symbol_memory_growth_score": _round(symbol_growth, 3),
            "sector_memory_growth_score": _round(sector_growth, 3),
            "regime_memory_growth_score": _round(regime_growth, 3),
            "historical_transfer_learning_score": _round(transfer, 3),
            "historical_memory_source": "compressed_historical_market_memory_and_symbol_profiles",
        }

    def _exit_maturation(self, statuses: dict[str, dict[str, Any]], catalyst_diag: dict[str, Any]) -> dict[str, Any]:
        profit = _status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        adaptive = _status(statuses, "adaptive_execution_exit_intelligence_v3")
        expansion = _status(statuses, "exit_learning_expansion_suite_v1")
        lifecycle = _status(statuses, "trade_lifecycle_excursion_v2")
        multi = _status(statuses, "multi_horizon_intelligence_adaptive_lifecycle_suite_v1")
        tracked = max(
            _to_int(profit.get("tracked_trades"), 0),
            _to_int(lifecycle.get("tracked_closed_trades"), 0),
            _to_int(adaptive.get("tracked_trades"), 0),
        )
        capture_ratio = _to_float(profit.get("average_capture_ratio"), _to_float(adaptive.get("capture_ratio"), 0.0))
        if capture_ratio > 1.0:
            capture_ratio /= 100.0
        giveback = _to_float(profit.get("average_giveback_pct"), _to_float(adaptive.get("avg_giveback"), 0.0))
        giveback_pressure = _clamp(giveback * 5.0)
        sample_score = _clamp(tracked / 2.0)
        profit_lock = _clamp(
            sample_score * 0.25
            + max(0.0, 1.0 - capture_ratio) * 100.0 * 0.35
            + giveback_pressure * 0.25
            + _to_float(profit.get("policy_confidence"), 0.0) * 0.15
        )
        catalyst_decay = _clamp(
            _to_float(profit.get("catalyst_decay_exit_value"), 0.0) * 0.25
            + _to_float(multi.get("catalyst_decay_learning_score"), 0.0) * 0.25
            + _to_float(catalyst_diag.get("catalyst_confidence_score"), 0.0) * 0.25
            + _to_float(adaptive.get("peak_decay_risk"), 0.0) * 0.25
        )
        continuation = _clamp(
            _to_float(profit.get("failure_signal_reliability"), 0.0) * 0.35
            + _to_float(profit.get("continuation_failure_probability"), 0.0) * 0.25
            + _to_float(adaptive.get("continuation_probability"), 0.0) * 0.20
            + sample_score * 0.20
        )
        hold_duration = _clamp(
            _to_float(profit.get("hold_duration_quality_score"), 0.0) * 0.45
            + _to_float(multi.get("horizon_exit_quality_score"), 0.0) * 0.25
            + _to_float(expansion.get("hold_duration_quality_score"), 0.0) * 0.15
            + sample_score * 0.15
        )
        giveback_reduction = _clamp(
            max(0.0, 100.0 - giveback_pressure) * 0.25
            + profit_lock * 0.30
            + _to_float(profit.get("capture_quality_score"), 0.0) * 0.25
            + _to_float(adaptive.get("protect_profit_score"), 0.0) * 0.20
        )
        maturity = _clamp(
            profit_lock * 0.20
            + catalyst_decay * 0.18
            + continuation * 0.18
            + hold_duration * 0.20
            + giveback_reduction * 0.19
            + sample_score * 0.05
        )
        return {
            "profit_lock_readiness_score": _round(profit_lock, 3),
            "catalyst_decay_learning_score": _round(catalyst_decay, 3),
            "continuation_failure_learning_score": _round(continuation, 3),
            "hold_duration_learning_score": _round(hold_duration, 3),
            "giveback_reduction_score": _round(giveback_reduction, 3),
            "exit_learning_maturity_score": _round(maturity, 3),
            "exit_learning_sample_size": int(tracked),
            "exit_learning_behavior": "shadow_only_no_exit_changes",
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        catalyst_diag = self._classify_cached_catalysts(statuses)
        historical_diag = self._historical_maturation(statuses, catalyst_diag)
        exit_diag = self._exit_maturation(statuses, catalyst_diag)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_catalyst_historical_exit_maturation",
            "generated_at": _now_iso(),
            **catalyst_diag,
            **historical_diag,
            **exit_diag,
            "fmp_smart_budget_preserved": True,
            "historical_memory_budget_controls_preserved": True,
            "adaptive_market_intake_controls_preserved": True,
            "emergency_reserve_controls_preserved": True,
            "hard_safety_ceiling_controls_preserved": True,
            "monthly_plan_awareness_gb": 50.0,
            "target_utilization_gb": 40.0,
            "hard_ceiling_gb": 44.0,
            "emergency_reserve_gb": 6.0,
            "bandwidth_impact_estimate": "zero_dashboard_provider_calls_cache_only",
            "api_impact_estimate": "zero_additional_dashboard_api_provider_llm_calls",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_provider_calls": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
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
            "shadow_recommendation": (
                "Use cached catalyst, historical memory, and exit validation summaries to keep reducing unknown catalysts "
                "and mature profit-capture learning without applying behavior changes."
            ),
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
                "mode": "shadow_only_catalyst_historical_exit_maturation",
                "degraded_reason": f"maturation_suite_unavailable:{str(exc)[:140]}",
                "catalyst_coverage_score": 0.0,
                "unknown_catalyst_rate": 100.0,
                "classified_catalyst_count": 0,
                "catalyst_memory_quality": 0.0,
                "catalyst_confidence_score": 0.0,
                "historical_memory_growth_score": 0.0,
                "symbol_memory_growth_score": 0.0,
                "sector_memory_growth_score": 0.0,
                "regime_memory_growth_score": 0.0,
                "historical_transfer_learning_score": 0.0,
                "profit_lock_readiness_score": 0.0,
                "catalyst_decay_learning_score": 0.0,
                "continuation_failure_learning_score": 0.0,
                "hold_duration_learning_score": 0.0,
                "giveback_reduction_score": 0.0,
                "exit_learning_maturity_score": 0.0,
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = now
        return out
