def multiply_numbers(a: float, b: float) -> float:
    """Return the product of *a* and *b*."""
    return a * b


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multiply two numbers.")
    parser.add_argument("a", type=float, help="First number")
    parser.add_argument("b", type=float, help="Second number")
    args = parser.parse_args()

    result = multiply_numbers(args.a, args.b)
    print(result)
