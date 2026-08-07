"""Bounded, read-only context for Astra Trading Intelligence Suite V2.

The module deliberately composes existing canonical broker truth, existing
symbol profiles, advisory opportunity-cost summaries, shadow diagnostics, and
summary indexes.  It is not an execution, promotion, or persistence engine.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from engine.astra_trading_intelligence_improvement_v1 import (
    SAFETY as V1_SAFETY,
    build_trading_intelligence_improvement_suite_v1,
)


VERSION = "1.0.0"
MAX_STRICT_TRUTHS = 500
STABLE_PROFILE_MINIMUM = 20
METRIC_MINIMUM = 5
STRICT_STATES = {
    "STRICT_TRUTH",
    "BROKER_TRUTH_CONFIRMED",
    "BROKER_CONFIRMED_COMPLETE",
    "COMPLETE",
}

SAFETY = {
    **V1_SAFETY,
    "shadow_analysis_mode": True,
    "advisory_only": True,
    "ranking_behavior_changed": False,
    "promotion_logic_changed": False,
    "paper_execution_changed": False,
    "automatic_replacement_authority": False,
    "automatic_promotion_authority": False,
    "full_history_scan_count": 0,
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _number(value: Any) -> float | None:
    try:
        if value in (None, "", "UNAVAILABLE"):
            return None
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _text(value: Any, fallback: str = "UNAVAILABLE") -> str:
    value = str(value or "").strip()
    return value.upper() if value else fallback


def _time() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strict_truths(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in registry.get("records") or []:
        if not isinstance(item, Mapping):
            continue
        # Reconstructed historical broker rows are valuable diagnostics but
        # cannot be promoted to this suite's strict tier without truth_state.
        if _text(item.get("truth_state")) not in STRICT_STATES:
            continue
        key = str(item.get("stable_key") or item.get("lifecycle_id") or item.get("exit_fill_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(dict(item))
        if len(rows) >= MAX_STRICT_TRUTHS:
            break
    return rows


def _return(row: Mapping[str, Any]) -> float | None:
    for key in ("realized_return", "realized_return_pct", "return_pct", "pnl_pct"):
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _context(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("pretrade_context_v1")
    return value if isinstance(value, Mapping) else {}


def _field(row: Mapping[str, Any], *keys: str, fallback: str = "UNAVAILABLE") -> str:
    context = _context(row)
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            value = context.get(key)
        if value not in (None, ""):
            return _text(value, fallback)
    return fallback


def _profile_status(sample_size: int) -> str:
    if sample_size >= STABLE_PROFILE_MINIMUM:
        return "STABLE_PROFILE"
    if sample_size > 0:
        return "EARLY_PROFILE"
    return "INSUFFICIENT_EVIDENCE"


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for value in (_return(row) for row in rows) if value is not None]
    profits = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    holds = [value for value in (_number(row.get("hold_duration")) for row in rows) if value is not None]
    mfe = [value for value in (_number(row.get("mfe")) for row in rows) if value is not None]
    mae = [value for value in (_number(row.get("mae")) for row in rows) if value is not None]
    giveback = [value for value in (_number(row.get("profit_giveback")) for row in rows) if value is not None]
    sample = len(rows)
    metric_valid = len(returns) >= METRIC_MINIMUM
    return {
        "sample_size": sample,
        "return_sample_size": len(returns),
        "win_rate_pct": round(sum(value > 0 for value in returns) * 100 / len(returns), 3) if returns else None,
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "expectancy_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "profit_factor": round(profits / losses, 4) if metric_valid and losses > 0 else None,
        "profit_factor_status": "OBSERVATIONAL" if metric_valid and losses > 0 else "INSUFFICIENT_EVIDENCE",
        "average_hold_duration_seconds": round(sum(holds) / len(holds), 3) if holds else None,
        "median_hold_duration_seconds": round(median(holds), 3) if holds else None,
        "average_mfe": round(sum(mfe) / len(mfe), 4) if mfe else None,
        "average_mae": round(sum(mae) / len(mae), 4) if mae else None,
        "average_profit_giveback": round(sum(giveback) / len(giveback), 4) if giveback else None,
        "metrics_status": "OBSERVATIONAL" if metric_valid else "INSUFFICIENT_EVIDENCE",
    }


def _index_counts(index: Mapping[str, Any]) -> dict[str, int]:
    values = index.get("dimension_counts")
    if not isinstance(values, Mapping):
        return {}
    return {str(key): sum(int(_number(value) or 0) for value in bucket.values()) for key, bucket in values.items() if isinstance(bucket, Mapping)}


def _symbol_profiles(strict_rows: list[dict[str, Any]], existing: Mapping[str, Any], shadow: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in strict_rows:
        grouped[_field(row, "symbol")].append(row)
    source_profiles = existing.get("profiles") if isinstance(existing.get("profiles"), Mapping) else {}
    symbols = sorted(set(grouped) | {str(key).upper() for key in source_profiles})
    shadow_sample = int(_number(shadow.get("completed_shadow_lifecycles")) or 0)
    output = []
    for symbol in symbols:
        rows = grouped.get(symbol, [])
        profile = source_profiles.get(symbol) or source_profiles.get(symbol.lower()) or {}
        metrics = _metrics(rows)
        strict_sample = len(rows)
        findings: list[str] = []
        if strict_sample >= METRIC_MINIMUM:
            horizons = defaultdict(int)
            for row in rows:
                horizons[_field(row, "paper_entry_horizon_style", "intended_horizon", "horizon", "lane_id")] += 1
            favored = max(horizons, key=horizons.get) if horizons else "UNAVAILABLE"
            if favored in {"DAY", "DAY_TRADE"}:
                findings.append("DAY_FAVORED")
            elif favored == "SCALP":
                findings.append("SCALP_FAVORED")
            elif favored == "SWING":
                findings.append("SWING_FAVORED")
        output.append({
            "symbol": symbol,
            "asset_class": _field(rows[0], "asset_class", "instrument_type", fallback="UNAVAILABLE") if rows else "UNAVAILABLE",
            "profile_status": _profile_status(strict_sample),
            "evidence_tier": "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH" if strict_sample else "DERIVED_PROFILE_ONLY",
            "strict_truth_sample_size": strict_sample,
            "shadow_sample_size_separate": shadow_sample,
            "derived_profile_sample_size": int(_number(profile.get("sample_size")) or 0),
            "best_performing_horizon": _text(profile.get("best_horizon")) if strict_sample >= METRIC_MINIMUM else "UNAVAILABLE",
            "worst_performing_horizon": _text(profile.get("worst_horizon")) if strict_sample >= METRIC_MINIMUM else "UNAVAILABLE",
            "preferred_exit_style": _text(profile.get("best_exit_style")) if strict_sample >= METRIC_MINIMUM else "UNAVAILABLE",
            "common_failure_patterns": list(profile.get("warning_flags") or [])[:5] if isinstance(profile, Mapping) else [],
            "observational_findings": findings,
            "automatic_weighting_eligible": False,
            "future_weighting_review_eligible": strict_sample >= STABLE_PROFILE_MINIMUM,
            **metrics,
        })
    return sorted(output, key=lambda row: (-int(row["strict_truth_sample_size"]), str(row["symbol"])))


def _regime_profiles(strict_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in strict_rows:
        grouped[_field(row, "market_regime", "regime", "regime_context")].append(row)
    output = []
    for regime, rows in sorted(grouped.items()):
        metrics = _metrics(rows)
        horizons = sorted({_field(row, "paper_entry_horizon_style", "intended_horizon", "horizon", "lane_id") for row in rows})
        output.append({
            "regime": regime,
            "evidence_tier": "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH",
            "profile_status": _profile_status(len(rows)),
            "lanes": sorted({_field(row, "lane_id") for row in rows}),
            "horizons": horizons,
            "prediction_accuracy_status": "UNAVAILABLE_ORIGINAL_PRETRADE_DIRECTION_MISSING",
            "confidence_calibration_status": "INSUFFICIENT_EVIDENCE" if len(rows) < METRIC_MINIMUM else "OBSERVATIONAL",
            "automatic_regime_action_eligible": False,
            **metrics,
        })
    return output


def _opportunity_cost(advisory: Mapping[str, Any], index: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for item in advisory.get("positions") or []:
        if not isinstance(item, Mapping):
            continue
        state = _text(item.get("opportunity_cost_state") or item.get("final_advisory") or "WATCH")
        rows.append({
            "symbol": _text(item.get("symbol")),
            "state": state,
            "current_return_pct": _number(item.get("unrealized_plpc") or item.get("return_pct")),
            "thesis_strength": (item.get("evidence_used") or {}).get("thesis_state") if isinstance(item.get("evidence_used"), Mapping) else "UNAVAILABLE",
            "replacement_candidate": item.get("replacement_candidate") or "UNAVAILABLE",
            "authority": "ADVISORY_ONLY_EXISTING_NATIVE_EXIT_AUTHORITY_PRESERVED",
            "automatic_replacement_authority": False,
        })
    states = defaultdict(int)
    for row in rows:
        states[row["state"]] += 1
    return {
        "status": "OBSERVATIONAL" if rows else "INSUFFICIENT_EVIDENCE",
        "active_position_count": len(rows),
        "state_counts": dict(sorted(states.items())),
        "positions": rows[:100],
        "summary_index_dimensions": _index_counts(index),
        "native_exit_authority": "UNCHANGED",
        "automatic_replacement_authority": False,
        "automatic_rotation_authority": False,
    }


def _shadow_validation(shadow: Mapping[str, Any], shadow_perf: Mapping[str, Any]) -> dict[str, Any]:
    sample = int(_number(shadow.get("completed_shadow_lifecycles")) or 0)
    pf = _number(shadow.get("crypto_profit_factor") or shadow.get("shadow_profit_factor"))
    if pf is None:
        pf = _number(shadow_perf.get("lifetime_shadow_pf") or shadow_perf.get("shadow_profit_factor_verified"))
    paper_pf = _number(shadow_perf.get("canonical_profit_factor") or shadow_perf.get("lifetime_paper_pf"))
    quality = _number(shadow.get("evidence_quality_score")) or 0.0
    consistency = _number(shadow.get("consensus_confidence_score")) or 0.0
    outperforms_paper = pf is not None and paper_pf is not None and pf > paper_pf
    human_review_candidate = sample >= 50 and quality >= 70 and consistency >= 70 and outperforms_paper
    blockers = []
    if sample < 50:
        blockers.append("SHADOW_SAMPLE_BELOW_50")
    if quality < 70:
        blockers.append("SHADOW_EVIDENCE_QUALITY_BELOW_70")
    if consistency < 70:
        blockers.append("SHADOW_REPEATABILITY_BELOW_70")
    if not outperforms_paper:
        blockers.append("SHADOW_OUTPERFORMANCE_NOT_VERIFIED_AGAINST_PAPER")
    return {
        "evidence_tier": "SHADOW_COUNTERFACTUAL_DISTINCT_FROM_BROKER_TRUTH",
        "shadow_sample_size": sample,
        "shadow_profit_factor": pf if sample >= METRIC_MINIMUM else None,
        "shadow_profit_factor_status": "OBSERVATIONAL" if sample >= METRIC_MINIMUM and pf is not None else "INSUFFICIENT_EVIDENCE",
        "shadow_win_rate": _number(shadow.get("crypto_win_rate") or shadow.get("shadow_win_rate")),
        "shadow_average_return": _number(shadow.get("crypto_avg_return") or shadow.get("shadow_avg_return")),
        "shadow_exit_effectiveness": _number(shadow.get("execution_realism_score") or shadow.get("evidence_quality_score")),
        "rejection_accuracy_status": "UNAVAILABLE_WITHOUT_CANDIDATE_LEVEL_SHADOW_OUTCOMES",
        "promotion_status": "HUMAN_REVIEW_ONLY" if human_review_candidate else "COLLECT_MORE_SHADOW_EVIDENCE",
        "promotion_gate": {
            "minimum_shadow_sample": 50,
            "minimum_evidence_quality": 70,
            "minimum_repeatability": 70,
            "paper_outperformance_required": True,
            "paper_profit_factor": paper_pf,
            "shadow_evidence_quality": quality,
            "shadow_repeatability": consistency,
            "shadow_outperforms_paper": outperforms_paper,
            "passed": human_review_candidate,
            "automatic_promotion_disabled": True,
        },
        "promotion_blockers": blockers,
        "automatic_promotion_authority": False,
        "shadow_may_count_as_strict_truth": False,
    }


def _retrieve(symbol_profiles: list[dict[str, Any]], regime_profiles: list[dict[str, Any]], query: Mapping[str, Any]) -> dict[str, Any]:
    symbol = _text(query.get("symbol"), "")
    regime = _text(query.get("regime"), "")
    horizon = _text(query.get("horizon"), "")
    results = []
    for profile in symbol_profiles:
        if symbol and profile["symbol"] != symbol:
            continue
        if horizon and profile.get("best_performing_horizon") not in {horizon, "UNAVAILABLE"}:
            continue
        results.append({"kind": "symbol_profile", **profile})
    for profile in regime_profiles:
        if regime and profile["regime"] != regime:
            continue
        if horizon and horizon not in profile.get("horizons", []):
            continue
        results.append({"kind": "regime_profile", **profile})
    return {
        "query": {key: value for key, value in query.items() if value not in (None, "")},
        "results": results[:50],
        "result_count": len(results[:50]),
        "index_used": "IN_MEMORY_BOUNDED_V2_CONTEXT_INDEX",
        "full_history_scan_used": False,
        "full_history_scan_count": 0,
        "cache_hit": False,
        "fallback_used": False,
    }


def build_trading_intelligence_improvement_suite_v2(
    state_dir: str = "state", query: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return tier-separated V2 context from bounded existing state only."""
    state = Path(state_dir)
    registry = _read(state / "broker_truth_records_v1.json")
    profiles = _read(state / "symbol_behavior_profiles_v1.json")
    advisory = _read(state / "astra_unified_position_advisory_v1.json")
    shadow = _read(state / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json")
    shadow_perf = _read(state / "dashboard_cache" / "shadow_vs_paper_performance_attribution_v1.json")
    market_index = _read(state / "storage_summary_indexes" / "market_context_learning_suite_v1.jsonl.summary_index.json")
    opportunity_index = _read(state / "storage_summary_indexes" / "opportunity_cost_learning_v1.jsonl.summary_index.json")
    strict_rows = _strict_truths(registry)
    symbol = _symbol_profiles(strict_rows, profiles, shadow)
    regime = _regime_profiles(strict_rows)
    retrieval = _retrieve(symbol, regime, query or {})
    v1 = build_trading_intelligence_improvement_suite_v1(state_dir)
    return {
        "suite": "ASTRA Trading Intelligence Improvement Suite V2",
        "version": VERSION,
        "generated_at": _time(),
        "status": "OBSERVATIONAL_READY" if strict_rows else "INSUFFICIENT_EVIDENCE",
        "canonical_input": {
            "strict_truth_registry": "broker_truth_records_v1",
            "strict_truth_count": len(strict_rows),
            "strict_truth_read_cap": MAX_STRICT_TRUTHS,
            "strict_truth_only": True,
            "shadow_truth_contamination_detected": False,
        },
        "symbol_intelligence": {
            "profiles": symbol,
            "profile_count": len(symbol),
            "existing_profile_source": "symbol_behavior_profiles_v1",
            "sample_size_gate": {"early_profile": 1, "stable_profile": STABLE_PROFILE_MINIMUM, "metric_minimum": METRIC_MINIMUM},
        },
        "market_regime_intelligence": {
            "profiles": regime,
            "profile_count": len(regime),
            "existing_regime_source": "canonical strict truth pretrade context + market_context_learning_suite_v1 summary index",
            "market_context_index_dimensions": _index_counts(market_index),
        },
        "opportunity_cost_intelligence": _opportunity_cost(advisory, opportunity_index),
        "shadow_validation_and_evidence_promotion": _shadow_validation(shadow, shadow_perf),
        "knowledge_retrieval": {
            **retrieval,
            "retrieval_health": "BOUNDED_INDEX_READY",
            "index_freshness_source": "existing summary indexes and canonical registry metadata",
            "broker_truth_and_shadow_separated": True,
        },
        "v1_integration": {
            "suite": "astra_trading_intelligence_improvement_suite_v1",
            "status": v1.get("status"),
            "pretrade_contract_owner": (v1.get("pretrade_thesis") or {}).get("owner"),
            "native_exit_authority": (v1.get("hold_monitoring") or {}).get("canonical_exit_authority"),
            "frozen_lifecycle_modified": False,
        },
        "observability": {
            "sentinel_governance_cortex_owner": "existing Sentinel -> Governance -> Cortex",
            "issues": [
                "REGIME_CONTEXT_MISSING_ON_STRICT_TRUTH" if any(row.get("regime") == "UNAVAILABLE" for row in regime) else None,
                "STRICT_TRUTH_SAMPLE_BELOW_STABLE_PROFILE_MINIMUM" if len(strict_rows) < STABLE_PROFILE_MINIMUM else None,
            ],
        },
        **SAFETY,
    }
