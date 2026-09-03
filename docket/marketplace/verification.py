"""What Docket has actually observed about a third-party listing, and nothing beyond it.

Six levels, weakest to strongest, each naming the evidence that earns it:

  registered         `ownerOf` answered on BSC. The chain says this token exists and who
                     holds it. Evidence: the owner address, the tokenURI, the RPC that
                     answered.
  endpoint_detected  the registration names an a2a or mcp endpoint. A `web` link is a
                     homepage and does not count: "the marketing site answered" is not
                     "the service answered". Evidence: the endpoints, by kind.
  live               that endpoint answered a guarded GET at any status. Evidence: the
                     probe observation — status, elapsed, and the same SSRF-guarded
                     request the snapshot sweep makes, because it is literally the same
                     function.
  payment_tested     the endpoint answered 402 with a body that parses as an x402
                     challenge. READ ONLY: Docket reads the challenge and never presents
                     a payment, so this level says a price exists and says nothing about
                     whether paying it works.
  docket_tested      a sample invocation came back as a schema-valid structured result.
                     Evidence: the request that was sent, the SHA-256 of the result, and
                     which schema it was checked against.
  docket_verified    docket_tested AND a paired benchmark family exists for this listing.
                     `benchmark_ref` is the hook and it returns None for every external
                     listing today, because Docket's v3 families are registered against
                     Docket's own service ids. Nothing reaches this level, and the code
                     says so rather than the level quietly never being computed.

Two rules keep the ladder honest.

**A level is never inflated and never demoted by an outage.** `ownerOf` failing because
every RPC endpoint refused is `rpc_unavailable`, not `not_registered`; the run records
the outage and the listing keeps the level it already held. That distinction is the one
`escrow.chain.Rpc` exists to preserve, and it is the difference between "Docket could not
look" and "the chain says no".

**`docket_tested` requires `live`, not `payment_tested`.** The plan orders the levels by
strength of evidence, and read literally that would mean an endpoint answering a real
request for free can never be tested — which would rank a service that only quotes a
price above one that actually did the work. So the prerequisite table below is explicit:
`payment_tested` and `docket_tested` both hang off `live`, and a listing reported at
`docket_tested` still carries its own `payment_tested: false` evidence row, so nobody can
read the level as a claim that a payment path was exercised.
"""

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import httpx

from ..hire.receipts import canonical_hash
from ..liveness import request_one
from ..scan8004 import lookup_owner_onchain
from .external import LEVELS, LEVEL_ORDER, ExternalListing, at_least

# Which level must already hold before a level can be reached. Written out rather than
# taken from LEVELS' order, because the two differ on purpose at `docket_tested`.
LEVEL_PREREQUISITE: dict[str, str | None] = {
    "registered": None,
    "endpoint_detected": "registered",
    "live": "endpoint_detected",
    "payment_tested": "live",
    "docket_tested": "live",
    "docket_verified": "docket_tested",
}

# JSON-RPC 2.0, the MCP capability listing. Read-only by construction: it asks the server
# what it can do and calls none of it. Named tools are never invoked — HeyAnon's Venus
# server lists `borrow` and `repay`, and a verification pass must not touch either.
MCP_TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
MCP_ACCEPT = "application/json, text/event-stream"

SAMPLE_SOURCES = ("declared_sample", "docket_default_mcp")

# What a body has to carry to be an x402 challenge rather than any other 402. Matched as
# "at least one of", because v1 and v2 name the requirements differently and a challenge
# Docket cannot read is not evidence that a challenge was served.
X402_MARKERS = ("x402Version", "accepts", "paymentRequirements")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def send(endpoint: dict, *, now: str) -> dict:
    """One guarded request, on a client of its own.

    A fresh direct client per target for the reason `liveness.probe_snapshot` gives: a
    connection pinned for one hostname must never be pooled for another hostname that
    happens to resolve to the same address.
    """
    with httpx.Client(trust_env=False) as client:
        return request_one(client, endpoint, now=now)


def benchmark_ref(listing: ExternalListing) -> str | None:
    """The paired-benchmark family registered for this listing, or None.

    Docket's v3 families are registered against Docket's own service ids
    (`hire.catalogue.SERVICE_BENCHMARK_FAMILIES`), and no external agent has one. This
    returns None for every external listing today; it is the seam a future registration
    plugs into, and until one exists `docket_verified` is unreachable and is recorded as
    unreached rather than skipped.
    """
    return None


