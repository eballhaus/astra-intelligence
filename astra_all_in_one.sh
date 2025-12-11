#!/bin/bash
# ============================================================
# 🧠 Astra Intelligence — Unified Launcher (Backend + Dashboard)
# ============================================================

# Activate virtual environment
cd "$(dirname "$0")"
source venv/bin/activate

echo ""
echo "🧠 Astra Intelligence — Launching Backend + Dashboard"
echo "--------------------------------------------------------"
echo "Guardian, Backend, and Streamlit UI will boot together."
echo ""

# Start Uvicorn backend in the background
echo "🚀 Starting Astra Backend..."
uvicorn astra_modules.astra_backend.main:app --reload --host 127.0.0.1 --port 8000 > logs_backend.txt 2>&1 &

BACK_PID=$!
sleep 4  # Give backend a few seconds to initialize

# Start Streamlit dashboard (foreground)
echo "🎨 Launching Streamlit Dashboard..."
streamlit run astra_core/ui/dashboard/tab_dashboard.py --server.port 8501

# When user exits Streamlit (Ctrl+C), stop backend automatically
echo ""
echo "🧩 Shutting down Astra backend..."
kill $BACK_PID 2>/dev/null

echo ""
echo "✅ Astra Intelligence shutdown complete."
echo "--------------------------------------------------------"
