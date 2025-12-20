#!/bin/bash
# ✅ Permanent Astra launcher
# Forces Streamlit to execute from the actual project root

cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
echo "🔹 Launching Astra from: $(pwd)"
echo "🔹 Using PYTHONPATH: $PYTHONPATH"

exec "$(which streamlit)" run "$(pwd)/app.py" --server.headless=true --server.fileWatcherType=none
