import os
import sys
import inspect
from pathlib import Path

ROOT = Path.home() / "Desktop" / "ai_trading_dashboard"

def color(msg, c): 
    return f"\033[{c}m{msg}\033[0m"

def ok(msg): 
    print(color(f"✔ {msg}", "92"))

def warn(msg): 
    print(color(f"⚠ {msg}", "93"))

def fail(msg): 
    print(color(f"✘ {msg}", "91"))

print("\n🔍 ASTRA ENVIRONMENT CHECKER\n")

# ------------------------------
# 1. Check PYTHONPATH
# ------------------------------
if str(ROOT) not in sys.path:
    fail("Project folder NOT in PYTHONPATH!")
    warn("Fix: export PYTHONPATH=\"$HOME/Desktop/ai_trading_dashboard:$PYTHONPATH\"")
else:
    ok("Project folder found in PYTHONPATH")

# ------------------------------
# 2. Check fetch_unified signature
# ------------------------------
try:
    import astra_modules.fetch_core.fetch_unified as fu
    sig = inspect.signature(fu.fetch_unified)
    if str(sig) != "(symbol: str, lookback_days: int = 90)":
        fail(f"fetch_unified signature incorrect: {sig}")
    else:
        ok("fetch_unified signature is correct")
except Exception as e:
    fail(f"Could not import fetch_unified: {e}")

# ------------------------------
# 3. Check that venv is active
# ------------------------------
venv_python = ROOT / "venv" / "bin" / "python"
if not str(sys.executable).startswith(str(venv_python)):
    fail(f"Not using venv Python! Currently: {sys.executable}")
else:
    ok("Using correct venv Python")

# ------------------------------
# 4. Check Streamlit installation
# ------------------------------
try:
    import streamlit
    ok(f"Streamlit OK — {streamlit.__version__}")
except:
    fail("Streamlit is NOT installed in venv!")

print("\n✨ Environment check completed.\n")
