import server_extend
from fastapi import FastAPI
import uvicorn

# Patch the missing top_signals route so it returns something safe
@server_extend.router.get("/api/top_signals")
def top_signals():
    return {
        "status": "ok",
        "message": "Guardian backend active",
        "signals": [
            {"symbol": "AAPL", "score": 0.82},
            {"symbol": "TSLA", "score": 0.76},
            {"symbol": "BTCUSD", "score": 0.68}
        ]
    }

app = FastAPI()
app.include_router(server_extend.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
