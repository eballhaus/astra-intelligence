#!/bin/bash
# ──────────────────────────────────────────────
# Astra Intelligence — Full Auto Launcher
# Launches backend + React dashboard + opens Chrome
# ──────────────────────────────────────────────

cd "$(dirname "$0")" || exit 1

# 1️⃣ Load environment
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
  echo "✅ Loaded environment from .env"
else
  echo "⚠️ No .env found, using defaults."
fi

# 2️⃣ Activate Python environment
if [ -d ".venv" ]; then
  source .venv/bin/activate
elif [ -d "venv" ]; then
  source venv/bin/activate
else
  echo "⚠️ Creating new venv..."
  python3 -m venv venv && source venv/bin/activate
  pip install -r requirements.txt
fi

# 3️⃣ Kill any old backend
lsof -ti:8000 | xargs kill -9 2>/dev/null

# 4️⃣ Launch backend in background
echo "🚀 Starting Astra live backend..."
nohup uvicorn quick_live_top_signals:app --host 0.0.0.0 --port 8000 > logs/backend.log 2>&1 &
sleep 5

# 5️⃣ Launch React dashboard
echo "🌐 Starting Astra dashboard..."
cd astra_dashboard/ui || exit 1
npm install --silent
nohup npm run dev > ../../logs/frontend.log 2>&1 &
sleep 8

# 6️⃣ Open in Chrome
echo "🔗 Opening Astra Intelligence Dashboard..."
open -a "Google Chrome" http://localhost:5173/

echo "✅ Astra Intelligence system fully launched!"
