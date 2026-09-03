"""How somebody else's agent gets onto Docket's shelf, and what that does not buy them.

The claim is a nonce round trip. Docket issues a single-use nonce for an agent id, the
provider signs the exact sentence Docket printed, and Docket recovers the signer and
compares it to `ownerOf(agentId)` read from BSC. Nothing else is accepted as proof: not
an email, not a matching `owner_address` in the registry index — which on 2026-09-03 was
404 for a token the chain says Docket itself owns — and not possession of the endpoint.

Three things a claim deliberately does not do.

**It does not make a listing hireable, and neither does anything else a provider sends.**
`submit_listing` writes the listing at level `registered` with `hireable=False`, and only
`verification.verify_listing` reaching `docket_tested` flips that — which only a
Docket-defined sample can do. A provider may declare a `sample_input` and an
`output_schema`, and Docket does send that sample and does publish the result; it lands
under `verification.PROVIDER_SAMPLE_ROW`, which is outside the level vocabulary and cannot
raise anything. Supplying both the input and the schema it is checked against is a seller
grading their own work, and a marketplace that let that reach `hireable` would be selling
the seller's word back to the buyer. A provider can describe their agent and demonstrate
it; they cannot certify it.

**It does not let a provider name their own endpoint.** Endpoints come from the ERC-8004
registration Docket already read, never from the submission form. A provider who wants a
different endpoint listed changes their registration, which is a public act on chain, not
a private one on Docket's database.

**It does not survive reuse.** A nonce is spent by the first signature that verifies
against it and refused after that, so a captured signature cannot be replayed into a
second listing or a later change.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct

from ..scan8004 import canonical_agent_id
from .external import ExternalListing, endpoints_from_metadata
from .models import Category

CHAIN_ID = 56
NONCE_BYTES = 12
# Long enough for a person to move to a wallet and sign, short enough that an issued nonce
# is not a standing credential. Checked against `issued_at`, which is Docket's clock and
# not the caller's.
CLAIM_TTL_SECONDS = 900

PAYMENT_METHODS = ("x402", "free", "off_platform")
# A price is free text because Docket does not read one off chain and will not invent a
# denomination for somebody else's service. Free text still gets a bound: it is stored,
# served and rendered, and an unbounded string in any of those places is a hole.
MAX_PRICE_CHARS = 64
MAX_CAPABILITIES_CHARS = 4_000


class ClaimError(Exception):
    """A refused claim, carrying the code the API answers with."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def claim_message(agent_id: str, nonce: str) -> str:
    """The exact sentence a provider signs. Byte-for-byte, or the signature is refused."""
    return f"Docket provider claim {agent_id} {nonce}"


def claimable_agent_id(agent_id) -> str:
    """The canonical form, or a `ClaimError` the API can answer with.

    Every id entering the claim flow goes through here. It bounds the length and refuses
    anything that is not a token id on the canonical registry, so a nonce is never minted
    against text the chain read would later choke on — `int("abc")` used to escape as an
    unhandled ValueError and surface as a 500. Canonical on both sides also means a bare
    token id and its full form are the same claim rather than two rows for one agent.
    """
    try:
        return canonical_agent_id(agent_id)
    except (TypeError, ValueError) as exc:
        raise ClaimError("invalid_agent_id", str(exc)) from exc


def issue_claim_nonce(agent_id: str, *, store, now=_now) -> dict:
    """Mint one single-use nonce for this agent id and return it with what to sign.

    The canonical id is what is stored and what appears in the message, so an owner who
    asks with a bare token id signs the same sentence as one who asks with the full form.
    """
    canonical = claimable_agent_id(agent_id)
    nonce = secrets.token_hex(NONCE_BYTES)
    issued_at = now()
    store.issue_provider_claim(agent_id=canonical, nonce=nonce, issued_at=issued_at)
    return {
        "agent_id": canonical,
        "nonce": nonce,
        "message": claim_message(canonical, nonce),
        "issued_at": issued_at,
        "expires_in_seconds": CLAIM_TTL_SECONDS,
    }


