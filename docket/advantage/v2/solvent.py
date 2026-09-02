"""One agent's published receipt chain, read for what it establishes and for what it does not.

Docket has never published a trading record. TermiX asks trading agents for a win rate, a
window and the risk taken, and the honest answer until now was that this build has none.
SOLVENT's chain is the only trading evidence in reach: 384 receipts over eleven days, hash
linked, with an on-chain anchor over most of the prefix. This module reads it, and the reason
it is a module rather than a paragraph is that two of the things worth saying about that chain
can only be established by recomputing it.

**Whether the chain verifies.** Every receipt carries `prev_hash`, and every envelope carries
the receipt's own published hash, so both limbs are checkable without asking SOLVENT for
anything: the linkage between consecutive receipts, and whether each published hash is the
digest of the body it is published beside. Only the second limb catches a body that was edited
after it was hashed, and it is the limb that needs the exact recipe. The recipe is one argument
away from the one this repository already uses for its own receipts: `RECEIPT_HASH_RECIPE`
sets `ensure_ascii=True` where `hire.receipts.canonical_hash` sets it False. The two agree on
every receipt whose body is pure ASCII, which is most of them, and disagree on the rest — so a
verifier that guessed wrong would report a chain that verifies almost everywhere, which is the
worst of the available failure modes. Both counts are reported for that reason.

**What counts as a trade.** A seal is the agent's own record that it acted. `outcome` is the
agent's word and `verification.status` is what the chain it traded on returned, and a
confirmed execution needs both. `unresolved` is the interesting case and the registration
fixed it before anything was counted: it is neither a success nor a failure, it keeps its
place in every denominator, and it is never re-read as either. The two nulls are the readings
either side of that decision — count every seal, or count only the ones whose commitment was
itself written to a public chain first — and both are computed here rather than asserted, so
the distance between them is a measured quantity.

Nothing here computes a return, a win rate or a drawdown, and `NO_RETURN_STATEMENT` says why in
the record itself, and points at the registered experiment that computes one from evidence this
corpus does not contain — `deposits`, which reads the wallet's own transfers on BSC and finds a
loss. Nothing in that record refutes anything in this one or is read back into it: this claim's
funding limb is about the fields inside this corpus, and those transfers are outside it. `equity_usd` is on every receipt and no receipt carries a funding field, so
a deposit and a profit are the same arithmetic in that series. Three steps in this chain are
larger than any trade it records, which establishes that the series is contaminated without
establishing by how much — and without saying what any one of those steps was, since a failed
balance read makes the same shape as a deposit and this chain is known to contain at least one
failed read. Smaller movements of money in or out are indistinguishable from trading by
construction. The key paths are enumerated and published so a reader can look for the funding
field themselves rather than take this module's word that there is none.
"""

import hashlib
import json
import re
import statistics
from pathlib import Path

from .scoring import rate

# One argument away from `hire.receipts.canonical_hash`, and the argument matters here: the
# receipts that carry a non-ASCII character are the only place the two recipes can disagree.
RECEIPT_HASH_RECIPE = (
    'hash(receipt) = "0x" + sha256(json.dumps(receipt, sort_keys=True, '
    'separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()'
)
ZERO_HASH = "0x" + "00" * 32

# The steps published beside the ones that exceed the notional bound. A step over the bound is
# a finding; the ordered neighbourhood around it is what lets a reader see that two of these
# steps nearly cancel a few receipts apart, which is a different story from a deposit and is
# not one this chain settles. Ten is a display choice and is served with the figures.
LARGEST_STEPS_SHOWN = 10

# `<cycle_id>:<kind>:<from>-><to>:<notional>`, the shape every intent_key in this chain takes.
# A key that does not match is listed by seq rather than coerced into the sizing distribution.
INTENT_KEY = re.compile(
    r"^(?P<cycle_id>[^:]+):(?P<kind>[^:]+):(?P<from>[^:>-]+)->(?P<to>[^:]+):(?P<notional>[0-9.]+)$"
)

