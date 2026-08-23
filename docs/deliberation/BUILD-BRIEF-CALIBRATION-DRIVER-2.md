# Build brief — calibration driver, round 2

Audited, and **every finding below I reproduced myself** before writing this. Nothing here is
opinion. The build is largely right: bytes are persisted untouched, the seat callable resolves at
call time, refusal fires before any side effect, no retry loop, and the `finally` genuinely writes
a record on the raise path — the tests read it back off disk rather than merely asserting the
exception propagated. That last one is the hard part and you got it right.

What follows is what the suite does not constrain, plus one thing that cannot work at all.

**Do not commit, push or deploy. Write code, do not re-survey the codebase** — two earlier
attempts spent their whole budget reading and produced nothing. 1203 tests pass.

## 1. A seat that returns nothing gets fabricated evidence — WORST

I applied `raw = seat(prompt)` → `raw = seat(prompt) or b"{}"` and **all 6 tests passed.**

A seat callable that returns `None` or `b""` *without raising* would bind `b"{}"` into the ledger
as CAPTURED. That is fabricated evidence in a record that is permanent by design — the first
attempt returning bytes is the one that counts, forever, and afterwards it is indistinguishable
from something the seat actually said.

The exception tests never reach that path because they raise. Nothing covers a non-raising falsy
return.

**Fix:** treat a falsy or non-`bytes` return as *no response*, not as an answer. Add the test.

## 2. A `str` return wedges the seat permanently — IRRECOVERABLE

I ran it: `call_seat=lambda p: "a string not bytes"` — the classic `response.text` instead of
`.content` — produces **request written, response NOT written**. `sha256(str)` raises *inside the
`finally`*, so the record never lands.

That seat is then bricked: `attempts()` raises "no response record", and there is no recovery API.
On 2026-08-21 that is the end of that seat under this registration.

**Fix:** the `finally` must not be able to raise. Normalise or reject the return type *before* it
can poison the persistence path, and persist a `no_response` record with the type error as its
reason. Test it with a `str` return.

## 3. `main()` can never drive a seat — P7 fails

Line 187 passes `call_seat=None`, and `run_seat` refuses before doing anything. **Every possible
CLI invocation refuses and exits.** There is no way to supply a real seat client — no import, no
env var, no `module:callable` argument.

The docstring rationalises this as refusing rather than inventing an answer. That is the right
instinct in the wrong place: refusing when *unconfigured* is correct, but there must be a way to
configure it, or the entry point cannot run on the morning it exists for.

**Fix:** accept a `module:callable` reference (or equivalent) and resolve it. Keep the refusal for
when it is absent. Test both branches — that a valid reference resolves and drives the seat, and
that a missing or unresolvable one refuses.

## 4. Three more surviving mutations

I confirmed the first empirically; these follow the same pattern of the tests agreeing with the
implementation rather than constraining it.

- **`prompt = calibration.derive_prompt(...)` → `prompt = b"{}"`.** Every test lambda ignores its
  prompt argument, and `open_attempt` re-derives the real prompt independently for the record. So
  the record would claim an ask that never happened. **Assert the seat receives the derived
  prompt.**
- **Hardcode `model_build` in the `open_attempt` call.** No test reads request-record fields
  through the driver. **Assert the recorded provenance matches what was passed in.**
- **The shared-session check's ALLOW branch is untested** — two seats with distinct sessions both
  succeeding is never exercised, so a mutation making the check always-refuse would block every
  second seat in production and pass the suite. **Test the success path, not only the refusal.**

## 5. No timeout of its own

The "timeout" test is the exception test with a different exception class. A genuinely hanging
seat client persists nothing until killed, then wedges exactly as in item 2. Say whether the
driver should own a timeout or whether that is properly the injected client's job — I think it is
arguable either way and I would rather read your reasoning than impose mine.

## What I will do when you return it

Re-apply every mutation above and expect each to fail. Run the `str` case and the empty-return
case for real. Invoke the CLI with a resolvable seat and confirm it drives one. Check scope.

Argue back where you think I am wrong — you were right twice on the orchestrator.
