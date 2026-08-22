"""Drive one evaluator seat through a single calibration attempt.

`calibration.py` is the ledger: it records the ask, records what came back, and refuses a
second capture. This module is the one that actually asks. It derives the prompt, opens the
attempt, invokes an injected seat callable once, and persists whatever came back — including
nothing, including an exception, including a timeout.

A vanished attempt un-enforces the capture gate: the next call would see no response record
and let the seat try again. So `record_response` runs in a `finally` on every path that
opened an attempt. There is no loop, no retry into a better answer, and no simulated seat.
If no callable is supplied, this refuses rather than inventing bytes that would afterwards
be indistinguishable from a real run.
"""

import argparse
import json
from importlib import import_module, resources
from pathlib import Path

from . import calibration
from .spec import load


class CalibrationRefused(RuntimeError):
    """The seat cannot be asked as registered, so it is not asked at all."""


def _resolve_spec(reference: str) -> Path:
    """Take a family id or a path, and return the specification the runtime actually has.

    Same order as capture.py, on purpose. A reference that is already a readable file
    is used as-is. Only when that path is not a file does the family id fall through to
    the spec shipped in the installed package.
    """
    candidate = Path(reference)
    try:
        looks_like_a_file = candidate.is_file()
    except OSError:
        looks_like_a_file = False
    if looks_like_a_file:
        return candidate
    packaged = (
        resources.files("docket.advantage") / "v3" / "specs" / f"{reference}.json"
    )
    if packaged.is_file():
        return Path(str(packaged))
    raise CalibrationRefused(
        f"{reference!r} is neither a readable specification file nor a family id shipped "
        "with the installed package"
    )


def _as_seat_bytes(raw):
    """A falsy or non-bytes return is no response, not an answer.

    `record_response` hashes whatever it is told was captured. A str (the usual
    `.text` instead of `.content`) makes that hash raise inside the caller's
    `finally`, so the request is written and the response is not. Normalising
    here means the persist path only ever sees bytes or None.
    """
    if isinstance(raw, bytes) and raw:
        return raw, None
    if isinstance(raw, bytes) or raw is None:
        return None, "no response bytes were received"
    mismatch = TypeError(f"seat returned {type(raw).__name__}, expected bytes")
    return None, f"{type(mismatch).__name__}: {mismatch}"


def _resolve_seat(reference: str):
    """Turn `module:callable` into the callable that will be asked."""
    module_name, separator, attr = reference.partition(":")
    if not separator or not module_name or not attr:
        raise CalibrationRefused(f"{reference!r} is not a module:callable reference")
    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise CalibrationRefused(f"seat {reference!r} could not be imported") from exc
    target = module
    try:
        for part in attr.split("."):
            if not part:
                raise AttributeError(attr)
            target = getattr(target, part)
    except AttributeError as exc:
        raise CalibrationRefused(
            f"seat {reference!r} does not name a callable on the imported module"
        ) from exc
    if not callable(target):
        raise CalibrationRefused(
            f"seat {reference!r} resolved to {type(target).__name__}, not a callable"
        )
    return target


