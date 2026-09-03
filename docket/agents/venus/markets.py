"""On-chain reader for Venus Core Pool on BSC. Reads, and interprets nothing.

Read-only by construction, the way `agents/pancake/positions.py` is: every call below is
an `eth_call` or a block-number read, no key is loaded, nothing is signed and no
transaction is built. There is no code path here that could move a user's funds.

Four facts this module exists to get right, each checked against BSC mainnet on
2026-08-10 at block 115,173,763 before it was written down.

**Venus publishes no health factor.** `getAccountLiquidity` returns `(error, liquidity,
shortfall)` in USD, 1e18-scaled — how much more could be borrowed, or how far past the
limit the account already is. `AccountState` carries exactly those, and deliberately has
no field called `health_factor`: that word belongs to a figure derived one module up with
its formula stated.

**One market of the 52 has no underlying.** vBNB at 0xA07c5b…ea36 is the native market,
and `underlying()` on it returns no bytes at all. `eth_call` *succeeds* — it is the ABI
decode that fails — so the probe here reads raw bytes and treats an empty answer as the
contract answering "none". Letting web3 decode it would raise, and a retry loop would
then report a market that exists as an endpoint outage.

**Only the markets the account has entered are read.** `getAssetsIn` is the same list the
comptroller itself iterates when it computes liquidity, so these rows and Venus's own
figure are drawn from one set. A supply in a market the account never entered is not
collateral, contributes nothing to liquidity, and is not read here — stated in the record
rather than left as a silence.

**A pinned read is a different read, and it says so when it cannot make one.** Every
call below takes an `observation_block`, because a paired experiment needs both arms
answering about the same chain state and "latest" moves between them: v3-09 registers one
account at one block and records an answer about a different block as a blocked contract
rather than a worse answer. Public BSC dataseeds prune, so a pinned read is attempted
against `DOCKET_ARCHIVE_RPC` first, exactly the order `agents/pancake/positions.py` uses.
Where no archive endpoint is configured a pinned read is REFUSED rather than quietly
served from the head — answering the wrong block is the one failure the registered
contract is written to catch, and it looks identical to success.

**Three scales, and none of them is 1e18 twice.** The collateral factor and the
liquidity/shortfall pair are 1e18. The exchange rate is 1e(18 + underlying decimals −
vToken decimals), which is 1e28 for the 18-decimal underlyings BSC uses against 8-decimal
vTokens. The oracle price is 1e(36 − underlying decimals). The two that vary cancel in
`balance × rate ÷ 1e18 × price ÷ 1e18`, which is why nothing here needs to know an
underlying's decimals — and why that arithmetic lives in `guard.py`, next to the sentence
explaining it, rather than here.
"""

import os
from dataclasses import dataclass

from web3 import Web3

from ...escrow.chain import Rpc
from ..pancake.positions import (
    PRUNED_STATE_MARKERS,
    PrunedStateError,
)

BSC_RPCS = (
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-rpc.publicnode.com",
    "https://binance.llamarpc.com",
)
# The Unitroller — the comptroller's storage proxy, and the address every Venus interface
# calls. 1,508 bytes of code on 2026-08-10, and `getAllMarkets()` returned 52 markets.
UNITROLLER = Web3.to_checksum_address("0xfD36E2c2a6789Db23113685031d7F16329158384")
# What `getAccountLiquidity` and `getAccountSnapshot` put in their first return slot when
# the answer that follows is meaningful. Anything else means the numbers beside it do not
# describe a position, and reading them anyway would invent one.
NO_ERROR = 0
UNDERLYING_SELECTOR = "0x" + Web3.keccak(text="underlying()")[:4].hex()
# What a caller gets when it asks for a block this deployment cannot read. A distinct
# code rather than a generic failure, because the remedy is an archive endpoint and
# nothing about retrying helps.
ARCHIVE_REQUIRED = "observation_block_unsupported"

