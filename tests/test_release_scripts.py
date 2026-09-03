import base64
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
BASH = (
    Path(r"C:\Program Files\Git\bin\bash.exe")
    if os.name == "nt"
    else Path(shutil.which("bash") or "")
)
COMMIT = "a" * 40
OLD_COMMIT = "b" * 40


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _write_wheel(path: Path, *, source_commit: str = COMMIT) -> str:
    dist_info = "docket-0.1.0.dist-info"
    provenance = (
        json.dumps(
            {"source_commit": source_commit},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    members = {
        "docket/__init__.py": b"",
        f"{dist_info}/METADATA": (
            b"Metadata-Version: 2.4\nName: docket\nVersion: 0.1.0\n"
        ),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            b"Tag: py3-none-any\n"
        ),
        f"{dist_info}/docket-provenance.json": provenance,
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, contents in sorted(members.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(
            b"="
        )
        writer.writerow((name, f"sha256={digest.decode('ascii')}", len(contents)))
    writer.writerow((f"{dist_info}/RECORD", "", ""))

    with zipfile.ZipFile(path, "w") as archive:
        for name, contents in members.items():
            archive.writestr(name, contents)
        archive.writestr(f"{dist_info}/RECORD", record.getvalue())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _deploy_asset_hashes(deploy: Path = DEPLOY) -> dict[str, str]:
    return {
        f"deploy/{path.relative_to(deploy).as_posix()}": hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in deploy.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def _write_release_manifest(
    wheel: Path,
    wheel_sha: str,
    *,
    source_commit: str = COMMIT,
    runtime_lock_sha: str | None = None,
    asset_overrides: dict[str, str] | None = None,
    deploy: Path = DEPLOY,
) -> Path:
    assets = _deploy_asset_hashes(deploy)
    assets.update(asset_overrides or {})
    if runtime_lock_sha is None:
        runtime_lock_sha = hashlib.sha256(
            (deploy / "runtime-requirements.txt").read_bytes()
        ).hexdigest()
    manifest = {
        "deploy_assets": assets,
        "runtime_lock": {
            "path": "deploy/runtime-requirements.txt",
            "sha256": runtime_lock_sha,
        },
        "schema_version": 1,
        "source_commit": source_commit,
        "wheel": {"filename": wheel.name, "sha256": wheel_sha},
    }
    path = wheel.with_suffix(".release-manifest.json")
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _fake_bin(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
url=${!#}
case "${url}" in
    */health)
        count=0
        if [[ -n "${FAKE_CURL_COUNT_FILE:-}" && -f "${FAKE_CURL_COUNT_FILE}" ]]; then
            count=$(<"${FAKE_CURL_COUNT_FILE}")
        fi
        count=$((count + 1))
        if [[ -n "${FAKE_CURL_COUNT_FILE:-}" ]]; then
            printf '%s\n' "${count}" >"${FAKE_CURL_COUNT_FILE}"
        fi
        if (( count <= ${FAKE_CURL_HEALTH_FAILURES:-0} )); then
            exit 22
        fi
        printf '{"status":"%s"}\n' "${FAKE_HEALTH_STATUS:-ok}"
        ;;
    */stats)
        if [[ "${FAKE_INVALID_ENDPOINT:-}" == stats ]]; then
            printf '%s\n' '{}'
        else
            printf '%s\n' '{"coverage":{"snapshot_id":1,"captured_at":"2026-08-22T00:00:00Z","snapshot_age_seconds":1,"sampled":1,"expected":1,"dropped":0,"complete":true,"population":"min_feedbacks>=1"},"refresh_status":null,"registry_total":1,"probe_method":"test"}'
        fi
        ;;
    */services)
        if [[ "${FAKE_INVALID_ENDPOINT:-}" == services ]]; then
            printf '%s\n' '{}'
        else
            last_service=warden-scan
            if [[ "${FAKE_INVALID_ENDPOINT:-}" == service-ids ]]; then
                last_service=unexpected-service
            fi
            printf '{"services":[{"service_id":"grid-operator","paid_stock":false,"stock_status":"preview","admission":{"fresh_paired_benchmark":false,"cold_canary":false,"decision_grade_presenter":true,"true_settlement":false}},{"service_id":"health-guard","paid_stock":false,"stock_status":"preview","admission":{"fresh_paired_benchmark":false,"cold_canary":false,"decision_grade_presenter":true,"true_settlement":false}},{"service_id":"range-doctor","paid_stock":false,"stock_status":"candidate","admission":{"fresh_paired_benchmark":false,"cold_canary":false,"decision_grade_presenter":true,"true_settlement":false}},{"service_id":"solvent-signal","paid_stock":false,"stock_status":"research","admission":{"fresh_paired_benchmark":false,"cold_canary":false,"decision_grade_presenter":false,"true_settlement":false}},{"service_id":"yield-router","paid_stock":false,"stock_status":"preview","admission":{"fresh_paired_benchmark":false,"cold_canary":false,"decision_grade_presenter":true,"true_settlement":false}},{"service_id":"%s","paid_stock":false,"stock_status":"beta","admission":{"fresh_paired_benchmark":false,"cold_canary":false,"decision_grade_presenter":true,"true_settlement":false}}],"total":6,"category":null,"ordering":"service_id","declaration":"test"}\n' "${last_service}"
        fi
        ;;
    */categories)
        last_category=health_factor
        if [[ "${FAKE_INVALID_ENDPOINT:-}" == categories ]]; then
            last_category=unregistered_category
        fi
        printf '{"categories":[{"category":"rebalancing"},{"category":"grid_trading"},{"category":"yield_optimisation"},{"category":"%s"}],"declaration":"test"}\n' "${last_category}"
        ;;
    */advantage/v3.json)
        if [[ "${FAKE_V3_STATUS:-200}" == 503 ]]; then
            exit 22
        elif [[ "${FAKE_INVALID_ENDPOINT:-}" == advantage/v3.json ]]; then
            printf '%s\n' '{}'
        else
            final_state=registered_waiting_for_inputs
            if [[ "${FAKE_INVALID_ENDPOINT:-}" == v3-states ]]; then
                final_state=locked_not_run
            fi
            printf '{"families":[{"spec_id":"v3-01-range-doctor","state":"superseded_before_input_lock"},{"spec_id":"v3-02-yield-router","state":"abandoned_after_failed_primary"},{"spec_id":"v3-03-warden-security","state":"superseded_before_input_lock"},{"spec_id":"v3-04-warden-security","state":"complete_unscored"},{"spec_id":"v3-05-range-doctor","state":"locked_not_run"},{"spec_id":"v3-06-yield-router-assisted","state":"registered_waiting_for_inputs"},{"spec_id":"v3-07-range-doctor","state":"registered_waiting_for_inputs"},{"spec_id":"v3-08-yield-router","state":"registered_waiting_for_inputs"},{"spec_id":"v3-09-health-guard","state":"%s"}],"summary":{"n_families":9}}\n' "${final_state}"
        fi
        ;;
    */static/style.css)
        if [[ "${FAKE_INVALID_ENDPOINT:-}" == static ]]; then
            printf '%s\n' 'body {}'
        else
            printf '%s\n' ':root { --bg: #fff; }'
        fi
        ;;
    */)
        if [[ "${FAKE_INVALID_ENDPOINT:-}" == homepage ]]; then
            printf '%s\n' '<html><title>Wrong site</title></html>'
        else
            printf '%s\n' '<!doctype html><title>Docket -- test</title>'
        fi
        ;;
    *)
        exit 22
        ;;
esac
""",
    )
    _write_executable(
        fake_bin / "nginx",
        """#!/usr/bin/env bash
