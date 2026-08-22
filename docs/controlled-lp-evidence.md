# Controlled PancakeSwap LP evidence

Docket keeps an append-only record of its controlled PancakeSwap v3 position at
`/var/lib/docket/lp-record/controlled.jsonl`. Each non-empty line is one JSON object. The
objects are read in file order; later lines do not rewrite earlier observations.

The configured wallet, position token ID, declared value, and recenter-cost input are in
`deploy/systemd/docket-lp-record.service` and are copied into the resulting history. The
history itself remains the source for changing observations such as range state, block, and
observation time; this page does not transcribe those outputs.

The daily job calls the same Range Doctor report used by the hire path. An observation records
the controlled wallet and position identifier, the report's diagnosis, and the BSC block and
time at which the state was read. A failed read is also a line in the history. It is an
infrastructure failure, not an empty position result.

## Observation, decision, later observation

An owner decision is a separate `owner_decision` event. The owner explicitly enters `WAIT` or
`RECENTER`, a rationale, the decision time, and the alternatives considered. Docket never
infers that choice from later chain state.

`prior_observation_sha256` binds the decision to the observation it answers. A later
observation carries `answers_decision_sha256` for the latest decision. Those references make
the sequence machine-checkable:

`observation -> owner decision -> later observation`

The sequence shows an observed association between a diagnosed state, the owner's stated
decision, and a later state. It does not establish that the decision caused the later state,
that the owner earned more, that a loss was avoided, or that Range Doctor produced causal
alpha. Market prices move independently. The rate fields remain fixed-notional, pool-wide
annualisations rather than realized earnings for this position.

The hashes also have a narrow integrity meaning. They detect a referenced line being removed
or edited while its reference remains. They do not authenticate the person who typed the
decision, provide an external timestamp, or prevent someone who controls the whole file from
rewriting a line and every later reference before publication.

## How to check the history

Use the repository's history checker on the file:

```python
from pathlib import Path

from docket.agents.pancake.lp_record import verify_history

verify_history(Path("/var/lib/docket/lp-record/controlled.jsonl"))
```

`verify_history` parses every JSONL line in order and recomputes each referenced digest. A
missing or changed referenced line raises an error.

To recompute one reference independently, serialize the complete referenced JSON object with
keys sorted, no whitespace separators, and UTF-8 output (`ensure_ascii=False`), then take its
SHA-256 digest. In Python:

```python
import hashlib
import json

canonical = json.dumps(
    referenced_record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
).encode("utf-8")
digest = hashlib.sha256(canonical).hexdigest()
```

Compare the hex digest with `prior_observation_sha256` or `answers_decision_sha256` on the
referencing line.

## Block pin and archive access

The report inside a successful observation names its BSC block. Checking the chain state means
repeating the position and pool reads with that value as `observation_block`, not asking for
`latest`. The wallet ownership, position state, and pool tick must all be read at the same block.

Historical BSC state may already be pruned from public endpoints. In that case Docket raises
`PrunedStateError`; it does not turn the missing node state into a claim that the position or
pool is absent. Set `DOCKET_ARCHIVE_RPC` to an owner-supplied BSC archive endpoint before the
check. The archive endpoint is tried first for pinned-block reads. A successful archive read
supports checking the block-pinned state; it does not change the causal limits of the record.
