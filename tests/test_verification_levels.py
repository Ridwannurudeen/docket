"""Every level, driven by a fake chain and a fake sender, and the ways it must not move.

The property under test throughout is that a level is earned. Each test builds exactly the
evidence one level needs, and asserts both that the level is reached and that the level
above it is not — a ladder that only ever goes up is indistinguishable from one that does
not measure anything.
"""

import json

import pytest

from docket.marketplace.external import LEVELS, ExternalListing, unverified
from docket.marketplace.verification import (
    LEVEL_PREREQUISITE,
    MCP_TOOLS_LIST,
    SAMPLE_SOURCES,
    apply_result,
    benchmark_ref,
    verify_listing,
)
from docket.store import Store

AGENT = "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:43129"
OWNER = "0xDa977767452C5DD021624511f14dF67B6c9c2C1b"


def _listing(*, endpoints=(), level=None, **extra) -> ExternalListing:
    verification = (
        unverified()
        if level is None
        else {
            "level": level,
            "evidence": [],
            "verified_at": "2026-09-03T00:00:00+00:00",
        }
    )
    return ExternalListing(
        agent_id=AGENT,
        chain_id=56,
        name="Venus powered by HeyAnon",
        owner=OWNER.lower(),
        registration_uri="ipfs://x",
        endpoints=tuple(endpoints),
        declared_category=None,
        classified_category=None,
        capability_source="docket_classified",
        price=None,
        payment_method=None,
        verification=verification,
        hireable=False,
        **extra,
    )


def _owned(agent_id):
    return {
        "agent_id": agent_id,
        "chain_id": 56,
        "token_id": "43129",
        "registry": "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432",
        "owner": OWNER,
        "token_uri": "ipfs://x",
        "rpc_url": "https://bsc-dataseed.example",
        "detail": None,
        "outcome": "owned",
    }


def _outcome(name):
    def rpc(agent_id):
        return {**_owned(agent_id), "outcome": name, "owner": None, "detail": name}

    return rpc


def _responder(*, status=200, body=None, outcome="responded", content_type=None):
    """A fake sender. Records every request so a test can assert nothing extra was sent."""
    sent: list = []

    def http(endpoint, *, now):
        sent.append(dict(endpoint))
        observation = {
            "snapshot_id": endpoint.get("snapshot_id"),
            "agent_id": endpoint.get("agent_id"),
            "url": endpoint["url"],
            "observed_at": now,
            "outcome": outcome,
            "status_code": status if outcome == "responded" else None,
            "elapsed_ms": 12,
            "detail": None if outcome == "responded" else outcome,
        }
        if endpoint.get("read_body"):
            observation["body"] = body if body is not None else ""
            observation["content_type"] = content_type
            observation["truncated"] = False
        return observation

    http.sent = sent
    return http


def _staged(responses):
    """A sender that answers each request from a list, in order."""
    sent: list = []

    def http(endpoint, *, now):
        sent.append(dict(endpoint))
        stage = responses[min(len(sent) - 1, len(responses) - 1)]
        return {
            "snapshot_id": None,
            "agent_id": endpoint.get("agent_id"),
            "url": endpoint["url"],
            "observed_at": now,
            "outcome": stage.get("outcome", "responded"),
            "status_code": stage.get("status"),
            "elapsed_ms": 5,
            "detail": None,
            "body": stage.get("body", ""),
            "content_type": stage.get("content_type"),
            "truncated": False,
        }

    http.sent = sent
    return http


MCP = ({"kind": "mcp", "url": "https://mcp.example/venus"},)
A2A = ({"kind": "a2a", "url": "https://a2a.example/card"},)
WEB = ({"kind": "web", "url": "https://example.test"},)
TOOLS_RESULT = json.dumps(
    {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "getBorrowAPR"}]}}
)
X402_CHALLENGE = json.dumps(
    {
        "x402Version": 2,
        "accepts": [{"scheme": "exact", "network": "eip155:56", "amount": "500000"}],
    }
)


def _levels(result) -> dict[str, bool]:
    return {run.level: run.ok for run in result.runs}


def test_registered_needs_the_chain_and_nothing_else_follows_without_it():
    result = verify_listing(
        _listing(endpoints=MCP), rpc=_outcome("not_registered"), http=_responder()
    )

    assert result.level is None
    assert _levels(result)["registered"] is False
    for level in LEVELS[1:]:
        assert _levels(result)[level] is False
    assert result.runs[1].detail["reason"] == "prerequisite_not_reached"


def test_a_web_homepage_does_not_reach_endpoint_detected():
    """ "The marketing site answered" is not "the service answered"."""
    http = _responder()
    result = verify_listing(_listing(endpoints=WEB), rpc=_owned, http=http)

    assert result.level == "registered"
    assert _levels(result)["endpoint_detected"] is False
    assert http.sent == [], (
        "no request should be made when nothing invocable is declared"
    )
    assert result.runs[1].detail["other_endpoints"] == [dict(WEB[0])]


