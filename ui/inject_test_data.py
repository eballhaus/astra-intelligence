import json, os, time

DATA_DIR = "data"  # or "state" if your canonical directory is that one
os.makedirs(DATA_DIR, exist_ok=True)

# --- Fake signal ---
signals = [{"symbol": "AAPL", "action": "BUY", "confidence": 0.92, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}]
with open(os.path.join(DATA_DIR, "cache_store.json"), "w") as f:
    json.dump(signals, f, indent=2)

# --- Fake paper trade ---
paper_trades = [{"symbol": "AAPL", "entry": 187.5, "status": "open", "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}]
with open(os.path.join(DATA_DIR, "paper_trades.json"), "w") as f:
    json.dump(paper_trades, f, indent=2)

# --- Fake metrics ---
metrics = [{"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "realized_trades": 0, "win_rate": 0.0, "loss_rate": 0.0, "expectancy": 0.0, "status": "active"}]
with open(os.path.join(DATA_DIR, "performance_metrics.json"), "w") as f:
    json.dump(metrics, f, indent=2)

print("[Inject] Test data written successfully ✅")
