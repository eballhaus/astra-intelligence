from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

try:
    from engine.context_capture_utils_v1 import enrich_context_row
except Exception:  # pragma: no cover - replay diagnostics must stay resilient
    def enrich_context_row(row, *, source_file):
        return row

VERSION = "2.0.0"
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


class ReplayCounterfactualLearningV2:
    """Shadow-only replay and counterfactual learning from paper lifecycle evidence."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.v2_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.profit_path = os.path.join(self.state_dir, "adaptive_profit_capture_intelligence_v1.jsonl")
        self.state_path = os.path.join(self.state_dir, "replay_counterfactual_learning_v2.jsonl")
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
        actual = _to_float(row.get("current_or_exit_profit_pct") or row.get("current_return_pct") or row.get("continuation_after_entry_pct"))
        mfe = max(0.0, _to_float(row.get("max_favorable_excursion_pct") or row.get("peak_unrealized_profit_pct")))
        mae = _to_float(row.get("max_adverse_excursion_pct"))
        giveback = _to_float(row.get("profit_giveback_pct"))
        capture = _to_float(row.get("profit_capture_ratio"), (max(0.0, actual) / mfe if mfe > 0 else 0.0))
        follow = _text(row.get("follow_through_label") or row.get("continuation_pattern_label"), "unknown")
        hold_minutes = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"))
        decay = _to_float(row.get("continuation_decay_score"), giveback * 12.0)
        confidence = _clamp(35.0 + min(25.0, hold_minutes / 60.0) + min(20.0, abs(mfe) * 2.0) + (20.0 if row.get("closed") else 8.0))
        paths = {
            "entered_earlier": actual + min(0.8, max(0.0, mfe - actual) * 0.18),
            "entered_later": actual - min(0.6, max(0.0, abs(mae)) * 0.14),
            "waited_for_confirmation": actual + (0.25 if "strong" in follow or "moderate" in follow else -0.25),
            "avoided_entry": 0.0,
            "exited_at_mfe": mfe,
            "exited_after_giveback_threshold": max(actual, mfe - max(0.35, mfe * 0.35)),
            "held_longer": actual + (0.35 if "strong" in follow and decay < 35 else -min(0.75, giveback * 0.2 + abs(mae) * 0.05)),
            "exited_earlier": actual + min(1.0, max(0.0, giveback) * 0.55),
            "exited_on_momentum_decay": actual + min(0.9, max(0.0, giveback) * 0.45 if decay >= 30 else 0.1),
            "shorter_hold": actual + min(0.65, max(0.0, giveback) * 0.35),
            "longer_hold": actual + (0.4 if "strong" in follow else -0.4),
            "scalp_hold": min(mfe, actual + min(0.5, mfe * 0.25)),
            "day_trade_hold": actual + (0.25 if hold_minutes < 240 and "failed" not in follow else -0.15),
            "swing_hold": actual + (0.5 if "strong" in follow and capture > 0.5 else -0.5),
        }
        best_path, best_return = max(paths.items(), key=lambda item: item[1])
        worst_path, worst_return = min(paths.items(), key=lambda item: item[1])
        improvement = best_return - actual
        replay_quality = _clamp(50.0 + capture * 20.0 + min(20.0, max(0.0, actual) * 3.0) - min(25.0, giveback * 1.2))
        if best_path in {"exited_at_mfe", "exited_after_giveback_threshold", "exited_earlier", "exited_on_momentum_decay"}:
            missed_pattern = "exit_timing_profit_capture"
        elif best_path in {"entered_earlier", "entered_later", "waited_for_confirmation", "avoided_entry"}:
            missed_pattern = "entry_timing_selection"
        else:
            missed_pattern = "hold_duration_management"
        return {
            "enabled": True,
            "version": VERSION,
            "lifecycle_id": lifecycle_id,
            "symbol": symbol,
            "timestamp": _text(row.get("timestamp") or row.get("last_update_timestamp") or row.get("current_timestamp") or _now_iso()),
            "actual_return_pct": _round(actual),
            "counterfactual_return_pct": _round(best_return),
            "best_counterfactual_return": _round(best_return),
            "worst_counterfactual_return": _round(worst_return),
            "improvement_vs_actual": _round(improvement),
            "worse_vs_actual": _round(worst_return - actual),
            "best_counterfactual_path": best_path,
            "worst_counterfactual_path": worst_path,
            "most_likely_missed_improvement": missed_pattern,
            "counterfactual_confidence": _round(confidence, 2),
            "replay_quality_score": _round(replay_quality, 2),
            "all_counterfactual_paths": {k: round(v, 4) for k, v in paths.items()},
            "trade_archetype": _text(row.get("trade_archetype"), "unknown"),
            "market_regime": _text(row.get("market_regime"), "unknown"),
            "sector": _text(row.get("sector"), "unknown"),
            "generated_at": _now_iso(),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
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
                for row in rows[-100:]:
                    enriched = enrich_context_row(row, source_file="replay_counterfactual_learning_v2.jsonl")
                    handle.write(json.dumps(enriched, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    @staticmethod
    def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [_to_float(row.get(key)) for row in rows if row.get(key) not in (None, "")]
        return round(mean(vals), 4) if vals else None

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
        patterns = Counter(_text(row.get("best_counterfactual_path"), "unknown") for row in records)
        missed = Counter(_text(row.get("most_likely_missed_improvement"), "unknown") for row in records)
        negative_rows = [row for row in records if _to_float(row.get("actual_return_pct")) < 0]
        outlier_rows = sorted(records, key=lambda row: abs(_to_float(row.get("actual_return_pct")) - (avg_actual or 0.0)) if 'avg_actual' in locals() and avg_actual is not None else abs(_to_float(row.get("actual_return_pct"))), reverse=True)[:6]
        avg_actual = self._avg(records, "actual_return_pct")
        avg_best = self._avg(records, "best_counterfactual_return")
        avg_improvement = self._avg(records, "improvement_vs_actual")
        avg_quality = self._avg(records, "replay_quality_score")
        outlier_rows = sorted(records, key=lambda row: abs(_to_float(row.get("actual_return_pct")) - (avg_actual or 0.0)), reverse=True)[:6]
        recommendation = "insufficient_data"
        if len(records) >= 5:
            recommendation = "review_exit_timing_counterfactuals" if missed.most_common(1) and missed.most_common(1)[0][0] == "exit_timing_profit_capture" else "review_entry_and_hold_counterfactuals"
        out = {
            "enabled": True,
            "version": VERSION,
            "tracked_lifecycles": len(records),
            "counterfactuals_generated": len(records) * 14,
            "average_actual_return": avg_actual,
            "average_best_counterfactual_return": avg_best,
            "average_counterfactual_improvement": avg_improvement,
            "average_actual_vs_best_possible": avg_improvement,
            "best_counterfactual_pattern": patterns.most_common(1)[0][0] if patterns else "insufficient_data",
            "most_common_missed_improvement": missed.most_common(1)[0][0] if missed else "insufficient_data",
            "replay_learning_score": avg_quality,
            "replay_learning_recommendation": recommendation,
            "replay_actual_avg_source": "trade_lifecycle_current_or_exit_profit_pct",
            "replay_best_virtual_source": "shadow_counterfactual_paths_from_mfe_mae_giveback",
            "replay_scope_label": "active_and_closed_lifecycle_rows_shadow_counterfactual",
            "replay_closed_only": False,
            "replay_open_included": True,
            "replay_outlier_symbols": [_text(row.get("symbol"), "unknown") for row in outlier_rows if _text(row.get("symbol"))],
            "replay_negative_return_drivers": dict(Counter(_text(row.get("symbol"), "unknown") for row in negative_rows).most_common(8)),
            "human_review_required": True,
            "auto_apply_allowed": False,
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
