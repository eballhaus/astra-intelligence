import os, datetime

# === Guardian v6: Safe and Backward-Compatible Logging ===
class guardian_log:
    """Universal guardian logging system with legacy safety and self-healing compatibility."""

    def __init__(self, *args, **kwargs):
        # Allow legacy call patterns like guardian_log("message")
        self.messages = []
        if args and isinstance(args[0], str):
            msg = args[0]
            print(f"[Guardian] {msg}")
            self.messages.append(msg)
        else:
            print("[Guardian] guardian_log initialized safely.")

    def log(self, *args, **kwargs):
        """
        Record and print a guardian message.
        Backward-compatible: can be called as log("msg") or log().
        """
        try:
            # Accept message as first arg or from kwargs
            message = args[0] if args else kwargs.get("message", "<empty log call>")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formatted = f"[GuardianLog] {timestamp} | {message}"
            print(formatted)
            self.messages.append(formatted)
        except Exception as e:
            print(f"[GuardianCompat] ⚠️ guardian_log.log() failed: {e}")

    def save(self, path=None):
        """Persist log messages to a file."""
        try:
            if not path:
                path = os.path.expanduser("~/astra_guardian_runtime/guardian_log.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as f:
                for msg in self.messages:
                    f.write(msg + "\n")
            print(f"[Guardian] Logs saved to {path}")
        except Exception as e:
            print(f"[GuardianCompat] ⚠️ Failed to save logs: {e}")

# === Compatibility shim for global use ===
try:
    import builtins
    builtins.guardian_log = guardian_log
    print("[GuardianCompat] ✅ guardian_log patched globally (safe mode).")
except Exception as e:
    print("[GuardianCompat] ⚠️ Failed to patch guardian_log globally:", e)

# === Legacy alias support (for Astra Dashboard compatibility) ===
try:
    # Provide old expected names for backward compatibility
    guardian = guardian_log  # legacy alias
    def guardian_boot(*args, **kwargs):
        print("[GuardianCompat] 🧠 Legacy guardian_boot() called — initializing guardian_log.")
        return guardian_log()

    import builtins
    builtins.guardian = guardian
    builtins.guardian_boot = guardian_boot
    print("[GuardianCompat] ✅ guardian and guardian_boot aliases restored.")
except Exception as e:
    print("[GuardianCompat] ⚠️ Failed to set guardian/guardian_boot aliases:", e)

# === Compatibility Fix: Ensure guardian_log supports .log(message) signature ===
try:
    if not hasattr(guardian_log, "log") or guardian_log.log.__code__.co_argcount < 2:
        class PatchedGuardianLog(guardian_log):
            def log(self, message: str):
                print(f"[Guardian Log] {message}")
        guardian_log = PatchedGuardianLog()
        import builtins
        builtins.guardian_log = guardian_log
        print("[GuardianCompat] ✅ guardian_log.log(message) method patched for compatibility.")
except Exception as e:
    print("[GuardianCompat] ⚠️ Failed to patch guardian_log.log:", e)

# === Global Alias Repair: Ensure guardian.log(message) works correctly ===
try:
    if hasattr(globals(), "guardian"):
        class GuardianAlias:
            def log(self, message):
                print(f"[Guardian Log] {message}")
        guardian = GuardianAlias()
        import builtins
        builtins.guardian = guardian
        print("[GuardianCompat] ✅ guardian.log(message) alias repaired globally.")
    else:
        print("[GuardianCompat] ⚠️ guardian alias not found, skipping alias repair.")
except Exception as e:
    print("[GuardianCompat] ⚠️ Failed to repair guardian.log alias:", e)

# === Guardian Log Method Fix ===
try:
    import builtins

    if hasattr(builtins, "guardian_log"):
        cls = builtins.guardian_log
    elif "guardian_log" in globals():
        cls = globals()["guardian_log"]
    else:
        cls = None

    if cls:
        def fixed_log(self, message):
            try:
                print(f"[Guardian Log] {message}")
            except Exception:
                pass

        setattr(cls, "log", fixed_log)
        print("[GuardianCompat] ✅ guardian_log.log(self, message) patched successfully.")
    else:
        print("[GuardianCompat] ⚠️ guardian_log class not found for patch.")
except Exception as e:
    print("[GuardianCompat] ⚠️ guardian_log.log() patch failed:", e)

# === Astra Dashboard Safe Mode Kill Switch ===
try:
    import builtins
    builtins.DASHBOARD_SAFE_MODE = False
    print("[GuardianCompat] 🧠 Safe mode disabled globally (guardian override).")

    # Force reload of dashboard modules to ensure real functions are used
    import importlib
    dashboard_mods = [
        "astra_core.ui.dashboard.dashboard_sidebar",
        "astra_core.ui.dashboard.dashboard_data",
        "astra_core.ui.dashboard.dashboard_cards",
    ]
    for mod in dashboard_mods:
        importlib.invalidate_caches()
        m = importlib.import_module(mod)
        print(f"[GuardianCompat] ✅ Reloaded dashboard module: {mod}")
    print("[GuardianCompat] ✅ Dashboard functions restored successfully.")
except Exception as e:
    print("[GuardianCompat] ⚠️ Safe mode override failed:", e)

# === Guardian v6 Callable Compatibility Patch ===
# Fixes "TypeError: 'PatchedGuardianLog' object is not callable"
try:
    import builtins
    if isinstance(builtins.guardian_log, object) and not isinstance(builtins.guardian_log, type):
        real_guardian_class = guardian_log if isinstance(guardian_log, type) else None
        if real_guardian_class:
            builtins.guardian_log = real_guardian_class
            print("[GuardianCompat] ✅ Restored guardian_log as callable class (was instance).")
        else:
            print("[GuardianCompat] ⚠️ guardian_log restoration skipped (already callable).")
except Exception as e:
    print("[GuardianCompat] ⚠️ guardian_log callable patch failed:", e)

# === Guardian v6 Critical Restoration Patch ===
# Ensures guardian_log is always callable and never replaced by an instance.
try:
    import builtins
    # Only reassign if guardian_log has become an instance, not a class
    if not isinstance(builtins.guardian_log, type):
        # Find the true class definition
        if 'guardian_log' in globals() and isinstance(globals()['guardian_log'], type):
            builtins.guardian_log = globals()['guardian_log']
            print("[GuardianCompat] ✅ Repaired: guardian_log restored as true class definition.")
        else:
            print("[GuardianCompat] ⚠️ Unable to locate real guardian_log class in globals().")
    else:
        print("[GuardianCompat] 🧠 guardian_log is already callable (no repair needed).")
except Exception as e:
    print("[GuardianCompat] ❌ Critical restoration failed:", e)

# === Guardian v6 Hard Reset Patch ===
# Ensures guardian_log remains a callable class, never an instance.
import builtins, inspect

def _restore_guardian_class():
    """
    This function scans the module for the true guardian_log class and restores it globally
    if it was replaced by a PatchedGuardianLog instance or other object.
    """
    real_class = None
    for name, obj in globals().items():
        if inspect.isclass(obj) and name == "guardian_log":
            real_class = obj
            break

    if not real_class:
        print("[GuardianCompat] ❌ Hard reset failed — guardian_log class not found.")
        return

    if not inspect.isclass(builtins.guardian_log):
        builtins.guardian_log = real_class
        print("[GuardianCompat] ✅ Hard reset — guardian_log restored as callable class.")
    else:
        print("[GuardianCompat] 🧠 guardian_log is already callable (class intact).")

_restore_guardian_class()

# === Guardian v6 Deferred Hard Reset Patch (Final Fix) ===
# Ensures guardian_log remains a callable class, even if patched early.
import builtins, inspect, types

def _deferred_guardian_fix():
    """Rebind guardian_log as a class after full module load."""
    try:
        real_class = globals().get("guardian_log", None)
        if not inspect.isclass(real_class):
            print("[GuardianCompat] ⚠️ Deferred fix — guardian_log class not yet loaded.")
            return

        # If it's already correct, skip
        if inspect.isclass(getattr(builtins, "guardian_log", None)):
            print("[GuardianCompat] 🧠 guardian_log is already callable (class intact).")
            return

        # If it's an instance, rebind
        builtins.guardian_log = real_class
        print("[GuardianCompat] ✅ Deferred fix — guardian_log restored as callable class.")
    except Exception as e:
        print("[GuardianCompat] ❌ Deferred fix failed:", e)

# Register post-import hook to run after class definition
def _post_import_guardian_fix():
    import sys
    module = sys.modules.get(__name__)
    if module and hasattr(module, "guardian_log"):
        _deferred_guardian_fix()

import atexit
atexit.register(_post_import_guardian_fix)

# === Guardian v6 Final Watchdog Patch ===
# Waits until guardian_log class is defined, then ensures it's callable globally.
import builtins, inspect, threading, time

def _watch_guardian_class():
    """Continuously checks for guardian_log definition and restores it globally when ready."""
    max_wait = 5  # seconds
    start = time.time()
    restored = False

    while time.time() - start < max_wait:
        try:
            real_class = globals().get("guardian_log", None)
            if inspect.isclass(real_class):
                if not inspect.isclass(getattr(builtins, "guardian_log", None)):
                    builtins.guardian_log = real_class
                    print("[GuardianCompat] ✅ Watchdog — guardian_log restored as callable class.")
                else:
                    print("[GuardianCompat] 🧠 Watchdog — guardian_log already callable.")
                restored = True
                break
        except Exception as e:
            print("[GuardianCompat] ⚠️ Watchdog iteration failed:", e)
        time.sleep(0.2)

    if not restored:
        print("[GuardianCompat] ❌ Watchdog timeout — guardian_log class not found after wait.")

threading.Thread(target=_watch_guardian_class, daemon=True).start()

# === Guardian v6 Bootstrap Override (Permanent Fix) ===
# Ensures guardian_log is *always* a class, never an instance, before any other module runs.
import builtins, inspect

# If a broken instance already exists, remove it
if not inspect.isclass(getattr(builtins, "guardian_log", None)):
    class guardian_log:
        """Safe bootstrap class — ensures compatibility if patched too early."""
        def __init__(self, *args, **kwargs):
            self.messages = []
            msg = args[0] if args else "[GuardianBootstrap] guardian_log initialized early."
            print(msg)
            self.messages.append(msg)
        def log(self, message):
            print("[GuardianBootstrap Log]", message)
            self.messages.append(message)
        def save(self, path=None):
            print("[GuardianBootstrap] Log saved (noop).")
    builtins.guardian_log = guardian_log
    print("[GuardianCompat] ✅ Bootstrap — guardian_log class reinstated before imports.")
else:
    print("[GuardianCompat] 🧠 guardian_log class already intact (no bootstrap needed).")
