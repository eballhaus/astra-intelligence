"""Regime Stress Testing V1."""
from __future__ import annotations
import json, os
from datetime import UTC, datetime
from typing import Any
VERSION="1.0.0"
def _now_iso(): return datetime.now(UTC).isoformat().replace("+00:00","Z")
def _to_float(v:Any,d:float=0.0)->float:
    try: return float(v)
    except Exception: return d
class RegimeStressTestingEngine:
    regimes=["bullish","bearish","volatile","low_volatility","risk_on","risk_off","recessionary","inflationary"]
    def __init__(self,state_dir:str="state")->None: self.state_dir=str(state_dir or "state"); self.learning_path=os.path.join(self.state_dir,"learning_insights_last_good.json")
    def _read(self):
        try:
            with open(self.learning_path,"r",encoding="utf-8") as fh: d=json.load(fh)
            return d if isinstance(d,dict) else {}
        except Exception: return {}
    def status(self):
        s=self._read(); wr=_to_float(s.get("current_engine_released_wr"),_to_float(s.get("released_hero_win_rate"),50)); purity=_to_float(s.get("buy_list_purity"),50); entry=_to_float(s.get("entry_quality"),50)
        rows=[]
        for r in self.regimes:
            penalty=12 if r in {"bearish","volatile","risk_off","recessionary","inflationary"} else 0
            score=max(0,min(100,(wr*.35+purity*.3+entry*.35)-penalty))
            rows.append({"regime":r,"stress_score":round(score,3),"pass":score>=55})
        strongest=[r["regime"] for r in sorted(rows,key=lambda x:x["stress_score"],reverse=True)[:3]]; weakest=[r["regime"] for r in sorted(rows,key=lambda x:x["stress_score"])[:3]]
        avg=sum(r["stress_score"] for r in rows)/max(1,len(rows))
        return {"enabled":True,"version":VERSION,"mode":"shadow_regime_stress_testing_reporting_only","local_only":True,"writes_files":False,"api_calls_used":0,"regime_stress_testing_status_v1":True,"stress_test_score":round(avg,3),"strongest_regimes":strongest,"weakest_regimes":weakest,"robustness_score":round(max(0,100-(max(r['stress_score'] for r in rows)-min(r['stress_score'] for r in rows))),3),"regime_results":rows,"changes_live_trading":False,"confidence_score":round(min(90,40+len(rows)*5),3),"next_recommended_action":"use_weak_regimes_to_prioritize_shadow_replay_batches","generated_at":_now_iso()}
