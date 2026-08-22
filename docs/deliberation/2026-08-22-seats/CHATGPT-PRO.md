# ChatGPT Pro audit — "Align Docket For Hackathon" (owner-supplied PDF, 2026-08-22)

Text extracted from the PDF with pdftotext. ChatGPT had NO repository access (the repo is private) and says so; this is a sponsor/product/positioning audit, not a code audit.

```text
       Worked for 22m 42s

           Called tool

           Called tool

      Called tool

   Called tool

Docket can contend for all three prizes—but not as a normal
agent directory

First, one important correction

The $30,000 BNB main-track prize is awarded to one winner, together with the opportunity for
official adoption as the canonical BNB Agent Studio marketplace. It is not a pool shared among
several winners. The partner prizes are judged independently: TermiX awards $6,000/$3,000/$1,000,
and PancakeSwap awards 1,000 CAKE. One project can win the main track and partner bounties
simultaneously. BNB Ch… +1

Repository audit status

I checked the exact repository through public GitHub and the connected GitHub integration. It currently
returns 404 and is not present among your publicly accessible repositories. That means I have not
been able to inspect:

      The current source code and architecture.
      Contract deployments and ABIs.
      Whether data is live, mocked, cached, or hard-coded.
      Wallet, hiring, payment, and transaction flows.
      Build, lint, tests, security configuration, and secrets.
      The deployed user experience.
I will not pretend this is a code audit when the code is inaccessible. What I have completed is the
deeper sponsor, protocol, product, judging, competitive-positioning, and technical due-diligence audit.
The published rules explicitly require the application to be functional and publicly accessible
during judging and the surfaced agents to be live on BSC; the eligibility section does not explicitly
state that the repository itself must be public. BNB Ch…

1. The winning product thesis
Docket should be positioned as:

    Docket is the evidence-backed marketplace for BNB agents—discover, compare, and hire
    live agents using verified outcomes, scoped permissions, and onchain job receipts.

Tagline

    Hire by evidence, not promises.

This is far stronger than “a marketplace for AI agents.”

There are already more than 200,000 ERC-8004 registrations on BNB Chain, and 8004scan already
provides raw registry discovery. BNB is explicitly asking for a product that makes agents
understandable, comparable, and hireable—not another registry explorer and not merely a portfolio
containing your own agents. BNB Ch… +1

Docket’s name gives you a natural product primitive:

Every agent gets a Docket

An agent’s Docket should contain:
      Its verified ERC-8004 identity.
      Whether its service endpoint is actually live.
      What it can and cannot do.
      Price and expected completion time.
      Supported chains, protocols, pools, and assets.
      Performance evidence and measurement window.
      Its allowed contracts, methods, tokens, and spend limits.
      Completed ERC-8183 jobs.
      Transaction and deliverable hashes.
      Disputes, failures, refunds, and policy violations.
      Data freshness and confidence level.

The distinction becomes:

Existing layer  Primary question

ERC-            “Does this agent identity exist?”
8004/8004scan

TermiX          “Can agents buy and sell work through onchain commerce?”

Docket          “Which agent should I trust for this specific job, under what limits, and what proof
                supports that decision?”
That makes Docket complementary to both 8004scan and TermiX rather than a clone of either.

2. Why proof and readiness must be the moat

A raw ERC-8004 rating cannot safely be treated as the definitive trust score.

ERC-8004 provides separate identity, reputation, and validation registries, with pluggable trust
models. It explicitly leaves payment outside the protocol. In other words, it provides useful primitives,
not a complete reliable marketplace ranking system. Ethereum Impr…

The current 8004scan registry snapshot also illustrates the cold-start problem: many recently
registered agents appear with zero score, zero feedback, and zero stars. 8004s…

More importantly, a June 2026 empirical study of ERC-8004 deployments reported that:

      Only 4% of BSC registrations exposed a valid registration file with at least one live service
      endpoint.
      59.2% of BSC reviewers in the study exhibited coordinated Sybil patterns.
      After filtering Sybil-flagged feedback, 72.3% of rated BSC agents had no valid feedback
      remaining.
This is a preprint and should not be treated as the final word on the ecosystem, but it clearly
demonstrates why Docket should verify operational evidence rather than blindly displaying raw
ratings. arXiv +1

The Docket readiness ladder

Every indexed agent should be placed in one transparent stage:
 1. Indexed — found in the BSC registry.
 2. Registered — identity and owner resolve correctly onchain.
 3. Reachable — registration file and declared service endpoint respond.
 4. Hireable — quote or negotiation completes successfully.
 5. Benchmarked — passed a standardized Docket task.
 6. Proven — completed paid jobs with verifiable outputs and receipts.

Only levels 5 and 6 should receive a Docket Verified badge.

Never label a newly registered agent “bad” merely because it lacks history. Label it Insufficient
Evidence.

Do not hide everything behind one score

The primary comparison should expose separate dimensions:
Dimension           What it measures
Availability        Endpoint uptime, heartbeat, latency, last successful check

Reliability         Job completion, failure, refund, timeout, and dispute rates

Outcome quality Category-specific performance, not generic ratings

Safety              Permissions, caps, simulations, audits, revocation, policy compliance

Value               Price, completion time, gas, and outcome versus a manual baseline

Trust               Identity, verified economic counterparties, validation, and job-linked feedback

A composite score can be used internally for ranking, but the UI must show sample size, measurement
window, data freshness, and confidence separately.

3. Exact alignment with the three judging targets

The published BNB rubric requires all four categories to be first-class, a complete beginner-friendly
journey, accurate real-time data, and live BSC agents. Single-category submissions score poorly.
TermiX separately weights service value, measured agent advantage, high-stakes track record, and
marketplace quality. PancakeSwap wants genuine trader or LP value without putting user funds at risk.

        BNB Ch… +2

Target              What the judges actually     What Docket must show
                    want

BNB main track      Canonical human-facing       Outcome-based search, equal category depth, real-time
                    discovery and activation     data, compare flow, live activation, builder onboarding
                    layer

TermiX first place  Agents that materially       Fast low-cost services, actual outputs, three-task Agent
                    outperform the manual        Advantage Report, trading/security evidence, no
                    alternative                  instruction-heavy flow

PancakeSwap         Tangible benefit to traders  A live Pancake LP Range Guardian, safe grid execution,
first place         or LPs with fund safety      yield intelligence, measurable net benefits, deterministic
                                                 guardrails

The triple-win architecture

Docket should have two layers:
Marketplace layer

The open BNB marketplace that indexes external agents, normalizes their services, verifies their
readiness, allows comparison, and manages hiring.

First-party proof layer

Four live agents built or operated by Docket to prove each official category works end-to-end:
      RangePilot — LP rebalancing and range management.
      GridPilot — automated Pancake Infinity grid orders.
      YieldScout — risk-adjusted yield optimization.
      LiquidationShield — health-factor monitoring and protection.

The official blog says the submission should be the marketplace itself, not merely a portfolio of agents.
Therefore, these first-party agents are seed marketplace inventory and benchmark references, not
the entire product. Docket must also index and onboard external builders. BNB Ch…

A strong launch target is three credible listings per category, with at least one fully tested live activation
per category. That is not an official numerical requirement; it is the minimum needed for comparison to
feel like a real marketplace rather than a four-agent portfolio.

4. The product experience judges should see

Homepage

The homepage should not begin with wallet connection or a wall of agent cards.

It should ask:

    What do you need an agent to do?

Suggested outcome buttons:
      Protect my loan.
      Rebalance my Pancake LP.
      Run a trading grid.
      Find better risk-adjusted yield.
      Compare agents.
      List my agent.

Suggested hero copy:
    The BNB agent marketplace built on proof.
    Compare live DeFi agents by results, permissions, price, and onchain receipts—then hire in a few
    clicks.

Users should be able to browse everything without connecting a wallet. Wallet connection should
appear only when they fund a job or authorize execution.

Discovery

Natural-language discovery can interpret a request such as:
    “Protect my Venus BNB position if health factor falls below 1.35 without spending more than $250.”

The model should only convert that sentence into structured filters. The final matching and safety
decisions should be deterministic.

Filters should include:

      Category.
      Protocol and pool.
      Observe, Recommend, or Execute mode.
      Price.
      Expected completion time.
      Docket readiness level.
      Maximum permitted notional.
      Completed-job count.
      Dispute rate.
      Data freshness.
      Live, simulated, or backtested evidence.

Comparison

Allow three agents to be compared side-by-side using normalized category metrics.

Every result should explain:

    Why Docket ranked this agent here.

Avoid unexplained “AI Recommended” labels.

Agent Docket page

Every page should have the same structure:
 1. Identity — ERC-8004 ID, owner, agent wallet, chain, registration file.
 2. Live status — endpoint status, latency, last checked.
 3. Service contract — input, output, price, expected completion time.
 4. Supported environments — protocols, pools, tokens, versions.
 5. Performance — category-specific results, sample size, time window.
 6. Safety envelope — permitted contracts, methods, tokens, spend, slippage, expiry.
 7. Proof runs — completed jobs, outputs, tx hashes, evidence hashes.
 8. Failures and disputes — not just successful examples.
 9. Hire panel — preview, quote, configure, fund.
10. Revoke panel — current authority and immediate revocation.

Activation flow

The official judging journey is essentially:
    Land → find → understand → activate.

Docket should extend it to:

    Land → describe outcome → compare → inspect evidence → preview → set limits → receive
    quote → fund escrow → track job → inspect output → accept/dispute → revoke → review.

Use three authorization modes across every category:

Mode         Agent authority

Observe      Reads public or approved position data and sends alerts

Recommend Produces a transaction plan but cannot execute it

Execute      May perform only explicitly scoped actions under the user’s caps

Default to Recommend, not Execute.

5. The four categories must be equally deep

Category specification

Category     Flagship agent         Data shown before        Action            Evidence after
Rebalancing  RangePilot             hiring                                     hiring
                                                             Monitor,
                                    Pool/version, position   recommend,        Old/new ranges,
                                    value, current tick,     collect, or       collected fees, gas,
                                    range, in-range          rebalance         slippage, txs, net
                                    percentage, fees,                          benefit calculation
                                    estimated IL, gas,
                                    projected net benefit
Category       Flagship agent     Data shown before       Action             Evidence after
Grid trading   GridPilot          hiring                                     hiring
                                                          Place, cancel,
                                  Pair, range, grid       replace, and       Fills, closed cycles,
                                  count, spacing,         settle grid        gross/net PnL, gas,
                                  capital, risk cap,      orders             maximum drawdown,
                                  historical volatility,                     measurement window
                                  pool depth

Yield          YieldScout         Gross APR, reward       Recommend or       Old/new allocation,
optimization                      APR, fees, gas,         reallocate within  realized yield, gas,
                                  lockup, TVL/depth, IL   approved           exit cost, risk changes
                                  exposure, reward-       protocols
                                  token risk

Health-factor  LiquidationShield  Protocol, health        Alert, repay, add  Trigger, response
monitoring                        factor, liquidation     collateral, or     time, action, resulting
                                  price, buffer, oracle   reduce             health factor, cost, tx
                                  freshness, stress       exposure           receipt
                                  scenarios, response
                                  latency

Equal depth means equal product treatment

All four categories need:
      Their own normalized card metrics.
      Their own comparison view.
      Their own sample task.
      At least one live service.
      The same quote, preview, funding, job, evidence, and review flow.
      Category-specific outcomes rather than generic “success” labels.
      Explicit safety policies.

Do not build a spectacular Pancake rebalancing screen and leave Yield and Health Factor as static
cards. The rules explicitly say that this will score poorly. BNB Ch…

6. PancakeSwap winning feature: RangePilot

The strongest PancakeSwap submission is not a generic swap chatbot. It is:
    RangePilot turns PancakeSwap V3 and Infinity LP positions into evidence-backed managed
    services. It monitors range health, calculates whether rebalancing is economically justified,
    proposes or executes changes under hard user limits, and issues a verifiable receipt.

What RangePilot should do

1. Read the position

Identify:
      Pancake version.
      Pool and pair.
      Position token.
      Current price and tick.
      Existing lower and upper ticks.
      In-range status.
      Uncollected fees.
      Position token composition.
      Recent volatility.
      Liquidity depth.

Pancake’s V3 SDK supports concentrated-liquidity pool mathematics and position management, while
its Smart Router can find routes across V2, V3, and Infinity, including split and multihop routes.

        PancakeSwap … +1

2. Calculate net—not headline—benefit

The agent should not rebalance merely because a position goes out of range.

Its decision should evaluate:

    Expected incremental fee revenue
    − gas cost
    − swap price impact
    − slippage
    − estimated adverse-selection/IL cost
    − opportunity cost
    = expected net benefit

The Docket page should show this calculation before requesting authorization.

3. Generate a bounded recommendation

Output:
      Proposed new range.
      Expected active-liquidity duration.
      Expected fee opportunity.
      Required token conversion.
      Estimated gas.
      Maximum slippage.
      Confidence and assumptions.
      “Do nothing” as a valid answer.

4. Simulate first

Before execution:
      Re-read the position.
      Obtain a fresh quote.
      Recalculate net benefit.
      Simulate every transaction.
      Verify the recipient.
      Display token movements.
      Verify all target contracts against an allowlist.

5. Execute under an explicit policy

The policy should include:
      Maximum notional.
      Maximum daily notional.
      Token allowlist.
      Router and position-manager allowlists.
      Maximum slippage.
      Maximum price impact.
      Minimum expected net benefit.
      Cooldown between actions.
      Expiry.
      Maximum gas.
      Emergency pause and revoke.

6. Produce a Docket Receipt

The completed record should contain:

    agentId
    serviceVersion
    jobId
    positionId
    inputHash
    policyHash
    quotedPrice
    oldRange
    newRange
    preExecutionQuote
    actualTokenMovements
    gasUsed
    transactionHashes
    deliverableHash
    verificationResult
    startedAt
    completedAt

Why this can win PancakeSwap

It directly serves LPs, uses Pancake liquidity and position infrastructure, produces a measurable
benefit, and makes fund safety visible to the judge.

Pancake’s own ERC-8183 settlement reference agent already emphasizes direct delivery to the user,
token and router allowlists, fresh quotes, positive minimum output, deadlines, value caps, concurrency
controls, idempotency, post-swap balance checks, and revert/refund behavior.

Its safety-critical guardrails are deliberately deterministic and independently testable rather than
delegated to an LLM.

Docket should match that safety standard and then go beyond the reference implementation with LP
management, economic decision-making, evidence receipts, and the marketplace experience.

Required negative tests

RangePilot should refuse or safely revert when:
      The ERC-8183 job is not in a processable state.
      The requested recipient differs from the job client.
      A token or router is not allowlisted.
      Minimum output is zero.
      Slippage exceeds the policy.
      The fresh quote makes the action uneconomic.
      The deadline is expired or excessive.
      Notional exceeds the user cap.
      The same job is submitted twice.
      The provider lacks sufficient gas.
      The position changed after the recommendation.
      Post-execution token balances violate the expected invariant.
      A router transaction reverts.
      Permissions have expired or been revoked.

GridPilot

Pancake Infinity’s official CLLimitOrderHook supports single-sided tick-based orders, automatic filling
through normal pool activity, cancellations, and fee distribution. That gives you a direct Pancake-native
foundation for laddered grid orders rather than simulating a grid in an offchain database.

        PancakeSwap …

GridPilot must show:

      Realized and unrealized PnL separately.
      Gross PnL versus net PnL after gas and fees.
      Number of fills and closed cycles.
      Capital and measurement window.
      Maximum drawdown.
      Stop conditions.
      Pool liquidity and price-impact limits.
Never market it using an unexplained win rate.

7. TermiX first-place strategy

TermiX explicitly says you do not need to integrate TermiX. It will hire agents from your marketplace
and evaluate the returned work. Its weights are:

      Service value: 30%.
      Proven agent advantage: 30%.
      High-stakes categories and track record: 20%.
      Marketplace quality: 20%.
The Agent Advantage Report is mandatory and must compare at least three real tasks both with and
without an agent, including time, cost, output quality, and actual outputs. At least one task must
concern trading, stocks, or security. BNB Ch… +1

The report should be a first-class product page

Create:

    /advantage-report

It should not be buried in the README.

Include:

      Methodology.
      Starting conditions.
      Manual baseline.
      Agent configuration.
      Repeated runs.
      Raw results.
      Actual deliverables.
      Transaction hashes.
      Job IDs.
      Screenshots.
      Machine-readable CSV/JSON.
      Known limitations.
      Failed runs.
      Reproduction instructions.

Recommended three experiments

Task           Agent route             Manual route           Primary measurements

Pancake LP     Hire RangePilot to      Manually inspect       Active human time, total completion
range rescue   assess and rebalance    pool, estimate range,  time, gas, tx count, out-of-range time,
               a position              quote swaps, and       collected fees, net outcome, constraint
                                       execute                compliance

Pancake grid   Hire GridPilot to       Manually derive        Setup time, execution errors, fills,
deployment     configure and manage    ticks, place/cancel    closed cycles, net PnL, maximum
               orders                  orders, track fills    drawdown, gas, capital at risk

Liquidation-   Hire LiquidationShield  Manually monitor       Detection latency, response latency,
risk incident  to detect and respond   and react              health-factor improvement, collateral
                                                              protected, gas, false positives, policy
                                                              compliance

Make the comparison defensible

For each task:
 1. Freeze the starting state.
 2. Use identical constraints and capital.
 3. Define the output-quality rubric before the run.
 4. Repeat the task where feasible.
 5. Report median and range, not only the best result.
 6. Include failures and retries.
 7. Separate live, simulated, and backtested results.
 8. Attach every output.
 9. Include all fees, gas, model costs, and service price.

10. State market window and risk taken.
A deterministic BSC fork can provide matched A/B conditions and repeatability, but it should
supplement rather than replace real live jobs. Use tightly capped low-notional live transactions to
demonstrate operational reality. Do not claim guaranteed returns.

Make it easy for TermiX to hire

The judges should encounter:
      A fixed-price sample task.
      Immediate quote.
      Clear expected output.
      No API keys.
      No requirement to read documentation.
      No manual agent installation.
      A completion target visible before funding.
      A structured human report and machine-readable JSON.
      Automatic refund or clear failure handling.
      One-click access to the evidence and job receipt.

TermiX itself describes an onchain marketplace model using escrow, locked deliverable hashes,
challenge windows, settlement, and reputation linked to jobs. Docket should be able to display those
same commercially meaningful signals. Ter…

8. The Docket Manifest and Receipt system

A strong ecosystem contribution would be an open Docket Manifest v0.1.

It should extend rather than replace ERC-8004.

Example structure:

         JSON

    {
       "version": "0.1",
       "identity": {
           "chainId": 56,
           "registry": "0x...",
           "agentId": "12345",
           "agentWallet": "0x..."
       },
       "services": [
           {
              "id": "pancake-lp-rebalance",
              "category": "rebalancing",
              "protocols": ["pancakeswap-v3", "pancakeswap-infinity"],
              "modes": ["observe", "recommend", "execute"],
              "inputSchema": "https://...",
              "outputSchema": "https://...",
              "price": {

                  "rail": "erc-8183",
                  "token": "0x...",
                  "minimum": "..."
              },
              "sla": {
                  "targetSeconds": 90
              },
              "permissions": {
                  "contracts": ["0x..."],
                  "methods": ["0x..."],
                  "tokens": ["0x..."],
                  "maxNotionalUsd": "500",
                  "maxSlippageBps": 50,
                  "expirySeconds": 3600
              },
              "evidence": {
                  "benchmarkSet": "docket-defi-v0.1",
                  "receiptSchema": "https://..."
              }
           }
       ]
    }

Three product primitives

Docket Manifest

What the agent claims, what service it sells, and what permission envelope it requires.

Docket Verifier

What Docket independently checks:
      Identity ownership.
      Endpoint health.
      Quote response.
      Service-schema validity.
      Supported chain.
      Contract and token addresses.
      Ability to complete a sample job.
      Data freshness.
      Permission-policy validity.

Docket Receipt

What actually happened:
      Job.
      Payment.
      Inputs.
      Policy.
      Output.
      Transactions.
      Verification.
      Outcome.
      Dispute or refund.

This trio could become Docket’s defensible infrastructure layer after the hackathon.

9. Technical architecture

Adapt this to the existing stack after repository access is restored.

8004scan API ─┐

BSC RPCs ─────┼──> Registry Indexer ──> Agent/Service Database

Agent URIs ───┘  │

                 v

                 Readiness Verifier

                 - URI validation

                 - Endpoint probes

                 - Quote tests

                 - Service schemas

                 - Policy validation

                 │

                 v

Pancake/Venus data ──> Category Metrics Workers

                 │

                 v

                 Docket API

                 │

                 Marketplace UI

                 │

                 Quote / Preview / Hire

                 │

                 ERC-8183 Job Contracts

                 │

                 Agent Studio Agents

                 │

                 Evidence Store + Hashes

                 │

                 Job and Receipt Indexer

Marketplace application
Likely components:
      Next.js/TypeScript frontend.
      Viem/Wagmi for BSC reads and wallet transactions.
      PostgreSQL for normalized agent and evidence data.
      Queue or scheduled workers for endpoint and metric refresh.
      Multiple BSC RPC providers.
      Structured cache with explicit freshness timestamps.
      Public status page and health checks.
      Analytics for land → search → compare → preview → hire → complete.

Agent infrastructure

Use the official BNB Agent SDK rather than inventing a parallel job protocol.

The SDK supports:

      ERC-8004 identity registration.
      ERC-8183 job escrow and lifecycle.
      Negotiation.
      Provider execution.
      Offchain deliverables with onchain hashes.
      Dispute windows.
      Completion, rejection, and expiry refunds. BNB Ch…
ERC-8183 outcomes should feed Docket’s evidence system. The standard recommends connecting
completed, rejected, and expired job outcomes to ERC-8004-compatible reputation or validation
signals. Ethereum Impr…

Use:

      ERC-8183 for substantive jobs with escrow and deliverables.
      x402 for inexpensive data, analysis, or pay-per-call services.
      ERC-8004 for identity and portable trust references.

8004scan

Apply immediately for the hackathon’s free Pro access. The published limits are up to 500 requests
per minute and 100,000 per day. Use it for discovery and indexing, but verify critical identity and
transaction information directly against BSC. BNB Ch…

Evidence storage

Store full deliverables in IPFS, BNB Greenfield, or another durable backend. Anchor the hash through
the ERC-8183 job.
Evidence must remain retrievable throughout judging.

10. Institutional-grade security posture

BNB Agent Studio’s documented architecture keeps private keys in user-controlled environments,
separates the keyless public service from the signing agent, prevents MCP from signing, gates typed-
data signing through explicit policies, excludes secrets from service packages, and records onchain
actions in an audit log. Docket’s agents should preserve those boundaries. BNB Ch…

Non-negotiable controls

      Never ask a user to paste a private key.
      Never place agent wallet keys in the frontend.
      Keep the public service keyless.
      Do not expose signing as an LLM-callable tool.
      Use Secrets Manager or equivalent for deployed secrets.
      Validate chain ID before every write.
      Re-read chain state immediately before signing.
      Simulate state-changing transactions.
      Show a human-readable transaction preview.
      Use exact or tightly limited approvals.
      Avoid unlimited Permit2 authority.
      Require explicit policy configuration when Permit2 is necessary.
      Add emergency pause and user revocation.
      Record every onchain action.
      Rate-limit negotiation and quote endpoints.
      Validate registration metadata and prevent script injection.
      Treat agent descriptions and external deliverables as untrusted input.
      Build RPC fallback and idempotency.
      Never blend testnet, fork, backtest, and mainnet performance.

Proof-linked feedback

Only give strong weight to feedback that is linked to:
      A funded job.
      A completed or rejected outcome.
      A retrievable deliverable.
      A transaction or payment.
      A unique economic counterparty.
      A sufficiently recent measurement window.

Downweight:
      Repeated reciprocal reviews.
      Review clusters controlled by related wallets.
      Feedback without a job.
      Feedback without actual economic cost.
      Old performance with no recent heartbeat.

11. Builder onboarding—the feature that makes this adoption-
worthy

The main prize is not just money. BNB says it intends to back the winning product as a standalone
discoverability layer and route users toward it. That implies the winner must serve the whole
ecosystem, not only judges during one demo. BNB Ch…

Docket needs a builder-side flow:

 1. Connect the ERC-8004 owner wallet.
 2. Import or claim the agent.
 3. Resolve the registration file.
 4. Detect its declared services.
 5. Add or upload a Docket Manifest.
 6. Select one or more categories.
 7. Define input/output schemas.
 8. Set price and SLA.
 9. Declare permission requirements.
10. Run endpoint and quote tests.
11. Run a Docket benchmark.
12. Preview the listing.
13. Publish.
14. Monitor live readiness.
15. Version or deprecate the service.
The marketplace should also support:

      Report-agent flow.
      Owner-response flow.
      Listing version history.
      Revoked or compromised status.
      Endpoint downtime warnings.
      Data-source provenance.
      Shareable agent pages.
      Search-engine-readable pages.
      A public discovery API.
That is what transforms Docket from a hackathon frontend into credible BNB infrastructure.

12. Judge Mode

Add a visible Judge Mode that does not fake the product but removes setup friction.

It should provide:

      One preset task per category.
      Small fixed prices.
      Sample public positions for preview.
      A live-run option.
      A replay of a previously verified real job.
      Job IDs and transaction links.
      One-click navigation to the Agent Advantage Report.
      A system-health panel showing all four agents.
      Clear labels for mainnet, testnet, fork, and backtest data.

Ideal three-minute demonstration

0:00–0:20 — Problem

“BNB has more than 200,000 registered agents, but registration does not tell users which agents are
alive, safe, or effective.”

0:20–0:45 — Outcome discovery

Enter:
    “Protect my lending position before liquidation.”

Show the four categories and normalized agent comparison.

0:45–1:15 — Agent Docket

Open LiquidationShield:
      Live status.
      Response latency.
      Historical jobs.
      Safety limits.
      Price and SLA.
      Proof receipts.
1:15–1:45 — Hire

      Select Recommend or Execute.
      Set spend cap and expiry.
      Preview.
      Fund ERC-8183 job.
      Show live status.

1:45–2:25 — Pancake wow moment

Open a Pancake LP position:
      Current range.
      Out-of-range exposure.
      Fees and gas.
      Proposed new range.
      Net-benefit calculation.
      Permission limits.
      Simulation.
      Transaction and receipt.

2:25–2:45 — TermiX proof

Open the Agent Advantage Report and show three controlled A/B tasks with actual outputs.

2:45–3:00 — Ecosystem scale

Show builder onboarding and explain that any BSC ERC-8004 agent can be claimed, verified,
benchmarked, and hired.

13. Build plan from August 22 to September 9

The submission deadline is September 9, 2026, UTC, and judging runs from September 9 through
September 23. The public application and agents therefore need to remain stable after feature
development stops. BNB Ch… +1

August 22–24: Foundation and one complete vertical slice

Deliver:
      Final positioning and copy.
      Docket Manifest and Receipt schemas.
      ERC-8004 import.
      Endpoint health check.
      Agent page.
      Quote.
      Preview.
      ERC-8183 funding.
      Job status.
      Deliverable and receipt.
Use one agent first, but complete the entire journey.

Definition of done: a new user can discover, understand, hire, and receive evidence without reading
a README.

August 25–27: Equal category depth

Deliver:
      Four category pages.
      Normalized category metrics.
      Outcome search.
      Compare view.
      Observe/Recommend/Execute modes.
      Data provenance and freshness states.
      Empty, loading, stale, and error states.
      Builder onboarding skeleton.

Definition of done: none of the four categories appears secondary or unfinished.

August 28–30: Four live first-party agents

Deliver:
      RangePilot.
      GridPilot.
      YieldScout.
      LiquidationShield.
      ERC-8004 registrations.
      ERC-8183 service endpoints.
      Sample tasks.
      Job receipts.
      External agent import.

Definition of done: one end-to-end completed job per category, with retrievable outputs.

August 31–September 2: PancakeSwap flagship

Deliver:
      V3/Infinity position reading.
      Range chart.
      Economic rebalance calculation.
      Smart Router quotes.
      Recommendation.
      Simulation.
      Scoped execution.
      Post-condition verification.
      Guardrail test suite.
      Revert/refund demonstration.
      Small-value live proof.

Definition of done: the Pancake benefit is measurable, non-custodial, and obvious within 30
seconds.

September 3–4: Agent Advantage Report

Deliver:
      Three real A/B tasks.
      Full methodology.
      Raw outputs.
      Job IDs.
      Tx hashes.
      Time/cost/quality calculations.
      Trading window, capital, and risk reporting.
      Public report page.
      CSV/JSON attachments.

Definition of done: TermiX eligibility and its 30% proven-advantage criterion are directly answered.

September 5–6: Hardening

Deliver:
      Unit and integration tests.
      Contract and policy negative tests.
      Secrets audit.
      Dependency audit.
      Rate limiting.
      RPC fallback.
      Retry and idempotency.
      Accessibility.
      Mobile layout.
      Performance optimization.
      Observability and alerts.
      Data-staleness handling.

Definition of done: a failed upstream service does not produce fake data or strand user funds.
September 7: Beginner testing

Have people who know nothing about Agent Studio try to:
      Find an agent.
      Understand its evidence.
      Preview a task.
      Hire it.
      Find the completed output.
      Revoke permissions.

Fix every dead end.

September 8: Submission freeze

      Stop adding features.
      Complete README and architecture diagram.
      Verify every deployment and explorer link.
      Rehearse Judge Mode.
      Test all four agents.
      Prepare fallback RPCs.
      Fund agent gas and service credits.
      Verify the report assets remain public.
      Record a clean backup demonstration.

September 9: Submission and operational handover

      Submit before the UTC cutoff.
      Preserve stable URLs.
      Keep agents and databases running.
      Monitor through the September 23 judging period.
      Avoid risky post-submission migrations.

14. P0 acceptance criteria

Docket is not submission-ready until all of these are true:
      Public deployment works without authentication.
      Four categories have equal depth.
      At least one live activation exists in every category.
      Each agent displays live status and data freshness.
      No production page presents mocked values as live.
      Users can browse without connecting a wallet.
      A beginner can understand price, outcome, and risk.
      Every performance claim shows sample size and window.
      Every completed result has a job or transaction reference.
      ERC-8183 escrow or another verifiable hiring rail works end-to-end.
      The Agent Advantage Report is public and complete.
      RangePilot has deterministic transaction guardrails.
      Agent authority is visible and revocable.
      The application has no dead-end buttons.
      Agent wallets and services remain operational throughout judging.
      The submitted repository or product link does not return 404.

15. Features to cut until the winning flow works

Do not spend the remaining build period on:
      A Docket token.
      DAO governance.
      Multi-chain support.
      Social feeds.
      NFT badges without underlying evidence.
      Complex referral systems.
      Generic AI chat.
      Hundreds of unverified agent cards.
      AI-generated trust scores.
      Autonomous multi-agent orchestration unrelated to discovery.
      Elaborate subscription tiers.
      Cosmetic sponsor-logo integrations.
      An admin dashboard more sophisticated than the user journey.
      Advanced portfolio analytics before all four categories work.

A polished directory with fake breadth will lose to a smaller marketplace with real, measurable,
verifiable hiring.

16. Hard failure conditions by prize

BNB main track

Likely loses when:
      One category is clearly the main event.
      Users need instructions or Agent Studio knowledge.
      Agent data is static or shallow.
      Activation buttons do not complete a real journey.
      The product is just your own agent portfolio.
      The app is unavailable during judging.

TermiX

Fails eligibility or becomes uncompetitive when:
      The Agent Advantage Report is missing.
      The report contains claims but not actual outputs.
      Only one side of the comparison is run.
      Costs exclude gas or service fees.
      Trading performance lacks window and risk.
      The judges must install software or read documentation.
      Services return generic LLM text instead of usable deliverables.

PancakeSwap

Becomes uncompetitive when:
      Integration is limited to displaying prices or a logo.
      The agent uses a generic router with no Pancake-specific utility.
      “Better yield” is asserted but not measured net of gas and risk.
      The agent takes custody of user funds.
      There are unlimited approvals or no revocation.
      Execution is controlled directly by probabilistic LLM output.
      No live or verifiable Pancake action is shown.

17. Recommended submission language

Main description

    Docket is the evidence-backed marketplace for BNB Chain agents. It transforms ERC-8004
    registrations into verified, comparable services by checking live readiness, normalizing
    category-specific performance, exposing scoped permissions, and connecting users to
    ERC-8183 jobs with onchain receipts. Users can discover and activate rebalancing, grid-
    trading, yield-optimization, and health-factor agents without needing Agent Studio
    knowledge.

BNB-specific statement

    Docket gives BNB Agent Studio its human-facing front door: an open marketplace where
    any live BSC agent can be claimed, verified, benchmarked, compared, and hired.
TermiX-specific statement

    Docket proves that its agents beat the manual alternative through three controlled A/B tasks
    with attached outputs, full cost accounting, and job-linked evidence.

PancakeSwap-specific statement

    Docket’s RangePilot manages PancakeSwap V3 and Infinity LP positions using net-benefit
    decisions, user-defined execution limits, deterministic guardrails, non-custodial settlement,
    and verifiable before-and-after receipts.

Final verdict

The most powerful version of Docket is not:
    “A place to browse AI agents.”

It is:
    The proof, comparison, permission, and hiring layer for BNB’s agent economy.

That product directly answers:
      BNB’s discoverability and adoption problem.
      TermiX’s demand for measurable agent advantage.
      PancakeSwap’s demand for useful and safe trader/LP automation.
      The real weaknesses of a registry-heavy ecosystem in which identity, availability, performance,
      and trustworthy feedback are not the same thing.

Make the repository accessible through the corrected GitHub link, connected-app permission, or an
attached ZIP, and include the deployed application URL; the next pass should be a file-by-file,
contract-by-contract, API-by-API, and screen-by-screen audit against this winning specification.

```
