# Docket — Claude's Assessment (2026-08-14, round 2)

Written before seeing Codex's or Fable 5's round-2 assessments, so the three stay independent.
Facts here were verified this session; where I did not verify, I say so.

---

## Executive verdict

| Track | My position | The binding constraint |
|---|---|---|
| **TermiX 1st** | **Winnable — most winnable of the three** | Pricing (30% criterion) and SOLVENT's missing track record (20% criterion). Both are addressable in days, neither is a rebuild. |
| **PancakeSwap** | **Winnable, and under-claimed today** | The brief explicitly permits analysis; our no-key design answers its only absolute *structurally*. The gap is narrative, plus optionally one real routed swap. |
| **BNB main $30k** | **Reachable but not favoured** | "Real-time" data (unbuilt), a zero-knowledge journey (unproven cold), and four categories filled by advisors rather than actors. |

I do not think winning all three is impossible. I think **BNB is the one that can be lost by
default** — through a stale snapshot and an unproven journey — rather than lost to a better
competitor.

---

## 1. The one structural insight I want on the record

**Docket's no-verdict discipline is currently applied at the wrong altitude for BNB.**

BNB's Data Quality criterion ends in a decision: *"A user should be able to look at what you're
showing and make a genuinely informed call on which agent to hire."* Docket today serves
observations and then explicitly declines to help the reader choose. That refusal is **correct**
at the level of a global trust score — we should never publish "this agent is safe" — and
**wrong** at the level of decision support.

The last synthesis already named the fix and it was never built:

> **Policy plane** — evaluate the user's *own stated* constraints ("observed inputs satisfy 4 of
> your 5 predicates; here's the one that failed"). Not a verdict — it's the user's own rule,
> checked.

Stages 0–4 built the fact plane and the action plane. **The policy plane is the missing third,
and it is precisely the thing that converts Data Quality from "honest" into "genuinely informed
call" without conceding a single inch of the no-verdict discipline.** A user says what they
care about; Docket checks their rule against observations and shows which predicate failed. The
verdict belongs to the user; Docket only does the arithmetic.

If I get one build after the refresh loop, this is it.

## 2. The finding I believe neither other assessor will surface

**Five of Docket's six services carry no on-chain identity.** Verified live this session:

| service | `agent_id` |
|---|---|
| `range-doctor` | `None` |
| `grid-operator` | `None` |
| `yield-router` | `None` |
| `health-guard` | `None` |
| `warden-scan` | `None` |
| `solvent-signal` | `56:0x8004…a432:136384` (and the agent is **halted**) |

This is honestly disclosed in the product and bound by a test
(`tests/test_marketplace.py:305`, `test_an_unbound_service_says_no_identity_is_bound`), so it
is not a hidden defect. But set it against BNB's eligibility line:

> "**Agents surfaced on your marketplace must be live on BSC.**"

The defence used in the last briefing was that the 506 indexed registry agents satisfy this.
That defence holds for the *marketplace*. It does **not** hold for the **four category slots**,
which are filled exclusively by Docket's own services — and four of those four have no BSC
identity at all. A judge who opens the Grid Trading category, clicks the one agent in it, and
asks "is this live on BSC?" gets `None`.

I rate this **higher than a scoring risk and lower than a disqualification**: the rule most
plausibly governs the marketplace's inventory rather than the operator's own tooling. But it is
the cheapest expensive problem on the board — a handful of `register()` transactions on BSC
mainnet closes it permanently, and it simultaneously strengthens Agent Diversity (the categories
become on-chain agents, not just Docket features) and TermiX's marketplace-quality criterion.
It needs gas and the user's approval, which is why it must be raised now rather than in
September.

## 3. On pricing — my recommendation, stated as a decision

Facts: every Docket service is **0.01 $U** (~1¢). TermiX's live marketplace is p25 **$20**,
median **$70**, p75 **$100**, and their 30% criterion is named *Value of the services*. Our own
approved spec says to price into that band and we did not.

The naive fixes are both wrong. Raising everything to $70 puts a tollbooth in front of the judge
BNB wants to activate frictionlessly, and invites "you charged $70 for a 30-second read."
Leaving everything at 1¢ tells a marketplace judge that nothing here is worth money.

**My recommendation: a two-tier structure, priced by what the work actually is.**

- **Preview / diagnostic tier — free or ~1¢, unchanged.** This is what BNB's judge hits and
  what makes the cold journey frictionless. It is also honest: a 25-second read *is* worth about
  a cent.
- **A priced tier in TermiX's band ($20–$100) for work that justifies it** — the depth that
  takes real compute and real analysis, and that a buyer would genuinely pay for. Priced per
  category, not uniformly.

The reason this is the right shape rather than a compromise: **it is the only version that is
true.** Docket's entire thesis is that prices and metrics should match what was actually done.
A uniform 1¢ and a uniform $70 are both claims we cannot defend; a tier that reflects the work
is one we can. It also demonstrates to BNB that the marketplace can carry real commerce, and to
TermiX that we understand what a service is worth — while keeping their own hire cheap enough
that they actually complete it.

I hold this less firmly than anything else in this document, and I have flagged it as the item I
most want Codex to overrule if it sees a better structure.

## 4. On "four advisors where the rubric describes four actors"

BNB's category verbs are *manages*, *places*, *routes*, *protects*. Docket's four category
services are read-only or preview-only.

I now think this is **a real risk, but a smaller one than I first framed it**, for a reason that
matters: BNB is judging **the marketplace**, and the category table describes **what agents in
that category do** — not what the marketplace operator's own agents do. A marketplace that
surfaces third-party rebalancing agents satisfies the category regardless of what Docket itself
builds.

