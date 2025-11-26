"""
Astra Remote Controller – Phase-101
-----------------------------------
Allows Guardian-supervised background operation and
remote control for Astra Intelligence.

Runs background tasks (learning, prediction fusion, etc.)
on a timed schedule or via simple REST API calls.
"""

import os
import sys
import json
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# --- Ensure project root in import path ---
sys.path.append(str(Path(__file__).resolve().parents[2]))
# ---------------------------------------------------

from astra_modules.guardian.guardian_v6 import GuardianV6
from astra_modules.agents.neural_agent import NeuralAgent
from astra_modules.agents.continual_trainer import ContinualTrainer
from astra_modules.agents.prediction_fusion import PredictionFusion


class AstraRemote:
    """Runs background learning and prediction services."""
    def __init__(self, base_path=None, port=8089):
        self.base_path = base_path or os.getcwd()
        self.guardian = GuardianV6(self.base_path)
        self.trainer = ContinualTrainer(base_path=self.base_path)
        self.fusion = PredictionFusion(base_path=self.base_path)
        self.port = port
        self.stop_event = threading.Event()
        self.guardian._write_log("🌐 Astra Remote Controller initialized.")

    # ----------------------------------------------------------------
    # Background continual learning loop
    # ----------------------------------------------------------------
    def start_learning_loop(self, interval=3600):
        """Runs continual learning cycle in background every 'interval' seconds."""
        def loop():
            while not self.stop_event.is_set():
                self.guardian.safe_run(lambda: self.trainer.step(iterations=5))
                time.sleep(interval)
        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        self.guardian._write_log(f"🧠 Background learning loop started (interval={interval}s).")

    # ----------------------------------------------------------------
    # REST API Handler
    # ----------------------------------------------------------------
    def start_server(self):
        """Launches a minimal REST API for remote commands."""
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, data, status=200):
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))

            def do_GET(self):
                if self.path == "/status":
                    self._send({"status": "ok", "phase": "101", "message": "Astra Remote Active"})
                elif self.path == "/predict":
                    import torch
                    x = torch.randn(5, 32)
                    y = controller.fusion.predict(x).tolist()
                    self._send({"predictions": y})
                elif self.path == "/train":
                    controller.guardian.safe_run(lambda: controller.trainer.step(iterations=5))
                    self._send({"status": "training cycle completed"})
                else:
                    self._send({"error": "unknown endpoint"}, status=404)

        server = HTTPServer(("0.0.0.0", self.port), Handler)
        self.guardian._write_log(f"🚀 Astra Remote API active at http://localhost:{self.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        server.server_close()
        self.guardian._write_log("🛑 Astra Remote API stopped.")

    # ----------------------------------------------------------------
    # Shutdown
    # ----------------------------------------------------------------
    def stop(self):
        self.stop_event.set()
        self.guardian._write_log("🧩 Astra Remote Controller stopped.")


# --------------------------------------------------------------------
# Direct execution
# --------------------------------------------------------------------
if __name__ == "__main__":
    ar = AstraRemote()
    ar.start_learning_loop(interval=10)  # small interval for demo
    ar.start_server()

