"""Pool statistics from PancakeSwap's own explorer, and the gates that keep them honest.

The explorer's cached routes are keyless and are what PancakeSwap's own interface
reads, so they are the closest thing to a first-party source. They are also
unaudited: the top pools served on 2026-08-08 included COSA/BTCB reporting $26.7m
of TVL against $746 of 24h volume. Anything derived from a row like that is
fiction, so `is_plausible` runs before any number is quoted and hands back the
reason it refused rather than dropping the row in silence.

Two traps this module refuses to walk into.

Fee APR is net of the protocol cut. `feeUSD24h` is the whole fee the pool charged;
LPs keep 66-68% of it depending on tier and the rest goes to the protocol, so
quoting the gross figure overstates a yield by about a third. Subtracting the
reported `protocolFeeUSD24h` tracks the real split per pool rather than baking in
a multiplier that changes when governance says so.

And the APR is a property of the *pool*, not of anyone's position. A concentrated
position earns at this rate only while it is in range and earns nothing while it
is not, so nothing here returns a per-position yield — that needs the position's
own range, which is the doctor's job.
"""

import time

import httpx

PCS_API = "https://explorer.pancakeswap.com/api/cached"
# The curated list PancakeSwap's own interface ships. Being on it is not a safety
# claim, only evidence that the token is not an anonymous fabrication.
TOKEN_LIST_URL = "https://tokens.pancakeswap.finance/pancakeswap-extended.json"
BSC_CHAIN_ID = 56
MAX_ATTEMPTS = 4
BACKOFF_S = (1.0, 3.0, 8.0)


class PoolClient:
    def __init__(
        self,
        base_url: str = PCS_API,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=30.0,
            headers={"accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoolClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, url: str) -> dict | list:
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = self._client.get(url)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = httpx.HTTPStatusError(
                        f"{resp.status_code} from {url}", request=resp.request, response=resp
                    )
                else:
                    resp.raise_for_status()
                    return resp.json()
            except httpx.TransportError as exc:
                last = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
        raise last  # type: ignore[misc]

    def top_pools(self, chain: str = "bsc", version: str = "v3") -> list[dict]:
        """The explorer's top pools by TVL, exactly as served — no coercion, no filtering.

        Callers get the raw rows so the plausibility gate can name what it rejected.
        """
        data = self._get(f"/pools/{version}/{chain}/list/top")
        # This route serves a bare list; sibling explorer routes wrap theirs in `rows`.
        if isinstance(data, dict):
            return list(data.get("rows") or [])
        return list(data)

    def token_allowlist(self) -> set[str]:
        """Lowercased BSC addresses from PancakeSwap's extended token list.

        The list carries a stray entry for another chain, and addresses arrive
        checksummed while the explorer reports them lowercase — comparing the two
        without normalising both would reject every pool. Indexed rather than
        `.get`-ed on purpose: a changed shape must fail loudly, because an empty
        allowlist silently rejects everything and looks like a quiet market.
        """
        data = self._get(TOKEN_LIST_URL)
        return {
            str(token["address"]).lower()
            for token in data["tokens"]
            if token.get("chainId") == BSC_CHAIN_ID
        }


def net_fee_apr(pool: dict) -> float:
    """Annualised fee rate the liquidity providers keep, after the protocol's cut.

    The 365x is a naive annualisation of one day, the same arithmetic every LP
    dashboard does: a quiet Sunday reads as a permanently poor pool, and a day of
    frenzy reads as a fortune. It is a rate observed over 24h, not a forecast.
    """
    tvl = float(pool.get("tvlUSD") or 0)
    if tvl <= 0:
        return 0.0
    lp_fees = float(pool.get("feeUSD24h") or 0) - float(pool.get("protocolFeeUSD24h") or 0)
    return lp_fees * 365 / tvl


def turnover(pool: dict) -> float:
    """24h volume as a multiple of TVL — the ratio that exposes a fabricated pool."""
    tvl = float(pool.get("tvlUSD") or 0)
    if tvl <= 0:
        return 0.0
    return float(pool.get("volumeUSD24h") or 0) / tvl


def is_plausible(
    pool: dict,
    allowlist: set[str],
    min_tvl: float = 10_000,
    max_turnover: float = 50.0,
) -> tuple[bool, str]:
    """Whether a pool's reported numbers can be quoted at all.

    Returns the reason as well as the verdict so a rejected pool can be shown with
    why it was rejected, rather than vanishing from a list the user cannot audit.
    The order matters: the TVL floor runs before the turnover ratio, so a pool with
    no meaningful liquidity is reported as thin rather than as suspiciously busy.
    """
    for side in ("token0", "token1"):
        token = pool.get(side) or {}
        address = str(token.get("id") or "").lower()
        if address not in allowlist:
            label = token.get("symbol") or address or "?"
            return False, f"{side} {label} is not on PancakeSwap's token allowlist"

    tvl = float(pool.get("tvlUSD") or 0)
    if tvl < min_tvl:
        return False, f"tvl ${tvl:,.0f} is below the ${min_tvl:,.0f} floor"

    rate = turnover(pool)
    if rate > max_turnover:
        return False, f"turnover of {rate:,.1f}x tvl in 24h is not plausible"

    return True, "ok"
