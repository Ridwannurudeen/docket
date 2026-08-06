# Docket — design spec

**Date:** 2026-08-06 · **Status:** approved by user (design locked; implementation plan pending)
**Hackathon:** BNB Chain "Build the Era" (The Smart Money Era), Aug 5 – Sep 9 2026 UTC+0, judging Sep 9–23, winners Nov 5.
**Targets, in priority order:** ① TermiX 1st ($6,000; $3k/$1k for 2nd/3rd) ② PancakeSwap (1,000 CAKE) ③ strong main-track entry ($30,000 + adoption — auto-entered, no extra submission). Altana (50,000 XP) rides as a cheap extension of ② and is first in the cut order.

Every load-bearing claim in this spec was verified 2026-08-06 against primary sources (live APIs, on-chain `eth_call`, SDK source, the hackathon page read in-browser). Constants are in the Appendix.

---

## 1. Product

**Docket** is a trust-first marketplace for AI agents on BNB Smart Chain. Thesis, stated with arithmetic: the sanctioned registry lists 243,421 BSC agents; **506 (0.21%) have ever received feedback**, at most 3.6% are callable at all (A2A/MCP), one publisher (Ave.ai) is 45.9% of the chain, and `is_verified` is zero everywhere sampled. Docket separates the agents actually worth hiring from the noise, backs every listing with verifiable evidence, and lets a stranger — human or software — find, compare, and hire one without instructions.

Non-goals: not an agent framework, not a chain indexer for its own sake, not four-category depth at launch (that is main-track insurance, added only if September allows).

## 2. Judging criteria this design is built against (verbatim anchors)

- TermiX 30%: "Real working agents at a price and speed that beat the alternative. TermiX will hire from your marketplace and evaluate the results."
- TermiX 30%: "Measured, not asserted, backed by the required Agent Advantage Report." (Report = eligibility gate.)
- TermiX 20%: "Trading, stock/equities and security agents weighted above general-purpose. Trading agents need a real record: win rate, the window, and the risk taken to get there."
- TermiX 20%: "Find, compare, hire, without instructions."
- PancakeSwap: "real benefit to PancakeSwap traders or liquidity providers … without ever putting user funds at risk."
- Main: Functionality / Data Quality ("real-time, accurate data that goes beyond basic counts") / Agent Diversity (four categories at equal depth).
- Global gates: publicly accessible Sep 9–23; listed agents live on BSC; one entry per team.

## 3. Inventory — three first-party agents, all genuinely hireable

| Agent | Category (TermiX band) | State | Report task |
|---|---|---|---|
| **SOLVENT** | Trading (mandatory) | Exists; BSC agent #136384; HALTED since Jun 29 — resume | Daily regime signal vs. manual market read |
| **Warden-BSC** | Security (over-weighted) | Engine exists (X Layer); needs BSC identity + endpoint | Payload/endpoint audit vs. manual review |
| **Range Doctor** | Yield/LP | New build | LP-position health report vs. manual spreadsheet |

Beyond these, Docket lists filtered third-party BSC agents (the ~506-with-feedback / callable set) as browse inventory with honest, sample-sized metrics — depth without fake hireability claims.

