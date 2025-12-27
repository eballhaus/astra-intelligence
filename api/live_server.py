from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from engine.data_orchestrator import fetch_live_data

app = FastAPI()

# --- Allow your React dashboard to access this backend ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["http://localhost:5173"] if you want stricter rules
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/live-data")
def get_live_data():
    return fetch_live_data()
