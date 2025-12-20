# Astra Performance System — performance_logger.py
"""
Astra Intelligence — Performance Logger
---------------------------------------
Logs every Astra prediction, trade, and evaluation result.
This module writes lightweight JSON logs to /state/performance_state.json.
"""

import os, json, time, uuid

class PerformanceLogger:
    def __init__(self, path="state/performance_state.json"):
        self.path = path
        self.data = self._load()

    # ---------- internal ----------
    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r") as f:
                try:
                    return json.load(f)
            data["history"] = data["history"][-1000:]
                except json.JSONDecodeError:
                    pass
        return {"predictions": {}, "history": []}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    # ---------- public ----------
    def log_prediction(self, packet):
        """
        packet = {
            'ticker': str,
            'direction': 'BUY' | 'SELL',
            'confidence': float,
            'price': float,
            'horizon': str,
            'agent_scores': dict
        }
        """
        pid = str(uuid.uuid4())
        packet.update({
            "timestamp": time.time(),
            "status": "OPEN",
            "id": pid
        })
        self.data["predictions"][pid] = packet
        self._save()
        return pid

    def close_prediction(self, pid, outcome):
        """
        outcome = {'exit_price': float, 'return_pct': float, 'correct': int}
        """
        pred = self.data["predictions"].pop(pid, None)
        if pred:
            pred.update(outcome)
            pred["status"] = "CLOSED"
            self.data["history"].append(pred)
            self._save()

    def get_summary(self):
        return {
            "open": len(self.data["predictions"]),
            "closed": len(self.data["history"])
        }
