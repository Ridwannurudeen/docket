"""Venus Core Pool on BSC: what the protocol publishes, and what it does not.

Venus is a Compound V2 fork. Its comptroller answers, for an account, `(error,
liquidity, shortfall)` in USD — how much more the account could borrow, or how far past
the limit it already is. **It publishes no health factor.** Aave publishes one; Venus
does not, and no call on any contract in this package returns one.

That matters because "health factor" is the phrase this category is named after, and the
easy way to fill the shelf is to print a number under that label. Anything of the sort is
a ratio somebody derived, not a figure Venus produced — so `markets.py` reads and carries
only what the chain answered, and `guard.py` derives the ratio in one place with the
formula and the inputs stated beside it.

`markets.py` reads. `guard.py` interprets and drafts. The split is the same one
`agents/pancake` keeps between `positions.py` and `doctor.py`, and it exists so the layer
that touches the chain has nothing to be wrong about.
"""
