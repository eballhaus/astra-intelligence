from __future__ import annotations

from engine.astra_intelligence_effectiveness_learning_velocity_v1 import (
    build_lesson_contextual_applicability_v1,
)


def _truth(lesson_id: str, *, lane: str = "DAY", horizon: str = "day_trade", regime: str = "TREND", evidence_class: str = "BROKER_CONFIRMED_COMPLETE") -> dict:
    return {
        "broker_truth_id": f"truth-{lesson_id}-{lane}-{regime}",
        "lesson_id": lesson_id,
        "evidence_class": evidence_class,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "return_pct": 1.0,
        "exit_timestamp": "2026-08-20T12:00:00Z",
        "lane_id": lane,
        "horizon": horizon,
        "regime": regime,
    }


def _target(*lesson_ids: str, lane: str = "DAY", horizon: str = "day_trade", regime: str | None = "TREND") -> dict:
    row = {"candidate_id": "candidate-1", "candidate_lesson_ids": list(lesson_ids), "lane_id": lane, "intended_horizon": horizon}
    if regime is not None:
        row["regime"] = regime
    return row


def _build(lessons: list[dict], truths: list[dict], targets: list[dict], effectiveness: list[dict] | None = None) -> dict:
    return build_lesson_contextual_applicability_v1(
        lessons=lessons,
        truths=truths,
        lesson_effectiveness=effectiveness or [],
        target_contexts=targets,
    )


def test_day_only_lesson_applies_to_day_but_not_scalp_or_crypto() -> None:
    lessons = [{"lesson_id": "day-lesson"}]
    truths = [_truth("day-lesson")]
    day = _build(lessons, truths, [_target("day-lesson")])["target_evaluations"][0]
    scalp = _build(lessons, truths, [_target("day-lesson", lane="SCALP", horizon="scalp")])["target_evaluations"][0]
    crypto = _build(lessons, truths, [_target("day-lesson", lane="CRYPTO", horizon="crypto")])["target_evaluations"][0]
    assert day["applicability_status"] == "APPLICABLE_WITH_CAUTION"
    assert scalp["applicability_status"] == "GENERALIZATION_NOT_PROVEN"
    assert crypto["applicability_status"] == "GENERALIZATION_NOT_PROVEN"


def test_multi_lane_lesson_applies_only_to_independently_proven_lanes() -> None:
    result = _build(
        [{"lesson_id": "multi"}],
        [_truth("multi", lane="DAY"), _truth("multi", lane="SCALP", horizon="scalp")],
        [_target("multi", lane="SCALP", horizon="scalp"), _target("multi", lane="SWING", horizon="swing_trade")],
    )
    assert result["target_evaluations"][0]["applicability_status"] == "APPLICABLE_WITH_CAUTION"
    assert result["target_evaluations"][1]["applicability_status"] == "GENERALIZATION_NOT_PROVEN"


def test_regime_match_mismatch_and_missing_regime_are_explicit() -> None:
    lessons, truths = [{"lesson_id": "trend"}], [_truth("trend", regime="TREND")]
    matched = _build(lessons, truths, [_target("trend", regime="TREND")])["target_evaluations"][0]
    mismatch = _build(lessons, truths, [_target("trend", regime="CHOP")])["target_evaluations"][0]
    missing = _build(lessons, truths, [_target("trend", regime=None)])["target_evaluations"][0]
    assert matched["regime_match"] == "REGIME_MATCH"
    assert mismatch["applicability_status"] == "CONTEXT_MISMATCH"
    assert missing["applicability_status"] == "INSUFFICIENT_EVIDENCE"


def test_explicit_contradiction_resolves_by_lane_context_without_deleting_evidence() -> None:
    lessons = [
        {"lesson_id": "day-cut", "contradictory_lesson_ids": ["scalp-hold"]},
        {"lesson_id": "scalp-hold", "contradictory_lesson_ids": ["day-cut"]},
    ]
    result = _build(
        lessons,
        [_truth("day-cut", lane="DAY"), _truth("scalp-hold", lane="SCALP", horizon="scalp")],
        [_target("day-cut", "scalp-hold", lane="DAY", horizon="day_trade")],
    )
    resolution = result["resolutions"][0]
    assert resolution["resolution_status"] == "CONTRADICTION_RESOLVED_BY_CONTEXT"
    assert resolution["contradictory_lesson_ids"] == ["day-cut", "scalp-hold"]
    assert result["conflicting_evidence_preserved"] is True


def test_explicit_contradiction_resolves_by_regime_context() -> None:
    lessons = [
        {"lesson_id": "trend", "contradictory_lesson_ids": ["chop"]},
        {"lesson_id": "chop", "contradictory_lesson_ids": ["trend"]},
    ]
    result = _build(
        lessons,
        [_truth("trend", regime="TREND"), _truth("chop", regime="CHOP")],
        [_target("trend", "chop", regime="TREND")],
    )
    assert result["resolutions"][0]["resolution_status"] == "CONTRADICTION_RESOLVED_BY_CONTEXT"


def test_unresolved_same_context_contradiction_fails_closed_for_guidance() -> None:
    lessons = [
        {"lesson_id": "one", "contradictory_lesson_ids": ["two"]},
        {"lesson_id": "two", "contradictory_lesson_ids": ["one"]},
    ]
    result = _build(lessons, [_truth("one"), _truth("two")], [_target("one", "two")])
    resolution = result["resolutions"][0]
    assert resolution["resolution_status"] == "CONTRADICTION_UNRESOLVED_FAIL_CLOSED"
    assert resolution["resolved_lesson_ids"] == []


def test_effectiveness_insufficient_never_becomes_proven_and_replay_never_supports_global_application() -> None:
    result = _build(
        [{"lesson_id": "replay"}],
        [_truth("replay", evidence_class="REPLAY")],
        [_target("replay")],
        effectiveness=[{"lesson_id": "replay", "evidence_status": "INSUFFICIENT_CANONICAL_EVIDENCE"}],
    )
    assert result["lesson_contexts"][0]["source_lane_ids"] == []
    assert result["summary"]["globally_applicable_lessons"] == 0
    assert result["execution_authority"] == "NONE"


def test_contextual_evaluation_is_idempotent_bounded_and_advisory() -> None:
    arguments = {
        "lessons": [{"lesson_id": "day"}],
        "truths": [_truth("day")],
        "target_contexts": [_target("day")],
        "max_rows": 1,
    }
    first = build_lesson_contextual_applicability_v1(**arguments)
    second = build_lesson_contextual_applicability_v1(**arguments)
    assert first["resolutions"] == second["resolutions"]
    assert first["full_history_scan_count"] == 0
    assert first["provider_calls_used"] == first["broker_calls_used"] == first["llm_calls_used"] == 0
