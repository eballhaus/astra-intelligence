from __future__ import annotations

import json
import os
import statistics
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"

BASELINE_WEIGHTS: dict[str, float] = {
    "expected_return_pct": 25.0,
    "conviction_10r": 20.0,
    "entry_quality_v3": 15.0,
    "confidence": 10.0,
    "grade_astra_score": 10.0,
    "rank_persistence": 10.0,
    "multi_brain_consensus": 5.0,
    "psychology_brain": 5.0,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_jsonl(path: str, limit: int = 5000) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows: list[dict[str, Any]] = []
    try:
        max_bytes = 1_250_000
        with open(path, "rb") as fh:
            try:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - max_bytes), os.SEEK_SET)
            except Exception:
                fh.seek(0)
            raw_text = fh.read(max_bytes).decode("utf-8", errors="ignore")
        lines = raw_text.splitlines()
        if len(lines) > 1 and not raw_text.startswith("{"):
            lines = lines[1:]
        for raw in lines[-limit:]:
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return []
    return rows[-limit:]


def _stable_rows(state_dir: str) -> list[dict[str, Any]]:
    snap = _read_json(os.path.join(state_dir, "snapshots", "stable_top_buys_v1.json"))
    rows = snap.get("stable_top_6") or ((snap.get("stocks") or {}).get("final") if isinstance(snap.get("stocks"), dict) else []) or []
    return [r for r in rows if isinstance(r, dict)]


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, _to_float(v)) for v in weights.values()) or 100.0
    return {k: round(max(0.0, _to_float(v)) * 100.0 / total, 3) for k, v in weights.items()}


class AdaptiveWeightOptimizer:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context if isinstance(context, dict) else {}
        lifecycle = _read_jsonl(os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl"))
        labels = _read_jsonl(os.path.join(self.state_dir, "outcome_labels_v1.jsonl"))
        ledger = _read_json(os.path.join(self.state_dir, "learning_ledger_state.json"))
        rows = _stable_rows(self.state_dir)
        sample_size = len(lifecycle) + len(labels) + int(_to_float(ledger.get("eligible_learning_rows"), 0.0))
        returns = [
            _to_float(r.get("realized_return_pct"), _to_float(r.get("return_pct"), _to_float(r.get("pnl_pct"), 0.0)))
            for r in lifecycle
            if any(k in r for k in ("realized_return_pct", "return_pct", "pnl_pct"))
        ]
        avg_return = statistics.fmean(returns) if returns else 0.0
        missed_profit = len([r for r in labels + lifecycle if bool(r.get("missed_profit_flag"))])
        premature = len([r for r in labels + lifecycle if bool(r.get("premature_exit_flag"))])
        target_rows = [r for r in lifecycle if r.get("target_accuracy_score") is not None or r.get("target_hit_status") is not None]
        has_target_evidence = bool(target_rows or any(r.get("expected_return_pct") is not None for r in rows))
        recommended = dict(BASELINE_WEIGHTS)
        reasons: list[str] = []
        if has_target_evidence:
            recommended["expected_return_pct"] += 2.0
            recommended["grade_astra_score"] -= 1.0
            recommended["rank_persistence"] -= 1.0
            reasons.append("target-zone and expected-return evidence is available, so shadow tests can modestly emphasize profit potential")
        if missed_profit > premature and missed_profit > 0:
            recommended["conviction_10r"] += 1.5
            recommended["confidence"] -= 1.0
            recommended["psychology_brain"] -= 0.5
            reasons.append("missed-profit labels exceed premature-exit labels, favoring conviction persistence in shadow testing")
        if avg_return < 0 and returns:
            recommended["entry_quality_v3"] += 2.0
            recommended["expected_return_pct"] -= 1.0
            recommended["multi_brain_consensus"] -= 1.0
            reasons.append("recent realized returns are weak, so shadow tests increase entry-quality emphasis")
        if not reasons:
            reasons.append("insufficient realized outcome separation; keep baseline weights while collecting more labels")
        recommended = _normalize_weights(recommended)
        changed = [k for k, v in recommended.items() if abs(v - BASELINE_WEIGHTS.get(k, 0.0)) >= 0.75]
        confidence = min(85.0, 20.0 + min(sample_size, 300) * 0.16 + len(rows) * 2.0)
        projected = 0.0 if sample_size < 10 else min(8.0, max(0.5, len(changed) * 0.45 + min(abs(avg_return), 5.0) * 0.12))
        best_change = "baseline unchanged"
        if changed:
            key = max(changed, key=lambda k: abs(recommended[k] - BASELINE_WEIGHTS.get(k, 0.0)))
            delta = recommended[key] - BASELINE_WEIGHTS.get(key, 0.0)
            best_change = f"{key} {'+' if delta >= 0 else ''}{round(delta, 2)} pts"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "adaptive_weight_optimizer_status_v1": True,
            "baseline_weights": dict(BASELINE_WEIGHTS),
            "recommended_shadow_weights": recommended,
            "projected_improvement_pct": round(projected, 3),
            "confidence": round(confidence, 3),
            "confidence_score": round(confidence, 3),
            "sample_size": int(sample_size),
            "outcome_rows_evaluated": len(lifecycle),
            "label_rows_evaluated": len(labels),
            "top_buy_rows_evaluated": len(rows),
            "best_recommended_weight_change": best_change,
            "recommendation_reason": "; ".join(reasons),
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "keep_weight_changes_shadow_only_until_walk_forward_gate_passes",
        }