def test_endpoint_detected_stops_there_when_the_endpoint_does_not_answer():
    result = verify_listing(
        _listing(endpoints=A2A), rpc=_owned, http=_responder(outcome="timeout")
    )

    assert result.level == "endpoint_detected"
    assert _levels(result)["live"] is False
    assert result.runs[2].detail["message"] == "no declared endpoint answered"


def test_live_follows_the_sweep_vocabulary_and_publishes_the_status_beside_it():
    """A 404 proves the host is up, which is what `live` claims. `answered_2xx` is the
    narrower reading, published beside the level rather than instead of it."""
    result = verify_listing(
        _listing(endpoints=A2A), rpc=_owned, http=_responder(status=404, body="nope")
    )

    assert result.level == "live"
    assert result.runs[2].detail["status_code"] == 404
    assert result.runs[2].detail["answered_2xx"] is False


def test_payment_tested_needs_a_402_carrying_a_readable_x402_body():
    result = verify_listing(
        _listing(endpoints=A2A),
        rpc=_owned,
        http=_responder(status=402, body=X402_CHALLENGE),
    )

    assert result.level == "payment_tested"
    payment = result.runs[3].detail
    assert payment["paid"] is False
    assert payment["challenge"]["x402Version"] == 2
    assert payment["observed_on"] == "live_probe"


def test_a_402_whose_body_is_not_an_x402_challenge_does_not_reach_payment_tested():
    result = verify_listing(
        _listing(endpoints=A2A),
        rpc=_owned,
        http=_responder(status=402, body='{"detail": "pay me"}'),
    )

    assert result.level == "live"
    assert _levels(result)["payment_tested"] is False


def test_docket_tested_sends_tools_list_and_hashes_the_result():
    http = _staged(
        [
            {"status": 200, "body": "{}"},
            {"status": 200, "body": TOOLS_RESULT},
        ]
    )
    result = verify_listing(_listing(endpoints=MCP), rpc=_owned, http=http)

    assert result.level == "docket_tested"
    tested = result.runs[4].detail
    assert tested["sample_source"] == "docket_default_mcp"
    assert tested["sample_source"] in SAMPLE_SOURCES
    assert tested["request"]["body"] == MCP_TOOLS_LIST
    assert tested["result_hash"].startswith("0x")
    assert "tools" in tested["schema_check"]


def test_the_sample_never_calls_a_tool_the_server_lists():
    """HeyAnon's Venus server lists `borrow` and `repay`. A verification pass that called
    one would be spending somebody's money to check that it could."""
    http = _staged(
        [{"status": 200, "body": "{}"}, {"status": 200, "body": TOOLS_RESULT}]
    )
    verify_listing(_listing(endpoints=MCP), rpc=_owned, http=http)

    bodies = [row.get("json_body") for row in http.sent if row.get("json_body")]
    assert bodies == [MCP_TOOLS_LIST]
    assert all(row.get("method", "GET") in ("GET", "POST") for row in http.sent)


def test_docket_tested_reached_without_a_payment_challenge_still_says_so():
    """`docket_tested` hangs off `live`, not off `payment_tested`. The level must never be
    readable as a claim that a payment path was exercised."""
    http = _staged(
        [{"status": 200, "body": "{}"}, {"status": 200, "body": TOOLS_RESULT}]
    )
    result = verify_listing(_listing(endpoints=MCP), rpc=_owned, http=http)

    assert result.level == "docket_tested"
    assert _levels(result)["payment_tested"] is False
    assert LEVEL_PREREQUISITE["docket_tested"] == "live"


def test_an_a2a_endpoint_without_a_declared_sample_stops_at_live():
    """The only free A2A read is the agent card, and a card describes an agent rather than
    being a result it produced."""
    http = _responder(status=200, body='{"name": "x", "skills": []}')
    result = verify_listing(_listing(endpoints=A2A), rpc=_owned, http=http)

    assert result.level == "live"
    assert _levels(result)["docket_tested"] is False
    assert "no sample is defined" in result.runs[4].detail["message"]
    assert len(http.sent) == 1, "no sample request should have been sent"


def test_a_declared_sample_is_checked_against_the_declared_output_schema():
    http = _staged(
        [
            {"status": 200, "body": "{}"},
            {"status": 200, "body": '{"health_factor": 1.4, "account": "0x1"}'},
        ]
    )
    listing = _listing(
        endpoints=A2A,
        sample_input={"account": "0x1"},
        output_schema={"type": "object", "required": ["health_factor"]},
    )
    result = verify_listing(listing, rpc=_owned, http=http)

    assert result.level == "docket_tested"
    assert result.runs[4].detail["sample_source"] == "declared_sample"
    assert set(SAMPLE_SOURCES) == {"declared_sample", "docket_default_mcp"}
    assert http.sent[1]["json_body"] == {"account": "0x1"}


