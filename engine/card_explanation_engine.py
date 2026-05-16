"""Plain-English AI Card Explanation Engine V2."""
from __future__ import annotations
import hashlib,json,os,shutil,subprocess,tempfile,time
from datetime import UTC, datetime
from typing import Any
VERSION='2.0.0'
def _now(): return datetime.now(UTC).isoformat().replace('+00:00','Z')
def _clean_words(text,max_words=60):
    words=str(text or '').replace('\n',' ').split()
    return ' '.join(words[:max_words])
class CardExplanationEngine:
    def __init__(self,state_dir='state',timeout_seconds=1.5):
        self.state_dir=str(state_dir or 'state'); self.timeout_seconds=max(0.5,min(2.0,float(timeout_seconds))); self.cache_path=os.path.join(self.state_dir,'snapshots','card_explanations_v2.json'); self._last={'generated':0,'cache_hits':0,'fallbacks':0,'total_time':0.0,'last_error':''}
    def _load(self):
        try:
            with open(self.cache_path,'r',encoding='utf-8') as f: d=json.load(f)
            return d if isinstance(d,dict) else {}
        except Exception: return {}
    def _write(self,d):
        try:
            os.makedirs(os.path.dirname(self.cache_path),exist_ok=True); fd,tmp=tempfile.mkstemp(prefix='.card_expl.',suffix='.tmp',dir=os.path.dirname(self.cache_path))
            with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(d,f,sort_keys=True,separators=(',',':')); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.cache_path); return True
        except Exception:
            return False
    def fingerprint(self,row):
        fields={k:row.get(k) for k in ['symbol','grade','confidence','canonical_final_state','price','stop_loss','why_this_is_a_buy','buy_quality_score','rolling_conviction_10r','profit_prediction_pct'] if isinstance(row,dict)}
        return hashlib.sha256(json.dumps(fields,sort_keys=True,default=str).encode()).hexdigest()[:20]
    def _fallback(self,row):
        sym=str((row or {}).get('symbol') or (row or {}).get('ticker') or 'This stock').upper()
        reason=str((row or {}).get('why_this_is_a_buy') or (row or {}).get('rationale') or (row or {}).get('summary') or 'Astra selected it because the current signal mix is stronger than nearby alternatives.').strip().rstrip('.')
        risk='The main risk is that follow-through fades or the stop level is reached before confirmation improves.'
        return _clean_words(f'{sym} stands out because {reason}. {risk}',60)
    def _ollama(self,row):
        binary=shutil.which('ollama')
        if not binary: return ''
        sym=str(row.get('symbol') or row.get('ticker') or 'symbol')
        prompt=('Write 1-2 plain-English sentences, 25-60 words, for a non-trader. Explain why selected, key opportunity, primary risk. Avoid repeating raw numbers. JSON not needed.\n'+json.dumps({'symbol':sym,'grade':row.get('grade'),'state':row.get('canonical_final_state'),'rationale':row.get('why_this_is_a_buy'),'risk':row.get('stop_loss')},ensure_ascii=True))
        try:
            proc=subprocess.run([binary,'run','llama3.2',prompt],capture_output=True,text=True,timeout=self.timeout_seconds,check=False)
            if proc.returncode==0 and proc.stdout.strip(): return _clean_words(proc.stdout.strip(),60)
            self._last['last_error']=(proc.stderr or proc.stdout or f'ollama_exit_{proc.returncode}')[:160]
        except Exception as exc: self._last['last_error']=str(exc)[:160]
        return ''
    def explain_row(self,row,generate_if_missing=False):
        started=time.time(); cache=self._load(); sym=str((row or {}).get('symbol') or (row or {}).get('ticker') or '').upper(); fp=self.fingerprint(row or {}); key=f'{sym}:{fp}'
        if key in cache:
            self._last['cache_hits']+=1; out=dict(cache[key]); out['cache_hit']=True; return out
        generated_text = self._ollama(row or {}) if generate_if_missing else ''
        text=generated_text or self._fallback(row or {})
        source='ollama_local' if generated_text else 'fallback_or_existing_summary'
        out={'symbol':sym,'fingerprint':fp,'explanation':text,'source':source,'cache_hit':False,'generated_at':_now(),'generation_time_seconds':round(time.time()-started,3),'api_calls_used':0}
        cache[key]=out; self._write(cache); self._last['generated']+=1; self._last['total_time']+=out['generation_time_seconds']; self._last['fallbacks']+=1 if source!='ollama_local' else 0
        return out
    def enrich_rows(self,rows):
        out=[]
        for row in list(rows or [])[:6]:
            if not isinstance(row,dict): continue
            exp=self.explain_row(row,generate_if_missing=False)
            r=dict(row); r['ai_card_explanation_v2']=exp.get('explanation'); r['ai_card_explanation_source']=exp.get('source'); r['ai_card_explanation_cache_hit']=exp.get('cache_hit'); r['ai_card_explanation_generation_time_seconds']=exp.get('generation_time_seconds'); out.append(r)
        return out
    def status(self):
        cache=self._load(); total=max(1,self._last['generated']); avg=self._last['total_time']/total
        return {'enabled':True,'version':VERSION,'mode':'local_ollama_cache_first_shadow_explanations','local_only':True,'writes_files':True,'api_calls_used':0,'card_explanation_status_v1':True,'cached_explanations':len(cache),'cache_hit_count':self._last['cache_hits'],'generated_count':self._last['generated'],'fallback_count':self._last['fallbacks'],'cache_hit_rate':round(100*self._last['cache_hits']/max(1,self._last['cache_hits']+self._last['generated']),2),'average_generation_time_seconds':round(avg,3),'hard_timeout_seconds':self.timeout_seconds,'last_error':self._last['last_error'],'confidence_score':80,'next_recommended_action':'keep explanations cache-first and never block card rendering','generated_at':_now()}
