# Docket — Codex Strategic Assessment

## Executive verdict

**Docket is a serious evidence observatory with a small machine-hire layer. It is not yet the product BNB described.** Today, a user can inspect registry claims and one-time endpoint observations, and a coding agent can call three hard-coded Docket services. A human cannot browse by BNB's four categories, compare hireable agents, activate one, or manage an active session. The discovered registry inventory and the hireable service inventory are separate systems with no join key.

My current competitive read is:

| Track | Current position | Why |
| --- | --- | --- |
| BNB main track | **Not competitive yet** | The full human journey is absent, the data is neither real-time nor decision-deep enough, and Docket has **zero** rubric-complete categories. |
| TermiX | **Eligible, but not first-place evidence** | The report format and epistemic discipline are excellent. The underlying service-value results are mixed, repeated track records are absent, and the paid hire does not settle. |
| PancakeSwap | **Legitimate fit, not yet a decisive fit** | Range Doctor provides real LP benefit and structural fund safety, but it neither manages liquidity nor proves improved outcomes or PancakeSwap volume/TVL. |
| Altana | **No implementation; eligibility not established here** | A session-key action path could become a credible rider, but the current repository contains no Altana code or dependency and the official Altana rubric is not in the verified briefing. |

The winning move is not to abandon Docket's evidence discipline. It is to **turn that discipline into the evidence plane of a category-first activation product**, then add a separate policy and execution plane. The product sentence should become:

> **Choose a job. See the evidence. Set the authority. Activate the agent.**

The raw registry explorer remains valuable, but it becomes a research surface, not the primary user journey.

## Audit basis

I read the briefing, all phase plans, and the requested source areas; I independently inspected the data store, live site, API schema, and repository state. I did not use `FABLE-AUDIT.md` in forming this assessment.

Verified during this audit:

- Repository HEAD was `9c6101b`; `docs/deliberation/` was untracked before this file.
- `./.venv/Scripts/python.exe -m pytest -q` passed **225 tests** with two dependency deprecation warnings.
- `https://docket.gudman.xyz/health` returned 200 with snapshot 3; the live `/hire` catalogue exposed the three expected services; live `/escrow` returned 404.
- GitHub reported `Ridwannurudeen/docket` as **PRIVATE** with no license metadata. No tracked README, LICENSE, SECURITY, CONTRIBUTING, deployment manifest, or `AI_USAGE.md` exists.
- Snapshot 3 was captured on 2026-08-07 and contains 506 of 506 agents **inside the `min_feedbacks >= 1` query**, not the complete BSC registry. The local database also contains an unfinished snapshot 2 with 101,500 rows against an expected 247,146.
- The briefing's only fact about BNB Phase 2 is that its criteria are undisclosed (`docs/deliberation/BRIEFING.md:28`). I make no claim to know them. Phase 2 recommendations below are explicitly diligence inferences.

## What Docket genuinely got right

These are assets to preserve, not rewrite:

1. **The evidence mechanics are substantive.** Snapshot-scoped storage, expected/sample counts, endpoint enrichment, and append-only liveness history exist (`docket/store.py:15-67`, `docket/store.py:91-155`, `docket/store.py:204-282`). Ingestion counts from stored unique rows, notices registry growth, and stops a non-advancing paginator (`docket/ingest.py:46-89`).

2. **The no-verdict contract is real.** Signals are pure observable facts (`docket/signals.py:40-50`), banned global-verdict field names are enforced in response models (`docket/api/models.py:14-29`), and the API carries explicit coverage objects (`docket/api/models.py:32-43`). This is a genuine differentiator in an agent market full of unsupported badges.

3. **Liveness was approached with unusual care.** DNS failure is kept separate from policy refusal; redirects are not followed; a rejected target is not contacted (`docket/netguard.py:15-21`, `docket/liveness.py:72-91`). The outcome vocabulary states less than most marketplace status badges do.

4. **Range Doctor contains real PancakeSwap-specific work.** It enumerates directly held and MasterChef-staked v3 positions, labels stale `tokensOwed` correctly, fails over per RPC call, subtracts the protocol fee from gross fees, and refuses implausible pool rows (`docket/agents/pancake/positions.py:10-33`, `docket/agents/pancake/pools.py:105-153`). This is not a generic LLM wrapper.

5. **The machine-facing cold path is strong.** `/llms.txt`, `SKILL.md`, OpenAPI, stable error shapes, a static service catalogue, free execution, and recomputable receipts make it possible for a coding agent to get work without setup (`docket/api/routes.py:325-356`, `docket/api/routes.py:477-495`, `docket/api/routes.py:607-717`; `docket/hire/receipts.py:27-50`).

6. **The Advantage Report tells the truth even when it hurts.** It publishes single-run limitations, incompatible clock methods, lack of correctness measurement, the trading non-answer, and the security loss in the first summary (`docket/api/web/advantage.html:101-130`, `docket/api/web/advantage.html:158-188`). That honesty is worth retaining.

