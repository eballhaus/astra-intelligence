from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 1_800_000
MAX_ROWS = 1500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or str(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


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


def _classify_archetype(row: dict[str, Any]) -> str:
    raw = _text(row.get("trade_archetype") or row.get("opportunity_type") or row.get("setup_type")).lower()
    horizon = _text(row.get("horizon_style")).lower()
    sector = _text(row.get("sector")).lower()
    follow = _text(row.get("follow_through_label") or row.get("continuation_pattern_label")).lower()
    cap = _text(row.get("cap_tier")).lower()
    mfe = _to_float(row.get("max_favorable_excursion_pct") or row.get("peak_unrealized_profit_pct"))
    mae = abs(_to_float(row.get("max_adverse_excursion_pct")))
    if "squeeze" in raw:
        return "squeeze_breakout"
    if "earn" in raw:
        return "earnings_continuation"
    if "reversal" in raw or "oversold" in raw or "mean" in raw:
        return "oversold_reversal"
    if "rotation" in raw or "sector" in raw:
        return "sector_rotation"
    if "range" in raw or "chop" in raw:
        return "range_rotation"
    if "breakout" in raw or ("strong" in follow and mfe >= 1.0):
        return "momentum_breakout"
    if "continuation" in raw or "trend" in raw or "day" in horizon:
        return "trend_continuation"
    if mfe >= 2.0 and mae >= 1.0:
        return "high_volatility_runner"
    if cap in {"small", "small_cap", "micro", "micro_cap"} and mfe >= 1.5:
        return "high_volatility_runner"
    if sector not in {"", "unknown"} and "rotation" in follow:
        return "sector_rotation"
    if raw and raw != "unknown":
        return raw if raw in {
            "momentum_breakout", "trend_continuation", "high_volatility_runner", "oversold_reversal",
            "range_rotation", "squeeze_breakout", "sector_rotation", "earnings_continuation",
        } else "low_quality_unclear"
    return "unknown"


def _classify_regime(row: dict[str, Any]) -> str:
    raw = _text(row.get("market_regime") or row.get("regime") or row.get("current_market_regime")).lower()
    follow = _text(row.get("follow_through_label") or row.get("continuation_pattern_label")).lower()
    mfe = _to_float(row.get("max_favorable_excursion_pct") or row.get("peak_unrealized_profit_pct"))
    mae = abs(_to_float(row.get("max_adverse_excursion_pct")))
    ret = _to_float(row.get("current_or_exit_profit_pct") or row.get("current_return_pct") or row.get("continuation_after_entry_pct"))
    if any(token in raw for token in ("risk_off", "panic", "bear")):
        return "risk_off" if "risk" in raw or "panic" in raw else "bearish_trend"
    if any(token in raw for token in ("risk_on", "bull", "uptrend")):
        return "risk_on" if "risk" in raw else "bullish_trend"
    if "momentum" in raw or "expansion" in raw:
        return "momentum_continuation"
    if "range" in raw or "mean" in raw:
        return "range_bound"
    if "choppy" in raw or "rotational" in raw:
        return "choppy_selective"
    if "low_vol" in raw or "compression" in raw:
        return "low_volatility"
    if "volatility" in raw or mae >= 2.0 or mfe >= 3.0:
        return "high_volatility"
    if "strong" in follow and ret > 0:
        return "momentum_continuation"
    if mae >= 1.5 and ret < 0:
        return "risk_off"
    if raw and raw != "unknown":
        return "uncertain_regime"
    return "uncertain_regime"


def _profit_factor(returns: list[float]) -> float:
    gains = sum(v for v in returns if v > 0)
    losses = abs(sum(v for v in returns if v < 0))
    if losses <= 0:
        return round(gains, 4) if gains > 0 else 0.0
    return round(gains / losses, 4)


def _score_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [_to_float(r.get("current_or_exit_profit_pct") or r.get("current_return_pct") or r.get("continuation_after_entry_pct")) for r in rows]
    sample_size = len(rows)
    wins = [r for r in returns if r > 0]
    avg_return = mean(returns) if returns else 0.0
    profit_factor = _profit_factor(returns)

    def avg(key: str) -> float:
        vals = [_to_float(r.get(key)) for r in rows if r.get(key) not in (None, "")]
        return mean(vals) if vals else 0.0

    avg_mfe = avg("max_favorable_excursion_pct") or avg("peak_unrealized_profit_pct")
    avg_mae = avg("max_adverse_excursion_pct")
    capture = avg("profit_capture_ratio")
    giveback = avg("profit_giveback_pct")
    follow = avg("follow_through_quality_score")
    exit_quality = avg("exit_quality_score")
    survivability = _clamp(68.0 + avg_return * 4.0 + avg_mae * 1.8 - giveback * 1.2)
    consistency = _clamp((len(wins) / sample_size * 100.0 if sample_size else 0.0) - min(25.0, abs(avg_mae)))
    quality = _clamp(
        (len(wins) / sample_size * 22.0 if sample_size else 0.0)
        + min(22.0, max(0.0, avg_return) * 8.0)
        + min(18.0, profit_factor * 5.0)
        + capture * 18.0
        + follow * 0.12
        + survivability * 0.08
        - min(18.0, giveback * 1.1)
    )
    return {
        "sample_size": sample_size,
        "win_rate": round((len(wins) / sample_size) * 100.0, 4) if sample_size else 0.0,
        "average_return_pct": round(avg_return, 4),
        "profit_factor": profit_factor,
        "average_mfe_pct": round(avg_mfe, 4),
        "average_mae_pct": round(avg_mae, 4),
        "average_profit_capture_ratio": round(capture, 4),
        "average_giveback_pct": round(giveback, 4),
        "follow_through_quality": round(follow, 4),
        "exit_quality": round(exit_quality, 4),
        "survivability_score": round(survivability, 4),
        "consistency_score": round(consistency, 4),
        "quality_score": round(quality, 4),
        "archetype_quality_score": round(quality, 4),
        "regime_quality_score": round(quality, 4),
    }


class TradeArchetypeRegimeIntelligenceV1:
    """Paper-only archetype and market-regime learning diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.v2_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.profit_path = os.path.join(self.state_dir, "adaptive_profit_capture_intelligence_v1.jsonl")
        self.state_path = os.path.join(self.state_dir, "trade_archetype_regime_intelligence_v1.jsonl")
        self.ttl_seconds = float(ttl_seconds or 8.0)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _latest_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for path in (self.v1_path, self.v2_path, self.profit_path):
            for row in _tail_jsonl(path):
                lifecycle_id = _text(row.get("lifecycle_id"))
                if not lifecycle_id:
                    continue
                merged = dict(latest.get(lifecycle_id) or {})
                merged.update(row)
                latest[lifecycle_id] = merged
        return list(latest.values())

    def _derive_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        lifecycle_id = _text(row.get("lifecycle_id"))
        symbol = _text(row.get("symbol")).upper()
        if not lifecycle_id or not symbol:
            return None
        archetype = _classify_archetype(row)
        regime = _classify_regime(row)
        return {
            "enabled": True,
            "version": VERSION,
            "lifecycle_id": lifecycle_id,
            "symbol": symbol,
            "timestamp": _text(row.get("timestamp") or row.get("last_update_timestamp") or row.get("current_timestamp") or _now_iso()),
            "closed": bool(row.get("closed")),
            "trade_archetype": archetype,
            "market_regime": regime,
            "current_or_exit_profit_pct": _round(row.get("current_or_exit_profit_pct") or row.get("current_return_pct") or row.get("continuation_after_entry_pct")),
            "max_favorable_excursion_pct": _round(row.get("max_favorable_excursion_pct") or row.get("peak_unrealized_profit_pct")),
            "max_adverse_excursion_pct": _round(row.get("max_adverse_excursion_pct")),
            "profit_capture_ratio": _round(row.get("profit_capture_ratio"), 4),
            "profit_giveback_pct": _round(row.get("profit_giveback_pct")),
            "follow_through_quality_score": _round(row.get("follow_through_quality_score") or row.get("follow_through_score")),
            "exit_quality_score": _round(row.get("exit_quality_score")),
            "survivability_score": _round(_to_float(row.get("survivability_score"), 65.0), 2),
            "sector": _text(row.get("sector"), "unknown"),
            "cap_tier": _text(row.get("cap_tier"), "unknown"),
            "horizon_style": _text(row.get("horizon_style"), "unknown"),
            "session_type": _text(row.get("session_type"), "unknown"),
            "allocation_lane": _text(row.get("allocation_lane"), "unknown"),
            "profit_capture_label": _text(row.get("profit_capture_label"), "unknown"),
            "continuation_label": _text(row.get("follow_through_label") or row.get("continuation_pattern_label"), "unknown"),
            "generated_at": _now_iso(),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        now = time.time()
        if not rows or now - self._last_write < 45.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                for row in rows[-80:]:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    @staticmethod
    def _group_scores(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[_text(row.get(key), "unknown")].append(row)
        return {name: _score_group(values) for name, values in grouped.items() if values}

    @staticmethod
    def _best(scores: dict[str, dict[str, Any]], metric: str = "quality_score", *, reverse: bool = True) -> str:
        if not scores:
            return "insufficient_data"
        return sorted(scores.items(), key=lambda item: _to_float(item[1].get(metric)), reverse=reverse)[0][0]

    def status(self, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out

        records = [row for row in (self._derive_row(raw) for raw in self._latest_rows()) if row]
        self._write_rows(records)
        archetype_scores = self._group_scores(records, "trade_archetype")
        regime_scores = self._group_scores(records, "market_regime")
        archetype_dist = dict(Counter(_text(row.get("trade_archetype"), "unknown") for row in records))
        regime_dist = dict(Counter(_text(row.get("market_regime"), "uncertain_regime") for row in records))
        matrix_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in records:
            pair = f"{_text(row.get('trade_archetype'), 'unknown')}|{_text(row.get('market_regime'), 'uncertain_regime')}"
            matrix_groups[pair].append(row)
        matrix_scores = {pair: _score_group(values) for pair, values in matrix_groups.items() if values}
        best_pair = self._best(matrix_scores, "quality_score", reverse=True)
        weakest_pair = self._best(matrix_scores, "quality_score", reverse=False)
        current_regime = records[-1].get("market_regime") if records else "uncertain_regime"
        current_pairs = {k: v for k, v in matrix_scores.items() if k.endswith(f"|{current_regime}")}
        current_best_pair = self._best(current_pairs, "quality_score", reverse=True)
        current_best_archetype = current_best_pair.split("|", 1)[0] if "|" in current_best_pair else "insufficient_data"
        current_alignment = _to_float(matrix_scores.get(current_best_pair, {}).get("quality_score"), 0.0)
        poor_fit_warning = current_alignment < 45.0 and current_best_archetype != "insufficient_data"
        best_archetype = self._best(archetype_scores, "archetype_quality_score", reverse=True)
        weakest_archetype = self._best(archetype_scores, "archetype_quality_score", reverse=False)
        highest_giveback_archetype = self._best(archetype_scores, "average_giveback_pct", reverse=True)
        recommendation = "insufficient_data"
        if len(records) >= 5:
            if poor_fit_warning:
                recommendation = "avoid_archetype_in_current_regime"
            elif highest_giveback_archetype not in {"insufficient_data", "unknown"}:
                recommendation = "monitor_archetype_giveback"
            elif best_archetype not in {"insufficient_data", "unknown"}:
                recommendation = "increase_attention_to_archetype"
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_archetype_regime_learning",
            "tracked_trades": len(records),
            "archetype_distribution": archetype_dist,
            "regime_distribution": regime_dist,
            "best_archetype": best_archetype,
            "weakest_archetype": weakest_archetype,
            "most_consistent_archetype": self._best(archetype_scores, "consistency_score", reverse=True),
            "highest_giveback_archetype": highest_giveback_archetype,
            "best_follow_through_archetype": self._best(archetype_scores, "follow_through_quality", reverse=True),
            "worst_follow_through_archetype": self._best(archetype_scores, "follow_through_quality", reverse=False),
            "best_regime": self._best(regime_scores, "regime_quality_score", reverse=True),
            "weakest_regime": self._best(regime_scores, "regime_quality_score", reverse=False),
            "current_regime": current_regime,
            "current_regime_quality": regime_scores.get(current_regime, {}).get("regime_quality_score", 0.0),
            "current_regime_trade_support": "supportive" if _to_float(regime_scores.get(current_regime, {}).get("regime_quality_score"), 0.0) >= 60 else "selective_or_uncertain",
            "best_archetype_regime_pair": best_pair,
            "weakest_archetype_regime_pair": weakest_pair,
            "current_best_supported_archetype": current_best_archetype,
            "current_archetype_regime_alignment_score": round(current_alignment, 4),
            "poor_fit_archetype_warning": bool(poor_fit_warning),
            "archetype_quality_scores": archetype_scores,
            "regime_quality_scores": regime_scores,
            "archetype_regime_matrix_summary": matrix_scores,
            "shadow_recommendation": recommendation,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "summary": f"Classified {len(records)} paper lifecycles into archetype/regime learning groups.",
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
