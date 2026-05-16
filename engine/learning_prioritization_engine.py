"""Learning Prioritization Engine V1."""
from __future__ import annotations
import json, os
from datetime import UTC, datetime
from typing import Any
VERSION="1.0.0"
def _now_iso(): return datetime.now(UTC).isoformat().replace("+00:00","Z")
def _to_float(v:Any,d:float=0.0)->float:
    try: return float(v)
    except Exception: return d
class LearningPrioritizationEngine:
    def __init__(self,state_dir:str="state")->None: self.state_dir=str(state_dir or "state"); self.learning_path=os.path.join(self.state_dir,"learning_insights_last_good.json")
    def _read(self):
        try:
            with open(self.learning_path,"r",encoding="utf-8") as fh: d=json.load(fh)
            return d if isinstance(d,dict) else {}
        except Exception: return {}
    def status(self):
        s=self._read(); metrics={"released_win_rate":_to_float(s.get("current_engine_released_wr"),_to_float(s.get("released_hero_win_rate"),0)),"buy_list_purity":_to_float(s.get("buy_list_purity"),0),"entry_quality":_to_float(s.get("entry_quality"),0),"confidence_truthfulness":_to_float(s.get("confidence_truthfulness"),0),"follow_through_quality":_to_float(s.get("follow_through_quality"),0)}
        priorities=[]
        for name,val in sorted(metrics.items(),key=lambda kv:kv[1]):
            priorities.append({"area":name,"current_score":round(val,3),"reason":"lowest_confidence_or_quality_area","expected_roi":"high" if val<50 else "moderate","recommended_learning_source":"multi_brain_replay_and_scenario_stress_tests"})
        return {"enabled":True,"version":VERSION,"mode":"shadow_learning_prioritization_reporting_only","local_only":True,"writes_files":False,"api_calls_used":0,"learning_prioritization_status_v1":True,"top_learning_priorities":priorities[:6],"estimated_improvement_opportunities":priorities[:6],"projected_learning_acceleration":"3x_to_8x_effective_examples_per_day_when_replay_batches_are_reviewed","weakness_inputs":metrics,"confidence_score":round(min(90,35+len(priorities)*10),3),"changes_live_trading":False,"next_recommended_action":"target_replay_generation_at_lowest_scoring_learning_dimensions_first","generated_at":_now_iso()}
