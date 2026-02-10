from __future__ import annotations

from typing import Union

Number = Union[int, float]


def multiply(a: Number, b: Number) -> Number:
    """Return the product of two numbers."""
    return a * b


__all__ = ["multiply", "Number"]
