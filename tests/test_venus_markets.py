"""Venus reads, with no network anywhere in this file.

Three properties are asserted harder than the rest, because each one is a place a
lending reader gets quietly wrong.

**The native market is read, not dropped.** One of Venus's 52 markets — vBNB — has no
`underlying()` at all, and a reader that treats the empty return as an error loses a
market or, worse, reports an outage. The distinction between "the contract answered with
nothing" and "the node did not answer" is the whole of that test.

**Nothing here is called a health factor.** Venus publishes liquidity and shortfall in
USD and publishes no health factor at all. `AccountState` is asserted not to carry the
field, so the word cannot enter this layer by accident and has to be derived openly one
module up.

**Every figure names the call it came from.** A lending position is assembled out of four
different contracts' answers, and a row that does not say which call produced which
number is a row nobody can check against the chain.
"""

import pytest
from web3 import Web3

from types import SimpleNamespace

from docket.agents.pancake.positions import PrunedStateError
from docket.agents.venus.markets import (
    BSC_RPCS,
    ORACLE_ABI,
    ROW_SOURCES,
    UNITROLLER,
    AccountState,
    Market,
    MarketPosition,
    VenusReader,
)

VUSDT = Web3.to_checksum_address("0xfD5840Cd36d94D7229439859C0112a4185BC0255")
VUSDC = Web3.to_checksum_address("0xecA88125a5ADbe82614ffC12D0DB554E2e2867C8")
VBUSD = Web3.to_checksum_address("0x95c78222B3D6e262426483D42CfA53685A67Ab9D")
VBNB = Web3.to_checksum_address("0xA07c5b74C9B40447a954e1466938b865b6BBea36")
USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
USDC = Web3.to_checksum_address("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d")
BUSD = Web3.to_checksum_address("0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56")
ORACLE = Web3.to_checksum_address("0x6592b5DE802159F3E74B2486b091D11a8256ab8A")
HOLDER = Web3.to_checksum_address("0x429898ba0Fc5b9F1fF0a8f0BD1D6D3cB33B26DdD")
BLOCK = 115_173_763
E18 = 10**18

# The three market rows every fixture below is assembled from, transcribed from the live
# read on 2026-08-10: vToken decimals are 8, underlying decimals are 18 on BSC, the
# exchange rate is scaled 1e28 accordingly, and vBNB answers `underlying()` with nothing.
MARKETS = {
    VUSDC: {
        "symbol": "vUSDC",
        "decimals": 8,
        "underlying": USDC,
        "collateral_factor": 825 * 10**15,
        "exchange_rate": 266_027_524_223_233_974_720_539_463,
        "price": 999_838_650_000_000_000,
    },
    VUSDT: {
        "symbol": "vUSDT",
        "decimals": 8,
        "underlying": USDT,
        "collateral_factor": 800 * 10**15,
        "exchange_rate": 264_313_571_779_695_838_956_523_484,
        "price": 1_000_100_000_000_000_000,
    },
    VBUSD: {
        "symbol": "vBUSD",
        "decimals": 8,
        "underlying": BUSD,
        # Listed, and worth nothing as collateral. 26 of the 52 markets read this way on
        # 2026-08-10, so it is the ordinary case rather than the odd one.
        "collateral_factor": 0,
        "exchange_rate": 223_053_904_731_981_672_695_321_355,
        "price": 999_000_000_000_000_000,
    },
    VBNB: {
        "symbol": "vBNB",
        "decimals": 8,
        # The empty answer, not an exception: `eth_call` succeeds and returns no bytes.
        "underlying": b"",
        "collateral_factor": 800 * 10**15,
        "exchange_rate": 224_000_000_000_000_000_000_000_000,
        "price": 800 * E18,
    },
}


class _Call:
    def __init__(self, result):
        self._result = result

    def call(self, *a, **kw):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Functions:
    def __init__(self, handlers):
        self._handlers = handlers

    def __getattr__(self, name):
        handler = self._handlers.get(name)
        if handler is None:
            raise AssertionError(f"the reader called {name}, which this fixture does not stub")

        def fn(*args):
            return _Call(handler(*args))

        return fn


