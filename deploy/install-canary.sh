#!/usr/bin/env bash
set -euo pipefail
umask 077

readonly APP_PYTHON=/opt/docket/.venv/bin/python
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SERVICE_SOURCE="${SCRIPT_DIR}/systemd/docket-canary.service"
readonly TIMER_SOURCE="${SCRIPT_DIR}/systemd/docket-canary.timer"
readonly CONFIG_SOURCE="${SCRIPT_DIR}/docket-canary.conf.example"

readonly SERVICE_TARGET=/etc/systemd/system/docket-canary.service
readonly TIMER_TARGET=/etc/systemd/system/docket-canary.timer
readonly CONFIG_TARGET=/etc/docket/docket-canary.conf
readonly TOKEN_TARGET=/etc/docket/docket-canary.token
readonly PAYMENT_KEY_TARGET=/etc/docket/docket-canary-payment.key
readonly CONFIG_DIRECTORY=/etc/docket
readonly STATE_DIRECTORY=/var/lib/docket
readonly DATA_TARGET=/var/lib/docket/data
readonly DATABASE_TARGET=/var/lib/docket/data/agents.sqlite3
readonly DROPIN_TARGET=/etc/systemd/system/docket.service.d/10-canary-token.conf
readonly BACKUP_ROOT="/var/backups/docket-canary/$(date -u +%Y%m%dT%H%M%SZ)"

TOKEN_TEMP=
DROPIN_TEMP=
cleanup() {
    [[ -z "${TOKEN_TEMP}" ]] || rm -f -- "${TOKEN_TEMP}"
    [[ -z "${DROPIN_TEMP}" ]] || rm -f -- "${DROPIN_TEMP}"
}
trap cleanup EXIT

if [[ "${EUID}" -ne 0 ]]; then
    printf '%s\n' 'install-canary.sh must run as root.' >&2
    exit 1
fi

for source_path in "${SERVICE_SOURCE}" "${TIMER_SOURCE}" "${CONFIG_SOURCE}"; do
    if [[ ! -f "${source_path}" ]]; then
        printf 'Missing installation source: %s\n' "${source_path}" >&2
        exit 1
    fi
done
if [[ ! -x "${APP_PYTHON}" ]]; then
    printf 'The separately staged Docket environment is missing: %s\n' "${APP_PYTHON}" >&2
    exit 1
fi
if ! getent passwd docket >/dev/null || ! getent group docket >/dev/null; then
    printf '%s\n' 'The docket service account and group must already exist.' >&2
    exit 1
fi
if [[ ! -x /usr/sbin/nologin ]]; then
    printf '%s\n' 'The required /usr/sbin/nologin shell is missing.' >&2
    exit 1
fi
if ! command -v setfacl >/dev/null; then
    printf '%s\n' 'The setfacl command is required.' >&2
    exit 1
fi
if ! command -v getfacl >/dev/null; then
    printf '%s\n' 'The getfacl command is required.' >&2
    exit 1
fi

