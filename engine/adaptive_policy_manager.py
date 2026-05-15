"""Adaptive Policy Manager V1.

Shadow-mode policy analysis only. This module does not mutate thresholds, write
files, place trades, or call providers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


class AdaptivePolicyManager:
    """Produces recommendation-only policy guidance from existing Astra metrics."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.threshold_guardrails = {
            "max_shadow_adjustment_pct_points": 5.0,
            "minimum_samples_before_activation": 50,
            "activation_requires_manual_review": True,
        }

    def _metric_summary(self, learning_snapshot: dict[str, Any] | None = None, provider_status: dict[str, Any] | None = None) -> dict[str, Any]:
        snap = learning_snapshot if isinstance(learning_snapshot, dict) else {}
        provider = provider_status if isinstance(provider_status, dict) else {}
        released_wr = _clamp(_to_float(snap.get("current_engine_released_wr"), snap.get("released_hero_win_rate") or 0.0))
        entry_quality = _clamp(_to_float(snap.get("entry_quality"), snap.get("entry_quality_score") or 0.0))
        buy_list_purity = _clamp(_to_float(snap.get("buy_list_purity"), snap.get("buy_list_purity_score") or 0.0))
        follow_through = _clamp(_to_float(snap.get("follow_through_quality"), snap.get("follow_through_quality_score") or 0.0))
        confidence_truthfulness = _clamp(_to_float(snap.get("confidence_truthfulness"), (released_wr + buy_list_purity) / 2.0))
        runtime_stability = _clamp(_to_float(snap.get("runtime_learning_stability"), 0.0))
        provider_reliability = _clamp(_to_float(provider.get("provider_reliability_score"), runtime_stability or 75.0))
        regime_performance = _clamp(_to_float(snap.get("regime_performance"), released_wr or 0.0))
        return {
            "released_win_rate": round(released_wr, 3),
            "buy_list_purity": round(buy_list_purity, 3),
            "entry_quality": round(entry_quality, 3),
            "confidence_truthfulness": round(confidence_truthfulness, 3),
            "follow_through_quality": round(follow_through, 3),
            "provider_reliability": round(provider_reliability, 3),
            "regime_performance": round(regime_performance, 3),
            "runtime_stability": round(runtime_stability, 3),
        }

    def recommendations(self, learning_snapshot: dict[str, Any] | None = None, provider_status: dict[str, Any] | None = None) -> dict[str, Any]:
        metrics = self._metric_summary(learning_snapshot, provider_status)
        recs: list[dict[str, Any]] = []
        if metrics["entry_quality"] < 60.0:
            recs.append({
                "policy_area": "entry_quality_threshold",
                "recommendation": "raise_minimum_entry_quality_in_shadow_tests",
                "suggested_adjustment_pct_points": 3.0,
                "reason": "Entry quality is below the preferred institutional band.",
            })
        if metrics["buy_list_purity"] < 60.0:
            recs.append({
                "policy_area": "buy_list_purity_gate",
                "recommendation": "tighten_candidate_release_gate_in_shadow_tests",
                "suggested_adjustment_pct_points": 2.5,
                "reason": "Buy list purity is the clearest pressure point.",
            })
        if metrics["confidence_truthfulness"] < 60.0:
            recs.append({
                "policy_area": "confidence_calibration",
                "recommendation": "discount_overconfident_scores_in_shadow_tests",
                "suggested_adjustment_pct_points": -2.0,
                "reason": "Confidence truthfulness trails desired reliability.",
            })
        if metrics["follow_through_quality"] >= 70.0 and metrics["released_win_rate"] >= 65.0:
            recs.append({
                "policy_area": "release_confidence",
                "recommendation": "maintain_current_thresholds_in_shadow_mode",
                "suggested_adjustment_pct_points": 0.0,
                "reason": "Released win rate and follow-through are aligned.",
            })
        if not recs:
            recs.append({
                "policy_area": "global_policy",
                "recommendation": "hold_current_policy_and_collect_more_evidence",
                "suggested_adjustment_pct_points": 0.0,
                "reason": "No metric has enough pressure to justify even a shadow adjustment.",
            })
        confidence_score = _clamp(sum(metrics.values()) / max(1, len(metrics)))
        activation_ready = bool(confidence_score >= 80.0 and metrics["runtime_stability"] >= 80.0)
        return {
            "enabled": True,
            "version": VERSION,
            "adaptive_policy_recommendations_v1": True,
            "mode": "shadow_only",
            "shadow_mode": True,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "analyzed_metrics": metrics,
            "recommended_threshold_adjustments": recs,
            "confidence_score": round(confidence_score, 3),
            "activation_readiness": {
                "ready": False,
                "shadow_score_ready": activation_ready,
                "manual_approval_required": True,
                "reason": "Adaptive policy is recommendation-only; live activation is intentionally disabled.",
            },
            "next_recommended_action": "review_shadow_recommendations_without_changing_live_thresholds",
        }

    def status(self, learning_snapshot: dict[str, Any] | None = None, provider_status: dict[str, Any] | None = None) -> dict[str, Any]:
        rec = self.recommendations(learning_snapshot=learning_snapshot, provider_status=provider_status)
        return {
            "enabled": True,
            "version": VERSION,
            "adaptive_policy_status_v1": True,
            "mode": "shadow_only",
            "shadow_mode": True,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "generated_at": rec.get("generated_at"),
            "analyzed_metric_names": list((rec.get("analyzed_metrics") or {}).keys()),
            "recommendation_count": len(rec.get("recommended_threshold_adjustments") or []),
            "confidence_score": rec.get("confidence_score", 0.0),
            "activation_readiness": rec.get("activation_readiness"),
            "threshold_guardrails": dict(self.threshold_guardrails),
            "next_recommended_action": rec.get("next_recommended_action"),
        }
