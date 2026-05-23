from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1_000
CORE_TARGET = 0.55
MOMENTUM_TARGET = 0.30
EXPLORATION_TARGET = 0.15

MEGA_CAP_SYMBOL_FALLBACK = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META", "TSLA", "AVGO", "BRK.B",
    "BRK-A", "LLY", "JPM", "V", "MA", "COST", "WMT", "NFLX", "ORCL", "XOM",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text if text else str(default)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _score01(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if out <= 1.0:
        out *= 100.0
    return _clamp(out)


def _first_number(row: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key), default)
    return float(default)


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
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


def _market_cap_bucket(row: dict[str, Any]) -> str:
    symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
    raw = _safe_text(
        row.get("candidate_universe_tier")
        or row.get("market_cap_bucket")
        or row.get("market_cap_group")
        or row.get("market_cap_category")
        or row.get("cap_bucket")
    ).lower()
    cap = _to_float(row.get("market_cap") or row.get("market_capitalization") or row.get("marketCap"), 0.0)
    if "mega" in raw or cap >= 200_000_000_000 or symbol in MEGA_CAP_SYMBOL_FALLBACK:
        return "mega_cap"
    if "large" in raw or cap >= 10_000_000_000:
        return "large_cap"
    if "mid" in raw or cap >= 2_000_000_000:
        return "mid_cap"
    if "small" in raw or cap >= 300_000_000:
        return "small_cap"
    if "micro" in raw or (0.0 < cap < 300_000_000):
        return "micro_cap"
    return "unknown"


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pack_key in ("stocks", "crypto"):
        pack = payload.get(pack_key)
        if not isinstance(pack, dict):
            continue
        for section in ("final", "qualified", "watchlist", "fill"):
            values = pack.get(section)
            if isinstance(values, list):
                rows.extend([dict(v) for v in values if isinstance(v, dict)])
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
        if symbol and symbol not in dedup:
            dedup[symbol] = row
    return list(dedup.values())


