#!/bin/bash
# Astra Intelligence Universal Launcher (Phase-90 Stable)
# Works locally or remotely — auto-builds Poetry env if missing.

cd "$(dirname "$0")"

# Load environment variables
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
  echo "✅ Loaded environment from .env"
else
  echo "⚠️ No .env file found. Using defaults."
fi


# Ensure Poetry is available
if ! command -v poetry &> /dev/null; then
  echo "⚠️ Poetry not found. Installing..."
  curl -sSL https://install.python-poetry.org | python3 -
  export PATH="$HOME/.local/bin:$PATH"
fi

# Create or activate Poetry environment
if [ ! -d ".venv" ]; then
  echo "🧱 Creating Astra environment..."
  poetry config virtualenvs.in-project true
  poetry install
fi

# Activate environment
source .venv/bin/activate

echo "🚀 Launching Astra Intelligence Dashboard..."
streamlit run app.py

