"""How somebody else's agent gets onto Docket's shelf, and what that does not buy them.

The claim is a nonce round trip. Docket issues a single-use nonce for an agent id, the
provider signs the exact sentence Docket printed, and Docket recovers the signer and
compares it to `ownerOf(agentId)` read from BSC. Nothing else is accepted as proof: not
an email, not a matching `owner_address` in the registry index — which on 2026-09-03 was
404 for a token the chain says Docket itself owns — and not possession of the endpoint.

Three things a claim deliberately does not do.

**It does not make a listing hireable.** `submit_listing` writes the listing at level
`registered` with `hireable=False`, and only `verification.verify_listing` reaching
`docket_tested` flips that. A provider can describe their agent; they cannot certify it.

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

from .external import ExternalListing, endpoints_from_metadata
from .models import Category

CHAIN_ID = 56
NONCE_BYTES = 12
# Long enough for a person to move to a wallet and sign, short enough that an issued nonce
# is not a standing credential. Checked against `issued_at`, which is Docket's clock and
# not the caller's.
CLAIM_TTL_SECONDS = 900

PAYMENT_METHODS = ("x402", "free", "off_platform")


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


def issue_claim_nonce(agent_id: str, *, store, now=_now) -> dict:
    """Mint one single-use nonce for this agent id and return it with what to sign."""
    if not agent_id or not agent_id.strip():
        raise ClaimError("invalid_agent_id", "An agent id is required to claim.")
    nonce = secrets.token_hex(NONCE_BYTES)
    issued_at = now()
    store.issue_provider_claim(agent_id=agent_id, nonce=nonce, issued_at=issued_at)
    return {
        "agent_id": agent_id,
        "nonce": nonce,
        "message": claim_message(agent_id, nonce),
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
    record = store.provider_claim(nonce)
    if not record or record["agent_id"] != agent_id:
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
        agent_id=agent_id,
        owner=owner,
        nonce=nonce,
        verified_at=at,
        token_uri=ownership.get("token_uri"),
    )


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
    if not capabilities or not capabilities.strip():
        raise ClaimError(
            "invalid_capabilities",
            "A listing must say what the agent does. Capabilities are required.",
        )
    if sample_input is not None and not isinstance(sample_input, dict):
        raise ClaimError(
            "invalid_sample_input", "sample_input must be a JSON object or omitted."
        )
    if output_schema is not None and not isinstance(output_schema, dict):
        raise ClaimError(
            "invalid_output_schema", "output_schema must be a JSON object or omitted."
        )

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
