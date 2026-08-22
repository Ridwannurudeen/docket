import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from docket.advantage.v3 import calibration, calibration_driver
from docket.advantage.v3.seats import claude_cli, codex_cli, record
from docket.advantage.v3.spec import load

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docket/advantage/v3/specs/v3-03-warden-security.json"
CALIBRATION_PATH = ROOT / "docket/advantage/v3/sources/warden-calibration-set.json"
SPEC = load(SPEC_PATH)


@pytest.fixture(autouse=True)
def _clear_seat_state(monkeypatch):
    for module in (codex_cli, claude_cli):
        monkeypatch.setattr(module, "_model", None)
        monkeypatch.setattr(module, "_last_command", None)


def _install_fake_clis(tmp_path: Path, monkeypatch) -> Path:
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    script = bin_dir / "fake_cli.py"
    script.write_text(
        """
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

cli, *args = sys.argv[1:]
prompt = sys.stdin.buffer.read()
log_path = Path(os.environ["FAKE_CLI_LOG"])
with log_path.open("a", encoding="utf-8") as log:
    log.write(json.dumps({
        "cli": cli,
        "argv": args,
        "cwd": os.getcwd(),
        "prompt_base64": base64.b64encode(prompt).decode("ascii"),
        "repo_hint_present": "W7_REPO_HINT" in os.environ,
        "key_hint_present": "W7_KEY_HINT" in os.environ,
    }, sort_keys=True) + "\\n")

mode = os.environ.get("FAKE_CLI_MODE", "bytes")
if "--version" in args:
    version = "codex-cli 99.1\\n" if cli == "codex" else "88.2 (Claude Code)\\n"
    sys.stdout.buffer.write(version.encode())
    raise SystemExit(9 if mode == "version-fail" else 0)

if mode == "nonzero":
    if cli == "codex":
        output = Path(args[args.index("-o") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"nonzero-response")
        sys.stderr.buffer.write(b"model: fake-codex-model\\n")
    else:
        sys.stdout.buffer.write(b"nonzero-response")
    raise SystemExit(7)
if mode == "timeout":
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    Path(os.environ["FAKE_CHILD_PID"]).write_text(str(child.pid), encoding="ascii")
    time.sleep(10)

if cli == "codex":
    output = Path(args[args.index("-o") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"" if mode == "empty" else b"raw-\\x00-codex\\n\\n")
    sys.stderr.buffer.write(b"model: fake-codex-model\\n")
elif args[args.index("--output-format") + 1] == "json":
    body = {
        "result": "MODEL_METADATA_OK\\n",
        "usage": {
            "input_tokens": 2,
            "output_tokens": 3,
            "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 7,
        },
        "modelUsage": {
            "fake-aux-model": {
                "inputTokens": 11,
                "outputTokens": 13,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
            },
            "fake-claude-model": {
                "inputTokens": 2,
                "outputTokens": 3,
                "cacheReadInputTokens": 5,
                "cacheCreationInputTokens": 7,
            },
        },
    }
    sys.stdout.buffer.write(json.dumps(body).encode())
else:
    sys.stdout.buffer.write(b"" if mode == "empty" else b"raw-\\x00-claude\\n\\n")
""".lstrip(),
        encoding="utf-8",
    )
    if os.name == "nt":
        for name in ("codex", "claude"):
            (bin_dir / f"{name}.cmd").write_text(
                f'@"{sys.executable}" "{script}" {name} %*\n', encoding="utf-8"
            )
    else:
        for name in ("codex", "claude"):
            launcher = bin_dir / name
            launcher.write_text(
                f"#!{sys.executable}\n"
                f"import runpy, sys\n"
                f"sys.argv = [{str(script)!r}, {name!r}, *sys.argv[1:]]\n"
                f"runpy.run_path({str(script)!r}, run_name='__main__')\n",
                encoding="utf-8",
            )
            launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_CLI_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("W7_REPO_HINT", str(ROOT))
    monkeypatch.setenv("W7_KEY_HINT", str(CALIBRATION_PATH))
    return tmp_path / "calls.jsonl"


def _calls(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    ("module", "expected"),
    [(codex_cli, b"raw-\x00-codex\n\n"), (claude_cli, b"raw-\x00-claude\n\n")],
)
def test_seats_return_the_fake_clis_raw_bytes(tmp_path, monkeypatch, module, expected):
    _install_fake_clis(tmp_path, monkeypatch)

    assert module.ask(b"derived prompt\n") == expected


