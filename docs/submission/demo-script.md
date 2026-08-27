# Three-minute Docket demo

Record at 1280×720 or higher from a cold browser with no wallet extension connected. Keep the address bar visible whenever changing pages so the public URL is part of the shot.

## 0:00–0:45 — the PancakeSwap decision surface

**URL:** <https://docket.gudman.xyz/pancake>

**Action:** Paste the URL and press Enter; do not click anything while **Live decision** loads, because this page issues the worked Range Doctor request when it opens. Scroll through **Fixed-window record**, **Economics**, **Conditional actions**, **Structural safety**, and **Decision impact**.

**Say:** “This is Docket's controlled PancakeSwap position. The top result is a fresh read, and the public [LP record](https://docket.gudman.xyz/lp-record) has 13 observations plus the owner's August 24 `WAIT` decision. The decision links to its prior observation, and three later states link back to it. That proves record linkage, not causal improvement, realized return, or that Docket caused the choice. Range Doctor holds no key, requests no approval, and has no transaction-sending path, so the choice and execution stay with the owner.”

**Point at:** the BSC block and observation time; the range-state rows; the fixed-notional and method labels; the post-hoc [v2](https://docket.gudman.xyz/advantage/v2.json) result in which protocol-fee correction produced `0/231` ordering changes across the frozen eligible-pool pairs.

## 0:45–1:30 — find and activate a service

**URL:** <https://docket.gudman.xyz/>

**Clicks:** Click **Services** in the top navigation if coming from `/pancake`; under **Keep LP earning**, click **Run it free**; on the Range Doctor page, click **Try the worked example**.

**Say:** “The marketplace starts with four jobs. A visitor can choose the LP job, read the limits, and activate this public sample with no account, key, or wallet. The response carries input and output hashes, delivery time, and payment state. The diagnosis is present, but measured value—including this-run duration and paired fields—is unavailable, so the canary fails and paid stock stays closed.”

**Point at:** the result headline, **What the chain says**, **Measured value**, and **Proof** on the [Range Doctor page](https://docket.gudman.xyz/service?id=range-doctor).

## 1:30–2:15 — show the report, including the losses

**URL:** <https://docket.gudman.xyz/advantage>

**Clicks:** Click **Advantage report** in the top navigation; at the top of the report, click **v3**, then use Back once.

**Say:** “The original report has three tasks, each run once with the service and once by hand, with both outputs attached. It includes the single-task security loss: manual reading of the frozen payload found four hostile vectors and Warden's layers identified one. V3 has no family result yet. Its v3-04 Warden input is locked and the run has begun: the first manual primary failed after a malformed operator answer, while 23 primaries remain unrun. Yield and the active Range successor still wait for inputs; the earlier Range and Warden registrations remain superseded.”

**Point at:** the question, both arms, time, cost note, output hashes, and full output in the [v1 report](https://docket.gudman.xyz/advantage.json); then the empty state in the [v3 report](https://docket.gudman.xyz/advantage/v3.json).

## 2:15–2:45 — show the marketplace's live registry layer

**URL:** <https://docket.gudman.xyz/stats>

**Action:** Paste the URL and press Enter; point at the capture timestamp and age before reading any count.

**Say:** “This is not a hand-typed total. The page states the live snapshot's capture time, population rule, sampled denominator, registry total, and endpoint-probe method. The snapshot refresh job runs every six hours, so the age on screen is the number to use.” [The timer and promotion method are recorded here.](../operational-evidence.md#the-registry-snapshot-is-no-longer-stale-and-it-moved-without-a-restart)

**Then open:** <https://docket.gudman.xyz/research>

**Say:** “The registry browser exposes the larger BSC population separately from the four Docket-run job cards; the category assignments are Docket declarations, not registry fields.”

## 2:45–3:00 — finish on identity and the owner step

**URL:** <https://docket.gudman.xyz/registrations/range-doctor.json>

**Action:** Paste the URL and press Enter.

**Say:** “This is one of four served ERC-8004 registration documents. The [registration procedure](../deployment-runbook.md#register-the-four-identities) checks that the public URI serves the committed bytes before it emits an unsigned transaction plan. The four category services are not bound on chain yet; broadcasting those owner transactions remains outside this demo.”

Finish on: “Docket makes what exists—and what does not—clickable.”

## Slow-read fallback

If the live Range Doctor request has not returned after 12 seconds, say: “The live chain read is still pending, so I am switching to the stored public evidence rather than narrating a value that has not arrived.” Then open, in order:

1. <https://docket.gudman.xyz/lp-record> — dated controlled-position observations.
2. <https://docket.gudman.xyz/advantage/v2.json> — the v2 artifact containing the frozen, post-hoc decision-impact arithmetic.
3. <https://docket.gudman.xyz/advantage.json> — the three completed paired tasks and actual outputs.

Return to <https://docket.gudman.xyz/pancake> only if the live result has arrived; do not claim that a pending or failed read succeeded.

## Thirty-second version

- **0:00–0:12:** Open <https://docket.gudman.xyz/pancake>. Say: “A fresh, read-only PancakeSwap position diagnosis sits above a public dated history. Its August 24 `WAIT` decision links one prior and three later observations; that proves linkage, not that Docket caused or improved the choice.”
- **0:12–0:22:** Open <https://docket.gudman.xyz/advantage>. Say: “Three completed single-task comparisons expose both arms and actual outputs, including Warden's layers finding one of four vectors identified by manual reading of the same security payload. V3 has no family result yet: v3-04 is input-locked and running after one failed manual primary, with 23 primaries still unrun.”
- **0:22–0:30:** Open <https://docket.gudman.xyz/stats>. Say: “The live registry layer publishes its timestamp, sample denominator, population rule, and probe method. Hire by evidence, not promises.”
