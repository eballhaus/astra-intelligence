#!/bin/bash
# ============================================================
# Astra GPT State Snapshot Script
# Saves all active configuration, logs, and patched files.
# ============================================================

timestamp=$(date +"%Y-%m-%d_%H-%M-%S")
output_dir="astra-intelligence/gpt_state"
output_file="$output_dir/gpt_state_$timestamp.md"

mkdir -p "$output_dir"

echo "# 🧠 Astra GPT Debug Session — $timestamp" > "$output_file"
echo "Captured all recent system modifications and state info." >> "$output_file"
echo "" >> "$output_file"

# --- Git-like summary ---
echo "## 📁 Modified Files" >> "$output_file"
find astra_core astra_modules astra_modules_backup -type f -newermt "1 day ago" 2>/dev/null >> "$output_file"
echo "" >> "$output_file"

# --- Include key logs ---
echo "## 🧩 Guardian & Dashboard Logs" >> "$output_file"
grep -E "\[Guardian|\[Dashboard" ~/.bash_history 2>/dev/null | tail -n 50 >> "$output_file"
echo "" >> "$output_file"

# --- Include critical module excerpts ---
for file in \
    "astra_core/guardian/guardian_v6.py" \
    "astra_core/ui/dashboard/tab_dashboard.py" \
    "astra_core/ui/dashboard/dashboard_sidebar.py" \
    "astra_core/ui/dashboard/dashboard_data.py" \
    "astra_core/ui/dashboard/dashboard_cards.py"
do
    if [ -f "$file" ]; then
        echo "## 🔧 $file" >> "$output_file"
        echo '```python' >> "$output_file"
        cat "$file" >> "$output_file"
        echo '```' >> "$output_file"
        echo "" >> "$output_file"
    fi
done

# --- System summary ---
echo "## 🖥️ System Environment" >> "$output_file"
python3 -V >> "$output_file" 2>&1
pip list | grep astra >> "$output_file" 2>/dev/null
echo "" >> "$output_file"

echo "✅ GPT session state saved to $output_file"
