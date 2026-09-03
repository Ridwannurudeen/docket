"""Registry lookups: 8004scan's internal API, and the chain itself where it disagrees.

Two APIs exist on 8004scan with incompatible conventions. This targets the
internal one (`/api/v1`, snake_case params, 180 req/min + 20k/day, no key),
because it is the only one exposing `min_feedbacks`/`min_score` and it carries
18x the anonymous quota of the documented public API. Verified 2026-08-07.

Not used deliberately: `/agents/search` (returns 502) and `/feedbacks?tokenId=`
(silently ignores the filter).

`lookup_owner_onchain` reads the IdentityRegistry directly because the index and
the chain do not agree. On 2026-09-03 `GET /agents/56/311253` answered 404 for a
token whose `ownerOf` returns Docket's own address — so an index miss is not
evidence that an agent is unregistered, and only the chain settles ownership.
"""

import time

import httpx

API_BASE = "https://8004scan.io/api/v1"
MAX_LIMIT = 100
MAX_ATTEMPTS = 4
BACKOFF_S = (1.0, 3.0, 8.0)
# 180 req/min ceiling; pace below it so a long sweep never trips the limiter.
MIN_INTERVAL_S = 0.4


class Scan8004Client:
    def __init__(
        self,
        base_url: str = API_BASE,
        transport: httpx.BaseTransport | None = None,
        pace: bool = True,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=30.0,
            headers={"accept": "application/json"},
        )
        self._pace = pace
        self._last_call = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Scan8004Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self) -> None:
        if not self._pace:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_INTERVAL_S:
            time.sleep(MIN_INTERVAL_S - elapsed)
        self._last_call = time.monotonic()

    def _get(self, path: str, params: dict) -> dict:
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            self._throttle()
            try:
                resp = self._client.get(path, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = httpx.HTTPStatusError(
                        f"{resp.status_code} from {path}",
                        request=resp.request,
                        response=resp,
                    )
                else:
                    resp.raise_for_status()
                    return resp.json()
            except httpx.TransportError as exc:
                last = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
        raise last  # type: ignore[misc]

    def list_agents(
        self,
        chain_id: int,
        *,
        limit: int = MAX_LIMIT,
        offset: int = 0,
        min_feedbacks: int | None = None,
        sort_by: str = "token_id",
        sort_order: str = "asc",
    ) -> tuple[list[dict], int]:
        params: dict[str, object] = {
            "chain_id": chain_id,
            "limit": min(limit, MAX_LIMIT),
            "offset": offset,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if min_feedbacks is not None:
            params["min_feedbacks"] = min_feedbacks
        data = self._get("/agents", params)
        return list(data.get("items") or []), int(data.get("total") or 0)

    def search_agents(
        self,
        chain_id: int,
        *,
        query: str | None = None,
        owner_address: str | None = None,
        limit: int = MAX_LIMIT,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Ask the registry index to narrow the query, and refuse to pretend it did not.

        What `/agents` actually supports, read off its own responses on 2026-09-03 by
        comparing each candidate parameter's `total` against the unfiltered baseline
        (300,431 BSC agents at the time of reading):

        * `search=` WORKS, server side. `search=Venus` -> total 20, `search=grid` -> 15,
          `search=liquidity` -> 340. It matches `name`, `description` and `owner_address`:
          `search=0x2a932bd8a09d7159b3d002b691c21ca02d6f7696` returned exactly the one
          agent that address owns.
        * `owner_address=` WORKS, server side, as an exact match on the indexed owner.
        * `search=` matches whole tokens, not prefixes. `search=DeFiMatrix` returned 0
          while the agent is named `DeFiMatrix.agent`; `search=DeFiMatrix.agent` and
          `search=defimatrix.agent` both returned it. A caller holding half a name gets
          nothing rather than a near miss, so the full declared name is what to send.
        * `name=`, `q=`, `query=`, `keyword=`, `name_contains=`, `filter=` and `token_id=`
          are SILENTLY IGNORED: every one of them answered with the unfiltered 300,431.
          They are never sent from here, because an ignored filter returns the whole
          registry wearing the shape of a hit.
        * 500s appear transiently under the 0.4 s pacing and clear on retry; `_get`
          already retries them, and a filtered `total` is only read from a 200.

        Nothing here fetches the whole registry: without `query` or `owner_address` this
        is one page of `list_agents`, and with them it is one page of the narrowed query.
        `sort_by=token_id` ascending is forced so paging a search is stable — the default
        order is newest first, and the registry gains thousands of agents a day.
        """
        params: dict[str, object] = {
            "chain_id": chain_id,
            "limit": min(max(limit, 1), MAX_LIMIT),
            "offset": max(offset, 0),
            "sort_by": "token_id",
            "sort_order": "asc",
        }
        if query:
            params["search"] = query
        if owner_address:
            params["owner_address"] = owner_address.lower()
        data = self._get("/agents", params)
        return list(data.get("items") or []), int(data.get("total") or 0)

    def get_agent(self, chain_id: int, token_id: str) -> dict:
        return self._get(f"/agents/{chain_id}/{token_id}", {})


# The longest an agent id may be before it is refused unread. The canonical form is
# 2 + 1 + 42 + 1 + <token digits>; 80 leaves room for a very large token id and refuses a
# megabyte of text arriving in a path segment or a JSON field.
MAX_AGENT_ID_CHARS = 80


def canonical_agent_id(agent_id: str | int) -> str:
    """`chain:registry:token` on the canonical BSC IdentityRegistry, or a ValueError.

    One parser, used everywhere an agent id enters Docket — the API paths, the provider
    claim flow and `lookup_owner_onchain` — so a bare token id and its full form resolve
    to the same string and cannot become two rows for one agent. It raises rather than
    returning None, because every caller has to refuse rather than continue, and it never
    calls `int()` on unvalidated text: `int("abc")` used to escape as an unhandled
    ValueError and surface as a 500.
    """
    from .identity.register import CHAIN_ID, IDENTITY_REGISTRY_ID

    text = str(agent_id).strip()
    if not text:
        raise ValueError("an agent id is required")
    if len(text) > MAX_AGENT_ID_CHARS:
        raise ValueError(
            f"an agent id is at most {MAX_AGENT_ID_CHARS} characters; got {len(text)}"
        )
    parts = text.split(":")
    if len(parts) == 3:
        chain_part, registry_part, token_part = parts
        if not chain_part.isdigit() or int(chain_part) != CHAIN_ID:
            raise ValueError(f"{text!r} is not a chain {CHAIN_ID} agent id")
        if registry_part.lower() != IDENTITY_REGISTRY_ID:
            raise ValueError(
                f"{text!r} names registry {registry_part!r}, not the canonical "
                f"IdentityRegistry {IDENTITY_REGISTRY_ID}"
            )
    elif len(parts) == 1:
        token_part = text
    else:
        raise ValueError(
            f"{text!r} must be a token id or chain:registry:token on chain {CHAIN_ID}"
        )
    # isdigit() rather than a try/except around int(): it refuses "+1", "1_0", unicode
    # digits and whitespace in one predicate, and leaves int() with nothing to raise on.
    if not token_part.isdigit() or not token_part.isascii():
        raise ValueError(f"{text!r} carries {token_part!r}, which is not a token id")
    return f"{CHAIN_ID}:{IDENTITY_REGISTRY_ID}:{int(token_part)}"


# Ownership outcomes, closed. `rpc_unavailable` exists so an outage can never be filed as
# `not_registered`: the first says Docket could not read the chain, the second says the
# chain answered that nobody owns this token, and a verification level must not move on
# the first.
OWNERSHIP_OUTCOMES = ("owned", "not_registered", "rpc_unavailable")


def lookup_owner_onchain(agent_id: str | int, *, rpc=None, w3=None) -> dict:
    """Who owns this ERC-8004 token, read from BSC rather than from an index.

    `agent_id` is either a bare token id or the `chain:registry:token` form the snapshot
    stores. Only the canonical IdentityRegistry on chain 56 is read; an id naming another
    registry or chain is refused rather than answered against the wrong contract.

    `ContractLogicError` is the registry answering "no such token" and is recorded as
    `not_registered`. Every other failure is the road to the chain and is recorded as
    `rpc_unavailable` — the distinction `escrow.chain.Rpc` was built to keep.
    """
    from web3 import Web3
    from web3.exceptions import ContractLogicError

    from .escrow.chain import Rpc
    from .identity.register import (
        CHAIN_ID,
        IDENTITY_ABI,
        IDENTITY_REGISTRY,
        IDENTITY_REGISTRY_ID,
    )

    canonical_id = canonical_agent_id(agent_id)
    token_id = int(canonical_id.rsplit(":", 1)[1])
    record = {
        "agent_id": canonical_id,
        "chain_id": CHAIN_ID,
        "token_id": str(token_id),
        "registry": IDENTITY_REGISTRY_ID,
        "owner": None,
        "token_uri": None,
        "rpc_url": None,
        "detail": None,
    }

    def read(session):
        registry = session.eth.contract(address=IDENTITY_REGISTRY, abi=IDENTITY_ABI)
        owner = registry.functions.ownerOf(token_id).call()
        token_uri = registry.functions.tokenURI(token_id).call()
        return Web3.to_checksum_address(owner), token_uri

    caller = rpc if rpc is not None else Rpc()
    try:
        if w3 is not None:
            owner, token_uri = read(w3)
            used = "injected"
        else:
            owner, token_uri = caller(read)
            used = getattr(caller, "used", None)
    except ContractLogicError as exc:
        return {**record, "outcome": "not_registered", "detail": str(exc)}
    except Exception as exc:  # every endpoint failed, or the road to them did
        return {
            **record,
            "outcome": "rpc_unavailable",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    return {
        **record,
        "outcome": "owned",
        "owner": owner,
        "token_uri": token_uri,
        "rpc_url": used,
    }
