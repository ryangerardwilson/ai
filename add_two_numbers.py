def add_two_numbers(a: float, b: float) -> float:
    """Return the sum of two numbers."""
    return a + b


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Add two numbers together.")
    parser.add_argument("a", type=float, help="First number")
    parser.add_argument("b", type=float, help="Second number")
    args = parser.parse_args()

    result = add_two_numbers(args.a, args.b)
    print(result)
