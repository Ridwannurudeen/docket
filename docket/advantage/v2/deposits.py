"""The same eleven days, read from the chain the account traded on rather than from its file.

The registered 06 record publishes no return. Its reason is a property of SOLVENT's receipt
chain: every receipt carries `equity_usd` and none carries a field recording money moving into
or out of the account, so in that series a deposit and a profit are the same arithmetic. 06's
falsifier covers the fields *inside* that corpus, so nothing here refutes it — an external
reconstruction is an addition beside it, and 06's claim and its falsifier are untouched.

What this adds is the term the chain was missing. Over the window exactly two external deposits
reached the wallet, both bare ERC-20 `transfer()` calls of Binance-Peg BSC-USD sent by
externally owned accounts, and the reconstruction found nothing transferred out. Subtract them
from the balance change and the account is **down 24.18 US dollars**. That is the finding, it is
adverse, and it is published as it came out.

Three things travel with it or it is dishonest.

**It is the wallet's return, not provably the agent's.** The wallet's transaction count advanced
by 113 over the window and the frozen chain names 37 distinct transaction hashes, so most of
what the key signed is not in the published record at all. A separate log sweep found 16 of 44
value-moving transactions absent from the chain's `executions`, including the two largest, and
that sweep is the repository owner's rather than this module's. Chain data cannot tell an
agent-engine trade from an operator trade signed with the same key, so no arithmetic available
here closes the gap. It belongs beside the headline, not under it.

**Gas is excluded and the true loss is larger.** `compute_equity` in SOLVENT's own engine sums
the balances of pinned BEP-20 tokens and skips every symbol absent from that pinned list, and
the native coin fees are paid in is not on it — so gas never entered the agent's series either.
It cannot be computed here: 113 transactions were sent and this corpus holds none of their
hashes — the two it does carry are the deposits, which other addresses sent. Every one of those
fees made the account smaller, so the loss below is a floor.

**The percentage depends on which denominator is meant, and one of them cannot be computed at
all.** Modified Dietz is mark-free over these readings — the opening basket holds no ETH and the
closing basket holds dust — so it is computed and published with both of its counts. A
time-weighted return is not: the second deposit lands while the account is most of the way into
ETH, and valuing that boundary needs a price this record did not observe. It is published as a
function of that mark over a registered grid, never as a point figure, and the spread across the
grid is the reason.

Nothing is signed and nothing is fetched while these figures are computed: the corpus was frozen
once, its digest is in the registration, and every reading below is a hex string a public
archive node returned.
"""

from datetime import UTC, datetime
from decimal import Decimal

from web3 import Web3

from .scoring import rate
from .solvent import key_paths, load_corpus

# Derived rather than transcribed, the way this repository's other selectors are. A deposit has
# to be both — the canonical event, and calldata that called nothing else — and the falsifier's
# first limb is what says so.
TRANSFER_EVENT_SIGNATURE = "Transfer(address,address,uint256)"
TRANSFER_SIGNATURE = "transfer(address,uint256)"
TRANSFER_TOPIC = "0x" + Web3.keccak(text=TRANSFER_EVENT_SIGNATURE).hex()
TRANSFER_SELECTOR = "0x" + Web3.keccak(text=TRANSFER_SIGNATURE)[:4].hex()
# Four bytes of selector and two 32-byte arguments, counted as hex characters with the 0x.
BARE_TRANSFER_INPUT_LENGTH = 2 + 8 + 64 + 64

# The two tokens this record values at one dollar. USDT and USDC on BSC are the account's own
# unit of account — SOLVENT's engine marks stables at `min(price, 1.0)` and never above — and
# both window boundaries are held in them alone, which is what makes the dollar figure exact
# without a price source. ETH is read at every boundary precisely because it is not pegged:
# where it is non-zero, a figure that needs it needs a mark, and this record says which figures
# those are rather than marking it quietly.
DOLLAR_PEGGED = ("USDT", "USDC")

# The ETH marks the time-weighted figure is evaluated at. A grid rather than an estimate: this
# record observed no price and does not pretend the one it did not observe sits near the middle
# of these. The span is wide on purpose, because what the table establishes is that a
# time-weighted return over this window is not determined by anything measured here.
ETH_MARK_GRID_USD = (1400, 1500, 1600, 1700, 1800)

# Leaf key names that would put the native coin, or a fee paid in it, inside the receipt chain's
# own series. The search is run over the same enumerated key paths 06 publishes rather than
# asserted, because the falsifier's fourth limb turns on its result.
GAS_KEY_WORDS = ("gas", "bnb", "native")

