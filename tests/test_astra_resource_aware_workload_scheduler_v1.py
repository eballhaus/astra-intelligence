from engine.astra_resource_aware_workload_scheduler_v1 import (
    build_resource_aware_workload_plan,
    claim_background_slot,
    release_background_slot,
)


def _state(**overrides):
    state = {
        "resource_state": "RESOURCE_NORMAL",
        "market_hours_mode": "OVERNIGHT_IDLE",
        "resource": {
            "resource_state": "RESOURCE_NORMAL",
            "worker_process": {"cpu_percent": 10, "memory_mb": 700},
            "resource_memory_telemetry_v1": {"rss_growth_mb_per_hour": 0, "background_work_suspended": False},
        },
        "cycle_timing_v1": {"latest": {"total_seconds": 5}},
    }
    state.update(overrides)
    return state


def test_normal_market_reserves_foreground_capacity():
    plan = build_resource_aware_workload_plan(_state(market_hours_mode="REGULAR_MARKET"), cpu_count=6)
    assert plan["mode"] == "NORMAL_MARKET"
    assert plan["max_background_workers"] == 1
    assert plan["workload_limits"]["HISTORICAL_ACQUISITION"] == 1


def test_overnight_scales_only_after_sustained_headroom():
    state = _state()
    first = build_resource_aware_workload_plan(state, cpu_count=6)
    assert first["max_background_workers"] == 1
    second = build_resource_aware_workload_plan(state, previous=first, cpu_count=6)
    third = build_resource_aware_workload_plan(state, previous=second, cpu_count=6)
    assert third["max_background_workers"] == 3
    assert third["healthy_samples"] == 3


def test_pressure_scales_down_and_blocks_background_work():
    plan = build_resource_aware_workload_plan(
        _state(resource_state="RESOURCE_MEMORY_PAUSE", resource={"resource_state": "RESOURCE_MEMORY_PAUSE"}),
        cpu_count=6,
    )
    assert plan["max_background_workers"] == 0
    assert plan["workload_limits"]["HISTORICAL_LEARNING"] == 0
    assert plan["scale_down_immediate"] is True


def test_elevated_pressure_keeps_only_bounded_acquisition_slot():
    plan = build_resource_aware_workload_plan(
        _state(resource_state="RESOURCE_ELEVATED", resource={"resource_state": "RESOURCE_ELEVATED"}),
        cpu_count=6,
    )
    assert plan["max_background_workers"] == 1
    assert plan["background_priority_ceiling"] == "ACQUISITION_ONLY"


def test_scheduler_lease_prevents_duplicate_background_owners(tmp_path):
    plan = build_resource_aware_workload_plan(_state(market_hours_mode="NORMAL_MARKET"), cpu_count=6)
    first = claim_background_slot(tmp_path, "learning", plan)
    second = claim_background_slot(tmp_path, "acquisition", plan)
    assert first["acquired"] is True
    assert second["acquired"] is False
    release_background_slot(tmp_path, "learning")
    third = claim_background_slot(tmp_path, "acquisition", plan)
    assert third["acquired"] is True
    release_background_slot(tmp_path, "acquisition")
