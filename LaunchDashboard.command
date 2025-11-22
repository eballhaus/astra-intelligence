#!/bin/zsh

echo "📂 Switched to: /Users/ericballhaus/Desktop/ai_trading_dashboard"
cd "/Users/ericballhaus/Desktop/ai_trading_dashboard"

echo "✅ Activating virtual environment..."
source "/Users/ericballhaus/Desktop/ai_trading_dashboard/venv/bin/activate"

echo "🚀 Launching Astra Intelligence Dashboard..."
streamlit run app.py &

echo "🌐 Opening dashboard in browser..."
open "http://localhost:8501/"

echo "🧠 Astra Intelligence Dashboard launched."
