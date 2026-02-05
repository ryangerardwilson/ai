"""Utility to add three numbers."""

from __future__ import annotations

from typing import Union

Number = Union[int, float, complex]


def add_three_numbers(a: Number, b: Number, c: Number) -> Number:
    """Return the sum of *a*, *b*, and *c*."""
    return a + b + c


def main() -> None:
    """Simple CLI entry point for manual testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Add three numbers.")
    parser.add_argument("a", type=float, help="First number to add")
    parser.add_argument("b", type=float, help="Second number to add")
    parser.add_argument("c", type=float, help="Third number to add")
    args = parser.parse_args()

    result = add_three_numbers(args.a, args.b, args.c)
    print(result)


if __name__ == "__main__":
    main()
