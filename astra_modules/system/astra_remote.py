"""
Astra Remote Controller – Phase-101
-----------------------------------
Guardian-supervised remote API for autonomous learning and training control.
"""

import os
import sys
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# === Force project root onto sys.path ===
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from astra_modules.guardian.guardian_v6 import GuardianV6
from astra_modules.agents.neural_agent import NeuralAgent
from astra_modules.agents.continual_trainer import ContinualTrainer


class AstraRemote:
    def __init__(self, base_path):
        self.base_path = base_path
        self.guardian = GuardianV6(base_path)
        self.agent = NeuralAgent(self.guardian)
        self.trainer = ContinualTrainer(self.guardian, self.agent)
        self.guardian._write_log("🌐 Astra Remote Controller initialized (Phase-101).")

    # ------------------------------------------------------------------

    def background_training_loop(self, interval=10):
        """Background continual training loop."""
        import time
        self.guardian._write_log(f"🧠 Background learning loop started (interval={interval}s).")

        while True:
            self.trainer.step(iterations=3)
            time.sleep(interval)


# ----------------------------------------------------------------------
# HTTP Interface
# ----------------------------------------------------------------------

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            response = {
                "status": "ok",
                "phase": "101",
                "message": "Astra Remote Active",
                "replay_buffer": getattr(self.server.controller.trainer.buffer, "size", lambda: 0)(),
            }
            self._respond(200, response)

        elif self.path == "/train":
            threading.Thread(target=self.server.controller.trainer.step, daemon=True).start()
            self._respond(200, {"status": "ok", "message": "Training cycle triggered"})

        else:
            self._respond(404, {"error": "Unknown endpoint"})

    def _respond(self, status, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


class AstraRemoteServer(HTTPServer):
    def __init__(self, controller, host="0.0.0.0", port=8089):
        self.controller = controller
        super().__init__((host, port), RequestHandler)


# ----------------------------------------------------------------------
# Main Entry
# ----------------------------------------------------------------------

if __name__ == "__main__":
    base_path = os.getcwd()
    controller = AstraRemote(base_path)

    # Launch background learning
    loop_thread = threading.Thread(
        target=controller.background_training_loop,
        daemon=True
    )
    loop_thread.start()

    # Start API server
    server = AstraRemoteServer(controller)
    controller.guardian._write_log("🚀 Astra Remote API active at http://0.0.0.0:8089")
    print("🚀 Astra Remote API active at http://0.0.0.0:8089")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        controller.guardian._write_log("🛑 Astra Remote shutting down.")
        print("\n🛑 Astra Remote shutting down.")
        server.server_close()

