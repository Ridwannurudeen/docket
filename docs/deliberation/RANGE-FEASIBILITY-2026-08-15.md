# The Range population cannot be captured — measured 2026-08-15

Recorded because a protocol that will fail on the day it runs should fail in a document six
days early instead.

## What the registration requires

`v3-01-range-doctor.json`, `case_selection.chosen_by`: at the first finalized BSC block at or
after `2026-08-21T12:00:00Z`, read **every ERC-721 Transfer log from block 0** emitted by
PancakeSwap v3 NPM `0x46A15B0b27311cedF172AB29E4f4766fbE7F4364` and MasterChefV3
`0x556B9306565093C855AEA9AE92A594704c2Cd59e`. The distinct non-zero recipients are the
candidate frame.

## What the infrastructure actually allows

Measured from the VPS, against the two endpoints this build already uses:

| Endpoint | `eth_getLogs` for the NPM address |
|---|---|
| `bsc-dataseed.binance.org` | `-32005 limit exceeded` at windows of 5000, 1000, 500, 100 **and 10 blocks** |
| `bsc-rpc.publicnode.com` | `-32602 Archive requests require a personal token` |

The 10-block result is the one that settles it. This is not a range limit to be worked around
by chunking — the method is effectively unavailable for this contract on the free endpoint, and
the other requires a paid token.

For scale: BSC head was **116,080,366**. Even if a 1000-block window had worked, a
block-0-to-head scan is roughly 116,000 requests per contract, for two contracts.

## Why this is the protocol working, not failing

The registration already names this outcome: *"If any log or enumeration range cannot complete,
input lock fails and this protocol must be recommitted before another block is used."*

So nothing here is a defect in the code. The population was written to be independently
re-derivable — which is the right property and the reason it reads the way it does — and the
free infrastructure cannot serve it. The choice is to buy archive access or to recommit the
population to something a reader can still re-derive without it.

## Status

Referred to Codex for the recommit ruling. **Not changed unilaterally**: a population rewritten
by whoever noticed the problem, on the day they noticed it, is the thing pre-registration exists
to prevent.

Yield is unaffected — its capture is two HTTP GETs, both reachable from the VPS, and the capture
job for it is built and tested.
