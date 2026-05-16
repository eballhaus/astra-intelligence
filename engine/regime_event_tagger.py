"""Regime & Event Tagging Engine V1."""
from __future__ import annotations

import json
import os
from collections import Counter
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


class RegimeEventTagger:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.candidate_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.learning_path = os.path.join(self.state_dir, "learning_insights_last_good.json")

    def _tail_jsonl(self, path: str, limit: int = 5000) -> list[dict[str, Any]]:
        if not os.path.exists(path):
            return []
        rows: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        rows.append(obj)
        except Exception:
            return []
        return rows[-max(1, int(limit)):]

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _tag_row(self, row: dict[str, Any], learning: dict[str, Any]) -> dict[str, str]:
        text = " ".join(str(row.get(k) or "").lower() for k in ("catalyst_context", "exit_reason", "outcome_label", "trade_archetype", "persona"))
        event_type = "earnings" if "earning" in text else "catalyst" if "catalyst" in text or "news" in text else "technical"
        seasonality = "q4" if any(str(row.get(k) or "").startswith(("2024-10", "2024-11", "2024-12", "2025-10", "2025-11", "2025-12", "2026-10", "2026-11", "2026-12")) for k in ("timestamp_utc", "created_at", "signal_timestamp", "entry_timestamp")) else "standard"
        released_wr = _to_float(learning.get("current_engine_released_wr"), _to_float(learning.get("released_hero_win_rate"), 0.0))
        regime = "constructive" if released_wr >= 60 else "mixed_or_defensive"
        return {
            "market_regime": str(row.get("market_regime") or row.get("regime") or regime),
            "seasonality": seasonality,
            "earnings_period": "earnings_related" if event_type == "earnings" else "non_earnings_or_unknown",
            "macro_state": str(row.get("macro_state") or row.get("risk_state") or "unknown_from_local_cache"),
            "catalyst_context": str(row.get("catalyst_context") or "none_recorded"),
            "event_type": event_type,
        }

    def status(self) -> dict[str, Any]:
        rows = self._tail_jsonl(self.lifecycle_path) + self._tail_jsonl(self.candidate_path)
        learning = self._read_json(self.learning_path)
        tag_counters: dict[str, Counter[str]] = {k: Counter() for k in ["market_regime", "seasonality", "earnings_period", "macro_state", "catalyst_context", "event_type"]}
        samples = []
        for row in rows[-1000:]:
            tags = self._tag_row(row, learning)
            for key, value in tags.items():
                tag_counters[key][str(value)[:80]] += 1
            if len(samples) < 20:
                samples.append({"symbol": str(row.get("symbol") or "").upper(), "tags": tags})
        tagged = len(rows[-1000:])
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "local_regime_event_tagging_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "regime_event_tagging_status_v1": True,
            "rows_examined": len(rows),
            "rows_tagged_preview": tagged,
            "tag_dimensions": list(tag_counters.keys()),
            "tag_counts": {k: dict(v.most_common(12)) for k, v in tag_counters.items()},
            "sample_tags": samples,
            "confidence_score": round(min(95.0, 35.0 + tagged / 20.0), 3),
            "next_recommended_action": "persist_tags_only_after_reviewing_local_preview_quality",
            "changes_live_trading": False,
        }