7. **The ERC-8183 investigation created useful protocol knowledge.** The local code knows the real mainnet sequence, seven-day dispute window, live job state, and permissionless settlement path (`docket/escrow/flow.py:115-206`, `docket/escrow/chain.py:165-223`, `docket/escrow/settle.py:116-160`). The problem is product fit and deployment, not that the work is fake.

## 1. Where Docket genuinely falls short

### BNB main track

BNB gives equal weight to Functionality, Data Quality, and Agent Diversity, and explicitly requires four equally deep categories (`docs/deliberation/BRIEFING.md:18-27`). Docket is currently weak on all three—not only Diversity.

#### Functionality: the required journey does not exist

The rubric asks for land → find by category → understand → activate, with no Agent Studio knowledge and no dead end (`docs/deliberation/BRIEFING.md:17`, `docs/deliberation/BRIEFING.md:25`). Current behavior is:

- Browse exposes only `has_feedback`, `declares_callable`, `responded`, and `publisher` filters (`docket/api/web/browse.html:70-101`; `docket/api/routes.py:376-425`). There is no category field anywhere in `AgentSummary` (`docket/api/models.py:46-58`).
- The listing links to an evidence page. The detail page renders declarations, endpoint observations, and snapshot coverage, then ends (`docket/api/web/app.js:684-743`). It has no hire, try, activate, wallet, session, or payment control.
- `/hire` is a separate JSON catalogue of three Docket-owned callables. `Service` has no `agent_id`, category, registration, evidence link, availability history, or track record (`docket/hire/catalogue.py:52-65`, `docket/hire/catalogue.py:114-205`). A user who found an ERC-8004 agent cannot hire it; a user who hires a Docket service cannot inspect the corresponding ERC-8004 identity.
- The paid x402 branch verifies an authorization but explicitly does not settle it. It also does not verify the signing domain's token contract, remember nonces, or enforce `validAfter` (`docket/hire/x402.py:11-31`). This is accurately labeled `verified_unsettled`, but it is not a completed paid hire.
- ERC-8183 is an API template, not a few-click product; the phase plan deliberately excludes browser signing and UI (`docs/plans/2026-08-10-phase1h-escrow-rail.md:105-121`), and production does not serve it.

The current human journey is therefore **land → inspect → stop**. Calling this a polish problem understates it; the product seam is missing.

#### Data Quality: honest but not sufficiently deep, fresh, or internally precise

BNB asks for real-time data that lets a user make a genuinely informed hiring choice (`docs/deliberation/BRIEFING.md:26`). Current agent comparison data is name, description, owner, aggregate feedback count, declared protocols, x402 declaration, a name-family heuristic, and whether a host answered one GET. A 404 counts as an answer by design (`docket/api/web/app.js:699-729`). That is honest reachability evidence, but it does not establish capability, task quality, price/value, outcome history, or risk.

There are also four integrity issues that should be repaired before Docket leans harder on “evidence” as the moat:

1. **The snapshot population filter is lost.** `_sweep` knows the expected total belongs to a `min_feedbacks` query (`docket/ingest.py:41-49`), but the snapshot table stores only chain, counts, and timestamps (`docket/store.py:15-23`). `ingest_targeted` returns `min_feedbacks` transiently and never persists it (`docket/ingest.py:113-140`). Consequently `/stats` presents snapshot 3 as complete 506/506 and 100% feedback without carrying “this universe was prefiltered to agents with feedback” in the primary coverage object (`docket/api/routes.py:358-374`). This is the filtered-total conflation the ingest docstring itself warns against (`docket/ingest.py:128-130`).

2. **“35 endpoints probed” is the wrong label.** Blocked and unresolved targets return before `client.get` (`docket/liveness.py:72-81`), yet `probe_snapshot` and `coverage_report` count every observation as probed (`docket/liveness.py:124-131`; `docket/coverage.py:45-47`). Snapshot 3 contains 13 responses, one timeout, 10 policy blocks, and 11 unresolved names: **35 targets evaluated, 14 HTTP attempts, 13 responses**. The published 37.143% is 13/35, not a response rate “of endpoints actually probed.” Publish both denominators; do not replace one ambiguity with the flattering 13/14 alone.

3. **“Publisher” is not publisher provenance.** For ordinary names, `publisher_key` takes the first word of the agent name; it uses owner only for empty/placeholder names (`docket/signals.py:28-37`). In snapshot 3, 421 generated “publisher” keys correspond to only 167 current owner addresses; 22 keys span owners and 53 owners span keys. Rename this to `name_family` now, then derive publisher/minter provenance from chain history later.

4. **The data is static and unsafe to promote automatically.** `create_app` chooses a snapshot once at process startup (`docket/api/routes.py:191-215`); there is no scheduled ingestion/probe workflow or package CLI. Worse, `latest_snapshot_id` does not require `finished_at` (`docket/store.py:157-163`), so a newly crashed sweep can become the next served snapshot after restart. The existing unfinished snapshot 2 proves this is not hypothetical state.

