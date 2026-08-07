#!/bin/bash
set -euo pipefail

LABEL="com.astra.boot-watchdog"
if launchctl print "system/${LABEL}"; then
  exit 0
fi
echo "[astra-launch-daemon-status] ${LABEL} is not loaded" >&2
exit 1