set -euo pipefail
for ((i = 0; i < ${FAKE_NGINX_WARNINGS:-22}; i++)); do
    printf '%s\n' "${FAKE_NGINX_WARNING:-2026/08/22 19:10:42 [warn] 3091734#3091734: protocol options redefined for 0.0.0.0:443 in /etc/nginx/sites-enabled/docket}" >&2
done
if [[ "${FAKE_NGINX_SUCCESS:-1}" == 1 ]]; then
    printf '%s\n' 'nginx: configuration file /etc/nginx/nginx.conf test is successful' >&2
fi
exit "${FAKE_NGINX_EXIT:-0}"
""",
    )
    _write_executable(
        fake_bin / "df",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'Filesystem 1024-blocks Used Available Capacity Mounted on'
printf '/dev/fake 10000000 1 %s 1%% /opt\n' "${FAKE_DF_AVAILABLE_KIB:-2097152}"
""",
    )
    _write_executable(
        fake_bin / "systemd-analyze",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'unit verification complete'
exit "${FAKE_SYSTEMD_VERIFY_EXIT:-0}"
""",
    )
    _write_executable(
        fake_bin / "journalctl",
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    --disk-usage)
        printf '%s\n' 'Archived and active journals take up 64.0M in the file system.'
        ;;
    --header)
        printf '%s\n' "${FAKE_JOURNAL_HEADER:-File path: /var/log/journal/0123456789abcdef/system.journal}"
        ;;
    *)
        exit 64
        ;;
esac
exit "${FAKE_JOURNAL_EXIT:-0}"
""",
    )
    _write_executable(
        fake_bin / "runuser",
        """#!/usr/bin/env bash
set -euo pipefail
exit "${FAKE_RUNUSER_EXIT:-0}"
""",
    )
    _write_executable(
        fake_bin / "flock",
        '#!/usr/bin/env bash\nset -euo pipefail\nexit "${FAKE_FLOCK_EXIT:-0}"\n',
    )
    _write_executable(
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
set -euo pipefail
name=${!#}
timer_missing=0
if [[ -n "${FAKE_SYSTEMD_ROOT:-}" && "${name}" == *.timer && \
      ! -f "${FAKE_SYSTEMD_ROOT}/${name}" ]]; then
    timer_missing=1
fi
if [[ "${1:-}" == show && "$*" == "show --property=LoadState --value ${name}" ]]; then
    if (( timer_missing )); then
        printf '%s\n' not-found
    else
        printf '%s\n' loaded
    fi
    exit 0
fi
if [[ "$*" == "is-enabled --quiet ${name}" && "${name}" == *.timer ]]; then
    if [[ "${name}" == "${FAKE_DISABLED_TIMER:-}" ]]; then
        exit 1
    fi
    (( ! timer_missing ))
    exit
fi
if [[ -n "${FAKE_ACTIVE_SERVICE:-}" && "$*" == "is-active --quiet ${FAKE_ACTIVE_SERVICE}" ]]; then
    exit 0
fi
if [[ "$*" == "is-active --quiet docket-canary.service" && "${FAKE_CANARY_ACTIVE:-0}" == 1 ]]; then
    exit 0
fi
if [[ "$*" == "is-active --quiet ${name}" && "${name}" == *.timer ]]; then
    if [[ "${name}" == "${FAKE_DISABLED_TIMER:-}" ]]; then
        exit 1
    fi
    (( ! timer_missing ))
    exit
fi
if [[ "${1:-}" =~ ^(disable|enable|start|stop)$ ]] && (( timer_missing )); then
    exit 5
fi
if [[ "$*" == "stop docket.service" && "${FAKE_APP_STOP_EXIT:-0}" != 0 ]]; then
    exit "${FAKE_APP_STOP_EXIT}"
fi
if [[ "${1:-}" =~ ^(disable|enable|start|stop)$ ]]; then
    exit 0
fi
exit 3
""",
    )
    return fake_bin


def _environment(root: Path, fake_bin: Path, **values: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment["DOCKET_RELEASE_ROOT"] = root.as_posix()
    environment["DOCKET_RELEASE_HEALTH_ATTEMPTS"] = "2"
    environment["DOCKET_RELEASE_TIMESTAMP"] = "20260822T120000Z"
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["DOCKET_RELEASE_CURL"] = (fake_bin / "curl").as_posix()
    environment["DOCKET_PREFLIGHT_NGINX"] = (fake_bin / "nginx").as_posix()
    environment["DOCKET_PREFLIGHT_DF"] = (fake_bin / "df").as_posix()
    environment["DOCKET_PREFLIGHT_SYSTEMD_ANALYZE"] = (
        fake_bin / "systemd-analyze"
    ).as_posix()
    environment["DOCKET_PREFLIGHT_JOURNALCTL"] = (fake_bin / "journalctl").as_posix()
    environment["DOCKET_RELEASE_JOURNALCTL"] = (fake_bin / "journalctl").as_posix()
    environment["DOCKET_RELEASE_RUNUSER"] = (fake_bin / "runuser").as_posix()
    environment.update(values)
    return environment


def _run(
    script: str,
    *args: str,
    environment: dict[str, str],
    deploy: Path = DEPLOY,
) -> subprocess.CompletedProcess:
    assert BASH.is_file(), f"Git Bash is required at {BASH}"
    return subprocess.run(
        [str(BASH), str(deploy / script), *args],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _prepare_live_release(root: Path) -> None:
    old_venv = root / "opt" / "docket-venvs" / OLD_COMMIT[:12]
    old_venv.mkdir(parents=True)
    (old_venv / "RELEASE-commit.txt").write_text(OLD_COMMIT + "\n", encoding="ascii")
    live = root / "opt" / "docket"
    live.mkdir(parents=True)
    (live / "old-release.txt").write_text("old\n", encoding="ascii")
    (live / ".venv.target").write_text(old_venv.as_posix() + "\n", encoding="utf-8")
    config = root / "etc" / "docket"
    config.mkdir(parents=True)
    (config / "docket-canary.conf").write_text(
        "DOCKET_CANARY_BASE_URL=https://docket.example\n", encoding="ascii"
    )
    (config / "docket-canary.token").write_text("test-token\n", encoding="ascii")
    database = root / "var" / "lib" / "docket" / "data" / "agents.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE release_fixture (value TEXT NOT NULL)")
        connection.execute("INSERT INTO release_fixture VALUES ('preserved')")


@pytest.mark.parametrize("script", ["install-canary.sh", "preflight.sh", "release.sh"])
def test_every_deployment_script_has_valid_bash_syntax(script: str):
    result = subprocess.run(
        [str(BASH), "-n", str(DEPLOY / script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_release_and_preflight_track_every_systemd_unit_and_document_the_count():
    expected = {path.name for path in (DEPLOY / "systemd").iterdir() if path.is_file()}
    assert len(expected) == 17

    for script_name in ("preflight.sh", "release.sh"):
        script = (DEPLOY / script_name).read_text(encoding="utf-8")
        start = script.index("readonly -a UNIT_NAMES=(")
        end = script.index("\n)", start)
        declared = {
            line.strip() for line in script[start:end].splitlines()[1:] if line.strip()
        }
        assert declared == expected

    runbook = (ROOT / "docs/deployment-runbook.md").read_text(encoding="utf-8")
    assert runbook.count("all seventeen tracked unit") == 2
    assert "all fifteen tracked unit" not in runbook
    assert "all ten tracked units" not in runbook
    assert "all twelve unit files" not in runbook
    assert "all thirteen tracked unit" not in runbook


def test_release_refuses_a_held_process_lock_before_artifact_or_runtime_mutation(
    tmp_path,
):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin, FAKE_FLOCK_EXIT="1"),
    )

    assert result.returncode != 0
    assert "another Docket release is already running" in result.stderr
    assert "release_bundle.py verify" not in result.stdout
    assert not (root / "opt" / "docket-venvs" / COMMIT[:12]).exists()
    assert (root / "opt" / "docket" / "old-release.txt").is_file()
    script = (DEPLOY / "release.sh").read_text(encoding="utf-8")
    assert "RELEASE_LOCK_DIR=/run/docket" in script
    assert "RELEASE_LOCK=${RELEASE_LOCK_DIR}/release.lock" in script
    assert "700:root:root" in script
    assert "/run/lock/docket" not in script


def test_release_refuses_wal_before_artifact_or_runtime_mutation(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    database = root / "var" / "lib" / "docket" / "data" / "agents.sqlite3"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "WAL mode" in result.stderr
    assert not (root / "opt" / "docket-venvs" / COMMIT[:12]).exists()
    assert (root / "opt" / "docket" / "old-release.txt").is_file()
    assert not (root / "var" / "backups" / "docket").exists()


@pytest.mark.skipif(os.name == "nt", reason="util-linux flock is required")
def test_two_release_processes_cannot_enter_artifact_mutation_together(tmp_path):
    real_flock = shutil.which("flock")
    if real_flock is None:
        pytest.skip("util-linux flock is unavailable")

    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    started = tmp_path / "first-verifier-started"
    release_first = tmp_path / "release-first"
    _write_executable(
        fake_bin / "python3",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"release_bundle.py verify"* && ! -e "${HOLD_STARTED}" ]]; then
    : >"${HOLD_STARTED}"
    while [[ ! -e "${HOLD_RELEASE}" ]]; do
        sleep 0.01
    done
fi
exec "${REAL_PYTHON}" "$@"
""",
    )
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest)
    environment = _environment(
        root,
        fake_bin,
        DOCKET_RELEASE_FLOCK=real_flock,
        DOCKET_RELEASE_LOCK_PATH=(tmp_path / "release.lock").as_posix(),
        HOLD_RELEASE=release_first.as_posix(),
        HOLD_STARTED=started.as_posix(),
        REAL_PYTHON=sys.executable,
    )
    command = [str(BASH), str(DEPLOY / "release.sh"), "--dry-run", manifest.as_posix()]
    first = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    first_stdout = ""
    first_stderr = ""
    try:
        deadline = time.monotonic() + 10
        while not started.exists():
            if first.poll() is not None:
                first_stdout, first_stderr = first.communicate()
                pytest.fail(
                    "first release exited before holding the verifier: "
                    + first_stdout
                    + first_stderr
                )
            if time.monotonic() >= deadline:
                pytest.fail("first release did not reach the held verifier")
            time.sleep(0.01)

        second = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert second.returncode != 0
        assert "another Docket release is already running" in second.stderr
        assert "release_bundle.py verify" not in second.stdout
        assert not (root / "opt" / "docket-venvs" / COMMIT[:12]).exists()
        assert (root / "opt" / "docket" / "old-release.txt").is_file()
    finally:
        release_first.touch()
        try:
            first_stdout, first_stderr = first.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            first.kill()
            first_stdout, first_stderr = first.communicate()

    assert first.returncode == 0, first_stdout + first_stderr