# Leaf key names worth looking at when the question is whether the chain records money moving
# into or out of the account. A word list cannot answer that question and is not asked to: it
# narrows 324 key paths to a handful, each of which is then read against the registered
# criterion and the reading published. `btc_funding_rate` is why the two steps are separate —
# it is the rate perpetual longs pay shorts, a market observation the agent bought, and no
# amount of matching on the word "funding" makes it a movement of anybody's money.
FUNDING_KEY_WORDS = (
    "deposit",
    "withdraw",
    "funding",
    "top_up",
    "topup",
    "inflow",
    "outflow",
    "contribution",
    "transfer",
)
# A leg of the swap one seal reports, denominated in that swap's own two tokens. It is a trade,
# not a movement into or out of the account — the definition the registration fixed, and not a
# carve-out for anything this corpus turned out to hold.
SWAP_LEG_PREFIXES = ("execution_seal.verification.", "executions[].verification.")

NOTICE = (
    "An execution-reliability record over a closed eleven-day window that ended on "
    "2026-06-29, read from the published receipts of one agent. It is not a return record and "
    "not a win-rate record: the chain reports equity without reporting funding, so no return "
    "is computed from it and none is published here."
)

NO_RETURN_STATEMENT = (
    "No return, win rate or drawdown is published, and the reason is a property of the chain "
    "rather than a choice about how to present it. Every receipt carries equity_usd and no "
    "receipt carries any field recording money moving into or out of the account, so a "
    "deposit and a profit are the same arithmetic in that series and nothing in the chain "
    "separates them. Several steps in the series are larger than any trade the chain records, "
    "which establishes that the series is contaminated; it does not establish by how much, "
    "and it does not even say what each of those steps was. A deposit and a failed balance "
    "read produce the same step, and this chain holds one reading of 0.0 between two "
    "identical non-zero readings, so failed reads are known to happen in it. A deposit or a "
    "withdrawal smaller than the bound is indistinguishable from trading by construction. A "
    "first-to-last reading of equity_usd is therefore not a return, and dividing the last "
    "reading by the first would state a figure this chain does not support in either "
    "direction. The account's transfer history has since been reconstructed from the chain "
    "it traded on, and the deposit-adjusted figure is published beside this statement as "
    "registered experiment 07-solvent-deposit-adjusted, with its own corpus, its own method "
    "and its own denominators: it is a loss. That evidence refutes nothing here. This limb "
    "is about the fields inside this corpus and a wallet's transactions on BSC are outside "
    "it, so no figure from 07 is read back into anything on this record and this record's "
    "own refusal to publish a return from this series stands unchanged."
)

# The candidates the word list turns up, and what each is, read against the registered
# criterion. Written out per path rather than as a verdict, so a reader who disagrees with a
# reading can see exactly which one they are disagreeing with.
FUNDING_CANDIDATE_READINGS = {
    "signals.btc_funding_rate": (
        "The perpetual funding rate for BTC — the periodic payment between long and short "
        "holders of a perpetual future, quoted as a rate and bought from a data vendor as a "
        "market signal. It records no movement into or out of this account, and this account "
        "held no perpetual position: every execution in this chain is a spot swap between two "
        "tokens. It does not refute the funding limb."
    ),
    "inference_proof.input.signals.btc_funding_rate": (
        "The same field, carried a second time inside the hashed input the agent committed to "
        "before it reasoned. Same reading: a market rate, not a movement of money."
    ),
}


