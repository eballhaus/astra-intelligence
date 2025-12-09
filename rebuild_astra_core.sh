#!/bin/bash
set -e

echo "🚀 Starting Astra Core rebuild..."

# === 1. Create unified core folder ===
mkdir -p astra_core/{ui/{dashboard,components},engine,forecast,learning,guardian,state,agents,core,utils,chart_core,compat}

# === 2. Backup old versions ===
timestamp=$(date +"%Y%m%d_%H%M%S")
mkdir -p astra_backups
cp -r astra_modules "astra_backups/astra_modules_$timestamp"

# === 3. Copy stable modules from backup 20251130 ===
cp -r astra_modules_backup_20251130_1720/engine/* astra_core/engine/
cp -r astra_modules_backup_20251130_1720/forecast/* astra_core/forecast/
cp -r astra_modules_backup_20251130_1720/learning/* astra_core/learning/
cp -r astra_modules_backup_20251130_1720/guardian/* astra_core/guardian/
cp -r astra_modules_backup_20251130_1720/state/* astra_core/state/
cp -r astra_modules_backup_20251130_1720/agents/* astra_core/agents/
cp -r astra_modules_backup_20251130_1720/core/* astra_core/core/
cp -r astra_modules_backup_20251130_1720/utils/* astra_core/utils/
cp -r astra_modules_backup_20251130_1720/chart_core/* astra_core/chart_core/
cp -r astra_modules_backup_20251130_1720/ui/components/* astra_core/ui/components/
cp -r astra_modules_backup_20251130_1720/ui/dashboard/* astra_core/ui/dashboard/

# === 4. Inject latest files from current astra_modules (keep your new updates) ===
rsync -a --ignore-existing astra_modules/ astra_core/

# === 5. Add compatibility shim ===
cat <<'EOF' > astra_core/compat/legacy_imports.py
import sys
from importlib import import_module

# Redirect legacy imports
sys.modules["astra_modules.state.state_manager"] = import_module("astra_core.state.state_bundle_builder")
sys.modules["astra_modules.guardian.guardian_sentinel"] = import_module("astra_core.guardian.guardian_v6")
sys.modules["astra_modules.ui.dashboard.dashboard_summary"] = import_module("astra_core.ui.dashboard.dashboard_snapshot")
EOF

echo "✅ Astra Core rebuild complete."

