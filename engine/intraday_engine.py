from __future__ import annotations


class IntradaySignalEngine:
    def __init__(self, *args, **kwargs):
        pass

    def get_ranked_intraday_signals(self, symbols):
        return [{"symbol": str(s).upper(), "intraday_score": 0.0} for s in (symbols or []) if str(s).strip()]