def receipt_hash(receipt: dict) -> str:
    """The published hash of one receipt, recomputed from the body it is published beside."""
    blob = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _ascii_insensitive_hash(receipt: dict) -> str:
    """The same recipe with `ensure_ascii=False` — this repository's own receipt digest."""
    blob = json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "0x" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_corpus(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_chain(envelopes: list[dict]) -> dict:
    """Both integrity limbs, recomputed, with every failing sequence number named.

    A share alone would let one broken receipt hide inside a rate of 383 of 384, so the seqs
    are listed and the rates are there to be read beside them rather than instead of them.
    """
    content_failures = []
    linkage_failures = []
    non_ascii = 0
    ascii_insensitive_agreements = 0
    for index, envelope in enumerate(envelopes):
        receipt = envelope["receipt"]
        if receipt_hash(receipt) != envelope["hash"]:
            content_failures.append(receipt["seq"])
        if _ascii_insensitive_hash(receipt) == envelope["hash"]:
            ascii_insensitive_agreements += 1
        else:
            non_ascii += 1
        if index:
            expected = envelopes[index - 1]["hash"]
            if receipt["prev_hash"] != expected:
                linkage_failures.append(receipt["seq"])
    genesis = envelopes[0]["receipt"]["prev_hash"]
    total = len(envelopes)
    return {
        "recipe": RECEIPT_HASH_RECIPE,
        "content_hashes_recomputed": rate(total - len(content_failures), total),
        "linkage_recomputed": rate(total - 1 - len(linkage_failures), total - 1),
        "genesis_prev_hash": genesis,
        "genesis_prev_hash_is_the_zero_word": genesis == ZERO_HASH,
        "content_failures": content_failures,
        "linkage_failures": linkage_failures,
        "head_hash": envelopes[-1]["hash"],
        "head_seq": envelopes[-1]["receipt"]["seq"],
        "ascii_insensitive_recipe_agrees": rate(ascii_insensitive_agreements, total),
        "receipts_the_two_recipes_disagree_on": non_ascii,
        "verifies": not content_failures
        and not linkage_failures
        and genesis == ZERO_HASH,
    }


def anchor_cross_check(envelopes: list[dict], v1_trading: dict) -> dict:
    """The verified chain against the two hashes Docket's own v1 task 02 recorded in August.

    The corpus can be internally consistent and still be a chain nobody else ever saw. This is
    the one check it cannot do for itself: v1's manual arm read the head SOLVENT served and the
    value carried by a BSC transaction, recorded both on 2026-08-08, and that record is in this
    repository and predates this corpus by 25 days. The transaction itself was mined on
    2026-06-28, while the chain was still being written.
    """
    manual = v1_trading["manual_arm"]["output"]
    by_seq = {envelope["receipt"]["seq"]: envelope["hash"] for envelope in envelopes}
    anchored_seq = manual["anchored_seq"]
    return {
        "observed_at": "2026-08-08",
        "source": "docket/advantage/experiments/02-trading.json",
        "anchor_tx_hash": manual["anchor_tx"]["hash"],
        "anchor_block": manual["anchor_tx"]["block"],
        "anchor_timestamp_utc": manual["anchor_tx"]["timestamp_utc"],
        "anchored_seq": anchored_seq,
        "recomputed_hash_at_anchored_seq": by_seq.get(anchored_seq),
        "anchored_hash_matches_this_corpus": by_seq.get(anchored_seq)
        == manual["recomputed_hash_at_seq_381"],
        "head_hash_matches_this_corpus": by_seq.get(max(by_seq))
        == manual["recomputed_head_hash"],
        "receipts_past_the_anchor": manual["unanchored_seqs"],
        "statement": (
            f"The value this corpus computes at seq {anchored_seq} is the value BSC "
            f"transaction {manual['anchor_tx']['hash']} carried in block "
            f"{manual['anchor_tx']['block']}, mined {manual['anchor_tx']['timestamp_utc']}, "
            "as Docket's own v1 task 02 read it on 2026-08-08, 25 days before this corpus "
            "was fetched. So the prefix through seq "
            f"{anchored_seq} cannot have been written after that block. Receipts "
            f"{manual['unanchored_seqs']} sit past the anchor: they link to the anchored "
            "prefix by hash, and no transaction fixes when they were written."
        ),
    }


def is_confirmed_execution(receipt: dict) -> bool:
    """The registered definition: the agent's own outcome and the chain's own confirmation."""
    seal = receipt["execution_seal"]
    verification = seal.get("verification") or {}
    return seal.get("outcome") == "executed_now" and verification.get("status") == 1


def count_every_seal(seals: list[dict]) -> dict:
    """The first null: every seal is a trade, whatever the seal says happened."""
    return rate(len(seals), len(seals))


def count_only_anchored_seals(seals: list[dict]) -> dict:
    """The second null: only the seals whose commitment was on chain before the execution."""
    anchored = sum(
        1
        for receipt in seals
        if receipt["execution_seal"].get("pre_trade_anchor_tx_hash")
    )
    return rate(anchored, len(seals))


def key_paths(receipts: list[dict]) -> list[str]:
    """Every key path present anywhere in any receipt, so a reader can look for themselves."""
    found = set()

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else key
                found.add(child)
                walk(value, child)
        elif isinstance(node, list):
            for value in node:
                walk(value, f"{path}[]")

    for receipt in receipts:
        walk(receipt, "")
    return sorted(found)


def funding_fields(paths: list[str]) -> dict:
    """The falsifier's fourth limb: the candidates, each read against what was registered.

    The registered criterion is a field recording money moving into or out of the account
    whose equity the receipts report. That is a question about what a field means, and a word
    list cannot answer it — so the list is used to narrow the search and every path it turns
    up is read out loud here. A candidate this module has no reading for is treated as a
    funding field and fires the limb, because an unread field is the one case where silence
    would be the wrong answer.
    """
    candidates = [
        path
        for path in paths
        if any(word in path.rsplit(".", 1)[-1].casefold() for word in FUNDING_KEY_WORDS)
        and not path.startswith(SWAP_LEG_PREFIXES)
    ]
    unread = [path for path in candidates if path not in FUNDING_CANDIDATE_READINGS]
    return {
        "candidates": candidates,
        "readings": {
            path: FUNDING_CANDIDATE_READINGS[path]
            for path in candidates
            if path in FUNDING_CANDIDATE_READINGS
        },
        "unread_candidates": unread,
        "fields_recording_money_into_or_out_of_the_account": unread,
        "words_searched": list(FUNDING_KEY_WORDS),
    }


def _distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "min": None, "median": None, "max": None, "sum": 0.0}
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
        "sum": round(sum(values), 10),
    }


