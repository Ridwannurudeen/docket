"""The registry the tick loop looks a category up in.

Empty at import. Each category's executor registers itself, and a category with nothing
registered is a category the loop reports on rather than one it crashes over: an
activation whose executor has not shipped yet is a real state of this system this week,
and a tick that died on it would take every other owner's activation down with it.
"""

from importlib import import_module

from ..models import CATEGORIES
from .base import Decision, Executor, NoopExecutor, PreparedCall

__all__ = [
    "CATEGORIES",
    "Decision",
    "EXECUTORS",
    "Executor",
    "NoopExecutor",
    "PreparedCall",
    "load_executors",
    "register",
]

# The four modules that claim a category. Imported by `load_executors` at call time rather
# than here, because each of them imports this module to call `register` and importing
# them at module scope would close the ring.
EXECUTOR_MODULES = ("range", "health", "grid", "yield_router")

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


def load_executors() -> None:
    """Import the modules that register the four category executors.

    Called by the tick, once per pass, rather than at import: each executor module imports
    `register` from here, so importing them from this module's body would be a cycle.
    Idempotent, because `register` refuses a second claim and a module imports once.

    A module that has not shipped yet is skipped — the four land lane by lane, and a tick
    that refused to start until all four existed would be a tick that never ran. A module
    that exists and raises on import is a real fault and is not swallowed: only the
    absence of the module itself is tolerated, checked by name so a missing dependency
    inside one of them still surfaces.
    """
    for name in EXECUTOR_MODULES:
        qualified = f"{__name__}.{name}"
        try:
            import_module(qualified)
        except ModuleNotFoundError as exc:
            if exc.name != qualified:
                raise
        except ValueError as exc:
            # `register` refuses a second claim on the same category. Re-importing an
            # already-imported module does not re-run it, so this only fires where two
            # modules claim one category — a configuration error worth surfacing.
            if "already has a registered executor" not in str(exc):
                raise
