from __future__ import annotations

import os
import time
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    append_jsonl_if_new,
    clamp,
    first,
    now_iso,
    rounded,
    safe_average,
    status_value,
    tail_jsonl,
    text,
    to_float,
    to_int,
    with_safety,
)


class ExitTournamentEngineV1(CachedDiagnosticModule):
    module_name = "exit_tournament_engine_v1"
    mode = "shadow_analysis_exit_tournament"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 20.0) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.tournament_path = os.path.join(self.state_dir, "exit_tournament_v1.jsonl")

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        maturation = status_value(statuses, "profit_lock_profit_capture_maturation_v2")
        protection = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        capacity = status_value(statuses, "multi_horizon_paper_capacity_exit_validation_v1")
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")

        actual_capture = to_float(first(profit.get("shadow_capture_ratio"), profit.get("capture_ratio"), maturation.get("capture_ratio"), default=50.0), 50.0)
        giveback = to_float(first(profit.get("shadow_giveback_pct"), profit.get("giveback_pct"), maturation.get("giveback_rate"), protection.get("giveback_risk_score"), default=18.0), 18.0)
        policy_scores = {
            "actual_exit": clamp(actual_capture),
            "trailing_stop_exit": clamp(actual_capture + max(0.0, giveback - 8.0) * 0.30),
            "time_exit": clamp(actual_capture + to_float(profit.get("hold_duration_quality_score"), 50.0) * 0.08),
            "volatility_exit": clamp(actual_capture + to_float(protection.get("giveback_risk_score"), 45.0) * 0.08),
            "catalyst_decay_exit": clamp(actual_capture + to_float(protection.get("catalyst_decay_risk"), 45.0) * 0.10),
            "regime_risk_exit": clamp(actual_capture + to_float(status_value(statuses, "market_transition_detection_v1").get("transition_risk_score"), 45.0) * 0.06),
            "profit_protection_exit": clamp(actual_capture + to_float(protection.get("profit_lock_readiness"), 45.0) * 0.10),
        }
        best_style, best_score = max(policy_scores.items(), key=lambda item: item[1])
        capture_gap = clamp(best_score - actual_capture)
        exit_regret = clamp(capture_gap * 0.65 + giveback * 0.35)
        snapshot_key = f"{rounded(actual_capture, 2)}:{rounded(giveback, 2)}:{best_style}:{rounded(capture_gap, 2)}"
        appended = append_jsonl_if_new(
            self.tournament_path,
            {
                "snapshot_key": snapshot_key,
                "generated_at": now_iso(),
                "actual_exit_capture": rounded(actual_capture, 3),
                "best_exit_style": best_style,
                "best_exit_capture_proxy": rounded(best_score, 3),
                "actual_vs_best_capture_gap": rounded(capture_gap, 3),
                "exit_regret": rounded(exit_regret, 3),
                "advisory_only": True,
            },
        )
        rows = tail_jsonl(self.tournament_path)
        evidence = max(to_int(profit.get("completed_shadow_lifecycles"), 0), to_int(profit.get("evidence_count"), 0), to_int(learned.get("baseline_exits_today"), 0) + to_int(learned.get("learned_corrected_exits_today"), 0))
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "ok" if evidence > 0 or actual_capture > 0 else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "exit_tournament_count": int(len(rows)),
            "latest_snapshot_appended": bool(appended),
            "best_exit_style": best_style,
            "actual_vs_best_capture_gap": rounded(capture_gap, 3),
            "average_giveback": rounded(giveback, 3),
            "capture_ratio": rounded(actual_capture, 3),
            "exit_regret": rounded(exit_regret, 3),
            "recommended_exit_bias": "profit_protection_review" if best_style == "profit_protection_exit" else best_style,
            "policy_scores": {key: rounded(value, 3) for key, value in policy_scores.items()},
            "capacity_freed_proxy": rounded(first(capacity.get("capacity_freed_today"), learned.get("capacity_freed_by_learned_exits"), default=0.0), 3),
            "evidence_count": int(evidence),
            "state_file": "state/exit_tournament_v1.jsonl",
            "append_only_diagnostic_file": True,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

