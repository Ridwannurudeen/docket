"""The payment layer, and an exact statement of how little it proves.

What this module establishes: a caller signed an EIP-712 authorization that names
this recipient, covers this price, on this chain, and has not expired — and the
signature recovers to the address the authorization declares as its payer. That
is a real cryptographic fact, and it is the whole of it.

What it does not establish, listed because a payment layer that stays quiet about
its gaps is how a system ends up claiming money it never received:

- **Settlement.** Nothing here broadcasts a transaction. The authorization is a
  signature sitting in a header; whether it is ever submitted, mined, or replaced
  is outside this process. So the status a caller gets is `verified_unsettled`,
  and the word "paid" appears nowhere in a hire response, enforced by a test.
- **Balance.** The payer's holdings are never read. A valid signature from an
  empty wallet verifies exactly like one from a full wallet.
- **Asset identity.** The domain's `verifyingContract` is not checked against the
  asset the challenge advertised, so this layer alone does not distinguish a
  signature over $U from one over a token of the same shape and no value.
- **Replay.** The `nonce` is carried but not remembered, so one authorization
  verifies as many times as it is presented. The free tier is what protects the
  service from repeat callers; the paid tier's protection lands with settlement.
- **`validAfter`.** Only the expiry end of the window is checked.

The challenge advertises one rail because one rail is what the verifier above can
actually read. `eip3009` — a `TransferWithAuthorization` message — is the shape
`verify_authorization` parses, and $U is an EIP-3009 token, so the offer and the
verifier agree. `permit2-exact` is the rail that ranks first on BSC when the asset
is a peg token that cannot do EIP-3009 (Binance-Peg USDC is not ERC-1271-aware);
adding it means adding a verifier for the Permit2 message shape, and advertising
it before then would be offering a payment method Docket would reject on arrival.
"""

import base64
import json
import time

from eth_account import Account
from eth_account.messages import encode_typed_data

from .catalogue import U_TOKEN, Service

OK = "ok"
X402_VERSION = 2
BSC_CHAIN_ID = 56
# CAIP-2, as the x402 v2 dialect Studio signers speak expects it — not the bare int.
NETWORK = "eip155:56"
SCHEME = "exact"
# The ceiling is 480s; Studio signers refuse anything longer. 300 leaves the payer
# a window it can actually sign inside without the offer aging out mid-exchange.
MAX_TIMEOUT_SECONDS = 300
ASSET_TRANSFER_METHOD = "eip3009"
# The EIP-712 domain a payer signs under, per asset. A challenge that names the rail
# without naming the domain cannot be signed by a client that has never seen this
# token, and a domain guessed for the wrong asset yields a signature that recovers
# to nobody — so an unlisted asset advertises no domain rather than a wrong one.
EIP712_DOMAINS = {U_TOKEN.lower(): {"name": "United Stables", "version": "1"}}
# Both spellings are in the wild; X-PAYMENT is the spec's, PAYMENT-SIGNATURE is what
# some Studio-generated clients send. Reading only one turns a paying caller into a 402.
HEADER_NAMES = ("x-payment", "payment-signature")


def build_challenge(service: Service, pay_to: str, *, resource: str) -> dict:
    """The 402 body: everything a caller needs to sign, with nothing it must ask for.

    A cold agent has to reconstruct the signing domain from this alone — chain id
    from `network`, `verifyingContract` from `asset`, name and version from
    `extra` — so the offer carries the domain material rather than assuming the
    caller already knows the token.
    """
    return {
        "x402Version": X402_VERSION,
        "accepts": [
            {
                "scheme": SCHEME,
                "network": NETWORK,
                "maxAmountRequired": str(service.price_atomic),
                "resource": resource,
                "description": service.what_you_get,
                "mimeType": "application/json",
                "payTo": pay_to,
                "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS,
                "asset": service.asset,
                "extra": {
                    "assetTransferMethod": ASSET_TRANSFER_METHOD,
                    **EIP712_DOMAINS.get(service.asset.lower(), {}),
                },
            }
        ],
    }


def parse_payment_header(headers) -> dict | None:
    """The authorization a caller attached, or None if there is nothing usable there.

    Never raises: the header is attacker-controlled, and a malformed one means
    "no payment was presented", not "the service is broken". The caller that sent
    it gets the free tier or a 402, either of which is a working answer.
    """
    for name in HEADER_NAMES:
        raw = headers.get(name)
        if not raw:
            continue
        try:
            payload = json.loads(base64.b64decode(raw, validate=True))
        except (ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def verify_authorization(
    auth: dict, *, expected_to: str, expected_value: int, chain_id: int = BSC_CHAIN_ID
) -> tuple[bool, str]:
    """Check one EIP-712 payment authorization. Returns `(ok, reason)`, first failure wins.

    Ordered cheapest-first — the four field comparisons run before the elliptic
    curve does, so a mismatched offer costs no recovery.

    Tampering needs no branch of its own. The signable message is rebuilt from the
    fields as presented, so editing any of them after signing changes the digest
    and recovery returns some other address. The cryptography detects the edit;
    code that tried to detect it separately would only be a second, weaker copy of
    the same check.

    Integers are coerced rather than trusted: JSON carries uint256 as a string as
    often as a number, and comparing a string to an int would raise instead of
    deciding. Addresses are compared lowercased — a caller that sends an
    unchecksummed address means the same address.
    """
    try:
        domain = auth["domain"]
        types = auth["types"]
        message = auth["message"]
        signature = auth["signature"]
        signed_chain = int(domain["chainId"])
        to = str(message["to"])
        value = int(message["value"])
        valid_before = int(message["validBefore"])
        declared_signer = str(message["from"])
    except (KeyError, TypeError, ValueError):
        return False, "malformed authorization: expected domain, types, message and signature"

    if signed_chain != chain_id:
        return False, f"wrong chain: authorization is for chain {signed_chain}, not {chain_id}"
    if to.lower() != expected_to.lower():
        return False, f"wrong recipient: authorization names {to}, not {expected_to}"
    if value < expected_value:
        return False, f"amount too low: authorization covers {value}, the price is {expected_value}"
    now = int(time.time())
    if valid_before <= now:
        return False, f"expired: validBefore {valid_before} is not after now ({now})"

    try:
        recovered = Account.recover_message(
            encode_typed_data(domain, types, message), signature=signature
        )
    # Broad on purpose: every byte here came from the network, and eth-account
    # raises a different type for each way it can be wrong (bad hex, wrong length,
    # empty, missing field). All of them mean the same thing to a caller.
    except Exception:
        return False, "signature could not be recovered from the authorization as presented"
    if recovered.lower() != declared_signer.lower():
        return False, f"signature recovers {recovered}, not the declared signer {declared_signer}"
    return True, OK