# Which call produced which figure. One dict rather than a string per row: the mapping is
# a property of this module, not of any particular account, and duplicating it per row
# would be 52 chances for one of them to say something the reader does not do.
ROW_SOURCES = {
    "symbol": "vToken.symbol",
    "collateral_factor_mantissa": "comptroller.markets",
    "snapshot_error": "vToken.getAccountSnapshot",
    "vtoken_balance": "vToken.getAccountSnapshot",
    "borrow_balance": "vToken.getAccountSnapshot",
    "exchange_rate_mantissa": "vToken.getAccountSnapshot",
    "underlying_price_mantissa": "oracle.getUnderlyingPrice",
}
ENTERED_ONLY = (
    "These rows are the markets getAssetsIn reports the account has entered, which is the "
    "same set the comptroller iterates when it computes liquidity and shortfall. A supply "
    "in a market the account never entered is not collateral, adds nothing to either "
    "figure, and is not read here."
)

COMPTROLLER_ABI = [
    {
        "name": "getAllMarkets",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address[]"}],
    },
    {
        "name": "markets",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "vToken", "type": "address"}],
        "outputs": [
            {"name": "isListed", "type": "bool"},
            {"name": "collateralFactorMantissa", "type": "uint256"},
            {"name": "isVenus", "type": "bool"},
        ],
    },
    {
        "name": "getAccountLiquidity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [
            {"name": "error", "type": "uint256"},
            {"name": "liquidity", "type": "uint256"},
            {"name": "shortfall", "type": "uint256"},
        ],
    },
    {
        "name": "getAssetsIn",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "address[]"}],
    },
    {
        "name": "oracle",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]
