from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pathlib import Path
import json

app = FastAPI()

@app.get("/metrics")
async def get_learning_metrics():
    """Return learning metrics JSON data."""
    metrics_path = Path(__file__).resolve().parent.parent / "state" / "learning_metrics.json"
    if not metrics_path.exists():
        return JSONResponse(content={"error": "learning_metrics.json not found"})
    try:
        with open(metrics_path, "r") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        return JSONResponse(content={"error": str(e)})