The SSRF boundary also needs one real hardening pass: Docket vets one DNS resolution, then hands the hostname to `httpx`, which resolves it again when connecting (`docket/netguard.py:77-89`; `docket/liveness.py:72-81`). That leaves a DNS-rebinding/TOCTOU gap. The probe also buffers a full response although it only needs status. This matters more once Docket runs continuously.

#### Agent Diversity: zero of four at the stated bar

The opening brief says Yield is covered and three categories are missing. I disagree. By BNB's own definitions, Docket currently has **zero rubric-complete categories**:

- **Rebalancing:** Range Doctor diagnoses a range and links to PancakeSwap. It does not manage the range or reset it automatically. Its action objects are conditional prose and a position URL (`docket/agents/pancake/doctor.py:141-166`, `docket/agents/pancake/doctor.py:298-316`).
- **Grid Trading:** no grid plan, order state, keeper, swap execution, or grid track record exists.
- **Yield Optimisation:** Range Doctor quotes the current pool's one-day annualized net fee rate when the row passes a plausibility gate. It neither searches a defined eligible universe for the highest observed APR nor routes liquidity there (`docket/agents/pancake/doctor.py:74-78`, `docket/agents/pancake/doctor.py:267-295`). Calling the experiment `yield/LP` does not satisfy the rubric's routing definition.
- **Health Factor Monitoring:** no lending position adapter, health-factor observation, monitor, alert, repay, or collateral action exists.

The schema reinforces this absence: `agents` has no category, category-specific evidence, price, activation, or performance window (`docket/store.py:24-39`). This is not “data-and-config-shaped.” Adding three labels would create four shallow shelves and likely make the submission less credible. It requires a marketplace ontology, four real service verticals, uniform evidence, and an activation/session model.

#### Adoption readiness: Docket is not yet a layer BNB can take over and grow

BNB describes adoption of a standalone product and team, not a one-off award (`docs/deliberation/BRIEFING.md:15-17`). Current adoption blockers include:

- hard-coded inventory in a Python dictionary rather than provider onboarding;
- dependence on an undocumented/internal 8004scan HTTP surface (`docket/scan8004.py:1-9`) rather than a durable chain-derived index;
- no persisted hire/action history or conversion funnel—the receipt is returned and discarded;
- synchronous in-request service work and in-memory, per-process allowance state;
- no scheduled freshness, service-level canaries, deployment manifest, operator runbook, or public reproducibility path;
- private repository, absent license and top-level product documentation.

The 225 green tests prove implementation mechanics. Because `data/` is ignored and API tests use synthetic stores, they do not independently reproduce the production dataset or live marketplace behavior.

### TermiX

The report satisfies an eligibility shape. It does not yet make a strong case on TermiX's weighted merits (`docs/deliberation/BRIEFING.md:31-34`).

| Criterion | What exists | Why it falls short |
| --- | --- | --- |
| Value of services — 30% | Range diagnosis, historical regime provenance, prompt-injection telemetry | Range is useful but thinner than the manual arm in several respects; SOLVENT is a stale historical record and does not verify its own provenance; Warden returned one of four hostile vectors. |
| Proven advantage — 30% | Three honest agent/manual records with hashes, time, cost, outputs, and notes | Every figure is one observation with no error bar, clock methods differ, and the page explicitly declares correctness out of scope (`docket/api/web/advantage.html:101-130`). Only liquidity clearly answers the task; trading supplies material but not proof; security loses. |
| High-stakes record — 20% | Trading and security labels | No win rate, evaluation window, exposure, drawdown, risk budget, repeated sample, or null baseline exists. The SOLVENT service explicitly says it is not a live feed or correctness/profitability proof (`docket/hire/catalogue.py:149-170`). |
| Marketplace quality — 20% | Excellent machine documentation and a free first call | The raw discovery catalogue and service catalogue are disconnected; humans cannot hire; services cannot be compared on result evidence; paid settlement is absent. |

The deeper disagreement is conceptual: **“Docket does not issue global trust verdicts” does not imply “correctness is out of scope.”** Docket should refuse an unqualified `trust_score`, `best`, or `safe`. It should absolutely measure bounded task correctness against a precommitted ground truth and publish numerator, denominator, dataset hash, method, window, costs, and failure cases. That is evidence, not endorsement.

TermiX's own hostility to suspiciously perfect rates and its use of null models supports this distinction (`docs/deliberation/BRIEFING.md:34`). A v2 Advantage Report should compare agent, manual, and null baselines across repeated blinded tasks. Keep the current report immutable as v1; do not overwrite or hide the losses.

### PancakeSwap

Claude's “soft fit” is fair as a statement of competitive strength, but not as a compliance diagnosis. PancakeSwap explicitly accepts smarter liquidity management as one of several valid benefits; execution is not mandatory (`docs/deliberation/BRIEFING.md:36-38`). Range Doctor's net-fee arithmetic, staked-position enumeration, range status, pool-data rejection, and structural inability to move funds are substantive.

