from __future__ import annotations

import json

from engine.astra_intelligence_effectiveness_learning_velocity_v1 import (
    AstraIntelligenceEffectivenessLearningVelocityV1,
    build_canonical_lesson_outcome_linkage_v1,
    build_lesson_mistake_recurrence_v1,
    build_truth_progression_v1,
)
from engine.self_correction_controller import SelfCorrectionController


def _truth(
    truth_id: str,
    candidate_id: str,
    value: float,
    timestamp: str,
    *,
    lane: str = "DAY",
    evidence_class: str = "BROKER_CONFIRMED_COMPLETE",
) -> dict:
    return {
        "broker_truth_id": truth_id,
        "candidate_id": candidate_id,
        "lifecycle_id": f"life-{candidate_id}",
        "evidence_class": evidence_class,
        "entry_price": 100.0,
        "exit_price": 100.0 + value,
        "return_pct": value,
        "exit_timestamp": timestamp,
        "lane": lane,
    }


def _application(lesson_id: str, candidate_id: str, timestamp: str, **extra: object) -> dict:
    return {
        "lesson_id": lesson_id,
        "candidate_id": candidate_id,
        "lesson_application_state": "LESSON_APPLIED",
        "applied_at": timestamp,
        "lane_id": "DAY",
        "decision_owner": "PaperAutopilot._evaluate_exit",
        "decision_type": "EXIT",
        "influenced_fields": ["exit_decision"],
        "lesson_consumed": True,
        **extra,
    }


def test_lesson_exists_or_retrieved_without_application_gets_no_effectiveness_credit() -> None:
    result = build_canonical_lesson_outcome_linkage_v1(
        lessons=[{"lesson_id": "lesson-1"}],
        truths=[_truth("truth-1", "candidate-1", 2.0, "2026-08-20T12:00:00Z")],
        application_events=[{"lesson_id": "lesson-1", "candidate_id": "candidate-1", "lesson_application_state": "LESSON_RETRIEVED"}],
    )
    lesson = result["lessons"][0]
    assert result["linked_outcomes"] == 0
    assert lesson["availability"] == "LESSON_RETRIEVED"
    assert lesson["evidence_status"] == "NOT_APPLIED"


def test_applied_lesson_links_later_canonical_truth_and_marks_improvement() -> None:
    result = build_canonical_lesson_outcome_linkage_v1(
        lessons=[{"lesson_id": "lesson-1"}],
        truths=[_truth("truth-1", "candidate-1", 2.0, "2026-08-20T12:00:00Z")],
        application_events=[_application("lesson-1", "candidate-1", "2026-08-20T11:00:00Z", baseline_return_pct=1.0)],
    )
    lesson = result["lessons"][0]
    assert result["linked_outcomes"] == 1
    assert lesson["canonical_outcomes"] == 1
    assert lesson["improved_outcomes"] == 1
    assert lesson["evidence_status"] == "PROMISING"


def test_worsened_canonical_outcome_is_not_hidden() -> None:
    result = build_canonical_lesson_outcome_linkage_v1(
        lessons=[{"lesson_id": "lesson-1"}],
        truths=[_truth("truth-1", "candidate-1", -2.0, "2026-08-20T12:00:00Z")],
        application_events=[_application("lesson-1", "candidate-1", "2026-08-20T11:00:00Z", baseline_return_pct=1.0)],
    )
    assert result["lessons"][0]["worsened_outcomes"] == 1


def test_replay_evidence_never_becomes_broker_confirmed_effectiveness() -> None:
    result = build_canonical_lesson_outcome_linkage_v1(
        lessons=[{"lesson_id": "lesson-1"}],
        truths=[_truth("replay-1", "candidate-1", 10.0, "2026-08-20T12:00:00Z", evidence_class="REPLAY")],
        application_events=[_application("lesson-1", "candidate-1", "2026-08-20T11:00:00Z")],
    )
    assert result["linked_outcomes"] == 0
    assert result["lessons"][0]["evidence_status"] == "INSUFFICIENT_CANONICAL_EVIDENCE"


