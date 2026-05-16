"""Historical Replay Farm V1 - local-only replay planning."""
from __future__ import annotations
import json, os
from datetime import UTC, datetime
from typing import Any
VERSION="1.0.0"
def _now_iso(): return datetime.now(UTC).isoformat().replace("+00:00","Z")
def _to_int(v:Any,d:int=0)->int:
    try: return int(float(v))
    except Exception: return d
class HistoricalReplayFarm:
    variants={"entry_timings":5,"stop_loss_variants":4,"trailing_stop_variants":4,"hold_time_variants":5,"partial_profit_variants":3,"position_sizing_variants":4}
    def __init__(self,state_dir:str="state")->None:
        self.state_dir=str(state_dir or "state"); self.paths=[os.path.join(self.state_dir,p) for p in ("trade_lifecycle_v1.jsonl","outcome_labels_v1.jsonl","candidate_decision_ledger_v1.jsonl")]; self.replay_path=os.path.join(self.state_dir,"replay_results_v2.json")
    def _count_jsonl(self,path:str,limit:int=50000)->int:
        if not os.path.exists(path): return 0
        c=0
        try:
            with open(path,"r",encoding="utf-8") as fh:
                for c,_ in enumerate(fh,1):
                    if c>=limit: break
        except Exception: return 0
        return c
    def _read_json(self,path:str)->dict[str,Any]:
        try:
            with open(path,"r",encoding="utf-8") as fh: data=json.load(fh)
            return data if isinstance(data,dict) else {}
        except Exception: return {}
    def status(self)->dict[str,Any]:
        base=sum(self._count_jsonl(p) for p in self.paths); replay=self._read_json(self.replay_path)
        base=max(base,_to_int(replay.get("source_row_count")),_to_int(replay.get("rows_evaluated")),_to_int(replay.get("sample_count")))
        combo=1
        for v in self.variants.values(): combo*=v
        scenarios=min(250000,max(0,base*combo))
        return {"enabled":True,"version":VERSION,"mode":"shadow_replay_farm_planning_only","local_only":True,"writes_files":False,"api_calls_used":0,"historical_replay_farm_status_v1":True,"uses_existing_stored_data_only":True,"replay_scenarios_planned":int(scenarios),"estimated_trade_experiences_generated":int(scenarios),"base_rows_available":int(base),"variant_families":self.variants,"changes_live_trading":False,"confidence_score":round(min(95.0,30.0+base/200.0),3),"next_recommended_action":"run_replay_batches_only_when_explicitly_enabled_and_hot_paths_are_idle","generated_at":_now_iso()}
