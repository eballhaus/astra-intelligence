#!/bin/bash
set -euo pipefail

# This controlled handoff creates the one boot-safe runtime. It never runs at
# boot and never fetches or pulls code. The Desktop state is retained only as
# an inactive recovery backup after the handoff.
SOURCE_ROOT="/Users/eric/Desktop/astra-intelligence-clean"
BOOT_ROOT="/Users/Shared/AstraRuntime"
SERVICE_USER="eric"
DRY_RUN=0
ADOPT_STATE=0

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --adopt-state) ADOPT_STATE=1 ;;
    *) echo "usage: $0 [--dry-run] [--adopt-state]" >&2; exit 64 ;;
  esac
done

if [[ ! -d "${SOURCE_ROOT}/.git" ]]; then
  echo "[astra-boot-sync] approved source checkout is unavailable" >&2
  exit 1
fi
if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[astra-boot-sync] source=${SOURCE_ROOT} boot_root=${BOOT_ROOT} adopt_state=${ADOPT_STATE}"
  echo "[astra-boot-sync] dry-run only; no runtime, state, or credentials changed"
  exit 0
fi
if [[ "$(id -u)" -ne 0 ]]; then
  echo "[astra-boot-sync] root privileges are required. Run: sudo ${SOURCE_ROOT}/scripts/sync_astra_boot_runtime.sh --adopt-state" >&2
  exit 77
fi
if [[ "${ADOPT_STATE}" != "1" ]]; then
  echo "[astra-boot-sync] --adopt-state is required for the first handoff to prevent split runtime state" >&2
  exit 78
fi

SOURCE_COMMIT="$(git -C "${SOURCE_ROOT}" rev-parse HEAD)"
mkdir -p "${BOOT_ROOT}"
rsync -a --delete \
  --exclude '.git/' --exclude 'state/' --exclude 'diagnostics/' --exclude 'logs/' \
  --exclude 'src/' --exclude '.env' --exclude 'venv/' --exclude '__pycache__/' \
  --exclude '.pytest_cache/' --exclude 'node_modules/' \
  "${SOURCE_ROOT}/" "${BOOT_ROOT}/"
rsync -a --delete "${SOURCE_ROOT}/venv/" "${BOOT_ROOT}/venv/"

MANIFEST_PATH="${BOOT_ROOT}/boot_runtime_manifest.json"
if [[ -e "${BOOT_ROOT}/state" && ! -f "${MANIFEST_PATH}" ]]; then
  echo "[astra-boot-sync] boot state exists without a manifest; refusing ambiguous migration" >&2
  exit 1
fi
mkdir -p "${BOOT_ROOT}/state" "${BOOT_ROOT}/logs"
if [[ ! -f "${MANIFEST_PATH}" ]]; then
  rsync -a "${SOURCE_ROOT}/state/" "${BOOT_ROOT}/state/"
else
  echo "[astra-boot-sync] existing canonical boot state retained without overwrite"
fi
if [[ -f "${SOURCE_ROOT}/.env" ]]; then
  install -o "${SERVICE_USER}" -g staff -m 600 "${SOURCE_ROOT}/.env" "${BOOT_ROOT}/.env"
fi
cat > "${MANIFEST_PATH}" <<EOF
{"schema_version":"astra_boot_runtime_v1","source_commit":"${SOURCE_COMMIT}","source_checkout":"${SOURCE_ROOT}","runtime_root":"${BOOT_ROOT}","canonical_state_root":"${BOOT_ROOT}/state","desktop_state_role":"inactive_recovery_backup_after_controlled_handoff","frontend_owner":"user_session_optional","managed_components":["backend","worker"],"automatic_git_operations":false}
EOF
chown -R "${SERVICE_USER}":staff "${BOOT_ROOT}"
chmod 700 "${BOOT_ROOT}"
chmod 600 "${BOOT_ROOT}/boot_runtime_manifest.json"
echo "[astra-boot-sync] deployed approved commit ${SOURCE_COMMIT} with canonical runtime state at ${BOOT_ROOT}/state"
