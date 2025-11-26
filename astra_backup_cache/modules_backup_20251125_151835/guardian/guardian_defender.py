"""
guardian_defender.py — Phase-90 AstraDefender
-------------------------------------------------
Expanded self-healing, auto-repair, and deep error logging system.
Works alongside GuardianV3 but handles UI-level failures, scoring faults,
scanner issues, universe failures, and Streamlit duplicate-key crashes.
"""

import traceback
import json
import time
from pathlib import Path

# Streamlit is optional in some backend calls
try:
    import streamlit as st
except Exception:
    st = None


# ============================================================
# ASTRA MEMORY LOCATION
# ============================================================
ASTRA_MEMORY_FILE = Path(__file__).parent.parent / "astra_memory.json"


# ============================================================
# ASTRA DEFENDER
# ============================================================
class AstraDefender:
    """
    High-level protection layer:
    - Wraps ANY function
    - Attempts auto-fixes for known issues
    - Avoids Streamlit crashes
    - Provides persistent error-memory
    - Protects UI, charts, scanners, fetchers, and ranking engine
    """

    def __init__(self):
        self.memory_file = ASTRA_MEMORY_FILE
        self.load_memory()

    # ---------------------------------------------------------
    # MEMORY SYSTEM
    # ---------------------------------------------------------
    def load_memory(self):
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r") as f:
                    self.memory = json.load(f)
            except:
                self.memory = {"errors": []}
        else:
            self.memory = {"errors": []}

    def save_memory(self):
        try:
            with open(self.memory_file, "w") as f:
                json.dump(self.memory, f, indent=2)
        except:
            print("⚠ Failed to save Astra memory file.")

    # ---------------------------------------------------------
    # SAFE EXECUTION WRAPPER
    # ---------------------------------------------------------
    def run_safe(self, func, *args, **kwargs):
        """
        Safely run ANY function within Astra.
        - Prevents UI crashes
        - Detects error type
        - Attempts repairs
        - Logs persistent memory for debugging
        - Returns None if unrecoverable
        """
        try:
            return func(*args, **kwargs)

        except Exception as e:
            # Attempt auto-fix first
            fixed = self.auto_fix(e, func, args, kwargs)
            if fixed is not None:
                return fixed

            # Log to persistent memory
            error_info = {
                "timestamp": time.time(),
                "function": func.__name__,
                "args": [str(a) for a in args],
                "kwargs": {k: str(v) for k, v in kwargs.items()},
                "error_type": type(e).__name__,
                "error_msg": str(e),
                "traceback": traceback.format_exc()
            }
            self.memory["errors"].append(error_info)
            self.save_memory()

            print(f"⚠ AstraDefender caught unhandled error in {func.__name__}: {e}")
            traceback.print_exc()

            return None

    # ---------------------------------------------------------
    # AUTO-REPAIR MODULE
    # ---------------------------------------------------------
    def auto_fix(self, e, func, args, kwargs):
        """
        Automatically attempts to fix common, predictable failures.
        Returns repaired value if possible, otherwise None.
        """

        err_msg = str(e)

        # ---------------------------------------------
        # FIX: Streamlit Duplicate Key
        # ---------------------------------------------
        if "DuplicateElementKey" in err_msg or "duplicate" in err_msg.lower():
            if "key" in kwargs:
                kwargs["key"] = f"{kwargs['key']}_{int(time.time()*1000)}"
                print(f"⚡ Auto-fixed duplicate key → {kwargs['key']}")
                try:
                    return func(*args, **kwargs)
                except:
                    return None

        # ---------------------------------------------
        # FIX: ValueError / TypeError (bad numeric format)
        # ---------------------------------------------
        if isinstance(e, (ValueError, TypeError)):
            new_args = []
            for a in args:
                try:
                    new_args.append(float(a))
                except:
                    new_args.append(a)
            new_kwargs = {}
            for k, v in kwargs.items():
                try:
                    new_kwargs[k] = float(v)
                except:
                    new_kwargs[k] = v

            print(f"⚡ Auto-fixed TypeError/ValueError for {func.__name__}")

            try:
                return func(*new_args, **new_kwargs)
            except:
                return None

        # ---------------------------------------------
        # FIX: AttributeError — list instead of dict
        # ---------------------------------------------
        if isinstance(e, AttributeError) and "'list' object has no attribute 'get'" in err_msg:
            print(f"⚡ Auto-fixed list→dict mismatch in {func.__name__}")
            try:
                if len(args) > 0 and isinstance(args[0], list) and len(args[0]) > 0:
                    args = (args[0][0], *args[1:])
                return func(*args, **kwargs)
            except:
                return None

        # ---------------------------------------------
        # FIX: Formatting errors (e.g., "{value:.2f}" on string)
        # ---------------------------------------------
        if isinstance(e, ValueError) and "Unknown format code" in err_msg:
            print(f"⚡ Auto-fixed float-format issue in {func.__name__}")
            for k, v in kwargs.items():
                if isinstance(v, str):
                    try:
                        kwargs[k] = float(v)
                    except:
                        kwargs[k] = 0.0
            try:
                return func(*args, **kwargs)
            except:
                return None

        # No known fix
        return None

    # ---------------------------------------------------------
    # HUMAN-FRIENDLY ERROR SUMMARY
    # ---------------------------------------------------------
    def analyze_errors(self):
        if not self.memory["errors"]:
            return "✅ No logged errors."

        out = []
        for e in self.memory["errors"]:
            out.append(f"{e['function']} → {e['error_type']}: {e['error_msg']}")

        return "\n".join(out)


# ============================================================
# SHARED INSTANCE
# ============================================================
defender = AstraDefender()
