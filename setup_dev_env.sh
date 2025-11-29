#!/bin/bash
# ===============================================================
# Astra Intelligence Phase-101.9 Developer Environment Protection
# ===============================================================

echo "🚀 Astra Phase-101.9: Full System Integrity Check"

# --- Core installs ---
pip install --quiet --upgrade pip
pip install --quiet black isort flake8 mypy autoflake pylint autopep8 pyright

# --- Clean up and auto-format ---
echo "🧹 Cleaning and formatting code..."
black astra_modules
isort astra_modules
autoflake --in-place --remove-unused-variables --remove-all-unused-imports -r astra_modules
autopep8 --in-place --recursive astra_modules

# --- Lint + Type Checks ---
echo "🔍 Running static code analysis..."
flake8 astra_modules || true
mypy --ignore-missing-imports --check-untyped-defs astra_modules || true
pylint -sn --disable=C,R astra_modules | grep -E "missing|undefined|import" || true

# --- Fix file permissions ---
find astra_modules -type f -name "*.py" -exec chmod 644 {} +

echo ""
echo "✅ Astra Developer Check Complete"
echo "   Run again anytime with: ./setup_dev_env.sh"
echo ""

