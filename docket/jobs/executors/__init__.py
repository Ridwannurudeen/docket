"""The registry the tick loop looks a category up in.

Empty at import. Each category's executor registers itself, and a category with nothing
registered is a category the loop reports on rather than one it crashes over.

**Lane B's copy of this file is the reference and replaces this one at integration.** It
is identical in behaviour and takes `CATEGORIES` from `docket/jobs/models.py`, which is
Lane B's to write; this stand-in names the four official categories itself so the package
imports before that module lands. `register(category, executor)` has the same signature
and the same refusal in both, so the two lines at the bottom of this file work unchanged
against either.
"""

from .base import Decision, Executor, NoopExecutor, PreparedCall

__all__ = [
    "CATEGORIES",
    "Decision",
    "EXECUTORS",
    "Executor",
    "NoopExecutor",
    "PreparedCall",
    "register",
]

# The four jobs the marketplace declares, in the spelling an activation carries.
CATEGORIES = ("rebalancing", "grid_trading", "yield_optimisation", "health_factor")

EXECUTORS: dict[str, Executor] = {}


def register(category: str, executor: Executor) -> None:
    """Claim one category. Refuses a second claim rather than silently replacing the
    first, because two executors for one category is a configuration error and the
    surviving one would be whichever module imported last."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; expected one of {CATEGORIES}")
    if category in EXECUTORS:
        raise ValueError(f"category {category!r} already has a registered executor")
    EXECUTORS[category] = executor


from .grid import GridExecutor  # noqa: E402  (importing is what registers it)
from .yield_router import YieldRouteExecutor  # noqa: E402
