import os

# =====================================================
# Astra Intelligence — Secure API Configuration (env-based)
# =====================================================

API_ENDPOINT = os.getenv("ASTRA_API_BASE", "https://your-api-gateway.example.com/v1/market")
API_KEY      = os.getenv("ASTRA_API_KEY", "YOUR_API_KEY_HERE")
TIMEOUT      = float(os.getenv("ASTRA_API_TIMEOUT", "10.0"))
DEBUG        = os.getenv("ASTRA_API_DEBUG", "False").lower() == "true"

# =====================================================
# End of File
# =====================================================
