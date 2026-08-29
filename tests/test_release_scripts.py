import hashlib
import os
import shutil
import subprocess
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


def _write_wheel(path: Path) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("docket/__init__.py", "")
        archive.writestr(
            "docket-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: docket\nVersion: 0.1.0\n",
        )
        archive.writestr(
            "docket-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
        archive.writestr("docket-0.1.0.dist-info/RECORD", "")
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
            printf '%s\n' '{"services":[{"service_id":"range-doctor","paid_stock":false,"stock_status":"candidate","admission":{"fresh_paired_benchmark":false,"cold_canary":false,"decision_grade_presenter":true,"true_settlement":false}}],"total":1,"category":null,"ordering":"service_id","declaration":"test"}'
        fi
        ;;
    */advantage/v3.json)
        if [[ "${FAKE_V3_STATUS:-200}" == 503 ]]; then
            exit 22
        elif [[ "${FAKE_INVALID_ENDPOINT:-}" == advantage/v3.json ]]; then
            printf '%s\n' '{}'
        else
            printf '%s\n' '{"families":[{"spec_id":"v3-04-warden-security"}],"summary":{"n_families":1}}'
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
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "is-active --quiet docket-canary.service" && "${FAKE_CANARY_ACTIVE:-0}" == 1 ]]; then
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
    script: str, *args: str, environment: dict[str, str]
) -> subprocess.CompletedProcess:
    assert BASH.is_file(), f"Git Bash is required at {BASH}"
    return subprocess.run(
        [str(BASH), str(DEPLOY / script), *args],
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


def test_release_refuses_a_wheel_sha_mismatch_before_creating_a_venv(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"not the expected wheel")

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        "0" * 64,
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "wheel SHA-256 mismatch" in result.stderr
    assert not (root / "opt" / "docket-venvs").exists()


def test_release_refuses_an_existing_venv_with_different_identity(tmp_path):
    root = tmp_path / "root"
    venv = root / "opt" / "docket-venvs" / COMMIT[:12]
    venv.mkdir(parents=True)
    (venv / "RELEASE-commit.txt").write_text(OLD_COMMIT + "\n", encoding="ascii")
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert "existing venv identity differs" in result.stderr
    assert (venv / "RELEASE-commit.txt").read_text(
        encoding="ascii"
    ).strip() == OLD_COMMIT


def test_release_refuses_when_pip_show_disagrees_with_the_wheel(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
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
        wheel.as_posix(),
        COMMIT,
        digest,
        environment=_environment(root, fake_bin),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lower_umask = result.stdout.index("+ umask 022")
    create_venv = result.stdout.index("python3 -m venv")
    install_wheel = result.stdout.index("/bin/python -m pip install")
    pip_check = result.stdout.index("/bin/python -m pip check")
    assert lower_umask < create_venv < install_wheel < pip_check


def test_release_refuses_an_unusable_venv_before_stopping_services(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
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
        wheel.as_posix(),
        COMMIT,
        digest,
        environment=_environment(root, fake_bin),
    )

    assert result.returncode != 0
    assert message in result.stderr
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_release_pins_canary_ownership_and_stops_it_before_the_app():
    script = (DEPLOY / "release.sh").read_text(encoding="utf-8")

    assert script.count("640:root:docket") == 2
    stop_timer = script.index("run_host systemctl stop docket-canary.timer")
    check_canary = script.index(
        "systemctl is-active --quiet docket-canary.service", stop_timer
    )
    stop_app = script.index("run_host systemctl stop docket.service", check_canary)
    move_live = script.index('run_fs mv -- "${OPT_DOCKET}" "${BACKUP}"', stop_app)
    assert stop_timer < check_canary < stop_app < move_live


def test_active_canary_abort_restores_the_canary_timer(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_SYSTEMCTL=(fake_bin / "systemctl").as_posix(),
            FAKE_CANARY_ACTIVE="1",
        ),
    )

    assert result.returncode != 0
    assert "docket-canary.service is active after its timer was stopped" in result.stderr
    stop_timer = result.stdout.index("systemctl stop docket-canary.timer")
    restore_timer = result.stdout.index(
        "systemctl start docket-canary.timer", stop_timer
    )
    assert stop_timer < restore_timer
    assert "systemctl stop docket.service" not in result.stdout
    assert f"mv -- {root.as_posix()}/opt/docket " not in result.stdout
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_release_refuses_the_range_activation_window_before_stopping_units(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
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


def test_release_refuses_the_yield_v6_capture_window_before_stopping_units(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
        environment=_environment(
            root,
            fake_bin,
            DOCKET_RELEASE_NOW_UTC="2026-09-03T12:01:00Z",
        ),
    )

    assert result.returncode != 0
    assert "Yield v3-06 capture activation window" in result.stderr
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
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    count_file = tmp_path / "curl-count"

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
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


def test_release_refuses_a_health_response_without_ok_status(tmp_path):
    root = tmp_path / "root"
    _prepare_live_release(root)
    fake_bin = _fake_bin(tmp_path)
    wheel = tmp_path / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
        environment=_environment(root, fake_bin, FAKE_HEALTH_STATUS="no_snapshot"),
    )

    assert result.returncode != 0
    assert "new release did not pass /health within 30 seconds" in result.stderr
    assert (root / "opt" / "docket" / "old-release.txt").is_file()


def test_release_retires_the_aug21_timer_and_enables_all_six_timers(tmp_path):
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

    result = _run(
        "release.sh",
        "--dry-run",
        wheel.as_posix(),
        COMMIT,
        digest,
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
    assert f"{COMMIT[:12]}/bin/python -m pip check" in result.stdout
    for timer in (
        "docket-canary.timer",
        "docket-lp-record.timer",
        "docket-refresh.timer",
        "docket-v3-capture.timer",
        "docket-v3-range-capture.timer",
        "docket-v3-yield-v6-capture.timer",
    ):
        assert f"systemctl enable --now {timer}" in result.stdout
    for name in (
        "docket-v3-range-capture.service",
        "docket-v3-range-capture.timer",
        "docket-v3-yield-v6-capture.service",
        "docket-v3-yield-v6-capture.timer",
    ):
        assert (units / name).read_bytes() == (DEPLOY / "systemd" / name).read_bytes()


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
        wheel.as_posix(),
        COMMIT,
        digest,
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
        wheel.as_posix(),
        COMMIT,
        digest,
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
        wheel.as_posix(),
        "c" * 40,
        digest,
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
        wheel.as_posix(),
        COMMIT,
        digest,
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
        wheel.as_posix(),
        COMMIT,
        digest,
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
        wheel.as_posix(),
        COMMIT,
        digest,
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
        wheel.as_posix(),
        COMMIT,
        digest,
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
        wheel.as_posix(),
        COMMIT,
        digest,
        environment=_environment(root, fake_bin, FAKE_INVALID_ENDPOINT=endpoint),
    )

    assert result.returncode != 0
    assert f"served /{endpoint} is missing its release contract fields" in result.stderr
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
        wheel.as_posix(),
        COMMIT,
        digest,
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
