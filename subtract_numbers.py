from __future__ import annotations

from typing import Union

Number = Union[int, float]


def subtract(a: Number, b: Number) -> Number:
    """Return the difference of two numbers (a - b)."""
    return a - b


__all__ = ["subtract", "Number"]
