"""Entry Quality V2 scoring helpers (shadow-only, local row fields only)."""

from __future__ import annotations

import time
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _band(score: float) -> str:
    if score >= 90:
        return "elite"
    if score >= 80:
        return "strong"
    if score >= 70:
        return "acceptable"
    if score >= 60:
        return "weak"
    return "reject"


def _promotion_for_band(band: str, confidence: float) -> str:
    if band == "elite" and confidence >= 80:
        return "live-ready candidate"
    if band == "strong":
        return "paper-ready or live-ready candidate" if confidence >= 82 else "paper-ready"
    if band == "acceptable":
        return "paper-ready"
    if band == "weak":
        return "monitor-only"
    return "blocked"


def score_entry_quality_v2(row: dict[str, Any] | None) -> dict[str, Any]:
    """Score a candidate conservatively without altering any live decision."""
    r = dict(row or {})
    base_entry = _to_float(r.get("entry_quality_score"), _to_float(r.get("entry_filter_v2_score"), 50.0))
    signal = _to_float(r.get("signal_quality_score"), _to_float(r.get("confidence"), 50.0))
    confirmation = _to_float(
        r.get("confirmation_strength_score"),
        _to_float(r.get("agreement_score"), _to_float(r.get("provider_blend_score"), 50.0)),
    )
    volume = _to_float(r.get("volume_score"), _to_float(r.get("volume_confirmation_score"), 50.0))
    freshness = _to_float(r.get("quote_freshness_score"), _to_float(r.get("data_quality_score"), 50.0))
    chase_risk = _to_float(r.get("entry_precision_v2_chase_risk"), _to_float(r.get("extension_risk_score"), 35.0))
    volatility_risk = _to_float(r.get("volatility_risk"), 100.0 - _to_float(r.get("volatility_score"), 55.0))
    disagreement = _to_float(r.get("persona_disagreement_index"), _to_float(r.get("brain_disagreement_score"), 25.0))

    penalties: list[str] = []
    reasons: list[str] = []
    score = (
        base_entry * 0.30
        + signal * 0.18
        + confirmation * 0.18
        + volume * 0.10
        + freshness * 0.10
        + max(0.0, 100.0 - volatility_risk) * 0.07
        + max(0.0, 100.0 - chase_risk) * 0.07
    )
    if chase_risk >= 70:
        score -= 7
        penalties.append("overextension_chase_risk")
    if disagreement >= 55:
        score -= 5
        penalties.append("high_signal_disagreement")
    if freshness < 45:
        score -= 6
        penalties.append("weak_quote_or_data_freshness")
    if confirmation >= 70:
        reasons.append("confirmation_supportive")
    if volume >= 65:
        reasons.append("volume_supportive")
    if base_entry >= 75:
        reasons.append("entry_quality_supportive")
    score = max(0.0, min(100.0, score))
    band = _band(score)
    confidence = max(0.0, min(100.0, (confirmation * 0.35) + (freshness * 0.25) + ((100.0 - disagreement) * 0.25) + (signal * 0.15)))
    promotion = _promotion_for_band(band, confidence)
    if str(r.get("canonical_final_state") or "").lower() in {"blocked", "reject"} and promotion in {
        "live-ready candidate",
        "paper-ready or live-ready candidate",
    }:
        promotion = "paper-ready"
    return {
        "entry_quality_score_v2": round(score, 3),
        "entry_quality_band_v2": band,
        "entry_quality_reason_codes_v2": reasons or ["mixed_or_insufficient_confirmation"],
        "entry_quality_summary_v2": f"{band} entry quality; {promotion}",
        "entry_quality_confidence_v2": round(confidence, 3),
        "promotion_recommendation_v2": promotion,
        "entry_quality_penalties_v2": penalties,
    }


class EntryQualityV2Engine:
    def __init__(self) -> None:
        self.created_at = time.time()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "mode": "shadow_scoring",
            "local_only": True,
            "api_calls_used": 0,
            "bands": {"elite": "90-100", "strong": "80-89", "acceptable": "70-79", "weak": "60-69", "reject": "<60"},
            "live_decision_changes": False,
        }

    def score_rows(self, rows: list[dict[str, Any]] | None, limit: int = 200) -> dict[str, Any]:
        scored = []
        dist: dict[str, int] = {}
        for row in list(rows or [])[: max(1, int(limit))]:
            if not isinstance(row, dict):
                continue
            result = score_entry_quality_v2(row)
            band = result["entry_quality_band_v2"]
            dist[band] = int(dist.get(band, 0)) + 1
            scored.append({**{"symbol": row.get("symbol")}, **result})
        avg = sum(_to_float(r.get("entry_quality_score_v2"), 0.0) for r in scored) / max(1, len(scored))
        return {"rows_scored": len(scored), "avg_entry_quality_score_v2": round(avg, 3), "band_distribution": dist, "sample": scored[:20]}
