"""
astra_backend.main — Compatibility entrypoint for Astra backend server.
This stub ensures Uvicorn/FastAPI imports succeed while redirecting to astra_core systems.
"""

print("[AstraCompat] ✅ astra_backend.main loaded (compatibility stub).")

try:
    from fastapi import FastAPI
    from astra_core.fetch_core import fetch_unified
    app = FastAPI(title="Astra Intelligence Backend (Compat Mode)")

    @app.get("/")
    async def root():
        return {"status": "ok", "message": "Astra Intelligence Backend active (compat mode)"}

    @app.get("/data/{symbol}")
    async def get_symbol_data(symbol: str):
        try:
            df = fetch_unified.get_symbol_data(symbol)
            if hasattr(df, "to_dict"):
                df = df.to_dict(orient="records")
            return {"symbol": symbol, "data": df}
        except Exception as e:
            return {"error": str(e)}

    print("[AstraCompat] ✅ FastAPI backend app ready.")
except Exception as e:
    print("[AstraCompat] ⚠️ Backend initialization fallback:", e)
    app = None