# The owner's sweep, cited and not reproduced. Its two named transactions are the sharpest
# statement about attribution available and neither is this module's measurement, so both the
# figures and their provenance are carried in one place rather than folded into prose.
OWNER_SWEEP = {
    "value_moving_transactions_found": 44,
    "absent_from_the_chains_executions": 16,
    "reproduced_by_this_module": False,
    "method": (
        "A full eth_getLogs sweep of the window's blocks whose per-token net flows were "
        "reconciled against the archive balanceOf deltas, run by the repository owner before "
        "this corpus was frozen. A public endpoint caps a getLogs range far below the span this "
        "window covers and no block-explorer key is configured in this repository, so the sweep "
        "is cited here and its reconciliation table is not restated as a measurement."
    ),
}
ABSENT_TRANSACTIONS = (
    {"prefix": "0x07f88b70", "moved": "951.40 USDT into 0.60125 ETH"},
    {"prefix": "0xe4fd127c", "moved": "0.72807 ETH into 1145.46 USDT"},
)

NOTICE = (
    "A deposit-adjusted result for one wallet on BSC over the same closed eleven-day window the "
    "registered 06 record covers, computed from archive balance readings and the two external "
    "deposits that reached the account. The result is a loss. It is the wallet's loss and not "
    "provably the agent's, and it excludes the gas of every transaction the wallet sent. It "
    "adds a figure beside 06 and refutes nothing in it: 06's funding limb is about the fields "
    "inside its own corpus, and this evidence is outside that corpus."
)

EXTERNAL_DEPOSIT_RULE = (
    "A transfer of value into the wallet whose transaction some other address sent: "
    "tx.from != the wallet. Both legs of every trade the account made are transactions the "
    "wallet itself sent, so no swap can enter this set however much value it moved. The rule "
    "was registered before any of these figures were computed, and it is a rule about who sent "
    "the transaction rather than a judgement about which of the wallet's own transactions "
    "looked like funding."
)

COMPLETENESS_STATEMENT = (
    "The deposit set is owner-attested and this module does not reproduce the sweep behind it. "
    "That exactly two external deposits reached the account and that nothing left it rests on "
    "that sweep, whose method is recorded beside this sentence. What this module does check is "
    "the part that needs no sweep: each deposit's own Transfer log equals the wallet's balance "
    "delta across the block containing it, which fixes those two amounts exactly and says "
    "nothing about whether a third exists. A third deposit or any withdrawal would move every "
    "figure here, and the falsifier's second limb is where it would show."
)

NO_TIME_WEIGHTED_POINT_FIGURE = (
    "No time-weighted return is published as a figure, and the reason is measured rather than "
    "asserted. Chain-linking needs the account valued at every flow, and at the second deposit "
    "most of the account's value sat in ETH — a token no balanceOf can price. This record "
    "observed no price source, so the time-weighted return is published as a function of that "
    "mark over a registered grid instead, and the grid's own spread is why: it is wider than "
    "the figure and it does not settle the sign. The deposit-adjusted dollar result and the "
    "Modified Dietz return need no mark at all, which is why those two are figures and this one "
    "is a table. A reader who has a mark can read the row; this record does not pick one for "
    "them."
)

DIETZ_CONVENTION = (
    "Weights are (closing block timestamp - flow block timestamp) / (closing block timestamp - "
    "opening block timestamp), in the seconds the blocks themselves carry. Calendar-day weights "
    "would move the denominator by under a dollar and the return by under a tenth of a "
    "percentage point; this record uses block seconds and says which rather than publishing a "
    "figure whose convention has to be guessed."
)

RESULT_METHOD = (
    "Closing stables minus opening stables minus the external deposits, every term read from an "
    "archive balanceOf at a pinned block and every token valued at the dollar it is pegged to. "
    "Two percentages follow from that one numerator and they answer different questions, so "
    "both are published: Modified Dietz divides by the capital weighted by how long the account "
    "held it, which is what a reader asking how the money did means, and the second divides by "
    "the opening balance and every dollar paid into it together, which is what a reader asking "
    "how much of the money the account ever held came back means. The first is the larger loss "
    "because most of the money arrived on the window's second-to-last day."
)


def _amount(word: str, decimals: int) -> Decimal:
    """A 32-byte hex word as a token amount. Exact: no float touches a balance here."""
    return Decimal(int(word, 16)) / (Decimal(10) ** decimals)


def _usd(value: Decimal) -> float:
    return round(float(value), 10)


def _topic_address(topic: str) -> str:
    return "0x" + topic[-40:]


