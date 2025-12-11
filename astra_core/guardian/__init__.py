# =============================================================================
# Guardian Fallback Initialization (Compatible with Astra v7–v8)
# =============================================================================

class GuardianLog:
    """Safe fallback Guardian logger supporting both call and .log() methods."""
    def __init__(self, *args, **kwargs):
        # Allow initialization with or without message
        if args or kwargs:
            self.__call__(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        """Allow calling guardian('msg') directly."""
        try:
            msg = " ".join(str(a) for a in args)
            print("[Guardian Log]", msg)
        except Exception:
            pass

    def log(self, *args, **kwargs):
        """Allow guardian.log('msg') style usage."""
        try:
            msg = " ".join(str(a) for a in args)
            print("[Guardian Log]", msg)
        except Exception:
            pass


# Allow legacy code to use guardian_log_func("message")
def guardian_log_func(*args, **kwargs):
    try:
        msg = " ".join(str(a) for a in args)
        print("[Guardian Log Func]", msg)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Create a global guardian fallback instance for cross-module use
# -----------------------------------------------------------------------------
guardian = GuardianLog()

print("[Guardian] ✅ Fallback guardian_log class and instance initialized safely.")

# -----------------------------------------------------------------------------
# Unified wrapper: allow `guardian_log("msg")` or `guardian.log("msg")`
# -----------------------------------------------------------------------------
def guardian_log(*args, **kwargs):
    """Unified fallback function for legacy calls."""
    try:
        from astra_core.guardian.guardian_v6 import guardian as g6
        g6.log(*args, **kwargs)
    except Exception:
        msg = " ".join(str(a) for a in args)
        print("[Guardian Log Fallback]", msg)

# -----------------------------------------------------------------------------
# End of file
# -----------------------------------------------------------------------------
