"""The exact ordered calls that fund an ERC-8183 escrow job, with the invariants that
make them work encoded rather than described.

Docket does not sign any of this. It hands a buyer the sequence — addresses, function,
arguments and the calldata bytes — and the buyer executes it in whatever wallet or
script they already use. That keeps Docket out of the custody business entirely and
gives an evaluator agent something it can audit against chain for free.

Three orderings and one slot are load-bearing, and each was learned from a real revert:

  * `evaluator` and `hook` must both be the router. A plain EOA in the evaluator slot
    aborts at `registerJob` with `RouterNotEvaluator` (E1b).
  * `registerJob` must precede `fund`, or `fund` reverts `PolicyNotSet` (E1).
  * `submit` must land before `expiredAt`, or it reverts `SubmissionTooLate` (E1b's
    contrast arm).

Pure: no network access, no clock. Everything here is a function of its arguments,
which is what lets it be tested without a chain.
"""

from web3 import Web3

from . import constants as c


class ExpiryTooLong(ValueError):
    """Asked for a job that outlives the kernel's own maximum."""


_w3 = Web3()

COMMERCE_ABI = [
    {
        "name": "createJob",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "provider", "type": "address"},
            {"name": "evaluator", "type": "address"},
            {"name": "expiredAt", "type": "uint256"},
            {"name": "description", "type": "string"},
            {"name": "hook", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "setBudget",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "jobId", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
            {"name": "optParams", "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "name": "fund",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "jobId", "type": "uint256"},
            {"name": "expectedBudget", "type": "uint256"},
            {"name": "optParams", "type": "bytes"},
        ],
        "outputs": [],
    },
]
ROUTER_ABI = [
    {
        "name": "registerJob",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "jobId", "type": "uint256"},
            {"name": "policy", "type": "address"},
        ],
        "outputs": [],
    }
]
ERC20_ABI = [
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    }
]


def _encode(abi: list, function: str, args: dict) -> str:
    contract = _w3.eth.contract(abi=abi)
    return contract.encode_abi(function, args=list(args.values()))


def _step(n, to, abi, function, args, note, needs=()):
    """One call. `calldata` is None exactly when an argument is not knowable yet, so a
    caller can never mistake a placeholder for something signable."""
    return {
        "step": n,
        "to": to,
        "abi": abi,
        "function": function,
        "args": args,
        "calldata": None if needs else _encode(abi, function, args),
        "needs": list(needs),
        "note": note,
    }


def hire_calls(
    provider: str,
    budget_atomic: int,
    expires_in_s: int,
    description: str,
    job_id: int | None = None,
    now: int | None = None,
) -> list[dict]:
    """The ordered calls that take a job from nothing to FUNDED.

    `job_id` is not known until `createJob` lands, so the three calls that need it come
    back with `calldata: None` and `needs: ["job_id"]` until it is supplied. Inventing
    one would encode a call against somebody else's job.

    `now` exists only so `expiredAt` is reproducible in a test; callers pass nothing.
    """
    if expires_in_s > c.MAX_EXPIRY_DURATION_S:
        raise ExpiryTooLong(
            f"expires_in_s={expires_in_s} exceeds the kernel's MAX_EXPIRY_DURATION "
            f"of {c.MAX_EXPIRY_DURATION_S}s ({c.MAX_EXPIRY_DURATION_S // 86400} days)"
        )

    import time

    base = int(now if now is not None else time.time())
    expired_at = base + expires_in_s
    provider = Web3.to_checksum_address(provider)
    budget_atomic = int(budget_atomic)
    pending = () if job_id is not None else ("job_id",)
    jid = int(job_id) if job_id is not None else 0

    return [
        _step(
            1,
            c.COMMERCE,
            COMMERCE_ABI,
            "createJob",
            {
                "provider": provider,
                "evaluator": c.ROUTER,
                "expiredAt": expired_at,
                "description": description,
                "hook": c.ROUTER,
            },
            "Creates the job and returns its id. The evaluator and hook slots are both "
            "the router and cannot be anything else: a plain address in the evaluator "
            "slot makes the next call revert RouterNotEvaluator. Read the new job id "
            "from the receipt, then request this sequence again with it.",
        ),
        _step(
            2,
            c.ROUTER,
            ROUTER_ABI,
            "registerJob",
            {"jobId": jid, "policy": c.POLICY},
            "Binds the job to the whitelisted optimistic policy. This must happen "
            "before fund, which otherwise reverts PolicyNotSet.",
            needs=pending,
        ),
        _step(
            3,
            c.COMMERCE,
            COMMERCE_ABI,
            "setBudget",
            {"jobId": jid, "amount": budget_atomic, "optParams": b""},
            "Sets the amount the job will hold in escrow.",
            needs=pending,
        ),
        _step(
            4,
            c.PAYMENT_TOKEN,
            ERC20_ABI,
            "approve",
            {"spender": c.COMMERCE, "value": budget_atomic},
            f"Approves the commerce contract to move the budget in "
            f"${c.PAYMENT_TOKEN_SYMBOL}. You also need BNB for gas; the kernel takes no "
            f"platform fee today.",
        ),
        _step(
            5,
            c.COMMERCE,
            COMMERCE_ABI,
            "fund",
            {"jobId": jid, "expectedBudget": budget_atomic, "optParams": b""},
            "Moves the budget into escrow. After this the provider submits a "
            "deliverable, which must land before expiredAt or it reverts "
            "SubmissionTooLate. Settlement then waits out a 7 day (604800s) dispute "
            "window — there is no early-accept path in this policy, so nobody can "
            "shorten it. Your lever during the window is dispute(jobId) on the policy.",
            needs=pending,
        ),
    ]