def _seconds(timestamp: str) -> int:
    """One receipt's own ts as the whole second a block timestamp is counted in."""
    return int(datetime.fromisoformat(timestamp).timestamp())


def _stables(balances: dict) -> Decimal:
    return sum((balances[symbol] for symbol in DOLLAR_PEGGED), Decimal(0))


def deposit_checks(
    *,
    transaction: dict,
    receipt: dict,
    token_address: str,
    wallet: str,
    code: dict,
    delta: Decimal,
    decimals: int,
) -> dict:
    """Every property that makes one transaction a bare external deposit, checked separately.

    Reported one by one rather than as a verdict. A transaction that credited the wallet but
    called a contract, or carried a second log, or came from the wallet itself, is a different
    thing from a deposit and would fail exactly one of these — which is why the falsifier's
    first limb names the failing reading instead of reporting a share.
    """
    logs = receipt["logs"]
    log = logs[0] if len(logs) == 1 else None
    return {
        "succeeded": receipt["status"] == "0x1",
        "sent_no_native_value": transaction["value"] == "0x0",
        "called_the_token_contract": transaction["to"].lower() == token_address.lower(),
        "calldata_is_a_bare_transfer": transaction["input"].startswith(
            TRANSFER_SELECTOR
        )
        and len(transaction["input"]) == BARE_TRANSFER_INPUT_LENGTH,
        "emitted_exactly_one_log": len(logs) == 1,
        "log_is_a_canonical_transfer": log is not None
        and log["topics"][0] == TRANSFER_TOPIC
        and log["address"].lower() == token_address.lower(),
        "log_credited_the_wallet": log is not None
        and _topic_address(log["topics"][2]).lower() == wallet.lower(),
        "log_came_from_the_transaction_sender": log is not None
        and _topic_address(log["topics"][1]).lower() == transaction["from"].lower(),
        "sender_is_not_the_wallet": transaction["from"].lower() != wallet.lower(),
        "sender_is_an_externally_owned_account": code[transaction["from"].lower()]
        == "0x",
        "amount_equals_the_balance_delta_across_its_block": log is not None
        and _amount(log["data"], decimals) == delta,
        "block_number_agrees_with_the_receipt": transaction["blockNumber"]
        == receipt["blockNumber"],
    }


def external_deposits(
    flows: dict, balances: dict, decimals: dict, code: dict
) -> list[dict]:
    """The two deposits, decoded from the frozen transactions and their receipts.

    An external deposit is fixed by one rule and it is the rule registered before any of this
    was computed: `EXTERNAL_DEPOSIT_RULE`. Every check that rule implies is recomputed per
    deposit rather than taken from the corpus, including the one the corpus cannot state for
    itself — that the amount the Transfer log carries is the balance delta across its own block.
    """
    wallet = flows["agent"]["wallet"]
    token = flows["tokens"]["USDT"]
    decoded = []
    for position, deposit in zip(
        ("first", "second"), flows["results"]["deposit_transactions"], strict=True
    ):
        transaction = deposit["transaction"]
        log = deposit["receipt"]["logs"][0]
        delta = (
            balances[f"at_{position}_deposit"]["USDT"]
            - balances[f"before_{position}_deposit"]["USDT"]
        )
        checks = deposit_checks(
            transaction=transaction,
            receipt=deposit["receipt"],
            token_address=token["address"],
            wallet=wallet,
            code=code,
            delta=delta,
            decimals=decimals["USDT"],
        )
        decoded.append(
            {
                "tx_hash": deposit["tx_hash"],
                "position": position,
                "block_number": int(transaction["blockNumber"], 16),
                "sender": transaction["from"],
                "token": "USDT",
                "token_address": token["address"],
                "amount_usd": _usd(_amount(log["data"], decimals["USDT"])),
                "balance_delta_usd": _usd(delta),
                "checks": checks,
                "is_a_bare_external_deposit": all(checks.values()),
            }
        )
    return decoded


def count_the_balance_change(opening_usd: Decimal, closing_usd: Decimal) -> dict:
    """The first null: read the balance change as the result, which is what subtraction gives.

    It takes no view on where the money came from, which is exactly what makes it the ceiling
    the registered arm has to be measured under. The distance between the two is the deposits.
    """
    return {
        "result_usd": _usd(closing_usd - opening_usd),
        "opening_stables_usd": _usd(opening_usd),
        "closing_stables_usd": _usd(closing_usd),
    }