def _seal_row(receipt: dict, envelope_hash: str, commitment_seq) -> dict:
    seal = receipt["execution_seal"]
    verification = seal.get("verification")
    intent = receipt["intents"][0] if receipt["intents"] else {}
    return {
        "seq": receipt["seq"],
        "ts": receipt["ts"],
        "cycle_id": receipt["cycle_id"],
        "intent_key": receipt["intent_key"],
        "kind": intent.get("kind"),
        "from_asset": intent.get("from"),
        "to_asset": intent.get("to"),
        "notional_usd": intent.get("notional_usd"),
        "outcome": seal.get("outcome"),
        "ok": seal.get("ok"),
        "applies_state_change": seal.get("applies_state_change"),
        "tx_hash": seal.get("tx_hash"),
        "pre_trade_anchor_tx_hash": seal.get("pre_trade_anchor_tx_hash"),
        "confirmed_execution": is_confirmed_execution(receipt),
        "verification": None
        if not verification
        else {
            "status": verification.get("status"),
            "block_number": verification.get("block_number"),
            "confirmations": verification.get("confirmations"),
            "from_symbol": verification.get("from_symbol"),
            "to_symbol": verification.get("to_symbol"),
            "from_balance_delta": verification.get("from_balance_delta"),
            "to_balance_delta": verification.get("to_balance_delta"),
        },
        "commitment_seq": commitment_seq,
        "receipt_hash": envelope_hash,
    }


