# Docket — Strategic Deliberation Briefing (2026-08-12)

This is a shared, verified fact base for a three-way strategy deliberation between Claude, Codex, and Fable 5. Everything below was verified this session against primary sources (the live hackathon page, the sponsors' own products, and the running code). Treat it as ground truth; challenge anything you think is wrong and say why.

## The question on the table

We entered the BNB "Build the Era" hackathon (5 Aug – 9 Sep 2026; judging 9–23 Sep). We built Docket. **Be honest: what did we get right, where did we fall short, and what must be built or changed so the submission aligns with what BNB, TermiX, and PancakeSwap actually want — enough to take first in all three?** Then draw an ambitious roadmap that serves the product's future, not only the hackathon.

The user's framing, verbatim in spirit: "we are competing with the best devs all over the world." No comfort, no flattery. Rigor.

---

## What each sponsor actually wants (verified from their own words)

### BNB Chain — Main Track ($30,000 + official adoption)
- The prize is **adoption**: *"we back it as a standalone product with its own brand and team, and incubate it as the discoverability layer for agents on BSC... keep it alive, drive users to, and grow with the ecosystem."* This is an acquisition of a growth funnel, not a grant.
- What to build: *"A front end that surfaces agent data, lets users discover and activate agents by category, and doesn't make them think too hard about it."* *"find agents, understand what they do, and hire them in a few clicks."* *"Whatever you ship here is what real users interact with next."*
- **Four categories, all first-class, EQUAL depth** — the hard requirement:
  - Rebalancing — manages LP ranges, resets positions automatically
  - Grid Trading — places and manages automated grid orders
  - Yield Optimisation — routes liquidity to the highest available APR
  - Health Factor Monitoring — protects lending positions from liquidation
  - *"Single-category submissions score poorly. All four, equally deep, is the bar."*
- Judged on three equally-weighted criteria:
  - **Functionality** — *"The full journey works end to end: land, find an agent by category, understand what it does, activate it, with minimal friction. Someone with zero Agent Studio knowledge should be able to get through it without hitting a dead end."*
  - **Data Quality** — *"Real-time, accurate data that goes beyond basic counts. A user should be able to look at what you're showing and make a genuinely informed call on which agent to hire."*
  - **Agent Diversity** — *"All four categories surfaced with equal depth. A submission that treats one category as the main event and the rest as an afterthought won't score well here."*
- **Phase 2 criteria are [REDACTED].** Top 3 shortlisted publicly, then judged again on undisclosed criteria. A submission must survive a second look.
- Tooling they promote: BNB Agent Studio CLI (pip `bnbagent-studio`, `bag` CLI), scaffolds against ERC-8004 identity + ERC-8183 task interface, deploys to AWS Bedrock AgentCore. Binance x402 is the payment facilitator.

### TermiX — Partner Track ($6,000 / $3,000 / $1,000)
- One question: *"does hiring an agent on your marketplace actually beat doing the job yourself, and can you prove it with numbers?"* They will **hire from your marketplace themselves**.
- Weights: Value of services 30% · Proven agent advantage 30% (the Agent Advantage Report — an ELIGIBILITY GATE) · High-stakes categories & track record 20% (trading/equities/security weighted above general-purpose; trading agents need *"win rate, the window, and the risk taken"*) · Marketplace quality 20% (*"find, compare, hire, without instructions"*).
- Their product (agent.family) runs a real reputation system that **flags pass rates >95% as suspicious** and exposes sample sizes next to every metric. Their capability taxonomy literally starts with null models (random-walk, coin-flip, null-hypothesis). They reward measured, honest evidence and are hostile to marketing gloss.

### PancakeSwap — Partner Challenge (1,000 CAKE)
- *"Your agent must deliver a real benefit to PancakeSwap traders or liquidity providers: smarter liquidity management, finding better yields, researching market movements to find demand where creating PancakeSwap pools could improve liquidity efficiency, or executing safe automated swaps using PancakeSwap products without ever putting user funds at risk."*
- Read strategically: PancakeSwap is a DEX; every prize is ecosystem growth. They want agents that route volume/TVL to PancakeSwap and keep LPs efficient.

---

## What we built (verified: docket repo `main`, 225 tests passing, deployed at https://docket.gudman.xyz)

- **Data spine**: ingest 8004scan (internal API, 180 req/min) → SQLite snapshot store → factual per-agent signals → generated coverage report. Every number carries its `sampled/expected/dropped` denominator. Targeted sweep = 506 BSC agents with ≥1 feedback, complete (0 dropped).
- **Liveness**: SSRF-guarded, single-attempt endpoint probing with a closed outcome vocabulary (responded/timeout/refused/blocked/unresolved/error). Of 506, 31 declare a callable endpoint, 35 endpoints probed, **13 responded**. `blocked` means policy refusal only; DNS failures are `unresolved`, kept separate so no rate is inflated.
- **Machine-facing API**: `/stats`, `/agents`, `/agents/{id}`, plus `/llms.txt`, `/skill.md`, `/openapi.json`, structured error codes. A contract test bans verdict field names (safe/trusted/verified/recommended/score/rank) across every response model. Every statistic must ship with its coverage or a test fails.
- **Human UI**: `/`, `/browse`, `/agent` — dependency-free static HTML/CSS/JS, dark, accessible, zero external requests. Landing headline: *"What answered, and what only claimed to."* Each figure prints its denominator; each outcome states what it does NOT mean.
- **Range Doctor** (`docket/agents/pancake`): read-only PancakeSwap v3 LP adviser. Reads a wallet's positions on-chain, flags in/out-of-range, computes NET fee APR (protocol-fee subtracted — gross overstates ~⅓), quotes pool APR only while in range, gates pool data through the PancakeSwap token allowlist + sanity bounds (rejects 6 of 30 live top pools). Structurally incapable of moving funds: no key, no signing, no approvals.
- **Hire flow**: `GET /hire`, `POST /hire/{service_id}`. x402 is ADDITIVE — free tier always works, a cold hire needs no account/key/wallet and returns HTTP 200 in ~32s. Receipts are hash-bound and recomputable with stdlib alone. Payment authorizations are cryptographically verified (EIP-712) but never settled; status is `verified_unsettled`, never "paid". Three live services: `range-doctor`, `solvent-signal` (SOLVENT's last regime call + on-chain provenance chain — the agent is halted, framed honestly as a historical, verifiable record), `warden-scan` (prompt-injection classification).
- **Agent Advantage Report** (`/advantage` + `/advantage.json`): three real tasks (liquidity/yield, trading, security) each run with an agent hired through Docket and by hand; full outputs attached, hashes recomputable, time and out-of-pocket cost reported separately (no invented hourly rate). One task **the agent lost** (security: manual found 4 vectors, our agent found 1) — published in the summary where a reader meets it first, pinned by a test. We also discount our own most flattering number (a 120× speedup that does not answer the question asked).
- **Escrow rail** (Phase 1h, built, NOT deployed): ERC-8183 mainnet hire/settle path. Experiment e1c verified the testnet escrow rail is closed and the rail is open on BSC MAINNET only (7-day dispute window, permissionless settle).

---

## Honest gaps (Claude's opening position — challenge these)

1. **Agent Diversity is our biggest main-track hole.** We cover Yield (Range Doctor) as a first-class evidenced category. Rebalancing, Grid Trading, and Health Factor Monitoring are NOT surfaced as their own depth-equal categories. On one of BNB's three equal criteria we currently forfeit. This is the single highest-leverage main-track gap and it is data-and-config-shaped, not a rebuild.
2. **Functionality is skeptic-shaped, not "few clicks, zero knowledge."** Our UI is built for someone reading evidence carefully. BNB wants a consumer who lands and activates an agent by category with minimal friction and no Agent Studio knowledge. The find→activate path needs to be genuinely effortless and category-first.
3. **PancakeSwap fit is real but soft.** Range Doctor *advises*; it does not route a swap or add liquidity to PancakeSwap. A judge asking "did this bring us volume/benefit?" gets a weaker yes than an agent that (safely) executes or that measurably improves an LP's outcome. Consider whether Range Doctor should be able to *act* (within a spend cap / session key) or at least drive users into PancakeSwap's own UI with a pre-filled action.
4. **We optimized for TermiX (honesty/evidence) and under-optimized for BNB (growth/breadth/polish).** That was a deliberate bounties-first bet. The Data Quality criterion is genuinely our strength (near-verbatim our thesis). But adoption is a growth decision, and a truth-telling audit layer is a harder thing for BNB to "drive users to and grow" than a slick activation product.
5. **On-chain presence.** Our own hireable agents are not all ERC-8004-registered on BSC. SOLVENT is #136384 (registration JSON now served; re-index nudge unsent). Range Doctor and a Warden-BSC identity are not on-chain. The rule "agents surfaced on your marketplace must be live on BSC" is satisfied by the 506 indexed agents, but our flagship services being on-chain would strengthen the story.
6. **Housekeeping that blocks submission**: repo is private (needs public before judging), no LICENSE, Terms of Participation unread, escrow not deployed.

## Questions for the deliberation

- Is closing Agent Diversity (the 3 missing categories) the right main-track move, or does it dilute the honesty thesis that wins TermiX? Can both coexist in one product?
- What is the minimum that makes the Functionality journey "zero-knowledge, few clicks" without betraying the no-verdict discipline?
- Should Range Doctor (or a new agent) gain the ability to ACT on PancakeSwap (session-key-scoped, spend-capped) to convert PancakeSwap's soft fit into a strong one? Does that reopen the Altana track (session keys) as a cheap rider?
- What does a submission need to survive the [REDACTED] Phase 2 second look?
- What is the ambitious, future-facing roadmap — the version of Docket that BNB would actually adopt as a standalone product and grow, beyond winning the hackathon?

Write your assessment and your proposed roadmap. Disagree with Claude's gaps where you see it differently. We synthesize afterward and surface any unresolved disagreement to the user.