def hold_the_stables(opening_usd: Decimal, deposits_usd: Decimal) -> dict:
    """The second null: the same money, contributed at the same moments, never traded.

    Both window boundaries and both deposits are dollar-pegged tokens, so a portfolio that
    received them and did nothing closes at exactly what was put into it and its
    deposit-adjusted result is zero. It is the arm an execution record has to be measured
    against — the question is whether trading beat leaving the money alone — and it sends no
    transaction, which is the second direction the comparison runs in.
    """
    closing = opening_usd + deposits_usd
    return {
        "result_usd": _usd(closing - opening_usd - deposits_usd),
        "closing_stables_usd": _usd(closing),
        "transactions_sent": 0,
    }


def modified_dietz(
    *,
    opening_usd: Decimal,
    closing_usd: Decimal,
    flows: list,
    opened_at: int,
    closed_at: int,
) -> dict:
    """The one percentage this window supports without a price mark, with both its counts.

    Its numerator is the deposit-adjusted result and its denominator is the capital the account
    held weighted by how long it held it: each contribution counts for the fraction of the
    window still to run when it arrived. Mark-free here for a reason that is a property of these
    readings rather than of the method — the opening basket holds no ETH, the closing basket
    holds dust, and both flows are dollar-pegged — so nothing in it has to be priced.
    """
    span = Decimal(closed_at - opened_at)
    weighted = []
    denominator = opening_usd
    for timestamp, amount in flows:
        weight = Decimal(closed_at - timestamp) / span
        denominator += weight * amount
        weighted.append(
            {
                "block_timestamp": timestamp,
                "amount_usd": _usd(amount),
                "weight": round(float(weight), 10),
                "weighted_usd": _usd(weight * amount),
            }
        )
    contributed = sum((amount for _, amount in flows), Decimal(0))
    return {
        "return": rate(
            _usd(closing_usd - opening_usd - contributed), _usd(denominator)
        ),
        "average_capital_usd": _usd(denominator),
        "weighted_flows": weighted,
        "window_seconds": int(span),
        "convention": DIETZ_CONVENTION,
    }


def time_weighted_grid(sub_periods: list, marks=ETH_MARK_GRID_USD) -> dict:
    """The chain-linked return at each registered ETH mark, and never at one of them alone.

    Each sub-period runs from one flow to the next and its return is the account's closing value
    over its opening value; the window's return is their product less one. Every boundary but
    one is dollar-pegged and needs no mark. The one that is not is the second deposit, where the
    account held most of its value in ETH, and it enters twice — ending the sub-period before it
    and opening the one after — so a mark that is wrong moves the two in opposite directions
    over very different bases and does not cancel. That is why this is a table: the grid's own
    spread is the finding and no row is the answer.
    """
    rows = []
    for mark in marks:
        price = Decimal(mark)
        linked = Decimal(1)
        periods = []
        for period in sub_periods:
            opened = period["opening_stables_usd"] + period["opening_eth"] * price
            closed = period["closing_stables_usd"] + period["closing_eth"] * price
            sub_return = closed / opened - 1
            linked *= 1 + sub_return
            periods.append(
                {
                    "name": period["name"],
                    "opening_value_usd": _usd(opened),
                    "closing_value_usd": _usd(closed),
                    "opening_eth": _usd(period["opening_eth"]),
                    "closing_eth": _usd(period["closing_eth"]),
                    "sub_period_return": round(float(sub_return), 10),
                }
            )
        rows.append(
            {
                "eth_mark_usd": mark,
                "time_weighted_return": round(float(linked - 1), 10),
                "sub_periods": periods,
            }
        )
    values = [row["time_weighted_return"] for row in rows]
    return {
        "published_as_a_point_figure": False,
        "eth_marks_usd": list(marks),
        "rows": rows,
        "spread": {
            "lowest": min(values),
            "highest": max(values),
            "marks_span_usd": [min(marks), max(marks)],
            "crosses_zero": min(values) < 0 < max(values),
        },
        "statement": NO_TIME_WEIGHTED_POINT_FIGURE,
    }


