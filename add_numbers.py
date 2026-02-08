#!/usr/bin/env python3
"""Standalone script that adds two numbers provided via CLI arguments."""

from __future__ import annotations

import argparse
import sys


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for two numeric values."""
    parser = argparse.ArgumentParser(
        description="Add two numbers supplied as command-line arguments."
    )
    parser.add_argument("num1", type=float, help="First number to add")
    parser.add_argument("num2", type=float, help="Second number to add")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point that adds the provided numbers and prints the sum."""
    args = parse_arguments(argv)
    total = args.num1 + args.num2
    print(f"{args.num1} + {args.num2} = {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
