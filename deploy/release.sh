#!/usr/bin/env bash
set -euo pipefail

export LC_ALL=C
umask 027

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
    shift
fi

if [[ $# -ne 3 ]]; then
    printf '%s\n' \
        'Usage: release.sh [--dry-run] <wheel> <40-hex-source-commit> <wheel-sha256>' >&2
    exit 2
fi

readonly WHEEL_ARGUMENT=$1
SOURCE_COMMIT=${2,,}
EXPECTED_WHEEL_SHA=${3,,}
[[ "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || {
    printf '%s\n' 'Source commit must be exactly 40 hexadecimal characters.' >&2
    exit 2
}
[[ "${EXPECTED_WHEEL_SHA}" =~ ^[0-9a-f]{64}$ ]] || {
    printf '%s\n' 'Wheel SHA-256 must be exactly 64 hexadecimal characters.' >&2
    exit 2
}

readonly SOURCE_COMMIT EXPECTED_WHEEL_SHA
readonly COMMIT12=${SOURCE_COMMIT:0:12}
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

[[ -f "${WHEEL_ARGUMENT}" ]] || fatal "wheel does not exist: ${WHEEL_ARGUMENT}"
WHEEL="$(cd -- "$(dirname -- "${WHEEL_ARGUMENT}")" && pwd -P)/$(basename -- "${WHEEL_ARGUMENT}")"
readonly WHEEL

trace_command sha256sum "${WHEEL}"
ACTUAL_WHEEL_SHA="$(sha256sum "${WHEEL}" | awk '{ print tolower($1) }')"
[[ "${ACTUAL_WHEEL_SHA}" == "${EXPECTED_WHEEL_SHA}" ]] || fatal \
    "wheel SHA-256 mismatch: got ${ACTUAL_WHEEL_SHA}, expected ${EXPECTED_WHEEL_SHA}"
readonly ACTUAL_WHEEL_SHA

trace_command python3 - "${WHEEL}"
set +e
wheel_metadata="$({ python3 - "${WHEEL}" <<'PY'
import email.parser
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    metadata_paths = [
        name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
    ]
    if len(metadata_paths) != 1:
        raise SystemExit("wheel must contain exactly one dist-info/METADATA file")
    metadata = email.parser.Parser().parsestr(
        archive.read(metadata_paths[0]).decode("utf-8")
    )
    print(metadata.get("Name", ""))
    print(metadata.get("Version", ""))
PY
} 2>&1)"
metadata_status=$?
set -e
(( metadata_status == 0 )) || fatal "wheel metadata check failed: ${wheel_metadata}"
wheel_metadata=${wheel_metadata//$'\r'/}
mapfile -t metadata_lines <<<"${wheel_metadata}"
WHEEL_NAME=${metadata_lines[0]:-}
WHEEL_VERSION=${metadata_lines[1]:-}
[[ "${WHEEL_NAME,,}" == docket && -n "${WHEEL_VERSION}" ]] || fatal \
    "wheel metadata must name docket and carry a version"
readonly WHEEL_NAME WHEEL_VERSION

readonly OPT_ROOT="$(root_path /opt)"
readonly OPT_DOCKET="$(root_path /opt/docket)"
readonly VENV_ROOT="$(root_path /opt/docket-venvs)"
readonly VENV="${VENV_ROOT}/${COMMIT12}"
readonly SYSTEMD_ROOT="$(root_path /etc/systemd/system)"
readonly JOURNALD_ROOT="$(root_path /etc/systemd/journald.conf.d)"
readonly JOURNALD_TARGET="${JOURNALD_ROOT}/docket.conf"
readonly CANARY_CONFIG="$(root_path /etc/docket/docket-canary.conf)"
readonly CANARY_TOKEN="$(root_path /etc/docket/docket-canary.token)"
if (( DRY_RUN )); then
    JSON_PYTHON=python3
    CURL_COMMAND=${DOCKET_RELEASE_CURL:-curl}
    JOURNALCTL_COMMAND=${DOCKET_RELEASE_JOURNALCTL:-journalctl}
    RUNUSER_COMMAND=${DOCKET_RELEASE_RUNUSER:-runuser}
    SYSTEMCTL_COMMAND=${DOCKET_RELEASE_SYSTEMCTL:-systemctl}
else
    JSON_PYTHON="${OPT_DOCKET}/.venv/bin/python"
    CURL_COMMAND=curl
    JOURNALCTL_COMMAND=journalctl
    RUNUSER_COMMAND=runuser
    SYSTEMCTL_COMMAND=systemctl
fi
readonly JSON_PYTHON CURL_COMMAND JOURNALCTL_COMMAND RUNUSER_COMMAND SYSTEMCTL_COMMAND

run_fs install -d -m 0755 "${OPT_ROOT}" "${VENV_ROOT}"
if [[ -e "${VENV}" ]]; then
    [[ -d "${VENV}" ]] || fatal "existing venv path is not a directory: ${VENV}"
    existing_commit=
    existing_sha=
    existing_version=
    [[ ! -f "${VENV}/RELEASE-commit.txt" ]] || \
        existing_commit="$(<"${VENV}/RELEASE-commit.txt")"
    [[ ! -f "${VENV}/WHEEL-sha256.txt" ]] || \
        existing_sha="$(<"${VENV}/WHEEL-sha256.txt")"
    [[ ! -f "${VENV}/DOCKET-version.txt" ]] || \
        existing_version="$(<"${VENV}/DOCKET-version.txt")"
    if [[ "${existing_commit}" != "${SOURCE_COMMIT}" || \
        "${existing_sha}" != "${EXPECTED_WHEEL_SHA}" || \
        "${existing_version}" != "${WHEEL_VERSION}" ]]; then
        fatal "existing venv identity differs: ${VENV}"
    fi
    printf 'Reusing matching venv: %s\n' "${VENV}"
else
    (
        run_fs umask 022
        trace_command python3 -m venv "${VENV}"
        if (( DRY_RUN )); then
            install -d -m 0755 "${VENV}/bin"
        else
            python3 -m venv "${VENV}"
        fi
        trace_command "${VENV}/bin/python" -m pip install -- "${WHEEL}"
        if (( ! DRY_RUN )); then
            "${VENV}/bin/python" -m pip install -- "${WHEEL}"
        fi
    )
fi

trace_command "${VENV}/bin/python" -m pip check
if (( ! DRY_RUN )); then
    "${VENV}/bin/python" -m pip check
fi
trace_command "${RUNUSER_COMMAND}" -u docket -- "${VENV}/bin/python" -c \
    'import docket, docket.api, docket.canary'
if (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_RUNUSER:-}" ]]; then
    if ! "${RUNUSER_COMMAND}" -u docket -- "${VENV}/bin/python" -c \
        'import docket, docket.api, docket.canary'; then
        fatal 'docket service user cannot import the installed release'
    fi
fi
trace_command "${VENV}/bin/python" -m pip show docket
if (( DRY_RUN )); then
    installed_name=docket
    installed_version=${DOCKET_RELEASE_INSTALLED_VERSION:-${WHEEL_VERSION}}
else
    pip_show="$("${VENV}/bin/python" -m pip show docket)"
    printf '%s\n' "${pip_show}"
    installed_name="$(awk -F ': ' '$1 == "Name" { print $2 }' <<<"${pip_show}")"
    installed_version="$(awk -F ': ' '$1 == "Version" { print $2 }' <<<"${pip_show}")"
fi
[[ "${installed_name,,}" == docket && "${installed_version}" == "${WHEEL_VERSION}" ]] || fatal \
    "pip show docket version ${installed_version:-<missing>} does not match wheel ${WHEEL_VERSION}"

if [[ ! -e "${VENV}/RELEASE-commit.txt" ]]; then
    trace_command printf '%s\\n' "${SOURCE_COMMIT}" '>' "${VENV}/RELEASE-commit.txt"
    printf '%s\n' "${SOURCE_COMMIT}" >"${VENV}/RELEASE-commit.txt"
    trace_command printf '%s\\n' "${EXPECTED_WHEEL_SHA}" '>' "${VENV}/WHEEL-sha256.txt"
    printf '%s\n' "${EXPECTED_WHEEL_SHA}" >"${VENV}/WHEEL-sha256.txt"
    trace_command printf '%s\\n' "${WHEEL_VERSION}" '>' "${VENV}/DOCKET-version.txt"
    printf '%s\n' "${WHEEL_VERSION}" >"${VENV}/DOCKET-version.txt"
fi

readonly -a UNIT_NAMES=(
    docket-canary.service
    docket-canary.timer
    docket-lp-record.service
    docket-lp-record.timer
    docket-refresh.service
    docket-refresh.timer
    docket-v3-capture.service
    docket-v3-capture.timer
    docket-v3-range-capture.service
    docket-v3-range-capture.timer
)
readonly -a TIMER_NAMES=(
    docket-canary.timer
    docket-lp-record.timer
    docket-refresh.timer
    docket-v3-capture.timer
    docket-v3-range-capture.timer
)
for name in "${UNIT_NAMES[@]}"; do
    [[ -f "${SCRIPT_DIR}/systemd/${name}" ]] || fatal \
        "missing release unit: ${SCRIPT_DIR}/systemd/${name}"
done
[[ -f "${SCRIPT_DIR}/journald-docket.conf" ]] || fatal \
    "missing release asset: ${SCRIPT_DIR}/journald-docket.conf"
[[ -f "${CANARY_CONFIG}" ]] || fatal "canary config is missing: ${CANARY_CONFIG}"
[[ -f "${CANARY_TOKEN}" ]] || fatal "canary token is missing: ${CANARY_TOKEN}"
if (( ! DRY_RUN )); then
    [[ "$(stat -c '%a:%U:%G' "${CANARY_CONFIG}")" == '640:root:docket' ]] || fatal \
        "canary config must be mode 0640 and owned by root:docket"
    [[ "$(stat -c '%a:%U:%G' "${CANARY_TOKEN}")" == '640:root:docket' ]] || fatal \
        "canary token must be mode 0640 and owned by root:docket"
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
[[ ! -e "${STAGE}" ]] || fatal "stage already exists: ${STAGE}"
[[ ! -e "${BACKUP}" ]] || fatal "backup already exists: ${BACKUP}"
[[ ! -e "${FAILED_RELEASE}" ]] || fatal "failed-release target exists: ${FAILED_RELEASE}"
[[ -d "${OPT_DOCKET}" ]] || fatal "current release is missing: ${OPT_DOCKET}"

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

run_fs install -d -m 0755 "${STAGE}/deploy"
run_fs cp -a "${SCRIPT_DIR}/." "${STAGE}/deploy/"
trace_command printf '%s\\n' "${SOURCE_COMMIT}" '>' "${STAGE}/RELEASE-commit.txt"
printf '%s\n' "${SOURCE_COMMIT}" >"${STAGE}/RELEASE-commit.txt"
trace_command printf '%s  %s\\n' "${EXPECTED_WHEEL_SHA}" "$(basename -- "${WHEEL}")" \
    '>' "${STAGE}/WHEEL-sha256.txt"
printf '%s  %s\n' "${EXPECTED_WHEEL_SHA}" "$(basename -- "${WHEEL}")" \
    >"${STAGE}/WHEEL-sha256.txt"

declare -A UNIT_EXISTED=()
declare -A TIMER_WAS_ENABLED=()
declare -A TIMER_WAS_ACTIVE=()
APP_STOPPED=0
BACKUP_MOVED=0
SWAPPED=0
UNITS_TOUCHED=0
TIMER_STATE_DIRTY=0
RELEASE_OK=0

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
        if [[ "${TIMER_WAS_ENABLED[${name}]:-0}" == 1 ]]; then
            run_host systemctl enable "${name}" || return 1
        else
            run_host systemctl disable "${name}" || return 1
        fi
        if [[ "${TIMER_WAS_ACTIVE[${name}]:-0}" == 1 ]]; then
            run_host systemctl start "${name}" || return 1
        else
            run_host systemctl stop "${name}" || return 1
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
    if (( APP_STOPPED || BACKUP_MOVED || SWAPPED )); then
        run_host systemctl start docket.service || rollback_ok=0
    fi
    if (( ! APP_STOPPED && ! BACKUP_MOVED && ! SWAPPED && rollback_ok )); then
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
        if (( APP_STOPPED || BACKUP_MOVED || SWAPPED || TIMER_STATE_DIRTY )); then
            rollback
        fi
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

refuse_range_capture_window

for name in "${TIMER_NAMES[@]}"; do
    if (( DRY_RUN )); then
        TIMER_WAS_ENABLED["${name}"]=1
        TIMER_WAS_ACTIVE["${name}"]=1
    else
        trace_command systemctl is-enabled --quiet "${name}"
        if systemctl is-enabled --quiet "${name}"; then
            TIMER_WAS_ENABLED["${name}"]=1
        else
            TIMER_WAS_ENABLED["${name}"]=0
        fi
        trace_command systemctl is-active --quiet "${name}"
        if systemctl is-active --quiet "${name}"; then
            TIMER_WAS_ACTIVE["${name}"]=1
        else
            TIMER_WAS_ACTIVE["${name}"]=0
        fi
    fi
done

run_host systemctl stop docket-canary.timer
TIMER_STATE_DIRTY=1
trace_command systemctl is-active --quiet docket-canary.service
if { (( ! DRY_RUN )) || [[ -n "${DOCKET_RELEASE_SYSTEMCTL:-}" ]]; } && \
    "${SYSTEMCTL_COMMAND}" is-active --quiet docket-canary.service; then
    fatal 'docket-canary.service is active after its timer was stopped'
fi
run_host systemctl stop docket.service
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
for name in "${TIMER_NAMES[@]}"; do
    if [[ "${name}" == docket-v3-range-capture.timer ]]; then
        refuse_range_capture_window
    fi
    run_host systemctl enable --now "${name}"
done

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

RELEASE_OK=1
printf 'Release complete: %s (%s), wheel %s.\n' \
    "${SOURCE_COMMIT}" "${WHEEL_VERSION}" "${EXPECTED_WHEEL_SHA}"
