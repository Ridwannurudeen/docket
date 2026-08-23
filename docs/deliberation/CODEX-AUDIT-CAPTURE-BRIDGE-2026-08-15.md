# Codex audit request — the Yield capture and its bridge to the input lock

You are auditing. I built; you find what is wrong. Two commits on
`docs/deliberation-round2`: `7c6121b` and `56fb650`. 1077 tests pass, which is
exactly why I want an adversarial read rather than a confirmation.

## What this code has to survive

The Yield family registered one moment: **2026-08-21T12:00:00Z**, two URLs, an
ordered pair of fetches, three attempts sixty seconds apart. If the capture
produces bytes the stage-two lock then refuses, there is no second capture —
the registered moment is gone and the protocol must be recommitted. So the
failure mode that matters is **passes locally, refused at lock**.

## What changed

`docket/advantage/v3/capture.py`
- attempts anchored to absolute registered times, not relative sleeps stacked
  after variable work (two 25s timeouts made an attempt ~50s; relative spacing
  started attempt three at 12:03:40, past its window)
- an attempt whose one-minute window has already closed is not fetched
- transport failure records status `0`, not `null` (validator requires int)
- per-URL `pools_observed_at` / `token_list_observed_at`, because snapshots are
  validated separately and must show pools observed no later than token_list
- `LATE_TOLERANCE_S` 300 → 5, with an import-time assertion that
  `LATE_TOLERANCE_S + 2*REQUEST_TIMEOUT_S < 60`
- `main()` + systemd units; spec resolved by family id from the installed
  package, because `/opt/docket/docket` is the previous release's source tree

`docket/advantage/v3/assemble.py` (new) — builds the lock envelope from a
capture. Imports `_token_allowlist`, `_yield_first_failed_gate`, `_yield_number`
from `spec.py` rather than reimplementing them.

## Where I most expect to be wrong

1. **The truth computation in `_cases()` is the one thing I did reimplement.**
   `net_rates`, `best_pool`, `extra_per_day`, `days_to_recover`, `decision` are
   transcribed from `_validate_yield_inputs` (spec.py ~1948-1990). The validator
   compares floats with `math.isclose(rel_tol=1e-12, abs_tol=1e-12)`. Is my
   arithmetic **operation-order identical**, or only algebraically equal? A
   reassociation could pass my synthetic fixtures and fail on real pool numbers.
2. **`chosen = attempts[-1]`** assumes the last recorded attempt is the
   successful one. Check that against the window-closed `break` I added — can a
   failed attempt ever end up last while `captured` is true?
3. **Real PancakeSwap response shape.** My fixtures are synthetic. The pools
   endpoint may return `{"rows": [...]}` or a bare list; ids may be checksummed
   or have differing key names (`feeUSD24h`, `protocolFeeUSD24h`, `tvlUSD`,
   `volumeUSD24h`, `token0.id`). If the live shape differs, `_partition` raises
   on 2026-08-21 with the bytes frozen. **Fetch the two URLs now and tell me
   whether the real bodies pass `_partition` and `_token_allowlist` unchanged**,
   and whether ≥5 pools clear the gates.
4. **Clock.** The 5s tolerance assumes a true clock on the VPS. Also: is
   `AccuracySec=1s` with `Persistent=false` actually enough for systemd to fire
   inside the first attempt's minute?
5. **`load_capture` digest check** — does it close the tamper path, or can an
   edited body still reach `write_envelope` by another route?

## Constraints

Do not commit, push, deploy, or spend. Read-only plus the two HTTPS GETs in (3).
Report findings ranked by whether they would refuse at lock.
