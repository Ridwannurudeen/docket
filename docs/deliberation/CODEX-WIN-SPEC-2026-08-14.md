# Docket — Codex win spec for TermiX 1st + PancakeSwap (2026-08-14)

_Codex CLI 0.147.0, `gpt-5.6-sol` @ xhigh, read-only. Written after the owner's priority ruling: TermiX first place and PancakeSwap are PRIMARY and must actually land; BNB $30k is secondary. This is the operative spec._

# First-place ruling

The current plan is a credible podium plan. It is not yet a first-place plan.

The missing layer is not more marketplace breadth. It is:

- **TermiX:** quality-gated paid inventory plus a replicated, independently scored advantage report.
- **PancakeSwap:** proof that Range Doctor changes an LP decision or economic outcome—not only proof that gross APR arithmetic is wrong.

## 1. TermiX — criterion by criterion

| Criterion | First-place answer | Docket’s current answer | Exact gap closure |
|---|---|---|---|
| **Value of services — 30%** | Every service displaying **Pay and hire** returns a fresh, non-empty decision; quantified consequence; next action; limitation; and genuinely settled receipt. The result itself proves why `$0.50` beats manual work. | The plan correctly adds `$0.50`, settlement, a controlled wallet and human presenters. But it still allows weak paid outcomes: Range can return `[]`, default Yield is inert, Health commonly returns `no_position`, Grid is a preview, and SOLVENT is stale. [FABLE-AUDIT.md:78–109](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/FABLE-AUDIT-2026-08-14.md:78) [SYNTHESIS-V2.md:224–258](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-SYNTHESIS-V2.md:224) | Add a **paid-stock admission gate**: fresh paired benchmark, passing cold canary, decision-grade presenter, true settlement. Until they pass: Grid/Health are previews, SOLVENT is research, and Warden is beta. A no-applicable-position preflight must stop before settlement—**no result, no charge**. |
| **Proven advantage — 30%** | Git-preregistered paired work with repeated cases, objective output-quality scoring, complete outputs, failures retained, and the agent materially faster without lower quality. | V1 meets the literal three-task gate but is three `n=1` anecdotes and includes a substantive Warden loss. V2 is agent-versus-null, not agent-versus-human. The planned v3 fixes pairing but specifies neither replication, independent scoring nor a shipping threshold. [FABLE-AUDIT.md:200–227](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/FABLE-AUDIT-2026-08-14.md:200) [SYNTHESIS-V2.md:266–272](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-SYNTHESIS-V2.md:266) | Make v3 three **task families**, not three more anecdotes: Range on 5 preselected active positions; Yield on 5 fixed pool/size/cost/horizon cases; Warden on a 12-payload held-out set. Lock inputs, procedures, stopping rules and labels before running. Two evaluators score randomized A/B outputs without knowing the arm. Publish every case and loss. |
| **High-stakes categories and record — 20%** | A security agent with a dated, sample-sized record, strong decision recall/precision, reliable delivery and explicit known misses. Use security; do not manufacture a trading record. | Warden supplies the qualifying security category, but its attached evidence is not first-place quality: v1 found 1 of 4 hostile vectors; v2 detected 14 of 31 attacks, only two above the keyword null, with failed scans retained. SOLVENT is halted and lacks the named trading-record fields. [03-security.json:63–135](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/advantage/experiments/03-security.json:63) [FABLE-AUDIT.md:191–212](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/FABLE-AUDIT-2026-08-14.md:191) | Warden remediation is mandatory. Docket’s internal ship gate—not a published sponsor threshold—should be: **≥90% held-out decision recall, ≥90% precision, zero critical vector surviving a “sanitized” output, and ≥99% successful scans**. If it misses, it stays beta and TermiX’s 20% remains exposed. One Grid swap is not a win rate or trading record. |
| **Marketplace quality — 20%** | A cold judge can understand, compare, sample, pay, and explain the result without documentation or verbal help. | The cold category-to-hire path works, but wallet walls, raw JSON and the unreachable v2 report remain. The plan fixes examples and presenters but still lacks an actual service-comparison surface and uncoached acceptance testing. [FABLE-AUDIT.md:118–160](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/FABLE-AUDIT-2026-08-14.md:118) | Add one comparison table: **job, price, measured time saved, quality/sample size, freshness, limitation, evidence**. Each qualified service gets distinct **Try verified example** and **Pay `$0.50` and run mine** actions. Run three uncoached cold-user sessions; any repeated dead end blocks release. |

### The exact hire TermiX must receive

Feature Range Doctor as the first paid hire. Its human result must contain, in this order:

