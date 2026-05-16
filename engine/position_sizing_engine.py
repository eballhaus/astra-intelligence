from __future__ import annotations

import json
import os
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


class PositionSizingRiskEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.snapshot_path = os.path.join(self.state_dir, "runtime_top_buys_snapshot.json")

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _top_rows(self) -> list[dict[str, Any]]:
        data = self._read_json(self.snapshot_path)
        stocks = data.get("stocks") if isinstance(data.get("stocks"), dict) else {}
        rows = stocks.get("final") or data.get("final") or []
        return [r for r in rows if isinstance(r, dict)][:6]

    def status(self) -> dict[str, Any]:
        rows = self._top_rows()
        recs = []
        for row in rows:
            confidence = _to_float(row.get("confidence"), _to_float(row.get("score"), _to_float(row.get("grade"), 50.0)))
            setup = _to_float(row.get("entry_quality_score"), _to_float(row.get("entry_quality"), confidence))
            volatility = _to_float(row.get("volatility_score"), 50.0)
            quality = max(0.0, min(100.0, confidence * 0.45 + setup * 0.35 + (100.0 - min(100.0, volatility)) * 0.20))
            max_size = 0.08 if quality >= 80 else 0.05 if quality >= 65 else 0.025
            suggested = max_size * min(1.0, quality / 100.0)
            recs.append({
                "symbol": str(row.get("symbol") or row.get("ticker") or "").upper(),
                "confidence": round(confidence, 3),
                "setup_quality": round(setup, 3),
                "risk_class": "institutional_quality" if quality >= 80 else "standard" if quality >= 65 else "small_or_paper_only",
                "max_position_size_pct": round(max_size * 100.0, 3),
                "suggested_allocation_pct": round(suggested * 100.0, 3),
                "paper_to_live_tier": "eligible_after_manual_review" if quality >= 80 else "paper_or_reduced_size",
                "correlation_policy": "cap_same_sector_exposure_before_live_use",
            })
        confidence_score = min(90.0, 40.0 + len(recs) * 6.0)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_position_sizing_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "position_sizing_status_v1": True,
            "no_order_placement": True,
            "changes_live_trading": False,
            "portfolio_concentration_policy": "limit_single_name_and_sector_concentration_before_manual_live_use",
            "recommendations": recs,
            "confidence_score": round(confidence_score, 3),
            "next_recommended_action": "review_position_size_recommendations_manually_before_any_live_use",
        }
