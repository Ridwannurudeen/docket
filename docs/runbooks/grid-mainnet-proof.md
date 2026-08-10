# The Grid Operator mainnet proof — prepared, not run

**Status: NOTHING IN THIS DOCUMENT HAS BEEN EXECUTED.** No session has been granted, no
swap has been sent, no key has been registered, and no value-moving call has been made
from this repository — not even to "check". Every figure below came from a read.

This is the runbook for one tiny, reversible proof on BSC mainnet, to be run by the
wallet's owner after they have read it and decided to. It exists so the decision can be
made with the whole thing visible, rather than a step at a time with a signature prompt
already open.

---

## 1. What this proves, and what it does not

It proves six things, in order, and each one is checkable by a stranger with a block
explorer and no access to Docket:

1. A session key was registered on chain against the owner's wallet.
2. Docket read that session's authority from the chain and drafted a bounded action.
3. One swap executed inside it.
4. The session's spend cap decremented on chain by what the swap consumed.
5. The owner revoked the session.
6. The same action, attempted again, was refused — and refused by the chain, not by
   Docket being polite about it.

It does **not** prove the trade was worth making. A grid level filling at its own price
is a fill. Whether the position ends up ahead depends on what the market does next, and
nothing here measures that. It also does not prove Docket can trade at scale, on any
other pair, or in any condition other than the one minute it ran in.

## 2. What is Docket's and what is the owner's — read this before anything else

Docket **cannot perform steps 1, 3 or 5 of the proof.** This is a property of the build,
not a gap to be worked around on the day:

- **Granting** a session is a transaction signed by the account owner. Docket does not
  hold the owner key and is not going to.
- **Revoking** is gated `onlyKeyOwnerOrValidator` on chain, so it is the owner's call by
  construction.
- **Submitting** the swap means signing a userOp with the session key and sending it to
  Altana's relay. That path lives in Altana's TypeScript SDK; there is no Python
  equivalent on PyPI, and `docket.agents.grid.operator.GridOperator` therefore refuses to
  be constructed without a `submitter` supplied from outside. Docket ships none.

What Docket does, entirely from Python and with no SDK in the path, is **read the
authority from the chain and decide against it** — `KeyStore.isValidKey`,
`KeyStore.getKeys`, `account.spendInfos` and `account.canExecute`, over the BSC failover
list. That is steps 2, 4 and 6, and it is the half a judge should press on, because it is
the half that would otherwise be a server-side check wearing a session's clothes.

So the proof is run with two hands: Altana's SDK (or the owner's own wallet) for the
three transactions, and Docket for the three reads and the decision.

## 3. Preconditions

- [ ] An Altana wallet on BSC mainnet, with the admin key held by the owner and **not**
      by Docket.
- [ ] About **0.002 BNB** in it for gas and the key-registration fee (see §6 — the real
      figure today is roughly a quarter of that; the rest is headroom).
- [ ] **30 USDT** in it. BSC USDT is `0x55d398326f99059fF775485246999027B3197955` and is
      **18 decimals**, not 6. Every amount below is written in 18-decimal atomic units,
      and getting this wrong by twelve orders of magnitude in the wrong direction is the
      single most expensive typo available in this document.
- [ ] Node ≥ 20 and `@altananetwork/sdk` pinned **exactly**: `npm i @altananetwork/sdk@0.7.0`.
      It is pre-1.0 and its own documentation says minor versions may break. Note two
      packaging facts before you depend on it: the npm `repository.url` 404s (the real
      repo is `github.com/altananetwork/altana-sdk`), and the published tarball's LICENSE
      says GPL-3.0 while the GitHub repo says Apache-2.0. Resolve that with the
      maintainer if licensing matters to you.
- [ ] Docket checked out at the commit this runbook ships in, with `./.venv/Scripts/python`
      working and the suite green.

## 4. Rehearse on testnet 97 first

The full Altana stack is deployed on BSC testnet, and rehearsing there closes the one
thing nobody has been able to close by reading: **no Altana wallet on BSC mainnet could
be located to read**, so Docket's chain reads have been exercised against an address with
no keys and against fakes, and never against a live granted session. Do the whole of §7
on chain 97 first and confirm every read in §8 returns what it should.

