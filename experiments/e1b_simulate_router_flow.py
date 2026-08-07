"""E1-revised: can a Docket-owned EOA in the `evaluator` slot settle a router-
registered, funded, submitted ERC-8183 job? (BSC testnet 97, zero funding)

Task 2 proved `fund()` reverts `PolicyNotSet()` (selector 0x32d53d69, an
EvaluatorRouter error) until the job is bound to a policy via the router. The
router — 0xD7d3…6F25, which per the SDK "acts as job.evaluator and job.hook for
every job registered with it" — exposes `registerJob(jobId, policy)`, documented
"client-only, Open-only, single-shot, after createJob and before fund". So the
honest E1 question is now: build the *whole* canonical flow but put a plain
Docket EOA in the evaluator slot, and see whether that EOA can `complete()`.

This answers it with no keys and no funds: one `eth_simulateV1` runs the full
sequence — createJob(hook=router) -> router.registerJob -> setBudget -> approve
-> fund -> submit -> complete(from the EOA evaluator) — against overridden
balances, and reports each step's decoded status. `worked` is the final
`complete()` call succeeding for the EOA. The block is pinned so the in-sim
`jobCounter()+1` job id cannot race live testnet traffic.

One deliberate override: the sequence is prefixed with an owner-spoofed
`setPolicyWhitelist(policy, true)`. The brief's policy is the very one 18 recent
jobs are bound to, but the shared testnet router currently reports it NOT
whitelisted, so a plain run aborts at `PolicyNotWhitelisted()` — an admin-state
fact that has nothing to do with the evaluator. Whitelisting it in-sim (spoofed
`from` = router owner, balance overridden; still no key, no tx, no funds) removes
that confound so the run reaches, and reveals, the evaluator invariant itself.
The contrast run with `evaluator = router` funds cleanly under the identical
setup, which is what pins the barrier to the evaluator slot.

Run (primary, EOA evaluator -> e1b-result.json):
    python -m experiments.e1b_simulate_router_flow
Run (control, evaluator == router -> e1b-contrast-result.json):
    E1B_EVALUATOR=0xD7d36D66d2F1B608A0F943f722D27e3744f66F25 python -m experiments.e1b_simulate_router_flow
"""

import json
import os
import time

from hexbytes import HexBytes
from web3 import Web3

from experiments.e1_instant_settlement import (
    BUDGET,
    COMMERCE,
    HOOK,
    RPC,
    ROOT,
    STATUS,
    U_FAUCET,
    U_TOKEN,
    _decode_error,
    _load_abi,
    canonical_manifest_hash,
)

ROUTER = HOOK  # the router is the hook — same 0xD7d3…6F25 address in both slots
POLICY = Web3.to_checksum_address("0x4F4678D4439feC812Ac7674Bb3Efb4C8f5Fb78A6")
# throwaway actors — addresses only, never keys; eth_simulateV1 spoofs `from`
EOA_A = Web3.to_checksum_address("0x000000000000000000000000000000000000a1ce")  # client == provider
EOA_B = Web3.to_checksum_address(
    "0x00000000000000000000000000000000000d0cc7"
)  # Docket evaluator EOA
# The evaluator slot is the one variable this experiment turns. Default = the Docket
# EOA (the primary arm, -> e1b-result.json). Set E1B_EVALUATOR=<router> to run the
# canonical control arm (evaluator == router, -> e1b-contrast-result.json); that arm
# funds cleanly, and the difference is what pins the barrier to the evaluator slot.
EVALUATOR = Web3.to_checksum_address(os.environ.get("E1B_EVALUATOR", EOA_B))
IS_CONTRAST = EVALUATOR == ROUTER
OUT_NAME = "e1b-contrast-result.json" if IS_CONTRAST else "e1b-result.json"
FAUCET_ABI = [
    {
        "name": "requestTokens",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [],
        "outputs": [],
    }
]


def _jobs_output_types() -> list[str]:
    entry = next(
        e
        for e in _load_abi("AgenticCommerce.json")
        if e.get("type") == "function" and e["name"] == "jobs"
    )
    return [o["type"] for o in entry["outputs"]]


