# =============================================================================
# Guardian Fallback Initialization (Compatible with Astra v7–v8)
# =============================================================================

class guardian_log:
    """Safe fallback Guardian logger supporting both call and .log() methods."""
    def __init__(self, *args, **kwargs):
        # Allow initialization with or without message
        if args or kwargs:
            self.__call__(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        """Allow calling guardian_log('msg') directly."""
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


# Allow legacy code to use guardian_log() as a standalone function
def guardian_log_func(*args, **kwargs):
    try:
        msg = " ".join(str(a) for a in args)
        print("[Guardian Log Func]", msg)
    except Exception:
        pass


# Create a global guardian instance for cross-module use
guardian = guardian_log()

print("[Guardian] ✅ Fallback guardian_log class and instance initialized safely.")

# --- guardian_log callable wrapper fix (2025-12-09) ---
def guardian_log(*args, **kwargs):
    """Allow guardian_log('message') to call the guardian instance safely."""
    try:
        from astra_core.guardian import guardian
        guardian.log(*args, **kwargs)
    except Exception as e:
        print("[Guardian Log Wrapper Error]", e)
# --- end wrapper fix ---

