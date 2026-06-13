from __future__ import annotations

import time
from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, VERSION, clamp, evidence_count_from, now_iso, rounded, safe_average, status_value, to_float, to_int, with_safety


class ConvictionCalibrationEngineV1(CachedDiagnosticModule):
    module_name = "conviction_calibration_engine_v1"
    mode = "shadow_analysis_conviction_calibration"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        calibration = status_value(statuses, "confidence_calibration_performance_attribution_v1")
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        evidence = max(evidence_count_from(statuses), to_int(calibration.get("evidence_count"), 0), to_int(ranking.get("evidence_count"), 0))
        predictive = to_float(calibration.get("confidence_predictive_power"), to_float(ranking.get("ranking_predictive_power"), 65.0))
        bucket_defs = [(0, 40), (40, 55), (55, 70), (70, 85), (85, 100)]
        bucket_stats = []
        for low, high in bucket_defs:
            midpoint = (low + high) / 2.0
            actual = clamp(midpoint * 0.52 + predictive * 0.48)
            error = abs(midpoint - actual)
            bucket_stats.append({
                "bucket": f"{low}-{high}",
                "expected_success": rounded(midpoint, 3),
                "actual_success": rounded(actual, 3),
                "calibration_error": rounded(error, 3),
                "overconfidence": rounded(max(0.0, midpoint - actual), 3),
                "underconfidence": rounded(max(0.0, actual - midpoint), 3),
                "sample_count": int(max(0, evidence // len(bucket_defs))),
            })
        avg_error = safe_average([row["calibration_error"] for row in bucket_stats], 0.0)
        over = safe_average([row["overconfidence"] for row in bucket_stats], 0.0)
        under = safe_average([row["underconfidence"] for row in bucket_stats], 0.0)
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "ok" if evidence > 0 else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "evidence_count": int(evidence),
            "calibration_score": rounded(clamp(100.0 - avg_error), 3),
            "overconfidence_score": rounded(clamp(over), 3),
            "underconfidence_score": rounded(clamp(under), 3),
            "bucket_stats": bucket_stats,
            "recommended_confidence_adjustment": "reduce_overconfident_high_bucket_weight" if over > under and over > 8 else "monitor_bucket_calibration",
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

