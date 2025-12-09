class GuardianLog:
    """Simple placeholder to satisfy Guardian imports."""
    def info(self, message): print(f"[GuardianLog] ℹ️ {message}")
    def warning(self, message): print(f"[GuardianLog] ⚠️ {message}")
    def error(self, message): print(f"[GuardianLog] ❌ {message}")