@pytest.mark.parametrize("module", [codex_cli, claude_cli])
@pytest.mark.parametrize("returned", ["not bytes", b"", None])
def test_non_bytes_and_absent_subprocess_results_become_none(
    tmp_path, monkeypatch, module, returned
):
    _install_fake_clis(tmp_path, monkeypatch)
    model = "fake-codex-model" if module is codex_cli else "fake-claude-model"
    monkeypatch.setattr(module, "_model", model)
    monkeypatch.setattr(
        record,
        "run_process",
        lambda *args, **kwargs: record.ProcessResult(
            0, returned, b"model: fake-codex-model\n", False
        ),
    )

    assert module.ask(b"derived prompt\n") is None


@pytest.mark.parametrize("module", [codex_cli, claude_cli])
def test_nonzero_cli_exit_becomes_none(tmp_path, monkeypatch, module):
    _install_fake_clis(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLI_MODE", "nonzero")
    model = "fake-codex-model" if module is codex_cli else "fake-claude-model"
    monkeypatch.setattr(module, "_model", model)

    assert module.ask(b"derived prompt\n") is None


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=False,
            text=True,
        )
        return result.returncode == 0 and f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill_test_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize("module", [codex_cli, claude_cli])
def test_timeout_becomes_none_and_kills_the_process_tree(tmp_path, monkeypatch, module):
    _install_fake_clis(tmp_path, monkeypatch)
    pid_path = tmp_path / "child.pid"
    monkeypatch.setenv("FAKE_CLI_MODE", "timeout")
    monkeypatch.setenv("FAKE_CHILD_PID", str(pid_path))
    monkeypatch.setattr(module, "TIMEOUT_SECONDS", 3.0)
    model = "fake-codex-model" if module is codex_cli else "fake-claude-model"
    monkeypatch.setattr(module, "_model", model)

    assert module.ask(b"derived prompt\n") is None
    assert pid_path.is_file()
    pid = int(pid_path.read_text(encoding="ascii"))
    deadline = time.monotonic() + 2
    while _pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    alive = _pid_exists(pid)
    if alive:
        _kill_test_pid(pid)
    assert not alive