### 3.1 SOLVENT (fix, resume, list)
- **Blank-row fix:** `tokenURI(136384)` → `https://solvent.gudman.xyz`, which serves HTML. Serve the ERC-8004 registration JSON at that URL via content negotiation (`Accept`-based; JSON to non-browser agents), schema per the top-scoring BSC agent: `"type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"`, `name`, `description`, `services[]` (real A2A/x402 endpoints), `skills[]`, `capabilities`, `supportedTrust[]`, `registrations[]` (CAIP form). Then request re-parse via t.me/ERC8004 (indexer has not re-parsed since mint day). **Fallback if negotiation isn't honored:** one on-chain tx repointing `tokenURI` to `/agent-card.json`.
- **Resume:** VPS `solvent.ops.state_control resume --reason …` per RUNBOOK (refuses while journal has unresolved attempts). Wallet funding = user action. Keep `bnbagent==0.3.6` pin (seller flow predates the SDK's server-API removal; migration optional, never mid-build).
- **Demo asset:** film the blank-row → evidenced-card → hire journey. 30 seconds, whole thesis.
- **Credential:** SOLVENT won "Best Use of BNB Agent SDK" at the prior BNB hackathon — state it in the submission.

### 3.2 Warden-BSC (port)
Scanner engine unchanged. New: BSC ERC-8004 identity (one `register()` tx), an x402-payable scan/audit endpoint on BSC rails, listing priced in TermiX's band (their security comparable: $99/1-day; median listing $70). Metrics shown with n and window — never a bare rate ("92.55% recall, 87/94, held-out v1, 0.00% FP 0/45" — misses enumerated and linked).

### 3.3 Range Doctor (new; PancakeSwap bounty; Altana rider)
Read-only LP intelligence. Input: any wallet. Output: ranked findings — in/out-of-range per position, uncollected fees, realized fee APR vs. pool `apr24h` (net-of-protocol-fee form; LP shares 67/66/68/68% by tier), CAKE farm APR (mind `/1e12` on `latestPeriodCakePerSecond`), IL vs HODL where entry price is derivable, and "you'd earn more in pool X" via cross-protocol pair comparison + live Infinity campaigns. Output includes pancakeswap.finance deep links (act in their UI).
- Data: PancakeSwap's keyless Explorer REST API (primary); v3 positions read **on-chain** (their positions route is verifiably broken for v3 — say so, kindly, in the submission); Infinity CL/Bin via their positions API (works). All pool lists hard-filtered through the official token allowlist (scam pools report quadrillion-dollar TVL).
- Compatibility: ship as a skill compatible with `pancakeswap/pancakeswap-ai` conventions; report their dead documented endpoint (`router.pancakeswap.finance`, no DNS) as a contribution.
- Safety story = structure: zero keys, zero approvals, cannot touch funds. This is the bounty's "without ever putting user funds at risk" answered by construction.
- **Altana rider (cut order #2):** an execution variant on an Altana wallet — session with call allowlist (V2 router only; skills are V2-only), spend cap, expiry, registered in KeyStore; testnet transactions (count per rules; "mainnet is stronger" if cheap); Docket UI panel reading `KeyStore.isValidKey` + `IthacaAccount.spendInfos` live (the "what may my agent do / revoke it" control — copy the internal `keyHash` derivation, it isn't exported). Session-key `hireErc8183Agent` overload = undemonstrated-anywhere headline if time allows.

## 4. Marketplace architecture

Stack: FastAPI + Next.js 15 + wagmi/viem (PolyScope pattern), deployed to the shared VPS behind `docket.gudman.xyz` early (public from week two).

### 4.1 Data plane
- Ingest: 8004scan **internal** API (`/api/v1/agents`, snake_case, 180 req/min + 20k/day keyless; `min_score`, `min_feedbacks`, `search` work; offset/limit≤100) with the **public** API (`/api/v1/public`, camelCase; `protocol` filter works; page/limit) as secondary; never the semantic search route (502) or `/feedbacks?tokenId=` (silently ignored — filter client-side). File the free Pro-tier form for headroom, don't block on it.
- Noise filter: feedback count, protocol-callable, publisher clustering (Ave.ai/Purr-Fect/Termix bulk-mints collapsed), endpoint liveness probes. Trust scoring ported from sentinelnet's approach (wallet clustering, sequential-mint detection).
- Listings carry: honest metrics with **sample sizes and windows**, evidence links, price, delivery time, liveness heartbeat (~60s convention), and provenance of every number. Badges are rare and defined next to their threshold (the judge's own platform hands "topRated" to 243/287 — we do the opposite).

### 4.2 Two equal front doors
- **Human:** land → browse by category (the four main-track categories are first-class filters from day one) → compare → agent page (evidence pane, metrics, price) → hire.
- **Agent-facing:** `/llms.txt` + `SKILL.md` at stable URLs; public no-auth discovery endpoint usable with bare `curl`/Node-18 `fetch`; strict schemas; actionable error codes; "do not invent endpoints" discipline. TermiX's evaluators drive coding agents that fail closed on undocumented surfaces — this door is scored at 20% and most entrants won't build it.

### 4.3 Hire rails (both, labeled by use)
- **x402 instant** ("try this agent now"): per-call payment, immediate settlement, normal stablecoins via Permit2 on BSC (plus $U eip3009 rail for Studio buyers). Served with `@altananetwork/x402-server`-style guard or equivalent; `maxTimeoutSeconds ≤ 480`; run buyer-side server-side (CORS header trap).
- **ERC-8183 escrow** ("real job"): browser signs raw ABI calls via wagmi/viem (SDKs are not browser-safe — verified); server indexes `JobSubmitted` at submit time (the SDK's deliverable-url helper breaks past ~6h); copy `buy_workflow`'s pre-fund verification (recover quote signer = provider; signed price = funded amount); never wire UI to `voteReject` (whitelisted voters only — buyer's lever is `dispute`); `claimRefund` surfaced as the escape hatch.
- **Experiment E1 (build hour one):** on testnet, `createJob` with `evaluator = Docket` + `hook = 0`, skip `registerJob`, then `complete(jobId)` from that evaluator → if it works, accept-is-settlement is instant (the judge's own mental model) and mainnet's 7-day window stops being a UX constraint. If it fails: testnet (1-day window) for judge-facing escrow hires; mainnet demo ends at SUBMITTED + verified deliverable with settlement framed as scheduled.
- $U mainnet acquisition is a routine swap (USDT/$U v3 pool, $21M TVL — verified). Judges still need BNB gas; docs say so plainly.

### 4.4 Evidence layer (the differentiator)
- **Evidence-bound on-chain feedback** via the deployed ReputationRegistry (`0x8004BAa1…9b63`, bytecode verified on BSC): feedback entries whose `feedback_uri` resolves to verifiable evidence — Warden's benchmark JSON, SOLVENT's receipt-chain head + anchors, hire outcomes bound to payment proofs. 8004scan indexes these (11,705 BSC feedbacks today), so Docket's evidence surfaces on the sanctioned explorer too. (The ValidationRegistry is NOT deployed anywhere — probe-confirmed; the "first validator" framing is dead, do not resurrect it.)
- Reviews/outcomes count **only** when bound to a payment proof (Agent Arena's rule, adopted).
- Every public number is generated from data, never typed into prose; the marketplace states its own coverage honestly (sampled/expected pattern per Warden house style).

## 5. Agent Advantage Report (TermiX eligibility gate)

Six arms: 3 tasks × (agent hired through Docket | done manually). Framing per the judge's own taxonomy: **agent vs. named baseline** ("manual analyst with the same public data", stated tools), stated window, stated n. Each arm reports wall-clock time, cost (hire price + gas vs. hourly-rate proxy, method stated), output quality against a pre-registered rubric written **before** running either arm, raw outputs attached. Published as a first-class Docket page (browsable by an evaluator agent), plus a PDF artifact for the form. Tasks: §3's three agents. At least one arm runs through the exact public hire flow a judge would use, on the network judges would use. Hire flow therefore must work by **Aug 31**; Report runs Sep 1–5; no back-filling.

## 6. Schedule (34 days, OKX carved out) and cut order

- **Aug 6–10 · Foundations (light-hours; OKX deploy week owns priority):** register (user submits; answers drafted), 8004scan Pro form (user), Terms of Participation read (user), SOLVENT registration-JSON fix + re-parse request, SOLVENT branch rename, repo scaffold + CI, **E1 experiment**.
- **Aug 11–20 · Spine (OKX = monitoring):** ingestion + noise filter + trust scores; listing pages with evidence panes; agent-facing API + llms.txt; deploy publicly early.
- **Aug 20–31 · Hire + inventory:** x402 rail; ERC-8183 rail per E1's outcome; SOLVENT resumed + listed (user funds wallet); Warden-BSC identity + endpoint + listing; Range Doctor built + listed; Altana rider if on schedule. **Gate: a stranger can complete a paid hire end-to-end by Aug 31.**
- **Sep 1–7 · Proof:** Report (all six arms); evidence-bound feedback entries published; cold-stranger hire test (someone unfamiliar completes a hire, no instructions); deploy freeze Sep 6; uptime watch through judging.
- **Sep 8–9 · Submit** — only with explicit user approval, per standing rule.

**Pre-committed cut order** if capacity bites: ① main-track four-category depth ② Altana rider ③ sybil visualizations. **Never cut:** hire flow, three agents, Report, honest metrics, agent-facing API.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Value-of-services (30%) is the weak pillar | Agents return obviously-useful output in minutes; priced in the judge's band ($21–$100); delivery time surfaced; rehearsed cold |
| Solo capacity + OKX overlap (Aug 11–25) | Early public deploy; parallel build agents (Opus 5 default) with review gate; the cut order; hire-flow-by-Aug-31 gate |
| E1 fails → 7-day mainnet settlement | Testnet judge path (1-day window) + SUBMITTED-state demo framing; x402 rail is instant regardless |
| 8004scan re-parse never happens | Docket renders SOLVENT from its own enrichment pipeline regardless; explorer fix is upside, not dependency |
| SDK churn (both bnbagent + Altana republished days ago, pre-1.0) | Pin exact versions; raw-ABI browser path is SDK-independent; re-check before submission |
| Phase 2 criteria unknown (main track) | Build the honest, durable product; nothing demo-scripted |
| Terms of Participation unread | User reads inside the form before registering (this week) |

## 8. User-only actions
1. 8004scan Pro form · 2. Registration approval + submission (name: **Docket**; tracks: TermiX + PancakeSwap ticked) · 3. Read Terms of Participation · 4. Fund SOLVENT wallet (BSC mainnet) · 5. Approve final submission, demo video, any posts. Nothing outbound ships without explicit approval.

---

## Appendix — verified constants (all live-checked 2026-08-06)

**ERC-8004 (BSC 56 / 97):** IdentityRegistry `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432` / `0x8004A818BFB912233c491871b3d84c89A494BD9e`; ReputationRegistry `0x8004BAa17C55a88189AE136b182e5fdA19dE9b63` (56, bytecode verified). ValidationRegistry: **not deployed anywhere**.
**ERC-8183 (56 / 97):** commerce `0xEa4DAa3100A767e86FDed867729ae7446476EBA6` / `0xa206c0517B6371C6638CD9e4a42Cc9f02A33B0DE`; router `0x51895229E12F9876011789B04f8698af06cCD6DA` / `0xD7d36D66d2F1B608A0F943f722D27e3744f66F25`; policy `0x9C01845705b3078Aa2e8cfF7520a6376FD766dE5` / `0x4F4678D4439feC812Ac7674Bb3Efb4C8f5Fb78A6`; $U `0xcE24439F2D9C6a2289F741120FE202248B666666` / `0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565` (18 dec); disputeWindow 604800s / 86400s; platformFeeBP 0; testnet $U faucet `0x86e9197CC0F76E4e4aaa7082180945196bBAb5D3.requestTokens()`; MegaFuel gas sponsorship **testnet-only**, never the ERC-20 approve.
**8004scan:** internal `https://8004scan.io/api/v1/…` (snake_case; 180/min, 20k/day); public `…/api/v1/public/…` (camelCase; OpenAPI at `/api/v1/public/docs/openapi.json`; anon 10/min/100-day); detail `/agents/{chain_id}/{token_id}`; search = whole-lexeme AND.
**PancakeSwap:** Explorer API `https://explorer.pancakeswap.com/api/cached/pools/{protocol}/{chain}/list/top`, `…/pools/list` (`apr24h` decimal, net LP share), positions Infinity OK / v3 broken; v3 NPM `0x46A15B0b27311cedF172AB29E4f4766fbE7F4364`; MasterChefV3 `0x556B9306565093C855AEA9AE92A594704c2Cd59e` (`latestPeriodCakePerSecond` ÷ 1e12 ÷ 1e18); PancakeV3Factory `0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865`; Infinity campaigns `https://infinity.pancakeswap.com/farms/campaigns/56/false`; allowlist `https://tokens.pancakeswap.finance/pancakeswap-extended.json`; LP fee shares 67/66/68/68% (tiers 100/500/2500/10000); USDT/$U v3 pool `0xa0909f81785f87f3e79309f0e73a7d82208094e4` ($21M TVL). Testnet: contracts yes, data no → mainnet-read, testnet-write.
**Altana:** `@altananetwork/sdk@0.7.0` + `@altananetwork/x402-server@0.2.0` (pin; pre-1.0); relay `https://relay.altana.network` / `testnet-relay…` (no auth; native-gas only — testnet relay faucet is a no-op, fund tBNB manually); KeyStore 56 `0x6572427ED530BadcF7375Cf9A4709D8d2b0E7E0a` / 97 `0x6b8361C29d05D498b1a12B54A37310f94171E94A`; key registration ~0.000842 BNB; skills index `https://raw.githubusercontent.com/altananetwork/skills/main/index.json` (sha256-verify; PancakeSwap skills V2-only; mainnet addresses only); explorer `https://explorer.altana.network` / `https://testnet.altana.network`; `client.execute` (docs' bare `execute` doesn't exist); USDT/USDC 18 dec on BSC.
**TermiX (the judge):** platform `https://www.agent.family`, backend `https://platform-backend.prod.termix.live/api/v1/…` (listings/explorer/stats public); skill bundle `https://termix.ai/skills`; median price $70, security comparable $99/1-day; anomaly flag on pass rate >95%; sample sizes shipped with every metric; 72h challenge + one redo + accept-is-settlement.
**SOLVENT:** agent 56/#136384, owner `0xe4fe23fb57dbb9ac2f685ea29b6b9a1409a0d359`, tokenURI `https://solvent.gudman.xyz` (serves HTML — root cause of blank row); 384 receipts, head anchored daily Jun 16–28 (11 anchor keys on-chain); pinned `bnbagent==0.3.6`; runtime HALTED (resume via `solvent.ops.state_control`).
**Hackathon:** form `https://forms.gle/9g9XPNFwnYaHAz9L8`; 8004scan Pro form `https://forms.gle/jQevEPCAacBXaKG79`; page tabs are JS-rendered (read in browser); Telegram `t.me/bnbchain`, `t.me/BNBchaincommunity`; 8004scan contact `t.me/ERC8004`.
