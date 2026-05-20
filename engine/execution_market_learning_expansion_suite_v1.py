from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 4_000_000
MAX_ROWS = 2_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


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


def _parse_dt(value: Any) -> datetime | None:
    raw = _safe_text(value)
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _row_time(row: dict[str, Any]) -> datetime | None:
    for key in (
        "updated_at",
        "timestamp_utc",
        "evaluated_at_utc",
        "entry_timestamp",
        "entry_timestamp_utc",
        "exit_timestamp",
        "exit_timestamp_utc",
    ):
        dt = _parse_dt(row.get(key))
        if dt is not None:
            return dt
    return None


def _is_today(row: dict[str, Any], today: str) -> bool:
    dt = _row_time(row)
    return bool(dt and dt.date().isoformat() == today)


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


def _load_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _avg(rows: list[dict[str, Any]], key: str, default: float = 0.0) -> float:
    values = [_to_float(row.get(key), float("nan")) for row in rows]
    values = [v for v in values if v == v]
    return mean(values) if values else default


def _label(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 65:
        return "healthy"
    if score >= 45:
        return "watch"
    return "needs_attention"


class ExecutionMarketLearningExpansionSuiteV1:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.stable_top_buys_path = os.path.join(self.state_dir, "snapshots", "stable_top_buys_v1.json")

    def status(self, observation_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return self._status(observation_payload or {})
        except Exception as exc:
            return self._fallback(f"execution_market_learning_expansion_unavailable: {str(exc)[:140]}")

    def _status(self, observation_payload: dict[str, Any]) -> dict[str, Any]:
        today = _now().date().isoformat()
        lifecycle = _tail_jsonl(self.lifecycle_path)
        labels = _tail_jsonl(self.labels_path)
        ledger = _tail_jsonl(self.ledger_path)
        stable = _load_json(self.stable_top_buys_path)
        top_rows = [r for r in stable.get("stable_top_6") or [] if isinstance(r, dict)]

        lifecycle_today = [r for r in lifecycle if _is_today(r, today)]
        label_today = [r for r in labels if _is_today(r, today)]
        ledger_today = [r for r in ledger if _is_today(r, today)]

        current_entries_today = int(
            _to_float(observation_payload.get("trades_opened_today"), 0.0)
            or len({(_safe_text(r.get("lifecycle_id")) or _safe_text(r.get("symbol")) or str(i)) for i, r in enumerate(lifecycle_today) if _safe_text(r.get("entry_timestamp") or r.get("entry_timestamp_utc"))})
        )
        current_closures_today = int(
            _to_float(observation_payload.get("trades_closed_today"), 0.0)
            or len({(_safe_text(r.get("lifecycle_id")) or _safe_text(r.get("symbol")) or str(i)) for i, r in enumerate(lifecycle_today) if _safe_text(r.get("exit_timestamp") or r.get("exit_timestamp_utc"))})
        )
        labels_today = int(_to_float(observation_payload.get("labels_created_today"), 0.0) or len(label_today))
        open_monitoring = len(
            {
                _safe_text(r.get("lifecycle_id")) or _safe_text(r.get("symbol")) or str(i)
                for i, r in enumerate(lifecycle)
                if _safe_text(r.get("lifecycle_stage")).lower() in {"monitoring", "open", "active"}
                and not _safe_text(r.get("exit_timestamp") or r.get("exit_timestamp_utc"))
            }
        )

        observation_completion = _to_float(observation_payload.get("observation_completion_score"), 0.0)
        learning_throughput = _to_float(observation_payload.get("learning_throughput_score"), 0.0)
        current_bottleneck = _safe_text(observation_payload.get("primary_learning_bottleneck"), "insufficient_closed_trades")

        avg_confidence = _avg(top_rows or ledger_today, "confidence", 70.0)
        avg_entry_quality = _avg(top_rows or ledger_today, "entry_quality_v3_score", _avg(top_rows or ledger_today, "entry_quality_score", 45.0))
        avg_liquidity_proxy = _avg(top_rows or ledger_today, "live_quality_score", _avg(top_rows or ledger_today, "data_quality_score", 65.0))
        avg_context = _avg(top_rows or ledger_today, "context_score", 50.0)
        avg_portfolio_risk = _avg(top_rows, "portfolio_risk_score", 62.0) if top_rows else 62.0
        avg_spread_proxy = max(0.0, 100.0 - avg_liquidity_proxy)

        insufficient_labels = sum(1 for r in label_today if _safe_text(r.get("outcome_label")).lower() == "insufficient_data")
        insufficient_rate = (insufficient_labels / max(1, labels_today)) * 100.0 if labels_today else 0.0

        liquidity_score = _clamp((avg_liquidity_proxy * 0.70) + (avg_confidence * 0.20) + (avg_portfolio_risk * 0.10))
        expected_slippage_bps = round(_clamp(55.0 - (liquidity_score * 0.42) + (avg_spread_proxy * 0.20), 4.0, 80.0), 3)
        order_execution_score = _clamp((liquidity_score * 0.40) + (avg_entry_quality * 0.25) + (avg_confidence * 0.20) + (avg_portfolio_risk * 0.15))
        execution_readiness_score = _clamp(order_execution_score - max(0.0, insufficient_rate - 50.0) * 0.10)
        limit_order_preference = "prefer_limit_orders" if expected_slippage_bps >= 18.0 else "limit_or_midpoint_ok"

        catalyst_hits = sum(1 for r in label_today + ledger_today + top_rows if bool(r.get("catalyst_flag")) or _safe_text(r.get("catalyst_context")))
        analyst_hits = sum(1 for r in label_today + ledger_today + top_rows if _safe_text(r.get("analyst_context") or r.get("analyst_rating") or r.get("analyst_signal")))
        sentiment_hits = sum(1 for r in label_today + ledger_today + top_rows if _safe_text(r.get("sentiment_context") or r.get("sentiment_signal") or r.get("news_sentiment")))
        local_context_n = max(1, len(label_today + ledger_today + top_rows))
        catalyst_context_score = _clamp(45.0 + min(25.0, (catalyst_hits / local_context_n) * 100.0))
        analyst_context_score = _clamp(42.0 + min(20.0, (analyst_hits / local_context_n) * 100.0))
        sentiment_context_score = _clamp(42.0 + min(20.0, (sentiment_hits / local_context_n) * 100.0))
        market_knowledge_score = _clamp((catalyst_context_score * 0.34) + (analyst_context_score * 0.26) + (sentiment_context_score * 0.26) + (avg_context * 0.14))

        entry_utilization_score = _clamp(min(100.0, current_entries_today * 18.0 + open_monitoring * 3.0))
        closure_utilization_score = _clamp(min(100.0, current_closures_today * 22.0 + labels_today * 0.45) - insufficient_rate * 0.18)
        learning_expansion_score = _clamp((entry_utilization_score * 0.30) + (closure_utilization_score * 0.35) + (observation_completion * 0.20) + (learning_throughput * 0.15))

        primary_constraint = self._primary_constraint(
            current_bottleneck,
            current_entries_today,
            current_closures_today,
            insufficient_rate,
            avg_entry_quality,
            execution_readiness_score,
        )

        suggested_new = 1
        suggested_concurrent = 4
        threshold_adjustment = "no_change"
        soft_allowance = "allow_paper_only_soft_candidates_when_execution_ready"
        cooldown = 240
        if primary_constraint in {"insufficient_entries", "insufficient_closed_trades"} and execution_readiness_score >= 55.0:
            suggested_new = 2
            suggested_concurrent = 6 if avg_portfolio_risk >= 55.0 else 5
            threshold_adjustment = "slightly_relax_paper_only_thresholds_shadow_recommendation"
            cooldown = 180
        if primary_constraint in {"label_quality_gap", "execution_quality_gap"}:
            suggested_new = 1
            suggested_concurrent = min(suggested_concurrent, 4)
            threshold_adjustment = "hold_thresholds_until_quality_improves"
            cooldown = 360

        projected_trades_opened_per_day = round(max(current_entries_today, suggested_new * 6), 3)
        natural_close_rate = 0.28 if open_monitoring > 0 else 0.18
        projected_trades_closed_per_day = round(max(current_closures_today, projected_trades_opened_per_day * natural_close_rate), 3)
        projected_labels_created_per_day = round(max(labels_today, projected_trades_closed_per_day * 3.0), 3)
        projected_learning_speed_multiplier = round(_clamp(1.0 + (suggested_new * 0.18) + (learning_expansion_score / 300.0), 1.0, 3.5), 3)

        master_score = _clamp(
            (execution_readiness_score * 0.30)
            + (market_knowledge_score * 0.18)
            + (learning_expansion_score * 0.30)
            + (observation_completion * 0.12)
            + (avg_portfolio_risk * 0.10)
        )
        reasons, penalties = self._reasons_penalties(
            execution_readiness_score,
            market_knowledge_score,
            learning_expansion_score,
            current_closures_today,
            insufficient_rate,
            primary_constraint,
        )

        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "forced_early_exits": False,
            "execution_market_learning_expansion_status_v1": True,
            "generated_at": _now_iso(),
            "source_files": [self.lifecycle_path, self.labels_path, self.ledger_path, self.stable_top_buys_path],
            "max_rows_per_file": MAX_ROWS,
            "max_tail_bytes": MAX_TAIL_BYTES,
            "current_entries_today": current_entries_today,
            "current_closures_today": current_closures_today,
            "current_labels_today": labels_today,
            "open_paper_positions_observed": open_monitoring,
            "suggested_max_new_paper_trades_per_cycle": suggested_new,
            "suggested_max_concurrent_paper_positions": suggested_concurrent,
            "suggested_paper_entry_threshold_adjustment": threshold_adjustment,
            "suggested_paper_only_soft_candidate_allowance": soft_allowance,
            "suggested_paper_cooldown_seconds": cooldown,
            "projected_trades_opened_per_day": projected_trades_opened_per_day,
            "projected_trades_closed_per_day": projected_trades_closed_per_day,
            "projected_labels_created_per_day": projected_labels_created_per_day,
            "projected_learning_speed_multiplier": projected_learning_speed_multiplier,
            "expected_slippage_bps": expected_slippage_bps,
            "liquidity_score": round(liquidity_score, 3),
            "order_execution_score": round(order_execution_score, 3),
            "limit_order_preference": limit_order_preference,
            "execution_readiness_score": round(execution_readiness_score, 3),
            "execution_reasons": reasons[:5],
            "execution_penalties": penalties[:5],
            "execution_summary": (
                f"Execution readiness {_label(execution_readiness_score)} with expected slippage "
                f"near {expected_slippage_bps:.1f} bps; {limit_order_preference.replace('_', ' ')}."
            ),
            "catalyst_context_score": round(catalyst_context_score, 3),
            "analyst_context_score": round(analyst_context_score, 3),
            "sentiment_context_score": round(sentiment_context_score, 3),
            "market_knowledge_score": round(market_knowledge_score, 3),
            "market_knowledge_label": _label(market_knowledge_score),
            "market_knowledge_summary": "Local-only catalyst, analyst, and sentiment placeholders are active; no external calls used.",
            "entry_utilization_score": round(entry_utilization_score, 3),
            "closure_utilization_score": round(closure_utilization_score, 3),
            "learning_expansion_score": round(learning_expansion_score, 3),
            "primary_learning_constraint": primary_constraint,
            "expansion_summary": (
                f"Shadow paper throughput can be nudged to {suggested_new}/cycle and "
                f"{suggested_concurrent} concurrent positions without forcing exits."
            ),
            "master_suite_3_score": round(master_score, 3),
            "master_suite_3_label": _label(master_score),
            "master_suite_3_reasons": reasons,
            "master_suite_3_penalties": penalties,
            "master_suite_3_summary": (
                f"Primary constraint is {primary_constraint.replace('_', ' ')}. "
                f"Recommend paper-only observation expansion while preserving existing exit logic."
            ),
            "next_recommended_action": "review_shadow_recommendations_without_changing_live_or_paper_execution_settings",
        }

    def _primary_constraint(
        self,
        bottleneck: str,
        entries: int,
        closures: int,
        insufficient_rate: float,
        entry_quality: float,
        execution_score: float,
    ) -> str:
        if closures <= 0 or bottleneck == "insufficient_closed_trades":
            return "insufficient_closed_trades"
        if entries <= 0:
            return "insufficient_entries"
        if insufficient_rate >= 55.0:
            return "label_quality_gap"
        if entry_quality < 40.0:
            return "entry_quality_gap"
        if execution_score < 50.0:
            return "execution_quality_gap"
        return "healthy"

    def _reasons_penalties(
        self,
        execution_score: float,
        market_knowledge_score: float,
        learning_expansion_score: float,
        closures: int,
        insufficient_rate: float,
        constraint: str,
    ) -> tuple[list[str], list[str]]:
        reasons: list[str] = []
        penalties: list[str] = []
        if execution_score >= 55:
            reasons.append("execution_readiness_supports_paper_only_expansion")
        else:
            penalties.append("execution_readiness_below_target")
        if market_knowledge_score >= 45:
            reasons.append("local_market_knowledge_placeholders_active")
        else:
            penalties.append("market_knowledge_context_sparse")
        if learning_expansion_score >= 45:
            reasons.append("learning_expansion_path_available")
        else:
            penalties.append("learning_expansion_needs_more_completed_observations")
        if closures <= 0:
            penalties.append("no_new_natural_closures_detected_today")
        if insufficient_rate >= 55:
            penalties.append("insufficient_data_label_rate_elevated")
        if constraint == "healthy":
            reasons.append("no_major_learning_constraint_detected")
        return list(dict.fromkeys(reasons))[:8], list(dict.fromkeys(penalties))[:8]

    def _fallback(self, reason: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "forced_early_exits": False,
            "execution_market_learning_expansion_status_v1": True,
            "current_entries_today": 0,
            "current_closures_today": 0,
            "suggested_max_new_paper_trades_per_cycle": 0,
            "suggested_max_concurrent_paper_positions": 0,
            "projected_trades_opened_per_day": 0.0,
            "projected_trades_closed_per_day": 0.0,
            "projected_labels_created_per_day": 0.0,
            "projected_learning_speed_multiplier": 1.0,
            "expected_slippage_bps": 0.0,
            "liquidity_score": 0.0,
            "execution_readiness_score": 0.0,
            "market_knowledge_score": 0.0,
            "learning_expansion_score": 0.0,
            "master_suite_3_score": 0.0,
            "primary_learning_constraint": "suite_error",
            "master_suite_3_summary": reason,
        }
