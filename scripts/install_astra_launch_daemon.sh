#!/bin/bash
set -euo pipefail

ROOT_DIR="/Users/eric/Desktop/astra-intelligence-clean"
SERVICE_USER="eric"
LABEL="com.astra.boot-watchdog"
SOURCE_PLIST="${ROOT_DIR}/scripts/${LABEL}.plist"
TARGET_PLIST="/Library/LaunchDaemons/${LABEL}.plist"
AGENT_LABEL="com.astra.watchdog"
AGENT_PLIST="/Users/${SERVICE_USER}/Library/LaunchAgents/${AGENT_LABEL}.plist"
DISABLED_AGENT_PLIST="${AGENT_PLIST}.disabled-by-boot-daemon"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

if [[ ! -f "${SOURCE_PLIST}" ]]; then
  echo "[astra-launch-daemon-install] missing template: ${SOURCE_PLIST}" >&2
  exit 1
fi

if command -v plutil >/dev/null 2>&1; then
  plutil -lint "${SOURCE_PLIST}"
fi

echo "[astra-launch-daemon-install] source: ${SOURCE_PLIST}"
echo "[astra-launch-daemon-install] target: ${TARGET_PLIST}"
echo "[astra-launch-daemon-install] ownership: daemon owns backend and worker recovery; frontend remains optional user-session UI; the GUI LaunchAgent is disabled to prevent duplicates"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[astra-launch-daemon-install] dry-run only; no files copied or launchctl changes made"
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[astra-launch-daemon-install] root privileges are required. Run: sudo ${ROOT_DIR}/scripts/install_astra_launch_daemon.sh" >&2
  exit 77
fi

SERVICE_UID="$(id -u "${SERVICE_USER}")"
# Checkpoint the Desktop-owned process tree before the one-time state handoff.
# The boot daemon becomes the only runtime owner after this point.
bash "${ROOT_DIR}/stop_astra_persistent.sh" >/dev/null 2>&1 || true
"${ROOT_DIR}/scripts/sync_astra_boot_runtime.sh" --adopt-state
mkdir -p /Library/Logs/Astra "/Users/${SERVICE_USER}/Library/Logs/Astra"
chown root:wheel /Library/Logs/Astra
chown "${SERVICE_USER}":staff "/Users/${SERVICE_USER}/Library/Logs/Astra"

if [[ -f "${TARGET_PLIST}" ]]; then
  BACKUP="${TARGET_PLIST}.backup.$(date +%Y%m%d%H%M%S)"
  cp "${TARGET_PLIST}" "${BACKUP}"
  echo "[astra-launch-daemon-install] existing daemon plist backed up to ${BACKUP}"
fi
install -o root -g wheel -m 644 "${SOURCE_PLIST}" "${TARGET_PLIST}"

# The boot daemon is the authoritative owner.  Keep the prior user template
# reversibly disabled so login cannot create a second watchdog.
launchctl bootout "gui/${SERVICE_UID}/${AGENT_LABEL}" >/dev/null 2>&1 || true
if [[ -f "${AGENT_PLIST}" && ! -f "${DISABLED_AGENT_PLIST}" ]]; then
  mv "${AGENT_PLIST}" "${DISABLED_AGENT_PLIST}"
  chown "${SERVICE_USER}":staff "${DISABLED_AGENT_PLIST}"
  echo "[astra-launch-daemon-install] disabled competing LaunchAgent template"
fi

launchctl bootout "system/${LABEL}" >/dev/null 2>&1 || true
launchctl bootstrap system "${TARGET_PLIST}"
launchctl print "system/${LABEL}" >/dev/null
echo "[astra-launch-daemon-install] installed and loaded ${LABEL}"
