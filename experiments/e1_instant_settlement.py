"""E1: can a non-router evaluator settle an ERC-8183 job instantly? (BSC testnet 97)

The plan assumed `createJob(..., hook = address(0))`. The deployed testnet kernel
rejects that with `HookRequired()`, and rejects any address without the hook
interface with `HookMissingInterface()`. 0xD7d3...6F25 is the only conformant hook
deployed on chain 97 — every one of the 445 jobs created so far uses it. So E1's
question narrows rather than dies: create the job with the stock hook, never
register it with the marketplace router, and put a plain Docket EOA in the
`evaluator` slot. Read-only probes on 2026-08-07 showed that shape simulates
cleanly through `createJob`, and that `complete()` is `Unauthorized()` to everyone
except the job's evaluator. What no on-chain job has ever exercised — and what
this script settles — is whether the hook lets an *EOA* evaluator release payment.

Expect it to stop earlier than `complete`, though. Measured read-only on 2026-08-07:
calling `fund()` straight on the kernel reverts with selector 0x32d53d69, which
belongs to the hook and not to the kernel — stubbing the hook's bytecode out with an
always-true contract in an eth_call state override makes that same `fund()` succeed.
It reverts for a fresh unregistered job and for live router-created job 445 alike, so
the hook gates escrow funding on something the marketplace does outside `createJob`.
Recording that revert is still a real E1 answer: it says settlement timing is not
Docket's to control while the money can only enter escrow through the router.

ABI facts this script is pinned to (read from abis/AgenticCommerce.json):
  complete(uint256 jobId, bytes32 reason, bytes optParams)  <- reason is bytes32,
      not a string, hence `b"accepted".ljust(32, b"\\x00")`.
  jobs(uint256) -> (id, client, provider, evaluator, description, budget,
                    expiredAt, status, hook, submittedAt, deliverable)

Env: E1_CLIENT_KEY (funded with tBNB; acts as client AND provider),
     E1_EVALUATOR_KEY (the 'Docket marketplace' evaluator; script funds it from client).
Run: python -m experiments.e1_instant_settlement
"""

import json
import os
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.logs import DISCARD

RPC = "https://bsc-testnet-rpc.publicnode.com"
CHAIN_ID = 97
COMMERCE = Web3.to_checksum_address("0xa206c0517B6371C6638CD9e4a42Cc9f02A33B0DE")
U_TOKEN = Web3.to_checksum_address("0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565")
U_FAUCET = Web3.to_checksum_address("0x86e9197CC0F76E4e4aaa7082180945196bBAb5D3")
HOOK = Web3.to_checksum_address("0xD7d36D66d2F1B608A0F943f722D27e3744f66F25")
STATUS = ["OPEN", "FUNDED", "SUBMITTED", "COMPLETED", "REJECTED", "EXPIRED"]
BUDGET = 10**16  # 0.01 $U
ROOT = Path(__file__).resolve().parents[1]


def canonical_manifest_hash(manifest: dict) -> str:
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return Web3.keccak(blob).to_0x_hex()


def _load_abi(name: str) -> list:
    abi = json.loads((ROOT / "abis" / name).read_text())
    return abi["abi"] if isinstance(abi, dict) else abi


def _error_selectors() -> dict[str, str]:
    out = {}
    for entry in _load_abi("AgenticCommerce.json"):
        if entry.get("type") == "error":
            signature = f"{entry['name']}({','.join(i['type'] for i in entry['inputs'])})"
            out["0x" + Web3.keccak(text=signature)[:4].hex()] = signature
    return out


ERROR_SELECTORS = _error_selectors()


def _decode_error(blob: str) -> str | None:
    """Name the kernel's custom error inside a stringified web3 exception.

    web3 surfaces these as a bare 4-byte selector, so an undecoded failure record
    would be unreadable — and the failure record IS this experiment's answer.
    """
    for selector, signature in ERROR_SELECTORS.items():
        if selector in blob:
            return signature
    return None


def _abort_note(reached: list[str]) -> str:
    """Say so, in `notes`, when a run died before it ever attempted `complete()`.

    Phase 1 branches on this file, and `worked: false` on its own cannot tell a
    settlement the kernel refused apart from a run that never got that far — the
    likely outcome while the hook gates `fund()`. `reached` holds every step `_send`
    attempted, so its last entry names where the run stopped.
    """
    if reached and reached[-1] == "complete":
        return ""
    return (
        f" — RUN ABORTED AT {reached[-1] if reached else 'setup'}, BEFORE complete(); "
        "this result does NOT answer E1"
    )


