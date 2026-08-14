# Docket — Codex Strategic Assessment, round two (2026-08-14)

_Produced by Codex CLI 0.147.0, model `gpt-5.6-sol`, reasoning effort `xhigh`, service tier priority, read-only sandbox. 272,266 tokens. Input: `docs/deliberation/2026-08-14-BRIEFING-V2.md`._

| Track | Position | Why |
|---|---|---|
| **TermiX** | **Winnable, conditional** | Docket can win if it ships a genuinely settled paid hire, replaces the free-personalized-call model, and produces a new sponsor-shaped Agent Advantage Report on Sep 1–5. The current v2 is not that report. |
| **PancakeSwap** | **Winnable** | The published brief expressly permits analysis. Range Doctor’s structural no-key safety and the measured LP-fee correction are legitimate benefits. The submission needs one singular hero agent, decision-grade presentation, and fresh comparative proof—not necessarily trading volume. |
| **BNB $30,000 main track** | **Not genuinely winnable under the current one-builder, 26-day constraint** | A shortlist is attainable. First place requires four identity-bound, equally deep BSC agents, fresh operations, real paid activation, a genuine supply-side marketplace rather than six first-party offers, and adoption-grade packaging. That is materially more than the remaining calendar supports. |

# Docket strategic assessment — round two

## Executive call

“Win all three” is not a credible execution target with one solo builder and the outstanding user gates. The correct portfolio is:

1. **TermiX first place**
2. **PancakeSwap challenge**
3. **BNB shortlist-quality submission**, preserving the possibility of a surprise win without allowing the main track to consume the work that makes the first two winnable.

If forced to pick two, pick **TermiX and PancakeSwap**.

Making BNB first place genuinely winnable would require changing the resource constraint: clear every user gate immediately, suspend competing work, add implementation/operations capacity, bind all four services to live BSC identities, and onboard at least one independent provider through a real supply path. Without that change, Docket remains a well-engineered first-party service portfolio presented inside marketplace furniture.

I did not independently re-fetch the sponsor pages. I treated §1 of the briefing as the live source of record, as instructed. I also did not rerun pytest or mutate the workspace; the 792-test and deployment-parity claims below come from briefing §2. Hidden BNB Phase 2 criteria remain unknowable.

## Why the tracks diverge

TermiX and PancakeSwap reward what Docket already does unusually well: bounded work, exact outputs, honest limitations, fast delivery, and reproducible evidence. BNB is buying something broader: an ecosystem distribution product whose marketplace can be adopted and grown. Its sponsor language explicitly prioritizes the marketplace—not a portfolio—and a frictionless find-and-hire journey ([BRIEFING-V2.md:43–52](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:43)).

Docket’s actual inventory is still two hard-coded dictionaries of Docket-operated services ([registry.py:60–397](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:60), [catalogue.py:302–603](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/catalogue.py:302)). More importantly, all four scored-category services explicitly have no bound BSC identity:

- Health Guard: [registry.py:61–69](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:61)
- Yield Router: [registry.py:98–106](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:98)
- Grid Operator: [registry.py:131–144](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:131)
- Range Doctor: [registry.py:170–177](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:170)

Only the stale, halted SOLVENT listing is identity-bound. That is at least a serious eligibility ambiguity against “agents surfaced … must be live on BSC,” not merely a narrative weakness.

## Direct response to Claude’s seven claims

### 1. Data Quality is the highest-leverage main-track gap

**Agree for BNB; refine “pure build” and “weeks.”**

Freshness is the best points-per-effort improvement inside the main-track rubric. BNB explicitly asks for real-time decision-quality data ([BRIEFING-V2.md:65–71](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:65)), while the current snapshot will be 33 days old on Sep 9.

But this is not just “add a scheduler”:

