"""Adaptive Self-Correction Controller V1 (shadow recommendation mode, local-only)."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _parse_iso(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


class SelfCorrectionController:
    """Local-only recommendation controller. Never changes live behavior."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.candidate_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.outcome_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.replay_path = os.path.join(self.state_dir, "replay_results_v2.json")
        self.history_path = os.path.join(self.state_dir, "self_correction_history_v1.json")
        self.learning_insights_last_good_path = os.path.join(self.state_dir, "learning_insights_last_good.json")
        self._lock = threading.Lock()
        self._cache_payload: dict[str, Any] | None = None
        self._cache_ts = 0.0
        try:
            self.ttl_seconds = max(15.0, min(300.0, float(os.getenv("ASTRA_SELF_CORRECTION_TTL_SECONDS", "45"))))
        except Exception:
            self.ttl_seconds = 45.0
        try:
            self.max_rows = max(500, min(30000, int(float(os.getenv("ASTRA_SELF_CORRECTION_MAX_ROWS", "7000")))))
        except Exception:
            self.max_rows = 7000
        self.persistence_cycles = 3
        self.persistence_hours = 24

    def status(self) -> dict[str, Any]:
        payload = self.recommendations(force_refresh=False)
        return {
            "enabled": True,
            "mode": "shadow_recommendation",
            "local_only": True,
            "api_calls_used": 0,
            "last_updated_utc": str(payload.get("generated_at") or _now_iso()),
            "recommendation_count": int(len(payload.get("recommendation_priority") or [])),
            "health_score": round(_to_float((payload.get("evidence_summary") or {}).get("learning_pipeline_health_score"), 0.0), 2),
        }

    def recommendations(
        self,
        *,
        policy_compare_payload: dict[str, Any] | None = None,
        learning_quality_payload: dict[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if (
                not force_refresh
                and self._cache_payload is not None
                and (now - self._cache_ts) <= self.ttl_seconds
            ):
                return dict(self._cache_payload)

        payload = self._build_payload(
            policy_compare_payload=policy_compare_payload or {},
            learning_quality_payload=learning_quality_payload or {},
        )
        with self._lock:
            self._cache_payload = dict(payload)
            self._cache_ts = time.time()
        return payload

    def _tail_jsonl_rows(self, path: str, max_rows: int) -> list[dict[str, Any]]:
        out: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_rows)))
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    s = str(raw or "").strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        out.append(obj)
        except Exception:
            return []
        return list(out)

    def _safe_read_json(self, path: str, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default

    def _safe_write_json(self, path: str, payload: Any) -> bool:
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            os.replace(tmp_path, path)
            return True
        except Exception:
            return False

    @staticmethod
    def _evidence_score(evidence: dict[str, Any]) -> float:
        values = [
            _to_float(evidence.get("learning_pipeline_health_score"), 0.0),
            _to_float(evidence.get("runtime_health_score"), 0.0),
            _to_float(evidence.get("provider_health_score"), 0.0),
            _to_float(evidence.get("behavior_verification_score"), 0.0),
            _to_float(evidence.get("learning_continuity_score"), 0.0),
        ]
        present = [value for value in values if value > 0.0]
        return sum(present) / max(1, len(present))

    @staticmethod
    def _entry_signature(recommendation: str, evidence: dict[str, Any]) -> str:
        root_cause = str(evidence.get("root_cause") or evidence.get("primary_blocker") or "")
        bottleneck = str(evidence.get("paper_learning_bottleneck") or "")
        return f"{recommendation}|{root_cause}|{bottleneck}"

    def decision_memory_summary(self) -> dict[str, Any]:
        history = self._safe_read_json(self.history_path, {})
        entries = list((history or {}).get("entries") or []) if isinstance(history, dict) else []
        resolved = [row for row in entries if row.get("recommendation_effectiveness_score") is not None]
        improved = [row for row in resolved if row.get("improved_later") is True]
        repeated = sum(max(0, _to_int(row.get("repeat_count"), 1) - 1) for row in entries)
        latest = entries[-1] if entries else {}
        latest_ts = _parse_iso(latest.get("last_seen_at") or latest.get("timestamp"))
        age_hours = (
            max(0.0, time.time() - latest_ts.timestamp()) / 3600.0
            if latest_ts is not None
            else None
        )
        retention = min(
            100.0,
            (35.0 if entries else 0.0)
            + min(25.0, len(resolved) * 2.5)
            + (20.0 if (history or {}).get("compressed_archive_count") else 0.0)
            + (20.0 if latest.get("intelligence_dna") else 0.0),
        )
        effectiveness = (
            sum(_to_float(row.get("recommendation_effectiveness_score"), 0.0) for row in resolved)
            / max(1, len(resolved))
        )
        return {
            "status": "ok" if entries else "insufficient_evidence",
            "decision_memory_enabled": True,
            "memory_path": self.history_path,
            "active_memory_entries": len(entries),
            "correction_memories_stored": len(entries),
            "compressed_archive_count": _to_int((history or {}).get("compressed_archive_count"), 0),
            "duplicate_snapshots_suppressed": _to_int((history or {}).get("duplicate_snapshots_suppressed"), 0),
            "repeated_observations_retained": repeated,
            "outcomes_evaluated": len(resolved),
            "recommendations_improved_later": len(improved),
            "successful_corrections": len(improved),
            "failed_corrections": max(0, len(resolved) - len(improved)),
            "prior_correction_matches": int(bool(entries and latest.get("repeat_count", 1) > 1)),
            "recurring_issue_memory_hits": repeated,
            "recommendation_effectiveness_score": round(effectiveness, 3),
            "knowledge_retention_score": round(retention, 3),
            "latest_memory_age_hours": round(age_hours, 3) if age_hours is not None else None,
            "latest_root_cause": str(
                (latest.get("evidence_metrics") or {}).get("root_cause")
                or (latest.get("evidence_metrics") or {}).get("primary_blocker")
                or "insufficient_evidence"
            ),
            "latest_recommendation": str(latest.get("recommendation") or "insufficient_evidence"),
            "latest_intelligence_dna": dict(latest.get("intelligence_dna") or {}),
            "decision_memory_prevents_duplicate_research": bool(
                _to_int((history or {}).get("duplicate_snapshots_suppressed"), 0) > 0
            ),
            "memory_reinforcement_needed": len(resolved) < max(3, len(entries) // 4),
            "decision_memory_summary": (
                f"{len(entries)} bounded correction memories retained; {len(resolved)} have comparable outcomes, "
                f"{len(improved)} improved, and {max(0, len(resolved) - len(improved))} did not."
            ),
            "behavior_safe_to_apply": False,
            "paper_only_preserved": True,
            "broker_behavior_changed": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
        }

    def record_maturation_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        recommendation = {
            "recommendation": str(snapshot.get("recommended_action") or "continue_collecting"),
            "severity": str(snapshot.get("severity") or "info"),
            "expected_benefit": dict(snapshot.get("expected_benefit") or {}),
        }
        evidence = {
            "issue_detected": str(snapshot.get("issue_detected") or snapshot.get("primary_blocker") or "none"),
            "root_cause": str(snapshot.get("root_cause") or "insufficient_evidence"),
            "correction_applied": str(snapshot.get("correction_applied") or "advisory_recommendation_only"),
            "correction_worked": snapshot.get("correction_worked"),
            "behavior_test_result": str(snapshot.get("behavior_test_result") or "not_yet_evaluated"),
            "learning_impact": snapshot.get("learning_impact"),
            "paper_trading_impact": snapshot.get("paper_trading_impact"),
            "shadow_readiness_impact": snapshot.get("shadow_readiness_impact"),
            "issue_recurred": bool(snapshot.get("issue_recurred")),
            "future_recommendation": str(snapshot.get("future_recommendation") or snapshot.get("recommended_action") or "continue_collecting"),
            "primary_blocker": str(snapshot.get("primary_blocker") or "none"),
            "paper_learning_bottleneck": str(snapshot.get("paper_learning_bottleneck") or "none"),
            "behavior_verification_score": _to_float(snapshot.get("behavior_verification_score"), 0.0),
            "learning_continuity_score": _to_float(snapshot.get("learning_continuity_score"), 0.0),
            "promotion_readiness_score": _to_float(snapshot.get("promotion_readiness_score"), 0.0),
            "improvement_priority": str(snapshot.get("improvement_priority") or "none"),
        }
        return self._write_and_summarize_history(
            recommendation=recommendation,
            evidence=evidence,
            intelligence_dna=dict(snapshot.get("intelligence_dna") or {}),
        )

    def _runtime_health_score(self) -> float:
        heartbeat_path = os.path.join(self.state_dir, "backend_watchdog_heartbeat")
        if not os.path.exists(heartbeat_path):
            return 55.0
        try:
            age = max(0.0, time.time() - float(os.path.getmtime(heartbeat_path)))
        except Exception:
            return 55.0
        if age <= 120:
            return 95.0
        if age <= 300:
            return 80.0
        if age <= 900:
            return 60.0
        return 35.0

    def _provider_health_score(self) -> float:
        gov_path = os.path.join(self.state_dir, "api_usage_governor.json")
        gov = self._safe_read_json(gov_path, {})
        if not isinstance(gov, dict):
            return 75.0
        hard_block = bool(gov.get("hard_stop") or gov.get("hard_stop_active"))
        warning = bool(gov.get("warning") or gov.get("warning_active"))
        if hard_block:
            return 40.0
        if warning:
            return 65.0
        return 90.0

    def _build_payload(self, *, policy_compare_payload: dict[str, Any], learning_quality_payload: dict[str, Any]) -> dict[str, Any]:
        outcomes = self._tail_jsonl_rows(self.outcome_path, self.max_rows)
        candidates = self._tail_jsonl_rows(self.candidate_path, self.max_rows)
        lifecycle = self._tail_jsonl_rows(self.lifecycle_path, self.max_rows)
        replay = self._safe_read_json(self.replay_path, {})
        learning_snapshot = self._safe_read_json(self.learning_insights_last_good_path, {})

        labeled_count = len(outcomes)
        released = [r for r in outcomes if bool(r.get("was_released", False))]
        blocked = [r for r in outcomes if bool(r.get("was_blocked", False))]
        recent_released = []
        now_ts = time.time()
        for r in released:
            dt = _parse_iso(r.get("evaluated_at_utc")) or _parse_iso(r.get("timestamp_utc"))
            if dt is not None and (now_ts - dt.timestamp()) <= 86400:
                recent_released.append(r)

        def _win_rate(rows: list[dict[str, Any]]) -> float:
            if not rows:
                return 0.0
            wins = 0
            for r in rows:
                ret = _to_float(r.get("return_pct"), 0.0)
                if ret > 0:
                    wins += 1
            return (wins / max(1, len(rows))) * 100.0

        released_wr = _win_rate(released)
        blocked_wr = _win_rate(blocked)
        released_vs_blocked_gap = released_wr - blocked_wr
        entry_quality = sum(_to_float(r.get("entry_quality_score"), 0.0) for r in released) / max(1, len(released))
        follow_through_quality = sum(_to_float(r.get("return_pct"), 0.0) for r in released) / max(1, len(released))
        exit_timing_quality = sum(_to_float(r.get("mfe_efficiency_score"), 0.0) for r in released) / max(1, len(released))
        buy_list_purity = released_wr

        # Confidence truthfulness and FP/FN style estimates from local labels.
        high_conf = [r for r in outcomes if _to_float(r.get("confidence"), 0.0) >= 70.0]
        high_conf_losses = [r for r in high_conf if _to_float(r.get("return_pct"), 0.0) < 0]
        false_positive_rate = (len(high_conf_losses) / max(1, len(high_conf))) * 100.0
        blocked_winners = [r for r in blocked if _to_float(r.get("return_pct"), 0.0) > 0]
        false_negative_rate = (len(blocked_winners) / max(1, len(blocked))) * 100.0 if blocked else 0.0
        confidence_truthfulness = max(0.0, min(100.0, 100.0 - false_positive_rate))

        learning_health = _to_float(learning_quality_payload.get("learning_pipeline_health_score"), 0.0)
        freshness = _to_float(learning_quality_payload.get("learning_data_freshness_score"), 0.0)
        policy_reco = str(policy_compare_payload.get("recommendation") or "insufficient_data")
        policy_metrics = policy_compare_payload.get("metrics_by_policy") if isinstance(policy_compare_payload, dict) else {}
        current_policy_samples = 0
        if isinstance(policy_metrics, dict):
            cur = policy_metrics.get("current_policy")
            if isinstance(cur, dict):
                current_policy_samples = _to_int(cur.get("sample_count"), 0)

        replay_rows_available = max(
            _to_int((replay or {}).get("source_row_count"), 0),
            _to_int((replay or {}).get("rows_evaluated"), 0),
            _to_int((replay or {}).get("sample_count"), 0),
        )
        open_trade_count = len([r for r in lifecycle if not str(r.get("lifecycle_stage") or "").startswith("closed") and not str(r.get("exit_timestamp") or "").strip()])
        closed_trade_count = len([r for r in lifecycle if str(r.get("lifecycle_stage") or "").startswith("closed") or str(r.get("exit_timestamp") or "").strip()])

        runtime_health = self._runtime_health_score()
        provider_health = self._provider_health_score()

        evidence_thresholds_met = bool(
            labeled_count >= 100
            and len(recent_released) >= 30
            and current_policy_samples >= 20
            and learning_health >= 60.0
        )
        blockers: list[str] = []
        if labeled_count < 100:
            blockers.append("labeled_trades_below_100")
        if len(recent_released) < 30:
            blockers.append("recent_released_trades_below_30")
        if current_policy_samples < 20:
            blockers.append("policy_context_samples_below_20")
        if learning_health < 60.0:
            blockers.append("learning_pipeline_health_below_60")
        if freshness < 60.0:
            blockers.append("data_freshness_below_60")
        if runtime_health < 60.0:
            blockers.append("runtime_health_degraded")
        if provider_health < 60.0:
            blockers.append("provider_health_degraded")

        rec_candidates: list[dict[str, Any]] = []
        if not evidence_thresholds_met:
            rec_candidates.append(
                {
                    "recommendation": "continue_collecting" if labeled_count > 0 else "insufficient_data",
                    "severity": "info",
                    "confidence": 0.55,
                    "estimate_confidence": "low",
                    "reasons": ["minimum_evidence_thresholds_not_met"],
                    "bounded_adjustments": [
                        "require 50–100 additional labeled trades before reconsideration",
                    ],
                    "expected_benefit": {
                        "expected_wr_improvement": 0.0,
                        "expected_false_positive_reduction": 0.0,
                        "expected_purity_improvement": 0.0,
                    },
                    "rollback_guidance": {
                        "reevaluate_after_samples": 100,
                        "reevaluate_after_hours": 24,
                        "revert_if_no_improvement": "n/a_shadow_only",
                    },
                    "impact_score": 25.0,
                }
            )
        else:
            # Cross-metric recommendations.
            if entry_quality < 58.0 and released_wr < 52.0 and policy_reco in {"keep_current", "insufficient_data", "monitor"}:
                rec_candidates.append(
                    {
                        "recommendation": "tighten_entry_confirmation",
                        "severity": "warning",
                        "confidence": 0.78,
                        "estimate_confidence": "moderate",
                        "reasons": ["entry_quality_weak", "released_wr_weak", "policy_compare_not_supporting_looser"],
                        "bounded_adjustments": [
                            "increase confirmation threshold by 2–5 points",
                            "move weak setups to monitor-only for 24 hours",
                        ],
                        "expected_benefit": {
                            "expected_wr_improvement": 2.5,
                            "expected_false_positive_reduction": 5.0,
                            "expected_purity_improvement": 3.0,
                        },
                        "rollback_guidance": {
                            "reevaluate_after_samples": 200,
                            "reevaluate_after_hours": 24,
                            "revert_if_no_improvement": "wr_improvement_below_2_points",
                        },
                        "impact_score": 78.0,
                    }
                )
            if false_positive_rate > 42.0 and confidence_truthfulness < 60.0:
                rec_candidates.append(
                    {
                        "recommendation": "lower_confidence_scores",
                        "severity": "caution",
                        "confidence": 0.74,
                        "estimate_confidence": "moderate",
                        "reasons": ["false_positive_rate_elevated", "confidence_truthfulness_low"],
                        "bounded_adjustments": [
                            "lower confidence by 3–7 points",
                            "reduce policy weight by 5–10%",
                        ],
                        "expected_benefit": {
                            "expected_wr_improvement": 1.5,
                            "expected_false_positive_reduction": 6.5,
                            "expected_purity_improvement": 2.0,
                        },
                        "rollback_guidance": {
                            "reevaluate_after_samples": 180,
                            "reevaluate_after_hours": 24,
                            "revert_if_no_improvement": "false_positive_reduction_below_2_points",
                        },
                        "impact_score": 71.0,
                    }
                )
            if false_negative_rate > 45.0 and blocked_wr > released_wr + 5.0:
                rec_candidates.append(
                    {
                        "recommendation": "loosen_entry_confirmation",
                        "severity": "caution",
                        "confidence": 0.66,
                        "estimate_confidence": "low",
                        "reasons": ["false_negative_rate_high", "blocked_winners_exceed_released"],
                        "bounded_adjustments": [
                            "decrease confirmation threshold by 2–4 points",
                            "increase policy weight by 5–8% for validated setups only",
                        ],
                        "expected_benefit": {
                            "expected_wr_improvement": 1.0,
                            "expected_false_positive_reduction": 0.0,
                            "expected_purity_improvement": 1.5,
                        },
                        "rollback_guidance": {
                            "reevaluate_after_samples": 220,
                            "reevaluate_after_hours": 24,
                            "revert_if_no_improvement": "purity_improvement_below_1_point",
                        },
                        "impact_score": 63.0,
                    }
                )
            if not rec_candidates:
                rec_candidates.append(
                    {
                        "recommendation": "keep_current",
                        "severity": "info",
                        "confidence": 0.72,
                        "estimate_confidence": "moderate",
                        "reasons": ["cross_metric_signals_stable"],
                        "bounded_adjustments": ["continue monitoring with current bounded posture"],
                        "expected_benefit": {
                            "expected_wr_improvement": 0.0,
                            "expected_false_positive_reduction": 0.0,
                            "expected_purity_improvement": 0.0,
                        },
                        "rollback_guidance": {
                            "reevaluate_after_samples": 150,
                            "reevaluate_after_hours": 24,
                            "revert_if_no_improvement": "n/a_shadow_only",
                        },
                        "impact_score": 40.0,
                    }
                )

        persisted_rec = self._apply_persistence_gates(rec_candidates)
        final_reco = persisted_rec[0]
        history_summary = self._write_and_summarize_history(
            recommendation=final_reco,
            evidence={
                "labeled_count": labeled_count,
                "recent_released_count": len(recent_released),
                "current_policy_samples": current_policy_samples,
                "learning_pipeline_health_score": learning_health,
                "runtime_health_score": runtime_health,
                "provider_health_score": provider_health,
            },
        )

        evidence_summary = {
            "current_engine_released_wr": round(released_wr, 3),
            "released_vs_blocked_wr_gap": round(released_vs_blocked_gap, 3),
            "entry_quality": round(entry_quality, 3),
            "follow_through_quality": round(follow_through_quality, 4),
            "exit_timing_quality": round(exit_timing_quality, 3),
            "buy_list_purity": round(buy_list_purity, 3),
            "confidence_truthfulness": round(confidence_truthfulness, 3),
            "false_positive_rate": round(false_positive_rate, 3),
            "false_negative_rate": round(false_negative_rate, 3),
            "policy_compare_recommendation": policy_reco,
            "learning_pipeline_health_score": round(learning_health, 3),
            "data_freshness_score": round(freshness, 3),
            "provider_health_score": round(provider_health, 3),
            "runtime_health_score": round(runtime_health, 3),
            "labeled_trade_count": int(labeled_count),
            "recent_released_trade_count": int(len(recent_released)),
            "context_specific_samples": int(current_policy_samples),
            "open_trade_count": int(open_trade_count),
            "closed_trade_count": int(closed_trade_count),
            "replay_learning_rows_available": int(replay_rows_available),
            "candidate_rows_count": int(len(candidates)),
            "learning_snapshot_available": bool(isinstance(learning_snapshot, dict) and len(learning_snapshot) > 0),
        }

        return {
            "enabled": True,
            "mode": "shadow_recommendation",
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "recommendation": str(final_reco.get("recommendation") or "insufficient_data"),
            "severity": str(final_reco.get("severity") or "info"),
            "confidence": round(_to_float(final_reco.get("confidence"), 0.0), 4),
            "estimate_confidence": str(final_reco.get("estimate_confidence") or "low"),
            "reasons": list(final_reco.get("reasons") or []),
            "blockers": blockers,
            "suggested_safe_actions": [
                "shadow_only_no_live_changes",
                "review_recommendations_with_human_before_any_policy_update",
            ],
            "bounded_adjustments": list(final_reco.get("bounded_adjustments") or []),
            "expected_benefit": dict(final_reco.get("expected_benefit") or {}),
            "rollback_guidance": dict(final_reco.get("rollback_guidance") or {}),
            "evidence_summary": evidence_summary,
            "metrics_used": sorted(list(evidence_summary.keys())),
            "recommendation_priority": persisted_rec,
            "recommendation_history_summary": history_summary,
            "stability_guardrails_active": bool(len(blockers) > 0),
            "minimum_evidence_thresholds": {
                "labeled_trades": 100,
                "recent_released_trades": 30,
                "context_specific_trades": 20,
                "learning_pipeline_health_score": 60,
            },
            "persistence_requirement": {
                "cycles": self.persistence_cycles,
                "hours": self.persistence_hours,
            },
        }

    def _apply_persistence_gates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = sorted(
            [dict(c) for c in candidates],
            key=lambda c: (
                -_to_float(c.get("impact_score"), 0.0),
                {"critical": 4, "warning": 3, "caution": 2, "info": 1}.get(str(c.get("severity") or "info"), 1),
                _to_float(c.get("confidence"), 0.0),
            ),
        )
        history = self._safe_read_json(self.history_path, {})
        entries = list((history or {}).get("entries") or [])
        now_dt = datetime.now(UTC)

        for item in ranked:
            key = str(item.get("recommendation") or "")
            if not key:
                continue
            same = []
            for ent in reversed(entries):
                if str(ent.get("recommendation") or "") == key:
                    same.append(ent)
                    if len(same) >= self.persistence_cycles:
                        break
            sustained_cycles = len(same) >= self.persistence_cycles
            sustained_time = False
            if same:
                oldest_ts = _parse_iso((same[-1] or {}).get("timestamp"))
                if oldest_ts is not None:
                    sustained_time = (now_dt.timestamp() - oldest_ts.timestamp()) >= (self.persistence_hours * 3600)
            if sustained_cycles or sustained_time:
                item["persistence_confirmed"] = True
                item["persistence_detail"] = (
                    f"{len(same)}_cycles" if sustained_cycles else f"{self.persistence_hours}h_window"
                )
            else:
                item["persistence_confirmed"] = False
                item["persistence_detail"] = f"needs_{self.persistence_cycles}_cycles_or_{self.persistence_hours}h"
                if item.get("recommendation") not in {"continue_collecting", "insufficient_data", "keep_current"}:
                    item["recommendation"] = "continue_collecting"
                    item["severity"] = "info"
                    reasons = list(item.get("reasons") or [])
                    reasons.append("persistence_not_met")
                    item["reasons"] = reasons
                    item["bounded_adjustments"] = [
                        "hold recommendation in shadow for persistence window",
                        "collect additional stable evidence before any change",
                    ]
        return ranked

    def _write_and_summarize_history(
        self,
        *,
        recommendation: dict[str, Any],
        evidence: dict[str, Any],
        intelligence_dna: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        history = self._safe_read_json(self.history_path, {})
        if not isinstance(history, dict):
            history = {}
        entries = list(history.get("entries") or [])
        now_iso = _now_iso()
        recommendation_name = str(recommendation.get("recommendation") or "insufficient_data")
        signature = self._entry_signature(recommendation_name, evidence)
        current_score = self._evidence_score(evidence)

        for prior in reversed(entries):
            if prior.get("recommendation_effectiveness_score") is not None:
                continue
            prior_score = self._evidence_score(dict(prior.get("evidence_metrics") or {}))
            if prior_score <= 0.0 or current_score <= 0.0:
                continue
            delta = current_score - prior_score
            prior["improved_later"] = bool(delta > 1.0)
            prior["recommendation_effectiveness_score"] = round(max(-100.0, min(100.0, delta)), 3)
            prior["evaluated_at"] = now_iso
            break

        duplicate = False
        if entries:
            latest = entries[-1]
            latest_ts = _parse_iso(latest.get("last_seen_at") or latest.get("timestamp"))
            duplicate = bool(
                latest.get("signature") == signature
                and latest_ts is not None
                and (time.time() - latest_ts.timestamp()) <= 21600
            )
        if duplicate:
            entries[-1]["last_seen_at"] = now_iso
            entries[-1]["repeat_count"] = _to_int(entries[-1].get("repeat_count"), 1) + 1
            entries[-1]["evidence_metrics"] = dict(evidence)
            if intelligence_dna:
                entries[-1]["intelligence_dna"] = dict(intelligence_dna)
            history["duplicate_snapshots_suppressed"] = _to_int(
                history.get("duplicate_snapshots_suppressed"), 0
            ) + 1
        else:
            entries.append(
                {
                    "timestamp": now_iso,
                    "last_seen_at": now_iso,
                    "signature": signature,
                    "repeat_count": 1,
                    "recommendation": recommendation_name,
                    "severity": str(recommendation.get("severity") or "info"),
                    "evidence_metrics": dict(evidence),
                    "intelligence_dna": dict(intelligence_dna or {}),
                    "expected_benefit": dict(recommendation.get("expected_benefit") or {}),
                    "improved_later": None,
                    "recommendation_effectiveness_score": None,
                }
            )
        if len(entries) > 300:
            removed = len(entries) - 300
            history["compressed_archive_count"] = _to_int(history.get("compressed_archive_count"), 0) + removed
            entries = entries[-300:]
        history["entries"] = entries
        history["last_updated_utc"] = now_iso
        self._safe_write_json(self.history_path, history)

        recent = entries[-100:]
        dist: dict[str, int] = {}
        sev: dict[str, int] = {}
        for e in recent:
            r = str(e.get("recommendation") or "unknown")
            s = str(e.get("severity") or "info")
            dist[r] = int(dist.get(r, 0)) + 1
            sev[s] = int(sev.get(s, 0)) + 1
        return {
            "history_path": self.history_path,
            "entries_total": int(len(entries)),
            "compressed_archive_count": _to_int(history.get("compressed_archive_count"), 0),
            "duplicate_snapshots_suppressed": _to_int(history.get("duplicate_snapshots_suppressed"), 0),
            "entries_recent_100": int(len(recent)),
            "recommendation_distribution_recent_100": dist,
            "severity_distribution_recent_100": sev,
            "last_recommendation": str(entries[-1].get("recommendation") if entries else ""),
        }
