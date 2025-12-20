#!/bin/bash
# ──────────────────────────────────────────────
# Astra Intelligence — Launch Dashboard Script
# Launches Streamlit dashboard in default browser
# Updated for stable UI and Guardian integrity system
# ──────────────────────────────────────────────

cd "$(dirname "$0")"  # navigate to project root
source venv/bin/activate  # activate virtual environment

echo "🚀 Launching Astra Intelligence Dashboard..."
sleep 1

# Start the Streamlit dashboard
streamlit run astra_modules/ui/dashboard/tab_dashboard.py --server.port 8501 --browser.serverAddress localhost