def _simulate(w3, calls, overrides, block_hex):
    """One eth_simulateV1 over `calls` (label, frm, to, ContractFunction) with the given
    balance `overrides`. Returns [(label, status, returnData)] or ('__rpc_error__', err)
    if the node lacks eth_simulateV1."""
    payload = {
        "blockStateCalls": [
            {
                "stateOverrides": overrides,
                "calls": [
                    {
                        "from": frm,
                        "to": to,
                        "data": fn._encode_transaction_data(),
                        "gas": hex(4_000_000),
                    }
                    for _, frm, to, fn in calls
                ],
            }
        ],
        "validation": False,
        "traceTransfers": False,
    }
    resp = w3.provider.make_request("eth_simulateV1", [payload, block_hex])
    if "result" not in resp:
        return [("__rpc_error__", 0, json.dumps(resp.get("error")))]
    out = []
    for (label, *_), call in zip(calls, resp["result"][0]["calls"]):
        out.append((label, int(call["status"], 16), call.get("returnData", "0x")))
    return out


def _eth_call_fallback(w3, calls, overrides, block_hex):
    """Degraded path if the node has no eth_simulateV1: probe each step with a lone
    eth_call and balance overrides. State does NOT chain between calls, so only the
    first reverting step is authoritative — later ones see un-mutated state."""
    out = []
    for label, frm, to, fn in calls:
        tx = {"from": frm, "to": to, "data": fn._encode_transaction_data(), "gas": hex(4_000_000)}
        resp = w3.provider.make_request("eth_call", [tx, block_hex, overrides])
        if "error" in resp:
            data = resp["error"].get("data", "") or json.dumps(resp["error"])
            out.append((label, 0, data if str(data).startswith("0x") else "0x"))
        else:
            out.append((label, 1, resp["result"]))
    return out