def attribution(receipts: list, readings: dict) -> dict:
    """How much of what the key signed the published chain accounts for, counted here.

    The transaction count is the wallet's own and the hash set is the chain's own, so the gap
    between them is measured rather than taken from the owner's sweep. The sweep's finding
    travels beside it, attributed, because it is the sharper statement and it is not this
    module's. The gap is a floor in one direction only: a hash the chain asserts is not
    necessarily one of the transactions the wallet sent, and 06 records that 10 of the 37 name a
    transaction the chain never confirms.
    """
    hashes = set()
    for receipt in receipts:
        seal = receipt.get("execution_seal") or {}
        if seal.get("tx_hash"):
            hashes.add(seal["tx_hash"].lower())
        for execution in receipt.get("executions") or []:
            if execution.get("tx_hash"):
                hashes.add(execution["tx_hash"].lower())
    opened = int(readings["window_open"]["transaction_count"], 16)
    closed = int(readings["window_close"]["transaction_count"], 16)
    sent = closed - opened
    absent = [
        entry
        | {
            "matches_a_hash_the_chain_names": [
                value for value in sorted(hashes) if value.startswith(entry["prefix"])
            ]
        }
        for entry in ABSENT_TRANSACTIONS
    ]
    unnamed = rate(sent - len(hashes), sent)
    return {
        "transaction_count_at_the_opening_block": opened,
        "transaction_count_at_the_closing_block": closed,
        "transactions_the_wallet_sent": sent,
        "distinct_tx_hashes_the_chain_names": len(hashes),
        "wallet_transactions_the_chain_names_no_hash_for": unnamed,
        "the_two_largest_absent_transactions": absent,
        "owner_sweep": OWNER_SWEEP,
        "provably_the_agents": False,
        "statement": (
            f"This is the wallet's return and it is not provably the agent's. The wallet's "
            f"transaction count advanced from {opened} at the opening block to {closed} at the "
            f"closing block, so {sent} transactions were sent from the key over the window, "
            f"while the frozen receipt chain names {len(hashes)} distinct transaction hashes in "
            f"total — so at least {unnamed['numerator']} of the {sent} appear nowhere in the "
            "record the agent published. That is a floor rather than an exact count, because a "
            "hash the chain asserts need not be one the wallet sent: 06 records that 10 of "
            f"those {len(hashes)} name a transaction the chain never confirms. A separate "
            f"eth_getLogs sweep, run by the repository owner and not reproduced by this module, "
            f"identified {OWNER_SWEEP['value_moving_transactions_found']} wallet-initiated "
            f"value-moving transactions of which "
            f"{OWNER_SWEEP['absent_from_the_chains_executions']} are absent from the chain's "
            "executions, including the two largest: "
            + ", ".join(
                f"{entry['prefix']}..., which moved {entry['moved']}"
                for entry in ABSENT_TRANSACTIONS
            )
            + ". This module confirms from the registered chain that neither prefix matches any "
            "hash the chain asserts. Chain data cannot distinguish a trade the agent's engine "
            "signed from a trade an operator signed with the same key, so no arithmetic "
            "available here attributes this loss to the agent, and it is not described as the "
            "agent's anywhere in this record."
        ),
    }


def gas_and_recorded_costs(
    receipts: list, paths: list, *, sent: int, named_by_the_chain: int, pnl: Decimal
) -> dict:
    """Whether the receipt chain's own series could have carried the fees. It could not.

    Searched rather than asserted, over the same enumerated key paths 06 publishes: a leaf
    naming the native coin or a gas cost would mean the fees were inside the equity series after
    all, and the falsifier's fourth limb turns on exactly that. The data purchases are counted
    beside it because they are the one recorded cost the chain does carry, and where they
    settled from is a question this record leaves open rather than answers.
    """
    matches = [
        path
        for path in paths
        if any(word in path.rsplit(".", 1)[-1].casefold() for word in GAS_KEY_WORDS)
    ]
    purchases = [
        purchase
        for receipt in receipts
        for purchase in receipt.get("data_purchases") or []
    ]
    recorded = sum(Decimal(str(purchase["cost_usdc"])) for purchase in purchases)
    return {
        "words_searched": list(GAS_KEY_WORDS),
        "key_paths_matching": matches,
        "the_chain_could_have_carried_the_fees": bool(matches),
        "transactions_the_wallet_sent": sent,
        "wallet_transaction_hashes_on_this_record": 0,
        "wallet_transaction_hashes_the_chain_names": named_by_the_chain,
        "recorded_data_purchases": len(purchases),
        "recorded_data_purchase_cost_usdc": _usd(recorded),
        "result_if_every_recorded_purchase_left_this_wallet_usd": _usd(pnl + recorded),
        "statement": (
            "Gas is excluded and the true economic loss is larger by an amount this record "
            "cannot compute. SOLVENT's own compute_equity sums the balances of pinned BEP-20 "
            "tokens and skips every symbol absent from that pinned list, and the native coin "
            f"the fees are paid in is not on it, so gas never entered the equity series either. "
            f"{sent} transactions were sent from the wallet over the window and this record "
            "holds none of their hashes: the two transactions it does carry are the deposits, "
            "which other addresses sent, so they are not among those "
            f"{sent} and their fees were not paid by this account. The receipt chain names "
            f"{named_by_the_chain} of the {sent} and the owner's sweep identified "
            f"{OWNER_SWEEP['value_moving_transactions_found']} value-moving ones, and neither "
            "set travels with the fee each transaction paid — so the total is neither in the "
            "agent's series nor computable from this corpus. The omission runs one way: every "
            "one of those fees made the account smaller, so the deposit-adjusted loss is a "
            "floor and not an estimate. "
            f"Separately, the chain records {len(purchases)} data purchases costing "
            f"{_usd(recorded)} USDC in total. If any of that settled from this wallet on BSC it "
            "was an external transfer out, and the deposit-adjusted result would be smaller by "
            f"that much — {_usd(pnl + recorded)} US dollars rather than {_usd(pnl)} if the whole "
            "of it left this account. The owner's sweep reports no external transfer out and "
            "this module does not reproduce that sweep, so the tension is published rather than "
            "resolved. The result is a loss under either reading."
        ),
    }