| Contract | Chain 97 |
| --- | --- |
| KeyStore | `0x6b8361C29d05D498b1a12B54A37310f94171E94A` |
| KeyStoreController | `0xb530D1971f5453F3359518343F05D0AedFfF7e12` |
| Relay | `https://testnet-relay.altana.network` |

Faucet: `testnet.bnbchain.org/faucet-smart`. Point Docket's reader at the testnet KeyStore
with `AltanaSessionAuthority(account=WALLET, keystore="0x6b8361C29d05D498b1a12B54A37310f94171E94A")`.

If the testnet rehearsal does not produce a clean §8, **stop**. Do not spend the mainnet
step discovering something the testnet would have told you for free.

## 5. The exact grant

One contract, one method, one token, one day. Nothing wider "while we're here".

```ts
import { createClient } from "@altananetwork/sdk";

const client = createClient({ chainId: 56 });

const session = await client.grantSession({
  wallet,                       // the Altana account
  signer: ownerSigner,          // the OWNER's key. Never Docket's.
  register: true,               // MANDATORY — see below
  expiry: Math.floor(Date.now() / 1000) + 24 * 60 * 60,
  permissions: {
    calls: [
      { to: "0x10ED43C718714eb63d5aA57B78B54704E256024E",
        signature: "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)" },
      { to: "0x55d398326f99059fF775485246999027B3197955",
        signature: "approve(address,uint256)" },
    ],
    spend: [
      { token: "0x55d398326f99059fF775485246999027B3197955",
        limit: 30000000000000000000n,   // 30 USDT at 18 decimals
        period: "day" },
    ],
  },
});
```

Four things about that block are load-bearing:

- **`register: true` is not optional here.** A session granted with `register: false`
  works perfectly and is written to no public KeyStore, which makes it invisible to every
  on-chain reader including Docket's. An unregistered session cannot be proved, so it
  cannot be the subject of a proof.
- **`calls` must be present.** Altana's own documentation states that an omitted `calls`
  lets the session call any contract within its spend cap. An omitted allowlist is not a
  narrow default; it is no allowlist.
- **`approve` is on the token, not the router.** The session needs to let the router pull
  USDT; that is a call to USDT's own contract.
- **`grantSession` takes tens of seconds and returns a `Session`, not a transaction
  hash.** It waits for the relay to confirm, then polls the account until the new key is
  visible, then waits again for public RPC caches to catch up. Keep
  `session.publicKey` (SEC1 uncompressed, `0x04‖x‖y`) and the session signer's address —
  Docket needs both, and they are not interchangeable.

## 6. The tiny amount, and what it costs

| | |
| --- | --- |
| Grid band | drawn ±10% around the observed WBNB/USDT price |
| Levels | 6 |
| Size per level | **5 USDT** (`5000000000000000000`) — override the 25 USDT default |
| Levels the proof fires | **one** |
| At risk if everything goes wrong | 5 USDT, bounded by the intent's `min_output`, and 30 USDT bounded by the on-chain cap |

Cost, read from BSC mainnet at block 115,161,822 on 2026-08-10:

| Item | Figure |
| --- | --- |
| Gas price | 0.05 gwei |
| `approve` (~46,000 gas) | 0.0000023 BNB |
| V2 swap (~150,000 gas) | 0.0000075 BNB |
| Key registration fee (`KeyStoreController.getRegistrationFeeInWei()`) | **0.000833613026745366 BNB** |
| **Total** | **≈ 0.00084 BNB** |

Two caveats on that table. The registration fee is **mutable** — `setRegistrationFee`
exists in the deployed bytecode, and the figure read today already differs from one read
by another party earlier the same day. Re-read it before you sign. And BSC gas at 0.05
gwei is unusually cheap; at 3 gwei the two transactions cost about 0.0006 BNB instead of
0.00001, which changes nothing material but is worth not being surprised by.

## 7. The commands

### 7.1 — Grant (owner, TypeScript)

Run §5. Record `session.publicKey`, the session signer address, and the wallet address.

### 7.2 — Read the authority (Docket, Python)

