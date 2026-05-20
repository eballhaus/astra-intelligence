from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from statistics import median
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 4_000_000
MAX_ROWS_PER_FILE = 2_000


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
        "evaluated_at_utc",
        "timestamp_utc",
        "generated_at",
        "entry_timestamp_utc",
        "exit_timestamp_utc",
        "entry_timestamp",
        "exit_timestamp",
        "closed_at",
        "opened_at",
    ):
        dt = _parse_dt(row.get(key))
        if dt is not None:
            return dt
    return None


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS_PER_FILE, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            data = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = data.splitlines()
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


def _is_today(row: dict[str, Any], today: str) -> bool:
    dt = _row_time(row)
    return bool(dt and dt.date().isoformat() == today)


def _has_any(row: dict[str, Any], needles: tuple[str, ...]) -> bool:
    hay = " ".join(
        _safe_text(row.get(k)).lower()
        for k in (
            "lifecycle_stage",
            "release_status",
            "source_endpoint",
            "outcome_label",
            "exit_reason",
            "canonical_state",
            "status",
            "action",
            "final_action",
            "qualification",
            "promotion_type",
            "promotion_reason",
            "entry_quality_band",
            "exit_quality_band",
            "learning_activation_decision",
            "setup_type",
            "regime_context",
            "risk_tier",
            "sizing_tier",
        )
    )
    return any(n in hay for n in needles)


def _label_has_entry(row: dict[str, Any]) -> bool:
    return bool(
        _to_float(row.get("entry_quality_score"), 0.0) > 0
        or _safe_text(row.get("entry_quality_band"))
        or _safe_text(row.get("entry_precision_v2_decision"))
        or _has_any(row, ("good_entry", "bad_entry", "entry"))
    )


def _label_has_exit(row: dict[str, Any]) -> bool:
    return bool(
        _to_float(row.get("exit_quality_score"), 0.0) > 0
        or _safe_text(row.get("exit_quality_band"))
        or _safe_text(row.get("exit_reason"))
        or _has_any(row, ("early_exit", "late_exit", "missed_profit", "exit", "winner", "loser"))
    )


