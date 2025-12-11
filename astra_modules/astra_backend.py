"""
astra_backend compatibility stub.
Preserves legacy imports for older modules that expect astra_modules.astra_backend.
This safely redirects backend functionality to astra_core systems.
"""

print("[AstraCompat] ✅ astra_backend compatibility module loaded.")

try:
    # Redirect to new engine + core subsystems
    from astra_core.engine import *  # if available
    from astra_core.fetch_core import *  # market data bridge
    from astra_core.state import *  # internal state access
    print("[AstraCompat] 🔁 astra_backend → redirected to astra_core subsystems.")
except Exception as e:
    print("[AstraCompat] ⚠️ Limited astra_backend stub active:", e)

# Minimal callable placeholder
def initialize_backend():
    print("[AstraBackend] Initialized (compatibility mode).")
    return True
