from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from astra_dashboard.fetch_core.api_router import get_best

app = FastAPI(title="Astra Intelligence API", version="1.0")

# Enable CORS for your React UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ---------------------------
# Root endpoint
# ---------------------------
@app.get("/")
def root():
    return {"status": "Astra API online"}


# ---------------------------
# Learning Status
# ---------------------------
@app.get("/learning/status")
def learning_status():
    try:
        from astra_dashboard.learning.learning_manager import start_background_learning
        return {"success": True, "status": "learning_active"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------
# Learning Metrics
# ---------------------------
@app.get("/learning/metrics")
def learning_metrics():
    from pathlib import Path
    import json

    metrics_path = Path(__file__).resolve().parent.parent / "state" / "learning_metrics.json"
    if not metrics_path.exists():
        return {"error": "learning_metrics.json not found"}

    try:
        with open(metrics_path) as f:
            data = json.load(f)
        return data
    except Exception as e:
        return {"error": str(e)}


# ---------------------------
# Live Market Data
# ---------------------------
@app.get("/live")
def get_live_data():
    try:
        data = get_best()
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}

# === Dashboard Live Data Route (connected to Orchestrator) ===
from engine.data_orchestrator import fetch_live_data

@app.get("/dashboard/live")
async def dashboard_live():
    """Expose Astra Orchestrator live data bundle for dashboard."""
    try:
        data = fetch_live_data()
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}