1. **Decision:** “Position 123 is above its range and currently earns no pool fees.”
2. **Verifiable facts:** pair, position ID, current tick, range bounds, BSC block and observation time.
3. **Economic consequence:** gross APR, protocol-adjusted net APR, percentage/percentage-point overstatement, and dollar effect at the position’s declared value. State that the 24-hour annualization is an observation, not a forecast.
4. **Conditional actions:** wait versus recenter, with each assumption and cost—gas and realized impermanent loss—and a PancakeSwap deep link.
5. **Coverage:** positions held/examined/closed-skipped and whether the scan was complete. Never silently return `[]`.
6. **Measured value:** `$0.50`, this-run time, paired manual time, quality result and report link. The old Range figures—43.06 seconds versus 528.31—imply a provisional break-even value of time of only **$3.71/hour**; v3 must remeasure this. [BRIEFING-V2.md:118–129](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:118)
7. **Proof:** settled transaction/payment ID, unique nonce, input hash, output hash and delivery time.
8. **Primary limitation:** one prominent sentence, with raw evidence expandable below.

Range Doctor already has the factual core—range status, net rate, conditional actions and block provenance. The missing pieces are reliable coverage, dollar-level consequence, measured value and settlement. [doctor.py:86–177](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/agents/pancake/doctor.py:86)

### TermiX track-losing failures

- The receipt still says `verified_unsettled`, or replay can buy a second result.
- TermiX pays and receives `[]`, `no_position`, zero-delta Yield, stale SOLVENT, or raw JSON.
- V3 lacks a genuine manual arm, time, cost, quality, full outputs or a high-stakes task—the formal eligibility gate. [BRIEFING-V2.md:125–129](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:125)
- V3 inputs are selected after results, failures are discarded, or v2’s null arms are described as human comparisons.
- Current Warden is presented as strong despite its attached loss and low recall.
- The controlled example drifts during Sep 9–23 and the report’s own input stops reproducing.
- Any claim says Grid has a trading record, or Pancake volume was routed without the approved proof.

## 2. PancakeSwap

**Range Doctor plus the 22-pool/49.3% result is enough to place. It is not enough to make first place the expected result.**

The finding is real and unusually good: SHA-pinned data, 22 eligible pools, gross error larger than rounding error on 22/22, median relative overstatement 49.3%. But it is one annualized 24-hour snapshot; it proves a calculation error, not that an LP changed a decision, avoided a loss or earned more. [01-liquidity-arithmetic.json:7–25](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/advantage/v2/runs/01-liquidity-arithmetic.json:7) Its provenance is also self-attested because the liquidity spec and run entered git together. [FABLE-AUDIT.md:213–216](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/FABLE-AUDIT-2026-08-14.md:213)

A winning Pancake submission needs one unmistakable loop:

> **Range Doctor finds a live Pancake LP mistake, quantifies the money at stake, and gives the LP a safer decision without ever obtaining authority over the funds.**

Close it with:

- A Docket-controlled, still-open V3 LP position that remains reproducible through Sep 23.
- A human result showing position state, dollar consequence, net-versus-gross rate, switching cost/break-even and exact next action.
- A preregistered decision-impact artifact: measure pool-ranking reversals, dollar overstatement at fixed notionals and break-even changes—not just APR error.
- A fixed-window live record: state → diagnosis → owner decision → later state. Report observation, not causal alpha.
- Range Doctor remains the singular hero. Yield supplies calculations underneath it; it is not pitched as a second hero.
- Preserve the structural safety claim: Range Doctor holds no key, requests no approval and has no path that moves funds. [doctor.py:1–7](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docket/agents/pancake/doctor.py:1)

### If Grid mainnet is not approved

It does **not** change the hero or make Pancake ineligible: the published paragraph expressly allows smarter liquidity analysis and yield discovery; execution is optional, while fund safety is absolute. [BRIEFING-V2.md:166–181](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:166)

It does make the Range Doctor decision-impact proof non-negotiable. Cut all submitter/testnet work and move those 2–3 days into the live LP record and repeated net-versus-gross analysis. Claim no routed volume.

If Grid is approved, show it only as an appendix: registered session, one confirmed swap, cap decrement, revoke and post-revoke refusal. A transaction proves safe execution; it does not prove the trade benefited the user. Current ground truth is zero routed volume. [BRIEFING-V2.md:283–295](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-BRIEFING-V2.md:283)

## 3. Revised dated build order

