# Docket vs. BNB "Build the Era" MAIN TRACK — judge-side audit

Audited 2026-08-22. Repo `<repo>`, branch
`docs/deliberation-round2` @ `fdf02cf`. Live site `https://docket.gudman.xyz` @ `534af82`
(6 commits behind the branch; the 6 are v3 advantage plumbing, none user-visible).
Everything below marked *verified* was fetched or read today. Read-only: nothing in the
repo was edited.

---

## (a) Honest probability

**As the site stands today — top-3 shortlist ~12%, winning the $30k + adoption ~4%.**
**If G1 (four ERC-8004 registrations) lands — shortlist ~25%, win ~8%.**
**If G1 + G2 + G3 + G7 land — shortlist ~40%, win ~13%.**

These are lower than a first pass would suggest, and the reason is §(c): **the field is
crowded, not thin.** An exhaustive GitHub sweep run today found **28 public main-track
entrants**, six of which already have a live four-category site, and at least one
(`san-npm/agripinaa`, pushed today) has **four ERC-8004 identities registered on BSC
mainnet, one per required category, with an activate flow behind scoped revocable session
keys.** Docket has none of those four things. The official submission channel is a private
Google Form, so there is no leaderboard — but GitHub is wide open and the competition is
visible there. Docket's repo is private, so Docket is the one entrant nobody can see.

The single largest swing factor is **G1**, because it is the only item that moves a **hard
gate** rather than a scored criterion. Everything else is points; that one is admission —
and a rival who builds four shallow agents inside BNB Agent Studio clears it for free,
because the Studio registers an ERC-8004 identity automatically at deploy.

