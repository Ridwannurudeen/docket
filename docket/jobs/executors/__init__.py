"""The registry the tick loop looks a category up in.

Empty at import. Each category's executor registers itself, and a category with nothing
registered is a category the loop reports on rather than one it crashes over: an
activation whose executor has not shipped yet is a real state of this system this week,
and a tick that died on it would take every other owner's activation down with it.
"""

from ..models import CATEGORIES
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