def test_release_refuses_a_wheel_sha_mismatch_before_creating_a_venv(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest)
    wheel.write_bytes(b"not the expected wheel")

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "wheel SHA-256 mismatch" in result.stderr
    assert not (root / "opt" / "docket-venvs").exists()


def test_release_refuses_an_embedded_commit_mismatch_before_mutation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel, source_commit=OLD_COMMIT)
    manifest = _write_release_manifest(wheel, digest)

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "embedded source commit does not match the release manifest" in result.stderr
    assert not (root / "opt" / "docket-venvs").exists()


def test_release_refuses_a_runtime_lock_hash_mismatch_before_mutation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest, runtime_lock_sha="0" * 64)

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "runtime lock SHA-256 mismatch" in result.stderr
    assert not (root / "opt" / "docket-venvs").exists()


def test_release_refuses_a_deploy_asset_hash_mismatch_before_mutation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(
        wheel,
        digest,
        asset_overrides={"deploy/journald-docket.conf": "0" * 64},
    )

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "deploy asset SHA-256 mismatch" in result.stderr
    assert not (root / "opt" / "docket-venvs").exists()


def test_release_refuses_a_missing_runtime_lock_before_mutation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)
    copied_deploy = tmp_path / "copied-deploy"
    shutil.copytree(DEPLOY, copied_deploy)
    (copied_deploy / "runtime-requirements.txt").unlink()
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(
        wheel,
        digest,
        runtime_lock_sha="0" * 64,
        deploy=copied_deploy,
    )

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(root, fake_bin),
        deploy=copied_deploy,
    )

    assert result.returncode != 0
    assert "runtime lock is missing" in result.stderr
    assert not (root / "opt" / "docket-venvs").exists()


def test_release_refuses_an_existing_venv_with_different_identity(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    venv = root / "opt" / "docket-venvs" / COMMIT[:12]
    venv.mkdir(parents=True)
    (venv / "RELEASE-commit.txt").write_text(OLD_COMMIT + "\n", encoding="ascii")
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest)

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "existing venv identity differs" in result.stderr
    assert (venv / "RELEASE-commit.txt").read_text(
        encoding="ascii"
    ).strip() == OLD_COMMIT


def test_release_refuses_when_pip_show_disagrees_with_the_wheel(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root, fake_bin, DOCKET_RELEASE_INSTALLED_VERSION="9.9.9"
        ),
    )

    assert result.returncode != 0
    assert "pip show docket version 9.9.9 does not match wheel 0.1.0" in result.stderr


