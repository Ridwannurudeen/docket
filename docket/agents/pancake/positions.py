"""On-chain reader for PancakeSwap v3 positions on BSC.

Read-only by construction. Every call in this module is an `eth_call` or a
block-number read: no key is loaded, nothing is signed, and no transaction is
built. There is no code path here that could move a user's funds, which is a
stronger guarantee than a promise not to.

Three facts this module exists to get right.

**Staked positions are owned by the farm.** A position deposited into
MasterChefV3 has its NFT transferred there, so `NPM.ownerOf` returns
0x556B93...d59e and `NPM.balanceOf(wallet)` does not count it. A wallet that
farms everything reads as empty if only the position manager is enumerated.
Verified 2026-08-08: token 7087132 belongs to 0x429898...6ddd, and `ownerOf`
returns MasterChefV3. Both holders are enumerated and each position records
which one found it under `staked`, because a staked position's rewards accrue
somewhere this reader does not look.

**`tokensOwed0/1` is stale.** The pair is only written when the position is
touched on-chain, so a position that has been earning for a month still reports
the figures from its last mint, collect or burn — very often 0/0, as token
7087132 does while sitting in range. Current uncollected fees need a `collect()`
simulation against the pool's fee-growth accumulators, which is deferred to
Phase 2. The values are returned under `tokens_owed0/1` and every consumer must
label them as the stale snapshot they are.

**RPC failover is mandatory, per call.** DNS resolution to any single BSC
endpoint fails intermittently, and an enumeration of a large wallet is hundreds
of sequential calls — long enough that an endpoint which answered at connection
time can stop answering halfway through. So failover wraps each call, not just
the first, and it catches broadly: a rate-limited dataseed replies HTTP 200 with
a JSON-RPC error body, which web3 raises as a `ValueError` rather than as a
transport error. The order below is the measured one, best first.
"""

import time

from web3 import Web3

BSC_RPCS = (
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-rpc.publicnode.com",
    "https://binance.llamarpc.com",
)
ATTEMPTS_PER_RPC = 2
RPC_TIMEOUT_S = 20
RETRY_PAUSE_S = 0.5

# The ceiling on positions read in one call, which is what actually bounds cost: two
# sequential RPC calls each, measured at roughly 0.4s per call against a public dataseed.
# Thirty covers the whole of most wallets in about twenty-five seconds and stops a wallet
# holding hundreds from turning one hire into a five-minute read.
MAX_EXAMINED = 30

NPM = Web3.to_checksum_address("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
FACTORY = Web3.to_checksum_address("0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865")
MASTER_CHEF_V3 = Web3.to_checksum_address("0x556B9306565093C855AEA9AE92A594704c2Cd59e")
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Minimal fragments rather than the full artifacts: these six functions are the
# whole surface this module touches, and each was called against mainnet on
# 2026-08-08 before being written down.
HOLDER_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "tokenOfOwnerByIndex",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "index", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]
NPM_ABI = HOLDER_ABI + [
    {
        "name": "positions",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [
            {"name": "nonce", "type": "uint96"},
            {"name": "operator", "type": "address"},
            {"name": "token0", "type": "address"},
            {"name": "token1", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"},
            {"name": "liquidity", "type": "uint128"},
            {"name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"name": "tokensOwed0", "type": "uint128"},
            {"name": "tokensOwed1", "type": "uint128"},
        ],
    },
]
FACTORY_ABI = [
    {
        "name": "getPool",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "tokenA", "type": "address"},
            {"name": "tokenB", "type": "address"},
            {"name": "fee", "type": "uint24"},
        ],
        "outputs": [{"name": "", "type": "address"}],
    },
]
# PancakeSwap widened Uniswap's packed `uint8 feeProtocol` to `uint32` — decoding
# slot0 with the Uniswap tuple fails outright, so the shape is pinned here.
POOL_ABI = [
    {
        "name": "slot0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint32"},
            {"name": "unlocked", "type": "bool"},
        ],
    },
    {
        "name": "liquidity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint128"}],
    },
]


