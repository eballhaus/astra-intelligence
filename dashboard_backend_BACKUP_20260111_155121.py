import sys, os, importlib
from flask import Flask, jsonify, request

# --- Allow imports from project root ---
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# --- Dynamically import SmartScan no matter the case ---
scanners_path = os.path.join(ROOT_DIR, "scanners")
for name in os.listdir(scanners_path):
    if name.lower().startswith("smartscan") and name.endswith((".py", "")):
        module_name = f"scanners.{os.path.splitext(name)[0]}"
        SmartScan = importlib.import_module(module_name).SmartScan
        break

from core.guardian.guardian_v7 import GuardianV7
from chart_core.chart_utils import get_chart_data

app = Flask(__name__)

guardian = GuardianV7()
# scanner = SmartScan()  # temporarily disabled to prevent NameError

@app.route("/api/market_overview")
def market_overview():
    try:
        data = guardian.get_market_overview()
        overview = [
            {"name": k, "value": v.get("price"), "change": v.get("change_percent", 0)}
            for k, v in data.items()
        ]
        return jsonify(overview)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/recommendations")
def recommendations():
    try:
        data = scanner.get_ranked_signals()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/chart_data")
def chart_data():
    symbol = request.args.get("symbol", "AAPL")
    try:
        data = get_chart_data(symbol)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