| Date | Work and hard exit |
|---|---|
| **Aug 14** | Lock the v3 task-family specs and Pancake decision-impact protocol in git before any run. Owner clears registration/Terms, paid-hire approval and the controlled Pancake LP input. Move Grid’s yes/no deadline from Aug 23 to **Aug 16**. Define the paid-stock admission and no-result/no-charge rules. |
| **Aug 15–16** | Fix Range’s limit/closed-position failure; add the controlled example and decision-grade presenter; begin daily LP-state capture. Land the wheel/homepage defects and v1→v2 relationship. Exit: a fresh browser gets a non-empty, intelligible Range result. |
| **Aug 17–20** | Exact-once `$0.50` settlement: asset/domain/time binding, persistent nonce/payment ID, replay handling and payment-to-output binding. Exit: a stranger pays once and receives the non-empty Range result; replay is refused or idempotent. |
| **Aug 21–23** | Repair and evaluate Warden; wire Yield’s complete named-pool inputs; finish the replicated v3 runner and blinded score sheets. Weak services do not enter paid stock. |
| **Aug 24–26** | Finish the Pancake decision-impact artifact from the live capture. If Grid was approved and all preceding gates are green, execute the single bounded proof; otherwise do no Grid implementation. |
| **Aug 27–28** | Publish the minimal package: README, license, AI usage, claims-to-evidence table, one TermiX evidence route and one Pancake hero route. Public by Aug 28. |
| **Aug 29–30** | **BNB shortlist lane, capped at two days:** four ERC-8004 registrations, reverse agent→hire links, one verified complete registry sweep and application restart. It may not displace an unfinished primary gate. |
| **Aug 31** | Uncoached cold rehearsal: sample, settled hire, replay attempt, Range/Yield/Warden results, mobile, clean install and failure recovery. |
| **Sep 1–4** | Execute all preregistered paired cases and preserve every output/failure. |
| **Sep 5** | Blind scoring, report generation, claim audit and Pancake fixed-window publication. |
| **Sep 6** | Freeze the exact tested deployment and evidence hashes. |
| **Sep 7–9** | Demo/submission rehearsal; submit only after explicit owner approval. |
| **Through Sep 23** | Monitor the paid hire, featured services and controlled LP input continuously. [SYNTHESIS-V2.md:288–293](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-SYNTHESIS-V2.md:288) |

## 4. Single highest-risk item

**The first cold paid Range Doctor hire fails to return decision-grade value.**

That one event damages TermiX’s 30% Value and 20% Marketplace Quality scores and simultaneously destroys Pancake’s hero demonstration. The exact failure already exists: the evidence wallet returns an empty position list after examining only closed positions. [SYNTHESIS-V2.md:119](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-SYNTHESIS-V2.md:119)

Mitigation: make one daily release canary the governing gate:

> fresh browser → controlled live LP → exact `$0.50` settlement → complete human result → matching payment/input/output proof → rejected replay.

Any failure automatically removes **Pay and hire** until corrected; the free verified example remains available.

## 5. What a stronger competitor will do

A well-resourced competitor will:

- Show completed paid jobs and independently scored agent-versus-human evidence, not minimum three-task compliance.
- Show one Pancake-native outcome in dollars, across multiple observation windows, rather than a static percentage headline.
- Present one hero that works in under a minute without a wallet hunt or JSON interpretation.
- If it executes, publish allowlist, cap, expiry, transaction and revocation evidence.
- Keep durable judge inputs and live canaries so the report and button never contradict each other.
- Enter judging with a high-stakes agent whose attached record is genuinely strong, rather than relying on transparency about weak performance.

Docket’s advantages are evidence integrity and structural safety. A stronger competitor beats it by matching those while adding external validation, outcome proof and flawless presentation.

## 6. Waste under the new priority

Cut entirely:

- **SOLVENT funding, resumption and card work.** Retire the halted read to research; Warden is the TermiX high-stakes lane. The operative synthesis already permits removal. [SYNTHESIS-V2.md:155–157](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-SYNTHESIS-V2.md:155)
- **The Venus-borrow half of the demo wallet** and new Health-specific evidence work.
- **Broad four-category metric parity.** Keep evidence work only for Range, Yield, Warden and approved Grid.
- **The full six-hour registry refresh daemon and weeks-long registry-history build.** Replace it with one verified complete sweep/restart for the capped BNB lane. Retain service/payment/LP canaries because those protect the primary tracks.
- **All Grid submitter/testnet work if approval is absent on Aug 16.**
- **Provider onboarding, BNB Phase-2 adoption assets, Agent Studio/Bedrock, Altana UI, autonomous keepers, Venus execution, full Yield migration, second-chain work and trust scoring.** [SYNTHESIS-V2.md:297–304](/C:/Users/gudma/OneDrive/Desktop/GITHUB-FILES/docket/docs/deliberation/2026-08-14-SYNTHESIS-V2.md:297)

Keep the four ERC-8004 registrations and one fresh sweep only because they are the minimum defensible BNB-shortlist package. Everything before them must first make TermiX’s paid hire and Pancake’s Range Doctor proof first-place quality.
