#!/usr/bin/env bash
set -euo pipefail

export LC_ALL=C

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
    shift
fi

if [[ $# -ne 1 || ! "$1" =~ ^[0-9]+$ ]]; then
    printf '%s\n' 'Usage: preflight.sh [--dry-run] <expected-nginx-warning-count>' >&2
    exit 2
fi
readonly EXPECTED_WARNINGS=$1
readonly MIN_FREE_KIB=2097152
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if (( DRY_RUN )); then
    if [[ -z "${DOCKET_RELEASE_ROOT:-}" ]]; then
        printf '%s\n' 'NO-GO: --dry-run requires DOCKET_RELEASE_ROOT.' >&2
        exit 1
    fi
    RELEASE_ROOT="$(cd -- "${DOCKET_RELEASE_ROOT}" && pwd -P)"
    if [[ "${RELEASE_ROOT}" == / ]]; then
        printf '%s\n' 'NO-GO: DOCKET_RELEASE_ROOT must not resolve to /.' >&2
        exit 1
    fi
elif [[ "${EUID}" -ne 0 ]]; then
    printf '%s\n' 'NO-GO: preflight.sh must run as root.' >&2
    exit 1
fi

NGINX_COMMAND=nginx
DF_COMMAND=df
SYSTEMD_ANALYZE_COMMAND=systemd-analyze
JOURNALCTL_COMMAND=journalctl
if (( DRY_RUN )); then
    NGINX_COMMAND=${DOCKET_PREFLIGHT_NGINX:-nginx}
    DF_COMMAND=${DOCKET_PREFLIGHT_DF:-df}
    SYSTEMD_ANALYZE_COMMAND=${DOCKET_PREFLIGHT_SYSTEMD_ANALYZE:-systemd-analyze}
    JOURNALCTL_COMMAND=${DOCKET_PREFLIGHT_JOURNALCTL:-journalctl}
fi
readonly NGINX_COMMAND DF_COMMAND SYSTEMD_ANALYZE_COMMAND JOURNALCTL_COMMAND

trace_command() {
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
}

no_go() {
    printf 'NO-GO: %s\n' "$1" >&2
    exit 1
}

readonly -a UNIT_NAMES=(
    docket.service
    docket-canary.service
    docket-canary.timer
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
)
UNIT_FILES=()
for name in "${UNIT_NAMES[@]}"; do
    path="${SCRIPT_DIR}/systemd/${name}"
    [[ -f "${path}" ]] || no_go "missing unit file ${path}"
    UNIT_FILES+=("${path}")
done

trace_command "${NGINX_COMMAND}" -t
set +e
nginx_output="$("${NGINX_COMMAND}" -t 2>&1)"
nginx_status=$?
set -e
printf '%s\n' "${nginx_output}"
(( nginx_status == 0 )) || no_go "nginx -t failed with exit ${nginx_status}"
warning_count="$(grep -cF '[warn]' <<<"${nginx_output}" || true)"
[[ "${warning_count}" == "${EXPECTED_WARNINGS}" ]] || no_go \
    "nginx warning count is ${warning_count}, expected ${EXPECTED_WARNINGS}"
grep -Fq 'test is successful' <<<"${nginx_output}" || no_go \
    "nginx -t did not report 'test is successful'"
printf 'nginx guard passed with %s nginx warnings.\n' "${warning_count}"

disk_path=/opt
if (( DRY_RUN )); then
    disk_path="${RELEASE_ROOT}/opt"
fi
trace_command "${DF_COMMAND}" -Pk "${disk_path}"
set +e
df_output="$("${DF_COMMAND}" -Pk "${disk_path}" 2>&1)"
df_status=$?
set -e
printf '%s\n' "${df_output}"
(( df_status == 0 )) || no_go "disk free-space check failed with exit ${df_status}"
available_kib="$(awk 'NR == 2 { print $4 }' <<<"${df_output}")"
[[ "${available_kib}" =~ ^[0-9]+$ ]] || no_go \
    'disk free-space check did not return an integer KiB value'
(( available_kib >= MIN_FREE_KIB )) || no_go \
    "disk free space is ${available_kib} KiB, less than ${MIN_FREE_KIB} KiB"
printf 'Disk guard passed with %s KiB free.\n' "${available_kib}"

trace_command "${SYSTEMD_ANALYZE_COMMAND}" verify "${UNIT_FILES[@]}"
set +e
verify_output="$("${SYSTEMD_ANALYZE_COMMAND}" verify "${UNIT_FILES[@]}" 2>&1)"
verify_status=$?
set -e
printf '%s\n' "${verify_output}"
(( verify_status == 0 )) || no_go \
    "systemd unit verification failed with exit ${verify_status}"

trace_command "${JOURNALCTL_COMMAND}" --disk-usage
set +e
journal_output="$("${JOURNALCTL_COMMAND}" --disk-usage 2>&1)"
journal_status=$?
set -e
printf '%s\n' "${journal_output}"
(( journal_status == 0 )) || no_go \
    "journal disk-usage check failed with exit ${journal_status}"

printf '%s\n' 'GO: release preflight passed.'
