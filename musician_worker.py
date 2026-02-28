from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_engine_config import resolve_model
from cli_renderer import CLIRenderer
from config_loader import DEFAULT_MODEL, load_config
from inline_mode_renderer import InlineModeRenderer


def run_assignment(*, prompt: str, scopes: list[Path], repo_root: Path) -> int:
    config = load_config()
    renderer = CLIRenderer(show_reasoning=False)
    inline = InlineModeRenderer(
        renderer=renderer,
        config=config,
        default_model=resolve_model("inline", config, default_model=DEFAULT_MODEL),
        enforce_mutation_for_edit_requests=False,
    )
    return inline.run(prompt=prompt, scopes=scopes)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a single musician assignment")
    parser.add_argument("--prompt", required=True, help="Assignment instruction")
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Optional scope path (repeatable)",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root used to resolve relative scopes",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    scopes: list[Path] = []
    for raw in args.scope:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        else:
            path = path.resolve()
        scopes.append(path)
    return run_assignment(prompt=args.prompt, scopes=scopes, repo_root=repo_root)


if __name__ == "__main__":
    sys.exit(main())
