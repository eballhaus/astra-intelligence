#!/bin/bash
set -e

echo "🔍 Checking Git repository..."
if [ ! -d ".git" ]; then
  echo "❌ Not a Git repository. Initializing..."
  git init
  git branch -M main
  git remote add origin https://github.com/eballhaus/astra-intelligence.git
fi

# Prevent Git from choking on large files
echo "🧹 Checking for large files (>100MB)..."
large_files=$(find . -type f -size +100M ! -path "./.git/*" ! -path "./venv/*")
if [ -n "$large_files" ]; then
  echo "⚠️  The following files are too large and will be skipped:"
  echo "$large_files"
  for f in $large_files; do
    git rm --cached "$f" 2>/dev/null || true
    echo "$f" >> .gitignore
  done
  echo "✅ Large files excluded and added to .gitignore."
fi

# Add, commit, and push changes
echo "📦 Adding all changes..."
git add .

commit_msg="Auto-sync $(date '+%Y-%m-%d %H:%M:%S')"
echo "📝 Committing with message: $commit_msg"
git commit -m "$commit_msg" || echo "ℹ️  No new changes to commit."

echo "🚀 Pushing to GitHub..."
git push -u origin main --force
echo "✅ Push complete!"
