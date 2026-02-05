#!/usr/bin/env python3

from __future__ import annotations

import sys
from typing import Optional

from orchestrator import Orchestrator


def main(argv: Optional[list[str]] = None) -> int:
    orchestrator = Orchestrator()
    args = sys.argv[1:] if argv is None else argv
    return orchestrator.run(args)


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)
    else:
        sys.exit(exit_code)
