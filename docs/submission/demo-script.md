# Docket recording plan — September 9 closeout

This is an optional recording plan, not an outstanding submission requirement or an existing video.
The owner clarified that video is optional. No demo video is supplied as of
the September 9 closeout. The owner reports that the Google form has already been submitted.
Record real narration and a fresh live journey; do not present stored evidence
or a prior log as live execution.

## Required outcome disclosure — add up to 45 seconds to the tour

After the evidence segment, say: “The local Yield experiment did not obtain the three
required valid pairs. One manual attempt was interrupted, a second timed out, and the
remaining case is unstarted. I completed a separate assisted text-review demo; it has no
elapsed-time measurement and cannot support a registered human-versus-agent speed claim.
The original experiment record is preserved.”

If showing the downloaded JSON, keep its assisted label and show only non-private fields:
`registered: false`, `assistant_assisted: true`, `eligible_for_speed: false`, and
`elapsed_seconds: null`. Identify it as local evidence. Do not imply these later outcomes
already appear on the public report. The v1 LP manual-tool arm was also agent-operated;
do not describe its recorded time as an unaided human baseline or guarantee TermiX eligibility.
See the [closeout](closeout-2026-09-09.md) for exact timestamps and evidence hashes.

**Recording gate.** Record this only against the deployed integrated release — the
activation pages, bounded sessions, marketplace search and the status page all live on the
host being filmed; if any one of them is not serving, the recording does not start.
Every figure that appears in the film is read off the page at the moment it is shown, so
nothing in this script is a number to recite and no figure here can go stale into a video.

Record at 1280×720 or higher from a cold browser with a wallet available but initially disconnected. Keep the address bar visible whenever changing pages so the public URL is part of the shot. Connect only at the activation step. Do not fund a session for this script.

This is a successful journey, recorded in the order a visitor walks it: the promise, the comparison, the activation, the result, the four categories, the evidence, and the boundary. Describe what is on screen. Read every figure off the page at the moment it is shown rather than reciting one from this script — a number typed here goes stale, and a stale number in a recording cannot be corrected.

## 0:00–0:20 — the promise

**URL:** <https://docket.gudman.xyz/>

**Action:** Land on the marketplace. Do not scroll yet.

**Say:** “Docket's snapshot page reports the BSC registry population it observed, with its age and denominator. Registration alone does not tell us whether a service works. Docket lets a visitor compare the recorded evidence, activate a service with bounded permissions, and inspect the result's receipt and supporting record.”

