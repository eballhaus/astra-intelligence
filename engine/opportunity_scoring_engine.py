"""Profit-Maximizing Opportunity Scoring Engine V1."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if n == n else float(default)
    except Exception:
        return float(default)


def _grade_score(row: dict[str, Any]) -> float:
    explicit = _f(row.get("grade_percent"), -1.0)
    if explicit >= 0:
        return max(0.0, min(100.0, explicit))
    grade = str(row.get("grade") or row.get("buy_grade") or "").upper()[:1]
    return {"A": 92.0, "B": 78.0, "C": 62.0, "D": 42.0, "F": 18.0}.get(grade, 50.0)


def _label(score: float) -> str:
    if score >= 85:
        return "Elite"
    if score >= 75:
        return "Strong"
    if score >= 60:
        return "Good"
    if score >= 45:
        return "Watch"
    return "Weak"


def _grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 82:
        return "A"
    if score >= 74:
        return "B+"
    if score >= 66:
        return "B"
    if score >= 55:
        return "C"
    return "Watch"


class OpportunityScoringEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "profit_maximizing_shadow_display_score"

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        src = dict(row or {})
        expected_pct = _f(src.get("expected_return_pct"), _f(src.get("expected_move_percent"), 0.0))
        expected_component = max(0.0, min(100.0, expected_pct * 4.0))
        conv10 = _f(src.get("conviction_10r"), _f(src.get("rolling_conviction_10r"), _f(src.get("conviction_display_score"), 50.0)))
        entry = _f(src.get("entry_quality_v3_score"), _f(src.get("entry_quality_v2_score"), _f(src.get("entry_quality_score"), 50.0)))
        confidence = _f(src.get("confidence"), _f(src.get("buy_confidence"), 50.0))
        grade_or_astra = max(_grade_score(src), _f(src.get("astra_composite_score"), _f(src.get("stable_composite_score"), 50.0)))
        persistence = _f(src.get("persistence_score"), _f(src.get("rank_stability_score"), 50.0))
        consensus = _f(src.get("multi_brain_agreement"), _f(src.get("multi_brain_score"), 50.0))
        psychology = _f(src.get("psychology_score"), 60.0)
        risk_penalty = max(0.0, _f(src.get("psychology_chase_risk"), 0.0) - 65.0) * 0.12
        score = (
            expected_component * 0.25
            + conv10 * 0.20
            + entry * 0.15
            + confidence * 0.10
            + grade_or_astra * 0.10
            + persistence * 0.10
            + consensus * 0.05
            + psychology * 0.05
            - risk_penalty
        )
        score = max(0.0, min(100.0, score))
        return {
            "opportunity_grade": _grade(score),
            "opportunity_score_pct": round(score, 3),
            "opportunity_score_label": _label(score),
            "profit_priority_score": round(score, 3),
            "opportunity_formula": "expected_return_25 + 10r_20 + entry_v3_15 + confidence_10 + grade_astra_10 + persistence_10 + consensus_5 + psychology_5",
            "api_calls_used": 0,
        }

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scored = [self.score_row(r) for r in list(rows or []) if isinstance(r, dict)]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "opportunity_scoring_status_v1": True,
            "candidates_evaluated": len(scored),
            "average_opportunity_score_pct": round(sum(float(r.get("opportunity_score_pct") or 0) for r in scored) / max(1, len(scored)), 3),
            "top_opportunity_grade": max((str(r.get("opportunity_grade") or "") for r in scored), default=""),
            "generated_at": _now_iso(),
            "next_recommended_action": "rank_display_candidates_by_profit_priority_without_live_execution_changes",
        }
