def multiply_numbers(a: float, b: float) -> float:
    """Return the product of two numbers."""
    return a * b


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python multiply_numbers.py <a> <b>")
        raise SystemExit(1)

    try:
        a_value = float(sys.argv[1])
        b_value = float(sys.argv[2])
    except ValueError as exc:
        print(f"Error: {exc}. Please provide numeric values.")
        raise SystemExit(1)

    print(multiply_numbers(a_value, b_value))
