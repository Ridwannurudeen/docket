"""The provider claim, signed with real keys.

Every signature here is produced by `eth_account` over the exact sentence Docket printed,
so the tests exercise the recovery path rather than a stub of it. The refusals matter more
than the acceptance: a claim flow that accepts the wrong signer, a replayed nonce, or a
chain outage read as an answer would put somebody else's agent under an owner's control.
"""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from docket.marketplace.external import ExternalListing, listing_from_registry
from docket.marketplace.models import Category
from docket.marketplace.providers import (
    CLAIM_TTL_SECONDS,
    ClaimError,
    claim_message,
    issue_claim_nonce,
    submit_listing,
    verify_claim,
)
from docket.store import Store

AGENT = "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:43129"
OWNER = Account.from_key("0x" + "11" * 32)
STRANGER = Account.from_key("0x" + "22" * 32)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "d.sqlite3")


def _rpc(owner_address: str, outcome: str = "owned"):
    def rpc(agent_id):
        return {
            "agent_id": agent_id,
            "chain_id": 56,
            "token_id": "43129",
            "registry": "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432",
            "owner": owner_address,
            "token_uri": "ipfs://card",
            "rpc_url": "https://bsc-dataseed.example",
            "detail": None,
            "outcome": outcome,
        }

    return rpc


def _sign(account, message: str) -> str:
    return Account.sign_message(
        encode_defunct(text=message), private_key=account.key
    ).signature.hex()


def _claim(store, account=OWNER, *, rpc=None):
    issued = issue_claim_nonce(AGENT, store=store)
    return verify_claim(
        AGENT,
        _sign(account, issued["message"]),
        nonce=issued["nonce"],
        store=store,
        rpc=rpc or _rpc(OWNER.address),
    )


def test_the_message_is_the_exact_sentence_the_owner_signs():
    issued_message = claim_message(AGENT, "abc123")

    assert issued_message == f"Docket provider claim {AGENT} abc123"


def test_the_nonce_round_trip_hands_back_what_to_sign(store):
    issued = issue_claim_nonce(AGENT, store=store)

    assert issued["message"] == claim_message(AGENT, issued["nonce"])
    assert issued["expires_in_seconds"] == CLAIM_TTL_SECONDS
    assert store.provider_claim(issued["nonce"])["verified_at"] is None


def test_the_owner_signature_is_accepted_and_spends_the_nonce(store):
    claim = _claim(store)

    assert claim.owner == OWNER.address
    assert claim.token_uri == "ipfs://card"
    assert store.provider_claim(claim.nonce)["verified_at"] == claim.verified_at


def test_a_signature_from_anybody_but_the_on_chain_owner_is_refused(store):
    issued = issue_claim_nonce(AGENT, store=store)

    with pytest.raises(ClaimError) as refused:
        verify_claim(
            AGENT,
            _sign(STRANGER, issued["message"]),
            nonce=issued["nonce"],
            store=store,
            rpc=_rpc(OWNER.address),
        )

    assert refused.value.code == "not_owner"
    assert STRANGER.address in refused.value.message
    assert store.provider_claim(issued["nonce"])["verified_at"] is None


def test_a_signature_over_a_different_sentence_recovers_the_wrong_signer(store):
    """The message is the whole binding. Signing anything else must not claim the agent."""
    issued = issue_claim_nonce(AGENT, store=store)

    with pytest.raises(ClaimError) as refused:
        verify_claim(
            AGENT,
            _sign(OWNER, "Docket provider claim something else"),
            nonce=issued["nonce"],
            store=store,
            rpc=_rpc(OWNER.address),
        )

    assert refused.value.code == "not_owner"


def test_a_nonce_cannot_be_spent_twice(store):
    issued = issue_claim_nonce(AGENT, store=store)
    signature = _sign(OWNER, issued["message"])
    verify_claim(
        AGENT, signature, nonce=issued["nonce"], store=store, rpc=_rpc(OWNER.address)
    )

    with pytest.raises(ClaimError) as refused:
        verify_claim(
            AGENT,
            signature,
            nonce=issued["nonce"],
            store=store,
            rpc=_rpc(OWNER.address),
        )

    assert refused.value.code == "stale_nonce"


def test_a_nonce_issued_for_one_agent_cannot_claim_another(store):
    issued = issue_claim_nonce(AGENT, store=store)
    other = "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:1"

    with pytest.raises(ClaimError) as refused:
        verify_claim(
            other,
            _sign(OWNER, claim_message(other, issued["nonce"])),
            nonce=issued["nonce"],
            store=store,
            rpc=_rpc(OWNER.address),
        )

    assert refused.value.code == "stale_nonce"


def test_an_expired_nonce_is_refused(store):
    issued = issue_claim_nonce(
        AGENT, store=store, now=lambda: "2026-09-03T00:00:00+00:00"
    )

    with pytest.raises(ClaimError) as refused:
        verify_claim(
            AGENT,
            _sign(OWNER, issued["message"]),
            nonce=issued["nonce"],
            store=store,
            rpc=_rpc(OWNER.address),
            now=lambda: "2026-09-03T01:00:00+00:00",
        )

    assert refused.value.code == "stale_nonce"


