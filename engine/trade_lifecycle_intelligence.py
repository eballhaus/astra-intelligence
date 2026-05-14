"""Trade Lifecycle Intelligence V1 (local-only, shadow diagnostics)."""

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


def _parse_iso(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


class TradeLifecycleIntelligence:
    """Evaluates completed trade outcomes without changing live decisions."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.candidate_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.outcome_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self._lock = threading.Lock()
        self._cache_payload: dict[str, Any] | None = None
        self._cache_ts = 0.0
        try:
            self.cache_ttl_seconds = max(15.0, min(300.0, float(os.getenv("ASTRA_TRADE_LIFECYCLE_TTL_SECONDS", "45"))))
        except Exception:
            self.cache_ttl_seconds = 45.0
        try:
            self.max_rows = max(200, min(30000, int(float(os.getenv("ASTRA_TRADE_LIFECYCLE_MAX_ROWS", "7000")))))
        except Exception:
            self.max_rows = 7000

    def status(self, force_refresh: bool = False) -> dict[str, Any]:
        return self.report(force_refresh=force_refresh)

    def report(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if (
                not force_refresh
                and self._cache_payload is not None
                and (now - self._cache_ts) <= self.cache_ttl_seconds
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

    def _return_pct(self, row: dict[str, Any]) -> float | None:
        for key in (
            "return_pct",
            "return_percent",
            "profit_loss_percent",
            "friction_adjusted_return",
            "pnl_pct",
        ):
            if row.get(key) is not None:
                return _to_float(row.get(key), 0.0)
        return None

    def _is_closed(self, row: dict[str, Any]) -> bool:
        stage = str(row.get("lifecycle_stage") or row.get("status") or "").strip().lower()
        return bool(
            stage.startswith("closed")
            or stage in {"exited", "complete", "completed"}
            or str(row.get("exit_timestamp") or "").strip()
            or self._return_pct(row) is not None
        )

    def _normalize_trade(self, row: dict[str, Any], source: str) -> dict[str, Any] | None:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            return None
        ret = self._return_pct(row)
        closed = self._is_closed(row)
        entered_raw = (
            row.get("entry_timestamp")
            or row.get("opened_at")
            or row.get("signal_timestamp")
            or row.get("timestamp_utc")
            or row.get("evaluated_at_utc")
            or row.get("created_at")
            or ""
        )
        exited_raw = row.get("exit_timestamp") or row.get("closed_at") or row.get("evaluated_at_utc") or ""
        entered_dt = _parse_iso(entered_raw)
        exited_dt = _parse_iso(exited_raw)
        hold_minutes = _to_float(row.get("holding_period"), _to_float(row.get("duration_minutes"), 0.0))
        if hold_minutes <= 0 and entered_dt is not None and exited_dt is not None:
            hold_minutes = max(0.0, (exited_dt.timestamp() - entered_dt.timestamp()) / 60.0)
        if ret is None and not closed:
            return None
        return {
            "symbol": symbol,
            "source": source,
            "return_pct": _to_float(ret, 0.0),
            "closed": bool(closed),
            "entry_quality_score": _to_float(row.get("entry_quality_score"), _to_float(row.get("entry_quality_score_v2"), 0.0)),
            "confidence": _to_float(row.get("confidence"), _to_float(row.get("confidence_score"), 0.0)),
            "max_drawdown_pct": _to_float(row.get("max_drawdown_pct"), _to_float(row.get("drawdown_pct"), 0.0)),
            "mfe_efficiency_score": _to_float(row.get("mfe_efficiency_score"), 0.0),
            "holding_minutes": hold_minutes,
            "exit_reason": str(row.get("exit_reason") or row.get("outcome_label") or row.get("win_label") or "unknown"),
            "event_time": str(exited_raw or entered_raw or ""),
        }

    def _closed_metrics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        closed = [r for r in rows if bool(r.get("closed"))]
        returns = [_to_float(r.get("return_pct"), 0.0) for r in closed]
        wins = [x for x in returns if x > 0]
        losses = [x for x in returns if x <= 0]
        avg_return = statistics.fmean(returns) if returns else 0.0
        median_return = statistics.median(returns) if returns else 0.0
        gross_profit = sum(wins)
        gross_loss_abs = abs(sum(losses))
        profit_factor = gross_profit / max(1e-9, gross_loss_abs) if gross_profit > 0 else 0.0
        avg_hold = statistics.fmean([_to_float(r.get("holding_minutes"), 0.0) for r in closed]) if closed else 0.0
        avg_drawdown = statistics.fmean([_to_float(r.get("max_drawdown_pct"), 0.0) for r in closed]) if closed else 0.0
        avg_mfe_eff = statistics.fmean([_to_float(r.get("mfe_efficiency_score"), 0.0) for r in closed]) if closed else 0.0
        return {
            "closed_trade_count": int(len(closed)),
            "win_count": int(len(wins)),
            "loss_count": int(len(losses)),
            "win_rate": round((len(wins) / max(1, len(closed))) * 100.0, 3),
            "average_return": round(avg_return, 6),
            "median_return": round(median_return, 6),
            "profit_factor": round(profit_factor, 6),
            "average_holding_minutes": round(avg_hold, 3),
            "average_drawdown_pct": round(avg_drawdown, 6),
            "average_mfe_efficiency_score": round(avg_mfe_eff, 3),
        }

    def _recommendations(self, metrics: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        closed_count = _to_int(metrics.get("closed_trade_count"), 0)
        win_rate = _to_float(metrics.get("win_rate"), 0.0)
        profit_factor = _to_float(metrics.get("profit_factor"), 0.0)
        avg_drawdown = _to_float(metrics.get("average_drawdown_pct"), 0.0)
        recommendations: list[dict[str, Any]] = []
        if closed_count < 30:
            recommendations.append(
                {
                    "recommendation": "continue_collecting_outcomes",
                    "severity": "info",
                    "confidence": 0.45,
                    "reason": "closed_trade_sample_below_30",
                    "bounded_policy_adjustment": "none_shadow_only",
                }
            )
        else:
            if win_rate < 48.0 or profit_factor < 1.0:
                recommendations.append(
                    {
                        "recommendation": "tighten_release_quality",
                        "severity": "caution",
                        "confidence": 0.68,
                        "reason": "closed_trade_outcomes_below_quality_floor",
                        "bounded_policy_adjustment": "raise entry/confirmation thresholds by 2-4 points after human review",
                    }
                )
            if avg_drawdown > 3.5:
                recommendations.append(
                    {
                        "recommendation": "reduce_initial_risk",
                        "severity": "caution",
                        "confidence": 0.62,
                        "reason": "average_drawdown_elevated",
                        "bounded_policy_adjustment": "route weaker setups to smaller sizing or paper-only",
                    }
                )
            if not recommendations:
                recommendations.append(
                    {
                        "recommendation": "keep_current",
                        "severity": "info",
                        "confidence": 0.70,
                        "reason": "closed_trade_outcomes_stable",
                        "bounded_policy_adjustment": "none_shadow_only",
                    }
                )
        return recommendations[:6]

    def _build_payload(self) -> dict[str, Any]:
        max_each = max(50, int(self.max_rows / 3))
        lifecycle_raw = self._tail_jsonl(self.lifecycle_path, max_each)
        candidate_raw = self._tail_jsonl(self.candidate_path, max_each)
        outcome_raw = self._tail_jsonl(self.outcome_path, max_each)
        rows: list[dict[str, Any]] = []
        for source, raw_rows in (
            ("trade_lifecycle_v1", lifecycle_raw),
            ("candidate_decision_ledger_v1", candidate_raw),
            ("outcome_labels_v1", outcome_raw),
        ):
            for raw in raw_rows:
                norm = self._normalize_trade(raw, source)
                if norm is not None:
                    rows.append(norm)
        rows.sort(key=lambda r: str(r.get("event_time") or ""))
        if len(rows) > self.max_rows:
            rows = rows[-self.max_rows :]
        metrics = self._closed_metrics(rows)
        by_source: dict[str, int] = {}
        exit_reasons: dict[str, int] = {}
        for row in rows:
            src = str(row.get("source") or "unknown")
            by_source[src] = int(by_source.get(src, 0)) + 1
            reason = str(row.get("exit_reason") or "unknown").strip().lower()[:80]
            exit_reasons[reason] = int(exit_reasons.get(reason, 0)) + 1
        return {
            "enabled": True,
            "mode": "shadow_lifecycle_intelligence",
            "trade_lifecycle_status_v1": True,
            "institutional_intelligence_bundle_2": True,
            "version": "v1",
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "cache_ttl_seconds": int(self.cache_ttl_seconds),
            "max_rows": int(self.max_rows),
            "source_counts": {
                "trade_lifecycle_v1": int(len(lifecycle_raw)),
                "candidate_decision_ledger_v1": int(len(candidate_raw)),
                "outcome_labels_v1": int(len(outcome_raw)),
            },
            "normalized_trade_count": int(len(rows)),
            "metrics": metrics,
            "source_mix": by_source,
            "exit_reason_counts": dict(sorted(exit_reasons.items(), key=lambda item: item[1], reverse=True)[:12]),
            "recommendations": self._recommendations(metrics, rows),
            "sample": rows[-20:],
        }
