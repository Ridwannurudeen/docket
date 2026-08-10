"""The ERC-8183 deployment Docket's escrow rail runs against.

Every value here was read from BSC mainnet by `eth_call` on the date below, not copied
from a brief. The run that established them, including the two findings that decide the
shape of this rail, is committed at `experiments/e1c-result.json`:

  * mainnet is the only chain whose policy is whitelisted, so it is the only chain where
    a job can be registered and funded at all;
  * settle() is not gated on the caller, so Docket can close a ripe job itself.

There are deliberately **no testnet constants**. Testnet's only bound policy reads
`policyWhitelist == false`, so `registerJob` reverts `PolicyNotWhitelisted`, and the
router owner is not ours — there is nothing to fix and nothing to point a rail at.
Carrying the addresses anyway would only invite someone to try.
"""

from web3 import Web3

VERIFIED_ON = "2026-08-10"
EVIDENCE = "experiments/e1c-result.json"

CHAIN_ID = 56

COMMERCE = Web3.to_checksum_address("0xEa4DAa3100A767e86FDed867729ae7446476EBA6")
ROUTER = Web3.to_checksum_address("0x51895229E12F9876011789B04f8698af06cCD6DA")
POLICY = Web3.to_checksum_address("0x9C01845705b3078Aa2e8cfF7520a6376FD766dE5")
# commerce.paymentToken(); symbol "U", 18 decimals
PAYMENT_TOKEN = Web3.to_checksum_address("0xcE24439F2D9C6a2289F741120FE202248B666666")
PAYMENT_TOKEN_SYMBOL = "U"
PAYMENT_TOKEN_DECIMALS = 18

# policy.disputeWindow(). Seven days exactly, and there is no client-accept path in
# OptimisticPolicy, so a funded job cannot be settled early however willing both sides.
DISPUTE_WINDOW_S = 604800
# commerce.MAX_EXPIRY_DURATION()
MAX_EXPIRY_DURATION_S = 31536000
# policy.voteQuorum() of policy.activeVoterCount(); reject votes, not the buyer's lever
VOTE_QUORUM = 3
ACTIVE_VOTERS = 5
# commerce.platformFeeBP() — the kernel takes nothing today
PLATFORM_FEE_BP = 0

# Job status enum, in the order IACP.JobStatus declares it
JOB_STATUS = ("OPEN", "FUNDED", "SUBMITTED", "COMPLETED", "REJECTED", "EXPIRED")

# One public endpoint starts refusing under a few hundred sequential eth_calls, so reads
# fail over rather than trusting any single node. Order measured in positions.py.
RPC_URLS = (
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-rpc.publicnode.com",
    "https://binance.llamarpc.com",
)
