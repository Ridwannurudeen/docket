"""Docket's ERC-8183 escrow rail: the "real job" hire, as opposed to x402's "try this
agent now".

Docket never takes a buyer's key, never proxies a signature, and never holds escrowed
funds. It publishes the exact call sequence, reads the resulting job from chain, and
closes the job once the dispute window elapses — which it can do because settle() is
not gated on the caller.
"""
