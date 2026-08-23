"""Call the installed Claude CLI as an isolated evaluator seat."""

import json

from . import record

TIMEOUT_SECONDS = 300
VERSION_TIMEOUT_SECONDS = 30
_model = None
_last_command = None


def _command(executable: str, model: str | None, output_format: str) -> list[str]:
    command = [
        executable,
        "--print",
        "--safe-mode",
        "--no-chrome",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--tools",
        "",
        "--permission-mode",
        "dontAsk",
        "--prompt-suggestions",
        "false",
    ]
    if model is not None:
        command.extend(("--model", model))
    command.extend(("--output-format", output_format))
    return command


def _invoke(prompt: bytes, *, model: str | None, output_format: str):
    executable = record.resolve_cli("claude")
    if executable is None:
        raise record.SeatUnavailable("Claude CLI was not found")
    with record.temporary_workspace("docket-claude-seat-") as (root, scratch):
        prompt_path = root / "prompt.bin"
        prompt_path.write_bytes(prompt)
        command = _command(executable, model, output_format)
        result = record.run_process(
            command,
            prompt_path=prompt_path,
            cwd=scratch,
            response_path=None,
            timeout=TIMEOUT_SECONDS,
        )
    return command, result


def _primary_model(raw: object) -> str:
    if not isinstance(raw, bytes) or not raw:
        raise record.SeatUnavailable("Claude model probe returned no bytes")
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise record.SeatUnavailable("Claude model probe did not return JSON") from exc
    usage = body.get("usage")
    models = body.get("modelUsage")
    if not isinstance(usage, dict) or not isinstance(models, dict):
        raise record.SeatUnavailable("Claude model probe omitted usage metadata")
    fields = {
        "input_tokens": "inputTokens",
        "output_tokens": "outputTokens",
        "cache_read_input_tokens": "cacheReadInputTokens",
        "cache_creation_input_tokens": "cacheCreationInputTokens",
    }
    matches = [
        model
        for model, model_usage in models.items()
        if isinstance(model, str)
        and model.strip()
        and isinstance(model_usage, dict)
        and all(
            model_usage.get(target) == usage.get(source)
            for source, target in fields.items()
        )
    ]
    if len(matches) != 1:
        raise record.SeatUnavailable(
            "Claude model probe did not identify one primary model"
        )
    return matches[0]


def _discover_model() -> str:
    _command_used, result = _invoke(
        b"Reply with exactly: MODEL_METADATA_OK\n",
        model=None,
        output_format="json",
    )
    return _primary_model(result.response)


def ask(prompt: bytes) -> bytes | None:
    global _last_command, _model
    try:
        executable = record.resolve_cli("claude")
        if executable is None:
            raise record.SeatUnavailable("Claude CLI was not found")
        if _model is None:
            _model = _discover_model()
        command, result = _invoke(prompt, model=_model, output_format="text")
        response = record.response_bytes(result.response)
        if response is None:
            return None
        _last_command = command
        return response
    except record.SeatUnavailable:
        return None


def model_build() -> str:
    global _last_command, _model
    executable = record.resolve_cli("claude")
    if executable is None:
        raise record.SeatUnavailable("Claude CLI version command cannot be found")
    version = (
        record.version_output(
            [executable, "--version"], timeout=VERSION_TIMEOUT_SECONDS
        )
        .decode("utf-8")
        .strip()
    )
    if _model is None:
        _model = _discover_model()
    _last_command = _command(executable, _model, "text")
    return (
        f"version={version}; model={_model}; "
        f"command={record.command_line(_last_command)}"
    )


ask.model_build = model_build