def _send(w3, acct, call, label, txs, reached):
    """`call` is a ContractFunction (built here, so a revert still carries `label`)
    or a plain tx dict for a native transfer."""
    reached.append(label)
    try:
        params = {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": CHAIN_ID,
            "gasPrice": w3.eth.gas_price,  # legacy pricing: BSC, and keeps 1559 defaults out
        }
        tx = (
            call.build_transaction(params)
            if hasattr(call, "build_transaction")
            else {**params, **call}
        )
        if "gas" not in tx:
            tx["gas"] = w3.eth.estimate_gas(tx)
        tx["gas"] = int(tx["gas"] * 1.3)
        signed = acct.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        txs[label] = h.to_0x_hex()
        receipt = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    except Exception as exc:
        named = _decode_error(repr(exc)) or "no kernel error selector"
        raise RuntimeError(f"{label}: {named} <- {repr(exc)[:300]}") from exc
    if receipt.status != 1:
        raise RuntimeError(f"{label}: mined but reverted, tx {txs[label]}")
    return receipt


def main() -> int:
    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
    client = Account.from_key(os.environ["E1_CLIENT_KEY"])
    evaluator = Account.from_key(os.environ["E1_EVALUATOR_KEY"])
    commerce = w3.eth.contract(address=COMMERCE, abi=_load_abi("AgenticCommerce.json"))
    u = w3.eth.contract(address=U_TOKEN, abi=_load_abi("ERC20.json"))
    txs: dict[str, str] = {}
    reached: list[str] = []
    result = {
        "worked": False,
        "job_id": None,
        "final_status": None,
        "provider_u_delta_wei": None,
        "txs": txs,
        "revert": None,
        "notes": (
            "complete() called by a plain EOA evaluator on a job created with the stock hook "
            f"{HOOK} (the testnet kernel rejects hook=0 with HookRequired()) and never registered "
            "with the marketplace router; client and provider are the same account"
        ),
    }
    try:
        # 0) evaluator gas: top up from client if evaluator has < 0.002 tBNB
        if w3.eth.get_balance(evaluator.address) < w3.to_wei("0.002", "ether"):
            _send(
                w3,
                client,
                {"to": evaluator.address, "value": w3.to_wei("0.005", "ether")},
                "fund_evaluator_gas",
                txs,
                reached,
            )
        # 1) $U: faucet gives 10 $U per call
        if u.functions.balanceOf(client.address).call() < BUDGET:
            faucet = w3.eth.contract(
                address=U_FAUCET,
                abi=[
                    {
                        "name": "requestTokens",
                        "type": "function",
                        "stateMutability": "nonpayable",
                        "inputs": [],
                        "outputs": [],
                    }
                ],
            )
            _send(w3, client, faucet.functions.requestTokens(), "u_faucet", txs, reached)
        # 2) createJob with evaluator = Docket EOA, stock hook, NO registerJob.
        #    client == provider is allowed here (probed); if a kernel upgrade ever forbids it,
        #    fall back to a third throwaway account funded from the client that signs `submit`.
        expired_at = int(time.time()) + 3600
        rcpt = _send(
            w3,
            client,
            commerce.functions.createJob(
                client.address, evaluator.address, expired_at, "E1 instant-settlement probe", HOOK
            ),
            "create_job",
            txs,
            reached,
        )
        # read the id from the event, not jobCounter() — testnet has live third-party traffic
        job_id = commerce.events.JobCreated().process_receipt(rcpt, errors=DISCARD)[0]["args"][
            "jobId"
        ]
        result["job_id"] = job_id
        # 3) budget + approve + fund
        _send(
            w3,
            client,
            commerce.functions.setBudget(job_id, BUDGET, b""),
            "set_budget",
            txs,
            reached,
        )
        _send(w3, client, u.functions.approve(COMMERCE, BUDGET), "approve", txs, reached)
        _send(w3, client, commerce.functions.fund(job_id, BUDGET, b""), "fund", txs, reached)
        # 4) provider (== client) submits a deliverable
        manifest = {"service": "e1-probe", "content": "hello", "ts": expired_at}
        opt = json.dumps(
            {"deliverable_url": "https://docket.gudman.xyz/e1"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        _send(
            w3,
            client,
            commerce.functions.submit(
                job_id, Web3.to_bytes(hexstr=canonical_manifest_hash(manifest)), opt
            ),
            "submit",
            txs,
            reached,
        )
        # 5) THE TEST: evaluator EOA calls complete() immediately (no dispute window).
        #    Balance is sampled here, not before fund(): client == provider, so a whole-run
        #    delta nets to zero and would say nothing about whether payment was released.
        u_before = u.functions.balanceOf(client.address).call()
        _send(
            w3,
            evaluator,
            commerce.functions.complete(job_id, b"accepted".ljust(32, b"\x00"), b""),
            "complete",
            txs,
            reached,
        )
        status = STATUS[commerce.functions.jobs(job_id).call()[7]]
        result["final_status"] = status
        result["provider_u_delta_wei"] = str(
            u.functions.balanceOf(client.address).call() - u_before
        )
        result["worked"] = status == "COMPLETED"
    except Exception as exc:  # record the failure verbatim — that IS the experiment result
        result["revert"] = repr(exc)
        result["notes"] += _abort_note(reached)
    (ROOT / "experiments" / "e1-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["worked"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