class PaperOpportunityAllocationEngineV1:
    """Paper-only lane allocation and exploration scorer.

    This engine only decorates and orders paper candidates. It does not change
    live trading, broker mode, exits, provider logic, or safety gates.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self._outcome_cache: dict[str, Any] | None = None

    def _features(self, row: dict[str, Any]) -> dict[str, float | str | bool]:
        r = dict(row or {})
        predicted_profit = _first_number(r, ("predicted_profit_percent", "expected_return_percent", "expected_return_pct", "profit_prediction_pct", "expected_move_percent"), 0.0)
        confidence = _score01(r.get("confidence"), _score01(r.get("predicted_win_probability"), 52.0))
        entry_quality = _score01(
            r.get("entry_quality_v3_score"),
            _score01(r.get("entry_quality_v2_score"), _score01(r.get("entry_filter_v2_score"), _score01(r.get("entry_quality_score"), 52.0))),
        )
        aggressive_profit = _score01(r.get("aggressive_profit_score"), _clamp(45.0 + max(0.0, predicted_profit) * 6.0))
        risk_adjusted_profit = _score01(
            r.get("risk_adjusted_profit_score"),
            _clamp((aggressive_profit * 0.32) + (confidence * 0.28) + (entry_quality * 0.24) + (_score01(r.get("portfolio_risk_score"), 58.0) * 0.16)),
        )
        momentum = _score01(r.get("momentum_expansion_score"), _score01(r.get("momentum_score"), 50.0))
        breakout = _score01(r.get("breakout_probability_score"), 50.0)
        accel = _score01(r.get("intraday_acceleration_score"), 50.0)
        volatility = _score01(r.get("volatility_expansion_score"), _score01(r.get("volatility_score"), 50.0))
        liquidity = _score01(r.get("liquidity_score"), _score01(r.get("data_quality_score"), 58.0))
        execution = _score01(r.get("execution_readiness_score"), _score01(r.get("order_execution_score"), 58.0))
        portfolio_risk = _score01(r.get("portfolio_risk_score"), 58.0)
        drawdown_risk = _score01(r.get("drawdown_risk_score"), 35.0)
        cap = _market_cap_bucket(r)
        high_upside = bool(r.get("high_upside_candidate")) or predicted_profit >= 4.0 or aggressive_profit >= 68.0
        opportunity_type = _safe_text(r.get("candidate_opportunity_type") or r.get("candidate_discovery_reason")).lower()
        momentum_candidate = (
            bool(r.get("momentum_runner"))
            or "momentum" in opportunity_type
            or "breakout" in opportunity_type
            or momentum >= 58.0
            or breakout >= 62.0
            or accel >= 62.0
            or bool(r.get("unusual_volume"))
        )
        risk_minimums = bool(confidence >= 48.0 and entry_quality >= 44.0 and liquidity >= 42.0 and execution >= 42.0 and portfolio_risk >= 35.0 and drawdown_risk <= 82.0)
        exploration_allowed = bool(risk_minimums and high_upside and cap in {"mid_cap", "small_cap", "micro_cap", "unknown"})
        if risk_minimums and high_upside and cap == "mega_cap" and momentum_candidate:
            exploration_allowed = True
        if not risk_minimums:
            rejection = "risk_quality_minimums_not_met"
        elif not high_upside and not momentum_candidate:
            rejection = "not_high_upside_or_momentum"
        elif cap in {"mega_cap", "large_cap"} and not momentum_candidate:
            rejection = "not_exploration_tier"
        else:
            rejection = ""
        if exploration_allowed and high_upside and cap in {"mid_cap", "small_cap", "micro_cap", "unknown"}:
            lane = "high_upside_exploration"
            lane_score = _clamp((risk_adjusted_profit * 0.34) + (aggressive_profit * 0.28) + (momentum * 0.18) + (liquidity * 0.10) + (execution * 0.10))
            reason = "controlled high-upside paper exploration with risk minimums satisfied"
        elif momentum_candidate:
            lane = "momentum_opportunity"
            lane_score = _clamp((risk_adjusted_profit * 0.34) + (momentum * 0.24) + (breakout * 0.16) + (accel * 0.12) + (liquidity * 0.14))
            reason = "momentum/breakout paper lane candidate"
        else:
            lane = "core_quality"
            lane_score = _clamp((risk_adjusted_profit * 0.44) + (confidence * 0.22) + (entry_quality * 0.18) + (liquidity * 0.08) + (portfolio_risk * 0.08))
            reason = "core risk-adjusted paper quality lane"
        risk_label = "controlled"
        if not risk_minimums:
            risk_label = "blocked_quality_risk"
        elif drawdown_risk >= 68.0 or liquidity < 50.0:
            risk_label = "elevated_watch"
        elif exploration_allowed:
            risk_label = "controlled_exploration"
        priority = _clamp((lane_score * 0.58) + (risk_adjusted_profit * 0.28) + (aggressive_profit * 0.14))
        if lane == "high_upside_exploration":
            priority = _clamp(priority + 4.0)
        elif lane == "momentum_opportunity":
            priority = _clamp(priority + 2.0)
        horizon = _safe_text(r.get("best_horizon_style") or r.get("trade_horizon_style") or r.get("best_discovery_horizon"), "day_trade")
        return {
            "predicted_profit_percent": round(predicted_profit, 4),
            "confidence": confidence,
            "entry_quality": entry_quality,
            "aggressive_profit_score": aggressive_profit,
            "risk_adjusted_profit_score": risk_adjusted_profit,
            "momentum_expansion_score": momentum,
            "breakout_probability_score": breakout,
            "volatility_expansion_score": volatility,
            "liquidity_score": liquidity,
            "execution_readiness_score": execution,
            "portfolio_risk_score": portfolio_risk,
            "candidate_universe_tier": cap,
            "best_horizon_style": horizon,
            "allocation_lane": lane,
            "allocation_lane_score": round(lane_score, 2),
            "allocation_reason": reason,
            "exploration_candidate": bool(lane in {"momentum_opportunity", "high_upside_exploration"}),
            "exploration_risk_label": risk_label,
            "exploration_allowed": bool(exploration_allowed or (lane == "momentum_opportunity" and risk_minimums)),
            "exploration_rejection_reason": rejection,
            "risk_adjusted_opportunity_rank": 0,
            "paper_allocation_priority": round(priority, 2),
        }

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        out = self._features(row)
        out["paper_opportunity_allocation_engine_v1"] = True
        out["api_calls_used"] = 0
        out["live_trading_changed"] = False
        return out

    def decorate_candidates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        decorated: list[dict[str, Any]] = []
        for row in rows[:300]:
            if not isinstance(row, dict):
                continue
            scored = self.score_row(row)
            decorated.append({**row, **scored})
        decorated.sort(key=lambda r: (_to_float(r.get("paper_allocation_priority"), 0.0), _to_float(r.get("risk_adjusted_profit_score"), 0.0)), reverse=True)
        for idx, row in enumerate(decorated, start=1):
            row["risk_adjusted_opportunity_rank"] = idx
        return decorated

    def _outcome_stats(self) -> dict[str, Any]:
        if self._outcome_cache is not None:
            return self._outcome_cache
        rows = []
        rows.extend(_tail_jsonl(self.lifecycle_path, 400))
        rows.extend(_tail_jsonl(self.labels_path, 400))
        by_lane: dict[str, list[float]] = defaultdict(list)
        wins: Counter[str] = Counter()
        totals: Counter[str] = Counter()
        horizon_lane: Counter[str] = Counter()
        for raw in rows[-MAX_ROWS:]:
            if not isinstance(raw, dict):
                continue
            lane = _safe_text(raw.get("allocation_lane") or raw.get("paper_allocation_lane"), "unknown")
            if lane == "unknown":
                continue
            ret = _first_number(raw, ("realized_return_pct", "return_percent", "return_pct", "pnl_pct"), 0.0)
            by_lane[lane].append(ret)
            totals[lane] += 1
            if ret > 0:
                wins[lane] += 1
            horizon = _safe_text(raw.get("trade_horizon_style") or raw.get("best_horizon_style"), "unknown")
            horizon_lane[f"{horizon}:{lane}"] += 1
        result: dict[str, Any] = {"lanes": {}, "horizon_lane_counts": dict(horizon_lane)}
        for lane in ("core_quality", "momentum_opportunity", "high_upside_exploration"):
            vals = by_lane.get(lane, [])
            result["lanes"][lane] = {
                "sample_size": int(totals.get(lane, 0)),
                "win_rate": round((wins.get(lane, 0) / max(1, totals.get(lane, 0))) * 100.0, 2) if totals.get(lane, 0) else None,
                "average_return_pct": round(mean(vals), 4) if vals else None,
                "profit_factor": None,
            }
        self._outcome_cache = result
        return result

    def recommended_weights(self) -> dict[str, Any]:
        stats = self._outcome_stats().get("lanes", {})
        sample_total = sum(int((stats.get(lane) or {}).get("sample_size") or 0) for lane in stats)
        if sample_total < 12:
            return {
                "recommended_core_lane_weight": 0.55,
                "recommended_momentum_lane_weight": 0.30,
                "recommended_exploration_lane_weight": 0.15,
                "allocation_adjustment_reason": "insufficient_lane_outcome_samples_keep_default_targets",
                "allocation_confidence": "low",
            }
        scores = {}
        for lane, base in (("core_quality", 0.55), ("momentum_opportunity", 0.30), ("high_upside_exploration", 0.15)):
            item = stats.get(lane) or {}
            wr = _to_float(item.get("win_rate"), 50.0)
            avg = _to_float(item.get("average_return_pct"), 0.0)
            scores[lane] = max(0.05, base + ((wr - 50.0) / 500.0) + (avg / 80.0))
        total = sum(scores.values()) or 1.0
        core = _clamp(scores["core_quality"] / total, 0.40, 0.70)
        momentum = _clamp(scores["momentum_opportunity"] / total, 0.15, 0.45)
        exploration = _clamp(1.0 - core - momentum, 0.05, 0.25)
        return {
            "recommended_core_lane_weight": round(core, 3),
            "recommended_momentum_lane_weight": round(momentum, 3),
            "recommended_exploration_lane_weight": round(exploration, 3),
            "allocation_adjustment_reason": "lane_outcome_weighting_shadow_review",
            "allocation_confidence": "medium" if sample_total >= 30 else "low",
        }

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        decorated = self.decorate_candidates([dict(r) for r in (rows or []) if isinstance(r, dict)])
        lanes = Counter(str(r.get("allocation_lane") or "unknown") for r in decorated)
        cap_counts = Counter(str(r.get("candidate_universe_tier") or _market_cap_bucket(r)) for r in decorated)
        high_reviewed = [
            r for r in decorated
            if bool(r.get("high_upside_candidate"))
            or bool(r.get("exploration_candidate"))
            or _to_float(r.get("predicted_profit_percent"), 0.0) >= 4.0
            or _to_float(r.get("aggressive_profit_score"), 0.0) >= 68.0
        ]
        approved = [r for r in high_reviewed if bool(r.get("exploration_allowed"))]
        rejected = [r for r in high_reviewed if not bool(r.get("exploration_allowed"))]
        rejection_counts = Counter(str(r.get("exploration_rejection_reason") or "not_rejected") for r in rejected)
        total = len(decorated)
        mega = cap_counts.get("mega_cap", 0)
        rec = self.recommended_weights()
        summary = (
            f"Paper allocation lanes: core {lanes.get('core_quality', 0)}, momentum {lanes.get('momentum_opportunity', 0)}, "
            f"exploration {lanes.get('high_upside_exploration', 0)}. Valid exploration candidates {len(approved)}; "
            f"mega-cap concentration {(mega / max(1, total)) * 100.0:.1f}%."
        ) if total else "No paper candidates available for allocation review."
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_allocation",
            "paper_opportunity_allocation_status_v1": True,
            "core_lane_target_pct": round(CORE_TARGET * 100.0, 1),
            "momentum_lane_target_pct": round(MOMENTUM_TARGET * 100.0, 1),
            "exploration_lane_target_pct": round(EXPLORATION_TARGET * 100.0, 1),
            "current_core_lane_count": int(lanes.get("core_quality", 0)),
            "current_momentum_lane_count": int(lanes.get("momentum_opportunity", 0)),
            "current_exploration_lane_count": int(lanes.get("high_upside_exploration", 0)),
            "valid_exploration_candidates": int(len(approved)),
            "high_upside_candidates_reviewed": int(len(high_reviewed)),
            "high_upside_candidates_approved": int(len(approved)),
            "high_upside_candidates_rejected": int(len(rejected)),
            "top_exploration_rejection_reasons": [{"reason": k, "count": v} for k, v in rejection_counts.most_common(5)],
            "mega_cap_concentration_pct": round((mega / max(1, total)) * 100.0, 2) if total else 0.0,
            "non_mega_candidate_count": int(total - mega),
            "lane_counts": dict(lanes),
            "market_cap_distribution": dict(cap_counts),
            "allocation_summary": summary,
            **rec,
            "lane_outcome_stats": self._outcome_stats().get("lanes", {}),
            "auto_apply_allowed": False,
            "human_review_required": True,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_live_behavior_changed": False,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "alpaca_paper_only_preserved": True,
            "generated_at": _now_iso(),
        }

    def enrich_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload or {})
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            pack_out = dict(pack)
            for section in ("final", "qualified", "watchlist", "fill"):
                values = pack_out.get(section)
                if not isinstance(values, list):
                    continue
                pack_out[section] = self.decorate_candidates([dict(v) for v in values if isinstance(v, dict)])
            out[pack_key] = pack_out
        rows = _candidate_rows(out)
        out["paper_opportunity_allocation_engine_v1"] = True
        out["paper_opportunity_allocation_summary"] = self.status(rows=rows)
        return out
