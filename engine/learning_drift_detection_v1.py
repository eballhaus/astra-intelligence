from __future__ import annotations

import time
from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, VERSION, clamp, first, now_iso, pick_max, rounded, status_score, status_value, to_float, with_safety


class LearningDriftDetectionV1(CachedDiagnosticModule):
    module_name = "learning_drift_detection_v1"
    mode = "shadow_analysis_learning_drift"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        perf = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        family = status_value(statuses, "trade_family_intelligence_v1")
        regime = status_value(statuses, "market_condition_attribution_v1")
        calibration = status_value(statuses, "confidence_calibration_performance_attribution_v1")
        signals = [
            {"drift_source": "PF drift", "score": clamp(60.0 - to_float(first(perf.get("paper_profit_factor_verified"), perf.get("paper_profit_factor"), default=2.0)) * 18.0)},
            {"drift_source": "ranking drift", "score": clamp(100.0 - to_float(ranking.get("ranking_quality_score"), 64.0))},
            {"drift_source": "win-rate drift", "score": clamp(65.0 - to_float(perf.get("paper_win_rate"), 55.0))},
            {"drift_source": "capture-ratio drift", "score": clamp(70.0 - status_score(statuses, "profit_capture_peak_decay_exit_validation_suite_v1", ["capture_ratio", "shadow_capture_ratio"], 50.0))},
            {"drift_source": "catalyst decay", "score": clamp(to_float(catalyst.get("decay_probability"), 35.0))},
            {"drift_source": "trade-family decay", "score": clamp(80.0 - to_float(family.get("family_transfer_confidence"), 50.0))},
            {"drift_source": "regime reliability decay", "score": clamp(80.0 - to_float(regime.get("condition_confidence_score"), 50.0))},
            {"drift_source": "calibration drift", "score": clamp(to_float(calibration.get("calibration_error"), 25.0))},
        ]
        top = pick_max(signals, "score")
        drift_score = clamp(sum(row["score"] for row in signals) / max(1, len(signals)))
        drift_level = "high" if drift_score >= 65 else "moderate" if drift_score >= 40 else "low"
        affected = "profit_capture" if "capture" in top.get("drift_source", "").lower() else top.get("drift_source", "insufficient_data").replace(" ", "_")
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "drift_score": rounded(drift_score, 3),
            "drift_level": drift_level,
            "drift_source": top.get("drift_source", "insufficient_data"),
            "affected_area": affected,
            "suggested_action": "prioritize_shadow_validation_and_tournament_review" if drift_level != "low" else "continue_monitoring",
            "evidence_count": max(to_float(perf.get("canonical_closed_trade_count"), 0), to_float(ranking.get("evidence_count"), 0)),
            "drift_signals": [{**row, "score": rounded(row.get("score"), 3)} for row in signals],
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

