# Three-minute Docket demo

Record at 1280×720 or higher from a cold browser with no wallet extension connected. Keep the address bar visible whenever changing pages so the public URL is part of the shot.

This is a successful journey, recorded in the order a visitor walks it: the promise, the comparison, the activation, the result, the four categories, the evidence, and the boundary. Describe what is on screen. Read every figure off the page at the moment it is shown rather than reciting one from this script — a number typed here goes stale, and a stale number in a recording cannot be corrected.

## 0:00–0:20 — the promise

**URL:** <https://docket.gudman.xyz/>

**Action:** Land on the marketplace. Do not scroll yet.

**Say:** “BSC has a very large ERC-8004 agent registry — read the current total off Docket's own snapshot page in a moment; at the time of recording, from `/stats`, it is the figure shown there. Almost none of those registrations tell you whether the agent works. Docket is the marketplace that answers that: find BSC agents that actually work, compare them on live performance, activate them with bounded permissions, and verify every result onchain.”

**Point at:** the headline, the two actions, and the counter rail beneath them. Say that every counter on that rail is counted from the store at page build and published at [/api/marketplace/summary](https://docket.gudman.xyz/api/marketplace/summary), including the counter that is zero.

## 0:20–0:50 — discover and compare

**Clicks:** **Explore live agents**, then scroll through the four job cards into the listings grid.

**Say:** “A visitor starts from the job, not from a taxonomy: keep an LP position in range, automate a trading grid, move liquidity to better yield, protect a lending position. Under them, every listing answers the same questions — the job, the BSC identity, the last successful verification, the successful-run count against its denominator, the measurement window, the price per completed run, the custody model, the permissions required, what can be cancelled or revoked, and the evidence link. Where there is nothing behind a field, it says `not yet measured` instead of disappearing. That is what makes two listings comparable.”

**Point at:** the same field appearing in the same place on two different cards, and one `not yet measured` cell.

## 0:50–1:35 — activate

**URL:** <https://docket.gudman.xyz/activate?category=health_factor>

**Clicks:** Open the health-factor job, choose the Health Guard listing, and load the sample Venus position that the form offers.

**Say:** “Activation is three steps: choose the job, set the limits, activate. Here the limits are the ones this job needs — the minimum collateral ratio the agent must defend, the rescue cap it may never exceed, and the expiry after which the permission lapses on its own. Those are stated before anything is signed. Then the wallet connects, and the authorization is written for an exact amount rather than an open approval.”

**Point at:** each control as it is named; then the summary of what is about to be granted, immediately before the confirmation step.

**Boundary to say out loud:** “Venus publishes no health factor. Docket derives the collateral ratio from the liquidity and shortfall the comptroller reports, and the page carries the formula, its inputs and its scales inline.”

## 1:35–1:55 — the result and the control that follows it

**Say:** “The run comes back with the job it did, and a receipt that binds the request hash and the result hash to a delivery record. The permission it was granted is shown as scope, not as a promise: what it may call, how much it may move, and when it expires. The same page carries pause and revoke, and revoking sweeps the session back to the owner.”

**Point at:** the result headline, the receipt's input and output hashes, the permission scope block, and the pause and revoke controls.

**Boundary to say out loud:** “A receipt binds hashes to a delivery record. It does not establish that the result is correct, and it does not establish that a reported settlement reached chain finality.”

## 1:55–2:20 — the same journey in all four categories

**URL:** <https://docket.gudman.xyz/categories>, then back to the listings grid.

**Say:** “Every one of BNB's four categories has an agent behind it, and all four are activated through the same flow with the same shape of limits: Range Doctor for rebalancing, Grid Operator for grid trading, Yield Router for yield optimisation, Health Guard for health factor. The category labels are Docket's own declarations about services Docket runs — the registry publishes no field that says what job an agent does, and the category response says so in its own body.”

**Point at:** the four listings in the grid, then the declaration sentence in the JSON.

## 2:20–2:40 — agent advantage, one page

**URL:** <https://docket.gudman.xyz/advantage>

**Say:** “At the top of the report, every registered task and family sits on one page: the arms it ran, how many, the times and costs its records carry, its objective quality measure, and its state. Three words do the work a blank cell cannot — `unscored` means the required scoring artifacts are absent, `not run` means no attempt became terminal, and `not recorded` means the protocol registered no such measure. Every value is read from the committed artifacts.”

**Point at:** one row whose state is `complete_unscored`, one row whose measures read `not run`, and the caption naming which report each table comes from.

## 2:40–3:00 — the trust moat

**Say:** “Five things stand behind a listing here. An ERC-8004 identity on BSC that anyone can resolve. Endpoint verification, recorded with the time it was last observed. A payment receipt whose hashes a buyer can recompute. Evidence provenance — every figure carries its numerator, denominator, window and method. And an adverse-results archive: the security comparison where the human arm beat ours is on the same site, at the same level of detail as everything else, because a marketplace that published only its flattering results would be publishing a verdict.”

**Then open:** <https://docket.gudman.xyz/registrations/range-doctor.json> and, briefly, the adverse case on the home page.

**Say:** “This is the published token URI for Range Doctor, BSC ERC-8004 agent 311253. Grid, Yield, and Health are agents 311255, 311257, and 311259; all four were minted on August 28 and the recorded owner is the registration wallet. Registration is not endorsement, not paid stock, and not evidence that a service produced a result. Warden remains unbound.” [The exact blocks and transactions are committed here.](../erc8004-category-identities.json)

Finish on: “Docket makes what exists — and what does not — clickable.”

## Slow-read fallback

If a live chain read has not returned after 12 seconds, say: “The live chain read is still pending, so I am switching to the stored public evidence rather than narrating a value that has not arrived.” Then open, in order:

1. <https://docket.gudman.xyz/api/marketplace/summary> — the counters behind the rail, recounted per request.
2. <https://docket.gudman.xyz/services> — every catalogue service with its admission limbs and `paid_stock` state.
3. <https://docket.gudman.xyz/advantage/v2.json> — the v2 artifact containing the frozen, post-hoc decision-impact arithmetic.
4. <https://docket.gudman.xyz/advantage.json> — the three completed paired tasks and actual outputs.

Return to the activation flow only if the live result has arrived; do not claim that a pending or failed read succeeded.

## What must not be said

- Do not describe any service as available to buy. No Docket service is paid stock, and the listings say so. One owner-approved Range Doctor canary settled 0.50 USDT on August 30 and the identical signed request was then rejected as a replay; that private bootstrap opened no public inventory, and the counter rail keeps the two apart.
- Do not read a registry total from memory. It is read off `/stats` at the moment it is shown, and cited as the figure `/stats` reported at the time of recording.
- Do not call `v3-04-warden-security` a performance result. It is `complete_unscored`: all 24 primaries became terminal, 23 succeeded, manual `w4-ho-01` failed, a named scoring seat returned no first response, and the registered rule forbids a retry or a substitute.

## Thirty-second version

- **0:00–0:10:** Open <https://docket.gudman.xyz/>. Say: “Find BSC agents that actually work. Every listing answers the same ten questions, and every counter on this rail is counted from the store rather than typed.”
- **0:10–0:22:** Open the health-factor activation. Say: “Choose the job, set the limits — minimum collateral ratio, rescue cap, expiry — then activate. The authorization is for an exact amount, and the permission can be paused and revoked.”
- **0:22–0:30:** Open <https://docket.gudman.xyz/advantage>. Say: “Every registered task and family on one page, with `unscored` and `not run` distinguished from a blank. Including the comparison our own security agent lost. Hire by evidence, not promises.”
