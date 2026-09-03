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

import os
import time
from datetime import UTC, datetime

from web3 import Web3
from web3.exceptions import BadFunctionCallOutput, ContractLogicError
from web3.middleware import ExtraDataToPOAMiddleware

BSC_RPCS = (
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-rpc.publicnode.com",
    "https://binance.llamarpc.com",
)
ATTEMPTS_PER_RPC = 2
RPC_TIMEOUT_S = 20
RETRY_PAUSE_S = 0.5


def default_session(url: str) -> Web3:
    """The connection the failover path builds for itself.

    BSC is proof-of-authority and its headers carry 280 bytes of extraData where the
    spec allows 32, so `get_block` rejects every one of them without this middleware.
    Contract calls alone never touch a header, which is why this stayed invisible until
    the observation block was pinned: from that commit every read fetches a block first,
    and every endpoint began failing identically. `escrow/chain.py` already carried the
    same line for the same reason.
    """
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": RPC_TIMEOUT_S}))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


# The ceiling on positions read in one call, which is what actually bounds cost: two
# sequential RPC calls each, measured at roughly 0.4s per call against a public dataseed.
# Thirty covers the whole of most wallets in about twenty-five seconds and stops a wallet
# holding hundreds from turning one hire into a five-minute read.
MAX_EXAMINED = 30

# What a pruned full node says when asked for state it no longer holds. This is the trap that
# once made this repository publish the opposite of what the chain said: it is an
# INFRASTRUCTURE fault, not a revert and not an answer. A read that hits it has failed to
# observe, and must say so rather than report an absence as a finding.
PRUNED_STATE_MARKERS = (
    "missing trie node",
    "header not found",
    "state is not available",
    "required historical state unavailable",
)


