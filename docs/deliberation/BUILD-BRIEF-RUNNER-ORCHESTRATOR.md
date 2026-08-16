# Build brief — the v3 run orchestrator

You are building. I guide before and audit after; the auditor of record above us both is Codex.
**Do not commit, push, deploy or spend.** Build and stop; I review the diff, run the suite,
mutation-test the claims, and commit.

Repo `C:\Users\gudma\OneDrive\Desktop\GITHUB-FILES\docket`, branch `docs/deliberation-round2`,
clean, **1167 tests pass**. Run python as `./.venv/Scripts/python`. Never run `ruff format` on a
whole directory — it reformatted thirty untouched files here once. Format only files you edited.

## What is missing, and why it is the critical item

`docket/advantage/v3/runner.py` has the ledger, slot claiming, state folding, recovery and
interruption handling. `scoring.py` has blinding, sheet ingestion and the mapping. Neither has a
`main()` or any entry point. **Nothing drives "reveal the case → run the arm → persist the
result."** The registration's Sep 1–4 window executes all preregistered paired cases; without an
orchestrator that window cannot happen, and discovering that on Sep 1 has no recovery.

This is the 30% "proven advantage" criterion. It is the largest unbuilt thing left.

## Read these first

1. `docket/advantage/v3/runner.py` — especially `ledger_path`, `append_event`, `read_events`,
   `slot_id`, `scheduled_slots`, `open_run`, `claim_slot`, `terminate_slot`, `recover_interrupted`,
   `read_state`, and the `SlotState` fold. This is the machine you are writing the driver for.
2. `docket/advantage/v3/spec.py` — `assert_runnable`, and `execution_protocol` on any registered
   spec (`arm_block_order`, `agent_endpoint`, `agent_service_id`, `agent_request_contract`).
3. `docket/advantage/v3/specs/v3-02-yield-router.json` — a real registration to build against.
4. `docket/advantage/v3/calibration.py` — **the shape to follow.** Its first-write discipline,
   its exclusive creation, and its refusal to select a later attempt are the standard this
   orchestrator is held to.
5. `docket/hire/catalogue.py` around line 376 — how a service is actually invoked.

## The properties that must hold

These are not style preferences. Each one is a way the evidence could be quietly invalidated.

1. **A slot is claimed before the work starts, and the claim is durable.** A run that crashes
   mid-arm must be visible as an interrupted slot, not as a slot that never existed. `runner`
   already models this — use it rather than inventing a second state machine.
2. **The registered arm order is obeyed.** `execution_protocol.arm_block_order` decides which arm
   runs first. The orchestrator does not choose, and must refuse if asked to run out of order.
3. **A failed arm is recorded, never retried into success.** Same rule the calibration capture
   enforces: the first terminal outcome for a slot binds. No retry loop that keeps going until an
   arm succeeds.
4. **The timing is the harness's.** `spec.timing` says the clock never pauses and the operator
   cannot start, stop or edit it. Elapsed seconds come from a monotonic clock the orchestrator
   owns, measured between the registered start and stop events.
5. **Refuse to run before `assert_runnable` passes.** No arm runs against an unlocked spec.
6. **Everything injectable.** The network call, the clock and the ledger path are parameters, so
   the whole policy is testable without a network. Resolve them at call time, not as signature
   defaults — a default binds at import and silently pins the real call. That exact bug shipped
   here once.

## What to deliver

- The orchestrator, in `docket/advantage/v3/runner.py` or a new module beside it — your call,
  but say which and why.
- A `main()` and CLI entry point, so a timer or an operator can actually run it. `capture.py`'s
  `main()` is the pattern; note its comment about resolving a family id from the installed
  package rather than a path.
- Tests that are **mutation-resistant**. Do not assert "it raises". Assert *which* slot's result
  reaches the ledger, *which* arm ran first, *which* attempt bound. For each test, name the
  mutation it kills. I will mutate your implementation and expect exactly one test to fail per
  mutation; a mutation that kills nothing means the test is decorative.
- Honest limits written down. Anything you could not verify, say so plainly rather than omitting
  it.

## What I will check when you hand it back

I will run the full suite, mutate your implementation against your tests, verify every factual
claim by reading the code rather than trusting the description, and check that you did not
reformat files you had no reason to touch. If the tests only agree with the implementation
instead of constraining it, that is the finding I will report.

Ask me before choosing anything the brief does not settle. I would rather answer a question now
than audit a wrong assumption later.