def test_failed_tree_kill_still_has_a_bounded_pipe_wait(tmp_path, monkeypatch):
    class Pipe:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class Process:
        returncode = None
        stdout = Pipe()
        stderr = Pipe()

        def communicate(self, timeout):
            raise subprocess.TimeoutExpired("fake", timeout)

    process = Process()
    prompt_path = tmp_path / "prompt.bin"
    prompt_path.write_bytes(b"prompt")
    monkeypatch.setattr(record, "_popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(record, "_kill_process_tree", lambda _process: None)

    result = record.run_process(
        ["fake"],
        prompt_path=prompt_path,
        cwd=tmp_path,
        response_path=None,
        timeout=0.1,
    )

    assert result.timed_out is True
    assert result.response is None
    assert process.stdout.closed is True
    assert process.stderr.closed is True


@pytest.mark.parametrize("module", [codex_cli, claude_cli])
def test_model_build_refuses_when_the_version_command_fails(
    tmp_path, monkeypatch, module
):
    _install_fake_clis(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLI_MODE", "version-fail")

    with pytest.raises(record.SeatUnavailable, match="version"):
        module.model_build()


@pytest.mark.parametrize(
    ("module", "cli", "version", "model"),
    [
        (codex_cli, "codex", "codex-cli 99.1", "fake-codex-model"),
        (claude_cli, "claude", "88.2 (Claude Code)", "fake-claude-model"),
    ],
)
def test_model_build_pins_cli_owned_model_and_records_the_exact_isolated_command(
    tmp_path, monkeypatch, module, cli, version, model
):
    log_path = _install_fake_clis(tmp_path, monkeypatch)

    build = module.model_build()
    assert module.ask(b"derived prompt without answer key\n") is not None

    calls = _calls(log_path)
    seat_call = calls[-1]
    executable = record.resolve_cli(cli)
    exact_command = subprocess.list2cmdline([executable, *seat_call["argv"]])
    assert version in build
    assert model in build
    assert exact_command in build
    assert seat_call["repo_hint_present"] is False
    assert seat_call["key_hint_present"] is False
    assert str(ROOT).lower() not in seat_call["cwd"].lower()
    assert str(ROOT).lower() not in " ".join(seat_call["argv"]).lower()
    assert base64.b64decode(seat_call["prompt_base64"]) == (
        b"derived prompt without answer key\n"
    )
    assert seat_call["argv"][seat_call["argv"].index("--model") + 1] == model
    if cli == "codex":
        assert ["--sandbox", "danger-full-access"] == seat_call["argv"][
            seat_call["argv"].index("--sandbox") : seat_call["argv"].index("--sandbox")
            + 2
        ]
        assert "--ignore-user-config" in seat_call["argv"]
        assert "--ignore-rules" in seat_call["argv"]
        assert ["--disable", "plugins"] == seat_call["argv"][
            seat_call["argv"].index("--disable") : seat_call["argv"].index("--disable")
            + 2
        ]
    else:
        assert "--safe-mode" in seat_call["argv"]
        assert ["--tools", ""] == seat_call["argv"][
            seat_call["argv"].index("--tools") : seat_call["argv"].index("--tools") + 2
        ]


def test_driver_uses_the_seat_owned_model_build_before_opening_the_attempt(
    tmp_path, monkeypatch
):
    def seat(_prompt):
        return b"{}"

    seat.model_build = lambda: "cli-owned-build-and-command"
    monkeypatch.setattr(calibration_driver, "_resolve_seat", lambda _reference: seat)

    code = calibration_driver.main(
        [
            str(SPEC_PATH),
            str(tmp_path / "capture"),
            "--evaluator-id",
            "seat-a",
            "--session-id",
            "seat-a-2026-08-25",
            "--calibration-set",
            str(CALIBRATION_PATH),
            "--seat",
            "fake:ask",
        ]
    )

    assert code == 0
    request = json.loads(
        calibration.request_path(SPEC, tmp_path / "capture", "seat-a", 1).read_text(
            encoding="utf-8"
        )
    )
    assert request["model_build"] == "cli-owned-build-and-command"


def test_driver_refuses_spent_and_shared_seats_before_model_provenance(
    tmp_path, monkeypatch
):
    calls = {"model_build": 0}

    def seat(_prompt):
        return b"{}"

    def model_build():
        calls["model_build"] += 1
        return "must-not-be-read"

    seat.model_build = model_build
    monkeypatch.setattr(calibration_driver, "_resolve_seat", lambda _reference: seat)
    raw_set = CALIBRATION_PATH.read_bytes()

    spent_root = tmp_path / "spent"
    request = calibration.open_attempt(
        SPEC,
        spent_root,
        evaluator_id="seat-a",
        model_build="first-build",
        session_id="first-session",
        calibration_set=raw_set,
    )
    calibration.record_response(
        SPEC,
        spent_root,
        evaluator_id="seat-a",
        attempt_ordinal=request["attempt_ordinal"],
        raw_response=b"{}",
    )
    spent = calibration_driver.main(
        [
            str(SPEC_PATH),
            str(spent_root),
            "--evaluator-id",
            "seat-a",
            "--session-id",
            "second-session",
            "--calibration-set",
            str(CALIBRATION_PATH),
            "--seat",
            "fake:ask",
        ]
    )

    shared_root = tmp_path / "shared"
    request = calibration.open_attempt(
        SPEC,
        shared_root,
        evaluator_id="seat-a",
        model_build="first-build",
        session_id="shared-session",
        calibration_set=raw_set,
    )
    calibration.record_response(
        SPEC,
        shared_root,
        evaluator_id="seat-a",
        attempt_ordinal=request["attempt_ordinal"],
        raw_response=b"{}",
    )
    shared = calibration_driver.main(
        [
            str(SPEC_PATH),
            str(shared_root),
            "--evaluator-id",
            "seat-b",
            "--session-id",
            "shared-session",
            "--calibration-set",
            str(CALIBRATION_PATH),
            "--seat",
            "fake:ask",
        ]
    )

    assert spent == 2
    assert shared == 2
    assert calls["model_build"] == 0


def test_codex_self_test_prints_only_length_and_cli_owned_build(
    tmp_path, monkeypatch, capsys
):
    _install_fake_clis(tmp_path, monkeypatch)

    assert codex_cli.main(["--self-test"]) == 0

    output = capsys.readouterr().out
    assert "bytes=13" in output
    assert "codex-cli 99.1" in output
    assert "fake-codex-model" in output