def _parse_json(observation: dict):
    body = observation.get("body")
    if not isinstance(body, str) or not body.strip():
        return None
    text = body.strip()
    # Streamable-HTTP MCP servers may answer a JSON-RPC POST as one SSE event. The payload
    # is still JSON; it just arrives behind `data: `. Read it rather than calling a server
    # that answered correctly a failure.
    if text.startswith("event:") or text.startswith("data:"):
        for line in text.splitlines():
            if line.startswith("data:"):
                text = line[5:].strip()
                break
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def _x402_challenge(observation: dict) -> dict | None:
    """The x402 challenge in a 402 response, or None when there is not one to read."""
    if observation.get("status_code") != 402:
        return None
    payload = _parse_json(observation)
    if not isinstance(payload, dict):
        return None
    if not any(marker in payload for marker in X402_MARKERS):
        return None
    return payload


def _matches_output_schema(result, schema: dict | None) -> tuple[bool, str]:
    """Whether a result satisfies the listing's declared output schema.

    Only the parts of JSON Schema a listing can be held to without a validator library:
    the declared type, and the presence of every declared required property. A schema
    naming anything else is not silently treated as satisfied — the check reports which
    keys it enforced, so a reader knows exactly how much was checked.
    """
    if not isinstance(schema, dict):
        if isinstance(result, dict) and result:
            return True, "no declared output schema; checked a non-empty JSON object"
        return False, "no declared output schema and the result is not a JSON object"
    declared_type = schema.get("type")
    if declared_type == "object" and not isinstance(result, dict):
        return False, "the declared output schema is an object and the result is not"
    if declared_type == "array" and not isinstance(result, list):
        return False, "the declared output schema is an array and the result is not"
    required = schema.get("required")
    if isinstance(required, (list, tuple)) and isinstance(result, dict):
        missing = [key for key in required if key not in result]
        if missing:
            return False, f"the result is missing required keys: {', '.join(missing)}"
        return True, f"required keys present: {', '.join(str(k) for k in required)}"
    return True, f"declared type {declared_type!r} satisfied"


def _mcp_result(payload) -> tuple[object | None, str]:
    if not isinstance(payload, dict):
        return None, "the response body is not a JSON object"
    if "error" in payload:
        return None, f"the server returned a JSON-RPC error: {payload['error']}"
    result = payload.get("result")
    if not isinstance(result, dict):
        return None, "the JSON-RPC response carries no result object"
    if not isinstance(result.get("tools"), list):
        return None, "the tools/list result carries no tools array"
    return result, f"tools/list returned {len(result['tools'])} tools"