def test_release_creates_and_installs_a_new_venv_under_umask_022(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lower_umask = result.stdout.index("+ umask 022")
    create_venv = result.stdout.index("python3 -m venv")
    create_venv_line = result.stdout[
        create_venv : result.stdout.index("\n", create_venv)
    ]
    install_lock = result.stdout.index(
        "pip install --require-hashes --only-binary=:all: -r"
    )
    install_wheel = result.stdout.index("pip install --no-deps", install_lock)
    pip_check = result.stdout.index("/bin/python -m pip check")
    write_identity = result.stdout.index("RELEASE-commit.txt", pip_check)
    fsync_identity = result.stdout.index("python3 - file", write_identity)
    fsync_partial = result.stdout.index("python3 - directory", fsync_identity)
    publish_venv = result.stdout.index("mv -T --", write_identity)
    fsync_venv_root = result.stdout.index("python3 - directory", publish_venv)
    reverified = result.stdout.index("Release manifest reverified before mutation")
    stop_timers = [
        result.stdout.index(f"systemctl stop {timer}", reverified)
        for timer in (
            "docket-canary.timer",
            "docket-lp-record.timer",
            "docket-refresh.timer",
            "docket-v3-capture.timer",
            "docket-v3-range-capture.timer",
            "docket-v3-yield-v6-capture.timer",
        )
    ]
    database_backup = result.stdout.index("Database backup verified:")
    stop_app = result.stdout.index("systemctl stop docket.service")
    assert result.stdout.count("release_bundle.py verify") == 2
    assert ".partial" in create_venv_line
    assert (
        lower_umask
        < create_venv
        < install_lock
        < install_wheel
        < pip_check
        < write_identity
        < fsync_identity
        < fsync_partial
        < publish_venv
        < fsync_venv_root
        < reverified
        < min(stop_timers)
        <= max(stop_timers)
        < database_backup
        < stop_app
    )


@pytest.mark.parametrize("failed_check", ["pip", "import"])
def test_release_rebuilds_a_matching_venv_that_fails_validation(tmp_path, failed_check):
    root = tmp_path / "root"
    _prepare_live_release(root)
    venv_root = root / "opt" / "docket-venvs"
    final = venv_root / COMMIT[:12]
    final.mkdir()
    digest_path = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(digest_path)
    runtime_sha = hashlib.sha256(
        (DEPLOY / "runtime-requirements.txt").read_bytes()
    ).hexdigest()
    for name, value in (
        ("RELEASE-commit.txt", COMMIT),
        ("WHEEL-sha256.txt", digest),
        ("DOCKET-version.txt", "0.1.0"),
        ("RUNTIME-LOCK-sha256.txt", runtime_sha),
    ):
        (final / name).write_text(value + "\n", encoding="ascii")
    (final / "corrupt-environment.txt").write_text("bad\n", encoding="ascii")
    fake_bin = _fake_bin(tmp_path)
    environment = _environment(root, fake_bin)
    failed_once = tmp_path / f"{failed_check}-failed-once"
    if failed_check == "pip":
        validation_python = fake_bin / "validation-python"
        _write_executable(
            validation_python,
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [[ "$*" == "-m pip check" && ! -e "${FAIL_ONCE}" ]]; then\n'
            '    : >"${FAIL_ONCE}"\n'
            "    exit 17\n"
            "fi\n"
            "exit 0\n",
        )
        environment["DOCKET_RELEASE_VENV_PYTHON"] = validation_python.as_posix()
    else:
        validation_runuser = fake_bin / "validation-runuser"
        _write_executable(
            validation_runuser,
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [[ ! -e "${FAIL_ONCE}" ]]; then\n'
            '    : >"${FAIL_ONCE}"\n'
            "    exit 18\n"
            "fi\n"
            "exit 0\n",
        )
        environment["DOCKET_RELEASE_RUNUSER"] = validation_runuser.as_posix()
    environment["FAIL_ONCE"] = failed_once.as_posix()

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(digest_path, digest).as_posix(),
        environment=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Matching venv failed validation; rebuilding:" in result.stderr
    assert final.is_dir()
    assert not (final / "corrupt-environment.txt").exists()
    assert not list(venv_root.glob(f"{COMMIT[:12]}.partial*"))
    assert not list(venv_root.glob(f"{COMMIT[:12]}.invalid*"))


def test_release_refuses_to_publish_when_identity_fsync_fails(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    failing_fsync = fake_bin / "failing-fsync-python"
    _write_executable(
        failing_fsync,
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 21\n",
    )
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_FSYNC_PYTHON=failing_fsync.as_posix(),
        ),
    )

    assert result.returncode != 0
    assert "could not durably publish release environment identity" in result.stderr
    assert "Release manifest reverified before mutation" not in result.stdout
    assert "systemctl stop" not in result.stdout
    venv_root = root / "opt" / "docket-venvs"
    assert not (venv_root / COMMIT[:12]).exists()
    assert not list(venv_root.glob(f"{COMMIT[:12]}.partial*"))


def test_release_replaces_a_stale_partial_venv_without_publishing_it_early(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    venv_root = root / "opt" / "docket-venvs"
    stale = venv_root / f"{COMMIT[:12]}.partial"
    stale.mkdir(parents=True)
    (stale / "interrupted-install.txt").write_text("partial\n", encoding="ascii")
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    final = venv_root / COMMIT[:12]
    assert final.is_dir()
    assert (final / "RELEASE-commit.txt").read_text(encoding="ascii").strip() == COMMIT
    assert not list(venv_root.glob(f"{COMMIT[:12]}.partial*"))
    assert not (final / "interrupted-install.txt").exists()


def test_release_replaces_a_stale_stage_under_the_process_lock(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    stage = root / "opt" / f"docket.stage-{COMMIT[:12]}"
    stage.mkdir()
    (stage / "interrupted-copy.txt").write_text("partial\n", encoding="ascii")
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Removing stale release stage:" in result.stdout
    assert not (root / "opt" / "docket" / "interrupted-copy.txt").exists()
    assert not stage.exists()


def test_stage_copy_failure_is_cleaned_and_the_same_release_can_retry(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    failing_cp = fake_bin / "cp"
    _write_executable(
        failing_cp,
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 22\n",
    )
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest)

    failed = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(
            root, fake_bin, DOCKET_RELEASE_COPY=failing_cp.as_posix()
        ),
    )

    stage = root / "opt" / f"docket.stage-{COMMIT[:12]}"
    assert failed.returncode != 0
    assert not stage.exists()
    failing_cp.unlink()

    retried = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(root, fake_bin),
    )
    assert retried.returncode == 0, retried.stdout + retried.stderr
    assert not stage.exists()


def test_release_refuses_an_incompatible_runtime_lock_before_mutation(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    incompatible_python = fake_bin / "incompatible-python"
    _write_executable(
        incompatible_python,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' 'locked dependency is incompatible' >&2\n"
        "exit 19\n",
    )
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_VENV_PYTHON=incompatible_python.as_posix(),
        ),
    )

    assert result.returncode != 0
    assert "release environment installation failed" in result.stderr
    assert "locked dependency is incompatible" in result.stderr
    assert "Database backup verified:" not in result.stdout
    assert "systemctl stop" not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()
    assert not (root / "var" / "backups" / "docket").exists()
    venv_root = root / "opt" / "docket-venvs"
    assert not (venv_root / COMMIT[:12]).exists()
    assert not list(venv_root.glob(f"{COMMIT[:12]}.partial*"))


def test_release_reverification_catches_bundle_substitution_before_mutation(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    copied_deploy = tmp_path / "copied-deploy"
    shutil.copytree(DEPLOY, copied_deploy)
    tampering_python = fake_bin / "tampering-python"
    _write_executable(
        tampering_python,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ ! -e "${FAKE_TAMPER_SENTINEL}" ]]; then\n'
        "    printf '%s\\n' '# substituted' >>\"${FAKE_TAMPER_ASSET}\"\n"
        "    printf '%s\\n' tampered >\"${FAKE_TAMPER_SENTINEL}\"\n"
        "fi\n",
    )
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest, deploy=copied_deploy)

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_VENV_PYTHON=tampering_python.as_posix(),
            FAKE_TAMPER_ASSET=(copied_deploy / "journald-docket.conf").as_posix(),
            FAKE_TAMPER_SENTINEL=(tmp_path / "tampered").as_posix(),
        ),
        deploy=copied_deploy,
    )

    assert result.returncode != 0
    assert "release manifest reverification failed before mutation" in result.stderr
    assert "deploy asset SHA-256 mismatch" in result.stderr
    assert "Database backup verified:" not in result.stdout
    assert "systemctl stop" not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()
    assert not (root / "var" / "backups" / "docket").exists()