def measure(flows: dict, chain: dict) -> dict:
    """Every published figure, recomputed from the two frozen corpora and from nothing else."""
    results = flows["results"]
    decimals = {
        symbol: int(word, 16) for symbol, word in results["token_decimals"].items()
    }
    readings = {
        reading["label"]: reading for reading in results["balance_and_nonce_readings"]
    }
    code = {
        address.lower(): value for address, value in results["code_at_address"].items()
    }
    receipts = [envelope["receipt"] for envelope in chain["receipts"]]
    balances = {
        label: {
            symbol: _amount(word, decimals[symbol])
            for symbol, word in reading["balance_of"].items()
        }
        for label, reading in readings.items()
    }

    opening = _stables(balances["window_open"])
    closing = _stables(balances["window_close"])
    deposits = external_deposits(flows, balances, decimals, code)
    contributed = sum(
        (Decimal(str(deposit["amount_usd"])) for deposit in deposits), Decimal(0)
    )
    pnl = closing - opening - contributed
    opened_at = int(readings["window_open"]["block_timestamp"], 16)
    closed_at = int(readings["window_close"]["block_timestamp"], 16)

    dietz = modified_dietz(
        opening_usd=opening,
        closing_usd=closing,
        flows=[
            (
                int(
                    readings[f"at_{deposit['position']}_deposit"]["block_timestamp"], 16
                ),
                Decimal(str(deposit["amount_usd"])),
            )
            for deposit in deposits
        ],
        opened_at=opened_at,
        closed_at=closed_at,
    )
    grid = time_weighted_grid(
        [
            {
                "name": "the opening to the first deposit",
                "opening_stables_usd": opening,
                "opening_eth": balances["window_open"]["ETH"],
                "closing_stables_usd": _stables(balances["before_first_deposit"]),
                "closing_eth": balances["before_first_deposit"]["ETH"],
            },
            {
                "name": "the first deposit to the second",
                "opening_stables_usd": _stables(balances["at_first_deposit"]),
                "opening_eth": balances["at_first_deposit"]["ETH"],
                "closing_stables_usd": _stables(balances["before_second_deposit"]),
                "closing_eth": balances["before_second_deposit"]["ETH"],
            },
            {
                "name": "the second deposit to the close",
                "opening_stables_usd": _stables(balances["at_second_deposit"]),
                "opening_eth": balances["at_second_deposit"]["ETH"],
                "closing_stables_usd": closing,
                "closing_eth": balances["window_close"]["ETH"],
            },
        ]
    )
    attributed = attribution(receipts, readings)

    adjacent = [
        {
            "block_number": reading["block_number"],
            "block_timestamp": int(reading["block_timestamp"], 16),
            "stables_usd": _usd(
                sum(
                    (
                        _amount(reading["balance_of"][symbol], decimals[symbol])
                        for symbol in DOLLAR_PEGGED
                    ),
                    Decimal(0),
                )
            ),
        }
        for reading in results["adjacent_block_readings"]
    ]
    boundaries = {_usd(opening), _usd(closing)}
    return {
        "window": flows["window"]
        | {
            "opening_block_timestamp": opened_at,
            "closing_block_timestamp": closed_at,
            "opening_block_is_the_first_receipts_own_second": opened_at
            == _seconds(chain["window"]["first_receipt_ts"]),
            "closing_block_is_the_last_receipts_own_second": closed_at
            == _seconds(chain["window"]["last_receipt_ts"]),
        },
        "evidence": {
            "endpoint": flows["endpoint"],
            "fetched_at": flows["fetched_at"],
            "readings_sha256": flows["readings_sha256"],
            "token_decimals": decimals,
            "wallet_is_an_externally_owned_account": code[
                flows["agent"]["wallet"].lower()
            ]
            == "0x",
            "balance_readings": [
                {
                    "label": label,
                    "block_number": readings[label]["block_number"],
                    "block_timestamp": int(readings[label]["block_timestamp"], 16),
                    "transaction_count": int(readings[label]["transaction_count"], 16),
                    "usdt": _usd(balances[label]["USDT"]),
                    "usdc": _usd(balances[label]["USDC"]),
                    "eth": _usd(balances[label]["ETH"]),
                    "stables_usd": _usd(_stables(balances[label])),
                }
                for label in balances
            ],
            "adjacent_block_readings": adjacent,
            "boundary_blocks_are_insensitive_to_the_neighbouring_block": all(
                reading["stables_usd"] in boundaries for reading in adjacent
            ),
            "block_choice": flows["block_choice"],
        },
        "flows": {
            "deposits": deposits,
            "n_deposits": len(deposits),
            "external_deposits_usd": _usd(contributed),
            "external_withdrawals_usd": 0.0,
            "every_deposit_is_a_bare_external_transfer": all(
                deposit["is_a_bare_external_deposit"] for deposit in deposits
            ),
            "what_counts_as_an_external_deposit": EXTERNAL_DEPOSIT_RULE,
            "completeness": COMPLETENESS_STATEMENT,
        },
        "result": {
            "opening_stables_usd": _usd(opening),
            "closing_stables_usd": _usd(closing),
            "balance_change_usd": _usd(closing - opening),
            "external_deposits_usd": _usd(contributed),
            "deposit_adjusted_pnl_usd": _usd(pnl),
            "is_a_loss": pnl < 0,
            "modified_dietz": dietz,
            "over_the_opening_balance_and_the_deposits": rate(
                _usd(pnl), _usd(opening + contributed)
            ),
            "units": "US dollars, each dollar-pegged token valued at the dollar it is pegged to",
            "method": RESULT_METHOD,
        },
        "time_weighted": grid,
        "attribution": attributed,
        "gas": gas_and_recorded_costs(
            receipts,
            key_paths(receipts),
            sent=attributed["transactions_the_wallet_sent"],
            named_by_the_chain=attributed["distinct_tx_hashes_the_chain_names"],
            pnl=pnl,
        ),
        "nulls": {
            "count_the_balance_change_as_the_result": count_the_balance_change(
                opening, closing
            ),
            "hold_the_stables": hold_the_stables(opening, contributed),
        },
    }


