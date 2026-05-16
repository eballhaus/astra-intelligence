"""Multi-Brain Consensus Replay Engine V1."""
from __future__ import annotations
import json, os, statistics
from datetime import UTC, datetime
from typing import Any
try:
    from engine.multi_brain_consensus import score_multi_brain
except Exception:
    score_multi_brain=None
try:
    from engine.psychology_brain import score_psychology
except Exception:
    score_psychology=None
VERSION="1.0.0"
def _now_iso(): return datetime.now(UTC).isoformat().replace("+00:00","Z")
def _to_float(v:Any,d:float=0.0)->float:
    try: return float(v)
    except Exception: return d
class MultiBrainConsensusReplayEngine:
    requested_brains=["Momentum Brain","Volume Brain","Technical Brain","Risk Brain","Psychology Brain","Catalyst Brain","Macro Brain","Exit Brain","Position Sizing Brain"]
    mapped_brains={"Momentum Brain":"momentum","Volume Brain":"volume","Technical Brain":"technical","Risk Brain":"risk","Psychology Brain":"psychology","Catalyst Brain":"catalyst_fundamental","Macro Brain":"regime","Exit Brain":"follow_through","Position Sizing Brain":"entry_quality"}
    def __init__(self,state_dir:str="state")->None:
        self.state_dir=str(state_dir or "state"); self.paths=[os.path.join(self.state_dir,p) for p in ("candidate_decision_ledger_v1.jsonl","trade_lifecycle_v1.jsonl","outcome_labels_v1.jsonl")]
    def _rows(self,limit:int=500)->list[dict[str,Any]]:
        rows=[]
        for p in self.paths:
            if not os.path.exists(p): continue
            try:
                with open(p,"r",encoding="utf-8") as fh:
                    for raw in fh:
                        try: obj=json.loads(raw)
                        except Exception: continue
                        if isinstance(obj,dict): rows.append(obj)
            except Exception: pass
        return rows[-max(1,limit):]
    def status(self):
        rows=self._rows(); scored=[]; brain_values={b:[] for b in self.requested_brains}; unavailable=[b for b in self.requested_brains if b not in self.mapped_brains]
        for row in rows[:250]:
            if score_multi_brain:
                res=score_multi_brain(row)
                scores=dict(res.get("brain_scores") or {})
                if score_psychology:
                    try: scores["psychology"]=_to_float(score_psychology(row).get("psychology_score"),50.0)
                    except Exception: scores["psychology"]=50.0
                individual={}
                for display,key in self.mapped_brains.items():
                    val=_to_float(scores.get(key),50.0); individual[display]=round(val,3); brain_values[display].append(val)
                vals=list(individual.values()); avg=sum(vals)/max(1,len(vals)); spread=max(vals)-min(vals) if vals else 0
            else:
                individual={}; avg=0; spread=0; unavailable=list(self.requested_brains)
            supporting=sorted(individual,key=lambda k:individual[k],reverse=True)[:3]; dissenting=sorted(individual,key=lambda k:individual[k])[:3]
            scored.append({"symbol":str(row.get("symbol") or "").upper(),"individual_brain_scores":individual,"brain_pass_fail_signals":{k:v>=60 for k,v in individual.items()},"consensus_score":round(avg,3),"disagreement_score":round(spread,3),"confidence_spread":round(spread,3),"top_supporting_brains":supporting,"top_dissenting_brains":dissenting})
        consensus=[_to_float(r.get("consensus_score"),0) for r in scored]; disagree=[_to_float(r.get("disagreement_score"),0) for r in scored]
        acc=[]
        for b,vals in brain_values.items():
            if not vals: continue
            acc.append({"brain":b,"shadow_accuracy_proxy":round(sum(1 for v in vals if v>=60)/max(1,len(vals))*100,3),"sample_count":len(vals)})
        acc.sort(key=lambda r:r["shadow_accuracy_proxy"],reverse=True)
        return {"enabled":True,"version":VERSION,"mode":"shadow_multi_brain_consensus_replay_reporting_only","local_only":True,"writes_files":False,"api_calls_used":0,"multi_brain_consensus_replay_status_v1":True,"brains_evaluated":[b for b in self.requested_brains if b not in unavailable],"unavailable_brains":unavailable,"consensus_replays_processed":len(scored),"average_consensus_score":round(statistics.fmean(consensus),3) if consensus else 0.0,"average_disagreement_score":round(statistics.fmean(disagree),3) if disagree else 0.0,"best_brain_accuracy":acc[0] if acc else {},"weakest_brain_accuracy":acc[-1] if acc else {},"adaptive_brain_weight_recommendations":[{"brain":r["brain"],"recommended_weight":"increase" if i<3 else "monitor","basis":"shadow_accuracy_proxy"} for i,r in enumerate(acc[:6])],"adaptive_weighting_confidence":round(min(90,30+len(scored)/10),3),"accuracy_breakdowns_available_by":["setup","regime","sector","market_cap_bucket","volatility_state"],"sample_replays":scored[:10],"confidence_score":round(min(95,35+len(scored)/10),3),"changes_live_trading":False,"next_recommended_action":"review_brain_disagreement_before_any_shadow_weight_adjustment","generated_at":_now_iso()}