def test_release_refuses_an_unusable_venv_before_stopping_services(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin, FAKE_RUNUSER_EXIT="1"),
    )

    assert result.returncode != 0
    assert "docket service user cannot import the installed release" in result.stderr
    assert " -u docket -- " in result.stdout
    assert "import\\ docket\\,\\ docket.api\\,\\ docket.canary" in result.stdout
    assert "systemctl stop docket-canary.timer" not in result.stdout
    assert f"mv -- {root.as_posix()}/opt/docket " not in result.stdout


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("docket-canary.conf", "canary config is missing"),
        ("docket-canary.token", "canary token is missing"),
    ],
)
def test_release_requires_the_existing_canary_files(tmp_path, filename, message):
    root = tmp_path / "root"
    _prepare_live_release(root)
    (root / "etc" / "docket" / filename).unlink()
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert message in result.stderr
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_release_pins_canary_ownership_and_quiesces_all_timer_workers_before_the_app():
    script = (DEPLOY / "release.sh").read_text(encoding="utf-8")

    assert script.count("640:root:docket-canary") == 2
    assert script.count("640:root:docket") == 3
    mutation_boundary = script.index("Release manifest reverified before mutation.")
    snapshot_timers = script.index(
        'for name in "${TIMER_NAMES[@]}"; do', mutation_boundary
    )
    mark_dirty = script.index("TIMER_STATE_DIRTY=1", snapshot_timers)
    stop_timers = script.index('run_host systemctl stop "${name}"', mark_dirty)
    map_worker = script.index('service="${name%.timer}.service"', stop_timers)
    check_workers = script.index("is-active --quiet", map_worker)
    backup = script.index("\ncreate_database_backup\n", check_workers)
    mark_stop_attempted = script.index("APP_STOP_ATTEMPTED=1", backup)
    stop_app = script.index(
        "trace_command systemctl stop docket.service", mark_stop_attempted
    )
    mark_stopped = script.index("APP_STOPPED=1", stop_app)
    move_live = script.index('run_fs mv -- "${OPT_DOCKET}" "${BACKUP}"', stop_app)
    assert (
        snapshot_timers
        < mark_dirty
        < stop_timers
        < map_worker
        < check_workers
        < backup
        < mark_stop_attempted
        < stop_app
        < mark_stopped
        < move_live
    )


def test_release_revalidates_the_signer_identity_acl_and_access_boundary():
    script = (DEPLOY / "release.sh").read_text(encoding="utf-8")

    for required in (
        "validate_canary_identity",
        '"${canary_groups}" == docket-canary',
        '-z "${group_members}"',
        "! -e /nonexistent && ! -L /nonexistent",
        "docket must not be a member of docket-canary",
        "canary payment recipient must match the public web settlement recipient",
        "require_exact_acl",
        "ACL contains missing or unexpected entries",
        "canary configuration",
        "canary payment key",
        "user:docket-canary:--x",
        "user:docket-canary:r--",
        "user:docket-canary:rw-",
        "default:user:docket-canary:rwx",
        "default:user:docket:rwx",
        "default:other::---",
        "canary signer cannot read its configuration",
        "canary signer cannot read and write the live database",
        "docket web user can read canary configuration",
        "docket web user can read canary payment key",
        '"${RUNUSER_COMMAND}" -u docket-canary -g docket-canary -- test',
    ):
        assert required in script
    assert "-G docket" not in script

    identity_check = script.index("\n    validate_canary_identity\n")
    acl_check = script.index("data_acl=$(getfacl", identity_check)
    mutation_boundary = script.index("Release manifest reverified before mutation.")
    assert identity_check < acl_check < mutation_boundary


def test_application_unit_safely_runs_a_module_after_relocating_the_venv(tmp_path):
    partial = tmp_path / "commit.partial"
    partial_bin = partial / "bin"
    partial_bin.mkdir(parents=True)
    (partial_bin / "python").write_text("", encoding="ascii")
    (partial_bin / "uvicorn").write_text(
        f"#!{(partial_bin / 'python').as_posix()}\n", encoding="ascii"
    )

    published = tmp_path / "commit"
    partial.rename(published)

    shebang = (published / "bin" / "uvicorn").read_text(encoding="ascii").strip()
    assert not Path(shebang.removeprefix("#!")).exists()
    assert (published / "bin" / "python").is_file()

    writable_cwd = tmp_path / "writable-cwd"
    installed_modules = tmp_path / "installed-modules"
    writable_cwd.mkdir()
    installed_modules.mkdir()
    (writable_cwd / "uvicorn.py").write_text(
        "print('writable cwd')\n", encoding="ascii"
    )
    (installed_modules / "uvicorn.py").write_text(
        "print('installed module')\n", encoding="ascii"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONSAFEPATH", None)
    environment["PYTHONPATH"] = str(installed_modules)
    unsafe = subprocess.run(
        [sys.executable, "-m", "uvicorn"],
        cwd=writable_cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    safe = subprocess.run(
        [sys.executable, "-P", "-m", "uvicorn"],
        cwd=writable_cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert unsafe.stdout.strip() == "writable cwd"
    assert safe.stdout.strip() == "installed module"

    service = (DEPLOY / "systemd" / "docket.service").read_text(encoding="utf-8")
    exec_start = next(
        line.removeprefix("ExecStart=")
        for line in service.splitlines()
        if line.startswith("ExecStart=")
    )
    assert exec_start == (
        "/opt/docket/.venv/bin/python -P -m uvicorn --factory docket.api:create_app "
        "--host 127.0.0.1 --port 8090"
    )


def test_the_tracked_application_unit_matches_the_verified_runtime():
    service = (DEPLOY / "systemd" / "docket.service").read_text(encoding="utf-8")
    directives = {}
    for line in service.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "[")):
            continue
        key, value = line.split("=", 1)
        directives[key] = value

    assert directives == {
        "Description": "Docket - evidence API and site for BSC ERC-8004 agents",
        "After": "network-online.target",
        "Wants": "network-online.target",
        "Type": "simple",
        "User": "docket",
        "Group": "docket",
        "WorkingDirectory": "/var/lib/docket",
        "Environment": "DOCKET_DB=/var/lib/docket/data/agents.sqlite3",
        "ExecStart": (
            "/opt/docket/.venv/bin/python -P -m uvicorn --factory docket.api:create_app "
            "--host 127.0.0.1 --port 8090"
        ),
        "Restart": "on-failure",
        "RestartSec": "5",
        "UMask": "0027",
        "CapabilityBoundingSet": "",
        "NoNewPrivileges": "true",
        "PrivateTmp": "true",
        "PrivateDevices": "true",
        "ProtectSystem": "strict",
        "ProtectHome": "true",
        "ProtectClock": "true",
        "ProtectHostname": "true",
        "ProtectKernelLogs": "true",
        "ProtectKernelModules": "true",
        "ReadWritePaths": "/var/lib/docket",
        "InaccessiblePaths": (
            "-/etc/docket/docket-canary.conf -/etc/docket/docket-canary-payment.key"
        ),
        "ProtectKernelTunables": "true",
        "ProtectControlGroups": "true",
        "ProtectProc": "invisible",
        "ProcSubset": "pid",
        "LockPersonality": "true",
        "MemoryDenyWriteExecute": "true",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6",
        "RestrictNamespaces": "true",
        "RestrictRealtime": "true",
        "RestrictSUIDSGID": "true",
        "RemoveIPC": "true",
        "SystemCallArchitectures": "native",
        "SystemCallFilter": "@system-service",
        "SystemCallErrorNumber": "EPERM",
        "WantedBy": "multi-user.target",
    }
    assert "EnvironmentFile=" not in service
    assert "PrivateNetwork=" not in service
    assert "IPAddressDeny=" not in service
    runbook = (ROOT / "docs/deployment-runbook.md").read_text(encoding="utf-8")
    for directive in (
        "UMask=0027",
        "CapabilityBoundingSet=",
        "PrivateDevices=true",
        "ProtectClock=true",
        "ProtectHostname=true",
        "ProtectKernelLogs=true",
        "ProtectKernelModules=true",
        "ProtectKernelTunables=true",
        "ProtectControlGroups=true",
        "ProtectProc=invisible",
        "ProcSubset=pid",
        "LockPersonality=true",
        "MemoryDenyWriteExecute=true",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "RestrictNamespaces=true",
        "RestrictRealtime=true",
        "RestrictSUIDSGID=true",
        "RemoveIPC=true",
        "SystemCallArchitectures=native",
        "SystemCallFilter=@system-service",
        "SystemCallErrorNumber=EPERM",
    ):
        assert f"`{directive}`" in runbook
    assert "do not set `PrivateNetwork` or `IPAddressDeny`" in " ".join(runbook.split())


def test_every_tracked_python_service_uses_safe_execution_and_containment():
    expected = {
        "UMask": "0027",
        "CapabilityBoundingSet": "",
        "PrivateDevices": "true",
        "ProtectClock": "true",
        "ProtectHostname": "true",
        "ProtectKernelLogs": "true",
        "ProtectKernelModules": "true",
        "ProtectKernelTunables": "true",
        "ProtectControlGroups": "true",
        "ProtectProc": "invisible",
        "ProcSubset": "pid",
        "LockPersonality": "true",
        "MemoryDenyWriteExecute": "true",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6",
        "RestrictNamespaces": "true",
        "RestrictRealtime": "true",
        "RestrictSUIDSGID": "true",
        "RemoveIPC": "true",
        "SystemCallArchitectures": "native",
        "SystemCallFilter": "@system-service",
        "SystemCallErrorNumber": "EPERM",
    }
    expected_exec_starts = {
        "docket-canary.service": ("/opt/docket/.venv/bin/python -P -m docket.canary"),
        "docket-lp-record.service": (
            "/opt/docket/.venv/bin/python -P -m docket.agents.pancake.lp_record "
            "0xe55816904796341bf8535e25f6c8b647927fc946 7141050 "
            "/var/lib/docket/lp-record/controlled.jsonl --declared-value-usd 50.55 "
            "--recenter-cost-usd 1.00 --horizon-days 30"
        ),
        "docket-refresh.service": ("/opt/docket/.venv/bin/python -P -m docket.refresh"),
        "docket-v3-capture.service": (
            "/opt/docket/.venv/bin/python -P -m docket.advantage.v3.capture "
            "v3-02-yield-router /var/lib/docket/v3-capture/yield"
        ),
        "docket-v3-range-capture.service": (
            "/opt/docket/.venv/bin/python -P -m docket.advantage.v3.capture "
            "v3-05-range-doctor /var/lib/docket/v3-capture/range"
        ),
        "docket-v3-yield-v6-capture.service": (
            "/opt/docket/.venv/bin/python -P -m docket.advantage.v3.capture "
            "v3-06-yield-router-assisted /var/lib/docket/v3-capture/yield-v3-06"
        ),
        "docket-v3-range-v7-capture.service": (
            "/opt/docket/.venv/bin/python -P -m docket.advantage.v3.capture "
            "v3-07-range-doctor /var/lib/docket/v3-capture/range-v3-07"
        ),
        "docket-v3-yield-v8-capture.service": (
            "/opt/docket/.venv/bin/python -P -m docket.advantage.v3.capture "
            "v3-08-yield-router /var/lib/docket/v3-capture/yield-v3-08"
        ),
        "docket.service": (
            "/opt/docket/.venv/bin/python -P -m uvicorn --factory "
            "docket.api:create_app --host 127.0.0.1 --port 8090"
        ),
    }
    services = sorted((DEPLOY / "systemd").glob("*.service"))

    assert {service.name for service in services} == set(expected_exec_starts)
    for service in services:
        directives = {}
        service_text = service.read_text(encoding="utf-8").replace("\\\n", " ")
        for line in service_text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "[")) or "=" not in line:
                continue
            key, value = line.split("=", 1)
            directives.setdefault(key, []).append(value)

        for key, value in expected.items():
            assert directives.get(key) == [value], f"{service.name}: {key}"
        assert directives.get("WorkingDirectory") == ["/var/lib/docket"]
        assert [
            " ".join(value.split()) for value in directives.get("ExecStart", [])
        ] == [expected_exec_starts[service.name]]
        assert "PrivateNetwork" not in directives
        assert "IPAddressDeny" not in directives

    runbook = (ROOT / "docs/deployment-runbook.md").read_text(encoding="utf-8")
    assert "Every tracked Python service" in runbook