Why it is not yet winning-grade:

- It reports stale `tokensOwed` and explicitly does not simulate current collectable fees (`docket/agents/pancake/positions.py:19-25`).
- It answers primarily in ticks even though the user needs token prices and amounts; the Advantage Report calls this out (`docket/api/web/advantage.html:195-211`).
- It quotes a current pool rate but does not compare an explicit eligible pool universe, include farm emissions, compute switching break-even, or route yield.
- It is a one-shot request, not a monitor. There is no time-in-range history, alert, automated reset, or measurement that the doctor increased fee-earning time or retained TVL.
- Its “actions” are links, not a prefilled transaction plan, simulation, authorization, or execution receipt.
- It supports PancakeSwap v3 positions only. That can be an acceptable deliberate scope, but it must not be presented as all PancakeSwap liquidity.

The strongest PancakeSwap submission is therefore not “we added a signer.” It is **read → explain → simulate → act within a hard cap → publish before/after outcome evidence**, with at least one real, user-approved, tiny on-chain proof.

## 2. Direct disagreements with the opening “Honest gaps”

1. **Gap 1 is understated:** current coverage is zero of four at rubric depth, not one of four; the fix is not configuration.
2. **Gap 2 is understated:** the human activation journey is absent, not merely too skeptical or wordy.
3. **Gap 3 needs nuance:** Range Doctor is a valid PancakeSwap entry without execution, but action plus outcome measurement would make it materially stronger.
4. **Gap 4 overstates TermiX optimization:** Docket optimized for TermiX's epistemic style and report eligibility, not for the actual value/advantage/track-record score. BNB Data Quality is a potential strength, not yet a clean win because population, probe, freshness, and publisher semantics need correction.
5. **Gap 5 uses the wrong satisfaction test:** 506 unrelated BSC registry rows do not make Docket's three hireable services first-party BSC agents. Every flagship service needs an explicit identity/service/evidence binding.
6. **Gap 6 is correct where verifiable:** private repo, no license, and undeployed escrow are confirmed. Whether a person has read the Terms cannot be established from code. Add absent README, reproducible deployment, security/runbook documentation, and `AI_USAGE.md` to the closeout list.

Missing from the opening list entirely: the lost source-population filter, overloaded probe denominator, name-family-as-publisher label, static/unsafe snapshot promotion, DNS-rebinding gap, disconnected discovery/hire models, absent repeated track records, and lack of a real paid settlement.

## 3. How BNB breadth and TermiX evidence coexist

They coexist cleanly if Docket separates three responsibilities.

| Plane | Responsibility | What it may say/do | What it must not do |
| --- | --- | --- | --- |
| **Fact plane** | Registry, protocol state, liveness, task outcomes, source provenance | “13 of 14 attempted requests responded”; “tick X is above bound Y”; “7 wins in 20 runs over dates A–B” | Global safety/trust/recommendation verdicts |
| **Policy plane** | Evaluate the user's explicit objective and constraints | “Observed inputs satisfy 4 of your 5 stated predicates”; show the failed predicate and inputs | Quietly choose the user's risk appetite or hide defaults |
| **Action plane** | Simulate and execute only authorized actions | Exact target, calldata commitment, cap, expiry, nonce, before/after receipt | Hold the owner key, invent broader authority, or rely on a server-only cap |

The current no-verdict contract stays on the fact plane. The mistake would be applying it to bounded measurements or user-authored policy predicates.

### One marketplace object, not two catalogues

Add a first-class service/capability model, conceptually:

- `service_id` and bound BSC `agent_id`/registration URI;
- exactly one primary BNB category plus explicit secondary tags;
- claimed capability, declared protocol, input/output schema, price, typical delivery time;
- activation mode: one-shot, monitor, or policy-controlled action;
- availability observations and category-specific benchmark records;
- every metric as `{value or numerator/denominator, unit, window, observed_at, source, method, evidence_hash}`;
- session requirements and revocation support;
- current limitations stated alongside the primary claim.

Keep `/agents` as the raw registry/evidence API. Add a curated `/services` or `/marketplace` API joined to it. Move the raw 506-row browser under a “Research the registry” navigation item; make the four job categories the home page.

### Equal depth must be an acceptance contract

A category does not count until it has all of these:

1. a BSC ERC-8004 identity bound to a live callable service;
2. current, category-specific protocol state with provenance;
3. a no-wallet sample run and a user-wallet preview;
4. an explicit policy/plan with costs, assumptions, and failure states;
5. a working activation path;
6. for fund-moving agents, an on-chain-enforced cap, expiry, pause, and revoke path;
7. post-run receipts and a repeated track record with sample/window/risk;
8. identical UX depth: understand, preview, activate, observe, pause/revoke.

The four products should be:

| Category | Product to build | Read/plan depth | Bounded action | Evidence that matters |
| --- | --- | --- | --- | --- |
| Rebalancing | **Range Keeper** built on Range Doctor | Exact v3 position state, current collect simulation, token prices, range policy, gas/IL/switch cost | Reset only compatible smart-account-held positions under user-specified width, threshold, cooldown, slippage, gas, and token caps | Time in range; fees net of protocol cut, gas and realized IL; passive-position baseline; n/window |
| Grid Trading | **Grid Operator** | User-defined levels, size per level, trigger source/window, quote and slippage simulation | Submit only pre-authorized exact-input PancakeSwap swaps; per-level nonce, cooldown, cumulative token cap | Net P&L after fees/slippage/gas; fills; exposure; max drawdown; null/passive baseline; n/window |
| Yield Optimisation | **Yield Router** | Explicit eligible universe, allowlist, net APR components, capacity, gas and switching break-even | Move only approved assets among approved destinations when the user's threshold remains true | Realized net yield, time deployed, switch costs, adverse movements, candidate-universe coverage; n/window |
| Health Factor Monitoring | **Health Guard** | One verified BSC lending adapter first; collateral, debt, health factor, liquidation threshold, freshness | Conservative actions only: capped repay or supply-collateral; no borrow or withdraw permission | Detection/intervention latency, before/after health factor, failed actions, cap usage; never claim a counterfactual liquidation was “prevented” without a defined simulation |

Build one adapter per category deeply. Multiple shallow protocols do not satisfy equal depth.

### “Few clicks, zero knowledge” without epistemic dishonesty

The default human journey should be:

1. Land on four plain-language jobs: “Keep LP earning,” “Run a capped grid,” “Move idle liquidity,” “Protect a loan.”
2. Choose a job and run a sample instantly, or paste/connect a wallet for a personal preview.
3. See a one-screen result: what was observed, what would happen, maximum authority, cost, and the main limitation. Exact evidence lives in an expanded drawer, not in the way of the primary action.
4. Choose a clearly specified policy template or edit its numbers. Docket describes the mechanics; it does not call a template best or safe.
5. Authorize once. The session page immediately shows status, next condition, remaining cap, expiry, receipts, Pause, and Revoke.

The target interaction is category → preview → authorize, with wallet connection deferred until value movement is requested. Agent Studio, ERC numbers, ABI calls, and payment dialects remain in the advanced/API surface.

Comparison can remain no-verdict: default ordering is recency or name, and a user may sort by an explicitly chosen observed metric. “Matches the constraints you entered” is legitimate; “Docket recommends this agent” is not.

## 4. Should an agent act on PancakeSwap?

**Yes—build a separate, tightly scoped Pancake Operator execution plane. Do not put a key inside Range Doctor.**

Range Doctor should remain the independently testable, read-only observation engine. Its output becomes an input to Range Keeper's planner. This preserves the strong property that the diagnosis itself cannot move funds and gives users a durable “inspect only” mode.

### Build order

1. **First executable recipe: Grid Operator exact-input swaps.** This is materially simpler than v3 NFT rebalancing, supplies BNB's missing Grid category, routes real PancakeSwap volume, and is the cleanest session-key demonstration.
2. **Second executable recipe: Range Keeper recentering.** Add only after current fee simulation, token/price amounts, exact protocol math, ownership/approval constraints, and an atomic simulation are correct. `tickmath.py` explicitly says its floats are display-grade and must never size a transaction (`docket/agents/pancake/tickmath.py:1-7`).
3. **Reuse the same action kernel for Yield Router**, then the same authority/session UI for Health Guard.

### Concrete authority design

The user grants a session to a smart account or verified session-wallet implementation. The owner key never reaches Docket. The authority record must enforce on chain, not merely in the API:

- chain ID and account;
- delegate/session key;
- `valid_after` and `valid_until`;
- exact allowed target contracts and function selectors;
- allowed input/output tokens and paths;
- per-token per-call and cumulative spend caps (not a vague USD cap that depends on an oracle);
- maximum native BNB gas spend;
- maximum actions, cooldown, and nonce/replay state;
- pause/revoke controlled by the owner;
- a commitment to the authorized policy or set of action intents.

A call allowlist plus spend cap is necessary but insufficient. A compromised agent could still make a permitted swap at a terrible price. Each autonomous action therefore also needs a semantic intent:

- evidence snapshot/block and strategy version;
- condition that must be true;
- exact target and calldata hash or bounded call template;
- maximum input, minimum output, route, slippage bound, deadline, and gas ceiling;
- unique idempotency key/nonce;
- user-authorized policy-root membership;
- successful preflight simulation against the account that will execute it.

The safest hackathon implementation is a finite policy bundle: the user authorizes a bounded set or Merkle root of grid-level intents once; the session key may submit an unused leaf only when its explicit condition is met. It cannot invent a new pair, route, amount, or approval.

The action state machine should be observable:

`draft → simulated → authorized → active → submitted → confirmed|failed`, with `paused`, `expired`, and `revoked` reachable from every pre-submission state.

