"""Replay and Counterfactual Trade Expansion V1 (local-only shadow analysis)."""

from __future__ import annotations

import json
import os
import statistics
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


class ReplayCounterfactualEngine:
    """Generates alternative outcome labels from existing local trade/replay rows only."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.outcome_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.candidate_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.replay_path = os.path.join(self.state_dir, "replay_results_v2.json")
        self._lock = threading.Lock()
        self._cache_payload: dict[str, Any] | None = None
        self._cache_ts = 0.0
        try:
            self.ttl_seconds = max(15.0, min(300.0, float(os.getenv("ASTRA_REPLAY_COUNTERFACTUAL_TTL_SECONDS", "45"))))
        except Exception:
            self.ttl_seconds = 45.0
        try:
            self.max_rows = max(200, min(30000, int(float(os.getenv("ASTRA_REPLAY_COUNTERFACTUAL_MAX_ROWS", "8000")))))
        except Exception:
            self.max_rows = 8000

    def status(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.report(force_refresh=force_refresh)

    def summary(self, force_refresh: bool = False) -> dict[str, Any]:
        payload = self.report(force_refresh=force_refresh)
        return {
            "enabled": bool(payload.get("enabled", False)),
            "mode": str(payload.get("mode") or "shadow_counterfactual_analysis"),
            "counterfactual_row_count": int(_to_int(payload.get("counterfactual_row_count"), 0)),
            "best_policy": payload.get("best_counterfactual_policy"),
            "average_best_capture_ratio": payload.get("average_best_capture_ratio"),
            "average_worst_capture_ratio": payload.get("average_worst_capture_ratio"),
            "recommended_learning_use": payload.get("recommended_learning_use"),
        }

    def report(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if (
                not force_refresh
                and self._cache_payload is not None
                and (now - self._cache_ts) <= self.ttl_seconds
            ):
                return dict(self._cache_payload)

        payload = self._build_payload()
        with self._lock:
            self._cache_payload = dict(payload)
            self._cache_ts = time.time()
        return payload

    def _tail_jsonl(self, path: str, max_rows: int) -> list[dict[str, Any]]:
        rows: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_rows)))
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    s = str(raw or "").strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        rows.append(obj)
        except Exception:
            return []
        return list(rows)

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _return_pct(self, row: dict[str, Any]) -> float | None:
        for key in ("return_pct", "return_percent", "profit_loss_percent", "friction_adjusted_return", "pnl_pct"):
            if row.get(key) is not None:
                return _to_float(row.get(key), 0.0)
        return None

    def _normalize_trade(self, row: dict[str, Any], source: str) -> dict[str, Any] | None:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            return None
        actual = self._return_pct(row)
        if actual is None:
            return None
        best = max(
            _to_float(row.get("max_favorable_excursion_pct"), actual),
            _to_float(row.get("mfe_pct"), actual),
            _to_float(row.get("peak_return_pct"), actual),
            actual,
        )
        worst = min(
            _to_float(row.get("max_adverse_excursion_pct"), actual),
            -abs(_to_float(row.get("max_drawdown_pct"), 0.0)),
            _to_float(row.get("mae_pct"), actual),
            actual,
        )
        holding_minutes = _to_float(row.get("holding_period"), _to_float(row.get("duration_minutes"), 0.0))
        confidence = _to_float(row.get("confidence"), _to_float(row.get("confidence_score"), 0.0))
        entry_quality = _to_float(row.get("entry_quality_score"), _to_float(row.get("entry_quality_score_v2"), 0.0))
        return {
            "symbol": symbol,
            "source": source,
            "actual_return_pct": actual,
            "best_return_pct": best,
            "worst_return_pct": worst,
            "holding_minutes": holding_minutes,
            "confidence": confidence,
            "entry_quality_score": entry_quality,
            "exit_reason": str(row.get("exit_reason") or row.get("outcome_label") or row.get("win_label") or "unknown"),
        }

    def _counterfactuals_for_trade(self, trade: dict[str, Any]) -> list[dict[str, Any]]:
        actual = _to_float(trade.get("actual_return_pct"), 0.0)
        best = _to_float(trade.get("best_return_pct"), actual)
        worst = _to_float(trade.get("worst_return_pct"), actual)
        hold = _to_float(trade.get("holding_minutes"), 0.0)
        confidence = _to_float(trade.get("confidence"), 0.0)
        entry_quality = _to_float(trade.get("entry_quality_score"), 0.0)
        scenarios = {
            "stop_loss_1pct": max(actual, -1.0) if worst <= -1.0 else actual,
            "stop_loss_2pct": max(actual, -2.0) if worst <= -2.0 else actual,
            "trailing_exit_capture_50pct": max(actual, best * 0.50) if best > 0 else actual,
            "trailing_exit_capture_70pct": max(actual, best * 0.70) if best > 0 else actual,
            "half_hold_time": (actual * 0.55) + (best * 0.25) + (worst * 0.20),
            "double_hold_time": (actual * 0.70) + (best * 0.15) + (worst * 0.15),
            "early_exit_quality_guard": actual if entry_quality >= 60.0 else min(actual, 0.0),
            "confidence_scaled_hold": actual + ((confidence - 50.0) / 100.0) * max(-2.0, min(2.0, best - actual)),
        }
        denom = max(0.01, abs(best) if best > 0 else max(0.01, abs(actual)))
        rows = []
        for name, value in scenarios.items():
            rows.append(
                {
                    "symbol": trade.get("symbol"),
                    "scenario": name,
                    "counterfactual_return_pct": round(float(value), 6),
                    "actual_return_pct": round(actual, 6),
                    "delta_vs_actual_pct": round(float(value) - actual, 6),
                    "best_capture_ratio": round(max(0.0, min(2.0, float(value) / denom)), 6),
                    "worst_capture_ratio": round(max(0.0, min(2.0, abs(float(value)) / max(0.01, abs(worst)))) if worst < 0 else 0.0, 6),
                    "holding_minutes": round(hold, 3),
                    "label": "winner" if float(value) > 0 else "loser_or_flat",
                    "shadow_only": True,
                }
            )
        return rows

    def _build_payload(self) -> dict[str, Any]:
        max_each = max(50, int(self.max_rows / 3))
        lifecycle_rows = self._tail_jsonl(self.lifecycle_path, max_each)
        outcome_rows = self._tail_jsonl(self.outcome_path, max_each)
        candidate_rows = self._tail_jsonl(self.candidate_path, max_each)
        replay_json = self._read_json(self.replay_path)
        trades: list[dict[str, Any]] = []
        for source, rows in (
            ("trade_lifecycle_v1", lifecycle_rows),
            ("outcome_labels_v1", outcome_rows),
            ("candidate_decision_ledger_v1", candidate_rows),
        ):
            for row in rows:
                norm = self._normalize_trade(row, source)
                if norm is not None:
                    trades.append(norm)
        if len(trades) > self.max_rows:
            trades = trades[-self.max_rows :]
        cf_rows: list[dict[str, Any]] = []
        scenario_stats: dict[str, list[float]] = {}
        for trade in trades:
            for cf in self._counterfactuals_for_trade(trade):
                cf_rows.append(cf)
                scenario_stats.setdefault(str(cf.get("scenario")), []).append(_to_float(cf.get("delta_vs_actual_pct"), 0.0))
        scenario_summary = []
        for scenario, deltas in scenario_stats.items():
            avg_delta = statistics.fmean(deltas) if deltas else 0.0
            scenario_summary.append(
                {
                    "scenario": scenario,
                    "sample_count": int(len(deltas)),
                    "average_delta_vs_actual_pct": round(avg_delta, 6),
                    "positive_delta_rate": round((len([d for d in deltas if d > 0]) / max(1, len(deltas))) * 100.0, 3),
                }
            )
        scenario_summary.sort(key=lambda r: _to_float(r.get("average_delta_vs_actual_pct"), 0.0), reverse=True)
        capture_best = [_to_float(r.get("best_capture_ratio"), 0.0) for r in cf_rows]
        capture_worst = [_to_float(r.get("worst_capture_ratio"), 0.0) for r in cf_rows]
        best_policy = scenario_summary[0]["scenario"] if scenario_summary else None
        replay_rows_available = max(
            _to_int(replay_json.get("source_row_count"), 0),
            _to_int(replay_json.get("rows_evaluated"), 0),
            _to_int(replay_json.get("sample_count"), 0),
        )
        return {
            "enabled": True,
            "mode": "shadow_counterfactual_analysis",
            "replay_counterfactual_status_v1": True,
            "local_only": True,
            "api_calls_used": 0,
            "writes_files": False,
            "changes_live_rankings": False,
            "changes_live_top_buys": False,
            "generated_at": _now_iso(),
            "cache_ttl_seconds": int(self.ttl_seconds),
            "source_counts": {
                "trade_lifecycle_v1": int(len(lifecycle_rows)),
                "outcome_labels_v1": int(len(outcome_rows)),
                "candidate_decision_ledger_v1": int(len(candidate_rows)),
                "replay_rows_available": int(replay_rows_available),
            },
            "base_trade_count": int(len(trades)),
            "counterfactual_row_count": int(len(cf_rows)),
            "scenario_count": int(len(scenario_summary)),
            "scenario_summary": scenario_summary[:12],
            "best_counterfactual_policy": best_policy,
            "average_best_capture_ratio": round(statistics.fmean(capture_best), 6) if capture_best else 0.0,
            "average_worst_capture_ratio": round(statistics.fmean(capture_worst), 6) if capture_worst else 0.0,
            "recommended_learning_use": (
                "use_as_shadow_training_examples_only" if len(cf_rows) >= 100 else "collect_more_real_outcomes_first"
            ),
            "sample": cf_rows[:30],
        }
