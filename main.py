#!/usr/bin/env python3

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import Optional

from config_paths import get_config_path
from orchestrator import Orchestrator


def _open_config_in_editor() -> int:
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text("{}\n", encoding="utf-8")
    editor = (os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vim").strip()
    editor_cmd = shlex.split(editor) if editor else ["vim"]
    if not editor_cmd:
        editor_cmd = ["vim"]
    return subprocess.run([*editor_cmd, str(config_path)], check=False).returncode


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["conf"]:
        return _open_config_in_editor()
    orchestrator = Orchestrator()
    return orchestrator.run(args)


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)
    else:
        sys.exit(exit_code)