VTOKEN_ABI = [
    {
        "name": "symbol",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    },
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
    {
        # `(error, vTokenBalance, borrowBalance, exchangeRateMantissa)` in one call, which
        # is three reads' worth of answer for one round trip and — more to the point — one
        # consistent moment rather than three.
        "name": "getAccountSnapshot",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [
            {"name": "error", "type": "uint256"},
            {"name": "vTokenBalance", "type": "uint256"},
            {"name": "borrowBalance", "type": "uint256"},
            {"name": "exchangeRateMantissa", "type": "uint256"},
        ],
    },
]
ORACLE_ABI = [
    {
        "name": "getUnderlyingPrice",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "vToken", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]

NATIVE_NOTE = (
    "no underlying(): this is the native market, and the call returns no bytes rather "
    "than reverting. The chain answered — it was the decode that had nothing to decode."
)


@dataclass(frozen=True)
class Market:
    """One listed market, as the comptroller and the vToken describe it."""

    vtoken: str
    symbol: str
    decimals: int
    underlying: str | None
    collateral_factor_mantissa: int
    is_listed: bool
    as_of_block: int

    def as_record(self) -> dict:
        return {
            "vtoken": self.vtoken,
            "symbol": self.symbol,
            "decimals": self.decimals,
            "underlying": self.underlying,
            "underlying_note": None if self.underlying else NATIVE_NOTE,
            "collateral_factor_mantissa": str(self.collateral_factor_mantissa),
            "collateral_factor_scale": "1e18",
            "is_listed": self.is_listed,
            "as_of_block": self.as_of_block,
        }


@dataclass(frozen=True)
class MarketPosition:
    """What one entered market holds for one account. Raw, in the units the chain used.

    No field here is a conversion of another. `vtoken_balance` is in vToken units and
    `borrow_balance` is in the underlying's, and turning the first into the second needs
    the exchange rate beside them — which is carried rather than applied, so the module
    that applies it can say so where a reader can see it.
    """

    vtoken: str
    symbol: str
    collateral_factor_mantissa: int
    snapshot_error: int
    vtoken_balance: int
    borrow_balance: int
    exchange_rate_mantissa: int
    underlying_price_mantissa: int
    as_of_block: int

    def as_record(self) -> dict:
        return {
            "vtoken": self.vtoken,
            "symbol": self.symbol,
            "collateral_factor_mantissa": str(self.collateral_factor_mantissa),
            "snapshot_error": self.snapshot_error,
            "vtoken_balance": str(self.vtoken_balance),
            "borrow_balance": str(self.borrow_balance),
            "exchange_rate_mantissa": str(self.exchange_rate_mantissa),
            "underlying_price_mantissa": str(self.underlying_price_mantissa),
            "as_of_block": self.as_of_block,
            "sources": dict(ROW_SOURCES),
        }


@dataclass(frozen=True)
class AccountState:
    """Venus's own answer about an account, and the rows it was computed over.

    There is deliberately no `health_factor` field. Venus does not publish one, and a
    field with that name here would make an invented ratio look like a read.
    """

    address: str
    error_code: int
    liquidity_usd: int
    shortfall_usd: int
    markets_listed: int
    rows: tuple[MarketPosition, ...]
    oracle: str
    as_of_block: int
    reads: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Whether every answer that went into this state was one the chain stood behind."""
        return self.error_code == NO_ERROR and all(
            row.snapshot_error == NO_ERROR for row in self.rows
        )

    def as_record(self) -> dict:
        return {
            "address": self.address,
            "error_code": self.error_code,
            "liquidity_usd": str(self.liquidity_usd),
            "shortfall_usd": str(self.shortfall_usd),
            "scale": "1e18 USD, as the comptroller reports both figures",
            "markets_listed": self.markets_listed,
            "markets_entered": len(self.rows),
            "rows": [row.as_record() for row in self.rows],
            "oracle": self.oracle,
            "as_of_block": self.as_of_block,
            "complete": self.complete,
            "reads": list(self.reads),
            "note": ENTERED_ONLY,
        }


def _at_block(observation_block: int | None):
    """What web3 wants as a `block_identifier`: a number, or the head."""
    return "latest" if observation_block is None else int(observation_block)


class VenusReader:
    """The comptroller, the vTokens and the oracle, read over the endpoint failover.

    `escrow.chain.Rpc` is reused rather than copied, for the reason its own docstring
    gives: the failover shape already exists in three places here and a fourth would be
    the one that goes stale. It retries each endpoint twice, drops a failing endpoint's
    session so the retry opens a fresh connection, and raises naming every endpoint it
    tried when none of them answers.
    """

    def __init__(
        self,
        rpc_urls=BSC_RPCS,
        *,
        comptroller: str = UNITROLLER,
        rpc=None,
        session_factory=None,
        archive_rpc: str | None = None,
    ) -> None:
        self.comptroller = Web3.to_checksum_address(comptroller)
        # Read once at construction, the way `PositionReader` reads it, so a pinned read
        # and a head read on the same object never disagree about which endpoints exist.
        self.archive_rpc = (
            os.environ.get("DOCKET_ARCHIVE_RPC", "").strip()
            if archive_rpc is None
            else archive_rpc.strip()
        )
        self._urls = tuple(rpc_urls)
        self._session_factory = session_factory
        if rpc is not None:
            # Supplied as given, with no failover: whoever passed it — a test, or a caller
            # with their own node — owns its reliability, including whether it holds the
            # history a pinned read asks for.
            self._rpc = rpc
            self._injected = True
        elif session_factory is not None:
            self._rpc = Rpc(rpc_urls, session_factory=session_factory)
            self._injected = False
        else:
            self._rpc = Rpc(rpc_urls)
            self._injected = False
        self._archive = None

    def _at(self, observation_block: int | None):
        """The caller to run a read through, given the block it is asking about.

        A head read goes through the ordinary failover. A pinned read goes through one
        whose first endpoint is the archive, because the public dataseeds prune and a
        pruned node answers `missing trie node` rather than the state that was there.
        """
        if observation_block is None or self._injected:
            return self._rpc
        if not self.archive_rpc:
            raise ValueError(
                f"{ARCHIVE_REQUIRED}: reading block {observation_block} needs an archive "
                "endpoint and DOCKET_ARCHIVE_RPC is not set on this deployment. The head "
                "would answer, but it would be answering about a different block"
            )
        if self._archive is None:
            urls = (self.archive_rpc, *self._urls)
            self._archive = (
                Rpc(urls, session_factory=self._session_factory)
                if self._session_factory is not None
                else Rpc(urls)
            )
        return self._archive

    def _read(self, do, *, observation_block: int | None = None):
        """One read, with a pruned endpoint reported as a gap rather than as an answer."""
        try:
            return self._at(observation_block)(do)
        except PrunedStateError:
            raise
        except Exception as exc:
            text = str(exc).lower()
            if observation_block is not None and any(
                marker in text for marker in PRUNED_STATE_MARKERS
            ):
                raise PrunedStateError(
                    f"block {observation_block} is no longer held by the endpoints this "
                    f"read reached: {type(exc).__name__}: {exc}. This is a pruned-endpoint "
                    "failure and not an empty account — a reachable archive node is "
                    "required to read it."
                ) from exc
            raise

    def _comptroller(self, w3):
        return w3.eth.contract(address=self.comptroller, abi=COMPTROLLER_ABI)

    def _vtoken(self, w3, vtoken: str):
        return w3.eth.contract(address=Web3.to_checksum_address(vtoken), abi=VTOKEN_ABI)

    def block_number(self) -> int:
        return self._read(lambda w3: w3.eth.block_number)

    def listed_markets(self, *, observation_block: int | None = None) -> tuple[str, ...]:
        """Every vToken the comptroller lists, in its own order. One call."""
        at = _at_block(observation_block)
        return tuple(
            Web3.to_checksum_address(address)
            for address in self._read(
                lambda w3: self._comptroller(w3)
                .functions.getAllMarkets()
                .call(block_identifier=at),
                observation_block=observation_block,
            )
        )

    def underlying_of(
        self, vtoken: str, *, observation_block: int | None = None
    ) -> str | None:
        """The market's underlying token, or None where the market is the native asset.

        Read as raw bytes on purpose. `underlying()` on vBNB returns nothing, and web3's
        decoder raises on that — which the failover would then retry against every
        endpoint and report as an outage. An empty return is the contract's answer and is
        read as one; anything else is left to fail.
        """
        at = _at_block(observation_block)
        raw = self._read(
            lambda w3: w3.eth.call(
                {"to": Web3.to_checksum_address(vtoken), "data": UNDERLYING_SELECTOR},
                block_identifier=at,
            ),
            observation_block=observation_block,
        )
        if not raw:
            return None
        return Web3.to_checksum_address(bytes(raw)[-20:])

    def markets(
        self, *, limit: int | None = None, observation_block: int | None = None
    ) -> list[Market]:
        """Every listed market with its collateral factor, or the first `limit` of them.

        Four calls per market against 55 markets is 220 sequential round trips, which on a
        public dataseed is minutes rather than seconds — the same arithmetic that bounds
        the Range Keeper's read. `limit` is the lever for that, and it takes the
        comptroller's own order so a bounded read is reproducible rather than arbitrary.
        """
        block = (
            self.block_number() if observation_block is None else int(observation_block)
        )
        at = _at_block(observation_block)
        listed = self.listed_markets(observation_block=observation_block)
        if limit is not None:
            listed = listed[:limit]
        out = []
        for vtoken in listed:
            is_listed, collateral_factor, _ = self._read(
                lambda w3, v=vtoken: self._comptroller(w3)
                .functions.markets(v)
                .call(block_identifier=at),
                observation_block=observation_block,
            )
            out.append(
                Market(
                    vtoken=vtoken,
                    symbol=self._read(
                        lambda w3, v=vtoken: self._vtoken(w3, v)
                        .functions.symbol()
                        .call(block_identifier=at),
                        observation_block=observation_block,
                    ),
                    decimals=int(
                        self._read(
                            lambda w3, v=vtoken: self._vtoken(w3, v)
                            .functions.decimals()
                            .call(block_identifier=at),
                            observation_block=observation_block,
                        )
                    ),
                    underlying=self.underlying_of(
                        vtoken, observation_block=observation_block
                    ),
                    collateral_factor_mantissa=int(collateral_factor),
                    is_listed=bool(is_listed),
                    as_of_block=block,
                )
            )
        return out

    def account(
        self, address: str, *, observation_block: int | None = None
    ) -> AccountState:
        """Venus's own liquidity and shortfall for an account, and the rows behind them.

        With no `observation_block` the block is read first and stamped on everything, so
        the whole state names one moment. It is a provenance stamp rather than an
        atomicity claim: an account in several markets takes several round trips, and the
        later rows are read a block or two after the first.

        With one, every call below is pinned to it and the state is exactly reproducible —
        which is what a paired experiment needs, because "latest" moves between its two
        arms and an answer about a different block is a different observation rather than
        a worse one. A pinned read needs an archive endpoint; without one it is refused
        rather than served from the head.
        """
        account = Web3.to_checksum_address(address)
        block = (
            self.block_number() if observation_block is None else int(observation_block)
        )
        at = _at_block(observation_block)
        reads = [
            "eth_blockNumber" if observation_block is None else "caller-pinned block",
            "comptroller.getAccountLiquidity",
            "comptroller.getAssetsIn",
        ]

        error, liquidity, shortfall = self._read(
            lambda w3: self._comptroller(w3)
            .functions.getAccountLiquidity(account)
            .call(block_identifier=at),
            observation_block=observation_block,
        )
        entered = tuple(
            Web3.to_checksum_address(v)
            for v in self._read(
                lambda w3: self._comptroller(w3)
                .functions.getAssetsIn(account)
                .call(block_identifier=at),
                observation_block=observation_block,
            )
        )
        listed = self.listed_markets(observation_block=observation_block)
        reads.append("comptroller.getAllMarkets")

        oracle = Web3.to_checksum_address(
            self._read(
                lambda w3: self._comptroller(w3)
                .functions.oracle()
                .call(block_identifier=at),
                observation_block=observation_block,
            )
        )
        reads.append("comptroller.oracle")
        if entered:
            reads.extend(sorted(set(ROW_SOURCES.values())))

        rows = []
        for vtoken in entered:
            _, collateral_factor, _ = self._read(
                lambda w3, v=vtoken: self._comptroller(w3)
                .functions.markets(v)
                .call(block_identifier=at),
                observation_block=observation_block,
            )
            snapshot = self._read(
                lambda w3, v=vtoken: self._vtoken(w3, v)
                .functions.getAccountSnapshot(account)
                .call(block_identifier=at),
                observation_block=observation_block,
            )
            price = self._read(
                lambda w3, v=vtoken: w3.eth.contract(address=oracle, abi=ORACLE_ABI)
                .functions.getUnderlyingPrice(v)
                .call(block_identifier=at),
                observation_block=observation_block,
            )
            rows.append(
                MarketPosition(
                    vtoken=vtoken,
                    symbol=self._read(
                        lambda w3, v=vtoken: self._vtoken(w3, v)
                        .functions.symbol()
                        .call(block_identifier=at),
                        observation_block=observation_block,
                    ),
                    collateral_factor_mantissa=int(collateral_factor),
                    snapshot_error=int(snapshot[0]),
                    vtoken_balance=int(snapshot[1]),
                    borrow_balance=int(snapshot[2]),
                    exchange_rate_mantissa=int(snapshot[3]),
                    underlying_price_mantissa=int(price),
                    as_of_block=block,
                )
            )

        return AccountState(
            address=account,
            error_code=int(error),
            liquidity_usd=int(liquidity),
            shortfall_usd=int(shortfall),
            markets_listed=len(listed),
            rows=tuple(rows),
            oracle=oracle,
            as_of_block=block,
            reads=tuple(reads),
        )
