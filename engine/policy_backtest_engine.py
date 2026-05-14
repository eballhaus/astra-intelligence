"""Shadow-only policy backtest and A/B comparison engine (V2)."""

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


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value or "").strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


class PolicyBacktestEngine:
    """Compares candidate policies using local rows only (no provider/API calls)."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self._cache_lock = threading.Lock()
        self._cache_payload: dict[str, Any] | None = None
        self._cache_ts = 0.0
        try:
            self._cache_ttl_seconds = max(
                15.0,
                min(300.0, float(os.getenv("ASTRA_POLICY_COMPARE_TTL_SECONDS", "45"))),
            )
        except Exception:
            self._cache_ttl_seconds = 45.0
        try:
            self._max_rows = max(
                200,
                min(10000, int(float(os.getenv("ASTRA_POLICY_COMPARE_MAX_ROWS", "2500")))),
            )
        except Exception:
            self._max_rows = 2500
        self._paths = [
            os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl"),
            os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl"),
            os.path.join(self.state_dir, "outcome_labels_v1.jsonl"),
        ]

    def status(self) -> dict[str, Any]:
        with self._cache_lock:
            cache_age = max(0.0, time.time() - self._cache_ts) if self._cache_ts > 0 else None
            cache_ready = bool(self._cache_payload)
        return {
            "enabled": True,
            "mode": "shadow_analysis",
            "policy_backtest_engine_version": "v2",
            "institutional_intelligence_bundle_2": True,
            "cache_ttl_seconds": int(self._cache_ttl_seconds),
            "cache_ready": cache_ready,
            "cache_age_seconds": round(cache_age, 3) if cache_age is not None else None,
            "max_rows": int(self._max_rows),
            "data_sources": [p for p in self._paths],
            "local_only": True,
            "api_calls_used": 0,
        }

    def compare_policies(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        with self._cache_lock:
            if (
                not force_refresh
                and self._cache_payload is not None
                and (now - self._cache_ts) <= self._cache_ttl_seconds
            ):
                return dict(self._cache_payload)

        rows, source_counts = self._load_rows()
        payload = self._build_result(rows, source_counts)
        with self._cache_lock:
            self._cache_payload = dict(payload)
            self._cache_ts = time.time()
        return payload

    def _load_rows(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        rows: list[dict[str, Any]] = []
        source_counts: dict[str, int] = {}
        max_per_file = max(50, int(self._max_rows / max(1, len(self._paths))))
        for path in self._paths:
            loaded = 0
            try:
                if not os.path.exists(path):
                    source_counts[path] = 0
                    continue
                tail_rows: deque[dict[str, Any]] = deque(maxlen=max_per_file)
                with open(path, "r", encoding="utf-8") as f:
                    for raw in f:
                        s = str(raw or "").strip()
                        if not s:
                            continue
                        try:
                            obj = json.loads(s)
                        except Exception:
                            continue
                        if not isinstance(obj, dict):
                            continue
                        row = self._normalize_row(obj)
                        if row is None:
                            continue
                        tail_rows.append(row)
                loaded = len(tail_rows)
                rows.extend(list(tail_rows))
                source_counts[path] = loaded
            except Exception:
                source_counts[path] = loaded
        rows.sort(key=lambda r: str(r.get("event_time") or ""))
        if len(rows) > self._max_rows:
            rows = rows[-self._max_rows :]
        return rows, source_counts

    def _normalize_row(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        ret = raw.get("return_pct")
        if ret is None:
            ret = raw.get("pnl_pct")
        if ret is None:
            ret = raw.get("return_percent")
        ret_f = _to_float(ret, 0.0)
        has_outcome = any(
            [
                raw.get("outcome_label") is not None,
                raw.get("win_label") is not None,
                raw.get("exit_reason") is not None,
                ret is not None,
            ]
        )
        if not has_outcome:
            return None
        symbol = str(raw.get("symbol") or "").strip().upper()
        if not symbol:
            return None
        return {
            "symbol": symbol,
            "return_pct": ret_f,
            "confidence": _to_float(raw.get("confidence"), _to_float(raw.get("confidence_score"), 0.0)),
            "entry_quality_score": _to_float(raw.get("entry_quality_score"), 0.0),
            "grade_percent": _to_float(raw.get("grade_percent"), 0.0),
            "released": _to_bool(raw.get("released")) or str(raw.get("release_status") or "").strip().lower() in {"released", "paper_ready"},
            "event_time": str(
                raw.get("entry_timestamp")
                or raw.get("signal_timestamp")
                or raw.get("timestamp_utc")
                or raw.get("evaluated_at_utc")
                or raw.get("timestamp")
                or raw.get("created_at")
                or ""
            ),
            "outcome_label": str(raw.get("outcome_label") or raw.get("win_label") or ""),
            "raw": raw,
        }

    def _passes_policy(self, policy: str, row: dict[str, Any]) -> bool:
        entry_q = _to_float(row.get("entry_quality_score"), 0.0)
        conf = _to_float(row.get("confidence"), 0.0)
        grade = _to_float(row.get("grade_percent"), 0.0)
        released = bool(row.get("released"))
        has_outcome = str(row.get("outcome_label") or "").strip().lower() not in {"", "insufficient_data"}
        if policy == "current_policy":
            return released or (entry_q >= 55.0 and conf >= 45.0) or has_outcome
        if policy == "entry_quality_v2_shadow_policy":
            return entry_q >= 62.0 and conf >= 50.0
        if policy == "conservative_confirmation_policy":
            return entry_q >= 70.0 and conf >= 60.0 and grade >= 65.0
        if policy == "soft_buy_policy":
            return entry_q >= 55.0 and conf >= 40.0
        if policy == "hard_buy_policy":
            return entry_q >= 75.0 and conf >= 65.0 and grade >= 72.0
        return False

    def _metrics_for_policy(
        self, policy: str, rows: list[dict[str, Any]], current_selected: list[dict[str, Any]]
    ) -> dict[str, Any]:
        selected = [r for r in rows if self._passes_policy(policy, r)]
        returns = [_to_float(r.get("return_pct"), 0.0) for r in selected]
        wins = [x for x in returns if x > 0]
        losses = [x for x in returns if x <= 0]
        sample_count = len(selected)
        win_rate = (len(wins) / max(1, sample_count)) * 100.0
        avg_return = statistics.fmean(returns) if returns else 0.0
        median_return = statistics.median(returns) if returns else 0.0
        gross_profit = sum(wins)
        gross_loss_abs = abs(sum(losses))
        profit_factor = gross_profit / max(1e-9, gross_loss_abs) if gross_profit > 0 else 0.0

        all_bad = [r for r in rows if _to_float(r.get("return_pct"), 0.0) < 0]
        all_winners = [r for r in rows if _to_float(r.get("return_pct"), 0.0) > 0]
        prevented_bad_entries = len([r for r in all_bad if not self._passes_policy(policy, r)])
        missed_winners = len([r for r in all_winners if not self._passes_policy(policy, r)])
        false_positive_rate = (len(losses) / max(1, sample_count)) * 100.0
        false_negative_rate = (missed_winners / max(1, len(all_winners))) * 100.0

        base_win_rate = (
            (len([_to_float(r.get("return_pct"), 0.0) for r in current_selected if _to_float(r.get("return_pct"), 0.0) > 0]) / max(1, len(current_selected))) * 100.0
            if current_selected
            else 0.0
        )
        released_vs_blocked_gap = win_rate - base_win_rate
        confidence_truthfulness = max(0.0, min(100.0, 100.0 - false_positive_rate))

        return {
            "sample_count": int(sample_count),
            "win_rate": round(win_rate, 3),
            "average_return": round(avg_return, 6),
            "median_return": round(median_return, 6),
            "profit_factor": round(profit_factor, 6),
            "prevented_bad_entries": int(prevented_bad_entries),
            "missed_winners": int(missed_winners),
            "false_positive_rate": round(false_positive_rate, 3),
            "false_negative_rate": round(false_negative_rate, 3),
            "released_vs_blocked_gap": round(released_vs_blocked_gap, 3),
            "confidence_truthfulness": round(confidence_truthfulness, 3),
        }

    def _build_result(self, rows: list[dict[str, Any]], source_counts: dict[str, int]) -> dict[str, Any]:
        policies = [
            "current_policy",
            "entry_quality_v2_shadow_policy",
            "conservative_confirmation_policy",
            "soft_buy_policy",
            "hard_buy_policy",
        ]
        current_selected = [r for r in rows if self._passes_policy("current_policy", r)]
        metrics_by_policy = {
            name: self._metrics_for_policy(name, rows, current_selected) for name in policies
        }
        enough_data = len(rows) >= 80 and metrics_by_policy["current_policy"]["sample_count"] >= 30
        winner = None
        recommendation = "insufficient_data"
        reason_summary = "Insufficient comparable local outcomes."

        if enough_data:
            scored = []
            for name, m in metrics_by_policy.items():
                score = (
                    (_to_float(m.get("win_rate"), 0.0) * 0.45)
                    + (_to_float(m.get("average_return"), 0.0) * 12.0)
                    + (_to_float(m.get("confidence_truthfulness"), 0.0) * 0.35)
                    - (_to_float(m.get("false_negative_rate"), 0.0) * 0.15)
                )
                scored.append((name, score))
            scored.sort(key=lambda x: x[1], reverse=True)
            winner = scored[0][0] if scored else None
            if winner == "current_policy":
                recommendation = "keep_current"
                reason_summary = "Current policy remains strongest on local evidence."
            else:
                delta = scored[0][1] - scored[1][1] if len(scored) > 1 else 0.0
                if delta >= 4.0:
                    recommendation = "promote_candidate_later"
                    reason_summary = f"{winner} outperforms current policy on local sample."
                else:
                    recommendation = "monitor"
                    reason_summary = f"{winner} is promising but evidence gap is modest."

        return {
            "enabled": True,
            "mode": "shadow_analysis",
            "policy_backtest_engine_version": "v2",
            "institutional_intelligence_bundle_2": True,
            "generated_at": _now_iso(),
            "policies_compared": policies,
            "winner": winner,
            "recommendation": recommendation,
            "reason_summary": reason_summary,
            "evidence_based": bool(enough_data),
            "source_row_count": int(len(rows)),
            "source_counts": dict(source_counts),
            "metrics_by_policy": metrics_by_policy,
            "policy_adjustment_recommendations": self._policy_adjustment_recommendations(
                metrics_by_policy=metrics_by_policy,
                enough_data=enough_data,
                winner=winner,
            ),
            "api_calls_used": 0,
            "bandwidth_used": 0,
            "local_only": True,
        }

    def _policy_adjustment_recommendations(
        self,
        *,
        metrics_by_policy: dict[str, dict[str, Any]],
        enough_data: bool,
        winner: str | None,
    ) -> list[dict[str, Any]]:
        if not enough_data:
            return [
                {
                    "recommendation": "continue_collecting_policy_outcomes",
                    "severity": "info",
                    "confidence": 0.45,
                    "reason": "policy_backtest_sample_below_v2_threshold",
                    "safe_action": "shadow_only_no_live_policy_change",
                }
            ]
        current = dict(metrics_by_policy.get("current_policy") or {})
        winning = dict(metrics_by_policy.get(str(winner or "")) or {})
        current_wr = _to_float(current.get("win_rate"), 0.0)
        winning_wr = _to_float(winning.get("win_rate"), 0.0)
        current_pf = _to_float(current.get("profit_factor"), 0.0)
        winning_pf = _to_float(winning.get("profit_factor"), 0.0)
        if winner and winner != "current_policy" and (winning_wr - current_wr) >= 3.0 and winning_pf >= current_pf:
            return [
                {
                    "recommendation": "promote_policy_candidate_to_shadow_gate",
                    "policy": str(winner),
                    "severity": "caution",
                    "confidence": 0.68,
                    "reason": "candidate_policy_outperformed_current_on_local_outcomes",
                    "safe_action": "review_before_any_live_threshold_change",
                }
            ]
        return [
            {
                "recommendation": "keep_current_policy",
                "policy": "current_policy",
                "severity": "info",
                "confidence": 0.72,
                "reason": "no_candidate_policy_has_sufficient_v2_edge",
                "safe_action": "continue_monitoring",
            }
        ]
