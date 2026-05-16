from __future__ import annotations

import json
import os
import statistics
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


class WalkForwardValidationEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.learning_path = os.path.join(self.state_dir, "learning_insights_last_good.json")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _rows(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.lifecycle_path):
            return []
        rows = []
        try:
            with open(self.lifecycle_path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        rows.append(obj)
        except Exception:
            return []
        return rows[-5000:]

    def status(self) -> dict[str, Any]:
        snap = self._read_json(self.learning_path)
        rows = self._rows()
        returns = [_to_float(r.get("pnl_pct"), _to_float(r.get("return_pct"), 0.0)) for r in rows if r.get("pnl_pct") is not None or r.get("return_pct") is not None]
        windows = []
        window_size = max(10, min(50, int(len(returns) / 3) or 10))
        for idx in range(0, len(returns), window_size):
            test = returns[idx:idx + window_size]
            if not test:
                continue
            wins = len([x for x in test if x > 0])
            windows.append({"window": len(windows) + 1, "sample_count": len(test), "win_rate": round((wins / max(1, len(test))) * 100.0, 3), "avg_return": round(sum(test) / max(1, len(test)), 6)})
        released_wr = _to_float(snap.get("current_engine_released_wr"), _to_float(snap.get("released_hero_win_rate"), 0.0))
        entry_quality = _to_float(snap.get("entry_quality"), _to_float(snap.get("entry_quality_score"), 0.0))
        buy_purity = _to_float(snap.get("buy_list_purity"), 0.0)
        exit_quality = min(100.0, max(0.0, statistics.fmean([w["win_rate"] for w in windows]) if windows else released_wr))
        truth = _to_float(snap.get("confidence_truthfulness"), (released_wr + buy_purity) / 2.0)
        stability = 100.0 - min(100.0, statistics.pstdev([w["win_rate"] for w in windows]) if len(windows) > 1 else 50.0)
        score = max(0.0, min(100.0, (released_wr + entry_quality + buy_purity + exit_quality + truth + stability) / 6.0))
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_walk_forward_validation_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "walk_forward_validation_status_v1": True,
            "rolling_windows": windows[:12],
            "metrics_evaluated": ["released_wr", "buy_list_purity", "entry_quality", "exit_quality", "confidence_truthfulness"],
            "walk_forward_score": round(score, 3),
            "overfit_risk": "elevated_until_more_windows" if len(windows) < 3 else "moderate" if stability < 65 else "low",
            "stability_score": round(stability, 3),
            "validation_confidence": round(min(95.0, 25.0 + len(windows) * 12.0), 3),
            "confidence_score": round(min(95.0, 25.0 + len(windows) * 12.0), 3),
            "next_recommended_action": "keep_validation_shadow_only_and_accumulate_more_rolling_windows",
        }
