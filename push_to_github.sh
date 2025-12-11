#!/bin/bash
# 🚀 Astra Intelligence — All-in-One GitHub Push
set -e

# 1️⃣ Ensure GPT state is always current
if [ -f "./save_gpt_state.sh" ]; then
    echo "🧠 Saving GPT state..."
    bash ./save_gpt_state.sh
fi

# 2️⃣ Auto-add everything safely
echo "📦 Staging all changes..."
git add -A

# 3️⃣ Commit with timestamp and optional user message
COMMIT_MSG="Astra auto-commit — $(date +%Y-%m-%dT%H-%M-%S)"
if [ -n "$1" ]; then
    COMMIT_MSG="$COMMIT_MSG — $1"
fi
echo "📝 Commit message: $COMMIT_MSG"
git commit -m "$COMMIT_MSG" || echo "⚠️ Nothing to commit."

# 4️⃣ Ensure we're synced with remote before pushing
echo "🔄 Pulling latest changes (safe rebase)..."
git pull --rebase origin main || echo "⚠️ Pull rebase encountered issues — continuing."

# 5️⃣ Push to GitHub
echo "🚀 Pushing to GitHub..."
git push origin main

# 6️⃣ Done!
echo "✅ Astra Intelligence successfully pushed to GitHub."