def test_a_malformed_signature_is_refused_before_the_chain_is_read(store):
    issued = issue_claim_nonce(AGENT, store=store)
    reads: list = []

    def rpc(agent_id):
        reads.append(agent_id)
        return _rpc(OWNER.address)(agent_id)

    with pytest.raises(ClaimError) as refused:
        verify_claim(
            AGENT, "not-a-signature", nonce=issued["nonce"], store=store, rpc=rpc
        )

    assert refused.value.code == "bad_signature"
    assert reads == []


def test_a_chain_outage_is_neither_an_acceptance_nor_a_refusal(store):
    issued = issue_claim_nonce(AGENT, store=store)

    with pytest.raises(ClaimError) as refused:
        verify_claim(
            AGENT,
            _sign(OWNER, issued["message"]),
            nonce=issued["nonce"],
            store=store,
            rpc=_rpc(None, "rpc_unavailable"),
        )

    assert refused.value.code == "chain_unavailable"
    assert "neither accepted nor refused" in refused.value.message
    assert store.provider_claim(issued["nonce"])["verified_at"] is None


def test_an_unregistered_agent_cannot_be_claimed(store):
    issued = issue_claim_nonce(AGENT, store=store)

    with pytest.raises(ClaimError) as refused:
        verify_claim(
            AGENT,
            _sign(OWNER, issued["message"]),
            nonce=issued["nonce"],
            store=store,
            rpc=_rpc(None, "not_registered"),
        )

    assert refused.value.code == "not_registered"


def test_a_submitted_listing_is_registered_provider_declared_and_not_hireable(store):
    listing = submit_listing(
        _claim(store),
        capabilities="Reads a Venus position and returns its health factor.",
        category="health_factor",
        price="0.50 USDT",
        payment_method="x402",
        sample_input={"account": "0x1"},
        output_schema={"type": "object", "required": ["health_factor"]},
        store=store,
    )

    assert listing.level == "registered"
    assert listing.capability_source == "provider_declared"
    assert listing.declared_category is Category.HEALTH_FACTOR
    assert listing.hireable is False
    assert listing.source == "provider_submitted"
    assert listing.verification["evidence"][0]["detail"]["owner"] == OWNER.address
    assert store.external_listing(AGENT)["hireable"] is False


def test_a_provider_cannot_name_their_own_endpoint(store):
    """Endpoints come from the on-chain registration. Accepting one from the form would let
    an owner point their listing anywhere without changing anything anybody can audit."""
    store.upsert_external_listing(
        listing_from_registry(
            {
                "agent_id": AGENT,
                "token_id": "43129",
                "chain_id": 56,
                "name": "Venus powered by HeyAnon",
                "description": "Reads collateral ratios.",
                "services": {"mcp": {"endpoint": "https://mcp.example/venus"}},
            }
        ).to_json()
    )

    listing = submit_listing(
        _claim(store),
        capabilities="Anything I like.",
        category=None,
        price=None,
        payment_method=None,
        sample_input=None,
        output_schema=None,
        store=store,
    )

    assert [row["url"] for row in listing.endpoints] == ["https://mcp.example/venus"]
    assert listing.name == "Venus powered by HeyAnon"


def test_a_category_outside_the_four_is_refused(store):
    with pytest.raises(ClaimError) as refused:
        submit_listing(
            _claim(store),
            capabilities="x",
            category="arbitrage",
            price=None,
            payment_method=None,
            sample_input=None,
            output_schema=None,
            store=store,
        )

    assert refused.value.code == "invalid_category"


@pytest.mark.parametrize(
    "field, value, code",
    [
        ("capabilities", "   ", "invalid_capabilities"),
        ("payment_method", "cash", "invalid_payment_method"),
        ("sample_input", ["not", "an", "object"], "invalid_sample_input"),
        ("output_schema", "not an object", "invalid_output_schema"),
    ],
)
def test_a_malformed_submission_names_the_field_it_refused(store, field, value, code):
    payload = {
        "capabilities": "Reads a position.",
        "category": None,
        "price": None,
        "payment_method": None,
        "sample_input": None,
        "output_schema": None,
        field: value,
    }

    with pytest.raises(ClaimError) as refused:
        submit_listing(_claim(store), store=store, **payload)

    assert refused.value.code == code


def test_a_submitted_listing_round_trips_through_the_store(store):
    submit_listing(
        _claim(store),
        capabilities="Reads a Venus position.",
        category="health_factor",
        price=None,
        payment_method="free",
        sample_input=None,
        output_schema=None,
        store=store,
    )
    restored = ExternalListing.from_json(store.external_listing(AGENT))

    assert restored.capability_source == "provider_declared"
    assert restored.category is Category.HEALTH_FACTOR
    rows, total = store.search_external_listings(category="health_factor")
    assert total == 1 and rows[0]["agent_id"] == AGENT
