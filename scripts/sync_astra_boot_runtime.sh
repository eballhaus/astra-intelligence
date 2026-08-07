#!/bin/bash
set -euo pipefail

# This controlled deployment copies immutable approved code and performs one
# explicit handoff of mutable authority to the boot-safe runtime. Afterward,
# the Desktop checkout is a symlinked consumer, never a second state owner.
SOURCE_ROOT="/Users/eric/Desktop/astra-intelligence-clean"
BOOT_ROOT="/Users/Shared/AstraRuntime"
SERVICE_USER="eric"
SOURCE_STATE_ROOT="${SOURCE_ROOT}/state"
SOURCE_ENV_PATH="${SOURCE_ROOT}/.env"
CANONICAL_STATE_ROOT="${BOOT_ROOT}/state"
CANONICAL_ENV_PATH="${BOOT_ROOT}/.env"
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
  echo "[astra-boot-sync] source=${SOURCE_ROOT} boot_root=${BOOT_ROOT} canonical_state_root=${CANONICAL_STATE_ROOT} adopt_state=${ADOPT_STATE}"
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
  --exclude '.git/' --exclude 'state' --exclude 'state/***' --exclude 'diagnostics/' --exclude 'logs/' \
  --exclude 'recovery_backups/' --exclude 'boot_runtime_manifest.json' \
  --exclude 'src/' --exclude '.env' --exclude 'venv/' --exclude '__pycache__/' \
  --exclude '.pytest_cache/' --exclude 'node_modules/' \
  "${SOURCE_ROOT}/" "${BOOT_ROOT}/"
rsync -a --delete "${SOURCE_ROOT}/venv/" "${BOOT_ROOT}/venv/"

MANIFEST_PATH="${BOOT_ROOT}/boot_runtime_manifest.json"
BACKUP_ROOT="${BOOT_ROOT}/recovery_backups"
BOOT_STATE_PATH="${CANONICAL_STATE_ROOT}"
BOOT_ENV_PATH="${CANONICAL_ENV_PATH}"
mkdir -p "${BOOT_ROOT}/logs" "${BACKUP_ROOT}"

timestamp="$(date +%Y%m%dT%H%M%SZ)"

# First handoff: copy the healthy Desktop state while services are stopped,
# verify the copy, retain a rollback backup, and atomically make Shared active.
if [[ -L "${SOURCE_STATE_ROOT}" ]]; then
  if [[ "$(readlink "${SOURCE_STATE_ROOT}")" != "${CANONICAL_STATE_ROOT}" ]]; then
    echo "[astra-boot-sync] Desktop state link points to an unexpected authority" >&2
    exit 1
  fi
elif [[ -d "${SOURCE_STATE_ROOT}" ]]; then
  STAGED_STATE="${BOOT_ROOT}/.state_migration_${timestamp}"
  rsync -a "${SOURCE_STATE_ROOT}/" "${STAGED_STATE}/"
  if [[ -n "$(rsync -a --checksum --dry-run "${SOURCE_STATE_ROOT}/" "${STAGED_STATE}/")" ]]; then
    echo "[astra-boot-sync] state migration verification failed" >&2
    exit 1
  fi
  rsync -a "${SOURCE_STATE_ROOT}/" "${BACKUP_ROOT}/desktop_state_pre_migration_${timestamp}/"
  if [[ -e "${BOOT_STATE_PATH}" || -L "${BOOT_STATE_PATH}" ]]; then
    mv "${BOOT_STATE_PATH}" "${BACKUP_ROOT}/preexisting_boot_state_${timestamp}"
  fi
  mv "${STAGED_STATE}" "${BOOT_STATE_PATH}"
  mv "${SOURCE_STATE_ROOT}" "${SOURCE_ROOT}/.astra_state_pre_migration_${timestamp}"
  ln -s "${CANONICAL_STATE_ROOT}" "${SOURCE_STATE_ROOT}"
else
  echo "[astra-boot-sync] Desktop state root is unavailable: ${SOURCE_STATE_ROOT}" >&2
  exit 1
fi

# Make Shared the single physical credential source. The Desktop path becomes
# only a symlink after a byte-for-byte staged copy has been verified.
if [[ -L "${SOURCE_ENV_PATH}" ]]; then
  if [[ "$(readlink "${SOURCE_ENV_PATH}")" != "${CANONICAL_ENV_PATH}" ]]; then
    echo "[astra-boot-sync] Desktop credential link points to an unexpected authority" >&2
    exit 1
  fi
elif [[ -f "${SOURCE_ENV_PATH}" ]]; then
  STAGED_ENV="${BOOT_ROOT}/.env_migration_${timestamp}"
  install -o "${SERVICE_USER}" -g staff -m 600 "${SOURCE_ENV_PATH}" "${STAGED_ENV}"
  if ! cmp -s "${SOURCE_ENV_PATH}" "${STAGED_ENV}"; then
    echo "[astra-boot-sync] credential migration verification failed" >&2
    exit 1
  fi
  rm -f "${BOOT_ENV_PATH}"
  mv "${STAGED_ENV}" "${BOOT_ENV_PATH}"
  rm -f "${SOURCE_ENV_PATH}"
  ln -s "${CANONICAL_ENV_PATH}" "${SOURCE_ENV_PATH}"
else
  echo "[astra-boot-sync] Desktop credential source is unavailable: ${SOURCE_ENV_PATH}" >&2
  exit 1
fi
cat > "${MANIFEST_PATH}" <<EOF
{"schema_version":"astra_boot_runtime_v3","source_commit":"${SOURCE_COMMIT}","source_checkout":"${SOURCE_ROOT}","runtime_root":"${BOOT_ROOT}","canonical_state_root":"${CANONICAL_STATE_ROOT}","desktop_state_path":"${SOURCE_STATE_ROOT}","desktop_state_mode":"symlink_to_shared_canonical_state","canonical_env_path":"${CANONICAL_ENV_PATH}","desktop_env_mode":"symlink_to_shared_canonical_env","rollback_backup":"${BACKUP_ROOT}/desktop_state_pre_migration_${timestamp}","frontend_owner":"user_session_optional","managed_components":["backend","worker"],"automatic_git_operations":false}
EOF
chown "${SERVICE_USER}":staff "${BOOT_ROOT}" "${BOOT_ROOT}/logs" "${BACKUP_ROOT}"
chown -R "${SERVICE_USER}":staff "${BOOT_STATE_PATH}"
chown -h "${SERVICE_USER}":staff "${SOURCE_STATE_ROOT}" "${SOURCE_ENV_PATH}"
chown "${SERVICE_USER}":staff "${BOOT_ENV_PATH}"
chmod 600 "${BOOT_ENV_PATH}"
chmod 700 "${BOOT_ROOT}"
chmod 600 "${BOOT_ROOT}/boot_runtime_manifest.json"
echo "[astra-boot-sync] deployed approved commit ${SOURCE_COMMIT} with boot-safe canonical state at ${CANONICAL_STATE_ROOT}"