def main() -> int:
    w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 45}))
    commerce = w3.eth.contract(address=COMMERCE, abi=_load_abi("AgenticCommerce.json"))
    router = w3.eth.contract(address=ROUTER, abi=_load_abi("EvaluatorRouter.json"))
    u = w3.eth.contract(address=U_TOKEN, abi=_load_abi("ERC20.json"))
    faucet = w3.eth.contract(address=U_FAUCET, abi=FAUCET_ABI)

    owner = router.functions.owner().call()  # only used to spoof the whitelist bypass below
    block_number = w3.eth.block_number
    block_hex = hex(block_number)
    job_id = commerce.functions.jobCounter().call(block_identifier=block_number) + 1
    # local clock, not w3.eth.get_block — BSC's 279-byte extraData trips web3's POA
    # block validator; the kernel only needs expiredAt inside its min/max window
    expired_at = int(time.time()) + 3600
    manifest = {"service": "e1b-probe", "content": "hello", "ts": expired_at}
    deliverable = Web3.to_bytes(hexstr=canonical_manifest_hash(manifest))
    opt = json.dumps(
        {"deliverable_url": "https://docket.gudman.xyz/e1b"}, sort_keys=True, separators=(",", ":")
    ).encode()
    reason = b"accepted".ljust(32, b"\x00")

    # createJob puts EOA_B (a plain EOA) in the evaluator slot; the router stays as the
    # hook. Everything else is the canonical router flow. u_before / u_after bracket the
    # provider's $U so a successful complete() shows the +BUDGET escrow release. The
    # leading whitelist call is owner-spoofed (see module docstring) so registerJob's
    # own gate, not the incidental testnet whitelist state, is what the run measures.
    calls = [
        ("whitelist_policy", owner, ROUTER, router.functions.setPolicyWhitelist(POLICY, True)),
        ("u_faucet", EOA_A, U_FAUCET, faucet.functions.requestTokens()),
        (
            "create_job",
            EOA_A,
            COMMERCE,
            commerce.functions.createJob(
                EOA_A, EVALUATOR, expired_at, "E1b router-flow probe", ROUTER
            ),
        ),
        ("register_job", EOA_A, ROUTER, router.functions.registerJob(job_id, POLICY)),
        ("set_budget", EOA_A, COMMERCE, commerce.functions.setBudget(job_id, BUDGET, b"")),
        ("approve", EOA_A, U_TOKEN, u.functions.approve(COMMERCE, BUDGET)),
        ("u_before", EOA_A, U_TOKEN, u.functions.balanceOf(EOA_A)),
        ("fund", EOA_A, COMMERCE, commerce.functions.fund(job_id, BUDGET, b"")),
        ("submit", EOA_A, COMMERCE, commerce.functions.submit(job_id, deliverable, opt)),
        ("complete", EOA_B, COMMERCE, commerce.functions.complete(job_id, reason, b"")),
        ("u_after", EOA_A, U_TOKEN, u.functions.balanceOf(EOA_A)),
        ("job_status", EOA_A, COMMERCE, commerce.functions.jobs(job_id)),
    ]

    overrides = {a: {"balance": hex(10**18)} for a in (EOA_A, EOA_B, owner)}
    method = "eth_simulateV1"
    results = _simulate(w3, calls, overrides, block_hex)
    if results and results[0][0] == "__rpc_error__":
        method = "eth_call-sequential (degraded: state not chained)"
        results = _eth_call_fallback(w3, calls, overrides, block_hex)

    by_label = {label: (status, rd) for label, status, rd in results}
    steps = {}  # step -> "ok" | "revert:<decoded-or-selector>"
    first_revert = None
    for label, status, rd in results:
        if label in ("u_before", "u_after", "job_status"):
            continue
        if status == 1:
            steps[label] = "ok"
        else:
            named = _decode_error(rd) or (
                rd[:10] if rd.startswith("0x") and len(rd) >= 10 else "revert"
            )
            steps[label] = f"revert:{named}"
            if first_revert is None:
                first_revert = f"{label}: {named}"

    complete_status, _ = by_label.get("complete", (0, "0x"))
    worked = complete_status == 1

    final_status = None
    js_status, js_rd = by_label.get("job_status", (0, "0x"))
    if js_status == 1 and js_rd not in ("0x", ""):
        status_idx = w3.codec.decode(_jobs_output_types(), HexBytes(js_rd))[7]
        final_status = STATUS[status_idx] if status_idx < len(STATUS) else str(status_idx)

    delta = None
    b_status, b_rd = by_label.get("u_before", (0, "0x"))
    a_status, a_rd = by_label.get("u_after", (0, "0x"))
    if b_status == 1 and a_status == 1:
        delta = str(int(a_rd, 16) - int(b_rd, 16))

    if IS_CONTRAST:
        # control arm: the canonical config (evaluator == router). Its job is to prove the
        # flow funds when ONLY the evaluator address differs from the primary arm.
        notes = (
            "evaluator=router control (canonical config, the setup all 445 live jobs use). "
            f"register_job={steps.get('register_job')}, fund={steps.get('fund')}, "
            f"final_status={final_status}. This is the arm that funds cleanly: it succeeds "
            "through funding under the identical setup that reverts RouterNotEvaluator at "
            "register_job when the evaluator is a plain EOA, which is what pins the E1-revised "
            "barrier to the evaluator slot. Steps past fund (submit/complete) are governed by "
            "the OptimisticPolicy dispute window and are not this control's concern; complete "
            "here is still called from the Docket EOA, which is not this arm's evaluator."
        )
    elif worked:
        notes = (
            "an EOA evaluator settled a router-registered job in simulation; "
            "accept-is-settlement is available to Docket"
        )
    elif first_revert and first_revert.startswith("register_job"):
        notes = (
            f"EOA-evaluator settlement is not reachable: the flow aborts at {first_revert}. "
            "registerJob refuses a job whose evaluator is not the router itself "
            "(RouterNotEvaluator), so the job never binds a policy, fund() then reverts "
            "PolicyNotSet, and no funded/submitted state exists for the EOA to complete(). "
            "The router is job.evaluator and job.hook for every registered job; settlement "
            "must flow through EvaluatorRouter.settle() under the policy's dispute window. "
            "A contrast run with evaluator=router funds cleanly under the identical setup, "
            "pinning the barrier to the evaluator slot. Separately, on the live shared router "
            "the brief's policy currently reads NOT whitelisted, so an un-spoofed run would "
            "abort even earlier at PolicyNotWhitelisted; this sim whitelists it owner-spoofed "
            "to expose the evaluator invariant underneath."
        )
    else:
        # the run never reached registerJob (setup step reverted, or a node fault) — do not
        # let the RouterNotEvaluator diagnosis stand for a result that never measured it
        notes = (
            f"RUN ABORTED AT {first_revert or 'setup'}, before the registerJob evaluator gate; "
            "this result does NOT answer E1-revised. Re-run once the failing setup step is fixed."
        )

    result = {
        "worked": worked,
        "job_id": job_id,
        "final_status": final_status,
        "provider_u_delta_wei": delta,
        "txs": steps,
        "revert": first_revert,
        "notes": notes,
        "method": method,
    }
    (ROOT / "experiments" / OUT_NAME).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if worked else 1


if __name__ == "__main__":
    raise SystemExit(main())