class ObservationLearningThroughputSuiteV1:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")

    def _load_sources(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "lifecycle": _tail_jsonl(self.lifecycle_path),
            "labels": _tail_jsonl(self.labels_path),
            "decision_ledger": _tail_jsonl(self.ledger_path, max_rows=1_000, max_bytes=2_000_000),
        }

    def _duration_hours(self, row: dict[str, Any]) -> float | None:
        entry = _parse_dt(row.get("entry_timestamp") or row.get("entry_timestamp_utc") or row.get("opened_at"))
        exit_dt = _parse_dt(row.get("exit_timestamp") or row.get("exit_timestamp_utc") or row.get("closed_at"))
        if entry is None or exit_dt is None or exit_dt < entry:
            return None
        return (exit_dt - entry).total_seconds() / 3600.0

    def status(self) -> dict[str, Any]:
        try:
            return self._status()
        except Exception as exc:
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "shadow_only",
                "local_only": True,
                "writes_files": False,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "observation_learning_throughput_status_v1": True,
                "trades_opened_today": 0,
                "trades_closed_today": 0,
                "labels_created_today": 0,
                "observation_completion_score": 0.0,
                "learning_throughput_score": 0.0,
                "observation_intelligence_score": 0.0,
                "average_time_to_close_hours": None,
                "completed_trade_coverage_pct": 0.0,
                "primary_learning_bottleneck": "suite_error",
                "throughput_recommendation_summary": f"Observation suite unavailable: {str(exc)[:140]}",
            }

    def _status(self) -> dict[str, Any]:
        sources = self._load_sources()
        today = _now().date().isoformat()
        lifecycle = sources["lifecycle"]
        labels = sources["labels"]
        ledger = sources["decision_ledger"]

        lifecycle_today = [r for r in lifecycle if _is_today(r, today)]
        labels_today = [r for r in labels if _is_today(r, today)]
        ledger_today = [r for r in ledger if _is_today(r, today)]

        opened_rows = [
            r
            for r in lifecycle_today
            if _safe_text(r.get("entry_timestamp") or r.get("entry_timestamp_utc"))
            or _has_any(r, ("opened", "entry", "monitoring", "paper"))
        ]
        closed_rows = [
            r
            for r in lifecycle_today
            if _safe_text(r.get("exit_timestamp") or r.get("exit_timestamp_utc") or r.get("closed_at"))
            or _has_any(r, ("closed", "exit", "take_profit", "stop"))
        ]

        label_rows = [r for r in labels_today if _safe_text(r.get("outcome_label"))]
        entries_classified = sum(1 for r in labels_today if _label_has_entry(r))
        exits_classified = sum(1 for r in labels_today if _label_has_exit(r))
        contextual_updates = sum(
            1
            for r in labels_today + ledger_today
            if any(_safe_text(r.get(k)) for k in ("regime", "regime_context", "setup_type", "sector", "cap_bucket"))
        )
        portfolio_updates = sum(
            1
            for r in labels_today + ledger_today
            if any(_safe_text(r.get(k)) for k in ("risk_tier", "risk_class", "sizing_tier"))
            or _to_float(r.get("allocation_percent"), 0.0) > 0
        )

        durations = [d for row in closed_rows for d in [self._duration_hours(row)] if d is not None]
        avg_close = (sum(durations) / len(durations)) if durations else None
        med_close = median(durations) if durations else None

        trades_opened_today = len({(_safe_text(r.get("lifecycle_id")) or _safe_text(r.get("symbol")) or str(i)) for i, r in enumerate(opened_rows)})
        trades_closed_today = len({(_safe_text(r.get("lifecycle_id")) or _safe_text(r.get("symbol")) or str(i)) for i, r in enumerate(closed_rows)})
        labels_created_today = len(label_rows)

        label_coverage = _clamp((labels_created_today / max(1, trades_closed_today)) * 100.0) if trades_closed_today else 0.0
        entry_coverage = _clamp((entries_classified / max(1, labels_created_today)) * 100.0) if labels_created_today else 0.0
        exit_coverage = _clamp((exits_classified / max(1, labels_created_today)) * 100.0) if labels_created_today else 0.0
        context_coverage = _clamp((contextual_updates / max(1, labels_created_today)) * 100.0) if labels_created_today else 0.0
        portfolio_coverage = _clamp((portfolio_updates / max(1, labels_created_today)) * 100.0) if labels_created_today else 0.0

        observation_completion_score = _clamp(
            (label_coverage * 0.35)
            + (entry_coverage * 0.20)
            + (exit_coverage * 0.20)
            + (context_coverage * 0.15)
            + (portfolio_coverage * 0.10)
        )
        learning_throughput_score = _clamp(
            min(labels_created_today, 30) / 30.0 * 40.0
            + min(trades_closed_today, 10) / 10.0 * 25.0
            + min(contextual_updates, 30) / 30.0 * 20.0
            + min(portfolio_updates, 20) / 20.0 * 15.0
        )
        observation_intelligence_score = _clamp((observation_completion_score * 0.58) + (learning_throughput_score * 0.42))

        if trades_closed_today <= 0:
            bottleneck = "insufficient_closed_trades"
            severity = "high" if trades_opened_today <= 0 else "medium"
        elif label_coverage < 75.0:
            bottleneck = "labeling_pipeline_gap"
            severity = "high"
        elif context_coverage < 50.0:
            bottleneck = "limited_contextual_evidence"
            severity = "medium"
        elif portfolio_coverage < 35.0:
            bottleneck = "limited_portfolio_risk_learning"
            severity = "medium"
        else:
            bottleneck = "healthy"
            severity = "low"

        suggested_max_concurrent = 6 if observation_intelligence_score >= 65 else 4
        if bottleneck == "insufficient_closed_trades" and trades_opened_today < 4:
            suggested_new_per_cycle = 2
            cooldown = 180
        elif bottleneck == "labeling_pipeline_gap":
            suggested_new_per_cycle = 1
            cooldown = 360
        else:
            suggested_new_per_cycle = 1
            cooldown = 240

        recommendation = {
            "insufficient_closed_trades": "Allow normal paper exits to complete; add only modest new paper candidates when portfolio heat is safe.",
            "labeling_pipeline_gap": "Prioritize label completion for closed paper trades before increasing paper throughput.",
            "limited_contextual_evidence": "Keep trade flow natural and enrich completed labels with regime, setup, and context fields.",
            "limited_portfolio_risk_learning": "Attach portfolio heat and sizing context to completed paper observations.",
            "healthy": "Observation pipeline is healthy; keep current paper cadence and monitor coverage.",
        }.get(bottleneck, "Monitor observation coverage using shadow-only diagnostics.")

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
            "observation_learning_throughput_status_v1": True,
            "generated_at": _now_iso(),
            "source_files": [self.lifecycle_path, self.labels_path, self.ledger_path],
            "max_rows_per_file": MAX_ROWS_PER_FILE,
            "max_tail_bytes": MAX_TAIL_BYTES,
            "trades_opened_today": trades_opened_today,
            "trades_closed_today": trades_closed_today,
            "labels_created_today": labels_created_today,
            "entries_classified_today": int(entries_classified),
            "exits_classified_today": int(exits_classified),
            "contextual_updates_today": int(contextual_updates),
            "portfolio_updates_today": int(portfolio_updates),
            "observation_completion_score": round(observation_completion_score, 3),
            "observation_completion_label": self._label_score(observation_completion_score),
            "learning_throughput_score": round(learning_throughput_score, 3),
            "learning_throughput_label": self._label_score(learning_throughput_score),
            "average_time_to_close_hours": round(avg_close, 3) if avg_close is not None else None,
            "median_time_to_close_hours": round(med_close, 3) if med_close is not None else None,
            "average_labels_per_trade": round(labels_created_today / max(1, trades_closed_today), 3),
            "completed_trade_coverage_pct": round(label_coverage, 3),
            "primary_learning_bottleneck": bottleneck,
            "bottleneck_severity": severity,
            "throughput_recommendation_summary": recommendation,
            "observation_intelligence_score": round(observation_intelligence_score, 3),
            "observation_intelligence_label": self._label_score(observation_intelligence_score),
            "observation_reasons": self._reasons(
                trades_opened_today,
                trades_closed_today,
                labels_created_today,
                label_coverage,
                context_coverage,
                portfolio_coverage,
            ),
            "observation_penalties": self._penalties(bottleneck, label_coverage, context_coverage, portfolio_coverage),
            "observation_summary": (
                f"{labels_created_today} labels from {trades_closed_today} closed paper observations today; "
                f"completion {label_coverage:.1f}%, bottleneck={bottleneck}."
            ),
            "suggested_max_new_paper_trades_per_cycle": int(suggested_new_per_cycle),
            "suggested_max_concurrent_paper_positions": int(suggested_max_concurrent),
            "suggested_paper_trade_cooldown_seconds": int(cooldown),
            "next_recommended_action": "use_shadow_throughput_guidance_without_forcing_exits_or_changing_live_trading",
        }

    def _label_score(self, score: float) -> str:
        if score >= 80:
            return "strong"
        if score >= 60:
            return "healthy"
        if score >= 35:
            return "watch"
        return "needs_attention"

    def _reasons(
        self,
        opened: int,
        closed: int,
        labels: int,
        label_coverage: float,
        context_coverage: float,
        portfolio_coverage: float,
    ) -> list[str]:
        reasons: list[str] = []
        if opened > 0:
            reasons.append("paper_lifecycle_activity_detected")
        if closed > 0:
            reasons.append("completed_observations_available")
        if labels > 0:
            reasons.append("outcome_labels_created_today")
        if label_coverage >= 80:
            reasons.append("closed_trade_label_coverage_strong")
        if context_coverage >= 50:
            reasons.append("contextual_learning_fields_present")
        if portfolio_coverage >= 35:
            reasons.append("portfolio_risk_learning_fields_present")
        return reasons[:8] or ["waiting_for_fresh_paper_observations"]

    def _penalties(self, bottleneck: str, label_coverage: float, context_coverage: float, portfolio_coverage: float) -> list[str]:
        penalties: list[str] = []
        if bottleneck != "healthy":
            penalties.append(bottleneck)
        if label_coverage < 75:
            penalties.append("closed_trade_label_coverage_below_target")
        if context_coverage < 50:
            penalties.append("contextual_learning_coverage_limited")
        if portfolio_coverage < 35:
            penalties.append("portfolio_risk_learning_coverage_limited")
        return list(dict.fromkeys(penalties))[:8]
