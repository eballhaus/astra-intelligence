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
    status_value,
    tail_jsonl,
    text,
    to_float,
    to_int,
    with_safety,
)


class RankingTournamentEngineV1(CachedDiagnosticModule):
    module_name = "ranking_tournament_engine_v1"
    mode = "shadow_analysis_ranking_tournament"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 20.0) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.tournament_path = os.path.join(self.state_dir, "ranking_tournament_v1.jsonl")

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        opportunity = status_value(statuses, "opportunity_cost_learning")
        execution = status_value(statuses, "execution_participation_audit")
        trace = status_value(statuses, "paper_execution_trace")

        selected = max(to_int(ranking.get("selected_candidates"), 0), to_int(execution.get("candidates_submitted"), 0), to_int(opportunity.get("selected_candidates_reviewed"), 0))
        reviewed = max(to_int(ranking.get("top_ranked_candidates"), 0), to_int(execution.get("reviewed_total"), 0), selected)
        missed = max(to_int(ranking.get("missed_candidates"), 0), to_int(ranking.get("missed_winners"), 0), to_int(execution.get("high_confidence_candidates_blocked"), 0))
        ranking_quality = to_float(ranking.get("ranking_quality_score"), 0.0)
        predictive = to_float(ranking.get("ranking_predictive_power"), 0.0)
        promotion_accuracy = to_float(ranking.get("promotion_accuracy"), 0.0)
        astra_win_rate = clamp((ranking_quality * 0.45) + (predictive * 0.35) + (promotion_accuracy * 0.20))
        regret = clamp(to_float(ranking.get("opportunity_ranking_gap"), 0.0) + max(0.0, 100.0 - astra_win_rate) * 0.28 + min(25.0, missed * 0.25))
        best_missed = text(first(ranking.get("biggest_missed_promotion"), ranking.get("dominant_missed_winner_pattern"), default="insufficient_data"))
        failure_modes = [
            text(ranking.get("dominant_ranking_mistake"), "ranking_factor_misalignment"),
            text(ranking.get("dominant_rejection_mistake"), "rejection_threshold_noise"),
            text(ranking.get("most_overvalued_factor"), "overvalued_context_factor"),
        ]
        snapshot_key = f"{to_int(reviewed)}:{to_int(selected)}:{to_int(missed)}:{rounded(regret, 2)}:{best_missed}"
        appended = append_jsonl_if_new(
            self.tournament_path,
            {
                "snapshot_key": snapshot_key,
                "generated_at": now_iso(),
                "candidate_set_size": int(reviewed),
                "astra_selected_count": int(selected),
                "later_best_proxy": best_missed,
                "average_ranking_regret": rounded(regret, 3),
                "astra_win_rate": rounded(astra_win_rate, 3),
                "advisory_only": True,
            },
        )
        rows = tail_jsonl(self.tournament_path)
        tournament_count = len(rows)
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "ok" if reviewed > 0 else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "tournament_count": int(tournament_count),
            "latest_snapshot_appended": bool(appended),
            "candidate_set_size": int(reviewed),
            "astra_selected_count": int(selected),
            "astra_win_rate": rounded(astra_win_rate, 3),
            "average_ranking_regret": rounded(regret, 3),
            "best_missed_candidate": best_missed,
            "ranking_quality_delta": rounded(ranking_quality - 70.0, 3),
            "top_ranking_failure_modes": failure_modes[:3],
            "recommendation": "study_missed_promotions_and_overvalued_ranking_factors" if regret >= 25 else "continue_ranking_tournament_collection",
            "state_file": "state/ranking_tournament_v1.jsonl",
            "append_only_diagnostic_file": True,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

