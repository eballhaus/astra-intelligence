"""Idle Replay Worker Planner V1."""
from __future__ import annotations
import os
from datetime import UTC, datetime
VERSION = "1.0.0"
def _now(): return datetime.now(UTC).isoformat().replace("+00:00", "Z")
class IdleReplayWorkerPlanner:
    def __init__(self, state_dir: str = "state") -> None: self.state_dir = str(state_dir or "state")
    def status(self) -> dict:
        files = 0
        for root, _, names in os.walk(self.state_dir):
            files += sum(1 for n in names if n.endswith((".jsonl", ".json")))
            if files > 500: break
        batches = max(1, min(12, files // 8 if files else 1))
        return {"enabled": True, "version": VERSION, "mode": "idle_replay_worker_planning_only", "local_only": True, "writes_files": False, "api_calls_used": 0, "idle_replay_worker_status_v1": True, "idle_replay_batches_planned": batches, "recommended_batch_size": 50, "recommended_worker_count": 1 if batches < 4 else 2, "max_worker_count": 2, "cpu_safety_limit_pct": 65, "memory_safety_limit_pct": 70, "blocks_hot_paths": False, "uses_existing_data_only": True, "uncontrolled_background_loops": False, "confidence_score": min(90, 45 + batches * 3), "live_trading_changed": False, "next_recommended_action": "schedule_shadow_replay_only_when_dashboard_hot_paths_are_idle", "generated_at": _now()}
