# AI usage disclosure

Docket used model-assisted development and review.

## Roles

- Codex was used to inspect source, draft implementation and documentation changes, run
  tests, and assemble evidence mappings.
- Claude was used for code and evidence audits and, under the project workflow, performs
  the commit only after its audit passes.
- Fable 5 was used as an adversarial model review seat. It is not an independent person or
  external assurance provider.

The owner retains authority over repository visibility, registrations, deployments,
transactions, spending, and hackathon submission. Model output is not an approval for any
of those actions.

## AI-assisted artifacts

Model assistance appears in source and test changes, the deliberately adversarial security
corpus, experiment and scoring designs, plans, audits, and public documentation. The
repository keeps those claims bounded to committed inputs, output records, hashes, stated
denominators, and explicit limitations where those artifacts exist.

The v3 evaluator roster names two model seats operated by one owner. Prompt-level blinding
and the committed calibration artifacts do not make those seats independent evaluators. At
the committed-artifact observation on 2026-08-29, the committed v3 artifacts contain 6
families: `v3-02-yield-router` is `abandoned_after_failed_primary`;
`v3-04-warden-security` is `complete_unscored`; `v3-05-range-doctor` is
`locked_not_run`; `v3-06-yield-router-assisted` is `registered_waiting_for_inputs`;
`v3-01-range-doctor` and `v3-03-warden-security` are
`superseded_before_input_lock`. The v3-02 failed-primary ledger is preserved, v3-05 is
locked with no claimed primary, and v3-06 awaits its future capture and input lock. V3-04 has a locked input and all 24
primaries terminal (23 succeeded; manual `w4-ho-01` failed with `invoke_error` /
`JSONDecodeError`). Its rubric is permanently unscored because seat B (Claude) returned no
first scoring response and the registered rule forbids retry or substitution; no registered
falsifier result exists.

## Boundaries

- No generated result is represented as an independently verified fact.
- No missing metric, transaction, input lock, calibration artifact, or deployment proof is
  filled with a synthetic placeholder.
- Secrets, private keys, seed phrases, and production credentials must not be placed in
  model prompts or committed artifacts.
- The exact AI-assisted evidence and deliberation history remains in `docs/deliberation/`;
  those records are analysis, not sponsor endorsement.
