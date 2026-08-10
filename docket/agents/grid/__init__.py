"""Grid Operator: a band of price levels, and the actions that fire inside it.

Two halves, kept apart on purpose. `plan.py` is arithmetic — it takes a user's band and
returns the levels, and it cannot reach a network, so the same inputs produce the same
plan and the same hash wherever anybody rebuilds it. `operator.py` is the half that
observes a price and asks the execution plane for permission to act.

The split is what makes a commitment worth making: an intent that names a level and a
plan hash can be checked by somebody who has the plan and no access to Docket at all.
"""