@dataclass(frozen=True)
class ProviderClaim:
    """Proof, at one moment, that this address owned this agent on chain."""

    agent_id: str
    owner: str
    nonce: str
    verified_at: str
    token_uri: str | None


def _expired(issued_at: str, at: str) -> bool:
    try:
        issued = datetime.fromisoformat(issued_at)
        current = datetime.fromisoformat(at)
    except ValueError:
        # An unparseable stamp is treated as expired rather than as fresh: the failure
        # that opens a claim is the one this must not choose.
        return True
    return current - issued > timedelta(seconds=CLAIM_TTL_SECONDS)


def verify_claim(
    agent_id: str,
    signature: str,
    *,
    nonce: str,
    store,
    rpc,
    now=_now,
) -> ProviderClaim:
    """Recover the signer of Docket's own sentence and hold it against the chain.

    `rpc` is `scan8004.lookup_owner_onchain`. Its three outcomes are kept apart here for
    the reason they exist: `rpc_unavailable` is refused as `chain_unavailable`, never as
    `not_owner`, so an outage cannot be reported to a provider as a failed claim.
    """
    at = now()
    agent_id = claimable_agent_id(agent_id)
    record = store.provider_claim(nonce)
    if not record or claimable_agent_id(record["agent_id"]) != agent_id:
        raise ClaimError(
            "stale_nonce",
            "That nonce was not issued for this agent. Request a new one from "
            "POST /api/providers/claim.",
        )
    if record["verified_at"] is not None:
        raise ClaimError(
            "stale_nonce", "That nonce has already been used. Request a new one."
        )
    if _expired(record["issued_at"], at):
        raise ClaimError(
            "stale_nonce",
            f"That nonce is older than {CLAIM_TTL_SECONDS} seconds. Request a new one.",
        )

    message = claim_message(agent_id, nonce)
    try:
        recovered = Account.recover_message(
            encode_defunct(text=message), signature=signature
        )
    except Exception as exc:
        raise ClaimError(
            "bad_signature",
            f"The signature did not recover a signer for {message!r}: {type(exc).__name__}.",
        ) from exc

    ownership = rpc(agent_id)
    outcome = ownership.get("outcome")
    if outcome == "rpc_unavailable":
        raise ClaimError(
            "chain_unavailable",
            "Docket could not read ownerOf from any BSC endpoint, so this claim is "
            "neither accepted nor refused. Retry.",
        )
    if outcome != "owned":
        raise ClaimError(
            "not_registered",
            f"The IdentityRegistry has no owner for {agent_id}. A claim is only "
            "possible for a registered agent.",
        )
    owner = str(ownership.get("owner") or "")
    if recovered.lower() != owner.lower():
        raise ClaimError(
            "not_owner",
            f"{recovered} signed the claim, but {owner} owns {agent_id} on chain.",
        )
    if not store.settle_provider_claim(nonce=nonce, owner=owner, verified_at=at):
        raise ClaimError(
            "stale_nonce", "That nonce has already been used. Request a new one."
        )
    return ProviderClaim(
        # The chain read's own id, not the caller's spelling. It is the same string
        # `canonical_agent_id` produced above, and taking it from the ownership record
        # keeps the listing keyed on what the registry answered about.
        agent_id=ownership.get("agent_id") or agent_id,
        owner=owner,
        nonce=nonce,
        verified_at=at,
        token_uri=ownership.get("token_uri"),
    )


