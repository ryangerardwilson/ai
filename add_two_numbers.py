"""Utility for adding two numeric values."""

from __future__ import annotations

import sys
from typing import Union

Number = Union[int, float]


def add_two_numbers(a: Number, b: Number) -> Number:
    """Return the sum of *a* and *b*.

    Parameters
    ----------
    a: Number
        First addend.
    b: Number
        Second addend.

    Returns
    -------
    Number
        The arithmetic sum of the two inputs.
    """

    return a + b


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python add_two_numbers.py <a> <b>")
        return 1

    try:
        a = float(argv[0])
        b = float(argv[1])
    except ValueError:
        print("Both arguments must be numeric values.")
        return 1

    result = add_two_numbers(a, b)
    if result.is_integer():
        result = int(result)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
