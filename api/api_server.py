"""
api_server.py — Phase 2.7 Read-Only API Interface
-------------------------------------------------
Exposes Astra Intelligence runtime data (signals, trades, metrics)
via safe, read-only HTTP endpoints for dashboard visualization.

✅ Strictly GET-only
✅ Zero writes or mutations
✅ Independent from backend execution
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os, json

# ============================================================
# CONFIGURATION — adjust this path if your canonical folder is "state"
# ============================================================
DATA_PATH = "data"   # or "state" if that's where cache_store.json lives
SIGNALS_FILE = "cache_store.json"  # the canonical signal output
PAPER_TRADES_FILE = "paper_trades.json"
TRADE_HISTORY_FILE = "trade_history.json"
METRICS_FILE = "performance_metrics.json"

# ============================================================
# FASTAPI INITIALIZATION
# ============================================================
app = FastAPI(title="Astra Intelligence API", version="2.7")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"]
)

# ============================================================
# HELPER — SAFE FILE READ
# ============================================================
def safe_read(filename):
    """Read JSON safely; return [] on error."""
    try:
        path = os.path.join(DATA_PATH, filename)
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []

# ============================================================
# ENDPOINTS — READ ONLY
# ============================================================
@app.get("/api/signals")
def get_signals():
    """Return the canonical signal cache (read-only)."""
    return safe_read(SIGNALS_FILE)

@app.get("/api/paper_trades")
def get_paper_trades():
    """Return open paper trades."""
    return safe_read(PAPER_TRADES_FILE)

@app.get("/api/performance_metrics")
def get_performance_metrics():
    """Return derived performance metrics."""
    return safe_read(METRICS_FILE)

# Optional: health check endpoint
@app.get("/api/health")
def get_health():
    return {"status": "ok", "phase": "2.7", "mode": "read-only"}

# ============================================================
# CORS — allow React dev server (Phase 2.7 enhancement)
# ============================================================
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
