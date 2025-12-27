from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json, os

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

STATE_DIR = "state"

def read_json(file):
    path = os.path.join(STATE_DIR, file)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

@app.get("/api/signals")
def signals(): return read_json("learning_metrics.json")
@app.get("/api/market_overview")
def overview(): return read_json("market_overview.json")
@app.get("/api/funnel")
def funnel(): return read_json("funnel_state.json")
@app.get("/api/system_health")
def health(): return read_json("system_health.json")
@app.get("/api/learning_state")
def learning(): return read_json("learning_state.json")
@app.get("/api/persona")
def persona(): return read_json("persona.json")
from server_extend import router as router_extend
app.include_router(router_extend)