def test_a_declared_sample_missing_a_required_key_does_not_reach_docket_tested():
    http = _staged(
        [{"status": 200, "body": "{}"}, {"status": 200, "body": '{"account": "0x1"}'}]
    )
    listing = _listing(
        endpoints=A2A,
        sample_input={"account": "0x1"},
        output_schema={"type": "object", "required": ["health_factor"]},
    )
    result = verify_listing(listing, rpc=_owned, http=http)

    assert result.level == "live"
    assert "missing required keys: health_factor" in result.runs[4].detail["message"]


def test_a_sample_that_answers_with_something_other_than_json_does_not_pass():
    http = _staged(
        [{"status": 200, "body": "{}"}, {"status": 200, "body": "<html>hello</html>"}]
    )
    result = verify_listing(_listing(endpoints=MCP), rpc=_owned, http=http)

    assert result.level == "live"
    assert result.runs[4].detail["message"] == "the sample response body is not JSON"


def test_a_json_rpc_error_is_not_a_result():
    http = _staged(
        [
            {"status": 200, "body": "{}"},
            {"status": 200, "body": '{"jsonrpc":"2.0","id":1,"error":{"code":-32601}}'},
        ]
    )
    result = verify_listing(_listing(endpoints=MCP), rpc=_owned, http=http)

    assert result.level == "live"
    assert "JSON-RPC error" in result.runs[4].detail["message"]


def test_an_mcp_server_answering_over_sse_is_read_rather_than_failed():
    http = _staged(
        [
            {"status": 200, "body": "{}"},
            {
                "status": 200,
                "body": f"event: message\ndata: {TOOLS_RESULT}\n\n",
                "content_type": "text/event-stream",
            },
        ]
    )
    result = verify_listing(_listing(endpoints=MCP), rpc=_owned, http=http)

    assert result.level == "docket_tested"


def test_docket_verified_is_computed_and_recorded_as_unreached():
    http = _staged(
        [{"status": 200, "body": "{}"}, {"status": 200, "body": TOOLS_RESULT}]
    )
    result = verify_listing(_listing(endpoints=MCP), rpc=_owned, http=http)

    assert benchmark_ref(_listing()) is None
    assert _levels(result)["docket_verified"] is False
    assert "no paired-benchmark family" in result.runs[5].detail["message"]
    assert result.runs[5].detail["check"].startswith("docket_tested plus")


def test_a_chain_outage_never_demotes_a_level_a_listing_already_earned():
    """`rpc_unavailable` says Docket could not look. Recording it as a lost level would
    turn an outage into a verdict about somebody else's agent."""
    listing = _listing(endpoints=MCP, level="docket_tested")
    result = verify_listing(listing, rpc=_outcome("rpc_unavailable"), http=_responder())

    assert result.outage is True
    assert result.level == "docket_tested"
    assert result.previous_level == "docket_tested"
    assert _levels(result)["registered"] is False
    assert result.runs[0].detail["outcome"] == "rpc_unavailable"


def test_a_chain_revert_is_not_an_outage_and_does_take_the_level_away():
    listing = _listing(endpoints=MCP, level="docket_tested")
    result = verify_listing(listing, rpc=_outcome("not_registered"), http=_responder())

    assert result.outage is False
    assert result.level is None


def test_every_attempted_level_writes_one_evidence_row_pass_or_fail(tmp_path):
    store = Store(tmp_path / "d.sqlite3")
    http = _staged(
        [{"status": 200, "body": "{}"}, {"status": 200, "body": TOOLS_RESULT}]
    )
    result = verify_listing(_listing(endpoints=MCP), store=store, rpc=_owned, http=http)

    runs = store.iter_verification_runs(AGENT)
    assert [run["level"] for run in runs] == list(reversed(LEVELS))
    assert len(runs) == len(LEVELS) == len(result.runs)
    passed = {run["level"] for run in runs if run["ok"]}
    assert passed == {"registered", "endpoint_detected", "live", "docket_tested"}
    assert all(isinstance(run["detail"], dict) for run in runs)


def test_a_verified_listing_becomes_hireable_only_at_docket_tested():
    http = _staged(
        [{"status": 200, "body": "{}"}, {"status": 200, "body": TOOLS_RESULT}]
    )
    tested = apply_result(
        _listing(endpoints=MCP),
        verify_listing(_listing(endpoints=MCP), rpc=_owned, http=http),
    )
    live = apply_result(
        _listing(endpoints=A2A),
        verify_listing(
            _listing(endpoints=A2A), rpc=_owned, http=_responder(status=200, body="{}")
        ),
    )

    assert tested.hireable is True and tested.level == "docket_tested"
    assert live.hireable is False and live.level == "live"


@pytest.mark.parametrize("level", LEVELS)
def test_no_level_is_ever_reported_without_its_prerequisite(level):
    """The property, stated once over the whole vocabulary."""
    required = LEVEL_PREREQUISITE[level]
    assert required is None or required in LEVELS
    if required is not None:
        assert LEVELS.index(required) < LEVELS.index(level)
