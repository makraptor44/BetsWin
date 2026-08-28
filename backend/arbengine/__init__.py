"""BetsWin arbitrage engine.

A prediction-market arbitrage scanner built on the mathematics in
`arbitrage_betting_theory.pdf` and the architecture in
`arbitrage_betting_python.pdf`.

Pipeline: fetch -> normalise -> detect -> size -> alert/expose -> track.
"""

__version__ = "1.0.0"