def test_release_quiesces_timer_workers_then_backs_up_before_stopping_the_app(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    backup = root / "var" / "backups" / "docket" / "agents-20260822T120000Z.sqlite3"
    assert backup.is_file()
    if os.name != "nt":
        assert backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert connection.execute("SELECT value FROM release_fixture").fetchone() == (
            "preserved",
        )
    checked = result.stdout.index("Database backup verified:")
    assert backup.name in result.stdout[checked:]
    timers = (
        "docket-canary.timer",
        "docket-lp-record.timer",
        "docket-refresh.timer",
        "docket-v3-capture.timer",
        "docket-v3-range-capture.timer",
        "docket-v3-yield-v6-capture.timer",
    )
    stop_timers = [result.stdout.index(f"systemctl stop {timer}") for timer in timers]
    check_workers = [
        result.stdout.index(
            f"systemctl is-active --quiet {timer.removesuffix('.timer')}.service"
        )
        for timer in timers
    ]
    stop_app = result.stdout.index("systemctl stop docket.service")
    swap = result.stdout.index("mv -- ", stop_app)
    assert (
        min(stop_timers)
        <= max(stop_timers)
        < min(check_workers)
        <= max(check_workers)
        < checked
        < stop_app
        < swap
    )
    assert "chmod 0600" in result.stdout
    release = (DEPLOY / "release.sh").read_text(encoding="utf-8")
    assert '"${SCRIPT_DIR}/sqlite_backup.py"' in release
    assert "600:root:root" in release


def test_release_refuses_runtime_mutation_when_sqlite_backup_fails(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    failing_backup = fake_bin / "failing-backup-python"
    _write_executable(
        failing_backup,
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 23\n",
    )
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_BACKUP_PYTHON=failing_backup.as_posix(),
        ),
    )

    assert result.returncode != 0
    assert "SQLite backup failed" in result.stderr
    for timer in (
        "docket-canary.timer",
        "docket-lp-record.timer",
        "docket-refresh.timer",
        "docket-v3-capture.timer",
        "docket-v3-range-capture.timer",
        "docket-v3-yield-v6-capture.timer",
    ):
        stopped = result.stdout.index(f"systemctl stop {timer}")
        restored = result.stdout.index(f"systemctl start {timer}", stopped)
        assert stopped < restored
    assert "systemctl stop docket.service" not in result.stdout
    assert f"mv -- {root.as_posix()}/opt/docket " not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()
    backup_root = root / "var" / "backups" / "docket"
    assert not list(backup_root.glob("*.sqlite3"))
    assert not list(backup_root.glob("*.partial"))


def test_app_stop_failure_restarts_and_health_checks_the_untouched_release(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_SYSTEMCTL=(fake_bin / "systemctl").as_posix(),
            FAKE_APP_STOP_EXIT="27",
        ),
    )

    assert result.returncode != 0
    assert "could not stop docket.service" in result.stderr
    failed_stop = result.stdout.index("systemctl stop docket.service")
    assert "systemctl start docket.service" in result.stdout[failed_stop:]
    assert "Health accepted" in result.stdout[failed_stop:]
    assert "previous release is healthy" in result.stderr
    for timer in (
        "docket-canary.timer",
        "docket-lp-record.timer",
        "docket-refresh.timer",
        "docket-v3-capture.timer",
        "docket-v3-range-capture.timer",
        "docket-v3-yield-v6-capture.timer",
    ):
        stopped = result.stdout.index(f"systemctl stop {timer}")
        restored = result.stdout.index(f"systemctl start {timer}", stopped)
        assert stopped < failed_stop < restored
    assert f"mv -- {root.as_posix()}/opt/docket " not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_release_skips_a_prior_absent_timer_and_restores_later_timers(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    units = root / "etc" / "systemd" / "system"
    units.mkdir(parents=True)
    missing_timer = "docket-refresh.timer"
    for source in (DEPLOY / "systemd").iterdir():
        if source.name != missing_timer:
            shutil.copy2(source, units / source.name)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    count_file = tmp_path / "curl-count"
    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_SYSTEMCTL=(fake_bin / "systemctl").as_posix(),
            FAKE_SYSTEMD_ROOT=units.as_posix(),
            FAKE_CURL_COUNT_FILE=count_file.as_posix(),
            FAKE_CURL_HEALTH_FAILURES="2",
        ),
    )

    assert result.returncode != 0
    assert "previous release is healthy" in result.stderr
    assert f"systemctl stop {missing_timer}" not in result.stdout
    assert f"systemctl start {missing_timer}" not in result.stdout
    assert "systemctl start docket-v3-yield-v6-capture.timer" in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