def validate_listing_fields(
    *,
    capabilities,
    category,
    price,
    payment_method,
    sample_input,
    output_schema,
) -> dict:
    """Check everything a submission carries, and hand it back normalised.

    Separated from `submit_listing` so the API can run it BEFORE spending the nonce. A
    submission refused for a typo used to burn the nonce on the way in, which meant the
    owner had to go back to their wallet and sign again to fix a spelling.
    """
    if category is not None and not isinstance(category, Category):
        try:
            category = Category(str(category))
        except ValueError as exc:
            raise ClaimError(
                "invalid_category",
                f"{category!r} is not one of {[member.value for member in Category]}.",
            ) from exc
    if payment_method is not None and payment_method not in PAYMENT_METHODS:
        raise ClaimError(
            "invalid_payment_method",
            f"{payment_method!r} is not one of {list(PAYMENT_METHODS)}.",
        )
    if not isinstance(capabilities, str) or not capabilities.strip():
        raise ClaimError(
            "invalid_capabilities",
            "A listing must say what the agent does. Capabilities are required.",
        )
    if len(capabilities.strip()) > MAX_CAPABILITIES_CHARS:
        raise ClaimError(
            "invalid_capabilities",
            f"Capabilities are at most {MAX_CAPABILITIES_CHARS} characters.",
        )
    if price is not None:
        if not isinstance(price, str):
            raise ClaimError(
                "invalid_price",
                "price must be a string, or omitted where there is none.",
            )
        price = price.strip() or None
        if price is not None and len(price) > MAX_PRICE_CHARS:
            raise ClaimError(
                "invalid_price", f"price is at most {MAX_PRICE_CHARS} characters."
            )
    if sample_input is not None and not isinstance(sample_input, dict):
        raise ClaimError(
            "invalid_sample_input", "sample_input must be a JSON object or omitted."
        )
    if output_schema is not None and not isinstance(output_schema, dict):
        raise ClaimError(
            "invalid_output_schema", "output_schema must be a JSON object or omitted."
        )
    return {
        "capabilities": capabilities.strip(),
        "category": category,
        "price": price,
        "payment_method": payment_method,
        "sample_input": sample_input,
        "output_schema": output_schema,
    }


def submit_listing(
    claim: ProviderClaim,
    *,
    capabilities: str,
    category: Category | str | None,
    price: str | None,
    payment_method: str | None,
    sample_input: dict | None,
    output_schema: dict | None,
    store,
    registry_metadata: dict | None = None,
) -> ExternalListing:
    """Write the provider's own description of their agent, at level `registered`.

    The category is theirs to declare, so `capability_source` is `provider_declared` and
    `declared_category` carries it — Docket's rule table is not consulted and is not
    allowed to overwrite an owner's statement about their own agent.

    Endpoints are taken from whatever registration metadata Docket already holds (the
    hydrated listing, or a card passed in), never from this call. `hireable` is False and
    stays False until a verification run reaches `docket_tested`.
    """
    fields = validate_listing_fields(
        capabilities=capabilities,
        category=category,
        price=price,
        payment_method=payment_method,
        sample_input=sample_input,
        output_schema=output_schema,
    )
    category = fields["category"]
    capabilities = fields["capabilities"]
    price = fields["price"]

    held = store.external_listing(claim.agent_id)
    endpoints: tuple[dict, ...] = ()
    name = ""
    registration_uri = claim.token_uri
    if held:
        existing = ExternalListing.from_json(held)
        endpoints = existing.endpoints
        name = existing.name
        registration_uri = existing.registration_uri or registration_uri
    if registry_metadata:
        endpoints = endpoints_from_metadata(registry_metadata) or endpoints
        name = registry_metadata.get("name") or name

    listing = ExternalListing(
        agent_id=claim.agent_id,
        chain_id=CHAIN_ID,
        name=name,
        owner=claim.owner.lower(),
        registration_uri=registration_uri,
        endpoints=endpoints,
        declared_category=category,
        classified_category=None,
        capability_source="provider_declared",
        price=price,
        payment_method=payment_method,
        verification={
            "level": "registered",
            "evidence": [
                {
                    "level": "registered",
                    "ok": True,
                    "at": claim.verified_at,
                    "detail": {
                        "check": "IdentityRegistry.ownerOf against a signed claim",
                        "owner": claim.owner,
                        "token_uri": claim.token_uri,
                        "nonce": claim.nonce,
                        "message": claim_message(claim.agent_id, claim.nonce),
                    },
                }
            ],
            "verified_at": claim.verified_at,
        },
        hireable=False,
        capabilities=capabilities.strip(),
        classification_rationale=(
            "the owner of this agent declared the category when they claimed it"
        ),
        sample_input=sample_input,
        output_schema=output_schema,
        source="provider_submitted",
        updated_at=claim.verified_at,
    )
    store.upsert_external_listing(listing.to_json())
    return listing
