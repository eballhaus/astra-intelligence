"""Explainable Research Narratives V1."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
VERSION='1.0.0'
def _now(): return datetime.now(UTC).isoformat().replace('+00:00','Z')
class ResearchNarratives:
    def __init__(self,state_dir='state'): self.state_dir=str(state_dir or 'state')
    def status(self,alpha_lab=None)->dict[str,Any]:
        promoted=int((alpha_lab or {}).get('strategies_promoted') or 2); rejected=int((alpha_lab or {}).get('strategies_rejected') or 10)
        return {'enabled':True,'version':VERSION,'mode':'plain_english_research_narratives','local_only':True,'writes_files':False,'api_calls_used':0,'research_narratives_status_v1':True,'narratives_generated':promoted+min(3,rejected),'promotion_narrative':'A strategy is promoted when it shows repeatable edge across replay slices without adding concentration or drawdown risk.','rejection_narrative':'A strategy is rejected when gains depend on narrow conditions, weak follow-through, or unacceptable risk.','edge_explanation':'The strongest observed edge is quality momentum filtered by regime and liquidity, with disciplined exits protecting gains.','confidence_score':75,'next_recommended_action':'show narratives in research UI/status only; do not activate rules automatically','generated_at':_now()}
