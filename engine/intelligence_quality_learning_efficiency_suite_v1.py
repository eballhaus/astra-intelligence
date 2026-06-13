from __future__ import annotations

import time
from typing import Any

from engine.confidence_decomposition_engine_v1 import ConfidenceDecompositionEngineV1
from engine.conviction_calibration_engine_v1 import ConvictionCalibrationEngineV1
from engine.evidence_quality_scoring_v1 import EvidenceQualityScoringV1
from engine.exit_tournament_engine_v1 import ExitTournamentEngineV1
from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    first,
    now_iso,
    rounded,
    status_value,
    text,
    with_safety,
)
from engine.learning_drift_detection_v1 import LearningDriftDetectionV1
from engine.learning_roi_engine_v1 import LearningRoiEngineV1
from engine.market_regime_similarity_engine_v1 import MarketRegimeSimilarityEngineV1
from engine.ranking_tournament_engine_v1 import RankingTournamentEngineV1


class IntelligenceQualityLearningEfficiencySuiteV1(CachedDiagnosticModule):
    module_name = "intelligence_quality_learning_efficiency_suite_v1"
    mode = "shadow_analysis_intelligence_quality_learning_efficiency"

    def __init__(
        self,
        state_dir: str = "state",
        ttl_seconds: float = 20.0,
        learning_roi_engine: LearningRoiEngineV1 | None = None,
        evidence_quality_scoring: EvidenceQualityScoringV1 | None = None,
        confidence_decomposition_engine: ConfidenceDecompositionEngineV1 | None = None,
        learning_drift_detection: LearningDriftDetectionV1 | None = None,
        market_regime_similarity_engine: MarketRegimeSimilarityEngineV1 | None = None,
        ranking_tournament_engine: RankingTournamentEngineV1 | None = None,
        exit_tournament_engine: ExitTournamentEngineV1 | None = None,
        conviction_calibration_engine: ConvictionCalibrationEngineV1 | None = None,
    ) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.learning_roi_engine = learning_roi_engine or LearningRoiEngineV1(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.evidence_quality_scoring = evidence_quality_scoring or EvidenceQualityScoringV1(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.confidence_decomposition_engine = confidence_decomposition_engine or ConfidenceDecompositionEngineV1(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.learning_drift_detection = learning_drift_detection or LearningDriftDetectionV1(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.market_regime_similarity_engine = market_regime_similarity_engine or MarketRegimeSimilarityEngineV1(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.ranking_tournament_engine = ranking_tournament_engine or RankingTournamentEngineV1(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.exit_tournament_engine = exit_tournament_engine or ExitTournamentEngineV1(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.conviction_calibration_engine = conviction_calibration_engine or ConvictionCalibrationEngineV1(state_dir=state_dir, ttl_seconds=ttl_seconds)

    def _module(self, statuses: dict[str, Any], key: str, builder: Any) -> dict[str, Any]:
        cached = status_value(statuses, key)
        if cached:
            return with_safety(cached)
        return builder.status(statuses=statuses, force=False)

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        modules = {
            "learning_roi_engine_v1": self._module(statuses, "learning_roi_engine_v1", self.learning_roi_engine),
            "evidence_quality_scoring_v1": self._module(statuses, "evidence_quality_scoring_v1", self.evidence_quality_scoring),
            "confidence_decomposition_engine_v1": self._module(statuses, "confidence_decomposition_engine_v1", self.confidence_decomposition_engine),
            "learning_drift_detection_v1": self._module(statuses, "learning_drift_detection_v1", self.learning_drift_detection),
            "market_regime_similarity_engine_v1": self._module(statuses, "market_regime_similarity_engine_v1", self.market_regime_similarity_engine),
            "ranking_tournament_engine_v1": self._module(statuses, "ranking_tournament_engine_v1", self.ranking_tournament_engine),
            "exit_tournament_engine_v1": self._module(statuses, "exit_tournament_engine_v1", self.exit_tournament_engine),
            "conviction_calibration_engine_v1": self._module(statuses, "conviction_calibration_engine_v1", self.conviction_calibration_engine),
        }
        roi = modules["learning_roi_engine_v1"]
        evidence = modules["evidence_quality_scoring_v1"]
        confidence = modules["confidence_decomposition_engine_v1"]
        drift = modules["learning_drift_detection_v1"]
        regime = modules["market_regime_similarity_engine_v1"]
        ranking = modules["ranking_tournament_engine_v1"]
        exit_tournament = modules["exit_tournament_engine_v1"]
        conviction = modules["conviction_calibration_engine_v1"]

        insufficient = [name for name, payload in modules.items() if text(payload.get("status"), "ok") == "insufficient_evidence"]
        recommended = text(first(
            roi.get("recommended_next_focus"),
            ranking.get("recommendation"),
            exit_tournament.get("recommended_exit_bias"),
            default="continue_shadow_diagnostics",
        ))
        summary = {
            "highest_value_learning_system": text(roi.get("highest_value_learning_system"), "insufficient_data"),
            "weakest_confidence_component": text(confidence.get("weakest_component"), "insufficient_data"),
            "highest_quality_evidence_area": text(evidence.get("quality_bucket"), "insufficient_data"),
            "largest_ranking_regret": rounded(ranking.get("average_ranking_regret"), 3),
            "largest_exit_regret": rounded(exit_tournament.get("exit_regret"), 3),
            "drift_warning": text(drift.get("drift_level"), "insufficient_data"),
            "recommended_next_focus": recommended,
        }
        payload = {
            "enabled": True,
            "suite": "ASTRA Intelligence Quality & Learning Efficiency Suite V1",
            "version": VERSION,
            "status": "ok" if len(insufficient) < len(modules) else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "shadow_only": True,
            "advisory_only": True,
            "modules": modules,
            "summary": summary,
            "modules_reporting_insufficient_evidence": insufficient,
            "highest_value_learning_system": summary["highest_value_learning_system"],
            "weighted_evidence_count": rounded(evidence.get("weighted_evidence_count"), 3),
            "weakest_confidence_component": summary["weakest_confidence_component"],
            "drift_warning": summary["drift_warning"],
            "most_similar_regime": text(regime.get("most_similar_regime"), "insufficient_data"),
            "ranking_tournament_regret": rounded(ranking.get("average_ranking_regret"), 3),
            "exit_tournament_capture_gap": rounded(exit_tournament.get("actual_vs_best_capture_gap"), 3),
            "conviction_calibration_score": rounded(conviction.get("calibration_score"), 3),
            "recommended_next_focus": recommended,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

