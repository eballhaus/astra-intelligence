# ============================================================
# GuardianStreamManager
# Live Data Streaming via TwelveData WebSocket API
# ============================================================

import json
import threading
import websocket
import time
from datetime import datetime
from core.guardian.guardian_secure_api import GuardianSecureAPI


class GuardianStreamManager:
    def start(self):
        print("[GuardianStream] 🚀 Starting live data stream...")
        import threading
        import time
        self._stop_event = threading.Event()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._connect, daemon=True)
        print("[GuardianStream] 🔗 Launching connection thread...")
        self._thread.start()

    def stop(self):
        print("[GuardianStream] 🛑 Stopping stream...")
        self._stop_event.set()
        if hasattr(self, "ws") and self.ws:
            self.ws.close()
    def __init__(self, symbols=None, on_update=None):
        self.api = GuardianSecureAPI()
        self.api_key = self.api.keys.get("TWELVEDATA_API_KEY")
        self.url = "wss://ws.finnhub.io?token=your_key_here?apikey=${self.api_key}"
        self.symbols = symbols or ["SPY", "BTC/USD"]
        self.on_update = on_update
        self.ws = None
        self._stop_event = threading.Event()
        self._thread = None

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if "price" in data:
                print(f"[GuardianStream] 💹 Live update: {data['symbol']} @ {data['price']}")
                if self.on_update:
                    self.on_update(data)
        except Exception as e:
            print(f"[GuardianStream] ⚠️ Message error: {e}")

    def _on_error(self, ws, error):
        print(f"[GuardianStream] ⚠️ WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"[GuardianStream] 🔌 Connection closed ({close_status_code}): {close_msg}")
        if not self._stop_event.is_set():
            print("[GuardianStream] 🔁 Reconnecting in 5s...")
            time.sleep(5)
            self._connect()

    def _on_open(self, ws):
        print("[GuardianStream] ✅ Connected to TwelveData WebSocket.")

    def _connect(self):
        def on_open(ws):
            print("[GuardianStream] 🌐 WebSocket on_open triggered")
            for symbol in self.symbols:
                payload = {"type": "subscribe", "symbol": symbol}
                ws.send(json.dumps(payload))
                print(f"[GuardianStream] 📡 Subscribed to {symbol}")
            print("[GuardianStream] ✅ Connected to Finnhub stream.")
        url = f"wss://ws.finnhub.io?token=your_key_here"
        
        def on_message(ws, message):
            print(f"[GuardianStream] 📨 Raw message: {message}")
            data = json.loads(message)
            print("[GuardianStream] 🔔", data)
            if isinstance(data, dict) and data.get("event") == "price":
                if self.on_update:
                    self.on_update(data)
        
        def on_error(ws, error):
            print(f"[GuardianStream] ❌ Error detail: {error}")
            print(f"[GuardianStream] ⚠️ WebSocket error: {error}")
        
        def on_close(ws, code, msg):
            print(f"[GuardianStream] 🔚 Close detail: code={code}, msg={msg}")
            print(f"[GuardianStream] 🔌 Connection closed: {code} {msg}")
            if not self._stop_event.is_set():
                print("[GuardianStream] 🔁 Reconnecting in 5s...")
                time.sleep(5)
                self._connect()
        