class _Eth:
    """A chain that answers only the calls this module is supposed to make."""

    def __init__(self, *, listed, positions, liquidity, assets_in, block=BLOCK):
        self.block_number = block
        self._listed = listed
        self._positions = positions
        self._liquidity = liquidity
        self._assets_in = assets_in
        self.calls: list[str] = []

    def contract(self, address=None, abi=None):
        if address == UNITROLLER:
            handlers = {
                "getAllMarkets": lambda: self._record("getAllMarkets", list(self._listed)),
                "markets": lambda v: self._record(
                    "markets",
                    [True, MARKETS[v]["collateral_factor"], True],
                ),
                "getAccountLiquidity": lambda a: self._record(
                    "getAccountLiquidity", list(self._liquidity)
                ),
                "getAssetsIn": lambda a: self._record("getAssetsIn", list(self._assets_in)),
                "oracle": lambda: self._record("oracle", ORACLE),
            }
        elif address == ORACLE:
            assert abi is ORACLE_ABI
            handlers = {
                "getUnderlyingPrice": lambda v: self._record(
                    "getUnderlyingPrice", MARKETS[v]["price"]
                )
            }
        else:
            row = MARKETS[address]
            handlers = {
                "symbol": lambda: self._record("symbol", row["symbol"]),
                "decimals": lambda: self._record("decimals", row["decimals"]),
                "getAccountSnapshot": lambda a: self._record(
                    "getAccountSnapshot",
                    list(self._positions.get(address, (0, 0, 0, row["exchange_rate"]))),
                ),
            }
        return type("C", (), {"functions": _Functions(handlers)})()

    def call(self, tx, block_identifier="latest"):
        """The raw `underlying()` probe. Returns bytes, and empty bytes is an answer.

        Takes a `block_identifier` because the real one does: every read carries the block
        it is asking about, and a fake that ignored it would let a pinned read silently
        answer from the head — the one failure the registered contract exists to catch.
        """
        self._record("underlying", None)
        value = MARKETS[Web3.to_checksum_address(tx["to"])]["underlying"]
        if value == b"":
            return b""
        return bytes(12) + bytes.fromhex(value[2:])

    def _record(self, name, value):
        self.calls.append(name)
        return value


class _Chain:
    def __init__(self, eth):
        self.eth = eth


def _reader(**kwargs) -> tuple[VenusReader, _Eth]:
    eth = _Eth(**kwargs)
    return VenusReader(rpc=lambda do: do(_Chain(eth))), eth


def _quiet(**overrides):
    fields = {
        "listed": (VUSDC, VUSDT, VBUSD, VBNB),
        "positions": {},
        "liquidity": (0, 0, 0),
        "assets_in": (),
    }
    fields.update(overrides)
    return _reader(**fields)


# ------------------------------------------------------------------------ markets


def test_every_listed_market_parses_with_its_collateral_factor():
    reader, _ = _quiet()
    markets = reader.markets()
    assert [m.vtoken for m in markets] == [VUSDC, VUSDT, VBUSD, VBNB]
    usdc = markets[0]
    assert isinstance(usdc, Market)
    assert usdc.symbol == "vUSDC"
    assert usdc.decimals == 8
    assert usdc.underlying == USDC
    assert usdc.collateral_factor_mantissa == 825 * 10**15
    assert usdc.as_of_block == BLOCK


def test_a_market_whose_collateral_factor_is_zero_is_reported_rather_than_hidden():
    """26 of Venus's 52 markets carried a zero collateral factor on 2026-08-10. A listed
    market nothing may be borrowed against is a real state, and dropping it would make the
    universe smaller than the one the comptroller itself iterates."""
    reader, _ = _quiet()
    busd = next(m for m in reader.markets() if m.vtoken == VBUSD)
    assert busd.is_listed is True
    assert busd.collateral_factor_mantissa == 0


def test_the_native_market_reads_as_native_instead_of_disappearing():
    """vBNB has no `underlying()`. The call succeeds and returns no bytes, which is the
    contract answering — not the node failing — and the two must not be blurred."""
    reader, _ = _quiet()
    bnb = next(m for m in reader.markets() if m.vtoken == VBNB)
    assert bnb.underlying is None
    assert "no underlying" in bnb.as_record()["underlying_note"].lower()


def test_a_bounded_market_read_announces_that_it_was_bounded():
    reader, _ = _quiet()
    assert [m.vtoken for m in reader.markets(limit=2)] == [VUSDC, VUSDT]


# ------------------------------------------------------------------------ accounts


