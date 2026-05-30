#!/bin/bash
set -euo pipefail

TARGET_PLIST="${HOME}/Library/LaunchAgents/com.astra.watchdog.plist"

if [[ -f "${TARGET_PLIST}" ]]; then
  launchctl unload "${TARGET_PLIST}" >/dev/null 2>&1 || true
  rm -f "${TARGET_PLIST}"
  echo "[astra-launch-agent-uninstall] unloaded and removed ${TARGET_PLIST}"
else
  launchctl remove "com.astra.watchdog" >/dev/null 2>&1 || true
  echo "[astra-launch-agent-uninstall] plist not present; launchctl remove attempted"
fi

echo "[astra-launch-agent-uninstall] Astra project files were not deleted"
