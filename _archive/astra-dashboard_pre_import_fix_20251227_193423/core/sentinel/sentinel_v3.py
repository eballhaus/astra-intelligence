import os, json
from datetime import datetime, timedelta
from statistics import mean

ASTRA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
LOG_PATH = os.path.join(ASTRA_ROOT, "state", "SENTINEL_LOG.jsonl")
TREND_PATH = os.path.join(ASTRA_ROOT, "state", "SENTINEL_TRENDS.json")

def load_log_entries():
    if not os.path.exists(LOG_PATH):
        print("⚠️ No Sentinel log found. Run Sentinel v2 first.")
        return []
    with open(LOG_PATH, "r") as f:
        return [json.loads(line) for line in f if line.strip()]

def analyze_trends(entries):
    if not entries:
        return {"integrity_score": 0, "duplicates": 0, "trend": "no data"}

    recent = entries[-20:]  # last 20 scans
    scores = [e.get("integrity_score", 0) for e in recent]
    dups = [e.get("duplicates", 0) for e in recent]

    avg_score = round(mean(scores), 2)
    avg_dups = round(mean(dups), 2)
    delta = round(scores[-1] - scores[0], 2) if len(scores) > 1 else 0
    trend = "rising" if delta > 0 else "falling" if delta < 0 else "stable"

    risk_level = "low"
    if avg_score < 90: risk_level = "high"
    elif avg_score < 95: risk_level = "medium"

    result = {
        "timestamp": datetime.now().isoformat(),
        "average_integrity": avg_score,
        "average_duplicates": avg_dups,
        "recent_change": delta,
        "trend": trend,
        "risk_level": risk_level,
        "samples_analyzed": len(recent)
    }
    return result

def write_trend_summary(summary):
    os.makedirs(os.path.dirname(TREND_PATH), exist_ok=True)
    with open(TREND_PATH, "w") as f:
        json.dump(summary, f, indent=4)
    print(f"📈 Trend summary written to: {TREND_PATH}")

def main():
    print("\n🧠 ASTRA SENTINEL v3 — Structural Intelligence\n")
    entries = load_log_entries()
    summary = analyze_trends(entries)
    write_trend_summary(summary)
    print(f"🔹 Integrity avg: {summary['average_integrity']}% | Trend: {summary['trend']} | Risk: {summary['risk_level']}")

if __name__ == "__main__":
    main()
