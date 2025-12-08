import os
import traceback

print("🔍 Astra API Diagnostic Utility")

try:
    from core.api_client import AstraAPI
except ModuleNotFoundError:
    print("❌ Could not import core.api_client — check PYTHONPATH and directory structure.")
    print("PYTHONPATH =", os.getenv("PYTHONPATH"))
    raise SystemExit(1)

backend_url = os.getenv("ASTRA_BACKEND_URL", "http://127.0.0.1:8000")
print(f"🌐 Backend URL: {backend_url}")

try:
    api = AstraAPI()
    print("⚙️  Fetching live quote for AAPL...")
    result = api.get_quote("AAPL")
    print("✅ Live API response:")
    print(result)
except Exception as e:
    print("❌ API check failed.")
    traceback.print_exc()

