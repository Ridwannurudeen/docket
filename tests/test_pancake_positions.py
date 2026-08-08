"""Bounded and selective reading, checked by counting the calls it makes.

The point of `limit` is that the work stops, not that the list is short, so
these tests assert the call log rather than only the returned length. A version
that enumerated everything and sliced afterwards would pass a length assertion
and still take the five minutes the argument exists to avoid.

The injected-Web3 seam is the one `PositionReader` already documents: a supplied
`w3` is used as given, with no failover, so the fake below never touches a
network.
"""

from docket.agents.pancake.positions import MASTER_CHEF_V3, NPM, PositionReader

WALLET = "0x451871A1753903FB8fdd64a6B838E95aB8D5B80f"
BLOCK = 114746894
# token id -> liquidity. Two open, two closed, interleaved so a limit cannot
# accidentally land on a clean split.
HOLDINGS = {NPM: (7098969, 7087132, 6000001), MASTER_CHEF_V3: (5000002,)}
LIQUIDITY = {7098969: 659954198098656185285999, 7087132: 0, 6000001: 0, 5000002: 12345}


def _raw(token_id: int) -> list:
    """A `positions()` tuple: 12 fields, only the ones this module reads are real."""
    return [
        0,
        "0x0000000000000000000000000000000000000000",
        "0x205812CdBed920aFf76C6580abD681a46D11efc7",
        "0x55d398326f99059fF775485246999027B3197955",
        100,
        65811,
        65820,
        LIQUIDITY[token_id],
        0,
        0,
        0,
        0,
    ]


class _Call:
    def __init__(self, log, entry, result):
        self._log, self._entry, self._result = log, entry, result

    def call(self):
        self._log.append(self._entry)
        return self._result


class _Functions:
    def __init__(self, address, log):
        self._address, self._log = address, log

    def balanceOf(self, owner):
        return _Call(self._log, ("balanceOf", self._address), len(HOLDINGS[self._address]))

    def tokenOfOwnerByIndex(self, owner, index):
        return _Call(
            self._log,
            ("tokenOfOwnerByIndex", self._address, index),
            HOLDINGS[self._address][index],
        )

    def positions(self, token_id):
        return _Call(self._log, ("positions", token_id), _raw(token_id))


class _Contract:
    def __init__(self, address, log):
        self.functions = _Functions(address, log)


class _Eth:
    def __init__(self, log):
        self._log = log
        self.block_number = BLOCK

    def contract(self, address, abi):
        return _Contract(address, self._log)


class _FakeW3:
    def __init__(self, log):
        self.eth = _Eth(log)


def _reader() -> tuple[PositionReader, list]:
    log: list = []
    return PositionReader(w3=_FakeW3(log)), log


def test_closed_positions_are_skipped_but_stay_countable():
    reader, log = _reader()
    read = reader.wallet_positions(WALLET)

    assert [p["token_id"] for p in read["positions"]] == [7098969, 5000002]
    assert read["positions_held"] == 4
    assert read["positions_examined"] == 4
    # The two zero-liquidity ones are absent from the list and present in the count.
    assert read["closed_skipped"] == 2
    assert log.count(("positions", 7087132)) == 1


def test_include_closed_returns_every_position_and_skips_none():
    reader, _ = _reader()
    read = reader.wallet_positions(WALLET, include_closed=True)

    assert [p["token_id"] for p in read["positions"]] == [7098969, 7087132, 6000001, 5000002]
    assert read["closed_skipped"] == 0
    assert read["positions_examined"] == 4


def test_limit_stops_the_enumeration_rather_than_truncating_the_result():
    reader, log = _reader()
    read = reader.wallet_positions(WALLET, limit=2)

    enumerated = [e for e in log if e[0] == "tokenOfOwnerByIndex"]
    fetched = [e for e in log if e[0] == "positions"]
    # Two ids, two position reads: the work stopped, it was not done and discarded.
    assert len(enumerated) == 2 and len(fetched) == 2
    # The limit was reached inside the NPM holdings, so the farm was never enumerated.
    assert all(e[1] == NPM for e in enumerated)
    assert read["positions_examined"] == 2
    assert [p["token_id"] for p in read["positions"]] == [7098969]
    assert read["closed_skipped"] == 1


def test_the_wallet_total_is_read_even_when_the_limit_cuts_the_enumeration_short():
    """A bounded read must still be able to say what it did not look at."""
    reader, log = _reader()
    read = reader.wallet_positions(WALLET, limit=1)

    assert read["positions_held"] == 4
    assert read["positions_examined"] == 1
    # Both holders are still counted — that is two cheap calls, not an enumeration.
    assert [e[1] for e in log if e[0] == "balanceOf"] == [NPM, MASTER_CHEF_V3]


def test_a_limit_beyond_the_holdings_reads_everything_once():
    reader, log = _reader()
    read = reader.wallet_positions(WALLET, limit=99, include_closed=True)

    assert read["positions_examined"] == 4
    assert len([e for e in log if e[0] == "tokenOfOwnerByIndex"]) == 4