class PositionReader:
    def __init__(self, rpc_urls=BSC_RPCS, w3: Web3 | None = None) -> None:
        self._rpc_urls = tuple(rpc_urls)
        # An injected Web3 is used as given, with no failover: whoever supplied
        # it — a test, or a caller with their own node — owns its reliability.
        self._injected = w3
        self._sessions: dict[str, Web3] = {}

    def _call(self, do):
        """Run `do(w3)` against the first endpoint that answers it.

        Each endpoint gets two attempts before the next is tried, and a failing
        endpoint's session is dropped so the retry builds a fresh connection
        rather than reusing a dead keep-alive.
        """
        if self._injected is not None:
            return do(self._injected)

        failures: list[str] = []
        for url in self._rpc_urls:
            for attempt in range(ATTEMPTS_PER_RPC):
                try:
                    session = self._sessions.get(url)
                    if session is None:
                        session = Web3(
                            Web3.HTTPProvider(
                                url, request_kwargs={"timeout": RPC_TIMEOUT_S}
                            )
                        )
                        self._sessions[url] = session
                    return do(session)
                except Exception as exc:
                    self._sessions.pop(url, None)
                    failures.append(
                        f"{url} (attempt {attempt + 1}): {type(exc).__name__}: {exc}"
                    )
                    if attempt < ATTEMPTS_PER_RPC - 1:
                        time.sleep(RETRY_PAUSE_S)
        raise RuntimeError("every BSC endpoint failed:\n  " + "\n  ".join(failures))

    def wallet_positions(
        self,
        address: str,
        *,
        limit: int | None = None,
        include_closed: bool = False,
        max_examined: int | None = MAX_EXAMINED,
    ) -> dict:
        """The wallet's v3 positions, held directly or staked, with counts of what was left out.

        Enumeration costs two sequential calls per position — one
        `tokenOfOwnerByIndex`, one `positions` — and a dataseed answers each in
        about a second, so a wallet holding 155 of them takes five minutes. The
        two arguments below are the levers for that, and they do different jobs.

        `limit` caps how many positions are RETURNED, not how many are looked at.
        It used to cap the enumeration, and that made the bound land on the wrong
        thing: closed positions spent the budget before any open one was reached,
        so a wallet holding ten closed positions and one open one answered with an
        empty list. `max_examined` is what keeps the read cheap now — the caller
        bounds the work explicitly instead of getting a work bound disguised as a
        result bound.

        Cost is two sequential calls per position examined, plus three fixed
        reads. A wallet whose direct holdings exhaust `max_examined` has none of
        its staked positions reached, which is why the total is reported
        separately and why `scan_complete` says whether the enumeration got to
        the end of the wallet.

        `include_closed` does not save a single call — liquidity is only known
        once `positions` has already been read — it decides what is worth
        returning. A position with zero liquidity holds nothing in the pool and
        cannot be advised on, and wallets accumulate them by the hundred.

        Every bound leaves a count behind rather than a silence. `positions_held`
        is the wallet's true total from the two `balanceOf` reads, taken before
        any bound applies; `positions_examined` is how many were actually read;
        `closed_skipped` is how many of those held nothing; and `scan_complete`
        says whether the read reached the end of the wallet. A caller can always
        say what it did not look at, and — the case this is for — an empty list
        can always say which of the two empties it is: a wallet whose positions
        are all closed, or a wallet whose open ones were never reached.

        `block_number` is read once, before enumeration, and is the block the
        read began at: a wallet with hundreds of positions takes long enough that
        the later ones are read a block or two after. It is a provenance stamp,
        not a claim that the whole list is one atomic snapshot.
        """
        owner = Web3.to_checksum_address(address)
        block = self._call(lambda w3: w3.eth.block_number)

        # Both balances first: the wallet's true total is read before any bound applies, so a
        # truncated scan still reports what it did not reach.
        holdings: list[tuple[str, bool, int]] = []
        held_total = 0
        for holder, staked in ((NPM, False), (MASTER_CHEF_V3, True)):
            count = self._call(
                lambda w3, h=holder: (
                    w3.eth.contract(address=h, abi=HOLDER_ABI)
                    .functions.balanceOf(owner)
                    .call()
                )
            )
            held_total += count
            holdings.append((holder, staked, count))

        positions: list[dict] = []
        closed_skipped = 0
        examined = 0
        # Enumeration and reading are interleaved so the loop can stop on a result count.
        # Kept as one pass rather than two: enumerating everything first would spend a call
        # per position before learning that the first few answered the question.
        scan_complete = True
        for holder, staked, count in holdings:
            for index in range(count):
                if limit is not None and len(positions) >= limit:
                    scan_complete = False
                    break
                if max_examined is not None and examined >= max_examined:
                    scan_complete = False
                    break
                token_id = self._call(
                    lambda w3, h=holder, i=index: (
                        w3.eth.contract(address=h, abi=HOLDER_ABI)
                        .functions.tokenOfOwnerByIndex(owner, i)
                        .call()
                    )
                )
                raw = self._call(
                    lambda w3, t=token_id: (
                        w3.eth.contract(address=NPM, abi=NPM_ABI)
                        .functions.positions(t)
                        .call()
                    )
                )
                examined += 1
                if raw[7] == 0 and not include_closed:
                    closed_skipped += 1
                    continue
                positions.append(
                    {
                        "token_id": token_id,
                        "staked": staked,
                        "token0": raw[2],
                        "token1": raw[3],
                        "fee": raw[4],
                        "tick_lower": raw[5],
                        "tick_upper": raw[6],
                        "liquidity": raw[7],
                        "tokens_owed0": raw[10],
                        "tokens_owed1": raw[11],
                        "block_number": block,
                    }
                )
            if not scan_complete:
                break  # a bound stopped the NPM holdings, so the farm is not reached either
        return {
            "positions": positions,
            "positions_held": held_total,
            "positions_examined": examined,
            "closed_skipped": closed_skipped,
            # Whether the enumeration reached the end of the wallet. False means a bound
            # stopped it, and the positions not reached are neither open nor closed here —
            # they are unknown, which is a different thing and has to read as one.
            "scan_complete": scan_complete,
        }

    def pool_state(self, token0: str, token1: str, fee: int) -> dict:
        """Current tick, sqrt price and active liquidity for a pool.

        A pair the factory has never deployed reports `address: None` with the
        rest null, rather than raising: one unrecognised position must not take
        down a whole wallet's report.
        """
        address = self._call(
            lambda w3: (
                w3.eth.contract(address=FACTORY, abi=FACTORY_ABI)
                .functions.getPool(
                    Web3.to_checksum_address(token0),
                    Web3.to_checksum_address(token1),
                    int(fee),
                )
                .call()
            )
        )
        if address == ZERO_ADDRESS:
            return {
                "address": None,
                "tick": None,
                "sqrt_price_x96": None,
                "liquidity": None,
                "block_number": None,
            }

        pool = Web3.to_checksum_address(address)
        block = self._call(lambda w3: w3.eth.block_number)
        slot0 = self._call(
            lambda w3: (
                w3.eth.contract(address=pool, abi=POOL_ABI).functions.slot0().call()
            )
        )
        liquidity = self._call(
            lambda w3: (
                w3.eth.contract(address=pool, abi=POOL_ABI).functions.liquidity().call()
            )
        )
        return {
            "address": pool,
            "tick": slot0[1],
            "sqrt_price_x96": slot0[0],
            "liquidity": liquidity,
            "block_number": block,
        }
