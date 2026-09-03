"""Exercise a running Docket the way a caller does, and write down what happened.

The canary answers a different question: it checks that the *paid* path settles, against the
public URL, with real money, and it is deliberately off between exercises. This probe answers
the cheap one — is the deployment serving — from inside the host, against the loopback port
the application actually listens on, so a broken nginx, a broken TLS certificate and a broken
application are three separate findings rather than one silence.

Five steps, chosen because each fails for a different reason:

  * `/` is the shell every page is built from, and the one thing a reader sees first.
  * `/services` is the catalogue, and the release contract pins its exact inventory.
  * `/api/status` is this deployment's own account of itself, including the readings that
    are not otherwise exercised until someone looks.
  * `/advantage/v3.json` is reconstructed from durable artifacts at process startup, so a
    process that came up without them serves a 503 here and nowhere else.
  * `POST /hire/range-doctor` is the only step that spends anything: it runs the free tier
    against BSC with the catalogue's own worked example, so a broken RPC path, a broken
    position read and a broken receipt are all caught by the one request a buyer makes.

The example body is read out of the catalogue rather than written down here. A worked example
typed into a probe is a second copy of the terms, and the copy is the one that goes stale.
"""

import argparse
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx

from .hire.catalogue import get_service
from .store import Store

DEFAULT_BASE_URL = "http://127.0.0.1:8090"
PROBE_SERVICE_ID = "range-doctor"
# The hire step reads a wallet's positions from BSC through a failover list, and `/api/status`
# makes its own bounded chain read, so the ceiling here is the slowest honest answer rather
# than a latency target. A step that exceeds it is recorded as a failure with its elapsed time.
STEP_TIMEOUT_S = 90.0
SERVED_STATUSES = ("ok", "degraded")


def worked_example(service_id: str = PROBE_SERVICE_ID) -> dict:
    """The catalogue's own example request: every input field that publishes a default."""
    service = get_service(service_id)
    if service is None:
        raise ValueError(f"no service {service_id!r} in the catalogue")
    return {
        name: field["default"] for name, field in service.input_schema.items() if "default" in field
    }


def _step(name: str, ok: bool, status_code: int | None, started: float, detail: str) -> dict:
    return {
        "name": name,
        "ok": ok,
        "status_code": status_code,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "detail": detail,
    }


def _run_step(name: str, call, check) -> dict:
    """One request and one reading of its answer, with the failure modes kept apart.

    A transport error, a status the route does not serve and a body that does not carry what
    the route promises are three different faults, and a probe that recorded them all as
    "failed" would send an operator to the wrong place.
    """
    started = time.monotonic()
    try:
        response = call()
    except httpx.HTTPError as exc:
        return _step(name, False, None, started, f"{type(exc).__name__}: {exc}")
    if response.status_code != 200:
        return _step(name, False, response.status_code, started, "the route did not answer 200")
    try:
        detail = check(response)
    except (ValueError, KeyError, TypeError) as exc:
        return _step(
            name,
            False,
            response.status_code,
            started,
            f"the answer could not be read: {type(exc).__name__}: {exc}",
        )
    return _step(name, detail is None, response.status_code, started, detail or "as served")


def _check_home(response: httpx.Response) -> str | None:
    return None if "<title>Docket" in response.text else "the shell carries no Docket title"


def _check_services(response: httpx.Response) -> str | None:
    body = response.json()
    services = body["services"]
    if not isinstance(services, list) or not services:
        return "no services are listed"
    if body["total"] != len(services):
        return f"total {body['total']} does not match the {len(services)} rows served"
    return None


def _check_status(response: httpx.Response) -> str | None:
    served = response.json()["status"]
    if served not in SERVED_STATUSES:
        return f"the deployment reports {served!r}"
    return None


def _check_advantage(response: httpx.Response) -> str | None:
    body = response.json()
    families = body["families"]
    declared = body["summary"]["n_families"]
    if not isinstance(families, list):
        return "families is not a list"
    if declared != len(families):
        return f"summary claims {declared} families and {len(families)} were served"
    return None


def _check_hire(response: httpx.Response) -> str | None:
    body = response.json()
    if not isinstance(body.get("result"), dict):
        return "the free-tier hire returned no result object"
    if not isinstance(body.get("receipt"), dict):
        return "the free-tier hire returned no receipt"
    return None


def run(base_url: str, *, client: httpx.Client | None = None) -> list[dict]:
    """Every step, in order, whatever any one of them does. A probe that stopped at the first
    failure would report one fault per run and hide the rest of the deployment's state."""
    owned = client is None
    session = client or httpx.Client(
        timeout=STEP_TIMEOUT_S,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "Docket production probe/1"},
    )
    try:
        return [
            _run_step("home", lambda: session.get(f"{base_url}/"), _check_home),
            _run_step("services", lambda: session.get(f"{base_url}/services"), _check_services),
            _run_step("api_status", lambda: session.get(f"{base_url}/api/status"), _check_status),
            _run_step(
                "advantage_v3",
                lambda: session.get(f"{base_url}/advantage/v3.json"),
                _check_advantage,
            ),
            _run_step(
                "free_tier_hire",
                lambda: session.post(f"{base_url}/hire/{PROBE_SERVICE_ID}", json=worked_example()),
                _check_hire,
            ),
        ]
    finally:
        if owned:
            session.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=(
            "the Docket to exercise. The default is the loopback port the application unit "
            "listens on, so a probe run measures the application and not the proxy in front "
            f"of it (default: {DEFAULT_BASE_URL})"
        ),
    )
    args = parser.parse_args(argv)

    database = os.environ.get("DOCKET_DB", "").strip()
    if not database:
        print("Docket probe: failed (DOCKET_DB is required)")
        return 1

    started_at = datetime.now(UTC).isoformat()
    steps = run(args.base_url.rstrip("/"))
    finished_at = datetime.now(UTC).isoformat()
    ok = all(step["ok"] for step in steps)
    # Printed before the write, deliberately. The run happened whether or not it could be
    # recorded, and a probe that failed to reach its database used to take its own findings
    # with it — leaving the journal saying only that something went wrong, at the moment the
    # readings were most worth having.
    for step in steps:
        print(
            f"Docket probe: {step['name']} "
            f"{'ok' if step['ok'] else 'FAILED'} "
            f"({step['status_code']}, {step['latency_ms']}ms) — {step['detail']}"
        )
    try:
        Store(database).record_probe_run(
            started_at=started_at, finished_at=finished_at, ok=ok, steps=steps
        )
    except Exception as exc:
        print(f"Docket probe: not recorded ({type(exc).__name__}: {exc})")
        return 1
    print(f"Docket probe: {'passed' if ok else 'failed'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
