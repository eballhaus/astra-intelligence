cd ~/Desktop/astra-intelligence && \
python3 -c "import pathlib, datetime, textwrap; \
now=datetime.datetime.now().strftime('%Y_%m_%d_%H%M'); \
p=pathlib.Path(f'astra_gpt_refresh_{now}.txt'); \
content=textwrap.dedent('''\
────────────────────────────────────────────
ASTRA GPT REFRESH SNAPSHOT
────────────────────────────────────────────
TIMESTAMP: '''+datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')+'''
────────────────────────────────────────────

📍 REPOSITORY ROOT:
~/Desktop/astra-intelligence

────────────────────────────────────────────
📦 ACTIVE FRONTEND (DASHBOARD):
Path:
astra_dashboard/ui/src/dashboard/pages/Dashboard.jsx

React project path:
~/Desktop/astra-intelligence/astra_dashboard/ui

To start UI:
    cd ~/Desktop/astra-intelligence/astra_dashboard/ui
    npm run dev
Then open:
    http://localhost:5173/

────────────────────────────────────────────
🧩 ACTIVE BACKEND (LIVE ENDPOINT):

File currently used:
~/Desktop/astra-intelligence/quick_live_top_signals.py

Backend server start:
    cd ~/Desktop/astra-intelligence
    nohup uvicorn quick_live_top_signals:app --host 127.0.0.1 --port 8001 --reload > backend.log 2>&1 &

Check running port:
    lsof -i :8001

Test live endpoint:
    curl -s http://127.0.0.1:8001/api/top_signals | jq

────────────────────────────────────────────
📡 CURRENT BACKEND RESPONSE SHAPE:
{
  "signals": {
    "AAPL": { "symbol": "AAPL", "price": 259.37, "grade": "B+", "signal": "BUY" },
    "TSLA": { "symbol": "TSLA", "price": 445.01, "grade": "B+", "signal": "BUY" },
    "NVDA": { "symbol": "NVDA", "price": 184.86, "grade": "B", "signal": "HOLD" }
  }
}

Notes:
- signals is an OBJECT (not array)
- keys are symbols
- each value is a signal object
- backend must NOT be changed

────────────────────────────────────────────
🎯 DASHBOARD.JSX CANONICAL REQUIREMENTS:
- Fetch from http://127.0.0.1:8001/api/top_signals
- Use:
      const signalList = Object.values(liveData?.signals || {});
- Map signalList into cards
- Keep existing CSS classes & structure:
      dashboard-container, market-overview, dashboard-content,
      stocks-section, cryptos-section, card, stock-card, crypto-card,
      chart-section, chart-placeholder
- Refresh interval: 15s
- Use safe optional chaining (?.) and fallbacks
- Never modify layout, spacing, colors, or chart placeholder
- No Tailwind, Recharts, or library changes
- No App.jsx / main.jsx edits

────────────────────────────────────────────
💾 FRONTEND REPAIR NOTES:
If Vite fails with:
  'Port 5173 is already in use'
Free it with:
    lsof -i :5173
    kill -9 <PID>
Then:
    npm run dev

────────────────────────────────────────────
🧠 CONTEXT SUMMARY:
- UI rendering broke due to schema mismatch (backend returns object, not array)
- Canonical solution normalizes backend data via Object.values()
- Current Dashboard.jsx includes live fetch every 15 seconds
- No redesign, CSS untouched
- Backend (quick_live_top_signals.py) must be running for live data

────────────────────────────────────────────
✅ RESTART SEQUENCE (CLEAN BOOT):
1. Kill existing backend: 
       lsof -i :8001 && kill -9 <PID>
2. Start backend:
       nohup uvicorn quick_live_top_signals:app --host 127.0.0.1 --port 8001 --reload > backend.log 2>&1 &
3. Start UI:
       cd ~/Desktop/astra-intelligence/astra_dashboard/ui
       npm run dev
4. Verify:
       curl -s http://127.0.0.1:8001/api/top_signals | jq
       Open http://localhost:5173/

────────────────────────────────────────────
🚦 STATUS:
- Backend ✅ verified (AAPL, TSLA, NVDA live signals)
- UI ✅ runs under Vite
- Data schema confirmed
- Dashboard.jsx functional once reconnected to backend live data

────────────────────────────────────────────
END OF SNAPSHOT
────────────────────────────────────────────
'''); \
p.write_text(content); \
print(f'✅ GPT Refresh file created: {p.resolve()}');"