- The application resolves the latest completed snapshot once at process startup and then keeps serving that ID ([routes.py:288–320](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/api/routes.py:288)). A successful background refresh remains invisible until the app reloads or snapshot promotion becomes dynamic.
- A new, distinct promotion bug exists. `_sweep()` can stop because of `max_pages` or a non-advancing paginator and then still call `finish_snapshot()` ([ingest.py:62–95](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/ingest.py:62)). `latest_complete_snapshot_id()` checks only `finished_at` and `sampled`, not whether `sampled == expected` ([store.py:183–197](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/store.py:183)). `coverage_report()` knows the proper completeness condition ([coverage.py:56–66](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/coverage.py:56)). Automation can therefore promote a finished-but-partial sweep.

I disagree that weeks of history are required by the published rubric. BNB names freshness, not a minimum observation window. Several days of successful cadence, visible failure history, and stale-state handling can substantiate freshness. Start now because every delayed day is unrecoverable operational evidence.

Across all three tracks, however, the single highest-leverage build is **a settled paid hire with a human-readable result and persistent receipt**. Freshness primarily moves BNB; paid hiring unlocks TermiX, strengthens BNB Functionality, and supplies the required report’s agent arms.

### 2. One-cent pricing is a TermiX risk

**Agree, but the answer is neither $20 nor tiering.**

Concrete recommendation:

> **Charge 0.50 $U for every completed competition hire through Sep 23. Provide one separate, prefilled free sample; require actual settlement for personalized `/hire` work. Remove SOLVENT’s historical read from paid stock.**

Why 0.50 $U:

- It matches the observed floor of TermiX’s live marketplace, so Docket is no longer priced below the entire surveyed market ([BRIEFING-V2.md:131–144](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:131)).
- It remains forty times below the $20 p25 and preserves the literal price-and-speed advantage TermiX scores.
- Docket sells 2–40-second atomic calls, not one-to-five-day professional engagements. Current timings are encoded alongside the one-cent prices in [catalogue.py:331–334](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/catalogue.py:331), [catalogue.py:430–433](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/catalogue.py:430), and [catalogue.py:478–481](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/catalogue.py:478). Charging $20–$70 for current previews would make “beats doing it yourself” harder to prove.
- The current manual report arms have zero direct cash cost. A higher price does not manufacture value.
- A real settled fifty-cent payment is stronger evidence than a nominal $20 authorization that moves nothing.

The actual problem is larger than price. Current hires are full personalized work served free, and even a valid authorization never becomes a paid hire:

- Every request consumes the same 20-per-hour allowance ([routes.py:112–118](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/api/routes.py:112)).
- A valid authorization is still rejected after the allowance is exhausted ([routes.py:913–938](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/api/routes.py:913)).
- Before exhaustion, it merely changes the receipt to `verified_unsettled` ([routes.py:965–979](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/api/routes.py:965)).
- The verifier explicitly omits settlement, asset-domain binding, replay protection, and `validAfter` ([x402.py:8–31](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/x402.py:8)).

Keep $U for this deadline because that is the EIP-3009 asset the current verifier understands; do not announce USDC support until a current facilitator/Permit2 path has been independently reverified.

### 3. SOLVENT is the only sponsor-named silence

**Disagree. SOLVENT is the most explicit silence, not the only one.**

SOLVENT lacks the exact win rate, window, and risk fields TermiX names. Its current listing instead says the historical read proves neither correctness nor what happened afterward ([registry.py:249–294](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:249)).

But three scored-category services are even more silent:

- Health Guard has no metrics or evidence ([registry.py:61–95](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:61)).
- Yield Router has no metrics or evidence ([registry.py:98–128](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:98)).
- Grid Operator has no metrics or evidence ([registry.py:131–167](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:131)).

The grid evidence cannot substitute for a trading record. Its committed run says no transaction was sent, the comparison is empty, and the claim was refuted ([04-grid-replay.json:1–10](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/advantage/v2/runs/04-grid-replay.json:1), [04-grid-replay.json:29–51](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/advantage/v2/runs/04-grid-replay.json:29)).

Recommendation:

- Give SOLVENT an Aug 20 drop-dead gate.
- If funded and genuinely resumed, derive wins/total, exact dates, exposure, fees, drawdown, and risk from its real record.
- If it misses the gate, preserve it as research evidence but remove it from the paid hero path.
- Use Warden’s security task to satisfy TermiX’s required high-stakes category. The sponsor requires trading, stock, **or security**, not specifically trading ([BRIEFING-V2.md:125–129](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:125)).

