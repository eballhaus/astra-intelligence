"""Parallel Replay Orchestrator V1 - planning only, no worker loop."""
from __future__ import annotations
import math
from datetime import UTC, datetime
from typing import Any
VERSION="1.0.0"
def _now_iso(): return datetime.now(UTC).isoformat().replace("+00:00","Z")
def _to_int(v:Any,d:int=0)->int:
    try: return int(float(v))
    except Exception: return d
class ParallelReplayOrchestrator:
    def __init__(self,state_dir:str="state",replay_farm:Any=None,consensus_replay:Any=None)->None:
        self.state_dir=str(state_dir or "state"); self.replay_farm=replay_farm; self.consensus_replay=consensus_replay; self.max_parallel_workers_default=2; self.max_parallel_workers_hard_cap=4; self.cpu_safety_limit_pct=70; self.memory_safety_limit_pct=70; self.batch_size=250
    def status(self):
        farm={}; consensus={}
        try: farm=self.replay_farm.status() if self.replay_farm else {}
        except Exception: farm={}
        try: consensus=self.consensus_replay.status() if self.consensus_replay else {}
        except Exception: consensus={}
        scenarios=_to_int(farm.get("replay_scenarios_planned"),0); batches=math.ceil(scenarios/max(1,self.batch_size)) if scenarios else 0
        rec_workers=min(self.max_parallel_workers_default,self.max_parallel_workers_hard_cap,max(1,batches)) if batches else 1
        speedup=round(min(float(rec_workers)*0.82,float(self.max_parallel_workers_hard_cap)),3)
        return {"enabled":True,"version":VERSION,"mode":"parallel_replay_orchestration_planning_only","local_only":True,"writes_files":False,"api_calls_used":0,"parallel_replay_orchestrator_status_v1":True,"parallel_execution_enabled":False,"parallel_execution_planned":True,"uncontrolled_background_loop_enabled":False,"parallel_batches_planned":int(batches),"batch_size":self.batch_size,"max_parallel_workers":self.max_parallel_workers_hard_cap,"recommended_parallel_workers":rec_workers,"estimated_wall_clock_speedup":speedup,"cpu_safety_limit_pct":self.cpu_safety_limit_pct,"memory_safety_limit_pct":self.memory_safety_limit_pct,"falls_back_to_sequential":True,"blocks_hot_paths":False,"protected_hot_paths":["/api/rankings","/api/top_buys","/api/health","dashboard_loading"],"consensus_replays_processed":_to_int(consensus.get("consensus_replays_processed"),0),"confidence_score":85.0,"changes_live_trading":False,"next_recommended_action":"keep_parallel_replay_planned_until_operator_starts_safe_shadow_batch","generated_at":_now_iso()}