def _model_build_for(seat, declared: str | None) -> str:
    if declared is not None:
        return declared
    build = getattr(seat, "model_build", None)
    if not callable(build):
        raise CalibrationRefused(
            "the resolved seat exposes no model_build() and --model-build was not supplied"
        )
    try:
        value = build()
    except Exception as exc:
        raise CalibrationRefused(
            f"seat model_build() refused: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(value, str) or not value.strip():
        raise CalibrationRefused("seat model_build() returned no nonblank string")
    return value


def _refuse_shared_session(
    spec, calibration_dir, evaluator_id: str, session_id: str
) -> None:
    """Two seats reporting one session id is one run counted twice.

    The lock already refuses that. Failing here means the second request is never minted,
    so the operator does not discover the collision after both seats have already answered.
    """
    parent = calibration.seat_dir(spec, calibration_dir, evaluator_id).parent
    if not parent.is_dir():
        return
    for seat_path in parent.iterdir():
        if not seat_path.is_dir():
            continue
        for req_path in seat_path.glob("attempt-*.request.json"):
            try:
                body = json.loads(req_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CalibrationRefused(
                    f"calibration: request record {req_path.name!r} is unreadable, so a "
                    "shared session cannot be ruled out"
                ) from exc
            if (
                body.get("session_id") == session_id
                and body.get("evaluator_id") != evaluator_id
            ):
                raise CalibrationRefused(
                    f"session {session_id!r} is already bound to seat "
                    f"{body.get('evaluator_id')!r}; every evaluator seat needs its own "
                    "distinct session. One session id reported twice is one run counted twice."
                )


def run_seat(
    spec,
    calibration_dir,
    *,
    evaluator_id: str,
    model_build: str,
    session_id: str,
    calibration_set: bytes,
    call_seat=None,
) -> dict:
    """Ask one seat once. Persist the first bytes, whatever they say.

    `call_seat` is resolved at call time. A signature default that bound a client at
    import would pin a live call inside every unit test that forgot to inject one, and
    a default that synthesised an answer would be a fabricated calibration.
    """
    seat = call_seat
    if seat is None:
        raise CalibrationRefused(
            "no seat callable was supplied. A missing client is a refusal, not a cue "
            "to simulate an answer — a fabricated calibration is indistinguishable from "
            "a real one afterwards."
        )

    _refuse_shared_session(spec, calibration_dir, evaluator_id, session_id)

    prompt = calibration.derive_prompt(spec, calibration_set, evaluator_id)
    request = calibration.open_attempt(
        spec,
        calibration_dir,
        evaluator_id=evaluator_id,
        model_build=model_build,
        session_id=session_id,
        calibration_set=calibration_set,
    )

    raw = None
    error = None
    try:
        raw = seat(prompt)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raw = None
        raise
    finally:
        persist_raw, persist_error = _as_seat_bytes(raw)
        if error is not None:
            persist_raw, persist_error = None, error
        recorded = calibration.record_response(
            spec,
            calibration_dir,
            evaluator_id=evaluator_id,
            attempt_ordinal=request["attempt_ordinal"],
            raw_response=persist_raw,
            error=persist_error,
        )
    return recorded


def main(argv: list[str] | None = None) -> int:
    """The production entry point, so a seat is something an operator can actually run.

    Without this the module is reachable only from its own tests — which is the shape of
    code that passes every check and then does not exist on the morning it was written for.
    The seat callable is still injected at the call, never defaulted: this CLI
    resolves a `module:callable` reference when one is given, and refuses when
    it is absent rather than inventing an answer.
    """
    parser = argparse.ArgumentParser(
        description="Drive one evaluator seat through a single calibration attempt."
    )
    parser.add_argument(
        "spec", help="a registered family id, or a path to a specification JSON"
    )
    parser.add_argument(
        "out", help="directory to write the seat's request and response records into"
    )
    parser.add_argument("--evaluator-id", required=True, help="roster seat to ask")
    parser.add_argument(
        "--model-build",
        help="the build that will actually answer; defaults to the seat's model_build()",
    )
    parser.add_argument(
        "--session-id", required=True, help="distinct session for this seat"
    )
    parser.add_argument(
        "--calibration-set",
        required=True,
        help="path to the shared eight-case calibration key",
    )
    parser.add_argument(
        "--seat",
        default=None,
        help="module:callable to ask, for example pack.client:ask. "
        "Absent is a refusal, not a simulated seat.",
    )
    args = parser.parse_args(argv)

    try:
        spec = load(_resolve_spec(args.spec))
    except CalibrationRefused as refusal:
        print(f"calibration refused: {refusal}")
        return 2
    except ValueError as exc:
        print(f"calibration refused: {exc}")
        return 2

    try:
        seat = _resolve_seat(args.seat) if args.seat else None
        if seat is not None:
            calibration_dir = Path(args.out)
            _refuse_shared_session(
                spec, calibration_dir, args.evaluator_id, args.session_id
            )
            for attempt in calibration.attempts(
                spec, calibration_dir, args.evaluator_id
            ):
                if attempt["response"]["outcome"] == calibration.CAPTURED:
                    raise CalibrationRefused(
                        f"calibration: seat {args.evaluator_id!r} already captured a "
                        f"response on attempt {attempt['ordinal']}. No provenance probe "
                        "or further request is permitted under this registration."
                    )
        model_build = (
            _model_build_for(seat, args.model_build)
            if seat is not None
            else args.model_build or ""
        )
        result = run_seat(
            spec,
            Path(args.out),
            evaluator_id=args.evaluator_id,
            model_build=model_build,
            session_id=args.session_id,
            calibration_set=Path(args.calibration_set).read_bytes(),
            call_seat=seat,
        )
    except CalibrationRefused as refusal:
        print(f"calibration refused: {refusal}")
        return 2
    except ValueError as exc:
        print(f"calibration refused: {exc}")
        return 2

    print(
        f"seat {result['evaluator_id']} attempt {result['attempt_ordinal']}: "
        f"{result['outcome']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
