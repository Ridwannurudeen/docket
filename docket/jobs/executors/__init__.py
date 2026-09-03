"""Every category executor, keyed by the category its activation declares.

The registry is populated at import time by the modules below, so `EXECUTORS` is
complete for anything that imports this package, and a category with no executor
raises a `KeyError` naming itself rather than silently doing nothing.
"""

from .base import (
    BSC_CHAIN_ID,
    DECISION_KINDS,
    SIMULATION_FIELDS,
    Decision,
    Executor,
    PreparedCall,
)

EXECUTORS: dict[str, Executor] = {}


def register(executor: Executor) -> Executor:
    """Bind one executor to its category, refusing a second claim on the same one.

    Refusing rather than overwriting: two executors for one category is a merge that
    went wrong, and the one that silently wins would be whichever module imported last.
    Re-registering the same class is allowed, because that is what a module reimported
    under a different name does and it changes nothing.
    """
    category = executor.category
    existing = EXECUTORS.get(category)
    if existing is not None and type(existing) is not type(executor):
        raise ValueError(
            f"category {category!r} is already served by {type(existing).__name__}; "
            f"{type(executor).__name__} cannot also claim it"
        )
    EXECUTORS[category] = executor
    return executor


from .grid import GridExecutor  # noqa: E402  (importing is what registers it)
from .yield_router import YieldRouteExecutor  # noqa: E402

__all__ = [
    "BSC_CHAIN_ID",
    "DECISION_KINDS",
    "EXECUTORS",
    "SIMULATION_FIELDS",
    "Decision",
    "Executor",
    "GridExecutor",
    "PreparedCall",
    "YieldRouteExecutor",
    "register",
]