Do not manufacture a 20-day “trading record” to fill a rubric field.

### 4. Four advisors where BNB describes four actors

**Real scoring risk, but not proof that four fund-moving executors are mandatory.**

The category definitions are embedded inside the Agent Diversity rubric and use manages/resets, places/manages, routes, and protects ([BRIEFING-V2.md:54–71](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:54)). Docket’s internal definitions quietly soften those verbs:

- Rebalancing becomes “reads or manages.”
- Yield “states what moving it would cost.”
- Health “acts, or tells the borrower to.”

Those phrases are in [models.py:62–94](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/models.py:62).

The implementation is weaker still:

- Range Doctor is read-only.
- `/hire/grid-operator` constructs `GridPreview`, not the armed class ([catalogue.py:150–187](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/catalogue.py:150)).
- Grid’s armed class refuses construction without a submitter, and Docket ships none ([operator.py:23–27](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/agents/grid/operator.py:23), [operator.py:305–330](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/agents/grid/operator.py:305)).
- Yield stops after drafting one swap leg; it does not add liquidity to the destination ([registry.py:121–128](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/marketplace/registry.py:121)).
- Health has no armed counterpart or Venus submission path ([catalogue.py:190–213](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/catalogue.py:190)).

However, BNB’s Functionality wording requires activation, not four on-chain transfers. Data Quality also plainly contemplates decision support. The defensible minimum is:

- Grid: one bounded real action, if approved.
- Health: persistent monitoring plus actionable alerts can qualify without autonomous repayment.
- Range: exact current diagnosis, usable recenter plan, and measured outcome evidence.
- Yield: explicit universe, economic comparison, and a complete route plan—not merely “pool X has higher APR.”
- All four: equal sampleability, identity, evidence, activation, failure recovery, and track record.

Current Docket does not meet that bar. Four separate money-moving systems would be disproportionate and unsafe, but four one-shot advisors are not equal-depth actors either.

### 5. PancakeSwap is winnable and under-claimed

**Agree that it is winnable; disagree that zero volume is a published defect.**

Pancake explicitly permits yield discovery and market research, while fund safety is the only absolute ([BRIEFING-V2.md:166–181](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:166)). Therefore zero routed volume is not a rubric failure.

The strongest singular submission is:

> **Range Doctor — the Pancake LP agent that prevents an LP from making decisions using gross fee yield or an out-of-range position.**

Yield Router is supporting capability, not a second hero.

Docket already has a concrete sponsor benefit: over 22 eligible Pancake pools, quoting gross overstated the net rate by a median 49.3%, and the gross error exceeded display-rounding error on all 22 ([01-liquidity-arithmetic.json:7–25](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/advantage/v2/runs/01-liquidity-arithmetic.json:7)). That is far stronger than “AI for LPs.”

What remains:

- Add a one-click known-wallet sample; Range Doctor currently requires a wallet with no default ([catalogue.py:315–329](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/catalogue.py:315)).
- Present token prices, economic consequence, and next action in plain language.
- Preserve expandable raw evidence.
- Produce a fresh paid-hire-versus-manual report task.
- Keep the no-key path as the primary safety claim.

The current browser simply dumps the returned JSON into `<pre>` ([app.js:532–562](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/api/web/app.js:532)). That still loses the Pancake demo even though the underlying work is legitimate.

One tiny session-capped Grid proof is useful upside for BNB and Pancake, but the Pancake submission must not depend on it. If the user does not approve it by Aug 23, submit the analysis agent honestly and do not imply routed volume.

### 6. The BNB adoption question is unanswered in the narrative

**Disagree: this is a product gap, not a narrative gap.**

BNB says it wants the marketplace itself rather than a portfolio of agents. Docket currently has:

- hard-coded first-party inventory;
- no provider submission or ownership-verification path;
- no persistent hire/payment/action history in the SQLite schema;
- four unbound flagship identities;
- no paid completion;
- no service canary history;
- no clean install guarantee.

A growth-funnel paragraph cannot repair those facts.

