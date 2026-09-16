"""One family of errors, so a caller can catch this package without catching everything.

Every failure this package raises deliberately derives from `MescIOError`. What a caller
gets is still specific — the narrow class says what went wrong — but a program that only
wants to know "the file could not be used" can say so in one except clause.

The exceptions Python raises on its own are left alone: a missing file is still a
`FileNotFoundError`, and an unknown unit is still a `KeyError`, because those already mean
exactly the right thing and shadowing them would surprise people.
"""
from __future__ import annotations

__all__ = ["MescIOError"]


class MescIOError(Exception):
    """Base for every error this package raises on purpose."""
