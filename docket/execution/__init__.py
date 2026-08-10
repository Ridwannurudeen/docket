"""The action plane: the only part of Docket that can move anything.

It is a separate package for one reason. `agents/pancake` reads chains and states
what it read; it holds no key, builds no transaction, and there is no code path
through it that could spend a user's funds. That property is worth more than any
feature, so execution lives here instead, and the reader keeps it by not importing
this package at all.

Two rules bind everything under this directory.

**Docket never holds the owner key.** The authority to act comes from a session the
owner granted and can revoke. Docket holds the session, not the account.

**A check written in Python is not a limit.** The caps, the call allowlist and the
expiry are enforced on chain by the session authority, which reverts at validation
time. Anything this package checks is a second, narrower gate in front of that one —
it may refuse an action the chain would have allowed, and it must never be the thing
standing between a bug and somebody's money. `authority.py` says exactly how much of
that is live today and how much is a stub.
"""

import time


def now() -> int:
    """Unix seconds, as the one clock this package reads.

    Deadlines, expiries and state timestamps all come through here so a test can
    freeze time in one place, and so two modules can never disagree about what
    "expired" means because one of them called a different clock.
    """
    return int(time.time())
