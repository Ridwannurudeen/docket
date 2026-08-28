"""Run one CLI in an empty directory and preserve its response bytes."""

import os
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

POST_KILL_WAIT_SECONDS = 5


class SeatUnavailable(RuntimeError):
    """The requested CLI cannot provide a provenance-bound response."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    response: object
    stderr: object
    timed_out: bool


def resolve_cli(name: str) -> str | None:
    return shutil.which(name)


def isolated_environment() -> dict[str, str]:
    environment = os.environ.copy()
    repository = str(Path.cwd().resolve()).casefold()
    path_parts = [
        part
        for part in environment.get("PATH", "").split(os.pathsep)
        if repository not in part.casefold()
    ]
    environment["PATH"] = os.pathsep.join(path_parts)
    for name, value in tuple(environment.items()):
        if name == "PATH":
            continue
        if repository in value.casefold():
            environment.pop(name)
    for name in (
        "CLAUDE_PROJECT_DIR",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "INIT_CWD",
        "OLDPWD",
        "PWD",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "npm_config_local_prefix",
    ):
        environment.pop(name, None)
    environment["NO_COLOR"] = "1"
    return environment


@contextmanager
def temporary_workspace(prefix: str):
    root = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        scratch = root / "work"
        scratch.mkdir()
        yield root, scratch
    finally:
        last_error = None
        for _ in range(20):
            try:
                shutil.rmtree(root)
                break
            except FileNotFoundError:
                break
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.1)
        if root.exists():
            raise SeatUnavailable(
                f"temporary seat directory {root} remained in use"
            ) from last_error


def _popen(argv: list[str], *, cwd: Path, stdin):
    options = {
        "cwd": cwd,
        "env": isolated_environment(),
        "stdin": stdin,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(argv, **options)


def _kill_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        try:
            subprocess.run(
                [
                    str(system_root / "System32" / "taskkill.exe"),
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()


def run_process(
    argv: list[str],
    *,
    prompt_path: Path,
    cwd: Path,
    response_path: Path | None,
    timeout: float,
) -> ProcessResult:
    with prompt_path.open("rb") as prompt:
        process = _popen(argv, cwd=cwd, stdin=prompt)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            try:
                _stdout, stderr = process.communicate(timeout=POST_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
                stderr = None
            return ProcessResult(process.returncode, None, stderr, True)
    if process.returncode != 0:
        return ProcessResult(process.returncode, None, stderr, False)
    if response_path is None:
        response = stdout
    else:
        try:
            response = response_path.read_bytes()
        except OSError:
            response = None
    return ProcessResult(process.returncode, response, stderr, False)


def version_output(argv: list[str], *, timeout: float) -> bytes:
    process = _popen(argv, cwd=Path(tempfile.gettempdir()), stdin=subprocess.DEVNULL)
    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_process_tree(process)
        try:
            process.communicate(timeout=POST_KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        raise SeatUnavailable("CLI version command timed out") from exc
    if process.returncode != 0 or not isinstance(stdout, bytes) or not stdout.strip():
        raise SeatUnavailable("CLI version command failed")
    return stdout


def response_bytes(value: object) -> bytes | None:
    return value if isinstance(value, bytes) and value else None


def command_line(argv: list[str]) -> str:
    return subprocess.list2cmdline([Path(argv[0]).name, *argv[1:]])
