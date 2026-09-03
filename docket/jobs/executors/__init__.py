"""The registry the tick loop looks a category up in.

Empty at import. Each category's executor registers itself, and a category with nothing
registered is a category the loop reports on rather than one it crashes over.

`base.py` is Lane B's file, taken verbatim from `build/pivot-B` so the two branches carry
one contract rather than two that resemble each other. `register(category, executor)` has
Lane B's signature for the same reason; Lane B's copy additionally validates the category
against `docket/jobs/models.py::CATEGORIES`, which does not exist on this branch, so that
one line is the only difference and it disappears when the branches merge.

The executors are deliberately not imported here. They import the agent modules, the agent
modules import `PreparedCall` from `.base`, and an eager import would close that ring and
break `import docket.agents.pancake.keeper` outright. Importing
`docket.jobs.executors.range` registers the rebalancing executor; importing
`docket.jobs.executors.health` registers the health-factor one.
"""

from .base import BSC_CHAIN_ID, Decision, Executor, NoopExecutor, PreparedCall

__all__ = [
    "BSC_CHAIN_ID",
    "Decision",
    "EXECUTORS",
    "Executor",
    "NoopExecutor",
    "PreparedCall",
    "register",
]

EXECUTORS: dict[str, Executor] = {}


def register(category: str, executor: Executor) -> None:
    """Claim one category. Refuses a second claim rather than silently replacing the
    first, because two executors for one category is a configuration error and the
    surviving one would be whichever module imported last."""
    if category in EXECUTORS:
        raise ValueError(f"category {category!r} already has a registered executor")
    EXECUTORS[category] = executor