**Point at:** the headline, the two actions, and the counter rail beneath them. Say that every counter on that rail is counted from the store at page build and published at [/api/marketplace/summary](https://docket.gudman.xyz/api/marketplace/summary). Read the displayed values, including any zeros.

## 0:20–0:50 — discover and compare

**Clicks:** **Explore live agents**, then scroll through the four job cards into the listings grid.

**Say:** “A visitor starts from the job, not from a taxonomy: keep an LP position in range, automate a trading grid, move liquidity to better yield, protect a lending position. Under them, every listing answers the same questions — the job, the BSC identity, the last successful verification, the successful-run count against its denominator, the measurement window, the price per completed run, the custody model, the permissions required, what can be cancelled or revoked, and the evidence link. Where there is nothing behind a field, it says `not yet measured` instead of disappearing. That is what makes two listings comparable.”

**Point at:** the same field appearing in the same place on two different cards, and one `not yet measured` cell.

## 0:50–1:35 — activate

**URL:** <https://docket.gudman.xyz/activate?service=range-doctor>

**Clicks:** Open **Range Keeper** (service id `range-doctor`), choose a one-shot, enter the worked-example inputs shown by the form, and select **Activate on the free tier**. Connect the wallet and sign the create and approve requests. **Try free sample** and **Use the worked example** run samples, not activations.

**Say:** “This is a one-shot activation on the free tier, not a payment. The page states the inputs, price and permission scope before the wallet signs. Create and approve are separate signed requests; the result appears only after the run completes.”

**Point at:** each control as it is named; then the summary of what is about to be granted, immediately before the confirmation step.

**Boundary to say out loud:** “This free one-shot reads and reports. It is not a funded session executing a trade.”

## 1:35–1:55 — the result and the control that follows it

**Say, only after completion:** “The one-shot completed with a result and a receipt binding the input and output hashes. A continuous session is a separate lifecycle. The published September 5 evidence records an unfunded session key being minted and revoked, with all balances verified zero; that is not evidence of funded execution.”

**Point at:** the one-shot's completed state, result, receipt hashes, and permission scope. If showing session controls, label them as a separate session; do not claim a one-shot has been paused or revoked. [Dated session evidence](../operational-evidence.md#the-first-real-activations).

**Boundary to say out loud:** “A receipt binds hashes to a delivery record. It does not establish that the result is correct, and it does not establish that a reported settlement reached chain finality.”

## 1:55–2:20 — the same journey in all four categories

**URL:** <https://docket.gudman.xyz/categories>, then back to the listings grid.

**Say:** “Every one of BNB's four categories has an agent behind it, and all four are activated through the same flow with the same shape of limits: Range Keeper for rebalancing, Grid Operator for grid trading, Yield Router for yield optimisation, Health Shield for health factor. Each listing prints its service id — `range-doctor`, `grid-operator`, `yield-router`, `health-guard` — beside the name, so the marketplace name and the API contract can always be joined. The category labels are Docket's own declarations about services Docket runs; the registry publishes no field that says what job an agent does, and the category response says so in its own body.”

**Point at:** the four listings in the grid, then the declaration sentence in the JSON.

## 2:20–2:40 — agent advantage, one page

**URL:** <https://docket.gudman.xyz/advantage>

**Say:** “At the top of the report, every registered task and family sits on one page: the arms it ran, how many, the times and costs its records carry, its objective quality measure, and its state. Three words do the work a blank cell cannot — `unscored` means the required scoring artifacts are absent, `not run` means no attempt became terminal, and `not recorded` means the protocol registered no such measure. Every value is read from the committed artifacts.”

**Point at:** one row whose state is `complete_unscored`, one row whose measures read `not run`, and the caption naming which report each table comes from.

## 2:40–3:00 — the trust moat

**Say:** “The catalogue makes its evidence inspectable: BSC identity bindings where present, dated endpoint observations, delivery receipts with recomputable hashes, metric provenance, and adverse results. Missing evidence stays visible. The security comparison where the human arm beat ours is on the same site as the flattering results.”

**Then open:** <https://docket.gudman.xyz/registrations/range-doctor.json> and, briefly, the adverse case on the home page.

**Say:** “This is the published token URI for `range-doctor`, the service behind Range Keeper: BSC ERC-8004 agent 311253. Grid, Yield, and Health are agents 311255, 311257, and 311259; all four were minted on August 28 and the recorded owner is the registration wallet. Registration is not endorsement, not paid stock, and not evidence that a service produced a result. Warden remains unbound.” [The exact blocks and transactions are committed here.](../erc8004-category-identities.json)

Finish on: “Docket makes what exists — and what does not — clickable.”

## Slow-read fallback

If a live chain read has not returned after 12 seconds, say: “The live chain read is still pending, so I am switching to the stored public evidence rather than narrating a value that has not arrived.” Then open, in order:

1. <https://docket.gudman.xyz/api/marketplace/summary> — the counters behind the rail, recounted per request.
2. <https://docket.gudman.xyz/services> — every catalogue service with its admission limbs and `paid_stock` state.
3. <https://docket.gudman.xyz/advantage/v2.json> — the v2 artifact containing the frozen, post-hoc decision-impact arithmetic.
4. <https://docket.gudman.xyz/advantage.json> — the three completed paired tasks and actual outputs.

Return to the activation flow only if the live result has arrived; do not claim that a pending or failed read succeeded.

## What must not be said

- Do not describe any service as available to buy. At the 2026-09-04 observation this script is based on, `cold_canary` is false for all six services, so all six remain `paid_stock=false` even where fresh paired evidence is true, and the listings say so. One owner-approved Range Doctor canary settled 0.50 USDT on August 30 and the identical signed request was then rejected as a replay; that private bootstrap opened no public inventory, and the counter rail keeps the two apart.
- Do not read a registry total from memory. It is read off `/stats` at the moment it is shown, and cited as the figure `/stats` reported at the time of recording.
- Do not call `v3-04-warden-security` a performance result. It is `complete_unscored`: all 24 primaries became terminal, 23 succeeded, manual `w4-ho-01` failed, a named scoring seat returned no first response, and the registered rule forbids a retry or a substitute.

## Thirty-second version

- **0:00–0:10:** Open <https://docket.gudman.xyz/>. Say: “Find BSC agents that actually work. Every listing answers the same ten questions, and every counter on this rail is counted from the store rather than typed.”
- **0:10–0:22:** Open the Range one-shot activation. Say: “Choose the job, inspect the inputs, price and scope, then sign. This is quoted free; the receipt does not prove payment or funded execution.”
- **0:22–0:30:** Open <https://docket.gudman.xyz/advantage>. Say: “Every registered task and family on one page, with `unscored` and `not run` distinguished from a blank. Including the comparison our own security agent lost. Hire by evidence, not promises.”
