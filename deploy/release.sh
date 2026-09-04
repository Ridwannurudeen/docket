#!/usr/bin/env bash
set -euo pipefail

export LC_ALL=C
umask 027

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
    shift
fi

if [[ $# -ne 1 ]]; then
    printf '%s\n' \
        'Usage: release.sh [--dry-run] <release-manifest.json>' >&2
    exit 2
fi

readonly MANIFEST_ARGUMENT=$1
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if (( DRY_RUN )); then
    if [[ -z "${DOCKET_RELEASE_ROOT:-}" ]]; then
        printf '%s\n' '--dry-run requires DOCKET_RELEASE_ROOT.' >&2
        exit 1
    fi
    RELEASE_ROOT="$(cd -- "${DOCKET_RELEASE_ROOT}" && pwd -P)"
    if [[ "${RELEASE_ROOT}" == / ]]; then
        printf '%s\n' 'DOCKET_RELEASE_ROOT must not resolve to /.' >&2
        exit 1
    fi
elif [[ "${EUID}" -ne 0 ]]; then
    printf '%s\n' 'release.sh must run as root.' >&2
    exit 1
else
    RELEASE_ROOT=
fi
readonly RELEASE_ROOT

root_path() {
    printf '%s%s' "${RELEASE_ROOT}" "$1"
}

trace_command() {
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
}

run_fs() {
    trace_command "$@"
    "$@"
}

run_host() {
    trace_command "$@"
    if (( ! DRY_RUN )); then
        "$@"
    fi
}

install_file() {
    local source=$1
    local target=$2
    trace_command install -o root -g root -m 0644 "${source}" "${target}"
    if (( DRY_RUN )); then
        install -m 0644 "${source}" "${target}"
    else
        install -o root -g root -m 0644 "${source}" "${target}"
    fi
}

FAILURE_REASON='release command failed'
fatal() {
    FAILURE_REASON=$1
    printf 'Release refused: %s\n' "${FAILURE_REASON}" >&2
    exit 1
}

if (( DRY_RUN )); then
    RELEASE_LOCK=${DOCKET_RELEASE_LOCK_PATH:-$(root_path /run/docket/release.lock)}
    FLOCK_COMMAND=${DOCKET_RELEASE_FLOCK:-flock}
    run_fs mkdir -p "$(dirname -- "${RELEASE_LOCK}")"
    run_fs chmod 0700 "$(dirname -- "${RELEASE_LOCK}")"
else
    RELEASE_LOCK_DIR=/run/docket
    RELEASE_LOCK=${RELEASE_LOCK_DIR}/release.lock
    FLOCK_COMMAND=flock
    [[ -d /run && ! -L /run ]] || fatal '/run must be a real directory'
    [[ "$(stat -c '%U:%G' /run)" == root:root ]] || fatal \
        '/run must be owned by root:root'
    run_mode=$(stat -c '%a' /run)
    (( (8#${run_mode} & 8#022) == 0 )) || fatal \
        '/run must not be group/world writable'
    if [[ ! -e "${RELEASE_LOCK_DIR}" && ! -L "${RELEASE_LOCK_DIR}" ]]; then
        run_fs mkdir -m 0700 -- "${RELEASE_LOCK_DIR}"
    fi
    [[ -d "${RELEASE_LOCK_DIR}" && ! -L "${RELEASE_LOCK_DIR}" ]] || fatal \
        "release lock directory is invalid: ${RELEASE_LOCK_DIR}"
    [[ "$(stat -c '%a:%U:%G' "${RELEASE_LOCK_DIR}")" == '700:root:root' ]] || fatal \
        'release lock directory must be mode 0700 and owned by root:root'
fi
readonly RELEASE_LOCK FLOCK_COMMAND
if [[ -e "${RELEASE_LOCK}" || -L "${RELEASE_LOCK}" ]]; then
    [[ -f "${RELEASE_LOCK}" && ! -L "${RELEASE_LOCK}" ]] || fatal \
        "release lock must be a regular file: ${RELEASE_LOCK}"
    if (( ! DRY_RUN )); then
        [[ "$(stat -c '%a:%U:%G' "${RELEASE_LOCK}")" == '600:root:root' ]] || fatal \
            'existing release lock must be mode 0600 and owned by root:root'
    fi
fi
exec {RELEASE_LOCK_FD}>"${RELEASE_LOCK}" || fatal \
    "could not open release lock: ${RELEASE_LOCK}"
readonly RELEASE_LOCK_FD
trace_command "${FLOCK_COMMAND}" -n "${RELEASE_LOCK_FD}"
"${FLOCK_COMMAND}" -n "${RELEASE_LOCK_FD}" || fatal \
    'another Docket release is already running'
if (( DRY_RUN )); then
    run_fs chmod 0600 "${RELEASE_LOCK}"
else
    run_fs chown root:root "${RELEASE_LOCK}"
    run_fs chmod 0600 "${RELEASE_LOCK}"
fi

[[ -f "${MANIFEST_ARGUMENT}" ]] || fatal \
    "release manifest does not exist: ${MANIFEST_ARGUMENT}"
MANIFEST="$(cd -- "$(dirname -- "${MANIFEST_ARGUMENT}")" && pwd -P)/$(basename -- "${MANIFEST_ARGUMENT}")"
readonly MANIFEST
VERIFY_SECURITY_ARGS=()
if (( ! DRY_RUN )); then
    VERIFY_SECURITY_ARGS=(--secure-owner 0)
fi
readonly -a VERIFY_SECURITY_ARGS
trace_command python3 "${SCRIPT_DIR}/release_bundle.py" verify "${MANIFEST}" \
    "${SCRIPT_DIR}" "${VERIFY_SECURITY_ARGS[@]}"
set +e
manifest_verification="$({
    python3 "${SCRIPT_DIR}/release_bundle.py" verify "${MANIFEST}" \
        "${SCRIPT_DIR}" "${VERIFY_SECURITY_ARGS[@]}"
} 2>&1)"
manifest_status=$?
set -e
(( manifest_status == 0 )) || fatal \
    "release manifest verification failed: ${manifest_verification}"
manifest_verification=${manifest_verification//$'\r'/}
mapfile -t manifest_lines <<<"${manifest_verification}"
[[ ${#manifest_lines[@]} -eq 8 ]] || fatal \
    'release manifest verifier returned an invalid response'
SOURCE_COMMIT=${manifest_lines[0]}
WHEEL=${manifest_lines[1]}
EXPECTED_WHEEL_SHA=${manifest_lines[2]}
WHEEL_NAME=${manifest_lines[3]}
WHEEL_VERSION=${manifest_lines[4]}
RUNTIME_LOCK=${manifest_lines[5]}
RUNTIME_LOCK_SHA=${manifest_lines[6]}
MANIFEST_SHA=${manifest_lines[7]}
readonly SOURCE_COMMIT WHEEL EXPECTED_WHEEL_SHA WHEEL_NAME WHEEL_VERSION
readonly RUNTIME_LOCK RUNTIME_LOCK_SHA MANIFEST_SHA
readonly ACTUAL_WHEEL_SHA=${EXPECTED_WHEEL_SHA}
readonly COMMIT12=${SOURCE_COMMIT:0:12}
printf 'Release manifest verified: %s (%s).\n' "${SOURCE_COMMIT}" "${MANIFEST_SHA}"

readonly OPT_ROOT="$(root_path /opt)"
readonly OPT_DOCKET="$(root_path /opt/docket)"
readonly VENV_ROOT="$(root_path /opt/docket-venvs)"
readonly VENV="${VENV_ROOT}/${COMMIT12}"
readonly VENV_PARTIAL="${VENV}.partial"
readonly VENV_INVALID="${VENV}.invalid"
readonly SYSTEMD_ROOT="$(root_path /etc/systemd/system)"
readonly JOURNALD_ROOT="$(root_path /etc/systemd/journald.conf.d)"
readonly JOURNALD_TARGET="${JOURNALD_ROOT}/docket.conf"
readonly CANARY_CONFIG="$(root_path /etc/docket/docket-canary.conf)"
readonly CANARY_TOKEN="$(root_path /etc/docket/docket-canary.token)"
readonly CANARY_KEY="$(root_path /etc/docket/docket-canary-payment.key)"
readonly CONFIG_DIRECTORY="$(root_path /etc/docket)"
readonly STATE_DIRECTORY="$(root_path /var/lib/docket)"
readonly DATA_DIRECTORY="$(root_path /var/lib/docket/data)"
readonly DATABASE_PATH="$(root_path /var/lib/docket/data/agents.sqlite3)"
readonly DATABASE_BACKUP_ROOT="$(root_path /var/backups/docket)"
if (( DRY_RUN )); then
    JSON_PYTHON=python3
    BACKUP_PYTHON=${DOCKET_RELEASE_BACKUP_PYTHON:-python3}
    FSYNC_PYTHON=${DOCKET_RELEASE_FSYNC_PYTHON:-python3}
    COPY_COMMAND=${DOCKET_RELEASE_COPY:-cp}
    CURL_COMMAND=${DOCKET_RELEASE_CURL:-curl}
    JOURNALCTL_COMMAND=${DOCKET_RELEASE_JOURNALCTL:-journalctl}
    RUNUSER_COMMAND=${DOCKET_RELEASE_RUNUSER:-runuser}
    SYSTEMCTL_COMMAND=${DOCKET_RELEASE_SYSTEMCTL:-systemctl}
else
    JSON_PYTHON="${OPT_DOCKET}/.venv/bin/python"
    BACKUP_PYTHON="${OPT_DOCKET}/.venv/bin/python"
    FSYNC_PYTHON=python3
    COPY_COMMAND=cp
    CURL_COMMAND=curl
    JOURNALCTL_COMMAND=journalctl
    RUNUSER_COMMAND=runuser
    SYSTEMCTL_COMMAND=systemctl
fi
readonly JSON_PYTHON BACKUP_PYTHON FSYNC_PYTHON COPY_COMMAND CURL_COMMAND JOURNALCTL_COMMAND
readonly RUNUSER_COMMAND SYSTEMCTL_COMMAND

validate_canary_identity() {
    local group_record user_record
    local group_name group_password group_id group_members
    local user_name user_password user_id user_group_id user_gecos user_home user_shell
    local uid_min gid_min canary_groups
    group_record=$(getent group docket-canary) || fatal \
        'docket-canary system group is missing'
    user_record=$(getent passwd docket-canary) || fatal \
        'docket-canary system user is missing'
    IFS=: read -r group_name group_password group_id group_members <<<"${group_record}"
    IFS=: read -r user_name user_password user_id user_group_id user_gecos user_home user_shell \
        <<<"${user_record}"
    uid_min=$(awk '$1 == "UID_MIN" { print $2; exit }' /etc/login.defs)
    gid_min=$(awk '$1 == "GID_MIN" { print $2; exit }' /etc/login.defs)
    canary_groups=$(id -nG docket-canary)
    [[ "${group_name}" == docket-canary && "${group_id}" =~ ^[0-9]+$ && \
        -z "${group_members}" && "${canary_groups}" == docket-canary && \
        "${user_name}" == docket-canary && "${user_id}" =~ ^[0-9]+$ && \
        "${user_group_id}" == "${group_id}" && "${user_home}" == /nonexistent && \
        ! -e /nonexistent && ! -L /nonexistent && \
        "${user_shell}" == /usr/sbin/nologin && "${uid_min}" =~ ^[0-9]+$ && \
        "${gid_min}" =~ ^[0-9]+$ && "${user_id}" -lt "${uid_min}" && \
        "${group_id}" -lt "${gid_min}" ]] || fatal \
        'docket-canary must be a nologin, no-home system user with its matching system group'
    if id -nG docket | tr ' ' '\n' | grep -Fxq docket-canary; then
        fatal 'docket must not be a member of docket-canary'
    fi
}

require_exact_acl() {
    local acl=$1
    local target=$2
    shift 2
    local actual expected
    actual=$(sed '/^[[:space:]]*$/d' <<<"${acl}" | sort)
    expected=$(printf '%s\n' "$@" | sort)
    [[ "${actual}" == "${expected}" ]] || fatal \
        "${target} ACL contains missing or unexpected entries"
}

run_canary_test() {
    "${RUNUSER_COMMAND}" -u docket-canary -g docket-canary -- test "$@"
}

validate_database_storage_mode() {
    local header header_status
    [[ -f "${DATABASE_PATH}" && ! -L "${DATABASE_PATH}" ]] || fatal \
        "runtime database is missing or unsafe: ${DATABASE_PATH}"
    for sidecar in "${DATABASE_PATH}-wal" "${DATABASE_PATH}-shm"; do
        [[ ! -e "${sidecar}" && ! -L "${sidecar}" ]] || fatal \
            'live database is in WAL mode; quiesce and convert it to DELETE mode before release'
    done
    trace_command "${JSON_PYTHON}" - "${DATABASE_PATH}"
    set +e
    header="$("${JSON_PYTHON}" - "${DATABASE_PATH}" <<'PY'
import sys
from pathlib import Path

with Path(sys.argv[1]).open("rb") as database:
    header = database.read(20)
if len(header) != 20 or header[:16] != b"SQLite format 3\x00":
    raise SystemExit("invalid SQLite database header")
print(f"{header[18]}:{header[19]}")
PY
    )"
    header_status=$?
    set -e
    (( header_status == 0 )) || fatal 'live database has an invalid SQLite header'
    [[ "${header}" == '1:1' ]] || fatal \
        'live database is in WAL mode; quiesce and convert it to DELETE mode before release'
}

validate_database_storage_mode

run_fs install -d -m 0755 "${OPT_ROOT}" "${VENV_ROOT}"
BUILDING_VENV=0
PUBLISHED_VENV=0
QUARANTINED_VENV=0
VENV_WORK=${VENV}
cleanup_partial_venv() {
    if (( BUILDING_VENV )); then
        if (( PUBLISHED_VENV )) && [[ -e "${VENV}" || -L "${VENV}" ]]; then
            trace_command rm -rf -- "${VENV}"
            rm -rf -- "${VENV}"
        fi
        if (( QUARANTINED_VENV )) && \
            [[ -d "${VENV_INVALID}" && ! -L "${VENV_INVALID}" ]] && \
            [[ ! -e "${VENV}" && ! -L "${VENV}" ]]; then
            trace_command mv -T -- "${VENV_INVALID}" "${VENV}"
            mv -T -- "${VENV_INVALID}" "${VENV}"
        fi
        if [[ -e "${VENV_PARTIAL}" || -L "${VENV_PARTIAL}" ]]; then
            trace_command rm -rf -- "${VENV_PARTIAL}"
            rm -rf -- "${VENV_PARTIAL}"
        fi
    fi
}
on_venv_exit() {
    local status=$?
    trap - EXIT
    if (( status != 0 )); then
        set +e
        cleanup_partial_venv
    fi
    exit "${status}"
}
trap on_venv_exit EXIT

fsync_paths() {
    local kind=$1
    shift
    trace_command "${FSYNC_PYTHON}" - "${kind}" "$@"
    if (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_FSYNC_PYTHON:-}" ]]; then
        "${FSYNC_PYTHON}" - "${kind}" "$@" <<'PY'
import os
import sys

kind, *paths = sys.argv[1:]
flags = os.O_RDONLY
if kind == "directory":
    flags |= getattr(os, "O_DIRECTORY", 0)
elif kind != "file":
    raise SystemExit(f"unsupported fsync path kind: {kind}")
for path in paths:
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
    fi
}

VENV_VALIDATION_REASON=
validate_release_environment() {
    local path=$1
    local python=$2
    local installed_name installed_version pip_show
    VENV_VALIDATION_REASON=
    trace_command "${python}" -m pip check
    if { (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_VENV_PYTHON:-}" ]]; } && \
        ! "${python}" -m pip check; then
        VENV_VALIDATION_REASON='release environment failed pip check'
        return 1
    fi
    trace_command "${RUNUSER_COMMAND}" -u docket -- "${path}/bin/python" -c \
        'import docket, docket.api, docket.canary'
    if (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_RUNUSER:-}" ]]; then
        if ! "${RUNUSER_COMMAND}" -u docket -- "${path}/bin/python" -c \
            'import docket, docket.api, docket.canary'; then
            VENV_VALIDATION_REASON='docket service user cannot import the installed release'
            return 1
        fi
    fi
    trace_command "${python}" -m pip show docket
    if (( DRY_RUN )); then
        installed_name=docket
        installed_version=${DOCKET_RELEASE_INSTALLED_VERSION:-${WHEEL_VERSION}}
    else
        pip_show="$("${python}" -m pip show docket)" || {
            VENV_VALIDATION_REASON='pip show docket failed for the release environment'
            return 1
        }
        printf '%s\n' "${pip_show}"
        installed_name="$(awk -F ': ' '$1 == "Name" { print $2 }' <<<"${pip_show}")"
        installed_version="$(awk -F ': ' '$1 == "Version" { print $2 }' <<<"${pip_show}")"
    fi
    if [[ "${installed_name,,}" != docket || "${installed_version}" != "${WHEEL_VERSION}" ]]; then
        VENV_VALIDATION_REASON="pip show docket version ${installed_version:-<missing>} does not match wheel ${WHEEL_VERSION}"
        return 1
    fi
}

if [[ -e "${VENV}" || -L "${VENV}" ]]; then
    [[ -d "${VENV}" && ! -L "${VENV}" ]] || fatal \
        "existing venv path is not a directory: ${VENV}"
    existing_commit=
    existing_sha=
    existing_version=
    existing_lock_sha=
    [[ ! -f "${VENV}/RELEASE-commit.txt" ]] || \
        existing_commit="$(<"${VENV}/RELEASE-commit.txt")"
    [[ ! -f "${VENV}/WHEEL-sha256.txt" ]] || \
        existing_sha="$(<"${VENV}/WHEEL-sha256.txt")"
    [[ ! -f "${VENV}/DOCKET-version.txt" ]] || \
        existing_version="$(<"${VENV}/DOCKET-version.txt")"
    [[ ! -f "${VENV}/RUNTIME-LOCK-sha256.txt" ]] || \
        existing_lock_sha="$(<"${VENV}/RUNTIME-LOCK-sha256.txt")"
    if [[ "${existing_commit}" != "${SOURCE_COMMIT}" || \
        "${existing_sha}" != "${EXPECTED_WHEEL_SHA}" || \
        "${existing_version}" != "${WHEEL_VERSION}" || \
        "${existing_lock_sha}" != "${RUNTIME_LOCK_SHA}" ]]; then
        fatal "existing venv identity differs: ${VENV}"
    fi
    if (( DRY_RUN )); then
        existing_python=${DOCKET_RELEASE_VENV_PYTHON:-${VENV}/bin/python}
    else
        existing_python=${VENV}/bin/python
    fi
    if validate_release_environment "${VENV}" "${existing_python}"; then
        printf 'Reusing matching venv: %s\n' "${VENV}"
    else
        printf 'Matching venv failed validation; rebuilding: %s\n' \
            "${VENV_VALIDATION_REASON}" >&2
        BUILDING_VENV=1
        VENV_WORK=${VENV_PARTIAL}
    fi
else
    BUILDING_VENV=1
    VENV_WORK=${VENV_PARTIAL}
fi
if [[ -e "${VENV_PARTIAL}" || -L "${VENV_PARTIAL}" ]]; then
    [[ -d "${VENV_PARTIAL}" && ! -L "${VENV_PARTIAL}" ]] || fatal \
        "stale partial venv path is invalid: ${VENV_PARTIAL}"
    run_fs rm -rf -- "${VENV_PARTIAL}"
fi
if [[ -e "${VENV_INVALID}" || -L "${VENV_INVALID}" ]]; then
    [[ -d "${VENV_INVALID}" && ! -L "${VENV_INVALID}" ]] || fatal \
        "quarantined venv path is invalid: ${VENV_INVALID}"
    if [[ -e "${VENV}" || -L "${VENV}" ]]; then
        run_fs rm -rf -- "${VENV_INVALID}"
    fi
fi
readonly VENV_WORK
if (( DRY_RUN )); then
    VENV_PYTHON=${DOCKET_RELEASE_VENV_PYTHON:-${VENV_WORK}/bin/python}
else
    VENV_PYTHON=${VENV_WORK}/bin/python
fi
readonly VENV_PYTHON

if (( BUILDING_VENV )); then
    if ! (
        run_fs umask 022
        trace_command python3 -m venv "${VENV_WORK}"
        if (( DRY_RUN )); then
            install -d -m 0755 "${VENV_WORK}/bin"
        else
            python3 -m venv "${VENV_WORK}" || exit 1
        fi
        trace_command "${VENV_PYTHON}" -m pip install --require-hashes \
            --only-binary=:all: -r "${RUNTIME_LOCK}"
        if (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_VENV_PYTHON:-}" ]]; then
            "${VENV_PYTHON}" -m pip install --require-hashes \
                --only-binary=:all: -r "${RUNTIME_LOCK}" || exit 1
        fi
        trace_command "${VENV_PYTHON}" -m pip install --no-deps "${WHEEL}"
        if (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_VENV_PYTHON:-}" ]]; then
            "${VENV_PYTHON}" -m pip install --no-deps "${WHEEL}" || exit 1
        fi
    ); then
        fatal 'release environment installation failed'
    fi
fi

if (( BUILDING_VENV )); then
    validate_release_environment "${VENV_WORK}" "${VENV_PYTHON}" || fatal \
        "${VENV_VALIDATION_REASON}"
    trace_command printf '%s\\n' "${SOURCE_COMMIT}" '>' "${VENV_WORK}/RELEASE-commit.txt"
    printf '%s\n' "${SOURCE_COMMIT}" >"${VENV_WORK}/RELEASE-commit.txt"
    trace_command printf '%s\\n' "${EXPECTED_WHEEL_SHA}" '>' \
        "${VENV_WORK}/WHEEL-sha256.txt"
    printf '%s\n' "${EXPECTED_WHEEL_SHA}" >"${VENV_WORK}/WHEEL-sha256.txt"
    trace_command printf '%s\\n' "${WHEEL_VERSION}" '>' "${VENV_WORK}/DOCKET-version.txt"
    printf '%s\n' "${WHEEL_VERSION}" >"${VENV_WORK}/DOCKET-version.txt"
    trace_command printf '%s\\n' "${RUNTIME_LOCK_SHA}" '>' \
        "${VENV_WORK}/RUNTIME-LOCK-sha256.txt"
    printf '%s\n' "${RUNTIME_LOCK_SHA}" >"${VENV_WORK}/RUNTIME-LOCK-sha256.txt"
    run_fs chmod 0644 \
        "${VENV_WORK}/RELEASE-commit.txt" \
        "${VENV_WORK}/WHEEL-sha256.txt" \
        "${VENV_WORK}/DOCKET-version.txt" \
        "${VENV_WORK}/RUNTIME-LOCK-sha256.txt"
    fsync_paths file \
        "${VENV_WORK}/RELEASE-commit.txt" \
        "${VENV_WORK}/WHEEL-sha256.txt" \
        "${VENV_WORK}/DOCKET-version.txt" \
        "${VENV_WORK}/RUNTIME-LOCK-sha256.txt" || fatal \
        'could not durably publish release environment identity'
    fsync_paths directory "${VENV_WORK}" || fatal \
        'could not durably publish release environment identity directory'
    if [[ -e "${VENV}" || -L "${VENV}" ]]; then
        run_fs mv -T -- "${VENV}" "${VENV_INVALID}"
        QUARANTINED_VENV=1
    fi
    run_fs mv -T -- "${VENV_WORK}" "${VENV}"
    PUBLISHED_VENV=1
    fsync_paths directory "${VENV_ROOT}" || fatal \
        'could not durably publish release environment root'
    BUILDING_VENV=0
    PUBLISHED_VENV=0
    if [[ -e "${VENV_INVALID}" || -L "${VENV_INVALID}" ]]; then
        run_fs rm -rf -- "${VENV_INVALID}"
        fsync_paths directory "${VENV_ROOT}" || fatal \
            'could not durably remove the quarantined release environment'
    fi
fi
trap - EXIT

readonly -a UNIT_NAMES=(
    docket.service
    docket-canary.service
    docket-canary.timer
    docket-jobs.service
    docket-jobs.timer
    docket-lp-record.service
    docket-lp-record.timer
    docket-probe.service
    docket-probe.timer
    docket-refresh.service
    docket-refresh.timer
    docket-v3-capture.service
    docket-v3-capture.timer
    docket-v3-range-capture.service
    docket-v3-range-capture.timer
    docket-v3-yield-v6-capture.service
    docket-v3-yield-v6-capture.timer
    docket-v3-range-v7-capture.service
    docket-v3-range-v7-capture.timer
    docket-v3-yield-v8-capture.service
    docket-v3-yield-v8-capture.timer
)
readonly -a TIMER_NAMES=(
    docket-canary.timer
    docket-jobs.timer
    docket-lp-record.timer
    docket-probe.timer
    docket-refresh.timer
    docket-v3-capture.timer
    docket-v3-range-capture.timer
    docket-v3-yield-v6-capture.timer
    docket-v3-range-v7-capture.timer
    docket-v3-yield-v8-capture.timer
)
for name in "${UNIT_NAMES[@]}"; do
    [[ -f "${SCRIPT_DIR}/systemd/${name}" ]] || fatal \
        "missing release unit: ${SCRIPT_DIR}/systemd/${name}"
done
[[ -f "${SCRIPT_DIR}/journald-docket.conf" ]] || fatal \
    "missing release asset: ${SCRIPT_DIR}/journald-docket.conf"
[[ -f "${CANARY_CONFIG}" && ! -L "${CANARY_CONFIG}" ]] || fatal \
    "canary config is missing or unsafe: ${CANARY_CONFIG}"
[[ -f "${CANARY_TOKEN}" && ! -L "${CANARY_TOKEN}" ]] || fatal \
    "canary token is missing or unsafe: ${CANARY_TOKEN}"
if (( ! DRY_RUN )); then
    validate_canary_identity
    [[ "$(stat -c '%a:%U:%G' "${CANARY_CONFIG}")" == '640:root:docket-canary' ]] || fatal \
        "canary config must be mode 0640 and owned by root:docket-canary"
    [[ "$(stat -c '%a:%U:%G' "${CANARY_TOKEN}")" == '640:root:docket' ]] || fatal \
        "canary token must be mode 0640 and owned by root:docket"
    [[ "$(stat -c '%a:%U:%G' "${CONFIG_DIRECTORY}")" == '750:root:docket' ]] || fatal \
        'Docket configuration directory must be mode 0750 and owned by root:docket'
    [[ "$(stat -c '%a:%U:%G' "${STATE_DIRECTORY}")" == '750:docket:docket' ]] || fatal \
        'Docket state directory must be mode 0750 and owned by docket:docket'
    [[ "$(stat -c '%a:%U:%G' "${DATA_DIRECTORY}")" == '770:docket:docket' ]] || fatal \
        'Docket data directory must have effective mode 0770 and owner docket:docket'
    [[ "$(stat -c '%a:%U:%G' "${DATABASE_PATH}")" == '660:docket:docket' ]] || fatal \
        'live database must have effective mode 0660 and owner docket:docket'

    mapfile -t canary_recipient_settings < <(
        sed -n 's/^[[:space:]]*DOCKET_PAY_TO=//p' "${CANARY_CONFIG}"
    )
    (( ${#canary_recipient_settings[@]} == 1 )) || fatal \
        'canary config must name exactly one payment recipient'
    [[ "${canary_recipient_settings[0],,}" == \
        0xe55816904796341bf8535e25f6c8b647927fc946 ]] || fatal \
        'canary payment recipient must match the public web settlement recipient'

    mapfile -t canary_key_settings < <(
        sed -n 's/^[[:space:]]*DOCKET_CANARY_PRIVATE_KEY_FILE=//p' "${CANARY_CONFIG}"
    )
    (( ${#canary_key_settings[@]} <= 1 )) || fatal \
        'canary config must name at most one payment key'
    canary_key_configured=0
    if (( ${#canary_key_settings[@]} == 1 )); then
        [[ "${canary_key_settings[0]}" == /etc/docket/docket-canary-payment.key ]] || \
            fatal 'canary payment key must use /etc/docket/docket-canary-payment.key'
        [[ -f "${CANARY_KEY}" && ! -L "${CANARY_KEY}" ]] || fatal \
            'canary payment key must be a regular non-symlink file'
        [[ "$(stat -c '%a:%U:%G' "${CANARY_KEY}")" == '640:root:docket-canary' ]] || \
            fatal 'canary payment key must be mode 0640 and owned by root:docket-canary'
        canary_key_configured=1
    fi

    [[ -d "${DATA_DIRECTORY}" && ! -L "${DATA_DIRECTORY}" && \
        -f "${DATABASE_PATH}" && ! -L "${DATABASE_PATH}" ]] || fatal \
        'live database paths must be regular non-symlink targets'
    config_directory_acl=$(getfacl -cp -- "${CONFIG_DIRECTORY}") || fatal \
        'could not read the Docket configuration directory ACL'
    config_acl=$(getfacl -cp -- "${CANARY_CONFIG}") || fatal \
        'could not read the canary configuration ACL'
    state_directory_acl=$(getfacl -cp -- "${STATE_DIRECTORY}") || fatal \
        'could not read the Docket state directory ACL'
    token_acl=$(getfacl -cp -- "${CANARY_TOKEN}") || fatal \
        'could not read the shared canary token ACL'
    data_acl=$(getfacl -cp -- "${DATA_DIRECTORY}") || fatal \
        'could not read the live data directory ACL'
    database_acl=$(getfacl -cp -- "${DATABASE_PATH}") || fatal \
        'could not read the live database ACL'
    require_exact_acl "${config_directory_acl}" 'Docket configuration directory' \
        'user::rwx' 'user:docket-canary:--x' 'group::r-x' 'mask::r-x' 'other::---'
    require_exact_acl "${config_acl}" 'canary configuration' \
        'user::rw-' 'group::r--' 'other::---'
    require_exact_acl "${state_directory_acl}" 'Docket state directory' \
        'user::rwx' 'user:docket-canary:--x' 'group::r-x' 'mask::r-x' 'other::---'
    require_exact_acl "${token_acl}" 'shared canary token' \
        'user::rw-' 'user:docket-canary:r--' 'group::r--' 'mask::r--' 'other::---'
    require_exact_acl "${data_acl}" 'live data directory' \
        'user::rwx' 'user:docket:rwx' 'user:docket-canary:rwx' 'group::r-x' \
        'mask::rwx' 'other::---' 'default:user::rwx' 'default:user:docket:rwx' \
        'default:user:docket-canary:rwx' 'default:group::r-x' 'default:mask::rwx' \
        'default:other::---'
    require_exact_acl "${database_acl}" 'live database' \
        'user::rw-' 'user:docket:rw-' 'user:docket-canary:rw-' 'group::r--' \
        'mask::rw-' 'other::---'

    run_canary_test -r "${CANARY_CONFIG}" || fatal \
        'canary signer cannot read its configuration'
    run_canary_test -r "${CANARY_TOKEN}" || fatal \
        'canary signer cannot read the shared token'
    if ! run_canary_test -x "${CONFIG_DIRECTORY}" || \
        ! run_canary_test -x "${STATE_DIRECTORY}" || \
        ! run_canary_test -r "${DATABASE_PATH}" || \
        ! run_canary_test -w "${DATABASE_PATH}" || \
        ! run_canary_test -w "${DATA_DIRECTORY}" || \
        ! run_canary_test -x "${DATA_DIRECTORY}"; then
        fatal 'canary signer cannot read and write the live database'
    fi
    if "${RUNUSER_COMMAND}" -u docket -- test -r "${CANARY_CONFIG}"; then
        fatal 'docket web user can read canary configuration'
    fi
    if (( canary_key_configured )); then
        key_acl=$(getfacl -cp -- "${CANARY_KEY}") || fatal \
            'could not read the canary payment key ACL'
        require_exact_acl "${key_acl}" 'canary payment key' \
            'user::rw-' 'group::r--' 'other::---'
        run_canary_test -r "${CANARY_KEY}" || fatal \
            'canary signer cannot read its payment key'
        if "${RUNUSER_COMMAND}" -u docket -- test -r "${CANARY_KEY}"; then
            fatal 'docket web user can read canary payment key'
        fi
    fi
fi
if [[ -e "${JOURNALD_TARGET}" ]] && \
    { [[ ! -f "${JOURNALD_TARGET}" ]] || \
        ! cmp -s "${SCRIPT_DIR}/journald-docket.conf" "${JOURNALD_TARGET}"; }; then
    fatal "existing journald config differs: ${JOURNALD_TARGET}"
fi

STAMP=${DOCKET_RELEASE_TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}
[[ "${STAMP}" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || fatal \
    'DOCKET_RELEASE_TIMESTAMP must use YYYYMMDDTHHMMSSZ'
readonly STAMP
readonly STAGE="$(root_path "/opt/docket.stage-${COMMIT12}")"
readonly BACKUP="$(root_path "/opt/docket.bak-${STAMP}")"
readonly FAILED_RELEASE="$(root_path "/opt/docket.failed-${STAMP}-${COMMIT12}")"
readonly UNIT_BACKUP="$(root_path "/opt/docket-unit-backups/${STAMP}-${COMMIT12}")"
readonly DATABASE_BACKUP="${DATABASE_BACKUP_ROOT}/agents-${STAMP}.sqlite3"
readonly DATABASE_BACKUP_PARTIAL="${DATABASE_BACKUP}.partial"
if [[ -e "${STAGE}" || -L "${STAGE}" ]]; then
    [[ -d "${STAGE}" && ! -L "${STAGE}" ]] || fatal \
        "stale release stage is invalid: ${STAGE}"
    if (( ! DRY_RUN )); then
        [[ "$(stat -c '%U:%G' "${STAGE}")" == root:root ]] || fatal \
            "stale release stage must be owned by root:root: ${STAGE}"
    fi
    printf 'Removing stale release stage: %s\n' "${STAGE}"
    run_fs rm -rf -- "${STAGE}"
fi
[[ ! -e "${BACKUP}" ]] || fatal "backup already exists: ${BACKUP}"
[[ ! -e "${FAILED_RELEASE}" ]] || fatal "failed-release target exists: ${FAILED_RELEASE}"
[[ ! -e "${DATABASE_BACKUP}" ]] || fatal \
    "database backup already exists: ${DATABASE_BACKUP}"
[[ ! -e "${DATABASE_BACKUP_PARTIAL}" ]] || fatal \
    "partial database backup already exists: ${DATABASE_BACKUP_PARTIAL}"
[[ -d "${OPT_DOCKET}" ]] || fatal "current release is missing: ${OPT_DOCKET}"
[[ -f "${DATABASE_PATH}" ]] || fatal "runtime database is missing: ${DATABASE_PATH}"

if (( DRY_RUN )); then
    [[ -f "${OPT_DOCKET}/.venv.target" ]] || fatal \
        "dry-run current release lacks .venv.target"
    PREVIOUS_VENV_TARGET="$(<"${OPT_DOCKET}/.venv.target")"
else
    [[ -L "${OPT_DOCKET}/.venv" ]] || fatal "current release .venv is not a symlink"
    PREVIOUS_VENV_TARGET="$(readlink -- "${OPT_DOCKET}/.venv")"
fi
[[ -n "${PREVIOUS_VENV_TARGET}" ]] || fatal 'current release .venv target is empty'
readonly PREVIOUS_VENV_TARGET

STAGE_CREATED=0
cleanup_stage() {
    if (( STAGE_CREATED )) && [[ -e "${STAGE}" || -L "${STAGE}" ]]; then
        trace_command rm -rf -- "${STAGE}"
        rm -rf -- "${STAGE}"
    fi
}
on_stage_exit() {
    local status=$?
    trap - EXIT
    if (( status != 0 )); then
        set +e
        cleanup_stage
    fi
    exit "${status}"
}
trap on_stage_exit EXIT

STAGE_CREATED=1
run_fs install -d -m 0755 "${STAGE}/deploy"
run_fs "${COPY_COMMAND}" -a "${SCRIPT_DIR}/." "${STAGE}/deploy/"
run_fs cp -- "${MANIFEST}" "${STAGE}/release-manifest.json"
trace_command printf '%s\\n' "${SOURCE_COMMIT}" '>' "${STAGE}/RELEASE-commit.txt"
printf '%s\n' "${SOURCE_COMMIT}" >"${STAGE}/RELEASE-commit.txt"
trace_command printf '%s  %s\\n' "${EXPECTED_WHEEL_SHA}" "$(basename -- "${WHEEL}")" \
    '>' "${STAGE}/WHEEL-sha256.txt"
printf '%s  %s\n' "${EXPECTED_WHEEL_SHA}" "$(basename -- "${WHEEL}")" \
    >"${STAGE}/WHEEL-sha256.txt"
trace_command printf '%s\\n' "${RUNTIME_LOCK_SHA}" '>' \
    "${STAGE}/RUNTIME-LOCK-sha256.txt"
printf '%s\n' "${RUNTIME_LOCK_SHA}" >"${STAGE}/RUNTIME-LOCK-sha256.txt"

declare -A UNIT_EXISTED=()
declare -A TIMER_EXISTED=()
declare -A TIMER_WAS_ENABLED=()
declare -A TIMER_WAS_ACTIVE=()
APP_STOP_ATTEMPTED=0
APP_STOPPED=0
BACKUP_MOVED=0
SWAPPED=0
UNITS_TOUCHED=0
TIMER_STATE_DIRTY=0
RELEASE_OK=0

run_timer_systemctl() {
    trace_command systemctl "$@"
    if (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_SYSTEMCTL:-}" ]]; then
        "${SYSTEMCTL_COMMAND}" "$@"
    fi
}

atomic_venv_link() {
    local target=$1
    local link=$2
    local temporary="${link}.new-${COMMIT12}"
    if (( DRY_RUN )); then
        trace_command ln -sfn "${target}" "${temporary}"
        printf '%s\n' "${target}" >"${temporary}.target"
        trace_command mv -Tf "${temporary}" "${link}"
        mv -Tf "${temporary}.target" "${link}.target"
    else
        [[ ! -e "${temporary}" && ! -L "${temporary}" ]] || return 1
        run_fs ln -sfn "${target}" "${temporary}"
        run_fs mv -Tf "${temporary}" "${link}"
    fi
}

create_database_backup() {
    local backup_output backup_status
    trace_command install -d -o root -g root -m 0700 "${DATABASE_BACKUP_ROOT}"
    if (( DRY_RUN )); then
        install -d "${DATABASE_BACKUP_ROOT}"
    else
        install -d -o root -g root -m 0700 "${DATABASE_BACKUP_ROOT}"
    fi
    # sqlite_backup.py performs the online backup, PRAGMA quick_check and durable publish.
    trace_command "${BACKUP_PYTHON}" "${SCRIPT_DIR}/sqlite_backup.py" \
        "${DATABASE_PATH}" "${DATABASE_BACKUP}"
    set +e
    backup_output="$(
        (
            umask 077
            "${BACKUP_PYTHON}" "${SCRIPT_DIR}/sqlite_backup.py" \
                "${DATABASE_PATH}" "${DATABASE_BACKUP}"
        ) 2>&1
    )"
    backup_status=$?
    set -e
    if (( backup_status != 0 )); then
        fatal "SQLite backup failed: ${backup_output}"
    fi
    [[ -f "${DATABASE_BACKUP}" ]] || fatal \
        "SQLite backup did not create ${DATABASE_BACKUP}"
    if (( ! DRY_RUN )); then
        [[ "$(stat -c '%a:%U:%G' "${DATABASE_BACKUP}")" == '600:root:root' ]] || \
            fatal 'SQLite backup must be mode 0600 and owned by root:root'
    fi
    printf 'Database backup verified: %s (chmod 0600, durably published).\n' \
        "${DATABASE_BACKUP}"
}

wait_for_health() {
    local attempts=30
    local attempt
    if (( DRY_RUN )); then
        attempts=${DOCKET_RELEASE_HEALTH_ATTEMPTS:-30}
    fi
    [[ "${attempts}" =~ ^[1-9][0-9]*$ ]] || return 1
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/health
        if "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/health 2>/dev/null | \
            "${JSON_PYTHON}" -c \
                'import json,sys; value=json.load(sys.stdin); raise SystemExit(value.get("status") != "ok")' \
                2>/dev/null; then
            printf 'Health accepted on attempt %s of %s.\n' "${attempt}" "${attempts}"
            return 0
        fi
        if (( attempt < attempts )); then
            run_host sleep 1
        fi
    done
    return 1
}

restore_units() {
    local name target saved destination
    if (( UNITS_TOUCHED )); then
        for name in "${UNIT_NAMES[@]}"; do
            target="${SYSTEMD_ROOT}/${name}"
            saved="${UNIT_BACKUP}/${name}"
            if [[ "${UNIT_EXISTED[${name}]:-0}" == 1 ]]; then
                install_file "${saved}" "${target}" || return 1
            elif [[ -e "${target}" ]]; then
                destination="${FAILED_RELEASE}/installed-units/${name}"
                run_fs install -d -m 0755 "$(dirname -- "${destination}")" || return 1
                run_fs mv -- "${target}" "${destination}" || return 1
            fi
        done
        run_host systemctl daemon-reload || return 1
    fi
    (( TIMER_STATE_DIRTY )) || return 0
    for name in "${TIMER_NAMES[@]}"; do
        [[ "${TIMER_EXISTED[${name}]:-0}" == 1 ]] || continue
        if [[ "${TIMER_WAS_ENABLED[${name}]:-0}" == 1 ]]; then
            run_timer_systemctl enable "${name}" || return 1
        else
            run_timer_systemctl disable "${name}" || return 1
        fi
        if [[ "${TIMER_WAS_ACTIVE[${name}]:-0}" == 1 ]]; then
            run_timer_systemctl start "${name}" || return 1
        else
            run_timer_systemctl stop "${name}" || return 1
        fi
    done
}

rollback() {
    local rollback_ok=1
    printf 'Release failed after runtime state changed: %s\n' "${FAILURE_REASON}" >&2
    if (( APP_STOPPED || BACKUP_MOVED || SWAPPED )); then
        run_host systemctl stop docket.service || rollback_ok=0
    fi
    if (( SWAPPED )) && [[ -d "${OPT_DOCKET}" ]]; then
        run_fs mv -- "${OPT_DOCKET}" "${FAILED_RELEASE}" || rollback_ok=0
    fi
    if (( BACKUP_MOVED )) && [[ -d "${BACKUP}" ]]; then
        run_fs mv -- "${BACKUP}" "${OPT_DOCKET}" || rollback_ok=0
        atomic_venv_link "${PREVIOUS_VENV_TARGET}" "${OPT_DOCKET}/.venv" || rollback_ok=0
    fi
    restore_units || rollback_ok=0
    if (( APP_STOP_ATTEMPTED || APP_STOPPED || BACKUP_MOVED || SWAPPED )); then
        run_host systemctl start docket.service || rollback_ok=0
    fi
    if (( ! APP_STOP_ATTEMPTED && ! APP_STOPPED && ! BACKUP_MOVED && ! SWAPPED && rollback_ok )); then
        printf '%s\n' 'Rollback completed and the captured timer state was restored.' >&2
    elif (( rollback_ok )) && wait_for_health; then
        printf '%s\n' 'Rollback completed and the previous release is healthy.' >&2
    else
        printf '%s\n' 'Rollback attempted but the previous release did not pass health.' >&2
    fi
}

on_exit() {
    local status=$?
    trap - EXIT
    if (( status != 0 && ! RELEASE_OK )); then
        set +e
        if (( APP_STOP_ATTEMPTED || APP_STOPPED || BACKUP_MOVED || SWAPPED || TIMER_STATE_DIRTY )); then
            rollback
        fi
        cleanup_stage
    fi
    exit "${status}"
}
trap on_exit EXIT

refuse_range_capture_window() {
    local now_utc=${DOCKET_RELEASE_NOW_UTC:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}
    [[ "${now_utc}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || \
        fatal 'release UTC clock must use YYYY-MM-DDTHH:MM:SSZ'
    if [[ "${now_utc}" > '2026-08-26T12:02:54Z' && \
        "${now_utc}" < '2026-08-26T12:10:06Z' ]]; then
        fatal 'Range capture activation window is closed to releases through 2026-08-26T12:10:05Z'
    fi
}

refuse_yield_v6_capture_window() {
    local now_utc=${DOCKET_RELEASE_NOW_UTC:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}
    [[ "${now_utc}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || \
        fatal 'release UTC clock must use YYYY-MM-DDTHH:MM:SSZ'
    if [[ "${now_utc}" > '2026-09-03T11:49:54Z' && \
        "${now_utc}" < '2026-09-03T12:03:06Z' ]]; then
        fatal 'Yield v3-06 capture activation window is closed to releases through 2026-09-03T12:03:05Z'
    fi
}

refuse_range_v7_capture_window() {
    local now_utc=${DOCKET_RELEASE_NOW_UTC:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}
    [[ "${now_utc}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || \
        fatal 'release UTC clock must use YYYY-MM-DDTHH:MM:SSZ'
    if [[ "${now_utc}" > '2026-09-05T11:49:54Z' && \
        "${now_utc}" < '2026-09-05T12:03:06Z' ]]; then
        fatal 'Range v3-07 capture activation window is closed to releases through 2026-09-05T12:03:05Z'
    fi
}

refuse_yield_v8_capture_window() {
    local now_utc=${DOCKET_RELEASE_NOW_UTC:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}
    [[ "${now_utc}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || \
        fatal 'release UTC clock must use YYYY-MM-DDTHH:MM:SSZ'
    if [[ "${now_utc}" > '2026-09-06T11:49:54Z' && \
        "${now_utc}" < '2026-09-06T12:03:06Z' ]]; then
        fatal 'Yield v3-08 capture activation window is closed to releases through 2026-09-06T12:03:05Z'
    fi
}

refuse_range_capture_window
refuse_yield_v6_capture_window
refuse_range_v7_capture_window
refuse_yield_v8_capture_window
trace_command python3 "${SCRIPT_DIR}/release_bundle.py" verify "${MANIFEST}" \
    "${SCRIPT_DIR}" "${VERIFY_SECURITY_ARGS[@]}"
set +e
manifest_reverification="$({
    python3 "${SCRIPT_DIR}/release_bundle.py" verify "${MANIFEST}" \
        "${SCRIPT_DIR}" "${VERIFY_SECURITY_ARGS[@]}"
} 2>&1)"
manifest_reverification_status=$?
set -e
(( manifest_reverification_status == 0 )) || fatal \
    "release manifest reverification failed before mutation: ${manifest_reverification}"
manifest_reverification=${manifest_reverification//$'\r'/}
[[ "${manifest_reverification}" == "${manifest_verification}" ]] || fatal \
    'release artifact bindings changed before mutation'
printf '%s\n' 'Release manifest reverified before mutation.'

for name in "${TIMER_NAMES[@]}"; do
    if (( DRY_RUN )) && [[ -z "${DOCKET_RELEASE_SYSTEMCTL:-}" ]]; then
        TIMER_EXISTED["${name}"]=1
        TIMER_WAS_ENABLED["${name}"]=1
        TIMER_WAS_ACTIVE["${name}"]=1
    else
        trace_command systemctl show --property=LoadState --value "${name}"
        if ! load_state="$(
            "${SYSTEMCTL_COMMAND}" show --property=LoadState --value "${name}"
        )"; then
            fatal "could not read the installed state of ${name}"
        fi
        if [[ "${load_state}" == not-found ]]; then
            TIMER_EXISTED["${name}"]=0
            TIMER_WAS_ENABLED["${name}"]=0
            TIMER_WAS_ACTIVE["${name}"]=0
            continue
        fi
        [[ -n "${load_state}" ]] || fatal "systemd returned no load state for ${name}"
        TIMER_EXISTED["${name}"]=1
        trace_command systemctl is-enabled --quiet "${name}"
        if "${SYSTEMCTL_COMMAND}" is-enabled --quiet "${name}"; then
            TIMER_WAS_ENABLED["${name}"]=1
        else
            TIMER_WAS_ENABLED["${name}"]=0
        fi
        trace_command systemctl is-active --quiet "${name}"
        if "${SYSTEMCTL_COMMAND}" is-active --quiet "${name}"; then
            TIMER_WAS_ACTIVE["${name}"]=1
        else
            TIMER_WAS_ACTIVE["${name}"]=0
        fi
    fi
done

TIMER_STATE_DIRTY=1
for name in "${TIMER_NAMES[@]}"; do
    [[ "${TIMER_EXISTED[${name}]:-0}" == 1 ]] || continue
    run_host systemctl stop "${name}"
    if (( DRY_RUN )) && [[ -n "${DOCKET_RELEASE_SYSTEMCTL:-}" ]]; then
        "${SYSTEMCTL_COMMAND}" stop "${name}"
    fi
done
for name in "${TIMER_NAMES[@]}"; do
    service="${name%.timer}.service"
    trace_command systemctl is-active --quiet "${service}"
    if { (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_SYSTEMCTL:-}" ]]; } && \
        "${SYSTEMCTL_COMMAND}" is-active --quiet "${service}"; then
        fatal "${service} is active after release timers were stopped"
    fi
done
create_database_backup
APP_STOP_ATTEMPTED=1
trace_command systemctl stop docket.service
if { (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_SYSTEMCTL:-}" ]]; } && \
    ! "${SYSTEMCTL_COMMAND}" stop docket.service; then
    fatal 'could not stop docket.service'
fi
APP_STOPPED=1
run_fs mv -- "${OPT_DOCKET}" "${BACKUP}"
BACKUP_MOVED=1
run_fs mv -- "${STAGE}" "${OPT_DOCKET}"
SWAPPED=1
atomic_venv_link "${VENV}" "${OPT_DOCKET}/.venv" || fatal \
    'atomic .venv symlink flip failed'

run_fs install -d -m 0755 "${SYSTEMD_ROOT}" "${UNIT_BACKUP}"
for name in "${UNIT_NAMES[@]}"; do
    target="${SYSTEMD_ROOT}/${name}"
    if [[ -e "${target}" ]]; then
        UNIT_EXISTED["${name}"]=1
        run_fs cp -a -- "${target}" "${UNIT_BACKUP}/${name}"
    else
        UNIT_EXISTED["${name}"]=0
    fi
done
UNITS_TOUCHED=1

capture_target="${SYSTEMD_ROOT}/docket-v3-capture.timer"
capture_source="${OPT_DOCKET}/deploy/systemd/docket-v3-capture.timer"
if [[ -f "${capture_target}" ]] && \
    grep -Eq '^OnCalendar=.*2026-08-21' "${capture_target}"; then
    printf '%s\n' 'Unit differs: docket-v3-capture.timer (retiring Aug-21 schedule)'
    set +e
    diff -u "${capture_target}" "${capture_source}"
    diff_status=$?
    set -e
    (( diff_status <= 1 )) || fatal 'could not diff the installed capture timer'
    run_host systemctl disable --now docket-v3-capture.timer
    run_fs mv -- "${capture_target}" \
        "${UNIT_BACKUP}/docket-v3-capture.timer.retired-2026-08-21"
fi

for name in "${UNIT_NAMES[@]}"; do
    source="${OPT_DOCKET}/deploy/systemd/${name}"
    target="${SYSTEMD_ROOT}/${name}"
    if [[ -f "${target}" ]] && cmp -s "${source}" "${target}"; then
        printf 'Unit unchanged: %s\n' "${name}"
        continue
    fi
    if [[ -f "${target}" ]]; then
        printf 'Unit differs: %s\n' "${name}"
        set +e
        diff -u "${target}" "${source}"
        diff_status=$?
        set -e
        (( diff_status <= 1 )) || fatal "could not diff unit ${name}"
    else
        printf 'Installing new unit: %s\n' "${name}"
    fi
    install_file "${source}" "${target}"
done

run_host systemctl daemon-reload
if [[ ! -e "${JOURNALD_TARGET}" ]]; then
    run_fs install -d -m 0755 "${JOURNALD_ROOT}"
    install_file "${OPT_DOCKET}/deploy/journald-docket.conf" "${JOURNALD_TARGET}"
else
    printf '%s\n' 'Journald config already exists; preserving it.'
fi
run_host install -d -m 2755 -o root -g systemd-journal /var/log/journal
run_host systemd-tmpfiles --create --prefix /var/log/journal
run_host systemctl restart systemd-journald
run_host "${JOURNALCTL_COMMAND}" --flush
printf '%s\n' \
    'Persistent journald configured; the former volatile journal was lost at this restart.'
trace_command "${JOURNALCTL_COMMAND}" --header
if (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_JOURNALCTL:-}" ]]; then
    if ! journal_header="$("${JOURNALCTL_COMMAND}" --header 2>&1)"; then
        fatal 'persistent journald verification failed: journalctl --header failed'
    fi
    printf '%s\n' "${journal_header}"
    grep -Fq '/var/log/journal/' <<<"${journal_header}" || fatal \
        'persistent journald verification failed: no /var/log/journal file was found'
fi

run_host systemctl enable --now docket.service
wait_for_health || fatal 'new release did not pass /health within 30 seconds'

trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/stats
if ! "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/stats | "${JSON_PYTHON}" -c '
import json, sys
body = json.load(sys.stdin)
required = {"coverage", "refresh_status", "registry_total", "probe_method"}
coverage = {"snapshot_id", "captured_at", "snapshot_age_seconds", "sampled", "expected", "dropped", "complete", "population"}
raise SystemExit(not required <= body.keys() or not coverage <= body.get("coverage", {}).keys())
'; then
    fatal 'served /stats is missing its release contract fields'
fi

trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/services
if ! "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/services | "${JSON_PYTHON}" -c '
import json, sys
body = json.load(sys.stdin)
top = {"services", "total", "category", "ordering", "declaration"}
service = {"service_id", "paid_stock", "stock_status", "admission"}
admission = {"fresh_paired_benchmark", "cold_canary", "decision_grade_presenter", "true_settlement"}
rows = body.get("services", [])
raise SystemExit(not top <= body.keys() or not rows or any(not service <= row.keys() or not admission <= row.get("admission", {}).keys() for row in rows))
'; then
    fatal 'served /services is missing its release contract fields'
fi

trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/services
if ! "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/services | "${JSON_PYTHON}" -c '
import json, sys
body = json.load(sys.stdin)
rows = body.get("services")
expected = {
    "grid-operator",
    "health-guard",
    "range-doctor",
    "solvent-signal",
    "warden-scan",
    "yield-router",
}
service_ids = [row.get("service_id") for row in rows] if isinstance(rows, list) else []
raise SystemExit(
    len(service_ids) != len(expected)
    or set(service_ids) != expected
    or body.get("total") != len(expected)
)
'; then
    fatal 'served /services does not match the release inventory'
fi

trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/categories
if ! "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/categories | "${JSON_PYTHON}" -c '
import json, sys
body = json.load(sys.stdin)
rows = body.get("categories")
expected = {"rebalancing", "grid_trading", "yield_optimisation", "health_factor"}
categories = [row.get("category") for row in rows] if isinstance(rows, list) else []
raise SystemExit(len(categories) != len(expected) or set(categories) != expected)
'; then
    fatal 'served /categories does not match the release inventory'
fi

trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/advantage/v3.json
if ! "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/advantage/v3.json | "${JSON_PYTHON}" -c '
import json, sys
body = json.load(sys.stdin)
families = body.get("families")
summary = body.get("summary")
n_families = summary.get("n_families") if isinstance(summary, dict) else None
raise SystemExit(not isinstance(families, list) or not isinstance(n_families, int) or isinstance(n_families, bool) or n_families != len(families))
'; then
    fatal 'served /advantage/v3.json is missing its release contract fields'
fi

trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/advantage/v3.json
if ! "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/advantage/v3.json | "${JSON_PYTHON}" -c '
import json, sys
body = json.load(sys.stdin)
families = body.get("families")
expected = {
    "v3-01-range-doctor": "superseded_before_input_lock",
    "v3-02-yield-router": "abandoned_after_failed_primary",
    "v3-03-warden-security": "superseded_before_input_lock",
    "v3-04-warden-security": "complete_unscored",
    "v3-05-range-doctor": "locked_not_run",
    "v3-06-yield-router-assisted": "registered_waiting_for_inputs",
    "v3-07-range-doctor": "registered_waiting_for_inputs",
    "v3-08-yield-router": "registered_waiting_for_inputs",
    "v3-09-health-guard": "registered_waiting_for_inputs",
}
observed = (
    {row.get("spec_id"): row.get("state") for row in families}
    if isinstance(families, list)
    else {}
)
summary = body.get("summary")
n_families = summary.get("n_families") if isinstance(summary, dict) else None
raise SystemExit(
    not isinstance(families, list)
    or len(families) != len(expected)
    or observed != expected
    or n_families != len(expected)
)
'; then
    fatal 'served /advantage/v3.json does not match the release state'
fi

trace_command "${CURL_COMMAND}" -fsS -H 'Accept: text/html' http://127.0.0.1:8090/
if ! "${CURL_COMMAND}" -fsS -H 'Accept: text/html' \
    http://127.0.0.1:8090/ | grep -Fq '<title>Docket'; then
    fatal 'served homepage smoke failed'
fi

trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/static/style.css
if ! "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/static/style.css | \
    grep -F ':root {' >/dev/null; then
    fatal 'served static asset smoke failed'
fi

trace_command "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/api/status
if ! "${CURL_COMMAND}" -fsS http://127.0.0.1:8090/api/status | \
    DOCKET_EXPECTED_COMMIT="${SOURCE_COMMIT}" "${JSON_PYTHON}" -c '
import json, os, sys
body = json.load(sys.stdin)
raise SystemExit(
    body.get("status") not in {"ok", "degraded"}
    or body.get("deployed_commit") != os.environ["DOCKET_EXPECTED_COMMIT"]
)
'; then
    fatal 'served /api/status does not report this release as serving'
fi

trace_command "${CURL_COMMAND}" -fsS -H 'Accept: text/html' http://127.0.0.1:8090/status
if ! "${CURL_COMMAND}" -fsS -H 'Accept: text/html' \
    http://127.0.0.1:8090/status | grep -Fq '<title>Docket'; then
    fatal 'served status page smoke failed'
fi

refuse_range_capture_window
refuse_yield_v6_capture_window
refuse_range_v7_capture_window
refuse_yield_v8_capture_window
for name in "${TIMER_NAMES[@]}"; do
    if [[ "${name}" == docket-canary.timer && \
        "${TIMER_WAS_ENABLED[${name}]:-0}" != 1 ]]; then
        run_host systemctl disable --now "${name}"
    else
        run_host systemctl enable --now "${name}"
    fi
done

RELEASE_OK=1
printf 'Release complete: %s (%s), wheel %s.\n' \
    "${SOURCE_COMMIT}" "${WHEEL_VERSION}" "${EXPECTED_WHEEL_SHA}"