class PrunedStateError(RuntimeError):
    """A historical read landed on a node that no longer holds that block's state.

    Separate from every other failure because the remedy is different — an archive endpoint,
    not a retry — and because treating it as "no position found" would turn a gap in the
    infrastructure into a claim about somebody's wallet.
    """


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
# Reading one NFT directly, for the case where walking the wallet to find it is the thing
# that fails. `ownerOf` is what stops a direct read from answering about someone else's
# position, so it is not optional.
OWNER_ABI = [
    {
        "name": "ownerOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
    },
]
# A staked position is owned by the farm, so `ownerOf` names MasterChefV3 rather than the
# wallet. The farm records who deposited it; the shape below was read off-chain against a
# live farm-held token rather than transcribed from documentation.
FARM_OWNER_ABI = [
    {
        "name": "userPositionInfos",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [
            {"name": "liquidity", "type": "uint128"},
            {"name": "boostLiquidity", "type": "uint128"},
            {"name": "tickLower", "type": "int24"},
            {"name": "tickUpper", "type": "int24"},
            {"name": "rewardGrowthInside", "type": "uint256"},
            {"name": "reward", "type": "uint256"},
            {"name": "user", "type": "address"},
            {"name": "pid", "type": "uint256"},
            {"name": "boostMultiplier", "type": "uint256"},
        ],
    },
]
USER_POSITION_OWNER_INDEX = 6

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
    def __init__(self, rpc_urls=None, w3: Web3 | None = None) -> None:
        if rpc_urls is None:
            self._archive_rpc = os.environ.get("DOCKET_ARCHIVE_RPC", "").strip()
            rpc_urls = BSC_RPCS
        else:
            self._archive_rpc = ""
        self._rpc_urls = tuple(rpc_urls)
        # An injected Web3 is used as given, with no failover: whoever supplied
        # it — a test, or a caller with their own node — owns its reliability.
        self._injected = w3
        self._sessions: dict[str, Web3] = {}

    def _call(self, do, *, observation_block: int | None = None):
        """Run `do(w3)` against the first endpoint that answers it.

        Each endpoint gets two attempts before the next is tried, and a failing
        endpoint's session is dropped so the retry builds a fresh connection
        rather than reusing a dead keep-alive.
        """
        if self._injected is not None:
            return do(self._injected)

        failures: list[str] = []
        pruned_urls: set[str] = set()
        ordinary_failure_urls: set[str] = set()
        last_pruned: Exception | None = None
        rpc_urls = self._rpc_urls
        if observation_block is not None and self._archive_rpc:
            rpc_urls = (self._archive_rpc, *rpc_urls)
        for url in rpc_urls:
            for attempt in range(ATTEMPTS_PER_RPC):
                try:
                    session = self._sessions.get(url)
                    if session is None:
                        session = default_session(url)
                        self._sessions[url] = session
                    return do(session)
                except Exception as exc:
                    self._sessions.pop(url, None)
                    text = str(exc).lower()
                    if isinstance(exc, PrunedStateError) or any(
                        marker in text for marker in PRUNED_STATE_MARKERS
                    ):
                        failure = (
                            f"{url}: {type(exc).__name__}: {exc} (pruned endpoint)"
                        )
                        failures.append(failure)
                        pruned_urls.add(url)
                        last_pruned = exc
                        # Retrying the same node cannot restore historical state. Try the
                        # next configured endpoint, which may be the archive RPC.
                        break
                    ordinary_failure_urls.add(url)
                    failures.append(
                        f"{url} (attempt {attempt + 1}): {type(exc).__name__}: {exc}"
                    )
                    if attempt < ATTEMPTS_PER_RPC - 1:
                        time.sleep(RETRY_PAUSE_S)
        all_endpoints_pruned = bool(pruned_urls) and pruned_urls == set(rpc_urls)
        archive_unreachable = (
            bool(self._archive_rpc)
            and self._archive_rpc in ordinary_failure_urls
            and ordinary_failure_urls <= {self._archive_rpc}
            and set(rpc_urls) - {self._archive_rpc} <= pruned_urls
        )
        if all_endpoints_pruned or archive_unreachable:
            summary = (
                "every BSC endpoint was pruned"
                if all_endpoints_pruned
                else "public BSC endpoints were pruned and the configured archive endpoint failed"
            )
            raise PrunedStateError(
                summary
                + ":\n  "
                + "\n  ".join(failures)
                + "\nThis is a pruned-endpoint failure, not an empty result — a "
                "reachable archive node is required to read it."
            ) from last_pruned
        raise RuntimeError("every BSC endpoint failed:\n  " + "\n  ".join(failures))

    def _exact_position(
        self,
        owner: str,
        token_id: int,
        block: int,
        observed_at: str,
        observation_block: int | None,
    ) -> dict | None:
        """Read one NFT directly and confirm this wallet holds it.

        Ownership is checked, not assumed. `positions(token_id)` answers for any token on the
        contract, so returning it without `ownerOf` would let a caller ask about a stranger's
        position and be told it was theirs. A staked position is owned by the farm, so the
        farm counts as this wallet holding it only when the farm says so — which is the same
        rule the enumeration below follows.
        """
        try:
            holder = self._call(
                lambda w3: (
                    w3.eth.contract(address=NPM, abi=OWNER_ABI)
                    .functions.ownerOf(int(token_id))
                    .call(block_identifier=block)
                ),
                observation_block=observation_block,
            )
        except (BadFunctionCallOutput, ContractLogicError, ValueError):
            # A burned or never-minted token id. Not an error: the caller asked whether this
            # wallet has it, and the answer is no.
            return None
        holder = Web3.to_checksum_address(holder)
        staked = holder == MASTER_CHEF_V3
        if holder != owner and not staked:
            return None
        if staked:
            farm_owner = self._call(
                lambda w3: (
                    w3.eth.contract(address=MASTER_CHEF_V3, abi=FARM_OWNER_ABI)
                    .functions.userPositionInfos(int(token_id))
                    .call(block_identifier=block)
                ),
                observation_block=observation_block,
            )
            # userPositionInfos exposes the depositor; a farm-held token belongs to this
            # wallet only if the farm records this wallet as the one that staked it.
            if Web3.to_checksum_address(farm_owner[USER_POSITION_OWNER_INDEX]) != owner:
                return None
        raw = self._call(
            lambda w3: (
                w3.eth.contract(address=NPM, abi=NPM_ABI)
                .functions.positions(int(token_id))
                .call(block_identifier=block)
            ),
            observation_block=observation_block,
        )
        return {
            "token_id": int(token_id),
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
            "observation_time": observed_at,
        }

    def wallet_positions(
        self,
        address: str,
        *,
        limit: int | None = None,
        include_closed: bool = False,
        max_examined: int | None = MAX_EXAMINED,
        token_id: int | None = None,
        observation_block: int | None = None,
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

        `token_id` narrows the answer to one exact NFT while the reader continues
        enumerating the wallet for honest coverage. The selected NFT is returned even
        when it is closed; otherwise an exact request for a closed position would collapse
        into the same empty list as a position that was never found.

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

        `observation_block` and `observation_time` are read together before
        enumeration and mark when the read began: a wallet with hundreds of positions
        takes long enough that later positions may be read a block or two after. They are
        provenance stamps, not a claim that the whole list is one atomic snapshot.
        """
        owner = Web3.to_checksum_address(address)
        # A pinned block makes the read reproducible, which is what a paired experiment needs:
        # the manual arm and the agent arm must be answering about the same chain state, and
        # "latest" moves between them. Every state read below is pinned to the same block, so
        # a caller cannot be handed a position from one block and a pool from another.
        at_block = "latest" if observation_block is None else int(observation_block)
        observed = self._call(
            lambda w3: w3.eth.get_block(at_block),
            observation_block=observation_block,
        )
        block = int(observed["number"])
        observed_at = datetime.fromtimestamp(
            int(observed["timestamp"]), UTC
        ).isoformat()

        # Both balances first: the wallet's true total is read before any bound applies, so a
        # truncated scan still reports what it did not reach.
        holdings: list[tuple[str, bool, int]] = []
        held_total = 0
        for holder, staked in ((NPM, False), (MASTER_CHEF_V3, True)):
            count = self._call(
                lambda w3, h=holder: (
                    w3.eth.contract(address=h, abi=HOLDER_ABI)
                    .functions.balanceOf(owner)
                    .call(block_identifier=block)
                ),
                observation_block=observation_block,
            )
            held_total += count
            holdings.append((holder, staked, count))

        positions: list[dict] = []
        closed_skipped = 0
        open_skipped = 0
        examined = 0
        # An exact request is answered by reading the token, not by hoping the walk reaches
        # it. `max_examined` stops the enumeration after thirty positions, so a wallet holding
        # 155 of them could hide the requested NFT behind the bound and report it missing —
        # and the v3 registration says that if the hire cannot select its token_id, no arm
        # runs at all. Two calls settle it regardless of where the token sits in the wallet;
        # the enumeration below still runs, for the coverage counts it is the only source of.
        direct = (
            self._exact_position(owner, token_id, block, observed_at, observation_block)
            if token_id
            else None
        )
        if direct is not None:
            positions.append(direct)
        # Enumeration and reading are interleaved so the loop can stop on a result count.
        # Kept as one pass rather than two: enumerating everything first would spend a call
        # per position before learning that the first few answered the question.
        scan_complete = True
        # Which bound stopped it, because the two have different remedies and telling a
        # caller to raise `limit` when the work ceiling truncated the read is advice that
        # cannot work.
        stopped_by = None
        for holder, staked, count in holdings:
            for index in range(count):
                if token_id is None and limit is not None and len(positions) >= limit:
                    scan_complete = False
                    stopped_by = "limit"
                    break
                if max_examined is not None and examined >= max_examined:
                    scan_complete = False
                    stopped_by = "max_examined"
                    break
                position_id = self._call(
                    lambda w3, h=holder, i=index: (
                        w3.eth.contract(address=h, abi=HOLDER_ABI)
                        .functions.tokenOfOwnerByIndex(owner, i)
                        .call(block_identifier=block)
                    ),
                    observation_block=observation_block,
                )
                raw = self._call(
                    lambda w3, t=position_id: (
                        w3.eth.contract(address=NPM, abi=NPM_ABI)
                        .functions.positions(t)
                        .call(block_identifier=block)
                    ),
                    observation_block=observation_block,
                )
                examined += 1
                # The target was already read directly, so the walk counts it for coverage
                # rather than returning it twice.
                selected = token_id is None or (
                    token_id == position_id and direct is None
                )
                if direct is not None and position_id == token_id:
                    # Reached the target the direct read already returned. It is neither
                    # selected again nor skipped — counting it as skipped would report the
                    # answer as something the read left out.
                    continue
                if not selected:
                    if raw[7] == 0:
                        closed_skipped += 1
                    else:
                        open_skipped += 1
                    continue
                if raw[7] == 0 and not include_closed and token_id is None:
                    closed_skipped += 1
                    continue
                positions.append(
                    {
                        "token_id": position_id,
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
                        "observation_time": observed_at,
                    }
                )
            if not scan_complete:
                break  # a bound stopped the NPM holdings, so the farm is not reached either
        return {
            "positions": positions,
            "positions_held": held_total,
            "positions_examined": examined,
            "closed_skipped": closed_skipped,
            "open_skipped": open_skipped,
            "target_token_id": token_id,
            "target_found": token_id is None or bool(positions),
            "observation_block": block,
            "observation_time": observed_at,
            # Whether the enumeration reached the end of the wallet. False means a bound
            # stopped it, and the positions not reached are neither open nor closed here —
            # they are unknown, which is a different thing and has to read as one.
            "scan_complete": scan_complete,
            # None when the scan finished, otherwise "limit" or "max_examined". A caller
            # told to raise `limit` when the work ceiling was what stopped the read has
            # been given a remedy that does nothing.
            "stopped_by": stopped_by,
        }

    def pool_state(
        self,
        token0: str,
        token1: str,
        fee: int,
        *,
        observation_block: int | None = None,
        archive_first: bool | None = None,
    ) -> dict:
        """Current tick, sqrt price and active liquidity for a pool.

        A pair the factory has never deployed reports `address: None` with the
        rest null, rather than raising: one unrecognised position must not take
        down a whole wallet's report.

        `observation_block` pins the pool to the same block the position was read at. Without
        it a diagnosis compares a position from one moment against a price from another, and
        the mismatch is invisible in the output — the range would be real, the tick would be
        real, and "in range" could still be wrong.

        `archive_first` distinguishes a caller-pinned historical read from the numeric block
        captured during a latest read. Direct pinned reads prefer the configured archive by
        default; the report path overrides this when it is only keeping one live read atomic.
        """
        _at = "latest" if observation_block is None else int(observation_block)
        if archive_first is None:
            archive_first = observation_block is not None
        archive_block = observation_block if archive_first else None
        address = self._call(
            lambda w3: (
                w3.eth.contract(address=FACTORY, abi=FACTORY_ABI)
                .functions.getPool(
                    Web3.to_checksum_address(token0),
                    Web3.to_checksum_address(token1),
                    int(fee),
                )
                .call(block_identifier=_at)
            ),
            observation_block=archive_block,
        )
        if address == ZERO_ADDRESS:
            return {
                "address": None,
                "tick": None,
                "sqrt_price_x96": None,
                "liquidity": None,
                "block_number": None,
                "observation_time": None,
            }

        pool = Web3.to_checksum_address(address)
        observed = self._call(
            lambda w3: w3.eth.get_block(_at),
            observation_block=archive_block,
        )
        block = int(observed["number"])
        observed_at = datetime.fromtimestamp(
            int(observed["timestamp"]), UTC
        ).isoformat()
        slot0 = self._call(
            lambda w3: (
                w3.eth.contract(address=pool, abi=POOL_ABI)
                .functions.slot0()
                .call(block_identifier=_at)
            ),
            observation_block=archive_block,
        )
        liquidity = self._call(
            lambda w3: (
                w3.eth.contract(address=pool, abi=POOL_ABI)
                .functions.liquidity()
                .call(block_identifier=_at)
            ),
            observation_block=archive_block,
        )
        return {
            "address": pool,
            "tick": slot0[1],
            "sqrt_price_x96": slot0[0],
            "liquidity": liquidity,
            "block_number": block,
            "observation_time": observed_at,
        }
