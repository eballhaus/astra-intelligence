#!/bin/bash
set -euo pipefail

# This controlled deployment copies immutable approved code only. Mutable
# execution state and credentials remain single-authority files owned by the
# established Astra checkout; the boot runtime reaches them through symlinks.
SOURCE_ROOT="/Users/eric/Desktop/astra-intelligence-clean"
BOOT_ROOT="/Users/Shared/AstraRuntime"
SERVICE_USER="eric"
CANONICAL_STATE_ROOT="${ASTRA_STATE_ROOT:-${SOURCE_ROOT}/state}"
CANONICAL_ENV_PATH="${ASTRA_ENV_FILE:-${SOURCE_ROOT}/.env}"
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
  echo "[astra-boot-sync] source=${SOURCE_ROOT} boot_root=${BOOT_ROOT} state_root=${CANONICAL_STATE_ROOT} adopt_state=${ADOPT_STATE}"
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
if [[ ! -d "${CANONICAL_STATE_ROOT}" ]]; then
  echo "[astra-boot-sync] canonical state root is unavailable: ${CANONICAL_STATE_ROOT}" >&2
  exit 1
fi
if [[ ! -f "${CANONICAL_ENV_PATH}" ]]; then
  echo "[astra-boot-sync] canonical credential source is unavailable: ${CANONICAL_ENV_PATH}" >&2
  exit 1
fi
mkdir -p "${BOOT_ROOT}"
rsync -a --delete \
  --exclude '.git/' --exclude 'state' --exclude 'state/***' --exclude 'diagnostics/' --exclude 'logs/' \
  --exclude 'src/' --exclude '.env' --exclude 'venv/' --exclude '__pycache__/' \
  --exclude '.pytest_cache/' --exclude 'node_modules/' \
  "${SOURCE_ROOT}/" "${BOOT_ROOT}/"
rsync -a --delete "${SOURCE_ROOT}/venv/" "${BOOT_ROOT}/venv/"

MANIFEST_PATH="${BOOT_ROOT}/boot_runtime_manifest.json"
BACKUP_ROOT="${BOOT_ROOT}/recovery_backups"
BOOT_STATE_LINK="${BOOT_ROOT}/state"
BOOT_ENV_LINK="${BOOT_ROOT}/.env"
mkdir -p "${BOOT_ROOT}/logs" "${BACKUP_ROOT}"

# A prior deployment copied mutable state. Preserve it outside the active
# runtime, then replace it with a link to the single canonical state root.
if [[ -L "${BOOT_STATE_LINK}" ]]; then
  if [[ "$(readlink "${BOOT_STATE_LINK}")" != "${CANONICAL_STATE_ROOT}" ]]; then
    mv "${BOOT_STATE_LINK}" "${BACKUP_ROOT}/split_state_link_$(date +%Y%m%dT%H%M%SZ)"
  fi
elif [[ -e "${BOOT_STATE_LINK}" ]]; then
  mv "${BOOT_STATE_LINK}" "${BACKUP_ROOT}/split_state_$(date +%Y%m%dT%H%M%SZ)"
fi
if [[ ! -L "${BOOT_STATE_LINK}" ]]; then
  ln -s "${CANONICAL_STATE_ROOT}" "${BOOT_STATE_LINK}"
fi

# The boot runtime must not retain a second credential file. A symlink keeps
# one protected physical source while preserving standard dotenv discovery.
if [[ -L "${BOOT_ENV_LINK}" ]]; then
  if [[ "$(readlink "${BOOT_ENV_LINK}")" != "${CANONICAL_ENV_PATH}" ]]; then
    echo "[astra-boot-sync] boot credential link points to an unexpected source" >&2
    exit 1
  fi
elif [[ -e "${BOOT_ENV_LINK}" ]]; then
  if ! cmp -s "${BOOT_ENV_LINK}" "${CANONICAL_ENV_PATH}"; then
    echo "[astra-boot-sync] refusing to remove a non-identical boot credential file" >&2
    exit 1
  fi
  rm -f "${BOOT_ENV_LINK}"
fi
if [[ ! -L "${BOOT_ENV_LINK}" ]]; then
  ln -s "${CANONICAL_ENV_PATH}" "${BOOT_ENV_LINK}"
fi
cat > "${MANIFEST_PATH}" <<EOF
{"schema_version":"astra_boot_runtime_v2","source_commit":"${SOURCE_COMMIT}","source_checkout":"${SOURCE_ROOT}","runtime_root":"${BOOT_ROOT}","canonical_state_root":"${CANONICAL_STATE_ROOT}","boot_state_path":"${BOOT_STATE_LINK}","boot_state_mode":"symlink_to_canonical_state","canonical_env_path":"${CANONICAL_ENV_PATH}","boot_env_mode":"symlink_to_canonical_env","frontend_owner":"user_session_optional","managed_components":["backend","worker"],"automatic_git_operations":false}
EOF
chown "${SERVICE_USER}":staff "${BOOT_ROOT}" "${BOOT_ROOT}/logs" "${BACKUP_ROOT}"
chown -h "${SERVICE_USER}":staff "${BOOT_STATE_LINK}" "${BOOT_ENV_LINK}"
chmod 700 "${BOOT_ROOT}"
chmod 600 "${BOOT_ROOT}/boot_runtime_manifest.json"
echo "[astra-boot-sync] deployed approved commit ${SOURCE_COMMIT} with one canonical state root at ${CANONICAL_STATE_ROOT}"
