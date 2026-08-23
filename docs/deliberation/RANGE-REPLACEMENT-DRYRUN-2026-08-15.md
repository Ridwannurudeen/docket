# The ruled Range replacement, measured before it is registered — 2026-08-15

Codex's ruling on the failed block-0 Transfer-log population was: recommit Range to a
deterministic NPM `totalSupply()`/`tokenByIndex()` sample, and **"dry-run the exact 1,024-index
algorithm against a current finalized block and prove it fills all five strata. Do not
preregister an unmeasured replacement."**

This is that dry run. It does not preregister anything.

## What works

The enumeration method itself is sound, and unlike the block-0 log scan it is reachable on
free infrastructure:

| Check | Result |
|---|---|
| `eth_getBlockByNumber("finalized")` | works — but only via a raw provider request. web3.py's `get_block("finalized")` raises `extraData is 280 bytes, but should be 32` on BSC's PoA header |
| `NPM.totalSupply()` at a pinned block | **4,847,332** |
| `NPM.tokenByIndex(i)` at indices 0, 1, mid, last | all answered |
| `NPM.ownerOf(tokenId)` | answered |
| Agreement across endpoints | `bsc-dataseed.binance.org`, `bsc-dataseed1.defibit.io` and `bsc-rpc.publicnode.com` returned **identical** totals and token ids — the frame is independently re-derivable, which is the property the population exists to have |

`binance.llamarpc.com` did not resolve in any measurement today.

## What does not work: stratum density

A clean 160-index sample (0 errors, 27s, one endpoint) at block 116,089,351:

| | count | of sample |
|---|---|---|
| indices probed | 160 | |
| positions with non-zero liquidity | 6 | **3.8%** |
| of those, pool covered by the registered pool truth | 3 | |
| of those, pool gate passes | 3 | 1.9% |

Classified into the registered strata:

| Stratum | Sampled | Projected at 1024 |
|---|---|---|
| (1) in range, gate passes | 2 | ~13 |
| (2) above range, gate passes | 1 | ~6 |
| **(3) below range, gate passes** | **0** | **~0** |
| (4) live, gate fails | 3 | ~19 |
| (5) any remaining live | 6 | ~38 |

The registration says **"if any stratum is empty, input lock fails."** Stratum 3 drew nothing.

Two structural reasons, both independent of the sample size:

1. **96% of the NFTs are closed.** 4.85M tokens have ever been minted; only about one in
   twenty-five still holds liquidity. The population requires non-zero liquidity.
2. **The pool gate can only pass for pools the pool truth covers, and that is the top 27.**
   A live position in any other pool has no `tvlUSD`/`feeUSD24h` to test, so it lands in
   stratum 4 by construction. Only about half the live positions sampled were in a covered
   pool.

So a 1024-index draw yields on the order of twenty gate-passing positions, split across three
range states — and below-range is the rarest of the three, because a pool's tick has to sit
under a position's whole range rather than inside or over it.

## The finding that settles it: free BSC nodes prune state in under six minutes

Every read in this population must be pinned to the one registered observation block — that is
what makes both arms answer about the same chain state. Measured at head 116,102,267:

| Age of the pinned block | `bsc-dataseed1.defibit.io` | `bsc-rpc.publicnode.com` |
|---|---|---|
| head | `totalSupply` 4,848,210 | 4,848,210 |
| −80 blocks (~1 min) | 4,848,203 | 4,848,205 |
| −480 blocks (~6 min) | **`missing trie node`** | **403 Forbidden** |
| −2,800 blocks (~35 min) | `missing trie node` | 403 |
| −9,600 blocks (~2 h) | `missing trie node` | 403 |

`bsc-dataseed.binance.org` was unreachable during this measurement.

So the pinned block's state survives somewhere between one and six minutes. A 1,024-index
sample takes **thirty-five minutes and counting**. The walk cannot finish before the block it
is pinned to stops existing, at any concurrency — pacing it slower to dodge the rate limiter
makes this strictly worse.

This is the same root cause that killed the original block-0 Transfer-log frame, stated
properly: **the free endpoints are pruned nodes, not archive nodes.** The block-0 scan failed
on `eth_getLogs` limits; the enumeration fails on state age. Both are the absence of archive
access, and no rewrite of the sampling rule fixes it. It is also exactly the trap
`positions.py` already documents and guards with `PrunedStateError` — an infrastructure fault,
not an answer, and one that must never be recorded as a finding about somebody's wallet.

## Throughput is a second, separate constraint

| Run | Concurrency | Endpoints | Errors |
|---|---|---|---|
| 160 probes | 8 workers | 1 | **0** |
| 1024 probes | 8 workers | 1 | 704 / 1024 (`Web3RPCError`) |
| 1024 probes | 5 workers | 3, rotating | 961 / 1024 |

The 160-run sustained ~12 calls/s cleanly, so the limiter is burst-rate sensitive rather than
volume-capped. A paced run is being measured; whichever way it lands, the honest reading is
that a 1024-index sample is at the edge of what free endpoints will serve, and the capture has
one registered moment in which to succeed.

## What this means for the recommit

**Do not preregister a 1,024-index sample.** It fails on two independent grounds, and the
first is fatal on its own:

1. The pinned block's state is gone from every free endpoint long before the walk can finish.
2. Even a walk that completed would draw roughly twenty gate-passing positions, and stratum 3
   drew zero.

Any replacement has to answer the archive problem first, because sampling rules cannot. Four
directions, none taken here — a population rewritten by whoever noticed the problem is the
thing pre-registration exists to prevent:

1. **Buy archive access.** The honest fix. It restores the original block-0 frame as well, and
   it is the only option that leaves the protocol's re-derivability intact for a reader who
   does not share our infrastructure.
2. **Shrink the frame to fit the pruning window.** A few hundred indices can be read inside a
   minute. That deepens the stratum-density problem rather than solving it, and stratum 3 is
   already empty at 1,024.
3. **Enumerate at the head and pin afterwards** — record the block each read actually landed
   on instead of demanding one block for all of them. This gives up the property that both
   arms answer about identical state, which is most of why the protocol reads as it does.
4. **Register fewer strata.** A three-stratum protocol that completes is worth more than a
   five-stratum protocol that fails its own input lock — but only if the reduction is
   registered in advance and justified, not discovered convenient after the draw.

Yield is unaffected: its capture is two HTTP GETs, both reachable, and the whole
capture-to-lock path has now been exercised end to end against live PancakeSwap data.

## Status

Measured, not decided. The population is not rewritten by whoever noticed the problem on the
day they noticed it — that is what pre-registration exists to prevent, and it is the same
reason the original frame was referred out rather than quietly swapped.