def test_an_account_with_no_position_reads_zero_and_names_the_call_that_said_so():
    reader, _ = _quiet()
    state = reader.account(HOLDER)
    assert isinstance(state, AccountState)
    assert state.liquidity_usd == 0
    assert state.shortfall_usd == 0
    assert state.rows == ()
    assert state.as_of_block == BLOCK
    record = state.as_record()
    assert "comptroller.getAccountLiquidity" in record["reads"]
    assert "getAssetsIn" in record["note"]


def test_an_account_state_carries_no_field_called_health_factor():
    """Venus publishes liquidity and shortfall in USD and publishes no health factor.
    The word is reserved for a figure derived one module up, with its method stated."""
    assert "health_factor" not in AccountState.__dataclass_fields__
    assert "health_factor" not in MarketPosition.__dataclass_fields__
    reader, _ = _quiet()
    assert "health_factor" not in reader.account(HOLDER).as_record()


def test_venus_s_own_liquidity_and_shortfall_travel_verbatim():
    reader, _ = _quiet(liquidity=(0, 4_200 * E18, 0), assets_in=(VUSDT,))
    state = reader.account(HOLDER)
    assert state.liquidity_usd == 4_200 * E18
    assert state.shortfall_usd == 0
    assert state.error_code == 0
    assert state.as_record()["scale"].startswith("1e18")


def test_a_borrowing_account_carries_one_row_per_market_it_has_entered():
    reader, _ = _quiet(
        liquidity=(0, 0, 150 * E18),
        assets_in=(VUSDC, VUSDT),
        positions={
            VUSDC: (0, 400 * 10**8, 0, MARKETS[VUSDC]["exchange_rate"]),
            VUSDT: (0, 0, 900 * E18, MARKETS[VUSDT]["exchange_rate"]),
        },
    )
    state = reader.account(HOLDER)
    assert [row.vtoken for row in state.rows] == [VUSDC, VUSDT]
    supplied, borrowed = state.rows
    assert supplied.vtoken_balance == 400 * 10**8
    assert supplied.borrow_balance == 0
    assert borrowed.borrow_balance == 900 * E18
    assert borrowed.underlying_price_mantissa == MARKETS[VUSDT]["price"]
    assert state.shortfall_usd == 150 * E18


def test_every_row_names_the_call_each_of_its_figures_came_from_and_the_block():
    reader, _ = _quiet(assets_in=(VUSDT,), positions={VUSDT: (0, 10**8, 0, 10**28)})
    row = reader.account(HOLDER).rows[0].as_record()
    assert row["as_of_block"] == BLOCK
    assert row["sources"] == dict(ROW_SOURCES)
    for field in ROW_SOURCES:
        assert field in row, field


def test_the_universe_the_rows_were_drawn_from_is_stated_alongside_them():
    """Two of three markets entered is a different claim from two markets existing."""
    reader, _ = _quiet(assets_in=(VUSDT,), positions={VUSDT: (0, 10**8, 0, 10**28)})
    record = reader.account(HOLDER).as_record()
    assert record["markets_listed"] == 4
    assert record["markets_entered"] == 1


def test_a_snapshot_the_vtoken_refused_to_answer_is_carried_rather_than_read_as_zero():
    """`getAccountSnapshot` returns an error code first. A nonzero one means the balances
    beside it mean nothing, and reading them as a position would invent one."""
    reader, _ = _quiet(assets_in=(VUSDT,), positions={VUSDT: (9, 0, 0, 0)})
    state = reader.account(HOLDER)
    assert state.rows[0].snapshot_error == 9
    assert state.complete is False


def test_an_account_every_market_answered_for_is_marked_complete():
    reader, _ = _quiet(assets_in=(VUSDT,), positions={VUSDT: (0, 10**8, 0, 10**28)})
    assert reader.account(HOLDER).complete is True


def test_the_oracle_is_read_from_the_comptroller_rather_than_assumed():
    """Venus can point the comptroller at a different oracle. Reading the address rather
    than hardcoding it means a swapped oracle changes the answer instead of being missed."""
    reader, eth = _quiet(assets_in=(VUSDT,), positions={VUSDT: (0, 10**8, 0, 10**28)})
    state = reader.account(HOLDER)
    assert state.oracle == ORACLE
    assert "oracle" in eth.calls


# ------------------------------------------------------------------------ failover


