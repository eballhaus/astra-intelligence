#!/bin/bash
set -euo pipefail

ROOT_DIR="/Users/eric/Desktop/astra-intelligence-clean"
SERVICE_USER="eric"
LABEL="com.astra.boot-watchdog"
TARGET_PLIST="/Library/LaunchDaemons/${LABEL}.plist"
AGENT_PLIST="/Users/${SERVICE_USER}/Library/LaunchAgents/com.astra.watchdog.plist"
DISABLED_AGENT_PLIST="${AGENT_PLIST}.disabled-by-boot-daemon"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[astra-launch-daemon-uninstall] root privileges are required. Run: sudo ${ROOT_DIR}/scripts/uninstall_astra_launch_daemon.sh" >&2
  exit 77
fi

launchctl bootout "system/${LABEL}" >/dev/null 2>&1 || true
rm -f "${TARGET_PLIST}"

# Restore the prior user template but do not bootstrap it automatically.
if [[ -f "${DISABLED_AGENT_PLIST}" && ! -f "${AGENT_PLIST}" ]]; then
  mv "${DISABLED_AGENT_PLIST}" "${AGENT_PLIST}"
  chown "${SERVICE_USER}":staff "${AGENT_PLIST}"
  echo "[astra-launch-daemon-uninstall] restored LaunchAgent template without loading it"
fi
echo "[astra-launch-daemon-uninstall] removed ${LABEL}"
