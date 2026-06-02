from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1800


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
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


def _return_pct(row: dict[str, Any]) -> float:
    return _to_float(
        row.get("current_or_exit_profit_pct"),
        _to_float(row.get("current_return_pct"), _to_float(row.get("continuation_after_entry_pct"), _to_float(row.get("actual_return_pct")))),
    )


def _profit_factor(returns: list[float]) -> float:
    gains = sum(v for v in returns if v > 0)
    losses = abs(sum(v for v in returns if v < 0))
    if losses <= 0:
        return round(gains, 4) if gains > 0 else 0.0
    return round(gains / losses, 4)


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [_to_float(row.get(key)) for row in rows if row.get(key) not in (None, "")]
    return round(mean(vals), 4) if vals else None


def _context(row: dict[str, Any]) -> dict[str, str]:
    return {
        "archetype": _text(row.get("trade_archetype") or row.get("archetype") or row.get("same_archetype"), "unknown"),
        "regime": _text(row.get("market_regime") or row.get("regime") or row.get("same_regime"), "unknown"),
        "sector": _text(row.get("sector") or row.get("same_sector"), "unknown"),
        "cap_tier": _text(row.get("cap_tier") or row.get("same_cap_tier"), "unknown"),
        "horizon_style": _text(row.get("horizon_style") or row.get("same_horizon_style"), "unknown"),
        "follow_through": _text(row.get("follow_through_label") or row.get("continuation_pattern_label"), "unknown"),
    }


