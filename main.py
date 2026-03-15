#!/usr/bin/env python3

from __future__ import annotations

import sys

from config_paths import get_config_path
from _version import __version__
from orchestrator import Orchestrator
from rgw_cli_contract import AppSpec, resolve_install_script_path, run_app


INSTALL_SCRIPT = resolve_install_script_path(__file__)
HELP_TEXT = """ai

flags:
  ai -h
    show this help
  ai -v
    print the installed version
  ai -u
    upgrade to the latest release
  ai conf
    open the config in $VISUAL/$EDITOR

features:
  start the interactive coding assistant
  # ai
  ai

  ask a one-shot question against files or a repo path
  # ai path/to/file.py "what does this do"
  ai path/to/file.py "what does this do"

  start orchestrator mode with tmux-backed sub-agents
  # ai -o "implement the feature"
  ai -o "implement the feature"
"""


def _dispatch(argv: list[str]) -> int:
    orchestrator = Orchestrator()
    return orchestrator.run(argv)


APP_SPEC = AppSpec(
    app_name="ai",
    version=__version__,
    help_text=HELP_TEXT,
    install_script_path=INSTALL_SCRIPT,
    no_args_mode="dispatch",
    config_path_factory=get_config_path,
    config_bootstrap_text="{}\n",
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return run_app(APP_SPEC, args, _dispatch)


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)
    else:
        sys.exit(exit_code)