def test_all_endpoints_failing_names_every_endpoint_that_was_tried():
    """A reader that says only "the chain is down" sends somebody to debug the wrong
    thing. The endpoints are named so the failure can be told apart from an outage."""
    urls = ("https://one.invalid", "https://two.invalid")

    def explode(url):
        raise ConnectionError(f"no route to {url}")

    reader = VenusReader(rpc_urls=urls, session_factory=explode)
    with pytest.raises(RuntimeError) as exc:
        reader.account(HOLDER)
    for url in urls:
        assert url in str(exc.value)


def test_the_reader_is_read_only_all_the_way_down():
    """No key, no signing, no transaction: every call this module makes is an eth_call or
    a block read, which is a stronger guarantee than a promise not to send one."""
    import inspect

    from docket.agents.venus import markets

    source = inspect.getsource(markets)
    for forbidden in ("send_raw_transaction", "sign_transaction", "private_key", "eth.account"):
        assert forbidden not in source, forbidden


# ------------------------------------------------------------- pinned reads


class _PinnedRpc:
    """A chain that records the block every read asked about.

    v3-09 records an answer about a different block as a blocked contract rather than a
    worse answer, so "which block did each call actually name" is the property under test —
    not whether the numbers came back.
    """

    def __init__(self, *, pruned=False):
        self.blocks = []
        self._pruned = pruned

    def __call__(self, do):
        outer = self

        class _Eth:
            block_number = 119_999_999

            def call(self, tx, block_identifier="latest"):
                outer._note(block_identifier)
                return b""

            def contract(self, address=None, abi=None):
                return _Contract()

        class _Contract:
            functions = None

            def __getattr__(self, name):
                raise AttributeError(name)

        return do(SimpleNamespace(eth=_Eth()))

    def _note(self, block_identifier):
        self.blocks.append(block_identifier)
        if self._pruned:
            raise ValueError("missing trie node 0xdead (path )")


def test_a_pinned_read_needs_an_archive_endpoint_and_says_so_when_there_is_none():
    """Answering from the head instead is the one failure the registered contract exists
    to catch, and it looks exactly like success."""
    reader = VenusReader(archive_rpc="")
    with pytest.raises(ValueError, match="observation_block_unsupported"):
        reader.account(HOLDER, observation_block=119_627_412)
    with pytest.raises(ValueError, match="DOCKET_ARCHIVE_RPC is not set"):
        reader.listed_markets(observation_block=119_627_412)


def test_a_pinned_read_puts_the_archive_endpoint_first():
    """The public dataseeds prune, so the order is the one `positions.py` uses: the
    archive, then the ordinary endpoints behind it."""
    reader = VenusReader(archive_rpc="https://archive.example")
    handle = reader._at(119_627_412)
    assert handle._urls[0] == "https://archive.example"
    assert tuple(handle._urls[1:]) == BSC_RPCS
    # A head read never reaches for it.
    assert reader._at(None) is reader._rpc


def test_an_environment_archive_endpoint_is_read_the_way_positions_reads_it(monkeypatch):
    monkeypatch.setenv("DOCKET_ARCHIVE_RPC", " https://env.example ")
    assert VenusReader().archive_rpc == "https://env.example"
    monkeypatch.delenv("DOCKET_ARCHIVE_RPC")
    assert VenusReader().archive_rpc == ""


def test_a_pinned_read_names_that_block_on_every_call_it_makes():
    rpc = _PinnedRpc()
    reader = VenusReader(rpc=rpc, archive_rpc="https://archive.example")
    reader.underlying_of(VUSDT, observation_block=119_627_412)
    assert rpc.blocks == [119_627_412]
    rpc.blocks.clear()
    reader.underlying_of(VUSDT)
    assert rpc.blocks == ["latest"]


def test_a_block_the_endpoints_no_longer_hold_is_a_stated_failure_not_an_empty_account():
    """A pruned node answers `missing trie node` rather than the state that was there.
    Reading that as "this account has nothing" would turn a gap in the infrastructure into
    a claim about somebody's position."""
    reader = VenusReader(
        rpc=_PinnedRpc(pruned=True), archive_rpc="https://archive.example"
    )
    with pytest.raises(PrunedStateError, match="block 119627412 is no longer held"):
        reader.underlying_of(VUSDT, observation_block=119_627_412)
    # A head read of the same failure is left as the ordinary error it is.
    with pytest.raises(ValueError, match="missing trie node"):
        reader.underlying_of(VUSDT)
