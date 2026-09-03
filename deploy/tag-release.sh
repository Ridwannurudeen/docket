#!/usr/bin/env bash
# Tag the commit that is actually deployed, and say what was checked before tagging it.
#
# A tag is a claim about a commit, and the two claims worth making here are the two that go
# stale silently: that this commit passed CI, and that this commit is what the production host
# is running. Both are verified against their own source rather than assumed from a green
# terminal — `gh run list --commit` for the first, a read-only ssh for the second — and the
# release notes carry the wheel digest and runtime-lock digest the host itself reports, so a
# reader can reproduce the environment the tag names.
#
# Nothing here writes to the host. The only mutations are the local annotated tag and the
# GitHub release, and both refuse to overwrite an existing one.
#
# Usage: tag-release.sh [--dry-run] <commit> <ssh-host>
#
# There is no default host. A deployment tagger that guesses which machine to ask is a
# tagger that will eventually certify the wrong one.
set -euo pipefail

export LC_ALL=C

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
    shift
fi

if [[ $# -ne 2 ]]; then
    printf '%s\n' 'Usage: tag-release.sh [--dry-run] <commit> <ssh-host>' >&2
    exit 2
fi

readonly COMMIT=$1
readonly SSH_HOST=$2
readonly TAG_NAME=v1.0.0-hackathon
readonly RELEASE_ROOT=/opt/docket
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ ! "${COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' 'NO-GO: the commit must be a full 40-character lowercase sha.' >&2
    exit 1
fi
if [[ ! "${SSH_HOST}" =~ ^[A-Za-z0-9_.@-]+$ ]]; then
    printf '%s\n' 'NO-GO: the ssh host must be a plain [A-Za-z0-9_.@-] destination.' >&2
    exit 1
fi

GH_COMMAND=gh
SSH_COMMAND=ssh
GIT_COMMAND=git
JSON_PYTHON=python3
if (( DRY_RUN )); then
    GH_COMMAND=${DOCKET_TAG_GH:-gh}
    SSH_COMMAND=${DOCKET_TAG_SSH:-ssh}
    GIT_COMMAND=${DOCKET_TAG_GIT:-git}
    JSON_PYTHON=${DOCKET_TAG_PYTHON:-python3}
fi
readonly GH_COMMAND SSH_COMMAND GIT_COMMAND JSON_PYTHON

trace_command() {
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
}

fatal() {
    printf 'NO-GO: %s\n' "$1" >&2
    exit 1
}

run_mutation() {
    trace_command "$@"
    if (( DRY_RUN )); then
        return 0
    fi
    "$@"
}

# --- the commit exists here ------------------------------------------------------------
trace_command "${GIT_COMMAND}" -C "${SCRIPT_DIR}/.." cat-file -e "${COMMIT}^{commit}"
"${GIT_COMMAND}" -C "${SCRIPT_DIR}/.." cat-file -e "${COMMIT}^{commit}" 2>/dev/null || fatal \
    "this checkout has no commit ${COMMIT}"

trace_command "${GIT_COMMAND}" -C "${SCRIPT_DIR}/.." tag --list "${TAG_NAME}"
existing_tag="$("${GIT_COMMAND}" -C "${SCRIPT_DIR}/.." tag --list "${TAG_NAME}")"
[[ -z "${existing_tag}" ]] || fatal \
    "${TAG_NAME} already exists locally; delete it deliberately before retagging"

# A local checkout that has never fetched tags knows nothing about what origin carries, and
# a tag that already exists there is one someone has already published under this name.
trace_command "${GIT_COMMAND}" -C "${SCRIPT_DIR}/.." ls-remote --tags origin \
    "refs/tags/${TAG_NAME}"
if ! remote_tag="$("${GIT_COMMAND}" -C "${SCRIPT_DIR}/.." ls-remote --tags origin \
    "refs/tags/${TAG_NAME}")"; then
    fatal "could not ask origin whether ${TAG_NAME} already exists"
fi
[[ -z "${remote_tag}" ]] || fatal \
    "origin already carries ${TAG_NAME}; delete it deliberately before retagging"

trace_command "${GH_COMMAND}" release view "${TAG_NAME}"
if "${GH_COMMAND}" release view "${TAG_NAME}" >/dev/null 2>&1; then
    fatal "a GitHub release named ${TAG_NAME} already exists"
fi

# --- CI concluded success for exactly this commit --------------------------------------
trace_command "${GH_COMMAND}" run list --commit "${COMMIT}" --json \
    workflowName,status,conclusion,databaseId
if ! ci_runs="$("${GH_COMMAND}" run list --commit "${COMMIT}" --json \
    workflowName,status,conclusion,databaseId)"; then
    fatal "gh run list failed for ${COMMIT}"
fi
printf '%s\n' "${ci_runs}"
if ! ci_summary="$(printf '%s' "${ci_runs}" | "${JSON_PYTHON}" -c '
import json, sys

runs = json.load(sys.stdin)
if not isinstance(runs, list) or not runs:
    raise SystemExit("no workflow run is recorded for this commit")
completed = [run for run in runs if run.get("status") == "completed"]
if len(completed) != len(runs):
    raise SystemExit("a workflow run for this commit has not finished")
failed = [
    str(run.get("workflowName"))
    + "#"
    + str(run.get("databaseId"))
    + "="
    + str(run.get("conclusion"))
    for run in completed
    if run.get("conclusion") != "success"
]
if failed:
    raise SystemExit("workflow runs did not succeed: " + ", ".join(failed))
if not any(run.get("workflowName") == "ci" for run in completed):
    raise SystemExit("no run of the ci workflow is recorded for this commit")
print(
    ", ".join(
        str(run["workflowName"]) + "#" + str(run["databaseId"]) for run in completed
    )
)
')"; then
    fatal "CI is not green for ${COMMIT}"
fi
printf 'CI verified for %s: %s.\n' "${COMMIT}" "${ci_summary}"

# --- the host is running exactly this commit -------------------------------------------
# Traced by each caller rather than from inside: this runs in a command substitution, and a
# trace printed there is captured as part of the value it was tracing.
read_host_file() {
    local name=$1
    "${SSH_COMMAND}" -o BatchMode=yes -- "${SSH_HOST}" "cat ${RELEASE_ROOT}/${name}"
}

trace_host_read() {
    trace_command "${SSH_COMMAND}" -o BatchMode=yes -- "${SSH_HOST}" \
        "cat ${RELEASE_ROOT}/$1"
}

trace_host_read RELEASE-commit.txt
if ! host_commit="$(read_host_file RELEASE-commit.txt)"; then
    fatal "could not read ${RELEASE_ROOT}/RELEASE-commit.txt on ${SSH_HOST}"
fi
host_commit="${host_commit//[$'\r\n\t ']/}"
[[ "${host_commit}" == "${COMMIT}" ]] || fatal \
    "${SSH_HOST} is running ${host_commit:-nothing}, not ${COMMIT}"

trace_host_read WHEEL-sha256.txt
if ! host_wheel="$(read_host_file WHEEL-sha256.txt)"; then
    fatal "could not read ${RELEASE_ROOT}/WHEEL-sha256.txt on ${SSH_HOST}"
fi
host_wheel="$(printf '%s' "${host_wheel}" | awk 'NR == 1 { print $1 }')"
[[ "${host_wheel}" =~ ^[0-9a-f]{64}$ ]] || fatal \
    "${SSH_HOST} reports an unreadable wheel digest"

trace_host_read RUNTIME-LOCK-sha256.txt
if ! host_lock="$(read_host_file RUNTIME-LOCK-sha256.txt)"; then
    fatal "could not read ${RELEASE_ROOT}/RUNTIME-LOCK-sha256.txt on ${SSH_HOST}"
fi
host_lock="$(printf '%s' "${host_lock}" | awk 'NR == 1 { print $1 }')"
[[ "${host_lock}" =~ ^[0-9a-f]{64}$ ]] || fatal \
    "${SSH_HOST} reports an unreadable runtime-lock digest"

printf 'Host %s verified at commit %s.\n' "${SSH_HOST}" "${COMMIT}"

# --- tag it ------------------------------------------------------------------------------
NOTES="$(cat <<EOF
Docket at the commit the production host was serving when this tag was cut.

| What | Value |
| --- | --- |
| Deployed commit | \`${COMMIT}\` |
| Wheel SHA-256 | \`${host_wheel}\` |
| Runtime lock SHA-256 | \`${host_lock}\` |
| CI runs verified | ${ci_summary} |

The wheel and runtime-lock digests were read from \`${RELEASE_ROOT}\` on the deployment host,
not recomputed here, so they are the digests the running environment reports about itself.
Rebuild with \`python deploy/release_bundle.py build <dir>\` at this commit and compare.
EOF
)"

# The release is created first, and it creates the tag on origin at --target in the same
# call. Tagging locally first and releasing second is the ordering that leaves a half-done
# state: the tag exists, the release does not, and the pre-checks above then refuse the retry
# that would finish the job. One call cannot half-succeed.
run_mutation "${GH_COMMAND}" release create "${TAG_NAME}" --target "${COMMIT}" \
    --title "Docket ${TAG_NAME}" --notes "${NOTES}"

# Local annotation, after the fact and deliberately not guarded: origin already carries the
# tag and the release, so this is a convenience for the operator's own checkout. If it fails,
# nothing published is wrong and `git fetch --tags` recovers it.
run_mutation "${GIT_COMMAND}" -C "${SCRIPT_DIR}/.." tag -a "${TAG_NAME}" "${COMMIT}" -m \
    "Docket ${TAG_NAME}: deployed commit ${COMMIT}, wheel ${host_wheel}"

printf 'Released %s at %s on origin, and annotated it in this checkout.\n' \
    "${TAG_NAME}" "${COMMIT}"
