# Submission readiness — September 9, 2026

Observed between 03:53 and 04:00 UTC. This is a dated readiness audit, not a
submission, independent attestation, funded execution record or uptime guarantee.
The public runtime checked was `c469a434c92738ce0c8eaaff2ad91eb0996461ae`.
Local corrections described below are not yet deployed.

## The three requirements

| Requirement | Verified now | Remaining boundary |
|---|---|---|
| Functional and publicly accessible during September 9–23 | Public HTTPS pages and all four free previews worked; service and worker timers are active and enabled across reboot. | Future uptime requires continued operation and monitoring; today's checks cannot prove the next two weeks. |
| Marketplace agents live on BSC | Chain ID 56, direct ownership and token-URI reads, active public registration documents, and successful invocations for all four category agents. | Research-directory HTTP responses are not successful invocations. Keep unregistered/historical utilities separate from the primary marketplace. |
| All four categories with equal depth | Four real executors, a common activation/policy lifecycle, four successful previews and 286 focused passing tests. | Funded production execution is not demonstrated equally. Health's demo wallet has no entered lending position. Comparative evidence is unequal; do not claim equal measured performance. |

## Four live invocations

With explicit owner approval, each public `/hire/{service_id}` preview was called
exactly once at approximately 03:57 UTC, with no payment/signature headers and no
activation. Each returned HTTP 200, a nonempty result and a free-tier receipt.
The receipt's service, canonical input hash and canonical output hash were checked.
These are read-only outputs, not transactions or paired experimental primaries.

| Category / BSC ERC-8004 ID | Service | Observation |
|---|---|---|
| Rebalancing / 311253 | `range-doctor` | 3.19 s; complete position scan with token 7141050 found at block 120810113. |
| Grid trading / 311255 | `grid-operator` | 3.53 s; six bounded AMM grid levels with quote/calldata records at block 120810121; nothing submitted. |
| Yield optimisation / 311257 | `yield-router` | 1.91 s; 28 pools considered, 26 included and two excluded, with ranking and break-even output at 03:57:22 UTC; nothing submitted. Empty request uses disclosed hypothetical defaults, not the owner's portfolio. |
| Health monitoring / 311259 | `health-guard` | 1.80 s; complete Venus read at block 120810127, error code zero, 55 markets listed and zero entered. Honest `no_position`, null ratio and no actions. This does not demonstrate protecting an active loan. |

Direct BSC reads independently confirmed all four identities and their matching
[published token-URI documents](https://docket.gudman.xyz/registrations/range-doctor.json).
Registration proves identity, not effectiveness or endorsement.

Canonical output hashes (digests only; raw responses were not committed):

```text
range-doctor  d65c761222b3d8f35ee9b1a6f20eac38a716b001bdf842793c73cc7084798e4d
grid-operator 909bae1f79f6e898460fdf24b3569c5a048f8bd6d7370bcc6754a943f105b53c
yield-router dc84b1f46cbc195250f017299b223fb1b666907bcb0ab7d7c21f7476988874d1
health-guard 129f3111f730c51ad50b730818e82c9cd8de78c30887fb411b44a464988ac18a
```

## Availability evidence

- [Public status](https://docket.gudman.xyz/api/status) was `ok`: database reachable,
  BSC read successful, no refresh in flight, and 144/144 synthetic runs passed in the
  preceding 24 hours. Last complete registry refresh: September 9, 01:41:17 UTC.
- HTTPS certificate expires November 7, beyond the judging window. Docket's service
  has `Restart=on-failure`, zero restarts since the September 6 release, and its
  jobs, refresh and ten-minute probe timers are enabled and active.
- Host root disk was 26% used with 839 GB available; available memory was about
  5.5 GB. Release-time database backups remain present. A fresh restore drill was
  not performed. The shared host's certificate-renewal service reports a failure;
  this was not changed, and the current Docket certificate remains valid throughout judging.
- GET-only browser checks at 375 and 1440 pixels passed for home, Search, all four
  category activation pages and My Agents: HTTP 200, no JavaScript errors and no
  horizontal overflow. No browser wallet or transaction interaction was performed.

## Submission corrections and release gates

The owner approved separating the primary four-category BSC marketplace from
research-only utilities and external registry observations. Preserve every raw
catalogue entry, registration and historical adverse result; do not improve an
evidence count by deleting it.

The external directory's current GET responses included 12 HTTP 200, nine 404,
four 401 and one 405 across 26 listings. The existing `live` level means HTTP
reachability at an observation time, not a functioning callable agent. It must
not be represented as proof that every research listing works.

Other audited corrections: exact-match Search filter labels; verification tooltips
that do not invent a settled payment; Grid metadata that correctly describes
runner-held session keys and off-chain enforcement; README and filing notes that
distinguish shipped previews/sessions from funded execution.

Candidate validation: 119 browser tests passed, including four-card inventory and
research separation; the focused homepage module passed nine tests. Desktop and
mobile screenshots were inspected. Release-script tests passed 92 with one
platform skip. The full remaining Python run passed 2,750 with two platform skips
and exposed three Grid-copy assertion failures. Those failures were reproduced,
the wording and obsolete on-chain-enforcement assertions corrected, and all 174
affected marketplace, service, identity and catalogue tests then passed. Ruff and
whitespace checks passed. The complete Python suite has not been rerun after that
final wording-only correction; require green release CI before deployment.

The candidate starts from the public runtime commit, not the unpublished local
experiment checkpoint. No experiment artifacts or operator ledgers are included
in this correction. The earlier checkpoint-tree diagnostic failures must not be
treated as failures of this isolated candidate, or silently repaired by changing
experimental evidence.

## Balanced four-minute recording plan

Use real voice and a fresh live browser at 720p or higher. Give each category about
35 seconds, showing its input, actual result, constraint and receipt rather than
only its card. Range: position/range decision. Grid: six bounded levels and no resting
orders. Yield: net rates and switching-cost test. Health: explain the observed account
state honestly; an empty account is not a rescued loan. Never fund an account merely
to make the video appear more complete.

Use the remaining time for the common activation controls, BSC identity links,
public status and evidence limitations. Any wallet signature or funded action needs
its own owner approval. No video exists from this audit; use the
[recording instructions](demo-script.md) for capture safeguards, not as an existing artifact.

## Still owner-gated

1. Review and release the tested corrections; this audit alone changes no public runtime.
2. Arrange judging-period checks and respond to failures through September 23.
3. Supply the real demo video and confirm whether a form entry already exists.
4. Review personal fields, prize address and terms, then approve the completed submission.

Published build deadline: September 9, 12:00 UTC (13:00 Lagos), per the
[official form](https://forms.gle/9g9XPNFwnYaHAz9L8). Automatic form closure is not
confirmed. The owner paused manual-run work; its records are preserved, and this
readiness audit claims no new comparative result.
