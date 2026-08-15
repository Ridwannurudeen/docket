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
    "${DROPIN_TARGET}"; do
    backup_existing "${target}"
done

install -o root -g root -m 0644 "${SERVICE_SOURCE}" "${SERVICE_TARGET}"
install -o root -g root -m 0644 "${TIMER_SOURCE}" "${TIMER_TARGET}"

if [[ ! -e "${CONFIG_TARGET}" ]]; then
    install -o root -g docket -m 0640 "${CONFIG_SOURCE}" "${CONFIG_TARGET}"
else
    chown root:docket "${CONFIG_TARGET}"
    chmod 0640 "${CONFIG_TARGET}"
fi

if [[ ! -e "${TOKEN_TARGET}" ]]; then
    TOKEN_TEMP="$(mktemp /etc/docket/.docket-canary.token.XXXXXX)"
    "${APP_PYTHON}" -c \
        'import pathlib, secrets, sys; pathlib.Path(sys.argv[1]).write_text(secrets.token_hex(32) + "\n", encoding="ascii")' \
        "${TOKEN_TEMP}"
    install -o root -g docket -m 0640 "${TOKEN_TEMP}" "${TOKEN_TARGET}"
    rm -f -- "${TOKEN_TEMP}"
    TOKEN_TEMP=
else
    chown root:docket "${TOKEN_TARGET}"
    chmod 0640 "${TOKEN_TARGET}"
fi

DROPIN_TEMP="$(mktemp)"
printf '%s\n' \
    '[Service]' \
    'Environment=DOCKET_CANARY_TOKEN_FILE=/etc/docket/docket-canary.token' \
    >"${DROPIN_TEMP}"
install -o root -g root -m 0644 "${DROPIN_TEMP}" "${DROPIN_TARGET}"
rm -f -- "${DROPIN_TEMP}"
DROPIN_TEMP=

systemctl daemon-reload
systemctl enable docket-canary.timer

printf '%s\n' \
    "Canary units installed. Existing targets were backed up under ${BACKUP_ROOT}." \
    "Operator configuration is ${CONFIG_TARGET}; the shared token is ${TOKEN_TARGET}." \
    'No service was started or restarted.' \
    'After reviewing the config and the staged release, run:' \
    '  systemctl restart docket.service' \
    '  systemctl start docket-canary.timer' \
    'Then verify scheduling without exposing configuration values:' \
    '  systemctl list-timers docket-canary.timer'

