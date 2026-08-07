#!/bin/bash
set -euo pipefail

TARGET_PLIST="${HOME}/Library/LaunchAgents/com.astra.watchdog.plist"
UID_VALUE="$(id -u)"

if [[ -f "${TARGET_PLIST}" ]]; then
  launchctl bootout "gui/${UID_VALUE}/com.astra.watchdog" >/dev/null 2>&1 || launchctl unload "${TARGET_PLIST}" >/dev/null 2>&1 || true
  rm -f "${TARGET_PLIST}"
  echo "[astra-launch-agent-uninstall] unloaded and removed ${TARGET_PLIST}"
else
  launchctl bootout "gui/${UID_VALUE}/com.astra.watchdog" >/dev/null 2>&1 || launchctl remove "com.astra.watchdog" >/dev/null 2>&1 || true
  echo "[astra-launch-agent-uninstall] plist not present; launchctl remove attempted"
fi

echo "[astra-launch-agent-uninstall] Astra project files were not deleted"