For a genuine BNB-winning attempt, Docket needs a signed provider manifest, identity ownership proof, category canary, price and input schema, evidence binding, and publication without a code deploy. It also needs at least one non-Docket provider successfully onboarded and hired. That is the point at which “marketplace” becomes true operationally.

This is also why the BNB win is the sacrificed target under solo capacity. Do not spend the next 26 days constructing a rushed provider platform that damages TermiX and Pancake.

### 7. Housekeeping is being carried too long

**Agree on urgency; refine “none of it is hard.”**

Registration and Terms are overdue, while repository visibility and final approval are user-only gates ([BRIEFING-V2.md:325–344](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:325)).

Creating three files is easy. Releasing a private repository safely is not purely clerical. It needs:

- license choice;
- secret and history review;
- clean installation;
- reproducible setup;
- live/source parity;
- explicit user approval.

There is already a clean-install defect: the explicit package list omits `docket.agents.venus` and `docket.agents.yield_router` ([pyproject.toml:23–37](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/pyproject.toml:23)), although the hire catalogue imports both lazily ([catalogue.py:190–237](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/hire/catalogue.py:190)). Source-tree tests can pass while a built distribution loses two scored categories.

Treat public readiness as an Aug 28 gate, not Sep 8 housekeeping.

## The unnamed problem

**Stage 4 built the wrong artifact for TermiX’s eligibility gate.**

TermiX requires three real tasks run both ways—agent hired through the marketplace versus without it—with time, cost, output quality, and actual outputs attached.

The shipped v2 explicitly says:

- only v1 contains agent-versus-human comparisons;
- v2 is agent-versus-null;
- v2 does not supersede v1 ([report.py:114–141](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/advantage/v2/report.py:114)).

Therefore Sep 1–5 cannot mean “rerun v2.” It must produce a new preserved report version with three paired production hires and three manual arms.

There is a second evidentiary warning. Briefing §2.2 calls the v2 specifications “pre-registered,” but repository history supports that strongly for only the Grid experiment. Liquidity and Security entered history with their completed runs, and Security’s claim and question were rewritten afterward ([report.py:53–111](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/advantage/v2/report.py:53)). The report discloses this honestly, but it cannot be submitted as if all three were independently pre-registered.

The new final report must be git-provably specified before either arm runs. V1 and v2 remain attached as historical evidence; neither is rewritten.

Recommended final tasks:

1. Range Doctor versus manual Pancake LP-position diagnosis.
2. Yield Router versus manual Pancake pool/yield comparison.
3. Warden versus manual security review on fresh, preselected inputs.

For each: identical inputs, prewritten quality rubric, paid marketplace receipt, wall time, direct cash cost, output hash, full output, failure retention, and a separate manual record. Warden satisfies the required high-stakes category.

The deeper pattern is that Docket tests numerical honesty more rigorously than it tests whether the served product claim matches the runnable product. That is why the homepage says every service has a recorded run while three have none ([index.html:48–59](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/api/web/index.html:48)); “Grid Operator” can only preview; “paid” cannot settle; and the installable package omits two categories.

## What must survive BNB Phase 2

The following are diligence inferences from BNB’s published adoption intent, not claims about the redacted rubric.

A submission that survives a second look needs:

- Four scored services bound to inspectable BSC identities and callable from clean clients.
- A clean-browser category → sample → paid hire → result → receipt journey.
- Human-readable results, not raw JSON as the primary output.
- Real settled payment with nonce/idempotency protection and a persistent proof.
- Fresh snapshots with safe promotion, failure history, staleness disclosure, and app reload.
- Service-level canaries and availability history.
- Equal evidence depth across all four categories; no empty metrics hidden behind elaborate limitations.
- Public source, license, README, AI usage disclosure, architecture, threat model, operations runbook, and exact deployment provenance.
- A built-wheel installation test outside the checkout.
- Preservation of v1’s loss, v2’s refuted Grid run, and all failed trials.
- At least one externally verifiable Pancake action receipt if the user approves it.
- A claims-to-evidence table mapping every submission sentence to an API field, artifact hash, identity, or transaction.
- Uptime and freshness monitoring through Sep 23.
- For a genuine BNB-winning rather than shortlist attempt: provider onboarding and at least one independent provider successfully hired.

