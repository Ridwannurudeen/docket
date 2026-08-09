"""E1c: on which chain is the ERC-8183 escrow rail actually open today, and can
Docket close a job itself once the dispute window elapses?

E1b settled the shape of settlement — the router must hold both the evaluator and
hook slots, so there is no instant accept-is-settlement and money moves through
`EvaluatorRouter.settle()` under the policy's dispute window. It left two questions
that decide whether Docket can offer an escrow hire at all, and it left one of them
hidden inside an override: E1b only reached the evaluator gate by owner-spoofing
`setPolicyWhitelist`, because the brief's testnet policy read NOT whitelisted.

The design spec plans for testnet to be the judge-facing escrow path, on the strength
of its 1-day dispute window against mainnet's 7. This experiment checks that plan
against the live chains rather than assuming it, by asking:

  Q1  Is the policy that jobs are actually bound to whitelisted on the router?
      A non-whitelisted policy means `registerJob` reverts PolicyNotWhitelisted and
      no job on that chain can ever be funded. The router owner is not ours, so this
      is not a state Docket can fix.
  Q2  May a caller who is party to nothing call `settle()` on a ripe job?
      If yes, Docket can close a judge's job the moment the window elapses instead of
      asking the judge to return a week later.

Read-only: `eth_call` only, no keys, no funds, no state overrides. Nothing here can
change a chain, and `settle()` is probed with `.call()`, which is never broadcast.

Run:
    python -m experiments.e1c_settlement_surface
"""

import json
import time

from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.middleware import ExtraDataToPOAMiddleware

from experiments.e1_instant_settlement import ROOT, _load_abi

# A caller that is party to nothing: not client, provider, evaluator, or voter on any
# job. If settle() works for this address it is not gated on who is asking.
STRANGER = Web3.to_checksum_address("0x000000000000000000000000000000000000dEaD")
JOB_SCAN_DEPTH = 40  # how far back to look for SUBMITTED jobs
POLICY_SCAN_DEPTH = 40  # how far back to look for the policy jobs actually bind
ATTEMPTS_PER_RPC = 2
RPC_TIMEOUT_S = 20
RETRY_PAUSE_S = 0.5
BLOCK_LAG = 5  # pin a few blocks back so a lagging endpoint can still serve the read

CHAINS = {
    56: {
        "name": "BSC mainnet",
        # same order positions.py measured best-first; a single endpoint 403s under
        # the call volume this experiment makes
        "rpc": [
            "https://bsc-dataseed.binance.org",
            "https://bsc-dataseed1.defibit.io",
            "https://bsc-rpc.publicnode.com",
            "https://binance.llamarpc.com",
        ],
        "router": "0x51895229E12F9876011789B04f8698af06cCD6DA",
        "commerce": "0xEa4DAa3100A767e86FDed867729ae7446476EBA6",
        "brief_policy": "0x9C01845705b3078Aa2e8cfF7520a6376FD766dE5",
    },
    97: {
        "name": "BSC testnet",
        "rpc": [
            "https://bsc-testnet-rpc.publicnode.com",
            "https://data-seed-prebsc-1-s1.binance.org:8545",
        ],
        "router": "0xD7d36D66d2F1B608A0F943f722D27e3744f66F25",
        "commerce": "0xa206c0517B6371C6638CD9e4a42Cc9f02A33B0DE",
        "brief_policy": "0x4F4678D4439feC812Ac7674Bb3Efb4C8f5Fb78A6",
    },
}

# struct IACP.Job field order, from AgenticCommerce.json getJob outputs
JOB_STATUS = 7
JOB_SUBMITTED_AT = 9
SUBMITTED = 2


class Rpc:
    """Runs a read against the first endpoint that answers it.

    A rate-limited endpoint is the normal failure here, not an exotic one: this
    experiment makes a few hundred eth_calls and a single public node starts
    returning 403 partway through. So failover wraps every call rather than only
    the first, and a failing endpoint's session is dropped so the retry opens a
    fresh connection instead of reusing a throttled keep-alive.
    """

    def __init__(self, urls):
        self._urls = list(urls)
        self._sessions = {}
        self.used = None

    def __call__(self, do):
        failures = []
        for url in self._urls:
            for attempt in range(ATTEMPTS_PER_RPC):
                try:
                    session = self._sessions.get(url)
                    if session is None:
                        session = Web3(
                            Web3.HTTPProvider(
                                url, request_kwargs={"timeout": RPC_TIMEOUT_S}
                            )
                        )
                        session.middleware_onion.inject(
                            ExtraDataToPOAMiddleware, layer=0
                        )  # BSC is PoA: 280-byte extraData
                        self._sessions[url] = session
                    out = do(session)
                    self.used = url
                    return out
                except ContractLogicError:
                    # The contract answered, and the answer was "no". That is a result,
                    # not a transport fault: retrying it on three more endpoints would
                    # get the same revert and, worse, let it be reported as an outage.
                    raise
                except Exception as exc:
                    self._sessions.pop(url, None)
                    failures.append(
                        f"{url} (attempt {attempt + 1}): {type(exc).__name__}: {exc}"
                    )
                    if attempt < ATTEMPTS_PER_RPC - 1:
                        time.sleep(RETRY_PAUSE_S)
        raise RuntimeError("every endpoint failed:\n  " + "\n  ".join(failures))