```bash
cd docket
./.venv/Scripts/python - <<'PY'
from docket.execution.authority import AltanaSessionAuthority, SessionRef, \
    SessionPermissions, CallPermission, SpendPermission

WALLET      = "0x..."   # the Altana account
SESSION_KEY = "0x..."   # session signer address
PUBLIC_KEY  = "0x04..." # session.publicKey, SEC1 uncompressed (65 bytes)
EXPIRY      = 0         # the unix seconds the grant in 5 was given
ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
USDT   = "0x55d398326f99059fF775485246999027B3197955"

permissions = SessionPermissions(
    calls=(CallPermission(to=ROUTER, signature="swapExactTokensForTokens"),
           CallPermission(to=USDT,   signature="approve")),
    spend=(SpendPermission(token=USDT, limit=30 * 10**18, period=86_400),),
)
ref = SessionRef(session_id="grid-proof-1", account=WALLET, key_address=SESSION_KEY,
                 chain_id=56, expiry=EXPIRY, public_key=PUBLIC_KEY)

authority = AltanaSessionAuthority(account=WALLET)
print(authority.status(ref, permissions=permissions).as_record())
PY
```

Expect `source: "chain"`, `revoked: false`, `valid: true`, `reads` naming the three
KeyStore/account calls, and `remaining_cap` showing the full 30 USDT.

### 7.3 — Preview the grid (Docket, Python — no session needed, and none used)

```bash
./.venv/Scripts/python - <<'PY'
from docket.hire.catalogue import _run_grid_operator
import json
print(json.dumps(_run_grid_operator({"wallet": "0x...", "size_per_level": 5 * 10**18}), indent=2))
PY
```

This is the same code path `POST /hire/grid-operator` serves. It holds no session and has
no method that submits. Read the level it says the price has reached, and its intent's
`min_output`, `calldata_hash` and `deadline`.

### 7.4 — Approve USDT to the router (owner or session, TypeScript)

One `approve` for exactly the cap, not `MaxUint256`. An unlimited approval outlives the
session and is the thing left behind after a revoke that a revoke does not undo.

### 7.5 — Draft, simulate, decide and submit (Docket + a submitter)

`GridOperator` refuses to be constructed without a `submitter`. Supply one that signs the
intent's calldata with the session key and sends it through Altana's relay — that is the
TypeScript half. The operator draws the level, drafts the intent, quotes it, refuses if
the quote is below the intent's floor, asks the chain whether the session permits the
exact call, and only then hands the calldata to the submitter.

Keep the receipt it returns. It carries the intent, the intent key, the plan hash, the
simulation, the authority status with its `source` field, the cap before, the lifecycle
and the transaction hash — and a `receipt_hash` anyone can recompute.

### 7.6 — Revoke (owner, TypeScript)

```ts
const result = await client.revokeSession({ wallet, signer: ownerSigner, session });
if (result.status !== "CONFIRMED") throw new Error(`revoke ${result.status}`);
```

**A failed revocation returns `status: "FAILED"` rather than throwing.** Check the field.
Do not treat "no exception" as revoked.

## 8. The six checks

Run each one and record the answer. Every one is checkable by a stranger.

| # | What | How to check it yourself |
| --- | --- | --- |
| 1 | Session registered | `KeyStore.getKeys(wallet)` contains `keccak256(session.publicKey)`; `KeyStore.isValidKey(wallet, keyId)` is `true` |
| 2 | Intent simulated and agreed | the receipt's `simulation.agrees` is `true`, `checks` lists `router.getAmountsOut`, and `expected_output ≥ intent.min_output` |
| 3 | One confirmed swap | the transaction hash on BscScan, `Success`, one `Swap` event on the WBNB/USDT V2 pair, and the calldata's keccak equal to the receipt's `intent.calldata_hash` |
| 4 | Cap decremented on chain | `account.spendInfos(keyHash)` for USDT: `limit - currentSpent` fell by the amount swapped. **`currentSpent`, not `spent`** — and the field named `current` is the start of the current period, a timestamp, not a balance |
| 5 | Revoked | `KeyStore.isValidKey` is now `false` and the key id is gone from `getKeys` |
| 6 | Post-revoke attempt refused | re-run 7.2 and 7.5. `can_execute` returns `(False, "the session has been revoked…")`, and the submitter is never reached |

