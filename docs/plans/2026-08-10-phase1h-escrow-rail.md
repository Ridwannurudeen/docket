# Docket Phase 1h — ERC-8183 escrow rail on mainnet

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Docket's second hire rail — the "real job" one — for buyers who want funds held in escrow rather than paid per call. x402 already serves "try this agent now"; this serves "I am hiring you for a job", which is the rail TermiX's own platform runs on.

**Architecture:** Server-side reads and machine-readable instructions, not browser signing. Docket never holds a buyer's key and never asks for one: it publishes the exact ordered call sequence with encoded calldata, reads the resulting job's live state from chain, and — once the dispute window elapses — can close the job itself, because `settle()` turns out not to care who calls it. The buyer signs in whatever wallet or script they already use.

**Tech Stack:** Existing pins only (`web3==7.16.0`, `eth-account==0.13.7`, FastAPI). No new dependencies, and no bundler: the web UI is dependency-free today and stays that way.

## What changed since the design spec, and why this plan departs from it

Spec §4.3 routes judge-facing escrow hires to **testnet** for its 1-day dispute window, and has the browser sign raw ABI calls through wagmi/viem. Both are now wrong, and `experiments/e1c-result.json` is the evidence:

- **Testnet escrow is closed.** The only policy testnet jobs bind (`0x4F46…B78A6`) reads `policyWhitelist == false`, so `registerJob` reverts `PolicyNotWhitelisted` and nothing new can be funded there. The jobs already bound to it registered before the whitelist was withdrawn. The router owner (`0x1001b2…D134`) is not ours, so this is not state Docket can repair, and no amount of building routes around it.
- **Mainnet is open**, and is therefore the only chain this rail can run on. Its cost is a hard **7-day** dispute window, and `OptimisticPolicy` has no client-accept path at all — a funded job cannot settle early however willing both sides are.
- **`settle()` is not gated on the caller.** A stranger address, party to nothing, settles a ripe job in `eth_call`. That is what makes a 7-day window survivable: Docket closes the job itself the moment it ripens, instead of asking a buyer to come back a week later.
- **wagmi/viem is out of reach** without adding a bundler and a JS dependency tree to a UI that currently has neither. Publishing exact calldata is the smaller, honest answer, and it serves the agent-facing door — scored at 20% — better than a browser wallet flow would.

Verified live on BSC mainnet 2026-08-10, all by `eth_call`: commerce `0xEa4DAa3100A767e86FDed867729ae7446476EBA6` (`paused=false`, `platformFeeBP=0`, `MAX_EXPIRY_DURATION=31536000`, `HOOK_GAS_LIMIT=1000000`), router `0x51895229E12F9876011789B04f8698af06cCD6DA` (unpaused), policy `0x9C01845705b3078Aa2e8cfF7520a6376FD766dE5` (whitelisted, `disputeWindow=604800`, quorum 3 of 5), payment token `commerce.paymentToken() = 0xcE24439F2D9C6a2289F741120FE202248B666666` (symbol `U`, 18 decimals).

## Global Constraints

- **Docket never takes a buyer's key**, never proxies a signature, and never holds escrowed funds. It publishes calldata and reads chain state. Any design that needs a buyer secret is out of scope, not a later task.
- **The 7-day window is stated everywhere it is relevant, never buried.** A buyer who learns about it after funding has been misled by omission. It belongs in the terms, in the job state, and on the page — as a concrete settle-eligible timestamp, not "about a week".
- **The invariants are enforced in the builder, not documented and hoped for.** `evaluator` and `hook` must both be the router (`RouterNotEvaluator` otherwise); `registerJob` comes after `createJob` and before `fund` (`PolicyNotSet` otherwise); `submit` must land before `expiredAt` (`SubmissionTooLate`). A builder that can emit an invalid sequence will eventually emit one.
- **No state-reading `eth_call` gets a pinned historical block.** BSC full nodes prune and answer `missing trie node`; that is an infrastructure fault and must never be recorded as a contract verdict. Reuse E1c's classification: `ContractLogicError` is a result, everything else is an outage.
- **The settle worker ships disarmed.** Sending a transaction needs a funded Docket EOA, which is a user action; it must be impossible to broadcast by accident, and its absence must degrade to an honest "not armed" rather than a silent no-op.
- **The buyer's lever is `policy.dispute(jobId)`, client-only. Never surface `voteReject`** — it is restricted to whitelisted voters and wiring a buyer to it would produce a confusing revert.
- No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename.
- Repo `C:\Users\gudma\OneDrive\Desktop\GITHUB-FILES\docket`, run with `./.venv/Scripts/python`. Baseline is 187 tests green.

