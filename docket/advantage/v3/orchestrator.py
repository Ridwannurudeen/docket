"""Drive a locked family's registered slots: claim, run, persist.

runner.py is the ledger machine — slot identities, the claim-once rule, the fold, and
recovery. This module is the driver that walks that machine. It does not choose the arm
order, does not retry a terminal primary, and does not take elapsed time from the arm.

The production shape is the same as capture.py: a timer or an operator runs `main`.
A path that already names a readable file wins; otherwise a family id is resolved
from the installed package.
"""

import argparse
import json
import sys
import time
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path

import httpx

from . import runner
from .runner import (
    _agent_payload,
    _locked_inputs,
    _manual_reveal,
    _record_manual_reveal_sources,
    _terminate_slot,
    claim_slot,
    ledger_path,
    open_run,
    read_state,
    recover_interrupted,
    scheduled_slots,
    terminate_slot,
)
from .spec import REPO_ROOT, assert_runnable, load


class OrchestratorRefused(RuntimeError):
    """The run cannot proceed as registered, so no arm is started."""


def _resolve_spec(reference: str) -> Path:
    """Take a family id or a path, and return the specification the runtime actually has.

    Same order as capture.py, on purpose. A reference that is already a readable file
    — absolute or cwd-relative — is used as-is. Only when that path is not a file does
    the family id fall through to the spec shipped in the installed package. A stray
    local file named like a family id therefore shadows the packaged registration.
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
    raise OrchestratorRefused(
        f"{reference!r} is neither a readable specification file nor a family id shipped "
        "with the installed package"
    )


def _root(repo_root) -> Path:
    return (
        Path(repo_root)
        if repo_root is not None
        else Path(__file__).resolve().parents[3]
    )


def _http_hire(url, *, json, headers, timeout, client=None):
    owned = client is None
    session = httpx.Client() if client is None else client
    try:
        return session.post(url, json=json, headers=headers, timeout=timeout)
    finally:
        if owned:
            session.close()


def hire_agent(spec, payload, *, hire=None, client=None, headers=None) -> dict:
    """POST the registered endpoint. The network call is a parameter, not a default."""
    post = _http_hire if hire is None else hire
    try:
        response = post(
            spec.execution_protocol["agent_endpoint"],
            json=payload,
            headers=headers or {},
            timeout=spec.timing["timeout_seconds"],
            client=client,
        )
    except httpx.TimeoutException as exc:
        return {
            "failure": {"kind": runner.TIMED_OUT, "message": str(exc)},
            "forced_outcome": runner.TIMED_OUT,
        }
    except httpx.RequestError as exc:
        return {
            "failure": {
                "kind": "transport_error",
                "message": f"{type(exc).__name__}: {exc}",
            }
        }
    if response.status_code in (400, 402, 422):
        return {
            "failure": {
                "kind": runner.BLOCKED_CONTRACT,
                "message": (
                    f"the registered request was refused with HTTP {response.status_code}"
                ),
            },
            "forced_outcome": runner.BLOCKED_CONTRACT,
        }
    if response.status_code != 200:
        return {
            "failure": {
                "kind": "http_error",
                "message": f"agent endpoint returned HTTP {response.status_code}",
            }
        }
    try:
        body = response.json()
    except ValueError as exc:
        return {"failure": {"kind": "malformed_json", "message": str(exc)}}
    result = body.get("result") if isinstance(body, dict) else None
    receipt = body.get("receipt") if isinstance(body, dict) else None
    payment = receipt.get("payment") if isinstance(receipt, dict) else None
    receipt_valid = bool(
        isinstance(receipt, dict)
        and receipt.get("service") == spec.execution_protocol["agent_service_id"]
        and receipt.get("input_hash") == runner.canonical_hash(payload)
        and result not in (None, "", [], {})
        and receipt.get("output_hash") == runner.canonical_hash(result)
        and isinstance(payment, dict)
        and payment.get("status") in {"free_tier", "settled"}
    )
    if not receipt_valid:
        return {
            "failure": {
                "kind": "invalid_receipt_or_empty",
                "message": (
                    "agent response lacked a nonempty hash-bound result or a valid "
                    "free-tier/settled receipt"
                ),
            },
            "receipt": receipt,
        }
    cost = None
    amount = payment.get("amount")
    asset = payment.get("asset")
    if isinstance(asset, str) and asset.strip():
        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            decimal_amount = None
        if (
            decimal_amount is not None
            and decimal_amount.is_finite()
            and decimal_amount >= 0
        ):
            cost = {"amount": str(amount), "unit": asset}
    return {
        "raw_output": result,
        "receipt": receipt,
        "cost": cost,
    }


def next_open_slot(spec, runs_dir, *, repo_root=None):
    """The first scheduled primary that is not yet terminal, or None."""
    state = read_state(ledger_path(spec, runs_dir))
    for scheduled in scheduled_slots(spec, repo_root=repo_root):
        current = state.get(scheduled.slot, runner.SlotState())
        if current.is_dangling:
            raise OrchestratorRefused(
                f"scheduled slot {scheduled.slot} is still active"
            )
        if current.is_terminated:
            continue
        return scheduled
    return None


def _prepare(spec, runs_dir, repo_root) -> list[dict]:
    try:
        recovered = recover_interrupted(spec, runs_dir)
        open_run(spec, runs_dir, repo_root=repo_root)
    except ValueError as exc:
        raise OrchestratorRefused(str(exc)) from exc
    return recovered


def _baseline_readiness(spec, slot) -> dict | None:
    """Return the unscored readiness contract for its registered baseline arm."""
    readiness = spec.execution_protocol.get("baseline_readiness")
    identity = spec.execution_protocol.get("baseline_identity")
    if (
        isinstance(readiness, dict)
        and readiness.get("required_before_primary") is True
        and isinstance(identity, dict)
        and slot.arm == identity.get("arm")
    ):
        return readiness
    return None


def _verify_baseline_readiness(spec, slot, input_stream) -> bool:
    readiness = _baseline_readiness(spec, slot)
    if readiness is None:
        return False
    print(
        json.dumps(
            {"baseline_readiness": readiness["fixture"]},
            sort_keys=True,
            ensure_ascii=False,
        ),
        flush=True,
    )
    line = input_stream.readline()
    try:
        submitted = json.loads(line)
    except (json.JSONDecodeError, TypeError) as exc:
        raise OrchestratorRefused(
            "the unscored baseline readiness answer is not valid JSON; no official "
            "run event was written, so the readiness check may be retried"
        ) from exc
    if runner.canonical_hash(submitted) != runner.canonical_hash(
        readiness["expected_output"]
    ):
        raise OrchestratorRefused(
            "the unscored baseline readiness answer does not exactly match the "
            "registered expected JSON; no official run event was written, so the "
            "readiness check may be retried"
        )
    return True


def _reveal(spec, slot, repo_root):
    """Load the locked case this slot is bound to.

    A failure here is a problem with the registration or the bytes on disk, not
    with the arm. The caller must refuse before claiming: recording FAILED would
    spend one of the five preregistered pairs on a fault the operator can still
    fix, and recording INTERRUPTED would spend that pair just as permanently.
    """
    inputs = _locked_inputs(spec, repo_root)
    case = next(row for row in inputs["cases"] if row["case_id"] == slot.case_id)
    if slot.arm == "manual":
        return _manual_reveal(spec, inputs, case, _root(repo_root))
    return _agent_payload(spec, inputs, case, _root(repo_root))


def _persist(spec, runs_dir, slot, result, repo_root, clock) -> dict:
    if result is None:
        body = {"failure": {"kind": "empty", "message": "invoke returned nothing"}}
    elif isinstance(result, dict) and (
        "failure" in result or "raw_output" in result or "receipt" in result
    ):
        body = result
    else:
        body = {"raw_output": result}
    kwargs = {
        "slot": slot,
        "repo_root": repo_root,
        "raw_output": body.get("raw_output"),
        "failure": body.get("failure"),
        "cost": body.get("cost"),
        "receipt": body.get("receipt"),
        "clock": clock,
    }
    forced = body.get("forced_outcome")
    if forced is not None:
        return _terminate_slot(spec, runs_dir, forced_outcome=forced, **kwargs)
    return terminate_slot(spec, runs_dir, **kwargs)


def run_next(
    spec,
    runs_dir,
    *,
    invoke=None,
    clock=None,
    hire=None,
    repo_root=None,
    slot=None,
    prepare=True,
    payment_headers=None,
    client=None,
    readiness_verified=False,
) -> dict:
    """Claim the next open slot, run it once, persist the first terminal outcome.

    `invoke`, `clock` and `hire` are resolved at call time. A signature default would
    bind at import and silently pin the real call.

    The locked case is revealed before the claim. A reveal fault is refused rather
    than recorded as FAILED or INTERRUPTED — see `_reveal`.
    """
    tick = time.monotonic_ns if clock is None else clock
    post = _http_hire if hire is None else hire
    try:
        assert_runnable(spec, repo_root=_root(repo_root))
    except ValueError as exc:
        raise OrchestratorRefused(str(exc)) from exc
    prepared = False
    if prepare and not isinstance(
        spec.execution_protocol.get("baseline_readiness"), dict
    ):
        _prepare(spec, runs_dir, repo_root)
        prepared = True
    try:
        nxt = next_open_slot(spec, runs_dir, repo_root=repo_root)
    except ValueError as exc:
        raise OrchestratorRefused(str(exc)) from exc
    if nxt is None:
        raise OrchestratorRefused("every registered primary is recorded")
    if _baseline_readiness(spec, nxt) is not None and readiness_verified is not True:
        raise OrchestratorRefused(
            "the registered Codex-assisted baseline readiness check must pass before "
            "the primary is claimed"
        )
    if prepare and not prepared:
        _prepare(spec, runs_dir, repo_root)
    if slot is not None and slot.slot != nxt.slot:
        raise OrchestratorRefused(
            f"the registered {nxt.arm} block must run next; refusing {slot.slot}"
        )
    if invoke is None and nxt.arm == "manual":
        raise OrchestratorRefused(
            "the manual arm has no invoke; refusing before the slot is claimed"
        )
    try:
        revealed = _reveal(spec, nxt, repo_root)
    except Exception as exc:
        raise OrchestratorRefused(
            f"the locked case cannot be revealed for {nxt.slot}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    def default_invoke(chosen, revealed_case):
        return hire_agent(
            spec,
            revealed_case,
            hire=post,
            client=client,
            headers=payment_headers,
        )

    run_arm = default_invoke if invoke is None else invoke
    try:
        claim_slot(spec, runs_dir, slot=nxt, repo_root=repo_root, clock=tick)
    except ValueError as exc:
        raise OrchestratorRefused(str(exc)) from exc
    if nxt.arm == "manual":
        _record_manual_reveal_sources(
            spec,
            runs_dir,
            nxt,
            revealed,
            _root(repo_root),
        )
    try:
        result = run_arm(nxt, revealed)
    except Exception as exc:
        result = {
            "failure": {
                "kind": "invoke_error",
                "message": f"{type(exc).__name__}: {exc}",
            }
        }
    return _persist(spec, runs_dir, nxt, result, repo_root, tick)


def run_remaining(
    spec,
    runs_dir,
    *,
    invoke=None,
    clock=None,
    hire=None,
    repo_root=None,
    limit=None,
    payment_headers=None,
    client=None,
    readiness_verified=False,
) -> list[dict]:
    """Walk every remaining primary in registered order. A failed slot is not retried."""
    tick = time.monotonic_ns if clock is None else clock
    post = _http_hire if hire is None else hire
    try:
        assert_runnable(spec, repo_root=_root(repo_root))
    except ValueError as exc:
        raise OrchestratorRefused(str(exc)) from exc
    if isinstance(spec.execution_protocol.get("baseline_readiness"), dict):
        try:
            nxt = next_open_slot(spec, runs_dir, repo_root=repo_root)
        except ValueError as exc:
            raise OrchestratorRefused(str(exc)) from exc
        if (
            nxt is not None
            and _baseline_readiness(spec, nxt) is not None
            and readiness_verified is not True
        ):
            raise OrchestratorRefused(
                "the registered Codex-assisted baseline readiness check must pass before "
                "the run is opened"
            )
    recovered = _prepare(spec, runs_dir, repo_root)
    results = list(recovered)
    ran = 0
    while True:
        nxt = next_open_slot(spec, runs_dir, repo_root=repo_root)
        if nxt is None:
            return results
        if limit is not None and ran >= limit:
            return results
        results.append(
            run_next(
                spec,
                runs_dir,
                invoke=invoke,
                clock=tick,
                hire=post,
                repo_root=repo_root,
                prepare=False,
                payment_headers=payment_headers,
                client=client,
                readiness_verified=readiness_verified,
            )
        )
        ran += 1


def main(argv: list[str] | None = None, *, client=None, stdin=None) -> int:
    """The production entry point, so a timer or an operator can actually run the family."""
    parser = argparse.ArgumentParser(
        description="Run a v3 family's registered primary slots, in registered order."
    )
    parser.add_argument(
        "spec", help="a registered family id, or a path to a specification JSON"
    )
    parser.add_argument(
        "runs_dir", help="directory that holds the family's JSONL ledger"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="reveal each manual case after its timed claim and read one JSON line",
    )
    parser.add_argument(
        "--repo-root",
        help="repository root the spec's inputs_ref is relative to",
    )
    parser.add_argument(
        "--once", action="store_true", help="run only the next open slot"
    )
    parser.add_argument(
        "--payment-header",
        help="value of the X-PAYMENT header sent with agent hires",
    )
    parser.add_argument(
        "--canary-header",
        help="value of the X-Docket-Canary header sent with agent hires",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else REPO_ROOT
    try:
        spec = load(_resolve_spec(args.spec), repo_root=repo_root)
    except OrchestratorRefused as refusal:
        print(f"orchestrator refused: {refusal}")
        return 2
    except ValueError as exc:
        print(f"orchestrator refused: {exc}")
        return 2
    try:
        assert_runnable(spec, repo_root=repo_root)
    except ValueError as exc:
        print(f"orchestrator refused before any slot: {exc}")
        return 2

    runs_dir = Path(args.runs_dir)
    # A service whose paid stock is closed still admits a settled hire on the
    # owner-operated canary authorization, so a family that registers a paid agent
    # arm needs both headers or its payment is ignored and the hire runs free.
    headers = {
        name: value
        for name, value in (
            ("X-PAYMENT", args.payment_header),
            ("X-Docket-Canary", args.canary_header),
        )
        if value
    } or None
    input_stream = sys.stdin if stdin is None else stdin

    try:
        readiness_verified = False
        if isinstance(spec.execution_protocol.get("baseline_readiness"), dict):
            nxt = next_open_slot(spec, runs_dir, repo_root=repo_root)
            if nxt is not None and _baseline_readiness(spec, nxt) is not None:
                if not args.interactive:
                    raise OrchestratorRefused(
                        "the Codex-assisted baseline readiness check requires "
                        "--interactive; refusing before the run is opened"
                    )
                readiness_verified = _verify_baseline_readiness(spec, nxt, input_stream)
        recovered = _prepare(spec, runs_dir, repo_root)
        for event in recovered:
            print(f"{event['slot']} {event['outcome']}")
        while True:
            nxt = next_open_slot(spec, runs_dir, repo_root=repo_root)
            if nxt is None:
                return 0
            if nxt.arm == "manual" and not args.interactive:
                raise OrchestratorRefused(
                    f"manual slot {nxt.case_id} requires --interactive; refusing "
                    "before the slot is claimed"
                )
            if nxt.arm == "manual":

                def invoke(chosen, revealed):
                    print(
                        json.dumps(
                            {"slot": chosen.slot, "case": revealed},
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    return {"raw_output": json.loads(input_stream.readline())}

            else:
                invoke = None
            terminal = run_next(
                spec,
                runs_dir,
                repo_root=repo_root,
                invoke=invoke,
                payment_headers=headers,
                client=client,
                prepare=False,
                readiness_verified=readiness_verified,
            )
            print(f"{terminal['slot']} {terminal['outcome']}")
            if terminal["outcome"] == runner.BLOCKED_CONTRACT:
                return 2
            if args.once:
                return 0
    except OrchestratorRefused as refusal:
        print(f"orchestrator refused: {refusal}")
        return 2
    except ValueError as exc:
        print(f"orchestrator refused: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
