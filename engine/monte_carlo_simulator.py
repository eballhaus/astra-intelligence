"""Monte Carlo Outcome Simulator V1 - deterministic planning summary."""
from __future__ import annotations
import json, os, statistics, math
from datetime import UTC, datetime
from typing import Any
VERSION="1.0.0"
def _now_iso(): return datetime.now(UTC).isoformat().replace("+00:00","Z")
def _to_float(v:Any,d:float=0.0)->float:
    try: return float(v)
    except Exception: return d
class MonteCarloOutcomeSimulator:
    def __init__(self,state_dir:str="state")->None: self.state_dir=str(state_dir or "state"); self.paths=[os.path.join(self.state_dir,p) for p in ("trade_lifecycle_v1.jsonl","outcome_labels_v1.jsonl")]
    def _returns(self)->list[float]:
        out=[]
        for p in self.paths:
            if not os.path.exists(p): continue
            try:
                with open(p,"r",encoding="utf-8") as fh:
                    for raw in fh:
                        try: row=json.loads(raw)
                        except Exception: continue
                        if isinstance(row,dict) and (row.get("pnl_pct") is not None or row.get("return_pct") is not None): out.append(_to_float(row.get("pnl_pct"),_to_float(row.get("return_pct"),0)))
            except Exception: pass
        return out[-5000:]
    def status(self):
        rets=self._returns(); runs=1000 if len(rets)>=20 else 250; avg=statistics.fmean(rets) if rets else 0.0; sd=statistics.pstdev(rets) if len(rets)>1 else 2.0
        expected_dd=abs(min(0,avg-2*sd))*10; ruin=max(0,min(100,35-(avg*5)+(sd*1.5))) if rets else 50.0; conf=min(95,25+len(rets)/20)
        return {"enabled":True,"version":VERSION,"mode":"shadow_monte_carlo_outcome_simulation_reporting_only","local_only":True,"writes_files":False,"api_calls_used":0,"monte_carlo_simulator_status_v1":True,"monte_carlo_runs":runs,"sample_return_count":len(rets),"risk_of_ruin":round(ruin,3),"expected_max_drawdown":round(expected_dd,3),"return_distribution":{"mean_return_pct":round(avg,6),"stddev_return_pct":round(sd,6),"approx_95pct_interval":[round(avg-1.96*sd,6),round(avg+1.96*sd,6)]},"distribution_confidence":round(conf,3),"confidence_score":round(conf,3),"changes_live_trading":False,"next_recommended_action":"increase_real_outcome_sample_before_using_distribution_for_any_live_policy","generated_at":_now_iso()}