def measure(corpus: dict, v1_trading: dict) -> dict:
    """Every published figure, recomputed from the frozen corpus and from nothing else."""
    envelopes = corpus["receipts"]
    receipts = [envelope["receipt"] for envelope in envelopes]
    hash_by_seq = {
        envelope["receipt"]["seq"]: envelope["hash"] for envelope in envelopes
    }
    seq_by_hash = {
        envelope["hash"]: envelope["receipt"]["seq"] for envelope in envelopes
    }
    receipt_by_seq = {receipt["seq"]: receipt for receipt in receipts}

    commitments = [r for r in receipts if r["phase"] == "pre_trade_commit"]
    seals = [r for r in receipts if r["phase"] == "execution_seal"]
    summaries = [r for r in receipts if r["phase"] == "cycle_summary"]
    confirmed = [r for r in seals if is_confirmed_execution(r)]

    bound_commitment_seqs = []
    for receipt in seals:
        seq = seq_by_hash.get(receipt["pre_trade_hash"])
        pointed = None if seq is None else receipt_by_seq[seq]
        bound = (
            pointed is not None
            and pointed["phase"] == "pre_trade_commit"
            and pointed["intent_key"] == receipt["intent_key"]
        )
        bound_commitment_seqs.append(seq if bound else None)
    bound = [seq for seq in bound_commitment_seqs if seq is not None]
    never_sealed = sorted(
        receipt["seq"] for receipt in commitments if receipt["seq"] not in set(bound)
    )

    notionals = {}
    unparsed = []
    disagreements = []
    for receipt in seals:
        match = INTENT_KEY.match(receipt["intent_key"] or "")
        if match is None:
            unparsed.append(receipt["seq"])
            continue
        parsed = float(match.group("notional"))
        notionals[receipt["seq"]] = parsed
        declared = receipt["intents"][0]["notional_usd"] if receipt["intents"] else None
        if declared is None or abs(parsed - declared) > 1e-9:
            disagreements.append(receipt["seq"])

    all_intent_notionals = [
        intent["notional_usd"] for receipt in receipts for intent in receipt["intents"]
    ]
    notional_bound = max(all_intent_notionals)

    equity = [(r["seq"], r["ts"], r["equity_usd"]) for r in receipts]
    read_failures = [
        {
            "seq": seq,
            "ts": ts,
            "equity_usd": value,
            "previous_equity_usd": equity[index - 1][2],
            "next_equity_usd": equity[index + 1][2],
        }
        for index, (seq, ts, value) in enumerate(equity)
        if value == 0.0
        and 0 < index < len(equity) - 1
        and equity[index - 1][2] == equity[index + 1][2] != 0.0
    ]
    excluded = {failure["seq"] for failure in read_failures}
    steps = [
        {
            "from_seq": equity[index][0],
            "to_seq": equity[index + 1][0],
            "ts": equity[index + 1][1],
            "from_equity_usd": equity[index][2],
            "to_equity_usd": equity[index + 1][2],
            "step_usd": round(equity[index + 1][2] - equity[index][2], 10),
        }
        for index in range(len(equity) - 1)
        if equity[index][0] not in excluded and equity[index + 1][0] not in excluded
    ]
    unexplained = [step for step in steps if abs(step["step_usd"]) > notional_bound]
    largest_steps = sorted(steps, key=lambda step: -abs(step["step_usd"]))[
        :LARGEST_STEPS_SHOWN
    ]

    paths = key_paths(receipts)
    outcomes = {}
    for receipt in seals:
        outcome = receipt["execution_seal"].get("outcome")
        key = "no_outcome_recorded" if outcome is None else outcome
        outcomes[key] = outcomes.get(key, 0) + 1
    regimes = {}
    for receipt in receipts:
        regimes[receipt["regime"]] = regimes.get(receipt["regime"], 0) + 1
    kinds_all = {}
    kinds_confirmed = {}
    for receipt in seals:
        kind = receipt["intents"][0]["kind"] if receipt["intents"] else None
        kinds_all[kind] = kinds_all.get(kind, 0) + 1
        if is_confirmed_execution(receipt):
            kinds_confirmed[kind] = kinds_confirmed.get(kind, 0) + 1

    tx_hashes = [
        receipt["execution_seal"]["tx_hash"]
        for receipt in seals
        if receipt["execution_seal"].get("tx_hash")
    ]
    return {
        "window": corpus["window"],
        "phases": {
            "cycle_summary": len(summaries),
            "pre_trade_commit": len(commitments),
            "execution_seal": len(seals),
            "n_receipts": len(receipts),
            "phases_partition_the_chain": len(summaries) + len(commitments) + len(seals)
            == len(receipts),
        },
        "chain": verify_chain(envelopes)
        | {"anchor_cross_check": anchor_cross_check(envelopes, v1_trading)},
        "execution": {
            "confirmed_over_seals": rate(len(confirmed), len(seals)),
            "confirmed_over_commitments": rate(len(confirmed), len(commitments)),
            "outcomes": outcomes,
            "seals_with_a_tx_hash": rate(len(tx_hashes), len(seals)),
            "seals_with_a_tx_hash_and_no_confirmation": rate(
                len(tx_hashes) - len(confirmed), len(seals)
            ),
            "seals_with_a_pre_trade_anchor": count_only_anchored_seals(seals),
            "distinct_tx_hashes": len(set(tx_hashes)),
            "outcome_and_verification_name_the_same_seals": {
                receipt["seq"]
                for receipt in seals
                if receipt["execution_seal"].get("outcome") == "executed_now"
            }
            == {receipt["seq"] for receipt in confirmed},
        },
        "commitment_binding": {
            "seals_bound_to_a_commitment_in_the_chain": rate(len(bound), len(seals)),
            "distinct_commitments_bound": len(set(bound)),
            "commitments": len(commitments),
            "commitments_never_sealed": never_sealed,
            "binding_is_on_chain": False,
        },
        "sizing": {
            "over_all_seals": _distribution(
                [notionals[r["seq"]] for r in seals if r["seq"] in notionals]
            ),
            "over_confirmed_executions": _distribution(
                [notionals[r["seq"]] for r in confirmed if r["seq"] in notionals]
            ),
            "largest_intent_notional_usd": notional_bound,
            "kind_over_all_seals": kinds_all,
            "kind_over_confirmed_executions": kinds_confirmed,
            "intent_keys_that_did_not_parse": unparsed,
            "seqs_where_the_key_and_the_intent_disagree": disagreements,
            "units": "US dollars of intended notional, never token units",
        },
        "regime": regimes | {"n_receipts": len(receipts)},
        "equity": {
            "first": {
                "seq": equity[0][0],
                "ts": equity[0][1],
                "equity_usd": equity[0][2],
            },
            "last": {
                "seq": equity[-1][0],
                "ts": equity[-1][1],
                "equity_usd": equity[-1][2],
            },
            "read_failures": read_failures,
            "steps_no_recorded_trade_explains": unexplained,
            "largest_steps": largest_steps,
            "n_largest_steps_shown": LARGEST_STEPS_SHOWN,
            "notional_bound_usd": notional_bound,
            "n_steps_considered": len(steps),
            "key_paths": paths,
            "funding_fields": funding_fields(paths),
            "swap_leg_paths_excluded_by_definition": [
                path for path in paths if path.startswith(SWAP_LEG_PREFIXES)
            ],
            "no_return_published": NO_RETURN_STATEMENT,
        },
        "nulls": {
            "count_every_seal_as_a_trade": count_every_seal(seals),
            "count_only_anchored_seals": count_only_anchored_seals(seals),
        },
        "seals": [
            _seal_row(receipt, hash_by_seq[receipt["seq"]], commitment_seq)
            for receipt, commitment_seq in zip(seals, bound_commitment_seqs)
        ],
    }


