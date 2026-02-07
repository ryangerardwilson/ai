from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from add_two_numbers import add_two_numbers


def test_add_two_numbers_function():
    assert add_two_numbers(1, 2) == 3
    assert add_two_numbers(-5, 2.5) == -2.5
    assert add_two_numbers(0, 0) == 0


def test_add_two_numbers_cli():
    script_path = ROOT / "add_two_numbers.py"

    completed = subprocess.run(
        [sys.executable, str(script_path), "3", "4"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.strip() == "7.0"
