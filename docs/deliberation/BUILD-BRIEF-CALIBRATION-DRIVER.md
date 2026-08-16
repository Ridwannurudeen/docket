# Build brief — the calibration run driver, and promoting the key it answers

Same arrangement as the orchestrator: you build, a second model audits, I reproduce every finding
before it reaches you. That loop caught a real hole last time — a neutered receipt check that the
whole suite waved through — and you correctly rejected two findings it overstated. Do that again
where you disagree.

**Do not commit, push, deploy or spend.** Build and stop. Format only files you edit. 1197 tests
pass; `./.venv/Scripts/python`.

## Why this is the next thing and why the date matters

**No family is runnable.** All three specs carry `inputs_sha256: ""` and
`docket/advantage/v3/inputs/` has never existed. Every route to a locked family runs through two
calibrated model seats: Warden needs them, and Yield's `assemble_yield_envelope` refuses without
`evaluator_calibration` too.

**The Yield capture fires 2026-08-21T12:00:00Z — one shot, no recapture.** If this driver does not
exist by then, the capture freezes its bytes and sits unusable, because nothing can assemble them
into a lockable envelope. That is the worst version of this failure: an irreplaceable observation
landing in a pipeline that cannot accept it.

## What already exists — do not rebuild it

`docket/advantage/v3/calibration.py` is the storage side and it is mutation-verified. Read it
first. It gives you `derive_prompt`, `open_attempt`, `record_response`, `attempts`,
`binding_attempt`, `assemble_evaluator_calibration`, `verify_calibration_capture`.

Its rules are already enforced and you must not weaken them: the request is persisted **before**
the call, the binding attempt is **the first that produced bytes whatever they say**, a further
attempt is refused once anything is captured, and each attempt names the digest of the previous
one's response.

## Part 1 — promote the eight-case key to a real artifact

The authored Warden calibration key currently exists **only as a test helper**:
`_calibration_set()` in `tests/test_advantage_v3_warden_heldout.py`. There is no source artifact.
That is backwards — it is evidence, and it is living in a file whose job is to check evidence.

- Move it to `docket/advantage/v3/sources/` beside the held-out cases and the vendor snapshot.
  `.gitattributes` already protects `sources/*` from line-ending rewriting; confirm the new file
  is covered.
- **Promote it unchanged.** Its eight cases already name only published vendor classes — I
  verified that. Do not improve them.
- The test helper must then **read the artifact** rather than rebuild it, so the two cannot drift.
- Note `tests/test_advantage_v3_assemble.py` has its own separate `_calibration_set()` for Yield.
  Yield needs its own key eventually; say whether you think this build should include it or
  whether it is a separate authoring job. I have not decided.

## Part 2 — the run driver

One seat, one attempt, fully recorded. Then the other seat.

**The properties that must hold.** Each is a way the evidence could be quietly invalidated.

1. **A response is persisted on every path, including an exception and including a timeout.** If
   the call raises, `record_response` still runs with the error. An exception path that writes
   nothing makes the attempt vanish — and a vanished attempt un-enforces the gate, because the
   next call sees no capture and lets the seat try again. This is the single most important
   property here.
2. **Untouched bytes.** Persist exactly what the seat returned. Do not parse, re-encode,
   pretty-print or strip anything before recording. The digest is taken over what arrived.
3. **The seat caller is injectable and resolved at call time**, not as a signature default. A
   default binds at import; that has already shipped here once and put a live network call inside
   a unit test.
4. **It must refuse rather than simulate.** If no seat client is configured, it stops. Under no
   circumstances does it synthesise, stub or default a seat's answer — a fabricated calibration is
   worse than no calibration, because it is indistinguishable from a real one afterwards.
5. **It does not retry into success.** One attempt per invocation. No loop that keeps calling
   until a seat passes. `open_attempt` already refuses after a capture; do not work around it.
6. **The two seats are distinct sessions**, and the driver cannot run both under one session id —
   `_validate_evaluator_calibration` requires distinct sessions and the driver should fail early
   rather than at lock.
7. **A CLI entry point**, so an operator can actually run a seat. `capture.py`'s `main()` is the
   pattern.

## Tests

Mutation-resistant, as before. For each test, name the mutation it kills. I will apply them and
expect exactly one failure each — a mutation that kills nothing means the test is decorative.

Cover at minimum: the exception path still persists; the timeout path still persists; bytes are
recorded unmodified (use bytes that would change under a JSON round-trip); a second invocation
after a capture is refused; a missing seat client refuses rather than returning anything; the two
seats cannot share a session.

## What I will do when you return it

Apply every mutation you name and some you do not. Read the error paths rather than the happy
path. Check that nothing writes a seat response the seat did not send. Check scope.

If you think a property here is wrong, argue it — you were right twice last time and I would
rather hear it now.