Check 6 is the one worth doing twice. Docket refusing is not the claim; the claim is that
the chain would refuse even if Docket did not, and a session that has been revoked cannot
be reinstated — revocation is monotonic in Altana v1.0.0, so this is a one-way door.

**The two key identifiers are not the same value and are the likeliest way to get a
wrong answer here.** The KeyStore files a key under `keccak256(publicKey)` — the 65-byte
SEC1 blob. The wallet's own key table files the same key under
`keccak256(abi.encode(uint256(2), keccak256(pad32(sessionAddress))))`. Docket exposes both
as `docket.execution.authority.keystore_key_id` and `account_key_hash`; use those rather
than deriving them by hand.

## 9. Rollback

There is no rollback for a confirmed swap, and pretending otherwise would be the wrong
shape of comfort. What there is:

1. **Revoke immediately** (7.6) at the first sign of anything unexpected. It is one
   transaction, it is monotonic, and it costs no fee — revocation calls the KeyStore
   directly.
2. **Let the expiry run.** The grant is 24 hours. Doing nothing is a valid response.
3. **Withdraw the USDT** from the wallet. A session with a cap over an empty balance can
   spend nothing.
4. **Reduce the approval to zero.** The revoke removes the session's authority; it does
   not remove an ERC-20 allowance already granted to the router.

One trap: **revoking a key id that was never registered reverts**, and because the bundle
is atomic it takes the rest of the revoke down with it. The SDK guards this by checking
`isValidKey` first. If you drive `KeyStore.revokeKey` directly, do the same.

A second: revocation is per chain. If the key was ever mirrored to another chain's cache,
that cache keeps answering `isValidKey == true` until a post-revocation proof is pushed to
it. This proof never leaves chain 56, so it does not arise — but do not carry the habit.

## 10. Links to check each step

| What | Where |
| --- | --- |
| Altana KeyStore (chain 56) | `https://bscscan.com/address/0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a` |
| KeyStoreController (chain 56) | `https://bscscan.com/address/0x0834Ee2C9BdC3E3efF0a2dC34393D4B0e546A555` |
| The wallet's own account | `https://bscscan.com/address/<wallet>` |
| PancakeSwap V2 router | `https://bscscan.com/address/0x10ED43C718714eb63d5aA57B78B54704E256024E` |
| USDT (18 decimals on BSC) | `https://bscscan.com/token/0x55d398326f99059fF775485246999027B3197955` |
| The swap | `https://bscscan.com/tx/<hash>` |
| The grant | `https://bscscan.com/tx/<hash>#eventlog` |
| The revoke | `https://bscscan.com/tx/<hash>#eventlog` |

Two things about that table are worth stating rather than assuming. Whether these
contracts are **source-verified on BscScan has not been established** — bscscan.com was
not reachable from the machine this was prepared on. And Altana's KeyStore Solidity is not
published anywhere public, so the ABI Docket reads it with is the subset Altana's own SDK
vendors, matched against the deployed runtime bytecode rather than against source anybody
can read. That is a weaker footing than reading verified source, and it is the footing
this proof stands on.

## 11. What was checked before this was written

From this machine, on 2026-08-10, over the BSC failover list:

- KeyStore `0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a`: **8,756 bytes** of code on chain
  56, `VERSION()` reads `1.0.1`, and `isValidKey` / `getKeys` answer correctly for an
  address holding no keys.
- KeyStoreController `0x0834Ee2C9BdC3E3efF0a2dC34393D4B0e546A555`: 3,609 bytes.
- Account implementation `0x4B5d20CD8a3927B500540d9BcCDDc27385c9fA79`: 23,384 bytes, and
  the selectors for `spendInfos`, `canExecute`, `getKeys`, `getKey`, `keyCount` and
  `spendAndExecuteInfos` are all present in that runtime bytecode.
- Every ABI fragment in `docket/execution/authority.py` re-encodes to the selector found
  in the deployed code; a test asserts it.

And what was **not**: no live Altana session on BSC mainnet was found to read, so the
spend-cap and `canExecute` paths have been exercised against fakes and against empty
state, never against real session data. §4 exists to close exactly that.
