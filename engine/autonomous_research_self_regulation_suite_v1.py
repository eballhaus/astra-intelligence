from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 3_000_000
MAX_ROWS = 1_500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text if text else str(default)


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


def _load_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _label(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 65:
        return "healthy"
    if score >= 45:
        return "watch"
    return "needs_attention"


class AutonomousResearchSelfRegulationSuiteV1:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.learning_last_good_path = os.path.join(self.state_dir, "learning_insights_last_good.json")
        self.stable_top_buys_path = os.path.join(self.state_dir, "snapshots", "stable_top_buys_v1.json")

    def status(
        self,
        observation_payload: dict[str, Any] | None = None,
        execution_payload: dict[str, Any] | None = None,
        portfolio_payload: dict[str, Any] | None = None,
        learning_snapshot_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._status(
                observation_payload or {},
                execution_payload or {},
                portfolio_payload or {},
                learning_snapshot_payload or {},
            )
        except Exception as exc:
            return self._fallback(f"autonomous_research_self_regulation_unavailable: {str(exc)[:140]}")

    def _status(
        self,
        observation: dict[str, Any],
        execution: dict[str, Any],
        portfolio: dict[str, Any],
        learning_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        stable = _load_json(self.stable_top_buys_path)
        learning_last_good = _load_json(self.learning_last_good_path)
        labels = _tail_jsonl(self.labels_path)
        lifecycle = _tail_jsonl(self.lifecycle_path)
        ledger = _tail_jsonl(self.ledger_path, max_rows=800, max_bytes=1_500_000)
        top_rows = [r for r in stable.get("stable_top_6") or [] if isinstance(r, dict)]

        metrics = {
            "released_win_rate": _to_float(
                learning_snapshot.get("current_engine_released_wr"),
                _to_float(learning_last_good.get("released_hero_win_rate"), 0.0),
            ),
            "entry_quality": _to_float(
                learning_snapshot.get("entry_quality"),
                _to_float(learning_last_good.get("entry_quality_score"), 0.0),
            ),
            "exit_quality": _to_float(
                learning_snapshot.get("exit_quality"),
                _to_float(learning_last_good.get("current_engine_exit_timing_score"), 0.0),
            ),
            "buy_list_purity": _to_float(
                learning_snapshot.get("buy_list_purity"),
                _to_float(learning_last_good.get("buy_list_purity_score"), 0.0),
            ),
            "context_confidence": _to_float(execution.get("market_knowledge_score"), _avg(top_rows, "context_score", 50.0)),
            "portfolio_concentration": 100.0 - _to_float(portfolio.get("highest_concentration_risk"), 0.0),
            "execution_readiness": _to_float(execution.get("execution_readiness_score"), 0.0),
            "closed_trade_flow": _to_float(observation.get("trades_closed_today"), 0.0) * 25.0,
            "label_flow": _to_float(observation.get("learning_throughput_score"), 0.0),
            "observation_completion": _to_float(observation.get("observation_completion_score"), 0.0),
        }
        normalized = {k: _normalize_metric(k, v) for k, v in metrics.items()}
        weakness_key, weakness_score = min(normalized.items(), key=lambda kv: kv[1])
        weakness_severity = _clamp(100.0 - weakness_score)

        likely_causes = self._root_causes(
            weakness_key,
            observation,
            execution,
            portfolio,
            labels,
            lifecycle,
            stable,
        )
        root_confidence = _clamp(55.0 + min(30.0, len(likely_causes) * 7.0))

        ranking_count = len(ledger)
        top_count = len(top_rows)
        label_count = len(labels)
        lifecycle_count = len(lifecycle)
        stable_ok = bool(stable.get("stable_top_6")) and _to_float(stable.get("stable_count"), top_count) > 0
        top_buys_integrity = 100.0 if top_count >= 6 else _clamp(top_count / 6.0 * 100.0)
        ranking_integrity = 100.0 if ranking_count > 0 else 0.0
        label_integrity = _clamp(min(100.0, label_count / 200.0 * 100.0))
        lifecycle_integrity = _clamp(min(100.0, lifecycle_count / 100.0 * 100.0))
        structural_health = _clamp(
            (top_buys_integrity * 0.30)
            + (ranking_integrity * 0.20)
            + (label_integrity * 0.20)
            + (lifecycle_integrity * 0.15)
            + ((100.0 if stable_ok else 35.0) * 0.15)
        )
        primary_structural = self._primary_structural_weakness(top_count, ranking_count, label_count, lifecycle_count, stable_ok)

        label_flow_score = _clamp(_to_float(observation.get("learning_throughput_score"), 0.0))
        observation_flow_score = _clamp(_to_float(observation.get("observation_intelligence_score"), 0.0))
        learning_pipeline_integrity = _clamp(
            (ranking_integrity * 0.18)
            + (top_buys_integrity * 0.18)
            + (observation_flow_score * 0.24)
            + (label_flow_score * 0.25)
            + (lifecycle_integrity * 0.15)
        )

        experiments = self._experiments(weakness_key, likely_causes, execution)
        highest_experiment = experiments[0] if experiments else "continue_shadow_observation_collection"
        promotion_recommendation = "continue_shadow_testing"
        if weakness_severity >= 75 or structural_health < 55:
            promotion_recommendation = "monitor_only"
        elif structural_health >= 80 and learning_pipeline_integrity >= 70 and weakness_severity < 35:
            promotion_recommendation = "continue_shadow_testing"
        promotion_confidence = _clamp((structural_health * 0.35) + (learning_pipeline_integrity * 0.35) + ((100.0 - weakness_severity) * 0.30))

        research_priority = _clamp((weakness_severity * 0.45) + ((100.0 - learning_pipeline_integrity) * 0.25) + ((100.0 - structural_health) * 0.20) + (len(likely_causes) * 2.0))
        priorities = self._priorities(weakness_key, likely_causes, primary_structural)
        suite_score = _clamp((structural_health * 0.30) + (learning_pipeline_integrity * 0.30) + ((100.0 - weakness_severity) * 0.25) + ((100.0 - research_priority) * 0.15))
        reasons, penalties = self._reasons_penalties(structural_health, learning_pipeline_integrity, weakness_key, likely_causes, primary_structural)

        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "automatic_promotions_enabled": False,
            "automatic_threshold_changes_enabled": False,
            "autonomous_research_self_regulation_status_v1": True,
            "generated_at": _now_iso(),
            "max_rows": MAX_ROWS,
            "max_tail_bytes": MAX_TAIL_BYTES,
            "primary_trading_weakness": weakness_key,
            "weakness_severity_score": round(weakness_severity, 3),
            "weakness_summary": f"Weakest current area is {weakness_key.replace('_', ' ')} with severity {weakness_severity:.1f}.",
            "likely_root_causes": likely_causes,
            "root_cause_confidence": round(root_confidence, 3),
            "root_cause_summary": ", ".join(c.replace("_", " ") for c in likely_causes[:3]) or "insufficient evidence",
            "recommended_experiments": experiments,
            "highest_priority_experiment": highest_experiment,
            "expected_improvement_area": weakness_key,
            "experiment_safety_label": "shadow_only_no_auto_promotion",
            "promotion_recommendation": promotion_recommendation,
            "promotion_reason": "Recommendations require more shadow evidence before any production use.",
            "promotion_confidence": round(promotion_confidence, 3),
            "structural_health_score": round(structural_health, 3),
            "structural_health_label": _label(structural_health),
            "primary_structural_weakness": primary_structural,
            "structural_recommendation_summary": self._structural_summary(primary_structural),
            "learning_pipeline_integrity_score": round(learning_pipeline_integrity, 3),
            "label_flow_score": round(label_flow_score, 3),
            "observation_flow_score": round(observation_flow_score, 3),
            "learning_integrity_summary": (
                f"Pipeline integrity {learning_pipeline_integrity:.1f}; rankings/top_buys/local labels are present, "
                f"but observation closure flow remains the main limiter."
            ),
            "research_priority_score": round(research_priority, 3),
            "top_research_priorities": priorities,
            "next_best_action_summary": priorities[0] if priorities else "continue_shadow_monitoring",
            "suite_4_score": round(suite_score, 3),
            "suite_4_label": _label(suite_score),
            "suite_4_reasons": reasons,
            "suite_4_penalties": penalties,
            "suite_4_summary": (
                f"Control tower recommends {highest_experiment.replace('_', ' ')}; "
                f"promotion remains {promotion_recommendation.replace('_', ' ')}."
            ),
            "source_summary": {
                "top_buys_count": top_count,
                "label_rows_sampled": label_count,
                "lifecycle_rows_sampled": lifecycle_count,
                "decision_rows_sampled": ranking_count,
            },
        }

    def _root_causes(
        self,
        weakness: str,
        observation: dict[str, Any],
        execution: dict[str, Any],
        portfolio: dict[str, Any],
        labels: list[dict[str, Any]],
        lifecycle: list[dict[str, Any]],
        stable: dict[str, Any],
    ) -> list[str]:
        causes: list[str] = []
        closed = _to_float(observation.get("trades_closed_today"), 0.0)
        completion = _to_float(observation.get("observation_completion_score"), 0.0)
        insufficient = sum(1 for r in labels if _safe_text(r.get("outcome_label")).lower() == "insufficient_data")
        insufficient_rate = insufficient / max(1, len(labels)) * 100.0
        if closed <= 0:
            causes.append("insufficient_closed_trades")
        if completion < 45:
            causes.append("observation_completion_gap")
        if insufficient_rate >= 45:
            causes.append("stale_or_insufficient_labels")
        if weakness in {"entry_quality", "buy_list_purity"}:
            causes.append("weak_entries_or_confirmation")
        if weakness in {"exit_quality", "closed_trade_flow"}:
            causes.append("limited_natural_exit_evidence")
        if _to_float(execution.get("expected_slippage_bps"), 0.0) >= 25:
            causes.append("execution_friction")
        if _to_float(portfolio.get("highest_concentration_risk"), 0.0) >= 60:
            causes.append("concentration_risk")
        if _to_float(stable.get("stable_count"), len(stable.get("stable_top_6") or [])) < 6:
            causes.append("top_buys_fill_or_integrity_gap")
        if not lifecycle:
            causes.append("lifecycle_flow_missing")
        return list(dict.fromkeys(causes))[:8] or ["insufficient_evidence"]

    def _experiments(self, weakness: str, causes: list[str], execution: dict[str, Any]) -> list[str]:
        experiments: list[str] = []
        if "insufficient_closed_trades" in causes:
            experiments.append("shadow_test_modest_paper_only_entry_expansion_without_forced_exits")
        if weakness in {"entry_quality", "buy_list_purity"} or "weak_entries_or_confirmation" in causes:
            experiments.append("shadow_compare_entry_confirmation_filters_by_setup_and_regime")
        if weakness in {"exit_quality", "closed_trade_flow"}:
            experiments.append("shadow_analyze_natural_exit_paths_for_premature_or_late_exit_patterns")
        if "stale_or_insufficient_labels" in causes:
            experiments.append("shadow_prioritize_label_completeness_for_recent_paper_outcomes")
        if _to_float(execution.get("execution_readiness_score"), 0.0) >= 60:
            experiments.append("shadow_evaluate_limit_order_preference_for_paper_ready_candidates")
        experiments.append("shadow_rank_next_improvement_by_learning_pipeline_impact")
        return list(dict.fromkeys(experiments))[:6]

    def _priorities(self, weakness: str, causes: list[str], structural: str) -> list[str]:
        out = [
            f"improve_{weakness}",
            "increase_completed_paper_observations_naturally",
            "raise_label_and_context_completeness",
        ]
        if structural != "healthy":
            out.insert(0, f"fix_{structural}")
        for cause in causes:
            if cause not in {"insufficient_evidence"}:
                out.append(f"investigate_{cause}")
        return list(dict.fromkeys(out))[:8]

    def _primary_structural_weakness(self, top_count: int, ranking_count: int, label_count: int, lifecycle_count: int, stable_ok: bool) -> str:
        if ranking_count <= 0:
            return "ranking_pipeline_missing_recent_rows"
        if top_count < 6:
            return "stable_top_buys_snapshot_underfilled"
        if not stable_ok:
            return "stable_top_buys_snapshot_stale_or_missing"
        if lifecycle_count <= 0:
            return "lifecycle_flow_missing"
        if label_count <= 0:
            return "label_flow_missing"
        return "healthy"

    def _structural_summary(self, weakness: str) -> str:
        if weakness == "healthy":
            return "Core local ranking, top_buys, lifecycle, and label artifacts are present."
        return f"Monitor and repair {weakness.replace('_', ' ')} before considering any promotion."

    def _reasons_penalties(self, structural: float, integrity: float, weakness: str, causes: list[str], structural_weakness: str) -> tuple[list[str], list[str]]:
        reasons: list[str] = []
        penalties: list[str] = []
        if structural >= 65:
            reasons.append("structural_artifacts_present")
        else:
            penalties.append("structural_health_below_target")
        if integrity >= 50:
            reasons.append("learning_pipeline_partially_connected")
        else:
            penalties.append("learning_pipeline_integrity_low")
        if structural_weakness != "healthy":
            penalties.append(structural_weakness)
        if "insufficient_closed_trades" in causes:
            penalties.append("insufficient_closed_trades")
        if weakness:
            penalties.append(f"primary_weakness_{weakness}")
        return list(dict.fromkeys(reasons))[:8], list(dict.fromkeys(penalties))[:8]

    def _fallback(self, reason: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "automatic_promotions_enabled": False,
            "automatic_threshold_changes_enabled": False,
            "autonomous_research_self_regulation_status_v1": True,
            "primary_trading_weakness": "suite_error",
            "weakness_severity_score": 100.0,
            "likely_root_causes": ["suite_error"],
            "highest_priority_experiment": "inspect_suite_runtime",
            "promotion_recommendation": "monitor_only",
            "structural_health_score": 0.0,
            "primary_structural_weakness": "suite_error",
            "learning_pipeline_integrity_score": 0.0,
            "research_priority_score": 100.0,
            "suite_4_score": 0.0,
            "suite_4_summary": reason,
        }


def _avg(rows: list[dict[str, Any]], key: str, default: float = 0.0) -> float:
    values = [_to_float(row.get(key), float("nan")) for row in rows]
    values = [v for v in values if v == v]
    return sum(values) / len(values) if values else default


def _normalize_metric(key: str, value: float) -> float:
    value = _to_float(value, 0.0)
    if key == "released_win_rate":
        return _clamp(value if value > 1.0 else value * 100.0)
    if key == "closed_trade_flow":
        return _clamp(value)
    if key == "portfolio_concentration":
        return _clamp(value)
    return _clamp(value)
