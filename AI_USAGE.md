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
and published calibration artifacts, if they later exist, would not make those seats
independent evaluators. At present the calibration artifacts do not exist, no v3 input is
locked, and no v3 arm has run.

## Boundaries

- No generated result is represented as an independently verified fact.
- No missing metric, transaction, input lock, calibration artifact, or deployment proof is
  filled with a synthetic placeholder.
- Secrets, private keys, seed phrases, and production credentials must not be placed in
  model prompts or committed artifacts.
- The exact AI-assisted evidence and deliberation history remains in `docs/deliberation/`;
  those records are analysis, not sponsor endorsement.