def build_run_record(
    spec, flows: dict, measured: dict, *, started_at, finished_at
) -> dict:
    """The committed run record: the measured figures and the sentences that qualify them."""
    result = measured["result"]
    dietz = result["modified_dietz"]["return"]
    contributed = result["over_the_opening_balance_and_the_deposits"]
    attributed = measured["attribution"]
    spread = measured["time_weighted"]["spread"]
    nulls = measured["nulls"]
    return {
        "spec_id": spec.spec_id,
        "spec_hash": spec.spec_hash,
        "corpus_id": flows["corpus_id"],
        "dataset_ref": spec.dataset_ref,
        "dataset_sha256": spec.dataset_sha256,
        "receipt_chain_ref": flows["window"]["receipt_chain_ref"],
        "endpoint": flows["endpoint"],
        "readings_sha256": flows["readings_sha256"],
        "fetched_at": flows["fetched_at"],
        "started_at": started_at,
        "finished_at": finished_at,
        "n_planned": spec.n_planned,
        "notice": NOTICE,
        "cross_reference": {
            "experiment_id": "06-solvent-record",
            "refutes_06": False,
            "statement": (
                "06 registered that no receipt in its corpus carries a field recording money "
                "moving into or out of the account, and that limb is about the fields inside "
                "that corpus. This evidence is outside it: it is a wallet's transactions on "
                "BSC, not a field on a receipt. So 06 is not refuted, its claim and its "
                "falsifier are unchanged and were not edited for this, and this record is an "
                "addition beside it rather than a correction of it. What it supplies is the "
                "term 06 said was missing, and 06's own record points at this one for it."
            ),
        },
        "arms": {
            "registered": (
                "closing stables minus opening stables minus the external deposits, over the "
                "same closed window"
            ),
            "count_the_balance_change_as_the_result": (
                "the balance change alone, taking no view on where the money came from"
            ),
            "hold_the_stables": (
                "the same contributions at the same moments, never traded and sending no "
                "transaction"
            ),
        },
        "method": (
            NOTICE
            + " Every figure is recomputed from the two registered corpora and from nothing "
            "else: the chain readings were fetched once at the recorded fetched_at, the digest "
            "over the node's own answers is on this record, and no network call and no chain "
            "read was made while these figures were computed. Nothing was signed and no "
            "transaction of any kind was made at any point. An external deposit is fixed by the "
            "registered rule — a transfer of value into the wallet sent by some other address — "
            "so both legs of every trade the account made are excluded by construction rather "
            "than by judgement, and every property that rule implies is rechecked per deposit "
            "against the frozen transaction rather than read off it. Both boundary baskets are "
            "dollar-pegged tokens, so the dollar result and the Modified Dietz return need no "
            "price mark; the time-weighted return does, because the second deposit lands while "
            "the account is mostly in ETH, and it is published as a table over a registered "
            "grid of marks rather than as a figure. The naive quotient of the last equity "
            "reading over the first is never computed here and 06 holds the reason. Two things "
            "this record states rather than measures, both of them limits on it: the deposit "
            "set is owner-attested from a log sweep this module does not reproduce, and the "
            "split between agent-signed and operator-signed transactions cannot be made from "
            "chain data at all."
        ),
        "finding": (
            f"Over the same closed window the registered 06 record covers, "
            f"{measured['flows']['n_deposits']} external deposits reached SOLVENT's wallet on "
            f"BSC, totalling {result['external_deposits_usd']:,.6f} US dollars, and the sweep "
            f"behind this record found nothing transferred out. The account's stable balance "
            f"rose from {result['opening_stables_usd']:,.6f} to "
            f"{result['closing_stables_usd']:,.6f} US dollars, a change of "
            f"{result['balance_change_usd']:,.6f} — so once the deposits are subtracted the "
            f"result is a LOSS of {abs(result['deposit_adjusted_pnl_usd']):,.6f} US dollars. "
            f"That is {dietz['value'] * 100:.2f}% of the "
            f"{dietz['denominator']:,.2f} US dollars of capital the account held weighted by "
            f"how long it held it, and {contributed['value'] * 100:.2f}% of the "
            f"{contributed['denominator']:,.2f} US dollars the account opened with and "
            "received together. Doing nothing with the "
            f"same contributions returns exactly "
            f"{nulls['hold_the_stables']['result_usd']:,.2f}, so the whole of the loss is the "
            "distance from leaving the money alone; reading the balance change as the result "
            f"gives {nulls['count_the_balance_change_as_the_result']['result_usd']:,.2f} US "
            "dollars and is wrong by exactly what was paid in. Two things this figure is not. "
            "It is the wallet's return and not provably the agent's: the wallet sent "
            f"{attributed['transactions_the_wallet_sent']} transactions over the window while "
            f"the chain names {attributed['distinct_tx_hashes_the_chain_names']} distinct "
            f"hashes, so at least "
            f"{attributed['wallet_transactions_the_chain_names_no_hash_for']['numerator']} of "
            "them appear nowhere in the published record, and chain data cannot separate a "
            "trade the agent's engine signed from one an operator signed with the same key. And "
            "it excludes gas: those transactions were paid for in a native coin the agent's own "
            "equity function never counts, this record holds none of their hashes — the two it "
            "carries are the deposits, which other addresses sent — and every one of those fees "
            "made the account smaller, so the loss is a floor. No "
            "time-weighted return is published as a figure: across the registered marks it runs "
            f"from {spread['lowest'] * 100:.2f}% to {spread['highest'] * 100:.2f}%, a spread "
            "wider than the figure, because the second deposit lands while the account is "
            "mostly in a token this record did not price."
        ),
        **measured,
    }


if __name__ == "__main__":
    # `python -m docket.advantage.v2.deposits` is what produced the committed record. The two
    # stamps bracket arithmetic and nothing else: both corpora were frozen before the
    # registration was written, and everything between them reads those two files.
    from pathlib import Path

    from .replay import save_run
    from .spec import load

    root = Path(__file__).resolve().parents[3]
    registration = load(
        root / "docket/advantage/v2/specs/07-solvent-deposit-adjusted.json"
    )
    started = datetime.now(UTC).isoformat(timespec="seconds")
    frozen = load_corpus(root / registration.dataset_ref)
    receipt_chain = load_corpus(
        root / "docket/advantage/v2/corpus/trading/solvent-receipts.json"
    )
    record = build_run_record(
        registration,
        frozen,
        measure(frozen, receipt_chain),
        started_at=started,
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    save_run(record, root / "docket/advantage/v2/runs/07-solvent-deposit-adjusted.json")
    print(record["finding"])
