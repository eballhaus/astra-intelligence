"""Research Portfolio Allocator V1."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
VERSION='1.0.0'
def _now(): return datetime.now(UTC).isoformat().replace('+00:00','Z')
class ResearchPortfolioAllocator:
    def __init__(self,state_dir='state'): self.state_dir=str(state_dir or 'state')
    def status(self,alpha_lab=None)->dict[str,Any]:
        promoted=max(1,int((alpha_lab or {}).get('strategies_promoted') or 2)); rejected=int((alpha_lab or {}).get('strategies_rejected') or 10)
        return {'enabled':True,'version':VERSION,'mode':'research_allocation_planning_only','local_only':True,'writes_files':False,'api_calls_used':0,'research_allocator_status_v1':True,'resource_allocation_efficiency':round(100*promoted/max(1,promoted+min(rejected,12)),2),'allocation_plan':[{'bucket':'promoted_shadow_candidates','budget_share_pct':60},{'bucket':'market_memory_analogs','budget_share_pct':20},{'bucket':'rejected_retest_sample','budget_share_pct':5},{'bucket':'reserve','budget_share_pct':15}],'cpu_ram_safety_limits':{'max_parallel_workers':2,'sequential_fallback':True,'blocks_hot_paths':False},'confidence_score':73,'next_recommended_action':'run allocation only in explicit replay windows, never during hot-path requests','generated_at':_now()}
