from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json, os

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:8000",
        "http://localhost:8000"
    ] + [x.strip() for x in str(os.getenv("ASTRA_EXTRA_CORS_ORIGINS", "")).split(",") if x.strip()],
    allow_origin_regex=r"^https?://((localhost)|(127\.0\.0\.1)|(\d{1,3}(\.\d{1,3}){3}))(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client_is_loopback(host: str) -> bool:
    v = str(host or "").strip().lower()
    return v in {"127.0.0.1", "::1", "localhost"}


def _extract_access_token(req: Request) -> str:
    header_token = str(req.headers.get("x-astra-access-token") or "").strip()
    if header_token:
        return header_token
    auth = str(req.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


@app.middleware("http")
async def _astra_remote_access_guard(request: Request, call_next):
    required_token = str(os.getenv("ASTRA_REMOTE_ACCESS_TOKEN", "")).strip()
    if not required_token:
        return await call_next(request)

    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if request.url.path in {"/api/health"}:
        return await call_next(request)

    enforce_for_loopback = str(os.getenv("ASTRA_REMOTE_REQUIRE_TOKEN_FOR_LOOPBACK", "0")).strip().lower() in {"1", "true", "yes", "on"}
    client_host = str((request.client.host if request.client else "") or "")
    if _client_is_loopback(client_host) and not enforce_for_loopback:
        return await call_next(request)

    supplied = _extract_access_token(request)
    if supplied != required_token:
        return JSONResponse(status_code=401, content={"ok": False, "error": "remote_access_token_required"})
    return await call_next(request)

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
from server_extend import _ensure_paper_autopilot_started as _ensure_paper_autopilot_started_runtime
app.include_router(router_extend)


@app.on_event("startup")
def _astra_startup_background():
    try:
        _ensure_paper_autopilot_started_runtime()
    except Exception:
        pass
