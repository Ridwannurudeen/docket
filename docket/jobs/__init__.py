"""The activation and job plane: what a persistent hire is, and who runs it.

`executors/` holds the per-category evaluators. An executor reads live state, decides
whether anything is due, and hands back fully bounded calls somebody else may send. No
executor holds a key and none of them sends anything — that is `docket/sessions/` alone.
"""