@dataclass(frozen=True)
class LevelRun:
    """One level, attempted. `ok` is what was observed; `detail` is why."""

    level: str
    ok: bool
    at: str
    detail: dict

    def to_json(self) -> dict:
        return {
            "level": self.level,
            "ok": self.ok,
            "at": self.at,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class VerificationResult:
    agent_id: str
    level: str | None
    previous_level: str | None
    runs: tuple[LevelRun, ...]
    verified_at: str
    outage: bool

    @property
    def evidence(self) -> list[dict]:
        return [run.to_json() for run in self.runs]

    def verification_block(self) -> dict:
        return {
            "level": self.level,
            "evidence": self.evidence,
            "verified_at": self.verified_at,
        }


def _sample_request(listing: ExternalListing, endpoint: dict) -> dict | None:
    """The one request Docket sends as a sample, or None where it will not invent one.

    A provider-submitted listing names its own `sample_input`, which is POSTed to the
    declared endpoint. Otherwise Docket has exactly one default, and it is for MCP:
    `tools/list`, which is the server describing itself in a structured JSON-RPC result.

    There is deliberately no default for an A2A endpoint. The only read that costs
    nothing is fetching the agent card, and a card is a description of the agent rather
    than a result the agent produced — handing out `docket_tested` for serving a card
    would be exactly the inflation this ladder exists to prevent. An A2A listing reaches
    `docket_tested` when its provider declares a sample input, and stops at `live`
    otherwise.
    """
    if listing.sample_input is not None:
        return {
            "url": endpoint["url"],
            "method": "POST",
            "json_body": listing.sample_input,
            "read_body": True,
            "sample_source": "declared_sample",
        }
    if endpoint["kind"] == "mcp":
        return {
            "url": endpoint["url"],
            "method": "POST",
            "json_body": MCP_TOOLS_LIST,
            "accept": MCP_ACCEPT,
            "read_body": True,
            "sample_source": "docket_default_mcp",
        }
    return None


def verify_listing(
    listing: ExternalListing,
    *,
    store=None,
    http=send,
    rpc=lookup_owner_onchain,
    now=_now,
) -> VerificationResult:
    """Run every level in order, record what each one observed, and report the highest
    level whose prerequisite chain holds.

    `http` is `send`, which is `liveness.request_one` — the same SSRF-guarded,
    address-pinned, redirect-refusing sender the snapshot sweep uses. `rpc` is
    `scan8004.lookup_owner_onchain`. Both are arguments so a test can supply a fake, and
    both default to the real thing so a caller cannot accidentally verify against nothing.

    Every attempted level writes one row to `verification_runs` when a store is supplied,
    passed or failed. A level that was not attempted because its prerequisite failed is
    still recorded, with the prerequisite named, so the evidence trail says why the ladder
    stopped instead of going quiet.
    """
    at = now()
    previous_level = listing.level
    runs: list[LevelRun] = []
    reached: dict[str, bool] = {}
    outage = False

    def record(level: str, ok: bool, detail: dict) -> None:
        runs.append(LevelRun(level=level, ok=ok, at=at, detail=detail))
        reached[level] = ok

    def prerequisite_holds(level: str) -> tuple[bool, str | None]:
        required = LEVEL_PREREQUISITE[level]
        if required is None:
            return True, None
        return reached.get(required, False), required

    def skip(level: str, required: str) -> None:
        record(
            level,
            False,
            {
                "reason": "prerequisite_not_reached",
                "requires": required,
                "message": f"{level} was not attempted because {required} was not reached",
            },
        )

    # 1. registered ---------------------------------------------------------------
    ownership = rpc(listing.agent_id)
    outcome = ownership.get("outcome")
    outage = outcome == "rpc_unavailable"
    record(
        "registered",
        outcome == "owned",
        {
            "check": "IdentityRegistry.ownerOf",
            "outcome": outcome,
            "owner": ownership.get("owner"),
            "token_uri": ownership.get("token_uri"),
            "rpc_url": ownership.get("rpc_url"),
            "message": ownership.get("detail"),
        },
    )

    # 2. endpoint_detected --------------------------------------------------------
    ok, required = prerequisite_holds("endpoint_detected")
    if not ok:
        skip("endpoint_detected", required)
    else:
        invocable = listing.invocable_endpoints
        record(
            "endpoint_detected",
            bool(invocable),
            {
                "check": "registration names an a2a or mcp endpoint",
                "invocable_endpoints": [dict(row) for row in invocable],
                "other_endpoints": [
                    dict(row) for row in listing.endpoints if row not in invocable
                ],
                "message": (
                    "no a2a or mcp endpoint is declared; a web link is a homepage and "
                    "does not count"
                )
                if not invocable
                else None,
            },
        )

    # 3. live ---------------------------------------------------------------------
    live_observation: dict | None = None
    endpoint: dict | None = None
    ok, required = prerequisite_holds("live")
    if not ok:
        skip("live", required)
    else:
        attempts = []
        for candidate in listing.invocable_endpoints:
            observation = http(
                {
                    "snapshot_id": None,
                    "agent_id": listing.agent_id,
                    "url": candidate["url"],
                    "read_body": True,
                },
                now=at,
            )
            attempts.append({**observation, "kind": candidate["kind"]})
            if observation["outcome"] == "responded":
                live_observation = observation
                endpoint = candidate
                break
        status = (live_observation or {}).get("status_code")
        record(
            "live",
            live_observation is not None,
            {
                "check": "guarded GET of the declared endpoint",
                # Both lifted out of `attempts` because they are what a reader must see
                # before quoting this level. `live` follows the sweep's vocabulary — a
                # response at any status proves the host is up — so a 404 reaches it
                # while saying the declared path is not there. `answered_2xx` is the
                # narrower reading, published beside the level rather than instead of it.
                "status_code": status,
                "answered_2xx": status is not None and 200 <= int(status) < 300,
                "attempts": [_publishable(row) for row in attempts],
                "message": None
                if live_observation
                else "no declared endpoint answered",
            },
        )

    # The sample invocation. Sent once, read by both of the levels that follow.
    sample_observation: dict | None = None
    sample_plan: dict | None = None
    if endpoint is not None:
        sample_plan = _sample_request(listing, endpoint)
        if sample_plan is not None:
            sample_observation = http(
                {
                    "snapshot_id": None,
                    "agent_id": listing.agent_id,
                    **{
                        key: value
                        for key, value in sample_plan.items()
                        if key != "sample_source"
                    },
                },
                now=at,
            )

    # 4. payment_tested -----------------------------------------------------------
    ok, required = prerequisite_holds("payment_tested")
    if not ok:
        skip("payment_tested", required)
    else:
        challenge = None
        challenged_by = None
        for label, observation in (
            ("live_probe", live_observation),
            ("sample_invocation", sample_observation),
        ):
            if observation is None:
                continue
            found = _x402_challenge(observation)
            if found is not None:
                challenge = found
                challenged_by = label
                break
        record(
            "payment_tested",
            challenge is not None,
            {
                "check": "a 402 carrying a body that parses as an x402 challenge",
                "paid": False,
                "observed_on": challenged_by,
                "challenge": challenge,
                "statuses": {
                    "live_probe": (live_observation or {}).get("status_code"),
                    "sample_invocation": (sample_observation or {}).get("status_code"),
                },
                "message": None
                if challenge is not None
                else "the endpoint answered without an x402 payment challenge",
            },
        )

    # 5. docket_tested ------------------------------------------------------------
    ok, required = prerequisite_holds("docket_tested")
    if not ok:
        skip("docket_tested", required)
    else:
        detail: dict = {
            "check": "a sample invocation returning a schema-valid structured result",
            "sample_source": (sample_plan or {}).get("sample_source"),
            "request": None
            if sample_plan is None
            else {
                "url": sample_plan["url"],
                "method": sample_plan["method"],
                "body": sample_plan.get("json_body"),
            },
            "status_code": (sample_observation or {}).get("status_code"),
            "result_hash": None,
            "schema_check": None,
            "message": None,
        }
        passed = False
        if sample_plan is None:
            detail["message"] = (
                "no sample is defined for this listing: Docket has one default sample "
                "and it is MCP tools/list, and this endpoint is not MCP. An A2A listing "
                "reaches docket_tested when its provider declares a sample input."
            )
        elif sample_observation is None or sample_observation["outcome"] != "responded":
            detail["message"] = (
                f"the sample invocation did not get a response: "
                f"{(sample_observation or {}).get('outcome')}"
            )
        elif not 200 <= int(sample_observation["status_code"]) < 300:
            detail["message"] = (
                f"the sample invocation answered HTTP "
                f"{sample_observation['status_code']}, not a success"
            )
        else:
            payload = _parse_json(sample_observation)
            if payload is None:
                detail["message"] = "the sample response body is not JSON"
            elif detail["sample_source"] == "docket_default_mcp":
                result, why = _mcp_result(payload)
                detail["schema_check"] = why
                if result is None:
                    detail["message"] = why
                else:
                    passed = True
                    detail["result_hash"] = canonical_hash(result)
            else:
                valid, why = _matches_output_schema(payload, listing.output_schema)
                detail["schema_check"] = why
                if valid:
                    passed = True
                    detail["result_hash"] = canonical_hash(payload)
                else:
                    detail["message"] = why
        record("docket_tested", passed, detail)

    # 6. docket_verified ----------------------------------------------------------
    ok, required = prerequisite_holds("docket_verified")
    if not ok:
        skip("docket_verified", required)
    else:
        reference = benchmark_ref(listing)
        record(
            "docket_verified",
            reference is not None,
            {
                "check": "docket_tested plus a registered paired-benchmark family",
                "benchmark_ref": reference,
                "message": None
                if reference
                else (
                    "no paired-benchmark family is registered for this listing; Docket's "
                    "v3 families are registered against Docket's own service ids"
                ),
            },
        )

    level = _highest_reached(reached)
    if outage and previous_level is not None and not at_least(level, previous_level):
        # An outage must not cost a listing a level it already earned. The runs above are
        # still recorded exactly as observed; only the published level is held.
        level = previous_level

    result = VerificationResult(
        agent_id=listing.agent_id,
        level=level,
        previous_level=previous_level,
        runs=tuple(runs),
        verified_at=at,
        outage=outage,
    )
    if store is not None:
        for run in result.runs:
            store.record_verification_run(
                listing.agent_id,
                level=run.level,
                at=run.at,
                ok=run.ok,
                detail=run.detail,
            )
    return result


def _highest_reached(reached: dict[str, bool]) -> str | None:
    """The strongest level whose own check passed and whose prerequisite chain holds."""
    best: str | None = None
    for level in LEVELS:
        if not reached.get(level):
            continue
        required = LEVEL_PREREQUISITE[level]
        if required is not None and not reached.get(required):
            continue
        if best is None or LEVEL_ORDER[level] > LEVEL_ORDER[best]:
            best = level
    return best


# What of a raw observation is safe and useful to publish. The body is the part a reader
# most wants and the part most likely to be large or to carry somebody else's content, so
# only its first 500 characters travel and the row says it was cut.
_PUBLISHED_BODY_CHARACTERS = 500


def _publishable(observation: dict) -> dict:
    row = {
        key: value
        for key, value in observation.items()
        if key in ("url", "kind", "outcome", "status_code", "elapsed_ms", "detail")
    }
    body = observation.get("body")
    if isinstance(body, str):
        row["body_excerpt"] = body[:_PUBLISHED_BODY_CHARACTERS]
        row["body_excerpt_truncated"] = len(body) > _PUBLISHED_BODY_CHARACTERS
        row["content_type"] = observation.get("content_type")
    return row


def apply_result(
    listing: ExternalListing, result: VerificationResult
) -> ExternalListing:
    """The same listing carrying what this run observed. Never mutates the input."""

    return replace(
        listing,
        verification=result.verification_block(),
        hireable=at_least(result.level, "docket_tested"),
        updated_at=result.verified_at,
    )
