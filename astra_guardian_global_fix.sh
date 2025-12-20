#!/bin/bash
echo "🧠 Astra Intelligence — Global Guardian Interface Repair"
echo "---------------------------------------------------------"

ROOT_DIR="$(pwd)"
LOGFILE="$ROOT_DIR/guardian_fix_log.txt"
echo "[LOG] Starting Guardian repair pass at $(date)" > "$LOGFILE"

# Backup directory for safety
BACKUP_DIR="$ROOT_DIR/guardian_fix_backups"
mkdir -p "$BACKUP_DIR"

# 1️⃣ Find all files containing 'guardian_log' (excluding guardian_v6)
FILES=$(grep -rl "guardian_log" astra_core astra_modules | grep -v "guardian_v6")

if [ -z "$FILES" ]; then
    echo "✅ No legacy guardian_log references found. System is clean."
    exit 0
fi

# 2️⃣ Process each file
for FILE in $FILES; do
    echo "[Repairing] $FILE"
    cp "$FILE" "$BACKUP_DIR/$(basename $FILE).bak"

    # Replace import statements
    sed -i '' 's/from astra_core.guardian.*/from astra_core.guardian.guardian_v6 import guardian/g' "$FILE"

    # Replace all guardian_log( calls
    sed -i '' 's/guardian_log(/guardian.log(/g' "$FILE"

    echo "[OK] Updated $FILE" >> "$LOGFILE"
done

# 3️⃣ Verify syntax of all changed files
echo "🧩 Running syntax check..."
python3 -m py_compile $(echo $FILES | tr '\n' ' ') 2>> "$LOGFILE"

if [ $? -eq 0 ]; then
    echo "✅ Syntax verification passed. Guardian interface unified."
else
    echo "⚠️ Syntax check reported issues. See $LOGFILE for details."
fi

echo "---------------------------------------------------------"
echo "🧠 Repair complete. Backups stored in: $BACKUP_DIR"
