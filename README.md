# ai

`ai` is a Vim-first rewrite of OpenAI Codex running on the latest Responses API
superset of Completions. Launch it to analyze a repository snapshot, iterate on
follow-up questions, or hand it a file to rewrite while keeping eyes on the
diff. Everything runs from a single binary with explicit controls for upgrades
and versioning.

- CLI and TUI modes wrap the Responses API so you can audit diffs, chat, or edit
  without leaving the keyboard.
- Minimal, opinionated workflow trims noise and keeps every run focused on
  shipping the next concrete change.
- Git safeguards stage changes for you and refuse to auto-commit, so the AI
  never hijacks version control.

---

## Installation

### Prebuilt binary (Linux x86_64)

Grab the latest tagged release via the helper script:

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/ai/main/install.sh | bash
```

The script drops the unpacked bundle into `~/.ai/app` and a shim in
`~/.ai/bin`. It will attempt to append that directory to your `PATH` (unless
you opt out). Once installed, run `ai -h` to confirm everything works.

Installer flags of note:

- `-v <x.y.z>`: install a specific tagged release (`v0.2.0`, etc.).
- `-v` (no argument): print the latest GitHub release version.
- `-u`: reinstall only if GitHub has something newer than your current local copy.
- `-b /path/to/ai-linux-x64.tar.gz`: install from an already-downloaded archive.
- `-h`: show installer usage.
- `--no-modify-path`: skip editing shell rc files; the script prints the `PATH` entry you need.

You can also download the `ai-linux-x64.tar.gz` artifact manually from the
releases page and run `install.sh --binary` if you prefer to manage the bundle
yourself.

### From source

```bash
git clone https://github.com/ryangerardwilson/ai.git
cd ai
python main.py
```

---

## Usage

- `ai` — launches an interactive session immediately. Type your first instruction at the `💬 >` prompt.
- Within the session, the assistant analyzes the current repository, streams answers live, and waits for follow-up prompts until you press Enter on an empty line or hit `Ctrl+D`.
- Use in-session instructions to request scoped analyses or edits (for example: “Focus on `path/to/file.py` and rewrite the error handling.”).
- `ai "how do i add 2 and 2 in python"` — run a one-shot inline prompt (read-only, no follow-ups).
- `ai path/to/file.py path/to/other.py "what are these files about"` — inline prompt scoped to one or more files or directories.
- `ai '!pytest -q'` — run a sandboxed shell command immediately; the command output is shown without entering the model loop.
- `ai --read path/to/file.py --offset 400 --limit 200` — preview a specific slice of a file (line numbers mirror the assistant’s context hints).
- `ai v` — open Vim (or `$EDITOR`) immediately to craft the first prompt before the session starts.
- Type `v` at the `💬 >` prompt to pop open Vim (or `$EDITOR`) so you can draft the next instruction before sending it; you can add text after `v` to seed the buffer.
- Type `help` for an inline cheat sheet or `new` to reset the current conversation context without exiting.
- While a response streams you can press `q` to stop the current reply or `r` to retry the same prompt without leaving the session.
- When supported by the model, `ai` streams the agent’s reasoning as a dim `🤖` line while it thinks; set `AI_SHOW_REASONING=0` (legacy `AI_SHOW_THINKING=0`) to suppress it.
- `ai -d` — enable verbose OpenAI debug logs (writes to `debug.log` by default, or supply a path like `ai -d logs/session.log`).
- When the assistant provides file contents, the CLI shows a unified diff for each file and asks for confirmation before writing; approved files are created or updated immediately.
- Type your dog whistle approval phrase (default `jfdi`, but configurable—think `ship it`, `hakuna matata`, etc.) once you’re confident in the plan; that explicit signal unlocks file writes and shell commands for the current session.
- `ai -v` — print the installed version.
- `ai -u` — rerun the installer script if a newer release exists.
- `ai -h` — show the CLI help summary.

Each response streams live to your terminal, followed by the `💬 >` prompt so
you can iterate. Editing mode (triggered by a file scope or a conversation-
generated file) shows a unified diff and preserves permissions when you approve
the change.

## Tool Suite

- `read_file` / `write` / `apply_patch` — precise file IO primitives that surface diffs and require approval before anything is persisted.
- `glob` — repo-scoped file discovery powered by pattern matching (`src/**/*.py`, `tests/**/*_spec.py`, etc.).
- `search_content` — ripgrep-backed content search that returns `path:line:text` snippets right in the transcript.
- `shell` — sandboxed command runner (`!pytest`, `!ls src`) constrained to the repo root with output automatically attached to the conversation.
- `unit_test_coverage` — one-shot `pytest --cov` runner for quick coverage spot checks.
- `plan_update` (with legacy `update_plan`) — structured todo management so the assistant can publish, merge, and summarize task lists as work progresses.

As the assistant works you’ll see tool output in-line—diff previews, coverage
summaries, plan updates—so every action stays transparent.

### Why a Single-Agent + Dog-Whistle Flow?

- **One brain beats a committee.** Rather than juggling planner/builder/runner bots, a single assistant carries full context from plan to execution.
- **User-controlled execution.** Your dog whistle phrase (default `jfdi`, but feel free to use `ship it`, `make it so`, `hakuna matata`) becomes the explicit “go” signal. Until you say it, nothing mutates.
- **Transparent guardrails.** When a tool is blocked, the assistant tells you exactly why and reminds you of the phrase—no rummaging through agent logs.
- **Easy to customize.** Teams can pick a phrase that fits their culture; set it once in config or via `DOG_WHISTLE` and keep the workflow playful *and* safe.

---

## Configuration & Environment

- `~/.config/ai/config.json` (respecting `XDG_CONFIG_HOME`) stores your OpenAI API key, dog whistle phrase, and default model.
- On first launch `ai` asks for your OpenAI API key, then the dog whistle phrase (press Enter to keep `jfdi`), then prompts for the default model before writing the config file for you.

- `OPENAI_API_KEY` overrides the `openai_api_key` entry at runtime (handy for CI or shells).
- `AI_MODEL` overrides the single `model` value.
- `DOG_WHISTLE` overrides the approval phrase used to authorize file edits and shell commands.
- `AI_COLOR` adjusts the ANSI color prefix for assistant output.
- `AI_SHOW_REASONING=0` (or `AI_SHOW_THINKING=0`) disables the live reasoning stream.
- `AI_REASONING_EFFORT` tweaks how hard reasoning models think (`minimal`, `low`, `medium`, `high`, etc.); defaults to `medium` when reasoning is enabled.
- `AI_DEBUG_API` (alias `AI_DEBUG_REASONING`) enables verbose OpenAI interaction logs; combine with the `-d` flag to capture them automatically.
- `AI_BASH_MAX_SECONDS` and `AI_BASH_MAX_OUTPUT` tune shell command timeout and output caps.
- Context window defaults (`read_limit` 2000, `max_bytes` 51200, listings disabled) are hard-coded; directory inventories never ship in the prompt.
- Models with the `-codex` suffix (for example `gpt-5-codex`) are Responses-only per [OpenAI's docs](https://platform.openai.com/docs/models/gpt-5-codex); `ai` automatically switches the edit workflow to the Responses API when you configure one.

The application stores temporary chat buffers in `/tmp/chat_history_*.txt`.
Killing the process with `Ctrl+C` cleans up any remaining scratch files.

---

## Upgrading

Reinstall in place with:

```bash
ai -u
```

The binary checks GitHub for the latest release and only downloads when a newer
version exists. You can also fetch a specific tag by running:

```bash
install.sh -v 0.4.0
```

---

## Releases

Tag the repository with the desired semantic version and push:

```bash
git tag v0.4.0
git push origin v0.4.0
```

GitHub Actions builds a PyInstaller bundle (`ai-linux-x64.tar.gz`), updates
`_version.py`, and publishes the asset alongside the tagged release.

---

## Development

- Requirements live in `requirements.txt`.
- `_version.py` carries the runtime version string; the release workflow overwrites it during tagged builds.
- Run `python main.py -h` to view the CLI summary from source.
- `ai_engine.py` hosts the core orchestration (context gathering, tool dispatch, Responses loop) and can be reused by future UIs.
- `cli_renderer.py` implements the current terminal UX; alternative renderers (TUI, GUI) can plug into the same engine.
- `orchestrator.py` wires configuration, renderer, and engine together so `main.py` remains a thin entrypoint.
