"""Call the installed Codex CLI as an isolated evaluator seat."""

import argparse
import re
from pathlib import Path

from . import record

TIMEOUT_SECONDS = 300
VERSION_TIMEOUT_SECONDS = 30
_model = None
_last_command = None


def _command(executable: str, model: str | None) -> list[str]:
    command = [
        executable,
        "exec",
        "--sandbox",
        "danger-full-access",
        "-C",
        ".",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        "--color",
        "never",
    ]
    if model is not None:
        command.extend(("--model", model))
    command.extend(("-o", str(Path("..") / "last-message.bin"), "-"))
    return command


def _model_line(stderr: object) -> str:
    if not isinstance(stderr, bytes):
        raise record.SeatUnavailable(
            "Codex emitted no byte transcript with a model line"
        )
    matches = re.findall(rb"^model:\s*(\S.*?)\s*$", stderr, re.MULTILINE)
    if len(matches) != 1:
        raise record.SeatUnavailable("Codex emitted no unique model line")
    try:
        return matches[0].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise record.SeatUnavailable("Codex model line is not UTF-8") from exc


def _invoke(prompt: bytes, *, model: str | None):
    executable = record.resolve_cli("codex")
    if executable is None:
        raise record.SeatUnavailable("Codex CLI was not found")
    with record.temporary_workspace("docket-codex-seat-") as (root, scratch):
        prompt_path = root / "prompt.bin"
        prompt_path.write_bytes(prompt)
        command = _command(executable, model)
        result = record.run_process(
            command,
            prompt_path=prompt_path,
            cwd=scratch,
            response_path=root / "last-message.bin",
            timeout=TIMEOUT_SECONDS,
        )
    return command, result


def ask(prompt: bytes) -> bytes | None:
    global _last_command, _model
    try:
        command, result = _invoke(prompt, model=_model)
        response = record.response_bytes(result.response)
        if response is None:
            return None
        observed_model = _model_line(result.stderr)
        if _model is not None and observed_model != _model:
            return None
        _model = observed_model
        _last_command = command
        return response
    except record.SeatUnavailable:
        return None


def model_build() -> str:
    global _last_command, _model
    executable = record.resolve_cli("codex")
    if executable is None:
        raise record.SeatUnavailable("Codex CLI version command cannot be found")
    version = (
        record.version_output(
            [executable, "--version"], timeout=VERSION_TIMEOUT_SECONDS
        )
        .decode("utf-8")
        .strip()
    )
    if _model is None:
        command, result = _invoke(
            b"Reply with exactly: MODEL_METADATA_OK\n", model=None
        )
        if record.response_bytes(result.response) is None:
            raise record.SeatUnavailable("Codex model probe failed")
        _model = _model_line(result.stderr)
        _last_command = _command(executable, _model)
    command = _last_command or _command(executable, _model)
    return f"version={version}; model={_model}; command={record.command_line(command)}"


ask.model_build = model_build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_test:
        parser.error("--self-test is required")
    response = ask(b"Reply with exactly: SEAT_CLI_SELF_TEST_OK\n")
    if response is None:
        print("self-test refused: Codex returned no response bytes")
        return 2
    try:
        build = model_build()
    except record.SeatUnavailable as exc:
        print(f"self-test refused: {exc}")
        return 2
    print(f"bytes={len(response)}")
    print(f"model_build={build}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
