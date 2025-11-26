"""
environment_guardian.py — Guardian Import & Safety Layer
--------------------------------------------------------
Provides safe import handling, environment validation,
and detailed diagnostics for Astra Intelligence modules.
"""

import importlib
import traceback
import os
import sys
from datetime import datetime
import json

# ==========================================================
# SAFE IMPORT FUNCTION (with detailed diagnostics)
# ==========================================================

def safe_import(module_name):
    """
    Safely imports a module and logs detailed error diagnostics.
    Returns the module if successful, None if import fails.
    """
    log_entry = {
        "module": module_name,
        "status": "unknown",
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        print(f"🧩 [DEBUG] Attempting to import: {module_name}")
        module = importlib.import_module(module_name)
        print(f"✅ [DEBUG] Successfully imported: {module_name}")
        log_entry["status"] = "success"
        _log_import_result(log_entry)
        return module

    except ModuleNotFoundError as e:
        print(f"❌ [ERROR] Module not found: {module_name}")
        print(f"   ↳ {e}")
        log_entry["status"] = "not_found"
        log_entry["error"] = str(e)

    except SyntaxError as e:
        print(f"❌ [ERROR] Syntax error in module: {module_name}")
        print(f"   ↳ File: {e.filename}, Line: {e.lineno}, Msg: {e.msg}")
        log_entry["status"] = "syntax_error"
        log_entry["error"] = f"{e.filename}:{e.lineno} — {e.msg}"

    except Exception as e:
        print(f"❌ [ERROR] Unexpected import failure for: {module_name}")
        traceback.print_exc()
        log_entry["status"] = "exception"
        log_entry["error"] = str(e)

    _log_import_result(log_entry)
    return None

# ==========================================================
# LOGGING HELPER — writes all import attempts to a file
# ==========================================================

def _log_import_result(entry):
    """Save import diagnostics to guardian_import_log.json"""
    log_path = os.path.join("astra_modules", "guardian", "guardian_import_log.json")
    logs = []

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                logs = json.load(f)
        except Exception:
            logs = []

    logs.append(entry)
    with open(log_path, "w") as f:
        json.dump(logs, f, indent=2)

# ==========================================================
# ENVIRONMENT VALIDATION
# ==========================================================

def check_environment():
    """Perform environment consistency check for Astra."""
    results = {
        "cwd": os.getcwd(),
        "python": sys.version,
        "venv_active": sys.prefix != sys.base_prefix,
        "timestamp": datetime.utcnow().isoformat()
    }

    print("🧠 Environment Check:")
    for k, v in results.items():
        print(f"   {k}: {v}")

    return results

# ==========================================================
# RUN VALIDATION ON DIRECT EXECUTION
# ==========================================================

if __name__ == "__main__":
    print("🔍 Running Environment Guardian Diagnostics...\n")
    check_environment()
    print("\n🧩 Import test: streamlit")
    safe_import("streamlit")
    print("\n✅ Diagnostics complete.")
