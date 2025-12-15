"""
guardian_v7.py — Temporary Guardian Fix
---------------------------------------
Bypasses broken patched Guardian and replaces it with a safe print-based logger.
"""
import builtins

class GuardianPrint:
    def log(self, msg):
        print(f"[GuardianLog] {msg}")
    def warn(self, msg):
        print(f"[GuardianWarn] {msg}")
    def error(self, msg):
        print(f"[GuardianError] {msg}")
    def info(self, msg):
        print(f"[GuardianInfo] {msg}")

guardian = GuardianPrint()
guardian_boot = lambda: print("[GuardianBoot] Booted safe print guardian.")
builtins.guardian = guardian