@pytest.mark.parametrize(
    "active_service",
    [
        "docket-canary.service",
        "docket-lp-record.service",
        "docket-refresh.service",
        "docket-v3-capture.service",
        "docket-v3-range-capture.service",
        "docket-v3-yield-v6-capture.service",
    ],
)
def test_active_timer_worker_aborts_without_killing_it_and_restores_all_timers(
    tmp_path, active_service
):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_SYSTEMCTL=(fake_bin / "systemctl").as_posix(),
            FAKE_ACTIVE_SERVICE=active_service,
        ),
    )

    assert result.returncode != 0
    assert (
        f"{active_service} is active after release timers were stopped" in result.stderr
    )
    timers = (
        "docket-canary.timer",
        "docket-lp-record.timer",
        "docket-refresh.timer",
        "docket-v3-capture.timer",
        "docket-v3-range-capture.timer",
        "docket-v3-yield-v6-capture.timer",
    )
    stopped = [result.stdout.index(f"systemctl stop {timer}") for timer in timers]
    checked = result.stdout.index(f"systemctl is-active --quiet {active_service}")
    assert max(stopped) < checked
    for timer in timers:
        restored = result.stdout.index(f"systemctl start {timer}", checked)
        assert checked < restored
    assert f"systemctl stop {active_service}" not in result.stdout
    assert "Database backup verified:" not in result.stdout
    assert "systemctl stop docket.service" not in result.stdout
    assert f"mv -- {root.as_posix()}/opt/docket " not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()
    assert not (root / "var" / "backups" / "docket").exists()


def test_release_refuses_the_range_activation_window_before_stopping_units(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_NOW_UTC="2026-08-26T12:05:00Z",
        ),
    )

    assert result.returncode != 0
    assert "Range capture activation window" in result.stderr
    assert "systemctl stop docket-canary.timer" not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


@pytest.mark.parametrize("now_utc", ["2026-09-03T12:01:00Z", "2026-09-03T12:02:30Z"])
def test_release_refuses_the_yield_v6_capture_window_before_stopping_units(
    tmp_path, now_utc
):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_NOW_UTC=now_utc,
        ),
    )

    assert result.returncode != 0
    assert "Yield v3-06 capture activation window" in result.stderr
    assert "systemctl stop docket-canary.timer" not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


@pytest.mark.parametrize("now_utc", ["2026-09-06T11:55:00Z", "2026-09-06T12:02:30Z"])
def test_release_refuses_the_yield_v8_capture_window_before_stopping_units(
    tmp_path, now_utc
):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_NOW_UTC=now_utc,
        ),
    )

    assert result.returncode != 0
    assert "Yield v3-08 capture activation window" in result.stderr
    assert "systemctl stop docket-canary.timer" not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


@pytest.mark.parametrize("now_utc", ["2026-09-05T11:55:00Z", "2026-09-05T12:02:30Z"])
def test_release_refuses_the_range_v7_capture_window_before_stopping_units(
    tmp_path, now_utc
):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_NOW_UTC=now_utc,
        ),
    )

    assert result.returncode != 0
    assert "Range v3-07 capture activation window" in result.stderr
    assert "systemctl stop docket-canary.timer" not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_release_tooling_never_changes_or_reloads_nginx():
    release = (DEPLOY / "release.sh").read_text(encoding="utf-8")
    preflight = (DEPLOY / "preflight.sh").read_text(encoding="utf-8")

    assert "nginx" not in release
    assert "systemctl reload nginx" not in preflight
    assert "install /etc/nginx" not in preflight


def test_post_swap_health_failure_restores_the_old_release_and_symlink(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    installed_service = root / "etc" / "systemd" / "system" / "docket.service"
    installed_service.parent.mkdir(parents=True)
    previous_service = b"[Service]\nExecStart=/opt/docket-old/bin/uvicorn\n"
    installed_service.write_bytes(previous_service)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    count_file = tmp_path / "curl-count"

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            FAKE_CURL_COUNT_FILE=count_file.as_posix(),
            FAKE_CURL_HEALTH_FAILURES="2",
        ),
    )

    assert result.returncode != 0
    assert "Rollback completed" in result.stderr
    live = root / "opt" / "docket"
    assert (live / "old-release.txt").read_text(encoding="ascii") == "old\n"
    assert (
        (live / ".venv.target")
        .read_text(encoding="utf-8")
        .strip()
        .endswith(OLD_COMMIT[:12])
    )
    failed = list((root / "opt").glob("docket.failed-20260822T120000Z*"))
    assert len(failed) == 1
    assert (failed[0] / "RELEASE-commit.txt").read_text(
        encoding="ascii"
    ).strip() == COMMIT
    assert installed_service.read_bytes() == previous_service


def test_release_refuses_a_health_response_without_ok_status(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin, FAKE_HEALTH_STATUS="no_snapshot"),
    )

    assert result.returncode != 0
    assert "new release did not pass /health within 30 seconds" in result.stderr
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_release_retires_the_aug21_timer_and_enables_every_timer(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    units = root / "etc" / "systemd" / "system"
    units.mkdir(parents=True)
    (units / "docket-v3-capture.timer").write_text(
        "[Timer]\nOnCalendar=2026-08-21 12:00:00 UTC\n", encoding="utf-8"
    )
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest)

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "http://127.0.0.1:8090/advantage/v3.json" in result.stdout
    assert "systemctl disable --now docket-v3-capture.timer" in result.stdout
    installed = (units / "docket-v3-capture.timer").read_text(encoding="utf-8")
    assert "2026-08-21" not in installed
    assert "OnCalendar=2026-08-26 11:50:00 UTC" in installed
    live = root / "opt" / "docket"
    assert (live / "RELEASE-commit.txt").read_text(encoding="ascii").strip() == COMMIT
    assert (live / "WHEEL-sha256.txt").read_text(encoding="ascii").split()[0] == digest
    assert (live / "release-manifest.json").read_bytes() == manifest.read_bytes()
    assert (live / "deploy" / "runtime-requirements.txt").read_bytes() == (
        DEPLOY / "runtime-requirements.txt"
    ).read_bytes()
    lock_sha = hashlib.sha256(
        (DEPLOY / "runtime-requirements.txt").read_bytes()
    ).hexdigest()
    assert (live / "RUNTIME-LOCK-sha256.txt").read_text(
        encoding="ascii"
    ).strip() == lock_sha
    assert f"{COMMIT[:12]}.partial/bin/python -m pip check" in result.stdout
    assert not list((root / "opt" / "docket-venvs").glob(f"{COMMIT[:12]}.partial*"))
    last_smoke = result.stdout.rindex("http://127.0.0.1:8090/static/style.css")
    for timer in (
        "docket-canary.timer",
        "docket-lp-record.timer",
        "docket-refresh.timer",
        "docket-v3-capture.timer",
        "docket-v3-range-capture.timer",
        "docket-v3-yield-v6-capture.timer",
    ):
        enable = result.stdout.index(f"systemctl enable --now {timer}")
        assert last_smoke < enable
    for name in (
        "docket.service",
        "docket-v3-range-capture.service",
        "docket-v3-range-capture.timer",
        "docket-v3-yield-v6-capture.service",
        "docket-v3-yield-v6-capture.timer",
    ):
        assert (units / name).read_bytes() == (DEPLOY / "systemd" / name).read_bytes()


