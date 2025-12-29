
# --- Sentinel auto-cleanup integration ---
try:
    import os, runpy
    sentinel_script = os.path.join(os.getcwd(), "sentinel_smart_backup_retention.py")
    if os.path.exists(sentinel_script):
        print("[Sentinel] Running smart backup retention...")
        runpy.run_path(sentinel_script)
except Exception as e:
    print(f"[Sentinel] Cleanup skipped: {e}")
# --- End Sentinel auto-cleanup ---
