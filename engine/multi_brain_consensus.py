"""Multi-Brain Consensus V1 (cache/local row fields only, shadow mode)."""

from __future__ import annotations

import time
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def score_multi_brain(row: dict[str, Any] | None) -> dict[str, Any]:
    r = dict(row or {})
    brains = {
        "momentum": _to_float(r.get("momentum_score"), _to_float(r.get("trend_score"), 50.0)),
        "technical": _to_float(r.get("technical_score"), _to_float(r.get("entry_quality_score"), 50.0)),
        "volume": _to_float(r.get("volume_score"), _to_float(r.get("volume_confirmation_score"), 50.0)),
        "risk": max(0.0, 100.0 - _to_float(r.get("risk_score"), _to_float(r.get("stale_data_risk_score"), 35.0))),
        "catalyst_fundamental": _to_float(r.get("fundamental_score"), _to_float(r.get("fmp_enrichment_score"), 50.0)),
        "regime": _to_float(r.get("regime_score"), _to_float(r.get("regime_compatibility_score"), 50.0)),
        "entry_quality": _to_float(r.get("entry_quality_score_v2"), _to_float(r.get("entry_quality_score"), 50.0)),
        "follow_through": _to_float(r.get("follow_through_quality_score"), _to_float(r.get("profit_quality_score"), 50.0)),
    }
    vals = list(brains.values())
    avg = sum(vals) / max(1, len(vals))
    spread = max(vals) - min(vals) if vals else 0.0
    agreement = max(0.0, min(100.0, 100.0 - spread))
    confidence = max(0.0, min(100.0, (avg * 0.65) + (agreement * 0.35)))
    if avg >= 82 and agreement >= 68:
        band = "strong_consensus"
        recommendation = "allow_with_confirmation"
    elif avg >= 70 and agreement >= 55:
        band = "constructive_consensus"
        recommendation = "paper_ready"
    elif avg >= 58:
        band = "mixed_consensus"
        recommendation = "monitor_only"
    else:
        band = "weak_consensus"
        recommendation = "block_or_monitor"
    if agreement < 45:
        recommendation = "require_confirmation"
    return {
        "multi_brain_score": round(avg, 3),
        "multi_brain_confidence": round(confidence, 3),
        "brain_agreement_score": round(agreement, 3),
        "brain_disagreement_score": round(100.0 - agreement, 3),
        "brain_scores": {k: round(v, 3) for k, v in brains.items()},
        "consensus_band": band,
        "consensus_recommendation": recommendation,
        "consensus_reason_summary": f"{band}; agreement={agreement:.1f}; recommendation={recommendation}",
    }


class MultiBrainConsensusEngine:
    def __init__(self) -> None:
        self.created_at = time.time()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "mode": "shadow_consensus",
            "local_only": True,
            "api_calls_used": 0,
            "brains": [
                "Momentum Brain",
                "Technical Brain",
                "Volume Brain",
                "Risk Brain",
                "Catalyst/Fundamental Brain",
                "Regime Brain",
                "Entry Quality Brain",
                "Follow-Through Brain",
            ],
            "live_decision_changes": False,
        }

    def score_rows(self, rows: list[dict[str, Any]] | None, limit: int = 200) -> dict[str, Any]:
        scored = []
        dist: dict[str, int] = {}
        for row in list(rows or [])[: max(1, int(limit))]:
            if not isinstance(row, dict):
                continue
            result = score_multi_brain(row)
            band = result["consensus_band"]
            dist[band] = int(dist.get(band, 0)) + 1
            scored.append({**{"symbol": row.get("symbol")}, **result})
        avg = sum(_to_float(r.get("multi_brain_score"), 0.0) for r in scored) / max(1, len(scored))
        return {"rows_scored": len(scored), "avg_multi_brain_score": round(avg, 3), "band_distribution": dist, "sample": scored[:20]}