But that defence has a hole we dug ourselves: `/categories` declares that Docket "assigns none
[no category] to a third-party registry agent." So today the categories contain *only* our own
advisory services, and the third-party inventory that would satisfy the verbs is uncategorised.

**The fix is therefore not "make our agents act."** It is to categorise the registry inventory —
which is the marketplace's actual job, is what BNB asked for ("make that legible to a person
deciding who to hire"), and does not require us to build four executing agents in 26 days. Our
own services then sit inside those categories as first-party depth rather than as the entire
contents.

That said — Grid Operator can already act, and the mainnet proof is one approved session away.
One real executed grid level would convert the strongest category from preview to actor and
serve PancakeSwap at the same time. Highest single-action leverage on the board, and it is
user-gated.

## 5. Where I stand on my own opening position

Re-reading §3 of the briefing having verified more:

- **(1) Refresh loop first** — I hold this, more firmly. It is the only gap that is purely a
  build, blocks nothing, and directly answers a criterion's first word.
- **(2) Pricing** — refined into §3 above.
- **(3) SOLVENT's win rate / window / risk** — I hold this. It is the only place a sponsor named
  something explicitly and we publish nothing. Note the honest constraint: the agent halted
  2026-06-28, so any record is historical. That is fine — TermiX asked for *the window*, which
  means a dated window is a valid answer. Silence is not.
- **(4) Four advisors vs four actors** — revised, see §4. The fix is categorising inventory, not
  building executors.
- **(5) PancakeSwap under-claimed** — I hold this and would go further: our structural safety
  answer is stronger than anything an executing competitor can claim, and we are not saying so.
- **(6) The adoption question** — I hold this and now think it is the key to Phase 2. See §6.
- **(7) Housekeeping** — I hold this. It is the only category of risk here that is purely
  self-inflicted.

## 6. What survives the [REDACTED] Phase 2

Phase 2 is unknowable, so the only rational strategy is to be the submission that gets *better*
under scrutiny rather than worse. Three properties do that:

1. **Every number recomputable by the reader.** Already true and already tested. This is
   Docket's deepest moat and it is exactly what a second, closer look rewards.
2. **A published loss.** The Advantage Report v1 publishes a task the agent lost, pinned by a
   test. Nothing signals "these numbers are real" like a number that isn't flattering.
3. **An honest answer to "can we grow this?"** — which we have never written. BNB is buying a
   growth funnel. A submission that says *here is who the next 1,000 users are, here is what
   breaks at that scale, here is what we would need* reads as a team worth incubating. Every
   other entrant will say "we're excited to grow with BNB Chain."

## 7. The thing nobody has named

**We have been building for the rubric and not for the judge's ten minutes.**

Stages 0–4 added enormous real depth — 792 tests, pre-registered falsifiers, computed null
baselines, a 47-payload labelled corpus. Almost none of that is visible in the first ten minutes
of someone landing on `docket.gudman.xyz` cold. BNB's Functionality criterion is *explicitly* a
ten-minute test: land, find, understand, activate, no dead end.

The risk is not that Docket is shallow. It is that **Docket's depth is arranged for a reader who
already trusts it**, and every judge arrives untrusting and in a hurry. The landing page leads
with epistemics ("What answered, and what only claimed to") where BNB's judge needs to be
oriented and moving within seconds.

This does not mean dumbing anything down. It means **progressive disclosure**: the answer first,
the evidence one click behind it, the caveat attached to the number rather than in front of it.
Same facts, same discipline, different order. That reordering may be worth more BNB points than
any new feature we could build in 26 days — and it costs no integrity, because nothing is
removed.

---

## My ranked build order (input to the synthesis, not the final word)

Calendar: 26 days. Aug 31 paid-hire gate. Sep 1–5 report re-run. Sep 6 freeze.

| # | Item | Why now | Gate |
|---|---|---|---|
| 0 | **Housekeeping**: README, LICENSE, AI_USAGE.md; registration + Terms | Submission-blocking; overdue; needs no approval to draft | User must register + flip repo |
| 1 | **Refresh loop** | Answers "real-time"; must run for weeks before Sep 1–5 to be credible | — |
| 2 | **Categorise the registry inventory** | Turns 4 slots-with-one-service into a real marketplace; serves Diversity + Functionality + the "legible" mandate | — |
| 3 | **Progressive-disclosure pass on the human journey** | The ten-minute test; cheapest large BNB gain | — |
| 4 | **Pricing tier** | TermiX 30% | User decision |
| 5 | **SOLVENT window/risk/win-rate** | TermiX 20%, named explicitly | Data exists |
| 6 | **Policy plane (user's own predicates)** | Converts Data Quality to "informed call" | — |
| 7 | **Paid x402 proven end-to-end** | Hard Aug-31 gate | User approval, 0.01 $U |
| 8 | **On-chain identity for the four category services** | Closes the BSC-live question | User approval + gas |
| 9 | **Grid mainnet proof** | Converts PancakeSwap to a hard fit; one action | User approval + session key |
| 10 | **Adoption/growth narrative** | Phase 2 | — |

Items 0, 7, 8, 9 are user-gated and must be raised **this week**, not in September, because they
sit in front of dated gates.

---

*Independent view, written 2026-08-14 before reading Codex's or Fable's round-2 output. Per the
standing directive, Codex is the director on this project; where this document and Codex's spec
disagree, Codex's spec governs unless I can show a verified factual error.*
