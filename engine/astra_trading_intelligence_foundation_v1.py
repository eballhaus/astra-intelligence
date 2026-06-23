from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_500_000
MAX_ROWS = 2200
CACHE_TTL_SECONDS = 20.0
HORIZON_BUCKETS = ["intraday", "1_to_3_days", "4_to_7_days", "8_to_14_days", "15_to_30_days", "30_plus_days", "unknown"]


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


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _avg(values: list[float], default: float = 0.0) -> float:
    vals = [float(v) for v in values if math.isfinite(float(v))]
    return round(mean(vals), 4) if vals else float(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _text(value: Any, default: str = "insufficient_evidence") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


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


def _parse_time(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _safe_flags(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "behavior_safe_to_apply": False,
        "broker_execution_added": False,
        "automatic_entries_enabled": False,
        "automatic_exits_enabled": False,
        "automatic_sizing_enabled": False,
        "automatic_allocations_enabled": False,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "advisory_only": True,
        "shadow_analysis_mode": True,
        "human_review_required": True,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "shadow_logic_changed": False,
        "aios_logic_changed": False,
        "provider_ownership_changed": False,
        "provider_polling_frequency_changed": False,
        "dashboard_endpoint_storm_created": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }
    out.update(extra or {})
    return out


def _tail_jsonl(path: Path, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            raw = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = raw.splitlines()
    if path.stat().st_size > max_bytes and lines:
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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _status(statuses: dict[str, Any], key: str) -> dict[str, Any]:
    value = statuses.get(key) if isinstance(statuses, dict) else {}
    return dict(value) if isinstance(value, dict) else {}


def _unwrap_cache(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("summary"), dict):
        merged = dict(payload.get("summary") or {})
        merged.update({k: v for k, v in payload.items() if k not in {"summary"}})
        return merged
    return dict(payload or {})


def _profit_factor(returns: list[float]) -> float | None:
    vals = [v for v in returns if abs(v) > 1e-9]
    if not vals:
        return None
    gains = sum(v for v in vals if v > 0)
    losses = abs(sum(v for v in vals if v < 0))
    if losses <= 0:
        return round(gains, 4) if gains > 0 else 0.0
    return round(gains / losses, 4)


def _return_pct(row: dict[str, Any]) -> float:
    return _to_float(_first(
        row.get("current_or_exit_profit_pct"),
        row.get("current_return_pct"),
        row.get("realized_return_pct"),
        row.get("actual_return_pct"),
        row.get("pnl_pct"),
        row.get("return_pct"),
        row.get("continuation_after_entry_pct"),
        default=0.0,
    ))


def _mfe(row: dict[str, Any], ret: float = 0.0) -> float:
    return _to_float(_first(row.get("max_favorable_excursion_pct"), row.get("mfe_pct"), row.get("peak_unrealized_profit_pct"), default=max(0.0, ret)))


def _mae(row: dict[str, Any], ret: float = 0.0) -> float:
    val = _to_float(_first(row.get("max_adverse_excursion_pct"), row.get("mae_pct"), row.get("max_drawdown_experienced_pct"), default=min(0.0, ret)))
    if val > 0 and abs(val - ret) < 1e-9:
        return 0.0
    return val


def _hold_days(row: dict[str, Any]) -> float:
    minutes = _first(row.get("hold_duration_minutes"), row.get("actual_hold_duration_minutes"), row.get("elapsed_hold_minutes"), row.get("hold_minutes"), default=None)
    if minutes is not None:
        return max(0.0, _to_float(minutes) / 1440.0)
    days = _first(row.get("days_held"), row.get("hold_days"), row.get("age_days"), default=None)
    if days is not None:
        return max(0.0, _to_float(days))
    entry = _parse_time(_first(row.get("entry_timestamp"), row.get("entry_time"), default=""))
    exit_t = _parse_time(_first(row.get("exit_timestamp"), row.get("exit_time"), row.get("updated_at"), row.get("generated_at"), default=""))
    if entry and exit_t:
        return max(0.0, (exit_t - entry).total_seconds() / 86400.0)
    return 0.0


def _horizon_bucket(days: float) -> str:
    if days <= 0:
        return "unknown"
    if days < 1.0:
        return "intraday"
    if days <= 3:
        return "1_to_3_days"
    if days <= 7:
        return "4_to_7_days"
    if days <= 14:
        return "8_to_14_days"
    if days <= 30:
        return "15_to_30_days"
    return "30_plus_days"


def _closed(row: dict[str, Any]) -> bool:
    if bool(row.get("closed")):
        return True
    stage = _text(_first(row.get("lifecycle_stage"), row.get("status"), row.get("state"), default=""), "").lower()
    return stage in {"closed", "filled_exit", "exit_filled", "realized"} or bool(row.get("exit_timestamp") or row.get("exit_time"))


def _classify_exit(closed: bool, ret: float, mfe: float, mae: float, giveback: float, capture: float, days: float, raw_label: str = "") -> str:
    raw = raw_label.lower()
    if any(token in raw for token in ("panic", "stop_loss")) and ret < 0:
        return "panic_exit"
    if not closed:
        if days >= 7 and giveback >= 3:
            return "overheld"
        if mfe >= 2 and ret <= 0:
            return "profit_reversal"
        if giveback >= 5:
            return "missed_exit"
        return "insufficient_evidence"
    if mfe <= 0.1:
        return "insufficient_evidence"
    if capture >= 85:
        return "perfect_exit"
    if capture >= 60:
        return "good_exit"
    if ret > 0 and giveback >= 4:
        return "late_exit"
    if ret < 0 and mfe > 1:
        return "profit_reversal"
    if ret > 0 and capture < 25:
        return "early_exit"
    if days >= 7 and giveback >= 2:
        return "overheld"
    if mae < -5:
        return "panic_exit"
    return "insufficient_evidence"


def _behavior_label(profile: dict[str, Any]) -> str:
    evidence = _to_int(profile.get("evidence_count"))
    if evidence < 3:
        return "insufficient_evidence"
    avg_mfe = _to_float(profile.get("avg_mfe"))
    avg_giveback = _to_float(profile.get("avg_giveback"))
    continuation = _to_float(profile.get("continuation_tendency"))
    reversal = _to_float(profile.get("reversal_tendency"))
    volatility = _to_float(profile.get("volatility_score"))
    if avg_giveback >= 5:
        return "high_giveback_risk"
    if continuation >= 65 and avg_mfe >= 2:
        return "momentum_leader"
    if volatility >= 8 and avg_mfe >= 2:
        return "volatility_breakout"
    if reversal >= 60:
        return "mean_reversion_candidate"
    if continuation < 45:
        return "weak_continuation"
    return "catalyst_driven" if _text(profile.get("best_catalyst_type"), "unknown") != "unknown" else "slow_compounder"


class AstraTradingIntelligenceFoundationV1:
    """Observation-only trading intelligence foundation.

    This module consolidates existing lifecycle, horizon, symbol, shadow, and
    broker-truth evidence into one bounded diagnostic contract. It never writes
    trading state, never sends orders, and never changes rankings, entries,
    exits, sizing, allocation, thresholds, providers, AIOS, or Shadow logic.
    """

    module_name = "astra_trading_intelligence_foundation_v1"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = Path(state_dir or "state")
        self.cache_dir = self.state_dir / "dashboard_cache"
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _lifecycle_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for path_name in (
            "trade_lifecycle_excursion_v2.jsonl",
            "trade_lifecycle_excursion_v1.jsonl",
            "trade_lifecycle_v1.jsonl",
            "adaptive_profit_capture_intelligence_v1.jsonl",
        ):
            for row in _tail_jsonl(self.state_dir / path_name):
                symbol = _text(row.get("symbol"), "").upper()
                key = _text(_first(row.get("lifecycle_id"), row.get("trade_id"), default=""), "")
                if not key:
                    key = f"{symbol}:{_text(_first(row.get('entry_timestamp'), row.get('timestamp'), row.get('updated_at'), default=''))[:19]}"
                if not symbol or key == ":":
                    continue
                merged = dict(latest.get(key) or {})
                merged.update(row)
                latest[key] = merged
        return list(latest.values())[-MAX_ROWS:]

    def _cached_statuses(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for path in self.cache_dir.glob("*.json"):
            out[path.stem] = _unwrap_cache(_read_json(path))
        return out

    def _trade_lifecycle(self, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        trade_rows: list[dict[str, Any]] = []
        issue_counter: Counter[str] = Counter()
        for row in rows:
            symbol = _text(row.get("symbol"), "").upper()
            if not symbol:
                continue
            ret = _return_pct(row)
            mfe = _mfe(row, ret)
            mae = _mae(row, ret)
            closed = _closed(row)
            days = _hold_days(row)
            current_profit = ret
            giveback = max(0.0, _to_float(_first(row.get("profit_giveback_pct"), row.get("giveback_pct"), default=mfe - current_profit)))
            capture = _to_float(_first(row.get("profit_capture_pct"), row.get("profit_capture_ratio"), default=(max(0.0, current_profit) / mfe * 100.0 if mfe > 0 else 0.0)))
            if capture <= 1.5 and mfe > 0:
                capture *= 100.0
            capture = _clamp(capture)
            classification = _classify_exit(closed, ret, mfe, mae, giveback, capture, days, _text(_first(row.get("exit_label"), row.get("exit_timing_label"), row.get("exit_classification"), default=""), ""))
            issue_counter[classification] += 1
            trade_rows.append({
                "symbol": symbol,
                "side": _text(_first(row.get("side"), row.get("asset_side"), default="long"), "long"),
                "entry_price": _round(row.get("entry_price")),
                "current_price": _round(row.get("current_price")),
                "exit_price": row.get("exit_price") if closed else None,
                "quantity": _round(_first(row.get("quantity"), row.get("qty"), default=0.0)),
                "entry_time": _text(_first(row.get("entry_timestamp"), row.get("entry_time"), default=""), ""),
                "exit_time": _text(_first(row.get("exit_timestamp"), row.get("exit_time"), default=""), "") if closed else "",
                "days_held": _round(days, 3),
                "current_return_pct": _round(ret, 4),
                "realized_return_pct": _round(ret, 4) if closed else None,
                "mfe_pct": _round(mfe, 4),
                "mae_pct": _round(mae, 4),
                "current_drawdown_from_mfe_pct": _round(max(0.0, mfe - ret), 4),
                "profit_capture_pct": _round(capture, 3),
                "profit_left_behind_pct": _round(max(0.0, mfe - ret), 4),
                "giveback_pct": _round(giveback, 4),
                "max_drawdown_experienced_pct": _round(mae, 4),
                "lifecycle_status": "closed" if closed else "open" if days < 45 else "stale",
                "exit_classification": classification,
            })
        if not trade_rows:
            return {"status": "insufficient_evidence", "trades_reviewed": 0}, []
        best = max(trade_rows, key=lambda r: _to_float(r.get("profit_capture_pct")))
        weakest = max(trade_rows, key=lambda r: _to_float(r.get("giveback_pct")))
        dominant = issue_counter.most_common(1)[0][0] if issue_counter else "insufficient_evidence"
        out = {
            "status": "ok",
            "trades_reviewed": len(trade_rows),
            "open_trades_reviewed": sum(1 for r in trade_rows if r.get("lifecycle_status") == "open"),
            "closed_trades_reviewed": sum(1 for r in trade_rows if r.get("lifecycle_status") == "closed"),
            "avg_mfe": _avg([_to_float(r.get("mfe_pct")) for r in trade_rows]),
            "avg_mae": _avg([_to_float(r.get("mae_pct")) for r in trade_rows]),
            "avg_giveback": _avg([_to_float(r.get("giveback_pct")) for r in trade_rows]),
            "avg_profit_capture": _avg([_to_float(r.get("profit_capture_pct")) for r in trade_rows]),
            "overheld_count": issue_counter.get("overheld", 0),
            "profit_reversal_count": issue_counter.get("profit_reversal", 0),
            "late_exit_count": issue_counter.get("late_exit", 0),
            "early_exit_count": issue_counter.get("early_exit", 0),
            "best_lifecycle_symbol": best.get("symbol"),
            "weakest_lifecycle_symbol": weakest.get("symbol"),
            "dominant_lifecycle_issue": dominant,
            "recommended_focus": "profit_capture_and_overhold_review" if dominant in {"overheld", "late_exit", "missed_exit", "profit_reversal"} else "continue_collecting_lifecycle_evidence",
            "sample_trades": trade_rows[-20:],
        }
        return out, trade_rows

    def _horizon(self, trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
        buckets: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in HORIZON_BUCKETS}
        by_symbol: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for row in trade_rows:
            bucket = _horizon_bucket(_to_float(row.get("days_held")))
            buckets.setdefault(bucket, []).append(row)
            by_symbol[_text(row.get("symbol"), "unknown")][bucket].append(_to_float(row.get("current_return_pct")))
        scorecard: dict[str, dict[str, Any]] = {}
        for bucket in HORIZON_BUCKETS:
            rows = buckets.get(bucket, [])
            returns = [_to_float(r.get("current_return_pct")) for r in rows]
            wins = [r for r in returns if r > 0]
            scorecard[bucket] = {
                "trade_count": len(rows),
                "win_rate": _round((len(wins) / len(rows)) * 100.0 if rows else 0.0, 3),
                "avg_return": _avg(returns),
                "profit_factor": _profit_factor(returns),
                "avg_mfe": _avg([_to_float(r.get("mfe_pct")) for r in rows]),
                "avg_mae": _avg([_to_float(r.get("mae_pct")) for r in rows]),
                "avg_giveback": _avg([_to_float(r.get("giveback_pct")) for r in rows]),
                "avg_profit_capture": _avg([_to_float(r.get("profit_capture_pct")) for r in rows]),
                "continuation_quality": _round(_clamp(_avg([_to_float(r.get("profit_capture_pct")) for r in rows]) * 0.6 + max(0.0, _avg(returns)) * 4.0), 3),
                "exit_quality": _round(max(0.0, 100.0 - _avg([_to_float(r.get("giveback_pct")) for r in rows]) * 8.0), 3) if rows else 0.0,
                "confidence": _round(min(95.0, len(rows) * 4.0), 3),
            }
        ranked = sorted(scorecard.items(), key=lambda kv: (_to_float(kv[1].get("avg_return")), _to_float(kv[1].get("avg_profit_capture"))), reverse=True)
        with_trades = [(k, v) for k, v in ranked if _to_int(v.get("trade_count")) > 0]
        best = with_trades[0][0] if with_trades else "unknown"
        worst = with_trades[-1][0] if with_trades else "unknown"
        distribution = {k: v["trade_count"] for k, v in scorecard.items()}
        max_bucket = max(distribution, key=distribution.get) if distribution else "unknown"
        min_bucket = min(distribution, key=distribution.get) if distribution else "unknown"
        symbol_best = {}
        for symbol, bucket_map in by_symbol.items():
            best_bucket = max(bucket_map.items(), key=lambda kv: _avg(kv[1]))[0]
            symbol_best[symbol] = best_bucket
        counts = [v for v in distribution.values() if v > 0]
        balance = 100.0 - ((max(counts) - min(counts)) / max(1, sum(counts)) * 100.0) if len(counts) > 1 else (45.0 if counts else 0.0)
        return {
            "status": "ok" if trade_rows else "insufficient_evidence",
            "horizon_intelligence_v2": True,
            "horizon_scorecard": scorecard,
            "horizon_distribution": distribution,
            "horizon_accuracy": _round(_avg([_to_float(v.get("exit_quality")) for v in scorecard.values()]), 3),
            "best_horizon": best,
            "worst_horizon": worst,
            "best_horizon_by_symbol": dict(sorted(symbol_best.items())[:25]),
            "best_horizon_by_sector": {},
            "best_horizon_by_regime": {},
            "overused_horizon": max_bucket,
            "underused_horizon": min_bucket,
            "horizon_balance_score": _round(balance, 3),
            "horizon_accuracy_score": _round(_avg([_to_float(v.get("exit_quality")) for v in scorecard.values()]), 3),
            "horizon_confidence": _round(min(95.0, len(trade_rows) * 1.7), 3),
            "recommended_horizon_focus": f"collect_more_{min_bucket}_evidence" if min_bucket != "unknown" else "improve_horizon_label_coverage",
        }

    def _symbol_memory(self, trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in trade_rows:
            grouped[_text(row.get("symbol"), "unknown").upper()].append(row)
        profiles = []
        for symbol, rows in grouped.items():
            if symbol == "UNKNOWN":
                continue
            returns = [_to_float(r.get("current_return_pct")) for r in rows]
            horizon_counts = Counter(_horizon_bucket(_to_float(r.get("days_held"))) for r in rows)
            best_horizon = max(horizon_counts, key=horizon_counts.get) if horizon_counts else "unknown"
            avg_mfe = _avg([_to_float(r.get("mfe_pct")) for r in rows])
            avg_mae = _avg([_to_float(r.get("mae_pct")) for r in rows])
            avg_giveback = _avg([_to_float(r.get("giveback_pct")) for r in rows])
            avg_capture = _avg([_to_float(r.get("profit_capture_pct")) for r in rows])
            continuation = _round(sum(1 for r in returns if r > 0) / max(1, len(returns)) * 100.0, 3)
            reversal = _round(sum(1 for r in rows if _to_float(r.get("giveback_pct")) >= 3) / max(1, len(rows)) * 100.0, 3)
            volatility = avg_mfe + abs(avg_mae)
            profile = {
                "symbol": symbol,
                "evidence_count": len(rows),
                "best_horizon": best_horizon,
                "worst_horizon": min(horizon_counts, key=horizon_counts.get) if horizon_counts else "unknown",
                "best_regime": "unknown",
                "worst_regime": "unknown",
                "best_catalyst_type": "unknown",
                "worst_catalyst_type": "unknown",
                "best_exit_style": Counter(_text(r.get("exit_classification"), "unknown") for r in rows).most_common(1)[0][0],
                "weakest_exit_style": "high_giveback" if avg_giveback >= 3 else "insufficient_evidence",
                "average_hold_duration": _avg([_to_float(r.get("days_held")) for r in rows]),
                "avg_mfe": avg_mfe,
                "avg_mae": avg_mae,
                "avg_giveback": avg_giveback,
                "avg_profit_capture": avg_capture,
                "continuation_tendency": continuation,
                "reversal_tendency": reversal,
                "volatility_score": _round(volatility, 3),
                "volatility_personality": "high" if volatility >= 8 else "moderate" if volatility >= 3 else "low",
                "catalyst_sensitivity": "unknown",
                "sector_sensitivity": "unknown",
                "confidence_drift": 0.0,
                "behavior_stability": _round(max(0.0, 100.0 - reversal), 3),
                "profile_confidence": _round(min(95.0, len(rows) * 8.0), 3),
                "last_updated": _now_iso(),
            }
            profile["behavior_label"] = _behavior_label(profile)
            profiles.append(profile)
        if not profiles:
            return {"status": "insufficient_evidence", "symbol_profiles_created": 0, "symbol_profiles_updated": 0, "symbol_profiles": []}
        strongest = max(profiles, key=lambda p: (_to_float(p.get("profile_confidence")), _to_float(p.get("avg_profit_capture"))))
        weakest = max(profiles, key=lambda p: _to_float(p.get("avg_giveback")))
        labels = Counter(p.get("behavior_label") for p in profiles)
        return {
            "status": "ok",
            "symbol_profiles_created": len(profiles),
            "symbol_profiles_updated": len(profiles),
            "symbol_profiles": sorted(profiles, key=lambda p: _to_float(p.get("profile_confidence")), reverse=True)[:40],
            "strongest_symbol_profile": strongest.get("symbol"),
            "weakest_symbol_profile": weakest.get("symbol"),
            "highest_giveback_symbol": weakest.get("symbol"),
            "most_stable_symbol": max(profiles, key=lambda p: _to_float(p.get("behavior_stability"))).get("symbol"),
            "most_unstable_symbol": min(profiles, key=lambda p: _to_float(p.get("behavior_stability"))).get("symbol"),
            "best_behavior_label": labels.most_common(1)[0][0] if labels else "insufficient_evidence",
            "weakest_behavior_label": weakest.get("behavior_label"),
            "symbol_memory_maturity": _round(min(100.0, len(profiles) * 4.0), 3),
            "symbol_memory_confidence": _round(_avg([_to_float(p.get("profile_confidence")) for p in profiles]), 3),
        }

    def _data_preservation(self, statuses: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        ledger_count = len(_tail_jsonl(self.state_dir / "candidate_decision_ledger_v1.jsonl", max_rows=MAX_ROWS, max_bytes=1_500_000))
        lifecycle_count = len(rows)
        replay_count = len(_tail_jsonl(self.state_dir / "replay_counterfactual_learning_v2.jsonl", max_rows=MAX_ROWS, max_bytes=1_500_000))
        shadow_count = _to_int(_first(_status(statuses, "realistic_shadow_evidence_learning_lab_v1").get("evidence_count"), _status(statuses, "shadow_vs_paper_performance_attribution_v1").get("shadow_trade_count"), default=0))
        raw = max(ledger_count + lifecycle_count + replay_count, lifecycle_count)
        accepted = lifecycle_count + replay_count
        filtered = max(0, raw - accepted)
        compressed = sum(1 for _ in self.cache_dir.glob("*.json"))
        stored = accepted + compressed
        used_learning = lifecycle_count
        used_shadow = max(shadow_count, replay_count)
        used_symbol = len({ _text(r.get("symbol"), "").upper() for r in rows if r.get("symbol") })
        used_horizon = lifecycle_count
        used_exit = sum(1 for r in rows if r.get("exit_classification") or r.get("exit_label"))
        discard_rate = (filtered / raw * 100.0) if raw else 0.0
        utilization = (stored / raw * 100.0) if raw else 0.0
        learning_util = (used_learning / raw * 100.0) if raw else 0.0
        shadow_util = (used_shadow / raw * 100.0) if raw else 0.0
        starvation = _clamp(100.0 - learning_util * 2.0 + discard_rate * 0.35)
        if raw == 0:
            warning = "insufficient_tracking"
        elif discard_rate > 65:
            warning = "excessive_discard"
        elif starvation > 70:
            warning = "evidence_starvation"
        elif discard_rate > 45:
            warning = "over_filtering"
        elif learning_util < 25:
            warning = "mild_underuse"
        else:
            warning = "healthy"
        return {
            "status": "ok" if raw else "insufficient_evidence",
            "data_preservation_layer_v1": True,
            "raw_evidence_count": raw,
            "accepted_evidence_count": accepted,
            "filtered_evidence_count": filtered,
            "compressed_evidence_count": compressed,
            "stored_evidence_count": stored,
            "discarded_evidence_count": filtered,
            "used_for_learning_count": used_learning,
            "used_for_shadow_count": used_shadow,
            "used_for_symbol_memory_count": used_symbol,
            "used_for_horizon_learning_count": used_horizon,
            "used_for_exit_learning_count": used_exit,
            "evidence_utilization_rate": _round(utilization, 3),
            "learning_utilization_rate": _round(learning_util, 3),
            "shadow_utilization_rate": _round(shadow_util, 3),
            "compression_ratio": _round(compressed / max(1, raw), 5),
            "discard_rate": _round(discard_rate, 3),
            "evidence_starvation_score": _round(starvation, 3),
            "funnel_efficiency_score": _round(max(0.0, 100.0 - starvation * 0.55 - discard_rate * 0.25), 3),
            "over_filtering_risk": discard_rate > 45,
            "under_learning_risk": learning_util < 25,
            "warning_label": warning,
            "evidence_flow_summary": f"{accepted} accepted from {raw} bounded local evidence rows; warning={warning}",
            "recommended_evidence_focus": "increase_lifecycle_usage_from_existing_cached_rows" if warning != "healthy" else "preserve_current_cache_first_evidence_flow",
        }

    def _shadow_weakness(self, statuses: dict[str, Any], horizon: dict[str, Any], symbol_memory: dict[str, Any]) -> dict[str, Any]:
        shadow = _status(statuses, "shadow_vs_paper_performance_attribution_v1")
        correction = _status(statuses, "shadow_correction_validation_attribution_v1")
        profiles = symbol_memory.get("symbol_profiles") or []
        weak_symbols = [p.get("symbol") for p in sorted(profiles, key=lambda p: _to_float(p.get("avg_giveback")), reverse=True)[:5]]
        strong_symbols = [p.get("symbol") for p in sorted(profiles, key=lambda p: _to_float(p.get("avg_profit_capture")), reverse=True)[:5]]
        weak_horizon = horizon.get("worst_horizon", "unknown")
        strong_horizon = horizon.get("best_horizon", "unknown")
        weaknesses = [
            {"area": "symbols", "value": weak_symbols, "reason": "highest bounded giveback"},
            {"area": "horizon", "value": weak_horizon, "reason": "weakest horizon scorecard bucket"},
            {"area": "profit_capture", "value": _to_float(_first(shadow.get("profit_capture_delta"), default=0.0)), "reason": "shadow_vs_paper_capture_delta"},
            {"area": "exit_styles", "value": "high_giveback", "reason": "dominant lifecycle pressure"},
            {"area": "follow_through", "value": "weak_continuation", "reason": "bounded lifecycle continuation review"},
        ]
        strengths = [
            {"area": "symbols", "value": strong_symbols, "reason": "highest bounded capture"},
            {"area": "horizon", "value": strong_horizon, "reason": "best horizon scorecard bucket"},
            {"area": "candidate_ranking", "value": correction.get("strongest_validated_improvement", "warming_up"), "reason": "shadow correction attribution"},
            {"area": "paper_truth", "value": shadow.get("canonical_performance_source", "broker_truth_engine_v1"), "reason": "reconciled metric source"},
            {"area": "evidence", "value": symbol_memory.get("symbol_profiles_created", 0), "reason": "symbol memory profile count"},
        ]
        readiness = _round(_clamp(_first(shadow.get("shadow_alpha_confidence"), correction.get("confidence_score"), default=0.0)), 3)
        return {
            "status": "ok" if profiles else "insufficient_evidence",
            "top_5_shadow_weaknesses": weaknesses,
            "top_5_shadow_strengths": strengths,
            "weak_symbols": weak_symbols,
            "weak_regimes": [],
            "weak_horizons": [weak_horizon] if weak_horizon != "unknown" else [],
            "weak_sectors": [],
            "weak_catalysts": [],
            "weak_exit_styles": ["high_giveback"],
            "weak_profit_capture_contexts": ["low_capture_high_giveback"],
            "weak_follow_through_contexts": ["weak_continuation"],
            "strongest_symbols": strong_symbols,
            "strongest_regimes": [],
            "strongest_horizons": [strong_horizon] if strong_horizon != "unknown" else [],
            "strongest_sectors": [],
            "strongest_catalysts": [],
            "strongest_exit_styles": ["good_exit", "perfect_exit"],
            "dominant_shadow_gap": "profit_capture_and_horizon_follow_through",
            "shadow_learning_priority": "validate_profit_capture_and_horizon_specific_weaknesses_shadow_only",
            "shadow_readiness_score": readiness,
            "shadow_confidence_score": readiness,
            "promotion_not_ready_reason": "diagnostic_only_bundle_shadow_promotion_disabled",
        }

    def _executive_snapshot(self, statuses: dict[str, Any], lifecycle: dict[str, Any], horizon: dict[str, Any], data_preservation: dict[str, Any]) -> dict[str, Any]:
        broker = _status(statuses, "alpaca_paper_broker") or _status(statuses, "alpaca_paper_status_v1")
        shadow = _status(statuses, "shadow_vs_paper_performance_attribution_v1")
        perf = _status(statuses, "performance_summary")
        official = {
            "true_paper_profit_factor": _first(shadow.get("paper_profit_factor_verified"), broker.get("true_paper_profit_factor"), perf.get("profit_factor"), default=None),
            "true_paper_win_rate": _first(shadow.get("paper_win_rate"), broker.get("true_paper_win_rate"), perf.get("win_rate"), default=None),
            "true_avg_return": _first(shadow.get("paper_avg_return"), broker.get("true_paper_avg_return"), perf.get("average_return"), default=None),
            "true_total_p_l": _first(broker.get("total_pl"), broker.get("total_unrealized_pl"), default=None),
            "true_today_p_l": _first(broker.get("today_pl"), broker.get("daily_pl"), default=None),
            "active_positions": _first(broker.get("open_positions_count"), broker.get("broker_confirmed_positions"), default=None),
            "portfolio_value": _first(broker.get("account_equity"), broker.get("portfolio_value"), default=None),
            "broker_truth_status": "paper_verified" if broker.get("paper_mode_verified") else "warming_up",
        }
        diagnostic = {
            "learning_profit_factor": perf.get("profit_factor"),
            "learning_win_rate": perf.get("win_rate"),
            "learning_avg_return": perf.get("average_return"),
            "shadow_profit_factor": shadow.get("shadow_profit_factor_verified"),
            "replay_profit_factor": shadow.get("rolling_20_shadow_pf"),
            "virtual_profit_factor": shadow.get("lifetime_shadow_pf"),
        }
        lifecycle_metrics = {
            "profit_capture": lifecycle.get("avg_profit_capture"),
            "exit_quality": max(0.0, 100.0 - _to_float(lifecycle.get("avg_giveback")) * 8.0),
            "giveback_reduction": max(0.0, 100.0 - _to_float(lifecycle.get("avg_giveback")) * 10.0),
            "horizon_accuracy": horizon.get("horizon_accuracy_score"),
            "risk_adjusted_return": perf.get("risk_adjusted_return"),
            "regime_stability": _first(_status(statuses, "market_transition_detection_v1").get("regime_stability_score"), default=None),
            "evidence_count": data_preservation.get("raw_evidence_count"),
        }
        weakness = lifecycle.get("dominant_lifecycle_issue", "insufficient_evidence")
        strongest = "broker_truth_available" if official.get("broker_truth_status") == "paper_verified" else "diagnostic_learning_available"
        return {
            "status": "ok",
            "executive_trading_snapshot_v1": True,
            "official_metrics": official,
            "diagnostic_metrics": diagnostic,
            "lifecycle_metrics": lifecycle_metrics,
            "primary_trading_weakness": weakness,
            "strongest_trading_area": strongest,
            "next_best_focus": lifecycle.get("recommended_focus", "continue_collecting_evidence"),
            "metric_confidence": _round(min(95.0, _to_float(data_preservation.get("raw_evidence_count")) / 40.0), 3),
            "metric_freshness": "cache_first_current",
            "truth_status": "official_and_diagnostic_separated",
        }

    def status(self, statuses: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache and now - self._cache_ts < self.ttl_seconds:
            return dict(self._cache)
        merged_statuses = self._cached_statuses()
        if isinstance(statuses, dict):
            merged_statuses.update({k: v for k, v in statuses.items() if isinstance(v, dict)})
        rows = self._lifecycle_rows()
        lifecycle, trade_rows = self._trade_lifecycle(rows)
        horizon = self._horizon(trade_rows)
        symbol_memory = self._symbol_memory(trade_rows)
        data_preservation = self._data_preservation(merged_statuses, rows)
        shadow_weakness = self._shadow_weakness(merged_statuses, horizon, symbol_memory)
        executive_snapshot = self._executive_snapshot(merged_statuses, lifecycle, horizon, data_preservation)
        payload = {
            "ok": True,
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Bundle 3A Trading Intelligence Foundation V1",
            "module": self.module_name,
            "status": "ok" if trade_rows else "insufficient_evidence",
            "mode": "cache_first_observation_measurement_memory_diagnostics_only",
            "trade_lifecycle_intelligence_v1": lifecycle,
            "horizon_intelligence_v2": horizon,
            "symbol_behavioral_memory_v1": symbol_memory,
            "data_preservation_layer_v1": data_preservation,
            "shadow_weakness_detector_v1": shadow_weakness,
            "executive_trading_snapshot_v1": executive_snapshot,
            "summary": {
                "trades_reviewed": lifecycle.get("trades_reviewed", 0),
                "dominant_lifecycle_issue": lifecycle.get("dominant_lifecycle_issue", "insufficient_evidence"),
                "best_horizon": horizon.get("best_horizon", "unknown"),
                "weakest_horizon": horizon.get("worst_horizon", "unknown"),
                "symbol_profiles_created": symbol_memory.get("symbol_profiles_created", 0),
                "evidence_starvation_score": data_preservation.get("evidence_starvation_score", 0),
                "dominant_shadow_gap": shadow_weakness.get("dominant_shadow_gap", "insufficient_evidence"),
                "primary_trading_weakness": executive_snapshot.get("primary_trading_weakness", "insufficient_evidence"),
                "next_best_focus": executive_snapshot.get("next_best_focus", "continue_collecting_evidence"),
            },
            "generated_at": _now_iso(),
            **_safe_flags(),
        }
        self._cache = dict(payload)
        self._cache_ts = now
        return payload
