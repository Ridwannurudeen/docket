"""What `search_agents` sends, and what `lookup_owner_onchain` refuses to conclude.

The search tests assert on the parameters that leave this process, not on the rows that
come back. That is the whole risk: 8004scan silently ignores `name=`, `q=`, `query=`,
`keyword=`, `name_contains=`, `filter=` and `token_id=` and answers with the unfiltered
registry, so a client that sent one of those would page 300,000 agents believing it had
narrowed to twenty.
"""

import httpx
import pytest
from web3.exceptions import ContractLogicError

from docket.scan8004 import (
    MAX_LIMIT,
    OWNERSHIP_OUTCOMES,
    Scan8004Client,
    lookup_owner_onchain,
)

REGISTRY = "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432"
UNFILTERED_TOTAL = 300_595


def _recording_transport(recorded: list, *, items=None, total=1):
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(dict(request.url.params))
        return httpx.Response(200, json={"items": items or [], "total": total})

    return httpx.MockTransport(handler)


def _client(recorded: list, **kwargs) -> Scan8004Client:
    return Scan8004Client(
        transport=_recording_transport(recorded, **kwargs), pace=False
    )


def test_a_query_is_sent_as_search_and_never_as_a_parameter_the_api_ignores():
    recorded: list = []
    with _client(recorded) as client:
        client.search_agents(56, query="health factor")

    assert recorded[0]["search"] == "health factor"
    for ignored in (
        "name",
        "q",
        "query",
        "keyword",
        "name_contains",
        "filter",
        "token_id",
    ):
        assert ignored not in recorded[0], (
            f"{ignored} is ignored by 8004scan and would return the unfiltered registry"
        )


def test_paging_a_search_is_pinned_to_ascending_token_id():
    """The default order is newest first and the registry gains thousands of agents a day,
    so an unpinned second page would skip the rows that shifted under the cursor."""
    recorded: list = []
    with _client(recorded) as client:
        client.search_agents(56, query="grid", limit=10, offset=10)

    assert recorded[0]["sort_by"] == "token_id"
    assert recorded[0]["sort_order"] == "asc"
    assert recorded[0]["offset"] == "10"


def test_an_owner_lookup_is_sent_lowercased_as_the_indexed_field():
    recorded: list = []
    with _client(recorded) as client:
        client.search_agents(
            56, owner_address="0x2A932BD8A09D7159B3D002B691C21CA02D6F7696"
        )

    assert recorded[0]["owner_address"] == "0x2a932bd8a09d7159b3d002b691c21ca02d6f7696"


def test_no_query_sends_no_search_parameter_at_all():
    """An empty search box must ask for one page, not for `search=`."""
    recorded: list = []
    with _client(recorded) as client:
        client.search_agents(56)

    assert "search" not in recorded[0]
    assert "owner_address" not in recorded[0]


def test_the_page_size_is_capped_at_the_api_maximum():
    recorded: list = []
    with _client(recorded) as client:
        client.search_agents(56, query="yield", limit=10_000)

    assert recorded[0]["limit"] == str(MAX_LIMIT)


def test_the_total_returned_is_the_filtered_total_not_the_registry():
    recorded: list = []
    with _client(recorded, items=[{"agent_id": "56:0xreg:1"}], total=20) as client:
        rows, total = client.search_agents(56, query="Venus")

    assert (len(rows), total) == (1, 20)
    assert total != UNFILTERED_TOTAL


class _Answering:
    """A stand-in for `escrow.chain.Rpc`: runs the read against a fake web3."""

    used = "https://bsc-dataseed.example"

    def __init__(self, owner: str, token_uri: str) -> None:
        self._owner = owner
        self._token_uri = token_uri

    def __call__(self, do):
        return self._owner, self._token_uri


class _Raising:
    used = None

    def __init__(self, error: Exception) -> None:
        self._error = error

    def __call__(self, do):
        raise self._error


def test_an_owned_token_reports_its_owner_and_uri_and_which_rpc_answered():
    record = lookup_owner_onchain(
        f"56:{REGISTRY}:311253",
        rpc=_Answering(
            "0xe55816904796341BF8535e25f6c8b647927fc946", "https://x/y.json"
        ),
    )

    assert record["outcome"] == "owned"
    assert record["owner"] == "0xe55816904796341BF8535e25f6c8b647927fc946"
    assert record["token_uri"] == "https://x/y.json"
    assert record["rpc_url"] == "https://bsc-dataseed.example"
    assert record["agent_id"] == f"56:{REGISTRY}:311253"


def test_every_ownership_outcome_is_one_of_the_three_declared_ones():
    """The vocabulary is closed so a new failure mode has to be classified rather than
    arriving unlabelled and being read as one of the others."""
    outcomes = {
        lookup_owner_onchain(1, rpc=_Answering("0xabc", "ipfs://x"))["outcome"],
        lookup_owner_onchain(1, rpc=_Raising(ContractLogicError("x")))["outcome"],
        lookup_owner_onchain(1, rpc=_Raising(RuntimeError("down")))["outcome"],
    }

    assert outcomes == set(OWNERSHIP_OUTCOMES)


def test_a_contract_revert_is_not_registered_and_an_outage_is_not_a_verdict():
    """The whole point of the split. A registry answering "no such token" and every RPC
    endpoint refusing are different facts, and only the first is about the agent."""
    reverted = lookup_owner_onchain(999_999_999, rpc=_Raising(ContractLogicError("x")))
    outage = lookup_owner_onchain(
        999_999_999, rpc=_Raising(RuntimeError("every endpoint failed"))
    )

    assert reverted["outcome"] == "not_registered"
    assert outage["outcome"] == "rpc_unavailable"
    assert outage["owner"] is None
    assert "RuntimeError" in outage["detail"]


def test_a_bare_token_id_is_normalised_onto_the_canonical_registry():
    record = lookup_owner_onchain(43129, rpc=_Answering("0xabc", "ipfs://x"))

    assert record["agent_id"] == f"56:{REGISTRY}:43129"
    assert record["registry"] == REGISTRY
    assert record["chain_id"] == 56


@pytest.mark.parametrize(
    "agent_id",
    [
        "1:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:1",
        "56:0x0000000000000000000000000000000000000001:1",
        "56:0xreg",
        "not-a-token",
    ],
)
def test_an_id_naming_another_registry_or_chain_is_refused_rather_than_read(agent_id):
    """Answering against the wrong contract would publish an owner for a token that
    contract never minted."""
    with pytest.raises(ValueError):
        lookup_owner_onchain(agent_id, rpc=_Answering("0xabc", "ipfs://x"))