Each receipt should bind the triggering observations, policy version, simulation result, signed authority, target/calldata commitment, transaction hash, confirmation block, before/after balances or position state, cap consumed, and any failure. A confirmed transaction proves execution, not benefit; outcome measurement remains a later observation.

For v3 rebalancing, support only positions controlled by the compatible smart account at first. An EOA's existing NFT cannot be managed merely because it authorized a session somewhere else. Avoid unlimited approvals; approval targets and amounts must be part of the session policy. If the decrease/collect/swap/mint sequence cannot be simulated and made safely atomic for the supported path, ship preview plus prefilled PancakeSwap UI instead of pretending automation is safe.

### Does this cheaply reopen Altana?

**Not today. It becomes a bounded rider after the generic action plane exists.** The current Python/static project has no Altana package, wallet adapter, session UI, executor, or transaction proof. The older design spec records an Altana wallet, KeyStore, call allowlist, spend cap, expiry, live validity/spend/revoke display, and V2-only Pancake skills as the intended route (`docs/specs/2026-08-06-docket-design.md:46-51`, `docs/specs/2026-08-06-docket-design.md:114`). Those SDK facts and the official partner rubric must be reverified immediately before implementation; they are not established by this briefing.

If current rules support that path, a credible Altana slice is:

1. implement `AltanaSessionAuthority` behind the generic session interface;
2. register a scoped key through Altana's native mechanism;
3. show live valid/expiry/allowlist/cap state in Docket;
4. execute one capped PancakeSwap grid leaf;
5. show spend-state decrement and transaction receipt;
6. revoke the key and prove a second attempt is rejected.

A generic session-key slide, a server-side cap, or a deep link does not reopen the track. Native registration plus bounded execution plus revocation proof does. If this adapter threatens four-category parity, cut the Altana adapter—not the shared action kernel.

## 5. What survives the `[REDACTED]` Phase 2 second look

We cannot optimize for undisclosed criteria. We can eliminate the failure modes that a second diligence pass normally exposes. The following are inferences from BNB's public adoption intent, not claims about the hidden rubric.

1. **A stranger can repeat the product, not only watch a demo.** Four categories work from a clean browser and wallet; sample mode has no setup; every failure has a recovery path.
2. **The second visit still works.** Scheduled data is fresh, only completed snapshots are promoted, endpoint/task canaries run continuously, and stale state is visible rather than silently served.
3. **Every flagship is real on BSC.** Each service is identity-bound, callable, and has at least one real task or tiny user-approved action receipt. “Registered inventory nearby” is not enough.
4. **Equal depth is visible without explanation.** The four cards share the same evidence, preview, activation, session, receipt, and track-record structure. No “coming soon,” stub, or read-only afterthought appears.
5. **Security survives adversarial reading.** The SSRF boundary is fixed; session limits are on-chain; semantic intents constrain allowed calls; replay, slippage, approvals, expiry, pause, and revoke are tested; an independent review has findings and remediations.
6. **Claims reproduce.** Snapshot population and query are persisted; raw source hashes and benchmark dataset hashes are published; task results have n/window/method; the negative v1 report remains accessible.
7. **The repository looks adoptable.** Public only after user approval, with license, README, architecture, setup, threat model, deployment/runbook, API examples, `AI_USAGE.md`, and green CI from a clean checkout.
8. **There is evidence of use, not vanity traffic.** Track time-to-first-result, category preview completion, activation conversion, successful/failed actions, repeat sessions, protocol volume/TVL routed, and cap/revoke use. Publish denominators and exclude internal/demo traffic.
9. **BNB can grow it without the founder hand-editing Python.** A provider can submit a signed manifest, bind an ERC-8004 identity, pass category canaries, price a service, and appear with its evidence—without a code deploy.
10. **The economics and operations are legible.** Per-task infrastructure cost, RPC/API dependencies, rate limits, failure queues, service SLOs, abuse controls, and rollback are documented.

The private repository, no license, no README, stale single snapshot, hard-coded services, and demo-only payment are exactly the kind of first-look polish that fails a second look.

## 6. Ambitious sequenced roadmap

### Hackathon sequence

#### Stage 0 — Repair the evidence contract before expanding it

Build first:

- In `docket/store.py` and `docket/ingest.py`, persist source, query/population predicate, expected-at-start/final, status, and a promoted/complete marker. Add `latest_complete_snapshot_id`; refuse chain/filter mismatch on resume.
- In `docket/liveness.py`, `docket/coverage.py`, API models, docs, and web copy, split `targets_evaluated`, `requests_attempted`, `responded`, `blocked`, and `unresolved`. Display both 13/35 target coverage and 13/14 attempted-request response where useful, never one unlabeled percentage.
- Rename the current `publisher` output to `name_family`; add a separately sourced owner/minter field when chain provenance exists.
- Close DNS rebinding by binding the vetted resolution to the connection, stream only enough response bytes to establish status, and add adversarial tests.
- Make the scheduled pipeline write a candidate snapshot, verify invariants, then atomically promote it. Never serve an unfinished sweep.
- Start precommitted benchmark and shadow-run logging now, because a real window cannot be manufactured in submission week.