## What not to build

- No Agent Studio, Bedrock, or `bag` work; BNB explicitly says not to chase it.
- No ERC-8183 browser flow. Its seven-day mainnet settlement window does not solve Aug 31.
- No Altana bounty UI. Altana may support the optional Grid proof; the bounty itself is out of scope.
- No full V3 automatic range reset.
- No full Yield Router liquidity migration.
- No Venus transaction executor.
- No autonomous long-running Grid keeper before filled-level and nonce state are persisted.
- No second chain or additional protocol.
- No opaque trust score or global recommendation system.
- No $20–$70 price applied to seconds-long previews.
- No cosmetic redesign before payment, result semantics, freshness, packaging, and report work.
- No rewrite or removal of v1/v2 evidence.
- No provider-onboarding platform in the recommended TermiX/Pancake plan. This knowingly concedes BNB first place; if resources change, provider onboarding becomes the first major addition.

## Build order

| Date | Work | Exact files/functions | Exit gate |
|---|---|---|---|
| **Aug 14** | Clear human gates and lock strategy | User completes hackathon registration, reads Terms, files 8004scan Pro form, schedules payment/Grid approvals, and decides SOLVENT funding. Begin the final report specification. | Registration/Terms no longer block eligibility; TermiX/Pancake are primary; BNB is shortlist scope. |
| **Aug 14–15** | Fix immediate integrity and release defects | `pyproject.toml`: package Venus and Yield Router. `.github/workflows/ci.yml`: build a wheel, install it outside the checkout, smoke all four hires. `docket/api/web/index.html`: remove the false “every service has a recorded run” claim. `docket/api/web/app.js`: make integers string/BigInt-safe and add a real array control for Grid’s `filled` field. | Clean installed artifact contains all four categories; homepage claims match records; custom Grid inputs are not rounded or misparsed. |
| **Aug 14–17** | Build safe freshness and start the operational window | `docket/store.py`: explicit candidate/promoted snapshot state or a promotion predicate requiring true completeness. `docket/ingest.py::_sweep`: closed `stop_reason` and no promotion of bounded/non-advancing sweeps. New `docket/refresh.py::refresh_once`: ingest → enrich → probe → validate → promote. `tests/test_store.py`, `tests/test_ingest.py`, new `tests/test_refresh.py`. Add VPS timer/service definitions and reload the app only after promotion. | A partial sweep cannot become current; registry refresh runs at least every six hours; owned-service canaries run more frequently; the served snapshot actually advances. |
| **Aug 15–20** | Replace the non-payment path with real x402 settlement | First reverify the current official Binance/x402 facilitator contract. `docket/hire/x402.py`: asset-domain binding, both validity bounds, exact message validation. New `docket/hire/settlement.py`: settle exactly once and return proof. `docket/store.py`: persistent payment/hire records with unique nonce/payment ID and request/output hashes. `docket/api/routes.py::hire`: paid work runs only after settlement; replay is idempotent or refused. `docket/hire/catalogue.py`: price paid services at `0.50 $U`; remove SOLVENT from paid stock. `docket/api/web/app.js`: separate “Try sample” from “Pay 0.50 $U and hire.” | **Aug 20 kill gate:** a controlled preflight can settle once, reject replay, and bind payment to output. If not, TermiX first place becomes unlikely. |
| **Aug 18–23** | Make PancakeSwap the hero experience | `docket/agents/pancake/doctor.py`, `positions.py`: decision-grade token/price and economic presentation while preserving raw evidence and stale-fee disclosure. `docket/api/web/app.js`: Range- and Yield-specific result presenters with finding, observed block/time, economic consequence, next step, primary limitation, and expandable JSON. `docket/hire/catalogue.py`: prefilled known-wallet sample path. | A stranger can run the Pancake hero without inventing an address and understand the result without reading JSON or ticks. |
| **Aug 18–24** | Remove BSC identity ambiguity | Prepare four ERC-8004 registrations and service cards; user approves any transactions. After confirmation, bind identities in `docket/marketplace/registry.py`; expose registration URIs and live endpoint/canary evidence. | Every scored-category service says “bound to BSC agent,” not “No BSC identity bound yet.” |
| **Aug 20** | SOLVENT drop-dead decision | If funded/resumed, add computed wins/total, exact window, exposure, fees, drawdown/risk to its evidence record. Otherwise preserve it as historical research and exclude it from the paid/report hero path. | No submission sentence presents a halted provenance relay as a trading record. |
| **Aug 21–25** | Optional bounded Grid proof, after core gates | Reverify the current Altana SDK. Add only the minimal session-key submitter needed by `GridOperator`; reuse `docket/execution/*` and `docs/runbooks/grid-mainnet-proof.md`. Rehearse on testnet. Present exact amount/cap/gas/revoke flow by Aug 23. Execute one tiny mainnet proof only with explicit user approval. | If approved: registered session → agreed simulation → one confirmed swap → cap decrement → revoke → post-revoke refusal. If not approved, no volume claim appears. |
| **Aug 21–27** | Add equal-depth evidence where honestly possible | `docket/marketplace/registry.py`: measured canary/task figures for Grid, Yield, and Health. `docket/store.py`: service availability and hire receipt history. `docket/api/web/app.js`: consistent failure/recovery states. Run cold browser and `/llms.txt` client tests. | All four category pages have current evidence, sample activation, understandable results, and honest recovery—not merely category labels. |
| **Aug 24–28** | Public/adoption package | Root `README.md`, `LICENSE`, `AI_USAGE.md`; architecture, deployment/runbook, threat model, API/payment semantics, evidence reproduction, and source/deploy manifest. Perform secret/history review. User flips repo public by Aug 28. | Clean clone → wheel install → tests → four service smokes succeeds; public source and live deployment identify the same artifact. |
| **Aug 14–27** | Build and lock the real TermiX report specification | Add `docket/advantage/v3/spec.py`, `harness.py`, `report.py`, `specs/*.json`, and `runs/*.json`; update `pyproject.toml`, `docket/api/routes.py`, and the web page. Reuse v1 hashing/timing and v2 failure retention. Specify Range, Yield, and Warden paired tasks now; lock exact inputs, quality rubrics, clocks, costs, and stopping rules by Aug 27, before either arm runs. | Git proves each specification predates every corresponding run. No post-result claim or question edits. |
| **Aug 27–31** | Cold paid-hire rehearsal | Run unfamiliar human and coding-agent flows from a clean state. Fix only dead ends. Exercise sample separately from paid work. Persist receipts and recovery outcomes. | **Aug 31 hard gate:** a stranger completes a settled `0.50 $U` personalized hire end to end; payment proof, input hash, output hash, and receipt agree. `verified_unsettled` fails the gate. |
| **Sep 1–5** | Run the sponsor-required Agent Advantage Report | Execute the three locked paired tasks: paid Docket hire versus manual workflow. Record wall time, settled price, gas/facilitator fees, direct manual cost, separately stated labor proxy if used, prewritten quality score, failures, and full outputs. Publish v3; link v1 and v2 as preserved appendices. | Three fresh tasks satisfy the sponsor’s exact both-ways/time/cost/quality/outputs requirement; Warden supplies the high-stakes task. No backfilling. |
| **Sep 6** | Freeze | Deploy the exact tested commit. Record commit, wheel hash, OpenAPI hash, snapshot ID, report hashes, identity bindings, and payment/action receipts. Begin uptime and freshness watch through Sep 23. | No feature changes after freeze; live/source/evidence hashes agree. |
| **Sep 6–7** | Submission and Phase 2 evidence | Prepare the live category → sample → paid hire → result → receipt demo; final Report; freshness history; clean-install log; claims-to-evidence table; limitations; optional Pancake transaction/revoke proof. | A judge can independently repeat every headline flow without private instructions. |
| **Sep 8–9** | Approval and submission | Present the final form, repository, live URL, report, demo, identities, and evidence package to the user. Submit only after explicit approval. | Submission accepted before Sep 9; public service remains monitored through Sep 23. |
