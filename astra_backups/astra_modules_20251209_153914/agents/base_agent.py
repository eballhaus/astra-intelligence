# astra_modules/agents/base_agent.py
class BaseAgent:
    """Shared guardian-safe logging mixin."""

    def __init__(self, guardian=None):
        self.guardian = guardian

    def g_log(self, msg: str):
        """Guardian-aware log output."""
        try:
            if self.guardian:
                self.guardian._write_log(msg)
            else:
                print(msg)
        except Exception:
            print(msg)

    def predict(self, x=None):
        """Temporary calibration stub."""
        self.g_log(f"[{self.__class__.__name__}] Predict placeholder executed.")
        return 0.5
