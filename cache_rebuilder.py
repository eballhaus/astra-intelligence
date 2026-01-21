
# --- Phase 2.6 Metrics Hook ---
try:
    from metrics_engine_v2 import run_metrics_engine
    run_metrics_engine()
except Exception as e:
    print(f"[MetricsEngine] Warning: failed to compute metrics – {e}")

