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
request for free can never be tested — which would put a service that only quotes a price
above one that actually did the work. So the prerequisite table below is explicit:
`payment_tested` and `docket_tested` both hang off `live`.

`docket_tested` therefore means exactly one thing: **a sample invocation returned a
schema-valid structured result.** It says nothing whatever about payment. A listing at
`docket_tested` still carries its own `payment_tested` boolean and the evidence row behind
it — `ExternalListing.to_json` derives both from this run's evidence on every
serialisation — so the level can never be read as a claim that a payment path was
exercised, in either direction.
"""

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import httpx

from ..hire.receipts import canonical_hash
from ..liveness import _pace, request_one
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

# Docket's own samples. A provider-declared sample is NOT in this list, and cannot be: a
# sample the seller wrote, validated against a schema the seller wrote, is the seller
# certifying themselves. It is still sent and still recorded — as PROVIDER_SAMPLE_ROW,
# which carries no level.
SAMPLE_SOURCES = ("docket_default_mcp",)
# Recorded beside the levels, never as one. `_highest_reached` walks LEVELS, so a row under
# this name cannot raise anything however it turns out.
PROVIDER_SAMPLE_ROW = "provider_sample_ok"

# The most endpoints one verification will touch. A registration may name many; probing all
# of them turns one API call into a burst against somebody else's host, and the first three
# invocable ones are already more than any agent in the census declared.
MAX_ENDPOINTS_PER_RUN = 3

# What a body has to carry to be an x402 challenge rather than any other 402. Matched as
# "at least one of", because v1 and v2 name the requirements differently and a challenge
# Docket cannot read is not evidence that a challenge was served.
#
# `accepts` was in this list and has been taken out. On its own it is not an x402 marker at
# all — it is an ordinary English word that appears as a key in unrelated JSON — so a 402
# from any paywall carrying `{"accepts": [...]}` was being published as a read x402
# challenge. Both remaining markers are names only x402 uses.
X402_MARKERS = ("x402Version", "paymentRequirements")


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


def _minimal_json_check(result) -> tuple[bool, str]:
    """The floor every result clears, schema or no schema: a non-empty JSON object.

    Empty is refused on purpose. `{}` is valid JSON, it satisfies `{"type": "object"}`, and
    it is what an endpoint returns when it has nothing to say — so accepting it would let a
    server that does nothing pass the same check as one that works.
    """
    if isinstance(result, dict) and result:
        return True, "checked a non-empty JSON object"
    if isinstance(result, list) and result:
        return True, "checked a non-empty JSON array"
    return False, "the result is not a non-empty JSON object or array"


def _matches_output_schema(result, schema: dict | None) -> tuple[bool, str]:
    """Whether a result satisfies a declared output schema, and how much was checked.

    Only the parts of JSON Schema a listing can be held to without a validator library:
    the declared type, and the presence of every declared required property.

    A schema that constrains NOTHING is treated as no schema at all, rather than as a
    schema everything satisfies. `{}` used to return "declared type None satisfied" for any
    body whatsoever, and `{"type": "object"}` used to accept `{}` — so a schema its own
    author wrote could certify an endpoint that returned nothing. The minimal check is the
    floor underneath every branch here, and a schema can only add to it.
    """
    if not isinstance(schema, dict):
        ok, why = _minimal_json_check(result)
        return ok, f"no declared output schema; {why}"
    declared_type = schema.get("type")
    required = [
        key
        for key in (schema.get("required") or ())
        if isinstance(key, str) and key.strip()
    ]
    if declared_type not in ("object", "array") and not required:
        ok, why = _minimal_json_check(result)
        return ok, f"the declared output schema constrains nothing; {why}"
    if declared_type == "object" and not isinstance(result, dict):
        return False, "the declared output schema is an object and the result is not"
    if declared_type == "array" and not isinstance(result, list):
        return False, "the declared output schema is an array and the result is not"
    ok, why = _minimal_json_check(result)
    if not ok:
        return False, why
    if required:
        if not isinstance(result, dict):
            return (
                False,
                "the schema declares required keys and the result is not an object",
            )
        missing = [key for key in required if key not in result]
        if missing:
            return False, f"the result is missing required keys: {', '.join(missing)}"
        return True, f"{why}; required keys present: {', '.join(required)}"
    return True, f"{why}; declared type {declared_type!r} satisfied"


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


def _docket_sample(endpoint: dict) -> dict | None:
    """The request DOCKET sends as its sample, or None where it will not invent one.

    `docket_tested` — and therefore `hireable` — can only be reached by a request Docket
    itself defined. A seller supplying both the input and the schema it is checked against
    is a seller certifying themselves, and a marketplace that let that raise a level would
    be selling the seller's own word back to the buyer.

    Docket has exactly one such sample today and it is for MCP: `tools/list`, the server
    describing itself in a structured JSON-RPC result, read-only and calling no listed
    tool. There is deliberately no default for an A2A endpoint: the only read that costs
    nothing is fetching the agent card, and a card describes an agent rather than being
    something the agent produced. A per-category Docket-defined A2A request is the seam
    that would raise these listings past `live`, and none exists yet — inventing one by
    guessing at another operator's request shape would be a different kind of fabrication.
    """
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


def _provider_sample(listing: ExternalListing, endpoint: dict) -> dict | None:
    """The request the LISTING'S OWNER declared, which is sent and recorded but grades
    nothing. Its result lands under `PROVIDER_SAMPLE_ROW`, outside the level vocabulary."""
    if listing.sample_input is None:
        return None
    return {
        "url": endpoint["url"],
        "method": "POST",
        "json_body": listing.sample_input,
        "read_body": True,
        "sample_source": "provider_declared_sample",
    }


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
    # One hit per host per second, through the same helper the snapshot sweep paces with.
    # A verification can make three requests to one host, and three at once is a burst to
    # whoever operates it however small the number looks from here.
    last_hit: dict[str, float] = {}

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
        considered = listing.invocable_endpoints[:MAX_ENDPOINTS_PER_RUN]
        for candidate in considered:
            _pace(last_hit, candidate["url"])
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
                "endpoints_considered": len(considered),
                "endpoints_declared": len(listing.invocable_endpoints),
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

    # The sample invocations. Docket's own grades `docket_tested`; the provider's, if the
    # listing declares one, is sent and recorded and grades nothing.
    def invoke(plan: dict | None) -> dict | None:
        if plan is None:
            return None
        _pace(last_hit, plan["url"])
        return http(
            {
                "snapshot_id": None,
                "agent_id": listing.agent_id,
                **{key: value for key, value in plan.items() if key != "sample_source"},
            },
            now=at,
        )

    sample_plan: dict | None = None
    sample_observation: dict | None = None
    provider_plan: dict | None = None
    provider_observation: dict | None = None
    if endpoint is not None:
        sample_plan = _docket_sample(endpoint)
        sample_observation = invoke(sample_plan)
        provider_plan = _provider_sample(listing, endpoint)
        provider_observation = invoke(provider_plan)

    # 4. payment_tested -----------------------------------------------------------
    ok, required = prerequisite_holds("payment_tested")
    if not ok:
        skip("payment_tested", required)
    else:
        challenge = None
        challenged_by = None
        for label, observation in (
            ("live_probe", live_observation),
            ("docket_sample", sample_observation),
            ("provider_sample", provider_observation),
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
                    "docket_sample": (sample_observation or {}).get("status_code"),
                    "provider_sample": (provider_observation or {}).get("status_code"),
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
            "check": (
                "a Docket-defined sample invocation returning a schema-valid structured "
                "result. A provider-supplied sample never reaches this level"
            ),
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
                "Docket has no sample of its own for this endpoint. Its one default is "
                "MCP tools/list and this endpoint is not MCP; a sample the listing's own "
                "owner supplied cannot raise this level, so an A2A endpoint stops at live "
                "until a Docket-defined request exists for its category."
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
            else:
                result, why = _mcp_result(payload)
                detail["schema_check"] = why
                if result is None:
                    detail["message"] = why
                else:
                    passed = True
                    detail["result_hash"] = canonical_hash(result)
        record("docket_tested", passed, detail)

    # The provider's own sample, recorded outside the ladder. Written whenever a listing
    # declares one and an endpoint answered, so a reader can see that the seller's own
    # example works — and see, from the row's name, that it graded nothing.
    if provider_plan is not None:
        provider_detail: dict = {
            "check": (
                "the listing owner's declared sample against the owner's declared output "
                "schema. Recorded, never a level: a seller supplying both the input and "
                "the schema it is checked against is a seller certifying themselves"
            ),
            "raises_level": False,
            "request": {
                "url": provider_plan["url"],
                "method": provider_plan["method"],
                "body": provider_plan.get("json_body"),
            },
            "status_code": (provider_observation or {}).get("status_code"),
            "result_hash": None,
            "schema_check": None,
            "message": None,
        }
        provider_ok = False
        if (
            provider_observation is None
            or provider_observation["outcome"] != "responded"
        ):
            provider_detail["message"] = (
                f"the provider sample did not get a response: "
                f"{(provider_observation or {}).get('outcome')}"
            )
        elif not 200 <= int(provider_observation["status_code"]) < 300:
            provider_detail["message"] = (
                f"the provider sample answered HTTP "
                f"{provider_observation['status_code']}, not a success"
            )
        else:
            provider_payload = _parse_json(provider_observation)
            if provider_payload is None:
                provider_detail["message"] = "the provider sample body is not JSON"
            else:
                valid, why = _matches_output_schema(
                    provider_payload, listing.output_schema
                )
                provider_detail["schema_check"] = why
                if valid:
                    provider_ok = True
                    provider_detail["result_hash"] = canonical_hash(provider_payload)
                else:
                    provider_detail["message"] = why
        runs.append(
            LevelRun(
                level=PROVIDER_SAMPLE_ROW, ok=provider_ok, at=at, detail=provider_detail
            )
        )

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


def held_through_outage(result: VerificationResult) -> bool:
    """Whether this run could not read the chain and left a held level standing."""
    return (
        result.outage
        and result.previous_level is not None
        and result.level == result.previous_level
    )


def apply_result(
    listing: ExternalListing, result: VerificationResult
) -> ExternalListing:
    """The same listing carrying what this run observed. Never mutates the input.

    An outage that held a level does NOT overwrite the block. `verify_listing` reports the
    held level, but its runs are six `ok: false` rows — every level after `registered` was
    skipped because the chain could not be read — and writing those onto the listing
    published a `docket_tested` listing, `hireable: true`, over evidence in which nothing
    passed, stamped with a fresh `verified_at`. That is the worst shape this lane could
    serve: the strongest claim over the weakest evidence, dated now.

    So on a held outage the listing keeps the block it earned, keeps its `updated_at`, and
    gains two fields saying what happened. The outage runs are still written to
    `verification_runs` by `verify_listing`, which is where a reader goes for what this
    attempt actually observed.
    """
    if held_through_outage(result):
        return replace(
            listing,
            verification={
                **listing.verification,
                "held_from_outage": True,
                "held_at": result.verified_at,
            },
        )
    return replace(
        listing,
        verification=result.verification_block(),
        hireable=at_least(result.level, "docket_tested"),
        updated_at=result.verified_at,
    )
