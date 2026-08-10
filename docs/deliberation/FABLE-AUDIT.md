# Fable 5 — Independent Strategic Audit (2026-08-10)

Independent of Claude's briefing and Codex's build. Everything load-bearing below was checked
against the repo at `main` (9c6101b), the live product at https://docket.gudman.xyz, the sqlite
snapshot itself, and one real hire executed as a judge would execute it. Where I could not verify
(the sponsors' criteria text), I say so and audit against the briefing's quotes as given.

Method notes, stated up front because this audit holds Docket to Docket's own standard:

- I ran the full test suite locally: **225 passed** (28.46s). The briefing's count is accurate.
- I executed one live free-tier hire: `POST /hire/solvent-signal` → **HTTP 200 in 2.75s**, real
  payload, receipt with `payment.status: "free_tier"`. The cold-hire claim is true as deployed.
- The category-scarcity finding below rests on keyword search over `name + description` of the
  506 stored agents — a placeholder-heavy registry, so it may undercount. The direction is
  nonetheless unambiguous (zeros, not small numbers).
- Sponsor criteria (BNB's three criteria, TermiX's weights, PancakeSwap's brief) I could not
  reach independently this session; I audit the product against BRIEFING.md's quotes as given.

---

## 1. Is Claude's central claim true? (Data Quality win / Functionality compete / Diversity forfeit)

**Partially. Claude is over-generous to itself on two of the three, and the third is worse than
briefed.**

### Data Quality: strongest-in-field on integrity, but the criterion's first word is "real-time" — and Docket fails it today

What is genuinely true: no rival will match the integrity layer. Every figure carries its
denominator (`coverage.py:50-83`), the probe method travels with the number (`routes.py:94-99`),
the outcome vocabulary is closed and each outcome states what it does not mean
(`app.js:24-65`), and a contract test bans verdict vocabulary across every response model
(`tests/test_api_contract.py:37`). This is real and rare.

What the briefing under-weights:

- **The served data is a static snapshot pinned at process startup.** `create_app` resolves
  `snapshot_id` once (`routes.py:191-198`: "Resolved once here rather than per request") and the
  live `/stats` returns `captured_at: 2026-08-07T17:51:02Z` — already 3 days stale at audit time.
  There is **no refresh mechanism**: no cron, timer, or deploy script in the repo, and the only
  GitHub workflow (`.github/workflows/ci.yml`) runs tests on push — no schedule, no sweep, no
  deploy. The live `captured_at` of Aug 7 confirms nothing is refreshing. Judging runs 9–23
  Sept. Untouched, judges will read a **five-to-six-week-old snapshot** on a page whose own UI
  prints "captured 6 weeks ago" (`app.js relativeTime`). BNB's criterion as quoted: "Real-time,
  accurate data." We are accurate and not real-time, and our own honest UI will announce it.
- **"Make a genuinely informed call on which agent to hire"** — Docket's data mostly proves which
  agents are *dead* (13 endpoints responded of the 35 probed, across 506 agents). That is decision-relevant negative
  evidence, but the affirmative decision data BNB's four categories imply (APR performance,
  positions managed, win rate, health factors protected) exists nowhere in the index. Docket's
  Data Quality is deep on one axis (provenance) and thin on the axis the categories ask for.
- **A self-inconsistency a TermiX-grade judge would catch:** the human landing page prints
  "sampled 506 of 506 expected, complete" with no mention that the registry holds **247,278**
  agents and 506 is the ≥1-feedback slice. The 247,278 denominator is disclosed only in the
  machine docs (`llms.txt:247`, `SKILL.md:78`); `ingest.py:128-130` itself warns "a filtered
  total read as a registry total is the exact conflation this project exists not to publish" —
  and the human front page performs approximately that conflation by omission. The flagship
  denominator product omits its own largest denominator where humans read it. Cheap to fix;
  embarrassing to be caught on.

**Verdict: "wins Data Quality" is half-true — wins the integrity half, currently loses the
real-time half, and is thin on category decision data. With a refresh loop it becomes a true
claim.**

### Functionality: the machine journey competes; the human journey does not exist

The machine journey is genuinely excellent — a cold agent with no account, key, or wallet
orients from `/llms.txt`, hires, and gets a hash-bound receipt (verified live, 2.75s). But BNB's
criterion as quoted is the *human* journey: "land, find an agent by category, understand what it
does, activate it, with minimal friction."

- **There is no hire control anywhere in the human UI.** The nav is Overview / Browse agents /
  Advantage report / API (`index.html:37-42`, confirmed identical live). No page links `/hire`.
- **Hiring is POST-only** (`routes.py:607`) and **CORS is deliberately GET-only**
  (`routes.py:228-233`), so even a third-party page could not offer a hire button; llms.txt says
  it outright: "a cross-origin browser page cannot hire; hire from a CLI, a server, or
  same-origin." There is no same-origin page that does.
- **There is no category anything.** `signals.py:40-50` computes six signals; none is a
  category. Browse filters are has_feedback / declares_callable / responded / publisher
  (`app.js:320`). The only "category" in the codebase is the advantage harness's task label
  (`harness.py:44`).

A judge who lands with zero Agent Studio knowledge cannot find an agent by category (no
categories) and cannot activate anything (no control). **Against the criterion as written, we do
not "compete on Functionality" today — we forfeit the human half and excel at the machine half
that the criterion does not name.** Claude's "skeptic-shaped" framing softens this.

### Agent Diversity: forfeited, and — contra briefing gap #1 — NOT closable by data-and-config

The briefing calls this gap "data-and-config-shaped, not a rebuild." I checked the data. Keyword
search over the 506 stored agents' names + descriptions (snapshot 3, the live one):

| BNB category | matches among 506 |
|---|---|
| rebalanc\* | **0** |
| grid | **1** ("HodlAI Protocol") |
| yield | **3** |
| health factor / liquidat\* | **0** |

(Method caveat above; but the placeholder-heavy registry means the true counts are near these.)

**The four categories are essentially unpopulated in the population Docket indexes.** You cannot
tag your way to "all four, equally deep" — three of the four categories would be empty shelves.
Closing Agent Diversity requires *agents that exist*: building/registering our own category
agents (Range Doctor already is a Rebalancing-category adviser in substance — "manages LP
ranges" is its literal subject, `doctor.py:1-44`), and/or indexing the Agent-Studio-scaffolded
population BNB's tooling produces. That is a build, not a config change. **The briefing's one
concrete cost estimate for its highest-leverage gap is wrong, and planning on it would burn the
remaining month.**

A trap worth naming now: shipping a four-category browse UI *before* the agents exist would
display three empty categories — worse for Agent Diversity optics than no category UI at all.

### One more thing Claude did not flag: the deployed build lags main

Live `GET /escrow` → `404 {"error":{"code":"not_found"}}`, and the live root JSON has no
`escrow` key while `routes.py:303` includes it. **The whole Phase 1h escrow rail — six commits,
five test files, the TermiX-relevant "real job" rail — exists only in the repo.** Combined with
the private repo (verified: `gh … isPrivate: true`) and no LICENSE (verified), the thing judges
can see is materially less than the thing that was built. For a project whose thesis is "the
claim matches the observation," repo-live drift is the one bug class we cannot afford.

---

## 2. Honest probability picture

These are subjective priors over a field I cannot observe (top-tier global teams, unknown entry
counts). Ranges, not points; as-is vs. with the fix list in §5 landed.

### TermiX 1st ($6,000) — as-is ~25–35%, with fixes ~40–50%. Best odds of the three.

The alignment is real and rare: the Advantage Report eligibility gate exists with both arms'
full outputs and recomputable hashes; a published loss (03-security: manual found 4 vectors,
agent found 1) sits in the summary table where a reader meets it first (`advantage.html:187`);
the 120× trading number is discounted in our own copy (`advantage.html:731-732`); the payment
layer states exactly what it does not prove (`x402.py:1-31`, `verified_unsettled`, never
"paid"). TermiX's own product flags >95% pass rates and prints sample sizes — a jury with that
culture will recognize this build. Most rivals will skip the eligibility gate or fake it with
marketing gloss; TermiX says they will hire from the marketplace themselves, and our cold hire
works in 2.75s with no instructions.

**Single biggest threat: value-of-services thinness (their 30% weight) compounded by upstream
fragility.** Three services at 0.01 $U: one strong (Range Doctor), one an honestly-framed
*historical record from a halted agent* (SOLVENT, last signal 2026-06-29 — verified in my live
hire), one a relay of a scanner that *lost our own security benchmark 4-to-1*. Two of the three
depend on `solvent.gudman.xyz` / `warden.gudman.xyz` staying up through late September
(`catalogue.py:43-44`); an upstream outage during judging turns a hire into a 502 in front of
the one jury that will actually press the button. Secondary: "find, compare, hire, without
instructions" (their 20%) currently requires finding a JSON endpoint — the human hire page in §5
fixes that. Also unserved: TermiX's stated trading-agent bar is "win rate, the window, and the
risk taken" — SOLVENT has a completed scored window, and none of those three numbers appears on
the listing.

### PancakeSwap (1,000 CAKE) — ~20–30%, as-is or with cheap fixes.

Range Doctor is a genuine, careful LP benefit — "smarter liquidity management" is one of the
four benefit modes their brief names, and "without ever putting user funds at risk" is satisfied
maximally by a tool with no code path to move funds (`doctor.py:1-10`). Every action terminates
in a link into PancakeSwap's own UI (`doctor.py:37`), which *is* traffic routed to them. The
net-vs-gross fee APR correction (gross overstates ~⅓, `pools.py:14`) is the kind of detail their
own team will recognize.

**Single biggest threat: a rival that executes.** An agent that safely rebalances via session
keys — or even one that demonstrably moved volume/TVL — gives the judge a stronger "did this
benefit us?" answer than advice does. Our counter is measurement, not execution: we have exactly
one recorded experiment on one wallet. I do **not** endorse the briefing's suggestion to make
Range Doctor act; see §5.10.

### BNB main track ($30,000 + adoption) — as-is shortlist ~8–15%, win ~3–5%. With the full §5 package: shortlist ~25–35%, win ~10–15%.

As-is we forfeit one criterion outright (Diversity), forfeit the human half of a second
(Functionality), and undercut our genuine strength on the third with staleness. Adoption is a
growth acquisition and the current landing page is an audit report. The honest statement is that
today we are not top-3 among world-class consumer builds.

The with-fixes number is real, though, because of Phase 2: top 3 get re-judged on undisclosed
criteria, i.e., diligence. A polished rival's numbers that don't survive a second look
(fabricated activity, mock data, agents that don't answer) collapse exactly where our
receipts, tests, and denominators hold. **Our Phase-2 survivability is the best in any field;
our Phase-1 optics must merely clear the bar so it can matter.**

**Single biggest threat: the category-first activation product we don't have** — a rival whose
four categories are populated, live, and activatable in two clicks.

---

## 3. What a winning competitor likely builds that we have not

Model the strongest rival concretely. They read the same brief and build *to* it:

1. **Four Agent-Studio-scaffolded agents, one per category** — deployed via the promoted `bag`
   CLI to Bedrock AgentCore, registered ERC-8004, task interface ERC-8183, paid via Binance
   x402. Flatters every tool BNB's brief promotes; ours uses none of them by name.
2. **A category-first consumer storefront**: land → four cards (Rebalancing / Grid / Yield /
   Health Factor) → per-category live on-chain data (LP ranges with current tick, open grid
   orders, APR routing tables, health factors with liquidation distance) → "Activate" with
   wallet-connect → agent runs. Two clicks, zero jargon.
3. **Real-time by construction** — websocket or per-block indexer, "updated 12s ago" on every
   number. Against our "captured 6 weeks ago," this contrast alone decides Data Quality optics.
4. **Manufactured traction for the adoption narrative** — their own four agents seeded with
   feedback records, activity charts, a leaderboard, referral hooks. Growth-shaped, even if
   shallow.
5. **A demo video of the full journey** in under 90 seconds.

Where the strong rival is *weak* — and where we beat them if we survive Phase 1: their data is
their own agents' self-reported activity (the exact thing our probe layer exposes as usually
false — 13 of 35 declared endpoints answer at all); their metrics carry no denominators, no
provenance, no published losses; under Phase-2 diligence, "our four demo agents" is a thin
marketplace while our 506-agent index + liveness evidence + recomputable receipts is
infrastructure. The rival wins the demo; we win the audit. The job of the next month is to stop
losing the demo.

---

## 4. Does the honesty thesis hurt with BNB judges — and the framing that keeps it

Where it actively hurts, specifically:

- **The headline is negative-voiced.** "What answered, and what only claimed to"
  (`index.html:49`) frames the ecosystem BNB wants to *grow* as a field of liars. True, and the
  wrong first sentence for a judge whose prize is a growth funnel.
- **The information order is auditor-first.** The landing page leads with method (six outcomes,
  what each does not mean) before any user benefit. A consumer judge reads three screens of
  epistemics before finding anything to do.
- **There is nothing to activate**, so the honesty reads as the product instead of the
  product's warranty.

What must NOT change: the no-verdict contract (`test_api_contract.py:37`), denominators on every
figure, published losses. That is our Phase-2 armor and the TermiX win condition, and diluting
it loses the one prize we currently lead.

The reframing that keeps both — same facts, consumer voice, benefit-first order:

- **Headline flips from indictment to warranty.** "Hire agents that prove they answer. Every
  number on this site shows its receipts." Lead with the 13 endpoints that answered — they are
  the product; everything that didn't is the moat. Denominator directly beneath, unchanged.
- **"No verdicts" sold as user benefit, not abstention**: "We don't do star ratings. We show you
  the probe, the timestamp, and the receipt — you keep the judgment." That sentence reads as
  premium, not skeptical.
- **Categories as shelves with evidence chips**: each hireable listing carries "answered N days
  ago · M feedbacks of 506 sampled · advantage report" chips. Evidence becomes the visual
  language of a catalogue rather than the subject of the page.
- **The adoption pitch to BNB**: not "an audit layer" but "the discoverability layer where
  agents prove themselves — the only marketplace whose listings survive due diligence." That is
  a brand BNB can incubate; "the site that says your registry is 97% dead" is not.

---

## 5. Prioritized build list — marginal points per effort, across all three prizes

Ordered. Items 1–3 are days and convert forfeits into competitions; I would cut from the bottom,
never reorder the top.

1. **Deploy `main`; kill the /escrow 404. (hours)** Repo-live parity is a submission-blocking
   integrity bug in a project about claims matching observations. Also surfaces the escrow rail
   TermiX's own platform runs on — a differentiator no rival will have. Do today.
2. **Fresh sweep + scheduled refresh loop. (half a day)** Daily (or better, hourly) targeted
   ingest + probe + snapshot rollover. Note: `create_app` pins the snapshot at startup
   (`routes.py:191-198`), so the loop must restart/reload the service or the app must learn to
   re-resolve `latest_snapshot_id` — small change either way. This single item converts "Data
   Quality: fails real-time" into "Data Quality: strongest submission in the field," and it
   protects us from our own UI printing "captured 6 weeks ago" during judging. Highest
   points-per-effort on the board.
3. **Human hire page. (1–2 days)** `/hire` as a page: service cards, an input form, a run
   button, result rendered, receipt downloadable, free tier, no wallet. Requires allowing POST
   same-origin (CORS stays GET-only cross-origin). Scores simultaneously on BNB Functionality
   ("activate with minimal friction") and TermiX marketplace quality ("find, compare, hire,
   without instructions" — 20%). Add "Hire" to the nav on every page.
4. **Populate the four categories with agents that exist, then ship the category UI —
   in that order. (the big one; ~1–2 weeks)** Concretely, in Range Doctor's read-only,
   evidence-first mold:
   - **Rebalancing**: Range Doctor, reframed under this category — LP range management is its
     literal subject. (0 build; copy only.)
   - **Health Factor Monitoring**: a Venus Protocol position reader — health factor,
     liquidation distance, priced conditional actions. Venus is BSC's flagship lending market;
     read-only via comptroller calls; entirely buildable in the existing
     `agents/` pattern. Highest-value new agent: the category is otherwise empty ecosystem-wide
     (0 of 506).
   - **Yield Optimisation**: an APR comparator across PancakeSwap pools — the pool client and
     plausibility gate already exist (`agents/pancake/pools.py`); the new work is ranking
     wallet-relevant alternatives, stated with the same non-forecast discipline.
   - **Grid Trading**: the hardest honest fit. A grid *simulator* — replay a user-specified
     grid over recent pool history, report fills, fees, and drawdown as observations — is
     demoable without execution and without lying. If time runs out, this is the category to
     cover thinnest, stated plainly.
   Then the category-first browse/landing. Never ship the UI before its shelves are stocked
   (§1 trap).
5. **Register our agents on-chain. (1–2 days, mostly ops)** Range Doctor + new agents + Docket
   itself as ERC-8004 identities on BSC, endpoints declared, so our own index lists them and our
   probe layer shows them *answering* — the story closes on itself: the marketplace's own
   listings are its best-evidenced agents. Finish the SOLVENT #136384 re-index nudge.
6. **Surface SOLVENT's win rate, window, and risk on the listing. (half a day)** TermiX names
   those three numbers as the bar for trading agents; SOLVENT has a completed scored window;
   the listing currently shows none of them. Presented with sample size and the halt date, this
   is pure TermiX high-stakes-20% yield at trivial cost.
7. **Landing + browse reframe per §4. (1 day)** Copy and information order only; the contract
   tests stay.
8. **Fix the 506-of-247,278 disclosure on the human pages. (30 min)** Our thesis invites
   exactly this audit; pass it.
9. **Housekeeping gate: repo public, LICENSE, Terms of Participation read. (hours)**
   Zero-effort, submission-blocking. Schedule it; do not leave it for the last day.
10. **PancakeSwap extras — measured outcome over execution. (optional)** I disagree with the
    briefing's lean toward making Range Doctor act (session keys, spend caps). For 1,000 CAKE it
    is the worst points-per-effort on the board, it dilutes "structurally incapable of moving
    funds" — our clearest differentiator and safety claim — and it reopens an attack surface we
    would then have to defend under Phase-2 diligence. The cheap alternative that answers "did
    this benefit PancakeSwap?": one more recorded advantage-style experiment showing a real
    position's net fee APR before/after acting on a Range Doctor finding (acted by the human,
    through PancakeSwap's UI, via our deep link). Benefit, measured, with the user's hands on
    the wheel.

Not on the list deliberately: chasing Agent Studio / `bag` / Bedrock integration for its own
sake. Flattering the sponsor's toolchain is what the strongest rival does; our differentiation
is being the layer that *proves* what those toolchains deploy. One sentence in the submission
("Docket indexes and probes what Agent Studio ships") captures the alignment without a build.

---

## Bottom line

The build quality is the best I have audited in this program — 225 green tests, an SSRF guard
and payment verifier that state their own limits, and an evidence discipline no rival will
match. The strategy audit is harsher: today we would likely win the argument and lose the
demo. TermiX is ours to lose; BNB main is currently not ours to win. The month ahead is not
about more honesty — it is about putting shelves, stock, and a checkout in front of the
warehouse we already built, without breaking the receipts.
