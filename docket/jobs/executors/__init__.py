"""The executor registry, keyed by the official category each one performs.

The tick loop looks an activation's `category` up here. Registration is explicit and
happens in each executor's own module, at its bottom: importing
`docket.jobs.executors.range` registers the rebalancing executor and importing
`docket.jobs.executors.health` registers the health-factor one. This package deliberately
does not import them for you — the executors import the agent modules, the agent modules
import `PreparedCall` from `.base`, and an eager import here would close that ring and
break `import docket.agents.pancake.keeper` outright.
"""

from .base import Decision, Executor, PreparedCall
from .bounds import BSC_CHAIN_ID

EXECUTORS: dict[str, Executor] = {}


def register(executor: Executor) -> Executor:
    """Bind one executor to its category, refusing a second claim on the same one."""
    category = executor.category
    existing = EXECUTORS.get(category)
    if existing is not None and type(existing) is not type(executor):
        raise ValueError(
            f"category {category!r} is already served by {type(existing).__name__}; two "
            "executors for one category means the tick loop's choice depends on import "
            "order"
        )
    EXECUTORS[category] = executor
    return executor


__all__ = [
    "BSC_CHAIN_ID",
    "EXECUTORS",
    "Decision",
    "Executor",
    "PreparedCall",
    "register",
]