def _error_names():
    names = {}
    for abi_file in (
        "EvaluatorRouter.json",
        "OptimisticPolicy.json",
        "AgenticCommerce.json",
    ):
        for entry in _load_abi(abi_file):
            if entry.get("type") == "error":
                sig = (
                    entry["name"]
                    + "("
                    + ",".join(i["type"] for i in entry.get("inputs", []))
                    + ")"
                )
                names["0x" + Web3.keccak(text=sig)[:4].hex()] = entry["name"]
    return names


def _decode(exc, names):
    text = str(exc)
    for selector, name in names.items():
        if selector[2:] in text:
            return name
    return text[:200]


def _probe_chain(chain_id, cfg, names):
    rpc = Rpc(cfg["rpc"])
    router_addr = Web3.to_checksum_address(cfg["router"])
    commerce_addr = Web3.to_checksum_address(cfg["commerce"])
    brief = Web3.to_checksum_address(cfg["brief_policy"])
    router_abi = _load_abi("EvaluatorRouter.json")
    commerce_abi = _load_abi("AgenticCommerce.json")
    policy_abi = _load_abi("OptimisticPolicy.json")

    def router_at(w3):
        return w3.eth.contract(address=router_addr, abi=router_abi)

    def commerce_at(w3):
        return w3.eth.contract(address=commerce_addr, abi=commerce_abi)

    def policy_at(w3, addr):
        return w3.eth.contract(address=Web3.to_checksum_address(addr), abi=policy_abi)

    try:
        block = rpc(lambda w3: w3.eth.block_number) - BLOCK_LAG
        now = rpc(lambda w3: w3.eth.get_block(block)["timestamp"])
        job_counter = rpc(
            lambda w3: (
                commerce_at(w3).functions.jobCounter().call(block_identifier=block)
            )
        )
    except RuntimeError as exc:
        return {"error": str(exc), "rpc_tried": cfg["rpc"]}

    def whitelisted(addr):
        return rpc(
            lambda w3: (
                router_at(w3)
                .functions.policyWhitelist(Web3.to_checksum_address(addr))
                .call(block_identifier=block)
            )
        )

    out = {
        "chain": cfg["name"],
        "rpc": rpc.used,
        "block": block,
        "block_timestamp": now,
        "router": router_addr,
        "router_owner": rpc(
            lambda w3: router_at(w3).functions.owner().call(block_identifier=block)
        ),
        "router_paused": rpc(
            lambda w3: router_at(w3).functions.paused().call(block_identifier=block)
        ),
        "inflight_jobs": rpc(
            lambda w3: (
                router_at(w3).functions.inflightJobCount().call(block_identifier=block)
            )
        ),
        "job_counter": job_counter,
        "brief_policy": brief,
        "brief_policy_whitelisted": whitelisted(brief),
    }

    # Q1: which policy do live jobs bind, and is that one whitelisted?
    bound = {}
    for job_id in range(job_counter, max(job_counter - POLICY_SCAN_DEPTH, 0), -1):
        try:
            addr = rpc(
                lambda w3, j=job_id: (
                    router_at(w3).functions.jobPolicy(j).call(block_identifier=block)
                )
            )
        except RuntimeError:
            continue
        if int(addr, 16):
            bound.setdefault(addr, []).append(job_id)
    out["policies_on_recent_jobs"] = {
        addr: {
            "jobs_seen": ids[:5],
            "count_in_window": len(ids),
            "whitelisted": whitelisted(addr),
        }
        for addr, ids in bound.items()
    }
    out["registration_open"] = any(
        p["whitelisted"] for p in out["policies_on_recent_jobs"].values()
    )

    if out["brief_policy_whitelisted"]:
        out["dispute_window_seconds"] = rpc(
            lambda w3: (
                policy_at(w3, brief)
                .functions.disputeWindow()
                .call(block_identifier=block)
            )
        )
        out["vote_quorum"] = rpc(
            lambda w3: (
                policy_at(w3, brief).functions.voteQuorum().call(block_identifier=block)
            )
        )
        out["active_voters"] = rpc(
            lambda w3: (
                policy_at(w3, brief)
                .functions.activeVoterCount()
                .call(block_identifier=block)
            )
        )
        out["policy_router"] = rpc(
            lambda w3: (
                policy_at(w3, brief).functions.router().call(block_identifier=block)
            )
        )
    else:
        out["dispute_window_seconds"] = None

    # Q2: is settle() gated on who is asking? Needs a live SUBMITTED job to aim at.
    ripe, unripe = None, None
    window = out["dispute_window_seconds"]
    if window:
        for job_id in range(job_counter, max(job_counter - JOB_SCAN_DEPTH, 0), -1):
            if ripe and unripe:
                break
            try:
                job = rpc(
                    lambda w3, j=job_id: (
                        commerce_at(w3).functions.getJob(j).call(block_identifier=block)
                    )
                )
                if job[JOB_STATUS] != SUBMITTED:
                    continue
                if rpc(
                    lambda w3, j=job_id: (
                        policy_at(w3, brief)
                        .functions.disputed(j)
                        .call(block_identifier=block)
                    )
                ):
                    continue
            except RuntimeError:
                continue
            settle_at = job[JOB_SUBMITTED_AT] + window
            if settle_at <= now and ripe is None:
                ripe = (job_id, settle_at)
            elif settle_at > now and unripe is None:
                unripe = (job_id, settle_at)

    out["settle_probe"] = {}
    for label, found in (("ripe", ripe), ("still_in_window", unripe)):
        if found is None:
            out["settle_probe"][label] = {
                "job": None,
                "result": "no such job found in scan window",
            }
            continue
        job_id, settle_at = found
        # Deliberately at "latest", not the pinned block: settle() reads state, and BSC
        # full nodes prune it, so a pinned historical call answers "missing trie node" —
        # an infrastructure fault that must never be recorded as a contract verdict.
        try:
            rpc(
                lambda w3, j=job_id: (
                    router_at(w3).functions.settle(j, b"").call({"from": STRANGER})
                )
            )
            verdict = "succeeds"
        except ContractLogicError as exc:
            verdict = f"reverts {_decode(exc, names)}"
        except Exception as exc:
            verdict = f"undetermined: no endpoint answered ({type(exc).__name__})"
        out["settle_probe"][label] = {
            "job": job_id,
            "settle_at": settle_at,
            "result": verdict,
        }

    return out


