#!/usr/bin/env python3
"""A simple CLI tool to add two numbers."""

from __future__ import annotations

import sys
from pathlib import Path


def add_two_numbers(a: float, b: float) -> float:
    """Return the sum of *a* and *b*."""

    return a + b


def parse_arguments(argv: list[str]) -> tuple[float, float] | None:
    if len(argv) != 2:
        script_name = Path(sys.argv[0]).name
        print(f"Usage: {script_name} <number1> <number2>", file=sys.stderr)
        return None

    try:
        first = float(argv[0])
        second = float(argv[1])
    except ValueError:
        print("Error: both arguments must be numeric values.", file=sys.stderr)
        return None

    return first, second


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parsed = parse_arguments(argv)
    if parsed is None:
        return 1

    a, b = parsed
    result = add_two_numbers(a, b)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
