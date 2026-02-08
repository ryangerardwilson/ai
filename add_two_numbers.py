#!/usr/bin/env python3
"""Add two numbers supplied via command-line arguments or user input."""

from __future__ import annotations

import argparse


def parse_args() -> tuple[float, float] | None:
    parser = argparse.ArgumentParser(
        description="Add two numbers and print the sum.",
    )
    parser.add_argument("first", type=float, nargs="?", help="First number to add")
    parser.add_argument("second", type=float, nargs="?", help="Second number to add")
    args = parser.parse_args()

    if args.first is None or args.second is None:
        return None
    return args.first, args.second


def prompt_for_numbers() -> tuple[float, float]:
    while True:
        try:
            first_str = input("Enter the first number: ")
            first = float(first_str.strip())
            break
        except ValueError:
            print(f"Invalid number: '{first_str}'. Please try again.")

    while True:
        try:
            second_str = input("Enter the second number: ")
            second = float(second_str.strip())
            break
        except ValueError:
            print(f"Invalid number: '{second_str}'. Please try again.")

    return first, second


def add_two_numbers(first: float, second: float) -> float:
    return first + second


def format_result(first: float, second: float, total: float) -> str:
    if first.is_integer() and second.is_integer() and total.is_integer():
        return f"{int(first)} + {int(second)} = {int(total)}"
    return f"{first} + {second} = {total}"


def main() -> int:
    numbers = parse_args()
    if numbers is None:
        numbers = prompt_for_numbers()

    first, second = numbers
    total = add_two_numbers(first, second)
    print(format_result(first, second, total))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
