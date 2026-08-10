"""A job's live state, read from BSC mainnet.

Two things this module refuses to do, both learned from E1c:

  * It never pins a historical block for a state read. BSC full nodes prune and answer
    `missing trie node`, and a pinned read of a job that exists comes back looking like
    a job that does not.
  * It never records an outage as a verdict. A `ContractLogicError` is the contract
    answering; anything else is the road to it failing. Blurring the two is how E1c
    first published the opposite of what the chain says.

The injected-`w3` seam is the one `positions.py` established: a supplied `w3` is used as
given, with no failover, so tests never touch a network.

Note: the failover shape below now exists in three places (here,
`docket/agents/pancake/positions.py`, and `experiments/e1c_settlement_surface.py`).
Extracting it is worth doing, but it would mean editing a shipped agent and a committed
experiment in the middle of an unrelated phase, so it is left flagged rather than done.
"""

import time

from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.middleware import ExtraDataToPOAMiddleware

from . import constants as c

ATTEMPTS_PER_RPC = 2
RPC_TIMEOUT_S = 20
RETRY_PAUSE_S = 0.5

# Minimal fragments rather than the vendored artifacts, for the reason positions.py
# gives and for one more: `abis/` is a repo directory, not package data, so it does not
# exist on the deployed box. These three functions are the whole surface this module
# touches, and each was called against mainnet before being written down.
#
# JOB_FIELDS is declared here in the struct's own order and read back by name — E1c lost
# a run reading `[-1]` as status when status is field 7 and the last field is a bytes32
# deliverable.
JOB_FIELDS = (
    "id",
    "client",
    "provider",
    "evaluator",
    "description",
    "budget",
    "expiredAt",
    "status",
    "hook",
    "submittedAt",
    "deliverable",
)
COMMERCE_ABI = [
    {
        "name": "getJob",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "jobId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "id", "type": "uint256"},
                    {"name": "client", "type": "address"},
                    {"name": "provider", "type": "address"},
                    {"name": "evaluator", "type": "address"},
                    {"name": "description", "type": "string"},
                    {"name": "budget", "type": "uint256"},
                    {"name": "expiredAt", "type": "uint256"},
                    {"name": "status", "type": "uint8"},
                    {"name": "hook", "type": "address"},
                    {"name": "submittedAt", "type": "uint256"},
                    {"name": "deliverable", "type": "bytes32"},
                ],
            }
        ],
    }
]
ROUTER_ABI = [
    {
        "name": "jobPolicy",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "jobId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "address"}],
    }
]
POLICY_ABI = [
    {
        "name": "disputed",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "jobId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    }
]


def _default_session(url: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": RPC_TIMEOUT_S}))
    # BSC is PoA: 280-byte extraData, which get_block rejects without this.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


class Rpc:
    """Runs a read against the first endpoint that answers it.

    One public node starts refusing partway through a burst of reads, so failover wraps
    every call rather than only the first, and a failed endpoint's session is dropped so
    the retry opens a fresh connection instead of reusing a throttled keep-alive.
    """

    def __init__(self, urls=c.RPC_URLS, session_factory=_default_session):
        self._urls = list(urls)
        self._session_factory = session_factory
        self._sessions: dict[str, object] = {}
        self.used: str | None = None

    def __call__(self, do):
        failures = []
        for url in self._urls:
            for attempt in range(ATTEMPTS_PER_RPC):
                try:
                    session = self._sessions.get(url)
                    if session is None:
                        session = self._session_factory(url)
                        self._sessions[url] = session
                    out = do(session)
                    self.used = url
                    return out
                except ContractLogicError:
                    # The contract answered, and the answer was "no". Retrying that on
                    # three more nodes gets the same answer and, worse, lets a verdict
                    # be reported as an outage.
                    raise
                except Exception as exc:
                    self._sessions.pop(url, None)
                    failures.append(
                        f"{url} (attempt {attempt + 1}): {type(exc).__name__}: {exc}"
                    )
                    if attempt < ATTEMPTS_PER_RPC - 1:
                        time.sleep(RETRY_PAUSE_S)
        raise RuntimeError("every endpoint failed:\n  " + "\n  ".join(failures))


class JobNotFound(LookupError):
    """No job with this id exists on chain."""


class JobReader:
    """Reads one ERC-8183 job. No keys, no writes, no pinned blocks."""

    def __init__(self, rpc_urls=c.RPC_URLS, w3: Web3 | None = None):
        self._injected = w3
        self._rpc = Rpc(rpc_urls)

    def _call(self, do):
        if self._injected is not None:
            return do(self._injected)
        return self._rpc(do)

    def job_state(self, job_id: int) -> dict:
        def read(w3):
            commerce = w3.eth.contract(address=c.COMMERCE, abi=COMMERCE_ABI)
            router = w3.eth.contract(address=c.ROUTER, abi=ROUTER_ABI)
            raw = commerce.functions.getJob(job_id).call()
            policy = router.functions.jobPolicy(job_id).call()
            disputed = False
            if int(policy, 16):
                pol = w3.eth.contract(
                    address=Web3.to_checksum_address(policy), abi=POLICY_ABI
                )
                disputed = pol.functions.disputed(job_id).call()
            return (
                raw,
                policy,
                disputed,
                w3.eth.block_number,
                w3.eth.get_block("latest")["timestamp"],
            )

        raw, policy, disputed, block, now = self._call(read)
        job = dict(zip(JOB_FIELDS, raw))

        # getJob does not revert for an id nobody has created — it returns a zero-filled
        # struct, which renders as a real job that is OPEN with a zero budget and no
        # client. Saying "not found" is the only honest reading of that.
        if not int(job["client"], 16):
            raise JobNotFound(f"no ERC-8183 job {job_id} on chain {c.CHAIN_ID}")

        submitted_at = job["submittedAt"] or None
        settle_at = submitted_at + c.DISPUTE_WINDOW_S if submitted_at else None
        status = c.JOB_STATUS[job["status"]]
        budget = int(job["budget"])

        return {
            "job_id": job_id,
            "chain_id": c.CHAIN_ID,
            "status": status,
            "client": job["client"],
            "provider": job["provider"],
            "budget_atomic": str(budget),
            "budget_display": (
                f"{budget / 10**c.PAYMENT_TOKEN_DECIMALS:g} ${c.PAYMENT_TOKEN_SYMBOL}"
            ),
            "expired_at": job["expiredAt"],
            "submitted_at": submitted_at,
            "policy": Web3.to_checksum_address(policy) if int(policy, 16) else None,
            "disputed": bool(disputed),
            "settle_at": settle_at,
            "settle_ready": bool(
                status == "SUBMITTED"
                and settle_at is not None
                and now >= settle_at
                and not disputed
            ),
            "dispute_window_seconds": c.DISPUTE_WINDOW_S,
            "read_at_block": block,
            "read_at_timestamp": now,
        }
