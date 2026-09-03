"""The activation plane: what a hired agent does after the browser walks away.

Lane B owns the activation model, the store table and the tick loop. This file exists
so the executor package below it is importable on its own — an executor is a decision
function over one activation and one live read, and nothing in it needs the loop that
calls it.
"""