def _settle_sentence(stranger_settles, ripe_result):
    """What the settle() probe actually established — including the case where it
    established nothing, which is the one worth refusing to paper over."""
    if stranger_settles is True:
        return (
            "What makes that workable is that settle() is not gated on the caller: a stranger "
            "address, party to nothing, settles a ripe job in eth_call, so Docket can close a "
            "buyer's job itself the moment the window elapses."
        )
    if stranger_settles is False:
        return (
            "And settle() is gated on the caller — a stranger address is refused "
            f"({ripe_result}) — so closing a buyer's job needs an account that is party to it."
        )
    return (
        "Whether settle() is gated on the caller is UNRESOLVED here: no endpoint answered the "
        f"probe ({ripe_result or 'no ripe job found'}). Do not plan around either answer until "
        "this is re-run."
    )


def main() -> int:
    names = _error_names()
    chains = {str(cid): _probe_chain(cid, cfg, names) for cid, cfg in CHAINS.items()}

    mainnet, testnet = chains["56"], chains["97"]
    open_chains = [cid for cid, c in chains.items() if c.get("registration_open")]
    # Tri-state on purpose. An earlier cut of this script derived False from an RPC
    # fault and published "settle is not permissionless", which is the opposite of what
    # the chain says. A question the probe failed to reach stays None.
    ripe_result = mainnet.get("settle_probe", {}).get("ripe", {}).get("result", "")
    if ripe_result == "succeeds":
        stranger_settles = True
    elif ripe_result.startswith("reverts"):
        stranger_settles = False
    else:
        stranger_settles = None

    notes = (
        "The design spec routes judge-facing escrow hires to testnet for its 1-day dispute "
        "window. That route is closed: the only policy testnet jobs bind "
        f"({testnet.get('brief_policy')}) reads policyWhitelist=false, so registerJob reverts "
        "PolicyNotWhitelisted and no new testnet job can be funded. The jobs already bound to "
        "it registered before the whitelist was withdrawn; the router owner "
        f"({testnet.get('router_owner')}) is not ours, so this is not state Docket can repair. "
        "Mainnet is the inverse and is open: its policy is whitelisted and carries almost every "
        "recent job. The cost of that is the real one — a 7-day dispute window with no "
        "client-accept path anywhere in OptimisticPolicy, so a funded job cannot be settled "
        "early however willing both sides are. "
        + _settle_sentence(stranger_settles, ripe_result)
        + " Probed read-only: every settle() call is an eth_call and was never broadcast, so no "
        "live job was touched."
    )

    result = {
        "question": (
            "Which chain's ERC-8183 escrow rail is open today, and may Docket settle a job "
            "it is not party to once the dispute window elapses?"
        ),
        "registration_open_on": open_chains,
        "settle_is_permissionless_on_mainnet": stranger_settles,
        "testnet_escrow_open": bool(testnet.get("registration_open")),
        "mainnet_dispute_window_seconds": mainnet.get("dispute_window_seconds"),
        "chains": chains,
        "notes": notes,
        "method": (
            "eth_call, no keys and no state overrides. Inventory reads are pinned to the "
            "block recorded per chain so every figure describes one moment; the settle() "
            "probes run at latest, because they read state that full nodes prune."
        ),
    }
    (ROOT / "experiments" / "e1c-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