class AdvancedLearningIntelligenceV1:
    """Consolidated learning diagnostics across performance, memory, graph, and explanations.

    This module is intentionally observation-only. It reads bounded local state,
    writes append-only learning summaries, and never touches broker/ranking control.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or 8.0)
        self.lifecycle_v2_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.lifecycle_v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.replay_path = os.path.join(self.state_dir, "replay_counterfactual_learning_v2.jsonl")
        self.opportunity_path = os.path.join(self.state_dir, "opportunity_cost_learning_v1.jsonl")
        self.profit_path = os.path.join(self.state_dir, "adaptive_profit_capture_intelligence_v1.jsonl")
        self.archetype_path = os.path.join(self.state_dir, "trade_archetype_regime_intelligence_v1.jsonl")
        self.memory_path = os.path.join(self.state_dir, "trade_memory_similarity_v1.jsonl")
        self.graph_path = os.path.join(self.state_dir, "learning_knowledge_graph_v1.jsonl")
        self.explanation_path = os.path.join(self.state_dir, "explanation_intelligence_v1.jsonl")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _lifecycle_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for path in (self.lifecycle_v1_path, self.lifecycle_v2_path, self.profit_path, self.archetype_path):
            for row in _tail_jsonl(path):
                lifecycle_id = _text(row.get("lifecycle_id"))
                symbol = _text(row.get("symbol")).upper()
                key = lifecycle_id or f"{symbol}:{_text(row.get('entry_timestamp') or row.get('timestamp'))[:16]}"
                if not key or key == ":":
                    continue
                merged = dict(latest.get(key) or {})
                merged.update(row)
                latest[key] = merged
        return list(latest.values())

    def _metrics_reconciliation(self, lifecycle_rows: list[dict[str, Any]], replay_rows: list[dict[str, Any]], opportunity_rows: list[dict[str, Any]]) -> dict[str, Any]:
        returns = [_return_pct(row) for row in lifecycle_rows if row.get("symbol")]
        non_zero_returns = [v for v in returns if abs(v) > 1e-9]
        wins = [v for v in non_zero_returns if v > 0]
        losses = [v for v in non_zero_returns if v < 0]
        sample = len(non_zero_returns)
        win_rate = round((len(wins) / sample) * 100.0, 4) if sample else None
        profit_factor = _profit_factor(non_zero_returns) if sample else None
        avg_return = round(mean(non_zero_returns), 4) if sample else None
        expectancy = round(((win_rate or 0.0) * max(avg_return or 0.0, 0.0)) / 10.0, 4) if sample else None
        replay_count = len(replay_rows)
        opportunity_count = len(opportunity_rows)
        broker_close_count = len([r for r in lifecycle_rows if r.get("closed") or r.get("exit_timestamp")])
        replay_actual = _avg(replay_rows, "actual_return_pct")
        source_counts = {
            "lifecycle_evidence": len(lifecycle_rows),
            "return_evidence": sample,
            "replay_learning_evidence": replay_count,
            "opportunity_cost_evidence": opportunity_count,
            "broker_confirmed_closes_proxy": broker_close_count,
            "profit_capture_evidence": len(_tail_jsonl(self.profit_path, max_rows=800)),
        }
        populated_sources = sum(1 for value in source_counts.values() if value > 0)
        consistency = _clamp((populated_sources / max(1, len(source_counts))) * 82.0 + min(18.0, sample * 1.4))
        mismatch_flags: list[str] = []
        if lifecycle_rows and not non_zero_returns:
            mismatch_flags.append("lifecycle_rows_without_return_values")
        if replay_rows and sample and abs((replay_actual or 0.0) - (avg_return or 0.0)) > 8.0:
            mismatch_flags.append("replay_actual_return_differs_from_lifecycle_average")
        if not lifecycle_rows:
            mismatch_flags.append("empty_lifecycle_dataset")
        confidence = _clamp(consistency - len(mismatch_flags) * 9.0 + min(12.0, sample * 0.8))
        blocking_mismatches = [flag for flag in mismatch_flags if flag in {"lifecycle_rows_without_return_values", "empty_lifecycle_dataset"}]
        scope_mismatch = bool("replay_actual_return_differs_from_lifecycle_average" in mismatch_flags)
        return {
            "metrics_reconciled": bool(sample > 0 and not blocking_mismatches),
            "source_validation_passed": bool(populated_sources >= 3 and sample > 0 and not blocking_mismatches),
            "evidence_consistency_score": round(consistency, 4),
            "metric_confidence_score": round(confidence, 4),
            "released_win_rate": win_rate,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "average_return": avg_return,
            "expectancy": expectancy,
            "evidence_counts": source_counts,
            "mismatches": mismatch_flags,
            "dataset_scope_label": "lifecycle_return_rows_with_replay_scope_mismatch" if scope_mismatch else "lifecycle_return_rows",
            "dataset_scope_mismatch_detected": scope_mismatch,
            "open_trade_inclusion": "included_when_current_return_available",
            "closed_trade_inclusion": "included_when_exit_or_return_available",
            "replay_actual_average_return": replay_actual,
            "reconciliation_summary": (
                f"Reconciled {sample} return-bearing lifecycle rows across {populated_sources} learning sources."
                + (" Replay uses a different counterfactual/lifecycle scope, so it is labeled separately." if scope_mismatch else "")
                if sample
                else "Waiting for return-bearing lifecycle evidence before reconciling core performance metrics."
            ),
        }

    def _similarity_learning(self, rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        records: list[dict[str, Any]] = []
        if len(rows) < 2:
            return {
                "similar_trade_count": 0,
                "closest_trade_matches": [],
                "average_similar_return": None,
                "average_similar_follow_through": None,
                "average_similar_profit_capture": None,
                "best_similar_context": "insufficient_data",
                "worst_similar_context": "insufficient_data",
                "similarity_confidence": 0.0,
                "memory_quality_score": 0.0,
            }, records
        for idx, row in enumerate(rows):
            symbol = _text(row.get("symbol")).upper()
            if not symbol:
                continue
            ctx = _context(row)
            best_score = -1
            best: dict[str, Any] | None = None
            for jdx, other in enumerate(rows):
                if idx == jdx:
                    continue
                other_symbol = _text(other.get("symbol")).upper()
                if not other_symbol:
                    continue
                other_ctx = _context(other)
                score = sum(1 for key in ("archetype", "regime", "sector", "cap_tier", "horizon_style", "follow_through") if ctx[key] == other_ctx[key] and ctx[key] != "unknown")
                score += 1 if abs(_to_float(row.get("profit_capture_ratio")) - _to_float(other.get("profit_capture_ratio"))) <= 0.25 else 0
                score += 1 if abs(_to_float(row.get("hold_duration_minutes")) - _to_float(other.get("hold_duration_minutes"))) <= 90 else 0
                if score > best_score:
                    best_score = score
                    best = other
            if best:
                record = {
                    "symbol": symbol,
                    "closest_symbol": _text(best.get("symbol")).upper(),
                    "similarity_score": round((best_score / 8.0) * 100.0, 4),
                    "current_return_pct": _round(_return_pct(row)),
                    "similar_return_pct": _round(_return_pct(best)),
                    "similar_follow_through": _to_float(best.get("follow_through_quality_score")),
                    "similar_profit_capture": _to_float(best.get("profit_capture_ratio")),
                    "context": ctx,
                    "generated_at": _now_iso(),
                }
                records.append(record)
        contexts: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            ctx = _context(row)
            key = f"{ctx['archetype']}|{ctx['regime']}"
            contexts[key].append(_return_pct(row))
        best_ctx = max(contexts.items(), key=lambda item: mean(item[1]) if item[1] else -999, default=("insufficient_data", []))[0]
        worst_ctx = min(contexts.items(), key=lambda item: mean(item[1]) if item[1] else 999, default=("insufficient_data", []))[0]
        avg_score = mean([_to_float(r.get("similarity_score")) for r in records]) if records else 0.0
        return {
            "similar_trade_count": len(records),
            "closest_trade_matches": records[-8:],
            "average_similar_return": round(mean([_to_float(r.get("similar_return_pct")) for r in records]), 4) if records else None,
            "average_similar_follow_through": round(mean([_to_float(r.get("similar_follow_through")) for r in records]), 4) if records else None,
            "average_similar_profit_capture": round(mean([_to_float(r.get("similar_profit_capture")) for r in records]), 4) if records else None,
            "best_similar_context": best_ctx,
            "worst_similar_context": worst_ctx,
            "similarity_confidence": round(_clamp(avg_score), 4),
            "memory_quality_score": round(_clamp(avg_score * 0.7 + min(30.0, len(records) * 0.5)), 4),
        }, records

    def _knowledge_graph(self, rows: list[dict[str, Any]], opportunity_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        relationships: list[dict[str, Any]] = []
        specs = [
            ("archetype_to_profit_capture", "trade_archetype", "profit_capture_ratio"),
            ("archetype_to_follow_through", "trade_archetype", "follow_through_quality_score"),
            ("regime_to_profit_capture", "market_regime", "profit_capture_ratio"),
            ("regime_to_expectancy", "market_regime", "current_or_exit_profit_pct"),
        ]
        for name, group_key, metric_key in specs:
            grouped: dict[str, list[float]] = defaultdict(list)
            for row in rows:
                key = _text(row.get(group_key) or _context(row).get("archetype" if group_key == "trade_archetype" else "regime"), "unknown")
                value = _to_float(row.get(metric_key), _return_pct(row) if metric_key == "current_or_exit_profit_pct" else 0.0)
                if key != "unknown":
                    grouped[key].append(value)
            for key, values in grouped.items():
                if values:
                    relationships.append({
                        "connection": name,
                        "node": key,
                        "sample_size": len(values),
                        "strength": round(mean(values), 4),
                        "confidence": round(_clamp(min(100.0, len(values) * 12.0)), 4),
                    })
        if opportunity_rows:
            costs = [_to_float(r.get("opportunity_cost_pct")) for r in opportunity_rows]
            relationships.append({
                "connection": "opportunity_cost_to_selection_quality",
                "node": "selection_engine",
                "sample_size": len(costs),
                "strength": round(-mean(costs), 4) if costs else 0.0,
                "confidence": round(_clamp(min(100.0, len(costs) * 0.6)), 4),
            })
        strongest = max(relationships, key=lambda r: _to_float(r.get("strength")) + _to_float(r.get("confidence")) * 0.05, default={})
        weakest = min(relationships, key=lambda r: _to_float(r.get("strength")) - _to_float(r.get("confidence")) * 0.02, default={})
        confidence = round(mean([_to_float(r.get("confidence")) for r in relationships]), 4) if relationships else 0.0
        maturity = "warming_up"
        if confidence >= 70 and len(relationships) >= 10:
            maturity = "developing_graph"
        if confidence >= 82 and len(relationships) >= 18:
            maturity = "mature_learning_graph"
        graph = {
            "strongest_learning_connection": f"{_text(strongest.get('connection'), 'insufficient_data')}:{_text(strongest.get('node'), 'insufficient_data')}",
            "weakest_learning_connection": f"{_text(weakest.get('connection'), 'insufficient_data')}:{_text(weakest.get('node'), 'insufficient_data')}",
            "graph_confidence": confidence,
            "graph_maturity": maturity,
            "graph_insights": [
                f"{_text(strongest.get('connection'), 'insufficient_data')} is currently strongest around {_text(strongest.get('node'), 'insufficient_data')}.",
                f"{_text(weakest.get('connection'), 'insufficient_data')} needs more review around {_text(weakest.get('node'), 'insufficient_data')}.",
            ] if relationships else ["Waiting for enough lifecycle and opportunity-cost evidence to build graph insights."],
        }
        return graph, relationships

    def _explanation_intelligence(self, metrics: dict[str, Any], memory: dict[str, Any], graph: dict[str, Any], opportunity_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        evidence = _to_int((metrics.get("evidence_counts") or {}).get("return_evidence")) + _to_int(memory.get("similar_trade_count")) + len(opportunity_rows)
        explanation_confidence = _clamp((metrics.get("metric_confidence_score") or 0.0) * 0.35 + (memory.get("memory_quality_score") or 0.0) * 0.35 + (graph.get("graph_confidence") or 0.0) * 0.3)
        quality = _clamp(explanation_confidence + min(12.0, evidence * 0.05))
        recommendation = "insufficient_data"
        if evidence >= 25:
            recommendation = "use_similarity_regime_and_opportunity_cost_evidence_in_candidate_explanations"
        rows = [{
            "timestamp": _now_iso(),
            "explanation_quality_score": round(quality, 4),
            "explanation_confidence": round(explanation_confidence, 4),
            "supporting_evidence_count": evidence,
            "example_explanation": (
                "Selected because similar trades, current regime fit, profit-capture evidence, "
                "and opportunity-cost review support the candidate; human review remains required."
            ),
            "auto_apply_allowed": False,
            "live_trading_changed": False,
        }]
        return {
            "explanation_quality_score": round(quality, 4),
            "explanation_confidence": round(explanation_confidence, 4),
            "supporting_evidence_count": evidence,
            "explanation_recommendation": recommendation,
            "candidate_explanation_template": rows[0]["example_explanation"],
        }, rows

    def _write_rows(self, path: str, rows: list[dict[str, Any]], limit: int = 100) -> None:
        if not rows:
            return
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                for row in rows[-limit:]:
                    row = dict(row)
                    row.setdefault("enabled", True)
                    row.setdefault("version", VERSION)
                    row.setdefault("api_calls_used", 0)
                    row.setdefault("live_trading_changed", False)
                    row.setdefault("paper_only_preserved", True)
                    row.setdefault("alpaca_paper_only_preserved", True)
                    row.setdefault("natural_exit_preserved", True)
                    row.setdefault("forced_trades_enabled", False)
                    row.setdefault("forced_exits_enabled", False)
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def status(self, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out

        lifecycle_rows = self._lifecycle_rows()
        replay_rows = _tail_jsonl(self.replay_path, max_rows=900)
        opportunity_rows = _tail_jsonl(self.opportunity_path, max_rows=900)
        metrics = self._metrics_reconciliation(lifecycle_rows, replay_rows, opportunity_rows)
        memory, memory_rows = self._similarity_learning(lifecycle_rows)
        graph, graph_rows = self._knowledge_graph(lifecycle_rows, opportunity_rows)
        explanation, explanation_rows = self._explanation_intelligence(metrics, memory, graph, opportunity_rows)
        if now - self._last_write >= 45.0:
            self._last_write = now
            self._write_rows(self.memory_path, memory_rows, limit=120)
            self._write_rows(self.graph_path, graph_rows, limit=160)
            self._write_rows(self.explanation_path, explanation_rows, limit=20)

        recommendation = explanation.get("explanation_recommendation")
        if not metrics.get("source_validation_passed"):
            recommendation = "reconcile_metric_sources_before_tuning"
        elif _to_float(memory.get("memory_quality_score")) < 45:
            recommendation = "collect_more_similar_trade_memory"

        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_advanced_learning_diagnostics",
            **metrics,
            **memory,
            **graph,
            **explanation,
            "recommendation": recommendation,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
