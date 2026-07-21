"""
Contract tests.

These assert properties of the API SURFACE rather than of any one module: what may
appear on a plane, and what must no longer appear at all. They exist because those two
questions cut across every serializer, and a per-module test would let a new serializer
be added without anyone checking it against the contract.
"""
