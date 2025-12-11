#!/bin/bash
# ============================================================
# 🧠 Astra Intelligence — Full Dashboard Auto-Repair & Relaunch
# ============================================================

echo "🔧 Starting full dashboard repair..."
source venv/bin/activate

# --- Clean cache and compiled files ---
find astra_core/ui/dashboard -name "*.pyc" -delete 2>/dev/null

# --- Guardian Import Repairs ---
echo "🧩 Fixing guardian imports and assignments..."
grep -rl "guardian_log" astra_core/ui/dashboard | \
xargs sed -i '' 's/from astra_core.guardian.*/from astra_core.guardian.guardian_v6 import guardian/g' 2>/dev/null

grep -rl "getattr(guardian_log" astra_core/ui/dashboard | \
xargs sed -i '' 's/guardian = getattr(guardian_log, .log., guardian_log)/guardian = guardian/g' 2>/dev/null

grep -rl "guardian_log(" astra_core/ui/dashboard | \
xargs sed -i '' 's/guardian_log(/guardian.log(/g' 2>/dev/null

grep -rl "guardian_log.log(" astra_core/ui/dashboard | \
xargs sed -i '' 's/guardian_log.log(/guardian.log(/g' 2>/dev/null

# --- Indentation Fix for dashboard_data.py ---
echo "🧩 Fixing malformed try blocks..."
awk '
/^try:$/ {
    print $0
    print "    pass"
    next
}
{ print $0 }
' astra_core/ui/dashboard/dashboard_data.py > astra_core/ui/dashboard/dashboard_data.tmp && mv astra_core/ui/dashboard/dashboard_data.tmp astra_core/ui/dashboard/dashboard_data.py

# --- Syntax Check ---
echo "🔍 Verifying syntax..."
python3 -m compileall -q -f astra_core/ui/dashboard
if [ $? -ne 0 ]; then
    echo "❌ Syntax issues remain. Check output above."
    exit 1
fi

# --- Pylint Quick Scan ---
echo "🧠 Running pylint quick scan..."
pylint --disable=C,R astra_core/ui/dashboard | grep guardian_log && echo "⚠️ guardian_log references remain!" || echo "✅ Guardian references clean."

# --- Relaunch Astra ---
echo ""
echo "🚀 Relaunching Astra Intelligence..."
./astra_all_in_one.sh
