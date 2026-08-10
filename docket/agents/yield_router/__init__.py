"""Yield Router: what "the highest available APR" is allowed to mean.

The arithmetic in this package is ordinary. The honest part is the universe. A claim that
capital could earn more somewhere else is only checkable if the "somewhere else" is a set
the reader can reproduce — otherwise "highest" is a superlative over a population nobody
named, which cannot be contested and therefore says nothing.

`universe.py` builds that set and records why every row that did not make it was left out.
`router.py` compares within it, subtracts the protocol's cut before quoting a rate, and
states how long a move takes to pay for itself — including for the candidates whose
break-even is longer than anybody would want, which are shown rather than filtered so the
comparison cannot be flattered by what it dropped.
"""
