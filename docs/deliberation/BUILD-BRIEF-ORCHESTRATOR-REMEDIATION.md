# Build brief — orchestrator remediation

Your orchestrator was audited by a second model and every finding below was then **reproduced by
me** before reaching you. Nothing here is a stylistic preference or an unverified opinion: I
applied each named mutation and watched the suite stay green.

The build is good. Four of the six properties hold with genuinely mutation-resistant tests, the
scope was clean, you did not commit, and you resolved the injectables at call time rather than in
the signature — which is the exact trap that has bitten this repository before. What follows is
what the suite does not yet constrain.

**Same rules: do not commit, push, deploy or spend.** Build and stop. Format only files you edit —
never a whole directory. `./.venv/Scripts/python`. Currently 1184 tests pass.

## 1. BLOCKER — receipt validation is entirely unconstrained by the suite

`orchestrator.py:130`. I replaced the whole `receipt_valid = bool(...)` expression with
`receipt_valid = True` and **all 17 tests still passed.**

That is the most evidence-corrupting hole available here. The agent arm is the paid, hash-bound
one; its receipt is what ties the result to the payment and the input. With that line neutered, a
forged, mismatched or absent receipt binds into the ledger as SUCCEEDED, and the whole
registration exists to prove exactly that arm ran honestly.

The suite only exercises a 200-with-valid-receipt and a 422. Nothing sends a 200 carrying a wrong
`service`, a wrong `input_hash` or `output_hash`, a missing or unsettled `payment`, or an empty
`result`.

**Make each of those a case that fails if the check is removed.** One test per limb, each
asserting the *recorded ledger outcome*, not merely that something raised. Then re-apply the
mutation yourself and confirm it now fails.

Same family, same treatment: `hire_agent`'s 500 → `http_error`, `malformed_json`,
`transport_error`, and the `TimeoutException` → forced-TIMED_OUT branches are all untested.

## 2. An infrastructure error is recorded as an arm failure

`orchestrator.py:290-296`. The `except Exception` wraps **both** `_reveal(...)` and
`run_arm(...)`. So a case id missing from the locked inputs, or inputs moving under a run, binds
that slot terminal FAILED with `kind: invoke_error` — consuming one of five preregistered paired
cases and skewing the manual-versus-agent comparison, on a fault that was never about the arm.

A reveal failure is not an arm failure. Decide which it should be — refused before the claim, or
recorded as interrupted rather than failed — and make the distinction visible in the ledger.
Justify the choice in the docstring; I will audit the reasoning, not just the code.

## 3. `assert_runnable` is only wired into the CLI

Brief property 5 said nothing runs before `assert_runnable` passes. It is called in `main()`
(line 395) and **nowhere in `run_next` or `run_remaining`** — I checked both. A timer or library
caller importing `run_remaining` skips it entirely. The tests pass only because runner's own lock
check inside `_prepare` happens to refuse first, which is coincidence rather than the mandated
mechanism.

Put it where the property belongs, and test it there.

## 4. `_assert_registered_order` is dead code

I replaced its call site with `pass` and **all 17 tests passed.** The real ordering guarantee
comes from `next_open_slot` walking `scheduled_slots`, and the existing refusal test's
`match="manual"` matches both possible messages, so it pins neither path.

Either make it reachable and pin it with a test that distinguishes its message from the other
one, or delete it. A named enforcer that enforces nothing is worse than no enforcer, because the
next reader believes it.

## 5. `assert_runnable` in `main()` is untested

I replaced that call with `pass` and **all 17 tests passed** — the CLI test still sees exit 2 via
runner's own refusal. If you keep it, pin it with something only it can produce.

## 6. A docstring the code does not keep

`_resolve_spec` says "the run uses the registration the running Docket ships with", but it checks
a cwd-relative path first, so a stray local file named like a family id silently shadows the
packaged spec. Note that `capture.py` resolves the same way deliberately — do **not** diverge the
order without saying why. The cheapest honest fix is a docstring that describes what the code
actually does.

## What I will do when you return it

Re-apply every mutation above and expect each to fail a test now. Run the full suite. Read the
error paths rather than the happy path. Check you touched only what you needed to.

If a finding is wrong, say so and show me why — I reproduced these, but being reproduced is not
the same as being the right fix, and I would rather argue now than audit a wrong assumption later.