def test_release_keeps_an_intentionally_disabled_canary_timer_disabled(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest)

    result = _run(
        "release.sh",
        "--dry-run",
        manifest.as_posix(),
        environment=_environment(
            root,
            fake_bin,
            FAKE_DISABLED_TIMER="docket-canary.timer",
            DOCKET_RELEASE_SYSTEMCTL=(fake_bin / "systemctl").as_posix(),
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "systemctl disable --now docket-canary.timer" in result.stdout
    assert "systemctl enable --now docket-canary.timer" not in result.stdout
    assert "systemctl enable --now docket-refresh.timer" in result.stdout


def test_release_copies_only_changed_unit_files_and_prints_the_diff(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    units = root / "etc" / "systemd" / "system"
    units.mkdir(parents=True)
    shutil.copy2(
        DEPLOY / "systemd" / "docket-canary.service",
        units / "docket-canary.service",
    )
    (units / "docket-canary.timer").write_text(
        "[Timer]\nOnCalendar=hourly\n", encoding="utf-8"
    )
    unchanged_mtime = (units / "docket-canary.service").stat().st_mtime_ns
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Unit unchanged: docket-canary.service" in result.stdout
    assert (units / "docket-canary.service").stat().st_mtime_ns == unchanged_mtime
    assert "Unit differs: docket-canary.timer" in result.stdout
    assert "-OnCalendar=hourly" in result.stdout
    assert (units / "docket-canary.timer").read_bytes() == (
        DEPLOY / "systemd" / "docket-canary.timer"
    ).read_bytes()


def test_release_installs_journald_config_only_once(tmp_path):
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    fake_bin = _fake_bin(tmp_path)
    absent_root = tmp_path / "absent-root"
    absent_root.mkdir()
    _prepare_live_release(absent_root)

    installed = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(absent_root, fake_bin),
    )

    assert installed.returncode == 0, installed.stdout + installed.stderr
    target = absent_root / "etc" / "systemd" / "journald.conf.d" / "docket.conf"
    assert target.read_bytes() == (DEPLOY / "journald-docket.conf").read_bytes()
    assert "systemctl restart systemd-journald" in installed.stdout

    present_root = tmp_path / "present-root"
    present_root.mkdir()
    _prepare_live_release(present_root)
    existing = present_root / "etc" / "systemd" / "journald.conf.d" / "docket.conf"
    existing.parent.mkdir(parents=True)
    shutil.copy2(DEPLOY / "journald-docket.conf", existing)

    preserved = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(present_root, fake_bin),
    )

    assert preserved.returncode == 0, preserved.stdout + preserved.stderr
    assert existing.read_bytes() == (DEPLOY / "journald-docket.conf").read_bytes()
    assert "Journald config already exists; preserving it." in preserved.stdout
    assert "systemctl restart systemd-journald" in preserved.stdout


def test_release_prepares_and_flushes_persistent_journal_in_order(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    create_directory = result.stdout.index(
        "install -d -m 2755 -o root -g systemd-journal /var/log/journal"
    )
    create_tmpfiles = result.stdout.index(
        "systemd-tmpfiles --create --prefix /var/log/journal"
    )
    restart = result.stdout.index("systemctl restart systemd-journald")
    flush = result.stdout.index("journalctl --flush")
    assert create_directory < create_tmpfiles < restart < flush


def test_release_refuses_when_journal_remains_volatile(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            FAKE_JOURNAL_HEADER=(
                "File path: /run/log/journal/0123456789abcdef/system.journal"
            ),
        ),
    )

    assert result.returncode != 0
    assert (
        "persistent journald verification failed: no /var/log/journal file was found"
        in result.stderr
    )


def test_release_accepts_a_persistent_journal_header(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(
            root,
            fake_bin,
            FAKE_JOURNAL_HEADER=(
                "File path: /var/log/journal/0123456789abcdef/system.journal"
            ),
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{(fake_bin / 'journalctl').as_posix()} --header" in result.stdout


def test_release_refuses_a_different_existing_journald_config(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    existing = root / "etc" / "systemd" / "journald.conf.d" / "docket.conf"
    existing.parent.mkdir(parents=True)
    existing.write_text("[Journal]\nStorage=auto\n", encoding="utf-8")
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "existing journald config differs" in result.stderr
    assert existing.read_text(encoding="utf-8") == "[Journal]\nStorage=auto\n"
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


@pytest.mark.parametrize("endpoint", ["stats", "services", "advantage/v3.json"])
def test_release_rolls_back_when_a_served_contract_is_missing_fields(
    tmp_path, endpoint
):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin, FAKE_INVALID_ENDPOINT=endpoint),
    )

    assert result.returncode != 0
    assert f"served /{endpoint} is missing its release contract fields" in result.stderr
    assert "systemctl enable --now docket-canary.timer" not in result.stdout
    assert "Rollback completed" in result.stderr
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


@pytest.mark.parametrize(
    ("endpoint", "message"),
    [
        ("service-ids", "served /services does not match the release inventory"),
        ("categories", "served /categories does not match the release inventory"),
        ("v3-states", "served /advantage/v3.json does not match the release state"),
        ("homepage", "served homepage smoke failed"),
        ("static", "served static asset smoke failed"),
    ],
)
def test_release_rolls_back_when_exact_inventory_or_web_smoke_differs(
    tmp_path, endpoint, message
):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin, FAKE_INVALID_ENDPOINT=endpoint),
    )

    assert result.returncode != 0
    assert message in result.stderr
    assert "systemctl enable --now docket-canary.timer" not in result.stdout
    assert "Rollback completed" in result.stderr
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_release_rolls_back_when_v3_returns_503(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        _write_release_manifest(wheel, digest).as_posix(),
        environment=_environment(root, fake_bin, FAKE_V3_STATUS="503"),
    )

    assert result.returncode != 0
    assert (
        "served /advantage/v3.json is missing its release contract fields"
        in result.stderr
    )
    assert "Rollback completed" in result.stderr
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_preflight_accepts_the_guarded_production_baseline(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)

    result = _run(
        "preflight.sh",
        "--dry-run",
        "22",
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "GO: release preflight passed" in result.stdout
    assert "22 nginx warnings" in result.stdout
    assert "2097152 KiB free" in result.stdout
    assert "Archived and active journals take up 64.0M" in result.stdout
    assert "docket.service" in result.stdout


def test_preflight_accepts_nginx_prefixed_warning_format(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)

    result = _run(
        "preflight.sh",
        "--dry-run",
        "22",
        environment=_environment(
            root,
            fake_bin,
            FAKE_NGINX_WARNING="nginx: [warn] test warning",
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "22 nginx warnings" in result.stdout


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"FAKE_NGINX_WARNINGS": "21"}, "warning count is 21, expected 22"),
        ({"FAKE_NGINX_SUCCESS": "0"}, "did not report 'test is successful'"),
        ({"FAKE_NGINX_EXIT": "1"}, "nginx -t failed with exit 1"),
        ({"FAKE_DF_AVAILABLE_KIB": "2097151"}, "less than 2097152 KiB"),
        ({"FAKE_SYSTEMD_VERIFY_EXIT": "1"}, "systemd unit verification failed"),
        ({"FAKE_JOURNAL_EXIT": "1"}, "journal disk-usage check failed"),
    ],
)
def test_preflight_refuses_every_failed_gate(tmp_path, overrides, message):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)

    result = _run(
        "preflight.sh",
        "--dry-run",
        "22",
        environment=_environment(root, fake_bin, **overrides),
    )

    assert result.returncode != 0
    assert message in result.stderr
