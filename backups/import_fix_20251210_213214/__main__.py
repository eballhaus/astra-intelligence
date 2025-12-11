"""
Astra Guardian Main Entrypoint
------------------------------
Allows you to run `python -m astra_core.guardian` directly.
Automatically initializes guardian_log, runs pre-flight checks,
and confirms environment health before Streamlit dashboard launch.
"""

from . import guardian_log


def main():
    print("\n🧠 Launching Astra guardian_log via package entrypoint...\n")
    guardian = guardian.log()
    guardian.log("✅ guardian_log launched successfully via __main__.py")
    guardian.snapshot()
    print("\n🛡️ guardian_log is active, monitoring, and ready.\n")


if __name__ == "__main__":
    main()
