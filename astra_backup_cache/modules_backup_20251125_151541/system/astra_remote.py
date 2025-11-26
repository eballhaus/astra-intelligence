"""
Astra Remote Controller – Phase-101
-----------------------------------
Guardian-supervised background operation and remote control
for Astra Intelligence. Supports continual learning,
prediction fusion, and REST API access.
"""

import os
import sys
import json
import time
import torch
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# --- Ensure root path for imports ---
sys.path.append(str(Path(__file__).resolve().parents[2]))
# -------------------------------------------------------------

from astra_modules.guardian.guardian_v6 import GuardianV6
from astra_modules.agents.neural_agent import NeuralAgent
from astra_modules.agents.continual_trainer import ContinualTrainer
from astra_modules.agents.prediction_fusion import PredictionFusion


class AstraRemote:
    """Runs Guardian-supervised background training and API service."""

    def __init__(self, base_path=None, port=8089):
        self.base_path = base_path or os.getcwd()
        self.guardian = GuardianV6(self.base_path)
        self.trainer = ContinualTrainer(base_path=self.base_path)
        self.fusion = PredictionFusion(base_path=self.base_path)
        self.port = port
        self.stop_event = threading.Event()

        self.guardian._write_log("🌐 Astra Remote Controller initialized (Phase-101).")

    # ----------------------------------------------------------------
    # Safe background continual learning
    # ----------------------------------------------------------------
    def _safe_train_cycle(self):
        """Ensures replay buffer has valid data before training."""
        try:
            if self.trainer.buffer.size() == 0:
                self.guardian._write_log("⚠️ ReplayBuffer empty – skipping training cycle.")
                return
            self.trainer.step(iterations=5)
            self.guardian._write_log("✅ Background training cycle completed.")
        except Exception as e:
            self.guardian._write_log(f"⚠️ Training cycle skipped due to error: {e}")

    def start_learning_loop(self, interval=3600):
        """Runs continual learning in background every 'interval' seconds."""
        def loop():
            while not self.stop_event.is_set():
                self.guardian.safe_run(self._safe_train_cycle)
                time.sleep(interval)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        self.guardian._write_log(f"🧠 Background learning loop started (interval={interval}s).")

    # ----------------------------------------------------------------
    # REST API Service
    # ----------------------------------------------------------------
    def start_server(self):
        """Launches minimal REST API for remote Astra control."""
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, data, status=200):
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode('utf-8'))
                except Exception as e:
                    controller.guardian._write_log(f"⚠️ Failed to send response: {e}")

            def do_GET(self):
                try:
                    if self.path == "/status":
                        data = {
                            "status": "ok",
                            "phase": "101",
                            "message": "Astra Remote Active",
                            "replay_buffer": controller.trainer.buffer.size(),
                        }
                        self._send(data)
                    elif self.path == "/predict":
                        x = torch.randn(5, 32)
                        y = controller.fusion.predict(x).tolist()
                        self._send({"predictions": y})
                    elif self.path == "/train":
                        controller.guardian.safe_run(controller._safe_train_cycle)
                        self._send({"status": "training cycle completed"})
                    else:
                        self._send({"error": "unknown endpoint"}, status=404)
                except Exception as e:
                    controller.guardian._write_log(f"⚠️ API error: {e}")
                    self._send({"error": str(e)}, status=500)

        server = HTTPServer(("0.0.0.0", self.port), Handler)
        self.guardian._write_log(f"🚀 Astra Remote API active at http://localhost:{self.port}")

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            self.guardian._write_log(f"⚠️ Server error: {e}")
        finally:
            server.server_close()
            self.guardian._write_log("🛑 Astra Remote API stopped.")

    # ----------------------------------------------------------------
    # Graceful shutdown
    # ----------------------------------------------------------------
    def stop(self):
        self.stop_event.set()
        self.guardian._write_log("🧩 Astra Remote Controller stopped.")
        print("🧩 Astra Remote Controller stopped.")


# --------------------------------------------------------------------
# Direct Execution
# --------------------------------------------------------------------
if __name__ == "__main__":
    ar = AstraRemote()
    ar.start_learning_loop(interval=10)  # short interval for test/demo
    ar.start_server()

