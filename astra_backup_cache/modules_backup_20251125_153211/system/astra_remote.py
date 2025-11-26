"""
Astra Remote Controller – Phase-101
-----------------------------------
Handles remote control, status queries, and safe Guardian-wrapped operations.
"""

import os
import sys
import threading
import time
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- Ensure Astra root path is visible ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from astra_modules.guardian.guardian_v6 import GuardianV6
from astra_modules.agents.continual_trainer import ContinualTrainer
from astra_modules.agents.neural_agent import NeuralAgent


class AstraRemote:
    """Remote controller for Astra with Guardian-protected background learning."""

    def __init__(self, base_path: str):
        self.base_path = base_path
        self.guardian = GuardianV6(self.base_path)
        self.guardian._write_log("🌐 Astra Remote Controller initializing...")
        self.agent = NeuralAgent(self.guardian)
        self.trainer = ContinualTrainer(self.guardian, self.agent)
        self._stop_flag = False
        self._background_thread = threading.Thread(target=self._background_learning, daemon=True)
        self._background_thread.start()
        self.guardian._write_log("🌐 Astra Remote Controller initialized (Phase-101).")

    # ------------------------------------------------------------------
    def _background_learning(self):
        """Continuous Guardian-protected learning loop."""
        self.guardian._write_log("🧠 Background learning loop started (interval=10s).")
        while not self._stop_flag:
            self.guardian.safe_run(self._safe_train_cycle)
            time.sleep(10)

    def _safe_train_cycle(self):
        """Trains model if ReplayBuffer has data, else skips."""
        try:
            if not hasattr(self.trainer, "buffer") or self.trainer.buffer.size() == 0:
                self.guardian._write_log("⚠️ ReplayBuffer empty – skipping training cycle.")
                return
            self.trainer.step(iterations=3)
            self.guardian._write_log("✅ Training cycle complete.")
        except Exception as e:
            self.guardian._write_log(f"⚠️ Training cycle skipped due to error: {e}")

    # ------------------------------------------------------------------
    def serve(self, host="0.0.0.0", port=8089):
        """Starts Astra Remote API server."""

        remote = self

        class AstraHandler(BaseHTTPRequestHandler):
            def _send_json(self, data, code=200):
                self.send_response(code)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))

            def do_GET(self):
                if self.path == "/status":
                    response = {
                        "status": "ok",
                        "phase": "101",
                        "message": "Astra Remote Active",
                        "replay_buffer": getattr(remote.trainer.buffer, "size", lambda: 0)(),
                    }
                    self._send_json(response)

                elif self.path == "/train":
                    remote.guardian.safe_run(remote._safe_train_cycle)
                    self._send_json({"status": "ok", "message": "Training cycle triggered"})

                elif self.path == "/predict":
                    result = remote.guardian.safe_run(
                        lambda: remote.agent.predict([0.1] * 32)
                    )
                    self._send_json({"status": "ok", "prediction": str(result)})

                else:
                    self.send_error(404, "Endpoint not found.")

        server = HTTPServer((host, port), AstraHandler)
        self.guardian._write_log(f"🚀 Astra Remote API active at http://{host}:{port}")
        server.serve_forever()


# ----------------------------------------------------------------------
if __name__ == "__main__":
    base_path = os.getcwd()
    controller = AstraRemote(base_path)
    controller.serve()