def test_linkage_is_idempotent_for_repeated_application_events() -> None:
    app = _application("lesson-1", "candidate-1", "2026-08-20T11:00:00Z")
    result = build_canonical_lesson_outcome_linkage_v1(
        lessons=[{"lesson_id": "lesson-1"}],
        truths=[_truth("truth-1", "candidate-1", 2.0, "2026-08-20T12:00:00Z")],
        application_events=[app, app],
    )
    assert result["linked_outcomes"] == 1


def test_unattributed_application_is_not_credited_or_linked() -> None:
    event = _application("lesson-1", "candidate-1", "2026-08-20T11:00:00Z")
    event.pop("decision_owner")
    result = build_canonical_lesson_outcome_linkage_v1(
        lessons=[{"lesson_id": "lesson-1"}],
        truths=[_truth("truth-1", "candidate-1", 2.0, "2026-08-20T12:00:00Z")],
        application_events=[event],
    )
    assert result["explicit_application_events"] == 0
    assert result["invalid_application_events"] == 1
    assert result["invalid_application_reasons"] == {"MISSING_DECISION_OWNER": 1}
    assert result["linked_outcomes"] == 0


def test_truth_progression_is_chronological_and_lane_isolated() -> None:
    truths = [
        _truth("t1", "c1", -2.0, "2026-08-01T12:00:00Z"),
        _truth("t2", "c2", -1.0, "2026-08-02T12:00:00Z"),
        _truth("t3", "c3", 0.0, "2026-08-03T12:00:00Z"),
        _truth("t4", "c4", 0.5, "2026-08-04T12:00:00Z"),
        _truth("t5", "c5", 1.0, "2026-08-05T12:00:00Z"),
        _truth("t6", "c6", 2.0, "2026-08-06T12:00:00Z"),
    ]
    result = build_truth_progression_v1(truths)
    assert result["overall"]["status"] == "IMPROVING"
    assert result["by_lane"]["SCALP"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["by_lane"]["CRYPTO"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_multi_metric_progression_is_reported_without_overriding_canonical_status() -> None:
    truths = [
        _truth("t1", "c1", -3.0, "2026-08-01T12:00:00Z"),
        _truth("t2", "c2", -0.2, "2026-08-02T12:00:00Z"),
        _truth("t3", "c3", 0.5, "2026-08-03T12:00:00Z"),
        _truth("t4", "c4", -1.0, "2026-08-04T12:00:00Z"),
        _truth("t5", "c5", -0.5, "2026-08-05T12:00:00Z"),
        _truth("t6", "c6", 0.0, "2026-08-06T12:00:00Z"),
        _truth("t7", "c7", -0.9, "2026-08-07T12:00:00Z"),
        _truth("t8", "c8", -0.21, "2026-08-08T12:00:00Z"),
        _truth("t9", "c9", 1.0, "2026-08-09T12:00:00Z"),
    ]
    result = build_truth_progression_v1(truths)
    overall = result["overall"]
    assert overall["status"] == "DETERIORATING"
    assert overall["economic_multi_metric_trend"]["status"] == "IMPROVING_BUT_NOT_PROFITABLE"


def test_return_integrity_outlier_does_not_change_official_progression() -> None:
    truths = [
        _truth("t1", "c1", -1.0, "2026-08-01T12:00:00Z"),
        _truth("t2", "c2", -0.5, "2026-08-02T12:00:00Z"),
        _truth("t3", "c3", 0.0, "2026-08-03T12:00:00Z"),
        _truth("t4", "c4", 0.5, "2026-08-04T12:00:00Z"),
        _truth("t5", "c5", 1.0, "2026-08-05T12:00:00Z"),
        _truth("t6", "c6", 2.0, "2026-08-06T12:00:00Z"),
        _truth("outlier", "c7", 2001.0, "2026-08-07T12:00:00Z"),
    ]
    result = build_truth_progression_v1(truths)
    assert result["overall"]["truth_count"] == 6
    assert result["overall"]["return_integrity"]["outlier_count"] == 1


def test_recurrence_requires_prior_lesson_application() -> None:
    linkage = build_canonical_lesson_outcome_linkage_v1(
        lessons=[{"lesson_id": "lesson-1"}],
        truths=[_truth("truth-1", "candidate-1", -1.0, "2026-08-20T12:00:00Z")],
        application_events=[_application("lesson-1", "candidate-1", "2026-08-20T11:00:00Z")],
    )
    result = build_lesson_mistake_recurrence_v1(
        [
            {"pattern_id": "p1", "lesson_id": "lesson-1", "candidate_id": "candidate-1", "recurrence": True},
            {"pattern_id": "p2", "lesson_id": "lesson-2", "candidate_id": "candidate-2", "recurrence": True},
        ],
        linkage,
    )
    assert result["records"][0]["classification"] == "RECURRENCE_AFTER_LESSON"
    assert result["records"][1]["classification"] == "LESSON_CREATED_NOT_YET_APPLIED"


def test_self_correction_consumes_shared_recurrence_contract(tmp_path) -> None:
    controller = SelfCorrectionController(state_dir=str(tmp_path))
    result = controller.lesson_recurrence_summary(recurrence_events=[], lesson_outcome_linkage={"links": []})
    assert result["owner"] == "self_correction_controller"
    assert result["full_history_scan_count"] == 0


def test_module_uses_bounded_sources_and_does_not_turn_advisory_attachment_into_application(tmp_path) -> None:
    (tmp_path / "candidate_decision_ledger_v1.jsonl").write_text(
        json.dumps({"canonical_lesson_ids": ["lesson-1"], "candidate_id": "candidate-1", "timestamp_utc": "2026-08-20T11:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "canonical_lifecycle_lessons_v1.jsonl").write_text(json.dumps({"lesson_id": "lesson-1"}) + "\n", encoding="utf-8")
    (tmp_path / "broker_truth_records_v1.json").write_text(json.dumps({"records": [_truth("truth-1", "candidate-1", 2.0, "2026-08-20T12:00:00Z")]}), encoding="utf-8")
    payload = AstraIntelligenceEffectivenessLearningVelocityV1(state_dir=str(tmp_path), ttl_seconds=0).status(force=True)
    linkage = payload["canonical_lesson_outcome_linkage_v1"]
    assert linkage["retrieval_only_events"] == 1
    assert linkage["linked_outcomes"] == 0
    assert payload["bounded_processing"]["full_history_scan_count"] == 0
    assert payload["provider_calls_used"] == payload["broker_calls_used"] == payload["llm_calls_used"] == 0


def test_module_links_valid_persisted_candidate_application_to_exact_truth(tmp_path) -> None:
    application = _application("lesson-1", "candidate-1", "2026-08-20T11:00:00Z")
    row = {
        "candidate_id": "candidate-1",
        "lifecycle_id": "life-candidate-1",
        "lane_id": "DAY",
        "timestamp_utc": "2026-08-20T11:00:00Z",
        "lesson_application_evidence_v1": application,
    }
    (tmp_path / "candidate_decision_ledger_v1.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    (tmp_path / "canonical_lifecycle_lessons_v1.jsonl").write_text(json.dumps({"lesson_id": "lesson-1", "lane_id": "DAY"}) + "\n", encoding="utf-8")
    (tmp_path / "broker_truth_records_v1.json").write_text(json.dumps({"records": [_truth("truth-1", "candidate-1", 2.0, "2026-08-20T12:00:00Z")]}), encoding="utf-8")

    payload = AstraIntelligenceEffectivenessLearningVelocityV1(state_dir=str(tmp_path), ttl_seconds=0).status(force=True)
    linkage = payload["canonical_lesson_outcome_linkage_v1"]
    assert linkage["explicit_application_events"] == 1
    assert linkage["linked_outcomes"] == 1
    assert linkage["links"][0]["lifecycle_id"] == "life-candidate-1"


def test_linkage_honors_maximum_bounded_input_rows() -> None:
    truths = [_truth(f"t{i}", f"c{i}", 1.0, f"2026-08-{i + 1:02d}T12:00:00Z") for i in range(5)]
    result = build_canonical_lesson_outcome_linkage_v1(lessons=[], truths=truths, application_events=[], max_rows=2)
    assert result["canonical_truths_examined"] == 2
    assert result["full_history_scan_count"] == 0