readonly RELEASE_LOCK_DIR=/run/docket
readonly RELEASE_LOCK=${RELEASE_LOCK_DIR}/release.lock
[[ -d /run && ! -L /run && "$(stat -c '%U:%G' /run)" == root:root ]] || {
    printf '%s\n' '/run must be a real root-owned directory.' >&2
    exit 1
}
run_mode=$(stat -c '%a' /run)
if (( (8#${run_mode} & 8#022) != 0 )); then
    printf '%s\n' '/run must not be group/world writable.' >&2
    exit 1
fi
if [[ ! -e "${RELEASE_LOCK_DIR}" && ! -L "${RELEASE_LOCK_DIR}" ]]; then
    install -d -o root -g root -m 0700 "${RELEASE_LOCK_DIR}"
fi
if [[ ! -d "${RELEASE_LOCK_DIR}" || -L "${RELEASE_LOCK_DIR}" || \
    "$(stat -c '%a:%U:%G' "${RELEASE_LOCK_DIR}")" != '700:root:root' ]]; then
    printf '%s\n' 'The release lock directory is unsafe.' >&2
    exit 1
fi
if [[ -e "${RELEASE_LOCK}" || -L "${RELEASE_LOCK}" ]]; then
    if [[ ! -f "${RELEASE_LOCK}" || -L "${RELEASE_LOCK}" || \
        "$(stat -c '%a:%U:%G' "${RELEASE_LOCK}")" != '600:root:root' ]]; then
        printf '%s\n' 'The release lock is unsafe.' >&2
        exit 1
    fi
fi
exec {RELEASE_LOCK_FD}>"${RELEASE_LOCK}"
flock -n "${RELEASE_LOCK_FD}" || {
    printf '%s\n' 'Another Docket release or canary installation is running.' >&2
    exit 1
}
chown root:root "${RELEASE_LOCK}"
chmod 0600 "${RELEASE_LOCK}"

timer_load_state=$(systemctl show --property=LoadState --value docket-canary.timer)
if [[ "${timer_load_state}" != not-found ]]; then
    systemctl disable --now docket-canary.timer
fi
if systemctl is-active --quiet docket-canary.service; then
    printf '%s\n' 'docket-canary.service is active; the timer remains disabled and no files were changed.' >&2
    exit 1
fi

if ! getent group docket-canary >/dev/null; then
    groupadd --system docket-canary
fi
if ! getent passwd docket-canary >/dev/null; then
    useradd --system --gid docket-canary --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin docket-canary
fi

validate_canary_identity() {
    local group_record user_record
    local group_name group_password group_id group_members
    local user_name user_password user_id user_group_id user_gecos user_home user_shell
    local uid_min gid_min canary_groups
    group_record=$(getent group docket-canary) || {
        printf '%s\n' 'The docket-canary system group is missing.' >&2
        exit 1
    }
    user_record=$(getent passwd docket-canary) || {
        printf '%s\n' 'The docket-canary system user is missing.' >&2
        exit 1
    }
    IFS=: read -r group_name group_password group_id group_members <<<"${group_record}"
    IFS=: read -r user_name user_password user_id user_group_id user_gecos user_home user_shell \
        <<<"${user_record}"
    uid_min=$(awk '$1 == "UID_MIN" { print $2; exit }' /etc/login.defs)
    gid_min=$(awk '$1 == "GID_MIN" { print $2; exit }' /etc/login.defs)
    canary_groups=$(id -nG docket-canary)
    if [[ "${group_name}" != docket-canary || ! "${group_id}" =~ ^[0-9]+$ || \
        -n "${group_members}" || "${canary_groups}" != docket-canary || \
        "${user_name}" != docket-canary || ! "${user_id}" =~ ^[0-9]+$ || \
        "${user_group_id}" != "${group_id}" || "${user_home}" != /nonexistent || \
        -e /nonexistent || -L /nonexistent || \
        "${user_shell}" != /usr/sbin/nologin || ! "${uid_min}" =~ ^[0-9]+$ || \
        ! "${gid_min}" =~ ^[0-9]+$ || "${user_id}" -ge "${uid_min}" || \
        "${group_id}" -ge "${gid_min}" ]]; then
        printf '%s\n' 'docket-canary must be a nologin, no-home system user with its matching system group.' >&2
        exit 1
    fi
    if id -nG docket | tr ' ' '\n' | grep -Fxq docket-canary; then
        printf '%s\n' 'docket must not be a member of docket-canary.' >&2
        exit 1
    fi
}
validate_canary_identity

if [[ ! -d "${DATA_TARGET}" || -L "${DATA_TARGET}" || \
    ! -f "${DATABASE_TARGET}" || -L "${DATABASE_TARGET}" ]]; then
    printf '%s\n' 'The live Docket data directory and database must be regular existing targets.' >&2
    exit 1
fi
for existing_target in "${CONFIG_TARGET}" "${TOKEN_TARGET}" "${PAYMENT_KEY_TARGET}"; do
    if [[ -e "${existing_target}" || -L "${existing_target}" ]]; then
        if [[ ! -f "${existing_target}" || -L "${existing_target}" ]]; then
            printf 'Existing canary material must be a regular non-symlink file: %s\n' \
                "${existing_target}" >&2
            exit 1
        fi
    fi
done

install -d -o root -g root -m 0700 "${BACKUP_ROOT}"
install -d -o root -g docket -m 0750 /etc/docket
install -d -o root -g root -m 0755 /etc/systemd/system/docket.service.d

backup_existing() {
    local target=$1
    local backup_target
    if [[ ! -e "${target}" && ! -L "${target}" ]]; then
        return
    fi
    backup_target="${BACKUP_ROOT}${target}"
    install -d -o root -g root -m 0700 "$(dirname -- "${backup_target}")"
    cp -a -- "${target}" "${backup_target}"
}

# Backups precede every replacement. Operator config and token contents are backed up too,
# even though repeat installs preserve them rather than replacing them.
for target in \
    "${SERVICE_TARGET}" \
    "${TIMER_TARGET}" \
    "${CONFIG_TARGET}" \
    "${TOKEN_TARGET}" \
    "${PAYMENT_KEY_TARGET}" \
    "${DROPIN_TARGET}"; do
    backup_existing "${target}"
done

install -o root -g root -m 0644 "${SERVICE_SOURCE}" "${SERVICE_TARGET}"
install -o root -g root -m 0644 "${TIMER_SOURCE}" "${TIMER_TARGET}"

if [[ ! -e "${CONFIG_TARGET}" && ! -L "${CONFIG_TARGET}" ]]; then
    install -o root -g docket-canary -m 0640 "${CONFIG_SOURCE}" "${CONFIG_TARGET}"
else
    if [[ ! -f "${CONFIG_TARGET}" || -L "${CONFIG_TARGET}" ]]; then
        printf '%s\n' 'The existing canary config must be a regular non-symlink file.' >&2
        exit 1
    fi
    chown root:docket-canary "${CONFIG_TARGET}"
    chmod 0640 "${CONFIG_TARGET}"
fi

if [[ ! -e "${TOKEN_TARGET}" && ! -L "${TOKEN_TARGET}" ]]; then
    TOKEN_TEMP="$(mktemp /etc/docket/.docket-canary.token.XXXXXX)"
    "${APP_PYTHON}" -c \
        'import pathlib, secrets, sys; pathlib.Path(sys.argv[1]).write_text(secrets.token_hex(32) + "\n", encoding="ascii")' \
        "${TOKEN_TEMP}"
    install -o root -g docket -m 0640 "${TOKEN_TEMP}" "${TOKEN_TARGET}"
    rm -f -- "${TOKEN_TEMP}"
    TOKEN_TEMP=
else
    if [[ ! -f "${TOKEN_TARGET}" || -L "${TOKEN_TARGET}" ]]; then
        printf '%s\n' 'The existing canary token must be a regular non-symlink file.' >&2
        exit 1
    fi
    chown root:docket "${TOKEN_TARGET}"
    chmod 0640 "${TOKEN_TARGET}"
fi

if [[ -e "${PAYMENT_KEY_TARGET}" || -L "${PAYMENT_KEY_TARGET}" ]]; then
    if [[ ! -f "${PAYMENT_KEY_TARGET}" || -L "${PAYMENT_KEY_TARGET}" ]]; then
        printf '%s\n' 'The canary payment key must be a regular non-symlink file.' >&2
        exit 1
    fi
    chown root:docket-canary "${PAYMENT_KEY_TARGET}"
    chmod 0640 "${PAYMENT_KEY_TARGET}"
fi

chown docket:docket "${STATE_DIRECTORY}" "${DATA_TARGET}" "${DATABASE_TARGET}"
chmod 0750 "${STATE_DIRECTORY}" "${DATA_TARGET}"
chmod 0640 "${DATABASE_TARGET}"
setfacl -b "${TOKEN_TARGET}" "${CONFIG_TARGET}" "${DATABASE_TARGET}"
if [[ -e "${PAYMENT_KEY_TARGET}" ]]; then
    setfacl -b "${PAYMENT_KEY_TARGET}"
fi
setfacl -b -k "${CONFIG_DIRECTORY}" "${STATE_DIRECTORY}" "${DATA_TARGET}"
setfacl -m u:docket-canary:--x "${CONFIG_DIRECTORY}" "${STATE_DIRECTORY}"
setfacl -m u:docket-canary:r-- "${TOKEN_TARGET}"
setfacl -m u:docket:rwx,u:docket-canary:rwx,o::--- "${DATA_TARGET}"
setfacl -m d:u:docket:rwx,d:u:docket-canary:rwx,d:o::--- "${DATA_TARGET}"
setfacl -m u:docket:rw-,u:docket-canary:rw-,o::--- "${DATABASE_TARGET}"

DROPIN_TEMP="$(mktemp)"
printf '%s\n' \
    '[Service]' \
    'Environment=DOCKET_ENABLE_SETTLEMENT=1' \
    'Environment=DOCKET_FACILITATOR_KIND=b402' \
    'Environment=DOCKET_FACILITATOR_URL=https://facilitatorv3.b402.ai/api/v1' \
    'Environment=DOCKET_PAY_TO=0xe55816904796341bf8535e25f6c8b647927fc946' \
    'Environment=DOCKET_CANARY_TOKEN_FILE=/etc/docket/docket-canary.token' \
    >"${DROPIN_TEMP}"
install -o root -g root -m 0644 "${DROPIN_TEMP}" "${DROPIN_TARGET}"
rm -f -- "${DROPIN_TEMP}"
DROPIN_TEMP=

systemctl daemon-reload

printf '%s\n' \
    "Canary units installed. Existing targets were backed up under ${BACKUP_ROOT}." \
    "Operator configuration is ${CONFIG_TARGET}; the shared token is ${TOKEN_TARGET}." \
    'The payment-bearing timer remains disabled and no service was started or restarted.' \
    'After reviewing the config, deploy the staged release.' \
    'Enable scheduled canaries only with separate owner approval.'
