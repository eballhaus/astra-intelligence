# ============================================================
# 🧠 Dashboard Auto-Restore (Guardian Recovery)
# ============================================================
def auto_restore_dashboard_if_broken():
    """
    Guardian fallback: restores dashboard from stable version
    if the active dashboard fails to import or causes runtime crash.
    """
    import shutil
    import os

    main_dashboard = "astra_modules/ui/dashboard/tab_dashboard.py"
    stable_dashboard = "astra_modules/ui/dashboard/tab_dashboard_v7_stable.py"

    try:
        __import__("core.ui.dashboard.tab_dashboard")
    except Exception as e:
        guardian_log(f"[Guardian] 🚨 Dashboard import failed: {e}")
        if os.path.exists(stable_dashboard):
            shutil.copy(stable_dashboard, main_dashboard)
            guardian_log("[Guardian] 🛡️ Restored dashboard from stable fallback.")
        else:
            guardian_log("[Guardian] ⚠️ Stable dashboard fallback not found.")
