#!/bin/bash
set -euo pipefail

ROOT_DIR="/Users/eric/Desktop/astra-intelligence-clean"
SOURCE_PLIST="${ROOT_DIR}/scripts/com.astra.watchdog.plist"
TARGET_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${TARGET_DIR}/com.astra.watchdog.plist"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

if [[ ! -f "${SOURCE_PLIST}" ]]; then
  echo "[astra-launch-agent-install] missing template: ${SOURCE_PLIST}" >&2
  exit 1
fi

if command -v plutil >/dev/null 2>&1; then
  plutil -lint "${SOURCE_PLIST}"
fi

echo "[astra-launch-agent-install] source: ${SOURCE_PLIST}"
echo "[astra-launch-agent-install] target: ${TARGET_PLIST}"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[astra-launch-agent-install] dry-run only; no files copied or launchctl changes made"
  exit 0
fi

mkdir -p "${TARGET_DIR}"
if [[ -f "${TARGET_PLIST}" ]]; then
  BACKUP="${TARGET_PLIST}.backup.$(date +%Y%m%d%H%M%S)"
  cp "${TARGET_PLIST}" "${BACKUP}"
  echo "[astra-launch-agent-install] existing plist backed up to ${BACKUP}"
fi

cp "${SOURCE_PLIST}" "${TARGET_PLIST}"
chmod 644 "${TARGET_PLIST}"

launchctl unload "${TARGET_PLIST}" >/dev/null 2>&1 || true
launchctl load "${TARGET_PLIST}"

echo "[astra-launch-agent-install] installed and loaded"
launchctl list | grep -F "com.astra.watchdog" || true