**Exit gate:** a fresh run publishes its exact population, only complete data can become current, every liveness denominator is semantically true, and production-data assertions have an automated invariant check.

Why first: Docket cannot sell evidence while knowingly carrying denominator and provenance ambiguity. These repairs are smaller than the category build and protect every later claim.

#### Stage 1 — Unify discovery, evidence, and activation

Build:

- `docket/marketplace/` with service, category, metric/evidence, identity binding, price, activation mode, and session-status models.
- Store tables for services, capability claims, evidence records, availability canaries, hire/action receipts, and provider manifests.
- `/services`, `/services/{id}`, `/services/compare`, `/sessions/preview`, and session status endpoints; keep `/agents` unchanged as the raw fact API.
- A category-first home page, service detail, comparison view, preview form, and active-session page in `docket/api/web/`; move raw registry browsing to a secondary research route.
- Bind Range Doctor, SOLVENT, and Warden to explicit service records immediately; do not pretend a service is registered if it is not.

**Exit gate:** a cold human and a cold coding agent can choose a category, inspect a service, run a free preview, understand its limitation, and reach a real activation control without instructions.

Why second: this removes the split-brain architecture once, so the four agents land in a shared product rather than four bespoke demos.

#### Stage 2 — Build the shared policy/action kernel and Grid Operator

Build:

- `docket/execution/` for policy models, plan commitments, simulations, state transitions, receipts, idempotency, and revocation status.
- A session-authority interface with an on-chain-enforced implementation; add the Altana adapter only after current API/rubric verification.
- A narrow audited policy module or native wallet policy capable of target/selector/token/cap/expiry/nonce enforcement plus semantic intent validation.
- `docket/agents/grid/` with deterministic grid plans, trigger observations, exact-input PancakeSwap action intents, a keeper, and benchmark logging.
- Web controls for cap, expiry, remaining authority, pause, and revoke.

**Exit gate:** on a tiny, explicitly user-approved amount, one session registration, one simulated grid leaf, one confirmed PancakeSwap transaction, cap decrement, revoke, and rejected post-revoke attempt are all visible and independently verifiable.

Why third: this one vertical simultaneously supplies BNB Grid depth, PancakeSwap volume, the action/safety primitive for every other category, and the only credible basis for an Altana rider.

#### Stage 3 — Complete four-category parity

Build in this order, reusing the kernel:

1. `docket/agents/pancake/range_keeper.py`: current-fee simulation, token/price presentation, policy planner, then bounded v3 recenter execution.
2. `docket/agents/yield/`: explicit candidate-universe ingestion, normalized net APR, emissions/cost/break-even analysis, and capped movement.
3. `docket/agents/health/`: one verified lending adapter, durable monitor, alerting, and capped repay/supply-only action.

For each, add identical service models, UI states, machine docs, canaries, session controls, receipts, failure tests, and benchmarks. Register/bind one BSC identity per flagship only with user approval.

**Exit gate:** every cell of the eight-point equal-depth contract above is complete for all four categories. A label, read-only placeholder, or prerecorded output fails the gate.

Why this order: Range and Yield reuse existing Pancake data; Health is the only materially different protocol adapter. Shared mechanics prevent one hero category and three afterthoughts.

#### Stage 4 — Replace eligibility evidence with winning TermiX evidence

Build:

- `docket/advantage/v2/` with pre-registered task definitions, repeated trials, human and null baselines, dataset/source hashes, consistent clocks, failure retention, and distribution summaries.
- Category-specific objective metrics. Trading must publish wins/total, exact window, capital/exposure, fees/slippage, and drawdown/risk—not a provenance task labeled trading.
- A benchmark explorer that shows all runs, not only aggregates, and preserves v1 unchanged.
- A service-card evidence summary derived from the same records, so comparison and the report cannot drift.

Recommended three headline comparisons:

1. Range Keeper vs a passive unchanged position, measured on in-range time and realized net economics.
2. Grid Operator vs passive/null and a manual policy, measured on net P&L and risk over the same window.
3. Health Guard vs manual polling, measured on observation/intervention latency and action correctness; do not claim avoided liquidations as fact.

Keep Warden's loss public. Improve and re-run it on a blinded corpus if security remains a listed flagship; otherwise demote it from the main three without erasing history. Replace stale SOLVENT as the trading headline with the live Grid record.

**Exit gate:** every headline claim has repeated n/window/method/risk evidence; at least one clear agent advantage is on substantive outcome quality, not only speed.

Why before polish: TermiX will perform the work. No visual treatment rescues a service that loses or does not answer the question.

#### Stage 5 — Close payment, identity, and production gaps

Build:

- Complete one real x402 settlement using the verified current facilitator path; fix domain/token binding, nonce replay, and full validity-window checks before treating payment as paid.
- Keep the free sample path. Treat ERC-8183 as the advanced “real job” rail, not the main demo; deploy its read endpoints and add browser signing only if it no longer threatens the core journey.
- Schedule snapshot/enrichment/canary/benchmark jobs; add immutable production manifests and health alerts.
- Add provider onboarding, signed manifests, category canaries, and identity ownership proof.
- Stage README, LICENSE, SECURITY/threat model, deployment/runbook, architecture, API examples, and `AI_USAGE.md` locally. Repository visibility, registrations, mainnet transactions, external posts, and submission all remain explicit user-approval actions.

**Exit gate:** a clean checkout reproduces tests and a sample dataset; production survives restart; all four services remain current; one paid hire and one bounded action have real receipts; the public-readiness package is staged for approval.

#### Stage 6 — Freeze and rehearse the real product

- Run desktop/mobile/accessibility and machine-client E2E tests from a clean state.
- Give unfamiliar users only the URL; record dead ends and fix them.
- Rehearse a live category → preview → session → action → receipt → revoke flow. No prerecorded log replay.
- Freeze feature work, monitor uptime/freshness, and prepare the submission artifact. Submit only after explicit approval.

**Exit gate:** the exact deployed commit, public repository candidate, demo, evidence report, identities, and transaction receipts agree.

### Post-hackathon product roadmap

#### Product Phase A — BNB's evidence-backed distribution layer

- Replace the 8004scan dependency as source of truth with direct ERC-8004 event/state indexing; retain aggregators as cross-checks.
- Add self-service provider onboarding, signed service manifests, automated protocol/capability challenges, pricing, x402/8183 adapters, and category canaries.
- Build availability and task-result time series, not one-time GETs.
- Expose a stable embed/API so wallets, BNB properties, and agent clients can offer the same discovery/activation journey.

The adoption metric is not registered-agent count. It is **qualified services → previews → activations → successful repeat tasks**, with denominators.

#### Product Phase B — The agent evidence graph

- Persist task receipts, on-chain actions, disputes, refunds, provider responses, benchmark runs, and user-authorized feedback as linked evidence objects.
- Publish bounded capability records instead of one trust score: task, environment, sample, window, cost, risk, source, and reproducibility.
- Add challenge suites per category and independent evaluator support. Providers can contest data by rerunning the same method, not by asking Docket to change a badge.
- Build task-specific comparison queries and portfolio/session history for users.

This is the moat TermiX-compatible competitors will struggle to copy: not a score, but a continuously reproducible evidence graph tied to activation outcomes.

#### Product Phase C — Policy-controlled autonomous finance

- Standardize Docket's session policy and receipt format across BNB smart accounts and agent runtimes.
- Add audited protocol adapters one at a time, formal invariants for cap/revoke/replay behavior, simulation disagreement monitoring, and emergency global pause for Docket-operated executors.
- Separate planner, policy evaluator, and executor so a compromised model cannot widen authority.
- Add user-owned policy portability: a user can move an agent or executor without losing the policy and evidence history.

#### Product Phase D — Ecosystem operating layer

- Ship Agent Studio-compatible templates/adapters after verifying the then-current toolchain, so providers can publish into Docket without abandoning BNB's preferred stack.
- Give BNB ecosystem teams category conversion, uptime, action-volume, failure, and retention analytics with honest denominators.
- Support sponsored trials and protocol campaigns without turning sponsored placement into an evidence ranking.
- Expand beyond the four launch categories only after the onboarding/challenge/evidence pattern works without hand curation.

Stay BNB-first through these phases. Cross-chain expansion before BNB adoption would dilute the acquisition story and multiply policy risk.

## 7. What to stop doing

- Do not add three category labels to registry descriptions and call Diversity closed.
- Do not make the raw 506-row registry explorer the primary home page.
- Do not build an opaque trust/recommendation score to make the UI feel decisive.
- Do not use display-grade tick math to size a real v3 transaction.
- Do not treat a server-side spend check as session-key safety.
- Do not spend the next sprint polishing the seven-day escrow path while human activation and four categories are absent.
- Do not replace the Advantage Report's negative evidence; version it and improve the experiment.
- Do not call an authorization “paid” before settlement or a confirmed action “beneficial” before outcome evidence.
- Do not prioritize Altana-specific glue over the shared action kernel or four-category parity.
- Do not broaden to more chains or protocols before one deep implementation exists in every required category.

## Bottom line

The existing architecture is not a failed start. It built the hardest-to-fake component first: a culture and code path for saying exactly what was observed. But the opening strategy overlearned the no-verdict lesson and underbuilt the product.

**Recommended course:** repair the evidence-contract errors immediately; unify discovered identities and hireable services; make four category products equally deep; add a separate on-chain-capped execution plane beginning with Grid Operator; measure bounded outcomes repeatedly; then package the result as BNB's evidence-backed activation layer.

That plan lets BNB breadth and TermiX rigor coexist. It also turns PancakeSwap action and Altana session keys into shared infrastructure rather than distracting side quests. Anything materially smaller may remain a good evidence demo, but it will not match what the main-track sponsor said it wants to adopt.