## File Structure

```
docket/escrow/__init__.py
docket/escrow/constants.py    # the verified mainnet addresses and windows, in one place
docket/escrow/chain.py        # read-only job state, with E1c's failover and fault classification
docket/escrow/flow.py         # the ordered call sequence + encoded calldata, invariants enforced
docket/escrow/settle.py       # builds settle(); broadcasts only when explicitly armed
docket/api/routes.py          # MODIFY: GET /escrow, GET /escrow/job/{job_id}
docket/api/static/llms.txt    # MODIFY: both paths (the drift guard requires it)
docket/api/static/SKILL.md    # MODIFY: the escrow workflow
tests/test_escrow_constants.py
tests/test_escrow_chain.py
tests/test_escrow_flow.py
tests/test_escrow_settle.py
tests/test_escrow_api.py
```

---

### Task 1: Verified constants, in one place

**Files:** Create `docket/escrow/__init__.py`, `docket/escrow/constants.py`, `tests/test_escrow_constants.py`

- [ ] **Step 1: Write the test.** Assert every address is checksummed; `DISPUTE_WINDOW_S == 604800`; `CHAIN_ID == 56`; and that a `VERIFIED_ON` date string is present, because a constant copied from a spec without a date is a constant nobody can re-check.
- [ ] **Step 2: Implement.** Addresses, `DISPUTE_WINDOW_S`, `MAX_EXPIRY_DURATION_S`, the RPC failover list, and a comment naming `e1c-result.json` as the evidence. Testnet constants are deliberately absent: there is no testnet rail, and leaving them in the file invites someone to try.
- [ ] **Step 3: Run** → 187 + 4.
- [ ] **Step 4: Commit** `git commit -m "feat(escrow): the verified mainnet constants for the ERC-8183 rail"`

---

### Task 2: Read a job's real state

**Files:** Create `docket/escrow/chain.py`, `tests/test_escrow_chain.py`

**Interfaces:** `job_state(job_id) -> dict` returning `status` (name, not the raw enum), `client`, `provider`, `budget_atomic`, `expired_at`, `submitted_at`, `policy`, `disputed`, `settle_at`, `settle_ready`, and `read_at_block`.

- [ ] **Step 1: Write the test** against a fake web3 double, not the live chain: the status enum maps to names; `settle_at` is `submitted_at + DISPUTE_WINDOW_S` and is `None` before submission rather than a misleading zero; `settle_ready` is false while disputed even when the window has passed; an RPC outage raises rather than returning a job that looks unfunded; and a `ContractLogicError` is classified as a contract answer, not an outage.
- [ ] **Step 2: Implement**, reusing E1c's `Rpc` failover shape and its `ContractLogicError` re-raise. Read the job through `getJob`, addressing fields **by name from the ABI outputs, not by tuple index** — E1c wasted a run reading `[-1]` as status when status is field 7 and the last field is `deliverable`.
- [ ] **Step 3: Run** → +6.
- [ ] **Step 4: Commit** `git commit -m "feat(escrow): read a job's live state, with faults told apart from verdicts"`

---

### Task 3: The call sequence, with the invariants enforced

**Files:** Create `docket/escrow/flow.py`, `tests/test_escrow_flow.py`

**Interfaces:** `hire_calls(provider, budget_atomic, expires_in_s, description) -> list[dict]`, each entry `{step, to, function, args, calldata, note, must_precede}`.