What keeps the number from being lower: most of the field is Vercel SPAs running **testnet
or admitted demo data** (`AgentEra` discloses "fallback simulation"; `7777chu` says it "uses
demo data first"; `kaizenbnb`, `gilbertsahumada`, `eunomia` are testnet). Docket's four
category services return **live BSC mainnet reads with the block stamped on every figure**.
On Functionality and Data Quality *as actually experienced*, Docket is at or near the top of
this field. It is losing on the gate, on presentation, and on freshness of the registry
half — all three of which are 18-day-fixable.

Winning (as opposed to shortlisting) stays capped by §(e): BNB is buying something to grow,
and Docket's inventory is a hardcoded Python dict that no third party can add to.

### The six deciding facts

**1. The hard gate is failed on the plain reading, and Docket says so itself.**
BNB: *"Agents surfaced on your marketplace must be live on BSC."* Verified live today:
`GET /services` returns `agent_id: null` for `range-doctor`, `grid-operator`,
`yield-router`, `health-guard` and `warden-scan`. Each carries the sentence
*"No BSC identity bound yet. Docket runs this service from its own host and has
registered no ERC-8004 agent for it, so there is no on-chain record of it to read."*
All four scored-category slots are filled by services with **no on-chain identity**.
The one bound service, `solvent-signal` (`56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384`,
`marketplace/registry.py:246`), is **uncategorised** and **halted since 2026-06-28**.
So: **zero of the four scored category shelves contains an agent live on BSC.**

There is a second, more favourable reading — the 506 indexed registry agents *are* live
on BSC and *are* surfaced. Both readings should be stated in the submission, but a judge
who applies the first one has a clean disqualification and will not have to argue for it.

**2. The rubric's central sentence is inverted.**
BNB: *"the marketplace itself, not a portfolio of agents"* and *"how easily someone can
find an agent and hire it."* Docket is exactly two things that do not touch:
- 506 indexed agents that **cannot be hired** — verified: `GET /agents/{id}` returns
  `associated_services: []` for every agent sampled (ClawNews/1, AGENTSAI/129), and the
  agent page (`web/agent.html`, painter at `app.js:1162-1224`) renders no action control.
- 6 services that **can** be hired, all of which Docket runs itself — i.e. a portfolio of
  agents, the thing the rubric names as the wrong answer.

The reverse link is code-complete (`routes.py:785-790` populates `associated_services`
from records whose `agent_id` matches) and returns empty for 506/506 agents, because the
only bound service's agent is not in the snapshot at all.

**3. "Make identity and track record legible to a person deciding who to hire" scores ~0.**
Verified: `GET /agents/56:0x…a432:136384` → `agent_not_found`. Docket's default sweep is
`min_feedbacks>=1` (`ingest.py:138-160`: *"Of 247,278 BSC agents on 2026-08-07, 506 had
any feedback at all"*), and SOLVENT has none, so **the one service with an ERC-8004
identity has no on-chain record readable on the site.** `routes.py:793-800` handles this
honestly — `agent_path: null` plus an explanatory `identity_note`, no broken link — but
the net result is that a judge can read an ERC-8004 track record for **zero** hireable
services. This is the criterion sentence BNB wrote most specifically, and it is unmet at
100%.

**4. Agent Diversity is stocked but not equally deep, and it is provable from one file.**
`marketplace/registry.py:73-74` (health-guard), `:107-108` (yield-router), `:148-149`
(grid-operator) all carry `metrics=()` and `evidence=()`. Only `range-doctor` (`:171+`)
carries three metrics and evidence refs. **One of four categories has any recorded run
behind it.** Live `/compare` confirms: three of six rows return
`measured.available: false, reason: "No paired run against a human exists…"` and the two
that *do* have measurements besides range-doctor (`solvent-signal`, `warden-scan`) are the
two **uncategorised** services. The homepage says *"Three of these have been run against a
person doing the same job"* — true, but two of the three are outside the four categories,
which a judge who reads the table will notice.

The verb problem is real but **secondary** to this. BNB's verbs are manages / places /
routes / protects. Docket's live `stock_status` values are `candidate` (rebalancing) and
`preview` × 3. `grid-operator`'s own `limitations` string says *"structurally only a
preview: the object that produces it holds no session key, no signer and no submitter and
has no method that sends a transaction."* Verified in code: the only `send_raw_transaction`
in the whole package is `escrow/settle.py:151-159`; no agent module can transact. A judge
reading the four cards finds four read-only advisors where the rubric describes four
actors. That is a scoring risk, but it is *defensible* ("we route no user funds, and the
preview is bounded and hash-bound"). The empty-evidence asymmetry is **not** defensible —
it just looks like three categories were added late.

**5. Data Quality splits into two planes and only one of them is good.**
- **Hire plane — genuinely real-time, and this is Docket's strongest BNB asset.** Verified
  today: `POST /hire/grid-operator` returned live PancakeSwap V2 router quotes at
  `bsc_block` reads seconds old; `POST /hire/health-guard` returned Venus comptroller reads
  at `as_of_block 117428869` with the exact `reads[]` list
  (`comptroller.getAccountLiquidity`, `getAssetsIn`, `getAllMarkets`, `oracle`);
  `POST /hire/yield-router` (no arguments at all) returned live pool APRs with TVL, 24h
  fees, protocol cut and turnover in 3.1s. Every figure carries the block it was read at.
  This is *better* than "beyond basic counts" — it is decision-grade and self-checkable.
- **Registry plane — 15 days stale, will be ~33 at judging, and is 0.20% of the chain.**
  Verified: `/stats` → `snapshot_id 3`, `captured_at 2026-08-07T17:51:02Z`,
  `snapshot_age_seconds 1278650`, `sampled 506 / expected 506`, `registry_total 247146`.
  No `docket/refresh.py` exists (confirmed absent). Three systemd timers *do* run —
  `docket-canary.timer` (daily 04:17Z, **confirmed firing**: `/canary` shows run id 8
  started `2026-08-22T04:21:31Z`), `docket-lp-record.timer`, and a one-shot
  `docket-v3-capture.timer` for 2026-08-21 — so the earlier "no scheduler exists anywhere"
  claim is now **wrong in general and right in the specific**: nothing refreshes the
  registry snapshot.

The staleness is *displayed*, not hidden (`app.js:267-272`: `captured 14 days ago`,
`age 1,278,650 seconds`) — but it is displayed next to a green dot reading **"Complete
snapshot"**, with `population: unspecified`, and no warning banner (the banner at
`app.js:277-289` only fires on `dropped > 0`). A judge sees green + "complete" + a
seven-digit second count. Honest by construction, harmful by presentation.

**6. The field already contains a rival that has done fact 1, 2 and 4 correctly.**
`san-npm/agripinaa` (live, pushed today): four ERC-8004 identities on **BSC mainnet**
(`269703`–`269706`), one per required category, presented as four named agents with an
"Activate" control backed by scoped, revocable session keys. That is the identity gate, the
category shelving and an activation affordance, all closed. Its weakness is exactly the
inverse of Docket's: it displays **"Score 100"** for agents that 8004scan reports as
`total_score: 0, description: null, is_endpoint_verified: false`. So the field's leader is
strong where Docket is weak and fabricating where Docket is rigorous.

There is no configuration of the next 18 days in which Docket out-builds that team on
identity while also out-presenting them, unless G1 starts this week. Conversely, if G1 lands
and Docket keeps publishing real denominators against a rival showing invented scores, the
Data Quality criterion becomes Docket's to win — and it is the criterion BNB wrote at
greatest length.

### Why 4% and not lower

Docket is not a demo. It is publicly reachable, has a working cold hire path requiring no
wallet/account/key, has a daily canary proving uptime, has 72 test modules, publishes its own
unflattering numbers (`warden-scan` names 1 of 4 hostile vectors a manual read found), and
its `/compare` surface exists precisely to let a buyer choose. The *engineering* is
top-decile. The scoring gap is that BNB asked for a two-sided marketplace and this is a
one-sided evidence product with a hardcoded inventory.

### Why not higher

The prize is an acquisition — *"we back it as a standalone product with its own brand and
team"*, *"keep alive, drive users to, and grow"*. Docket's inventory is a Python dict
(`marketplace/registry.py:59 SERVICES`, `hire/catalogue.py:630 SERVICES`) and
`registry.py:47-52 EMPTY_CATEGORY` states the policy outright: *"Docket lists a service
only where it runs the work itself."* **A third party structurally cannot list.** There is
no provider onboarding, no listing flow, no schema for someone else's agent, no growth
mechanism. Adopting Docket means adopting six services and a hiring queue of one team. See
§(e).

---

## (b) Gaps ranked by points-per-day, 18 days (Aug 22 → Sep 9)

Ranked by BNB main-track points per builder-day. Items that also serve TermiX/PancakeSwap
are flagged **[shared]**.

### G1 — Register four ERC-8004 identities on BSC, and make them visible · ~1.5 days build + user txs · HIGHEST
- **file:line** — `marketplace/registry.py:62/99/132/171` (`agent_id` unset on all four);
  `routes.py:793-817` `_identity_link` already handles a bound identity;
  **no registration code exists anywhere** — verified: zero matches for
  `newAgent|registerAgent|mintAgent|IdentityRegistry` across `docket/`, `abis/`, `deploy/`;
  `abis/` holds only `AgenticCommerce.json`, `ERC20.json`, `EvaluatorRouter.json`,
  `OptimisticPolicy.json`. The registry address is only ever a *string* in the codebase
  (`registry.py:246`, `advantage/experiments/02-trading.json:94`,
  `api/static/SKILL.md:119`).
- **What the judge sees** — four category cards each saying "No BSC identity bound yet",
  against a gate that says agents must be live on BSC.
- **The contract and the call, verified on chain today (do not use the signature in the
  blog posts).** IdentityRegistry `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432`, chain 56,
  ERC-1967 proxy, implementation `0x7274e874ca62410a93bd8bf61c69d8045e399c02`,
  `getVersion()` = `2.0.0`. This is the address **BNB's own SDK pins** for `bsc-mainnet`
  (`bnbagent-sdk` `python/bnbagent/config.py:71`) and the one 8004scan indexes. The
  BNB-specific fork **BRC8004** (`0xfA09B3397fAC75424422C4D28b1729E3D4f659D7`, 26 agents,
  last pushed Feb 2026) is abandoned — do not build against it.

  ```solidity
  function register() external returns (uint256 agentId);                       // 0x1aa3a008
  function register(string agentURI) external returns (uint256 agentId);        // 0xf2c298be
  function register(string agentURI, MetadataEntry[] metadata) returns (uint256); // 0x8ea42286
  // struct MetadataEntry { string metadataKey; bytes metadataValue; }
  event Registered(uint256 indexed agentId, string agentURI, address indexed owner);
  ```

  All three selectors confirmed present in the **deployed runtime bytecode**.
  **`newAgent(string,address)` (`0x4750d0fa`) is ABSENT** — that signature is from an
  obsolete draft and is still repeated in many blog posts. Registration is **permissionless
  and non-payable**: no access control, no fee, `agentId = $._lastId++`. Measured cost:
  `eth_estimateGas` on `register(string)` → **163,334 gas**, at the observed `eth_gasPrice`
  of 0.05 gwei ≈ **0.0000082 BNB per agent**. Four agents cost fractions of a cent in gas.
- **The three-leg fix — and leg 3 is the one that is easy to miss.**
  1. Add `abis/IdentityRegistry.json` and a `docket/identity/register.py` that calls
     `register(string agentURI)` once per category service, with each `agentURI` pointing at
     a Docket-served `agent-registration.json`. Wire the returned `agentId` into the four
     `ServiceRecord`s.
  2. Run G3's sweep so the snapshot is current.
  3. **The four new agents still will not appear.** Docket's sweep is `min_feedbacks>=1`
     (`ingest.py:138-160`), and a freshly minted agent has zero feedback — which is
     *precisely* why SOLVENT's 136384 returns `agent_not_found` today. Without a third leg,
     G1 + G3 together still leave `GET /agents/{new_id}` → 404 and `agent_path: null`, and
     the service page keeps printing the "the snapshot does not hold this agent" note. Pick
     one: (a) an owned-agent allowlist merged into every sweep — cleanest, no chain writes;
     (b) special-case Docket's own ids in `_identity_link` so the service page renders the
     identity inline from chain rather than from the snapshot; or (c) seed one on-chain
     feedback per agent via ReputationRegistry `0x8004BAa17C55a88189AE136b182e5fdA19dE9b63`
     (`giveFeedback`, selector `0x3c036a7e` — the same 8-arg ABI already verified in the
     user's X Layer notes, since these are identical CREATE2 deployments). **(c) is what
     `san-npm/agripinaa` did** — all four of its mainnet agents carry `total_feedbacks: 1`.
     (a) is honest and cheap; (c) is self-dealing and should be disclosed if used at all.
- **Exit test** — `GET /services` returns a non-null `agent_id` for all four; **and**
  `GET /agents/{that_id}` returns 200 with `associated_services` containing the service;
  **and** the service page renders a working "Read what Docket observed of it" link. All
  three, from a cold client. The first alone is not the outcome.
- **Second route worth pricing before choosing** — BNB Agent Studio **registers an ERC-8004
  identity automatically at deploy** into this same registry (verified via the SDK config).
  Deploying thin Studio-built shells would clear the gate without writing registry code.
  BNB's *"that's just how it works, not a separate track to build for"* is an instruction not
  to chase the AWS runtime as a scoring surface — it is **not** a prohibition on using the
  Studio. Direct registration is cleaner, costs ~$0 in gas, and keeps Docket's stack intact;
  the Studio route is the fallback if the direct route stalls.
- **Precision on "we've done this before"** — the prior registration is two separate events,
  and only one of them is a mint: SOLVENT agent 136384 was **minted 2026-06-16**
  (`docs/plans/2026-08-06-phase0-foundations.md`), and tx `0xa21529…fb59a9` (block 106960688,
  2026-06-28) is a **`MetadataSet`**, not the registration. So the environment has proven a
  mint once and a metadata write once — enough to say the flow is known, not enough to say
  the exact `register(string)` call has been executed from this repo. It has not; there is no
  code for it.
- **Blocker** — user must approve the transactions. Gas is negligible; the approval is the
  lead time. Start this week.
- **Why this is #1 and not #2.** A rival who builds four shallow agents inside Agent Studio
  clears the "live on BSC" gate for free, and `san-npm/agripinaa` has already done it the
  hard way. On a hard gate, depth does not compensate.

### G2 — A worked example on every category service (kill the wallet wall) · ~1–1.5 days · **[shared]**
- **file:line** — `hire/catalogue.py:646`, `:769`, `:873` — `wallet` is
  `required: true` with **no default** for range-doctor, grid-operator and health-guard.
  `app.js:433-437 inputControl` prefills only from `field.default`, so the box renders
  blank and required. `routes.py:1080-1085` returns
  `422 {"code":"missing_field","message":"grid-operator requires wallet…"}` — verified live
  for all three.
- **What the judge sees** — lands, picks "Run a capped grid", clicks through, meets a form
  whose first field is a bare label reading `wallet` with the helper text *"the 0x-prefixed
  BSC address the previewed swaps name as recipient"*. A judge with zero Agent Studio
  knowledge and no BSC wallet stops here. This is the rubric's literal dead end.
  (`yield-router` is the exception — it takes no required argument and returns a full live
  APR comparison; it is the only one of the four that a cold judge can actually run.)
- **The page contradicts itself, on the hero line.** `index.html:51-53` promises
  *"Pick the job below, read what the service does and what it cannot do, and run it from
  the page. **No account, no key, no wallet** — the first request is served."* Three of the
  four category services then demand a wallet field. The promise is technically about
  *authentication* and the field is a *read target*, but no cold judge will parse that
  distinction — they will read it as the site breaking its own first promise. Either
  prefill the field (below) or reword the hero.
- **The fix** — a Docket-owned demo wallet with a live PancakeSwap v3 LP and a small Venus
  borrow; prefill it as `field.default` on all three, with a one-line "this is Docket's own
  demo position — swap in your own address" note. Not a new subsystem; three dict entries
  plus a funded wallet.
- **Exit test** — from a fresh browser with no wallet, all four category services can be run
  to a non-empty, human-readable result in ≤4 clicks each.
- **Note** — the failure is softer than it looks: all three *do* return live results for any
  address (verified with `0x…dEaD` — range-doctor read 10 of 53,929 position NFTs, health-guard
  returned `status: no_position`). The problem is purely that the judge has nothing to type.

### G3 — Refresh the registry snapshot, on a timer, starting now · ~1 day · HIGH
- **file:line** — `docket/refresh.py` does not exist; `ingest.py:39-75` has the sweep,
  `store.latest_complete_snapshot_id()` has the promotion, nothing joins them on a schedule.
  `routes.py:288` binds `snapshot_id` at app construction, so a new snapshot is invisible
  until restart. `deploy/systemd/` proves the timer pattern is already understood and
  working (canary fired 04:21Z today).
- **What the judge sees** — the criterion's first word is "real-time". The site's own status
  line says `captured 14 days ago` under a green "Complete snapshot" dot; on Sep 9 that
  reads `captured a month ago`, and on Sep 23 it reads ~47 days.
- **The fix** — `refresh_once` (ingest → enrich → probe → validate → promote) + a 6-hourly
  `docket-refresh.timer` modelled on `docket-canary.timer`, plus dynamic snapshot rebind or
  a post-promote app reload. Run it from today so that by judging there are ~4 weeks of
  refresh history to point at.
- **Exit test** — `GET /stats` `snapshot_age_seconds < 21600` at any moment during Sep 9–23,
  checked from a cold client.

### G4 — Say the staleness out loud, and stop calling a 0.2% slice "Complete" · ~0.5 day
- **file:line** — `app.js:262-289 paintCoverage`. `partial` is computed only from
  `complete !== true || dropped > 0`; there is no age term. `snapshot_age_seconds` renders
  as `1,278,650 seconds`. `populationLabel()` prints `unspecified` because snapshot 3
  predates the `population` column, even though the sweep *was* `min_feedbacks>=1`.
- **What the judge sees** — green dot, "Complete snapshot", `sampled 506 of 506`,
  `registry_total 247,146` elsewhere on the page. The inference available to a hostile
  reader is "they indexed 506 of 247,146 agents and called it complete."
- **The fix** — add an age term to `partial`; render age as "14 days"; backfill
  `population` on snapshot 3 to `min_feedbacks>=1`; and put "506 of 247,146 BSC agents —
  the ones carrying at least one feedback record" *next to* the sampled metric rather than
  in a footnote.
- **The reframe that turns this weakness into a strength — and it is free.** Independent
  on-chain sampling today found that of **293,117** agents minted on BSC, roughly
  **two-thirds are bulk or spam registrations**: 65.8% of a 120-agent random sample carry
  inline `data:` token URIs, and decoding a 70-agent subsample found **26 byte-identical
  "Ave.ai Trading Agent" records** plus entries literally named `"1111111111"` and
  `"52253"`. Only about **1–2%** of randomly sampled agents have any feedback client at all
  (`getClients(agentId)`, n=160, 2 hits). **Docket's `min_feedbacks>=1` sweep is therefore
  not a 0.2% coverage gap — it is a spam filter that isolates approximately the only real
  population on the chain.** Docket has never said this anywhere. Saying it converts the
  single most attackable number on the site ("you indexed 506 of 247,146") into the single
  most defensible one ("we indexed the 506 that aren't machine-generated, and here is how we
  counted"). One paragraph, no code.
- **Exit test** — a reader who looks only at the status line can state the age in days and
  the population filter without scrolling.
- **Cheap and disproportionately valuable**: this is the difference between "honest" and
  "reads as honest", and Data Quality is where it is scored.
- **The bigger prize hiding inside this item.** §(c) establishes that only **~10–15 genuine
  four-category agents exist on BSC mainnet** against ~275,000 registered, and that
  8004scan's own semantic search is noisy enough that `search=liquidity` returns 286 mostly
  unrelated prompt-persona agents. Every rival is competing on "browse 200k+ agents"; Docket
  half-adopts the same framing by surfacing `registry_total: 247,146`. **Docket should
  publish the opposite number.** A short, sourced "How many agents can actually do these
  four jobs?" panel — the keyword method, the counts, the template-spam it excluded, and the
  denominator — is roughly a day of work, is the single most defensible thing on the site
  after the hire path, and directly answers *"data that goes beyond basic counts"* by
  attacking the basic count. Nobody in the field is saying it, and the honest answer flatters
  a curated six-service marketplace over a 275k-row mirror.

### G5 — Evidence parity across the four categories · ~1.5 days · **[shared]**
- **file:line** — `marketplace/registry.py:73-74`, `:107-108`, `:148-149` —
  `metrics=(), evidence=()` on health-guard, yield-router and grid-operator.
- **What the judge sees** — the Agent Diversity criterion verbatim: *"A submission that
  treats one category as the main event and the rest as an afterthought won't score well."*
  Three cards with no figures, one card with three. `/compare` prints
  `"No paired run against a human exists for this service"` three times.
- **Worse than a blank: a silent blank.** `app.js:308-309` — `metricLines` returns the
  empty string when `metrics` is empty, so three of the four category cards render *nothing
  at all* in the figures slot. The homepage prose does explain this
  (`index.html:54-58`: *"a card with no figures on it has had no run recorded, and says so
  rather than borrowing another service's evidence"*) — but that sentence is in the hero,
  two sections above the card, and the card itself says nothing. Even before any new
  evidence is recorded, making `metricLines` emit *"No run recorded yet"* on the card is a
  10-minute change that converts an apparent omission into a visible, deliberate
  disclosure — which is the whole basis of Docket's positioning.
- **The fix** — three recorded runs, one per category, transcribed with `window`,
  `observed_at` and `method` in the existing `Metric` shape. `advantage/v3/` already has
  registered specs for range-doctor and yield-router; grid and health need one each. This
  does not require a *paired human arm* for BNB (that is TermiX's gate) — a single recorded
  run with its population is enough to remove the blank.
- **Exit test** — every one of the four category cards renders at least one metric line with
  a denominator and a link to the record.

### G6 — Reframe the 506 from "research" to "the marketplace", and give each one an action · ~2 days
- **file:line** — `web/index.html:250-262` puts the registry behind a CTA reading
  *"Research the registry"* (`index.html:256`), on `/research`; the primary nav
  (`index.html:37-41`) reads Services / Research the registry / Advantage report / API and
  has no `/agents` or "browse agents" entry at all (`index.html:39`). `routes.py:785-790` returns `associated_services: []` for every
  agent. `app.js:1162-1224` renders no action on an agent page.
- **What the judge sees** — the thing BNB asked for (a venue to browse agents and put them
  to work) is filed under "research", and clicking any of the 506 yields a page with a name,
  an owner address, a protocol list, and one 8-second HTTP probe. No hire. No action. No
  next step. (Verified on agent 129 — its declared endpoint is
  `https://www.8004scan.io/create`, which 308s; "responded" here means a marketing page
  redirected.)
- **The fix (minimum viable)** — on every agent detail page, add a "What you can do with
  this agent" block: its declared A2A/MCP endpoint as a copyable call, its x402 flag, and —
  where `declares_callable` is true and the endpoint answered — a *"try this endpoint"*
  control that issues the same probe live and shows what came back. Rename the nav entry to
  "Browse agents". That converts 506 dead rows into 31 with a live affordance
  (`callable_declared: 31`) and 475 with an honest "this agent declared no endpoint".
- **Exit test** — from the homepage, a judge reaches an agent that is not Docket's and can
  take *some* action on it without reading docs.
- **Honest caveat** — this does not make them hireable, and pretending otherwise would
  break the integrity posture the rest of the site is built on. It closes the "dead end"
  half of the criticism, not the "two half-marketplaces" half.
- **The sharpest sub-finding here.** BNB asks for a front end that *"lets users discover and
  activate agents **by category**"*. Verified: `/research` offers filters for
  `has_feedback`, `declares_callable`, `responded` and `name_family` — all liveness and
  provenance filters, **none of them a job category**. Docket's stated reason is correct and
  is published (`/categories.declaration`: *"An ERC-8004 registration records nothing about
  what job an agent does, so Docket declares categories for its own services and assigns
  none to a third-party registry agent."*). But the consequence is that **506 of Docket's
  512 surfaced agents cannot be discovered by category at all**, which is the criterion
  verbatim. If a competitor classifies registry agents — even heuristically from the
  `description` field, which ClawNews/1 shows is often rich — they will out-score Docket on
  this sentence while being less rigorous. The defensible middle: classify with a stated
  method and a confidence, label it "inferred from the agent's own description, not read
  from chain", and let the reader filter it out. That preserves the integrity posture and
  answers the criterion. ~1 extra day on top of G6.

### G7 — Fix the shop-front vocabulary · ~0.5 day · **[shared]**
- **file:line** — `app.js:336-338`: the primary CTA renders `Open ${stock_status}` →
  **"Open preview"**, **"Open candidate"**, **"Open research"**, **"Open beta"**.
  `app.js:478-480`: the submit button renders `Run the ${stock_status}` → **"Run the
  preview"**. `app.js:335`: the price label renders **"Price after admission"** and
  `app.js:344` renders **"Paid-stock status: preview"**.
- **What the judge sees** — *"doesn't make them think too hard about it"* is the criterion.
  A cold reader meets `paid_stock`, `stock_status`, `admission`, `candidate`, `preview`,
  `research`, `beta`, `decision_grade_presenter`, `cold_canary`,
  `fresh_paired_benchmark`, `true_settlement` — an internal admission vocabulary rendered
  verbatim in the buying surface. Nothing on the card says the plain thing: *free, no wallet,
  runs in 25 seconds*.
- **The fix** — CTA reads **"Run it free"** everywhere the service is not paid stock;
  keep the admission vocabulary, move it below the fold under "Why this isn't for sale yet".
- **Exit test** — a reader who has never seen the site can say what the button will do
  before clicking it.

### G8 — Publish the repo, and publish it with the work in it · ~0.5 day · GATING
- **file:line** — `git show main:README.md` → *"exists on disk, but not in 'main'"*.
  `main` is `0fb9c77` (Aug 11), **66 commits behind** `docs/deliberation-round2`. Repo is
  private.
- **What the judge sees** — today, nothing: a 404 or an empty repo. If the repo is flipped
  public without merging, a judge lands on a default branch with no README, no LICENSE, no
  AI_USAGE.md and none of Stage 1–4.
- **The fix** — merge `docs/deliberation-round2` → `main`, secret-scan history, flip public.
- **Exit test** — a logged-out browser opens the repo URL and sees the README's C-01…C-nn
  claims table on the landing page.
- **Note** — a submission-blocking item that has been carried since Aug 14. It is also the
  only item on this list that costs zero judgement.
- **It is now also a competitive-visibility item.** §(c) found **28 public entrant repos**.
  Every rival is visible to every other rival, and to anyone from BNB who scouts informally
  before Sep 9. Docket is the one entrant nobody can see. Given that Docket's differentiator
  is *evidence integrity*, a public repo with a claims-to-evidence table and 72 test modules
  is not just an eligibility box — it is the proof. Six of the top rivals have zero stars and
  one has an **empty README**; the bar for standing out on that channel is very low.
- **Sequencing warning.** `README.md:48-59` renders a "Current service state" table whose
  **On-chain identity** column reads `None` four times, on the four scored categories,
  directly beneath the gate that says agents must be live on BSC. The honesty is right and
  should not be softened — but flipping the repo public *before* G1 lands hands a judge a
  self-documented disqualification in the first screen of the README. **Do G1 first, then
  G8**, and update that column in the same commit. If G1 slips, the column needs a
  neighbouring sentence stating the favourable reading (the 506 surfaced agents are live on
  BSC; the Docket-run services read BSC live at every hire and publish the block) rather
  than a bare `None`.

### G9 — Answer the adoption question in the submission narrative · ~1 day
See §(e). No code; it is the difference between "a good marketplace" and "a product BNB
can adopt", and it is the criterion set BNB has told entrants exists but not published
(*"We'all also assess more criterias in the second phase"*).

### G10 — Deploy parity + judging-window operations · ~0.5 day
Live runs `534af82`; branch head is `fdf02cf`. The canary's `DOCKET_CANARY_END_AT` is
`2026-09-24T00:00:00Z` (`deploy/systemd/docket-canary.service`), which correctly covers
the Sep 9–23 judging window — good, and worth *saying* in the submission, because
*"functional and publicly accessible during judging"* is a hard gate and Docket is one of
the few entrants that can show a daily automated proof of it. Verified: `/canary` run id 8,
`2026-08-22T04:21:31Z`, `fresh_browser_surface` **passed**.

### Where this list disagrees with the plan of record

`CODEX-WIN-SPEC-2026-08-14.md:85` caps the BNB lane at **two days, Aug 29–30**, scoped to
"four ERC-8004 registrations, reverse agent→hire links, one verified complete registry
sweep and application restart". §6 of the same document explicitly **cuts** broad
four-category metric parity, the refresh daemon, provider onboarding, BNB Phase-2 adoption
assets, and the Venus-borrow half of the demo wallet. That ruling is the owner's, it is
reasoned, and this audit does not reopen the TermiX-first priority. Four specific cuts
look wrong **on BNB points-per-day**, and three of them are nearly free:

| Item | Plan of record | This audit | Delta |
|---|---|---|---|
| **G3 refresh** | one sweep + restart on Aug 30 | a 6-hourly timer | The sweep code already exists (`ingest.py:39-75`); the timer is ~12 lines modelled on `docket-canary.timer`, which already works. One sweep on Aug 30 is **24 days stale by Sep 23**, against a criterion whose first word is "real-time". Cost delta ≈ 2 hours. **The cut is wrong.** |
| **G5 parity** | keep evidence for Range, Yield, Warden, Grid | add one recorded run for **health-guard** | Warden is *uncategorised*. Under the plan as written, `health_factor` ends judging with `metrics=(), evidence=()` — the literal "one category as the main event, the rest as an afterthought" the criterion names. One recorded run, ~2 hours. **Partial cut, close the health hole.** |
| **G7 vocabulary** | not scheduled anywhere | ~0.5 day | "Open preview" / "Price after admission" / "Paid-stock status" is the first thing every judge on every track reads. Serves TermiX's *"find, compare, hire, without instructions"* identically. **Should be in the primary lane, not the BNB lane.** |
| **G9 adoption narrative** | cut entirely | ~1 day of prose | It is the only answer to Phase 2, it needs no code, and it can be written on a plane. Cutting a build is a capacity decision; cutting a paragraph is leaving the acquisition question blank. **Restore as submission-writing work, not build work.** |

Left cut, correctly: provider onboarding as a platform, the Venus-borrow wallet (the free
`0x…dEaD` read already demonstrates health-guard end to end), Agent Studio integration,
and the weeks-long registry-history build.

### One thing that is better than the team seems to think

`GET /escrow` (verified live) returns a complete, step-by-step ERC-8183 escrow hire
sequence against **real BSC mainnet contracts** — commerce `0xEa4DAa31…76EBA6`, router
`0x5189…CD6DA`, policy `0x9C01…766dE5` — with the exact calls, the exact argument that
must be the router in both the `evaluator` and `hook` slots, the revert reason if it is
not (`RouterNotEvaluator`), the payment token, and the plain-English statement that the
7-day dispute window has no early-accept path. Almost nothing in a hackathon field will
have this depth of real on-chain integration documented at an endpoint.

It is **not** a hire path a judge will use: the `provider` slot is
`0x0000000000000000000000000000000000000000` and a 7-day window outlasts the judging
visit. But it is strong evidence for the "we understand this chain" half of Data Quality,
and it is currently invisible — `/escrow` appears in no navigation and on no page. A single
line on the service pages ("this service can also be hired through an on-chain escrow —
see the rail") is ~10 minutes and surfaces the best-engineered thing on the site.

### Explicitly NOT recommended
- **Do not build provider onboarding as a full platform.** It is the only work that would
  materially raise the BNB ceiling, and at 18 days with one builder it would cannibalise
  the two tracks the prior deliberation ruled primary. Ship the *narrative* (G9) and a
  read-only "how a third party would list" spec instead. If capacity appears after Sep 1,
  a single `providers.yaml` + a submission form is the 2-day version.
- **Do not chase Agent Studio integration.** BNB says so verbatim.
- **Do not arm any agent to transact for BNB's sake.** The structural no-key posture is
  Docket's strongest safety claim and PancakeSwap's brief rewards it.

---

## (c) Competitor table

### First, the correction that matters most

My initial read — "the field is structurally invisible, so a negative search proves
nothing" — was **half right and dangerously reassuring**. The official channel *is* private
(submissions go to `forms.gle/9g9XPNFwnYaHAz9L8`; no Devpost, no DoraHacks listing, no
leaderboard, no entrant count). But an exhaustive authenticated GitHub Search sweep run
today (16 queries, 55 unique repos) found **28 public repos that are unambiguously main-track
entrants**, of which **~6 have a live site + four-category coverage + on-chain evidence.**

**The field is crowded, not thin.** Several entrants have already shipped things Docket has
not. This lowers the probability in §(a), and it is the most important finding in this audit
after the identity gate.

A second-order point with teeth: **Docket's repo is private, so Docket is invisible in the
one channel where the entire field is visible.** Every rival can see every other rival. If
judges (or BNB's team) do any informal scouting before Sep 9, they are scouting a list
Docket is not on.

### The six real threats

| Repo / product | Live URL | Categories | Hire/activate | Chain | Pushed |
|---|---|---|---|---|---|
| **`san-npm/agripinaa`** | `agripinaa.vercel.app` | All 4, named agents | "Activate" via scoped, revocable session keys; Ophis batch-auction routing | **BSC mainnet** — four registered agents `269703-269706`, one per category | **08-22** |
| **`wyka0/bnb-agent-marketplace`** | `bnb-agent-marketplace-web.vercel.app` | All 4 with live counts (Rebalancing 31 / Grid 4 / Yield 58 / Health 6) | **Fail-closed** — buttons read "Unavailable" until custody is authoritative | mixed, 8004scan-sourced | **08-22** |
| **`gilbertsahumada/bnb-agent-marketplace`** | `bnb-agent-marketplace-ruby.vercel.app` | All 4, **"declared vs observed"** distinction, trust scores | Hire unlocks only after ERC-8183 quote verification | BSC **testnet** (Job #551) | 08-20 |
| **`kaizenbnb/…`** (KaizenScope) | `bnb-agent-marketplace.vercel.app` | All 4, 4 live agents, 8 on-chain txs | *"Find real agents. Hire them in one click."* BscScan tx per agent | BSC **testnet** | 08-14 |
| **`Ai-Rook/bnb-agent-marketplace`** | `ai-rook.com/bnb-marketplace/` | 5 (4 + General) | Altana session keys + ERC-8183 ACP escrow; claims **"11 jobs · 0 disputes"** | claims **BSC mainnet**, "b402 mainnet round-trip verified" | 08-16 |
| **`ragna999/kopdes`** | `kopdes-one.vercel.app` | raw registry feed, not category-curated | discover → connect wallet with spend caps + expiry → execute | BSC mainnet, live 8004scan API | 08-11 |

Second tier, live but testnet / demo data: `Lutviansyah/AgentEra` (4 categories with
success% and TTFT, but data is "8004scan Pro API **with fallback simulation**"; also has a
`/termix` page, so it is competing in the same two tracks Docket is),
`7777chu/bnb-smart-money-agent-marketplace` (four named agents, `/hire/`, `/compare`,
`/proof` routes — *explicitly* demo data), `0xNexuz/eunomia`, `0xConsole/bnb-agent-studio`,
`mcfarhat/agentcensus` (no site, but has a **real BSC mainnet Venus health-factor agent**,
#270183), `FeeeeelixWong/mandatefi`, `stevenjjj-web/thesio-agent-marketplace`.

Then ~15 repo-only entries ranging from active-but-unverifiable
(`KaiVenn52/mandate-bnb-agent`, `fexx301/MandateX` — both pushed 08-22) down to three
literally empty repos. Highest star count anywhere in the cohort: **2**.

### How Docket compares on the three scored criteria

| Criterion | Docket | The field | Verdict |
|---|---|---|---|
| **Functionality** | Real cold hire, no wallet/account/key, returns live chain reads. But: 3 of 4 categories demand a `wallet` a judge lacks; CTA reads "Open preview"; the 506 have no action. | Several ship an explicit one-click hire framing (`kaizenbnb`) or a wallet-connect flow with spend caps (`kopdes`, `agripinaa`). `wyka0` is fail-closed and shows "Unavailable". | **Docket's hire is more real, its journey is worse.** Fixing G2 + G7 flips this to a clear lead, because most rivals' "hire" is against testnet or demo data. |
| **Data Quality** | Live block-stamped chain reads on the hire plane (**best in field**). Registry plane 15 days stale, 506 of 247k, no category filter. | `agripinaa` displays **"Score 100"** for agents 8004scan reports as `total_score: 0, description: null` — a live claims-vs-registry gap. `AgentEra` admits "fallback simulation". `gilbertsahumada` already ships a **"declared vs observed"** distinction — Docket's differentiator, partially taken, but only on testnet. | **Docket wins on method, loses on freshness and breadth.** G3 + G4 close it. |
| **Agent Diversity** | Four categories stocked, but only one has any recorded evidence, and none has an on-chain identity. | Most rivals surface four categories. **`agripinaa` has four ERC-8004 mainnet identities, one per category.** | **Docket is behind.** This is G1 + G5, and G1 is the gate. |

### Same agent, both sites — the literal comparison

Agent **BSC #1 "ClawNews"**, owner `0x89e9e1ab…5029`, fetched from both today:

| | Docket `/agents/56:0x8004…:1` | 8004scan `/agents/bsc/1` |
|---|---|---|
| Fields returned | 16: `agent_id, token_id, name, description, owner_address, has_feedback, feedback_count, declares_callable, protocols, x402, name_family, placeholder_name, endpoints[], observations[], coverage, associated_services[]` | ~70, incl. `total_score, rank, network_rank, health_score, health_status, health_checked_at, is_endpoint_verified, endpoint_verified_at, endpoint_verification_error, star_count, watch_count, owner_ens, owner_publisher_tier, merit_score, proof_score, evidence_tier, integrity_tier, agent_wallet, services[], cross_chain_versions, image_url, scores{…breakdown}` |
| Track record | `has_feedback: true, feedback_count: 2` — a raw count, no score | `v5_leaderboard_policy` v5.2 composite over 5 weighted dimensions (service 0.25, engagement 0.30, publisher 0.20, compliance 0.15, momentum 0.10) |
| Liveness | one timestamped GET per declared endpoint, with the method and denominator published | `health_status` + `health_checked_at`, cached (an observed record read `"HTTP 404 (cached)"`), method and denominator **not** published |
| Freshness | snapshot 3, **15 days old** | re-scored periodically; records fetched today carried `last_scored_at` minutes old |
| Hire | none for this agent (`associated_services: []`) | none — routes are `/agents /leaderboard /networks /developers /reports /create /donate /advertise /about` |
| Chains | BSC only | 59 supported; BSC fully covered (`/networks` lists `{"id":56,…,"slug":"bsc"}`) |

**Read that honestly.** On breadth and freshness Docket loses to its own upstream by a wide
margin. On *method* it wins, and the win is real but narrow: 8004scan publishes a composite
score without publishing how the dimensions were measured or against what population, and
its health field is a cached probe with no stated denominator. There is also a hard fact
underneath that favours Docket's whole thesis — **`getSummary` on the ReputationRegistry
requires a non-empty `clientAddresses` array, so there is no global on-chain reputation
score at all.** Every "score" anyone displays, 8004scan's included, is an off-chain
computation. The only question is who states their method. Docket does; nobody else in the
field does.

### Corrections to my own earlier claims in this report

- **I wrote that 8004scan "does not do liveness probes."** That is **wrong**. 8004scan's
  public API exposes `health_status`, `health_score`, `health_checked_at`,
  `endpoint_verified_at`, `endpoint_verified_domain`, `is_endpoint_verified` and
  `endpoint_verification_error` — 70 fields in total per agent, plus a scored
  `breakdown` under algorithm `v5_leaderboard_policy` v5.2 weighting service / quality /
  popularity / activity / wallet / freshness / metadata-completeness. Its health data *is*
  cached-and-periodic (an observed record read `"HTTP 404 (cached)"` with a `checked_at`
  hours old) rather than live, and it publishes no denominator or method statement — so
  Docket's real edge is **stated method + published population**, not "we probe and they
  don't." The submission must make that narrower, true claim, not the broad false one.
- **Docket surfaces far fewer fields than its own upstream.** A judge comparing side by side
  sees 70 fields on 8004scan versus roughly a dozen on Docket, fresher, across more chains.
  Foregrounding method-and-denominator is not optional framing; it is the only ground on
  which the registry half of Docket is defensible at all.

### The strategic insight worth more than the table

**The four required categories are populated by roughly 10–15 real agents on BSC mainnet.**
Keyword sweeps of the BSC registry returned ~4 genuine grid agents, ~4 health-factor, ~2
recent rebalancing (the rest being 16 identical March-2026 template-spam records), against
a registry of ~275,000. 8004scan's own semantic search is noisy enough that
`search=liquidity` and `search=liquidation` both return 286 results dominated by unrelated
prompt-persona agents.

So the "browse 200k agents" framing every rival uses — and which Docket half-adopts by
showing `registry_total: 247,146` — is surfacing **a registry, not a catalogue**. The
genuinely defensible product is a **curated venue over ~15 real agents with a working hire
flow and honest metadata**, which is much closer to what Docket already is than to what its
competitors are building. Docket should say this explicitly: *the number that matters is not
275,000, it is about fifteen, and here is how we counted.* Nobody in the field is saying it.

Also on-chain and unattributed: four agents registered on BSC mainnet within 16 minutes of
each other on 2026-08-17 — **Portfolio Rebalancer #269223, Grid Trader #269224, Yield
Allocator #269226, Health Factor Monitor #269228**, all on `agents.chainhelix.io/*` with
live ERC-8183 `negotiate` / `notify_funded` skills. One per required category. That is
**either a rival's fleet or BNB's unpublished reference set**, and it could not be
attributed. Worth watching; if they are BNB's references, the shape of the "right answer"
is now visible on chain.

### Baseline: what BNB itself ships

| # | What | Live? | Marketplace/hire? | Notes |
|---|---|---|---|---|
| B1 | **BNB Agent Studio** | Yes — a **CLI**, `npm i -g @bnbagent/studio-cli`, v0.0.12, Apache-2.0 | **None.** No browse, no directory, no hire. "Developer dashboard" is a *future* roadmap item | Closed-source: the npm homepage points at `github.com/bnb-chain/bnbagent-studio`, which **404s**. Registers an ERC-8004 identity automatically at deploy |
| B2 | **`bnb-chain/bnbagent-sdk`** | Yes, 58★, pushed 08-19 | n/a | Full tree walked: `erc8004/`, `erc8183/`, `signing/`, `storage/` — **no examples, no reference agents** |
| B3 | **8004scan** | Yes; API `https://8004scan.io/api/v1` | Browse + leaderboard, **no hire** | 70 fields/agent; BNB officially points entrants at `8004scan.io/agents?chain=56` and offers a free Pro tier |
| B4 | **agentstore.tools** | Yes | n/a — **not a competitor** | Raw HTML title: *"AgentStore - Claude Code Plugin Marketplace"*. A Claude Code plugin store that happens to use ERC-8004 + x402. No BSC DeFi relationship. Rule it out |
| B5 | **TermiX** (`app.termix.ai` → `agent.family`) | Yes — the only genuinely live agent marketplace on BNB | **Full hire flow**: listings, open requests, bounties, escrow → delivery → settlement, 1–3% fee | Its categories are Code / Security / Data / Design — **not** the four DeFi ones. It proves the hire flow and leaves the DeFi venue open |

**BNB published no reference agents for the four categories anywhere** — not on the
hackathon resources tab, not in the SDK tree, not in the org's **159** repos. The blog's
promise of "reference agents and skills spanning four categories" has not landed. The org's
only agent repos are `bnbagent-sdk` (58★), `stockanalyst-agent-demo` (4★),
`bnbagent-studio-evals`, `bnbchain-skills` (63★) and `skills-hub`; the SDK's `examples/`
are `a2a-agent`, `agent-server`, `client`, `security`, `twak`, `voter`, `x402/buyer_demo` —
none of them a category agent.

*(Incidental confirmation, not a re-litigation: BNB's announced reference categories are
**monitoring / grid trading / health factor / yield** — "rebalancing" is not among them.
The Aug-14 briefing already resolved this: the blog list describes the reference agents BNB
said it would share, while the **scored** list lives inside the Agent Diversity criterion on
the hackathon page and does say Rebalancing. Docket's four slugs match the scored list.
Nothing changes.)*

### What could not be searched

- **DoraHacks** — `dorahacks.io/api/hackathon/search` and `/api/buidl/search/` both return an
  AWS WAF human-verification challenge. If BNB syndicated there, entrant BUIDLs would be
  public and this audit is blind to them. **Worth 10 minutes in a real browser.**
- **X / Twitter** — `site:x.com` searches returned only press syndication; unauthenticated
  WebFetch on x.com fails. Absence here is not evidence.
- Several rivals' sites are React SPAs whose rendered content could not be read without a
  browser (`KaiVenn52/mandate-bnb-agent`, `devgreyman/Superagenthub`,
  `FeeeeelixWong/mandatefi`, `dropmoltbot/era-market`). Their READMEs claim four-category
  coverage; that claim is unverified.

## (d) Verified vs. unverified

### Verified today (fetched live or read in the repo)

| Fact | Evidence |
|---|---|
| Site is up, HTML at `/`, JSON at `/categories` `/services` `/agents` `/stats` `/compare` `/hire` `/escrow` `/health`, `/browse`→308→`/research` | curl, all 200 |
| Four categories stocked, one service each | `GET /categories` `service_count: 1` ×4 |
| **Price is 0.50 $U, not 0.01** — the task's known-state is stale | `GET /services` `price_display: "0.50 $U"`, `price_atomic: 500000000000000000` |
| 5 of 6 services have `agent_id: null`; only solvent-signal is bound, and it is uncategorised + halted | `GET /services` |
| SOLVENT's agent is **not in the served snapshot** — `agent_not_found` | `GET /agents/56:0x…a432:136384` |
| No agent has a hire affordance | `associated_services: []` on agents 1, 129; `routes.py:785-790` |
| Three of four category services hard-require `wallet`; `yield-router` requires nothing | `POST /hire/{id}` `{}` → 422 ×3, 200 for yield-router; `catalogue.py:646/769/873` |
| All three still return live results for an arbitrary address | `POST /hire/*` with `0x…dEaD` → 200, live block reads |
| Hire results are genuinely real-time | `bsc_block 117428777` / `as_of_block 117428869`, seconds old at read |
| Registry snapshot is 14.8 days old, no refresh loop | `/stats` `snapshot_age_seconds 1278650`; no `docket/refresh.py` |
| The 506 is `min_feedbacks>=1`, i.e. 0.20% of 247,146 | `ingest.py:138-160` |
| Staleness is displayed but not flagged | `app.js:262-289`; `partial` has no age term |
| A canary **does** run daily and passed today | `GET /canary` run id 8, `2026-08-22T04:21:31Z` |
| Three systemd timers exist (canary, lp-record, one-shot v3 capture) | `deploy/systemd/*.timer` |
| Only `range-doctor` of the four categories has metrics/evidence | `registry.py:73/107/148` `metrics=(), evidence=()` |
| No transaction-sending code in any agent module | only `escrow/settle.py:151-159` matches `send_raw_transaction` |
| **No ERC-8004 registration code exists** | zero matches for `newAgent|registerAgent|mintAgent|IdentityRegistry`; `abis/` has 4 files, none of them the registry |
| IdentityRegistry address in use: `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` (chain 56) | `registry.py:246`, `experiments/02-trading.json:94` |
| Registration has been done once before from this environment | `experiments/02-trading.json:127` — MetadataSet on agentId 136384, block 106960688 |
| `main` has no README and is 66 commits behind | `git show main:README.md` → fatal; `git rev-list --count main..HEAD` → 66 |
| Repo is **still private** as of today, default branch `main` | `gh repo view --json isPrivate` → `true` |
| README (126 lines), LICENSE, AI_USAGE.md exist **on the branch only** | `wc -l`; absent from `main` |
| Live commit `534af82` ≠ branch head `fdf02cf` | task brief + `git log` |
| v3 paired report is specified but **not run** | `/advantage/v3.json` — all 3 families `registered_waiting_for_inputs` |
| Canary is configured to run through `2026-09-24T00:00:00Z` | `deploy/systemd/docket-canary.service` |
| `registry.py:3-6` docstring is stale ("One of BNB's four categories has a service in it; three do not") | read |
| `/research` filters are `has_feedback`, `declares_callable`, `responded`, `name_family` — **no job-category filter for the 506** | `curl /research` |
| `/services?category=` validates and 422s on an unknown category | `?category=bogus` → `invalid_query_parameter` |
| `/escrow` is a complete real-mainnet ERC-8183 sequence but names `provider: 0x000…000` and is **linked from nowhere in the UI** | `GET /escrow`; zero grep hits for `/escrow` in `web/*.html` and `app.js` |
| `solvent-signal` has **no result presenter** — hiring it dumps raw JSON | `app.js:866-872 PRESENTERS` lists the other five only; `app.js:881-882` falls back to `<pre>` |
| The homepage hero promises "No account, no key, no wallet" | `index.html:51-53` |
| The Tier-1 "every service can show a recorded run" false claim **was fixed** | `index.html:54-56` now reads "Some carry a recorded run behind them and some do not yet" |
| BNB submissions go to a **private Google Form**; no Devpost/DoraHacks/leaderboard/entrant count | fetched `bnbchain.org/en/hackathons/smart-money-era` |
| **BNB Agent Studio has no marketplace, directory, browse or hire flow today**, and names no reference agents | fetched `bnbchain.org/en/bnb-agent-studio` |
| **Agent Studio auto-registers an ERC-8004 identity at deploy** | same fetch |
| 8004scan has a leaderboard and 554k+ feedback records but **no hire affordance**; homepage surfaces Base/Celo/Ethereum/Abstract | fetched `8004scan.io` |
| Docket's registry plane is sourced from 8004scan's internal API | `docket/scan8004.py:1-22`, `API_BASE = "https://8004scan.io/api/v1"` |
| BNB's blog names the problem as no way to compare "what an agent does, whether it's live, or how it has performed" | `bnbchain.org/en/blog/build-the-era-…` via search result text |
| Judging window Sep 9–23; prize pool $40k+; partners TermiX, PancakeSwap, **AltLayer**, Altana | press syndication of the Aug-5 wire; AltLayer is not in the Aug-14 briefing |
| **28 public main-track entrants exist on GitHub**; 6 with a live four-category site | authenticated GitHub Search sweep, 16 queries, 2026-08-22 — see §(c) |
| `san-npm/agripinaa` has **four ERC-8004 identities on BSC mainnet**, one per category (`269703`–`269706`), live activate flow, pushed today | live site + 8004scan API cross-check |
| `agripinaa` displays "Score 100" for agents the registry reports as `total_score: 0, description: null` | 8004scan `/api/v1/public/agents/56/{id}` |
| 8004scan **does** publish endpoint health (`health_status`, `health_checked_at`, `is_endpoint_verified`, 70 fields/agent) — cached, not live, and with no published method or denominator | 8004scan public API |
| Only **~10–15 genuine four-category agents** exist on BSC mainnet, against ~275k registered | keyword sweeps of the BSC registry (grid ~4, health ~4, rebalancing ~2 real + 16 template-spam) |
| Four category agents registered on BSC mainnet 2026-08-17 on `agents.chainhelix.io` (`269223/224/226/228`) — **attribution unknown** | 8004scan + live agent cards |
| `agentstore.tools` is a **Claude Code plugin marketplace**, not a BSC venue — rule it out | raw HTML `<title>` |
| `github.com/bnb-chain/bnbagent-studio` **404s**; the Studio CLI is closed-source (`@bnbagent/studio-cli` v0.0.12) | `gh api` + `npm view` |
| `bnb-chain/bnbagent-sdk` (58★) contains **no examples and no reference agents** | full git tree walk |
| TermiX (`app.termix.ai` → `agent.family`) is the only live agent marketplace on BNB with a full hire flow, but its categories are Code/Security/Data/Design — **not** the four DeFi ones | live fetch |
| IdentityRegistry `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` is an ERC-1967 proxy, impl `0x7274e874ca62410a93bd8bf61c69d8045e399c02`, `getVersion()` = `2.0.0`, and is the address **BNB's own SDK pins** for bsc-mainnet | on-chain reads via `bsc-dataseed.bnbchain.org`; `bnbagent-sdk` `python/bnbagent/config.py:71` |
| Registration is `register(string agentURI)` selector `0xf2c298be`, **permissionless, non-payable**, `agentId = _lastId++`; measured **163,334 gas ≈ 0.0000082 BNB** at 0.05 gwei | source + deployed-bytecode selector check + `eth_estimateGas` |
| **`newAgent(string,address)` (`0x4750d0fa`) is ABSENT from the deployed bytecode** — the signature repeated in blog posts is from an obsolete draft | bytecode selector scan |
| **BRC8004** (`0xfA09B3397fAC75424422C4D28b1729E3D4f659D7`, 26 agents, last push Feb 2026) is an abandoned BNB-specific fork | on-chain `totalSupply()` + repo activity |
| **ValidationRegistry is not deployed** by the canonical team on BSC or any listed chain; 8004scan reports `total_validators: 0` | canonical README address table + 8004scan `/stats` |
| **293,117 agents minted on BSC**, but ~two-thirds are bulk/spam (65.8% inline `data:` URIs; 26 byte-identical "Ave.ai Trading Agent" in a 70-agent subsample) | `ownerOf` binary search + tokenURI sampling |
| Only **~1–2%** of sampled agents have any feedback client — so `min_feedbacks>=1` is a spam filter, not a coverage gap | `getClients(agentId)`, n=160, 2 hits |
| `getSummary` requires a non-empty `clientAddresses` array → **there is no global on-chain reputation score**; any track record must be computed off-chain | ReputationRegistry source |
| ReputationRegistry is `0x8004BAa17C55a88189AE136b182e5fdA19dE9b63`; same CREATE2 addresses as the user's prior X Layer work, so `giveFeedback` selector `0x3c036a7e` ports unchanged | canonical deployment table + prior X Layer notes |
| **`facilitator.b402.ai` is DNS-dead and its repo was archived 2026-04-23** — a live trap for anyone copying it | DNS + HTTP probes returning code `000` |
| The **official Binance x402 facilitator endpoint could not be verified**; `*.binance.com` probes hit a wildcard catch-all that also answers invented subdomains | probes of 4 candidate hosts |
| 8004scan's **public** API is `/api/v1/public/...`, free, **10 req/min anonymous**; Docket uses the *internal* `/api/v1` at a claimed 180 req/min | 8004scan `/developers`; `docket/scan8004.py:1-22` |

### Not verified / could not verify

- Whether BNB's judges apply the BSC-liveness gate to *surfaced* agents (the 506, which
  qualify) or to *hireable* ones (the six, which mostly do not). Both readings are
  defensible from the published wording. This is the single largest binary risk.
- The rubric's **weights** are unpublished (the briefing verified the `Weight` column is
  empty). All points-per-day rankings here assume roughly equal weighting across
  Functionality / Data Quality / Agent Diversity; if Functionality dominates, G2 and G7
  outrank G1.
- Phase 2's criteria are `[REDACTED]`. §(e) is inference from the adoption language, not
  from a published rubric.
- Whether the hackathon registration was completed and whether one entry may take all
  three tracks — a user-only item flagged overdue on Aug 14 and not checkable from here.
- Whether the repo's git history is clean of secrets (required before the public flip).
- **DoraHacks could not be searched** — both `dorahacks.io/api/hackathon/search` and
  `/api/buidl/search/` return an AWS WAF human-verification challenge. If BNB syndicated the
  hackathon there, entrant BUIDLs are public and this audit is blind to them. Ten minutes in
  a real browser closes this.
- **X / Twitter could not be searched** — `site:x.com` queries returned only press
  syndication; unauthenticated fetches of x.com fail. Absence there is not evidence.
- Several rivals' live sites are React SPAs that could not be rendered
  (`KaiVenn52/mandate-bnb-agent`, `devgreyman/Superagenthub`, `FeeeeelixWong/mandatefi`,
  `dropmoltbot/era-market`). Their README claims of four-category coverage are unverified.
- The `agents.chainhelix.io` four-category mainnet cluster (`269223/224/226/228`,
  registered 2026-08-17) **could not be attributed** — it is either a rival's fleet or BNB's
  unpublished reference set.
- The total agent count on BSC is reported inconsistently across five sources (44k / 200k /
  247k / 275k / 447k). Docket serves `registry_total: 247,146`. I did not reconcile these;
  the spread is itself a Data Quality attack surface any entrant can be hit with.
- The competitive field — see §(c) for exactly what was and was not found.
- I did not execute any test suite (read-only mandate); the 792-passing figure is the
  Aug-14 briefing's, not re-verified.

---

## (e) The Phase 2 / adoption question

BNB is not buying a submission. *"Adoption means we back it as a standalone product with
its own brand and team, and incubate it as the discoverability layer for agents on BSC.
It's something we intend to keep alive, drive users to, and grow."* Read that as three
questions Docket must answer on the page, not in a README.

**1. Can a third party list? Today: structurally no.**
`marketplace/registry.py:59` and `hire/catalogue.py:630` are hardcoded `dict`s.
`registry.py:47-52 EMPTY_CATEGORY` states the policy as a *virtue*: *"Docket lists a
service only where it runs the work itself and can show a recorded run behind it… It does
not stock the shelf with agents from the registry."* That sentence is excellent integrity
engineering and, read by an acquirer, is a statement that the product cannot grow. It is
the single most damaging sentence in the codebase for this specific prize.

The concrete minimum: a published **listing contract** — the exact JSON a third party
serves at their agent's `tokenURI` for Docket to index them as hireable stock; the exact
evidence Docket requires before a listing leaves `preview`; and the admission gates
(`fresh_paired_benchmark`, `cold_canary`, `decision_grade_presenter`, `true_settlement`)
reframed from *internal status flags* into *the published bar every provider clears*.
Docket already has the hardest part — an objective, machine-checkable admission standard
that most marketplaces lack. It is described as a self-assessment. Reframing it as a
provider standard costs a page of prose and converts the weakness into the differentiator.

**2. What is the growth story? Today: absent.**
There is no acquisition surface at all — no way for an agent owner to discover Docket, no
claim flow ("this is my agent, let me add a description"), no notification, no embed, no
badge. Docket already indexes 506 agents with owner addresses on chain; the cheapest
credible growth mechanism in the whole design space is a **claim-your-listing** flow keyed
to the owner address, plus a "listed on Docket" badge. Neither exists. State the funnel
explicitly in the submission even if unbuilt: *index → claim → list → admit → hire*, with
the current build occupying stages 1 and 5 and the middle three named as the roadmap.

**3. Is it operable by someone other than the author? Partially — and this is a real strength.**
`deploy/systemd/` carries three hardened unit files (`ProtectSystem=strict`,
`NoNewPrivileges`, `ReadWritePaths`), the canary runs unattended and its verdict is a
public endpoint, `docs/deployment-runbook.md` and `docs/source-deploy-manifest.md` exist,
and the canary is configured through Sep 24. Almost no hackathon entry can show a
third-party-verifiable uptime proof. **Say this loudly** — it is the one place where
"we intend to keep this alive" is already answered with evidence rather than a promise.

What undercuts it: the deployed commit lags the branch, and the one thing an operator most
needs — a scheduled registry refresh — is exactly the timer that does not exist (G3).
Fixing G3 makes the operability claim complete rather than partial.

**The strongest unused asset: BNB's own problem statement is Docket's spec.**
BNB's launch blog states the problem verbatim (fetched today):

> *"Currently, hiring an agent means digging through X threads and GitHub repos, with no
> way to compare what an agent does, **whether it's live**, or **how it has performed**."*

Those two clauses are, precisely, Docket's two measured planes: a per-endpoint liveness
probe published with its method and its denominator (`/stats.probe_method`), and a
per-service performance record published with its window and population
(`marketplace/models.py Metric`). Docket did not merely build a marketplace — it built the
two things BNB named as missing, and it is the only entrant that can quote BNB's own
sentence back with a measurement under each clause. **This does not appear anywhere in
Docket's copy, the README, or `/llms.txt`.** It should be the first line of the submission
and the homepage hero. Cost: one paragraph.

**The narrative Docket should actually tell BNB**, which is defensible and is not currently
told anywhere:

> Every other marketplace will show you a list of agents and a green "verified" badge. We
> read 506 ERC-8004 agents on BSC and found 31 that declare a callable endpoint and 13 that
> answered — and we publish that, with the denominator, instead of a badge. TermiX's own
> live listings carry `topRated` on 83% of stock and `reviewCount: 0`. If BNB adopts a
> discoverability layer, the thing that has to survive contact with real users is whether
> its numbers mean anything. Ours state their population, their window, and what they do
> not prove. That is the asset. The inventory is the part we can grow; the standard is the
> part that is hard to build later.

That reframes Docket's actual strength — evidence integrity — as the acquisition thesis,
which is the only framing under which a six-service marketplace beats a
five-hundred-listing one.
