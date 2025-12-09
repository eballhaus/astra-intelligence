"""Phase 19 — Harmony Score Calculator"""
class HarmonyScoreCalculator:
    def __init__(self): self.score=None
    def compute_score(self,stability_index,empathic_metrics):
        self.score=None if (stability_index is None or empathic_metrics is None) else (stability_index+empathic_metrics)/2
        return self.score
    def report(self): return {"harmony_score":self.score}
