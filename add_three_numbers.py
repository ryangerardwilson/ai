"""Utility helpers for summing three numeric values."""


def add_three_numbers(a: float, b: float, c: float) -> float:
    """Return the sum of *a*, *b*, and *c*."""
    return a + b + c


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Add three numbers.")
    parser.add_argument("a", type=float, help="First number")
    parser.add_argument("b", type=float, help="Second number")
    parser.add_argument("c", type=float, help="Third number")
    args = parser.parse_args()

    result = add_three_numbers(args.a, args.b, args.c)
    print(result)
