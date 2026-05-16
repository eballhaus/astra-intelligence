"""Contextual Learning Memory V1."""
from __future__ import annotations

import json
import os
from collections import defaultdict
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


class ContextualLearningMemory:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.candidate_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")

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

    def _bucket(self, row: dict[str, Any]) -> tuple[str, str, str, str, str]:
        setup = str(row.get("trade_archetype") or row.get("setup") or "unknown_setup").lower()[:40]
        persona = str(row.get("persona") or row.get("brain") or "unknown_persona").lower()[:40]
        sector = str(row.get("sector") or row.get("sector_name") or "unknown_sector").lower()[:40]
        cap = str(row.get("market_cap_group") or row.get("cap_group") or "unknown_cap").lower()[:40]
        regime = str(row.get("market_regime") or row.get("regime") or "unknown_regime").lower()[:40]
        return setup, persona, sector, cap, regime

    def status(self) -> dict[str, Any]:
        rows = self._tail_jsonl(self.lifecycle_path) + self._tail_jsonl(self.candidate_path)
        memory: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(list)
        for row in rows:
            ret = row.get("pnl_pct") if row.get("pnl_pct") is not None else row.get("return_pct")
            if ret is None:
                continue
            memory[self._bucket(row)].append(_to_float(ret, 0.0))
        combos = []
        for key, vals in memory.items():
            wins = len([v for v in vals if v > 0])
            combos.append({
                "setup": key[0],
                "persona": key[1],
                "sector": key[2],
                "market_cap_group": key[3],
                "regime": key[4],
                "sample_count": len(vals),
                "win_rate": round((wins / max(1, len(vals))) * 100.0, 3),
                "avg_return": round(sum(vals) / max(1, len(vals)), 6),
            })
        combos.sort(key=lambda r: (r["sample_count"], r["win_rate"], r["avg_return"]), reverse=True)
        dimensions = 5
        populated = len([c for c in combos if c["sample_count"] > 0])
        coverage = min(100.0, populated / max(1, dimensions * 20) * 100.0)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "local_contextual_learning_memory_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "contextual_learning_memory_status_v1": True,
            "rows_examined": len(rows),
            "context_dimensions": ["setups", "personas", "sectors", "market_cap_groups", "regimes"],
            "context_combinations_available": len(combos),
            "contextual_learning_coverage_pct": round(coverage, 3),
            "best_context_combinations": combos[:20],
            "confidence_score": round(min(95.0, 30.0 + coverage * 0.65), 3),
            "next_recommended_action": "use_context_memory_for_explanations_and_shadow_reviews_before_strategy_changes",
            "changes_live_trading": False,
        }