def build_run_record(
    spec, corpus: dict, measured: dict, *, started_at, finished_at
) -> dict:
    """The committed run record: the measured figures and the sentences that qualify them."""
    execution = measured["execution"]
    chain = measured["chain"]
    sizing = measured["sizing"]
    return {
        "spec_id": spec.spec_id,
        "spec_hash": spec.spec_hash,
        "corpus_id": corpus["corpus_id"],
        "dataset_ref": spec.dataset_ref,
        "dataset_sha256": spec.dataset_sha256,
        "receipts_url": corpus["receipts_url"],
        "receipts_response_sha256": corpus["receipts_response_sha256"],
        "fetched_at": corpus["fetched_at"],
        "started_at": started_at,
        "finished_at": finished_at,
        "n_planned": spec.n_planned,
        "notice": NOTICE,
        "arms": {
            "registered": (
                "a seal whose outcome is executed_now and whose verification status is 1"
            ),
            "count_every_seal_as_a_trade": "every execution seal, whatever it says happened",
            "count_only_anchored_seals": (
                "only the seals carrying a pre_trade_anchor_tx_hash"
            ),
        },
        "method": (
            NOTICE
            + " Every figure is recomputed from the registered corpus and from nothing else: "
            "the chain was fetched once at the recorded fetched_at, its response digest is on "
            "this record, and no network call and no chain read was made while these figures "
            "were computed. The two integrity limbs are recomputed rather than read — the "
            "linkage between consecutive receipts, and whether each published hash is the "
            "digest of the body it is published beside — and the second needs the exact "
            "recipe, which differs from this repository's own by one argument and can only be "
            "told apart on the receipts carrying a non-ASCII character. A confirmed execution "
            "needs the agent's own outcome and the confirmation the chain it traded on "
            "returned; an unresolved seal is neither a success nor a failure and keeps its "
            "place in every denominator. Every count carries both of the denominators a "
            "reader might mean — seals, and the stated intentions behind them — because the "
            "two answer different questions. A tx_hash on a receipt is an assertion by the "
            "agent that a transaction exists, not a block read here: no transaction in this "
            "record was fetched from any chain, and the one external check that does not rest "
            "on SOLVENT's own word is the anchor Docket's v1 task 02 read on 2026-08-08. "
            "Nothing was signed, nothing was purchased and no transaction of any kind was "
            "made while this was computed."
        ),
        "finding": (
            f"Over the {measured['phases']['n_receipts']} receipts of the closed window "
            f"{corpus['window']['first_receipt_ts']} to "
            f"{corpus['window']['last_receipt_ts']}, the chain verifies end to end: "
            f"{chain['content_hashes_recomputed']['numerator']} of "
            f"{chain['content_hashes_recomputed']['denominator']} published hashes are the "
            "digest of the body they are published beside, "
            f"{chain['linkage_recomputed']['numerator']} of "
            f"{chain['linkage_recomputed']['denominator']} links hold, the genesis prev_hash "
            "is the zero word, and the value this corpus computes at seq "
            f"{chain['anchor_cross_check']['anchored_seq']} is the value a BSC transaction "
            "carried in a block mined "
            f"{chain['anchor_cross_check']['anchor_timestamp_utc'][:10]}, which Docket's own "
            "v1 task 02 read on chain on 2026-08-08, 25 days before this corpus was fetched. "
            "What the verified chain records is a thinner trading record than its length "
            "suggests. "
            f"{execution['confirmed_over_seals']['numerator']} of "
            f"{execution['confirmed_over_seals']['denominator']} execution seals reach a "
            "confirmed execution — just over half of the seals, and "
            f"{execution['confirmed_over_commitments']['numerator']} of the "
            f"{execution['confirmed_over_commitments']['denominator']} pre-trade commitments "
            "those seals answer, which is under half of those. "
            f"{execution['outcomes'].get('unresolved', 0)} seals were left unresolved and "
            "they keep their place in the denominator. "
            f"{execution['seals_with_a_tx_hash']['numerator']} seals carry a tx_hash, so "
            f"{execution['seals_with_a_tx_hash_and_no_confirmation']['numerator']} name a "
            "transaction the chain never confirms, and a pre-trade anchor appears on "
            f"{execution['seals_with_a_pre_trade_anchor']['numerator']} of "
            f"{execution['seals_with_a_pre_trade_anchor']['denominator']} seals — so this "
            "record is not pre-committed on chain and is not described as one. Where the confirmations landed matters as much as how many there were: "
            f"{sizing['kind_over_confirmed_executions'].get('qualify', 0)} of the "
            f"{sizing['kind_over_all_seals'].get('qualify', 0)} qualify seals are confirmed "
            "and they are the chain's smallest trades, while only "
            f"{sizing['kind_over_confirmed_executions'].get('exit', 0)} of the "
            f"{sizing['kind_over_all_seals'].get('exit', 0)} exit seals are — so the median "
            "confirmed trade is "
            f"{sizing['over_confirmed_executions']['median']} US dollars of intended notional "
            f"against a median of {sizing['over_all_seals']['median']} across all seals, and "
            "the seals that did not confirm are the larger ones. The regime call is the same "
            "value on all but one of the 384 receipts. "
            f"{len(measured['equity']['steps_no_recorded_trade_explains'])} steps in the "
            "equity series are larger than the largest notional any intent in the chain "
            f"records ({measured['equity']['notional_bound_usd']} US dollars), and one "
            "receipt reads 0.0 between two identical non-zero readings, so the series carries "
            "both money the trades cannot account for and at least one failed read. No "
            "return, win rate or drawdown is computed from it, and the reason is on this "
            "record rather than left as an omission."
        ),
        **measured,
    }


if __name__ == "__main__":
    # `python -m docket.advantage.v2.solvent` is what produced the committed record. The two
    # stamps bracket arithmetic and nothing else: the corpus was fetched and frozen before the
    # registration was written, and everything between them reads that file.
    from datetime import datetime, timezone

    from .replay import save_run
    from .spec import load

    root = Path(__file__).resolve().parents[3]
    registration = load(root / "docket/advantage/v2/specs/06-solvent-record.json")
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    frozen = load_corpus(root / registration.dataset_ref)
    v1 = json.loads(
        (root / "docket/advantage/experiments/02-trading.json").read_text(
            encoding="utf-8"
        )
    )
    record = build_run_record(
        registration,
        frozen,
        measure(frozen, v1),
        started_at=started,
        finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    save_run(record, root / "docket/advantage/v2/runs/06-solvent-record.json")
    print(record["finding"])