- [ ] **Step 1: Write the test.** The sequence is exactly `approve → createJob → registerJob → setBudget → fund`, in that order; `createJob`'s `evaluator` and `hook` are both the router; `registerJob` binds the whitelisted policy; `approve` is for at least the budget against the commerce contract; `expires_in_s` above `MAX_EXPIRY_DURATION_S` is rejected with a named error rather than silently clamped; every `calldata` decodes back to the stated function and args through the ABI; and the returned notes state the 7-day window and that `submit` must land before `expiredAt`.
- [ ] **Step 2: Implement.** Encode with `web3`'s ABI encoder against the vendored artifacts, so the calldata cannot drift from the ABI the reads use. No network access in this module — it is a pure function of its arguments, which is what makes it testable without a chain.
- [ ] **Step 3: Run** → +8.
- [ ] **Step 4: Commit** `git commit -m "feat(escrow): the hire call sequence, with its invariants enforced in the builder"`

---

### Task 4: Settle, disarmed by default

**Files:** Create `docket/escrow/settle.py`, `tests/test_escrow_settle.py`

**Interfaces:** `settle_calldata(job_id) -> dict`; `can_settle(job_id) -> dict` (an `eth_call` dry run, returning `ready`/`reason`); `settle(job_id) -> dict` which refuses unless `DOCKET_SETTLE_KEY` is set.

- [ ] **Step 1: Write the test.** `settle()` with no key configured raises a named `NotArmed` error and **makes no network call at all**; `can_settle` maps a `NotDecided` revert to a plain-language reason rather than a selector; and a job still inside its window reports the timestamp it becomes eligible. Assert no test in the suite can broadcast: the signing path is only reachable through the env var, and the suite never sets it.
- [ ] **Step 2: Implement.** `can_settle` is the `eth_call` dry run E1c already proved works. The broadcast path builds, signs and sends — but is dead code until a key exists.
- [ ] **Step 3: Run** → +5.
- [ ] **Step 4: Commit** `git commit -m "feat(escrow): settle a ripe job, disarmed until a key exists"`

**USER-GATED, not part of this phase:** arming it needs a funded Docket EOA on BSC mainnet (gas only, no $U). Do not create or fund a key without explicit approval.

---

### Task 5: Both front doors

**Files:** Modify `docket/api/routes.py`, `docket/api/static/llms.txt`, `docket/api/static/SKILL.md`; create `tests/test_escrow_api.py`

- [ ] **Step 1:** `GET /escrow` — the terms: addresses, the payment token and its decimals, the dispute window in seconds *and* as a plain sentence, the ordered call sequence as a template, the buyer's dispute lever, and what Docket does and does not do. `GET /escrow/job/{job_id}` — live state from Task 2, with a structured error for a job id that does not exist.
- [ ] **Step 2: Tests.** Both paths return 200 with the documented shape; an unknown job returns the project's structured error, not a 500; `/escrow` states the 7-day window; the response carries no verdict field (the existing contract ban); and `llms.txt` documents both new paths, since the existing drift guard requires every OpenAPI path to appear there.
- [ ] **Step 3: Run** → ~+7, suite green.
- [ ] **Step 4: Commit** `git commit -m "feat(escrow): publish the escrow terms and live job state on both doors"`

---

## Self-review (done at write time)

- This is the spec's "never cut" hire flow completed: x402 for a trial call, escrow for a real job. It departs from the spec on chain and on signing, and both departures are evidenced rather than asserted — `e1c-result.json` for the chain, the absent JS toolchain for the signing.
- The largest risk is that **no judge ever exercises this rail**, because it needs $U, gas, and a 7-day wait. That is honestly a real possibility, and the mitigation is not to hide the friction but to make the rail legible: an evaluator agent can read `/escrow`, see the whole sequence, and verify it against chain without spending anything. A rail that can be *audited* for free is worth more here than one that is merely claimed.
- The second risk is the settle worker becoming a footgun. It ships disarmed, its tests assert it cannot reach the network unarmed, and arming it is a user action.
- Deliberately out of scope: browser wallet signing, a testnet path (closed), and any UI beyond the two endpoints. The job-state web panel is a candidate for a later phase and is the first thing to cut if capacity bites.
